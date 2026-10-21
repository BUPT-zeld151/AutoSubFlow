#!/usr/bin/env python3
"""Read DSH context telemetry without reading messages or altering sessions.

Exit 0: handoff eligible; 2: continue; 3: telemetry unavailable (not permission
for a context handoff). This advisory does not stop or launch any agent.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import time

HANDOFF_FRACTION = 0.90
MAX_CACHE_AGE_SECONDS = 300
SESSION_ID = re.compile(r'(?:session-)?[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')

def unavailable(reason: str) -> dict:
    return {'decision': 'telemetry_unavailable', 'handoff_allowed': False,
            'reason': reason, 'next_action': '继续当前阶段；缺少用量不是上下文耗尽证据'}

def number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0

def home_from_environment() -> Path | None:
    configured = os.environ.get('DSH_HOME')
    if configured:
        return Path(configured).expanduser()
    # A DSH skills symlink may preserve the caller's home in __file__.
    invoked = Path(__file__).absolute()
    if len(invoked.parents) > 3:
        candidate = invoked.parents[3]
        if (candidate / 'storages/session_projcache/sessions').is_dir():
            return candidate
    return None

def read_record(path: Path) -> tuple[dict, float]:
    stat = path.stat()
    document = json.loads(path.read_text(encoding='utf-8'))
    record = document.get('record') if isinstance(document, dict) else None
    if not isinstance(record, dict) or not isinstance(record.get('rows'), dict) or not isinstance(record.get('identity'), dict):
        raise ValueError('会话缓存结构无效')
    return record, stat.st_mtime

def row_value(record: dict, key: str) -> dict:
    row = record.get('rows', {}).get(key, {})
    value = row.get('val', {})
    return value if isinstance(value, dict) else {}

def resolve_record(dsh_home: Path, workspace: Path, session_id: str | None, now: float) -> tuple[Path, dict, float]:
    cache = dsh_home / 'storages/session_projcache/sessions'
    if not cache.is_dir():
        raise ValueError('找不到 DSH session projection cache；显式传入实际 --dsh-home')
    if session_id:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError('session-id 格式不正确')
        path = cache / (session_id + '.json')
        record, modified = read_record(path)
    else:
        candidates = []
        for path in cache.glob('*.json'):
            try:
                if not SESSION_ID.fullmatch(path.stem) or now - path.stat().st_mtime > MAX_CACHE_AGE_SECONDS:
                    continue
                record, modified = read_record(path)
                cwd = record.get('identity', {}).get('cwd')
                child = row_value(record, 'subagent').get('identity')
                active = row_value(record, 'turnBoundary').get('openTurnStartSeq') is not None
                if cwd and Path(cwd).resolve() == workspace and child and active:
                    candidates.append((path, record, modified))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if len(candidates) != 1:
            raise ValueError(f'匹配到 {len(candidates)} 个近期活跃子会话；须提供确切 --session-id，不能猜测')
        path, record, modified = candidates[0]
    cwd = record.get('identity', {}).get('cwd')
    if not cwd or Path(cwd).resolve() != workspace:
        raise ValueError('会话工作区不匹配')
    if not row_value(record, 'subagent').get('identity'):
        raise ValueError('指定记录不是子代理；不能用主会话用量替代子代理用量')
    age = now - modified
    if age < -5 or age > MAX_CACHE_AGE_SECONDS:
        raise ValueError('会话用量缓存已过期或时钟异常，不能作为当前交接凭据')
    return path, record, modified

def evaluate(record: dict, session_id: str, modified: float, now: float) -> dict:
    pressure = row_value(record, 'contextPressure')
    used = pressure.get('pressureTokens')
    capacity = pressure.get('contextWindow')
    if not number(used) or not number(capacity) or capacity <= 0:
        return unavailable('缺少有效 pressureTokens/contextWindow，禁止用累计计费 token 或聊天长度代替')
    # projectedTokens is the provider anchor plus surface changes since sampling.
    projected = pressure.get('projectedTokens')
    surface, sampled = pressure.get('surfaceTokens'), pressure.get('sampledSurfaceTokens')
    if not number(projected) and number(surface) and number(sampled):
        projected = max(0, used + surface - sampled)
    current = max(used, projected) if number(projected) else used
    ratio = current / capacity
    eligible = ratio >= HANDOFF_FRACTION
    return {
        'session_id': session_id,
        'observed': True,
        'source': 'DSH contextPressure projection (latest provider prompt usage and surface delta)',
        'sample_seq': record.get('rows', {}).get('contextPressure', {}).get('seq'),
        'cache_updated_at': dt.datetime.fromtimestamp(modified, dt.timezone.utc).isoformat(),
        'cache_age_seconds': round(now - modified, 1),
        'pressure_tokens': used,
        'projected_tokens': projected if number(projected) else None,
        'effective_tokens': current,
        'context_window': capacity,
        'usage_fraction': round(ratio, 6),
        'remaining_tokens': max(0, capacity - current),
        'handoff_fraction': HANDOFF_FRACTION,
        'decision': 'handoff_eligible' if eligible else 'continue',
        'handoff_allowed': eligible,
        'reason': '实测达到交接阈值；在安全检查点保存交接' if eligible else '实测未达到交接阈值；同一工作者继续下一原子批次',
    }

def check(dsh_home: Path, workspace: Path, session_id: str | None = None) -> dict:
    now = time.time()
    try:
        path, record, modified = resolve_record(dsh_home, workspace.resolve(), session_id, now)
        return evaluate(record, path.stem, modified, now)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return unavailable(str(error))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh-home', type=Path, default=home_from_environment())
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--session-id', help='父会话验收交接时必须提供确切 child id；工作者唯一活跃时可自动定位')
    args = parser.parse_args()
    result = unavailable('无法定位 DSH_HOME，请传入实际 --dsh-home') if args.dsh_home is None else check(args.dsh_home.expanduser(), args.workspace, args.session_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['handoff_allowed'] else (2 if result['decision'] == 'continue' else 3)

if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Read OpenCode 2.x context usage through local read-only API calls.

No messages are sent, and no context text or credentials are printed or saved.
0=handoff eligible, 2=continue, 3=telemetry unavailable (not exhaustion).
"""
from __future__ import annotations
import argparse, datetime as dt, json, math, re, shutil, subprocess, sys, time
from pathlib import Path

THRESHOLD=0.90

def unavailable(reason):
    return {'decision':'telemetry_unavailable','handoff_allowed':False,'observed':False,
            'reason':reason,'next_action':'继续下一原子批次并保存进度；未知用量不是耗尽'}

def numeric(n):
    return isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and n>=0

def evaluate(messages,models,session_id):
    # Matches OpenCode 2.0.30's context occupancy display: latest assistant usage,
    # not the sum over a session or all previous requests.
    last=next((x for x in reversed(messages) if x.get('type')=='assistant' and isinstance(x.get('tokens'),dict) and not x.get('error')),None)
    if not last:return unavailable('当前上下文没有可用的单次模型用量样本')
    t=last['tokens'];cache=t.get('cache',{})
    fields=[t.get('input'),t.get('output'),t.get('reasoning'),cache.get('read'),cache.get('write')]
    if not all(numeric(x) for x in fields):return unavailable('用量字段不完整')
    ref=last.get('model',{})
    model=next((m for m in models if m.get('id')==ref.get('id') and m.get('providerID')==ref.get('providerID')),None)
    capacity=(model or {}).get('limit',{}).get('context')
    if not numeric(capacity) or capacity<=0:return unavailable('精确模型路由没有有效的上下文容量；不能假定1M')
    used=sum(fields);ratio=used/capacity
    if used<=0:return unavailable('提供方尚未报告有效用量')
    return {'session_id':session_id,'observed':True,'source':'OpenCode latest assistant tokens and exact model limit.context',
            'message_id':last.get('id'),'model':ref,'pressure_tokens':used,'effective_tokens':used,
            'context_window':capacity,'usage_fraction':round(ratio,6),'remaining_tokens':max(0,capacity-used),
            'handoff_fraction':THRESHOLD,'decision':'handoff_eligible' if ratio>=THRESHOLD else 'continue',
            'handoff_allowed':ratio>=THRESHOLD,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'note':'最新已报告请求的用量；不估算尚未完成调用或新工具输出，不累计历史计费用量'}

def api(cli,path,server=None):
    args=[cli,'api']+(['--server',server] if server else [])+['GET',path]
    r=subprocess.run(args,capture_output=True,text=True,timeout=45)
    if r.returncode:raise ValueError('OpenCode 本地只读 API 调用失败，请检查服务或 --opencode-cli/--server')
    try:d=json.loads(r.stdout)
    except ValueError:raise ValueError('OpenCode API 未返回可用 JSON')
    return d.get('data',d) if isinstance(d,dict) else d

def check(cli,workspace,session_id=None,server=None):
    workspace=workspace.resolve()
    try:
        if session_id:
            if not re.fullmatch(r'ses[A-Za-z0-9_-]+',session_id):raise ValueError('session-id 格式无效')
            session=api(cli,'/api/session/'+session_id,server)
        else:
            active=api(cli,'/api/session/active',server)
            matches=[]
            for ident in active:
                session=api(cli,'/api/session/'+ident,server)
                if session.get('parentID') and session.get('location',{}).get('directory') and Path(session['location']['directory']).resolve()==workspace:
                    matches.append(session)
            if len(matches)!=1:raise ValueError(f'匹配到 {len(matches)} 个活跃子会话；请提供确切 --session-id')
            session=matches[0];session_id=session['id']
        if not session.get('parentID'):raise ValueError('不能使用主会话的用量代替子代理用量')
        if not session.get('location',{}).get('directory') or Path(session['location']['directory']).resolve()!=workspace:raise ValueError('子会话工作区不匹配')
        messages=api(cli,'/api/session/'+session_id+'/context',server)
        models=api(cli,'/api/model',server)
        return evaluate(messages,models,session_id)
    except (ValueError,TypeError,KeyError,OSError,subprocess.TimeoutExpired):
        return unavailable('无法核验 OpenCode 子会话身份、模型或当前用量；检查服务、确切 session-id 和工作区')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--session-id')
    p.add_argument('--opencode-cli',default=shutil.which('opencode') or '/Applications/OpenCode.app/Contents/Resources/opencode-cli')
    p.add_argument('--server',help='使用独立服务时传其实际URL；默认使用OpenCode自带服务发现')
    a=p.parse_args();result=check(a.opencode_cli,a.workspace,a.session_id,a.server)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['handoff_allowed'] else (2 if result['decision']=='continue' else 3)

if __name__=='__main__':sys.exit(main())

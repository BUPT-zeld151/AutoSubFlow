#!/usr/bin/env python3
"""Read-only workspace inventory for the autosubflow Skill."""
from __future__ import annotations
import argparse
import json
import platform
from pathlib import Path
import shutil
import subprocess

VIDEOS = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm", ".ts", ".mpg", ".mpeg"}


def try_command(args, timeout=3):
    try:
        x = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {"exit_code": x.returncode, "output": (x.stdout or x.stderr).strip()[:800]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def samples(root: Path, glob_pat: str):
    return sorted(str(p.relative_to(root)) for p in root.glob(glob_pat) if p.is_file())[:15]


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--workspace', default='.', help='video project folder, not Skill folder')
    a.add_argument('--phase', type=int, choices=[1, 2, 3], required=True)
    opt = a.parse_args()
    root = Path(opt.workspace).expanduser().resolve()
    if not root.is_dir():
        a.error(f'Not a directory: {root}')
    videos = sorted(str(p.relative_to(root)) for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEOS)
    state_dirs = [f'.subtitle-{v}-work' for v in ('ja','zh')] + ['.subtitle-final-review']
    stage = {
        1: {"directory": ".subtitle-ja-work", "expected": ["A video source; whisper-cli + large-v3 (verified manually)"]},
        2: {"directory": ".subtitle-zh-work", "expected": ["Stage-1 handoff, accepted Japanese SRT"]},
        3: {"directory": ".subtitle-final-review", "expected": ["Stage-1 Japanese SRT and Stage-2 Chinese draft SRT"]},
    }[opt.phase]
    ja = samples(root, '.subtitle-ja-work/handoff/*.ja.srt') or samples(root, '.subtitle-ja-work/final/*.ja.srt') or samples(root,'*.ja.srt')
    zh = samples(root, '.subtitle-zh-work/final/*.zh.srt') or samples(root,'*.zh.srt')
    issues=[]
    if not videos: issues.append('No video found directly in workspace root; verify source location.')
    if len(videos)>1: issues.append('More than one root-level video: do not guess the target.')
    if opt.phase>=2 and not ja: issues.append('No Japanese SRT found in common stage-1 locations; check original handoff paths.')
    if opt.phase>=3 and not zh: issues.append('No Chinese draft SRT found in common stage-2 locations; check original handoff paths.')
    report = {
      'inspection_only': True, 'phase_selected': opt.phase, 'workspace': str(root),
      'videos_at_root': videos, 'stage': stage,
      'work_directory_exists': {d: (root/d).is_dir() for d in state_dirs},
      'stage1_japanese_srt_candidates': ja,
      'stage2_chinese_srt_candidates': zh,
      'handoffs': {d: samples(root, f'{d}/CONTINUE_IN_NEW_CHAT.md') for d in state_dirs},
      'tools': {k: shutil.which(k) for k in ('ffmpeg','ffprobe','whisper-cli','python3')},
      'machine': platform.platform(), 'warnings': issues,
      'important': 'An SRT file existing is NOT proof its phase passed QA; inspect progress, manifest, and review records before proceeding.'
    }
    if platform.system() == 'Darwin':
        report['macos_memory'] = {
            'hw_memsize': try_command(['sysctl','-n','hw.memsize']),
            'swapusage': try_command(['sysctl','vm.swapusage'])
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

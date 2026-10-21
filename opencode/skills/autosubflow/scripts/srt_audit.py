#!/usr/bin/env python3
"""Conservative, read-only SRT structural and reading-speed risk audit.

Only marks candidates for human/agent evidence review. Does not certify speech, timing,
translation, or visual semantics. No third-party dependencies.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

TIME = re.compile(r'^(\d+):(\d{2}):(\d{2}),(\d{3})$')
ARROW = re.compile(r'^\s*(\d+:\d{2}:\d{2},\d{3})\s*-->\s*(\d+:\d{2}:\d{2},\d{3})(?:\s+.*)?$')
HANZI = re.compile(r'[\u3400-\u9fff]')


def millis(t: str) -> int:
    m=TIME.fullmatch(t)
    if not m:
        raise ValueError(f'Invalid time: {t}')
    h,mm,ss,ms=map(int,m.groups())
    if mm>59 or ss>59: raise ValueError(f'Invalid time: {t}')
    return ((h*60+mm)*60+ss)*1000+ms


@dataclass
class Entry:
    number:int
    start:int
    end:int
    text:str


def parse_srt(path: Path):
    raw=path.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    blocks=re.split(r'\n[ \t]*\n',raw.strip()) if raw.strip() else []
    entries=[]
    errors=[]
    for bid,block in enumerate(blocks,1):
        lines=[x.strip() for x in block.splitlines() if x.strip()]
        try:
            if len(lines)<3 or not lines[0].isdigit(): raise ValueError('Bad SRT block number/content')
            m=ARROW.fullmatch(lines[1])
            if not m: raise ValueError('Bad SRT timestamp arrow')
            entries.append(Entry(int(lines[0]),millis(m[1]),millis(m[2]),'\n'.join(lines[2:])))
        except ValueError as exc: errors.append({'block':bid,'error':str(exc),'sample':block[:100]})
    return entries, errors


def audit(path:Path):
    es,parse_errors=parse_srt(path)
    risks=[]
    if not es: risks.append({'type':'empty_subtitles'})
    for i,x in enumerate(es):
        dur=(x.end-x.start)/1000
        n=len(HANZI.findall(x.text))
        if x.number!=i+1: risks.append({'index':i+1,'subtitle_no':x.number,'type':'nonsequential_index'})
        if dur<=0: risks.append({'index':i+1,'subtitle_no':x.number,'type':'nonpositive_duration','duration_s':dur})
        if i and x.start<es[i-1].start: risks.append({'index':i+1,'type':'out_of_order_time'})
        if i and x.start<es[i-1].end: risks.append({'index':i+1,'type':'overlap_or_stacked_subtitle','with_previous':i})
        if i and x.text==es[i-1].text: risks.append({'index':i+1,'type':'identical_consecutive_text'})
        if n>=8 and dur<=0.5: risks.append({'index':i+1,'type':'eight_hanzi_in_half_second','duration_s':dur,'hanzi':n})
        if dur>0 and n/dur>12: risks.append({'index':i+1,'type':'high_hanzi_per_second','hanzi_per_s':round(n/dur,2),'severe':n/dur>20})
    return es, {'path':str(path),'subtitle_count':len(es),'parse_errors':parse_errors,
                'last_end_ms':max((x.end for x in es),default=0),
                'risk_count':len(risks),'risk_categories':dict(Counter(x['type'] for x in risks)),
                'risk_examples':risks[:80],
                'risk_examples_truncated':len(risks)>80}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--ja',type=Path)
    a.add_argument('--zh',type=Path)
    args=a.parse_args()
    if not args.ja and not args.zh: a.error('Supply --ja and/or --zh')
    reports={}
    entries={}
    for lang, p in [('ja',args.ja),('zh',args.zh)]:
        if p is None:continue
        if not p.is_file():a.error(f'File not found: {p}')
        entries[lang],reports[lang]=audit(p)
    if 'ja' in entries and 'zh' in entries:
        js,zs=entries['ja'],entries['zh']
        pair_errors=[]
        if len(js)!=len(zs):pair_errors.append('different_subtitle_counts')
        for i,(j,z) in enumerate(zip(js,zs),1):
            if (j.start,j.end)!=(z.start,z.end):pair_errors.append({'index':i,'type':'time_mismatch','ja':[j.start,j.end],'zh':[z.start,z.end]})
        reports['pair']={'fully_aligned':not pair_errors,'problems':pair_errors[:80], 'problems_truncated':len(pair_errors)>80}
    reports['disclaimer']='Only structural/risk audit; audio truth, visual evidence and Chinese semantics require model review.'
    print(json.dumps(reports,ensure_ascii=False,indent=2))
    if any(v['parse_errors'] for k,v in reports.items() if k in ('ja','zh')):sys.exit(2)

if __name__=='__main__':main()

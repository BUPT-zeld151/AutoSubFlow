#!/usr/bin/env python3
"""Conservative read-only checks for a serial three-phase subtitle pipeline.

Commands:
  init   Create durable *work plan*, without pretending any work was done.
  status Compute next phase/unit from evidence on disk, fail closed on missing QA.
  gate   Check phase and optionally an individual unit.

This cannot certify auditory/visual understanding or translation quality. False evidence
cannot be detected from JSONL alone; signed off rows are corroborated structurally.
No third-party Python dependencies. ffprobe is needed only for init without --duration-ms.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, subprocess, sys, tempfile
from pathlib import Path
from typing import Any
from srt_audit import parse_srt

VIDEO_EXT={'.mp4','.mkv','.mov','.avi','.m4v','.webm','.ts'}
TERMINAL={'resolved','evidence_limited','rejected_with_evidence','verified','clear','not_applicable'}
BLOCKED={'open','pending','queued','in_progress','unreviewed','not_started','review_required','blocked','resource_blocked','needs_human_review'}
PHASE={1:'.subtitle-ja-work',2:'.subtitle-zh-work',3:'.subtitle-final-review'}
STEPS={1:'完整语音识别、30秒声学审计、双触发视觉核验和日文单元 QA',2:'逐句语义具体化、定向视频核验、两版重表达、全量中文及日中复核',3:'完整中文盲审、逐条日中核对、场景连贯性审查、证据纠错、全文回归'}

def read_json(p:Path)->Any:
    return json.loads(p.read_text(encoding='utf-8-sig'))

def rows(p:Path, errs:list[str], required=True)->list[dict]:
    if not p.is_file():
        if required: errs.append(f'缺失: {p}')
        return []
    out=[]
    try:
        for i,line in enumerate(p.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            obj=json.loads(line)
            if not isinstance(obj,dict):raise ValueError(f'line {i} is not an object')
            out.append(obj)
    except Exception as e:errs.append(f'JSONL 不可解析 {p}: {e}')
    return out

def required_json(p:Path, errs:list[str])->dict:
    try:
        d=read_json(p)
        if not isinstance(d,dict):raise ValueError('expected object')
        return d
    except Exception as e:
        errs.append(f'JSON 缺失或不可解析 {p}: {e}')
        return {}

def nonempty(p:Path,errs:list[str]):
    if not p.is_file() or p.stat().st_size==0:errs.append(f'缺失或空文件: {p}')

def is_pass(q:dict)->bool:
    return str(q.get('status',q.get('state',q.get('verdict','')))).lower() in {'qa_passed','passed','pass'}

def uidset(xs:list[dict], key_options=('uid','source_uid','subtitle_uid','ja_uid','zh_uid')):
    found=[]
    for row in xs:
        for k in key_options:
            if row.get(k) is not None:
                found.append(str(row[k]));break
    return found

def uniq_count(xs:list[dict],label:str,errs:list[str])->int:
    ids=uidset(xs)
    if len(ids)!=len(xs): errs.append(f'{label} 存在缺失 UID 的记录')
    if len(set(ids))!=len(ids):errs.append(f'{label} 存在重复 UID')
    return len(set(ids))

def closed_queue(queue, ev, phase, errs):
    ids={str(r.get('trigger_id',r.get('issue_id'))) for r in ev if r.get('trigger_id',r.get('issue_id')) is not None}
    for q in queue:
        ident=str(q.get('trigger_id',q.get('issue_id','?')))
        state=str(q.get('status','')).lower()
        if state in BLOCKED or state not in TERMINAL:
            errs.append(f'阶段{phase} 未闭环视频触发: {ident}: {state or "无状态"}')
        if state in {'resolved','verified','evidence_limited'}:
            matches=[r for r in ev if str(r.get('trigger_id',r.get('issue_id'))) == ident]
            # Evidence-limited is permitted only if actually attempted visual review.
            if not matches:errs.append(f'触发 {ident} 缺少视觉核验记录')
            else:
                has_frames=any(bool(r.get('frames_opened') or r.get('frame_ids_opened') or r.get('base_frame_times')) for r in matches)
                if not has_frames:errs.append(f'触发 {ident} 未记录实际打开的画面')
    return len(queue)

def durations_cover(rows_:list[dict],start:int,end:int,errs:list[str]):
    intervals=[]
    for r in rows_:
        try:
            a=int(r['start_ms']);b=int(r['end_ms'])
            if b<=a:raise ValueError('nonpositive')
            intervals.append((a,b))
        except Exception:errs.append(f'时间窗口缺失/非法: {str(r)[:130]}')
        state=str(r.get('status','')).lower()
        if state in BLOCKED or not state:errs.append(f'未审核音频窗口 {r.get("window_id", "?")}: {state or "无状态"}')
        if not r.get('inspection_method'):errs.append(f'音频窗口 {r.get("window_id", "?")} 缺少实际审核方法')
    point=start
    for a,b in sorted(intervals):
        if a>point+1:
            errs.append(f'音频窗口未覆盖 {point}..{a}ms');break
        if b>point:point=b
    if point<end-1:errs.append(f'音频窗口未覆盖到单元末尾，结束于 {point} < {end}ms')
    if not intervals:errs.append('没有音频窗口记录')
    return point>=end-1

def unit_declared_zero_entry(base:Path)->bool:
    """True only when the unit's QA explicitly declares it has no dialogue at all."""
    try:
        return read_json(base/'qa_report.json').get('zero_entry_unit') is True
    except Exception:
        return False

def srt(p:Path,errs:list[str], *, allow_global_numbering=False, allow_empty=False):
    if not p.is_file():errs.append(f'缺失 SRT {p}');return []
    try:
        e,parse_err=parse_srt(p)
        if parse_err:errs.append(f'SRT 解析错误 {p}: {parse_err[:2]}')
        if not e and not allow_empty:errs.append(f'空字幕文件 {p}')
        for n,x in enumerate(e,1):
            if x.number != (e[0].number + n - 1 if allow_global_numbering else n):errs.append(f'SRT 序号 {p} #{n} 非连续');break
            if x.end<=x.start:errs.append(f'SRT 非正时长 {p} #{n}');break
            if n>1 and e[n-2].start>x.start:errs.append(f'SRT 时间不单调 {p} #{n}');break
        return e
    except Exception as ex:errs.append(f'无法读取 SRT {p}: {ex}');return []

def discover_srt(dir_:Path, pattern:str,errs:list[str]):
    arr=sorted(dir_.glob(pattern)) if dir_.is_dir() else []
    if len(arr)!=1:
        errs.append(f'{dir_} 应有且仅有一份 {pattern}，当前 {len(arr)}')
        return None
    return arr[0]

def units_from_manifest(w:Path,errs:list[str]):
    m=required_json(w/'.subtitle-pipeline/manifest.json',errs)
    if m:
        v=Path(str(m.get('video','')))
        if not v.is_file():errs.append('manifest 对应的视频文件已不存在')
        elif 'video_size_bytes' in m and v.stat().st_size != m['video_size_bytes']:
            errs.append('视频文件大小变化：不能沿用已有字幕验收')
        elif 'video_mtime_ns' in m and v.stat().st_mtime_ns != m['video_mtime_ns']:
            errs.append('视频修改时间变化：请验证原始媒体是否已被替换')
    units=m.get('units',[])
    if not isinstance(units,list) or not units:errs.append('pipeline manifest 缺少 units');return m,[]
    try:
        seq=[(int(x['start_ms']),int(x['end_ms'])) for x in units]
        if seq[0][0]!=0:errs.append('工作单元未从视频开始')
        if seq[-1][1]!=int(m['duration_ms']):errs.append('工作单元未到视频末尾')
        for (a,b),(c,d) in zip(seq,seq[1:]):
            if b!=c:errs.append(f'单元间有缺口或重叠: {b} -> {c}')
        if any(b<=a for a,b in seq):errs.append('单元有非正时长')
    except Exception as e:errs.append(f'单元边界错误: {e}')
    return m,units

def unit_check(w:Path,phase:int,unit:dict)->dict:
    errs=[]; warn=[]; uid=unit['id'];base=w/PHASE[phase]/'segments'/uid
    q=required_json(base/'qa_report.json',errs)
    if q and not is_pass(q):errs.append(f'{uid} qa_report 尚未通过: {q.get("status",q.get("state"))}')
    if phase==1:
        aw=rows(base/'audio_windows.jsonl',errs)
        durations_cover(aw,int(unit['start_ms']),int(unit['end_ms']),errs)
        subs=rows(base/'subtitle_evidence.jsonl',errs)
        if subs:
            uniq_count(subs,f'{uid} 字幕证据',errs)
            for r in subs:
                if r.get('semantic_screened') is not True:errs.append(f'{uid} 字幕 {r.get("uid")} 缺少语义审查');break
                if not r.get('audio_window_ids'):errs.append(f'{uid} 字幕 {r.get("uid")} 未链接音频窗口');break
        qs=rows(base/'visual_review_queue.jsonl',errs)
        ve=rows(base/'visual_evidence.jsonl',errs)
        closed_queue(qs,ve,phase,errs)
        nonempty(base/'asr_raw',errs) if (base/'asr_raw').is_file() else None
        if not (base/'asr_raw').is_dir():errs.append(f'{uid} 缺少原始 ASR 输出目录')
        elif not any((base/'asr_raw').iterdir()):errs.append(f'{uid} ASR 输出目录为空')
    elif phase==2:
        ss=srt(base/'segment_zh.srt',errs,allow_global_numbering=True,
               allow_empty=bool(q) and q.get('zero_entry_unit') is True)
        mm=rows(base/'meaning_records.jsonl',errs)
        tt=rows(base/'translation_decisions.jsonl',errs)
        sv=rows(base/'semantic_verify.jsonl',errs)
        cc=rows(base/'dialogue_scene_cards.jsonl',errs)
        if ss and not cc:errs.append(f'{uid} 无对话场景卡（零对白场景需在 QA 中说明）')
        for label,xx in [('语义记录',mm),('重表达决策',tt),('语义复核',sv)]:
            n=uniq_count(xx,f'{uid} {label}',errs)
            if n!=len(ss):errs.append(f'{uid} {label} {n} 条，与中文字幕 {len(ss)} 条不符')
        qs=rows(base/'visual_review_queue.jsonl',errs)
        ve=rows(base/'visual_review.jsonl',errs)
        closed_queue(qs,ve,phase,errs)
        if not (base/'language_issues.jsonl').is_file():errs.append(f'{uid} 缺少语言问题清单（无问题时应为空 JSONL）')
        else:rows(base/'language_issues.jsonl',errs)
    return {'unit':uid,'phase':phase,'pass':not errs,'errors':errs,'warnings':warn}

def phase_check(w:Path,phase:int)->dict:
    errs=[];warn=[];m,units=units_from_manifest(w,errs)
    base=w/PHASE[phase]; unit_reports=[]
    if phase in (1,2):
        for u in units:
            r=unit_check(w,phase,u)
            unit_reports.append({'id':u['id'],'pass':r['pass'],'errors':r['errors'][:4]})
            errs.extend(r['errors'])
    if phase==1:
        backend=required_json(base/'asr_backend.json',errs)
        if backend and backend.get('metal_confirmed') is not True:errs.append('没有证实 whisper.cpp large-v3 Metal 后端')
        final=base/'final'
        sf=discover_srt(final,'*.ja.srt',errs)
        se=srt(sf,errs) if sf else []
        audit_count=0
        for u in units:
            p=base/'segments'/u['id']/'subtitle_evidence.jsonl'
            if p.is_file():audit_count+=len(rows(p,errs))
        if len(se)!=audit_count:errs.append(f'日文字幕数 {len(se)} 与审核条数 {audit_count} 不符')
        h=base/'handoff'
        for name in ['subtitles_with_evidence.jsonl','audio_audit_summary.json','scene_context_cards_all.jsonl','visual_review_queue_all.jsonl','visual_evidence_all.jsonl','unresolved_issues.jsonl','global_context.md','identification_report.md']:
            nonempty(h/name,errs) if name not in {'visual_review_queue_all.jsonl','visual_evidence_all.jsonl','unresolved_issues.jsonl'} else (errs.append(f'缺失: {h/name}') if not (h/name).is_file() else rows(h/name,errs))
        discover_srt(h,'*.ja.srt',errs)
    elif phase==2:
        final=base/'final'; ja=discover_srt(final,'*.ja.srt',errs);zh=discover_srt(final,'*.zh.srt',errs)
        j=srt(ja,errs) if ja else [];z=srt(zh,errs) if zh else []
        if len(j)!=len(z):errs.append('阶段 2 最终日中 SRT 条数不一致')
        elif [(x.start,x.end) for x in j]!=[(x.start,x.end) for x in z]:errs.append('阶段 2 最终日中时间轴不一致')
        c=0
        for u in units:
            p=base/'segments'/u['id']/'segment_zh.srt'
            if p.is_file():c+=len(srt(p,errs,allow_global_numbering=True,
                                      allow_empty=unit_declared_zero_entry(base/'segments'/u['id'])))
        if len(z)!=c:errs.append(f'阶段 2 最终中文字幕 {len(z)} 条 != 单元字幕总数 {c}')
        nonempty(final/'translation_report.md',errs)
        nonempty(final/'uid_ja_zh.tsv',errs)
    elif phase==3:
        inp=base/'input'; out=base/'final'
        zi=discover_srt(inp,'*.zh.srt',errs); ji=discover_srt(inp,'*.ja.srt',errs)
        a=srt(zi,errs) if zi else []; _=srt(ji,errs) if ji else []
        for label,path in [('中文盲审',base/'chinese_blind_audit.jsonl'),('日中逐条对照',base/'bilingual_audit.jsonl'),('全文回归',base/'regression_reviews.jsonl')]:
            rr=rows(path,errs)
            num=uniq_count(rr,label,errs)
            if num!=len(a):errs.append(f'{label} 覆盖 {num}/{len(a)} 条')
        coh=rows(base/'dialogue_coherence_audit.jsonl',errs)
        if a and not coh:errs.append('缺失连续对话场景的独立连贯性审查')
        for r in coh:
            st=str(r.get('coherence_status',r.get('scene_coherence_status',''))).lower()
            if st not in {'clear','evidence_limited'}:errs.append(f'对话场景 {r.get("scene_id")} 未闭环: {st}')
        issues=rows(base/'issues.jsonl',errs)
        for x in issues:
            st=str(x.get('status','')).lower()
            if st not in {'resolved','rejected_with_evidence','evidence_limited'}:errs.append(f'问题 {x.get("issue_id")} 未闭环: {st}')
        ve=rows(base/'visual_evidence.jsonl',errs)
        vq=rows(base/'visual_review_queue.jsonl',errs)
        closed_queue(vq,ve,phase,errs)
        reg=required_json(base/'regression_report.json',errs)
        if reg and not is_pass(reg):errs.append('全片回归报告未通过')
        zo=discover_srt(out,'*.zh.final.srt',errs)
        jo=discover_srt(out,'*.ja.corrected.srt',errs)
        z=srt(zo,errs) if zo else [];j=srt(jo,errs) if jo else []
        if len(z)!=len(j) or [(x.start,x.end) for x in z]!=[(x.start,x.end) for x in j]:errs.append('终稿日中 SRT 时间轴/条数不一致')
        nonempty(out/'final_review_report.md',errs)
        nonempty(out/'uid_mapping.tsv',errs)
    return {'phase':phase,'pass':not errs,'unit_reports':unit_reports,'errors':errs,'warnings':warn, 'disclaimer':'程序只检验文件及结构化证据完整性，不能证明语音、画面或翻译语义正确。'}

def status(w:Path):
    reports=[phase_check(w,p) for p in (1,2,3)]
    phase=next((p for p,r in enumerate(reports,1) if not r['pass']),None)
    unit=None
    if phase in (1,2):
        failed=next((x['id'] for x in reports[phase-1]['unit_reports'] if not x['pass']),None)
        unit=failed
    progress=w/PHASE[phase]/'progress.json' if phase else None
    hand=w/PHASE[phase]/'state/context_handoff.json' if phase else None
    next_action='全部阶段完成' if phase is None else f'由当前阶段工作者持续执行阶段 {phase} 的全部剩余工作：{STEPS[phase]}；仅无活动工作者或需上下文交接/中断恢复时由主会话派发'
    if unit:next_action+=f'；优先处理 {unit}'
    return {'overall_complete':phase is None,'next_phase':phase,'next_unit':unit,
            'next_action':next_action, 'phase_results':[{'phase':r['phase'],'pass':r['pass'],'failed_units':sum(not x['pass'] for x in r['unit_reports']),'error_count':len(r['errors']),'first_errors':r['errors'][:4]} for r in reports],
            'resume_paths':[str(p) for p in (progress,hand) if p and p.is_file()]}

def sha256(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for buf in iter(lambda:f.read(2**20),b''):h.update(buf)
    return h.hexdigest()

def init(w:Path,video:str|None,duration_ms:int|None):
    d=w/'.subtitle-pipeline';target=d/'manifest.json'
    if target.is_file():return {'already_initialized':True,'manifest':str(target),'video':read_json(target).get('video')}
    vids=[x for x in w.iterdir() if x.is_file() and x.suffix.lower() in VIDEO_EXT]
    if video:
        v=Path(video).resolve()
        if not v.is_file():raise ValueError(f'没有视频: {v}')
    else:
        if len(vids)!=1:raise ValueError(f'视频文件不唯一: 找到 {len(vids)} 个，请用 --video 显式指定')
        v=vids[0]
    if duration_ms is None:
        raw=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(v)],text=True,timeout=60)
        duration_ms=round(float(raw.strip())*1000)
    if duration_ms<=0:raise ValueError('视频时长必须大于零')
    units=[]
    for i,start in enumerate(range(0,duration_ms,360000),1):
        units.append({'id':f'S{i:04d}','start_ms':start,'end_ms':min(duration_ms,start+360000)})
    m={'schema_version':1,'video':str(v),'video_sha256':sha256(v),'duration_ms':duration_ms,'video_size_bytes':v.stat().st_size,'video_mtime_ns':v.stat().st_mtime_ns,'unit_ms':360000,'units':units,'note':'阶段 1/2 必须遵循这些单元核心时间范围，按 v4 要求执行全部工作。'}
    d.mkdir(exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=d,prefix='.manifest.',suffix='.json')
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(m,f,ensure_ascii=False,indent=2)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {'already_initialized':False,'manifest':str(target),'video':str(v),'duration_ms':duration_ms,'unit_count':len(units)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['init','status','gate','unit'])
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--video')
    p.add_argument('--duration-ms',type=int,help='仅用于已有时长的测试/恢复；默认以 ffprobe 为准')
    p.add_argument('--phase',type=int,choices=[1,2,3])
    p.add_argument('--unit-id')
    args=p.parse_args();w=args.workspace.resolve()
    if not w.is_dir():p.error(f'工作区不存在 {w}')
    try:
        if args.command=='init':d=init(w,args.video,args.duration_ms)
        elif args.command=='status':d=status(w)
        elif args.command=='gate':
            if not args.phase:p.error('gate 必须传 --phase')
            d=phase_check(w,args.phase)
        else:
            if not args.phase or not args.unit_id or args.phase==3:p.error('unit 必须传 --phase 1/2 和 --unit-id')
            errs=[];_,units=units_from_manifest(w,errs)
            u=next((u for u in units if u['id']==args.unit_id),None)
            if u is None:raise ValueError('没有该工作单元')
            d=unit_check(w,args.phase,u)
        print(json.dumps(d,ensure_ascii=False,indent=2))
        if args.command in ('gate','unit') and not d['pass']:sys.exit(2)
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(3)

if __name__=='__main__':main()

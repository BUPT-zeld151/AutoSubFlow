# PROMPT 01 v4｜音频全覆盖优先的精细日文字幕识别与定向音画核验

> **独立会话使用。** 输入：原始日语视频、必要的人名/术语信息。本阶段只生成日文 SRT 和可供翻译阶段复用的证据，不制作中文字幕。v4 与 v3 的本质区别：**取消全片 1 FPS 图像逐张人工式阅读，以及“先看完视频才允许转录”的门禁**；代之以全片音频覆盖、双通道疑点发现（声学＋语义）和被触发区域的高密度视觉核验。
>
> 本文件是可执行任务规范。不可只摘录要求、写计划后改按“快速模式”执行。所有计数、状态、视频观察和运行后端须以真实工具结果为据。

## S. 三阶段通用不可降级运行协议

1. **不改变质量目标，只改变证据投入位置。** 全部音频时间轴、全部有效日文候选、每个已触发视觉任务都必须核验。v4 **不要求**全片基础帧全部输入大模型；禁止以旧 v3 的“每秒 1 帧全片必看”为验收条件。也不得擅自把已触发的局部 1 FPS/加密观察再缩成一张关键帧。
2. **上下文不足不能快扫收尾。** 将任务划为 5–8 分钟处理单元及更小原子批次；每批完成后落盘。若估计无法高质量完成下一完整批次，保存 `progress.json`、`state/context_handoff.json` 和 `CONTINUE_IN_NEW_CHAT.md`，在当前会话停止后请求用户开启**新会话**继续。不得声称自行创建了新会话，不得将未审内容标为已完成。减少单批大小可以，减少总审核范围不可以。
3. **16GB Apple Silicon 统一内存保护。** 开工核实 `sysctl -n hw.memsize`；在重型任务前后及每单元边界观察 `memory_pressure`、`vm_stat`、`sysctl vm.swapusage` 和主要进程 RSS。**同一时刻最多一个重型任务**：Whisper/Metal、VAD 大模型、批量视频解码/镜头检测/图片处理不得重叠；大规模预处理流式、串行，工具线程审慎设限；不预加载两小时图像到内存。出现明显压力或 Swap 持续升高，停止启动新任务，等待/安全结束自己发起的任务，释放缓存并保存检查点；不得杀用户进程。日志入 `state/resource_log.jsonl`。内存紧张不等于上下文紧张；切换会话不能增加物理内存。
4. **证据诚信。** `produced`（文件已生成）、`opened`（实际被视觉模型查看）、`reviewed`（有具体审核结果）、`verified`（证据充分）、`uncertain`（查过但无法判断）、`unreviewed`（未做）、`blocked`（无法执行）彼此不同。VAD/波形有活动≠可辨语音；Whisper 结果≠真值；有关键帧≠已理解动作；上下文“合理”≠声音确实说过。
5. **保留原始材料和稳定标识。** 所有时间戳使用全片绝对毫秒；原音视频和初次 Whisper 输出不可覆盖；修改、分合字幕保留 `source_uid → output_uid` 追踪。脚本用于切片、索引、门禁及声学统计，不能代替真实的视听语义判断。不要擅自用子代理或第三种大型识别模型代替指定主模型决策。
6. **最小可恢复交接。** `context_handoff.json` 至少含 `phase,prompt_version,source_paths_and_hashes,completed_units,current_unit,current_step,last_verified_window_or_uid,next_exact_action,pending_tasks,open_issues,work_paths,quality_gate_results,asr_backend,memory_status`。原子写入并重新读取校验。跨会话恢复时先读本 Prompt、交接文件和证据索引，再从最后可信检查点继续；不能因新会话缺少旧聊天上下文就重做已经验收的全部工作或忽略未完成项。

## 0. 任务目标与新的证据分配原则

输出**完整、尽可能忠实、有准确时间戳的日文 SRT**。既防遗漏（尤其低音量、不到 1 秒的应答/语气词、重叠人声），也防 Whisper 幻觉及词义似是而非。**全部音频接受低成本无遗漏网格审计；视频只在规则触发时精细查看**。不得只依赖 VAD 阳性区或现有字幕时间点选择疑点；声音的物理活动须独立检查，且背景音乐/环境音也可能呈现明显波形。

本阶段不是中文翻译，但必须标注可能影响后续翻译的**语义风险**：人物称谓、条件/否定、身份关系、含蓄表达、词语歧义、指代与对话衔接。即使 Whisper 置信度高，只要语义不明，也要生成 `semantic_trigger`。例如教师与学生谈就业、暗示交换条件并发生拒绝/投诉等对话，关键在于将**实际说出的日文**与谁对谁说、字面请求和潜在意图区分；严禁仅用故事推测去改变日文。

## 1. 环境确认与素材准备（允许一次性机械预处理）

1. 使用 `ffprobe` 核验源视频/音轨/时长/声道和时基，保存 `media_info.json`；保留原始音轨并按需抽 16kHz 单声道 PCM 母版。双声道语音或混音异常时可回查原始声道，不将单声道作为唯一真值。
2. 定位并优先**复用已安装的 `whisper.cpp` C++ `whisper-cli` + GGML large-v3 + Metal**。从 `--help` 获取当前版本真实支持的命令参数；短音频 smoke test 核实模型路径、返回码及 Metal 后端日志，生成 `asr_backend.json` 与 `logs/asr_smoke_test.log`。不得悄悄换成 Python Whisper/faster-whisper、Kotoba、CPU 或并行多个 ASR；发生硬件/命令不兼容应 `blocked` 并提出具体阻塞，非经授权不改变后端。
3. 音频划成 5–8 分钟（默认 6 分钟）**上下文识别单元**，边界留 8–12 秒重叠；另建**独立的全片 30 秒连续审计网格**，边界恰好覆盖 `[0,duration)`，没有任何非审核的时间缺口。
4. 可生成全片镜头切换**索引**与低成本视频缩略预览以便快速定位，但**不预先生成并要求大模型阅读全部 1 FPS 画面**。镜头索引/缩略帧未经实际观察不得当作剧情证据。
5. 创建 `.subtitle-ja-work/`、`segments.json`、`progress.json`、`global_context.md`。人物与故事索引只能随**已审听/已观测的证据**逐步更新，不能挪用其他影片的已知角色或剧情。

## 2. 音频优先的单元执行顺序（核心变更）

固定顺序为 **A. Whisper 初转录 → B. 独立全窗口声学/VAD 审计 → C. 声学与语义双触发登记 → D. 定向深度视频理解 → E. 有针对性的日文修订、字幕对齐与单元验收**。B/C 可在实际实现中流水组织，但**未执行 B 的窗口不能声称已审**。与 v3 不同，**无需等待全片视频视觉分析才可启动 ASR**；若复用同一已加载 Whisper 单进程进行多个单元的初转录可提高效率，但**每个单元的审核结果仍须逐一验收**。

### A. Whisper 转录是候选，不是最终日文

- 对当前单元使用已核实的 whisper.cpp large-v3、强制 `-l ja`（具体参数以 `whisper-cli --help` 为准）；连续上下文转录，保留原始 SRT/JSON（若工具可提供）、参数、日志及置信度相关信号。不要为了缩短时间改用低质量模型。
- 合并时明确确认相对时间戳与全片时间戳的基准；重叠边界候选先核对相邻真实覆盖再去重，不可机械丢弃 lead-in 文本。
- 不对没有转录结果的时段直接宣告“无语音”；对短促片段、低声、重叠与异常长片保持候选状态。

### B. 全片 30 秒窗口：真正独立于 ASR 的声音审计

对**每一个** 30 秒核心窗口无条件执行低成本检查（即使 Whisper 和 VAD 均标静音），为每个窗口生成声学特征，并由执行模型**逐窗口读取实际特征摘要/图表、作出疑点判定**；不得由脚本仅批量写入 `reviewed=true` 便冒充完成检查。保存 `audio_windows.jsonl`：`window_id,start_ms,end_ms,asr_entries,vad_intervals,silence_regions,energy_peaks,spectrogram_refs,noise_or_music_signals,unexplained_acoustic_intervals,inspection_method,status`。

- 用波形、短时 RMS/峰值能量、谱图、静音检测和不同条件下的 VAD 结果找出**ASR/VAD 解释不了的实际声音活动**；同时检查 ASR 字幕内部可能包含额外短促声、边界切断、异常长 30 秒句子、连续重复及无语音时幻觉。
- **声学异常不是语音识别结论。** 它只能提出“这里的声音是什么？是否有人声？”的审核问题；背景音乐、呼吸、音效、压缩伪影都可能产生波形。即使静音特征较强也不能数学证明绝对无语音。
- 对每一项音频疑点记录证据与级别（`suspected_speech / likely_non_speech / possible_hallucination / timing_issue / overlapping_voices / uncertain`）。有真实音频听辨能力时优先检查含前后 2–5 秒上下文的原片段；无音频输入能力时明确标 `audio_direct_listening=false`，不得假装已回听。
- **不要因发现疑点便反复重跑整部 Whisper。** 对有明确预期收益的局部调整切片边界或转录参数，保留原始候选与新候选；不把第二遍同模型输出视为独立真值。短语不能孤立切成 0.2 秒要求模型猜。
- 一旦检查发现可疑低音量发声、VAD 阴性但存在**无法解释的疑似人声特征**，也必须进入下节触发清单，不能仅用“音频噪声大”草率归零。**但波形非零本身不构成视频触发**：对明显连续背景音乐/环境音，只有逐窗检查了时间结构、频谱与 ASR/VAD 关系并记录非语音判断依据后才可不进入视觉队列；判断仍存疑则必须进入队列。避免把持续音乐整片误触发成 1 FPS 视频核验。

### C. 不仅声学触发，还要触发“语义可信但理解不清”的视觉检查

逐条扫描**全部**日文候选，并结合前后至少 3–5 条对白判断是否有以下问题；该全量文本审核消耗远少于全量逐帧分析：

- **声学触发 `AUDIO`**：审计后仍有**未解释的疑似人声**（包括有声学活动但无字幕/无 VAD）、低声或背景混杂、疑似人声、短促惊呼、幻觉、重复、异乎寻常的时间戳、说话人与音频不一致。
- **语义触发 `SEMANTIC`**：句法不完整或 ASR 词汇不合逻辑；否定/条件/因果/数量可疑；省略主语、宾语或身份关系；“这个/那个/做这种事”指代不明；语用行为（请求、暗示、威胁、讽刺、回绝）无法由字面确定；说话人转换或人名/职业/身份词重要；字面说得通但连续对白不知道到底在谈什么。**ASR 有文字、无 VAD 异常且模型置信度高，也不能免除此类触发。**
- **局部场景触发 `SCENE`**：同一段对话涉及人物关系变化、身体接触或动作转换、强烈反应、画外说话人、镜头切换导致词义指代不清。
- **独立的场景最低检查**：每个连续对话场景至少生成一张 `scene_context_card`，记录已知/未知人物与关系、当前讨论对象、当前争议/行动目标、问答顺序及尚需画面确认的点。**只有文字不足以形成具体卡片时必须触发视频**；不能以“翻译阶段会看”推迟重要语义疑点。

将全部触发按时间合并为 `visual_review_queue.jsonl`，字段：`trigger_id,time_range,subtitle_uids,trigger_sources,question_to_resolve,priority,status`。与已有字幕无关的声学空档必须仍进入队列；不能只筛“看起来重要”的人类对白。

### D. 被触发区域必须真正深入视频，不以一张中点帧敷衍

- 每个触发点先取完整相关事件/对话轮次，通常向前后各扩约 10–20 秒；必要时跨镜头或跨单元扩展。**该局部区间至少 1 FPS 连续覆盖并实际打开观察**，镜头切换附近额外补帧；对复杂动作、人物反应、对象不清或表情变化按 **0.2–0.5 秒间隔**补帧，必要时查看短视频和高清局部裁剪。
- 明确记录：在场人物及确定性、相对位置/身份关系、谁→对谁/何物→执行何种可见动作→接触对象/位置→方向/开始/变化/结束、可观察表情和反应、场地/道具、说话人线索、事件因果链。涉及具体对象、动作位置与状态变化时，应在画面确实可辨认的前提下准确记录；判断某项动作是否发生或完成，必须有连续画面足以支持的时序证据，不能从单帧重叠、静态遮挡或姿态臆造。被遮挡的部分标不确定。**可见事实与情绪/意图推断分开**，不准只写“多人互动”“正在发生某事”。
- 对含蓄对话，另记 `literal_speech / observed_event / plausible_intent / alternative_interpretations / evidence_limitation`：例如职位推荐、权力关系、间接暗示、拒绝与投诉威胁，哪些是文本/画面直接支持的，哪些只是可能的会话含义。**不得将暗示替换成未经说出的直白日文**。
- 每个视觉任务写 `visual_evidence.jsonl`，包括 `trigger_id,video_window,base_frame_times,frames_opened,detail_frames_opened,observed_actions,observable_reactions,inferred_context,ambiguities,impact_on_ja,status`。已抽帧但未进入视觉输入的不能写 `frames_opened`。画面不能确定具体音素/否定词/发声次数，必须回到音频层证据。
- **无触发区间不需要全片 1 FPS 查看**：此为 v4 的有意优化，不是漏做；但触发区间必须完整按上述标准执行。

### E. 日文修订、最终对齐和单元质量门禁

- 将音频转录与局部视觉证据结合，逐句确定**真正听到的日文**、说话人（可未知）、时间戳、词汇歧义及语义风险；画面可帮助判定日文多义词在场景中的指向，**不得仅凭剧情给缺失音素补词、添加否定或编造说话次数**。
- 含条件/否定、特殊称谓、关键动作词、职业/身份、具体对象或动作位置词的条目必须审查日文活用和上下句逻辑，必要时回查声学证据。
- `subtitle_evidence.jsonl` 逐条有 `uid,start_ms,end_ms,ja,audio_window_ids,asr_source,speaker_or_unknown,semantic_screened,semantic_trigger_ids,visual_event_refs,lexical_uncertainty,status`。无触发视觉时 `visual_event_refs=[]` 是**合法**状态，不得伪造。
- 必须审计：本单元所有 30 秒窗口均存在实际审计记录；所有触发均为 `resolved/evidence_limited/blocked`（不能未经处理就删掉）；每条候选字幕均有文本审核与音频证据链；确认删除的幻觉另存 `rejected_entries.jsonl`；SRT 时间轴合法、块边界覆盖与 UID 映射无误。未通过不得将单元标记 `qa_passed`。区分“全部完成审核手续”与“声音事实无法确认”。
- 如果某个疑点当前工具能力确实无法定夺，记录已尝试的操作、证据边界与保守处理；不要随意标成人工待审，更不能用貌似合理的句子填补不确定内容。

## 3. 全片整合与翻译阶段交接

- 单元结果完成后进行人物/职业身份、地名、故事时序、对话轮次、时间戳、单元边界、同句重复与幻觉全片一致性检查。发现某段字幕虽然词句流畅但**无法复述“谁对谁提出什么要求、为什么回答如此”**，将其重新标 `SEMANTIC` 并补查，而不是让这种含混状态传递到第二阶段。
- 输出 UTF-8 日文 SRT，稳定 UID 与显示序号分离；词音无证据时不造词。提供可追踪证据及场景卡片，便于第二阶段**重点分析语义疑点**，而非再次看遍所有视频帧。

**旧版 `qa_gate.py` 若要求全片 1 FPS 阅读或每条字幕必有帧，不再兼容 v4，必须更新门禁，不能用旧脚本错误判定不合格。**

建议目录（除原输入外均为新文件）：

```text
.subtitle-ja-work/
├── media_info.json  asr_backend.json  segments.json  progress.json
├── global_context.md  task_plan.md  CONTINUE_IN_NEW_CHAT.md
├── state/context_handoff.json  state/resource_log.jsonl
├── audio/master_16k_mono.wav
├── segments/S0001/
│   ├── asr_raw/  audio_windows.jsonl  audio_suspects.jsonl
│   ├── scene_context_cards.jsonl  visual_review_queue.jsonl
│   ├── visual_evidence.jsonl  subtitle_evidence.jsonl
│   ├── issues.jsonl  qa_report.json
├── rejected_entries.jsonl
├── final/影片名.ja.srt
└── handoff/
    ├── 影片名.ja.srt
    ├── subtitles_with_evidence.jsonl
    ├── audio_audit_summary.json      # 30秒全窗审计与风险/能力状态
    ├── scene_context_cards_all.jsonl
    ├── visual_review_queue_all.jsonl
    ├── visual_evidence_all.jsonl
    ├── unresolved_issues.jsonl
    ├── global_context.md  glossary_ja.json
    └── identification_report.md
```

交接文件里的视觉证据路径必须可解析，没法共享的文件需复制或清楚说明。**新版不要求提供 v3 专用的 `frames/base` 全片 1 FPS 证据，也不把旧版 `scene_events_all.jsonl` 视为必备；如果已有，可作为辅助。**

## 4. 完成与停机条件

- 如实报告：全片时长、Whisper 实际后端、30 秒窗口总数/已审数、声学疑点数、语义触发数、触发视觉区间及实际看过的帧、修复/保留疑点数、音频直接听辨能力及工具限制。**不得用“全部窗口经过 VAD 统计”冒充全部疑点已解决。**
- 上下文满则按 S 保存交接、请求新会话，不得以快速扫完代替验收。16GB 内存压力过高则停止本任务的重负载阶段而非缩小质量范围。
- **启动时**先核验 whisper.cpp + Metal、媒体信息、目录和完整音频审核网格；再执行 A→E 的音频优先分段工作。不需要为满足“先看视频”的旧规重复打开 7000 多张基础帧。

## 附录｜结构性门禁最低条件

`audio_window_coverage == full_duration`；`subtitle_semantic_screen_count == candidate_subtitle_count`；`visual_trigger_pending_count == 0`（允许明示 `evidence_limited/blocked`，不能虚称 resolved）；`triggered_visual_windows` 具有实际 `frames_opened` 和时间覆盖记录；`qa_report.json` 的状态由可解析文件复算；凡是 `audio_direct_listening=false`，不得描述为“逐秒实际听过”。

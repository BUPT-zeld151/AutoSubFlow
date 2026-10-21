# PROMPT 02 v4｜日语字幕的语义具体化、情境精译与中文质量校订

> **独立新会话。** 输入：原视频、Prompt 01 v4 交接目录、已完成音频审计的日文 SRT。输出自然、准确、可直接观看的中文 SRT 与语义/校订证据。**本阶段不再强制重新观看全片 1 FPS 画面，也不逐句无条件打开中点帧。**主要算力用于逐条弄清“这句话在此时具体说了什么、指向什么、起什么作用”，按明确触发条件定向看视频。

## S. 三阶段通用不可降级运行协议

1. **不改变质量目标，只改变证据投入位置。** 全部日文字幕的语义具体化、全部中文译文的语言与忠实度审查、每个已触发视觉任务都必须核验。v4 **不要求**全片基础帧全部输入大模型；禁止以旧 v3 的“每秒 1 帧全片必看”为验收条件。也不得擅自把已触发的局部 1 FPS/加密观察再缩成一张关键帧。
2. **上下文不足不能快扫收尾。** 将任务划为 5–8 分钟处理单元及更小原子批次；每批完成后落盘。若估计无法高质量完成下一完整批次，保存 `progress.json`、`state/context_handoff.json` 和 `CONTINUE_IN_NEW_CHAT.md`，在当前会话停止后请求用户开启**新会话**继续。不得声称自行创建了新会话，不得将未审内容标为已完成。减少单批大小可以，减少总审核范围不可以。
3. **16GB Apple Silicon 统一内存保护。** 开工核实 `sysctl -n hw.memsize`；在重型任务前后及每单元边界观察 `memory_pressure`、`vm_stat`、`sysctl vm.swapusage` 和主要进程 RSS。**同一时刻最多一个重型任务**：Whisper/Metal、VAD 大模型、批量视频解码/镜头检测/图片处理不得重叠；大规模预处理流式、串行，工具线程审慎设限；不预加载两小时图像到内存。出现明显压力或 Swap 持续升高，停止启动新任务，等待/安全结束自己发起的任务，释放缓存并保存检查点；不得杀用户进程。日志入 `state/resource_log.jsonl`。内存紧张不等于上下文紧张；切换会话不能增加物理内存。
4. **证据诚信。** `produced`（文件已生成）、`opened`（实际被视觉模型查看）、`reviewed`（有具体审核结果）、`verified`（证据充分）、`uncertain`（查过但无法判断）、`unreviewed`（未做）、`blocked`（无法执行）彼此不同。VAD/波形有活动≠可辨语音；Whisper 结果≠真值；有关键帧≠已理解动作；上下文“合理”≠声音确实说过。
5. **保留原始材料和稳定标识。** 所有时间戳使用全片绝对毫秒；原音视频和初次 Whisper 输出不可覆盖；修改、分合字幕保留 `source_uid → output_uid` 追踪。脚本用于切片、索引、门禁及声学统计，不能代替真实的视听语义判断。不要擅自用子代理或第三种大型识别模型代替指定主模型决策。
6. **最小可恢复交接。** `context_handoff.json` 至少含 `phase,prompt_version,source_paths_and_hashes,completed_units,current_unit,current_step,last_verified_window_or_uid,next_exact_action,pending_tasks,open_issues,work_paths,quality_gate_results,asr_backend,memory_status`。原子写入并重新读取校验。跨会话恢复时先读本 Prompt、交接文件和证据索引，再从最后可信检查点继续；不能因新会话缺少旧聊天上下文就重做已经验收的全部工作或忽略未完成项。

## 0. 核心目标：不让“字面能译”替代“真的理解这段对白”

高质量字幕同时满足：①日文语义忠实；②**具体而清楚**，不使用无根据的模糊替代词；③人物关系/行为对象/对话意图可理解；④口语自然；⑤短句、称谓、应答/粗俗度保留；⑥符合 SRT 阅读约束。**每条都要进行语义审核，但不代表每条都需要重新读图**。非触发项允许依靠确实存在的日语语义与可靠交接证据完成。

严禁两种相反错误：
- **笼统敷衍**：将有明确具体指向的日文译成“那个”“这种事”“你自己知道”“那边”等模糊中文，读者不知道谁对谁做什么、问题在哪里。若原文省略而语境可唯一确定，应在**不增加未说信息**的前提下使用中文自然的指代/表达。
- **过度解释**：不能把潜台词直接写成原文没有说过的明示承诺、威胁、动作或条件。翻译应准确传达语用功能，但保留原句的含蓄程度；必要时将对话意图写进幕后 `meaning_record`，**而不是当成台词增译**。

例如一段有关教师推荐企业就业的交谈，人物关系、承诺和暗示、对方回绝以及投诉威胁都可能影响指代和语气。正确操作是先明确**文本字面、人物意图及画面证据的边界**，再翻出观众能听懂的对白；不可仅凭剧中动作推导不存在的日文词句，也不可沿用另一部影片的故事设定。

## 1. 读取交接，建立节省上下文的双层语境索引

1. 核实输入视频、`ja.srt`、Prompt 01 的 `subtitles_with_evidence.jsonl`、`audio_windows` 状态、`scene_context_cards_all.jsonl`、`visual_review_queue_all.jsonl`、`visual_evidence_all.jsonl`、`global_context.md`、`unresolved_issues.jsonl`。**如果交接路径不同，基于内容与 manifest 定位而非伪造缺失**。初识别未审区域须保留源语风险，不得一律当成 confirmed。
2. 建立精简 `story_bible.md`：人名/身份/职位/相互关系、叙事时序/闪回、事件/争议目标、重要名词与经证据支持的情绪线。用 `scene_id → 对话区间 → 人物与关系 → 争议对象 → 具体事件 → 不确定项` 组织；保存到磁盘，**不要每处理一个短句就在上下文中重新展开全片**。
3. 每个连续对话场景至少形成/复核一份 `dialogue_scene_card`：`scene_id,start_ms,end_ms,speakers,relationship,topic,each_party_goal,sequence_of_claims_requests_replies,observable_cues,open_questions,evidence_refs`。这里的“目标/潜台词”必须单独标 `inferred`，不能把猜测作为可见事实。
4. 对画外音、画面不同时空、剪辑叙事保持谨慎；没有必要为全片所有静默镜头做视觉长描述。

## 2. 每条日文的强制“语义具体化”检查（文本覆盖率 100%）

在 5–8 分钟单元中，按**连续 10–25 句的小批次**逐条建立 `meaning_records.jsonl`。每条至少有：

- `uid,ja,time_range,scene_id,speaker,listener,topic_ref`：说话人/听话人/话题对象，未知可为空但不能随意猜。
- `literal_proposition`：这句话字面上实际表达的内容，保留日语的肯定/否定/条件/时态、动作主体与受体、事实或疑问。
- `speech_act`：请求/提供机会/试探/暗示/拒绝/警告/辩解/威胁/反问/应答等，**语用推断必须有前后对话依据**。
- `referent_map`：每个重要省略项及“这/那/它/你说的”等分别指向谁或什么；`grounded / plausible / unknown` 分级。
- `logical_link`：承接上一句的何种提议、反驳、条件、后果或话题转换；看起来无逻辑时触发复核。
- `specificity_check`：若要译作“那个/这样/做这事”，具体所指是什么？原日文是否真的刻意含糊？有无证据可以写得更明确？
- `ambiguity_triggers / evidence_refs / confidence_reason`：不是给一个空洞自信分数，而是列出不清楚的**具体问题**。

**明确的质量门禁：模型必须能用一两句中文解释每条实质对白“谁在对谁谈什么、为了什么、这句和前一句什么关系”。** 对无此能力的条目，`semantic_pass=false` 并产生视频/原声核查任务，不能先翻成泛泛的中文再算通过。纯语气词可记录其在问答中承载的态度，无须强行扩成完整命题。

## 3. 语义触发型视频核验：把图像算力花在真正可能改译的地方

**不按全片固定采样、不无条件逐条打开中点帧。** 但下述触发器全部要扫描（文本扫描覆盖 100%），实际触发后必须执行媒体核查：

- A. 日语文本不合理、词语活用或省略关系不清；具体的人名/称谓/职业/身份指向影响译义。
- B. 对话逻辑不连贯：条件结果、因果、答非所问、拒绝对象、威胁对象、话题跳转不清。
- C. **潜台词/间接话语**：客套提出要求、暗示交易、身份权力关系、话外威胁、讽刺、刻意含混或“说一套做一套”；表面每句有日文但连起来不知道剧情。
- D. 词义与可见动作、动作受体、姿态变化或人物反应密切相关；视觉证据可能区分多义词，特别是具体对象、动作位置、道具等。
- E. Prompt 01 留下的语义/音频不确定、音画冲突或已触发但尚未查完的项目，以及译文 A/B 明显语义分歧。

对一组相关疑点**合并为一次视频事件查看**，避免同一场景反复提帧。通常看前后各 10–20 秒或完整问答；局部**连续至少 1 FPS**，实际打开观察，镜头变化/动作转折加 **0.2–0.5 秒补帧**，必要时查看短视频/原图裁剪。记载 `visual_review.jsonl`: `trigger_id,scene_id,video_window,base_frame_times,frames_opened,detail_frames_opened,observable_actions,observable_reactions,inferred_intent,meaning_impact,unresolved`。

细粒度观察要说清**人物身份、位置、谁对谁做什么、动作/接触的对象与先后、可见的神态变化**；对具体对象、动作位置与状态变化，采用可观察、必要且准确的术语；判断某项动作是否发生或完成，必须有连续画面的时序证据，不能从单帧重叠或静态遮挡推断；看不清时不猜。必须把“可观察动作”和“推断人物意图”分开记录，**不能用画面替换日文原声**。音频中是否有否定、某个词或发声次数，仍需回到已有音频证据，必要时交识别专项处理。

每个已触发且有足够视觉线索的疑点，必须记录最终如何**实质性影响 `referent_map`、语用解释或译文**；若观看后无新增证据，也要说明为什么不能定夺。旧场景卡可用于定位，不能充当本会话实际查看的证明。

## 4. 译文生成：先说清楚，再说自然，不添油加醋

1. 用 `meaning_record` 和对话场景卡生成中文初译 A；中文须体现日语实际语用和话题对象，但在**原文明示与暗示之间保持同等信息粒度**：文字有明确对象时勿退化为“那个”；原文只有暗示时勿直接补成未经原文支持的明确断言。
2. 人物发言的语言身份要合理（正式、居高临下、询问、客套、威胁、愤怒、拒绝等）但不允许把情绪当作添加词句的理由。短句、否定、条件、数量、时间、称谓、器物、具体对象及位置的原文信息不能丢失。
3. 对每组连续对白，从已有的**语义记录**重新写中文 B：**不沿用 A 的句法骨架**，着重修正生硬、抽象、跳跃的表达。若当前上下文中已出现 A，则标 `blind_reconstruction=false`；只有真正隔离的上下文调用未见 A 才标 true。A/B 不一致是复核信号，B 不是天然更正确；比照日文与画面证据选择 A/B/C。
4. 关键审核问句：**“不懂日语、只看这几句中文的观众，能否准确知道此段谁向谁提出什么、另一方为什么拒绝/回应、发生了什么变化？”** 如不能且源语/语境有足够依据，必须继续修改，不能以“翻译大致符合”验收。
5. 保留必要的原文重复和短促应答；不要机械合并发声或一律翻成同样的拟声。每行约 20 字只是参考，异常高阅读速度触发时间轴复查，不能通过删除真实关键信息满足字数阈值。

## 5. 中文校订与语义一致性：两项独立的全量检查

**第一轮：中文裸读。** 按场景连读全片中文（每批 15–30 条；保留前后 3–5 条），**暂不展示日文原文及之前的翻译理由**。逐条找中文观众看不明白的句子、搭配错误、语法残缺、指代漂移、客套句生硬、意思前后矛盾、阅读速度异常；不能给每句打“没有发现问题”就跳过。例：“那你很快要圣诞了”必须触发明确的语言诊断，不得因模型知道原文含义而放行。

**第二轮：日中忠实度逐条对照。** 全量核查否定/条件/因果/时态/人称、施动受动、说话人、重要名词/动作位置、问答与潜台词边界，特别防“把含蓄话语翻成不存在的明示行为”和“把明确话语译成模糊的那个”。对有实质语义疑问的句子回到第 3 节。日文源稿疑似缺失词音时记 `source_issue`，保留证据，**不能凭情节补写原文**。

**每条语言问题**必须具体记录 `uid,old_zh,span,issue_type,why_wrong,proposed_zh,evidence_refs,status`。能依据现有证据修复的必须实际修改并回归检查，禁止滥用 `needs_human_review`；仍需要真实原声的疑点保留 `evidence_limited`，不能强行清零。

## 6. 单元验收与跨阶段契约

每个单元输出：`dialogue_scene_cards.jsonl`、`meaning_records.jsonl`、`visual_review_queue.jsonl`、`visual_review.jsonl`、`translation_decisions.jsonl`、`language_issues.jsonl`、`semantic_verify.jsonl`、`segment_zh.srt`、`qa_report.json`。

**机械可验的门禁**：`meaning_record_count == ja_entry_count`；`semantic_screened_count == ja_entry_count`；`language_screened_count == zh_entry_count`；`semantic_verify_count == zh_entry_count`；所有触发项有 `resolved/evidence_limited/blocked` 状态，触发视觉者有实际 `frames_opened`；`source_uid` 映射和日中时间轴对应有效。**不要求 `all_entries_have_video_frames=true`，也不要求全片 1 FPS 帧查看覆盖**。旧版要求逐条有视频帧的 `qa_gate.py` 必须更新后再用于本阶段。事件/语言质量无法靠纯文件存在证明，报告不得写“绝对正确”。

完成全片后再检查人物身份/称谓、企业/职业名、全片暗线/闪回、同一词汇一致性与有理由的差异、语病和连贯对白；不允许因上下文趋紧而快扫收尾，按 S 节保存并在新会话继续。

建议目录：

```text
.subtitle-zh-work/
├── story_bible.md  glossary_zh.json  progress.json
├── CONTINUE_IN_NEW_CHAT.md
├── state/context_handoff.json  state/resource_log.jsonl
├── segments/S0001/
│   ├── dialogue_scene_cards.jsonl  meaning_records.jsonl
│   ├── visual_review_queue.jsonl  visual_review.jsonl
│   ├── translation_decisions.jsonl  language_issues.jsonl
│   ├── semantic_verify.jsonl  qa_report.json  segment_zh.srt
├── final/影片名.ja.srt  final/影片名.zh.srt
├── final/uid_ja_zh.tsv
└── final/translation_report.md
```

保留第一阶段音频窗口索引与视觉证据路径，不要求第一阶段必须具有旧版 v3 的 `scene_events_all.jsonl` 或 `frames/base`。最终输出不得仅剩 SRT；必须让第三阶段能够依据 UID 回溯音频、语义具体化结果与真正打开过的视频证据。

## 7. 启动指令

先验证日文源稿与媒体/交接证据、建立人物关系与精简场景卡；然后逐个 5–8 分钟单元执行**全量日文语义具体化 → 定向视觉复核 → 中文初译/独立重表达 → 中文裸读 → 日中忠实度检查 → 单元验收**。不要首先重新读取全片 1 FPS 图片。若某个已识别的对话场景**连起来仍不知道在说什么、想做什么或拒绝什么**，必须在翻译前补充场景核查；不要靠“写得含糊一些”蒙混通过。

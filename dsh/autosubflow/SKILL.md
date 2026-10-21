---
name: autosubflow
description: 自动为单部日语视频制作完整日文和简体中文字幕。用于字幕制作、日语识别、中文翻译和独立终审；主会话串行调度三个阶段，每阶段默认一个独立子智能体持续工作，仅在上下文不足或中断恢复时交接，以磁盘质量门禁验收。需 DeepSeek Harness subagent 和本地影音工具。
metadata:
  version: "4.0-orchestrated-3"
  compatibility: "DeepSeek Harness Standard with subagent and shell tools; equivalent isolated-subagent clients. macOS Apple Silicon 16GB preferred."
---

# autosubflow｜三阶段连续工作与自动交接

用户只需在视频工作区提出一次完整字幕制作请求，由主会话自动组织三个阶段，无需手动开启三个会话。**每阶段默认由一个独立子智能体连续完成；六分钟单元是处理、落盘与验收检查点，完成单元后由同一子智能体继续。** 只有上下文不足或实际中断恢复需要时才更换同阶段工作者。

三份 `references/PROMPT_0N_*_v4.md` 的识别、翻译、终审质量标准保持有效。它们所说“上下文不足时请求用户开启新会话”，在本自动调度环境中由主会话创建接替子智能体实现；只有确实没有自动调度工具时才需要用户操作。**划分处理批次不构成退出当前子智能体的理由。**

## 角色与执行边界

- 主会话读取本文件和 [agents/ORCHESTRATOR.md](agents/ORCHESTRATOR.md)，负责环境准备、阶段派发、交接和脚本验收；不在主会话识别、翻译或分析视频，不加载三份阶段 Prompt。
- 工作子智能体读取 [agents/WORKER.md](agents/WORKER.md) 和当前阶段的一份完整 Prompt；负责**该阶段所有剩余工作**，包括单元循环、跨段一致性、全片汇总、最终 QA 和交付。不得自行切阶段或递归创建子智能体。
- 任意时刻至多一个工作子智能体。默认前台等待 `subagent(run_in_background:false)`；一次性调用可以在一次任务内持续执行整个阶段。无需为本 Skill 修改 Harness 插件配置。
- 上下文不足时，依照 [references/CONTEXT_CONTINUITY.md](references/CONTEXT_CONTINUITY.md) 保存可恢复交接；主会话接替，无需用户重发阶段指令。阶段 3 使用新的独立工作者，先中文盲审，不复用阶段 2 的会话。
- 16GB Apple Silicon：Whisper/Metal、VAD、批量 ffmpeg 等重负载串行，执行阶段规范的内存监控。内存不足记为 `resource_blocked`，停止重负载；更换子智能体不能解决物理内存不足。

## 初始化与阶段路由

工作区取用户指定目录，否则当前目录。先确认唯一目标视频；多部视频且无法从用户请求确定时再询问。Skill 安装目录只放规则和工具，影音及中间成果写入视频工作区。

```bash
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" init --workspace "<VIDEO_WORKSPACE>"
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" status --workspace "<VIDEO_WORKSPACE>"
```

`init` 用 ffprobe 和 SHA-256 建立 `.subtitle-pipeline/manifest.json`，按连续六分钟核心区间建立 `S0001...`；已有清单只读复用。**清单不定义子智能体数量。** 保留现有三阶段目录、稳定 UID、绝对时间戳及已通过检查的产物。跨单元上下文可重叠，核心审计范围不能有缺口。

`status.next_phase` 是下一个未通过的阶段，`next_unit` 是阶段内最早未通过的检查点。若已有该阶段工作者在运行，由它处理下一单元；不得把每次 `status` 的结果理解为需要创建新工作者。状态脚本不掌握活跃子智能体，主会话须跟踪当前唯一调用/任务。

| 阶段 | 工作者读取的规范 | 持续执行范围 |
|---|---|---|
| 1 日语识别 | `references/PROMPT_01_JA_TRANSCRIPTION_v4.md` | 所有剩余单元的 ASR、30 秒声学审计、触发视觉核验、日文审查；全片一致性、JA 终稿与 handoff |
| 2 中文翻译 | `references/PROMPT_02_ZH_TRANSLATION_v4.md` | 建立全片人物/语境与术语索引，逐场景翻译和复核所有剩余单元；全片一致性、JA/ZH 对齐及 handoff |
| 3 独立终审 | `references/PROMPT_03_ZH_FINAL_REVIEW_v4.md` | 完整中文盲审、日中对照、场景连贯、分级纠错、逐条全片回归及最终报告；批次完成继续下一批 |

默认完整请求执行全部三阶段；用户只请求一个阶段时，验收该阶段后停止。

## 持续工作与验收

主会话按 ORCHESTRATOR 契约派发整个阶段，任务中的 `START_UNIT` 仅为起点，不能限制工作者只做这一段。工作者在自己的上下文内循环处理、保存与检查：

```bash
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" unit --workspace "<VIDEO_WORKSPACE>" --phase 1 --unit-id S0001
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" gate --workspace "<VIDEO_WORKSPACE>" --phase 1
```

阶段 2 替换 `--phase 2`；阶段 3 使用 `gate --phase 3`。单元通过后更新语境与进度，**同一工作者继续下一单元**；最后一单元通过后仍须生成全片终稿、交接和阶段 QA。只有阶段 Gate 通过才可报告 `phase_complete`，主会话实际重跑该阶段 Gate 后才进入下一阶段。Gate 缺失可修复文件时由当前工作者继续修复，不能靠“单元完成”提前结束。

上下文交接必须依据可核对的当前用量。默认达到窗口 **90%** 后才允许在安全检查点正常交接；例如窗口为 1,000,000 tokens 时，约 900,000 才进入交接范围，约 220,000–240,000 不构成耗尽。阈值是本 Skill 的调度约定，不是模型供应商保证。不得凭“工作很久、图很多、剩余任务多、无法一口气做完整阶段”或单元数量退出。

在单元/批次边界按 [CONTEXT_CONTINUITY](references/CONTEXT_CONTINUITY.md) 运行只读用量检查 [scripts/context_budget.py](scripts/context_budget.py)。DSH_HOME 和实际窗口必须从运行环境/记录读取，不能假定为 1M；优先提供方锚定用量，不能把累计计费 token、输出总量或文本字符估算当成当前上下文。没有遥测时仍继续下一原子批次并保存进度；未知不等于耗尽。唯一的阈值例外是可复核的供应商上下文长度拒绝；超时、网络、输出长度或物理内存故障应按各自原因处理。

**结构 Gate 只能检查证据与产物完整性，不能证明语音、画面和翻译语义正确。** 必须遵守 v4 的真实审核、逐句证据、完整覆盖和不确定性记录要求；禁止为了通过脚本制造记录。

## 恢复与停止

每个单元/原子批次均落盘，跨段人物、指代、术语和未决问题按 CONTEXT_CONTINUITY 契约维护；续接时读取相关证据，不能仅凭简短摘要猜测剧情。已有单元通过可复用；跨段检查发现问题时按证据有针对性修订并重跑受影响 Gate。

允许的正常返回是阶段完成、经用量检查支持的上下文交接、真实阻塞或用户暂停。外部超时/宿主中断时从可信磁盘检查点恢复。对子智能体无理由提前结束，按调度异常处理并明确记录，不能默认为正常的逐段轮换。连续两次接替运行没有实质进展时停止报告，避免空跑循环。

缺少真实 subagent、必要影音/听辨工具、权限或不可恢复的资源故障时明确报告；不得冒充调度成功，不自行安装新模型或杀用户进程。用户暂停则停止新调度、保留状态。Skill 不保证跨宿主关闭继续运行，重开后可从检查点续接。

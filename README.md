# AutoSubFlow · 自动字幕工坊

**一次启动，完成日语转录、中文翻译与独立终审。**

AutoSubFlow 是面向 **DeepSeek Harness（DSH）与 OpenCode** 的日中字幕 Skill。由主会话串行调度三个阶段，让字幕工作沿着完整规范持续进行，并在磁盘保存证据、进度与可恢复交接。

项目名称为 **AutoSubFlow**，Skill 调用名称和安装目录名统一为 **`autosubflow`**。

## 工作流程

| 阶段 | 工作内容 | 规范 |
| --- | --- | --- |
| 1 · 日语转录 | 语音识别、完整声学复核、必要的画面核验、日文审查与全片汇总 | `PROMPT_01_JA_TRANSCRIPTION_v4.md` |
| 2 · 中文翻译 | 建立人物与场景语境、逐句翻译、术语及指代一致性、日中对齐复核 | `PROMPT_02_ZH_TRANSLATION_v4.md` |
| 3 · 独立终审 | 新工作者先中文盲审，再日中对照、纠错和全片回归 | `PROMPT_03_ZH_FINAL_REVIEW_v4.md` |

- **默认每阶段一个独立子智能体，持续完成该阶段全部剩余工作。** 六分钟单元是处理与检查点，同一工作者完成后继续下一单元。
- 正常上下文交接要求只读核验实际用量达到窗口的 **90%**；窗口从运行环境读取，不假定为 1M。未知用量、单元数量或工作时间都不能作为耗尽证据。供应商明确拒绝超长上下文时按真实错误恢复。
- 保存跨段人物、术语、未决问题、证据位置及精确进度；实际中断后可从检查点恢复。
- 任意时刻至多一个工作子智能体；Whisper、VAD 与批量影音处理串行，避免重负载叠加。
- 主会话重新运行阶段 Gate，通过后才切换阶段。Gate 检查文件与证据结构，语音、画面和翻译的准确性仍须由工作者依照完整规范核验。

## 环境要求

需要支持独立子智能体、文件与 Shell 操作的宿主，以及 Python **3.10+**、`ffmpeg`、`ffprobe` 和阶段规范要求的语音识别、音频听辨与画面核验能力。模型、影音工具与权重需自行配置，本仓库不附带这些依赖。

现有规范主要针对 **macOS Apple Silicon / 16GB 内存**；其他环境需要核验工具、路径及资源约束。OpenCode 适配依据为 **2.0.30** 的原生 `subagent` 工具与本地 API，其他版本以实际 schema 为准。DSH 需要 `subagent` 能力；模型容量、运行时间和工具权限取决于宿主与提供方。

## 安装

先下载本仓库，或克隆后进入目录：

```bash
git clone https://github.com/BUPT-zeld151/AutoSubFlow.git
cd AutoSubFlow
```

### DeepSeek Harness

将 [`dsh/autosubflow`](dsh/autosubflow) **整个目录**复制到 Harness 实际扫描的 Skills 目录。若已有同名版本，请先备份。不要只复制 `SKILL.md`。

如果当前终端的 `DSH_HOME` 已指向实际运行目录，且目标尚未安装，可使用：

```bash
test -n "$DSH_HOME" && mkdir -p "$DSH_HOME/skills"
test -n "$DSH_HOME" && test ! -e "$DSH_HOME/skills/autosubflow" && cp -R dsh/autosubflow "$DSH_HOME/skills/"
```

未设置 `DSH_HOME` 时，请直接使用实际扫描目录；不同安装方式可能采用不同位置。刷新 Skills 或重启宿主后，在新会话确认已加载本目录。

### OpenCode

需要同时安装 Skill 和专用工作子智能体。先备份已有同名文件；目标尚未安装时，在仓库根目录执行：

```bash
mkdir -p ~/.config/opencode/skills ~/.config/opencode/agents
test ! -e ~/.config/opencode/skills/autosubflow && cp -R opencode/skills/autosubflow ~/.config/opencode/skills/
test ! -e ~/.config/opencode/agents/autosubflow-worker.md && cp opencode/agents/autosubflow-worker.md ~/.config/opencode/agents/
```

刷新或重启 OpenCode 后，确认可发现 `autosubflow` 与 `autosubflow-worker`。不强制指定模型，不设置任意步骤上限。低占用提前返回时，主会话应使用原 `sessionID` 继续当前阶段。详见 [OpenCode 适配说明](opencode/skills/autosubflow/references/OPENCODE.md)。

## 启动

在含一部目标视频的工作区中，向主会话发送：

```text
使用 autosubflow Skill，读取 examples/START_AUTO.md，
对当前工作区的唯一视频依次完成日语转录、中文翻译和独立终审。
严格执行各阶段完整 Prompt 与质量检查；每阶段默认一个子智能体持续完成，
仅在有依据的上下文不足或中断恢复时交接，并保存进度与跨段语境。
```

只处理某一阶段时，可使用各版本的 `examples/START_STAGE_01.md`、`02.md`、`03.md`。运行产物写入视频工作区，Skill 安装目录只保存规则与工具。

## 状态与恢复

将 `<SKILL_ROOT>` 与 `<VIDEO_WORKSPACE>` 替换为实际路径：

```bash
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" status --workspace "<VIDEO_WORKSPACE>"
python3 "<SKILL_ROOT>/scripts/pipeline_ctl.py" gate --workspace "<VIDEO_WORKSPACE>" --phase 1
python3 "<SKILL_ROOT>/scripts/context_budget.py" --workspace "<VIDEO_WORKSPACE>" --session-id "<CHILD_SESSION_ID>"
```

DSH 的用量检查还可传入 `--dsh-home`。两种版本的上下文脚本实现不同，请使用对应宿主的版本。返回码 `0` 表示达到交接阈值，`2` 表示应继续，`3` 表示遥测不可用；检查本身不启动或停止任务。

更新 Skill 文件不会自动改写已运行会话的指令；应在安全检查点保存后重新加载规范。宿主关闭后不保证后台继续运行，可重开并从磁盘检查点恢复。DSH 的一次性子智能体调用不支持实时消息，是否能持续通信取决于宿主的具体调用模式。

## 验证范围

仓库附带上下文交接与流水线状态的合成回归测试：

```bash
python3 -m unittest discover -s tests -v
```

这些检查不调用模型或处理真实媒体。当前发布经过结构与合成场景检查，**尚未完成新版完整三阶段的真实影音端到端验证**。90% 阈值是调度规则与辅助检查，不是宿主强制执行的保证，也不保证超时、自动压缩或资源中断不会发生。

## 目录

```text
dsh/autosubflow/              # DSH Skill
opencode/skills/autosubflow/  # OpenCode Skill
opencode/agents/                 # OpenCode 专用子智能体
tests/                           # 无模型调用的合成回归测试
```

## 许可证

[MIT](LICENSE) · Copyright (c) 2026 BUPT-zeld151。

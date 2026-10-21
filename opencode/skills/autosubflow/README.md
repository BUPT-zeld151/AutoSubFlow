# autosubflow：OpenCode 2.x 安装副本

本副本保留原有三份完整 v4 Prompt、单元/阶段 Gate、每阶段尽量一个子代理及90%实测交接规则。运行适配 OpenCode 2.0.30：subagent(agent, description, prompt, background, sessionID)，可用原 sessionID 继续同一会话。没有修改 DSH 安装。

安装位置：~/.config/opencode/skills/autosubflow/。配套工作者：~/.config/opencode/agents/autosubflow-worker.md。不固定模型，不设置步数上限，不修改全局模型或权限配置。

在视频工作区选择可执行工具的主代理，发送 examples/START_AUTO.md 的指令。只执行一个阶段用对应 START_STAGE_01/02/03 示例。具体调用和用量检查见 references/OPENCODE.md。

已检查规则/格式、只读用量脚本及安装发现；不等同于在 OpenCode 跑通实际视频全流程。OpenCode 可能自动压缩上下文；压缩本身不等于必须换子代理，进度与证据仍持续落盘。版本变化时以当前工具schema为准。

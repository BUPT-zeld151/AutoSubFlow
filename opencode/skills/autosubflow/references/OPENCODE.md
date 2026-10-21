# OpenCode 2.x 运行适配

已适配并核验的版本为 OpenCode 2.0.30；原生工具名为 `subagent`，不是旧版的 `task`。工具输入：`agent,description,prompt`，可选 `sessionID,background,model`。不指定模型，使用实际运行时默认/用户选择；不设置任意 steps 上限。

- 新阶段：`subagent(agent="autosubflow-worker", description="阶段1 日语识别", prompt=<完整阶段任务>, background=false)`，省略 sessionID。
- 同阶段低占用提前返回或可修复验收失败：以相同 agent 和返回的 sessionID 继续，提示具体剩余工作。这样保留原子会话上下文，不需要新建子代理。
- 达到实测90%而需重置上下文：保存完整交接，确认原工作者结束后，省略 sessionID 新建接替者，范围仍是当前阶段全部剩余工作。
- 阶段切换：始终新建独立会话；阶段3先中文盲审。
- 如果当前运行时工具不支持这些字段，读取实际 schema 后等价适配；不得编造调用成功或擅自退回主会话代做全部媒体工作。

本副本的 scripts/context_budget.py 已替换为 OpenCode 专用只读查询，不访问 DSH 数据：

```bash
python3 "<SKILL_ROOT>/scripts/context_budget.py" --workspace "<VIDEO_WORKSPACE>"
python3 "<SKILL_ROOT>/scripts/context_budget.py" --workspace "<VIDEO_WORKSPACE>" --session-id "<确切child的sessionID>"
```

脚本通过 OpenCode CLI 自带的本地服务发现和认证读取 session/active、session/{id}、session/{id}/context、model。只输出用量/模型/会话身份，不输出对话内容或凭据，不发送模型消息、不停止任务。PATH 没有 opencode 时使用本机应用内置 CLI `/Applications/OpenCode.app/Contents/Resources/opencode-cli`；可传 --opencode-cli 或私有服务的 --server。

自动定位仅接受目标工作区唯一活动子会话；多于一个时必须指定。父会话验收一定传自己 subagent 调用返回的精确 sessionID。模型容量从该次 assistant 请求对应的 provider/model 查询，不能假定1M。用量按当前版本界面的最近请求口径，非历史累计；新工具结果/尚未完成请求可能还未反映。

正常返回码0表示可交接（>=90%），2表示继续，3表示无可靠遥测（不能视为耗尽）。供应商明确上下文长度拒绝须额外保留真实错误。OpenCode自身压缩/工具超时/输出长度上限分别记原因，不能冒称已经用尽1M。

适配依据：OpenCode 2.0.30 二进制中工具schema、上下文占用算法及 `/openapi.json`；通用发现目录见 https://opencode.ai/docs/skills/ 。旧版网站示例可能仍用不同参数，以本机schema为准。

# 阶段工作子智能体契约

你运行在独立上下文，是当前阶段的持续工作者。**默认完成当前阶段全部剩余工作；六分钟单元和原子审核批次是检查点，完成后继续，不是任务结束点。** 不执行其他阶段，不递归调用子智能体。

## 输入

父会话提供：
- `SKILL_ROOT`、`VIDEO_WORKSPACE`：绝对路径。
- `PHASE`：1 / 2 / 3，`SCOPE=remaining_phase`。
- `START_UNIT`：阶段内最早未完成单元或恢复起点；为空可能表示仅剩全片汇总/交接。它不限制可处理的后续单元。旧任务传来的 `UNIT` 仅在没有 START_UNIT 时作为兼容的恢复起点。
- `PROMPT`：当前阶段的一份完整 v4 规范。
- manifest、检查点和前阶段交付路径，`FIRST_ERRORS`：真实 Gate 缺失/阻塞信息。

先读 SKILL.md 的角色/调度规则、`references/CONTEXT_CONTINUITY.md`、指定阶段完整 Prompt，再检查输入产物。v4 所说“上下文不足请用户新开会话”在这里映射为保存交接并返回给父调度器；阶段质量标准仍全部有效。

## 在同一上下文内循环

1. 核实 manifest、当前进度、handoff、实际证据与工具能力，保留已通过单元。按 CONTEXT_CONTINUITY 建立本阶段可用的全片语境，阶段 3 保持中文盲审顺序。
2. 按 manifest 核心区间执行当前阶段的下一单元，完整落实 v4 的审核/触发/修订流程。场景或问答跨界时查看必要的相邻上下文，不以时间分段切断语义判断；字幕核心范围与稳定 UID 仍按清单落盘。
3. 阶段 1/2 将产物写入 `segments/Sxxxx/` 并运行本单元 `pipeline_ctl.py unit`；失败先修复，真实不可解决的事实标记证据边界，不能编造。阶段 3 逐轮、逐 UID/场景保存进度，最终回归逐条写 `regression_reviews.jsonl`。
4. 每单元/批次完成更新 progress、语境及证据索引，并检查资源与剩余上下文。**只要仍能高质量执行，直接继续下一单元/批次；不要返回单元完成报告结束调用。** 原始日志和图片留磁盘，只把判断必需内容载入上下文，避免反复加载全量工具日志。
5. 单元/批次边界按 CONTEXT_CONTINUITY 运行 `context_budget.py` 获取自己的当前用量；**正常上下文交接须实测占用达到 90%**。低于阈值继续下一原子批次，不能因为不够一次做完所有剩余单元就退出；一次只需能做下一小步。没有用量时不得凭感觉宣布耗尽，也不得把估计标为 `observed:true`。每批持续落盘，减少不必要的日志回读；不能因节约 token 降低审核覆盖。达到阈值后保存完整交接并返回 `context_handoff`。若供应商明确拒绝上下文长度，则保留具体错误和来源，由父会话验证例外；网络/超时/输出长度错误不属于该例外。物理内存不足按 `resource_blocked` 处理。
6. 所有单元通过后，在同一工作者内完成全片汇总、时间轴/边界/重复检查、人物/指代/术语一致性和该阶段最终交付。阶段 1/2 的 START_UNIT 为空也必须继续这些剩余工作。阶段 3 必须完成全部审查轮次和全片回归。
7. 运行当前阶段 `pipeline_ctl.py gate`，修复可修复缺失直到通过；通过后才能返回 `phase_complete`。由父会话复验并决定是否进入下一阶段。

## 返回契约

返回极简 JSON，不复制整个工作记录：

```json
{
  "phase": 1,
  "scope": "remaining_phase",
  "exit_reason": "phase_complete",
  "phase_gate": "PASS",
  "completed_units": ["S0001", "S0002"],
  "resume_checkpoint": null,
  "context_pressure": {"observed": false, "reason": "本阶段已完成，无需上下文交接"},
  "evidence_paths": [],
  "blockers": [],
  "next_exact_action": "父会话重跑阶段 Gate"
}
```

`exit_reason` 允许 `phase_complete/context_handoff/blocked/resource_blocked/paused`。示例的单元列表与路径必须替换为实际数据，不能把示例当作完成证据。交接返回须给出 handoff 路径、最后可信检查点、具体下一步和 OpenCode context_budget.py 输出（session_id、message_id、model、effective_tokens、context_window、usage_fraction、checked_at、decision）；正常 context_handoff 需要 handoff_allowed=true。提供方超限例外附真实 error_evidence_path，由父会话核验。阶段未完整通过时 `phase_gate` 写 `FAIL` 或 `NOT_RUN`，不能用单元 Gate 的 PASS 冒充阶段 PASS。保存文件必须真实可读，完成前重新读取核对。不得为了凑成“每阶段一个工作者”降低质量或超出安全上下文。

OpenCode 2.x：用量检查参见 references/OPENCODE.md。不会仅因本轮需要返回或被系统压缩就把本阶段判定为完成；若父会话以相同 sessionID 继续，仍在原阶段工作。不得自行调用 subagent。

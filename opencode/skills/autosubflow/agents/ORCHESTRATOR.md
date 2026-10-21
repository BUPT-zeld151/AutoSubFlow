# OpenCode 2.x 主会话调度契约

默认每阶段一个独立子会话，连续完成整个阶段；每次仅一个活动工作者。先阅读 references/OPENCODE.md。父会话不执行媒体分析，不加载三份阶段 Prompt。

1. 初始化/复用 manifest，实际运行 pipeline_ctl.py status，读取 next_phase/next_unit；next_unit 是检查点，任务范围必须是该阶段全部剩余工作。
2. 用 OpenCode 原生 subagent：agent="autosubflow-worker"、description、prompt、background=false；参数以当前工具 schema 为准。本机2.0.30不使用 DSH run_in_background 或旧版 task/subagent_type/task_id。不指定未经用户要求的模型，不额外设置步数上限。
3. 新阶段省略 sessionID，获得独立上下文。prompt 完整提供绝对 SKILL_ROOT/VIDEO_WORKSPACE、PHASE、SCOPE=remaining_phase、START_UNIT、对应完整 v4 Prompt、WORKER.md、CONTEXT_CONTINUITY.md、manifest、真实错误和交接路径。六分钟只用于落盘/验收，不能按段换人。要求阶段内继续直到完整阶段 Gate PASS。
4. 默认前台等待，保存返回的 sessionID。若平台实际转后台，按平台通知等待完成，不能并行启动另一工作者，不主动重复其工作。
5. phase_complete：主会话实际重跑该阶段 Gate 和 status；失败则以原 sessionID 交还错误继续修复，通过后新建下一阶段独立子会话。第三阶段必须先中文盲审。
6. context_handoff：用 context_budget.py --workspace <workspace> --session-id <该child的sessionID> 独立复核用量，默认 >=90% 才批准新上下文；供应商明确上下文长度拒绝须核实真实错误证据。低占用/未知用量、工作很久、还有很多单元都不足以换人。过早返回记录 premature_context_handoff，并优先向同一 sessionID 继续派发剩余当前阶段任务，保留原上下文；只有无法恢复原会话才记录异常并基于磁盘恢复。
7. blocked/resource_blocked/paused 和外部中断分别处理；不能借换人绕过权限/工具/物理内存问题。先确认旧工作者及其重型进程状态，禁止重叠执行。连续两次恢复均无实质进展时停止并报告。

阶段任务核心：

> 你负责当前 PHASE 的全部剩余工作，START_UNIT只是起点。在同一会话中逐单元完整审核、落盘、验收并继续；之后完成全片一致性、终稿和handoff，阶段Gate通过才返回phase_complete。完整读取WORKER、CONTEXT_CONTINUITY和当前一份v4 Prompt。正常上下文交接须实测达到实际模型窗口90%；未知用量、处理了几个单元或剩余工作很多都不能作为耗尽依据。不递归派发，不跨阶段。质量与证据标准保持完整。

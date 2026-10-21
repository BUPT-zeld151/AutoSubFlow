# autosubflow 自动调度版（DeepSeek Harness）

## 安装与使用

Skill 名为 `autosubflow`。将完整目录放入 Harness 实际扫描的 Skills 目录；已有同名 Skill 时先备份并更新该目录，避免安装多个同名副本。不要只复制 SKILL.md，阶段规范与脚本都需要保留。

在视频工作目录中使用具有 skill、subagent、Shell/文件及必要影音能力的预设，发送 [examples/START_AUTO.md](examples/START_AUTO.md) 的指令即可。只执行某阶段时使用对应的 START_STAGE_01/02/03 示例，仍由主会话自动调度。

## 运行方式

- 唯一主会话调度阶段 1 日语识别、阶段 2 中文翻译、阶段 3 独立终审，无需手动开三个会话。
- **每阶段默认一个独立子智能体，连续完成该阶段全部剩余工作。** 六分钟单元仅为处理、进度和质量检查点，完成后仍由同一工作者继续。
- 正常上下文交接须只读实测达到窗口90%；缺少用量或剩余工作多不构成耗尽。外部中断恢复分别记录；保存人物/场景、译法约定、未完问答、证据位置和精确进度。不得固定每单元更换新子智能体。
- 所有单元通过后仍需全片汇总、一致性检查和 handoff；主会话重跑阶段 Gate，通过才进入下一阶段。阶段 3 使用独立上下文，先中文盲审。
- 默认一次性前台 subagent 足以连续执行整个阶段。one-shot 不支持 send_message；需要实时消息须另行配置 Harness 的 continuable 和控制工具，不能仅把 run_in_background 改为 true 就声称可通信。

详见 [SKILL.md](SKILL.md)、[主调度契约](agents/ORCHESTRATOR.md)、[工作者契约](agents/WORKER.md) 和 [语境连续性](references/CONTEXT_CONTINUITY.md)。

## 状态与检查

```bash
python3 '<skill>/scripts/pipeline_ctl.py' init --workspace '<project>'
python3 '<skill>/scripts/pipeline_ctl.py' status --workspace '<project>'
python3 '<skill>/scripts/pipeline_ctl.py' gate --workspace '<project>' --phase 1
python3 '<skill>/scripts/pipeline_ctl.py' gate --workspace '<project>' --phase 2
python3 '<skill>/scripts/pipeline_ctl.py' gate --workspace '<project>' --phase 3
```

`scripts/context_budget.py --dsh-home <actual-home> --workspace <project>` 只读核验上下文，正常交接须达到90%，父会话验收时另传确切 `--session-id`。该检查不停止/启动任务，无法让已返回的 one-shot 重新活过来。

`next_unit` 是下一检查点，不是新建子智能体信号。脚本不感知活跃子智能体，主会话跟踪唯一运行任务。manifest 与原有项目目录/文件兼容，已有可靠成果继续复用。

Gate 检查产物与结构化证据，不能证明音频、视觉和语义判断正确；全部阶段仍遵守原 v4 质量规范。资源故障/权限缺失须如实停止，换人不能解决物理内存不足。宿主关闭不保证继续运行，可从磁盘恢复。

## 已有运行迁移

更新文件不会自动重写已运行会话的系统上下文和先前派发的任务。等待当前工作者保存并结束后，让主会话重新读取 SKILL.md、ORCHESTRATOR.md、WORKER.md 和 CONTEXT_CONTINUITY.md，并明确撤销旧的“仅做一个单元”任务范围；下一次派发必须负责整个阶段剩余工作。不要启动第二个并行工作者。

三份阶段 v4 Prompt 的质量要求保持有效。验证范围包括 Skill 格式、调度指令一致性及状态脚本回归；尚不能据此宣称已在真实影音任务上跑通新版完整三阶段。

# Studio Kimi 浏览器流程验收

> 后续修复：[草稿立即重载问题已修复并经 Kimi 复测通过](STUDIO-DRAFT-IMMEDIATE-SAVE-20261013.zh-CN.md)。本文保留当时的失败及范围，保存前立即重载限制不再代表当前代码。

日期：2026-10-13（Asia/Shanghai）。接续[边界修复验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。本轮使用 [kimi-webbridge 技能](/Users/typ/.codex/skills/kimi-webbridge/SKILL.md)控制真实浏览器，初始化空白隔离存储并模拟用户操作；Shell 只用于服务管理、回归与只读核对。代码保留在本地，未提交、未部署到正式用户环境。

**受测技术流程通过，结论为 `PASS_WITH_SCOPE_LIMITS`。** 最后完整后端回归 **287/287、零跳过**，前端 **18 个 QA 脚本全部通过**。真实模型制作、精确封存、独立 Godot 验证、GUI、模拟接受、已保存草稿隔离及通信故障恢复通过。人工玩法、视觉及体验验收仍为 `NOT_TESTED`，`userCandidateAccepted=false`。保存完成前立即重载可能丢失未落盘输入，这一边界没有被计为通过。

[机器可读摘要](../evidence/workflow/studio-ui-kimi-20261013/summary.json)、[完整浏览器动作](../evidence/workflow/studio-ui-kimi-20261013/browser-actions.jsonl)与[后端检查点](../evidence/workflow/studio-ui-kimi-20261013/checkpoints.jsonl)保留本轮事实和失败。旧报告及旧证据未覆写。

## 环境与决定来源

四项组件为独立 frontend、backend、AgentRunner、ProjectRunner，实际 HTTP/SSE 通信。Kimi session 为 `studio-ui-acceptance-20261013`，分组「Studio 使用者验收」；未自行关闭分组或重启 daemon。

正常流程使用空白临时存储 `/private/tmp/studio-ui-kimi-normal-mflp3xvk`，frontend 8794、API 8795，`testData=false`、`productionAuthorized=true`。这些设置用于实跑真实批准门，所有批准和接受仍为模拟操作，没有正式用户数据。诊断存储 `/private/tmp/studio-ui-kimi-fgzpygk3` 为 `testData=true`，其四服务已停止，证据保留。

正常项目 `project-928251524e6c48beb610c429022b9e4c` 名称为「Kimi 正常流程模擬驗收」；空白对照 `project-a581de7fdd5c487fb50619aef6548a16` 名称为「Kimi 草稿隔離空白對照」，只创建项目，没有提交模型。受测环境为本机 macOS、`my_proxy` provider、Godot `4.6.3.stable.official.7d41c59c4`。

## 使用者流程与通信结果

| 操作/故障 | 实测结果 |
| --- | --- |
| 初始化和创建项目 | 真实页面从空项目管理页进入讨论页，四服务完成初始化 |
| 两角色设置 | 页面保存 planner/producer `gpt-6-luna / max`、180/240 秒；视图/心跳不覆盖未提交设置 |
| 概念、完整计划审阅、冻结 | 实际 planner 回应；冻结 ACK 后先读取权威阶段，再自动派发制作 |
| 实际制作、UID、封存与验证 | Producer 只追加获准注释；宿主准备两项缺失 UID 后封存；独立验证 PASS |
| 浏览器 GET 中断 | CDP 阻断项目 view GET，SSE/后端继续；后端到 READY_FOR_REVIEW。解除后无重载自动补回候选，无新模型或重复制作 |
| Godot GUI | 实际图形初始化；页重载恢复“停止预览”控制；页面停止后进程组消失，封存源不变 |
| 模拟接受 | 页面“接受并发布”及确认对话框完成；隔离作业 PUBLISHED、发布版本 1、迭代入口开放 |
| 已保存草稿重载 | 等待保存提示后重载，文字、对象反馈与选择恢复；修复后的草稿修订 1 保存并恢复 |
| 跨项目隔离 | 第二项目概念/迭代内容为空，无第一项目反馈；返回第一项目迭代页，文字与反馈完整，零新模型回合 |
| 空闲后端重启 | 修复后同一页面自动重新握手、恢复状态流；存储相同、服务实例改变；事件序号仍 594、发布版本仍 1，无业务重送或新模型回合 |
| 最终状态 | 四服务在线，两 Runner 心跳新鲜；所有受测 attempts 终态，观测到的 native/Godot 进程组均消失，未确认报告 outbox 为 0 |

[最终注册证据](../evidence/workflow/studio-ui-kimi-20261013/fresh-runner-registration-final.json)记录每个 Runner 本次启动的实际探针：planner/producer 各 31 项、verify 26 项、preview 29 项固定检查全部通过。权限不由页面 capability 自行授权。[最终状态](../evidence/workflow/studio-ui-kimi-20261013/final-state.json)另记录真实服务 PID、心跳、终态、队列和源核对。认证/工具隔离、受控 CA runtime 和 UID 来源的完整实现与对抗范围继续见[前轮报告](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。

## 精确源与模型回合

成功作业 `job-4b1ecd4918fe42c88271210ca12f75b9`；输入 Git 版本 `ddba353188bd6c1f9937033a8512e797f05e1c63`；封存源 `dfba0a0086a89d3ef70634884146c73b5be31966`。原 `scripts/main.gd` 的 150 bytes 完整保留，只追加 28 bytes：`# Kimi UI acceptance first.` 加换行。Producer 修改只有该脚本；可信准备另外生成 `scripts/main.gd.uid`、`studio/runtime.gd.uid`。验证、GUI、模拟发布和最后核对同源、Git clean、原始字节匹配。[源核对](../evidence/workflow/studio-ui-kimi-20261013/exact-source-verification.json)、[GUI 完成记录](../evidence/workflow/studio-ui-kimi-20261013/preview-completion.json)分别保存技术事实。没有独立 SHA/MD5/checksum 构建检查。

本轮 **8 个得到 turn/start 回执的真实 native 回合**：正常存储 4 个 planner、3 个 producer，诊断存储 1 个 planner；失败回合包含在数量内。诊断制作没有启动 native，不计额外回合。[逐回合记录](../evidence/workflow/studio-ui-kimi-20261013/native-turns.json)从持久数据提取 turnId、请求配置、实际 thread 模型/provider 和观测用量。实际 reasoning effort 没有报告；请求 `max` 不等于实际采用 `max`。用量仅为 `native_thread` 快照，未累加为完整计费。

## 修复与最终回归

修复使用现有组件，没有新增调度框架、消息中间件或权限体系。

| 文件 | 本轮修复 |
| --- | --- |
| `frontend/studio/studio.js` | 保留未保存角色设置；恢复 readiness 后隐藏旧启动提示；成功应用 view 后才确认 SSE 游标；失败释放旧 reader；冻结后刷新 allowedActions 再制作；BLOCKED 计划显示原因；修复草稿修订号覆写；SSE 401/403 在同存储内更新握手并只读恢复，存储错配仍拒绝 |
| `backend/studio_protocol.py` | test-data 制作在消费批准/建作业前拒绝；永久准备错误 FAILED；确认停止的 runner 失败保持 FAILED；新版待审阅候选列表只含 READY_FOR_REVIEW，与既有 workbench 一致，发布/拒绝仍留在历史 |
| `backend/general_verification.py` | Git batch 输入改用临时文件，解除 macOS 大 stdin 写入和 stdout 互相堵塞，保留字节/UID 核对 |
| `runners/project.py` | 以真正 protected root 和 active 工程计算 preview 保护范围，避免自身 runtime 祖先被误拒绝，保留其他项目保护 |

| 回归 | 最终结果 |
| --- | --- |
| 后端全套 | **287/287、0 failures、0 errors、0 skipped，170.760 秒**；包含最后 preview 和候选状态修复。[JSON](../evidence/workflow/studio-ui-kimi-20261013/backend-regression-after-candidate-state.json)、[日志](../evidence/workflow/studio-ui-kimi-20261013/backend-regression-after-candidate-state.log) |
| 前端全套 | **18 个 `*qa.cjs` 脚本全部通过，35.269 秒**；包含最后修订号和 SSE 握手修复。18 是脚本数，不是断言数。[JSON](../evidence/workflow/studio-ui-kimi-20261013/frontend-regression-final.json) |
| 浏览器恢复证据 | [草稿隔离](../evidence/workflow/studio-ui-kimi-20261013/draft-browser-isolation.json)、[后端重启](../evidence/workflow/studio-ui-kimi-20261013/idle-backend-restart-recovery.json)、[最终页面](../evidence/workflow/studio-ui-kimi-20261013/12-final-connected-iteration.png) |

此前 286 项全套在 preview 最后一行修复前通过，随后 35 项 Runner/runtime 定向通过；中间前端复跑也保留。它们与最终全套重叠，不相加。回归包含 fixture、mock 和真实子进程，不能把每个用例都称为真实浏览器或模型测试。

## 失败保留与未保证范围

- 初始 test-data 制作卡 PREPARING，已从页面取消，无 native identity/候选；修复后的消费前明确拒绝由回归确认。
- 首次真实制作的 Git batch 堵塞，保留[现场](../evidence/workflow/studio-ui-kimi-20261013/normal-first-production-pipe-failure.json)。只终止自有卡住 Git 子进程，未删除失败作业。
- 后续实际 runtime 复制与一次回归遇 ENOSPC，未计 PASS。只清理以前自有验收的可重建 `runtime/Godot.app` 副本，保留工程、日志、CA、profiles 与证据；[清理记录](../evidence/workflow/studio-ui-kimi-20261013/runtime-copy-cleanup.json)。最终约 7.9 GB 可用。
- 中间 285 项回归有一项 fake UID verifier 失败，定向复跑及最终全套通过。首轮缺详细 traceback，根因未确证，不编造磁盘归因。[首次失败](../evidence/workflow/studio-ui-kimi-20261013/backend-regression-first-failure.json)、[中断记录](../evidence/workflow/studio-ui-kimi-20261013/interrupted-backend-regression.json)、[ENOSPC 日志](../evidence/workflow/studio-ui-kimi-20261013/backend-regression-disk-exhausted.log)保留。
- 初次 preview 自身 runtime 祖先误拒绝的[日志](../evidence/workflow/studio-ui-kimi-20261013/preview-first-denied-runtime.log)、发布候选仍列待审阅的[截图](../evidence/workflow/studio-ui-kimi-20261013/10-final-iteration-draft.png)、旧 token 不能恢复的浏览器观测都保留；修复后分别实测通过。
- **草稿持久化边界：**250 ms debounce/IndexedDB 完成前立即重载曾丢失最后输入；保存提示后的重载、跨项目恢复通过。未保证浏览器崩溃或未落盘输入的恢复。
- 本轮覆盖本机、单浏览器、两个隔离项目和受测故障；没有长期 soak、多用户并发压力或全部 provider/模型/effort/平台组合验收。Godot 初始化与技术冒烟不能证明玩法、平衡和视觉质量。

四服务保留空闲，可查看[隔离验收工作台](http://127.0.0.1:8794/studio/)；模型与 Godot 预览已停止。页面“用户已接受”属于该隔离存储的模拟按钮决定，正式用户候选仍未接受。

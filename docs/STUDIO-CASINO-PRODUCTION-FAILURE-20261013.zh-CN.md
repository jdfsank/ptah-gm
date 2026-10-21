# casino 制作失败排查（2026-10-13）

已将 `casino` 定时追踪置为 `PAUSED`，保留原有频率、项目和提示词。

## 结论

本次失败发生在原生制作回合，尚未进入源封存及 Godot 独立验证。具体模型或上游错误内容没有落盘，不能确定是请求失败、流中断、上下文限制或其他原因。已确认的系统缺陷是失败诊断丢失；现有 `native_error` 只是通用分类。

## 实际证据

- 项目：`project-3fb9a45e958d457bbf425f7db2e05616`。
- 作业：`job-361aa1860ac840179aeea23c1768ebfb`。
- 执行：`attempt-f2f10c676649448586e67fb358cbdf14`，后端状态 `FAILED`。
- 北京时间 14:01:35 启动原生进程；14:10:52 最后一次错误与 `turn.completed` 事件，持续约 557 秒。
- 共 8 次 `error` 通知，30 次静态工具调用；最后一次工具调用为 14:08:05，之后有 6 次错误通知。
- 最终上报 `stopped=true`、`stopReason=native_error`、`diagnosticRef=native-terminal-not-completed`，后端已 ACK。
- 没有候选，发布版本仍为 0。原工作目录保留部分场景、武器资源和脚本，未验收；例如方案要求的 `scripts/round_controller.gd` 尚未生成。
- 没有取消请求；约 9 分钟的运行时长低于配置的 30 分钟上限。记录中没有软 token 上限。240404 是原生线程累计观测值，不能用作上下文溢出的证明。

## 为什么无法恢复具体错误

`backend/codex_driver.py` 会在结果中保存 `nativeErrors`、`nativeTurnError` 和 stderr，`runners/agent_worker.py` 也把完整结果传回父进程。但 `runners/agent.py` 只在内存中保留结果：确认停止后先删除 `.runner-tmp`，非 completed 结果最终只上报通用失败标记。该执行的原生临时目录现已不存在。

服务日志里的图片 JSON 截断 traceback 发生在 12:56，本次执行从 14:01 开始，不能用旧故障解释此次失败。系统日志中的偏好设置、DNS 和证书沙箱消息也不能证明具体终止原因；未找到当日 Codex 崩溃报告。

受信转发器使用 `timeout=15`，并把请求异常压缩为通用 502 或关闭响应流。这是后续定位应保留的诊断点，现有证据不足以断言本次由它触发。

## 下一步

先在清理临时目录之前持久化有界、脱敏的终止状态、原生错误摘要和转发器 HTTP 状态/异常类别，再通过新的执行重试。保持现有认证与工具隔离；不把认证、上游响应原文或请求内容写入诊断。避免仅延长时限或改模型来掩盖原因。

本轮只暂停追踪并检查记录；没有重派模型、修改执行设置、取消任务、启动 Godot 或接受候选。

证据：`evidence/workflow/studio-casino-project-tracking-20261013/production-failure-investigation.json`。

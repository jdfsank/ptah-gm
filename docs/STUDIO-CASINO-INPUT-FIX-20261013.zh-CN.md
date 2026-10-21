# Casino 项目策划输入故障修复

日期：2026-10-13。项目 `project-3fb9a45e958d457bbf425f7db2e05616`。

原始参考图为 3,084,340 字节，符合单图 5 MiB 限制。但 Runner 的 HTTP 客户端只读取 2,000,001 字节，图片编码后的输入 JSON 被截断，解析失败令 Agent 退出。原执行没有创建工作目录或启动 worker/native，租约到期后却一直保留为 `PLANNING_UNCERTAIN`。

修复让执行输入端点按既有 16 张、每张 5 MiB 的图片限额及 base64 大小完整读取；其他控制响应仍保持 2 MB 上限。超限先明确拒绝，再进行严格 JSON 解析。输入准备或 worker 启动失败会持久化失败报告，服务可以继续处理其他工作。

新增的 `launchPrevented` 是受信 Agent 对实际启动前失败的观察，只适用于已确认停止的 Agent 失败报告。已有 native 身份时拒绝认领为未启动；没有这项观察的过期失败仍保留未知占用。原代次不可再次启动，重新策划必须提交新命令。它不会改变角色隔离、认证归属或制作批准门。

本次恢复原失败记录前，核对了旧 Agent 已退出、原异常发生在读取输入时、工作目录不存在、worker/native 身份及启动报告均不存在。随后经原 Runner 的持久化报告与后端 ACK 完成核账，没有直接改数据库状态或重新派发模型。

验证结果：

- 相关后端测试 **85/85 通过，零跳过**；覆盖真实 HTTP 大图、容量拒绝、严格 JSON、启动失败、过期报告、身份冲突、生命周期及 schema 一致性。
- Kimi WebBridge 页面显示原始输入、“已确认停止”与“使用原输入重试策划”按钮；没有点击重试。
- 四个服务正常，Agent/Project 心跳新鲜；原输入与一张参考图保留，attempt/job 数量不变，新增模型回合为 0。
- Git 差异空白、Python 语法与 JSON 检查通过；没有独立 hash 构建检查，没有游戏制作或玩法验收。

项目当前保留为 `FAILED`，并标记可重试。刷新[项目工作台](http://127.0.0.1:8794/studio/?project=project-3fb9a45e958d457bbf425f7db2e05616)后可使用原输入重试策划。

[机器摘要](../evidence/workflow/studio-casino-input-fix-20261013/summary.json)、[恢复依据](../evidence/workflow/studio-casino-input-fix-20261013/recovery-proof.json)、[浏览器记录](../evidence/workflow/studio-casino-input-fix-20261013/browser-actions.jsonl)、[页面截图](../evidence/workflow/studio-casino-input-fix-20261013/retry-ready.png)。旧浏览器会话返回失效 tab ID，随后本次任务使用独立 Kimi 会话成功复测；没有重启浏览器 daemon。

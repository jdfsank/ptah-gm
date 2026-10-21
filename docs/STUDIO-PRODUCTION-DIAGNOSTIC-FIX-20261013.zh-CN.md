# 工作台制作阶段检查与修复

日期：2026-10-13（Asia/Shanghai）。模式：self_check 单轮快速检查，聚焦策划到制作的调用链与制作失败路径。

## 检查结论

策划、冻结与 `production.start` 的前后端接口一致。已有 casino 记录证明制作任务启动过，并向隔离工程写入了资源、场景和脚本；它在原生模型回合内失败，未进入独立 Godot 验证，未产生可接受候选。

旧记录仅保留 `native_error / native-terminal-not-completed`，具体模型或供应方错误已经丢失。不能据此断言上下文溢出、写权限不足或超时就是该次失败的根因。240404 是线程累计 token 观测值，不能证明上下文超限。

另有历史验收记录出现 Godot runtime 复制时 `No space left on device`；这是独立的宿主准备失败，不应混同为模型制作失败。

## 已修复问题

| 问题 | 修改 | 验证 |
| --- | --- | --- |
| 原生错误摘要随临时目录清理而丢失 | AgentRunner 在清理前事务写入本地 journal，失败/停止回执绑定 `local:native-diagnostics/<attemptId>` | 真实 Python 子进程失败、输出超限、超时、未确认停止与 journal 重开回归 |
| worker 异常时没有完整终态结果，bridge 诊断仍会丢失 | 独立 `diagnostic` 事件在 teardown 前发送，覆盖 driver、图片准备、工具准备及清理异常；父 Runner 合并该事件 | 异常路径测试与无终态结果的子进程回归 |
| 上游请求固定使用 15 秒 socket 超时，忽略供应方配置 | 遵循正整数 `stream_idle_timeout_ms`；未配置时为 300 秒；整体运行预算继续由 Runner 控制 | mock HTTPS 上游与真实本地 HTTP transport 测试，覆盖响应前/流中 timeout、HTTP 429 |
| 失败后公开 job 缺少 `productionFailure`，工作台只显示通用失败 | produce 回执生成结构化停止诊断，页面显示诊断引用；未确认停止要求先对账，确认停止建议手动新策划 | 作业/执行归属与公开视图测试、前端诊断和恢复门控测试 |

诊断只保存固定错误分类、HTTP 状态、重试标记、时长与计数等有界元数据。不会保存模型请求、响应正文、原始错误体、stderr 内容、上游 URL、认证或请求头。错误分类来自有限标签和消息匹配，未知原因保留 `unknown`；它不等于恢复旧错误原文。

验证任务的失败不会被标成原生制作失败。失败或超时结果不会封存为完成候选；停止未确认时保留占用与临时目录。没有自动重试、复用已消费批准或发布部分工程。

## 变更文件

- `runners/native_adapter.py`：配置超时与线程安全、有界的 bridge 诊断。
- `runners/native_diagnostics.py`：允许字段与错误分类，禁止任意原文落盘。
- `runners/agent_worker.py`：正常及异常路径的诊断事件。
- `runners/agent.py`：先持久化后清理，报告引用与异常事件合并。
- `backend/studio_protocol.py`、`frontend/studio/studio.js`：制作停止诊断的传递和展示。
- 对应后端与前端回归测试。

## 验证结果与适用范围

后端相关测试 122/122 通过，零失败、零跳过。覆盖 Codex driver、Agent 生命周期、Runner 输入与设置失败、角色探针、静态工具隔离、协议以及新增诊断测试。

前端 `studio-protocol-qa.cjs`、`studio-planner-regression-qa.cjs`、`studio-qa.cjs`、`studio-objects-qa.cjs` 四组通过；JavaScript 与改动 Python 文件语法检查通过。生命周期测试证据输出到临时目录，未覆盖既有验收证据。

未执行独立 hash/checksum 检查或旧包校验构建入口。此次未改 Godot 游戏源码，未启动真实模型制作或 Godot 验证，也未重启工作台服务。测试证明修复后的失败处理与超时配置行为；尚不能宣称当前用户游戏已经完成制作。

## 下次执行如何核对

代码在使用此 checkout 的服务下次启动后生效。重新执行仍使用正常策划、审阅与批准流程；旧执行的详细错误不能补回。

新的制作失败/停止卡片会给出诊断引用。操作者可在原状态目录的 `runners/agent/journal.sqlite3` 内，按该引用只读查询 `metadata` 表：

```sql
SELECT value FROM metadata WHERE key = 'local:native-diagnostics/<attemptId>';
```

该记录可区分已观测的 bridge timeout、HTTP 错误、原生错误分类与停止情况。未知原因仍应根据新执行诊断定位。默认 `.workbench` 服务注册表在本次检查时为空，没有据此定位到历史 casino 使用的 Studio v1 状态目录；本轮没有变更任何历史项目、批准或执行状态。

历史依据：[casino 制作失败排查](STUDIO-CASINO-PRODUCTION-FAILURE-20261013.zh-CN.md)。

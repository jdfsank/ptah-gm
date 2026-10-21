# Studio v1 共享协议

这些 JSON Schema 是前端、后端和两个 Runner 的共同边界，采用 JSON Schema Draft 2020-12。后端的关系、审批、Git 版本和占用校验在 schema 校验之后执行。用户内容中的 actor、路径、命令或 PASS 文本不形成授权。

| 契约 | 作用 |
| --- | --- |
| `message.v1.schema.json` | 命令、回执、项目事件、执行报告、ACK 与统一错误 |
| `project-view.v1.schema.json` | 一致公开项目视图与 `throughSequence` |
| `execution.v1.schema.json` | 独立执行请求、固定 profile、输入引用和角色范围 |
| `change-request.v1.schema.json` | 有稳定反馈编号的对象迭代请求 |
| `planner-result.v1.schema.json` | 严格策划结果及逐条反馈决定 |

已有 `studio.objects.v1` 对象文档保持原格式。旧项目继续使用旧写接口；`protocolVersion:1` 项目使用持久命令。双方不兼容时保留读取和草稿，不能降级绕过批准。

公开只读下载入口为 `/api/v1/contracts/<以上 schema 文件名>`。其他文件或路径返回 404。固定可运行示例保存在 `backend/tests/test_studio_schema_parity.py`、`backend/tests/test_studio_protocol.py` 和 `frontend/tests/studio-protocol-qa.cjs`，测试验证 schema 与实际后端输出一致。

命令由调用方保存 `commandId` 和原始内容。同 ID、同内容返回原回执；换内容明确冲突。执行报告以 `reportId` 去重，原 ACK 可在租约变化后查询。`storeId` 标识数据空间，普通重启沿用，旧备份恢复建立新空间。不得重投到另一空间。

线程配置报告保留原生模型、供应方和启动默认 effort；回合启动只报告原生 `turnId/status`。当前原生 API 未提供回合最终 profile 时，`actualProfile` 保持 null。累计用量去重，缺失保持未知；它不是硬预算或完整计费。

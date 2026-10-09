# GodotMaker non-pk Git 身份迁移说明

`sources/GodotMaker-non-pk/tools/review_support.py` 的历史 API 名称 `digest_bytes`、`digest_file`、`spec_digest`、`source_digest` 和 `test_digest` 仍为兼容调用方保留；这些函数现在返回 `git:blob:<object-id>`，对象身份由 Git 的临时索引生成。它们不再调用 Python `hashlib`。

当前检查报告以 `godot_git_identity` 表示 Godot 可执行文件身份，并使用 `manifest.git` 与 `evaluation-binding.git` 保存本地 Git blob 身份。新报告不写入或比较 `.sha256` 文件。Git 身份用于本机协作工作流中的内容变化检测，不代表同用户进程之间的安全隔离。

历史 run 目录可能仍含有 `.sha256` 文件或旧字段。当前工具不会把这些历史值解释为 Git 身份，也不会自动把旧批准绑定迁移为新的用户批准。需要恢复历史工作区时，应按原工具版本审阅归档；新的通用工作区应通过当前工作台重新生成并审阅冻结规格。

规格身份使用 `spec_git_ref(spec, project)`，对 GM 正规化的完整规范文本生成 Git blob 身份。通用工作台通过固定的 `sources/GodotMaker-non-pk/tools` 审批消费者校验该身份；浏览器不能指定 GM 工具路径。测试模式注册只用于诊断，不能通过生产确认门。

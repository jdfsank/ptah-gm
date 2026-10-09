# 交接包验证

2026-10-08 打包检查：

- 前端 HEAD fe1fc88ee4fe4a8d5ce32493b76e8d4c20dd2af1，原工作树干净；git archive 导出源码。
- Git bundle verify 通过，为完整可达历史，包含 main、checkpoint-v5-before-comments 和 HEAD。
- 两份源 ZIP CRC 完整、无重复成员/不安全相对路径/符号链接；逐文件 SHA-256 清单随包交付。
- 用 tools/unpack-sources.py 实际解包成功，并验证全部源文件 SHA；解出的临时 sources 未重复装入交付 ZIP。
- 两个真实源系统均存在；游戏 project.godot、AGENTS.md、PLAN.md、.agents、脚本、资源和测试实际保留。
- 对照前端 source-lock 69 文件，67 一致，2 不一致；见 SOURCE-BASELINE-DIFFERENCES.json。未修改原源包或 lock，已明确真实提交 BLOCKED 前置审阅。
- 真实 workbench-targets.json 在原游戏包中不存在，必须本地审阅建立。
- Python 3.12.14 下 bridge --help 可用；已带 dist 的 demo server 在临时端口返回 HTTP 200，随后关闭。该检查没有启动 Codex/model/GM/Godot，也不是视觉验收。
- 依赖完整测试沿用 v6 已保存的真实测试输出；此次只打包，没有把历史回归冒充新一次执行。
- 排除依赖安装物、虚拟环境、缓存、凭据和私人助手资料；项目自带 AGENTS、MEMORY、技能和运行记录为用户工程资料，保留其原语义。
- 旧云路径仅在历史源码/报告中保留，首页要求转换为已核实本机路径；参考 PNG 已独立补入 reference-inputs。

包文件哈希验证只能证明字节完整，不能证明功能验收或新系统兼容。最终独立审查结论另见 PACKAGE-AUDIT.zh-CN.md。

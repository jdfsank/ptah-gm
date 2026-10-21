# Godot MCP 插件

## 制作标准路径（2026-10-20）

**创建或载入 Godot 工程 → 内置插件完整且启用 → 隔离普通编辑器启动 → MCP 初始化、工具和精确工程身份核对 → 确认编辑器停止 → 启动制作。**

这是首次制作、候选返修和对象/参数迭代的共同前置步骤。Studio 的项目业务记录仍在“创建项目”时建立，实际 Godot 工程在批准后的输入准备阶段创建或载入。`AgentRunner` 在启动制作模型前强制检查；保留的通用/收集循环本地入口、`gm-scaffold`、`project-scaffold`、`gm-build` 和 `gm-fixgap` 使用相同检查模块。策划不启动编辑器，用户的确认与候选接受步骤保留。

新建工程或其他脚手架的标准命令（由受信操作员运行）：

```sh
python3 "<repository-root>/tools/godot_project_ready.py" "<absolute-project-path>" --install \
  --evidence-dir "<absolute-evidence-root>/mcp-<unique-batch-id>"
```

已有批准工程省略 `--install`，避免修改冻结输入。每轮使用一个全新的外部证据目录；可用 `--godot` 选择引擎、`--timeout` 设置大于 0 且不超过 120 秒的连接等待期限。默认等待 45 秒，程序启动和隔离准备另计。安装器仍可独立用于诊断，但它单独成功不再代表制作前置检查通过。

检查模块先只读核对 70 个 canonical 插件文件及启用项，再逐字节复制工程源文件。临时副本排除 Git、导入缓存、GM 运行记录和 Runner 临时目录；仅副本的工程名/用户数据位置改为本次唯一名称。普通编辑器在私有 HOME、设置、缓存、引擎副本和沙箱中运行，只允许本次 loopback 监听端口。原始工程不提供给编辑器，也不把副本的编辑器格式调整、UID 或缓存写回。既有独立验证沙箱的禁止联网规则不变。

当前副本限制为 256 MiB、30000 个普通文件；编辑器日志限制为 2 MiB，持续输出会被有界读取，超限阻止派发。报告保存失败也不得放行，错误继续携带真实停止状态。

`readiness.json` 记录初始化、工具数、源工程/隔离工程路径、精确路径匹配、源文件保持、编辑器进程组和停止结果。必须 `status=PASS`、`projectIdentityMatches=true`、`sourceUnchanged=true`、`editorStopped=true` 才放行。Runner 证据位于 journal 同级 `editor-mcp/<attemptId>/`，本地保留流程位于作业目录 `editor-mcp/`。报告和临时端点不交给托管制作模型；模型侧继续禁用直接 MCP 与 Godot 执行。检查结束即关闭自己的编辑器，随后才允许制作写入。

缺失/冲突/禁用插件、连接超时、取消或工程身份不符都会阻止制作 session。停止未确认则标记不确定并保留占用；报告留下原进程组供受信操作员核实，不能把未知状态写成“已停止”。不抢占固定 3000 端口，不连接/结束其他编辑器，不修改全局 MCP 设置。仅插件文件存在、启用标记、恢复模式导入或普通游戏运行都不足以证明就绪。这个检查证明编辑器通道可用，玩法、视觉、独立验证与用户验收继续单独进行。

## 插件来源与安装器

项目内的 `addons/godot_mcp/` 收纳了从本机项目
`/Users/typ/Desktop/godot_project/engine_project/gm-test/addons/godot_mcp/`
复制的插件。`plugin.cfg` 标注名称 **Godot MCP Server**、作者 **LIDAXIAN**、版本 **1.1.0**；
来源项目报告记录了 74 个工具定义。插件默认在编辑器启动时运行，并监听 `127.0.0.1:3000/mcp`。

两个 Godot 项目模板都包含这份插件，并在 `project.godot` 中默认启用它。因此从模板新建的项目会自动带上插件。

GodotMaker 的 `/gm-scaffold` 和直接运行 `project-scaffold` 在生成工程文件后调用 `tools/godot_project_ready.py --install`，从同一 canonical bundle 安装并启用插件，然后进行上述就绪检查。技能指令按其检出源文件位置定位仓库根目录，并传入新工程绝对路径，不依赖当前工作目录。`@coding-solo/godot-mcp` 是可选的运行时调试服务，不能替代这份项目内编辑器插件。

把插件安装到其他项目，运行：

```sh
python3 "<repository-root>/tools/godot_mcp_install.py" "<absolute-project-path>"
```

目标目录可以已存在，也可以是新目录。对新目录，工具会创建最小 `project.godot`；对已有项目，它会保留现有设置和其他 `editor_plugins` 项，并把 Godot MCP 加入启用列表。当前支持 Godot 常见的单行 `PackedStringArray(...)` 启用列表；无法安全解析的其他语法会在写入前拒绝。重复运行时，文件内容不变。若目标已有不同版本的 `addons/godot_mcp/`，或用户提供的项目路径或安装路径包含符号链接，工具会拒绝安装。macOS root-owned `/tmp` 和 `/var` 系统别名会先规范化到 `/private/tmp` 和 `/private/var`。

安装工具只写入指定项目，不修改 Codex 或其他客户端的全局配置。Godot MCP 插件面板会显示连接端点和客户端配置命令；客户端是否连接由用户在目标环境中决定。

这是供可信操作员使用的编辑器控制通道，不会向托管的规划/生产 Agent 开放 Godot 执行、后端数据或提供方认证。场景层级和节点属性工具检查或修改的是编辑器当前打开的场景；它们不能代表正在运行的游戏进程的 Remote Inspector 状态。一般项目验证仍把 `addons/` 排除在生产者写入范围之外，独立验证与角色能力门保持原样。

这份代码来自上述本机项目副本；仓库没有把它标记为经过官方上游校验。插件目录中未发现 `LICENSE` 文件，因此没有在仓库中补写或推定许可证。

实际验收：安装器回归 **7/7**（包含在后端完整 **275/275** 中）；[原 gm-test 控制](../evidence/workflow/studio-acceptance-gmtest-mcp-20261013.json)和[默认新工程控制](../evidence/workflow/studio-acceptance-default-mcp-20261013.json)均通过 initialize、74 tools 和精确项目身份核对，模板主场景通过 play_main/get_status/stop。新目录安装与重复安装通过，两个模板与 canonical bundle 逐文件字节一致。GodotMaker scaffold 调用路径完成静态检查，未运行完整含其他依赖的 scaffold。测试编辑器及游戏已停止，端点已关闭。

默认地址由每个项目的编辑器插件提供；同一端口一次控制一个已核对身份的编辑器。此次直接使用插件自身 HTTP JSON-RPC MCP，未将它冒充会话中不存在的注册工具。普通编辑器的项目设置元数据/格式调整及缺失 UID 生成已单独记录；严格 Runner 的同源验证见[补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。

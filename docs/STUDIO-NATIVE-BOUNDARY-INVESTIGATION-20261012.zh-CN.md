# Studio 原生 app-server 边界调研（2026-10-12）

## 结论

本机 Codex app-server 协议支持通过 `thread/start` 附加 `dynamicTools`，也允许在请求中传入 `config`、`sandbox`、`ephemeral` 等参数；本机导出的协议 schema 没有提供原生内建工具 allowlist 字段。`dynamicTools` 是额外工具入口，不能据此断定内建工具集合已被限制。设置 `shell_tool=false`、`view_image=false` 与命令行 `--disable` 是可验证的候选开关，但当前证据没有证明它们会关闭文件编辑等所有原生工具。

一次零模型探针成功完成 `initialize` 和 `thread/start`：线程使用 `ephemeral=true`、`sandbox=read-only`、`approvalPolicy=never`，并附带一个惰性 `dynamicTools` 说明。未调用 `turn/start`。响应接受了请求并报告 `readOnly` 与 `networkAccess=false`。这只证明请求被接受；它不证明模型最终看到的工具清单受限，也不证明没有线程或认证状态写入本机。

静态审查 [runners/native_adapter.py](../runners/native_adapter.py) 显示，新边界把 app-server 放入一个 Seatbelt 进程内沙箱，原生进程的工作目录和可读写根指向私有 runtime，并显式拒绝访问真实 `CODEX_HOME` 与 backend 目录。这比单靠 app-server 的 `read-only` 线程参数更接近需要的 OS 边界。不过当前代码仍有以下高优先级风险：可执行文件路径未固定为可信 Codex CLI；原生进程拥有通往任意公网地址的出站网络能力；“ephemeral”与本地凭据扫描尚不能证明认证从未被其他系统服务持久化。请在这些边界修正或取得独立证据前，把角色隔离标记为未验证。

## 协议与本机观察

### Schema 来源

证据文件 [studio-native-schema-20261012.json](../evidence/workflow/studio-native-schema-20261012.json) 是本机 `codex-cli 0.162.0-alpha.17.2` 运行 `codex app-server generate-json-schema --experimental` 导出的完整 v2 app-server 协议 schema。它保留了原始 JSON Schema 结构，便于后续逐项检索。本报告只使用本机导出内容，不把网络文档中不可访问的页面当作证据。

`ThreadStartParams` 包含 `config`（允许任意对象字段）、`cwd`、`dynamicTools`、`ephemeral`、`modelProvider`、`permissions`、`runtimeWorkspaceRoots`、`sandbox` 等字段。schema 中没有原生 builtin tool allowlist、`tool_filter`、`builtinToolConfig` 或工具规格覆盖字段。开放式 `config` 被 schema 接受，也不能单独证明 app-server 对任意传入配置的实际语义。

`DynamicToolSpec` 与 `item/tool/call` 请求提供一条服务端到客户端的动态工具调用通道，包含 thread/turn/call 身份和工具参数；它适合连接到独立的静态 broker。动态工具作为附加能力出现，不能把它解释为替换或清空原生工具集。

schema 还定义了独立 `command/exec` 协议，其 sandbox 参数沿用执行沙箱结构。它没有证明 `apply_patch` 或 `view_image` 一定路由到 exec-server，因此不能用远端 exec-server 替代本机文件编辑和图片工具的隔离证据。

### 工具开关与认证 API

本机 feature 清单显示 `shell_tool` 与 `view_image` 默认启用；本机 CLI 接受 `--disable shell_tool` 和 `--disable view_image`，feature 状态随之关闭。这一观察没有测量模型可见工具清单，也没有覆盖文件修改类内建工具。schema 中的 `ThreadStartParams` 没有原生工具 allowlist。

`account/login/start` 的 `chatgptAuthTokens` 登录变体被 schema 明确标记为 `[UNSTABLE] FOR OPENAI INTERNAL USE ONLY - DO NOT USE`。该变体接收 access token、account ID 和可选 plan type，不含 refresh token；过期时 app-server 可请求客户端通过 `account/chatgptAuthTokens/refresh` 返回新的 access token。此流程不应作为稳定集成接口。当前配置的 provider 是自定义 Responses provider，使用 `requires_openai_auth=false` 与 `experimental_bearer_token`，所以 ChatGPT 登录 token 路径也不代表当前 provider 认证方式。

配置 schema 中 `cli_auth_credentials_store` 允许 `file`、`keyring`、`auto`、`ephemeral` 等选项。字段存在不代表 `ephemeral` 已满足不落盘语义；本轮没有用合成 token 验证配置、Keychain 或数据库的落盘路径。

## 新 Adapter 的只读代码审查

审查目标为 [native_adapter.py](../runners/native_adapter.py)，仅读取，没有修改实现或运行它。以下风险来自静态代码路径，尚未通过合成认证做动态确认。

1. **高：Codex 可执行文件由 `PATH` 选择，随后被完整 allowlist。** `CodexDriver.run()` 使用 `shutil.which("codex")` 选择程序，`ManagedNativeContext.command()` 再把传入路径 `resolve()` 并生成只允许该精确路径执行的规则（`backend/codex_driver.py:239-247`、`runners/native_adapter.py:114-124`）。目前没有代码签名、安装位置或其他可信身份校验。若 `PATH` 中的同名可执行文件不可信，它将成为该沙箱唯一获准执行的程序；它能从 stdio 读取含 provider 认证的 `thread/start` 消息，并受下述宽泛网络规则保护。这会破坏“只有可信 adapter 处理认证”的假设。应把 CLI 解析固定到受信安装来源，并对执行文件身份做适当的本机验证。

2. **高：网络出站不是 provider 域名 allowlist。** `command()` 调用 `strict_sandbox_rules(... allow_internet=True)`，通用规则允许任意 `network-outbound`，只拒绝 TCP 目标主机名 `localhost`。provider URL 检查仅要求 HTTPS，并拒绝精确主机名 `localhost`、`127.0.0.1`、`::1`（`native_adapter.py:53-57, 117-124`；`runners/common.py:172-236`）。因此该沙箱不保证只连接配置的 provider，也未覆盖 loopback 的其他地址、私网地址、别名或 DNS 指向内部网络的主机。若威胁模型要求认证只流向配置 provider，当前策略过宽。

3. **中：线程与凭据存储的“不持久化”声明仍是未经验证的假设。** Adapter 将 `cli_auth_credentials_store="ephemeral"` 写入私有配置和 CLI override，并在 `thread/start` 请求里加入 `ephemeral=true`（`native_adapter.py:98-106, 122-124`；`backend/codex_driver.py:556-563`）。现有证据没有证明这些设置不会触发历史、数据库或系统凭据服务写入。`secrets_on_disk()` 只扫描 `root` 下的普通文件并搜索完整明文 token（`native_adapter.py:142-150`）；它不能证明 Keychain、Mach 服务、root 外位置、加密/编码/拆分后的内容均未保存。通用沙箱还允许所有 `mach-lookup`（`runners/common.py:172` 起），所以需用合成凭据单独验证系统凭据服务和应用自身持久化路径。报告中的扫描结果若为 `false`，只能表述为“runtime 根目录内未发现完整明文凭据”，不能表述为“凭据从未持久化”。

4. **中：Adapter 把完整用户配置载入内存。** `create()` 对 `auth_root/config.toml` 执行完整 `tomllib.loads()`，再选择一个 provider（`native_adapter.py:38-52`）。这样所有 provider 字段及其中其他认证值都会短暂进入 Python 对象图，而不只载入所选 provider。`config_overrides` 与 `secrets` 还在上下文生命周期内保留选定凭据；Python 字符串不能可靠清零。对模型侧的传输仍通过私有 stdio 请求，而非 argv、环境或写出的私有配置，但这不等于 adapter 进程内存已经最小化或擦除。

5. **低：结果脱敏不覆盖对象键。** `redact()` 递归处理字符串值、列表和映射值，但保留映射键不变（`native_adapter.py:152-160`）。如果错误对象或动态数据把完整凭据放在键名中，结果脱敏不会清理它。建议至少在输出边界检查键和值，避免把未经脱敏的对象存入报告。

### 当前边界能说明什么

`agent_worker.py` 通过 `native_context.root` 作为 app-server 的 `cwd`，并将 `config_overrides` 放进受信 adapter 发出的 `thread/start` 请求；项目文件工具通过独立的 `StaticToolBroker` 处理。`native_adapter.command()` 的 deny-default 沙箱只为 runtime 根授权读写，且显式拒绝 `real_auth_root` 与 `backend`。这形成了正确的隔离方向：原生模型进程不应直接得到项目读写目录，而由 adapter 的类型化工具桥接访问项目。

不过 schema 只说明协议字段，不证明 seatbelt 的实际行为；此前的一次 `thread/start` 零模型探针也没有运行新 `native_adapter` 沙箱。因此本报告不声称已验证模型无法读取项目、无法运行原生文件工具，或真实 provider 凭据不会落盘。`shell_tool`、`view_image`、`multi_agent`、`apps` 的 feature/CLI 关闭可作为减面措施，但不能替代 OS 边界和工具清单的实际检查。

## 探针边界与数据处理记录

- 本机零模型探针只有一次：`initialize` 与 `thread/start` 成功；没有 `turn/start`、没有真实模型调用。临时工作目录已清理。
- 探针使用临时只读线程请求，响应报告 `sandbox=readOnly`、`networkAccess=false`。请求成功不代表认证或 thread state 从未持久化，也不代表工具面已被限制。
- 没有读取 `auth.json`，没有调用登录、刷新或 Keychain API，也没有创建 synthetic-token 证据。
- **偏差披露：**先前调研者为识别非敏感 provider 类型，使用 `tomllib` 解析过完整的 `~/.codex/config.toml`。解析对象曾在进程内存中包含 `experimental_bearer_token`；未输出或保存凭据值。此操作超出了严格“不读取真实认证内容”的边界。本报告保留该事实作为审计记录，不重复读取。
- 没有官方文档页面可引用：先前检索因网络访问失败而未获得可核验页面内容。参数与字段结论以本机 schema 为依据。
- 本任务未运行构建、测试或任何 hash/checksum 检查。

## 后续验证建议

应先收紧并固定 Codex CLI 可执行文件来源，以及把原生网络限制在明确的 provider 出口；随后用合成凭据验证从 `thread/start` 到 app-server 运行结束的磁盘、系统凭据服务和日志持久化行为。另需在实际 seatbelt 下分别确认：项目文件读写被 OS 拒绝、被禁用的内建工具确实不进入模型工具面、静态工具 broker 仍只执行类型化且授权的文件操作。所有认证验证继续使用合成值，不读取真实认证。

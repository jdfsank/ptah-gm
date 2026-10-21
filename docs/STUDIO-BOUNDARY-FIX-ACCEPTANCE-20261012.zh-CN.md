# Studio 边界修复与补充验收

> 后续真实浏览器流程及最终回归见[Studio Kimi 浏览器验收](STUDIO-KIMI-UI-ACCEPTANCE-20261013.zh-CN.md)：后端 287/287，前端 18 个 QA 脚本通过。本页保留前轮范围、数字和失败，不以新结果覆写历史。

日期：2026-10-12 至 2026-10-13（Asia/Shanghai）。依据：[最终修改方案](STUDIO-FINAL-MODIFICATION-PLAN.zh-CN.md)第 9 节。改动保存在本地工作区，未提交代码、未接受用户生产候选。

本文接续[初次全功能验收](STUDIO-ACCEPTANCE-20261012.zh-CN.md)，保留其失败结论和原始证据。**受测环境的技术验收通过，人工玩法、视觉及体验验收仍为 `NOT_TESTED`。** 四项角色已通过 fresh 实测；Runner 每次启动重新探测，后端按固定观测、身份及新鲜度派生权限，失败仍禁用。真实业务闭环及重启、崩溃、取消停止核账通过；后端完整回归 **283/283、零跳过**，前端 **19/19**。项目内 MCP 默认安装与实际控制已完成。改动保存在本地，未提交、未接受正式用户候选，也未启动持久生产服务。[综合证据索引](../evidence/workflow/studio-acceptance-summary-20261013.json)区分实测、fixture 和人工决定。

## 1. 两个问题的完整表述

### 1.1 Agent 认证、工具分权与策划执行约束

原实现把 native app-server、工程工具及认证读取放在同一个父沙箱权限域。`readOnly` 只约束一部分写入；它既不禁止执行工程脚本，也不隔离认证读取。历史实际 `command/exec` 探针在 readOnly/workspace-write 配置下读到 `~/.codex` 中的合成 canary，readOnly 还能执行合成工程脚本。该测试没有读取真实凭据，但已足以否定原有角色隔离声明。

要求是让受信适配器使用实际模型认证，同时使 native、动态工具路由宿主及工程工具分别处于受控进程域。工程工具不能读取真实认证、后端数据或其他项目，也不能执行工程；策划仅能静态读取有界材料，制作仅能写批准范围。约束必须由实际文件、网络和进程拒绝证据证明，提示词、模型自报或 capability 字段不能代替执行边界。

本次已实施：

- `ProviderBridge` 只由受信适配器读取认证并向固定 HTTPS provider 注入。native 获得一次性 bridge nonce、私有 HOME/CODEX_HOME/TMP 和精确本机端口，实际凭据不复制到 native 的文件、环境或 argv。当前仅支持 `requires_openai_auth=false` 的无凭据文件自定义 provider；依赖官方 credential file 的认证路径失败关闭。
- native 与 `codex-code-mode-host` 分别在独立初始沙箱启动。路由宿主无项目、认证和后端数据读取及出站权限；native 无工程读取/执行权限，只可连接指定 bridge/host 端口。
- `StaticToolBroker` 将 `list/read` 与制作的获准文本写入分发到独立短生命周期工具进程。工具先应用 sandbox，再操作文件；不提供 shell、网络或工程运行。路径使用 no-follow/openat，拒绝隐藏路径、符号链接、硬链接、越界路径和模型写 UID。
- worker 与静态工具固定从受信宿主模块目录启动，禁用用户 Python site；项目中的 `runners/__init__.py` 不能利用模块导入先执行。
- 原生工具请求须匹配 thread、turn、namespace、arguments 和唯一 callId。未管理的内置工具、重复/错配请求均失败关闭，不能靠更改提示词开放执行工具。
- bridge 转发正文前检查认证值的明文及 JSON 转义形式，并保留有界尾部处理跨网络块匹配；发现反射立即断流。Authorization/Proxy-Authorization 的 Bearer/Basic 传输 token 也单独纳入保护，不能通过省略 scheme 前缀漏过。上游 Content-Type 只允许规范 JSON/SSE 类型，不转发可能反射认证的任意 header。
- 原生停止确认后若 UID 准备、审计或 Git 封存抛错，Runner 保存有界诊断并报告 `failed, stopped=true`；不退出服务、不报告 completed、不生成交付物。组消失期间的 EPERM 保持未知，有界重试后仍须 ESRCH 才确认停止。

实际新证据覆盖两角色的静态读/写、native 访问认证 canary/后台/项目的拒绝、工程执行拒绝、路由宿主和工具子进程的访问拒绝，以及真实 Producer 经桥接器完成制作。反射测试使用合成凭据和 mock 上游；它证明转发前的匹配/拒绝规则，不声称第三方 provider 永不以其他变换反射信息。

**当前边界：**以上证据限定于本机安装的 native、自定义 `my_proxy` provider 和受测配置。不能推导为所有认证方式、模型/图片组合或完整计费覆盖已验收。新启动的受信 Runner 只有 fresh 角色探针通过才获得相应权限；实际重启、崩溃及取消范围见第 2 节。

### 1.2 Godot 完整独立验证与 UID 来源

原版实际导入会访问 macOS 用户编辑器临时目录、帮助缓存和系统信任初始化；严格策略拒绝这些访问，导致 ERROR。导入还新增缺失的 `scripts/main.gd.uid`、`scripts/player.gd.uid`、`studio/runtime.gd.uid`，使封存后验证副本的精确源发生变化。仅把它们称为缓存或忽略所有 UID，都会让旧 PASS 与实际运行源脱离。

要求是建立每次执行私有的编辑器 runtime/cache，并在封存前明确 UID 来源。验证和试玩只能运行同一个封存源版本；只允许声明的 `.godot` 缓存及私有 runtime 派生写入。必须重新检查原版工程导入、主场景和 GUI，不能修改原版 `project.godot` 添加证书 override、放宽用户目录权限或过滤 ERROR 来冒充精确验证通过。

本次已实施：

- 每次 runtime 复制 Godot.app，使用 self-contained marker、私有 HOME/CFFIXED_USER_HOME/TMP/XDG 路径及 app 外侧 editor data。Godot 子进程对复制的 `.app` 也明确拒绝写入，避免工程覆写获准执行的引擎后再执行。
- 受信宿主以 no-follow、所有权/权限、大小及前后元数据检查读取固定 root-owned `/etc/ssl/cert.pem` 公有 CA，抽取完整证书块并验证 base64、DER 与可解析证书数，再写入私有 canonical PEM。系统 bundle 的公开注释不复制到证书块；空、坏或不完整 CA 失败关闭。
- 宿主用固定 CLT clang/SDK 编译受信 `godot_ca_interposer.m`；CA 路径在编译时绑定。Godot 子进程的 `SecTrustCopyAnchorCertificates` 从该非空 CA 副本创建真实证书，坏或空内容返回失败；没有环境变量切换 CA 来源。DYLD 注入只出现在 sandbox 内的 `/usr/bin/env` 启动参数中，不进入父进程环境；私有编辑器设置指向同一 bundle。未修改安装的 Godot.app 或原版项目 TLS 设置。
- 仅声明的 runtime 子目录及 `.godot` 获准派生写入；CA 支持目录、bundle、dylib 和复制 app 显式拒绝写入，file-link 也明确拒绝。真实 CA bundle/dylib 硬链接探针均得到 EPERM；去掉显式 file-link 拒绝的对照也得到 EPERM，确认 default deny 已拒绝该行为，不声称发现旧策略的硬链接漏洞或测试了 `.m` 源码硬链接。
- 缺固定 CLT/SDK、坏 CA 或编译失败会在启动 Godot 前失败。Preview 对这种 pre-Popen 构造失败记录有界 JSON 诊断、`processStarted=false` 和 `failed, stopped=true`，并清理 runtime；不会把启动后的异常包装为已停止。
- UID 准备在隔离副本内使用 `--recovery-mode` 编辑器导入。仅缺失的明确 `.gd.uid` 及对应原子临时文件获准写入；所有原有源逐文件比较原始字节。`@tool`、插件和脚本初始化不能获得 UID 来源权威。
- 宿主核对 UID 内容后复制到制作副本再封存。外侧 `evidence/uid-preparation.json` 绑定原 inputCommit、封存 sourceCommit、实际 engineVersion、sidecar 路径/字节及 `quarantine-godot-editor-recovery-import` 方法。后端交付门和 ProjectRunner 都重验来源；不接受旧非 recovery 方法、伪造/重复路径或 UID、错配 commit、链接文件或源漂移。UID-only 不能算制作修改。
- 独立验证以原 inputCommit 审计制作范围，重新导入已含受信 UID 的封存副本，再用后端自己的 harness 加载、实例化并推进主场景。源比较只排除 `.godot/`，保留引擎错误为失败。

真实恢复模式对抗探针中，`@tool` 的执行 marker 未出现，Godot 生成 UID 与预设 forged UID 不同；私有引擎可执行文件的写入也被拒绝。真实 Producer 链生成两项模板缺失 UID、通过外侧来源绑定、重新导入和源不可变检查。

**最新实测：**含默认 MCP bundle 的原版 `general_2d` 在受控 runtime 中完成 recovery 导入、主场景 game-mode 和 10 秒 GUI，无 CA 或其他非预期引擎错误；75 项原源字节保持不变，缺失 UID 单独列明。真实 Producer 只追加批准的 main.gd 注释；封存前宿主准备 `scripts/main.gd.uid`、`studio/runtime.gd.uid`，后端交付与 ProjectRunner 重验来源、Git 身份和精确变更集。独立验证 PASS、候选创建、同源 GUI 运行及 watchdog 停止通过，验证/试玩/封存源均不漂移。此模板没有 player.gd，早期含 player.gd 的记录属于其他 fixture。

原版 CA ERROR 的旧失败和合成 `res://ca.pem` override 通过记录均保留；当前 PASS 来自正式受控 CA 适配器重验，不是丢弃 ERROR 或替换项目设置。runtime 对抗探针故意发起被拒绝的 IPv4/IPv6 连接，记录预期连接错误；它们与原版模板的无错误运行分别判定。该实现及实测范围限定于本机 macOS/Godot 4.6.3，不推导为任意系统和引擎二进制都通过。

## 2. 本轮证据

2026-10-13 补齐了正式角色注册与真实业务验收，复用现有 Runner、报告日志及核账接口，没有增加调度、远端证明或权限框架：

- Agent 启动使用受控 native initialize/model-list 和实际文件/命令拒绝探针；策划与制作分别运行独立静态工具子进程，31/31 项固定检查均通过，零模型回合。[Agent fresh 注册记录](../evidence/workflow/studio-acceptance-agent-registration-20261013.json)保留认证不落盘与 native/路由宿主停止事实。native 网络没有直接 RPC 探针：IPv4/IPv6 与固定 bridge 证据来自同一网络/文件策略的 Python worker，仅可执行文件例外替换为 Python，记录明确保持 `nativeNetworkDirectRpcObserved=false`。
- ProjectRunner 实際 verify 与 GUI preview 的 26/26、29/29 项检查通过。认证、后台、另一项目、已接受源与封存源读写拒绝，源及 UID 写拒绝，私有缓存写允许，后台/批准域 IPv4/IPv6 活监听均零连接。[Project fresh 注册记录](../evidence/workflow/studio-acceptance-project-registration-20261013.json)使用进程内 API stub；后续业务验收另走真实 HTTP 注册。对抗 fixture 的每角色四条网络拒绝 ERROR 全部保留，并按精确行型、阶段和次数归类；该 fixture 未被冒充为技术 PASS。另一个无对抗行为的 clean fixture 经同一生产 verify PASS、GUI STOPPED 且无 ERROR，源不变、进程停止后才满足 clean 门槛。
- 后端从 `studio.role-probe.v1` 的固定 `checks` 派生 capability，绑定 runnerId/kind、probeId、deny-default 与 300 秒新鲜度；缺项、整数 1、错配或过期均拒绝。`verifiedCapabilities` 或 `PASS` 自报字串不授予权限。失败注册空列表清除旧权。Runner token 认证受信本地适配器，不构成任意远端 bearer 客户端的 attestation。
- 重启后，原停止报告可能仅获 `evidence_only`。共享 LocalJournal 现在核实原 PID 与 PGID 都已消失，再按原 nativeIdentity 调用已有 reconcile；失败保留原报告重试，不重开模型，不把迟到完成推进为候选。真实重启链无需 harness 手动核账。
- 真实 Producer 曾把 native runtime 的唯读提示理解成静态工具也不可写。现已明确已有 `studio_write_file` 在独立私有工具沙箱内实施批准范围，工具拒绝仍具权威；文件、进程与网络策略未放宽。私有原生证据只补有界工具名/成功布尔记录，不含参数或源码正文。


| 检查 | 实际结果与范围 |
| --- | --- |
| 完整后端回归 | **283/283 通过、零跳过**，Python 3.11/jsonschema 实际运行，149.396 秒，包含 fresh 注册、停止核账、认证保护、CA runtime、MCP 及工具调用证据；[最终回归](../evidence/workflow/studio-acceptance-final-role-regression-20261013.json)。46 项 driver/静态工具定向通过。旧 275/259/257 项结果保留，不把定向用例另加到总数 |
| 前端回归 | **19/19 通过**，直接 Node/jsdom；本轮边界补强未改前端，[证据](../evidence/workflow/studio-acceptance-frontend-fixes-20261012.json) |
| 真实角色/静态工具 | 两个真实 gpt-6-luna 回合分别完成策划静态读和制作文本写；native 对认证 canary、后台、工程、其他项目和工程执行均拒绝，native/host 停止确认；[角色记录](../evidence/workflow/studio-acceptance-native-role-boundary-20261012.json)。工具/host 的实际独立沙箱用例包含在最终回归中 |
| Agent 生命周期 | **6/6 实际 Python 子进程场景通过**：输出超限、leader 先退出、原生失败终态、无 identity 保留未知、timeout 归因、封存抛错；[记录](../evidence/workflow/studio-acceptance-agent-lifecycle-20261012.json)。不是六个模型回合 |
| 真实离线监督 | 真实 worker/native/host，材料 GET 后由 harness 合成控制面离线。soft_budget 与 time_limit 各一真实回合均通过、未封存；分别 8.754/6.002 秒。后者限制为 3 秒，停止有延迟；[修复后记录](../evidence/workflow/studio-acceptance-agent-supervision-fixed-20261012.json)。不宣称硬截止或所有真实断网方式均已覆盖 |
| 原版导入/恢复模式/引擎写拒绝 | 正式 runtime probe `allChecksPass=true`；原版导入、game-mode、10 秒 GUI 通过，原源不变，认证/后台/其他工程/源和 app 写/IPv4/IPv6/外部执行拒绝。recovery 对抗无工具执行/UID伪造；[最新 runtime](../evidence/workflow/studio-acceptance-godot-runtime-20261012.json)、[旧 CA 失败](../evidence/workflow/studio-acceptance-godot-runtime-original-template-ca-failure-20261012.json) |
| 真实封存链 | 临时存储中 fixture 策划、批准和角色注册，实际 HTTP、一个真实 Producer 回合、精确注释和受信 UID、Git 封存、后端交付门及 ProjectRunner 均通过。fresh import/main-scene/source immutable PASS，创建候选，同一 sourceCommit GUI 满 10 秒、唯一 time_limit stopped 终态，封存/试玩源不变；[完整记录](../evidence/workflow/studio-acceptance-sealed-chain-20261012.json)。总 73.462 秒，preview 调用 11.500 秒（含启动/停止）；[旧 CA 失败链](../evidence/workflow/studio-acceptance-sealed-chain-ca-failure-20261012.json)保留 |
| 真实完整业务链 | [业务记录](../evidence/workflow/studio-acceptance-business-20261013.json) **PASS、8 个真实 native 回合、335.544 秒**：3 次策划、2 次制作、3 次故障策划。READY 回改/三条决定/图片描述/旧审阅拒绝，两次精确注释及受信 UID 封存、独立验证均通过；synthetic accept 保留 needs_followup 与另两条 unreviewed；GUI 与制作实际重叠 **41.043 秒**，交付时 GUI 仍活；真实 preview.stop、候选拒绝、原接受快照与各副本源不变。重启 UNKNOWN 阻止 claim，Runner 自行核账 STOPPED；native crash/cancel 各一个真实回合、原程序组消失、无新候选 |
| 补充 HTTP/SSE | [四场景记录](../evidence/workflow/studio-acceptance-remaining-transport-20261013.json) PASS：慢 GET/发布重关联、订阅后事件/缺口 resync、终态 ACK 丢失重启重放、取消/迟到完成/停止核账。实际 HTTP/SSE，执行事实是明确标记的 fixture，无模型/Godot/Runner 子进程 |
| native 启动 ACK 丢失 | [最终工具版本](../evidence/workflow/studio-acceptance-native-start-loss-fixed-20261013.json) PASS：harness 收到真实 turn/start ACK 后只吞该 ACK，后续通知仍透传；一个实际回合，driver 15.348 秒 watchdog 停止，native/host/bridge 清理，无候选、不启动第二回合 |
| 最终静态检查 | Python/JavaScript/shell 语法、严格 JSON、本地文件链接与 git diff --check 通过；未发现本轮验收遗留受控程序；[检查记录](../evidence/workflow/studio-acceptance-final-static-20261013.json) |

该封存链没有把 Coordinator 标为 `testData=true`；这是用于通过实际批准门的独立临时 fixture，策划/批准/注册均为合成控制面，不是用户生产批准。[探针源码](../tools/studio_acceptance_sealed_chain.py)的执行路径没有 `candidate.accept`，运行记录保持 `userCandidateAccepted=false`；该判断来自受信 harness 与记录，不是假造的用户接受。临时状态已销毁，证据与候选不进入用户状态目录。记录内的 cleanup 另保存由原 native cwd 确定的临时存储路径及运行后实际检查到目录不存在的事实；这项检查未追加模型回合。

新业务记录同样在临时正常 Coordinator（`testData=false`）中执行。批准、接受与拒绝是 harness 的 synthetic operator 决定；模型、封存、Godot、HTTP 与停止核账均实际执行。它保留 `userCandidateAccepted=false`，临时目录已销毁，未操作正式用户状态。两轮制作只追加批准注释，不能推广为复杂玩法或视觉质量验收。

本次真实模型记录只确认请求的 `gpt-6-luna / max`、线程报告的模型/provider 及 turn/start 回执。native 未报告本回合实际 effort，`turnActual/actualProfile` 保持 null；用量覆盖保持 `partial_or_unknown`，不把累计快照相加，不声称完整计费。

## 3. 24 场景补充矩阵

“回归”表示 fixture/DOM 规则；“实测”表示该记录覆盖的实际 HTTP、浏览器或进程事实。部分通过不提升为完整场景 PASS。

| 编号 | 场景 | 当前结果与证据边界 |
| --- | --- | --- |
| 01 | 新项目空讨论页、无串扰 | 浏览器实测通过；[界面证据](../evidence/workflow/studio-acceptance-ui-20261012.json) |
| 02 | READY 回改/另一窗口修订 | 回归及真实 READY 回改通过；旧 reviewedPlanRef 拒绝，三条反馈决定完整 |
| 03 | 未加入文字/逐条反馈决定 | 回归及真实三条逐项 adopted/deferred 输出通过；人工体验独立未验 |
| 04 | 丢回执、同 ID/异内容重放 | 协议回归与重启后实际回执恢复通过 |
| 05 | 后端重启/旧 token | HTTP 实测通过；前端原意图/草稿由回归覆盖 |
| 06 | 新发布/慢 GET/草稿重关联 | 实际两组 HTTP 视图/慢 GET/fixture 发布与草稿重关联通过；不冒充双浏览器人工操作 |
| 07 | 非法成功 JSON/身份/额外 config | 严格拒绝回归通过 |
| 08 | 模型、effort、模态、目录变化 | 拒绝回归通过；受测模型/provider 与红色 reference PNG 实际输入/描述通过；不穷举所有型号/目录组合 |
| 09 | 偏好、草稿、刷新/心跳零回合 | 浏览器及回归通过；新真实验收回合来自显式探针，未由刷新自动产生 |
| 10 | 默认 effort/请求/实际报告 | 分层回归通过；真实模型/provider 已报告，实际 effort 仍未知 |
| 11 | 快照与订阅空窗更新 | 实际 HTTP/SSE 补发通过 |
| 12 | 断流/重复/缺口/过期/项目迟到 | HTTP/SSE 实测、订阅后实际更新、合成缺口 RESYNC_REQUIRED/resync 与 DOM 回归通过；缺口注入由 harness 控制 |
| 13 | 领取/原生启动丢响应或崩溃 | 回归及真实 native turn/start ACK 丢失、native 崩溃停止通过；不重开模型 |
| 14 | 后端重启、lease 过期仍执行 | 真实已启动模型跨后端重启通过：UNKNOWN 保留占用，原进程停止后 Runner 按原身份核账 STOPPED；lease 拒绝另由回归覆盖 |
| 15 | 终态 ACK 丢失/lease 改变 | 实际 HTTP 丢终态 ACK 后重启、lookup/同 reportId 重放通过，无重复候选；执行报告为 fixture |
| 16 | 取消完成竞争/停止未知 | 真实已启动回合取消与停止通过；迟到 completed/evidence_only/停止未知组合经实际 HTTP fixture 验证，不推进候选 |
| 17 | GM 消费后崩溃/伪造确认 | 幂等恢复/拒绝回归通过；真实 Producer 已使用准备输入并通过封存交付门 |
| 18 | 工具/游戏访问其他项目及批准域 | fresh native/host/策划/制作工具及实际 ProjectRunner verify/GUI 探针通过，四角色正式注册及失败关闭通过 |
| 19 | 重复/迟到/缺失/重置用量 | 回归通过，真实单线程用量已观测；外部工具/子线程完整覆盖未证明 |
| 20 | 离线达到时限/软预算 | 两个真实监督回合通过，控制面离线由 harness 合成；停止存在延迟 |
| 21 | 未停止制作/源漂移/导入改源 | 拒绝回归、真实 UID 来源/精确变更集、封存/fresh import/main-scene 与源不可变通过，技术 PASS 后形成候选；未停止不能通过交付门 |
| 22 | 试玩时新一轮/拒绝候选 | 真实接受快照 GUI 与 Producer2 重叠 41.043 秒、交付时 GUI 仍活，preview.stop 后独立验证，再 reject 保留原 snapshot；各源不变 |
| 23 | 接受候选且 needs_followup | 实际 HTTP synthetic accept 保留精确 Snapshot、needs_followup 与另两条 unreviewed；用户正式接受及人工体验仍 NOT_TESTED |
| 24 | 物化失败/旧备份/协议不兼容 | 引用/重试/兼容回归及新 storeId 恢复实测通过 |

通信、界面和原始矩阵的详细范围见[初次验收](STUDIO-ACCEPTANCE-20261012.zh-CN.md)及[HTTP/SSE 证据](../evidence/workflow/studio-acceptance-transport-20261012.json)。本文修正当前进展，不重写旧失败为成功。

## 4. 项目内 MCP 与默认安装

用户指定的 `gm-test/addons/godot_mcp` 已收纳为仓库 canonical `addons/godot_mcp`（Godot MCP Server / LIDAXIAN / 1.1.0，70 项可见普通文件，含来源 UID）。两后端模板默认包含并启用该 bundle；本仓库 GodotMaker 的 `gm-scaffold` 与直接 `project-scaffold` 指令均调用同一安装器，保留其他插件，不以可选 npm server 替代。安装器支持新目录/已有工程/幂等，冲突、不可解析启用列表或不安全路径在写入前拒绝。[安装与使用说明](GODOT-MCP.zh-CN.md)记录来源和适用限制。

[原项目 MCP 实测](../evidence/workflow/studio-acceptance-gmtest-mcp-20261013.json)完成 HTTP initialize、74 tools、核对项目身份、打开场景/读取编辑器层级/属性、运行和停止；173 项原源字节未改，测试编辑器已关闭。[默认工程实测](../evidence/workflow/studio-acceptance-default-mcp-20261013.json)分别检查安装器新建工程与 general_2d 模板，使用普通 GUI 编辑器的实际 MCP 服务。它们不属于严格 Runner 隔离证据；普通编辑器的 `config/features` 元数据、设置重排/格式化及缺失 UID 生成在记录中明确列出，不冒充精确封存源不变。

MCP 仅作为可信操作员控制通道，Producer 不可改 addons，Planner 不获工程执行权；严格验证使用 recovery 模式，不启动该 EditorPlugin。没有修改全局 Codex 客户端配置；MCP 不参与 Runner 权限授予，角色权限由前述 fresh 探针独立决定。

## 5. 历史证据、更正与验收限制

- 旧 `studio-acceptance-native-offline-budget-20261012.json` 的 `modelTurns=1` 是 harness 预填错误；实际上没有 acknowledged turn，MCP transport 在 thread/start 前拒绝。修复后监督证据显式更正为 **0**，旧文件保留。最新两项监督记录才是两个真实模型回合。
- [首次封存链](../evidence/workflow/studio-acceptance-sealed-chain-first-20261012.json) 的 `productionAttemptId` KeyError，以及[第二次 harness 失败](../evidence/workflow/studio-acceptance-sealed-chain-missing-script-20261012.json) 的缺失 player.gd，均为 **0 模型回合**。修复为真实模板 main.gd 后才运行当前一回合链。
- [合成证书 override 的通过副本](../evidence/workflow/studio-acceptance-godot-runtime-synthetic-override-20261012.json) 与原版 CA 失败分开保存。[历史 runtime failure 文件](../evidence/workflow/studio-acceptance-godot-runtime-historical-failure-20261012.json) 是标记过的失败摘要，完整旧日志仍在[原始 runtime 证据](../evidence/workflow/studio-acceptance-runtime-20261012.json)。
- 正式 CA probe 的[首次日志观测](../evidence/workflow/studio-acceptance-godot-runtime-ca-adapter-log-observation-20261012.json)因非 verbose 导入缺 `EditorSettings: Load OK!` marker 未通过；保留硬门槛并加 verbose 后实际重验通过，未手改 PASS。MCP 新探针的[停止参数错误](../evidence/workflow/studio-acceptance-default-mcp-harness-failure-20261013.json)、[版本元数据观测](../evidence/workflow/studio-acceptance-default-mcp-settings-observation-20261013.json)和[设置排序观测](../evidence/workflow/studio-acceptance-default-mcp-settings-order-observation-20261013.json)保留，未修改插件代码来掩盖差异。

新业务验收的前两次精确注释断言失败记录保留在[首次记录](../evidence/workflow/studio-acceptance-business-first-source-mismatch-20261013.json)与[批准文本句号差异](../evidence/workflow/studio-acceptance-business-approved-punctuation-mismatch-20261013.json)：第二次 diff 显示制作符合已审阅方案的句号，harness 期望漏了句号，修正后仍采用精确字节比较。第三次的[原生唯读提示误解](../evidence/workflow/studio-acceptance-business-native-readonly-confusion-20261013.json)保留首轮通过及第二 Producer 未修改源而被交付门拒绝的事实。三次分别观察到 3、3、5 回合，最终通过 8 回合，业务实跑总数为 **19**，没有只记成功回合。native 启动 ACK 探针的首次与最终版本各一实际回合；旧证据保留。

[首轮最终回归失败](../evidence/workflow/studio-acceptance-final-role-regression-initial-failure-20261013.json)及[工具说明定向超时](../evidence/workflow/studio-acceptance-tool-guide-test-first-timeout-20261013.json)也保留；正常 fake RPC 的默认等待改为 5 秒，专门的短超时/取消测试与生产时限未变。工具说明前的[283 项通过副本](../evidence/workflow/studio-acceptance-final-role-regression-before-tool-guide-20261013.json)与当前最终结果分开，不以旧运行替代新代码验证。

原版 CA、精确 UID/封存源验证、四角色注册及受测业务/故障链的技术阻断已解除。剩余用户决定是玩法、视觉与逐条体验验收（`NOT_TESTED`）；原生本回合 actual effort、完整计费与外部工具/子线程用量仍未报告或未证明，不填造数据，也不为穷举所有型号烧回合。旧 collect-loop 按原设计保留，`backend/verification.py` 未迁移到新版独立 sandbox；这不是本轮追加迁移任务，详见[部署边界](DEPLOYMENT-MANUAL.zh-CN.md)。完整 GodotMaker scaffold 的其他 addon 依赖未实跑，不扩大默认 MCP 安装验收的范围。服务启用权限仍须本机每次启动 fresh 探针通过，不能拿历史 JSON 或 fixture 直接授予能力。

本轮没有执行独立 SHA/MD5 或旧 checksum helpers。构建/范围依据 Git 身份、清单、diff 与原始字节比较；保留 `hud.gd/title_screen.gd` 历史差异拒绝门及用户既有未提交修改。

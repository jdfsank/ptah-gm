# 造物工作台部署与维护说明书

本文面向在 macOS 上安装、启动和维护本机游戏制作工作台的部署者。工作台包含旧 collect-loop 工作流和新 `objects-v1` 通用对象工作流。开始维护前，请用 Git 核对实际检出版本及差异；不要把此前 `r4-local-1` 检查点当成本次通用工作流版本。用户操作见[工作台用户说明书](USER-MANUAL.zh-CN.md)。

本文覆盖现行 Studio v1 与保留的旧工作流。新版协议、独立组件和备份工具的初次实施见[2026-10-12 实施记录](STUDIO-IMPLEMENTATION-20261012.zh-CN.md)，最新证据见[边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。在受测 macOS、stateless custom provider、Godot 4.6.3 范围内，四项角色探针、真实 Runner 注册和 fixture 控制的业务闭环通过；后端 283/283（零跳过），前端既有 19/19 未重跑。用户玩法/视觉验收仍为 `NOT_TESTED`，没有用户接受的生产候选；请求 effort=`max` 不是实际 effort 观测，实际 effort 与完整计费未知，未穷举全部模型/provider/平台。项目内 MCP 默认安装与实际控制见[Godot MCP 说明](GODOT-MCP.zh-CN.md)。

文档日期：2026-10-13。[返回说明书入口](README.zh-CN.md)。

本轮项目与阶段改造沿用现有 SQLite、Godot、Codex 和安装依赖，不引入新数据库服务、消息总线或容器。部署评估与交付记录见[可行性复核](STUDIO-PROJECT-STAGES-REVIEW.zh-CN.md)。

## 2026-10-12 独立组件入口

默认后端监听 `127.0.0.1:8765`，独立前端监听 `127.0.0.1:8764`。前端静态服务只代理同源 `/api/`，不代理内部 Runner 通道；直接访问后端的 `/studio/` 仍可使用。两个 Runner 使用独立进程、独立私有日志和内部 token，数据库仅由后端读取和裁决。

在仓库根目录运行：

```sh
.venv/bin/python -m tools.studio_services start
.venv/bin/python -m tools.studio_services status
.venv/bin/python -m tools.studio_services stop
```

也可使用 `start-studio-services.command`。默认采用 `.workbench/`。隔离测试须显式使用新的状态目录及 `--test-data`，例如：

```sh
.venv/bin/python -m tools.studio_services start --state-root /tmp/studio-disposable --test-data --api-port 8775 --frontend-port 8774
```

分组件维护用 `--component backend|frontend|agent|project`。后端需先启动，AgentRunner 注册时只读取真实模型目录，不启动模型回合。Godot 路径可通过 `--godot` 指定，当前默认 `/Applications/Godot.app/Contents/MacOS/Godot`。前端和后端端口通过 `--frontend-port` 与 `--api-port` 指定；不要将同一状态目录同时交给两个后端。

`status` 报告受管进程身份，不能单独证明模型回合或 Godot 主循环有响应。操作日志位于 `<state>/logs/`；Runner 日志位于 `<state>/runners/agent|project/journal.sqlite3`，启动意图和未确认报告保留在其中。不要直接修改这些日志或将内部 token 放入浏览器。分别查看 `/api/v1/handshake`、项目公开视图和执行监视来核对 API、状态流、Runner 与原生活动。

受测 native/provider bridge、路由宿主及静态工具已分权，实际拒绝探针和真实 Producer 封存链通过相应门禁；UID 在 recovery-mode 隔离导入后由受信宿主准备，再绑定 input/source commit 与引擎版本。原版 Godot 导入/主场景/GUI、独立验证和同源候选 GUI 的证据限定于受测配置。Agent 与 Project Runner 的真实 HTTP 注册均通过；四项角色能力由每次启动时绑定 Runner ID/kind 的新鲜本机检查派生，不硬编码 PASS。证据基于受信本地 Runner token 信任模型，不是远程 attestation；检查缺失、失败或过期时相应能力不会注册，页面继续禁用依赖该能力的动作。Native 网络拒绝依据是执行同一系统策略的 Python worker 探针，不是 native RPC 直接网络探针。不得手改注册证据绕过门禁。

## 阅读导航

| 运维任务 | 章节 |
| --- | --- |
| 第一次部署 | [首次安装](#3-首次安装) |
| 选择生产或测试状态目录 | [启动参数与存储选择](#4-启动参数与存储选择) |
| 启动并检查服务 | [启动与健康检查](#5-启动与健康检查) |
| 交付给用户 | [用户手册与部署者交接](#6-用户手册与部署者交接) |
| 理解数据位置与运行权限 | [安全边界](#7-安全和隐私边界)、[状态目录](#8-状态目录文件与权限) |
| 停止服务或处理未知作业 | [正常关停与进程状态](#9-正常关停与进程状态) |
| 备份与恢复 | [完整备份与恢复](#10-完整备份与恢复) |
| 升级、迁移到新 Mac、回滚 | [升级、迁移与回滚](#11-升级迁移与回滚) |
| 查看日志、排查错误 | [日志与故障排查](#12-日志与故障排查) |

## 1. 产品与部署模型

工作台由静态前端、Python 后端、AgentRunner 和 ProjectRunner 四个独立组件组成。独立前端默认地址 `http://127.0.0.1:8764/studio/`，通过同源代理连接后端 API；后端自带静态入口 `8765/studio/` 保留。后端持有项目和批准裁决、回执、租约与快照引用；两个 Runner 通过内部 JSON 通道领取和报告。浏览器不能传入 cwd、shell 命令、程序路径或权限配置。

新项目通过 Studio v1 命令和 `objects-v1` 对象文档处理：AgentRunner 和 ProjectRunner 在各自启动时依据新鲜本机检查注册可用能力，再执行策划、制作、验证与试玩；用户确认完整计划后冻结批准，接受精确候选后更新快照。以页面能力状态判断当前服务是否具备相应动作。迭代请求把自然语言、实际字段变更和对象反馈分开保存。已有项目继续由旧工作流处理，旧审批不会自动升级。

通用实现目标是 Godot 4、2D、GDScript。后端写入的对象文档和 `StudioRuntime` 桥接文件、GM 规格文件及验证器保持受保护。制作写入白名单为 `project.godot`、`scripts/**/*.gd`、`scenes/**/*.tscn`、`resources/**/*.tres` 及 `assets/` 下 PNG/JPEG/WebP；不接受插件、编辑器扩展、制作方测试或其它可执行入口。

**验证状态（2026-10-09）：**隔离原生探针 r3 已完成两个非收集玩法的策划和制作 session，验证器用 Godot 4.6.3 对三轮结果执行干净导入和后端主场景短运行冒烟；Bridge Runner 另完成 speed 220→300 px/s 以及玩家青色（`#00FFFF`）反馈迭代。后续 fixture 专项玩法复测也通过：Light Grid 以真实 viewport 鼠标与 R 键检查角/边/中心规则、moves、三步胜利、胜后锁定和按钮/按键重置；Bridge Runner 检查两段跳跃路线、胜利、按 R 重置后再次获胜、坠落恢复，并验证 speed/cyan 参数保留。缺陷准确表现为“获胜后按 R 返回出生点，却因旧出口接触立即再次进入 WON”，不是一般跳跃后重开失败。修复证据和结果见[反馈修复记录](../evidence/workflow/general/reset-feedback-probe.json)、[Bridge Runner 复测](../evidence/workflow/general/bridge-gameplay-repaired-r2.json)和[Light Grid 玩法探针](../evidence/workflow/general/puzzle-gameplay.json)；Bridge Runner 检查对应源码版本 `b4d535762b38dbb932c886c4e46db10972d4c762`。所有探针均为测试数据（`testData=true`、`productionAuthorized=false`、`humanAcceptance=NOT PERFORMED`）。这些 fixture 专项断言不改变一般生产报告中玩法需求仍为 `NOT_TESTED` 的状态，也不构成用户验收。前两次探针的策划响应不是严格 JSON，因此在策划阶段失败；r3 才跑通完整制作链路。模型报告 `completed` 仅表示回合结束；技术 PASS 仅表示报告列出的检查通过。

## 2. 支持范围与部署前提

### 2.1 支持的运行环境

本手册覆盖当前已核实的 macOS 本机部署：同一台电脑上运行服务、Codex app-server 和 Godot。 服务默认只绑定 `127.0.0.1`。浏览器必须在同一台电脑访问 `http://127.0.0.1:8765/studio/`。 应用当前没有 TLS、远程用户认证、多人权限管理或网络部署入口。不要把它暴露到局域网或公网。

服务端使用 Unix 文件锁 `fcntl`，当前工程运行路径、Codex app-server 路径和预览 Godot 路径均以本机 macOS 配置为基准。 Linux、Windows、容器、反向代理部署和共享服务器运行没有经过本工作流验证，不能视为受支持配置。

### 2.2 必需组件

需要 Python 3.11 或更高版本、Git、Codex CLI/app-server，以及 Godot 4。当前运行服务的同一 macOS 用户必须已配置可用的模型提供方与认证。服务不会自行登录或生成凭据。 Codex 的官方账号认证与自定义 provider 配置是不同路径：`codex login status` 反映 Codex CLI 官方登录状态，官方账号未登录不等于自定义 provider 必定不可用。官方认证说明见[Codex Authentication](https://developers.openai.com/codex/auth/)。本次无法在线核验该页面的最新内容，请以官方页面为准。

新版 `objects-v1` 的 ProjectRunner 在启动 Godot 验证或试玩前，还要求已存在的 Apple Command Line Tools：`/Library/Developer/CommandLineTools/usr/bin/clang` 和 `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`；并要求固定系统 CA 文件 `/etc/ssl/cert.pem` 可安全读取、由 root 所有且包含有效证书。受信宿主会在每个私有 runtime 中生成规范 PEM 并编译专用 dylib。这些是本机系统依赖，不由 Python requirements 安装，也不会由工作台安装。缺少工具链、CA 缺失或无效、编译失败时，新版 Godot 子进程启动前失败关闭。该实现当前的受测部署范围为 macOS 与 Godot `4.6.3.stable.official.7d41c59c4`。

当前工作流通过本机 CLI 启动 app-server，使用运行服务的同一用户环境和配置。`sessionDispatch=READY` 只表示找到了 CLI，不会验证 provider 凭据、登录或真实模型调用是否成功。

当前项目的 Godot 已安装在 `/Applications/Godot.app`。部署记录报告版本 `4.6.3.stable.official.7d41c59c4`。

服务使用项目本地 `.venv/` Python 环境。不要让不同项目或系统 Python 共用此虚拟环境。 Python 运行时依赖见[`backend/requirements.txt`](../backend/requirements.txt)。当前列出的唯一第三方运行时包是 `Pillow==12.3.0`。Node.js/npm 只用于前端开发与测试，启动静态 Studio 不需要它们。 Godot 和 Codex app-server 是独立的本机程序，不由 Python requirements 安装。

### 2.3 代码位置和检查点

部署时应使用一份完整、来源清楚的 Git 检出，包括 `backend/`、`frontend/studio/`、`backend/templates/collect_loop/`、`backend/templates/general_2d/` 及固定 GM non-pk 来源。用 `git status --short` 和已审查的提交/分支确认版本，不要只复制单个 Python 文件。

主要实现入口：[`backend/server.py`](../backend/server.py)、旧工作流 [`backend/coordinator.py`](../backend/coordinator.py)、通用流程 [`backend/generic_workflow.py`](../backend/generic_workflow.py)、对象协议 [`backend/object_protocol.py`](../backend/object_protocol.py)、通用验证器 [`backend/general_verification.py`](../backend/general_verification.py)。通用工作流的协议和验收计划见[实施契约](GENERAL-GAME-TOOL-PLAN.zh-CN.md)。

根目录 [`AGENTS.md`](../AGENTS.md)禁止构建期间独立 SHA/MD5 哈希检查。部署核对使用 Git 提交、Git 管理的对象引用和差异审阅；不要运行独立校验和脚本。

## 3. 首次安装

### 3.1 确认仓库位置

将整份仓库放在当前用户可读写的本机目录中。不要从 ZIP 内直接运行服务。 以下步骤假设终端当前目录是仓库根目录，也就是包含 `backend/`、`frontend/` 和 `start-studio.command` 的目录。 先确认当前位置：

```sh
pwd
```

确认部署版本和工作区：

```sh
git status --short
```

在继续之前，检查该仓库属于预期项目，并核对部署所采用的提交或标签。

### 3.2 确认 Python 与 Git

查看 Python 版本：

```sh
python3 --version
```

版本应为 3.11 或更高。 查看 Git 是否可用：

```sh
git --version
```

工作流使用 Git 保存项目基线、隔离 worktree 和候选提交。没有可用 Git 时，制作和验证不能正常完成。

### 3.3 创建标准 Python 虚拟环境

在仓库根目录创建项目专属虚拟环境：

```sh
python3 -m venv .venv
```

通过该虚拟环境安装仓库声明的 Python 依赖：

```sh
.venv/bin/python -m pip install -r backend/requirements.txt
```

检查解释器和依赖：

```sh
.venv/bin/python --version
.venv/bin/python -m pip show Pillow
```

如果机器上已有 `uv`，也可用 `uv venv --python 3.11 .venv` 和 `uv pip install --python .venv/bin/python -r backend/requirements.txt`。uv 创建的虚拟环境未必包含 pip，因此使用该方案时通过 `uv pip show` 和 `uv pip check` 检查依赖。 使用 pip 或 uv 二选一即可。不要把安装步骤加到每次启动服务的脚本中。

```sh
uv pip show --python .venv/bin/python Pillow
uv pip check --python .venv/bin/python
```

### 3.4 安装与确认 Godot

首次部署时，把可信来源的 `Godot.app` 安装到 `/Applications/Godot.app`，可以在 Finder 中拖入“应用程序”。本机使用的原安装包位于 `/Users/typ/Desktop/pj_timekettle/engine/Godot.app`，当前已经完成安装；其他机器应使用自己准备的应用包。已有 Godot 时先核对版本，避免直接覆盖还在使用的引擎。

检查当前安装记录中的可执行文件：

```sh
/Applications/Godot.app/Contents/MacOS/Godot --version
```

预期版本为 `4.6.3.stable.official.7d41c59c4`。其他 Godot 4 版本尚未在此版本部署记录中确认。旧 collect-loop 验证器解析顺序为显式路径、`GODOT_BIN`、PATH 中的 `godot`、最后回退到 `/Applications/Godot.app/Contents/MacOS/Godot`。新版 ProjectRunner 使用服务配置的 `--godot` 路径，未指定时由运行环境选择可执行文件。`GODOT_BIN`/`GODOT_PATH` 只选择引擎可执行文件，不改变新版 runtime 固定使用的 CA 来源和编译绑定。

```sh
studio_godot_bin="/Applications/Godot.app/Contents/MacOS/Godot"
export GODOT_BIN="$studio_godot_bin"
```

本机安装记录提到 `GODOT_PATH`，但旧的 `backend/verification.py` 使用的是 `GODOT_BIN`，不读取 `GODOT_PATH`。旧 collect-loop 验证器与新版 ProjectRunner 是不同执行路径，具体隔离差异见[安全边界](#controlled-execution)。无论新版从何处选择 Godot 可执行文件，项目设置或环境变量都不能替换私有 CA 文件、interposer 源码或编译绑定路径。

如果希望在终端直接使用 `godot`，可在用户自己的 `.local/bin` 建立链接。以下命令只适用于链接目标还不存在的首次设置；本机已有链接，无需重复执行：

```sh
mkdir -p "$HOME/.local/bin"
ln -s /Applications/Godot.app/Contents/MacOS/Godot "$HOME/.local/bin/godot"
export PATH="$HOME/.local/bin:$PATH"
export GODOT_BIN="/Applications/Godot.app/Contents/MacOS/Godot"
godot --version
```

需要持久生效时，将上面的 `export PATH` 和 `export GODOT_BIN` 行写入启动服务所用 shell 的配置文件，例如 zsh 的 `~/.zshrc` 或 bash 的 `~/.bash_profile`，再打开新终端。Finder 双击脚本的环境可能不同，固定 macOS 引擎路径和 Codex 应用包回退仍应可用。

### 3.5 确认 Codex

在运行服务的同一 macOS 用户会话中，检查 CLI 和官方登录状态：

```sh
command -v codex
codex --version
codex login status
```

若 `command -v codex` 找不到 CLI，工作流还会查找已知应用包路径。可用实际安装的绝对路径检查版本：

```sh
/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex --version
```

官方 OpenAI/Codex 账号认证可依照[官方认证说明](https://developers.openai.com/codex/auth/)处理。本次该网页返回 403，因此本手册不转述可能变化的交互细节。自定义模型提供方应按提供方说明，在当前运行服务用户的环境中配置认证；这不等同于官方账号登录，也不要把凭据复制到表单或仓库。

驱动器以 `codex app-server --stdio` 启动本机 session。旧入口使用运行服务用户的环境和配置；新版 AgentRunner 的受信适配器保留认证，native 只获得私有环境与一次性 bridge nonce。目前新版仅支持无原生 credential file 的自定义 provider，不支持的认证方式失败关闭。服务不会自行登录或生成凭据。`codex login status` 只报告官方 Codex 登录状态，不证明自定义提供方是否可用。`sessionDispatch=READY` 只证明找到 CLI，不验证认证或模型调用。实际 session 无法连接提供方时，检查所选 provider 的配置和认证。

### 3.6 确认启动脚本

仓库提供[`start-studio.command`](../start-studio.command)。脚本会切换到自身所在仓库目录，再使用 `.venv/bin/python` 启动后端。 也可以在仓库根目录手动启动：

```sh
.venv/bin/python -m backend.server --port 8765
```

如果提示本地 Python runtime 缺失，先完成第 3.3 节，不要改为系统 Python 运行。

## 4. 启动参数与存储选择

### 4.1 命令行参数

CLI 参数在[`backend/server.py`](../backend/server.py)中定义。 `--project-root PATH` 指定服务端拥有的代码与模板根目录，默认是由 `server.py` 所在位置推导出的仓库根目录。 `--state-root PATH` 指定私有工作流状态目录。省略时使用 `<project-root>/.workbench`。 `--test-data` 将该服务及其持久记录明确标为测试数据。它不会代替生产批准，不能与生产状态目录混用。 `--host ADDRESS` 默认 `127.0.0.1`。程序拒绝其他地址；该参数不能用来开启远程访问。 `--port NUMBER` 默认 `8765`。如果端口被占用，可以选一个未占用的本机端口，并在浏览器中使用相同端口。 查看当前版本的参数列表：

```sh
.venv/bin/python -m backend.server --help
```

`start-studio.command` 固定传入 `--port 8765`，其他参数需要通过终端手动启动模块时提供。

### 4.2 默认生产工作区

不带 `--test-data` 启动时，工作区字段为 `testData=false`、`productionAuthorized=true`。 默认存储目录是仓库根目录下 `.workbench/`。其中可能包含真实用户创建的项目、审批事件、候选和发布状态。 首次面向真实项目使用时，确认服务启动命令没有包含 `--test-data`，并确认 `--state-root` 没有指向临时探针目录。 制作玩法需要用户在 Studio 工作台实际确认对应表单。部署人员不能通过运行探针或直接修改数据库来代替用户批准。

### 4.3 隔离测试工作区

自动测试或演示探针必须使用单独的状态目录，并加 `--test-data`。在当前 macOS 用户的数据目录下选择独立测试位置：

```sh
studio_test_root="$HOME/Library/Application Support/Ptah/StudioTest"
```

创建测试目录：

```sh
mkdir -p "$studio_test_root"
```

从仓库根目录使用测试模式启动：

```sh
.venv/bin/python -m backend.server --port 8766 --state-root "$studio_test_root" --test-data
```

生产与测试数据库各自记录运行模式。如果用错误模式再次打开同一状态目录，服务会以 `MODE_MISMATCH` 拒绝启动。 测试模式记录保存 `testData=true`、`productionAuthorized=false`。即便测试结果显示候选已接受或发布，它仍是合成测试状态。 不要通过删除状态目录内的模式标记来“转换”测试工作区。真实生产操作请用新的生产工作区，并由真实用户完成确认。

## 5. 启动与健康检查

### 5.1 启动服务

在仓库根目录启动：

```sh
.venv/bin/python -m backend.server --port 8765
```

启动信息会在终端打印实际 Studio 地址。保持此终端会话开启，直到准备停止服务。 在浏览器打开：

```text
http://127.0.0.1:8765/studio/
```

如果选择了其他端口，将 URL 中的 `8765` 改成实际端口。

### 5.2 检查服务响应

健康检查不需要创建项目或启动制作 session。先检查工作区只读接口：

```sh
curl -i http://127.0.0.1:8765/api/workspace
```

HTTP 200 且返回工作区 JSON，表示 HTTP 服务已响应。 读取能力对象中的 `sessionDispatch`、`godotVerification` 和 `semanticProjection`，确认对应能力为 `READY`。 `sessionDispatch=READY` 仅表示找到了 Codex CLI；`godotVerification=READY` 仅表示能力探测找到引擎文件。 能力探测不会创建 Codex session、验证项目、运行完整游戏测试或替代人工接受。 检查 Studio 静态页面：

```sh
curl -I http://127.0.0.1:8765/studio/
```

检查端口监听者：

```sh
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

以上命令只检查本机服务。不要把本地健康检查地址分享为远程服务入口。

### 5.3 浏览器会话与草稿

浏览器前端从同源 `/api/session` 获取短期工作台 token 和操作员身份。写入请求必须使用同源请求和 token。项目首页只提供摘要；`GET /api/projects/<projectId>/workspace` 返回对应项目的讨论、表单与作业。资源操作使用项目作用域，原来未指明项目的提案、作业与附件接口不再是读取或写入的入口。

浏览器刷新项目链接后可恢复该项目作业和已确认表单；首页不自动恢复最近任务。草稿按服务存储身份、项目、阶段和发布版本隔离。浏览器草稿不等于后端已确认表单。升级浏览器或清理站点数据可能清除本地草稿；已保存的后端工作流记录保存在状态目录。发布版本变化后，草稿重关联需要前端展示差异并由用户确认。

服务存储身份 `storeId` 保存在 SQLite `meta` 中，同一存储重启后保持不变；新建存储获得新的身份。旧格式浏览器草稿没有这个身份，升级保留原记录但不自动迁移，避免凭 `local` 或 `test` 标签误认归属。

## 6. 用户手册与部署者交接

用户操作流程独立维护在[工作台用户说明书](USER-MANUAL.zh-CN.md)，包含通用概念策划、对象字段与反馈、冻结计划、候选审阅、旧 collect-loop 兼容和作业状态说明。

部署者交付时请告知用户本机 Studio URL 和当前连接的是生产还是测试工作区。r3 原生探针属于独立测试 state-root，测试工作区中的合成接受不能迁移成生产批准；不得将该探针的报告、数据库、候选或项目仓库复制到生产工作区。若页面出现“测试工作区”提示，确认和发布都只属于测试记录。生产用户仍需在候选页启动本机 Godot 试玩，并按计划逐条给出自己的体验决定。

用户需要了解对象计划、字段值、反馈类别、确认含义或错误状态时，请交付用户说明书；不要让部署人员以口头确认代替用户在正式工作台做出的决定。Godot 本机预览一次最多运行 15 分钟，每个项目同时只允许一个预览进程；不同项目的预览分别管理，到时服务会结束预览。

## 7. 安全和隐私边界

### 7.1 本机网络限制

服务只监听回环地址 `127.0.0.1`，并检查 Host、Origin 和 fetch-site 请求信息。 所有改变状态的请求还必须携带服务生成的工作台 token。服务同时返回基本安全响应头。 这些控制服务于同一台电脑上的本机使用。它们不构成远程用户认证、TLS 加密或多租户安全机制。 不要配置网络端口转发，也不要将服务地址发布到公网或局域网。

### 7.2 本机数据权限

后端将状态根目录权限设置为 `0700`，SQLite 主数据库文件设置为 `0600`。 上传图片文件设置为 `0600`。这些模式限制同一台电脑上的其他普通用户读取工作数据。 状态目录内的数据还受当前 macOS 用户、磁盘备份、设备加密和管理员权限影响。请将该目录纳入组织的本机数据保护政策。 不要把 `.workbench/` 上传到公共文件托管、工单或日志收集系统。图片和项目内容可能包含用户提供的私有信息。

<a id="controlled-execution"></a>

### 7.3 受控执行

新版 `objects-v1` 由独立 AgentRunner 和 ProjectRunner 执行。受信 ProviderBridge 持有受支持的 provider 认证；native、路由宿主和静态工程工具按各自进程策略分权。静态工具没有 shell、网络或工程执行能力。Agent 的 native `readOnly` 仅描述 native 运行时权限；制作文件通过独立静态工具 `studio_list_files`、`studio_read_file`、`studio_write_file` 访问，其中写工具只允许冻结的 `allowedFiles` 私有工程范围。工具名、参数及成功布尔值受协议校验并纳入有界证据；工具被拒绝仍是有效拒绝，交付门还会独立审计最终源。四项 capability 的启动注册结果由新鲜、绑定身份的本机固定检查派生；该信任模型依赖受信本地 Runner token，不构成远程 attestation。当前实测范围和限制见[边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。

新版 ProjectRunner 的 Godot 验证和试玩通过 `runners.godot_runtime.sandboxed_godot_argv` 启动受测子进程。macOS deny-default sandbox 将工程源限制为只读，只允许 `.godot` 缓存及本次私有 runtime 写入；UID 准备阶段只对受信调用者明确列出的缺失 `.gd.uid` sidecar 开放写入。网络访问拒绝；子进程只能启动受信 `/usr/bin/env` 和本次 Godot 可执行文件，项目脚本不能另起 shell 或任意程序。策略还拒绝 file-link，且 Godot 对私有 CA 支持目录、CA 文件、interposer dylib 和复制的 Godot.app 没有写权限。

受信宿主只从固定 `/etc/ssl/cert.pem` 读取系统 CA，检查文件类型/所有者并解析证书，再规范化为 PEM，写入每次执行的私有目录。编辑器导入使用私有 `EditorSettings` 的 `network/tls/editor_tls_certificates`；game-mode 则通过固定的 Security.framework trust-anchor interposer 读取同一份 CA。宿主用固定的 Command Line Tools `clang` 与 macOS SDK 编译 `runners/godot_ca_interposer.m`，把规范 CA 路径编译绑定在 dylib 中，通过受信启动环境加载。CA 路径不接受工程设置或项目提供的环境变量。缺 CLT、CA 文件不安全/不可解析或编译失败都会在 Godot 启动前失败关闭；ProjectRunner 的相应预览启动路径记录 `failed`、`stopped=true`，不会退回不受限启动。新版边界当前仅适用于本机 macOS 与受测 Godot 4.6.3 / stateless custom provider；依赖官方 credential-file 的认证路径失败关闭。

该边界只描述新版 Runner 路径，不覆盖旧 collect-loop。旧流程中的 [`backend/verification.py`](../backend/verification.py) 仍通过普通 `subprocess.run` 在运行服务的当前 macOS 用户权限下运行 Godot，没有上述 deny-default sandbox、固定 CA interposer 或 file-link 拒绝规则；项目代码仍是合作型本机执行。Git 写入范围和服务端记录属于应用层检查，不能把旧流程描述为 OS 隔离。旧项目和既有批准仍按原工作流保留，不自动迁移到新版。

“本机工作台”描述服务、项目管理和验证的运行地点，不代表模型推理完全离线。Codex 使用当前用户配置的模型提供方；若使用远端提供方，概念、计划、代码上下文及图片会按该提供方策略传输。

## 8. 状态目录、文件与权限

默认状态目录是 `<repository>/.workbench/`。使用 `--state-root` 时，以该参数给出的目录为准。

| 路径 | 用途 |
| --- | --- |
| `service.lock` | 使用中的服务进程互斥锁 |
| `state.sqlite3` | 项目、提案、表单、作业、审批、候选和发布元数据 |
| `state.sqlite3-wal`、`state.sqlite3-shm` | SQLite 运行期间可能出现的 WAL/共享内存文件 |
| `attachments/` | 后端分配 ID 保存的图片参考 |
| `projects/<project-id>/` | 每个工作项目的独立 Git 仓库 |
| `jobs/<job-id>/packet.json` | 已冻结并派发的工作表单记录 |
| `jobs/<job-id>/worktree/` | 制作和验证使用的隔离 Git worktree |
| `jobs/<job-id>/candidate.json` | 候选结果的本机证据文件（若作业已到相应阶段） |
| `previews/` | 本机候选预览解包目录及预览日志 |

实际目录中可能还存在 SQLite sidecar、运行日志或以后版本新增的内容。备份时按整个状态根目录处理，不要只挑选表格中的部分文件。 `service.lock` 使用操作系统文件锁。文件名存在不表示服务还活着，判断服务是否在运行要看端口监听和当前进程。

项目 Git 仓库和 worktree 由数据库记录、Git元数据和服务路径共同关联。移动或重命名状态根目录可能使 worktree 的管理链接失效。 **恢复工作区必须使用第 10 节的新空间工具；旧 worktree 的绝对路径关系另行核查。** 若确实要迁移路径，当前实现没有自动修复 Git worktree 链接的命令，应作为单独迁移工作审查处理。

## 9. 正常关停与进程状态

统一入口的正常停止顺序为 AgentRunner、ProjectRunner、前端、后端：

```sh
.venv/bin/python -m tools.studio_services stop --state-root /absolute/path/to/state
```

脚本按已记录的 PID 和原始启动时间核对身份，发出中断请求并等待；超时报告 `stop_unconfirmed`，不会强杀无关进程或假定执行停止。Runner 在停止确认前保留工作副本和未 ACK 的事实。停掉后端不会替独立 Runner 确认停止，也不会自动重开原回合。

手工启动的旧后端可在其终端按 `Control-C`。旧执行线程可能继续保留数据库锁；不得通过删除锁或数据库文件解除占用。仅凭端口无监听不能证明所有原生或 Godot 后代进程都已停止。

租约过期或后端重启后，已领取的 attempt 进入 `UNKNOWN/UNCERTAIN`，占用继续保留；排队但未启动的任务仍保留为排队。使用工作台的原执行核账入口，Runner 补送原日志。核账不会重发 native start，不会修改已接受版本。无法确认原身份时保留受阻状态，先核对执行器日志和受管进程。

## 10. 完整备份与恢复

使用专用离线工具；先停止后端和两个 Runner。统一部署将 Runner 日志放在 `<state>/runners/`，备份会核对这些服务锁，保存 SQLite WAL 中已提交的记录及整个工件库，并以 Git 对象核对被引用的交付。没有独立 SHA/MD5 校验步骤。

```sh
.venv/bin/python -m tools.studio_store backup /absolute/path/to/state /absolute/path/to/new-backup
.venv/bin/python -m tools.studio_store restore /absolute/path/to/new-backup /absolute/path/to/new-restored-state
```

目标必须是不存在的新目录。备份目标不能位于活动状态目录内。若手工启动 Runner 并把日志放在外部路径，先停掉它们并另行协调保存日志；专用工具不会自动发现状态根之外的日志。备份完成后保留 `backup.json`、软件 Git 版本、原绝对路径和维护记录。

恢复保留项目、批准、交付和历史证据，但建立新的 `storeId`，归档旧回执/报告/事件表，活动 attempt 标为待核查。Runner 旧日志被隔离，服务 PID 注册和内部 token 不被复用。首次启动恢复库时会生成新的内部 token；浏览器旧草稿/未知命令不得自动提交到新空间。普通服务重启仍沿用原 `storeId`。

旧 worktree 可能保留绝对路径链接，恢复工具不会替旧工作流改写这些关系；历史项目迁移后必须独立核对。不要把旧备份解包覆盖正在使用的目录，也不要为了恢复旧路径而复用旧命令空间。

## 11. 升级、迁移与回滚

升级前停止受管组件并用第 10 节保存完整备份；使用 `git status` 和差异清单记录代码。保留用户项目、历史计划与批准；新项目使用 `protocolVersion:1` 和 `executionBackend:runners`，旧项目按原协议运行，不自动改写历史批准。工作台前端依据项目协议选择写接口，服务器拒绝新版项目走旧的工作流写入口。

回滚代码需要同时核对数据库兼容性。若恢复到较旧数据，用第 10 节创建新状态目录和新命令空间，再核对旧 Runner 的未确认报告。恢复后指定新的 `--state-root`；不要复制测试项目、合成接受或测试批准到生产目录。迁移到另一台 Mac 后重新验证 Codex 目录、Godot 路径和各角色进程权限；这些能力不能由数据库副本继承为通过。

## 12. 日志与故障排查

### 12.1 日志在哪里

服务的启动提示和 Python 错误输出显示在启动它的终端。建议由部署者保护终端记录，并避免将用户概念或图片信息复制到公共工单。 HTTP handler 会关闭默认访问日志，以避免记录概念文本、上传文件名或授权 token。

Godot 验证命令的 stdout、stderr 和诊断保存在候选验证报告中。Godot 本机预览日志位于相应 `previews/` 子目录。 Codex session 的驱动器会保留有限的 stderr 诊断。session 完成不等于验证通过；查看工作台中的作业阶段和验证报告。

策划的原生记录位于状态根下 `planning/<proposal-id>/round-<revision>/session.json`，API 同时保留 `planningEvidence` 和安全的 `planningFailure` 摘要。早期版本缺少 API 诊断的失败记录，可从该原生文件只读补全显示，不改写旧记录。驱动保留有界的原生错误通知和终止 turn 的错误；网络重试通知不会被误判成完成。不要把 stderr 或完整配置粘贴到公开故障报告中，先排除凭据和私有路径。

`diagnostics.itemLifecycle` 最多保留 40 条 item 开始/完成事件，字段仅为事件、已校验类型、phase 和相对耗时，不包含正文、工具输入输出或路径。`commandEvidence.reasoningEffort` 记录服务预设的回合推理强度。原生 `timeout` 保持为 `timeout`，不会为了界面恢复而改成 `completed`。

超时后的问题恢复只适用于完整 JSON 通过对象协议校验、模型状态为 `NEEDS_CLARIFICATION`、受管进程已确认停止、没有审批/协议错误或命令执行证据、只读输入和目录审计通过的情况。系统清空返回的对象文档和任务，仅恢复摘要、问题及待解决项，并以 `planningRecovery.kind=CLARIFICATION_FROM_TIMEOUT` 显示明确提醒。`READY`、残缺 JSON、取消、状态未知和违规写入均不可走此路径，不生成 GM 规格、制作表单或作业。提问回合优先返回问题，完整对象文档在回答后生成，以减少长输出。

较早的失败提案可通过 `POST /api/projects/<projectId>/proposals/<id>/reconcile` 恢复问题。后端先确认资源属于此项目，再确认其仍为项目最新提案、发布基线未变、原进程组已退出，比较原始请求全部不可变字段并核对盘上结果；重复恢复幂等。已有新提案或新发布版本时拒绝旧恢复。回答下一回合时，上一回合的页面诊断和 lease 会清除，原 `round-<revision>/session.json` 继续保留。

只读策划当前使用同一已配置模型、`medium` 推理强度和 420 秒运行上限；通用制作继承已配置模型和推理设置，运行上限为 1800 秒（30 分钟）。这些设置只作用于服务管理的回合，不修改全局 Codex 配置、模型服务地址、凭据或系统代理。若诊断为网络中断，核对当前模型服务的连接；端点可达不代表长时间响应流稳定。只有确认原进程停止后才可手动用原输入创建新提案，旧失败记录继续保留。若原执行状态未知，先对账，禁止自动重投。通过新的策划回合也仍需用户单独确认制作计划。

通用制作未完成时，API 的 `productionFailure` 提供安全摘要，区分运行超时、模型连接、登录/权限和停止未确认；保留原生状态、实际耗时和停止确认。超时期间出现重连会另行标记，不把短暂重连认定为超时的唯一原因。旧作业的摘要在读取时从已有 `sessionEvidence` 推导，数据库中的原失败消息和原生记录不改写。部分源码修改继续留在该作业的隔离工程中，不跳过完成检查、后端验证或用户接受，不生成候选；恢复原输入是新的策划流程，不是继续执行旧 session。

重试请求的网络异常或 HTTP 5xx 属于结果未知。前端锁定原重试按钮并要求刷新工作区核账；只有明确 HTTP 4xx 拒绝或成功核账仍为原失败提案时才允许再次提交。核账不会自动重发策划或制作。

### 12.2 通用只读检查

确认服务器模块可解析启动参数：

```sh
.venv/bin/python -m backend.server --help
```

确认依赖安装在项目虚拟环境。标准 venv 使用 pip：

```sh
.venv/bin/python -m pip check
```

uv 创建的环境使用 uv：

```sh
uv pip check --python .venv/bin/python
```

确认 Git 工作区状态：

```sh
git status --short
```

确认 Godot：

```sh
/Applications/Godot.app/Contents/MacOS/Godot --version
```

确认 Studio HTTP API：

```sh
curl -i http://127.0.0.1:8765/api/workspace
```

### 12.3 常见问题

| 现象 | 可能原因 | 处理步骤 |
| --- | --- | --- |
| 启动脚本提示缺少 Python runtime | 仓库中没有 `.venv/bin/python` | 在仓库根按第 3.3 节创建环境并安装依赖 |
| `Address already in use` | 8765 已被服务或其他程序占用 | 用 `lsof` 查看监听者；确认归属后关闭旧 Studio，或手动换用本机空闲端口 |
| 页面打不开但服务进程存在 | 地址或端口不一致、启动异常 | 查看终端启动行；在同一端口访问 `127.0.0.1`；用 `curl -i` 检查 API |
| `SERVICE_ACTIVE` | 同一状态根已有持锁服务 | 查找使用相同 `--state-root` 的服务进程；不要删除锁文件 |
| `MODE_MISMATCH` | 测试模式与生产模式重用了同一个数据库 | 核对启动 flags 和 state-root；恢复正确工作区备份，不要改数据库标记 |
| `codex CLI not found` 或 session 能力 BLOCKED | CLI 不在 PATH 或应用路径不同 | 检查 `command -v codex`、`codex --version` 和应用安装路径；能力路径不一致时由维护者审查 |
| 官方登录状态未通过 | 当前用户未完成或无法使用 Codex 官方账号认证 | 按官方认证说明处理；该状态不判断自定义 provider |
| Session 无法连接模型 | 当前运行服务用户的 provider 配置或认证不可用 | 核对实际选用的模型提供方和凭据；不要仅凭 `sessionDispatch=READY` 判断认证已通过 |
| Codex 请求授权或工作流进入不确定状态 | app-server 回调需要处理，或协议请求不受支持 | Studio 不提供权限审批等待界面，相关回调会拒绝或失败关闭；不要等待浏览器批准或扩大本机权限 |
| `Godot 4 executable was not found` | Godot 不在固定路径、`GODOT_BIN` 错误或未安装 | 检查 `GODOT_BIN`、PATH、Godot 可执行权限及固定 macOS 路径 |
| 通用 Godot 验证失败 | 对象文档/源绑定不一致、Git 写入越界、存在多余忽略文件、干净导入失败或主场景无法加载 | 查看验证报告中的首条诊断；不要删除审批/GM 服务记录或直接接受候选。修复范围或代码后重新策划和确认。 |
| `GM_INTEGRATION` / GM 规格确认记录复核失败 | 固定 GM 依赖无法加载、阶段记录无法解析或读取 | 检查后端适配器与私有作业记录；作业中的 `gmSpecificationConfirmation` 保留已完成的确认结果。复核异常仍会阻断制作，但不等于用户没有确认。修复服务后由用户进入新的策划、审阅和确认流程，保留旧批准的消费状态与失败历史。 |
| 项目显示 `UNCERTAIN` | 服务重启时没有确认原制作或验证进程停止 | 通过“向服务对账”检查租约；确认进程组不可观测时保留阻塞并升级处理 |
| 上传图片被拒绝 | 图片超限、类型/MIME 不符、编码损坏或超过像素限制 | 使用有效 PNG/JPEG/WebP，单张不超过 5 MiB，提案最多六张 |
| 预览按钮不可用 | 候选没有形成、通用验证未通过或本项目已有预览 | 先检查候选与报告状态并关闭本项目现有预览。技术 PASS 仍需用户运行候选，且不代表玩法要求已经通过。 |
| 恢复备份后 Git worktree 错误 | 只恢复了部分文件或路径发生变化 | 停止服务，核对完整备份和原绝对路径；不要手工修复数据库/worktree 指针 |

### 12.4 需要提供给维护者的信息

记录软件版本、macOS 版本、Python 版本、Godot 版本、启动命令中的非敏感 flags、错误发生时间和作业 ID。 分享作业报告前检查其是否包含用户概念、上传文件路径或私人项目内容。只提供解决问题所需的最少内容。 绝不要把 `/api/session` 响应中的 token、完整私有状态目录或用户图片发到公开问题跟踪系统。

## 13. 维护者验证流程

本节是版本更新后的检查清单。命令仅供维护窗口使用；本轮实际回归见[实施记录](STUDIO-IMPLEMENTATION-20261012.zh-CN.md)。先核实代码版本并确认工作区改动：

```sh
git status --short
```

核对部署版本和相关文档中的基准是否一致。 检查后端单元测试命令。仅在隔离的开发环境中执行：

```sh
.venv/bin/python -m unittest discover -s backend/tests -p 'test*.py'
```

共享 Schema parity 测试另需 jsonschema；缺少时会明确跳过。验收记录必须区分实际通过与跳过。本轮用了具备该依赖的 Python 3.11 解释器完成这些检查。

前端 DOM/浏览器测试依赖前端开发依赖。执行前先阅读仓库内前端说明，并确保所用状态和浏览器都是测试用途。未来真实 session 探针仍必须使用单独 `--state-root` 与 `--test-data`；不要把测试数据库、测试候选或合成接受记录合并到生产工作区。任何制作或验证测试都应确认不会写入用户真实项目，且测试决策保留 `testData=true` 与 `productionAuthorized=false`。部署冒烟检查应仅验证静态页面和只读 `/api/workspace` 响应。不要以启动真实制作 session 作为简单健康检查。更新后重新核对生产启动命令、默认状态路径、监听地址、Godot 和 Codex 能力状态。任何新增远程部署、多用户认证、数据库迁移、权限策略、OS 沙箱或 3D/插件/音频等适配器都超出当前本机部署边界，需要单独设计与安全审查。fixture 专项玩法探针通过不等于用户试玩当前候选；通用候选的玩法证据仍需用户独立体验。

## 14. 部署完成检查表

- [ ] 仓库检出版本已核对为经批准的检查点。
- [ ] Python 3.11+、Git、Godot 4 和 Codex app-server 已在本机确认。
- [ ] 新版 ProjectRunner 使用前，固定路径的 Apple Command Line Tools clang/SDK 与 root-owned `/etc/ssl/cert.pem` 已存在；工作台不会自动安装或寻找替代 CA。
- [ ] 当前运行服务的 macOS 用户已配置可用的模型提供方与认证；已知 sessionDispatch READY 仅表示发现 CLI，不代表认证验证通过。
- [ ] `.venv/` 使用本仓库 `backend/requirements.txt` 安装依赖。
- [ ] Godot 实际 CLI 可用，且核对 `GODOT_BIN` 与固定 macOS 预览路径差异。
- [ ] 生产启动没有 `--test-data`，且生产 `--state-root` 与测试目录不同。
- [ ] Studio 仅经 `127.0.0.1` 打开，端口未暴露到外部网络。
- [ ] `/api/workspace` 返回预期工作区和能力状态。
- [ ] `.workbench/` 或自定义 state-root 位于受保护的本机磁盘。
- [ ] 已记录负责人、关停方式、备份位置和恢复联系人。
- [ ] 完整备份流程明确为停服后操作，且包含数据库、附件、Git 仓库和 worktree。
- [ ] 所有实际游戏制作、规格批准和候选接受均由相应用户在工作台完成。

## 15. 当前已知限制

通用路径已按稳定对象 ID、字段、关系、源绑定和需求建立流程，但当前范围只涵盖 Godot 4 的 2D GDScript 工程。插件、编辑器扩展、任意二进制资源、音频制作、远程协作、多人账号、导出签名和商店发布都不在当前写入或部署能力内。参考图片可以送入策划/制作流程，但上传本身不等于生成、许可核对或导入美术。

技术报告只说明它实际运行的范围检查、干净导入和后端拥有的主场景冒烟；主场景启动不能证明所有玩法正确，未被自动观察的要求仍需用户体验。r3 与 Bridge Runner / Light Grid 记录属于隔离测试数据，不能代替当前候选的体验、生产批准或新版角色权限证明。详细的当前边界证据与整体验收状态见[Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)；该报告不会覆盖[初次全功能验收](STUDIO-ACCEPTANCE-20261012.zh-CN.md)保存的失败历史。

新版 `objects-v1` Godot 子进程现有受测 deny-default 文件/网络/进程边界，CA 运行时依赖固定系统证书和 CLT。四项角色探针与 Runner 注册仅在受测 macOS、stateless custom provider、Godot 4.6.3 配置中通过；启动注册按本机新鲜证据派生能力，非远程 attestation。实际操作者体验/视觉验收仍为 `NOT_TESTED`，没有用户接受的正式生产候选。请求的 effort=`max` 不是实际回合强度观测，完整计费未知，也不能推断其他模型、平台或 provider 配置。旧 collect-loop 工程继续走原有 `backend/verification.py` 路径：它在当前服务用户权限中运行 Godot，未获得新版 sandbox，旧项目和批准也不会自动迁移。

## 16. 实现参考

- [本机工作台说明](../backend/README.zh-CN.md)
- [服务入口与 CLI 参数](../backend/server.py)
- [协调器状态目录、权限和恢复标记](../backend/coordinator.py)
- [协调器项目、作业与隔离 worktree](../backend/coordinator.py)
- [协调器预览与关停](../backend/coordinator.py)
- [Codex app-server 驱动](../backend/codex_driver.py)
- [旧 collect-loop 验证器（普通用户权限执行）](../backend/verification.py)
- [通用对象工作流与验证器](../backend/generic_workflow.py) · [通用验证器](../backend/general_verification.py)
- [新版 Godot 私有 runtime 与 sandbox](../runners/godot_runtime.py) · [固定 CA interposer 源码](../runners/godot_ca_interposer.m)
- [Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)
- [GM non-pk 来源与审批适配器](../backend/general_gm_integration.py) · [GM non-pk 源码说明](../sources/GodotMaker-non-pk/README.zh-CN.md)
- [GameStudio 参考版本 0722921](https://github.com/openai/plugins/tree/0722921d5542fc593105c27bd52630babd8b8c2a/plugins/game-studio)
- [Git 校验迁移与本机安装记录](../LOCAL-SETUP-GIT.zh-CN.md)
- [仓库执行约束](../AGENTS.md)

## 2026-10-20 Godot 工程制作前置检查

所有制作入口执行同一标准路径：创建或载入批准工程 → 内置插件完整且启用 → 隔离普通编辑器启动 → MCP 初始化/工具与工程身份核对 → 确认编辑器停止 → 启动制作。首次制作、返修与参数迭代均重新检查；规划阶段不启动编辑器。运行要求包含可执行的 Godot 4 和 macOS `sandbox-exec`。配置 `GODOT_BIN` 或 `GODOT_PATH`，就绪报告保存在 Runner journal 同级 `editor-mcp/<attemptId>/readiness.json`，本地保留流程保存在作业目录 `editor-mcp/readiness.json`。

检查失败或编辑器停止未确认时不得绕过检查派发制作；后者保持项目占用，由受信操作员核实报告中的原进程组。不得连接未知端点、杀死其他编辑器或使用旧 PASS 代替本轮检查。脚手架操作、隔离策略与命令见 [Godot MCP 标准路径](GODOT-MCP.zh-CN.md)。此检查不代表游戏可玩或用户已接受。

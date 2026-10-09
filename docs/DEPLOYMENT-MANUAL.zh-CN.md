# Ptah 本机工作台部署与维护说明书

本文面向在 macOS 上安装、启动和维护 Ptah 本机工作台的部署者。本文对应 r4-local-1 工作流和实现检查点 `13b3a03`。开始维护前，请先确认实际检出的 Git 版本。用户在页面中的完整操作步骤见[工作台用户说明书](USER-MANUAL.zh-CN.md)。

本手册说明当前已实现的本机能力。备份、升级、恢复等没有专用程序支持的操作会明确标为人工运维步骤。

文档日期：2026-10-09。[返回说明书入口](README.zh-CN.md)。

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

Ptah 工作台由一个本机 Python HTTP 服务和静态浏览器前端组成。前端从同一服务的 `/studio/` 路径加载，通过同源 `/api` 与服务交互。 浏览器负责录入概念、选择图片用途、回答澄清问题、编辑受支持参数、提交制作表单和审阅候选结果。

后端拥有项目路径、Git 仓库、隔离 worktree、Codex session 启动方式、验证命令、审批记录和发布快照。 浏览器不能提交本机 cwd、shell 命令、程序路径或执行配置。工作目录和验证命令由服务器代码固定管理。

制作完成、引擎验证通过和用户接受是三个不同状态。模型报告 `completed` 只表示回合结束，不能代替独立验证或用户决定。

当前可用适配器只支持收集挑战模板。它不是通用游戏生成平台，也不支持随意指定玩法并自动转化为任意游戏。 相关结构与使用范围见[后端工作台说明](../backend/README.zh-CN.md)和[工作流实施记录](WORKFLOW-IMPLEMENTATION.zh-CN.md)。

## 2. 支持范围与部署前提

### 2.1 支持的运行环境

本手册覆盖当前已核实的 macOS 本机部署：同一台电脑上运行服务、Codex app-server 和 Godot。 服务默认只绑定 `127.0.0.1`。浏览器必须在同一台电脑访问 `http://127.0.0.1:8765/studio/`。 应用当前没有 TLS、远程用户认证、多人权限管理或网络部署入口。不要把它暴露到局域网或公网。

服务端使用 Unix 文件锁 `fcntl`，当前工程运行路径、Codex app-server 路径和预览 Godot 路径均以本机 macOS 配置为基准。 Linux、Windows、容器、反向代理部署和共享服务器运行没有经过本工作流验证，不能视为受支持配置。

### 2.2 必需组件

需要 Python 3.11 或更高版本、Git、Codex CLI/app-server，以及 Godot 4。当前运行服务的同一 macOS 用户必须已配置可用的模型提供方与认证。服务不会自行登录或生成凭据。 Codex 的官方账号认证与自定义 provider 配置是不同路径：`codex login status` 反映 Codex CLI 官方登录状态，官方账号未登录不等于自定义 provider 必定不可用。官方认证说明见[Codex Authentication](https://developers.openai.com/codex/auth/)。本次无法在线核验该页面的最新内容，请以官方页面为准。

当前工作流通过本机 CLI 启动 app-server，使用运行服务的同一用户环境和配置。`sessionDispatch=READY` 只表示找到了 CLI，不会验证 provider 凭据、登录或真实模型调用是否成功。

当前项目的 Godot 已安装在 `/Applications/Godot.app`。部署记录报告版本 `4.6.3.stable.official.7d41c59c4`。

服务使用项目本地 `.venv/` Python 环境。不要让不同项目或系统 Python 共用此虚拟环境。 Python 运行时依赖见[`backend/requirements.txt`](../backend/requirements.txt)。当前列出的唯一第三方运行时包是 `Pillow==12.3.0`。Node.js/npm 只用于前端开发与测试，启动静态 Studio 不需要它们。 Godot 和 Codex app-server 是独立的本机程序，不由 Python requirements 安装。

### 2.3 代码位置和检查点

工作流代码、静态前端和受控模板必须一起保留在同一份仓库检出中。 版本基准为 `13b3a03` / `r4-local-1`。可用 `git status --short` 检查工作区是否含未提交修改。 此版本的后端入口为[`backend/server.py`](../backend/server.py)，工作流持久化和任务编排位于[`backend/coordinator.py`](../backend/coordinator.py)。 模型 session 驱动器位于[`backend/codex_driver.py`](../backend/codex_driver.py)，受控 Godot 验证位于[`backend/verification.py`](../backend/verification.py)。

应用级部署记录和 Git 校验迁移说明见[`LOCAL-SETUP-GIT.zh-CN.md`](../LOCAL-SETUP-GIT.zh-CN.md)。 根目录[`AGENTS.md`](../AGENTS.md)规定构建期间禁止单独 SHA/MD5 哈希检查，当前维护应使用 Git 提交、Git 管理的对象身份和差异审阅。本说明书使用 Git 记录版本、变更范围与差异。

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

预期版本为 `4.6.3.stable.official.7d41c59c4`。其他 Godot 4 版本尚未在此版本部署记录中确认。 验证器解析顺序为 `GODOT_BIN`、PATH 中的 `godot`、最后回退到 `/Applications/Godot.app/Contents/MacOS/Godot`。 如果需要为当前服务进程临时指定另一个 Godot 路径，可在同一终端设置 `GODOT_BIN` 后启动服务。

```sh
studio_godot_bin="/Applications/Godot.app/Contents/MacOS/Godot"
export GODOT_BIN="$studio_godot_bin"
```

本机安装记录提到 `GODOT_PATH`，但当前 `backend/verification.py` 使用的是 `GODOT_BIN`，不读取 `GODOT_PATH`。 Godot 能够被验证器解析，不代表预览路径也可在其他安装布局使用。当前预览和能力探测代码固定检查 macOS 应用路径。

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

驱动器以 `codex app-server --stdio` 启动本机 session，并使用运行服务用户的环境和配置。服务不会自行登录或生成凭据。`codex login status` 只报告官方 Codex 登录状态，不证明自定义提供方是否可用。`sessionDispatch=READY` 只证明找到 CLI，不验证认证或模型调用。实际 session 无法连接提供方时，先检查所选 provider 的配置和认证。

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

浏览器前端从同源 `/api/session` 获取短期工作台 token 和操作员身份。写入请求必须使用同源请求和 token。 浏览器刷新后可从后端恢复作业和已确认表单。草稿保存在浏览器 IndexedDB，并按项目和发布版本隔离。 浏览器草稿不等于后端已确认表单。升级浏览器或清理站点数据可能清除本地草稿；已保存的后端工作流记录保存在状态目录。 发布版本变化后，草稿重关联需要前端展示差异并由用户确认。

## 6. 用户手册与部署者交接

用户操作流程独立维护在[Ptah 工作台用户说明书](USER-MANUAL.zh-CN.md)，包含概念输入、澄清、表单确认、候选审阅、迭代和作业状态说明。

部署者交付时请告知用户本机 Studio URL、当前连接的是生产还是测试工作区，以及工作流只支持收集挑战模板。若页面出现“测试工作区”提示，确认和发布都只属于测试记录。

用户需要了解图片用途、支持参数、确认含义或错误状态时，请交付用户说明书；不要让部署人员以口头确认代替用户在正式工作台做出的决定。Godot 本机预览一次最多运行 15 分钟，同时只允许一个预览进程；到时服务会结束预览。

## 7. 安全和隐私边界

### 7.1 本机网络限制

服务只监听回环地址 `127.0.0.1`，并检查 Host、Origin 和 fetch-site 请求信息。 所有改变状态的请求还必须携带服务生成的工作台 token。服务同时返回基本安全响应头。 这些控制服务于同一台电脑上的本机使用。它们不构成远程用户认证、TLS 加密或多租户安全机制。 不要配置网络端口转发，也不要将服务地址发布到公网或局域网。

### 7.2 本机数据权限

后端将状态根目录权限设置为 `0700`，SQLite 主数据库文件设置为 `0600`。 上传图片文件设置为 `0600`。这些模式限制同一台电脑上的其他普通用户读取工作数据。 状态目录内的数据还受当前 macOS 用户、磁盘备份、设备加密和管理员权限影响。请将该目录纳入组织的本机数据保护政策。 不要把 `.workbench/` 上传到公共文件托管、工单或日志收集系统。图片和项目内容可能包含用户提供的私有信息。

### 7.3 受控执行

生产工作流通过服务器预设的 `workspace-write` 沙箱和 `on-request` 策略启动 Codex session，但 Studio 没有等待用户点击授权的界面。app-server 的文件变更和命令执行授权回调会被显式拒绝，权限请求不会获批；未知回调失败关闭。作业可能因此失败或进入待核实状态，不能等待用户在 Studio 弹窗批准。 程序限制制作文件范围，并将正式验证作为独立阶段。模型不能改写服务端项目路径或验证命令。不要通过扩大本机权限解决路径或依赖配置错误。

“本机工作台”描述的是服务、项目管理和 Godot 验证的位置。Codex 使用当前用户配置的模型提供方；如果该提供方在远端，概念、制作表单及参考图会按该配置提交给模型服务。它不代表模型推理完全离线。Git 身份与范围审计用于本机协作变更检测，不能代替操作系统隔离或远程身份认证。

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

项目 Git 仓库和 worktree 由数据库记录、Git元数据和服务路径共同关联。移动或重命名状态根目录可能使 worktree 的管理链接失效。 **恢复工作区时优先还原到原来的绝对路径。** 若确实要迁移路径，当前实现没有自动修复 Git worktree 链接的命令，应作为单独迁移工作审查处理。

## 9. 正常关停与进程状态

### 9.1 正常关停

在运行服务的终端按 `Control-C`。服务收到 KeyboardInterrupt 后关闭 HTTP 监听器并调用协调器清理逻辑。 协调器会发出取消请求、等待作业线程最多十秒，并停止由服务管理的预览进程。 这个十秒等待是一次线程 join 上限，不应理解为所有 session 或后代进程必定在十秒内结束。 若已有执行线程仍然存活，协调器会保留数据库连接和服务锁，不主动释放同一状态目录的独占权。 停止后，使用端口检查确认 8765 已无监听者：

```sh
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

若没有输出，只能说明该端口没有监听者。它不能证明没有所有残留的 Codex 或 Godot 子进程。

### 9.2 作业未知时

服务退出后作业线程或受管进程可能处于待确认状态。若端口释放但重新启动报告 `SERVICE_ACTIVE`，不要删除 `service.lock` 或 SQLite 文件。 先确认是否还有另一个服务进程使用相同的 `--state-root`，再检查对应工作流记录中的租约信息。

在现有 Studio 页面重新启动后，使用“向服务对账”。对账只检查原受管进程租约是否消失，不会替用户重投制作，也不应杀掉无关进程。 如果进程状态无法观测、租约信息缺失或系统重启后 PID 关系无法确认，保留项目为受阻状态并升级人工运维判断。 不要把 `UNCERTAIN` 当成一般失败后按“重试”即可处理的错误。

## 10. 完整备份与恢复

本项目没有内建备份、恢复、数据库迁移或备份一致性检查命令。以下命令是建议的人工运维流程，不是本次执行过的备份。

### 10.1 备份前

先通知正在使用工作台的用户暂停操作，并在服务终端执行正常关停。 使用端口检查确认 HTTP server 停止，再核对没有服务进程继续写入该状态根目录。 不要在服务运行时仅复制 `state.sqlite3`。SQLite 可能正在通过 WAL 文件记录已提交事务。 状态目录可能包含图片、源项目、Git对象、worktree、候选证据和审批状态。只备份数据库无法完整恢复工作台。

备份目标应是受控、加密且空间足够的本机磁盘或组织批准的备份位置。不要将私有用户数据上传到未经批准的服务。

### 10.2 创建完整归档

下面示例适用于默认 `.workbench/`。请在仓库根目录执行，并先把备份目标改成实际存在且受保护的位置。

```sh
studio_state_root="$PWD/.workbench"
studio_state_parent="$PWD"
studio_backup_dir="/Volumes/EncryptedBackup/ptah-studio"
studio_stamp="$(date +%Y%m%d-%H%M%S)"
studio_backup="$studio_backup_dir/workbench-$studio_stamp.tar.gz"
```

先确认变量和路径指向预期目录：

```sh
printf 'State: %s\nBackup: %s\n' "$studio_state_root" "$studio_backup"
```

确保备份目录已存在：

```sh
mkdir -p "$studio_backup_dir"
```

将整个默认状态目录归档：

```sh
tar -czpf "$studio_backup" -C "$studio_state_parent" .workbench
```

归档后记录软件 Git 版本、备份日期、原状态绝对路径和执行人，保存到备份位置的运维记录中。 不要在生产状态目录上运行探针或测试来“验证”备份。此手册未提供专用还原演练工具。

### 10.3 自定义状态根目录

若服务使用自定义 `--state-root`，先写入实际绝对路径，再从该路径派生父目录和末级目录名。以下归档示例只读源状态目录并创建 tar 文件：

```sh
studio_state_root="/absolute/path/to/PtahPrivateState"
studio_state_parent="$(dirname "$studio_state_root")"
studio_state_name="$(basename "$studio_state_root")"
studio_backup="/absolute/path/to/protected-backup/state-root.tar.gz"
tar -czpf "$studio_backup" -C "$studio_state_parent" "$studio_state_name"
```

执行前确认 `studio_state_root` 是实际私有状态目录、`studio_backup` 指向受保护的备份介质，且服务已经完全停止。归档内容会以 `studio_state_name` 作为顶层目录保存。

恢复时使用相同源归档，并把父目录设置为应还原到的原父路径：

```sh
studio_state_parent="/original/absolute/path/parent"
studio_backup="/absolute/path/to/protected-backup/state-root.tar.gz"
tar -xzpf "$studio_backup" -C "$studio_state_parent"
```

若状态目录在不同绝对路径恢复，数据库记录和 Git worktree 管理链接可能不再一致；当前程序没有路径重写或迁移命令。

### 10.4 恢复到原路径

先停止当前服务，并将现有状态目录移到隔离备份位置；不要直接覆盖一个仍在使用的状态库。准备仓库根目录（即 `.workbench/` 的父目录），再从可信备份归档解包。以下示例恢复默认 `.workbench/`：

```sh
studio_restore_parent="/absolute/path/to/repository"
studio_backup="/Volumes/EncryptedBackup/ptah-studio/workbench-YYYYMMDD-HHMMSS.tar.gz"
```

检查变量已经指向正确备份和仓库根目录（即 `.workbench/` 的父目录）后执行：

```sh
tar -xzpf "$studio_backup" -C "$studio_restore_parent"
```

随后确认恢复出的 `.workbench/` 在原来的绝对路径，并由同一 macOS 用户启动相同软件版本。 后端会强制重新设置状态目录为 `0700`、数据库为 `0600`。如果备份恢复的文件所有者不是运行服务的用户，先通过常规受管备份流程纠正所有者；本手册不建议扩大系统权限。 首次启动后只检查工作区是否可读和项目状态是否一致。不要直接接受候选或修改发布状态来掩盖恢复问题。

### 10.5 恢复限制

状态数据库保存审批和发布元数据，Git 仓库保存项目版本，worktree 元数据保存隔离工作区关联；三者必须来自同一时间点的完整备份。 无法保证单独恢复数据库、项目仓库或某一个 job 目录能够组成一致工作区。 尚无自动化的备份校验或灾难恢复演练记录。部署者需自行制定备份保留、加密、异地保护和恢复演练政策。 如果无法确定原租约进程是否结束，恢复后仍可能出现 `UNCERTAIN`。恢复流程不会自动授权重跑或接受任何候选。

## 11. 升级、迁移与回滚

### 11.1 升级前准备

当前交付没有独立数据库 schema 版本迁移命令，也没有对不同应用版本间状态数据库向前或向后兼容的保证。 升级前记录当前 Git 检查点和工作区状态：

```sh
git status --short
```

停止服务，按第 10 节完整备份状态根目录，并单独保留正在部署的软件 Git 版本。 不要在有运行中、待审阅或 `UNCERTAIN` 作业时升级。先让用户处理已知候选，并按第 9 节确认进程状态。 将新软件检出到可回退的 Git 检查点，再用原来的状态根路径启动。不要同时改变代码版本、状态目录路径和 Python 环境。

### 11.2 数据库兼容的现实限制

当前协调器启动时使用 `CREATE TABLE IF NOT EXISTS` 初始化表，不代表已有字段、JSON payload 或业务状态跨版本兼容。 代码没有对既有数据库执行编号迁移，也没有受支持的降级程序。新版本如果写入旧版本不认识的状态，直接回退可导致读取或业务错误。 不要把升级试运行连接到唯一生产数据库后，再假设切回旧代码即可恢复。先有完整备份，再决定升级窗口。

### 11.3 回滚

如果新代码在写入生产状态前启动失败，可停止服务并检出原软件版本后再启动。 如果新版本已经写入状态数据库，最可靠的回滚路径是停止服务、恢复升级前的完整状态备份、检出对应的软件版本，再启动。 恢复旧数据会丢弃升级后产生的工作流记录。先保存故障日志和需要保留的候选信息，再执行恢复。 在没有单独审核迁移方案时，不要手工编辑 SQLite 表、直接拼接数据库、删除 job 记录或改写审批位。

### 11.4 迁移到新 Mac

迁移前在旧 Mac 停止服务，并按第 10 节备份完整状态根目录。软件仓库应为已提交的经审阅版本；Git bundle 不包含未提交文件：

```sh
studio_repo_root="/absolute/path/to/original/repository"
studio_software_bundle="/path/to/transfer/ptah-software.bundle"
git -C "$studio_repo_root" status --short
git -C "$studio_repo_root" bundle create "$studio_software_bundle" --all
```

将软件 bundle 和第 10 节创建的完整状态归档安全地传到新 Mac。在新 Mac 把仓库克隆到**与旧 Mac完全相同的绝对路径**：

```sh
studio_repo_root="/absolute/path/to/original/repository"
studio_software_bundle="/path/to/transfer/ptah-software.bundle"
git clone "$studio_software_bundle" "$studio_repo_root"
cd "$studio_repo_root"
git status --short
```

不要把示例路径原样当作真实路径。目标仓库父目录须由当前用户预先创建。重建 Python 环境；标准 venv 可用 pip：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

若采用 uv：

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
```

确认 Godot 已安装于固定 macOS 路径，并把状态归档解包到**仓库根目录**。该归档示例内的顶层目录为 `.workbench`：

```sh
studio_state_root="$studio_repo_root/.workbench"
studio_backup="/path/to/transfer/workbench-backup.tar.gz"
/Applications/Godot.app/Contents/MacOS/Godot --version
tar -xzpf "$studio_backup" -C "$studio_repo_root"
```

这里的解包父目录必须是 `studio_repo_root`，不能用仓库的上级目录，否则 `.workbench` 会落在仓库外，服务会启动空状态库。自定义 `--state-root` 应按第 10.3 节用原父目录和目录名恢复到原绝对路径。

启动服务并只读检查工作区：

```sh
.venv/bin/python -m backend.server --port 8765 --state-root "$studio_state_root"
```

浏览器打开 `/studio/`，用 `/api/workspace` 确认预期项目、发布和作业状态。worktree 元数据可能引用仓库绝对路径，迁移到不同路径没有自动修复命令。Linux/Windows、远程或多人部署也没有当前支持流程。

## 12. 日志与故障排查

### 12.1 日志在哪里

服务的启动提示和 Python 错误输出显示在启动它的终端。建议由部署者保护终端记录，并避免将用户概念或图片信息复制到公共工单。 HTTP handler 会关闭默认访问日志，以避免记录概念文本、上传文件名或授权 token。

Godot 验证命令的 stdout、stderr 和诊断保存在候选验证报告中。Godot 本机预览日志位于相应 `previews/` 子目录。 Codex session 的驱动器会保留有限的 stderr 诊断。session 完成不等于验证通过；查看工作台中的作业阶段和验证报告。

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
| Godot 验证失败 | 规则、导入、Git 改动范围或闭环检查失败 | 在 UI 打开验证报告，按第一条失败诊断处理，不要直接接受候选 |
| 项目显示 `UNCERTAIN` | 服务重启时没有确认原制作或验证进程停止 | 通过“向服务对账”检查租约；确认进程组不可观测时保留阻塞并升级处理 |
| 上传图片被拒绝 | 图片超限、类型/MIME 不符、编码损坏或超过像素限制 | 使用有效 PNG/JPEG/WebP，单张不超过 5 MiB，提案最多六张 |
| 预览按钮不可用 | 候选尚未验证通过或预览已在运行 | 只对状态为 `READY_FOR_REVIEW` 或 `PUBLISHED` 且验证 PASS 的玩法候选预览；先关闭本机现有预览 |
| 恢复备份后 Git worktree 错误 | 只恢复了部分文件或路径发生变化 | 停止服务，核对完整备份和原绝对路径；不要手工修复数据库/worktree 指针 |

### 12.4 需要提供给维护者的信息

记录软件版本、macOS 版本、Python 版本、Godot 版本、启动命令中的非敏感 flags、错误发生时间和作业 ID。 分享作业报告前检查其是否包含用户概念、上传文件路径或私人项目内容。只提供解决问题所需的最少内容。 绝不要把 `/api/session` 响应中的 token、完整私有状态目录或用户图片发到公开问题跟踪系统。

## 13. 维护者验证流程

本节是版本更新后的检查清单。命令仅供维护窗口使用，本次编写手册时没有重复运行测试。 先核实源代码来自已审阅的 Git 提交，并确认没有非预期工作区改动：

```sh
git status --short
```

核对部署版本和相关文档中的基准是否一致。 检查后端单元测试命令。仅在隔离的开发环境中执行：

```sh
.venv/bin/python -m unittest discover -s backend/tests -p 'test*.py'
```

前端 DOM/浏览器测试依赖前端开发依赖。执行前先阅读仓库内前端说明，并确保所用状态和浏览器都是测试用途。 真实 session 探针只能使用单独 `--state-root` 与 `--test-data`。不要把测试数据库、测试候选或合成接受记录合并到生产工作区。 任何制作或验证测试都应确认不会写入用户真实项目，且测试决策保留 `testData=true` 与 `productionAuthorized=false`。 部署冒烟检查应仅验证静态页面和只读 `/api/workspace` 响应。不要以启动真实制作 session 作为简单健康检查。 更新后重新核对生产启动命令、默认状态路径、监听地址、Godot 和 Codex 能力状态。 任何新增远程部署、多用户认证、数据库迁移、权限策略或游戏适配器都超出当前 r4-local-1 本机部署基准，需要单独设计与安全审查。

## 14. 部署完成检查表

- [ ] 仓库检出版本已核对为经批准的检查点。
- [ ] Python 3.11+、Git、Godot 4 和 Codex app-server 已在本机确认。
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

当前只提供一个受控 collect-loop 模板，三个规则参数范围固定。其他题材、任意机制、自动素材生产和通用多模态策划尚未接入。 后端接受图片作为参考输入，但模板使用程序化图形；上传图像不会自动变成游戏运行资源。 服务只面向本机单用户使用。项目没有提供网络部署、远程认证、多用户角色、备份恢复程序或自动数据库迁移。 Godot 能力检查、预览路径与 verifier 的查找逻辑不完全一致。非标准 Godot 安装布局需要维护者逐处确认。 本工作流执行的模板验证不代表整个 GodotMaker/GM pipeline 的完整认证，也不执行导出、签名、发布或发行验收。 人类对游戏概念、规格和最终候选的判断仍是独立步骤。任何自动测试报告都不能冒充真人接受。

## 16. 实现参考

- [本机工作台说明](../backend/README.zh-CN.md)
- [服务入口与 CLI 参数](../backend/server.py)
- [协调器状态目录、权限和恢复标记](../backend/coordinator.py)
- [协调器项目、作业与隔离 worktree](../backend/coordinator.py)
- [协调器预览与关停](../backend/coordinator.py)
- [Codex app-server 驱动](../backend/codex_driver.py)
- [Godot 查找和固定验证流程](../backend/verification.py)
- [Godot 路径解析](../backend/verification.py)
- [Git 校验迁移与本机安装记录](../LOCAL-SETUP-GIT.zh-CN.md)
- [仓库执行约束](../AGENTS.md)

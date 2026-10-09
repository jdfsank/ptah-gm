# 本地 Codex 完整交接包

本包将已完成的 DNA Workbench v0.6 前端、实际 GodotMaker non-pk 框架、实际 Velvet Eclipse Godot 示例，以及将前端合并回源系统的分阶段方案一起交接。打包日期：2026-10-08。此次只整理交付，没有实现新功能，没有重新发布 Site。

## 从这里开始

1. 将本 ZIP 解压到一个新目录，勿覆盖已有项目。用本地 Codex 打开这个解压目录。
2. 将 `COPY-TO-CODEX.txt` 的全文复制给 Codex。第一轮只核对环境、用户当前仓库、版本和差异；确认实际目标工程后建立 checkpoint。
3. 用 `python3 tools/verify-package.py` 检查逐文件 SHA-256；再用 `python3 tools/unpack-sources.py` 解开两份独立源包（框架仅移除四个文档演示 GIF）。脚本从自身位置解析根目录，只写不存在的 `sources/`，不会覆盖用户工程。
4. 阅读 `docs/MERGE-PLAN.zh-CN.md`、`docs/REMAINING-WORK.zh-CN.md` 和 `docs/ACCEPTANCE-MATRIX.zh-CN.md`。先证明一个已有小改动的真实本地闭环，再开发 transition 新机制。

## 目录

- `frontend/`：v6 完整已提交源码、dist、bridge、tests、lockfile、历史验证报告；不是仅截图或前端构建产物。
- `history/frontend-v6.bundle`：前端完整可达 Git 历史；`frontend-commits.txt` 为提交列表。
- `source-zips/GodotMaker-non-pk-c16d4bb-code.zip`：实际框架，解压为 `sources/GodotMaker-non-pk/`。
- `source-zips/velvet-eclipse-source-v2-delivery.zip`：含 `.agents`、Godot 项目、游戏脚本、资源、测试和 PLAN 的实际示例，解压为 `sources/velvet-eclipse/`。
- `evidence/`：原框架验证摘要和已有证据 ZIP；它们是历史证据，不是本次 UI→Codex→GM→Godot 新提交的验收。
- `docs/`：合并方案、剩余任务、验收矩阵、版本与源包清单。
- `SHA256SUMS`：除本清单自身以外的每个交付文件；`tools/verify-package.py` 可在 macOS/Linux 用 Python 检查。

## 版本与事实边界

前端 HEAD 为 `fe1fc88ee4fe4a8d5ce32493b76e8d4c20dd2af1`，package 0.6.0；源码工作树打包时干净。框架为 `c16d4bb8091af784fc801ca6734e79d6b17b136e`。示例以源 ZIP 的 SHA-256 和文件清单标识，不猜测未提供的 Git commit。

v6 完成 183 个稳定目标的评论入口、导航/搜索/hash 定位和完整冻结预览。v5 支持 transition 的 unset/none/preset 编辑契约；共享 preset 只读，mask 资源未绑定。在线版只是模拟回执。GM v2 的 readiness、目标映射、范围、digest、diff 校验及人工正式证据导入已有有界实现；逐项 semantic target/task/assertion 证明仍 BLOCKED。真实浏览器验收、真实模型联动 Godot、真 TTY 人工门没有在这条端到端链上实证。

当前不是完整自动闭环。已有测试成功不等于真实模型执行、Godot 功能成功或用户验收。详见 `frontend/docs/VALIDATION-v6.md` 和 `frontend/docs/chain-boundaries-v5.md`。

## 已核实的源版本差异

前端 source-lock 共 69 项，与本包原始 Velvet v2 源 ZIP 比较，67 项匹配，两项不匹配：`scripts/ui/hud.gd`、`scripts/ui/title_screen.gd`。准确 SHA 见 `docs/SOURCE-BASELINE-DIFFERENCES.json`。此包保存各自真实已交付版本，不静默改源、不改 lock。真实模式会因 source freshness 不一致而阻塞，须先在本地审阅这两处差异及适配器影响，再建立新的已审基线；不要只刷新 hash 来绕过。示例缺少真实 workbench-targets.json，也必须按计划补齐。

## 本地预览

先检查 `node --version`、`npm --version`、`python3 --version`；jsdom 30.1.2 当前 lock 要求 Node ^22.22.2、^24.15.0 或 >=26.0.0，以 package-lock.json engines 为准。Python 3.10+；原测试 Python/Godot 版本见 evidence。已带 dist，预览不需安装依赖：

```sh
cd frontend
python3 bridge/server.py
```

打开打印的 loopback 地址，默认 demo，不调用模型。按 Ctrl+C 停止。运行源码构建和回归时，在前端目录执行 `npm ci`、`npm run build`、`npm run check`、`npm test`；安装需本机网络，不包含 node_modules。不要把静态 Site 当成本机入口。

真实模式在准备好项目、映射、已审规格、兼容 Codex 和空闲同工程线程之后，才按 `frontend/docs/LOCAL-SUBMIT.md` 配置。THREAD_ID 和绝对项目/state 路径必须本机新解析，不能照抄历史日志。默认绑定不是自动选择权限；禁止自动提权或代答审批。

首轮 Godot 期望核对 `4.6.3.stable.official.7d41c59c4`；doctor 接受 >=4.4 不等于所有依赖兼容。当前 bridge 用 fcntl，支持路径为 macOS/Linux；原生 Windows 未建立兼容结论。依赖锁文件已保留，安装物、虚拟环境和生成缓存没有交付。

## 保留历史与保护新代码

frontend 是源码快照，没有嵌入 .git 配置或登录信息。如需历史，在解压根目录执行 `git clone history/frontend-v6.bundle ../frontend-with-history`；不要 clone 到用户既有仓库。源 ZIP 不含原仓库 .git，按清单比较后再有选择地整合。用户现有工程若比示例更新，示例只作证据和参考，不替换其代码或资源。历史报告中的旧环境路径是出处，不是可直接执行的本地路径。

## 旧环境路径与输入素材

`reference-inputs/` 补齐本次交付可用的 8 张原始参考 PNG，按原文件名查找。源示例的 ASSETS.md/SCENES.md 可能保留原云端绝对路径；它们是历史出处，请解析到本包 reference-inputs 或已确认的本地素材，无法匹配就报告缺失，不能把云路径当本机路径。游戏运行资源已经在游戏源包内。

在本地 GM/export 前，必须检查 `.agents/godotmaker.yaml` 的 Godot 可执行文件路径和 `export_presets.cfg` 的模板/导出路径，使用本机已验证路径；不得照抄原环境。导出模板/浏览器安装物不在此包，按版本需求本地准备。历史验证报告保留原路径以便溯源。不要运行历史日志中的云端命令。

## 框架与游戏已部署工具差异

`frontend/bridge/gm-capability-lock.json` 的 47 项全部匹配游戏源包；其中 `tools/run_verify.py` 与 c16d4bb 框架原件不同。游戏 README 记录了后续 21ab459/d7496f8 修复。合并时保留游戏已审修复，不能用旧框架同名文件覆盖。frameworkRevision 标签不表示每一个已部署工具都与框架原 ZIP 字节相同；准确差异 hash 见 SOURCE-BASELINE-DIFFERENCES.json。

## 精简版说明

先前完整包保存到文件库时传输失败，因此本新 ZIP 仅省去 GM 框架 docs/assets 下的四个文档演示 GIF：demo_01.gif、demo_02.gif、demo_03.gif、phantom-camera-godot-demo.gif。它们不是游戏运行素材；文档原链接可能缺少这些演示图。全部框架代码、技能、测试、配置、许可证及其余资源完整保留；Godot 游戏源 ZIP、参考图、前端源码和 Git 历史完全不变。精简前原 ZIP 的 SHA 和每个排除文件的 SHA 见 docs/COMPACT-ARCHIVE-CHANGES.json。源包不再声称框架原 ZIP 字节未变。旧版本清单中的原框架 inventory 保留用于差异溯源，实际解包使用 VERSIONS.json 指向的新清单。

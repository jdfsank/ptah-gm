# 绯月赌城 · Velvet Eclipse

原创单人哥特赌场动作探索游戏的 Godot 源码交付包。当前包含五个连通房间、剑击／投牌／闪避、月步二段跳、神龛存档、两阶段 Boss 和结局。界面以中文为主。本次交付没有音频。

## 从源码运行：Godot 4.6.3

1. 解压本包，进入 `velvet-eclipse` 文件夹，`project.godot` 就在该文件夹根目录。
2. 使用官方 Godot **4.6.3** 标准版，在项目管理器选择“导入”，选中 `project.godot`，保持目录结构并等待首次导入完成。
3. 按 **F5** 运行项目；主入口是 `scenes/main.tscn`。项目使用 Compatibility 渲染器。
4. 已把 Godot 加入 PATH 时，可在项目根目录运行：

```sh
godot --headless --editor --path . --import
godot --path .
```

Windows 的可执行文件名可能不同，请换成本机的 Godot 路径。源码已包含资源和 addons，无需重新生成图片或下载这些插件。首次导入会重建未打包的 `.godot` 缓存。`scenes/game_world.tscn` 是复用世界场景，测试也使用它；正常玩家入口仍是主场景。

## 直接玩独立 Web 包

Web 导出单独交付为 `velvet-eclipse-web-v2-delivery.zip`，不包含在本源码 ZIP 中。

1. 解压 Web ZIP，保持所有 `index.*` 文件在同一目录。
2. 若电脑已安装 Python，在该目录打开终端，运行：

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Windows 可使用 `py -m http.server 8765 --bind 127.0.0.1`。

3. 在支持 WebAssembly 和 WebGL 2 的桌面浏览器打开 `http://127.0.0.1:8765/index.html`。等待加载后点击画布，让游戏获得键盘焦点。
4. 不要双击 HTML 或使用 `file://`。结束时在终端按 Ctrl-C。此服务器只监听本机，不是公开托管。

后续继续同一存档，请使用相同浏览器配置、地址和端口。Web 存档属于该浏览器来源；隐私模式、禁止站点存储、清除浏览数据或更换配置都可能影响存档。原生与 Web 存档互相独立。

## 操作与路线

- A／D 或左右方向键：移动
- 空格／W：跳跃；取得月步后，在空中再次按下可二段跳
- J：剑击
- K：投牌，消耗会恢复的能量
- Shift／L：闪避
- E：与附近选中的门、遗物或神龛互动（需落地）
- M：已探索房间地图；M 或 Escape 关闭
- Escape：暂停／继续；菜单支持上下方向键、Enter 和鼠标

从大厅探索牌宴回廊、轮盘钟楼，取得月步后回到大厅上层入口。挑战庄家王座前可在神龛休息并存档。地图只显示已到访房间，不提供传送。死亡后可从当前检查点重试或回标题。

## 在另一台电脑导出 Web

`export_presets.cfg` 原样保留了构建时的预设。两条自定义模板路径指向原构建机器的 `/workspace/shared/velvet-export-tools/...`；这些路径不是便携路径，模板也未包含在本包内。

请在“项目 → 导出 → Web”中，将 Custom Template 的 Debug、Release 分别改为本机完全匹配引擎版本的官方 **4.6.3** `web_nothreads_debug.zip`、`web_nothreads_release.zip`。保留 Thread Support、Extensions Support 关闭设置，使用单线程且不启用 GDExtension 的模板。请使用本机已有或通过官方 Godot 流程取得的匹配模板，不要混用其他引擎版本。

先创建 `build/web` 输出目录，再在编辑器导出，或运行：

```sh
godot --headless --path . --export-release Web build/web/index.html
```

导出后，在项目根目录可运行 `python3 -m http.server 8765 --bind 127.0.0.1 --directory build/web`。预设保留了 `data/rooms/*.json` 的显式包含规则。

`.agents/godotmaker.yaml` 中的 Godot 可执行文件路径也属于原构建机器；继续使用 GodotMaker 工具前，请改成本机路径。 本包有意不包含 `.git`；直接导入或运行 Godot 不需要 Git 仓库，但原机械静态检查器要求项目是 Git 仓库。因此，若要运行完整 GodotMaker 系统验证流程，请先在解压后的项目根目录执行 `git init` 创建本地仓库；无需远程仓库，也无需推送。`docs/BUILD-AND-PLAY.md` 包含原环境命令和更多存档细节，其中原环境 HOME／XDG／模板路径不是本机运行的前置条件。

## 测试与已知边界

已有原生 headless 集成记录为 **78／78 测试通过，22 个测试套件**。首次导入后，本机可复测：

```sh
godot --headless --path . -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd --add res://test/ --ignoreHeadlessMode --report-directory res://reports/local
```

独立云浏览器验收在打开本地测试地址时遇到 **ERR_BLOCKED_BY_CLIENT**。这是浏览器访问环节被阻挡，不是已证实的游戏运行时错误。因此，真实 Web 启动／渲染、浏览器键盘交互，以及刷新／重新打开后的存档持久性仍未验证。原生测试与 Web 导出成功不能替代这些浏览器检查。

框架原 `run_verify` 曾因绝对报告目录与固定版本 gdUnit 不兼容而返回 **ERROR**，该原始记录保留。随后通过独立系统修复提交 `21ab459` 与游戏项目工具同步 `d7496f8` 修正报告路径；新一次真实生产器运行以 **PASS／退出码 0** 完成，并经过严格校验：78／78 测试、22 套件、构建 PASS、29 项静态检查 PASS，可选 lint 为 SKIP。没有把旧错误报告改成通过。对应框架回归结果为 2135 passed、64 skipped、1 deselected。

完整正式绑定审查／验收仍未完成：没有实际用户 TTY 验收确认，必需的 Web 验证配置受阻。不能将本交付理解为所有原始流水线关卡都已通过。

独立原生实机检查：v1 已完成正常五房间路线、取得能力与回溯、存档后进程重启继续、死亡／重试、两阶段 Boss、真结局与重新开始。v2 重新走过五房间路线并检查两个 Boss 阶段至 25 HP，确认修正后的 Boss 血条及阶段提示不会遮挡玩家、武器和攻击预警；没有另外声称 v2 已再次完成结局。未发现阻塞性的原生问题。

目标流程时长为设计目标，尚未实际测量。独立新副本的 Godot 导入与短时 headless 启动均以 0 退出；强制结束启动检查时仍出现 ObjectDB／8 个资源未释放的清理诊断，不是完全无诊断的退出。

本包没有音频，不声称已完成人工验收，也不声称发布了已验收的版本 tag；文件名中的 v2 仅用于区分本次交付文件。

## 内容、来源与许可文本

- `scripts`、`scenes`、`data`、`resources`、`assets`：游戏源码和资源，原样保留；为避免损坏依赖，也保留 assets 中已有的预览／图集文件
- `addons`、`test`、`e2e`：插件与测试
- 根目录设计文档及 `docs/BUILD-AND-PLAY.md`：设计、计划与运行说明
- `tools`、`.agents` 及白名单内 `.godotmaker` 文件：项目已有的 GodotMaker 公共框架源文件和非秘密配置，用于继续开发；不含原机器主机配置、缓存、原始生成过程与证据
- `notices/gecs`、`notices/gdUnit4`、`notices/godot-e2e`：从已核实的本地供应商目录原样复制的许可及 NOTICE
- `assets/fonts/NotoSansCJK-LICENSE.txt`：字体自带许可
- `notices/GodotMaker/LICENSE`、`notices/GodotMaker/FORK.md`：工具框架的原始许可与分支说明，原样保留

本交付没有为用户的游戏另行指定许可，也未改动上述许可文本。请分别查阅框架、游戏及第三方内容的适用资料。框架延续资料可能引用未打包的生成证据；这不影响已有游戏在 Godot 中导入和运行。

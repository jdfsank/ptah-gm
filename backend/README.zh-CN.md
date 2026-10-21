# 本机造物工作台后端

> 当前验收入口：[Studio 边界修复与补充验收](../docs/STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。在受测 macOS、stateless custom provider、Godot 4.6.3 范围内，四项角色探针、Agent/Project Runner 的真实 HTTP 注册及 fixture 控制的业务闭环通过；记录了 8 个实际原生回合。后端 **283/283、零跳过**，前端既有 **19/19**（本轮未重跑）。用户玩法/视觉验收仍为 `NOT_TESTED`，尚无用户接受的生产候选；请求 effort=`max` 不是实际强度观测，实际 effort 与完整计费未知。能力按每次启动时的新鲜本机检查派生，基于受信本地 Runner token，不是远程 attestation。

- [部署与维护手册](../docs/DEPLOYMENT-MANUAL.zh-CN.md)
- [工作台用户说明书](../docs/USER-MANUAL.zh-CN.md)
- [通用对象工作流实施契约](../docs/GENERAL-GAME-TOOL-PLAN.zh-CN.md)
- [Studio v1 实施与验收记录](../docs/STUDIO-IMPLEMENTATION-20261012.zh-CN.md)
- [项目内 Godot MCP 默认安装](../docs/GODOT-MCP.zh-CN.md)

每次制作的标准路径（2026-10-20）：创建或载入已批准的 Godot 工程 → 核对内置 MCP 完整且启用 → 在隔离副本启动普通编辑器 → 检查初始化、工具和精确工程路径 → 确认编辑器停止 → 启动制作 session。首次制作、返修和参数迭代均通过同一共用检查；失败不派发，停止未知时保留占用。策划和独立验证保持分工。操作及报告位置见 [Godot MCP 标准路径](../docs/GODOT-MCP.zh-CN.md)。

## 当前工作流

服务提供本机 Studio API，并保留旧 collect-loop 与已有 `objects-v1` 流程。2026-10-12 起，通过新版命令创建的项目标记 `protocolVersion:1`、`executionBackend:runners`，使用持久回执、项目事件和一致公开视图；后端持有唯一批准与发布裁决，独立 Runner 领取策划、制作、验证和试玩任务。旧项目按原协议运行，历史批准不自动升级。

新版按用户命令冻结模型、供应方、effort、时限与软预算；请求配置、线程报告、回合回执与未知实际配置分别保存。输入准备在后端消费并复核持久批准后幂等物化，Runner 不读取批准数据库或获得用户接受权限。未确认停止的执行保留占用，普通心跳不能复活过期租约，丢失回执通过原 ID 核查。

边界修复补充验收覆盖本机 native、自定义 `my_proxy` provider、静态工程工具和受测 Godot 配置的实际拒绝检查，包含真实 Producer 回合及 UID 来源绑定。Agent 与 Project Runner 的真实 HTTP 注册均通过；四项能力由每次启动时绑定 Runner ID/kind 的新鲜本机固定检查派生，检查失败或过期即不注册。受信本地 Runner token 是其信任模型，不是远程 attestation。后台重启、原生崩溃及取消后的停止核账已通过；范围不包括全部认证方式、模型/图片组合或完整计费。原版主场景 CA 问题已在受测固定 runtime 中解决，封存候选与同源 GUI 通过；用户玩法/视觉仍需人工体验，尚无用户接受的生产候选。创建项目、草稿、设置和读取可用；最新证据见[补充验收记录](../docs/STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。

对象文档 `studio.objects.v1` 包含稳定对象 ID、父子关系、关联、源绑定、带类型与约束的字段，以及需求。通用路径目前限定 Godot 4、2D、GDScript；生产者可写 `project.godot`、`.gd` 脚本、`.tscn` 场景、受控 `.tres` 资源，以及 PNG/JPEG/WebP 图片。插件目录、测试脚本、执行入口和任意文件不在写入范围。

迭代请求把自然语言、实际变更字段和关联对象的反馈分开传输。字段仅包含用户实际修改的值，且由后端按现有对象与字段定义重新校验。项目已有声明会控制前端显示的可编辑能力。

## 独立验证与状态诚实

通用验证器不执行制作方指定的测试，也不接受制作 session 自报的 PASS。报告覆盖 Git 范围、冻结对象文档、源绑定、临时干净副本的 Godot 导入，以及后端自带的主场景加载/实例化/短运行冒烟。即使这些技术检查通过，通用玩法、平衡和视觉要求仍是 `NOT_TESTED`，等待用户体验。

隔离探针 `evidence/workflow/general/real-object-probe-r3.json` 已记录两种非收集游戏的原生策划/制作 session、Godot 4.6.3 干净导入与后端主场景短运行 PASS，以及 speed 220→300 px/s 和玩家青色反馈迭代。后续 Bridge Runner 的实际输入/物理探针与 Light Grid 的 viewport 输入探针也通过，见 `evidence/workflow/general/bridge-gameplay-repaired-r2.json`、`evidence/workflow/general/puzzle-gameplay.json`；反馈修复 session 记录见 `evidence/workflow/general/reset-feedback-probe.json`。Bridge Runner 的具体缺陷是获胜后按 R 返回出生点，却因旧出口接触立即再次进入 WON；对应源码 `b4d535762b38dbb932c886c4e46db10972d4c762` 的专项探针已通过。所有这些旧工作流证据标记 `testData=true`、`productionAuthorized=false`、`humanAcceptance=NOT PERFORMED`，不能替代当前 Runner 权限验收或用户体验。最新实测的 Godot 子进程使用 deny-default 系统沙箱；受测配置拒绝封存源写入、越界文件访问和 loopback 连接，正式受信公有 CA runtime 下的原版导入/主场景/GUI 和封存候选链已通过，详见[补充验收](../docs/STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)。

旧 collect-loop 项目保留旧路径和旧批准语义；系统不会自动迁移旧批准。工作台目前仅支持本机单用户运行。测试数据必须使用独立 `--state-root` 和 `--test-data`。此前真实 session/引擎证据不构成本轮 Runner 权限验收；最新边界验收的临时批准也不构成用户生产批准。

## 启动

在仓库根目录运行：

```bash
.venv/bin/python -m tools.studio_services start
```

打开 `http://127.0.0.1:8764/studio/`。用 `tools.studio_services status` 查看受管进程，用 `tools.studio_services stop` 顺序停止两个 Runner、前端和后端。分组件入口为 `backend.server`、`tools.studio_frontend`、`runners.agent`、`runners.project`，详细参数及备份/恢复见部署手册。原单后端入口和 `8765/studio/` 保留。服务仅监听 loopback。

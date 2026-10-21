# 造物工作台说明书入口

这里是本机游戏制作工作台的部署和使用入口。新项目使用通用 2D 对象工作流；已存在的 collect-loop 项目继续使用原流程，不会自动升级批准记录。

**初次实施摘要（2026-10-12 历史记录）：**已新增 Studio v1 持久命令、项目状态流、两角色设置、独立 AgentRunner/ProjectRunner、精确交付与备份恢复工具。四个组件已在隔离状态目录完成独立启停冒烟，未启动模型回合。下方 2026-10-09 证据属于此前工作流；当前状态见最新补充验收。

> 前轮受测状态（2026-10-13）见[Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)：在受测 macOS、stateless custom provider、Godot 4.6.3 配置中，8 个实际原生回合（335.544 秒）、四项角色探针及 Agent/Project Runner 的真实 HTTP 注册通过；后端 **283/283、零跳过**，前端既有 **19/19**（本轮未重跑），另有 46 项定向检查通过。证据见[业务闭环](../evidence/workflow/studio-acceptance-business-20261013.json)和[最终回归](../evidence/workflow/studio-acceptance-final-role-regression-20261013.json)。两模板的项目内 MCP 默认安装、启用及编辑器控制已验证；本仓库 scaffold 已接入统一安装器并完成静态检查，完整依赖流程未实跑。角色能力在 Runner 每次启动时由绑定身份的新鲜本机检查派生；信任模型是受信本地 Runner token，不是远程 attestation。用户玩法/视觉验收仍为 `NOT_TESTED`；批准、接受和拒绝由合成 operator fixture 覆盖，尚无用户接受的生产候选。请求的 effort=`max` 不代表实际回合采用 `max`；实际 effort 与完整计费未知，未穷举所有模型、effort、provider 或平台。

> **验证状态（2026-10-09）：**隔离的真实原生 session 已完成两个非收集类游戏制作，并完成一次对象属性与定向反馈迭代；Godot 4.6.3 的全新导入和后端主场景运行冒烟均通过。证据来自 `testData=true`、`productionAuthorized=false` 的探针，合成接受仅更新隔离测试快照，`humanAcceptance=NOT PERFORMED`。这证明了制作与技术验证链路可运行，不代表玩法已由人验收。详见 [原生探针 r3 证据](../evidence/workflow/general/real-object-probe-r3.json)。

> 后续草稿修复（2026-10-13）：[立即重载修复及复测](STUDIO-DRAFT-IMMEDIATE-SAVE-20261013.zh-CN.md)已通过。概念、迭代文字和反馈输入后立即重载均恢复，旧草稿迁移及项目/版本隔离保留；前端 18 个 QA 脚本全部通过，无新模型回合。下方 Kimi 全流程记录保留当时的限制和证据，该草稿限制现已修复。

> 最新受测状态（2026-10-13）见[Studio Kimi 浏览器流程验收](STUDIO-KIMI-UI-ACCEPTANCE-20261013.zh-CN.md)：真实浏览器初始化、8 个实际 native 回合、精确封存、独立 Godot 验证与 GUI、模拟接受、已保存草稿/项目隔离及后端重启恢复通过；最终后端 **287/287、零跳过**，前端 **18 个 QA 脚本全部通过**。四项隔离服务保留空闲，模型/预览已停止。人工玩法与视觉仍 `NOT_TESTED`，未接受正式用户候选；保存完成前立即重载、长期并发压力及全部 provider/平台组合不在通过范围，原始失败保留。

## 选择说明书

| 目标 | 阅读 | 内容 |
| --- | --- | --- |
| 安装、启动、隔离生产与测试环境 | [部署与维护手册](DEPLOYMENT-MANUAL.zh-CN.md) | 本机依赖、运行边界、备份恢复、对账与故障处理 |
| 从概念开始创建游戏 | [工作台用户说明书](USER-MANUAL.zh-CN.md) | 只读策划、问答、对象计划确认、独立制作与候选审阅 |
| 对对象和属性继续精细调整 | [工作台用户说明书](USER-MANUAL.zh-CN.md) | 字段修改、自然语言要求、对象反馈、草稿和版本恢复 |
| 查看协议、实施范围与待验项目 | [通用对象工作流实施契约](GENERAL-GAME-TOOL-PLAN.zh-CN.md) | 文档结构、通讯流程、验收目标和文件责任 |
| 查看实际完成情况与验证证据 | [实现与验证报告](GENERAL-GAME-TOOL-VERIFICATION.zh-CN.md) | 与原计划的变化、真实 session、玩法观察与限制 |
| 排查策划失败与工作台恢复 | [策划诊断与恢复修复](PLANNING-FAILURE-FIX.zh-CN.md) | 原生错误、超时问题恢复、重试核账与项目隔离 |
| 查看项目与阶段改造的评估和交付 | [可行性复核与实施记录](STUDIO-PROJECT-STAGES-REVIEW.zh-CN.md) | 收敛范围：项目管理、项目作用域、初始/迭代页面、信息来源和顶部状态 |
| 查看四边界改造的设计依据 | [最终修改方案](STUDIO-FINAL-MODIFICATION-PLAN.zh-CN.md) | 原设计：JSON、参数/反馈、异步恢复、独立 Runner、批准与交付边界、文件和验收批次 |
| 查看本轮落地与未验限制 | [2026-10-12 实施与验收记录](STUDIO-IMPLEMENTATION-20261012.zh-CN.md) | 代码范围、历史验收矩阵和角色能力注册规则 |
| 查看本轮浏览器验收及通信恢复 | [Studio Kimi 浏览器流程验收](STUDIO-KIMI-UI-ACCEPTANCE-20261013.zh-CN.md) | 真实 UI 闭环、故障恢复、草稿隔离与最终回归 |
| 查看边界修复及补充验收 | [Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md) | 分权、CA runtime、UID 来源、封存候选和 24 场景证据范围 |
| 新工程默认 MCP 与编辑器控制 | [Godot MCP 安装与使用](GODOT-MCP.zh-CN.md) | 项目内来源、模板/scaffold 默认安装、HTTP MCP 实测 |
| 查看前端组件和完整通信示例 | [类图、完整时序与逐图示例](STUDIO-USER-INTERACTION-SEQUENCES.zh-CN.md) | 最终方案的设计附件；不是已上线 API |
| 对照原始项目管理方案 | [项目隔离与分阶段交互方案](STUDIO-PROJECT-STAGES-PLAN.zh-CN.md) | 原始设计；分库、消息总线和新隔离基础设施已暂缓 |
| 查看后端当前范围 | [后端说明](../backend/README.zh-CN.md) | 工作流组成、写入边界与验证限制 |

## 快速启动

在仓库根目录启动四个独立组件：

```sh
./start-studio-services.command
```

也可运行：

```sh
.venv/bin/python -m tools.studio_services start
```

在同一台 Mac 的浏览器打开[独立前端](http://127.0.0.1:8764/studio/)。状态和关停分别用 `tools.studio_services status`、`tools.studio_services stop`。原 `start-studio.command` 仍提供单后端入口及 `8765/studio/`；新版能力按各 Runner 启动时的本机探针结果注册，页面显示当前实际能力。服务只监听 `127.0.0.1`。

## 新项目的流程

1. 输入概念文字或添加参考图片。
2. 由独立只读策划 session 提问并整理对象、属性、关系、制作任务和验收条件。
3. 回答澄清问题，检查完整计划并确认冻结范围。
4. 受信执行端创建或载入批准的 Godot 工程，验证内置 MCP 在隔离普通编辑器中可连接且工程身份正确，确认编辑器停止后，由另一个 session 实施已批准计划。首次制作、返修与参数迭代均执行此步骤；详见 [Godot MCP 标准路径](GODOT-MCP.zh-CN.md)。
5. 后端做范围审计、干净 Godot 导入和自己的运行冒烟；报告把技术证据与人工体验分开。
6. 用户亲自运行候选并接受或拒绝；接受只更新本机工作台快照。
7. 按对象选择字段与反馈继续迭代。

## 当前边界

工作流面向 Godot 4 的 2D GDScript。当前源文件白名单不包含插件、编辑器扩展、测试脚本、音频生成和导出打包。图片作为参考输入，不会自动转成已制作素材。r3 探针使用 Bridge Runner 与 Light Grid 两种不同玩法完成原生制作 session；Bridge Runner 的速度从 220 调整到 300 px/s，并通过定向视觉反馈把玩家颜色设为青色（`#00FFFF`）。后续隔离反馈修复与真实 Godot viewport 探针已通过：Bridge Runner 检查正常跳跃、两次平台落地、获胜、获胜后 R 重置、重置后再次获胜和坠落恢复；Light Grid 检查鼠标角/边/中心切换、计步、三步获胜、胜利后输入锁定及按键和按钮重置。相应证据见[反馈修复记录](../evidence/workflow/general/reset-feedback-probe.json)、[Bridge Runner 复测](../evidence/workflow/general/bridge-gameplay-repaired-r2.json)和[Light Grid 玩法探针](../evidence/workflow/general/puzzle-gameplay.json)。这些仍是 fixture 专项测试数据（`testData=true`、`productionAuthorized=false`），不是人工体验或生产批准；一般候选的玩法要求仍需用户试玩，`humanAcceptance=NOT PERFORMED`。缺陷原因为获胜后按 R 返回出生点，却因旧出口接触立即再次进入 WON；现在的特定复测通过，不代表所有游戏都适用同一自动玩法覆盖。

旧 collect-loop 项目仍在旧工作流内，旧批准不会被自动转换为通用对象批准。测试状态目录必须与生产隔离，测试接受不构成生产批准。

本项目遵守[仓库执行约束](../AGENTS.md)：用 Git 版本身份和差异审阅，不运行独立 SHA/MD5 校验。
# Studio 完整复刻持续目标（2026-10-14）

本轮的完整验收范围见[用户目标原文](STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.zh-CN.md)和[逐字持久化副本](acceptance/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.full.zh-CN.md)。两份全文必须保留，后续计划不得缩减范围。

按[89 项覆盖与实施计划](STUDIO-LEGACY-REPLICATION-PLAN.zh-CN.md)持续执行，再作[验证评估](STUDIO-LEGACY-REPLICATION-EVALUATION.zh-CN.md)。当前状态为进行中；验证评估和浏览器模拟操作都不等于用户验收。实际操作证据保存在 `evidence/workflow/studio-legacy-replication-20261014/`。


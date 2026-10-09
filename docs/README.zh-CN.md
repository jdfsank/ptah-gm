# 造物工作台说明书入口

这里是本机游戏制作工作台的部署和使用入口。新项目使用通用 2D 对象工作流；已存在的 collect-loop 项目继续使用原流程，不会自动升级批准记录。

> **验证状态（2026-10-09）：**隔离的真实原生 session 已完成两个非收集类游戏制作，并完成一次对象属性与定向反馈迭代；Godot 4.6.3 的全新导入和后端主场景运行冒烟均通过。证据来自 `testData=true`、`productionAuthorized=false` 的探针，合成接受仅更新隔离测试快照，`humanAcceptance=NOT PERFORMED`。这证明了制作与技术验证链路可运行，不代表玩法已由人验收。详见 [原生探针 r3 证据](../evidence/workflow/general/real-object-probe-r3.json)。

## 选择说明书

| 目标 | 阅读 | 内容 |
| --- | --- | --- |
| 安装、启动、隔离生产与测试环境 | [部署与维护手册](DEPLOYMENT-MANUAL.zh-CN.md) | 本机依赖、运行边界、备份恢复、对账与故障处理 |
| 从概念开始创建游戏 | [工作台用户说明书](USER-MANUAL.zh-CN.md) | 只读策划、问答、对象计划确认、独立制作与候选审阅 |
| 对对象和属性继续精细调整 | [工作台用户说明书](USER-MANUAL.zh-CN.md) | 字段修改、自然语言要求、对象反馈、草稿和版本恢复 |
| 查看协议、实施范围与待验项目 | [通用对象工作流实施契约](GENERAL-GAME-TOOL-PLAN.zh-CN.md) | 文档结构、通讯流程、验收目标和文件责任 |
| 查看实际完成情况与验证证据 | [实现与验证报告](GENERAL-GAME-TOOL-VERIFICATION.zh-CN.md) | 与原计划的变化、真实 session、玩法观察与限制 |
| 排查策划失败与工作台恢复 | [策划诊断与恢复修复](PLANNING-FAILURE-FIX.zh-CN.md) | 原生错误、超时问题恢复、重试核账与项目隔离 |
| 查看项目管理与阶段分离的改进方案 | [项目隔离与分阶段交互方案](STUDIO-PROJECT-STAGES-PLAN.zh-CN.md) | 待实施：项目首页、初始策划/迭代页面、信息来源和顶部工作状态 |
| 查看后端当前范围 | [后端说明](../backend/README.zh-CN.md) | 工作流组成、写入边界与验证限制 |

## 快速启动

在仓库根目录启动服务：

```sh
./start-studio.command
```

也可运行：

```sh
.venv/bin/python -m backend.server --port 8765
```

保持启动终端运行，在同一台 Mac 的浏览器打开 [本机工作台](http://127.0.0.1:8765/studio/)。服务只监听 `127.0.0.1`；不要把它配置成局域网或公网服务。

## 新项目的流程

1. 输入概念文字或添加参考图片。
2. 由独立只读策划 session 提问并整理对象、属性、关系、制作任务和验收条件。
3. 回答澄清问题，检查完整计划并确认冻结范围。
4. 由另一个 session 实施已批准计划。
5. 后端做范围审计、干净 Godot 导入和自己的运行冒烟；报告把技术证据与人工体验分开。
6. 用户亲自运行候选并接受或拒绝；接受只更新本机工作台快照。
7. 按对象选择字段与反馈继续迭代。

## 当前边界

工作流面向 Godot 4 的 2D GDScript。当前源文件白名单不包含插件、编辑器扩展、测试脚本、音频生成和导出打包。图片作为参考输入，不会自动转成已制作素材。r3 探针使用 Bridge Runner 与 Light Grid 两种不同玩法完成原生制作 session；Bridge Runner 的速度从 220 调整到 300 px/s，并通过定向视觉反馈把玩家颜色设为青色（`#00FFFF`）。后续隔离反馈修复与真实 Godot viewport 探针已通过：Bridge Runner 检查正常跳跃、两次平台落地、获胜、获胜后 R 重置、重置后再次获胜和坠落恢复；Light Grid 检查鼠标角/边/中心切换、计步、三步获胜、胜利后输入锁定及按键和按钮重置。相应证据见[反馈修复记录](../evidence/workflow/general/reset-feedback-probe.json)、[Bridge Runner 复测](../evidence/workflow/general/bridge-gameplay-repaired-r2.json)和[Light Grid 玩法探针](../evidence/workflow/general/puzzle-gameplay.json)。这些仍是 fixture 专项测试数据（`testData=true`、`productionAuthorized=false`），不是人工体验或生产批准；一般候选的玩法要求仍需用户试玩，`humanAcceptance=NOT PERFORMED`。缺陷原因为获胜后按 R 返回出生点，却因旧出口接触立即再次进入 WON；现在的特定复测通过，不代表所有游戏都适用同一自动玩法覆盖。

旧 collect-loop 项目仍在旧工作流内，旧批准不会被自动转换为通用对象批准。测试状态目录必须与生产隔离，测试接受不构成生产批准。

本项目遵守[仓库执行约束](../AGENTS.md)：用 Git 版本身份和差异审阅，不运行独立 SHA/MD5 校验。

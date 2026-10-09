# 本机造物工作台后端

- [部署与维护手册](../docs/DEPLOYMENT-MANUAL.zh-CN.md)
- [工作台用户说明书](../docs/USER-MANUAL.zh-CN.md)
- [通用对象工作流实施契约](../docs/GENERAL-GAME-TOOL-PLAN.zh-CN.md)

## 当前工作流

服务提供本机同源 Studio API，并组合旧 collect-loop 协调器与新 `objects-v1` 通用对象流程。新概念通过只读策划 session 形成问题和计划；用户确认完整对象文档与制作范围后，服务冻结表单，再启动独立制作 session。策划不会写项目文件，制作不能修改后端持有的对象文档、规格文件、受保护运行接口或验证记录。

对象文档 `studio.objects.v1` 包含稳定对象 ID、父子关系、关联、源绑定、带类型与约束的字段，以及需求。通用路径目前限定 Godot 4、2D、GDScript；生产者可写 `project.godot`、`.gd` 脚本、`.tscn` 场景、受控 `.tres` 资源，以及 PNG/JPEG/WebP 图片。插件目录、测试脚本、执行入口和任意文件不在写入范围。

迭代请求把自然语言、实际变更字段和关联对象的反馈分开传输。字段仅包含用户实际修改的值，且由后端按现有对象与字段定义重新校验。项目已有声明会控制前端显示的可编辑能力。

## 独立验证与状态诚实

通用验证器不执行制作方指定的测试，也不接受制作 session 自报的 PASS。报告覆盖 Git 范围、冻结对象文档、源绑定、临时干净副本的 Godot 导入，以及后端自带的主场景加载/实例化/短运行冒烟。即使这些技术检查通过，通用玩法、平衡和视觉要求仍是 `NOT_TESTED`，等待用户体验。

隔离探针 `evidence/workflow/general/real-object-probe-r3.json` 已记录两种非收集游戏的原生策划/制作 session、Godot 4.6.3 干净导入与后端主场景短运行 PASS，以及 speed 220→300 px/s 和玩家青色反馈迭代。后续 Bridge Runner 的实际输入/物理探针与 Light Grid 的 viewport 输入探针也通过，见 `evidence/workflow/general/bridge-gameplay-repaired-r2.json`、`evidence/workflow/general/puzzle-gameplay.json`；反馈修复 session 记录见 `evidence/workflow/general/reset-feedback-probe.json`。Bridge Runner 的具体缺陷是获胜后按 R 返回出生点，却因旧出口接触立即再次进入 WON；对应源码 `b4d535762b38dbb932c886c4e46db10972d4c762` 的专项探针已通过。所有这些证据标记 `testData=true`、`productionAuthorized=false`、`humanAcceptance=NOT PERFORMED`；一般生产候选的玩法要求仍须由用户体验，不要把专项 fixture 断言、技术 PASS、Python mock、session 完成或合成测试接受解释为用户验收。执行项目中的 Godot 代码仍是合作型本机执行，没有 OS 级沙箱。

新建项目使用 `objects-v1`，旧 collect-loop 项目保留旧路径和旧批准语义；系统不会自动迁移旧批准。工作台目前仅支持本机单用户运行。测试数据必须使用独立 `--state-root` 和 `--test-data`。

## 启动

在仓库根目录运行：

```bash
.venv/bin/python -m backend.server --port 8765
```

打开 `http://127.0.0.1:8765/studio/`。服务只允许 loopback。部署、备份、进程对账和恢复限制见部署手册。

# 通用 2D 游戏工作台实施契约

状态：2026-10-09 已完成本轮工具实现、回归和隔离原生闭环验证。结果及边界见[实现与验证报告](GENERAL-GAME-TOOL-VERIFICATION.zh-CN.md)。游戏项目的用户确认与候选验收仍逐轮执行。

本次用户授权将工具从固定收集挑战扩展为通用 2D 游戏制作工具。用户进一步明确：重点是标准化对象切分及用户、前端、agent、后端之间的通信，保持持续、精细的调整与反馈；无需按游戏类别划分产品流程。此授权针对工具开发，游戏用户仍需逐轮确认自己的制作计划及候选。

用户已明确指定来源为此前重组的 GM non-pk 和 GameStudio，禁止参考现有 Ptah 技能。本方案及后续实现以本仓库 `sources/GodotMaker-non-pk/` 为工作流来源；此前技能调用已终止。

GameStudio 参考已从 [openai/plugins 的 game-studio](https://github.com/openai/plugins/tree/main/plugins/game-studio) 读取，Git 版本为 `0722921d5542fc593105c27bd52630babd8b8c2a`。采用状态与渲染分离、稳定资源标识、明确输入动作及试玩反馈的原则。其浏览器引擎默认选择不改变本项目的 Godot 2D 目标，也不构成本项目新的授权。

## 目标与验收

- GT-01：使用统一对象文档描述项目、场景、实体、机制、规则、界面、素材与内容，保留稳定对象 ID、属性、关系和源文件绑定。
- GT-02：新概念通过单独、只读的原生策划 session 形成结构化问题或可审阅计划。回答可多轮往返，不把任意想法转换为固定收集游戏。
- GT-03：前端以对象为目标，提交自然语言、明确属性修改及反馈；结构化修改独立传输，不能被未修改数值框覆盖。
- GT-04：冻结表单包含完整对象文档、基线、对象变更、文件范围与验收条目。制作使用另一个 session，不能自行批准或改写冻结计划。
- GT-05：由后端执行范围审计、干净 Godot 导入和独立运行检查。自动技术检查和用户体验验收分别展示；未被自动观察的玩法要求保持人工待验。
- GT-06：候选返回可定位对象、属性和验证证据；用户接受后整体更新快照。之后仍在原工作台按对象精细迭代、反馈和重关联草稿。
- GT-07：保留旧 collect-loop 工作区、审批、幂等派发、Git worktree、进程组退出确认和未知状态隔离。旧批准不自动升级为新的范围。
- GT-08：至少用两个非收集玩法测试项目，以及一次对象属性与反馈迭代证明同一协议可工作。所有自动制作及合成接受仅发生在独立测试存储。

## 对象文档 v1

文档形状：

```json
{
  "schemaVersion": "studio.objects.v1",
  "dimension": "2d",
  "title": "游戏名称",
  "summary": "本轮核心体验和范围",
  "objects": [
    {
      "id": "player",
      "kind": "entity",
      "name": "玩家",
      "description": "在主场景中接受输入",
      "parentId": "main-scene",
      "relations": [],
      "sourceBindings": ["scripts/player.gd"],
      "fields": [
        {"id": "speed", "label": "移动速度", "type": "number", "value": 220, "min": 0, "max": 1200, "editable": true}
      ]
    }
  ],
  "requirements": [
    {"id": "move", "text": "玩家可通过键盘移动", "objectIds": ["player"], "verification": "manual"}
  ]
}
```

`kind` 为 `project/scene/entity/mechanic/rule/interface/asset/content`；不是游戏类型分类。对象 ID、字段 ID 为有界小写字母/数字/下划线/连字符。字段类型为 `number/integer/boolean/text/choice/color/vector2`。关系项为 `{type,targetId}`。父对象与关系必须存在，父链无环。字段可编辑性、类型、范围、选项以及源绑定经过后端验证。不能把模型自报当作行为已验证。

游戏代码从后端持有的 `design/game.json` 读取属性，配套受保护的 `studio/runtime.gd` 提供按对象和字段 ID 查询的接口。制作方不能修改这两个文件。对象源绑定只允许项目内 `scripts/`、`scenes/`、`resources/`、`assets/` 的受支持文件；不允许绝对路径、链接、隐藏路径或可执行脚本入口。新对象由策划产生，经用户审阅后进入冻结版本。

## 通信与策划 v1

新前端在 `/api/concepts` 显式传 `workflow: "objects-v1"`。旧 API 未声明工作流时保持旧契约；已存项目的工作流由后端持有。

`changeRequest` 单独传输：`{baseRevision,sourceCommit,targetObjectIds,fields,feedback}`。`fields` 是 `{objectId,fieldId,value}` 列表，只包含用户实际改动的属性；`feedback` 是 `{objectId,message,category}` 列表，类别为 `general/bug/visual/behavior`。后端以当前快照重新核对对象、属性、值、基线，并将结构化要求完整交给策划。自然语言保留原文，不通过拼接数值框解析。

策划结果严格 JSON：`{status,summary,questions,document,tasks,blockers}`。状态为 `NEEDS_CLARIFICATION/READY/BLOCKED`。问题为 `{id,prompt,type,required,options?}`，类型为 `text/choice/number/boolean`。`READY` 必须具有合法对象文档、非空要求与任务。未解决问题不得冻结。结果通过原生 session 的响应通道返回；策划不写项目文件。

提案保存 `workflow/document/discussion/changeRequest/planningEvidence` 以及原有身份、修订与基线字段。策划期间为 `PLANNING`，回答提交后递增修订并启动新的只读策划回合。界面轮询服务端提案，取消与重启保留执行租约；不自动重投不确定回合。

## 制作和验证

新通用工程由后端准备受控 Godot 2D 基线，然后按已确认的完整计划制作。用户无需批准一个固定玩法模板。写入策略只开放 `project.godot` 与受支持 `scripts/scenes/resources/assets` 文件；后端自己写计划、对象文档和受保护运行接口，生产者不能写测试、验证报告或审批记录。

通用验证报告明确分为结构、导入、运行冒烟、对象映射和用户体验要求。只有后端实际观察到的条目显示技术 PASS；通用玩法和美术体验不会仅凭启动成功被称为已通过。候选仍需用户本机体验及接受。

## 文件所有权

| 负责方 | 可写范围 |
| --- | --- |
| 主 agent | Coordinator/server/通用工作流编排、公共协议、文档、集成与日志 |
| 对象协议 agent | `backend/object_protocol.py`、该模块的纯协议测试 |
| 前端 agent | `frontend/studio/`、新增 Studio 对象测试；保留旧测试意图 |
| 验证 agent | `backend/general_verification.py`、`backend/general_verification_worker.py`、`backend/templates/general_2d/`、对应验证测试 |

共享 Godot 导入、完整测试、实际制作探针、截图与 Git 提交由主 agent 串行运行。使用 Git 版本身份与差异，不运行独立 SHA/MD5 检查。GameStudio 插件仅作为对象与交互设计参考，不替代本项目范围或批准来源。

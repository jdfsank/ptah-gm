# Studio 视觉反馈实施：原 125 项覆盖附录

日期：2026-10-19。原清单的 89 项完整目标和 36 项页面交互逐行保留。此处是实施后的技术检查覆盖记录，不是首次非代码用户走查，也不代表用户接受。

2026-10-20追加：下方125行及119部分检查/6未覆盖/0完整通过保留为初次实施的技术检查口径。新增交替试用的实际操作口径为99部分覆盖/26未覆盖/0完整通过，见文末及[逐项机器记录](../../tmp/studio-user-trial-cycles-20261020/coverage.json)；技术证据不自动升级为真实体验覆盖，两组数字不相加。

## 证据与判定

- 真实抽样：隔离页面、一次真实 ImageGen、真实策划/冻结/制作及 Godot 操作。视图见 `../../tmp/studio-visual-feedback-implementation-20261019/evidence/live-ready-candidate-view.json`，引擎证据见同目录 `godot-e2e.json`。
- DOM/fixture：同目录 `frontend-regressions-final.json` 记录 32 个脚本结果；后端测试使用临时存储与注入 provider。相关脚本通过不等于该行全部真实场景通过。
- 布局：同目录 `studio-final-320.png`、`studio-final-390.png`、`studio-final-1280.png`；实际 viewport/client/body 宽度另见 `browser-final-checks.json`。
- “部分检查”只表示有本轮相关证据；每行仍列出未覆盖部分。没有任何一行以局部抽样推定整行完整通过。“未覆盖”保留原要求，不以不适用删除。
- Casino 专属语义、真实 OS 中文输入法、跨浏览器、复杂连续运动和完整人工验收仍需后续按原要求检查。

## 逐项记录

| ID | 原交互与期待（保留原文） | 本轮状态 | 证据及限制 |
| --- | --- | --- | --- |
| G1.1 | 用游戏语义理解项目，而非从文件名猜对象。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.2 | 分清共享定义、场景实例、入口、生成规则和临时对象。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.3 | 浏览实体以及规则、回合等非实体系统。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.4 | 找到职责、驱动、行为、状态、生命周期、运动、表现和依赖。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.5 | 理解对象何时出现、创建、变化、清理、被使用及影响谁。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.6 | 从定义反查实例、生成与资源使用，从实例回到定义或行为。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.7 | 在同一目标下切换 Design/Narrative/Art，并理解缺失信息。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.8 | 对象与意见有稳定身份，切换后不会串写。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-semantics-qa.cjs、studio-objects-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G1.9 | 分清用户意图、工程事实、推断、提案、运行结果和缺口。 | 部分检查 | 真实链路/页面抽样：页面明确区分概念图、冻结要求与操作员截图；其余来源种类未逐项实操。 |
| G2.1 | 使用项目上下文、折叠导航、中央工作区、右侧详情和集中申报。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.2 | 场景→实例→定义/行为/资源/使用处之间跳转并返回。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.3 | 名称或精确 ID 搜索、分类、面包屑、深链、前进和后退。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.4 | 所有面板及意见同步到当前目标。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.5 | 切换观察面不改变目标和意见。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.6 | 分清浏览资源与新增、放置操作。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.7 | 按需展开来源、覆盖诊断和帮助。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G2.8 | 改主题、折叠界面、打开草稿入口、查看变化提示不改变内容。 | 部分检查 | 相关 DOM/契约回归：studio-route-hydration-qa.cjs、studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.1 | 查看场景构成、入口、出口和有向连接总览。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.2 | 查看背景、实例、边界、位置、大小、锚点、网格和辅助标记。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.3 | 查看缩略图、图集区域、真实首帧、资源使用及共享关系。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.4 | 查看连续运动、动作阶段及效果窗口。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。雨中演示的 Godot 右移/避雨/重置不替代全部动作预览能力。 |
| G3.5 | 预览响应、交互和规则语义。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。雨中演示的 Godot 右移/避雨/重置不替代全部动作预览能力。 |
| G3.6 | 查看生成条件、类型、位置及清理，并区分临时对象。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.7 | 查看过渡方向、出口、入口、模式、预设和效果。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G3.8 | 一次播放、停止，以及修改参数后刷新预览。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。雨中演示的 Godot 右移/避雨/重置不替代全部动作预览能力。 |
| G3.9 | 分清静态、参数推导、浏览器示意和真实运行，看到来源与能力边界。 | 部分检查 | 真实链路/页面抽样：概念图与原生 Godot 截图均实看，采集条件标为未独立验证；其他预览种类未逐项实操。 |
| G3.10 | 程序绘制、缺图、未绑定或不可预览时得到可理解的替代说明。 | 部分检查 | 真实链路/页面抽样：本例程序绘图没有虚构 PNG；缺图路径另有 DOM 反例，所有项目替代说明未逐项实操。 |
| G3.11 | 切目标或关闭后，旧播放、状态和高亮结束。 | 部分检查 | 相关 DOM/契约回归：studio-bound-resource-preview-qa.cjs、studio-preview-field-refs-qa.cjs、studio-transition-operation-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.1 | 读懂字段控件、单位、范围、枚举、默认值及错误。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.2 | 提议新场景、空白或最小模板、新实例、放置、取消和删除草稿。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.3 | 拖拽、坐标精调，并理解锚点与边界限制。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.4 | 使用固定、微调和自由约束，批量操作与 Agent 遵守范围。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.5 | 分开处理玩家定义、实例和出生入口，避免重复创建。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.6 | 修改出口的目标场景、入口和条件，识别无效引用。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.7 | 编辑独立有向过渡及共享预设，分清未设置、无、引用三态。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.8 | 理解实例、场景、定义及资源范围和影响。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.9 | 对拖拽、批量和应用提案成组撤销重做，取消不留半成品。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G4.10 | 只读目标仍可评论，新增条件或字段显示为期望。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs、studio-workbench-p4-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.1 | 向各类可寻址目标提出意见。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.2 | 提交纯文字、纯参数以及混合修改。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.3 | 意见自动携带目标身份、位置、预览和范围。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.4 | 用户原文独立于 Agent 理解和摘要。 | 部分检查 | 真实链路/页面抽样：真实概念原文、AI 策划反馈、冻结 userText 和 producer 输入有证据；其他原文路径未逐项实操。 |
| G5.5 | 对只读或没有控件的目标提出修改。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.6 | 多目标意见独立保存、汇总，切换及刷新不串写。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.7 | 连续输入和中文输入法内容及时保留。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。真实操作系统中文输入法未测。 |
| G5.8 | 编辑、移除意见，识别失效目标并明确重关联。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.9 | 仅必要歧义需要澄清，已明确的信息无需重复回答。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G5.10 | 原文与控件冲突有展示，双方内容都保留。 | 部分检查 | 相关 DOM/契约回归：studio-intent-input-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.1 | 区分可恢复草稿、保存状态和提交状态。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.2 | 保存、打开、重置、撤销、重做和导出，读懂各自范围。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.3 | 导出当前草稿、原文和首次覆盖备份并理解用途。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.4 | 项目隔离、多标签冲突不覆盖新内容。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.5 | 缺目标、格式不兼容或存储失败后可恢复或导出。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.6 | 已提交内容与随后新增内容分别保留。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G6.7 | 恢复草稿不会自动重新提交或重启 Agent。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-draft-regression-qa.cjs、studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.1 | 字段、意见及结构提案汇成同一申报单。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.2 | 申报展示对象、前后值、原文、范围和预览。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.3 | 参数改回原值净变化归零，纯意见仍可提交。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.4 | 多目标多类型申报保持身份关联。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.5 | 提交前定位、编辑、移除和处理冲突。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.6 | 空任务被拦截。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.7 | 预览与发送一致，相关内容改变后旧审阅失效。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.8 | 取消不发送、重复操作不重复发，未知结果能对账。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.9 | 理解收单、处理状态及刷新或断线后的恢复。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G7.10 | 沿同一工作流推进，无需重复搬运需求。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs、studio-intent-a3-a5-focused-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G8.1 | Agent 接收到目标、原文、差异、上下文和范围。 | 部分检查 | 真实链路/页面抽样：真实单场景制作收到同轮参考及用途；目标/范围多类型组合主要由契约测试验证。 |
| G8.2 | 一般自然语言由真实 Agent 处理。 | 部分检查 | 真实链路/页面抽样：真实 Agent 处理雨衣避雨自然语言并制作候选；不推广为所有项目通过。 |
| G8.3 | 角色边界、方案审阅、用户决定和授权复用清楚。 | 部分检查 | 真实链路/页面抽样：真实方案审阅、冻结、独立验证分别记录；未代用户决定候选，其他边界未逐项实操。 |
| G8.4 | 知道谁在处理、进度、受阻原因及下一动作。 | 部分检查 | 真实链路/页面抽样：页面显示制作、验证与待审阅，保留一次 cancelled 未知原因；全部失败恢复未实操。 |
| G8.5 | 每项需求可对应决定、实际变化、未完事项和澄清。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs、studio-repair-regression-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G8.6 | 分清收单、回合结束、源码变化、验证和认可。 | 部分检查 | 真实链路/页面抽样：真实链路区分生成、冻结、制作、技术通过、待审阅；未做用户接受。 |
| G8.7 | 从结果回到原元素看证据，接着下一轮。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs、studio-repair-regression-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G8.8 | 不满意时沿用工作台和返修上下文。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs、studio-repair-regression-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G8.9 | 无映射、无能力、失败或未验证情况如实保留。 | 部分检查 | 真实链路/页面抽样：未采集/缺少历史绑定/坏图反例在 DOM/契约覆盖；真实取消原因仍未知。 |
| G8.10 | 全局成功不替代逐项需求或体验判断。 | 部分检查 | 真实链路/页面抽样：真实静态对照和 Godot 移动/避雨/重置分开记录；未做体验接受。 |
| G9.1 | 预览和修改优先，协议、日志按需展开。 | 部分检查 | 真实链路/页面抽样：真实页面概览/详细与默认说明可见；所有诊断入口未逐项实操。 |
| G9.2 | 操作前理解范围，之后看到草稿，提交后找到原任务。 | 部分检查 | 相关 DOM/契约回归：studio-user-ux-core-qa.cjs、studio-workbench-dialog-lifecycle-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G9.3 | 当前只存在一个明确的详情上下文。 | 部分检查 | 相关 DOM/契约回归：studio-user-ux-core-qa.cjs、studio-workbench-dialog-lifecycle-qa.cjs；本行完整真实用户操作未逐项验证。 |
| G9.4 | 窄屏能切换导航、工作区、详情并返回。 | 部分检查 | 真实链路/页面抽样：320/390/1280px 实看并测无横向溢出；整套导航返回路径未逐项实操。 |
| G9.5 | 键盘、焦点、滚动、Escape、工作台撤销及文本原生撤销可用。 | 部分检查 | 相关 DOM/契约回归：studio-user-ux-core-qa.cjs、studio-workbench-dialog-lifecycle-qa.cjs；本行完整真实用户操作未逐项验证。键盘/模态只有局部及 DOM 测试，未覆盖所有恢复路径。 |
| G9.6 | 模态隔离背景，关闭后恢复焦点和位置。 | 部分检查 | 相关 DOM/契约回归：studio-user-ux-core-qa.cjs、studio-workbench-dialog-lifecycle-qa.cjs；本行完整真实用户操作未逐项验证。键盘/模态只有局部及 DOM 测试，未覆盖所有恢复路径。 |
| G9.7 | 长名称、ID、意见、大量元素、空、加载和错误状态可处理。 | 部分检查 | 真实链路/页面抽样：真实长 job/preview ID 溢出已修并复验；大量元素及所有空/加载/错误状态未完整实操。 |
| G9.8 | 演示、概念和静态内容不会冒充真实完成。 | 部分检查 | 真实链路/页面抽样：真实概念与候选图分别标明来源和未验证，未将技术通过标成用户接受。 |
| G10.1 | 理解 Casino 玩家、敌人、生成、武器、回合、环境、骰子、表现及 UI 关联。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| G10.2 | 分清环境与场景、定义与临时实例，以及武器关联。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| G10.3 | 理解骰子预警、生效、奖励、清理及来源。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| G10.4 | 程序绘制内容不会虚构 PNG。 | 部分检查 | 真实链路/页面抽样：本例明确程序绘图与概念参考分离；其他项目未逐项检查。 |
| G10.5 | 其他项目可复用工作流，支持能力按实际声明。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| G10.6 | 独立图片 CLI 边界清楚；无页面入口时标明不适用。 | 部分检查 | 真实链路/页面抽样：正式页面受信入口完成一次真实 ImageGen；CLI 保持通用职责，素材包路径另行保留。 |
| W01 | 从 /、/studio、/studio/ 进入，目标深链可恢复，找到旧版入口。 | 部分检查 | 真实链路/页面抽样：真实 /studio/ 页面及候选深链可刷新；/ 与 /studio 别名仅相关回归。 |
| W02 | 连接、加载、连接失败和重新连接的提示及动作。 | 部分检查 | 真实链路/页面抽样：真实服务重启后重连；页面曾显示状态流陈旧并恢复，全部网络故障未实操。 |
| W03 | 项目列表、创建名称校验、创建、打开、返回所有项目。 | 部分检查 | 真实链路/页面抽样：真实隔离项目已创建并打开；全部名称校验及返回分支未逐项实操。 |
| W04 | 重命名、取消，长名称在列表和项目中保持可读。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| W05 | 归档、取消、归档后入口和状态。 | 未覆盖 | 本轮未对该目标进行独立真实操作验证；保留现有目标，不能据可见入口或源码存在标通过。 |
| W06 | 策划及制作的模型、档位设置、支持能力和冻结配置说明。 | 部分检查 | 真实链路/页面抽样：真实 Agent 与项目执行能力可用；模型切换组合未逐项实操。 |
| W07 | 输入初始概念、连续中文输入、刷新和项目隔离。 | 部分检查 | 真实链路/页面抽样：真实概念与参考刷新后保留；中文文本输入不等于真实 OS 输入法验证。真实操作系统中文输入法未测。 |
| W08 | 图片用途、多图上传、移除、部分失败提示及项目隔离。 | 部分检查 | 真实链路/页面抽样：真实生成图选用和用途随冻结，真实候选 PNG 上传；多图/部分失败主要是契约测试。 |
| W09 | 开始规划、查看进度、规划失败和恢复入口。 | 部分检查 | 真实链路/页面抽样：真实两次规划和制作，一次 cancelled 保留原因未知；全部恢复入口未覆盖。 |
| W10 | 回答澄清，区分本修订与旧答案，离开后找回。 | 部分检查 | 相关 DOM/契约回归：studio-planner-regression-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W11 | READY 补充、修订变化及本轮补充草稿。 | 部分检查 | 相关 DOM/契约回归：studio-planner-regression-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W12 | 阅读“你的要求 / AI 怎样做 / 影响谁 / 保持什么 / 怎样验证”。 | 部分检查 | 真实链路/页面抽样：真实方案审阅与参考可见；多对象全部五维说明未逐项实操。 |
| W13 | 阅读确认框、冻结方案、制作前确认和恢复冻结表单。 | 部分检查 | 真实链路/页面抽样：真实冻结到指定 packet 并读取历史输入；所有恢复/取消分支未逐项实操。 |
| W14 | 选择运行、排队、失败作业和历史，知道当前对象及版本。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W15 | 请求取消、取消确认、停止等待和向服务对账。 | 部分检查 | 相关 DOM/契约回归：studio-protocol-qa.cjs、backend/tests/test_studio_delivery.py；本行完整真实用户操作未逐项验证。 |
| W16 | 作业刷新及断线恢复不重复派发。 | 部分检查 | 真实链路/页面抽样：真实刷新及后端重启未新增 ImageGen；执行作业所有断线重派分支由测试覆盖。 |
| W17 | 查看候选差异、对象映射及按需展开技术证据。 | 部分检查 | 真实链路/页面抽样：真实候选五个对象映射、差异和技术证据可读；所有种类未逐项展开。 |
| W18 | 从候选启动 Godot 试玩，理解运行反馈并停止。 | 部分检查 | 真实链路/页面抽样：初测解析失败已修复，真实页面启动和运行中停止由接受回执及 runner 日志确认，原生日志无错误；见 live-preview-final-readback.json。长浏览器调用响应曾超时；其余异常/恢复分支未完整实操。 |
| W19 | 仅在隔离副本中模拟接受候选，理解当前版本变化。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W20 | 仅在隔离副本中模拟继续修改、填写意见并找到返修上下文。 | 部分检查 | 相关 DOM/契约回归：studio-repair-regression-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W21 | 从结果卡返回原对象、切换候选并继续一轮。 | 部分检查 | 相关 DOM/契约回归：studio-result-context-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W22 | 创建恢复点、覆盖确认与取消、首次覆盖备份。 | 部分检查 | 相关 DOM/契约回归：studio-saved-checkpoint-overwrite-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W23 | 恢复或重置的确认、取消，以及撤销恢复。 | 部分检查 | 相关 DOM/契约回归：studio-restore-history-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W24 | 草稿导出、首次备份导出；确认实际下载或说明无法确认。 | 部分检查 | 相关 DOM/契约回归：studio-corrupt-draft-raw-recovery-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W25 | 损坏原始存档的只读查看、复制、下载及关闭；无自然触发则未覆盖。 | 部分检查 | 相关 DOM/契约回归：studio-corrupt-draft-raw-recovery-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W26 | 基线变化时保留旧稿、重关联与缺失目标处理；无自然触发则未覆盖。 | 部分检查 | 相关 DOM/契约回归：studio-e4-draft-restore-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W27 | 多标签冲突比较、两份内容保留和明确选择。 | 部分检查 | 相关 DOM/契约回归：studio-n2-cross-tab-draft-qa.cjs、studio-visual-feedback-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W28 | 从游戏意图找到对应对象及相关行为，首次不先读操作指南。 | 部分检查 | 相关 DOM/契约回归：studio-workbench-selection-click-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W29 | 修改一个参数，知道当前值、期望值和是否真正制作。 | 部分检查 | 相关 DOM/契约回归：studio-preview-field-refs-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W30 | 添加“只改当前实例、其余不变”的自然语言约束并核对范围。 | 部分检查 | 相关 DOM/契约回归：studio-intent-a3-a5-focused-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W31 | 多目标混合申报、编辑、冲突和取消，确认原文不丢失。 | 部分检查 | 相关 DOM/契约回归：studio-intent-http-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W32 | 提议场景和实例、取消放置、移除草稿及批量移动预览。 | 部分检查 | 相关 DOM/契约回归：studio-local-layout-proposal-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W33 | 从误操作恢复，判断撤销、恢复点与重置的区别。 | 部分检查 | 相关 DOM/契约回归：studio-restore-history-qa.cjs；本行完整真实用户操作未逐项验证。 |
| W34 | 理解失败、拒绝、部分完成、待试玩，找到可执行的下一步。 | 部分检查 | 真实链路/页面抽样：真实候选待试玩，保留取消作业及说明；拒绝/部分完成所有分支未覆盖。 |
| W35 | 宽屏和窄屏的导航、滚动、焦点与模态交互。 | 部分检查 | 真实链路/页面抽样：三档宽度实看，密度键盘抽样；所有模态、滚动与焦点路径未逐项实操。 |
| W36 | 主题、DNA 观察面、网格、辅助标记和诊断展开不改用户内容。 | 部分检查 | 真实链路/页面抽样：密度展示不改业务状态有 DOM 断言；其他观察面/网格/辅助标记主要是相关回归。 |

## 数量核对

共 125 行：完整目标 89 行、页面交互 36 行；部分检查 119 行，未覆盖 6 行，完整通过 0 行。该数字表示本轮检查完整度，不是产品功能失败数。

[正式实施记录](STUDIO-VISUAL-FEEDBACK-IMPLEMENTATION-20261019.zh-CN.md) · [原完整清单](STUDIO-USER-PERSPECTIVE-CHECKLIST-20261015.zh-CN.md) · [完整复制目标](STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.zh-CN.md) · [原文验收基线](acceptance/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.full.zh-CN.md)

## 2026-10-20 交替试用实际操作覆盖

6轮固定T1–T7试用、5批集中修改后，第六轮主要路径无需产品调整完成。每轮均先冻结实现，发现后继续记录，结束并封存后再集中修改；六轮试用中产品修改均0。该结论不包含原125条每个分支的完整通过，也不表示全部旧版复制能力已完成。

| 证据口径 | 部分 | 未覆盖 | 完整通过 | 用途 |
| --- | --- | --- | --- | --- |
| 初次实施技术检查（上方125行） | 119 | 6 | 0 | DOM/契约及真实链路抽样，保持原历史记录 |
| 本周期实际操作（coverage.json） | 99 | 26 | 0 | 正常UI、真实Agent/ImageGen、真实Godot自动输入，逐项保留限制 |

新增真实证据包括概念参考自动完成与修订失效、取消恢复、制作中同packet图、两目标原文与240→300申报、恢复点/撤销/重做/实际导出、真实候选与正式预览启停、240/300各11项玩法检查、390/1280深浅对比。它们补充相应行证据，没有把未走到的分支自动升级。原ID和期待与原清单逐项相等。

本轮对象关系和源映射缺失仍如实显示；精确ID定位不算关系跳转通过。双标签定向工具限制、OS中文输入法、Safari/Firefox、自然澄清、复杂场景/动作/结构及Casino专属语义仍未完整检查。03/04空白采集不算实看，后续截图及DOM测量按各自证据范围记录。

R5首候选避雨边界失败保留，技术修复不回填为R5通过。第六轮首候选入库只用于隔离模拟生命周期；第二候选仍READY_FOR_REVIEW，两条反馈均unreviewed，真人接受未执行。完整目标两份和原125项清单原字节保持，后续验收范围不缩小。

周期证据：[最终报告](../../tmp/studio-user-trial-cycles-20261020/FINAL.zh-CN.md)、[第六轮结果](../../tmp/studio-user-trial-cycles-20261020/round-06/RESULT.zh-CN.md)、[最终技术自检](../../tmp/studio-user-trial-cycles-20261020/batch-05/selfcheck/REPORT.zh-CN.md)、[交付核对](../../tmp/studio-user-trial-cycles-20261020/final-review/audit.json)。

# Studio 旧版复刻验证评估记录

原记录日期：2026-10-14（Asia/Shanghai）。当时状态：工程实施与有限覆盖评估收口；用户验收未进行。

> 2026-10-15 补充复评：用户追加的[深入评估原文](acceptance/STUDIO-INDEPTH-REVIEW-20261015.full.zh-CN.md)提供新的已知问题。原“当前无已知阻塞”结论已被新证据更新。方案制定时仅检查文档和源码，新增问题当时仍待修复、待复验；见[执行计划复评与修订方案](STUDIO-INTENT-INTEGRITY-EXECUTION-PLAN.zh-CN.md)。后续实现和验证的当前结论见[本轮执行记录](STUDIO-INTENT-INTEGRITY-EXECUTION-20261015.zh-CN.md)及末节“意图完整性增量评估”，不把旧通过记录当成本次通过。

2026-10-14 当轮终态见末节“有限最终评估”及PLAN第9节；前文旧PENDING和失败首测保留作历史。下文所称“当前结论”均属于当轮时点，2026-10-15 后续执行以上述补充方案为准。

完整范围继续以 [目标全文](STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.zh-CN.md)、[保留的完整目标基线](acceptance/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.full.zh-CN.md) 与 [89 条覆盖计划](STUDIO-LEGACY-REPLICATION-PLAN.zh-CN.md) 为准。下文保留实施期间各轮读取、发现与复验记录；当时尚未完成的接线不作当前最终缺陷，当前结论以后文“有限最终评估”为准。

## 评估边界

- 已读 `frontend/studio/workbench.js`、正在接入的 Studio HTML、`backend/workbench_results.py`、`studio_protocol.py` 的语义投影/精确来源端点与 `coordinator.py` 集成。
- 本评估代理没有操作正式用户数据、没有自行启动真实 Agent 或游戏；root 使用 8814/8815 与当前 Casino `.workbench` 副本开展真实浏览器与 Agent/独立游戏验证，下文分别记录。
- 本记录中的方法定向执行与 jsdom 是逻辑/DOM 证据，不是实际浏览器渲染、IME、触控、拖拽或用户体验通过证据。
- 没有执行独立 hash 检查；未改运行源码。执行期间的发现以函数名定位，修复后需重新读取并定向复验。

## 首轮发现（历史时点）

| 编号 | 优先级与用户后果 | 证据与复现 | 修复状态 |
| --- | --- | --- | --- |
| E1 | 阻塞：非空意见无法确认提交 | 初次版本的 `reportData()` 调用 `persistCurrentNote()`，后者每次读取都重写 `updatedAt`；完整 notes 进入 `reportFingerprint`。`confirmReport()` 再读取后签名不同，只刷新预览，永远不进入 submitIteration。初次定向执行同内容签名稳定性为 false。 | **BROWSER_AND_RECEIPT_RETEST_PASS**；Kimi 纯自然语言意见预览等待后确认实际收单，同一按钮双击只有一个 proposal。实际 Agent 结果回流另记。 |
| E2 | 高：结构提案输入静默丢给 Agent | 初次版本 `operationText()` 只拼接 `operationLabel()`；过渡遗漏 `condition/presetId`，新实例遗漏 `description`，新场景遗漏 `connections`。初次执行过渡提案出站摘要未含条件/预设。 | **MODULE_RETEST_PASS / PENDING_BROWSER_AND_HTTP**；现有版本完整 JSON 包含上述输入及稳定 operationId，实际请求和服务保留待核对。 |
| E3 | 高：孤儿重关联覆盖已有意见 | 初次版本 `renderOrphanNotes()` 重新关联直接覆盖 `targetNotes[target]`；jsdom 点击使 player 原文消失。对应 G5.6/G5.8。 | **BROWSER_RETEST_PASS（重关联保留原文）**；root 已用 Kimi 实测原 note 保留、单独重关联，再移除隔离 fixture。此结论不扩张为所有草稿冲突路径通过。 |

上述结论对应当时读取的工作区文件，不能据此判断执行代理后续修复仍然失败。修复到位后在本表另记复验结果，保留原发现作为排查记录。

当前隔离副本中的 accepted/candidate 数据没有构成人工认可；本次评估也没有为其赋予用户验收含义。后续浏览器 checkpoint 由 root 使用 Kimi 复测。

## 集成收尾时的 E1–E3 模块定向复验

仅导入当前 `frontend/studio/workbench.js`，使用已有 jsdom 和最小 app 回调，未调用服务、未新增 Agent 任务、未改正式数据。

| 行为 | 本轮执行输出 | 结论范围 |
| --- | --- | --- |
| E1 同原文相隔 12ms 两次 reportData；随后 confirmReport | `sameContentFingerprintStable=true`、`submitCalls=1`、`dialogClosed=1` | 不再因读取更新时间戳卡住确认；此处 submitIteration 是计数回调，尚不能证明真实 HTTP 收单。 |
| E2 过渡条件/预设、新实例描述、新场景连接说明序列化 | `condition=true`、`preset=true`、`description=true`、`connections=true`、`stableOperationIds=true` | 当前 operationText 保留所有检查输入；仍须比较浏览器实际发出的 fields/feedback/operations 和服务保存结果。 |
| E3 点击将 gone 意见关联到已有 player 意见 | `priorTargetNotePreserved=true`、`orphanTextPreserved=true`、`relinkedTargetCorrect=true`、`itemIdentityPreserved=true`、`separateNoteCount=2` | 两份原文和原反馈身份均保留，重关联至 player；真实浏览器刷新后恢复与后端收单待检查。 |

这三项原复现当前均未再出现。此结论不覆盖其他操作或完整目标，也不等于用户验收。

## root 首批 Kimi 真实浏览器发现

以下由 root 实际操作隔离副本后反馈，本评估代理只记录其观察、修复进度及证据界限，没有另行扫描或把转述扩充为其他路径通过。

| 编号 | 真实观察与用户后果 | 定位/修改范围 | 当前状态与待核对 |
| --- | --- | --- | --- |
| E4 | 两个对象的中文意见切换时可见，但目标深链接刷新后 `targetNotes={}`，全部意见丢失。 | UI 代理加入 hydration 屏障，避免 restoreDraft 前的路由初始化覆盖保存内容。 | **BROWSER_RETEST_PASS（同基线深链刷新）**。Kimi 复验二目标中文原文及 feedbackId 完整恢复；随后 CDP 真实 IME 输入骰子意见并刷新，原文保留。跨接受版本的恢复另见 E9，不能以本项替代。 |
| E5 | 实际场景因 scene 未加入 ROLE_LABELS，被显示为“未映射”，并落入默认 100×60 边界展示。 | 前端已调整 scene 角色识别及相关展示。 | **BROWSER_RETEST_PASS（角色与已映射边界）**。root 已确认场景 bounds 为 1152×768，player instance 和 start entry 均为 (576,415)、fixed。此结果不包含可自由移动对象的拖拽验证。 |
| E6 | 环境 preset 被错误命名为“过渡预设”，使用户误解当前配置职责。 | 前端已修改对应标签。 | **BROWSER_RETEST_PASS（标签）**。刷新后配置预设标签正确；此结论不代表独立有向过渡/共享预设完整交互通过。 |
| E7 | Kimi 的目标深链刷新曾返回 403：前端服务将真实浏览器带 cross-site 元信息的顶层 document 导航拦截。 | root 仅放行顶层 HTML document 导航；API 与 mutation 限制保持原有规则。 | **BROWSER_RETEST_PASS（仅顶层深链页面可达）**。Kimi 刷新已回到页面；此结果不证明 E4 草稿恢复、API 请求或提交链已通过。 |
| E9 | 接受候选时 `decideCandidate` 提前给 snapshot 赋值，绕过 rebase；随后实际换版曾被 `this.clearTransientInteractions is not a function` 阻塞。 | 方法已补；root 已完成 revision1→2 冷启动显式重关联并刷新，见 draft-rebase-browser.json。确认前没有 rev2 key，确认后保存新 key、保留旧 key。 | **COLD_REBASE_BROWSER_PASS / WARM_PUBLICATION_PENDING**。两份原文及 feedbackId、speed=260 刷新保留，且不再弹重关联框。下一真实候选的温态发布→重关联→新 key→刷新仍须实测，不能由冷启动路径替代。 |

E4–E7 属于真实浏览器发现，与 E1–E3 的模块复验分别记录。当前部分修复和页面可达均不代表完整目标完成或用户认可。

## root 已完成的真实收单与纯字段处理

证据集中在 [browser-actions.jsonl](../evidence/workflow/studio-legacy-replication-20261014/browser-actions.jsonl)、[纯自然语言收单](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-language.json) 与 [纯字段真实处理](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-field.json)。本评估代理仅针对这些现有记录核对摘要，没有另外发起执行。

| 路径 | 当前真实结果 | 明确限度 |
| --- | --- | --- |
| 纯自然语言意见 | Kimi 预览等待后确认实际收单，双击只产生一个 proposal；首次 planner 遗漏 definition 元数据失败，经保留旧映射修复和原输入重试，已完成真实 native planner→producer→独立 verifier→结果回流。job=`job-a71927e056b74b258523d81059aa1bd5`，candidate=`candidate-cf1231b043a34a378141ec2fb6a71ee1`，候选版本 `602b5c5cc2c3d75e9b6d075bae99b5c78338e1d8`。game_interface.gd 新增失败鼓励文案，技术验证 PASS，Kimi 已打开对应源码 diff，原 feedbackId 保留。 | 真实失败界面尚未操作体验；humanAcceptance=`NOT PERFORMED`。root 在隔离副本模拟发布 revision2 继续测试，非用户验收。不能以源码文案存在及主场景冒烟替代失败界面布局/体验通过。 |
| 纯字段修改 | player.move-speed=250，真实 native plan→produce→独立验证→候选回流；作业 `job-175dd285bf294187919da45508544737`，候选 `candidate-1e442ca3b234413f9084152e2e2a9e2f`，候选 Git 版本 `6563d48d65aa9e9059d3ec14b98be38d10136bc4`。Godot `4.6.3.stable.official.7d41c59c4`、fresh_import、main_scene_smoke 均 PASS。 | technical PASS，humanAcceptance=`NOT PERFORMED`；不是用户体验认可。root 在隔离副本模拟接受以继续测试，不构成人工验收；版本接受时发现 E9，须单独修复与复验。 |
| 二目标原文与真实 IME 刷新 | E4 修复后，二目标原文和 feedbackId 在深链刷新完整恢复；CDP 真实 IME 输入骰子意见后刷新仍保留。 | 覆盖同版本刷新与输入保存；跨接受版本重关联、孤儿重关联完整浏览器链不由此自动通过。 |

窄屏 toolbar 已实际复验：视口宽 390px，toolbar 为两列、控件高 38px，`body.scrollWidth=390`，没有由该 toolbar 引起的横向溢出；见 [04-narrow-toolbar-fixed.png](../evidence/workflow/studio-legacy-replication-20261014/04-narrow-toolbar-fixed.png)。root 另用原生鼠标打开申报单并按 Escape，焦点恢复实测通过。两项结论分别限于工具栏布局、该模态开闭/恢复路径，不代表全部窄屏、焦点循环和键盘路径通过。

### 最近两项实际问题与已有分派

| 用户路径问题 | 当前修复/执行情况 | 验证边界与下一出口 |
| --- | --- | --- |
| 纯自然语言 planner 省略既有 workbench definition 元数据，令 player 实例引用无效 | root 增加 `parse_planner_response(current_document)`：只对遗漏元数据保留旧来源映射，显式提供无效替换仍拒绝；24 项针对性测试通过后，原输入重试已完成真实制作、独立验证及源码 diff 回流。 | 本条失败恢复已具备真实回流证据；仍未测真实失败界面体验，不写用户认可。 |
| 本地 warning-duration 从 1.5 改到 2，控件显示 2，预览时间线仍为 1.5 | model/UI 已准备通用字段绑定与更新，属于当前已分派工作。 | **OPEN / PENDING_BOUND_PREVIEW_RETEST**。同一目标改参数后，时间线/一次播放采用草稿值；撤销/改回原值复原，切目标停止旧播放。只更新标签或单位不足以关闭本项。 |

## 历史批次：当时真实剩余要点

1. **补 E9 温态发布边界与 E10 提交后草稿保留**：冷启动显式重关联已实际通过；下一真实候选发布时检查新 key、二目标原文/feedbackId、提交后新增内容与刷新恢复，不重复已通过的冷启动同例。
2. **完成尚未闭环的形态**：纯字段与纯自然语言已分别真实回流；多目标混合和结构操作仍需实际收单及逐项处理记录。自然语言结果的真实失败界面体验尚未测。
3. **复验 E2 的浏览器与服务边界**：结构全部输入实际到达且保留。E3 现已实际重关联通过，不重复检查已通过的同一路径；双标签与跨版本草稿仍是不同待办。
4. **补 P4 尚未运行的分支**：空白新场景、放置取消零净变化、原生放置/拖拽、坐标、撤销/重做、删除及刷新已有实际证据（见最新记录）；最小模板、选已有玩家入口不重复、固定/可微调约束和独立方向过渡仍需对应路径，不能整类升级为通过。
5. **复验已分派预览同步**：warning-duration 的控件、时间线与一次播放使用同一草稿值；E5 边界与 390px toolbar 已有定向浏览器证据，无新变化不重复整套检查。

完整目标仍以十类 89 条及十四项完成标准为准。本轮证据证明上述具体路径，不宣称完整复刻、全部浏览器通过或用户验收。

## 下一小步：从 89 条中补尚无明确领用记录的直接路径

这里只从既有覆盖计划提取用户操作缺口，不开展广泛静态审计。P4 新场景/放置补齐、E9、自然语言原输入重试和预览字段绑定已有当前执行者，不重复分派；以下是本轮记录中尚未见明确领用的范围，正式派发前由 root 对照正在执行的工作避免重叠。

| 顺序 | 最小具体工作 | 目标条目 | 最短验证路径 |
| --- | --- | --- | --- |
| 1 | 申报单内直接编辑/移除每条意见及字段差异；对控件与原文冲突给出明确待解决项，保留双方内容和身份，不能只显示泛泛提醒。 | G5.8、G5.10、G7.5 | 同目标控件设 2、原文要求 3→申报中看两者→作出保留/改写/澄清决定→移除一项→确认出站内容和刚看过的一致；纯导航不失效。 |
| 2 | 同项目双标签更新提示与比较后保存；保留双方原文，较旧标签不能无提示覆盖新内容。 | G6.4 | A/B 打开同草稿→A 写一句并保存→B 写另一句→出现冲突提示→导出或明确合并→两句都可恢复；不因此启动 Agent。 |
| 3 | 补“导出已保存原文/覆盖前备份”和可整体撤销的“重置当前草稿”；与现有导出当前草稿/恢复已保存分别表达。 | G6.2、G6.3 | 保存 A→改 B→导出 A 原文/备份→重置当前草稿→撤销恢复 B→重新打开 A；每一步说明范围，不删除已保存版本，不提交。 |
| 4 | 独立有向过渡三态、真正过渡预设分类及入口引用校验；当前 Casino 没有的已实现源关系不能捏造，使用中立夹具补齐通用交互验证。 | G3.7、G4.6、G4.7 | A→B 设目标入口/条件/共享预设→B→A 保持不变→切“无过渡/未设置”分别有净差异→非法入口提示→环境配置不会混入过渡预设选择。 |

上述是上一批 N1–N4 的待办顺序记录；自然语言重试现已技术回流，最近下一批按下节 E9→资源/N4→混合提交推进。N1/N2/N3继续保留，每项实现后只跑其最短用户路径，当前文档没有把这些待办写为已完成。

## 资源预览与 N4 的前轮定向只读复查（最新状态见末节）

本节只读取资源预览合同/渲染和过渡表单/校验，未启动额外测试或复制已通过检查。完整 89 条、十四项条件继续保留。

| 能力 | 当前直接证据 | 与完整目标的差距 |
| --- | --- | --- |
| atlas 区域与真实动画剪辑首帧（G3.3） | 前轮仅整张图片的限制已由后续实现更新：`preview.resourcePath + optional clipName` 从精确保留 Git 来源生成 imagePreview，两个定向端点测试 PASS。真实旧资源的 Atlas region 和 run clip 首帧已有技术证据，见 resource-preview-technical.json。 | **技术实现已证实，浏览器路径待测**：裁切→clip 首帧→使用处→返回/评论尚未实际走通。只覆盖静态图片、AtlasTexture、SpriteFrames 源形式，不宣称引擎动画播放。Casino 程序绘制仍不能虚构图片。 |
| 选中有向过渡的精确编辑（G4.6/G4.7） | `workbench.js::openProposal('transition')` 以泛用表单提出 from/sceneId/entryId/mode/presetId；当时读取的表单没有绑定当前 transition.objectId，亦未预填既有目的地/入口/模式。 | 用户对原有边提出修改可能变为一条泛化的新连接意图，无法可靠核对前后及反方向独立；应按原边稳定 ID 编辑。 |
| 真正过渡预设与环境配置分离 | `openProposal` 的 preset 下拉选择所有 role=preset；后端操作校验只要求目标 role=preset。界面文字已区分“配置预设”，但选择与校验仍未区分用途。 | Casino 环境配置仍能进入过渡候选。仅更改导航标签不足以完成 N4，需要可来源化的用途声明及前后端同一筛选。 |
| 过渡入口合法性与三态 | 后端已有目的地 scene、entry 属于目的地、模式/preset 引用等基础校验。 | 应复用，补原边编辑与真实过渡预设用途；无需重写现有协议或另建连接任务体系。未设置/无过渡/引用必须保留不同净差异和前后。 |

### 最小下一批

1. **补 E9 温态发布路径**：冷启动 revision1→2 重关联与刷新已经实际通过；下一真实候选发布时核对接受→重关联→新 key→刷新，并联 E10 提交后新增草稿保护。
2. **资源首帧浏览器小闭环**：精确源 AtlasTexture 与 SpriteFrames 首帧描述已有实现和两个端点测试 PASS；接下来前端用同一目标显示真实裁切、clip 名称和首帧来源，再跳转使用处并能评论。使用旧版已有真实资源或显式中立 fixture，当前 Casino 无图片仍保持程序示意；不做任意资源自动解析平台。最短浏览器路径是“图集资源→区域→行为 clip 首帧→使用实例→返回”。
3. **N4 小闭环**：复用已有 backend 引用校验，精确绑定原 transition ID并预填参数；场景/入口选择器自动带身份；只列真正过渡预设；分别编辑未设置/无过渡/引用并整体撤销。用一组显式 A→B/B→A 夹具验证单方向变化不影响反向、错误入口可理解、环境 preset 不可选。
4. **接一笔多目标混合真实提交**：资源/过渡能力可先独立完成浏览器路径，但完整目标仍要一笔“原文+参数+已应用结构差异”的精确申报与真实逐项回流。不要为了补证据重复已通过的纯字段/纯自然语言同例。

N1 申报内编辑/冲突、N2 双标签、N3 已保存原文/备份/重置仍是完整目标待办；本批选择资源/N4不取消它们。当前 P4 放置/历史代码继续变化，只能按对应实际浏览器路径记录，不能凭函数存在称已完整实现。

## 最短 Kimi 用户检查序列

按以下次序在 root 的隔离项目进行；先发现提交阻塞，再检查 P4 直接操作。未明确执行到的步骤保持“未验证”。

1. **先提交一条原文意见**：精确 ID 搜索选择已映射对象，输入一句中文，打开统一申报，等待一秒后只点击一次确认。核对产生一个持久提案/命令且不是不断要求刷新预览；刷新页面后仍能追踪同一项。若无收单或出现报错，先停在此处定位，不继续堆其他意见。
2. **核对结构提案完整到达**：过渡输入目标入口、明显的条件文本与预设，另加新场景连接说明、新实例描述；统一预览查看完整请求，提交后核对 retained request/operations 中四类文本和稳定操作 ID 均保留。明确区分“用户意图已收单”和“实际结构已改变”。
3. **核对孤儿恢复不丢意见**：在隔离 fixture 使用一个失效目标意见和一个已有目标意见，将前者关联到后者；两份原文应同时可见，刷新后还在，统一申报各自保留身份。通过后移除本测试内容，避免混入真实修改。
4. **一口气走 P4 本地新建/放置闭环**：新建空白/最小场景→能选中该草稿场景→从共享定义开始放置→先预览再取消且零净变化→重新放置并出现草稿实例→拖动或坐标精调→撤销/重做→删除草稿实例。检查固定对象不可移动、选已有入口不重复玩家。若页面只有“提议新场景/新实例”表单与意图列表，应记录“直接操作仍缺失”，不能视为这条路径通过。
5. **检查独立有向过渡与最终取消**：选择出口，分别配置未设置/无过渡/共享预设、目标入口与条件，确认反方向未跟着变化；打开申报确认净变化/原文/范围，取消预览不收单。后续真实处理和独立验证由 root 单独记录，保留“用户认可未执行”。

真实中文 IME、焦点、拖拽位置和窄屏应在上述操作中顺带观察；不以模块或 jsdom 输出代替实际浏览器结论。

## 已观察到的有效基础与限度

- 来源端点根据当前 planning baseline 的 Git 版本读取目标绑定源码或图片，并有无资源/缺失提示；这比将元数据路径直接当静态图片地址可靠。尚未在隔离真实项目通过 HTTP/浏览器逐目标核对。
- `_enrich_workbench_snapshot` 明确共享浏览与迭代验证的投影入口，可让派生目标保持可寻址；模型文件当时尚在执行代理编写，不能提前宣称 Casino 映射完成。
- `iteration_results()` 复用已保留 proposal/packet/job/feedback，不建立另一个任务存储；字段文档值匹配、关联源码路径、技术验证与用户决定分列，未把文档匹配自动称为源码实现。
- 当前 `workbench.js` 已出现搜索/分类/DNA/关系/意见/草稿/统一申报/结构提案/元素预览/结果回链等入口。入口存在不等于旧版完整复刻；特别是实际新建与放置预览、一次播放/停止、约束操作、来源化语义和逐项真实回流，仍需执行完成后逐路径验证。

## 执行完成后的定向验证次序

1. 先复验 E1–E3：意见能真正出站、全部结构输入完整送达、重新关联不丢双方原文。
2. 核对同一稳定目标的目录→预览→详情→DNA→原文→申报→结果回链；至少两目标中文即时保存与刷新。
3. 用现有目标做纯字段、纯原文、多目标混合的申报预览/取消/确认，比较预览和实际载荷；净变化、失效目标、提交后输入不覆盖。
4. 核对 Casino 精确源工程中的玩家/入口、敌人定义/生成、武器行为/成长、环境配置、骰子各阶段；声明来源与预览缺口，不挪用其他 Casino 示例资产。
5. 对照旧版直接操作路径：新场景/最小结构、新实例/放置/取消、坐标/拖拽/约束、双向过渡/预设、提案应用/撤销重做、保存打开/重置/导出。缺失仍记录为缺失，不用“结构修改意见可提交”代替直接操作已经完成。
6. root 的真实浏览器检查负责桌面/窄屏、模态焦点与滚动、中文 IME/键盘/拖拽；真实 Agent 与独立 Godot 验证另记，不把静态或 DOM 回归改称浏览器/游戏通过。

最终只有用户可以决定体验是否满意；工程验证可报告证据与剩余项，不代用户验收。


## 最新定向证据：冷启动重关联、资源技术实现与 P4 原生直接操作

本节取代前文对应路径的旧“全待测/缺实现”状态，不扩大89条与十四项完成条件的通过范围。本轮只读取已有证据，没有执行新浏览器、Agent、游戏或 hash 检查。

| 路径 | 已有实际证据 | 仍需区分的边界 |
| --- | --- | --- |
| E9 冷启动恢复 | [draft-rebase-browser.json](../evidence/workflow/studio-legacy-replication-20261014/draft-rebase-browser.json)：rev1→rev2显式确认前无新key，确认后新key保存且旧key保留；两份原文/feedbackId、speed260与当前来源记录保留；实际Page.reload后恢复且无重关联对话框/错误。 | **冷启动浏览器PASS**；温态revision2→3真实首测另记FAIL，已分派修复、待复验；隔离模拟发布不是用户认可。 |
| 精确来源资源预览 | [resource-preview-technical.json](../evidence/workflow/studio-legacy-replication-20261014/resource-preview-technical.json)：绑定.tres的Atlas区域 `[272,0,288,448]` 使用保留版本像素，dirty工作图不影响结果；SpriteFrames的run剪辑为8帧/12fps，返回真实首帧，不存在clip被拒绝。 | **定向技术PASS；资源控件浏览器PASS（非可玩夹具）**。resource-browser.json已证Atlas裁切288×448、run首帧256×256可见；服务端仍CONCEPT/playable=false，浏览器只覆盖入口visibility gate且禁轮询/无提交。未证明正常进入、使用处返回、主预览跟随、真实Agent或引擎播放。 |
| P4放置与历史 | root真实CDP：空白“筹码练习备场”640×360；放置预览取消为零净变化；原生放置→拖至(416,234)→坐标改(430,240)→撤销/重做→删除→撤销恢复同一实例→重做删除。 | 此条直接操作已有实际证据，不能继续记为全部未验证；最小模板、已有玩家入口复用、固定/可微调约束、独立有向过渡等分支仍未由此通过。 |
| P4刷新与身份 | 现有browser-actions.jsonl的reload后evaluate（time=1791960541.633594）：ready=true，仅保留新场景operationId `722790cf-0bb6-4cd4-b732-97ede46f18e8`，实例仍删除；原feedbackId `3a4de731-5587-4658-b2f1-d76952b4176c` / `0bfd8c96-3c02-4dcd-a793-ec22d81a7b6d`、新场景note `3d98fee1-fbdd-42d1-af09-99232a940b08`、speed260/virtual-stick=false均保留，notice为空。 | **该次刷新状态与身份保留PASS**；不是结构已写回Godot源码。过期preview-report选择器未命中属于测试选择器问题，不记为应用缺陷。 |

### 本次增量：路由、申报控件与真实混合提交

- **P4路由复验PASS**：root已实际刷新确认selected、scene与URL均指向 `draft-scene-722790cf-0bb6-4cd4-b732-97ede46f18e8`；申报不再出现重复project意见。p4-browser.json中的route under repair/pending是前一时点，不能继续作当前结论。已有放置/移动/历史结论保持其原范围。
- **N1局部控件PASS**：[n1-browser.json](../evidence/workflow/studio-legacy-replication-20261014/n1-browser.json)记录同一非可玩通用夹具内，field180→200与原文要求300同时展示；申报内编辑保持feedback身份，选择请Agent澄清后原文/field200仍保留并新增独立决定；移除字段后实际fields=[]；取消未创建任务。限于这些控件，不宣称自动识别语义矛盾、正常迭代入口、实际出站或全N1完成。
- **资源控件局部PASS**：[resource-browser.json](../evidence/workflow/studio-legacy-replication-20261014/resource-browser.json)为显式CONCEPT/playable=false夹具，browser-only visibility gate override、禁轮询、无提交。真实Atlas区域与指定run首帧可见，截图已查看；正常进入、资源使用处/返回、主预览跟随仍未证实，不能计为真实Agent或游戏能力。
- **真实混合已READY_FOR_REVIEW / E10浏览器PASS**：[real-iteration-mixed.json](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-mixed.json)冻结260+反馈0bfd/3d98+new-scene722790cf；proposal-687074fab2904a6e9ce8f8311bbb647e、job-9779f662be39493ea87adea973f55dc2。真实收单后只清已交两反馈和结构操作，8秒延迟期间后加270/aceb0a1f反馈保留；结果视图evaluate（time1791963363.009423）仍保留两者。候选candidate-0c1d5782fc24456db6044437c8052b39，Git ef0630fee73f5b79c9830ef842ddfd5a40ff2f78，独立技术PASS，用户未验收。E10此收单/结果显示路径已通过；温态发布/rebase是另一待测边界。
- **N3真实浏览器PASS**：[n3-browser.json](../evidence/workflow/studio-legacy-replication-20261014/n3-browser.json)：保存A（aceb+270）→编辑B→下载含当前B与保存A→重置仍保留检查点→撤销恢复整份B→原生确认打开A，临时B不在；未触发Agent。confirm弹窗导致工具返回interrupted是原生确认流程，已接受并成功恢复，不记应用失败。
- **N2技术PASS/浏览器待测；N4定向浏览器PASS**：[n4-browser.json](../evidence/workflow/studio-legacy-replication-20261014/n4-browser.json)已实际通过稳定原边ID/预填、过渡preset用途隔离、三态/反向独立、invalid入口提示阻止确认、撤销重做、baseline净零及取消。限显式非可玩fixture、browser visibility override、无提交，不冒充Casino过渡/引擎执行；N2双标签仍待测。
- **通用preview与资源主预览最新fix浏览器PENDING**：root报告修复已实现；需一次实际参数→时间线/播放/撤销及切目标停止、主预览→准确图集/clip/使用处返回。旧fixture可见证据不代替最新fix通过，CONCEPT/playable=false及browser gate override/无提交限制继续保留。

### 本轮证据增量：E9失败、混合实际源与资源使用处准备

| 对应目标 | 当前证据与结论 | 下一出口 |
| --- | --- | --- |
| G6.6/G8.7 温态连续性 | [warm-rebase-browser.json](../evidence/workflow/studio-legacy-replication-20261014/warm-rebase-browser.json)：真实隔离发布candidate0c1d到rev3首测FAIL，pendingRebase为空、fields清空、新key未写；aceb意见和rev2旧记录仍保留。E10收单阶段PASS与冷启动PASS不覆盖该边界。 | 已分派model修复，原失败路径复验pending/270/aceb→确认→新key→刷新；不把UI进行中的部分写入判稳定失败，不作用户认可。 |
| G7.4/G8.5/G8.10 混合逐项源结果 | [mixed-retained-source.diff](../evidence/workflow/studio-legacy-replication-20261014/mixed-retained-source.diff)及更新的real-iteration-mixed.json确认准确骰子追加文案、独立Node2D空场景、稳定sceneId、640×360、无主流程连接。field260由既有StudioRuntime.object_value通用配置读取；运行速度不由文档值匹配自动证明。root报告逐操作结果关联已修。 | 撤回旧“逐操作关联确定缺实现”结论；待新结果卡实际浏览器核对来源/目标回链/限制。完整真实制作与技术PASS不等于游戏文案/速度体验通过。 |
| G2.2/G3.3/G5.1/G10.5 资源使用与返回 | [resource-usage-fixture.json](../evidence/workflow/studio-legacy-replication-20261014/resource-usage-fixture.json)补heroine_frames.tres→legacy-player-visual及三条真实源路径，sourceCommit=1dad5c89090278d335efd1a3c0e46a1d013108ca。 | fixture准备已具备，未据此写browserPASS；CONCEPT/playable=false、无Agent/验收限制不变。下一次只走clip→使用处→返回/意见。 |

layout预览/取消应用/过期和成组history、minimal markers、网格helpers、set-lock及独立语义预览/coverage当前整合中；root报告set-lock后端/schema/planner保护67项相关技术PASS。这些是实现进度，尚非实际浏览器证据；本轮不重读源码、更不将收尾中的瞬时状态列最终缺陷。

### 最短剩余路径优先序

1. **E9原失败路径＋结果卡**：修复后实际温态发布并发load→pending保留270/aceb→确认→新key→刷新；顺带检查新逐操作结果及新场景稳定目标回链。
2. **桌面编排＋键盘**：minimal/既有入口复用/锁定→layout取消零变化、应用整体历史、过期拒绝；顺带grid/helpers、焦点循环/Escape/输入原生撤销。
3. **资源/新语义＋窄屏长文空错误态**：指定clip→使用处→返回/意见、参数/播放停止，选择新语义/coverage入口；390px工作区返回、长文、无匹配恢复及来源错误可合并观察。
4. **N2＋故障恢复核账**：真实两标签比较保留，顺带模态键盘；受控存储写失败保留/导出、坏格式原文下载、断线后原commandId核账不重执行。N3正常路径与N4已过同例不重复。

**历史时点的确定阻塞（已由末节最终评估覆盖）**为E9温态首测失败，当时修复复验待完成；此前发现的坏格式原文导出缺口已给最小修复建议，待整合后真实补证，不提前判当前收尾版本失败。其他未运行分支保留在完整89条矩阵，最终逐行状态等root新浏览器证据再更新；十四项完成标准不缩减。工程验证不代用户验收，`userAcceptance=NOT_PERFORMED`。


## 最后浏览器增量：已关闭路径与待READY收尾

本节是最新状态，取代前文对应过时PENDING，保留原失败历史；完整89条与14条件已逐项写入PLAN第9节。持久证据见 [browser-followup.json](../evidence/workflow/studio-legacy-replication-20261014/browser-followup.json)，逐组附原日志行号/返回值。评估代理只整理已有证据，未操作浏览器、启动Agent/游戏、跑整套测试或独立hash。

- **E9准确边界**：原真实隔离发布rev2→3首测FAIL仍在warm-rebase-browser.json。修复后历史rev2快照+原270/aceb草稿在独立浏览器命名空间温态重放，并发load/pending→显式确认→rev3保存/旧档保留→刷新PASS；不是第二次真实发布，不要求为补证新跑Agent。
- **编排/预览/资源已通过新路径**：时间线/一次播放采用2秒草稿，切目标停止timer；结果逐项卡/稳定scene回链/真实源；fixed/nudge/free、layout取消/应用/历史/过期、grid/helpers、minimal意图/既有入口复用；run256×256/Atlas288×448主预览一份、真实资源使用处返回且原文身份保留。
- **恢复/输入已通过新路径**：两个真实标签比较/保留/恢复双方与ID；390px分屏长文/无匹配恢复/原生Mac文本撤销；受控写失败保留页面及原档，坏JSON/未来schema原始字符串查看/导出。raw只读模态两原档exact可见，18截图root已实际查看；copy pending曾是实际bug，修复后即时手动复制提示/全文选中、超过1.5秒持续且writesPaused。不声称系统剪贴板自动复制成功。
- **检查点与意见已通过新路径**：A保存→B取消覆盖保A→确认B备份A→C覆盖首备A原串不变；实际下载导出文件D/C/A三份原文与feedbackId精确核对，见exports/checkpoint-three-versions.json。合法档rawFor=null正常，raw字段只用于异常原档。申报移除D反馈7102f19d，只余E3791bc99，原文/ID不变且intent.changeRequest.feedback仅E；没有提交fixture。reportData返回intent/notes/operations/publicationRevision，对r.feedback/r.request两个不存在字段的旧探针不记应用失败。
- **命令/来源/模态已通过新路径**：受控丢可逆设置命令回执，原commandId查询accepted且只有1 POST、恢复原项目名；offline来源失败→online精确3源文件/原文不变。申报/提案模态真实Tab/ShiftTab首尾、Escape、overflow/priority/focus、scrollDelta0均复验PASS，覆盖早期失败路径。
- **真实Casino关联已读取**：enemy-roster触发/位置/清理→enemy-kind1推断动态非永久→weapon-loaded-dice→automatic/growth→environment-craps同竞技场配置→dice阶段/来源。DNA同目标、spawn分类仅enemy-roster、主题不改内容，切回Casino原270/aceb保留。

所有通用fixture仍明确CONCEPT/playable=false、browser-only gate override、禁轮询、无提交，资源/N4/控件证据不计真实Agent或引擎能力。纯字段/纯原文/混合三类真实native流程与独立技术PASS已经完成，逐项结果新卡已浏览器核对；不再列旧“混合未回流/结果卡待测”。

| 当前实际收尾项 | 状态 | 最短出口 |
| --- | --- | --- |
| syncUrl重复push，真实Back一次仍同目标 | 已派UI修复，待复验 | 一次选目标→一次Back准确返回→Forward；草稿不变。 |
| 旧两种preset演示提案未接入 | 已派UI补齐，待复验 | 两示例明确演示身份，预览/取消零净/应用成组历史/过期拒绝；不能由layout自动替代。 |
| growth守卫/转换与dice触发/位置/清理原缺口 | **已关闭：真实Casino浏览器PASS** | 最新#987–996与F第19组，实际来源/guard/from/to/清理显示正确；不虚构统一动作时间线。 |

**总体仍IN_PROGRESS_AWAITING_ROOT_READY，userAcceptance=NOT_PERFORMED。** 以上是有限覆盖评估，不是用户验收；真实游戏失败屏/速度/文案体验不由静态源码或技术PASS替代。目标全文、逐字基线、89条与14条件均未缩减。


### 紧接增量：项目隔离、冻结载荷与命令DB核账

F新增coverage-and-view-controls、project-isolation、preview-payload-equivalence、service-command-accounting四组，当前18组。真实所有项目切换到fixture时只恢复fixture原player/clarification/visual，未串入Casino的270/aceb；切回Casino的notes/fields与before整对象相等。Casino previewData.intent与buildIterationIntent整对象JSON相等，270与aceb原文ID保留且未提交。coverage推断筛选精确enemy-kind0/1/2共3/34，待提案筛选新scene共1/34；主题light/dark/折叠/DNA均不改内容。

root只读DB报告精确commandId56ec4e1e-841b-4ff0-ab37-309e46d822cf：commands行数1、关联project_events事件1(sequence6)，第二payload无POST，项目名已恢复。正式/隔离两服务jobs均终态（正式REJECTED1/FAILED2；隔离PUBLISHED3/REJECTED1/FAILED2）。该组明确是root结构化只读报告，不伪造浏览器日志行号；没有新Agent任务。


### 来源语义最后增量：真实Casino复验通过

F第19组casino-source-backed-semantics记录最新真实浏览器#987–996，覆盖此前已发现并分派的语义缺口。隔离后端idle后安全重启（root报告PID31860），项目1376/rev3/source ef0630fee73f5b79c9830ef842ddfd5a40ff2f78。growth显示实际options.is_empty()且experience>=cost()守卫与两条state关系；点击running→upgrade及upgrade→upgrade/running目标，guard/from/to、inference及精确来源相符，意见指向state自身。dice显示实际环境计时触发、落点/第二点策略与清理，来源GDD/dice_event/round_director；1.5/0.4/6阶段保留。automatic按各武器真实分支说明，明确未声明统一阶段时间线，没有拼造时长。原270/aceb意见身份保持。

root另报告semantic focused3 PASS，并将objects.v1.schema的fromState/toState与Python合同同步，单个schema parity test PASS。评估代理只记录既有结果，未重跑。该增量关闭本轮growth/dice/automatic语义缺口；语义推断仍准确标记inference，不计真实引擎播放或体验验收。当前来源台账36目标，前轮34目标筛选证据作为当时快照历史保留。

当前只等待UI历史去重、旧两preset示例与minimal marker最终整合复验及root READY；状态仍IN_PROGRESS_AWAITING_ROOT_READY，userAcceptance=NOT_PERFORMED。


## 有限最终评估：工程范围已收口，当前无已知阻塞

root已给最终READY。本评估只核对既有完整目标、89行、14条件及最后真实证据，没有另起任务、运行全量测试或独立hash。结论为 **COMPLETE_ENGINEERING_EVALUATION**：本轮完整工作台工程实施与有限覆盖验证范围已达成，当前没有必须继续修复的已知阻塞。用户验收仍为 **NOT_PERFORMED**；本结论不替用户勾选目标基线或决定候选体验。

最新F共24组，最后五组关闭全部明确收尾：

- **history-final**：growth→enemy一次Back回growth、Forward回enemy，notes/fields/normalRaw不变；原重复push首测保留。
- **minimal-marker-final**：入口anchorY0、spawn.bottom=floor.top且完整在canvas内，root已实际查看20-minimal-template-fixed.png；19旧裁切历史保留。最小模板仍准确标本地意图。
- **historical-demo-proposals-final**：decor在Casino无显式映射，实际点击正确no-op且不碰player/fields/ops；合成decor应用focused QA PASS单记，不声称真实decor或引擎通过。timing首测真实scalar未识别FAIL保留，scalar+step/minmax修复后1.5→1；取消零净、应用control/timeline/request一致、undo/redo整笔、预览后新增意见stale=true而按钮暂未disabled，但实际点击由guard拒绝，fields仍空、新原文保留，正常草稿原串不变。历史“剑击”名称明确映射到当前真实骰子字段，不伪造剑击动画。
- **primary-service-final**：正式8794真实正常入口canEnterIteration=true、kindREPAIR（既有被拒候选的正常返修上下文，原用户决定未改，非模拟发布）、rev0/source a5145f960ac7dca877882ce2557ce7b40fb2f537，35目标含2state与新dice来源字段；390px bodyWidth390及三pane正常，emulation已恢复。root已实际查看21-primary-workbench-final.png。隔离rev3/sourceef063…36目标多1项真实Agentblank场景，不能与正式混用。
- **service-refresh-final**：final-service-refresh.json保留正式8794/8795与隔离服务PID、全部终态任务及正式原REJECTED/FAILED；testDataCopiedIntoPrimary=false，无隔离模拟publish复制。服务刷新不当候选用户接受。

操作指南已覆盖来源/能力、历史示例、raw恢复/手动复制、保存覆盖取消及首次备份。三类真实Agent完整回流、后续草稿保护、逐项结果及真实源证据、双标签/项目隔离、存储/raw恢复、实际下载、原命令核账、语义与资源边界均有对应记录；旧PENDING仅为历史，不能再当当前缺口。

保留的能力与证据限制：通用资源/N4等fixture始终CONCEPT/playable=false、browser gate override、禁轮询/无提交；资源首帧不是引擎动画；没有来源的统一武器时间线不造；无decor映射不造。E9原真实温态发布FAIL与修复后历史快照重放PASS分别保留，未编造第二次真实发布。未穷举全部组合不构成自动新增待办。实际游戏文案/速度/失败屏满意度留给用户体验判断，不由源码存在或技术PASS代替。

完整89条及14条件终态见PLAN第9节；目标全文、逐字基线保持不变。`userAcceptance=NOT_PERFORMED`，`hashBuildChecks=NOT_RUN`。

## 2026-10-15 意图完整性增量评估

本节取代前节在受影响路径上的“完整收口／无已知阻塞”结论；前节保留其历史证据范围。新反例对应A1–A9、B1–B12、C1–C7，当前实现与实际验证见[本轮执行记录](STUDIO-INTENT-INTEGRITY-EXECUTION-20261015.zh-CN.md)，原89项及14条件的受影响更新见[PLAN第10节](STUDIO-LEGACY-REPLICATION-PLAN.zh-CN.md#10-2026-10-15-意图完整性执行增量)。

本轮已修复入口资源、目标输入归属、申报编辑冻结、决定失效、反馈历史、澄清/READY持久、附件部分成功、项目阶段和路由；统一意见、来源/范围、恢复点、方案五项卡和结果继续调整也已更新。定向QA、真实HTTP收单及有界浏览器复验分别留证；不是一次默认测试的总PASS。

Sol high评估指出并关闭了实际任务/需求投影遗漏、返修配置来源误标及用户要求混入策划讨论的问题；A4原文失效反例曾不独立，执行者先重建有效决定再仅改原文，补齐后只读核对通过。最后定向QA还分别覆盖scope、发布版本、sourceCommit和无依据旧决定。未扩展全仓库审计。

真实制作、实例隔离、奖励个数/总价值保持和第二轮制作的当前结论只由执行记录D2/D3及其实际产物支持；历史三类native及Godot证据不会改写成本版新测。模块通过、READY展示fixture、HTTP留存、文档值匹配、技术冒烟和真实用户体验分别记录。首次使用者五项任务仍为D5 `NOT_PERFORMED`，不由代理操作代替。

D2最终候选c3d905e…补齐遗漏的burst显示增强，实际Godot断言支持六枚各5/总30/寿命6及危险结束后开放奖励；竞技场显示子节点1.1倍、同定义对照默认缩放的实例属性亦通过。共享`character_visual.gd`含对照专用guard，原先“共享渲染不改”的方案句子未逐字满足，后续修复方案明确保留该条件。D2仅在隔离库技术接受为版本4，以继续D3；D3实际原生纯字段候选2b297a2…通过2.5秒及保留断言，保持待审未接受。首轮解析失败、不完整候选测试拒绝及D3非纯字段请求无源码改动失败均独立保留，不归入最终PASS。

[Sol最终有限评估](../evidence/workflow/studio-intent-20261015/final-bounded-evaluation.json)支持上述限定技术结论，没有重复测试。场景属性检查未加入场景树渲染，第二落点为源码规则加直接模拟，不是完整第三轮或视觉/手感体验；模型请求配置与native回报差异亦分列。正式项目候选决定未改变。

完整目标、逐字基线、角色边界、必要方案审阅和正式候选决定保留。`userAcceptance=NOT_PERFORMED`，`hashBuildChecks=NOT_RUN`；本轮没有用户验收。

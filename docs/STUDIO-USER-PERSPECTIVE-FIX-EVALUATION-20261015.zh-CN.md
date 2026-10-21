# Studio 用户视角问题修复与评估

日期：2026-10-15。本轮实施用户批准的 UR01–UR06 修复计划，范围为五项 P2 与一项轻量 P3。验证和用户模拟评估不构成用户验收；不以受控回执或历史技术结果证明新的真实 Agent 制作已完成。

主代理在实施前列出[本轮关联交互清单](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-FIX-CHECKLIST-20261015.zh-CN.md)。GPT-6 Luna max 子代理负责前端实施，主代理集成；唯一的 GPT-6.1 Sol high 子代理负责限定用户模拟评估。原始 125 项清单、覆盖状态、评估及完整复制目标均保留，本轮不重新检查全部能力。

## 六项修复

| 问题 | 本轮行为 | 实施位置 |
| --- | --- | --- |
| UR01 提交反馈 | 内部传递明确的 submitted / blocked / rejected / unknown / stale 结果，弹窗保留原因与原命令身份；同项目已有待审候选或活动作业时在发送前返回“未发送”并提供现有结果入口。仅与本次项目和申报上下文匹配的成功结果可清理对应已提交内容，提交期间新增编辑继续保留。 | studio.js、workbench.js、index.html |
| UR02 跨标签比较 | 以稳定对象、意见和操作身份比较用户内容，先呈现新增、删除、修改；时间、导航与编辑框镜像不制造差异。新场景/实例显示各自草稿中的名称和稳定 ID；旧稿未绑定内容如实标注，完整 JSON 按需展开，原三种选择和并发保护继续使用。 | studio.js |
| UR03 参数说明 | 参数旁列来源值与版本、来源声明的单位/范围/步长和本轮期望；显式来源步长优先于整数控件默认步长，缺失信息标明未声明。输入期间原控件保持，零值、false、空值与改回原值按实际含义处理。 | studio.js |
| UR04 目标范围 | 详情与申报分别说明意见目标、已知修改影响、运行存在方式和生命周期；实例的共享定义关系与独立编辑能力按快照说明，影响不明时仍需策划判断。 | workbench.js |
| UR05 编辑与结果层次 | 迭代编辑保持主位，候选阻塞与审阅入口仍可达；结果依提案/修订/作业/候选身份分组，历史默认折叠并显示失败与待处理数量，原文和技术证据可展开。 | studio.js、workbench.js、workbench.css |
| UR06 重置与撤销 | 重置旁说明清空整个当前项目/发布版本工作草稿、保留恢复点；操作后突出原有撤销入口，复用现有历史机制。 | workbench.js、index.html、workbench.css |

## 定向验证

下列定向脚本通过；围绕走查中发现的问题，只补跑对应回归。没有运行全量测试、构建、Godot 或独立 hash 检查。Node 使用 Codex bundled runtime，`jsdom` 通过现有依赖加载。

| 脚本 | 核对内容 | 证据 |
| --- | --- | --- |
| `studio-user-ux-core-qa.cjs` | 明确拒绝及回执身份；未知后以原 envelope / 命令编号核实；服务已接收后本地渲染失败仍报告已提交；重复点击、后续编辑、项目切换隔离。补查已知待审候选零派发、保留草稿/身份，其他项目与终态作业不误阻塞。 | [原 core 日志](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/focused-core.log)（由实际输出整理）；[最终门禁回归](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/ur01-known-blocker-regression.log) |
| `studio-user-ux-workbench-qa.cjs` | 五种弹窗结果、申报会话与回执身份；正确对账后保留新编辑；实例影响范围；同提案不同修订、失败无候选入口；展开状态、无变化轮询保留节点；混合草稿重置→撤销→重做，恢复点不变。 | [工作台日志](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/focused-workbench.log)；[门禁补修后集成输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/ur01-known-blocker-integration.log) |
| `studio-intent-a3-a5-focused-qa.cjs` | 语义内容比较、目标/分类变更、项目级意见、方案修订输入；参数原值/单位/范围/零值/false/空输入；保护申报编辑与旧决定；候选技术信息折叠。补查整数来源步长 10 的原生 DOM stepUp 100→110、无声明仍显示未声明，以及草稿场景/实例名称。 | [初次集成输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/final-semantic-parameter-regression.log)；[步长补查](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/ur03-step-regression.log)、[最终名称补查](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/ur02-draft-label-regression.log)（后两份由实际输出整理） |
| `studio-n2-cross-tab-draft-qa.cjs` | 存储事件冲突、比较并写入保护、保留稿与原三种显式恢复选择；零 Agent POST。 | [跨标签输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/cross-tab-regression.log) |
| `studio-result-context-qa.cjs` | 历史候选仍绑定其原轮次意见和证据，并保持只读。 | [结果上下文输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/result-context-regression.log) |
| `studio-restore-history-qa.cjs` | 恢复草稿后保留字段和意见基线，单步字段撤销/重做正确。 | [恢复历史输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/restore-history-regression.log) |
| `studio-workbench-p4-qa.cjs` | 复用现有场景/实例、申报决定及恢复点脚本，检查新增发送前门禁没有破坏既有工作台行为。 | [门禁回归中的 P4 输出](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/ur01-known-blocker-regression.log) |

修改后的 `studio.js`、`workbench.js` 与新增 QA 脚本通过 `node --check`。仅在后续相关改动后补跑对应脚本，没有重复扩展测试面。

前端服务 `55764` 已确认返回本轮最新文件。产品增量涉及 [studio.js](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/frontend/studio/studio.js)、[workbench.js](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/frontend/studio/workbench.js)、[index.html](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/frontend/studio/index.html) 与 [workbench.css](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/frontend/studio/workbench.css)。[本轮内容差异](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/product-changes.patch) 从实施前保存的前端文件比较生成，避免把原有大量未提交改动混算为本轮修改。

## 用户模拟复查

唯一评估子代理已通过真实浏览器可见控件完成桌面及 390×844 视口走查，并停止页面操作。主代理已核对报告并实际查看代表性截图。详细记录见[用户模拟原报告](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/user-evaluation.md)及[186 条浏览器操作记录](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/browser-actions.jsonl)。

| 项目 | 实际浏览器结果 |
| --- | --- |
| UR01 | 修前单次提交收到服务明确拒绝，原因持续留在弹窗；补上发送前门禁后，单次确认显示“未发送”、现有候选入口和返回编辑。四个目标的原文、两个字段、分类意见和结构草稿保留。 |
| UR02 | 两标签的不同意见直接可读；完整 JSON 可展开，三种选择及两份原稿恢复可达。补修后新场景标题显示用户名称和稳定 ID。 |
| UR03 | 速度 260→280、预警 2→3 时来源/期望同时可见，输入保留焦点；改回来源值显示无净修改。生命值真实 ArrowUp 从修前 100→101 修正为 100→110。 |
| UR04 | 实例说明与申报均区分目标、影响和运行存在方式；明确共享定义关系、未声明独立编辑能力及仍需策划判断，局部意见原文保留。 |
| UR05 | 迭代编辑与候选阻塞提示可达，历史默认折叠、数量可见。390px 可展开失败无候选记录，读取事实状态与下一步，并回到原目标；没有执行候选决定。 |
| UR06 | 混合草稿重置后清空，撤销恢复四目标和各类内容，重做再次清空；恢复点时间和版本说明保持，最后撤销保留检查稿。 |

走查发现的来源步长被整数默认覆盖、草稿目标仅显示编号，以及已知候选仍发送后被拒绝，均已作最小补修并复查对应路径；没有重新走一遍完整桌面流程。

必要截图：[桌面工作台与重置说明](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/screenshots/02-desktop-workbench.png) · [修前真实拒绝](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/screenshots/04-submit-natural-block.png) · [修后 390px 草稿比较](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/screenshots/07-narrow-draft-name-fixed.png) · [最终 390px 未发送与下一步](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/screenshots/08-narrow-not-sent-final.png)。其余修前与中段截图继续保留，原报告注明用途。

受控逻辑验证负责异常回执、成功与异步交错；浏览器只记录实际发生的用户操作和服务结果。两者的证据不能互相替代。

评估结论：六项主要用户路径已能完成，下一步和折叠内容在本轮桌面/窄屏路径可达。保留一项轻微窄屏残余：最终申报模态内部宽度为 357/350px，约 7px 横溢，原因和入口仍可读可用。此结论不代表所有能力或布局已无问题。

## 数据限制与执行边界

- 隔离 D2 已接受版本 4 将 `dice-burst.reward-value` 的单位声明为“秒”。本轮按来源展示，单独记录此数据限制；没有猜测单位或改写已接受快照。
- 不修改公开 HTTP 协议、存储结构或命令账本；不启动新规划或制作，不替用户接受或拒绝候选，不处理 Runner 环境。
- 用户走查使用隔离后端 `55755` 和新的前端来源 `55764`；本地草稿与原评估来源分开。前后状态边界以实体身份、状态和版本记录核对，不执行独立 hash/SHA/MD5 检查。
- [前态](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/environment-boundary-before.json)与[后态比较](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-ux-fix-20261015/environment-boundary-after.json)确认：隔离评估库与来源库各保留 10 个作业、4 个快照、发布版本 4；作业状态、候选身份和发布身份均未改变。比较范围不包含本地草稿历史或命令回执；修前隔离服务确实记录了一次自然拒绝请求，没有据此产生新制作作业。
- 390px 为浏览器视口模拟；中文原生 IME、触屏软键盘和完整键盘遍历未测。原生 select 的桥接/CDP 操作未成功，作为工具限制记录，没有将其写成产品缺陷或完成决定。零值/false/空值、跨项目隔离、同提案不同修订及并发交错的补充证据来自受控检查，不扩写为实际浏览器覆盖。
- 未覆盖的真实 Agent 制作闭环、原生 Godot 体验和其他能力保持原状态。

## 保留的原始材料

[原始用户视角报告](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-EVALUATION-20261015.zh-CN.md) · [原 125 项交互清单](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-CHECKLIST-20261015.zh-CN.md) · [原覆盖表](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-COVERAGE-20261015.zh-CN.md) · [完整复制目标](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.zh-CN.md) · [完整目标保留副本](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/acceptance/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.full.zh-CN.md)

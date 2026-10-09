# 前后分离方案最终自检

日期：2026-10-09。模式：多轮自检。依据：[self_check 技能](/Users/typ/.agents/skills/self_check/SKILL.md)及其流水线。

检查对象为[候选方案](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/FRONTEND-BACKEND-WORKFLOW-ASSESSMENT.zh-CN.md)的全部流程、契约、失败路径和与原计划的衔接。源码、技能及旧计划仅用于核对依据。按用户“方案自检”的范围，没有扩展为全游戏代码自检或真实构建验收。

代码基线为 `8269227`。自检记录、原方案副本、各轮文档快照和机械检查输出保存在 [.selfcheck/frontend-backend-plan-20261009](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/.selfcheck/frontend-backend-plan-20261009)。没有运行独立 SHA/MD5 检查，没有 Git 暂存或提交操作。

每轮固定科目为 `correctness`、`comparison`、`standards`、`emoji`、`style`、`smoke`。在方案层面分别对应流程与引用正确性、原计划及前轮比较、项目约束、文本扫描、表达与格式、只读文档检查及流程走查。动态科目逐轮登记并防重。

## Round 1

动态科目：

- `boundary-runtime-origin`：前端独立打包后能否保留当前精确 Host/Origin 条件。
- `api-contract-execution-packet`：冻结表单是否足够恢复新制作 session。
- `data-integrity-publication`：工程、语义清单和验证报告是否始终属于同一版本。
- `concurrency-cancel-writer`：取消、超时与迟到结果是否会产生第二个写入者。
- `compatibility-frontend-approval`：前端确认是否有合法的后端消费契约。
- `testability-gm-preparation`：规格与新测试能否在实施前由正确角色准备。

选择依据：这些是新路线相对当前 loopback、单 thread 和人工导入实现的直接变化。

| ID | 原方案问题 | 严重度 | 修订 |
|---|---|---|---|
| SC-01 | 同源代理未说明 Host/Origin 的适配条件 | 中 | 首版由本机服务加载独立前端包，共享 loopback origin；代理和跨端口另设显式契约 |
| SC-02 | 制作包缺少可执行的规格/测试准备顺序及统一 resolver 要求 | 高 | 先独立准备规格和必要测试，冻结精确版本；加入任务包字段、统一 resolver 和角色条件 |
| SC-03 | 前端确认被放在可选/后续迁移中，首轮仍不能保证完整前端流程 | 高 | 将 `interactive_frontend` 契约及 GM 消费端迁移列为新路线前置，不伪造旧 TTY 来源 |
| SC-04 | 验证后更新工程和工作台缺少完整发布单位及崩溃恢复规则 | 高 | 使用不可变 PublishedSnapshot、版本比较和原子指针切换，保留旧有效版本 |
| SC-05 | 取消未规定进程退出、写入租约及过期结果的处理 | 高 | 增加取消状态、超时清理、执行代次和确认停止后释放租约 |
| SC-06 | 新 session 自动执行尚未证实，但实施顺序没有独立能力门 | 中 | 增加阶段 0：验证创建、实际技能与角色执行、前端确认及发布契约 |

修复均限于方案文档，保留用户提出的两部分结构及核心工作流。没有修改旧 GM 权限、确认工具、前端或游戏代码。

验证：逐项复核修订与原计划，文档引用、格式及 emoji 检查通过。通用代码冒烟入口在仅含方案文档的范围内返回 `skip`；这是无代码入口，不记作运行通过。

本轮发现 6 项，修订 6 项，连续无问题计数为 0。

## Round 2

动态科目：

- `api-contract-revision-owners`：确认项目、提案、草稿、发布与源码版本的归属。
- `data-integrity-draft-cache`：检查刷新恢复与重关联是否会覆盖未提交意图。
- `robustness-clarification-routing`：核对明确修改、初始概念及有分歧时的路由。
- `boundary-upload-interpretation`：区分附件用途、有效媒体和执行政策。
- `error-handling-baseline-drift`：检查过期答案、源漂移及接受后发布冲突。
- `testability-pilot-gates`：将各阶段承诺转为可观察的通过及拒绝条件。

选择依据：第一轮补齐了执行契约，第二轮检查前端用户操作及跨版本数据如何进入和离开这些契约。

| ID | 问题 | 严重度 | 修订 |
|---|---|---|---|
| SC-07 | 原流程图强制先回答问题，并把初次/增量表单画成不明确的分支 | 中 | 统一概念与修改入口，有关键分歧才追问；明确准备、冻结、候选展示及发布路径 |
| SC-08 | 草稿持久化只是可能性，自动应用重关联没有可恢复预览约束 | 高 | 指定本机 IndexedDB 的版本隔离及能力边界，先保存旧草稿、审阅预览再换基线；补稳定 ID 迁移及无损要求 |
| SC-09 | 多种修订及 job/session 身份混用风险未具体消除，服务边界过于抽象 | 中 | 列出独立版本归属、最小服务能力和幂等/冲突条件；附件与产物使用受控引用 |
| SC-10 | 阶段证明条件偏概述，用户拒绝及接受后版本冲突缺少明确落点 | 中 | 增加逐阶段正向/反例验收表，REJECTED 状态及接受后阻塞发布规则 |

修订将方案更新为 r3，产品目标和源码保持。首版明确不承诺跨设备未提交草稿恢复、任意工程语义穷尽或远程执行已通过。

验证：对明确参数、初始概念、失效回答、新草稿、拒绝结果及发布冲突逐项走查；图文与状态定义一致。文档机械检查通过；代码冒烟仍为 `skip`。

本轮发现 4 项，修订 4 项，连续无问题计数为 0。

## Round 3

动态科目：

- `security-packet-authority`：审阅确认与任务包能否扩大角色或文件许可。
- `compatibility-schema-migration`：检查旧 bridge、拟议 schema 及前端确认来源的兼容边界。
- `data-integrity-source-catalog`：核对 Git、语义清单和正式证据是否共同绑定。
- `concurrency-multi-tab`：检查竞争答案、冻结及发布的预期版本条件。
- `dependency-health-executor-capability`：复核初始化、规划和制作的能力前置条件。
- `boundary-gm-role-limits`：核对工程外规划、项目内 GM 及独立测试准备的合法顺序。

选择依据：用源 GM 的真实前置条件审阅 r3，尤其检查新项目与已有工程能否共用同一准入条件。

| ID | 问题 | 严重度 | 修订 |
|---|---|---|---|
| SC-11 | 新项目的规格/测试准备被画在初始提案确认前，但项目内 GM 需要先有 project.godot，初始化和实施批准被混在一起 | 高 | r4 区分初始 MVP 提案、独立初始化包、精确实施包；明确初始化验收与准备失败路由，批准范围分别显示 |

验证：无工程时先完成工程外提案，确认后受控初始化，验收通过再规划及测试准备，最终确认实际版本的实施表单；已有工程直接进入准备。失败返回原工作台。其他科目未发现新问题。文档机械检查通过，代码冒烟为 `skip`。

本轮发现 1 项，修订 1 项，连续无问题计数为 0。

## Round 4

动态科目：`robustness-initial-project`、`error-transparency-blocked-demo`、`data-integrity-rebase-preview`、`determinism-id-migrations`、`compatibility-template-version`、`api-contract-approval-phase`。

选择依据：从用户初次创建、看到失败 Demo、收到回流及再次修改的角度完整复核 r4。

| 设计走查 | 核对结果 |
|---|---|
| 无工程、初始化失败 | 初始提案批准仅允许准备；未通过初始化验收时回流失败证据，后续制作被阻塞 |
| 已有工程的明确小参数 | 无关键分歧时跳过问题，检查规格/测试及版本后形成精确表单 |
| 新草稿与返回结果同时存在 | 旧草稿先持久保存，重关联先预览，草稿版本变化使预览失效 |
| 重命名、删除、合并、拆分对象 | 保留或迁移稳定 ID，未知字段与未覆盖项明确，不重编全部对象身份 |
| 规格批准和体验接受 | 分别关联具体版本，初始化批准不能代替实施批准，旧有效决定只按原绑定复用 |
| 不匹配模板/契约 | 保持只读或阻塞，不能静默降级为整个项目修改 |

固定科目复核：方案引用有效；与 Round 3 的 r4 内容相同，未改变产品目标或源码；用户禁哈希规则、原角色及来源边界保留；格式与 emoji 扫描通过。问题 0 项，修复 0 项。文档机械检查通过，代码冒烟 `skip`，连续无问题计数为 1。

## Round 5

动态科目：`error-handling-dispatch-disconnect`、`concurrency-fencing-publish`、`resource-usage-process-cleanup`、`data-integrity-atomic-snapshot`、`robustness-database-restart`、`boundary-rejected-candidate`。

选择依据：复核后端执行与发布的故障窗口，以及需要用户明确决定时的状态落点。

| 设计走查 | 核对结果 |
|---|---|
| 创建/投递后断线 | 持久作业和执行尝试用于对账；无法证明状态时保持 UNCERTAIN 与互斥，不自动创建第二 session |
| 取消及进程超时 | 等待 agent/Godot/子进程停止；超时本身不能释放租约；旧执行代次无权发布 |
| 验证后候选变化 | 原证据失效，不能将新源码与旧通过报告发布 |
| 发布前进程崩溃 | 不可变产物已准备但旧快照引用仍有效，重新读取状态恢复 |
| 发布后服务重启 | 从单一新引用恢复源码、清单、能力、报告和确认的对应关系 |
| 用户拒绝或接受后冲突 | 拒绝保留旧版本并进入新提案；接受后冲突阻塞发布，变化后的候选重新验收 |

固定科目复核：r4 内容与上轮一致；引用、项目规范、格式及 emoji 检查通过，未发现新增冲突。问题 0 项，修复 0 项。文档机械检查通过，代码冒烟 `skip`，连续无问题计数为 2。

## Round 6

动态科目：`maintainability-two-part-ownership`、`dependency-health-existing-blockers`、`testability-requirement-evidence`、`documentation-current-vs-proposed`、`scope-mvp-expansion`、`backward-compat-legacy-boundaries`。

选择依据：从实施交接角度检查职责、真实能力、阶段范围和旧系统的约束是否仍然清楚。

| 设计走查 | 核对结果 |
|---|---|
| 两部分结构与持久状态 | 前端表达与草稿、后端执行与工程分工清楚；session 结束不丢失项目；数据库未复制 PLAN/GAP 的验收权威 |
| 已知环境及源差异 | Godot/Git 的已完成状态与旧评估分开；HUD/title 两处差异、真实 mapping 和测试依赖继续列为实施前事项 |
| 证据链 | 要求、目标、任务、断言、run、源码与确认分别绑定；旧报告、回合完成、候选设计不获得当前请求 PASS |
| 当前实现与拟议能力 | 新 API、状态、字段及前端确认明确标为待实现；没有将源码专用提取器描述为通用解析器 |
| 首版范围 | 本机服务、一种受控模板、精确能力；远程部署、浏览器可玩导出和跨设备未提交草稿同步未纳入首版承诺 |
| 源计划约束 | 独立测试准备、角色许可、精确路径、人工决定及源漂移保护保留；新确认契约必须迁移，不伪造 TTY 或审批来源 |

固定科目复核：方案 r4 与前两轮一致，引用、规范、格式和 emoji 检查通过。问题 0 项，修复 0 项。文档机械检查通过，代码冒烟 `skip`，连续无问题计数为 3。

## 最终结果

| 轮次 | 发现 | 修订 | 方案文档检查 | 代码冒烟 | 连续无问题 |
|---|---|---|---|---|---|
| 1 | 6 | 6 | 通过 | skip | 0 |
| 2 | 4 | 4 | 通过 | skip | 0 |
| 3 | 1 | 1 | 通过 | skip | 0 |
| 4 | 0 | 0 | 通过 | skip | 1 |
| 5 | 0 | 0 | 通过 | skip | 2 |
| 6 | 0 | 0 | 通过 | skip | 3 |

完成 6 轮，累计修订 11 项，最后连续三轮未发现新的方案问题。每轮包含六个固定科目及六个不同动态科目，记账由 [round_guard 状态](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/.selfcheck/frontend-backend-plan-20261009/state.json)保存。

结论：r4 通过本次方案层面的最终复核，可以作为阶段 0 的实施候选。实施前仍需证明新 session 的实际执行通道、前端确认消费契约和正式验证/回流，并完成源差异及映射准备。评估方向可行不等于这些能力已经实现或通过运行验收。

本轮修改仅涉及候选方案、自检报告和自检证据。没有修改前端/后端/游戏源码、原计划、GM 权限或项目执行状态，没有创建制作 session、运行 Godot、导出或执行独立哈希校验。代码冒烟因检查范围内只有方案文档而跳过，未安装依赖或调用全游戏测试。

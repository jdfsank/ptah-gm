# 分图规划与批次生成：最终检查

日期：2026-10-21。延续已有实现，完成分图规划与批次生成路径的复试、集中修复和最终检查。完整验收基线保持原文，构建及检查没有运行独立 hash 校验；源码和 Git index 采用直接字节比较，Git 原生身份继续沿用。

## 交付结果

先展示建议图数、短标题、80 字内计划用途、覆盖概念和状态；展开核对详细说明、相关原文及实际提示词。支持共同风格、逐图编辑、材料选择、排序、增删及拆分。计划最多十二图，每批一至六图。确认后固定来源、说明、提示词和请求编号，共用串行调度，每次派发前检查来源。重启暂停、结果不明先核实、失败暂停、继续与取消余项均保留原记录。图片默认仅检查，采纳须填写用途、保持项和未知项，经原子修订进入后续方案。

本轮发现并修复四项：正常反馈 visualPlan:null 被静默忽略；远程归档后已打开面板控件未即时只读；只读打开创建本地空草稿影响审阅身份；旧 ImageGen 测试模拟 subprocess.run 而实际执行器已用 Popen。前三项已补产品回归，第四项只修测试夹具，避免测试启动真实 CLI。

## 完整试用与真实执行

四轮记录均保留在外层 tmp/studio-visual-image-plan-20261021。第一轮集中修复接口范围和具体建议选择；第二轮完成真实规划与真实两图生成并集中修复来源与归档边界；第三轮验证连续流转，追加旧回归发现只读草稿问题；第四轮从隔离原始基线复试完整路径，全段无产品修改，逐文件比较通过。

第四轮覆盖：READY 未提交补充隔离、打开不改变审阅草稿、读取七张真实建议、填写三项采纳说明、补充与参考原子提交、等待策划、必答澄清、仅参考连续修订、r4 冻结、聚焦编辑时远程归档即时只读且保留输入。请求数始终为原来的两条，旧图来源保持 r1。正常策划回复使用明确标注的夹具，不构成真实游戏制作或用户验收。浏览器驱动尾段一次变量重声明已改为局部作用域后继续，未改产品。

真实只读规划：a3e53ef3-5788-4c35-8424-f8c063e1dfbb；执行 attempt-c3ee943cfac14601b3ab73aaee2ccc3f，gpt-6.1-sol/high。返回七张不同检查目的建议，覆盖牌桌、卡牌正反面、三位对手、六工具和界面。批次 882de839-b130-4e9e-b58a-6b3708318aed 选择牌桌、对手两张。

两图真实串行时间（UTC）：牌桌 08:52:33.248557 至 08:54:33.356757；对手 08:54:33.362472 至 08:56:50.493086。提示词分别 2277、2330 字符，仅携带相关材料。默认请求 low、1536×1024；实际返回分别 1672×941、2172×724，界面保留两组尺寸。人工查看：牌桌有中央暗区和青/洋红桌缘，三位对手有义眼、机械下颌、面罩及青/洋红/琥珀差异。裁切、像素尺寸与小尺寸可读性仍须接入后检查，未自动采纳或新增自动读图请求。

## 验证结果与边界

- 后端完整发现运行 454 项，519.279 秒：453 通过、1 个旧进程模拟夹具失败。修正夹具后 ImageGen 工具四项通过，随后完整 ImageGen 资产、分图批次、视觉材料及单图生命周期四组共 45 项复测全部通过。没有把首次完整运行改写成全绿，也没有重新运行其余已经通过且不受测试夹具改动影响的项目。
- 相关扩大回归 171 项通过。前端十一组关键回归通过：分图、项目视图一致性、视觉策划、视觉反馈、跨标签草稿、冻结参考、协议、路由恢复、历史结果来源、策划和草稿保存。
- 111 个 backend/runners/tools Python 文件 AST 通过；Studio 合同 JSON 可解析；全部 Studio JavaScript 的 smoke_test.py 语法检查通过；backend 与 frontend/studio emoji 扫描均为零；改动范围 git diff --check 通过。
- 全后端通用 smoke_test.py 曾分别因导入根目录和 60/300 秒时限失败，原输出保留。补齐导入路径并运行可观察的完整发现回归后得到上述 454 项真实结果。
- 未新增本轮实际图像请求。原真实执行记录、原提示词及图片保留；隔离服务已正常退出，无本任务 ImageGen 或 Agent 执行进程遗留。原 Git index 字节不变，完整验收基线字节不变。
- 本轮未重启日常服务；已验证的是源码及隔离正式服务路径，不声称日常常驻后端已热更新。

## self_check 多轮记录

每轮固定检查 correctness、comparison、standards、emoji、style、smoke；动态科目依据对应阶段风险选择，逐轮不重复。检查覆盖应用源码、接口及合同、执行器、来源与参考流转，并保留已有项目验收基线。问题轮归零，最后第六至八轮连续三轮零问题。第六轮 45 项后端复测通过，第七轮前端核心复测通过，第八轮核对全量结果、原始执行时序、源码锁与进程清理。各轮语法冒烟通过。

| 轮次 | 动态科目 | 发现 / 修复 | 冒烟 |
|---|---|---|---|
| 1 | source-snapshot-binding, queue-admission-capacity, inline-extension-errors, batch-restart-recovery, planning-task-isolation | 2 / 2 | pass |
| 2 | draft-isolation-materials, cross-project-response-guards, prompt-size-scope, frozen-reference-provenance, archive-live-controls | 1 / 1 | pass |
| 3 | transient-suggestion-state, edited-plan-durability, readonly-review-identity, async-archive-render, legacy-single-compatibility | 0 / 0 | pass |
| 4 | scheduler-single-worker-handoff, source-preflight-per-dispatch, uncertain-no-repost, batch-cancel-terminal-state, runner-profile-freezing | 0 / 0 | pass |
| 5 | api-project-route-binding, material-canonical-order, per-image-unicode-length, reference-adoption-atomicity, history-feedback-versioning | 1 / 1 | pass |
| 6 | provider-fixture-network-isolation, subprocess-mock-boundary, process-group-cleanup-contract, output-partial-rejection, private-error-redaction | 0 / 0 | pass |
| 7 | plan-error-presentation, shared-style-instruction-scope, coverage-deferred-reasons, draft-source-switch-history, batch-confirm-freeze-input | 0 / 0 | pass |
| 8 | full-regression-result-accounting, acceptance-baseline-retention, native-request-timing-sequence, final-source-byte-comparison, temporary-worker-liveness | 0 / 0 | pass |

最终 streak=3，round_guard 状态 DONE。早期失败与修复记录保留，没有用最终结果覆盖原始证据。

证据目录中的关键文件：real-visual-plan.json、real-visual-plan-attempts.json、real-image-batch.json、real-image-requests.json、round04-browser-actions.json、round04-source-comparison.json、round04-final.png、temporary-server-cleanup.json、selfcheck/state.json、selfcheck/backend-full-verbose.txt。

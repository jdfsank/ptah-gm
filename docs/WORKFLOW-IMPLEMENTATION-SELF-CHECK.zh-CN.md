# r4 实施代码最终自检

完成 7 轮；前 4 轮登记并修复 20 类问题，最后 3 轮连续未发现新问题。机器记账见 [self-check-rounds.json](../evidence/workflow/self-check-rounds.json)。这份记录与此前的方案自检分别对应设计和实施。

范围为本轮后端、Studio、模板、固定 GM 审批工具及公共契约，并执行旧前端回归以检查兼容性。保留原始交付档案与历史文档；它们不是新增执行授权，也不做无关重排或清除。每轮固定科目为 correctness、comparison、standards、emoji、style、smoke。动态科目根据当前问题与最新变更选择，所有轮次均不重复。

| 轮次 | 动态科目（选择依据：当轮变更与风险） | 发现/修复 | 冒烟 | 连续未发现新问题 |
|---|---|---|---|---|
| 1 | security-approval-binding, concurrency-process-leases, data-integrity-freeze-inventory, api-contract-studio-controls, documentation-evidence-status | 7/7 | PASS | 0 |
| 2 | robustness-timeout-quarantine, backward-compat-legacy-source-lock, data-integrity-rebase-drafts, boundary-json-exponent, resource-usage-startup-shutdown | 3/3 | PASS | 0 |
| 3 | concurrency-response-generation, error-handling-project-load, security-client-execution-fields, determinism-candidate-publication, testability-cross-project-regression | 7/7 | PASS | 0 |
| 4 | data-integrity-rebase-confirm-cancel, robustness-no-storage-draft, security-production-execution-seams, boundary-producer-cache-files, error-transparency-model-no-edit | 3/3 | PASS | 0 |
| 5 | concurrency-rebase-read-write-return, data-integrity-reviewed-draft-content, compatibility-native-default-mode, logging-isolated-failure-evidence, maintainability-final-interface-map | 0/0 | PASS | 1 |
| 6 | documentation-certification-limits, config-consistency-production-store, resource-usage-verifier-cleanup, backward-compat-reviewed-source-mismatch, dependency-health-local-launch | 0/0 | PASS | 2 |
| 7 | security-checkpoint-file-scope, documentation-launch-handoff, testability-final-regression-inventory, data-integrity-evidence-links, resource-usage-test-surface-cleanup | 0/0 | PASS | 3 |

## 问题与处理

| 编号 | 问题 | 修复与验证 |
|---|---|---|
| CK-01 | 后端 import、异常边界和格式 | 统一 Ruff 格式；异常边界保留失败记录与进程清理。 |
| CK-02 | JSON 浮点溢出 | parse_float 统一拒绝非有限值；嵌套 answers 回归通过。 |
| CK-03 | 冻结提案状态误标 | 显示“已冻结，沿用原制作表单”。 |
| CK-04 | 跨项目候选决策窗口 | 按钮及提交双重校验候选项目与当前快照。 |
| CK-05 | 重复工作台加载 | 按项目复用进行中的请求。 |
| CK-06 | Studio 品牌字符 | 替换 emoji，新增实现扫描零检出。 |
| CK-07 | 实施记录未填写结果 | 按真实证据填写通过范围与未验收状态。 |
| CK-08 | 图片探针格式/可执行位 | 格式化并设置脚本可执行位。 |
| CK-09 | 切项目失败后的错误提交 | 恢复旧身份与草稿；所有已有项目提交绑定发布修订。 |
| CK-10 | 工作台响应/草稿读取乱序 | 用请求代次与快照身份丢弃迟到结果。 |
| CK-11 | 取消 rebase 仍套用旧值 | 先显示新发布值；只有确认后才关联旧稿。 |
| CK-12 | 无存储 rebase 绕过确认 | 提供明确的内存确认/取消，并提示无法持久保存。 |
| CK-13 | 待处理 rebase 可提交 | 确认或取消前暂停迭代入口。 |
| CK-14 | 作业触发的项目加载失败 | 失败恢复项目选择与内容一致性。 |
| CK-15 | 生产可注入测试执行器 | 严格布尔模式；自定义 driver/verifier 仅测试可用。 |
| CK-16 | 制作期缓存目录范围过宽 | 验证前拒绝 producer 的 .godot 文件；独立验证后才允许缓存。 |
| CK-17 | 原生执行指令表达不够明确 | 明确要求实际编辑；未编辑回合仍必须拒绝，不保证每次模型执行成功。 |
| CK-18 | rebase 确认异步返回覆盖新项目 | 每次 GET/PUT 返回后复核代次、pending 对象、项目和快照。 |
| CK-19 | 预览后草稿内容漂移 | 重新预览并再次确认，复制内容必须来自已审阅的草稿。 |
| CK-20 | 迟到存储结果污染当前提示 | 提示与字段更新绑定当前 key、代次和快照。 |

## 最终验证

- 后端 65 项单元/回归通过；每轮冒烟使用项目根 PYTHONPATH 运行嵌套测试，避免包导入路径造成误报。
- 前端 npm test 完整通过（81 项 Python 回归及原有 DOM/契约检查），新 Studio QA 已纳入默认测试入口；语法检查通过。
- Ruff check / format、Git diff whitespace、启动脚本语法检查通过；新增后端与 Studio emoji 扫描零检出。
- 实际三 session 初始化/实现/迭代闭环、浏览器派发与恢复、原生运行画面、真实验证进程组取消、真实图片引用均有独立测试证据。
- 最新缓存范围收紧后，真实初始化通过；两个未执行编辑的模型回合被正确拒绝。日志确认它们使用 default 执行模式。保留 FAIL 记录，不计为完整闭环成功，也未盲目重投。
- 正式服务启动、正常关闭、释放端口及重启通过；正式数据库 0 项目、0 作业、0 审批。浏览器测试区恢复版本 3 与待审阅候选，两个页面控制台无错误。
- Git 原生 inventory 与固定 capability lock 一致；Velvet 的 HUD/title 与原 source lock 未改。未执行独立 SHA/MD5 检查。

## 判断修正与限制

一项初步判断曾认为 effectsMayHaveOccurred=true 必须持续独占。复核后撤销：若整个进程组已确认停止，失败 worktree 不会发布，后续作业从原发布 commit 另建 worktree；新增回归证明局部改动隔离、幂等重放和 trusted baseline。退出无法确认时仍保留 UNCERTAIN。

仅交付 collect-loop-v1 与三个规则参数；通用 grill 访谈、任意游戏适配、自动美术、导出和发行不在本次完成范围。图片探针证明一次引用读取，POSIX 只读设置不应被解释为强 OS 沙箱。模型仍可能未执行请求，后端必须以文件、Git 和引擎证据判定。

实际生产游戏规格批准与真人体验验收：NOT PERFORMED。所有自动化制作/决定证据均为 testData=true、productionAuthorized=false；测试 PASS 不替代人类决定。

详细实施与证据见 [WORKFLOW-IMPLEMENTATION.zh-CN.md](WORKFLOW-IMPLEMENTATION.zh-CN.md)。

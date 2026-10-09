# 剩余任务与停止条件

按顺序建立证据，前置条件未满足不能越级宣称完成。

1. Local readiness：检测真实本机 Codex 版本/schema、skills 显式调用兼容、同项目 idle thread、原权限、Node/Python/Godot/插件。首轮以 Godot 4.6.3 原验证版本核对。产出环境报告；skill listed 和 toolOutput 可见都不是技能执行成功。
2. 项目映射与规格：先审阅 SOURCE-BASELINE-DIFFERENCES.json 中 hud.gd/title_screen.gd 的已有源版本差异，不静默改 lock。实际示例没有 .godotmaker/workbench-targets.json。用单一 resolver 为一个已有参数目标建立精确 mapping，绑定真正 PLAN tag/task/mechanic，按真实 source baseline 审阅。spec 人工门使用真 TTY，在实施前完成；不能由 Submit 代替。
3. 写入范围与测试：逐文件枚举必要 GM 工作流、源与测试产物；角色锁继续约束。新 E2E 测试先独立 Evaluator 审阅/基线，或者明确窄角色扩展，不借假 test_error。差异与 authority digest 再冻结预览。
4. 最小真实闭环：先改一个已有小参数。用户确认冻结 payload 后，证明显式 GM 技能与独立角色、源变更、干净 Godot import、正式 check 的本次 run/report。不得用 smoke/play、旧缓存、旧 verified 行替代。真实浏览器复验窄屏/焦点/IME/拖拽单独记录。
5. 结果关联自动化：补逐目标 request→target→task→assertion 和 run/report 证据，缺一个环节保持 BLOCKED。独立展示 global PASS。当前只有停 bridge 后本地 --import-result 人工流程，尚无自动 run discovery 或自动 source merge。
6. 源码再提取：更新并审阅真实 extractor 锚点/结构，不能仅 accept-reviewed-source 刷新 hash。新 source/test/adapter/mapping 基线清楚版本化，保留新草稿与孤儿评论。
7. Transition：新审规范和测试后实现 JSON/ECS 房间过渡。先单向 black fade，验证 covered 前不换房、placement+camera 后 reveal、reveal 完解锁、none/unset、独立计时、玩家状态保持，以及资源错误/重复输入/取消/timeout 不黑屏。再审逆向和 mask；mask 当前无绑定。完整回滚未实现。

## Feedback 与人工门

反馈六字段固定为 id、mechanics、platform、text、type、source_ref，引用当次合法正式 check run 的证据。implementation 先复现再 gm-fixgap；experience 先复现分类；design_change 先 GDD/PLAN 和新规格；test_error 交 Evaluator；capability 缺失则 BLOCKED。三个门按需出现：spec 在实施前，run acceptance 在验证后，resolve-feedback 在修复/验证后。由用户在实际本地 TTY 输入，不代输、不自动升级权限。

## 必须停下的情况

目标/路径不清，规范或源漂移，映射不合法，资源不存在，权限拒绝，所需能力缺失，thread 不空闲或工程不同，delivery uncertain，证据无法关联或真 TTY 确认未发生。先报告明确原因，保持可恢复状态；不自动重发、重绑线程或拓宽 scope。

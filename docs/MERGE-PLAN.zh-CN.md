# 将工作台合并到源系统

## 目标结构与权威

在实际 gm-non-pk 工程中以薄适配层承载 workbench；建议目录命名如 workbench/frontend、workbench/bridge、workbench/adapter，最终位置由本机仓库约定决定。本包 frontend 是交接快照，不意味着强制采用此目录。PLAN/GAP、当前精确 specification、GM 角色锁和原验证流程继续权威。工作台的 SQLite 只记录提交与传递状态，不成为另一份任务数据库。

同一版本化 target resolver 应统一 UI 选中 scope、semantic catalog 和 GM task/mechanic/source path 映射；不能前后端各自猜目标。稳定 ID、adapter version、sourceBaseline、规范和 authority digest 共同界定一次提交。当前适配器只覆盖已审 Velvet，不能宣称任意项目通用。

## 一次提交

编辑/评论保留为本地草稿。预览展示 notes、类型化净 diff、精确目标、范围、executionIntent、allowedSourcePaths、allowedDiffPaths、规范/权威摘要及人工阶段；冻结后用户确认逐字发送同一 payload。snapshot 仅提供上下文，不授予整个场景或工程修改权。服务器重新解析目标并检查 authority、source、thread、store 和冻结差异；变动就废弃旧预览重新审阅，不自动扩权。

优先本地 1B，绑定真实工程和已有空闲 Codex thread；loopback 同源 bridge。保留幂等 ID、单活动/不确定提交互斥、不自动重发、草稿版本与 source revision 分离，以及原线程权限。Site 演示不接本机。真实技能需显式调用 gm-build 等，并可证明角色分工；仅 toolOutput 投递或 skills/list 不构成执行证据。

## 合法写入与结果

逐文件授权包含真正必要的 workflow 产物，不能用目录/wildcard 放开 .godotmaker、docs、e2e。路径许可不改变角色所有权。规范内容变化必须重新审阅/确认，旧提交不能顺带改规范。当前 controlled inventory 是最终状态审计，不是 OS 沙箱，也不能证明没有临时越权后还原。

正式 check 的 run/report/manifest/digest 要与本次 submission/turn/task/baseline 一致。还需补 request-target-task-assertion 的语义证据，独立区分 implementation、verification、human gate、global run context。当前 import 只记录有界证据，逐项仍 BLOCKED；不要先改展示成 PASS。

原 GM Evaluator 只有真正 test_error 流程允许既有 E2E 调整。新功能先准备并审阅独立测试基线，或先通过明确窄角色扩展的新规范，再建立 source/test/config baseline。Worker 不写 e2e，不伪造反馈或人工事件。

## 源码回流

当前 tools/extract-velvet.py 有硬编码已审锚点。源码变化后要检查提取逻辑和新结构，审阅新语义基线与映射，再生成对应 dist 与 baseline；仅刷新 SHA 不等于理解新功能。用户较新的草稿必须保留并显示待重关联/冲突，不能用运行结果静默覆盖。

## Transition 新机制

这是下一阶段真实运行时工作，当前前端 preset 只是编辑契约。房间使用 JSON 配置和 ECS 重建，不应误写为 tscn SceneTree 换场景。常驻独立遮罩控制 covered→换房→placement/camera→reveal→解锁，去返各自配置。覆盖玩家 HP/能力/checkpoint 保持、AI/输入恢复、none/unset 跳过、无资源/重复输入/取消/超时的非黑屏失败恢复。当前无完整 rollback，不提前承诺。mask_wipe 资源未绑定，先审 black fade；旧链条文档把黑淡变列为样例候选，本交接优先级更新为先已有参数小改动，再做该新机制。

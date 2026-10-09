# 验收矩阵

每项分别记录证据路径、版本、日期和状态。未执行不可填 PASS。

| 项目 | 当前交付状态 | 本地验收证据 |
|---|---|---|
| 183 稳定目标评论、隔离、孤儿、冻结预览 | v6 回归已通过 | frontend/docs/TEST-OUTPUT-v6.txt；本地重跑及真实浏览器 |
| 导航/搜索/hash、模态与焦点、窄屏 | DOM/结构回归通过，真实视觉未验 | 桌面和窄屏截图、键盘/IME/拖拽实测 |
| unset/none/preset 与只读 preset | 契约/回归完成 | 解析和冻结载荷，scope 精确 |
| mask_wipe | 资源未绑定，真实执行 BLOCKED | 已审资源及运行时证据，不可伪造 |
| GM readiness/mapping/diff/digest/scope | 有界校验实现、mock 回归 | 本地真实工程、版本、映射、拒绝样例 |
| 同线程投递与 gm-build | 协议实现，真实执行未实证 | idle/thread/cwd、显式技能、角色和日志 |
| Godot 干净 import 与正式 check | 本条提交链未实证 | 无旧缓存依赖，真实 run/report/manifest |
| 每项实现与 assertion | BLOCKED | request-target-task-assertion 语义覆盖 |
| global run evidence import | 人工有界导入可用 | 停 bridge，原 store/submission/turn/run 绑定 |
| 新功能 Evaluator 测试 | 需独立已审基线/窄扩展 | 权限、角色、断言意图及不可变 baseline |
| 3 类真 TTY 人工门 | 本链未实证 | 原 GM 精确确认/acceptance/resolution provenance |
| 重新提取与草稿保护 | 显式提取/审阅，非自动 merge | 新结构/锚点审阅、基线版本、保留新草稿 |
| Transition 真实 runtime | 未实现闭环 | covered/placement/camera/reveal 时序和失败恢复 |

原框架 evidence/ 的 Godot fixture 和回归只证明当时框架范围，不证明此工作台新请求已通过。证据导入的文件范围检查也不是实时 OS 沙箱。

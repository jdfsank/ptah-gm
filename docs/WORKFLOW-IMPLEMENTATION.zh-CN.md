# r4 工作流实施记录

用户于 2026-10-09 在本对话明确“许可执行”，批准实施经过最终自检的 r4 方向。这是平台开发授权，具体游戏的规格批准与体验验收仍在工作台按版本记录。

目标：独立前端包、本机后端、结构化澄清、不可变制作包、新 Codex session、Git 管理的隔离工程、独立 Godot 验证及语义结果回流。采用一种收集挑战模板证明闭环；Velvet 的既有源差异继续保护。

| 要求 | 内容 | 本次验证 |
|---|---|---|
| WF-01 | 提案/答案/冻结版本、幂等作业和断线恢复 | PASS：Store/API 回归；真实浏览器恢复冻结表单与最新候选 |
| WF-02 | 新 session 实际执行受控任务包 | PASS：三个独立本机 session 完成初始化和两轮规则编辑；另一次从浏览器派发成功 |
| WF-03 | 服务产生并消费前端确认，保留旧 TTY | PASS（机制）：审批消费器与 GM 集成回归；真实生产用户批准尚未发生 |
| WF-04 | 后端管理 Git 工程与精确写入范围 | PASS：新增/删除/越界/基线漂移拒绝；原 Velvet 两处源差异保护未修改 |
| WF-05 | 当前配置、实际运行和语义清单同版本 | PASS：Godot 移动/获胜/失败/重试断言；接受后完整快照 CAS 切换 |
| WF-06 | 前端草稿持久化和显式重关联 | PASS：Studio DOM；真实浏览器刷新后保留版本 3 的文字与三个参数 |
| WF-07 | 限定模板的概念→Demo→增量修改 | PASS：目标 3→5、时限 30→40、速度 220→300 的真实制作闭环；浏览器另制作目标 6 的未接受候选 |
| WF-08 | 图片引用、用途和受控读取 | PASS：格式/大小/数量/用途回归；真实原生 session 正确读取一次参考图片，fixture 零变更 |
| WF-09 | 取消、未知投递、迟到结果及拒绝不发布 | PASS：租约/重启/对账/迟到结果回归；实际 Godot 验证子进程组取消成功 |

以上 PASS 只对应所列机制和限定模板，不表示任意游戏策划或完整 GM 发行认证。实际制作、合成接受与发布探针全部使用独立存储、`testData=true`、`productionAuthorized=false`，不充当用户批准。

审批契约：SQLite `approvals.payload` 与项目内固定路径 `.godotmaker/frontend-approval.json` 注册绑定各自包含 `testData`、`productionAuthorized` 两个布尔值。探针事件为 `true/false`，生产事件为 `false/true`；GM 消费端要求两处标记与服务端上下文一致，并由生产 gate 重新读取已消费的 SQLite 行，校验 event、操作者、项目、阶段、提案/表单/作业/候选修订和当前 Git 规格身份。客户端只提交 `eventId`；事件正文、操作者和私有数据库路径来自服务端登记数据。任一绑定缺失或不一致都不能通过 gate。

文件所有权：主 agent 管理 backend store/server、模板、公共契约、集成与记录；session_driver_r4 管理 native driver 及其测试/探针；frontend_studio_r4 管理 frontend/studio 与 Studio QA；approval_contract_r4 管理审批消费者及获准的 GM 工具集成。独立任务不并发修改同一文件，完整验证与 Git 锁更新由主 agent 串行执行。

不执行独立 SHA/MD5 检查，不自动扩大线程权限，不生成生产图片，不导出或发布游戏。运行失败、缺能力和未验证要求明确记录，源码保护不因平台实施授权而跳过。

## 已交付的边界

前端 `frontend/studio/` 是独立静态包，后端 `backend/` 管理私有 SQLite、图片、Git 仓库、隔离 worktree、native session 和 Godot 验证。浏览器没有选择目录、执行命令或权限 profile 的接口；每个 POST 要求精确 Host、Origin 和 session token。JSON 拒绝重复键、非有限字面量和浮点溢出，图片需经过 Pillow 内容验证。

本轮只支持 `collect-loop-v1`：方向键/WASD 移动、集齐目标获胜、倒计时失败、R 重试；目标 1–8、时限 10–300 秒、速度 60–400。澄清使用可审阅的固定问题与范围确认，尚未实现开放式 grill 访谈和任意游戏的代码生成。图片按声明用途传入制作 session，程序图形模板不会因此宣称已制作美术。超出模板的原始概念会保留并阻塞，用户可明确暂停额外机制。

新工程分为两个确认边界：初始化 session 只写 `initialization.json` 并返回不可玩的准备快照；随后工作台确认绑定 GM 规格、PLAN、测试和 Git 基线的玩法表单，另一个 session 只写 `config/rules.json`。生产 IMPLEMENTATION 必须通过固定 GM 消费器读取并消费真实前端事件；测试模式无法通过此生产 gate。

`completed` 仅说明模型回合结束。候选必须通过独立写入审计和 Godot 运行断言，用户审阅后才将源版本、语义清单和运行报告整体切换。未接受的候选不会替换当前工作台版本。制作期间的草稿按项目/发布修订保存；迁移需要明确预览与确认。

## 实际证据

| 证据 | 结果及范围 |
|---|---|
| [三 session 闭环](../evidence/workflow/integration/real-workflow-probe.json) | PASS；三个不同 session，测试发布修订 3，commit `fdfd07dbe96303b547e9f0e03f2308e64652177a`；三次 Godot 报告均 PASS，engine diagnostics 为空 |
| [浏览器派发](../evidence/workflow/integration/browser-dispatch-job.json) | PASS；候选 `412c9c5ad7dff29bf13f98b6acf29697997849df`，目标 6；独立 verification worker 进程组已退出，候选仍待审阅，发布修订仍为 3 |
| [验证取消](../evidence/workflow/integration/verifier-cancellation.json) | PASS；观察到正在运行的 Godot 子进程，取消后完整验证进程组消失；返回 VERIFY_CANCELLED |
| [原生运行截图](../evidence/workflow/integration/visual/visual-qa.md) | PASS；从精确 candidate Git archive 在可丢弃预览中捕获 960×540 运行画面；无运行日志错误 |
| [正式服务启动](../evidence/workflow/integration/production-startup.json) | PASS；8765 正式存储为空，启动/正常关闭/释放端口/重启均已观察；没有生产游戏批准或验收 |
| [真实图片引用](../evidence/workflow/reference-image-probe/result.json) | PASS；独立原生 session 正确描述参考图的场景/HUD，工作树零变更；仅证明一次引用读取，不代表通用策划或资产生成 |
| [首次探针拒绝](../evidence/workflow/integration/first-probe-ignore-rejection.json) | 保留修复前模板缺少 GM 临时文件忽略规则时的真实拒绝；未伪装为成功 |
| [未实际编辑的拒绝](../evidence/workflow/integration/final-probe-no-edit-rejection.json) | 模型回合 completed 但未改文件，精确内容审计拒绝；没有候选或发布 |
| [缓存范围收紧后的探针](../evidence/workflow/integration/final-source-gate-rejection.json) | 初始化实际编辑并独立验证 PASS；下一次实现 session 未实际编辑，正确 FAILED；不把该次探针计为完整闭环成功 |

制作和验证都持久保存启动前租约，并拥有独立进程组。取消与超时先停止整个组，再确认退出；重启将未完成作业封为 UNCERTAIN。对账仅观察服务器保存的组，缺少租约、仍存在或无法观察时继续独占，不扩大权限、不杀无关进程、不自动重投。

`effectsMayHaveOccurred` 表示可能有局部写入，不能当成可发布结果。若完整进程组已确认退出，失败结果只保留在隔离 worktree 中，不发布；相同 packet 幂等返回失败 job，新表单另从原发布 commit 建 worktree。新增超时回归覆盖了局部修改隔离、发布不变、无自动重投和下一次 trusted baseline。无法证明退出时仍保持 UNCERTAIN 独占。

实际用户的游戏规格批准与体验验收：**NOT PERFORMED**。自动化 probe 的接受操作、单元测试中的审批 fixture 及服务器的生产模式配置均不能替代这些决定。

## 启动与后续

双击仓库根目录 `start-studio.command`，打开 `http://127.0.0.1:8765/studio/`。安装路径与环境变量沿用 `LOCAL-SETUP-GIT.zh-CN.md`；Godot 为 `/Applications/Godot.app/Contents/MacOS/Godot`。开发依赖和状态存储不进 Git，提交仅包含代码、模板、文档与脱敏证据。

后续扩展需要新增有明确能力、规格、写入范围和验证断言的适配器；再逐步引入开放式访谈、更多语义编辑和资产流程。本轮完成的是经过运行验证的前后分离基础与一个可继续迭代的闭环。

实施后的最终自检见 [WORKFLOW-IMPLEMENTATION-SELF-CHECK.zh-CN.md](WORKFLOW-IMPLEMENTATION-SELF-CHECK.zh-CN.md)：7 轮，登记修复 20 类问题，最后连续 3 轮未发现新问题；65 项后端测试及前端完整回归通过。

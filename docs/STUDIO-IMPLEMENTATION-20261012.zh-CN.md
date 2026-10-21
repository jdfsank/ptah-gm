# Studio 最终修改方案：实施与验收记录

日期：2026-10-12（Asia/Shanghai）。设计依据：[最终修改方案](STUDIO-FINAL-MODIFICATION-PLAN.zh-CN.md)。改动保存在本地工作区，未创建提交。

> 本文是初次实施记录的历史快照；之后的 24 场景初次验收及失败证据保留在[全功能验收记录](STUDIO-ACCEPTANCE-20261012.zh-CN.md)。当前受测结论见[Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)：受测范围内四项角色探针、真实 Runner 注册与 fixture 控制的业务闭环通过；后端 283/283（零跳过），前端既有 19/19 未重跑。用户玩法/视觉验收仍为 `NOT_TESTED`，尚无用户接受的生产候选；请求 effort=`max` 不是实际 effort 观测，实际 effort 和完整计费未知。能力由每次 Runner 启动时的新鲜本机证据派生，详情与限制见当前报告。

**结论：A/B 的协议、交互和持久恢复实现已落地；C/D 的独立执行器、输入准备、交付验证和运维入口已落地并完成受控回归及四进程冒烟。整个方案尚未达到全部验收完成条件。** 原生工具与认证读取分离、策划禁止执行工程脚本，以及真实 Godot 角色权限仍未通过实测。真实 Runner 因此注册空执行能力，新版策划、制作、验证和试玩保持禁用。创建项目、编辑草稿/设置和查看资料可用。

本轮没有启动真实策划或制作模型回合，没有接受用户生产候选，没有修改用户游戏。原有项目、批准、未提交修改及六份设计附件保留。此前 2026-10-09 的模型/游戏 fixture 证据属于旧工作流，不能充当新版权限验收。

## 1. 实际代码范围

| 批次 | 已实现行为 | 主要入口 |
| --- | --- | --- |
| A | Studio v1 消息与严格 JSON；持久 commandId/回执；项目协议分流；READY 继续讨论；逐条反馈决定/理由；完整不可变审阅计划；两角色模型、effort、时限及软预算设置；真实目录与配置观测分层 | [共享契约](../contracts/studio/README.zh-CN.md)、[后端协议](../backend/studio_protocol.py)、[对象协议](../backend/object_protocol.py)、[原生驱动](../backend/codex_driver.py)、[Studio 前端](../frontend/studio/studio.js) |
| B | 业务事实、回执/报告和公开事件同事务；一致视图 throughSequence；带授权头的 fetch SSE；项目代次、去重/缺口恢复；串行 GET 降级与版本草稿重关联 | [HTTP/SSE](../backend/server.py)、[协调器事务](../backend/coordinator.py)、[前端通信与草稿](../frontend/studio/studio.js) |
| C | 独立 AgentRunner；冻结配置和领取复核；本地领取/启动意图与报告 outbox；租约未知保留占用；本地停止监督；后端持久消费批准后幂等准备 GM 确认输入；制作私有仓库与封存引用 | [AgentRunner](../runners/agent.py)、[日志与访问策略](../runners/common.py)、[GM 适配器](../backend/general_gm_integration.py)、[固定 GM consumer](../sources/GodotMaker-non-pk/tools/review_support.py) |
| D | 独立 ProjectRunner；精确 Git 工件复制；验证期间源内容审计；隔离试玩副本及停止入口；精确候选与体验反馈；接受事务保留 Snapshot 引用，物化可重试；四组件入口和协调备份/新空间恢复 | [ProjectRunner](../runners/project.py)、[验证器](../backend/general_verification.py)、[独立前端服务](../tools/studio_frontend.py)、[启停工具](../tools/studio_services.py)、[备份恢复](../tools/studio_store.py) |

原有 `studio.objects.v1` 对象文档和批准表继续使用。新增命令、报告、领取和项目事件表，不增加第二个批准库或独立业务状态机。每个新项目标记 `protocolVersion:1`、`executionBackend:runners`，后端不为这些任务启动旧执行线程。旧项目仍走旧写入口，服务器拒绝新版项目通过旧流程绕过命令门禁。

策划材料由后端静态读取精确基线，限制源片段数量与字符数并标记遗漏；不靠工程脚本生成检查材料。生产者收到受信输入与确认记录，不收到后端数据库路径或用户批准凭据。范围、完整审阅、批准、停止、工件和独立验证须由后端再次核对。`scripts/ui/hud.gd`、`scripts/ui/title_screen.gd` 的历史源差异拒绝检查保留。

## 2. 关键恢复与竞争规则

- 同 ID、同内容返回原回执；改变内容明确冲突。业务拒绝也保存回执。页面保存原命令和原内容，丢失响应先查原意图。
- 后端重启沿用 storeId，改变服务实例和用户写 token；内部 Runner token 保持。旧备份恢复使用新的 storeId，旧回执/事件分代保留，旧 Runner 日志隔离，能力重新验收。
- Runner 先保存领取和启动意图，启动意图只能消费一次。未知执行不能自动重投；终态事实在 ACK 前保留，ACK 身份不符时不删除 outbox。
- 后端重启或租约失效保留执行占用。普通心跳不恢复授权；迟到启动事实只补可信身份，恢复须核对同一身份。迟到停止核账不能撤销已完成候选或已接受快照。
- 取消先提交阻止候选；完成先提交并进入验证时，取消转向当前验证代次。准备输入期间取消不会重新入队，排队试玩停止不会启动 Godot。
- 已消费的 GM 批准决定先持久保存，输入准备失败后复用同一决定。重放校验 prepared.json、精确 HEAD、干净工作区、规格/模板清单、源引用及真实 GM 阶段确认。
- 完成报告必须有先前可信原生身份和确认停止。制作不能以自报 PASS 成为候选，源漂移不能借用旧验证。接受保存权威快照引用，磁盘物化失败进入 PENDING；重启重试派生操作。
- 技术验证不默认解决反馈。候选接受可记录 needs_followup，未明确验收的反馈仍保持未解决。试玩身份从公开视图恢复，刷新或服务重启后仍可请求停止。

## 3. 验证证据与复现

所有新增协议/交付测试使用临时状态目录，原生终态和用户接受使用受控 fixture；这些只验证门禁、持久性和版本绑定，不是用户体验验收。

| 检查 | 实际结果与范围 |
| --- | --- |
| 后端协议与交付定向回归 | 32 项通过，覆盖回执重放、事务回滚、事件补齐、配置冻结、租约失效、迟到身份、取消竞争、输入准备恢复、精确候选、快照物化和预览恢复 |
| Runner 与 GM 适配定向回归 | 初次收尾 22 项通过；最终 Runner 的 17 项及 Schema 的 3 项共 20 项通过。覆盖真实 macOS 拒绝探针、独立 Git 副本、持久意图/ACK、新空间隔离、断连循环、软预算、预览源审计、HTTP 错误分类及 outbox 容量保护 |
| 前端 DOM/契约 | 19 个 `frontend/tests/*.cjs` 实际通过；预览恢复/停止新增覆盖在 `studio-protocol-qa.cjs` 中通过 |
| 原生/Schema 审阅 | 原生回合终态必须匹配 turn/start 的 turnId 与 threadId，缺少明确状态不当作成功；Schema 使用 jsonschema 实际校验，不将跳过计为通过 |
| 独立部署冒烟 | 四个组件在一次性状态目录独立启动，读到 8 个原生模型；实际 ProjectView 通过 Schema，两个 Runner 在后端离线 6 秒期间保持进程；重启保留 storeId/原回执，旧写 token 拒绝，随后全部确认停止；零模型回合。见[进程冒烟记录](../evidence/workflow/studio-v1-services-20261012.json) |
| 最终回归 | 完整后端回归 225 次测试执行全部通过，覆盖 212 个不同用例；之后去除了导入夹具造成的 13 项重复发现，并完成上述受影响的 20 项回归。Schema 检查未跳过。前端 19/19 通过。Python/JS/shell 语法、严格 JSON、88 个本地文档链接及 git diff --check 通过 |

后端运行时仍只需 [`backend/requirements.txt`](../backend/requirements.txt)；Schema parity 测试另需 jsonschema。此次使用有 Pillow 与 jsonschema 的 Python 3.11 解释器运行测试，未把 `.venv` 中因缺少 jsonschema 而跳过的结果计为通过。

```sh
python -m unittest discover -s backend/tests -p 'test*.py'
```

前端使用 Node 与 jsdom 直接执行测试脚本，避免旧 npm test 的历史 checksum 前置步骤：

```sh
cd frontend
for studio_test in tests/*.cjs; do node "$studio_test" || exit; done
```

本轮没有执行独立 SHA/MD5 检查或旧校验和工具。版本/范围核对采用 Git 原生身份、清单和差异；Godot 临时验证副本使用逐文件原始内容比较，缓存仅排除 `.godot/`。

## 4. 与方案第 9 节的验收对应

“通过”仅指此列的 fixture、DOM 或进程检查；未标真实集成通过的场景仍需上线前验证。

| 方案场景 | 证据与当前判断 |
| --- | --- |
| 空项目、READY 回改和旧确认拒绝 | DOM 与完整审阅/修订回归通过 |
| 未加入反馈文字、三条逐条决定与关联 | DOM 与 feedbackDecisions 覆盖校验通过；体验决定独立保存 |
| POST 响应丢失、同 ID 重试/换内容 | 持久回执与冲突回归通过 |
| 后端重启、旧写 token、草稿和原意图 | HTTP 握手、重启身份与前端命令恢复通过 |
| 慢 GET、新发布和人工草稿重关联 | 前端 DOM 回归通过 |
| 非法 JSON、身份错误和任意额外 config | 驱动、对象协议、HTTP 和 ACK 身份回归通过 |
| 模型/effort/模态冲突与目录改变 | 冻结 profile 和拒绝回归通过；真实模型回合配置未验 |
| 设置/草稿/刷新/目录/心跳零新增回合 | fixture 无新 attempt；真实目录和服务冒烟零回合 |
| 请求、线程默认 effort 与回合实际值 | 原生回执分层回归通过；最终 actualProfile 无报告时保持 null |
| 快照至订阅空窗更新 | throughSequence 之后事件回放回归通过 |
| 断流、重复、缺口、过期游标、项目迟到 | 后端游标门禁和前端状态流恢复回归通过；未覆盖所有真实长连接故障组合 |
| 领取/启动响应丢失或崩溃 | 本地日志、单次启动意图、原领取 ID 重放回归通过；真实原生崩溃链路未验 |
| 后端重启、租约过期且 Runner 仍执行 | UNKNOWN、占用与核账门禁通过；真实持续模型执行未验 |
| 终态 ACK 丢失后租约变化 | 原 reportId 返回原 ACK 回归通过 |
| 取消/完成竞争、停止未知 | 制作转验证取消、准备取消、迟到核账、停止未知门禁回归通过 |
| GM 消费后崩溃、伪造确认或漂移输入 | 持久批准恢复、GM consumer 与准备重放拒绝回归通过 |
| 工具/游戏跨项目、批准接口访问拒绝 | 基础真实文件/loopback 探针通过；完整角色边界未验，能力禁用 |
| 重复/迟到/缺失/重置用量、子线程缺口 | 累计快照门禁和未知显示通过；子线程/外部工具完整覆盖未证明 |
| 后端离线时本地时限/软预算停止 | 受控 worker 和断连循环回归通过；真实模型网络/停止延迟未验，软阈值不承诺硬上限 |
| 未停止制作、验证漂移、导入改变源 | 完成门禁、保护文件、临时副本内容审计回归通过；新版真实 Godot 权限未验 |
| 试玩副本与新一轮/拒绝候选 | 独立 Git 副本、源审计、恢复和停止回归通过；真实并行 Godot 试玩未验 |
| 接受但一条 needs_followup | 精确版本发布并保留该反馈及未验反馈的回归通过 |
| 物化失败、旧备份、新空间、协议不兼容 | 快照引用/重启重试、协调备份、新 storeId、只读兼容回归通过 |

## 5. 尚未完成的角色验收

四种能力 `planning-readonly-v1`、`production-private-v1`、`verification-isolated-v1`、`preview-isolated-v1` 当前均未由真实 Runner 声明。注册门禁要求 deny-default 策略、verifiedCapabilities 与逐角色 PASS，基础探针不能启用它们。

Agent 原生 app-server 与工具子进程当前共享认证/配置读取范围。原生只读或 workspace-write 参数不能证明工具读不到凭据，也不能证明策划无法运行任意工程脚本。已有规则拒绝另一项目和 loopback，但认证/工具分权及执行工具约束仍缺少真实拒绝证据。

ProjectRunner 已移除 `~/.codex` 读取授权，试玩只授予本次源副本、声明缓存/临时目录及 Godot 依赖；验证另外需要受信验证代码。新版真实 Godot 导入、主场景、GUI 试玩、派生缓存和进程权限范围尚未完成集成验收，当前不得据受控 worker 或旧 fixture 开放能力。一般玩法/视觉质量仍须用户体验。

后续启用需要完成角色探针并保存真实证据：原生模型认证可用时工具无法读取凭据/后端数据/其他项目；策划无法执行工程；制作仅可写私有批准范围；Godot 仅可访问本次验证/试玩副本和声明依赖；相关后代进程停止可核实。不得通过修改注册声明跳过这些检查，也不得把本报告改成全量验收 PASS。

## 6. 启停、备份与交接

```sh
.venv/bin/python -m tools.studio_services start
.venv/bin/python -m tools.studio_services status
.venv/bin/python -m tools.studio_services stop
```

独立前端：[http://127.0.0.1:8764/studio/](http://127.0.0.1:8764/studio/)。后端默认 8765。原 `start-studio.command` 与后端静态入口保留。分组件启停、状态含义、token、日志路径、正常/未知停止见[部署手册](DEPLOYMENT-MANUAL.zh-CN.md)；操作流程和当前能力提示见[用户手册](USER-MANUAL.zh-CN.md)。

备份工具要求后端与标准 colocated Runner 都已停止，使用 SQLite backup 保存 WAL/outbox，复核被引用 Git 工件。外部手工配置的 Runner 日志不自动发现，须另行停服和协调保存。恢复到新目录、新 storeId，隔离旧意图并清空已验能力；历史 worktree 的绝对路径须独立核对。不会覆盖现有状态目录。

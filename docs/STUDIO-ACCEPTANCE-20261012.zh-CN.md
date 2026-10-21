# Studio 全功能验收记录

> 历史快照：本文保留初次验收的失败结论、证据与 24 场景状态，不被后续结果覆盖。最新结果见[Studio 边界修复与补充验收](STUDIO-BOUNDARY-FIX-ACCEPTANCE-20261012.zh-CN.md)：受测范围内四项角色探针、真实 Runner 注册及 fixture 控制的业务闭环通过；后端 283/283（零跳过），前端既有 19/19 未重跑。用户玩法/视觉验收仍为 `NOT_TESTED`，没有用户接受的生产候选。能力按每次 Runner 启动时的新鲜本机证据派生；详情见当前报告。

日期：2026-10-12（Asia/Shanghai）。依据：[最终修改方案](STUDIO-FINAL-MODIFICATION-PLAN.zh-CN.md)第 9 节全部 24 个场景。

**整体结论：未通过上线验收。** 协议、界面、持久恢复的回归与实际 HTTP/SSE/浏览器检查通过；真实进程检查发现原生策划隔离不成立，Godot 独立导入验证失败。四项角色能力仍注册为空，新版策划、制作、验证和试玩继续禁用，不能交付为可完成制作闭环的版本。

本报告区分实际进程/浏览器结果与受控 fixture 结果。全部场景均列入矩阵，依赖禁用角色的完整制作链路标为阻断；没有用合成成功报告代替真实制作或接受用户候选。三个子代理采用用户指定的 gpt-6-luna / max，分别负责回归、通信恢复、界面；主代理负责真实原生与 Godot 进程检查及集成修复。

## 实测证据

| 检查 | 本次结果及证据 |
| --- | --- |
| 完整后端回归 | 初始代码 212/212 通过、0 跳过；验收修复后六个受影响模块 96/96 通过、0 跳过，包含四项新增用例。Python 3.11、jsonschema 4.19.2 实际运行。见[回归记录](../evidence/workflow/studio-acceptance-regression-20261012.json)，不把新增定向执行冒充全套重新发现 |
| Agent 生命周期实际子进程 | 3/3 通过：输出超限停止外层和独立 native 组且不封存；leader 先退出后仍按时限停止 native 组；无可信 native identity 时 stopped=false 并保留临时目录。见[生命周期记录](../evidence/workflow/studio-acceptance-agent-lifecycle-20261012.json)及[测试](../backend/tests/test_agent_lifecycle.py)；worker/native 为真实 Python 子进程，无模型回合 |
| 前端回归 | 19/19 脚本通过、0 跳过；直接 Node + jsdom，未调用旧 npm checksum 前置入口；修复后的预览动作门禁另外复验 |
| 实际 HTTP/SSE 与备份恢复 | 快照订阅空窗补发、断流续传、重复游标、future cursor 409、跨项目隔离、重启旧 token 403/原回执恢复、活跃 Runner 锁阻止备份、新 storeId 恢复/旧启动意图隔离均通过；见[通信记录](../evidence/workflow/studio-acceptance-transport-20261012.json)及[复现脚本](../tools/studio_acceptance_transport.py) |
| 真实浏览器 | 空项目、A/B 草稿切换隔离、保存偏好不创建 attempt、候选/排队预览刷新与停止持久化；候选/目录来自明确标记的临时 fixture。启动能力为空时保持禁用。见[界面记录](../evidence/workflow/studio-acceptance-ui-20261012.json) |
| 原生沙箱 | app-server initialize + command/exec，零 thread/turn：显式 readOnly 仍能执行合成工程脚本；readOnly 与 workspaceWrite 都读到 `~/.codex` 中的合成 canary。Agent 外层拒绝其他项目，但允许相同 canary；未读取真实凭据。角色隔离结论为 FAIL，见[进程记录](../evidence/workflow/studio-acceptance-runtime-20261012.json) |
| Godot 实际文件/网络边界 | Godot 4.6.3 编译探针通过；拒绝读取其他项目和认证 canary、写封存源、缓存 symlink 逃逸、连接真实监听的 IPv4/IPv6 loopback，允许声明的缓存写入；源与其他项目保持不变。此结果只证明该探针范围，见[引擎边界记录](../evidence/workflow/studio-acceptance-godot-boundary-20261012.json)及[脚本](../tools/studio_acceptance_godot_boundary.py) |
| ProjectRunner 实际验证与预览 | 实际 worker 能导入依赖并完成报告，不再卡在 EOF；验证结构/规格/源绑定通过，Godot fresh import 和源不可变检查 FAIL。实际 GUI Godot 能启动并达到本地时限、进程组确认停止，但缓存/系统证书初始化仍有错误，不宣称游戏体验或完整主循环验收通过。见[进程记录](../evidence/workflow/studio-acceptance-runtime-20261012.json)及[脚本](../tools/studio_acceptance_runtime.py) |

真实进程检查只使用一次性副本。协议批准、原生终态与 HTTP ACK 在 runtime 脚本中来自明确的测试 fixture；Godot、native command/exec、文件权限拒绝和停止事实来自实际进程。没有启动真实策划/制作模型回合，没有启用角色能力，没有接受生产候选。旧四进程独立启停证据继续见[服务冒烟](../evidence/workflow/studio-v1-services-20261012.json)。

## 24 项验收矩阵

“实测通过”限定为相应实际通信、浏览器或进程事实；“回归通过”限定为 fixture/DOM 的业务规则；“部分/阻断”没有达到该行要求的完整真实链路。

| 编号 | 方案场景 | 结果与边界 |
| --- | --- | --- |
| 01 | 新项目未提交概念 | 实测通过：空讨论页，A/B 无方案、作业和草稿串扰 |
| 02 | READY 继续讨论/另一窗口修订 | 回归通过：新修订、旧确认拒绝、完整审阅载荷保留；真实策划链路阻断 |
| 03 | 未加入反馈文字/三条反馈决定 | 回归通过：未提交文字显式处理、逐条覆盖与理由/关联；真实策划阻断 |
| 04 | POST 回执丢失/同 ID 重放/内容冲突 | 回归通过：原回执与单业务效果、异内容冲突；重启原回执实际恢复通过 |
| 05 | 后端重启/旧写 token | 实测通过：实例变化、旧 token 403、原 store/receipt 保留；草稿/命令恢复由前端回归覆盖 |
| 06 | 同项目新发布/慢 GET/草稿重关联 | 回归通过：串行读取、精确基线刷新、人工重关联；实际多窗口发布闭环阻断 |
| 07 | 非法成功 JSON/身份/额外 config | 回归通过：严格拒绝，不更新成功或执行权限 |
| 08 | 模型/effort/图片模态/目录变化 | 回归通过；实际 native catalog 已观测，真实 turn 接受配置/图片覆盖阻断 |
| 09 | 设置/草稿/刷新/心跳/目录零回合 | 实测及回归通过：浏览器保存偏好后无 proposal/job/attempt；native 目录和 command 探针零模型回合，执行 profile 冻结由回归证明 |
| 10 | 默认 effort 与 turn 实际请求值 | 回归通过：请求/回执/报告分层、缺报告为未知；真实 turn 未执行 |
| 11 | 快照读取到订阅之间有事件 | 实测通过：从 throughSequence 补发空窗更新 |
| 12 | 断流/重复/缺口/过期游标/项目迟到 | HTTP 断流续传、重复 cursor、future cursor、跨项目隔离实测通过；浏览器迟到/重同步由 DOM 覆盖，全部真实故障组合未覆盖 |
| 13 | 领取/原生启动响应丢失或崩溃 | 回归通过：单次启动意图和原身份核账；真实模型启动崩溃链路阻断 |
| 14 | 后端重启/lease 过期/Runner 仍运行 | 回归通过：UNKNOWN/占用保留、禁止重投；真实四进程 idle 断连存活通过，持续模型执行阻断 |
| 15 | 终态 ACK 丢失后 lease 改变 | 回归通过：原 reportId/ACK，不重复验证/候选 |
| 16 | 取消完成竞争/停止未知 | 回归通过：事务顺序、保留未知占用与已接受快照；真实 Godot 本地时限停止通过，真实模型竞争阻断 |
| 17 | GM 消费后崩溃/伪造确认 | 回归通过：同持久决定恢复、无二次消费、精确确认与源锁拒绝；确认记录实际物化已修复 |
| 18 | Agent/工具/游戏跨项目与批准通道 | 未通过整体角色隔离：实际 Godot 文件、symlink、IPv4/IPv6 拒绝通过；native readOnly 允许执行工程脚本和读取认证范围 canary，Agent 两角色 FAIL |
| 19 | 重复/迟到/缺失/重置用量/子线程缺口 | 回归通过；完整 native/外部工具用量覆盖未证明，不报零或估计完整计费 |
| 20 | 后端离线达到时限/软预算 | 实际小 worker 的离线时限停止及回归通过；实际 GUI 本地停止通过；真实模型软预算/断网停止延迟未验，不宣称硬截止 |
| 21 | 制作未停止/验证源漂移/导入改源 | 拒绝规则回归通过；真实导入新增 `.gd.uid` 被检测并 FAIL，无可接受候选。正向精确验证未通过 |
| 22 | 试玩时开始另一轮/拒绝候选 | 独立副本/拒绝保持原基线回归通过；浏览器排队预览停止和 actual GUI stop 通过；真实并行制作与试玩闭环阻断 |
| 23 | 接受候选但 needs_followup | 回归通过：精确 Snapshot、该条继续保留、其余不默认解决；未执行用户生产接受 |
| 24 | 物化失败/旧备份/协议不兼容 | 引用保留/重试/兼容只读回归通过；备份新空间与旧 journal 隔离实测通过 |

## 本次修复

- Runner 改用非阻塞分块逐行读取，正确结束 EOF，半行输出也能继续时限、心跳和取消监督。
- 活动目录不再把自己的 scripts/cache 子目录误列为受保护兄弟；Python 仅增加必要包读取和父目录枚举，其他工程仍受拒绝规则约束。
- ProjectRunner 从后端输入物化精确 GM 记录，把验证临时副本移出源目录；使用受控 Git 配置和安装的 Git runtime，持久化进程身份与原子验证证据。
- 验证增加本地时限、输出异常清理与有界等待；预览首轮报告发送失败仍保留 outbox 并继续本地监督。
- 预览使用私有 log，允许必要随机设备和指定图形用户客户端；拒绝 `.godot` 缓存 symlink。Agent 的 project.godot 精确写根也拒绝 symlink。
- Agent 输出错误/取消/时限分别处理外层与已观测 native 进程组；未确认停止时保留临时目录、报告未知并禁止封存。
- 后端预览动作投影要求在线且拥有 preview-isolated-v1 的 ProjectRunner；新版前端同时服从 allowedActions，保留旧工作流兼容。

最初实际失败保存在[修复前进程证据](../evidence/workflow/studio-acceptance-runtime-before-20261012.json)，没有用修复后的结果覆盖失败历史。用户原有项目、批准、源差异门禁与未提交修改均保留；未提交 Git commit，未运行独立 SHA/MD5 或旧 checksum helpers。

## 阻断项与下一步

1. **Agent 认证/工具分权与策划执行约束。** 必须把原生模型认证留在受信适配器，同时让工具子进程不能读认证、后台数据或运行工程；当前 native readOnly/workspace-write 配置和共享父沙箱不具备该证明。不得通过声明 capability 或提示词绕过。
2. **Godot 完整独立验证。** 实际导入尝试访问 macOS 用户编辑器临时/帮助缓存和系统证书初始化，严格策略拒绝；同时新增 scripts/main.gd.uid、scripts/player.gd.uid、studio/runtime.gd.uid 导致精确源漂移。需要建立受控编辑器 runtime/cache，以及封存前明确的 UID 来源策略，再重验原版源、主场景和 GUI。
3. **真实制作闭环。** 上述角色通过后，方可在一次性工程中验证真实 frozen profile/turn、离线软预算/时限、封存→独立技术 PASS→试玩→用户决定。当前这些项目没有实际通过证据。

四项能力仍为 NOT_VERIFIED，整体上线结论保持未通过。基础文件/网络探针通过不能自动提升为全角色 PASS，技术导入也不替代用户的玩法与视觉验收。

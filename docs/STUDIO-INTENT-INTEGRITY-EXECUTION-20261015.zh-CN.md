# Studio 意图完整性执行与评估记录

日期：2026-10-15（Asia/Shanghai）。本轮实现、定向验证、真实D2/D3补证和有界评估已完成，结果与限制逐项记录。依据[执行方案](STUDIO-INTENT-INTEGRITY-EXECUTION-PLAN.zh-CN.md)，本次没有执行用户验收或首次使用者体验，`userAcceptance=NOT_PERFORMED`。

## 范围与环境

完整目标及逐字基线保持原文。本次复用已有草稿、历史、命令、方案和结果链，只补意图保留、审阅和展示缺口；没有新增协议字段、制作状态机、提交账本或截图平台。未运行旧版构建、默认全套测试或独立 hash 检查。工作区原有大量修改，未清理、回滚或整体暂存。

执行使用 GPT-6 Luna max 子代理；计划和有界评估使用 GPT-6.1 Sol high 子代理。评估和浏览器复验发现并修复了四处具体投影问题：五项卡漏读已有任务/需求、返修候选值误标为已发布配置、“你的要求”混入策划讨论JSON，以及无候选失败时遗漏真实作业验证。

原生模型档位证据单列：[D2记录](../evidence/workflow/studio-intent-20261015/real-d2.json)中，策划配置与逐turn的`turn_context`均为Sol/high，原生`threadStartReported.reasoningEffort`却报告max；最终制作配置为Luna/max，`threadStartReported`报告ultra。[D3最终策划](../evidence/workflow/studio-intent-20261015/d3-final/planner-session.json)的请求证据为high，启动回报为ultra；制作亦为请求max、启动回报ultra。两轮`turnActual`均为null。因此只能分别报告请求配置及原生回报，不能宣称已独立确认实际turn档位；详细执行状态以对应session证据为准。

- 浏览器经 kimi-webbridge 操作真实 Chrome，组名为“Studio 意图完整性复验”。[原始动作与观察](../evidence/workflow/studio-intent-20261015/browser-actions.jsonl)保留失败、修复和复验过程。
- 主要浏览器验证使用独立 store `/private/tmp/studio-intent-20261015`，端口8844/8845；Casino 为真实历史制作的已接受测试版本3、2个场景，基线 Git `ef0630fee73f5b79c9830ef842ddfd5a40ff2f78`。持久文档34个对象；工作台投影另加两个有源码依据的成长状态目标，因此API/浏览器显示36个可寻址对象，15项字段能力。
- 正式入口为8794/8795。只在确认所有正式作业均为终态后刷新前后端；原候选、任务决定和发布版本未改变，未复制隔离发布。[刷新记录](../evidence/workflow/studio-intent-20261015/service-refresh.json)。后续B11失败投影修复只再加载后端，前后状态仍一致，[B11刷新记录](../evidence/workflow/studio-intent-20261015/b11-service-refresh.json)。
- D2/D3原生执行使用独立库`/private/tmp/studio-casino-d2d3-20261015`、前端55654/后端55655。全部planner/producer及独立验证停止后重载后端以加载B11修复；新PID87028，版本4、D3待审及无活跃作业/规划状态保持，[隔离重载记录](../evidence/workflow/studio-intent-20261015/b11-d3-service-reload.json)。
- [真实HTTP用例](../evidence/workflow/studio-intent-20261015/http-request.json)经过StudioApp、独立前端代理和真实后端收单；该用例抑制原生策划，只证明传输与留存一致。

## A 类修复与证据

| 项 | 实现与实际验证 | 状态 |
| --- | --- | --- |
| A1 | 静态白名单补全语义模块/CSS与boot；三种入口及深链可初始化，旧版入口实际可用；真实浏览器拦截一个依赖后显示错误与重新加载，解除拦截恢复。首次HTTP依赖404反例已保留。 | 已修复并复验 |
| A2 | 待加入文字与分类按输入时目标保存，未知归属旧文字保留待关联。浏览器“玩家太慢”切敌人为空、切回恢复，加入后刷新仍为player及同一feedbackId；HTTP用例核对稳定目标与原文。 | 已修复并复验 |
| A3 | 意见缓冲即时进入既有受保护草稿；未完成的内容变化禁发，只打开编辑器可发送；完成编辑更新预览，确认接入既有提交副本。浏览器已见禁用状态与原ID更新；focused QA覆盖未完成编辑拦截及最新内容冻结，HTTP核对冻结请求及后来输入保留。 | 已修复并复验 |
| A4 | 决定带对象、字段值、原文/身份、范围与Git基线副本；旧或无依据决定保留并失效，出站过滤。浏览器选择“两项都执行”后纯导航仍有效，280→290后标失效；focused QA分别单独改变原文、scope、发布版本、sourceCommit，另覆盖缺decisionContext旧决定；实际HTTP保留普通意见并过滤失效决定。 | 已修复并复验 |
| A5 | 整份草稿深复制；分类意见添加、编辑、删除进入历史事务。浏览器添加→撤销→重做恢复原feedbackId；focused QA用真实readVisibleDraft验证编辑/移除历史及嵌套快照不串改。 | 已修复并复验 |
| A6 | 澄清与READY补充沿用DraftStore，按proposal/revision/question隔离；旧修订文字可查看。真实浏览器CDP中文composition/input/compositionend、刷新、重载、离开返回均保留澄清原文；独立READY fixture的中文补充同样通过刷新、重载和离开返回，未勾选审阅、未启动制作。修订隔离由模块用例覆盖。 | 已修复并复验 |
| A7 | 成功图片立即显示并逐项保存，失败不掩盖前项；迟到响应校验项目上下文。真实两文件上传中PNG成功、TXT被拒，显示部分成功且成功assetId在草稿中；切项目附件不串入。 | 已修复并复验 |
| A8 | workspace_summary复用已有_view_state投影workflowState，列表不再只靠版本号。后端覆盖初始/制作/候选/返修/接受；正式浏览器版本0显示“候选已拒绝·可继续返修”，隔离列表显示已接受/初始/需补充。 | 已修复并复验 |
| A9 | 无project地址回项目管理；路由按项目/目标/观察面/场景恢复，非法目标显式提示并保留草稿。浏览器验证首页、深链、非法目标、Back/Forward及刷新；迟到响应回归保留。额外修正无效场景误报对象缺失的归因，scene=arena反例现准确提示场景不存在，草稿仍保留。 | 已修复并复验 |

## B / C 类交付

| 项 | 交付与验证口径 |
| --- | --- |
| B1 | “希望怎样修改”为主入口，另一条分类意见折叠；均进入统一清单。 |
| B2 | 自动保存与“创建/更新恢复点”“恢复到恢复点”分开，显示时间和范围，恢复沿用可撤销事务。 |
| B3 | 字段卡并列当前值、期望、尚未制作和来源；返修明确候选配置及已接受基线，不冒充已生效。 |
| B4 | 保留实例原文范围和保留条件；现有字段/操作范围及已知使用关系可核对。没有独立控件不宣称已支持局部配置。实际兑现由D2检查。 |
| B5 | 保留fixed对移动/删除的校验；说明工作台编辑与游戏运行运动的边界，没有放宽约束。 |
| B6 | 互补参数与原文可“两项都执行”，矛盾交既有决定/澄清；未加入自然语言推断引擎。 |
| B7 | 复用已有语义/参数/首帧来源说明，结果区明确文档匹配和自动化技术验证的限度。 |
| B8 | 候选动作改为“接受为当前版本”“继续修改此候选”，保留原accept/reject与返修语义。 |
| B9 | 新增表单自动带入当前实例/定义的共享定义及当前场景，其他选项折叠。浏览器实际为player/arena-scene、默认free；取消未加入操作。P4 QA覆盖预填及折叠。 |
| B10 | 主要意见和分类意见同等支持编辑/移除/定位，按稳定ID回写与发出。 |
| B11 | 结果逐项保留原文、决定、配置/源码、技术状态与未完原因，增加继续调整及候选试玩入口；无候选时读取真实作业验证并说明失败，已有候选优先读取其验证，不把全局验证当作逐项达成；无运行情境证据仍待试玩。 |
| B12 | 单一“项目级·项目意见与概览”入口；系统对象身份保留，未强行合并不同语义。 |
| C1 | 当前页面按分组身份记展开状态；真实浏览器折叠系统组、搜索后清空仍保持折叠。 |
| C2 | 每次重绘重算搜索计数；浏览器player搜索3/36，清空恢复36/36。 |
| C3 | 示例按真实映射命名，历史来源折叠；装饰布局明确不保证通路。 |
| C4 | 正文/控件以14–16px为起点；已实际查看桌面与390px截图，页面宽度均等于视口，窄屏仍分导航/预览/详情。最后实例详情复验为正文14px、意见16px、页面390px无横向溢出；设备模拟已恢复。 |
| C5 | 项目主标题保留，重复项目侧卡隐藏；状态优先显示动作，当前目标优先显示名称并将ID/复制入口折叠。浏览器核对实例名、动作状态及单一项目主标题。 |
| C6 | 名称与所有同类/运行时词义优先；对象ID、协议关联、路径按需展开，精确ID搜索保留。浏览器核对“场景中的实例”“起始入口”等关系名，驱动源码路径收入既有来源折叠区。 |
| C7 | 沿用首次覆盖备份策略；当前C/首次A及导出C/A定向用例通过，提示显示首次备份仍保留和时间。 |

P3五项卡直接读取现有summary、tasks、requirements、objectChanges和feedbackDecisions；区分用户请求目标、方案对象差异与关联检查对象。“你的要求”优先用户初始原文，只加入role=user的后续文字与回答，并去重初始原文；策划讨论不当作用户要求。真实field/language形状用例及独立READY浏览器复验覆盖这些边界。未要求新的模型回合。

## 定向验证与独立评估

已完成的定向执行均核对实际PASS输出，无jsdom缺失造成的SKIP冒充通过：

- `backend.tests.test_studio_services`：6个用例通过，覆盖入口递归依赖、legacy静态范围及阶段投影。
- `backend.tests.test_workbench_results`：真实D2失败暴露无候选时验证投影遗漏，修复后4个用例通过；包含field/feedback/operation失败信息、候选优先级、原要求保留和用户未验收。
- `studio-intent-input-qa.cjs`：真实草稿方法的目标输入、旧文字保留、修订级输入、附件迟到响应及五项卡真实形状。
- `studio-intent-a3-a5-focused-qa.cjs`：A3未完成编辑与冻结、A4各依据独立变更及旧决定失效、A5真实反馈历史和深复制。Sol只读核对了原文失效反例的独立性。
- `studio-intent-http-qa.cjs`：审阅载荷与真实HTTP留存一致、稳定意见身份、失效决定过滤及回执不清后来内容。
- `studio-workbench-p4`、`studio-restore-history`、`studio-route-hydration`、`studio-saved-checkpoint-overwrite`：由Sol评估代理各执行一次，全部通过。
- `studio-n2-cross-tab-draft`、`studio-e9-warm-rebase-concurrency`、`studio-result-context`及boot语法：主代理各执行一次，[原始结果](../evidence/workflow/studio-intent-20261015/root-regression.json)。

有界评估没有重开全仓库审计。已指出的事实错误修复后由Sol只读复核；其余结论仅限被实际检查的路径。最终HTTP回归已刷新同一证据文件并实际输出PASS。原始浏览器日志中的临时选择器错误、空白裁切截图、加载未完成的快照和修复前截图不算产品PASS。正式场景身份为arena-scene；错误scene=arena用作无效场景提示归因的修复反例，不算正常深链失败。

Sol亦只读复核了B11无候选失败投影：候选验证优先、作业验证回退及失败原因均准确，没有改写逐项达成或用户认可；无新增发现，未重复运行测试。

[Sol最终有限技术评估](../evidence/workflow/studio-intent-20261015/final-bounded-evaluation.json)结论为`PASS_WITH_EXPLICIT_EVIDENCE_BOUNDARIES`：最终D2和D3证据支持相应源码、导入、主场景冒烟、场景实例属性及直接模拟断言；未见本范围内新增阻塞。评估复用已完成的D2源码复核，只读对照实际归档，没有新增测试、生产或业务代码改动。没有把源几何核对当作视觉验收，也不外推到完整第三轮、实际命中伤害、实时控制或碰撞行为。

READY浏览器使用8848/8849及`/private/tmp/ptah-studio-intent-ready-20261015`，项目明确命名“READY输入验证夹具（非Agent制作）”。该fixture仅证明输入和方案展示；可见启动能力闸门保持原样，不计真实策划或制作。修正后的五项卡见[截图09](../evidence/workflow/studio-intent-20261015/09-ready-five-part-corrected.png)，实例预填见[截图11](../evidence/workflow/studio-intent-20261015/11-instance-form-full.png)，最终390px详情见[截图12](../evidence/workflow/studio-intent-20261015/12-final-narrow-instance.png)；截图已实际查看。

## D 类真实链与边界

| 项 | 当前证据及限制 |
| --- | --- |
| D1 三类历史链 | [field](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-field.json)、[language](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-language.json)、[mixed](../evidence/workflow/studio-legacy-replication-20261014/real-iteration-mixed.json)保留历史真实Agent及独立Godot证据；本轮制作合同及原生Agent消费路径未改，复用其制作事实。新HTTP证据单列，不改写历史为本版新测。 |
| D2 实例范围/奖励保留 | 首轮冒烟失败及漏做burst增强的恢复候选均保留，后者已测试拒绝。最终候选c3d905e…补齐burst绘制，独立Godot针对性断言通过：预警2秒、六枚各5/总值30、存续6秒、0.4秒冲击后开放安全奖励；竞技场显示子节点1.1倍，同定义对照保持默认缩放。仅在隔离库技术接受为版本4；共享渲染的对照专用条件偏差见下文。 |
| D3 同上下文再调整 | 从隔离版本4正常经过原生策划、制作和独立验证生成2b297a2…待审候选；实际Godot断言通过2.5秒预警、3.3秒第二落点及D2保留行为。首个PRODUCER_NO_EDIT失败单列；最终采用现有纯字段通路，没有额外游戏脚本改动，未接受D3候选。 |
| D4 对象/场景规模 | 主要浏览器Casino36对象/2场景和已有通用fixture用于浏览与编辑。真实原生副本新增对照后为38对象/3场景；浏览器实际点击对照实例后，URL/场景/固定576,384及当时返修源a32ad47…一致。最终版本4仍显示38对象，待审D3与当前来源区分明确。不增加任意200目标/3场景门槛，不外推容量。 |
| D5 首次使用者 | `NOT_PERFORMED`。代理代操作不证明首次使用者能独立完成五项任务，也不替用户判断体验或接受候选。 |

本轮实现、对应技术验证及有限评估完成。[操作指南](STUDIO-LEGACY-WORKBENCH-USER-GUIDE.zh-CN.md)和原89项/14条件的受影响状态已同步；既有未重新执行的证据保留原范围，D5及用户验收仍未执行。

首轮D2的`job-fd820be77396483ab1156b47b20ac4ce`已停止。Godot4.6.3实际报告`character_visual.gd:12`的`appearance_control`无法从`:=`推断类型；源码范围、绑定、冻结文档和导入检查通过，主场景运行检查失败，后端正确阻止生成候选。[首轮原始packet/session/verification](../evidence/workflow/studio-intent-20261015/d2-first-attempt-failed/)保留该失败，修复不会覆盖历史。实际失败页还暴露了无候选时逐项技术结果遗漏作业验证的投影缺口；最小修复通过上述4项定向用例并重载后，真实浏览器中对应六项全部显示技术FAIL、用户NOT_PERFORMED和没有形成候选的原因，原文与计划决定仍在。

恢复作业`job-a27790d9faee4d18bbf3e204d5dd2e9e`生成`candidate-8cb4b565ced44120b286d9faf2a3ac71`，Git `a32ad47cd9f3f97c3af3ddc1877837b1f2e6f5dc`。其独立技术检查PASS，但主代理及执行者核对实际diff发现`arena_visual.gd`没有变化，奖励显示意图未兑现：恢复方案错误假定首轮未发布改动已在基线。该候选已通过旧项目支持的decision接口作测试拒绝，发布仍为3；[完整失败范围与差异证据](../evidence/workflow/studio-intent-20261015/d2-retry-incomplete-candidate/)保留，不把技术PASS改称D2通过。后续正常返修绑定系统返回的a32ad47…源、`operations=[]`，保留已存在的局部缩放及对照，只补实际burst绘制；Sol已给出该准确基线分支的规划纠偏。

最终D2为`job-420f11057dee43e7b9b64f99e8cff834`、`candidate-767f9a25dac54e53bbb55da11045b8f5`，Git `c3d905e9bdf54c6e53dfd86047f72e3b32226f70`。[最终方案、原生session、候选、验证及累计源码差异](../evidence/workflow/studio-intent-20261015/d2-final/)已归档。最后补做相对a32ad47…只改`arena_visual.gd`的`chip.burst`分支：菱形外延11→15，增加深色外缘和浅金内缘，普通掉落分支不变。[针对性断言](../evidence/workflow/studio-intent-20261015/d2-focused-assertions.json)在候选的临时副本运行，实际计数六枚、逐枚值5，并检查寿命、预警/冲击/安全奖励及清理；这比仅核对`reward-value=30`的文档总值更具体。临时验证脚本的变量声明及`quit(0)`后返回两处错误已修正后通过，没有改候选。

累计D2源码由Sol作有限复核：竞技场仅`CharacterVisual`局部缩放为基线1.1倍，未叠乘；玩家根节点、`scenes/player.tscn`、`scripts/simulation/player.gd`及普通实例行为保持。独立对照使用相同玩家定义、默认显示缩放，固定位置576,384，不接入主流程。但共享`scripts/rendering/character_visual.gd`增加了仅匹配`player-appearance-control`的绘制条件，并保留显式`bool`解析修复。因此原冻结方案“不得修改共享渲染脚本”没有逐字满足，后续修复方案明确保留了这个条件；不能声称共享脚本完全未改。该缩放是局部范围技术验证设计，不代表用户已认可美术效果。

Sol对针对性证据的复核确认Godot实际退出码0且覆盖与断言一致，同时限定结论：两场景是在`PackedScene.instantiate()`后检查属性，没有加入场景树作画面比较；burst半径与边缘是源码证据。第二落点以源码规则及`throw_dice(delay=0.8)`实际调用验证，没有运行完整第三轮。主场景独立冒烟另有记录；上述断言不替代画面质量、手感或首次使用者体验。

D3首个实际作业`job-c570c710ad6f48b29749fe0f36e65e46`没有生成候选，报`PRODUCER_NO_EDIT`，[首轮原始会话、冻结包及无候选结果](../evidence/workflow/studio-intent-20261015/d3-final/attempt-1-text-bearing-request/)已保留；该次未进入Godot验证。原因是本次技术测试请求额外提供非空说明文字，策划还改写了description/preview/requirements，故不符合既有纯字段通路的条件。冻结文档已含2.5秒，制作方确认现有源码读取配置，未作无意义源码修改，因此正常触发非纯字段作业的无改动拒绝。这是测试提交方式纠正，不是产品补丁：新请求采用`text=""`和唯一结构化字段，并在冻结前核对`apply_field_changes(currentDocument, request) == document`；仍经过正常原生策划、制作和独立验证。

最终D3为`proposal-667963f3668447899ce156887b16e9a2`、`job-f39ed6bbea2c4f89bdfe672e256eb06e`、`candidate-ada009b1bbc84279913bd1a90f8fb215`，Git `2b297a2a8c0db9481165a627bb60e34c4541874c`。[D3记录](../evidence/workflow/studio-intent-20261015/real-d3.json)和[完整归档](../evidence/workflow/studio-intent-20261015/d3-final/)保留精确字段核对、原生规划/制作会话、候选及独立验证。`dataOnlyUpdate=true`、`implementationFiles=[]`；实际差异为`design/game.json`及后端生成的四份方案文档，没有为制造差异而改脚本。独立验证PASS后，[针对性Godot断言](../evidence/workflow/studio-intent-20261015/d3-final/d3-focused-assertions.json)从封存候选的临时副本读取实际2.5秒，并验证0.4秒冲击、额外0.8秒、奖励六枚各5/总30/寿命6、到期清理、局部缩放与对照属性及D2绘制源码保持。场景渲染/完整第三轮的证据限制同D2。

精确字段相等是相对D3的`currentDocument`：规划输入已有自动`sourceCommit`元数据刷新。相对旧D2候选的整份JSON还包含这些版本来源变化，不能将跨候选文档称为逐字仅一处差异；游戏源码没有随D3改变。

D2仅在`testData=true`、`productionAuthorized=false`的独立库作技术接受，以建立D3版本4基线；D3保留`READY_FOR_REVIEW`，发布版本仍为4，未代用户接受。原生测试的GM生产确认仍为`BLOCKED`，没有改闸门或增加批准记录。[D2记录](../evidence/workflow/studio-intent-20261015/real-d2.json)以`d2RetryCompletion`及`d2-final/`为最终态；旧`currentProposal`、`producerRetry`等块是历史时点快照。

最后一次[实际浏览器观察](../evidence/workflow/studio-intent-20261015/native-browser.json)对应原始动作日志224、226、229行：D3最终结果显示配置前2、期望/候选2.5、技术PASS、用户NOT_PERFORMED及尚未决定；首个D3无改动作业的两项仍是技术NOT_PERFORMED并说明无候选。点击“查看候选与试玩入口”定位到Git2b297a2…，Godot运行按钮可用；没有在浏览器调用运行或候选决定。随后点击“回到原对象继续调整”，URL、详情及字段归属均回到`dice-burst`，编辑器显示已接受基线值2，待审候选值仍为2.5。该目标作用于全局运行时，保留当前有效对照场景画布上下文；页面1512px无横向溢出。

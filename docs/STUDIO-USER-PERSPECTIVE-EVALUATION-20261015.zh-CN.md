# Studio 用户视角评估报告

主代理先列出[125项交互清单](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-CHECKLIST-20261015.zh-CN.md)，随后由唯一的 GPT-6.1 Sol high 子代理进行用户模拟走查。本报告由主代理核对证据、整理；没有追加产品修复。完整逐项状态见[可读覆盖表](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-COVERAGE-20261015.zh-CN.md)。

2026-10-15。本轮由一个子代理模拟“有游戏想法、不会读源码的首次使用者”。结论是：能从游戏语义找到玩家和骰子，独立形成参数、自然语言条件、局部实例意见和统一申报草稿；恢复点也能实际恢复并撤销。还不能据本轮证明“提出意见 → 新的真实规划 → 制作 → 核对逐项结果”的闭环。申报被已有待审候选拦截，新项目则被隔离环境的 Runner 能力门禁拦截。

这不是人类首次用户研究、正式用户验收或产品修复。本轮没有新制作、没有接受/拒绝候选、没有修改产品代码，也没有独立 hash/SHA/MD5 检查。全部浏览器操作在独立来源 `55754`，测试数据变更只在隔离副本及此来源的本地草稿。边界核对见 [review-boundary.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/review-boundary.json)。

**五个用户任务的实际结果**

| 用户任务 | 能否独立完成 | 实际证据与界限 |
| --- | --- | --- |
| 改一个参数 | 能独立形成和审阅草稿；不能声称制作成功 | 玩家速度260→275、骰子预警2→3秒实际修改；骰子预览刷新。统一申报列出前后值与未制作状态。字段旁缺少可见单位、范围和并列基线值，需要打开申报才核对清楚。A014–A023、A044–A049。 |
| 增加条件 | 能用原文保存并进入预览；未证明 Agent 收到 | 添加“安全奖励开放后才提示返回拾取”，同时保留六枚×5、总值30、6秒等条件；原文与互补决定分别展示。实际发送因待审候选被拒绝。A147、A152–A159。 |
| 限制局部范围 | 能记录清楚；仍需谨慎核对范围 | 选竞技场玩家实例，写“共享定义、对照实例、位置、锁定和玩法参数不变”，预览保持逐字原文和实例身份。详情的“作用范围：运行时生成”不能直观说明“只改此实例”，且没有独立控件；未验证实际实现会遵守。A034–A036、A150–A152。 |
| 恢复误操作 | 恢复点路径可独立完成 | 创建恢复点，取消覆盖，再确认覆盖后保留首次备份；恢复到旧点后临时意见消失，撤销后原文返回。实际下载JSON含当前稿、恢复点、首次备份。重置草稿立即清空，未见确认；完整reset撤销链未核对，不算通过。A070–A090、A132–A142。 |
| 理解没有完全满足的结果 | 能读到事实，但信息负担明显 | 旧结果区分“FAIL / NOT_PERFORMED / 已拒绝 / 等待审阅”，明确技术通过不等于体验认可，并提供回对象和试玩入口。完整历史与技术信息默认堆叠；本轮提交失败原因还出现在模态背后，下一步难发现。只评价信息表达，不以旧PASS证明本轮完成。A005、A038、A044、A127、A159。 |

上述操作都在未先读指南的情况下进行。结束页面操作后才阅读 [docs/STUDIO-LEGACY-WORKBENCH-USER-GUIDE.zh-CN.md](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-LEGACY-WORKBENCH-USER-GUIDE.zh-CN.md)，用于说明现有边界；没有把指南所写但未操作的能力算通过。使用可访问性快照的语义名称定位控件，不能代表真实人类的视觉寻找时间。真实中文输入法、原生 Godot 试玩操作未模拟。

**五项明显摩擦与一项轻微建议（均未实施）**

**UR01 · P2 明显摩擦 · 提交失败原因位于申报模态背后。**

最短复现：打开有待审候选的 Casino → 写两目标意见和参数 → 预览统一申报 → 记录互补决定 → 点“交给当前 Agent 流程”。预期在当前模态说明“未发送，先处理待审候选”，给出可到达的下一步。实际模态仍显示“工作区内容发生变化，预览已更新。请检查后再提交”，背景全局错误才写“项目有正在执行、待审阅或状态未知的作业；请先处理该作业”。用户易重复点击或误以为正在提交。门槛本身合理，问题是反馈位置。A156–A162；截图 [06-submit-blocked-modal.png](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/screenshots/06-submit-blocked-modal.png) 已实际查看；A159保留模态与背景的同时DOM证据。需要帮助：需要退出当前模态找背景提示才能明确原因。建议优先处理。

**UR02 · P2 明显摩擦 · 多标签比较要求非代码用户读完整 JSON。**

最短复现：同一深链另开标签 → 第二标签修改场景意见 → 回首标签继续写 → 点“比较并选择”。预期先按对象显示真正不同的意见/字段。实际并排展示两份完整JSON，包括内部ID、decisionContext、所有未变字段，真正的一句差异淹没其中。双方内容确实保留，选择本标签后可继续，未发现覆盖丢失。A091–A103；截图 [03-multitab-json.png](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/screenshots/03-multitab-json.png) 已查看。需要帮助：可能需要懂JSON的人协助比较。建议其次处理。

**UR03 · P2 明显摩擦 · 参数输入处不直接解释单位、范围和原值。**

最短复现：选择玩家或骰子 → 查看“本目标意见”参数输入 → 改值。预期输入旁同时有单位、允许范围和已接受值/本轮期望。实际主要是字段名和一个数值；DOM虽有min/max/step，可见说明没有呈现这些信息；统一申报才列出260→275、2→3。用户能够改值，但需要跨区核对。A014–A023、A047–A049；截图 [02-dice-preview.png](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/screenshots/02-dice-preview.png) 已查看。需要帮助：预览/对象描述能补充一部分，无需读源码；直接修改仍需猜测。建议在提交反馈之后处理。

**UR04 · P2 明显摩擦 · 实例的“作用范围”词义不足以支撑局部修改判断。**

最短复现：选“赌场游侠 · 战斗场景实例” → 读详情。预期直接区分当前实例、共享定义及其他实例的影响。实际标题说场景实例、关系指向共享定义，但“作用范围”显示“运行时生成”；生命周期又说明场景加载创建、每局重置。这描述了出现方式，未直接回答修改影响谁。通过明确写保留条件可以补足意图，尚未证实会错误改到其他实例。A036、A150–A152。需要帮助：需要自己写出边界并核对申报。建议与范围说明一起处理。

**UR05 · P2 明显摩擦 · 迭代主要操作被默认展开的候选及技术历史挤远。**

最短复现：主页打开Casino → 进入迭代 → 找对象和意见。预期预览与修改保持主位，技术证据按需展开。实际对象区之前有完整候选映射和重复技术检查；中央对象预览下方还铺开多轮长原文、JSON配置和历史结果。读骰子触发条件还直接面对 `round_director.step_environment()` 等表达。用户能找到目标，但要跳过多屏信息。A005、A008、A012、A038、A044、A127；截图 [01-iteration-entry.png](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/screenshots/01-iteration-entry.png)、[02-dice-preview.png](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/screenshots/02-dice-preview.png) 已查看。需要帮助：本轮靠快照语义定位，不能据此宣称人类首用也容易找到。建议在核心反馈和范围问题之后处理。

**UR06 · P3 体验建议 · 多目标重置前的范围说明可以更明确。**

最短复现：草稿含多目标意见、字段和新场景 → 点“重置当前草稿”。实际直接清空，随后空申报显示目标0；恢复点仍保留。用户需要清楚知道它影响整个当前项目/版本草稿，以及之后如何撤销。A132–A142。本轮未核对完整reset撤销链，因此这是一项轻微体验建议，不是已确认的数据丢失或可靠性缺陷；也不把新增确认弹窗作为必需修复。后续可优先考虑范围摘要和清楚的撤销提示。本轮未实施。

**环境、数据与工具限制**

- 新项目“小小避雨者”创建成功，中文概念刷新后保留（A167–A177）。一次“重新连接”后，仍提示AgentRunner/模型目录、策划只读隔离、制作私有副本隔离未就绪，“梳理我的想法”disabled。是本轮隔离环境能力限制，不计产品bug。没有完成新的真实规划、五部分方案、澄清、制作或验收闭环。
- Casino没有本轮可移动装饰映射；原玩家固定。仅查看固定约束并取消新实例放置，未把缺数据当拖拽/批量通过，也未切夹具补造能力。真实图片、动画首帧、过渡/出口编辑未覆盖。
- Godot候选入口确实启动，页面显示当前Git候选已打开（A124、A127）。未观察原生游戏窗口和玩法；停止由主代理仅清理本轮隔离预览子进程完成（[preview-stop.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/preview-stop.json)），不计页面停止或原生关闭成功。没有网页停止按钮本身不作为缺陷。
- 分类意见曾直接通过CSS填写折叠区并点击加入（A018–A020），未先展开可见入口；这是操作方法限制，不将该路径计为真实用户独立完成。其他字段、主意见、场景和申报按实际可见操作记录。
- 两次调用陈旧ref未取得编辑效果，不计产品错误；合成Escape不能证明浏览器默认行为。补测启用焦点仿真后真实Escape可关闭模态（A117–A122），焦点陷阱、完整键盘导航和文本原生撤销仍只部分检查。
- 未注入损坏存储、断网或伪造状态；未完成候选接受/返修、基线重关联、未知收单结果对账。这些保留未覆盖。

**覆盖与证据**

125项全部保留在 [coverage.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/coverage.json)：**23项已检查未发现问题、8项发现问题、70项部分检查、23项未覆盖、1项当前项目不适用**。8个问题覆盖项关联上面的6个问题；不是8个独立bug。部分检查不等于通过，不能将101项有操作证据解释为101项完成。

[browser-actions.jsonl](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/browser-actions.jsonl)有A001–A177动作/快照，凭证字段过滤；所有7张截图已实际打开查看。[download-verification.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/download-verification.json)记录实际下载解析；[review-boundary.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/review-boundary.json)与[preview-stop.json](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/preview-stop.json)由主代理补充。本轮没有以历史技术PASS替代新的用户体验结果。

**证据索引与边界**

[原始子代理报告](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/user-review.md) · [完整可读覆盖表](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/docs/STUDIO-USER-PERSPECTIVE-COVERAGE-20261015.zh-CN.md) · [独立环境记录](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/environment.json) · [本轮边界核对](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-user-perspective-20261015/review-boundary.json)

主代理抽查了提交受阻、跨标签比较、参数编辑及窄屏等截图，并核对 A159 同时记录的模态文字与背景错误。所有125项ID均与事先清单对应，无遗漏或重复。产品目录的文件大小和修改时间未见变化，源测试库的作业决定与开始时相同；该边界核对没有使用 hash。

本轮只产出检查清单、评估报告、覆盖表和证据。真实人类首次使用研究、用户验收、新规划与制作闭环均未完成；本报告不关闭这些目标。

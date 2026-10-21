# 问题报告：Studio 真实双活页试用受浏览器控制链阻断

报告日期：2026-10-17（Asia/Shanghai）。以下事实来自2026-10-16已保存的实际回执；本次仅整理报告，没有重新操作浏览器或修改产品/环境。

## 问题与影响

同一Studio来源的两个活动页面需要分别选中，才能真实完成“形成不同草稿 → 比较 → 明确选择 → 恢复”的用户旅程。目前没有建立可稳定区分并控制A、B的公开工具路径，因此该必要旅程仍为 `NOT_PERFORMED`，严格循环结束条件保持 `allSatisfied=false`，第8轮未开始。

这是浏览器控制链的执行阻断。现有证据不足以判断Studio的实时双标签功能是否存在产品缺陷，也不足以确定AppleEvent超时的根因。“选页工具超时”只是概括，实际包含以下三个不同事实。

## 已确认事实

|入口|期望|实际回执与停止点|
|---|---|---|
|Kimi公共选页|在两个同来源应用页均存活时，分别返回已登记的A、B身份。|2026-10-16 15:06的最后一次有界准备中，A=2105163771、B=2105163772，两页均已加载；请求找回A时，按host匹配的`find_tab`仍返回B。步骤5立即停止，没有进行后续A→B→A或业务编辑。该API忽略path的匹配边界不支持用不同路径/query唯一选页。|
|CUA原生入口|提供可用于Chrome选页的原生应用/浏览器控制面。|2026-10-16 22:26只读清单仅有iab和mcpapps；apps为空，错误为`Native apps: Error: Sky Computer Use service startup request failed`。没有建立可用Chrome/native入口。|
|Chrome标准AppleScript|先以只读窗口/标签盘点建立唯一映射，再按公开active tab index选页，并由Kimi核对身份。|2026-10-16 22:34首次只读门槛返回`AppleEvent已超时。(-1712)`，exitCode=1、stdout为空。脚本内部超时5秒、外层上限6秒；立即停止，无选页指令、无B、无重试。|

AppleEvent超时不能据此判定为Automation权限拒绝；CUA服务启动失败也不能据此归因为Studio。没有取得足以进一步定位这些工具故障的证据。

## 最小复现与期望结果

既有Kimi现场：同session正常打开两个`http://127.0.0.1:55774/studio/`同来源项目页，分别记录A/B tabId；两页均加载后，用A的已记录URL执行公共`find_tab`，实际返回B。此为已保存的复现，不要求再次执行旧停车/激活方案。

所需能力是：通过公开工具稳定选择已登记的两个任务页，并实际核对A→B→A三个返回身份及两个应用持续存活。身份通过后仍须冻结新一轮，真实形成分歧、明确选择与恢复；工具准备本身不算用户旅程通过。不需要Studio新增HTTP、存储或审批流程。

## 数据与资源状态

- 第7轮主要单页旅程和390px可达操作已经完成，不能替代实时双活页。
- 14条意见、8项结构、64份保留版本已保全；旧全文与稳定身份保持。
- 独立下载分支实际取得草稿24，当前业务内容和首次备份全文补证成立；这与双页阻断分开记录。下载首次观察超过计划30秒的偏差已披露，不推导为新的产品缺陷或验收门槛。
- 本轮页3775和补证页3779已先保全后关闭，各自末次公开session清单为`tabs=[]`；没有清storage或关闭无关用户页。

## 继续条件

需要新的可执行公开选页条件，例如恢复可用的Chrome/native控制入口或工具提供稳定的标签身份选择。届时先由Sol high制定有界准备，确认真实A→B→A后再冻结完整试用。当前不重复已失败的host/停车/CDP激活/AppleScript参数，不要求用户反复找页，不以单页保留稿比较补算通过。

本报告为本地可转交的问题材料，未向外部平台提交。来源单位数据限制、两个P3、D5真人首次使用及完整125项目标的其他未覆盖边界继续保留。

## 原始证据

- [Kimi双页准备回执](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-trial-fix-cycle-20261016/round-07/preparation-fallback-result.json)
- [CUA只读清单](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-trial-fix-cycle-20261016/round-07/post-trial-control-inventory.json)
- [AppleEvent超时原回执](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-trial-fix-cycle-20261016/round-07/post-trial-preparation-native-gate.json)
- [独立Sol high有限复核](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-trial-fix-cycle-20261016/round-07/post-trial-preparation-verification.md)
- [第7轮交付与继续条件](/Users/typ/Desktop/godot_project/ptah-gm/local-codex-handoff-20261008-compact/evidence/workflow/studio-trial-fix-cycle-20261016/round-07/closeout.md)

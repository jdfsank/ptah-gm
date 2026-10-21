# 草稿立即重载丢失修复

日期：2026-10-13。本轮修复[上一轮 Kimi 验收](STUDIO-KIMI-UI-ACCEPTANCE-20261013.zh-CN.md)中“保存完成前立即重载可能丢失输入”的问题。**修复及复测通过。** 改动保留在本地，未提交。

原来概念草稿延迟 300 ms、迭代草稿延迟 250 ms 才写入 IndexedDB；重载的 pagehide 会取消计时器。仅在 pagehide 补异步写入也无法保证浏览器完成事务。

现在每次编辑都在输入事件返回前同步写入 localStorage，不等待计时器或离页回调。概念、迭代文字、字段值、对象选择、未添加/已添加反馈及类别均使用原有存储身份、项目、阶段、版本键。草稿只含文字/结构化值和附件引用，没有复制图片正文或改动后端命令。

已有具备完整作用域键的 IndexedDB 草稿仍能读取并迁移；缺存储身份的旧格式不认领。迟到的旧读取不能覆盖新编辑。提交/删除先保存空记录标记，避免旧草稿被迟到读取复活。浏览器存储不可用或容量不足时明确显示保存失败，不显示“已保存”。

## 验证

| 测试 | 结果 |
| --- | --- |
| Kimi：迭代文字、未添加反馈与类别，输入后同一 JavaScript 任务立即 reload | 完整恢复，无等待计时器或保存提示 |
| Kimi：添加反馈后同一任务立即 reload | 已添加反馈保留，输入框保持清空，既有反馈保留 |
| Kimi：连续三次输入后立即 reload | 恢复最后一次输入 |
| Kimi：概念页输入后同一任务立即 reload | 概念完整恢复 |
| Kimi：清空文字后立即 reload | 保持为空，不从旧 IndexedDB 恢复旧文字 |
| Kimi：跨项目往返 | 两项目草稿隔离，回原项目仍保留最后文字和反馈 |
| 扩展草稿回归 | 输入事件内保存、立即销毁/重新打开、字段恢复、旧读取/删除竞争、容量失败、存储/项目/版本隔离、显式重关联及异步过期保护通过 |
| 前端完整回归 | **18 个 QA 脚本全部通过，34.249 秒**；脚本数不等于断言数 |
| 后端只读核对 | 前后都是 7 个已回执模型回合、10 个 attempts、3 个 jobs，快照仍版本 1、源版本不变；本轮新增模型/作业为 0 |

本轮只改前端及使用说明，没有重跑后端全套或 Godot；上一轮后端 287/287 的证据保持原范围。本轮没有独立 hash 构建检查，没有操作正式用户工程。

[机器可读摘要](../evidence/workflow/studio-draft-immediate-save-20261013/summary.json)、[Kimi 动作](../evidence/workflow/studio-draft-immediate-save-20261013/browser-actions.jsonl)、[前端回归](../evidence/workflow/studio-draft-immediate-save-20261013/frontend-regression.json)、[结果截图](../evidence/workflow/studio-draft-immediate-save-20261013/immediate-save-result.png)保留实际证据。即时重载使用同一浏览器任务中的 DOM input/change/click 和 location.reload，避免独立工具调用的间隔掩盖原来的延迟窗口。

正常存储可用时，输入后立即重载的问题已消除。清除站点数据、存储被禁用/占满、系统崩溃或断电的恢复不作额外保证；草稿仍是本浏览器数据，不是后端备份或多人协作功能。

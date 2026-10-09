# v0.5：过渡节点与链条小幅验证

日期：2026-10-08。起点为 v4 `45c0569`，实施前 checkpoint `bd6c8a1`。

## 范围与自评

- 需求对齐：既有每条有向出口派生一个可寻址 Transition；三态 unset / none / preset，允许未设定；去程与回程独立；共享只读预设显示使用位置；搜索、面包屑、深链、返回、说明及冻结 Submit 统一使用 target resolver。
- 无重复终点：快照只保存 `sourceExitRef` 与 config。`targetEntryRef` 由现有 door target / targetSpawn 解析，改出口后随之更新。
- 没有扩建编辑器：不增加时间轴、素材生成、任意脚本或新平台。仅两个只读浏览器效果预设；maskResourceRef 为 null，不能执行真实遮罩。
- 来源诚信：出口引用有来源不代表遮罩机制已有来源。Transition 是派生目标，配置是新提案；草稿出口、未知 GM 映射与空资源保持 BLOCKED。
- 初始派生不是内容修改：baseline 与 draft 同样派生 unset，零净 diff。没有改变真实游戏包。

## 实际验证层级

### 已运行

1. 修改前独立执行旧 v4 全量 npm test：全部通过，包括 67 Python 测试；先确认原基线，不将新增功能测试误称为 test_error 修复。
2. 构建、JS 语法检查、全量既有 JS/DOM 与 Python 回归全部通过；最终 Python 78 项（新增 11 项）。
3. Transition DOM/model 11 项（另含继承属性预设 ID 与畸形配置负例）：零差异、三态撤销、方向、目标派生、迁移校验、共享使用位置、导航/搜索/深链/返回与效果预览无草稿修改。
4. 新产品组件/协议集成：加载实际 dist domain、React shell 和产品 browser-demo；真实 DOM 编辑单条 Transition 为 none；v1 拒绝；v2 冻结；Python schema 与服务端拥有的 adapter-baseline 净 diff 验证通过；确认后 browser-demo 保存完全相同 JSON，submission / task / target 标识保持关联。全程零网络与零模型调用。
5. 同集成的失败例：降级 v1、冒领 project target、伪造 before 值均拒绝。
6. Python计划和证据审计正反例使用受控临时文件及测试fixture验证规则。fixture 的许可仅属于测试，不是用户真实 GM 工程的审阅授权。

### 明确未运行

- 渲染浏览器的真实桌面/手机视觉检查；jsdom 不是渲染认证。
- 实际同线程 Codex 模型调用、GM角色委派、真人 TTY 规范确认。
- Godot 正式 check、GUI/play、遮罩帧序、相机就绪、输入锁定、中断/取消/超时与黑屏恢复。
- 从改后真实游戏源重新提取事实、审阅 mapping 并回读新前端语义。

## 链条合并到什么程度

现在可用正向路径是“真实产品组件 → 精确冻结 v2 → Python基线校验 → 浏览器模拟收据”。此收据诚实保留 delivery=NOT_DELIVERED、implementation=BLOCKED、verification=BLOCKED、runId=null、certified=false。

真实执行仍需要已有服务器审阅映射及规范确认。Bridge 仍以 toolOutput 传递计划，不是直接执行 GM skill；正式证据仍需操作员停 bridge 后 CLI import；source re-extraction 仍是人工审阅步骤。没有把模拟收据或合同测试升级为真实闭环。

## 残余风险与下一最小真人动作

1. 在本机原工程和同一 idle Codex 线程建立一个出口的 GM PLAN/spec 与逐项源路径映射；用原生真人 TTY 完成规格确认。
2. Evaluator 新功能测试先通过独立的测试编写与审阅步骤进入新基线，再进行运行实现提交。不得伪装 test_error，不通过本次接口放宽测试作者权限。
3. 首个真实功能选择一个 fade，保持当前 JSON/ECS 房间重建。正式实现必须证实 covered 前不换房、placements 与相机后 reveal、reveal 后解锁。遇到取消、超时、重复输入要明确清理；现游戏不具备完整旧房间回滚。
4. 正式 check、可见运行、目标断言、证据导入及源重提取全部完成后，才能标为已实现/已验证。

本轮不是“安全失败即完成”：交付有可编辑、可导航、可冻结并保存的正向产品路径，也有相应拒绝反例；真实引擎阶段被逐项保留为未运行。

## 独立审查

实现稳定基线 `46da5d5d50a94162ac7c4e3328d01e63791c698a` 经独立合同与UI审查。合同审查独立跑54项GM单测及Transition/跨语言集成，无P1/P2授权逃逸；同时发现SVG按钮漏响应Space。UI审查发现P2：从Transition新建场景或重置后残留旧targetOverride，可能使右侧编辑/说明仍指向旧出口。

修复：离开原目标的新建与重置在首次渲染前清除override；Space和Enter同样响应并阻止页面滚动。新增实际React scope、hash、Inspector同步断言。预览后纯导航仍保留冻结载荷，内容修改/Undo仍立即使旧确认失效。迁移另加原型继承名称和畸形config拒绝。最终修复提交与复验结果见源码包提交记录。

修复后的独立复验已完成：原P2路径通过，新建/重置的currentTarget、深链、Inspector及React说明scope一致；reset所有target事件均为大厅，无旧目标中间事件。Space激活及preventDefault通过。合同审查与UI审查均只读、独立于实施者；未留下阻塞发现。

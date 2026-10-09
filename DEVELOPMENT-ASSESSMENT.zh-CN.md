# 后续开发指令评估

评估日期：2026-10-09。对象为本次重组的 GM-DNA v6 交付包；附件中的历史批准、旧环境路径和开发指令均作为审计资料，不视为当前用户已授权实施。

结论：后续指令的总体方向和先后顺序合理，可以作为交接纲要；当前包尚不能原样进入真实构建提交链。首先需要解决构建期哈希检查与用户约束的冲突，明确实际目标工程和可恢复基线，再准备映射、规格及环境。真实 transition 属于后续新增运行时机制。

## 已经成立的部分

- 工作台作为薄适配层，继续以 PLAN/GAP、原 GM 角色和正式验证为权威，符合已有实现边界。
- 精确目标、逐文件范围、冻结提交、幂等 ID、不确定提交互斥和新草稿保护已有对应实现，值得保留。
- 先用一个已有参数修改证明真实执行链，再开发淡入淡出，能够分开定位桥接问题和玩法问题。
- 将模型回合完成、全局正式运行、逐目标验证和人工验收分别记录，符合当前代码实际能力。全局 PASS 不足以证明用户请求完成。
- 保留游戏中已部署的 `run_verify.py` 修复合理。其与框架副本的实质差异是 gdUnit 报告目录改为工程内临时目录和 `res://` 路径，不应被旧框架覆盖。

## 当前状态与前置缺口

| 项目 | 本次查到的事实 | 对后续实施的影响 |
|---|---|---|
| 实际工程与 checkpoint | 工作区、交接根、前端、游戏和框架均没有 `.git`；前端历史 bundle 已保留 | 先明确继续哪个实际工程，再建立可恢复快照/仓库；解压目录不等于恢复了游戏仓库历史 |
| Node / npm | Node 22.22.2、npm 10.9.7 | Node 满足现有 jsdom 锁文件 engines；前端依赖未安装，未跑回归 |
| Python / uv | Python 3.14.7、uv 0.12.15 | 达到文档声明的 Python 下限，但原测试插件与该版本的运行兼容性尚未验证 |
| Codex | CLI 0.162.0-alpha.2；本机生成的实验 schema 含 `toolOutput`、`TurnToolOutput.name/output`，CLI 支持 `--stdio` | 字段兼容已确认；尚未证明同工程线程绑定、真实技能执行或模型结果 |
| Godot | PATH 未找到 godot/godot4；配置中的 `/usr/local/bin/godot` 不存在；两个常见 Applications 目录未找到 Godot.app | 尚未定位本机可用引擎，不能宣称缺失安装，也不能进入已验证的干净导入/正式检查 |
| 导出配置 | Web 模板仍指向 `/workspace/shared/velvet-export-tools/...` | 后续需要导出时重新定位本机匹配模板；不是第一阶段工作台闭环的先决安装任务 |
| 目标映射 | 缺少 `.godotmaker/workbench-targets.json` | 精确真实目标提交无法 READY；映射需绑定当前 task/mechanic、diff 和逐文件范围 |
| 源适配基线 | 交付差异报告记载 `hud.gd`、`title_screen.gd` 两项与前端锁不同 | 先审差异及提取器影响，不直接刷新锁；本次未重算该报告中的 SHA |
| 规格确认与正式运行 | stage 只有历史角色时间戳，没有当前 tag/spec 的 local_interactive 确认证明；交付游戏没有当前 runs/verify_report | 不能把旧聊天批准或历史成功当本次确认和正式运行证据 |
| 结果回流 | 手工停 bridge 后导入已实现，逐项 verification 仍固定 BLOCKED | 结果语义关联是实际开发任务；不得提前把状态改成 PASS |

## 最优先需要修正的指令

### 1. 构建期禁哈希约束必须进入执行方案

用户规则为 `Strictly forbidden hash check at building.`。实际 bridge 的 `local_readiness()` 会先校验技能/工具 SHA，再生成受控文件 SHA inventory；投递前重新检查，正式结果导入也依赖 digest 校验。这是实际构建提交路径的依赖，不能靠跳过外层 `verify-package.py` 解决。

建议先定义并实现符合该规则的基线/漂移检查方案，例如已审不可变文件快照的直接字节比较，同时保留精确路径、角色、冻结载荷和运行身份检查。协议、测试与相关能力声明需要一起审阅；不能仅删除校验条件或伪报 freshness PASS。非构建阶段校验是否保留，可以在具体方案中清楚界定，不能把构建所依赖的检查改名来规避规则。

需要校准的细节：`frontend/tools/write-adapter-baseline.cjs` 本身只是生成或比较 JSON 基线，没有直接计算 SHA。强制哈希依赖主要在真实 bridge、提取器和正式证据链；不能把所有前端构建命令都描述为直接运行哈希检查。

证据：`frontend/bridge/gm_contract.py:33,260,269`；`frontend/bridge/server.py:78,98,114`；`frontend/tools/extract-velvet.py:14`。

### 2. 将“调用技能”改为可验收的执行要求

bridge 发出 `turn/start`，将工作流作为 `toolOutput` 提供给模型，本身没有直接执行 `gm-build`。文件存在、skills/list 成功和 toolOutput 字段兼容都不足以证明技能实际执行。

第一轮真实提交应记录具体技能加载/执行、角色分工、实际源改动及本次正式运行，不能仅凭模型声称完成。若实验 toolOutput 不能可靠触发预期工作流，应先修桥接投递契约，保留原线程权限。

证据：`frontend/bridge/server.py:45,75`；`frontend/bridge/gm_contract.py:422`。

### 3. 已完成的旧任务与新修改任务分开

当前 PLAN 的 R1、M01、M02、M03 均是 `completed`，没有 `verified` 状态。旧任务备注记录的是此前实施和验证，不能复用它们来宣称新参数修改已完成，也不能任意回退状态重跑 build。

一个已有参数修改仍需对应明确的新变更任务和验收意图，或者在真实缺陷时按合法反馈/GAP 路线处理。新增淡入淡出则需要新审规格和对应测试基线。若涉及标签变化，按该项目的 GDD/PLAN/ROADMAP 规则处理，不能借任意旧 mechanic 授权。

证据：`sources/velvet-eclipse/PLAN.md:190`；`docs/REMAINING-WORK.zh-CN.md:6,11,15`。

### 4. 区分现有换房与新增过渡效果

游戏已有 JSON/ECS 换房：设置 transition 模式、在安全 flush 重建房间并安排玩家 placement，placement 完成后回到 playing。它不是完全没有换房实现。

附件要求的独立常驻遮罩、covered/reveal 阶段、camera 就绪门控、去返独立配置、none/unset、取消/超时恢复没有对应运行时实现。角色动画在 playing 之外得到 0 delta，不能直接承担遮罩时钟。现有测试主要证明房间图和正常换房，没有证明这些新时序。mask_wipe 资源未绑定。

因此先实现一个方向的 black fade，按 covered → room rebuild → placement/camera ready → reveal → unlock 建立新契约；定义错误时如何退出遮罩和恢复输入。不要把该恢复能力描述为完整 rollback。再扩展逆向和 mask。

证据：`sources/velvet-eclipse/scripts/runtime/game_runtime.gd:132,173,349`；`sources/velvet-eclipse/scripts/systems/progression_system.gd:76`；`docs/MERGE-PLAN.zh-CN.md:29`。

### 5. 逐目标证据自动化要有明确输入和通过条件

当前导入已经校验部分运行身份、范围和报告关联，但代码明确保持逐目标 implementation/verification 为 BLOCKED。建议为每项记录 request/submission、target、task/mechanic、baseline、assertion/case、run/report 和人工决定之间的关系，并验证这些断言实际覆盖本次请求。

只有关系完整且相应当前断言通过，才允许该项目标 PASS；全局运行结果继续单独显示。首个真实闭环可以手工准备并审阅这组证据，自动发现运行和自动源回流随后实施。

证据：`frontend/bridge/gm_contract.py:581`；`docs/REMAINING-WORK.zh-CN.md:9`。

## 建议实施顺序

1. **环境和规则准备：** 明确真实目标工程，建立可恢复 checkpoint；定位 Godot；形成构建链无哈希校验的具体方案。保留现有三个源码目录，暂不移动或全面重写。
2. **一个目标的规格和映射：** 审现有源差异；建立最小真实 target mapping、新变更任务及必要测试基线；完成该阶段实际要求的规格人工门。
3. **一个已有参数的真实闭环：** 冻结确认后投递；记录实际 GM 角色执行、源变更、干净 Godot 导入、当前正式 check 与断言结果、按需人工验收。成功条件包含本次请求与运行证据的真实关联。
4. **证据和源回流工程化：** 自动关联逐目标证据；审提取器锚点和新基线；保护新草稿，显式处理冲突/孤儿说明。浏览器真实窄屏、焦点、IME 和拖拽验收可以在环境准备后独立开展。
5. **新增 transition：** 新审规格与 Evaluator 测试基线后，单方向 black fade → 逆向配置 → mask 资源及效果。保持失败恢复、玩家状态和解锁时序的独立验收。

候选影响范围主要为 `frontend/bridge/server.py`、`frontend/bridge/gm_contract.py`、提取/基线工具及相关测试，以及真实工程的映射/规格/正式运行工具。transition 再涉及 session、progression、runtime、常驻 UI 遮罩和房间配置。这些是规划候选，不是给整目录或所有列出文件授予写权限。

## 本次评估的边界

本次读取文档和代码，查看版本/路径，生成并检查本机 Codex 协议 schema。没有安装依赖、启动 bridge/app-server 服务、向线程投递、构建、测试、运行游戏或执行任何哈希校验。只新增这份评估文档，原交付指令和源码保留。

OpenAI 官方 app-server 页面获取失败（403；Python 获取另遇到本机证书链错误）。因此 Codex 接口结论限于本机 CLI schema 与 help，没有据此宣称真实链条通过。

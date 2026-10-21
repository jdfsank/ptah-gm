# 工作台用户交互：完整类图、时序与消息示例

日期：2026-10-12。代码基线：`6087e72`。补充[四部分架构](STUDIO-FOUR-PART-ASYNC-ARCHITECTURE.zh-CN.md)、[最终审查](STUDIO-FOUR-PART-FINAL-REVIEW.zh-CN.md)和[Session 参数与持续联系契约](STUDIO-SESSION-PROFILES-AND-LIVENESS.zh-CN.md)。

本图例是[最终修改方案](STUDIO-FINAL-MODIFICATION-PLAN.zh-CN.md)的交互附件；字段及实施顺序以主方案为准。GM 消费/确认仅在后端，inputCommit 与已接受 baseCommit 分开；profile 在接收执行意图时冻结，领取不重新选配置。

状态：拟实施设计。本文补足用户、前端交互组件、后端工作流、原生 Agent 和 Godot 项目之间的完整闭环；图中的类表示职责，可用现有 JavaScript 模块实现，不要求增加框架、服务或数据库。当前前端主要由 StudioApp 与 DraftStore 实现，下面的拆分尚未落地。

阅读路径：[前端类图](#frontend-classes) → [执行与项目类图](#execution-classes) → [项目与参数](#sequence-project) → [只读策划](#sequence-planning) → [制作与验收](#sequence-production) → [对象迭代](#sequence-iteration) → [失联与停止](#sequence-recovery)。

## 1. 前端组件与用户动作

<a id="frontend-classes"></a>

### 1.1 前端交互类图

```mermaid
classDiagram
    direction TB
    class StudioShell {
        +projectKey
        +mountProject()
        +renderAllowedStage()
    }
    class ProjectManager {
        +createOrOpenProject()
        +renameOrArchiveProject()
    }
    class DiscussionPanel {
        +editConceptDraft()
        +submitDiscussion()
        +showAIQuestionsAndUserAnswers()
    }
    class ReferenceTray {
        +uploadProjectReference()
        +selectReferencesForThisRound()
    }
    class ProposalReview {
        +showExactPlanAndDiff()
        +showFeedbackDecisions()
        +confirmReviewedRevision()
    }
    class IterationWorkbench {
        +restoreVersionedDraft()
        +submitObjectAdjustment()
    }
    class ObjectInspector {
        +selectStableObjectId()
        +editDeclaredField()
        +showSourceBindings()
    }
    class FeedbackEditor {
        +addTargetedFeedback()
        +reviewFeedbackDisposition()
    }
    class CandidateReview {
        +openOrStopPreview()
        +acceptOrRejectCandidate()
        +confirmExperienceFeedback()
    }
    class ExecutionMonitor {
        +showAttemptProfileAndEvidence()
        +requestCancelOrReconcile()
    }
    class DraftRebaseDialog {
        +showFieldConflictsAndNewBase()
        +confirmRebaseOrKeepOldDraft()
    }
    class SessionSettings {
        +filterEffortByModel()
        +saveRolePreferences()
        +showFrozenAttemptProfile()
    }
    class StatusBar {
        +showPhaseAndAttention()
        +showExecutionFreshnessAndUsage()
    }
    class ProjectController {
        +forwardTypedUserAction()
        +applyProjectView()
        +guardProjectAndPageGeneration()
    }
    class DraftStore {
        +saveVersionedDraft()
        +savePendingCommand()
        +restoreWithoutResubmitting()
    }
    class StudioTransport {
        +postTypedCommand()
        +queryOriginalReceipt()
        +resumeAuthorizedProjectEvents()
    }
    class ProjectView {
        +storeId
        +projectId
        +phaseAndAttention
        +allowedActions
        +throughSequence
    }
    class WorkflowService {
        +acceptCommand()
        +readProjectView()
        +replayProjectEvents()
    }

    StudioShell *-- ProjectManager
    StudioShell *-- DiscussionPanel
    StudioShell *-- ReferenceTray
    StudioShell *-- ProposalReview
    StudioShell *-- IterationWorkbench
    StudioShell *-- CandidateReview
    StudioShell *-- ExecutionMonitor
    StudioShell *-- DraftRebaseDialog
    StudioShell *-- SessionSettings
    StudioShell *-- StatusBar
    IterationWorkbench *-- ObjectInspector
    IterationWorkbench *-- FeedbackEditor
    StudioShell *-- ProjectController : 各面板的用户动作统一转交
    ProjectController *-- DraftStore
    ProjectController *-- StudioTransport
    ProjectController ..> ProjectView : 应用后端公开投影
    StatusBar ..> ProjectView : 展示业务状态与观测新鲜度
    StudioTransport ..> WorkflowService : HTTP JSON 与授权 SSE
```

各面板只产生用户动作并显示公开投影，由 ProjectController 统一关联项目、草稿与待核实命令。StudioTransport 处理通信；前端不自行裁定批准、原生成功或发布状态。图中没有前端直连 AgentRunner、原生 app-server、后端数据库或可变 Godot 工程的依赖。

### 1.2 组件如何对应现有界面

| 组件 | 用户操作与现有界面入口 | 输出/约束 |
| --- | --- | --- |
| ProjectManager / StudioShell | `#project-manager`、`#project-view`、项目路由 | 项目切换先保存本项目草稿、释放订阅；新页面不保留前项目的方案/作业/附件 |
| DiscussionPanel | `#concept-form`、`#answers-form`、`#questions` | 用户原文和 AI 问题分区；尚未形成方案时不展开 ProposalReview |
| ReferenceTray | `#images`、`#image-list` | 附件归属由后端确认；JSON 引用授权附件，不传任意本机路径 |
| ProposalReview | `#proposal-content`、`#freeze-area` | 显示精确方案、范围、差异与反馈决定；确认绑定该修订 |
| IterationWorkbench / ObjectInspector | `#workbench-panel`、`#object-catalog`、`#dynamic-fields` | 编辑稳定对象 ID 与声明字段；键入和保存草稿不启动 Agent |
| FeedbackEditor | `#feedback-editor`、`#feedback-list` | 为反馈保留稳定 feedbackId、对象、类别和原文；逐条显示处理决定 |
| CandidateReview | `#candidate-area`、`#candidate-preview` | 区分技术验证、试玩与用户接受；技术 PASS 不等于体验反馈已解决 |
| ExecutionMonitor | `#job-panel`、`#cancel-area`、`#reconcile-area` | 展示冻结执行配置、证据和停止事实；取消/核账仍经后端，不直接终止原生进程 |
| DraftRebaseDialog | `#rebase-dialog`、`#rebase-content` | 展示草稿与新基线的字段差异/冲突；用户选择重关联或保留旧草稿，不静默迁移 |
| SessionSettings | 拟新增策划/制作设置区 | 两角色偏好；按模型过滤 effort；运行配置另行只读显示 |
| StatusBar | `#workflow-status-copy`、`#job-panel`；观测明细拟补齐 | 显示下一位行动者、真实步骤、连接新鲜度、用量覆盖与停止状态 |
| ProjectController / StudioTransport | 从现有 StudioApp 内部职责逐步抽取 | 不另建工作流状态机；HTTP 写授权、SSE 游标和回执核查集中处理 |
| DraftStore | 现有 IndexedDB 草稿扩展 | 键至少包含 storeId/projectId、草稿种类、基线修订与 Git 引用；保存不等于提交 |

SessionSettings 是共享组件，按当前阶段显示适用角色。StatusBar 在项目页顶部持续可见。恢复 pending command 时只能查询或按原 ID/原内容重试，不把旧草稿自动变成新的制作请求。

## 2. 执行、协议记录与项目组件

<a id="execution-classes"></a>

```mermaid
classDiagram
    class StudioTransport {
        +postTypedCommand()
        +resumeProjectEvents()
    }
    class WorkflowService {
        +validateAndRecordCommand()
        +freezeProfileAndPlan()
        +applyExecutionFacts()
        +acceptCandidate()
    }
    class ProjectStore {
        +transaction()
        +receiptsAndEvents
        +projectsProposalsJobsSnapshots
    }
    class SessionPreferences {
        +projectId
        +preferencesRevision
        +plannerAndProducerPreferences
    }
    class ResolvedSessionProfile {
        +modelKeyAndProvider
        +effortAndLimits
        +rolePolicyAndCatalogRevision
    }
    class ProjectInspection {
        +projectIdAndSourceCommit
        +coveredScopeAndUnknowns
    }
    class ExecutionRequest {
        +ownerRefAndAttemptId
        +profileSnapshot
        +authorizedInputAndLease
    }
    class ApprovedPacket {
        +proposalRevisionAndBaseCommit
        +exactDocumentTasksFeedbackAndScope
    }
    class AgentRunner {
        +runPlannerOrProducer()
        +superviseAndReport()
        +confirmStopAndSealDelivery()
    }
    class CodexAdapter {
        +readModelCatalog()
        +startNativeTurn()
        +parseNativeFacts()
    }
    class ExecutionReport {
        +reportIdAndAttemptId
        +typedFactsAndStopEvidence
    }
    class ProjectRunner {
        +verifySealedArtifact()
        +previewSeparateCopy()
        +reportEngineFacts()
    }
    class GodotAdapter {
        +importRunAndStop()
        +observeEngine()
    }
    class ArtifactRef {
        +projectIdAndSourceCommit
        +jobIdAndAttemptId
    }
    class GodotProject {
        +objectDocumentAndBindings
        +nativeScenesScriptsAndAssets
        +runStandalone()
    }
    class Snapshot {
        +publicationRevision
        +acceptedArtifactRef
    }

    StudioTransport ..> WorkflowService : HTTP JSON 与 SSE
    WorkflowService *-- ProjectStore : 唯一业务事务
    WorkflowService --> SessionPreferences : 保存用户偏好
    WorkflowService --> ProjectInspection : 准备只读检查材料
    WorkflowService --> ExecutionRequest : 创建本次执行
    ExecutionRequest --> ResolvedSessionProfile : 冻结配置
    ExecutionRequest --> ProjectInspection : planner 输入
    ExecutionRequest --> ApprovedPacket : producer 或 verifier 输入
    AgentRunner ..> ExecutionRequest : JSON 领取
    AgentRunner *-- CodexAdapter : 内部原生适配
    AgentRunner --> ExecutionReport : 活动或终态事实
    AgentRunner --> ArtifactRef : producer 停止后封存
    ExecutionReport ..> WorkflowService : JSON 上报与持久回执
    ProjectRunner ..> ExecutionRequest : JSON 领取
    ProjectRunner ..> ArtifactRef : 验证或试玩精确输入
    ProjectRunner --> ExecutionReport : 验证或运行事实
    ProjectRunner *-- GodotAdapter : 内部引擎适配
    GodotAdapter ..> GodotProject : 原生文件与进程
    ArtifactRef ..> GodotProject : 精确 Git 版本
    WorkflowService --> Snapshot : 用户接受后记录
    Snapshot --> ArtifactRef : 发布版本的权威引用
```

跨进程虚线表示协议依赖，内部组合关系不要求独立服务。策划绑定 proposalId/revision，制作与验证绑定 jobId，各自有独立 attemptId。前端偏好、冻结执行配置、原生观测三者分开；后端批准和 Snapshot 不能由 Agent 文本或 Runner 直接改写。原生 stdio JSON-RPC 保持原格式，Godot 源码/资产走受控 Git/文件通道。

## 3. 完整时序与相邻示例

示例统一使用虚构的 store-example、project-example-a，全部模型、Git、原生身份和用量都是占位或说明性数据。它们说明工作台协议，不对应具体游戏案例，也没有发起实际执行。消息类型和字段是拟新增的严格类型化契约，不能直接提交给当前旧接口。命令走各自类型化路由，不增加任意 payload 的通用执行入口。

每个图例给出用户操作、关键消息和应出现的界面反馈。示例只展示选定消息，不是完整网络抓包；略去的事件不能成为客户端跳过 event.sequence 缺口的理由。回执只证明后端已持久接收，不证明原生执行已开始。

<a id="sequence-project"></a>

### 3.1 项目建立、切换、参数与订阅

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as 前端交互组件
    participant B as 后端工作流
    participant A as AgentRunner
    participant N as 原生 app-server

    A->>N: initialize 与 model/list，不启动 turn
    N-->>A: 模型键、支持 effort、输入模态
    A->>B: 注册执行器身份与能力目录
    U->>F: 打开工作台
    F->>B: 握手并读取授权项目摘要
    B-->>F: store、协议、写会话与项目列表
    alt 用户创建新项目
        U->>F: ProjectManager 输入名称并创建
        F->>B: project.create(commandId, title)
        Note over B: 类型化创建命令尚无 projectId；后端分配项目身份
        B-->>F: Receipt 与空项目引用
    else 用户选择已有项目
        U->>F: ProjectManager 选择 project-example-a
    end
    F->>F: 保存旧草稿，释放旧订阅，递增页面代次
    F->>B: 读取该项目一致 ProjectView
    B-->>F: 阶段、允许动作、throughSequence、偏好
    F->>B: 授权订阅该项目 after=throughSequence
    B-->>F: 后续持久事件与实时事件
    Note over F: StudioShell 只挂载已开放阶段；空项目仅显示初始讨论
    U->>F: SessionSettings 选择策划模型、effort、时限和软预算
    F->>B: session.preferences.update，绑定偏好修订
    Note over B: 校验所选 Runner 目录与角色策略；单事务保存
    B-->>F: Receipt 与新 preferencesRevision
    F->>F: 回显保存值；此操作不提交讨论或启动制作
```

示例：用户打开项目 A 的初始讨论页，设置策划使用目录中的模型、medium、420 秒和 12000 token 软预算。

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "session.preferences.update",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "preferences-planner-example",
  "expected": {"preferencesRevision": 1},
  "payload": {
    "role": "planner",
    "modelKey": "<该执行器目录中的实际模型键>",
    "effort": "medium",
    "limits": {"maxDurationSeconds": 420, "softTotalTokens": 12000}
  }
}
```

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "receipt",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "preferences-planner-example",
  "decision": "accepted",
  "effectRefs": {"preferencesRevision": 2}
}
```

界面显示“策划设置已保存；等待用户提交想法”。尚无初步方案、制作作业或活动模型回合。medium 在本例假设为所选模型支持的值；真实目录不支持时明确拒绝。

<a id="sequence-planning"></a>

### 3.2 初始讨论、只读检查、澄清与方案审阅

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as 前端讨论与方案组件
    participant B as 后端工作流
    participant A as AgentRunner
    participant N as 原生 app-server

    U->>F: DiscussionPanel 编辑文字
    opt 用户新增参考图
        U->>F: ReferenceTray 上传图片并选择用途
        F->>B: 上传到当前项目受控附件通道
        B-->>F: 归属已确认的 assetRef 与用途元数据
    end
    U->>F: ReferenceTray 选择本轮参考
    F->>F: 保存本项目概念草稿；不调用模型
    U->>F: 点击提交讨论
    F->>B: concept.submit，原意图 ID、内容基线、偏好修订
    Note over B: 原子保存提案修订、精确配置、回执、待执行记录与事件
    B-->>F: Receipt(proposalId, revision=1)
    B-->>F: SSE：等待策划开始
    loop 每次显式提交启动一轮；澄清后继续，READY 或失败后退出
        B->>B: 准备精确只读 ProjectInspection，使用已冻结 planner profile
        Note over B: 初始无游戏源时 sourceAvailable=false；不读取其他项目
        A->>B: 持久领取意图，claim(planner)
        B-->>A: ExecutionRequest(proposal/revision, attemptId, 输入, 租约)
        A->>A: 保存启动意图与本地时限，准备授权只读材料
        A->>N: thread/start，只读角色、精确模型、禁止静默替换
        N-->>A: 原生 thread 身份与启动配置
        alt 启动配置核对通过
            A->>N: turn/start(model, effort, 有界输入)
            N-->>A: turn 启动回执
            A->>B: 本次配置证据与实际启动观测
            B-->>F: SSE：等待 Agent 整理方案
            par 程序监督
                A->>B: 心跳、续约、控制状态查询
                B-->>A: 当前控制状态
            and 原生已有通知
                N-->>A: 状态、item、tokenUsage
                A->>B: 有界活动与累计用量报告
                B-->>F: SSE：真实步骤与观测新鲜度
            end
            N-->>A: turn/completed 与结构化策划结果
            A->>A: 核实原生与关联进程停止
            A->>B: planning.result(reportId, 结果, 检查覆盖, 停止事实)
            Note over B: 校验归属、修订、严格输出、字段和反馈覆盖
            B-->>A: 持久 ReportAck
            alt 仍需澄清
                B-->>F: SSE：AI 问题、等待用户反馈
                F->>U: DiscussionPanel 显示 AI 问题，方案区仍隐藏
                Note over A,N: 等待用户期间没有活动模型回合
                U->>F: 输入答案或补充约束
                F->>B: proposal.revise，新命令 ID、当前修订、新回答
                Note over B: 新修订绑定本次偏好并冻结配置；旧审阅失效
                B-->>F: Receipt，新提案修订，等待策划开始
            else 方案 READY
                B-->>F: SSE：精确方案引用，等待用户确认
                F->>U: ProposalReview 展开对象、任务、范围与反馈决定
            else 策划结果失败或停止未知
                B-->>F: SSE：失败或待核实，无 READY 方案
                F->>U: 保留输入和诊断入口；不自动重投
            end
        else 配置不符、拒绝或启动身份不明
            A->>B: 配置拒绝/未知事实；已启动进程按策略停止并核账
            B-->>A: ReportAck
            B-->>F: SSE：执行失败或待核实；不静默换模型/effort
        end
    end
    Note over U,F: 此处只得到可审阅方案；没有自动冻结或启动制作
```

示例：用户只提交“希望先明确对象、交互和首轮验证目标”，planner 返回需要确认 MVP 对象范围的问题。

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "concept.submit",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "concept-example-01",
  "expected": {"publicationRevision": 0, "sourceCommit": null, "preferencesRevision": 2},
  "payload": {
    "text": "希望先明确对象、交互和首轮验证目标。",
    "assetRefs": [],
    "targetObjectIds": []
  }
}
```

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "event",
  "type": "planning.changed",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "eventId": "planning-event-example-06",
  "sequence": 6,
  "ownerRef": {"kind": "proposal", "id": "proposal-example-initial", "revision": 1},
  "attemptId": "planner-attempt-example-01",
  "payload": {
    "status": "NEEDS_CLARIFICATION",
    "questions": [{"id": "question-example-mvp", "prompt": "哪些对象必须进入首个 Demo？", "type": "text", "required": true}],
    "planRef": null,
    "attention": "user_feedback"
  }
}
```

用户下一次回答使用新 commandId，但绑定旧提案的当前修订：

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "proposal.revise",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "answer-example-01",
  "expected": {
    "proposalRevision": 1,
    "publicationRevision": 0,
    "sourceCommit": null,
    "preferencesRevision": 2
  },
  "payload": {
    "proposalId": "proposal-example-initial",
    "answers": [{"questionId": "question-example-mvp", "text": "首轮仅包含对象 A 和对象 B。"}]
  }
}
```

后端递增为修订 2，创建新的只读 attempt。重送 concept-example-01 只返回原回执，不创建第二个提案。若用户回答后得到 READY，才展开 ProposalReview；“AI 问题已返回”不等于“初步方案已经完成”。参考图片/文档作为输入内容，不改变项目身份、角色权限或派发命令。

<a id="sequence-production"></a>

### 3.3 精确确认、可写制作、独立验证、试玩与接受

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as 前端审阅与候选组件
    participant B as 后端工作流
    participant A as AgentRunner
    participant N as 原生 app-server
    participant P as ProjectRunner
    participant G as Godot 进程

    U->>F: ProposalReview 阅读修订 2 并明确确认
    F->>B: proposal.freeze，精确审阅引用、修订与源基线
    Note over B: 校验完整文档/任务/反馈/范围，保存批准表单
    B-->>F: Receipt(packetId)
    F->>U: 显示冻结表单及 production 的 SessionSettings
    U->>F: 保存制作模型、effort、时限与软预算
    F->>B: session.preferences.update(role=producer)
    B-->>F: Receipt(preferencesRevision=3)
    U->>F: 点击开始制作
    F->>B: production.start，packetId、精确基线、偏好修订
    Note over B: 原批准/源锁/独占校验；一次消费；保存 job 与冻结 profile
    B-->>F: Receipt(jobId)，等待制作开始
    A->>B: claim(producer)，持久领取身份
    B-->>A: ExecutionRequest(jobId, attemptId, 表单, profile, 文件范围)
    A->>A: 准备并记录私有制作副本的精确输入 Git 基线
    A->>N: 独立 thread/start，可写角色与精确模型
    N-->>A: 原生身份与启动配置
    Note over A: 核对配置；不符/未知转入 3.5 停止或核账，禁止自动替换
    A->>N: turn/start，仅核对通过时提交批准输入与 effort
    N-->>A: turn 启动回执
    A->>B: 实际启动与配置观测
    B-->>F: SSE：等待 Agent 制作
    par 程序心跳与控制
        A->>B: 续约、观测与停止状态查询
        B-->>A: 当前控制状态
    and 原生制作事实
        N->>N: 在授权私有副本中修改批准文件
        N-->>A: 工具活动与 tokenUsage
        A->>B: 活动与累计用量摘要
        B-->>F: SSE：当前步骤及用量新鲜度
    end
    N-->>A: turn/completed
    A->>A: 确认停止；可信适配器封存精确 Git 交付
    A->>B: production.result(reportId, ArtifactRef, 停止事实)
    Note over B: 单事务保存报告、VERIFYING、事件与验证任务
    B-->>A: ReportAck
    B-->>F: SSE：等待后端验证
    P->>B: claim(verifier)
    B-->>P: 新 attempt、同一 ArtifactRef、批准表单
    P->>P: 物化独立验证副本，保持封存源不变
    P->>G: 按策略导入、编译与运行验证
    G-->>P: 引擎与运行证据
    P->>P: 确认停止、保护范围与源版本一致
    P->>B: verification.result，PASS 或 FAIL 与精确源引用
    B-->>P: ReportAck
    alt 有效 PASS 且未取消
        B-->>F: SSE(candidate.ready)，等待用户验收
        F->>U: CandidateReview 展示候选、技术证据与反馈决定
        opt 用户试玩
            U->>F: 点击试玩该候选
            F->>B: preview.start(commandId, candidateId)
            B-->>F: Receipt(previewId)
            P->>B: claim(preview)
            B-->>P: 该候选的精确预览请求
            P->>G: 独立试玩副本启动
            G-->>P: 运行观测
            P->>B: preview.started 与运行事实
            B-->>F: SSE：试玩入口与状态
            U->>F: 结束试玩
            F->>B: preview.stop(commandId, previewId)
            P->>B: 读取停止控制
            B-->>P: 请求停止
            P->>G: 停止并核实退出
            P->>B: preview.stopped
            B-->>F: SSE：试玩已停止
        end
        alt 用户接受
            U->>F: 明确接受精确候选
            F->>B: candidate.accept，候选源版本与当前发布基线
            Note over B: 事务记录用户决定、Snapshot 与 publicationRevision
            B-->>F: Receipt 与 SSE(publication.changed)
            F->>U: 显示已接受 Demo 和进入迭代工作台链接
        else 用户拒绝
            U->>F: 拒绝候选并记录反馈
            F->>B: candidate.reject，新命令与用户理由
            B-->>F: Receipt 与 SSE：候选已拒绝，已接受版本保留
        end
    else 验证失败
        B-->>F: SSE：失败原因与诊断引用，无可接受候选
        F->>U: 显示失败和恢复动作，不自动启动新制作
    end
```

示例：用户确认初始方案修订 2，精确审阅引用包含完整文档、任务、反馈决定和范围：

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "proposal.freeze",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "freeze-example-01",
  "expected": {"proposalRevision": 2, "publicationRevision": 0, "sourceCommit": null},
  "payload": {
    "proposalId": "proposal-example-initial",
    "reviewedPlanRef": "plan-example-initial-r2"
  }
}
```

reviewedPlanRef 指向后端保存的不可变精确内容，不能指向“最新方案”或任意路径。后端核对真实用户写授权、审阅内容与版本后生成 packet-example-initial-r2；用户另行选择制作设置并点击开始。

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "production.start",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "production-example-01",
  "expected": {"publicationRevision": 0, "sourceCommit": null, "preferencesRevision": 3},
  "payload": {"packetId": "packet-example-initial-r2"}
}
```

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "event",
  "type": "candidate.ready",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "eventId": "candidate-event-example-24",
  "sequence": 24,
  "ownerRef": {"kind": "job", "id": "job-example-01"},
  "attemptId": "verifier-attempt-example-01",
  "payload": {
    "candidateId": "candidate-example-01",
    "artifactRef": "artifact-example-01",
    "sourceCommit": "<source-commit-example-01>",
    "verification": "PASS",
    "attention": "user_acceptance",
    "published": false
  }
}
```

此刻顶部显示“等待用户验收”，已接受版本仍为 0。只有用户 candidate.accept 经后端确认后才成为发布修订 1，并显示“进入迭代工作台”。初始制作的 sourceCommit=null 表示尚无已接受游戏源；可信适配器仍须在该项目内准备、绑定并检查制作输入 Git 基线，不能借用另一项目工程或绕过规格确认。源锁、批准和停止门禁沿用原计划。

<a id="sequence-iteration"></a>

### 3.4 对象编辑、自然语言反馈、再策划与精细验收

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as 前端迭代工作台
    participant B as 后端工作流
    participant A as AgentRunner
    participant N as 原生 app-server
    participant P as ProjectRunner
    participant G as Godot 进程

    U->>F: 点击进入迭代工作台
    F->>B: 读取当前已接受 Snapshot、对象文档与 ProjectView
    B-->>F: 发布修订 1、精确 Git、对象/字段/绑定、允许动作
    U->>F: ObjectInspector 选对象 A，把字段 A 从 10 改为 12
    U->>F: FeedbackEditor 添加对象反馈；输入自然语言说明
    F->>F: 保存带基线的本项目草稿与 feedbackId；不调用模型
    U->>F: 点击整理本轮调整
    F->>B: iteration.submit，字段差异、原文、feedbackIds、版本与偏好
    B->>B: 校验字段/对象/附件归属与当前基线，保存新提案和冻结配置
    B-->>F: Receipt，等待策划开始
    B->>B: 按已接受 Git 准备目标范围 ProjectInspection
    A->>B: claim(planner)
    B-->>A: 新只读 attempt、有界检查材料、当前文档与反馈
    A->>N: 新只读 session，精确模型/effort 与本轮输入
    N-->>A: 活动、用量与结构化结果
    A->>A: 确认完成与停止
    A->>B: planning.result，字段结果、反馈决定与覆盖/未知
    B-->>A: ReportAck
    alt 反馈需要澄清或输出未覆盖请求
        B-->>F: SSE：问题或校验失败；没有 READY 方案
        F->>U: 显示关联 feedbackId 的问题，保留草稿
        Note over U,N: 用户回答后复用 3.2 的新修订策划流程；不自动制作
    else 有效 READY
        B-->>F: SSE：精确方案、字段差异与逐条 FeedbackResult
        F->>U: ProposalReview 显示采纳/推迟/拒绝/待澄清和理由
        U->>F: 审阅方案并确认本轮范围
        F->>B: proposal.freeze，精确审阅内容与基线
        B-->>F: Receipt(新 packetId)
        U->>F: 点击制作本轮
        F->>B: production.start，新 commandId、packetId、偏好修订
        B-->>F: Receipt(新 jobId)
        A->>B: claim(producer)
        B-->>A: 新制作 attempt、批准表单与私有副本输入
        A->>N: 独立可写 session，落实本轮已批准调整
        N-->>A: 活动、用量与完成事实
        A->>A: 确认停止并封存本轮交付
        A->>B: production.result，精确新 ArtifactRef
        B-->>A: ReportAck
        P->>B: claim(verifier)
        B-->>P: 同一新 ArtifactRef 与本轮批准表单
        P->>G: 独立副本技术验证与运行检查
        G-->>P: 精确版本的验证事实
        P->>B: verification.result，停止事实与 PASS/FAIL
        B-->>P: ReportAck
        alt 验证 PASS 且未取消
            B-->>F: SSE：新候选及反馈关联，仍保留发布修订 1
            Note over F,G: 试玩用新候选副本；原已接受版本不被制作修改
            U->>F: 试玩后接受候选；逐条确认已解决或仍需后续处理
            F->>B: candidate.accept，精确候选/基线与反馈验收决定
            B-->>F: Receipt 与发布修订 2 的 SSE
            F->>U: 更新已接受基线，保留未解决反馈与未提交草稿
            opt 当前草稿基线陈旧
                F->>U: DraftRebaseDialog 展示字段差异、冲突与新基线
                U->>F: 明确选择重关联，或保留旧草稿
                F->>F: 按用户选择保存草稿；不自动提交或调用模型
            end
        else 验证失败
            B-->>F: SSE：无可接受候选，保留发布修订 1
        end
    end
```

示例：用户修改对象 A 的声明字段，并针对同一对象补充自然语言反馈。该例只描述工作台编辑与关联，不预设游戏玩法。

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "iteration.submit",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "iteration-example-01",
  "expected": {
    "publicationRevision": 1,
    "sourceCommit": "<source-commit-example-01>",
    "preferencesRevision": 3
  },
  "payload": {
    "text": "请保留其他对象，本轮只调整对象 A，并说明这条反馈如何处理。",
    "targetObjectIds": ["object-example-a"],
    "fields": [{"objectId": "object-example-a", "fieldId": "field-example-a", "value": 12}],
    "feedback": [{
      "feedbackId": "feedback-example-a",
      "objectId": "object-example-a",
      "category": "behavior",
      "message": "希望这个对象的操作反馈更明确。"
    }]
  }
}
```

随后有效策划结果中的一条 FeedbackResult 片段：

```json
{
  "feedbackId": "feedback-example-a",
  "proposalId": "proposal-example-iteration",
  "proposalRevision": 1,
  "disposition": "adopted",
  "reason": "本轮采纳，关联目标对象的反馈表现和验证条件。",
  "taskRefs": ["task-example-feedback-a"],
  "requirementRefs": ["requirement-example-feedback-a"],
  "candidateRef": null,
  "userAcceptance": "pending"
}
```

这是“计划已采纳”的事实，不是“已实现”或“用户认为已解决”。候选形成后关联精确 candidateRef，用户体验验收后才记录对应接受决定。推迟/拒绝的反馈必须有理由，待澄清阻止 READY。字段结果必须精确保留 value=12；只读检查未覆盖的部分明示未知。字段本身若已由现有代码正确读取，制作可以不改游戏源码，不能为了制造 diff 做无关修改。

例如，用户可以接受本轮候选，同时记录一条体验反馈仍需后续调整：

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "command",
  "type": "candidate.accept",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "commandId": "accept-example-02",
  "expected": {"publicationRevision": 1, "sourceCommit": "<source-commit-example-01>"},
  "payload": {
    "candidateId": "candidate-example-02",
    "sourceCommit": "<source-commit-example-02>",
    "feedbackAcceptance": [{"feedbackId": "feedback-example-a", "decision": "needs_followup"}]
  }
}
```

候选接受和每条反馈的验收结论分别记录；本例更新到发布修订 2，但 feedback-example-a 仍进入后续迭代。后台必须校验反馈属于本项目、此次候选关联和允许的状态，不能由前端任意填写 ID 来解决其他反馈。没有明确提交体验验收决定的反馈，不因整体验收而被默认标记为已解决。

<a id="sequence-recovery"></a>

### 3.5 联系、新鲜度、断线恢复、预算停止与项目切换

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as 前端状态与通信组件
    participant B as 后端工作流
    participant A as AgentRunner
    participant N as 原生 app-server

    par 独立程序监督
        A->>B: 心跳、续约、原生进程观测
        B-->>A: 控制状态
    and 已有原生通知
        N-->>A: item、状态、累计 tokenUsage
        A->>B: 按 attempt 合并活动/用量摘要
        B-->>F: 项目 SSE：活动与各自观测时间
    end
    Note over F,N: 活动沉默不证明断线；心跳不调用模型
    alt 仅前端 SSE 断开
        F->>F: 显示状态流陈旧，保留草稿和原意图
        F->>B: 查询待核实 commandId，读取 ProjectView
        B-->>F: 原回执、快照与 throughSequence
        F->>B: 从快照游标恢复授权订阅
        B-->>F: 重放与实时事件；不创建新制作
    else 后端暂时断开
        A--xB: 心跳/报告暂时无法送达
        A->>A: 保留有界待确认记录；本地时限与用量监督继续
        Note over A,N: 原生身份和 attempt 不变；不重新启动回合
        B->>B: 重启并恢复持久 store 与工作流记录
        A->>B: 更新授权，核账原 attempt，补送事实
        B-->>A: 原回执或证据接收 ACK；租约失效时不直接推进
        F->>B: 握手、核对 store、读取快照并恢复订阅
        B-->>F: 后端裁决后的状态与新鲜度
    else Runner 或原生联系不能确认
        B->>B: 记录执行待核实；租约过期不视为已停止
        B-->>F: SSE：最后可信事实、独占与核账入口
        F->>U: ExecutionMonitor 提供核账；可保存草稿，新制作受门禁约束
    end

    opt 用户停止，或活动执行达到本地时限/可观测软预算
        opt 用户主动停止
            U->>F: ExecutionMonitor 请求停止当前执行
            F->>B: execution.cancel(commandId, ownerRef, attemptId)
            Note over B: 事务保存取消；阻止后续候选推进
            B-->>F: Receipt；尚未确认停止
            A->>B: 查询控制状态
            B-->>A: cancelRequested
        end
        Note over A: 本地阈值触发无需等待后端在线；只作用于活动执行
        A->>N: turn/interrupt，必要时停止持有的进程组
        alt 实际停止可确认
            A->>A: 保存 stopReason、最后可信用量与停止事实
            A->>B: 原 reportId 的 execution.stopped；离线则保留待补送
            Note over B: 事务保存；未完成交付不产生候选
            B--xA: ACK 丢失
            A->>B: 同 reportId、同内容补送
            B-->>A: 原 ReportAck；不重复执行状态效果
            B-->>F: SSE：已停止/已取消，显示用量覆盖
        else 停止无法确认
            A->>B: execution.observation，停止未知
            B-->>F: 执行状态待核实；保留占用，不自动重开
        end
    end

    U->>F: 切换到项目 B
    F->>F: 保存 A 的草稿，释放 A 订阅，更新页面代次
    F->>B: 读取项目 B 快照并订阅 B
    B-->>F: B 的 ProjectView 与事件
    B-->>F: 缓冲的项目 A 迟到事件
    F->>F: 校验 store/project/页面代次；A 事件不改变 B 界面
```

示例是 3.4 本轮制作的一种替代结局：job-example-02 还在制作时，原生累计用量报告为 13100，本次软预算是 12000；Runner 请求停止并确认退出。因此该路径没有 candidate-example-02 或发布修订 2。超过数值用于说明延迟，不是可保证的超额范围。

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "report",
  "type": "execution.stopped",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "ownerRef": {"kind": "job", "id": "job-example-02"},
  "attemptId": "producer-attempt-example-02",
  "reportId": "stop-report-example-01",
  "payload": {
    "stopReason": "soft_token_budget",
    "terminationConfirmed": true,
    "nativeRef": {"threadId": "thread-example-production-02", "turnId": "turn-example-production-02"},
    "usage": {
      "source": "thread/tokenUsage/updated",
      "coverage": "native_thread",
      "totalTokens": 13100
    },
    "artifactRef": null,
    "deliveryComplete": false
  }
}
```

```json
{
  "schemaVersion": "studio.message.v1",
  "kind": "report_ack",
  "storeId": "store-example",
  "projectId": "project-example-a",
  "reportId": "stop-report-example-01",
  "disposition": "recorded",
  "effectRefs": {"candidateId": null}
}
```

界面显示“本轮因软预算停止；没有可验收候选”。后端失联时该报告先留在 Runner，本地监督继续；补送 ACK 若仅确认“证据已保存”，需沿既有核账规则裁决，不能换 reportId 绕过租约或取消门禁。无法确认停止时不能显示“已停止”。用量缺失为 null/未知，不能假定为零；累计快照不能逐次相加，主线程统计不自动包含其他模型工具。

软预算没有原生硬 token 上限的保证。已完成后的可信用量补报仅更新记账，不重新启动执行，也不自动撤销已接受版本。用户取消与完成结果按后端事务顺序裁决：取消先提交则结果只留证据；结果先提交且已进入验证则取消当前验证；已发布版本不被取消执行撤销。

## 4. 图、示例和功能充分性核对

| 检查项 | 覆盖位置 | 必须保留的边界 |
| --- | --- | --- |
| 用户交互前端 | 1.1、1.2；所有时序均包含用户 | 组件是界面职责，动作统一经后端，不额外建业务服务 |
| 项目管理与首次进入 | 3.1 | 新项目空状态；归属检查与旧订阅释放；创建前尚无 projectId |
| 用户/AI 来源与逐步展开 | 3.2 | 问题与用户回答分区；READY 才显示方案，未自动批准 |
| 精确只读项目检查 | 3.2、3.4 | 绑定 Git 与覆盖范围；检查不执行工程，不读取另一项目 |
| 参数定义、保存与冻结 | 3.1、3.3 | 模型目录校验；两角色偏好；只影响后续 attempt |
| 制作、验证、试玩、接受 | 3.3 | 独立副本；停止后封存；精确验证；用户接受后发布 |
| 持续精细调整与反馈 | 3.4 | 稳定对象/字段/反馈身份；原文、处理决定、实现与体验验收分开 |
| 心跳、断线、预算、停止 | 3.5 | 程序观测；未知不伪装成功；不重复启动或循环调用模型 |
| 回执和补送顺序 | 3.1、3.2、3.5 | 授权/类型/归属后先查原命令/报告，再检查新基线/租约 |
| 跨项目与迟到消息 | 3.1、3.5 | store/project/页面代次、提案修订及执行身份共同防止串扰 |

每条 mutation/report 均有持久回执或 ACK；图中重复路径省略了部分相同 ACK，但不是允许省略实现确认。事件提交与业务状态、回执同事务；SSE 保活不是项目业务事件。工作流阶段与行动者仍由后端现有记录产生，前端只增加展示与通信职责。

已完成机械检查：本文 13 个 JSON 示例严格解析通过，无重复键和非标准常量；每张时序图后都有对应示例；本地链接/锚点、代码围栏、5 张时序图的参与者和分支、2 张类图的引用与括号一致。相关五份文档共核对 19 个 JSON 示例、9 张时序图、5 张类图与 20 个本地链接；这些是源码结构检查，没有验证 Mermaid 图形渲染。

本轮只补充设计、图与虚构消息示例，没有改动工作台运行代码或启动真实 Agent/Godot。图的结构检查与协议实现验收分开。

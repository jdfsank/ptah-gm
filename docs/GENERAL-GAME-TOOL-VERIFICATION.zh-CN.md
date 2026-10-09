# 通用 2D 游戏工作台实现与验证

日期：2026-10-09。工具开发和隔离测试已完成；游戏项目的方案确认与候选接受由工作台用户逐轮执行。

## 最终实现

统一对象协议 `studio.objects.v1` 描述项目、场景、实体、机制、规则、界面、素材和内容。每个对象具有稳定 ID、关系、字段和源文件绑定。字段支持数字、整数、布尔、文字、选项、颜色和二维坐标；二维坐标使用 `[x,y]`。字段调整与对象反馈独立于自然语言传输，后端重新校验类型、范围、可编辑性和当前 Git 基线。

前端提交初始文字或图片参考后，单独的只读策划 session 返回问题或完整对象计划。回答会启动新的策划回合。用户确认后，后端冻结提案修订、对象文档、GM 规格、验收条目和文件范围，再启动另一个制作 session。后端独立审计和运行候选，返回对象映射、差异、技术证据及待人工体验要求。用户接受后，工作台原子更新完整快照，继续按对象精细迭代。

当前实现以重组的 `sources/GodotMaker-non-pk/` 为规格与工作流来源，以 [GameStudio](https://github.com/openai/plugins/tree/main/plugins/game-studio) 的状态、渲染、输入和界面分离原则为参考。GameStudio 参考版本为 `0722921d5542fc593105c27bd52630babd8b8c2a`。本轮没有继续使用 Ptah 技能。Godot 2D 为制作目标。

## 与原计划的变化

| 方面 | 原有实现 | 当前实现 |
| --- | --- | --- |
| 新项目 | 固定 collect-loop 玩法和预设参数 | 开放概念与统一对象文档，不按游戏类别组织流程 |
| 交互目标 | 预置能力字段 | 稳定对象 ID、字段、关系、源绑定与定向反馈 |
| 策划 | 固定问题和范围 | 原生只读策划 session，多轮结构化澄清 |
| 制作输入 | 模板特定操作 | 冻结的完整对象计划与标准 changeRequest |
| 验证 | 特定玩法适配器 | 通用技术验证；特定玩法断言另行提供实际观察 |
| 后续调整 | 预定字段修改 | 对象字段、自然语言与反馈并行；草稿按版本保存和重关联 |

保留前后端分离、独立制作 session、Git worktree、幂等派发、人工确认和候选接受。旧 collect-loop 项目仍走原有流程，旧批准不会自动转换为通用范围。

## GT-01 至 GT-08 验收对应

| 条目 | 实现和证据 |
| --- | --- |
| GT-01 对象标准 | `backend/object_protocol.py`、协议回归、两种游戏对象目录 |
| GT-02 独立策划 | `backend/generic_workflow.py`、策划问答/修订/取消回归、原生策划 session 记录 |
| GT-03 精细调整 | Studio 对象编辑器与 QA、速度字段和青色反馈的真实迭代 |
| GT-04 冻结与独立制作 | 完整审阅绑定、GM non-pk 规格门、不同策划/制作 session ID |
| GT-05 后端验证 | 文件范围审计、干净导入、后端主场景 harness；用户要求保留 `NOT_TESTED` |
| GT-06 返回并继续迭代 | 完整快照更新、对象目录、草稿重关联、缺陷对象反馈修复 |
| GT-07 旧流程兼容 | 后端和完整前端回归，旧源锁保护保持；重启未知执行继续隔离 |
| GT-08 实际证明 | Bridge Runner、Light Grid、速度/颜色迭代、重开修复和独立玩法探针 |

## 原生制作证据

所有下列 session、合成确认和接受发生在单独测试存储 `/tmp/gm-general-probe-20261009-e3`。记录明确为 `testData=true`、`productionAuthorized=false`、`humanAcceptance=NOT PERFORMED`；未向正式工作区写入任何游戏或批准。

| 回合 | 策划 session | 制作 session | 候选 Git commit |
| --- | --- | --- | --- |
| 跳跃 MVP | `01a11fea-2d8c-71f2-bfd5-cfddae40614b` | `01a11fec-ec04-7a41-ae99-5ccc78709af1` | `3abd7d9af0802b002ea475b8ebddc7d23e248448` |
| 速度和青色反馈 | `01a11ff2-dbf9-73e3-ae33-3ba958489d1e` | `01a11ff5-226e-7221-8fc4-418bcbddd8cd` | `850d031194875fb5d302d188dae3baad709d95f7` |
| Lights Out MVP | `01a11ff6-7a40-7691-a173-69ab250387b4` | `01a11ff9-7387-7500-ba0f-18d0391a521c` | `a48afacc34667adf9f092c55180e75861ca088a9` |
| 重开缺陷反馈修复 | `01a12004-70f8-77d1-b3e1-15ea2488b265` | `01a12007-76da-7980-8813-352f8a035ffc` | `b4d535762b38dbb932c886c4e46db10972d4c762` |

前三轮详见[原生探针 r3](../evidence/workflow/general/real-object-probe-r3.json)，第四轮详见[对象反馈修复](../evidence/workflow/general/reset-feedback-probe.json)。四轮均由真实 Godot `4.6.3.stable.official.7d41c59c4` 完成干净导入和后端主场景冒烟。

前两次原生探针因策划输出为审计文字而非契约 JSON 失败，没有生成可接受候选：[第一次](../evidence/workflow/general/real-object-probe.json)、[第二次](../evidence/workflow/general/real-object-probe-r2.json)。驱动随后清理父 session 上下文、关闭托管回合委派、在直接提示中禁止子任务，并从最终消息边界提取响应；第三次才通过。保留失败记录供追溯。

## 实际玩法观察与修复

通用技术验证不会仅凭游戏启动推断玩法正确。后端另写了两个固定 fixture 的独立探针，从证据绑定的 Git commit 重建临时工程，使用实际输入和状态断言。

Bridge Runner 原候选在获胜后按 R 瞬移回出生点，却立即再次进入 WON。复现记录显示 `state=1, x=100, exitOverlap=false`，见[原始失败](../evidence/workflow/general/bridge-gameplay-original.json)和[复现](../evidence/workflow/general/bridge-gameplay-original-recheck.json)。问题作为 `main-scene` 的 bug 反馈进入正常策划与制作流程，未直接修改候选游戏。修复清除了旧出口接触，并核对当前碰撞形状。

[修复后的最终复测](../evidence/workflow/general/bridge-gameplay-repaired-r2.json)通过 12 项断言：冻结速度、保留速度 300 与青色、水平移动、跳跃、两次平台落地、实际路线获胜、获胜后 R 返回 playing、恢复控制和 HUD、再次完整路线获胜、坠落恢复。较早的[修复复测](../evidence/workflow/general/bridge-gameplay-repaired.json)保留较小的 10 项覆盖，不冒充再次通关证据。

[Light Grid 玩法探针](../evidence/workflow/general/puzzle-gameplay.json)通过 12 项断言：九格初始对角线、冻结强调色、实际鼠标点击角/边/中心的正交切换与计步、R 的重复键忽略、Reset 恢复、三步鼠标解法、胜利文字、胜后点击锁定、R 与按钮的获胜后重开。

这些是固定 fixture 的输入和状态观察，不是美术、手感、难度或任意游戏的完整验收。通用生产候选的体验要求仍显示 `NOT_TESTED`，由用户试玩和接受。

## 回归与最终复审

- 后端完整回归：105 项通过。
- 完整前端测试脚本通过，其中 Python 回归 81 项，含旧工作台和新 Studio 对象 QA。最后提示文案调整后，重新通过 Studio 两组 QA 与 JavaScript 语法检查。
- GM non-pk：review_support 43 项、bound_workflow 80 项、append_stage_event 21 项，共 144 项通过。
- 最终复审修复了策划在规格准备期间取消后永久占用项目的竞态；回归证明同项目可再次策划。
- 旧草稿重关联后的只读字段不会进入 changeRequest；删除未绑定源码同样触发范围失败。
- GM 服务记录按精确字节绑定；制作方不能篡改审批记录、冻结对象、规格或受保护运行接口。
- `git diff --check` 通过；原 HUD/title_screen 拒绝检查和 `frontend/tools/velvet-source-lock.json` 未改变。未运行独立 SHA/MD5 构建校验。

浏览器实测了对象目录、速度草稿、独立反馈和确切候选的 Godot 预览入口。[对象界面截图](../evidence/workflow/general/studio-object-feedback.png)中的 310 为未提交的测试草稿，正式快照仍为 300。原生窗口截图服务不可用，因此没有声称原生窗口视觉验收。

## 复现和部署

完整操作见[部署说明](DEPLOYMENT-MANUAL.zh-CN.md)与[用户说明](USER-MANUAL.zh-CN.md)。`tools/run_general_workflow_probe.py` 和 `tools/run_general_iteration_probe.py` 只使用隔离测试存储。`tools/run_general_gameplay_probe.py` 从原生测试记录绑定的 Git commit 重建工程并注入后端 harness。

持久 fixture 源码保存在 `evidence/workflow/general/fixtures/`，为被测提交的 Git 归档内容，不是游戏发布包。它们不包含 `.git`、`.godot`、审批记录或注入的 gameplay harness。可以将 fixture 复制到临时目录、复制对应 `harnesses/*_gameplay.gd` 为 `backend_gameplay.gd`，再执行干净导入与 `--script res://backend_gameplay.gd`；避免向正式项目写入测试脚本。

当前部署是 macOS 本机单用户服务，只监听 `127.0.0.1`。Godot 执行没有经过验证的 OS 沙箱；文件范围和临时副本是合作型同用户执行的应用层控制。当前协议不支持 3D、外部插件、音频/着色器制作或导出发布；图片可作为参考或已提供素材。后续适配器可以沿对象与通信协议扩展，并需建立对应的实际验证能力。

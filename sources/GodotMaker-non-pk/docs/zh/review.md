# 绑定版本的可玩验收（GM-Non-PK）

保留原 gm-* 流程与 PLAN/GAP 权威，不引入 planner-kernal、任务数据库或新的调度器。
命令不会自动生成游戏、安装依赖、发布或替用户批准。许可仍为 BUSL 1.1，来源见 FORK.md。
当前真实引擎验证环境是 Linux、Godot 4.6.3、Python 3.12.14；受控进程树执行目前限 POSIX。

## 环境与底层验证

依赖安装是独立、明确授权的准备操作，运行命令不会偷偷安装。已有 uv 时可执行：

```sh
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements-review.lock
.venv/bin/python -m pytest tests/ -q -m 'not network'
.venv/bin/ruff check .
GM_REAL_GODOT=1 .venv/bin/python -m pytest tests/integration/test_review_smoke.py -q
```

requirements-review.lock 固定实际验证过的依赖版本。真实引擎测试要求预装 Godot 4.6.3。
手动触发的 CI 配置使用预先准备的可信 Linux runner；本地运行不等于已跑托管 CI。

```sh
python tools/gm_review.py doctor --project /absolute/game --json
python tools/gm_review.py smoke --fixture one_room_loop --output /absolute/new-run --json
python tools/gm_review.py smoke --fixture one_room_loop --variant pause_input_leak --output /absolute/new-fault-run --json
```

doctor 复用原环境路径/版本探测，只读，不运行游戏。smoke 复制固定夹具，隔离导入缓存和
存档，执行真实引擎和断言，保留日志并检查输入漂移。已有输出目录拒绝覆盖。四个行为反例
使用同一套断言。夹具通过不代表生成质量、视觉、音频、真实设备或用户体验通过。

## 原流程上的正式验收

1. 原 gm-gdd/asset/build 和角色分工继续使用。PLAN 增加 Iteration Intent、Review Notes、
   Platform Commitments；用户在真实终端用 confirm-spec 确认当前约束。
2. check 创建固定源码副本，运行原 verify 与 evaluator 编写的 godot-e2e/pytest 测试。
   单独 --suite verify 或 --suite e2e 只作诊断，不能通过完整 gate。
3. Evaluator 保留原机制、Playable Unit、视觉及体验检查；若修改测试，必须重新 check。
   审查本次固定副本，缺画面/设备时如实阻塞。
4. 原 evaluation.json 增加当前 tag/run_id/spec_digest/source_digest/test_digest 和
   review_kind（self_review 或有审查者来源的 independent_review），保留原覆盖/视觉字段。
   bind-evaluation 校验并记录绑定 evaluate 事件，复用原 evaluation-runs 媒体归档。
   绑定流程不要再提前写旧的 plain evaluate 事件。
5. play --run 打开固定副本的 Godot 原生窗口，独立存档；进程完成不代表验收。无显示环境则
   BLOCKED。后续制作可继续，但旧副本不能批准新源码。
6. feedback --run --file 记录不可覆盖用户反馈并幂等进入 GAP；先复现再派发。用户否决不改写
   自动 approve。设计变更先确认 GDD/PLAN；错误测试交 evaluator；缺能力继续阻塞。
7. 原修复/重验完成后，真实用户用 resolve-feedback 确认已 verified 的 GAP 问题确实解决。
   decision --choice accept 对指定 run 和 PLAN 中所有必需 profile 作接受；changes_requested、
   design_change、defer 无须 reviewed-profile，均会使旧接受不再适用。
8. gate 与 finalize/seal_tag 复用同一锁内检查：当前输入、真实报告、原 evaluator 证据、用户
   决定及未解决反馈。源码/资产/测试/规范变化、缺证据、未完成任务或用户否决都会阻塞归档。

```sh
python tools/gm_review.py status --project /absolute/game --json
python tools/gm_review.py confirm-spec --project /absolute/game
python tools/gm_review.py check --project /absolute/game --json
python tools/gm_review.py bind-evaluation --project /absolute/game --run RUN-...
python tools/gm_review.py play --project /absolute/game --run RUN-...
python tools/gm_review.py decision --project /absolute/game --run RUN-... --choice changes_requested
python tools/gm_review.py gate --project /absolute/game --json
```

反馈文件示例（实际使用时必须填写真实用户原文和来源）：

```json
{"id":"FB01","mechanics":["v0.1.0-M1"],"platform":"Desktop","text":"用户原文","type":"experience","source_ref":"真实用户消息引用"}
```

类型支持 implementation、experience、design_change、test_error、capability。
source_ref 是审计来源，不是强身份认证。接受仅允许真实本地 TTY 输入；无交互时返回
needs_human，不能用 --actor=human、模型角色扮演或 CI 自动同意。单测里的合成协议证据
只在临时目录中验证程序分支，不是任何游戏或真人验收的实际成果。

## 摘要、恢复和边界

规格摘要包含明确 PLAN 规范章节及 GDD/DESIGN/SCENES/ASSETS/STRUCTURE，只排除纯进度
Task Status 与 Playable Unit 的 Evidence 列；未知模板/空提取会阻塞。源码摘要包含 dirty、
未跟踪资源、场景、addons 和项目配置；测试、runner、实际 Python 包版本和配置单独绑定。
副本中的规范文档与归一化配置也受漂移检测，不能只依赖只读文件权限。

忽略 Git/引擎缓存和运行结果，但显式引用被排除资源会阻塞。符号链接、凭据目录/文件、
未知配置键阻止快照；运行配置只复制已知非敏感标量，不复制任意注释或凭据。

run.lock 仅协调受控入口。中断/超时清理自有进程组；未知遗留写入者不会自动接管。
recover-lock 只在记录的本机 PID 均不存在且用户明确确认后移除锁，不自动重跑。
同权限外部编辑器可绕过工具，因此这是本地可信协作的防误用机制，不是安全沙箱、
强真人认证、跨主机一致性或多写入者协调。

退出码：PASS=0，真实断言 FAIL=1，缺依赖/必需跳过/零用例 BLOCKED=2，损坏/缺报告/矛盾/
超时 ERROR=3。只读 status 正常返回 0，不等于内容中的待验收项目已完成。

真实用户“制作→试玩否决→修复→重验→接受”仍需对应用户和真实游戏完成；不能从手工夹具
或合成单测推定。未满足 N05 产品门槛前，本实现不启动 N06 React 与 N07 可选设备扩展。

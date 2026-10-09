# 本机前后分离工作台

详细说明：[说明书入口](../docs/README.zh-CN.md) · [部署与维护](../docs/DEPLOYMENT-MANUAL.zh-CN.md) · [工作台用户操作](../docs/USER-MANUAL.zh-CN.md)。

前端是 `frontend/studio/` 的独立静态包；后端是本目录的 Python 服务。二者通过同源 `/api` 通信。项目、Git 仓库、session 权限和验证命令由后端持有，浏览器只提交概念、答案、表单编号和结果决定。

## 启动

在仓库根目录双击 `start-studio.command`，或运行：

```bash
.venv/bin/python -m backend.server --port 8765
```

打开 `http://127.0.0.1:8765/studio/`。正常停止时，在服务终端按 Ctrl+C；服务会请求取消当前制作、等待受管执行退出并关闭本机预览。异常退出或未确认停止的作业仍会受阻，需恢复后对账。服务仅监听 127.0.0.1；保留终端能查看启动状态。浏览器刷新后可恢复作业和已经确认的表单，重试沿用原表单编号。

Python 3.11 及以上。本机依赖已装入 `.venv/`，Godot 使用 `/Applications/Godot.app/Contents/MacOS/Godot`，Codex 使用已安装的 app-server。迁移到新机器时：

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
```

## 当前能力

仅支持一个受控 2D 收集挑战模板：WASD/方向键移动、收集获胜、倒计时失败、R 重试。三个可编辑参数是目标 1–8 个、时限 10–300 秒、速度 60–400 像素/秒。初步澄清是围绕此模板的结构化访谈，任意题材、关卡、额外机制与通用多模态策划仍需新适配器。超出范围会保留原意并阻塞，不会自动改写成受支持玩法。

PNG/JPEG/WebP 图片不超过 5 MiB，最多六张。用途可以是概念、风格、布局或素材输入。图片按服务分配的 ID 保存，并作为本机图片输入传给制作 session；当前模板仍使用程序图形，图片不会自动变成已制作美术资产。

新工程先确认初始化范围、单独执行并验证初始化，返回不可玩的准备基线；随后再确认绑定 GM 规格、PLAN、测试和 Git 基线的玩法表单。制作 session 只能修改规则 JSON。后端独立检查写入范围并运行 Godot。通过后返回候选；用户审阅并接受后，源版本、语义清单和运行报告作为完整快照一次切换。

制作工具的 `completed` 只说明模型回合结束。GM 规格批准与模板运行验证各有独立记录；模板验证不代表 GM 全流程认证、发行验收或已导出游戏。

制作 session 不能写 `.godot/` 来绕过范围检查；只有通过制作审计后启动的独立验证器可以产生引擎缓存。自定义 driver/verifier 仅允许在明确的测试模式中注入，正式启动固定使用原生 session 与独立验证 worker。

## 版本、恢复与边界

私有数据在 `.workbench/`：SQLite、图片、独立项目 Git 仓库、隔离制作 worktree 和候选证据。发布通过数据库指针切换，不覆盖原游戏源码。浏览器 IndexedDB 草稿按项目与发布版本隔离；新版本返回时，需要预览后显式重关联。

同一个项目同时只允许一个执行或待审阅作业。取消先请求停止，确认整个制作进程组消失后才解除独占。服务异常重启后，执行中作业进入 UNCERTAIN；“向服务对账”只核实原租约进程组是否消失。进程组仍存在、没有可信租约或无法观测时继续阻塞，不会盲目重投，也不会终止无关进程。缺失租约需本机操作者检查，可以保留受阻工程并在新项目重新开始。

默认是生产工作区，具体游戏批准必须来自实际用户工作台操作。自动测试使用单独 `--state-root` 和 `--test-data`；每个测试审批记录都保存 `testData=true`、`productionAuthorized=false`，即使修改注册配置也不能通过生产 GM gate。

旧版入口是 `/legacy/` 的只读静态页面。Velvet 的 HUD/title 已知源码差异仍受原锁保护，没有通过本次平台开发被默认为接受。这里不运行独立 SHA/MD5 校验，不生成美术，不导出或对外发布游戏。

## 验证

```bash
.venv/bin/python -m unittest discover -s backend/tests -p 'test*.py'
```

真实三 session 探针位于 `tools/run_workflow_probe.py`；它只可使用隔离测试存储。结果见 `evidence/workflow/integration/real-workflow-probe.json`。其中的接受与发布均为合成测试状态，真实用户体验验收是 NOT PERFORMED。

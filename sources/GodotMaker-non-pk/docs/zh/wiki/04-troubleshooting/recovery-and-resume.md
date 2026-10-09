# 恢复与继续

GodotMaker 的设计目标是：任何一个 `/gm-*` 命令跑完之后，你都可以随时停下来，之后再继续。这一页解释这套机制是怎么工作的，以及出了问题该怎么处理。

---

## 基本的恢复机制

每个 `/gm-*` 技能启动时都会先读两样东西：

1. **`.godotmaker/stage.jsonl`** — 一个只追加、不修改的角色完成日志。每一行格式大致是 `{"role": "build", "ts": "2026-04-27T10:00:00Z"}`。技能通过扫描这个文件来判断哪些角色已经跑过。
2. **关键输出文件** — 比如 `/gm-build` 会检查 `PLAN.md` 是否存在并读取任务状态；`/gm-fixgap` 会检查 `GAP.md`；`/gm-evaluate` 会检查 `.godotmaker/evaluation.json`。

如果某个角色已经完成（`stage.jsonl` 里有对应记录，且输出文件都在），技能会告诉你并推荐下一步命令。如果前置条件缺失，它会明确说需要先跑哪个角色。

你完全不需要记住上次做到哪一步——技能会自己从磁盘上的文件里判断。

---

## `current_role` 是干什么的

`.godotmaker/current_role` 是一个小文本文件，里面存着当前正在运行的角色名称（比如 `build`、`evaluate`）。每个 `/gm-*` 技能启动后做的第一件事就是把自己的角色名写进这个文件。

hook 系统在每次文件写入时都会读取 `current_role`，用来控制写入权限——比如，阻止 `/gm-build` 直接修改 `.gd` 文件（这类操作必须通过 Worker 子 Agent 来做），或者阻止 `/gm-evaluate` 去碰 `e2e/` 和 `.godotmaker/` 以外的东西。

当你开启一个新的 Claude Code 会话时，`session_start.py` 会清除 `current_role` 里残留的旧值。这很重要，因为上次崩溃的会话可能遗留了一个角色名，不清掉的话会导致下次恢复时应用了错误的权限规则。

---

## 恢复中断的 `/gm-build`

如果你在构建进行中关掉了 Claude Code：

1. 在游戏项目文件夹里打开一个新的 Claude Code 会话。
2. 运行 `/gm-build`。

技能会读取 `PLAN.md` 并逐一检查每个任务的状态列：

- `pending` — 还没开始，会被派发。
- `in_progress` — 会话挂掉时正在处理中，需要关注。
- `completed` — Worker 已完成，但 verifier/reviewer 还没跑。
- `verified` — 完全做完了，会跳过。

如果有任务卡在 `in_progress`，在运行 `/gm-build` 之前手动把它们改回 `pending`——否则技能可能误以为有 Worker 正在处理它们而跳过。

```bash
# Open PLAN.md in any text editor and change:
#   | in_progress | Task description |
# to:
#   | pending     | Task description |
```

然后运行 `/gm-build`。它会为 `pending` 的任务派发 Worker，并为那些 `completed` 但还没验证的任务跑一轮 verifier/reviewer。

---

## 恢复中断的 `/gm-fixgap`

`/gm-fixgap` 依赖位于项目根目录的 `GAP.md`，一次迭代进行时它就在那里。恢复逻辑如下：

- 如果 `GAP.md` 在项目根目录——说明 fixgap 正在进行中。运行 `/gm-fixgap` 会继续这次迭代。
- 如果项目根目录没有 `GAP.md`（它已被移动到 `.godotmaker/gaps/<n>/`）——说明上次 fixgap 已经完成。再次运行 `/gm-fixgap` 会从当前的 `evaluation.json` 开始一次新的迭代。

查看当前处于哪种状态：

```bash
ls GAP.md 2>/dev/null && echo "fixgap in progress" || echo "no active fixgap"
```

如果 fixgap 在任务中途被中断了，和处理 `/gm-build` 一样，把 `GAP.md` 里的 `in_progress` 改回 `pending`。

---

## 从头重新开始

如果项目真的乱掉了——文件缺失、`stage.jsonl` 里的记录前后矛盾、hook 把所有操作都拦住——先跑项目检查器，搞清楚现在是什么状态：

```bash
python tools/check_project.py <path-to-game>
```

它会列出缺失的必要文件、角色锁残留等常见问题，而且不会改动任何东西。

**删或重置之前：** 先做一个 git commit 或备份。大多数问题直接编辑 `PLAN.md` 或 `GAP.md` 就能解决，不需要推倒重来。

如果你决定只重跑某一个角色（而不是整个项目），最安全的做法是：

1. 从 `.godotmaker/stage.jsonl` 里删掉那个角色对应的那一行。
2. 删掉那个角色的输出文件（查 `.godotmaker/stage_schemas.json` 了解具体是哪些文件）。
3. 重新运行对应的 `/gm-*` 命令。

只有在代码库完全无法修复、也没有任何值得保留的代码时，才考虑全量重置（删掉 `src/`、`scenes/` 和 `stage.jsonl`）。这种情况非常少见。

---

## 重新运行已经跑过的角色

大多数角色都可以安全地重跑，少数有限制：

| 角色 | 可重跑？ | 备注 |
|------|---------|------|
| `/gm-scaffold` | 每个项目只能跑一次 | 用于创建 Godot 项目结构和初始 git 提交。在已有项目上再跑会和现有文件冲突，不要重跑。 |
| `/gm-gdd` | 可以 | 会重新访谈你并重写规划文档。每个新 tag 开始时用这个。 |
| `/gm-asset` | 可以 | 已存在的资源会跳过，只生成缺失的。 |
| `/gm-build` | 可以 | 从当前 `PLAN.md` 的状态继续。 |
| `/gm-verify` | 可以 | 机械检查，随时重跑都安全。 |
| `/gm-evaluate` | 可以 | 用最新结果覆盖 `evaluation.json`。 |
| `/gm-fixgap` | 可以 | 每次运行都会在 `.godotmaker/gaps/<n>/` 下创建一次新的迭代。 |
| `/gm-accept` | 可以 | 显示当前结果并再次询问确认。 |
| `/gm-finalize` | 每个 tag 一次 | 归档当前 tag 的工作文档并执行 `git tag <Tag>`。已封口的 tag 重跑会因 git tag 已存在而失败——如果 finalize 在封口前中断，可以再跑一次；如果想修改已封口的 tag，开一个新 tag。 |

`/gm-finalize` 完成后，下一个 tag 从 `/gm-gdd` 开始（不是 `/gm-scaffold`）。

---

## AI 明显跑偏了怎么办

正常情况下，hook 会拦截大多数违规操作——错误的文件写入会被阻断，跳步会被检测，格式不对的报告会被拒绝。但如果你发现情况不对（AI 在无视你的指令、往不该写的地方写东西，或者输出内容毫无逻辑）：

1. **停掉会话** — 关闭 Claude Code。
2. **跑项目检查器：**

   ```bash
   python tools/check_project.py <path-to-game>
   ```

3. **查看最近的指标日志** — `.godotmaker/` 目录里有带时间戳的事件日志：

   ```bash
   ls .godotmaker/metrics_*.jsonl
   ```

   打开最新的文件，找 `HOOK_BLOCK` 事件——这些记录显示了什么被拦截了以及原因。如果看到意外的拦截，说明角色状态可能不一致。

4. **清除 `current_role`**，如果它看起来是残留的旧值：

   ```bash
   echo "" > .godotmaker/current_role
   ```

5. **开一个新会话**，从最后一个干净的状态对应的 `/gm-*` 命令重新开始。

如果跨会话都反复出现同样的问题，检查一下 `.godotmaker/config.yaml` 里有没有影响行为的模型或设置覆盖项，并验证已安装的 GodotMaker 版本和仓库是否一致：

```bash
cat .godotmaker/version
cat <godotmaker-repo>/VERSION
```

如果版本不匹配，用 `python tools/publish.py <target>` 重新发布。

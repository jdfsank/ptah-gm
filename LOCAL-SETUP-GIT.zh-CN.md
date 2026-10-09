# Godot 安装与 Git 校验迁移

日期：2026-10-09。

Godot 已从 `/Users/typ/Desktop/pj_timekettle/engine/Godot.app` 安装到 `/Applications/Godot.app`。实际 CLI 输出为 `4.6.3.stable.official.7d41c59c4`，与交付包记录的引擎版本一致。

## 本机入口

- App：`/Applications/Godot.app`。
- 原生执行文件：`/Applications/Godot.app/Contents/MacOS/Godot`。
- CLI：`/Users/typ/.local/bin/godot`，链接到上述执行文件。
- shell 导出 `GODOT_BIN`、`GODOT_PATH`；`~/.local/bin` 加入 PATH。
- 已更新 `~/.bash_profile`、`~/.bashrc`、`~/.zprofile`，已有 Bash 配置保存在对应 `.codex-godot-backup-20261009` 文件。
- 游戏 `.agents/godotmaker.yaml` 已改用安装后的绝对路径。

新 Bash 和 Zsh 登录会话均已实际验证：

```sh
godot --version
```

## Git 仓库与检查点

此交付根目录已建立 Git 仓库，分支为 `main`。`handoff-v6-original` 保存从原始交付归档恢复的源码基线，不包含并行开发中的修改；不是恢复了未交付的游戏 Git 历史。

迁移完成版本保存为 `local-git-validation-v1` 检查点。可以在此目录查看此次改动：

```sh
git diff handoff-v6-original..local-git-validation-v1 --stat
git status --short
```

## 活动校验方式

构建提交、规范/测试基线、正式运行报告、Evaluator 绑定、阶段事件和标签归档，已改用 Git 原生对象身份和逐文件差异比较。没有运行 SHA/MD5 校验命令，也不再调用原 SHA 实现。

共享工具为 `tools/git_baseline.py`；游戏内 `sources/velvet-eclipse/tools/git_baseline.py` 保存相同实现，使游戏独立复制后仍可运行。检查使用临时 index；当前用户 index 和已暂存内容不受影响。正式工作流要求实际工程位于已有提交的 Git 仓库内。

检查继续覆盖修改、新增、删除和执行权限变化，拒绝路径逃逸与符号链接；目标、逐文件范围、规范冻结、正式 run/report 身份、角色和人工确认门保留。Git 原生 object ID 用于 Git 管理，不等于恢复独立 SHA 校验步骤；这种检查同样不构成实时 OS 写入沙箱。

活动数据使用 `gitBlob`；历史名称 `spec_digest`、`source_digest`、`test_digest`、`report_digests` 为兼容协议保留，但其值为 `git:...` 身份。新运行元数据使用 `manifest.git` / `evaluation-binding.git`，旧 SHA 运行记录不能直接充当新的正式证据。

## 基线保护

前端 69 项源锁来自已有只读 HTML 证据的源文本，迁移时没有采用游戏当前文本来静默刷新已审版本。67 项与当前游戏逐字节一致；`scripts/ui/hud.gd` 和 `scripts/ui/title_screen.gd` 的两处差异仍被阻止。语义 source refs、sourceManifest 和 adapter baseline 已同步使用同一 Git 身份。

部署能力锁改为 `version_scheme: git`，逐文件绑定 48 个实际工具/技能，包含游戏本地 Git 工具。新版源提取器继续要求人工审阅后的显式基线更新。

迁移语义模型 schema 时发现原交付两个 schema 副本缺少最末根对象闭合括号；已同时修正并验证 JSON 可解析。Python 3.14 回归发现的 SQLite 连接未关闭问题也已修复，事务提交/回滚逻辑保持。

## 验证与尚未完成事项

- Bridge 25 项、GM contract 56 项、Git 基线 6 项、runtime 辅助工具 4 项：共 91 项 Python 测试通过。
- JavaScript 语法、JSON/schema 解析、原 index 字节保持、48 项能力锁以及 69 项源引用一致性检查通过。
- 本机 doctor 能定位 Godot 4.6.3；当前 Python 尚未安装 pytest / godot_e2e。前端 jsdom 依赖也未安装，未重跑完整 DOM/浏览器矩阵。
- 没有运行游戏完整构建、正式 check、浏览器验收、导出或模型闭环。真实 target mapping、两处源差异审阅及按需人工门仍待后续工作。

原交付 ZIP 和 SHA 清单保留用于历史溯源。此本地政策替代旧交付文档中将 SHA 检查列为构建前置步骤的要求；其余真实验收和角色边界继续适用。

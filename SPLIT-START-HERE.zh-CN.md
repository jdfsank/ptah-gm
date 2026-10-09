# 拆分交付 从这里开始

共四个普通 ZIP，每个小于 40 MiB，可以分别解压，不是需要特定拼接软件的多卷压缩包。

请将四个 ZIP 下载到同一位置，分别解压到同一个新建父目录。它们都包含同名根目录 local-codex-handoff-20261008-compact，内容按职责分开，没有互相覆盖的文件。不要每包解到不同父目录，也不要解到现有用户工程。若解压器自动再加一层 ZIP 文件名目录，请把四包内的同名根目录合并到同一新目录，勿替换已有工程。

1. part1-start-frontend-history：先读本说明，然后 START-HERE.zh-CN.md；COPY-TO-CODEX.txt 可复制给本地 Codex。包含前端、Git历史、全部交接文档/清单/脚本。
2. part2-gm-framework：实际 GM 框架 ZIP，保留代码、技能、测试和许可证，只省去四个文档演示 GIF。
3. part3-godot-game-source：实际 Godot 游戏完整源 ZIP，保留所有必要游戏资源和依赖源码。
4. part4-reference-inputs：8张原始参考图。

四包解压齐后在共享根目录运行 python3 tools/verify-package.py，原精简完整包的 209 项文件都应通过。新增加的 SPLIT-START-HERE.zh-CN.md 和 SPLIT-DELIVERY.json 是拆分说明，原验证器会提示它们为额外本地文件，这是预期现象。再运行 python3 tools/unpack-sources.py，核验并解出两份源代码；脚本拒绝覆盖已有 sources 目录。

SPLIT-DELIVERY.json 列明每包用途及原内容逐文件 SHA。随附件单独提供的 SPLIT-ZIP-SHA256SUMS.txt 列出全部四个 ZIP 的 SHA-256；为避免自引用，ZIP 自身摘要不嵌入自己。可用 macOS shasum -a 256 或 Linux sha256sum 比对。

全部原精简包文件逐字保留，没有重新实现功能或发布 Site。两处 source-lock 差异、run_verify后续修复、workbench-targets.json缺失及真实闭环未验证等警示仍完整适用，先读 START-HERE。不要将已带 dist 的 demo 收据当真实执行结果。

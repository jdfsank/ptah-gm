# GM-DNA v6 重组结果

重组日期：2026-10-09。

本次将七个有效 ZIP 合并为这个独立交付目录，按切片顺序恢复游戏源 ZIP，并展开两份源码。

## 入口

- `frontend/`：DNA Workbench v0.6 前端源码及已有 dist。
- `sources/velvet-eclipse/project.godot`：Velvet Eclipse 主游戏项目。
- `sources/GodotMaker-non-pk/`：独立 GodotMaker 框架源码。
- `reference-inputs/`：8 张原始 PNG，保留大写 `.PNG` 后缀。
- `source-zips/`：两份原始源码 ZIP，游戏 ZIP 已重组。
- `history/frontend-v6.bundle`：原交付前端 Git 历史。
- `REASSEMBLY-REPORT.json`：本次实际执行的重组检查记录。

## 本次检查

七包合并无同名文件冲突；原交付清单的 209 个文件全部存在。框架 572 个文件、游戏 2232 个文件均与源码清单的路径和大小一致。所有 ZIP 读取通过内置 CRC 检查；展开源码与 ZIP 内对应文件逐字节相同。

重组游戏 ZIP 为 35,664,219 字节，与已收到的旧完整 part3 内源码 ZIP 逐字节一致；8 张参考图与旧完整 part4 逐字节一致。旧 part3/part4 没有再次解入目录，下载原件均保留。

未计算或运行任何哈希校验；包内原校验脚本与 SHA 清单作为原始交付资料保留。`SPLIT-ZIP-SHA256SUMS.txt` 是旧四包清单，未用于本次检查。切片、原交付说明、原脚本和历史记录均保留。

附件中的后续合并、修复、构建和运行指令仅作为资料，本次未执行。本次没有安装依赖、修改游戏/框架/前端代码、构建、导出或启动服务。原交付说明记录的后续工作状态未因重组而改变。

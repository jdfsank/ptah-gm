# godotmaker.yaml

`godotmaker.yaml` 位于每个生成的项目的 `.claude/godotmaker.yaml`。它告诉 GodotMaker 你的机器信息——主要是 Godot 可执行文件的路径——因此不同机器可以有各自不同的配置，而不会影响项目文件本身。

如果你在两台电脑上共同开发同一个项目（或者与其他开发者协作），每台机器会有自己独立的这个文件副本。项目文件保持不变，只有这一个文件因机器而异。

## 文件内容

目前该文件只有一个字段：

**`godot_path`** — 本机 Godot 4 可执行文件的完整路径。GodotMaker 在需要运行 Godot 时都会用到这个路径：编译脚本、运行单元测试、截取截图。

| 平台 | 典型值 |
|---|---|
| Windows | `"C:/Godot/Godot_v4.4-stable_win64.exe"` |
| macOS | `"/Applications/Godot.app/Contents/MacOS/Godot"` |
| Linux | `"/usr/local/bin/godot4"` |

如果 Godot 已经加入了系统 PATH，可以直接填写 `"godot"`，省略完整路径。

一个最简配置文件如下：

```yaml
# Host-specific tool paths -- not committed to git
godot_path: "C:/Godot/Godot_v4.4-stable_win64.exe"
```

## 什么时候需要修改

在以下情况下需要修改这个文件：

- 你把 Godot 安装目录移到了别的位置。
- 你升级了 Godot，可执行文件名称发生了变化（例如 `_v4.4` → `_v4.5`）。
- 你第一次在另一台机器上打开这个项目，而那台机器上的路径与第一台不同。

## 什么时候不应该修改

不要通过修改这个文件来调整项目行为，例如使用哪个 AI 模型、调用哪个图像生成器等。这些设置属于 `.godotmaker/config.yaml`——详见[项目配置](project-config.md)。

## 文件是怎么创建的

第一次运行 `python tools/publish.py <project>` 时，发布脚本会检查 `.claude/godotmaker.yaml` 是否已存在。如果不存在，它会问你一个问题：

```
No godotmaker.yaml found. Let's create one.
Enter the full path to your Godot executable
  (e.g. C:/path/to/Godot_v4.4-stable_win64.exe)
godot_path: _
```

你输入的路径在写入文件之前会被验证——publish 会运行 `<godot_path> --version`，根据结果有三种处理：

- **验证通过**——命令以 return code 0 正常退出。stdout 上打印的内容会作为"检测到的版本"反显（如果它一声不吭，会显示为 `?`——包装脚本和沙箱运行器有时会吞掉输出，这种情况也**故意**算通过）。publish 写文件并继续。
- **空输入或路径无效**——publish 打印错误（可执行文件不存在、非零退出、超时）并重新询问。最多 5 次机会，超过则放弃，不写文件。
- **主动中断**（Ctrl+C / Ctrl+D）——publish 打印"aborted"提示并不创建文件；之后再运行一次 publish 就可以重新设置。

如果 Godot 已经在 PATH 里，你仍然可以直接填 `"godot"`——同样会被验证（验证器实际执行 `godot --version`），只有真的能解析并跑起来才会写入。

只有在某次 publish 拿到了验证通过的路径之后，文件才会被创建。之后每次发布都不会覆盖这个文件——你的路径永远不会被自动更新。

## 配置错误会怎样

如果 `godot_path` 指向的可执行文件不存在或版本不对，大多数需要调用 Godot 的 `/gm-*` 命令都会因路径错误而失败。建议先运行 `python tools/check_env.py`——它会读取这个文件，尝试运行 Godot，并在你开始构建之前明确告知哪里出了问题。详见 [check-env](../05-tools/check-env.md)。

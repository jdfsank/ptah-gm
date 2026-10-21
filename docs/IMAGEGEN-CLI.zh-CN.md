# 独立 ImageGen CLI

`tools/imagegen_cli.py` 是独立的提示词到图片工具。输入为 prompt、文件名、输出目录、尺寸和质量；输出为图片路径、提示词记录和日志路径。模块不读取项目数据库，不理解策划/制作阶段，不处理审批，不导入图片，也不调用 Godot。视觉策划、概念探索和制作素材都可以复用同一个入口。

调用原有、不可修改的 `~/.codex/skills/.system/imagegen/scripts/image_gen.py`，固定默认模型 `gpt-image-2`。认证通过当前操作员环境的 `OPENAI_API_KEY`，SDK 可读取 `OPENAI_BASE_URL`。凭据不会写进输出记录或提供给托管策划/制作 session。CLI 的原始错误保存在权限为 0600 的操作员日志中。

安装可选依赖：

```bash
uv pip install --python .venv/bin/python -r tools/imagegen-requirements.txt
```

独立使用，无需启动工作台：

```bash
.venv/bin/python -m tools.imagegen_cli \
  --prompt '俯视赌场房间的视觉策划概念图，无文字' \
  --output-dir output/imagegen/casino-concept-v1 \
  --filename concept.png
```

输出目录必须是新目录；默认不覆盖已有文件。添加 `--dry-run` 只校验请求，不调用图片 API。`--prompt-file` 接收 UTF-8 提示词；`--input` 接收 JSON 数组：

```json
[
  {"prompt": "第一个独立图像需求", "filename": "first.png"},
  {"prompt": "第二个独立图像需求", "filename": "second.png"}
]
```

Python 接口同样独立：

```python
from tools.imagegen_cli import generate_images

result = generate_images(
    [{"prompt": "视觉策划概念图", "filename": "concept.png"}],
    output_dir="output/imagegen/concept-v2",
    size="1536x1024",
    quality="medium",
)
```

目前返回 PNG；`gpt-image-2` 没有透明背景参数。图片生成本身不验证动画网格、裁切、跨图角色一致性或游戏内效果。

# 工作台适配层

`tools/studio_imagegen.py` 和 `backend/imagegen_assets.py` 处理项目相关工作，单向调用上述工具。独立工具不依赖这些适配模块。

操作员从 READY/FROZEN 完整方案提取缺失的 PNG 绑定和对象描述，生成后逐张检查 PNG。只有整批成功才形成包含方案、提示词、图片和 Git 版本的素材包。数据库只读操作用于提取方案；导入通过后端持久命令 `proposal.assets.attach`，不直接改写数据库。

```bash
.venv/bin/python -m tools.studio_imagegen \
  --state-root /private/tmp/studio-ui-kimi-normal-mflp3xvk \
  --proposal-id proposal-bb709536d36e43afa50c8715ea661f22 \
  --url http://127.0.0.1:8795 \
  --attach
```

可先省略 `--attach` 检查图片，之后通过 `--bundle-id imagegen-... --attach` 导入同一个已生成素材包，避免重复 API 调用。生成记录位于 `<state-root>/imagegen/bundles/<bundle-id>/manifest.json`；最终 PNG 位于该目录的 `assets/`，中间请求及私有日志在 `<state-root>/imagegen/tmp/`。

导入建立新的 READY 修订并更新 GM 规格；原冻结表单、批准、失败作业和隔离工程保留。工作台完整审阅内容显示素材包、提示词和图片。用户在新修订确认后，受信准备器将精确已审阅图片复制进制作输入 Git 提交。托管制作 session 只编写代码和文本资源，不持有 ImageGen 认证。已审阅图片受到保护，缺失图片、脏素材包、错误项目/修订和 PNG 解码失败均不能启动制作。

历史封存失败显示为 `PRODUCTION_SEAL_FAILED`：制作回合完成，封存失败，独立验证尚未开始。素材包生成成功不等于游戏已验证或可发布。

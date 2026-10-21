"""Read static Godot texture references without loading or executing a project.

Only the image, AtlasTexture and SpriteFrames forms needed for a source preview
are supported. Unknown resource expressions remain unavailable instead of being
evaluated or replaced with a guessed thumbnail.
"""
from __future__ import annotations

import io
import re
from pathlib import PurePosixPath

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def resource_path(value):
    path = value.removeprefix("res://") if isinstance(value, str) else ""
    if not path or path.startswith("/") or "\\" in path or any(p in {"", ".", ".."} for p in path.split("/")):
        raise ValueError("资源路径不是工程内的安全路径。")
    return path


def _quoted_property(text, name):
    match = re.search(r'"' + re.escape(name) + r'"\s*:\s*&?"([^"\\]*)"', text)
    return match.group(1) if match else None


def _blocks(text, opening="{", closing="}"):
    """Find outer blocks, respecting strings and nested arrays/dictionaries."""
    depth, start, quoted, escaped = 0, None, False, False
    for i, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == opening:
            if depth == 0:
                start = i
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]
            if depth < 0:
                raise ValueError("资源列表格式无法预览。")
    if quoted or depth:
        raise ValueError("资源列表不完整。")


def describe_image(obj, read):
    """Resolve a bound image or the first source frame; read uses one Git ref."""
    preview = obj.get("workbench", {}).get("preview", {})
    bindings = obj.get("sourceBindings", [])
    declared = preview.get("resourcePath")
    if not declared:
        path = preview.get("imagePath") or next((p for p in bindings if PurePosixPath(p).suffix.lower() in IMAGE_TYPES), None)
        if not path or path not in bindings:
            raise ValueError("此目标没有绑定可用图片或可读取的图集 / 剪辑资源。")
        path = resource_path(path)
        if PurePosixPath(path).suffix.lower() not in IMAGE_TYPES:
            raise ValueError("绑定资源不是支持的静态图片。")
        return {"imagePath": path}
    path = resource_path(declared)
    if path not in bindings or not path.endswith(".tres"):
        raise ValueError("图集 / 剪辑必须引用此目标绑定的 .tres 资源。")
    text = read(path, 250_000).decode("utf-8")
    sections = re.split(r"(?m)^\[([^\n]+)\]\s*\n?", text)
    header = re.search(r'\[gd_resource\s+type="([^"]+)"', text)
    if not header or header.group(1) not in {"AtlasTexture", "SpriteFrames"}:
        raise ValueError("当前只支持 AtlasTexture 和 SpriteFrames 的静态来源预览。")
    external, subresources, body = {}, {}, ""
    for i in range(1, len(sections), 2):
        attrs, content = sections[i], sections[i + 1]
        identity = re.search(r'\bid="([^"\\]+)"', attrs)
        if attrs.startswith("ext_resource ") and identity:
            target = re.search(r'\bpath="([^"\\]+)"', attrs)
            if target:
                external[identity.group(1)] = resource_path(target.group(1))
        elif attrs.startswith("sub_resource ") and identity:
            subresources[identity.group(1)] = (attrs, content)
        elif attrs == "resource":
            body = content

    def texture(expression, nested=0):
        if nested > 4:
            raise ValueError("嵌套纹理过深，无法静态预览。")
        ref = re.fullmatch(r'(ExtResource|SubResource)\("([^"\\]+)"\)', expression.strip())
        if not ref:
            raise ValueError("此纹理表达式无法静态预览。")
        kind, identity = ref.groups()
        if kind == "ExtResource":
            target = external.get(identity)
            if not target or PurePosixPath(target).suffix.lower() not in IMAGE_TYPES:
                raise ValueError("首帧引用没有可用的静态图片绑定。")
            return {"imagePath": target}
        attrs, content = subresources.get(identity, ("", ""))
        if 'type="AtlasTexture"' not in attrs:
            raise ValueError("首帧子资源不是 AtlasTexture。")
        return atlas(content, nested + 1)

    def atlas(content, nested=0):
        reference = re.search(r'(?m)^atlas\s*=\s*((?:ExtResource|SubResource)\("[^"\\]+"\))\s*$', content)
        region = re.search(r'(?m)^region\s*=\s*Rect2\(([^)]+)\)', content)
        if not reference or not region:
            raise ValueError("图集未提供可读取的纹理和区域。")
        parts = [float(x.strip()) for x in region.group(1).split(",")]
        if len(parts) != 4 or any(not x.is_integer() for x in parts) or min(parts[:2]) < 0 or min(parts[2:]) <= 0:
            raise ValueError("图集区域必须是有效的整像素范围。")
        result = texture(reference.group(1), nested)
        if "region" in result:
            raise ValueError("嵌套图集区域暂不支持静态裁切。")
        return {**result, "region": [int(x) for x in parts]}

    if header.group(1) == "AtlasTexture":
        if preview.get("clipName"):
            raise ValueError("AtlasTexture 没有帧动画剪辑。")
        return {**atlas(body), "resourcePath": path}
    animations = re.search(r'(?m)^animations\s*=\s*(\[.*)', body, re.S)
    if not animations:
        raise ValueError("SpriteFrames 未提供动画列表。")
    clips = list(_blocks(animations.group(1)))
    selected = next((c for c in clips if _quoted_property(c, "name") == preview.get("clipName")), None) if preview.get("clipName") else next(iter(clips), None)
    if not selected:
        raise ValueError("此源版本没有指定的剪辑。")
    frames = re.search(r'"frames"\s*:\s*\[', selected)
    if not frames:
        raise ValueError("此剪辑没有帧列表。")
    frame_array = next(_blocks(selected[frames.end() - 1:], "[", "]"), "[]")
    frame_items = list(_blocks(frame_array))
    references = [re.search(r'"texture"\s*:\s*((?:ExtResource|SubResource)\("[^"\\]+"\))', f) for f in frame_items]
    if not references or references[0] is None:
        raise ValueError("此剪辑首帧为空或使用不支持的纹理表达式。")
    speed = re.search(r'"speed"\s*:\s*([0-9]+(?:\.[0-9]+)?)', selected)
    return {**texture(references[0].group(1)), "resourcePath": path,
            "clipName": _quoted_property(selected, "name"), "frameCount": len(frame_items),
            **({"fps": float(speed.group(1))} if speed else {})}


def preview_bytes(description, read):
    path = description["imagePath"]
    data = read(path, 5_000_000)
    mime = IMAGE_TYPES[PurePosixPath(path).suffix.lower()]
    if "region" not in description:
        return data, mime
    from PIL import Image
    x, y, width, height = description["region"]
    with Image.open(io.BytesIO(data)) as image:
        if x + width > image.width or y + height > image.height:
            raise ValueError("图集区域超出此源图片的实际尺寸。")
        result = io.BytesIO()
        image.crop((x, y, x + width, y + height)).save(result, format="PNG")
    return result.getvalue(), "image/png"

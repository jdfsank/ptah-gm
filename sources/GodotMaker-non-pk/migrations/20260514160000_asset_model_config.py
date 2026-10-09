"""Add configurable asset-generation model defaults."""
from pathlib import Path


DEFAULTS = {
    "vqa_model": "native",
    "vqa_fallback_model": "native",
    "asset_image_model": "native",
    "asset_video_model": "none",
}


def _parse_scalar_keys(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t")):
            continue
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def migrate(target: Path) -> None:
    config_path = target / ".godotmaker" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    values = _parse_scalar_keys(text)
    defaults = dict(DEFAULTS)

    changed = False
    lines = text.splitlines()
    if values.get("vqa_model") == "gemini-3-flash":
        lines = [
            "vqa_model: gemini:gemini-2.5-flash"
            if line.strip().startswith("vqa_model:")
            else line
            for line in lines
        ]
        changed = True
        values["vqa_model"] = "gemini:gemini-2.5-flash"
    elif (
        values.get("vqa_model")
        and ":" not in values["vqa_model"]
        and values["vqa_model"] not in {"native", "codex", "gemini", "openai"}
    ):
        lines = [
            f"vqa_model: gemini:{values['vqa_model']}"
            if line.strip().startswith("vqa_model:")
            else line
            for line in lines
        ]
        changed = True
        values["vqa_model"] = f"gemini:{values['vqa_model']}"

    if "asset_image_model" not in values and values.get("asset_image_provider"):
        provider = values["asset_image_provider"]
        if provider == "gemini":
            defaults["asset_image_model"] = (
                f"gemini:{values.get('gemini_image_model') or 'gemini-3.1-flash-image-preview'}"
            )
        elif provider == "grok":
            defaults["asset_image_model"] = (
                f"grok:{values.get('grok_image_model') or 'grok-imagine-image'}"
            )
        else:
            defaults["asset_image_model"] = provider

    if "asset_video_model" not in values and values.get("grok_video_model"):
        defaults["asset_video_model"] = f"grok:{values['grok_video_model']}"

    missing = [key for key in defaults if key not in values]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([
            "# Asset generation defaults",
            "# API-backed values are provider-prefixed. native is handled by the active agent runtime.",
            "# asset_video_model may be none when video generation is not needed.",
        ])
        for key in missing:
            lines.append(f"{key}: {defaults[key]}")
        changed = True

    if changed:
        config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print("  Updated .godotmaker/config.yaml asset model defaults")
    else:
        print("  .godotmaker/config.yaml asset model defaults already present")

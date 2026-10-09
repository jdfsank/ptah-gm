"""Tests for migrations/20260514160000_asset_model_config.py.

Migration adds project-level asset generation defaults and corrects only the
known-bad legacy VQA default. User-provided model values must be preserved.
"""
import importlib.util
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "20260514160000_asset_model_config.py"
)


@pytest.fixture
def migration_module():
    spec = importlib.util.spec_from_file_location("asset_model_config", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adds_missing_asset_model_defaults(migration_module, tmp_path):
    config = tmp_path / ".godotmaker" / "config.yaml"
    config.parent.mkdir()
    config.write_text("worker_model: opus\n", encoding="utf-8")

    migration_module.migrate(tmp_path)

    text = config.read_text(encoding="utf-8")
    assert "asset_image_model: native" in text
    assert "asset_video_model: none" in text
    assert "vqa_model: native" in text
    assert "vqa_fallback_model: native" in text


def test_replaces_only_old_invalid_vqa_default(migration_module, tmp_path):
    config = tmp_path / ".godotmaker" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "vqa_model: gemini-3-flash\n"
        "asset_image_provider: gemini\n"
        "gemini_image_model: custom-gemini-image\n"
        "grok_video_model: custom-grok-video\n",
        encoding="utf-8",
    )

    migration_module.migrate(tmp_path)

    text = config.read_text(encoding="utf-8")
    assert "vqa_model: gemini:gemini-2.5-flash" in text
    assert "asset_image_model: gemini:custom-gemini-image" in text
    assert "asset_video_model: grok:custom-grok-video" in text
    assert "gemini_image_model: custom-gemini-image" in text


def test_preserves_none_video_selector(migration_module, tmp_path):
    config = tmp_path / ".godotmaker" / "config.yaml"
    config.parent.mkdir()
    config.write_text("asset_video_model: none\n", encoding="utf-8")

    migration_module.migrate(tmp_path)

    text = config.read_text(encoding="utf-8")
    assert "asset_video_model: none" in text
    assert "asset_video_model: grok:" not in text


def test_preserves_codex_vqa_selector(migration_module, tmp_path):
    config = tmp_path / ".godotmaker" / "config.yaml"
    config.parent.mkdir()
    config.write_text("vqa_model: codex\n", encoding="utf-8")

    migration_module.migrate(tmp_path)

    text = config.read_text(encoding="utf-8")
    assert "vqa_model: codex" in text
    assert "vqa_model: gemini:codex" not in text


def test_is_idempotent(migration_module, tmp_path):
    config = tmp_path / ".godotmaker" / "config.yaml"
    config.parent.mkdir()
    config.write_text("worker_model: opus\n", encoding="utf-8")

    migration_module.migrate(tmp_path)
    once = config.read_text(encoding="utf-8")
    migration_module.migrate(tmp_path)

    assert config.read_text(encoding="utf-8") == once

"""Tests for session_start.py hook."""
import json
import os
import pytest
import tempfile
from .helpers import run_hook, cleanup_metrics

HOOK = "session_start.py"


@pytest.fixture(autouse=True)
def clean():
    yield
    cleanup_metrics()


@pytest.fixture
def project_dir():
    original = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(original)


class TestSessionStart:
    def test_clears_current_metrics(self, project_dir):
        # Create pre-existing current metrics
        os.makedirs(".godotmaker", exist_ok=True)
        with open(".godotmaker/metrics_current.jsonl", "w") as f:
            f.write('{"event": "old_event"}\n')

        _, code, _ = run_hook(HOOK, {})
        assert code == 0

        # Current should be empty
        with open(".godotmaker/metrics_current.jsonl") as f:
            assert f.read().strip() == ""

    def test_resets_state(self, project_dir):
        # Create pre-existing state with block count
        os.makedirs(".godotmaker", exist_ok=True)
        with open(".godotmaker/state.json", "w") as f:
            json.dump({"stop_block_count": 5}, f)

        _, code, _ = run_hook(HOOK, {})
        assert code == 0

        with open(".godotmaker/state.json") as f:
            state = json.load(f)
        assert state["stop_block_count"] == 0

    def test_never_blocks(self, project_dir):
        _, code, parsed = run_hook(HOOK, {})
        assert code == 0


class TestSessionStartTagBanner:
    """SessionStart should surface the current tag (from PLAN.md) in
    additionalContext so the lead agent knows which tag is active.
    """

    def _make_version_file(self):
        os.makedirs(".godotmaker", exist_ok=True)
        with open(".godotmaker/version", "w") as f:
            f.write("0.5.0")

    def test_no_version_file_no_banner(self, project_dir):
        # No version file → no additionalContext at all
        _, code, parsed = run_hook(HOOK, {})
        assert code == 0
        assert parsed is None or "additionalContext" not in parsed.get("hookSpecificOutput", {})

    def test_version_only_no_plan(self, project_dir):
        self._make_version_file()
        _, code, parsed = run_hook(HOOK, {})
        assert code == 0
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "v0.5.0" in ctx
        assert "no current tag" in ctx

    def test_version_with_plan_tag(self, project_dir):
        self._make_version_file()
        with open("PLAN.md", "w", encoding="utf-8") as f:
            f.write("# Plan\n\n**Tag:** v0.2.0\n")
        _, code, parsed = run_hook(HOOK, {})
        assert code == 0
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "v0.5.0" in ctx
        assert "v0.2.0" in ctx
        assert "tag:" in ctx

    def test_plan_without_tag_header_treated_as_no_tag(self, project_dir):
        self._make_version_file()
        with open("PLAN.md", "w", encoding="utf-8") as f:
            f.write("# Plan\n\nThis PLAN.md has no Tag header.\n")
        _, code, parsed = run_hook(HOOK, {})
        assert code == 0
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "no current tag" in ctx

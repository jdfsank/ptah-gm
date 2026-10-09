"""Tests for log_compaction.py — PreCompact hook."""
import json
import os
import tempfile

import pytest

from .helpers import cleanup_metrics, run_hook, write_current_role

HOOK = "log_compaction.py"


@pytest.fixture(autouse=True)
def clean():
    yield
    cleanup_metrics()


@pytest.fixture
def project_dir():
    original = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        os.makedirs(".godotmaker", exist_ok=True)
        yield tmpdir
        os.chdir(original)


def _read_events() -> list[dict]:
    path = os.path.join(".godotmaker", "metrics_current.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestPreCompactRecording:
    def test_manual_trigger_records_event(self, project_dir):
        write_current_role("build")
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "PreCompact",
            "session_id": "abc-123",
            "transcript_path": "/some/transcript.jsonl",
            "trigger": "manual",
        })
        assert code == 0
        events = _read_events()
        assert len(events) == 1
        assert events[0]["event"] == "compaction"
        assert events[0]["session_id"] == "abc-123"
        assert events[0]["trigger"] == "manual"
        assert events[0]["role"] == "build"

    def test_auto_trigger_records_event(self, project_dir):
        write_current_role("fixgap")
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "PreCompact",
            "session_id": "xyz-789",
            "trigger": "auto",
        })
        assert code == 0
        events = _read_events()
        assert events[0]["trigger"] == "auto"
        assert events[0]["role"] == "fixgap"

    def test_missing_current_role_records_empty(self, project_dir):
        """No `.godotmaker/current_role` → role is empty string, not crash."""
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "PreCompact",
            "session_id": "no-role",
            "trigger": "auto",
        })
        assert code == 0
        events = _read_events()
        assert events[0]["role"] == ""

    def test_missing_trigger_falls_back_to_unknown(self, project_dir):
        """Defensive: undocumented variants without `trigger` still record."""
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "PreCompact",
            "session_id": "no-trigger",
        })
        assert code == 0
        events = _read_events()
        assert events[0]["trigger"] == "unknown"


class TestNonCompactionEventsIgnored:
    def test_subagent_stop_ignored(self, project_dir):
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "SubagentStop",
            "session_id": "x",
        })
        assert code == 0
        assert _read_events() == []

    def test_session_start_ignored(self, project_dir):
        _, code, _ = run_hook(HOOK, {
            "hook_event_name": "SessionStart",
        })
        assert code == 0
        assert _read_events() == []

    def test_missing_event_name_ignored(self, project_dir):
        _, code, _ = run_hook(HOOK, {})
        assert code == 0
        assert _read_events() == []


class TestNeverBlocks:
    def test_bad_json_exits_zero(self, project_dir):
        import subprocess
        import sys
        from .helpers import HOOKS_DIR
        result = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, HOOK)],
            input="not json at all",
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert _read_events() == []

    def test_empty_stdin_exits_zero(self, project_dir):
        import subprocess
        import sys
        from .helpers import HOOKS_DIR
        result = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, HOOK)],
            input="",
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

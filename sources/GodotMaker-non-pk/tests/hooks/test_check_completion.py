"""Tests for check_completion.py hook (role-based pipeline)."""
import json
import os
import pytest
import tempfile
from .helpers import (
    run_hook, is_blocked, cleanup_metrics,
    write_current_role, write_metrics,
)

HOOK = "check_completion.py"


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


class TestRoleSkipping:
    """Roles other than build/fixgap should skip the diligence check."""

    @pytest.mark.parametrize("role",
                             ["scaffold", "gdd", "asset", "verify", "evaluate", "accept", "finalize"])
    def test_non_worker_roles_skipped(self, project_dir, role):
        write_current_role(role)
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
        ])
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed), f"role={role} must not be blocked"

    def test_no_role_set_skipped(self, project_dir):
        """No current_role file → skip (not in any pipeline session)."""
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed)


class TestSubagentIgnored:
    def test_subagent_stop_not_blocked(self, project_dir):
        write_current_role("build")
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "worker-123",
        })
        assert code == 0
        assert not is_blocked(parsed)


class TestBuildDiligence:
    def test_workers_without_verifiers_blocked(self, project_dir):
        write_current_role("build")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
            {"event": "subagent_start", "agent_id": "w2", "role": "worker"},
        ])
        _, _, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert is_blocked(parsed), "Build role with workers but no verifier must block"
        reason = parsed.get("reason", "").lower()
        assert "verifier" in reason

    def test_workers_without_reviewer_blocked(self, project_dir):
        """Build requires both verifier AND reviewer."""
        write_current_role("build")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
            {"event": "subagent_start", "agent_id": "v1", "role": "verifier"},
        ])
        _, _, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert is_blocked(parsed), "Build role with verifier but no reviewer must block"
        assert "reviewer" in parsed.get("reason", "").lower()

    def test_full_diligence_passes(self, project_dir):
        write_current_role("build")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
            {"event": "subagent_start", "agent_id": "v1", "role": "verifier"},
            {"event": "subagent_start", "agent_id": "r1", "role": "reviewer"},
        ])
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed), "Full diligence (worker+verifier+reviewer) must pass"

    def test_no_workers_dispatched_passes(self, project_dir):
        """If no workers were dispatched, no verifier needed."""
        write_current_role("build")
        write_metrics([])
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed)


class TestFixgapDiligence:
    """Fixgap requires both verifier AND reviewer (mirrors gm-fixgap Hard Rule 6)."""

    def test_workers_without_verifier_blocked(self, project_dir):
        write_current_role("fixgap")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
        ])
        _, _, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert is_blocked(parsed)
        assert "verifier" in parsed.get("reason", "").lower()

    def test_workers_without_reviewer_blocked(self, project_dir):
        write_current_role("fixgap")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
            {"event": "subagent_start", "agent_id": "v1", "role": "verifier"},
        ])
        _, _, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert is_blocked(parsed), "Fixgap with verifier but no reviewer must block"
        assert "reviewer" in parsed.get("reason", "").lower()

    def test_full_diligence_passes(self, project_dir):
        write_current_role("fixgap")
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
            {"event": "subagent_start", "agent_id": "v1", "role": "verifier"},
            {"event": "subagent_start", "agent_id": "r1", "role": "reviewer"},
        ])
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed)


class TestAntiDeadloop:
    def test_allows_after_limit_blocks(self, project_dir):
        write_current_role("build")
        os.makedirs(".godotmaker", exist_ok=True)
        with open(".godotmaker/state.json", "w") as f:
            json.dump({"stop_block_count": 5}, f)
        write_metrics([
            {"event": "subagent_start", "agent_id": "w1", "role": "worker"},
        ])
        _, code, parsed = run_hook(HOOK, {
            "hook_event_name": "Stop",
            "agent_id": "",
        })
        assert code == 0
        assert not is_blocked(parsed)

"""Production readiness boundary tests; engine integration is an isolated operator probe."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

from runners.agent import AgentRunner
from runners.common import LocalJournal, RunnerError
from runners.editor_mcp import (EditorMCPError, _drain_editor_output, _observe, _private_project_settings,
                                ensure_editor_mcp_ready)
from tools.godot_mcp_install import install_godot_mcp, verify_godot_mcp
from backend.tests.test_runner_setup_failure import SetupAPI


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        install_godot_mcp(self.project)
        self.evidence = self.root / "evidence"

    @contextmanager
    def engine_double(self, *, observe=None, stopped=True):
        with ExitStack() as stack:
            runtime = mock.Mock()
            runtime.home = self.root / "private-home"
            (runtime.home / "Library" / "Application Support").mkdir(parents=True)
            runtime.private_executable.return_value = Path("/bin/true")
            runtime.environment.return_value = {}
            stack.enter_context(mock.patch("runners.editor_mcp.GodotRuntime.create", return_value=runtime))
            stack.enter_context(mock.patch("runners.editor_mcp.subprocess.run",
                                           return_value=mock.Mock(stdout="4.6.3.stable", returncode=0)))
            stack.enter_context(mock.patch("runners.editor_mcp._editor_argv", return_value=["editor-double"]))
            process = mock.Mock(pid=987654)
            process.stdout = None
            process.poll.return_value = None
            spawn = stack.enter_context(mock.patch("runners.editor_mcp.subprocess.Popen", return_value=process))
            stack.enter_context(mock.patch("runners.editor_mcp.stop_process_group", return_value=stopped))
            stack.enter_context(mock.patch("runners.editor_mcp._observe", side_effect=observe or (
                lambda client, project: {"projectIdentityMatches": True, "toolCount": 74})))
            yield spawn

    def test_missing_disabled_and_conflicting_addons_block_before_engine_launch(self):
        for mode in ("missing", "disabled", "conflicting"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                project = root / "project"
                install_godot_mcp(project)
                if mode == "missing":
                    (project / "addons/godot_mcp/plugin.cfg").unlink()
                elif mode == "disabled":
                    settings = project / "project.godot"
                    settings.write_text(settings.read_text().replace(
                        'PackedStringArray("res://addons/godot_mcp/plugin.cfg")', 'PackedStringArray()'))
                else:
                    (project / "addons/godot_mcp/plugin.cfg").write_text("wrong version")
                with mock.patch("runners.editor_mcp.subprocess.Popen") as spawn:
                    with self.assertRaises(EditorMCPError) as raised:
                        ensure_editor_mcp_ready(project, root / "evidence")
                    spawn.assert_not_called()
                self.assertTrue(raised.exception.stopped)
                self.assertEqual(json.loads((root / "evidence/readiness.json").read_text())["status"], "FAIL")

    def test_success_preserves_source_and_removes_disposable_copy_after_confirmed_stop(self):
        before = {str(p.relative_to(self.project)): p.read_bytes()
                  for p in self.project.rglob("*") if p.is_file()}
        with self.engine_double() as spawn:
            report = ensure_editor_mcp_ready(self.project, self.evidence, timeout=1)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["editorStopped"])
        self.assertTrue(report["sourceUnchanged"])
        spawn.assert_called_once()
        self.assertFalse((self.evidence / "disposable").exists())
        self.assertEqual(before, {str(p.relative_to(self.project)): p.read_bytes()
                                 for p in self.project.rglob("*") if p.is_file()})

    def test_timeout_cancel_and_uncertain_stop_never_return_pass(self):
        cases = ("timeout", "cancel", "uncertain")
        # Each subcase has a separate runtime/evidence and no real engine.
        for mode in cases:
            with self.subTest(mode=mode), ExitStack() as stack:
                self.evidence = self.root / ("evidence-" + mode)
                for path in self.root.glob("private-home*"):
                    if path.is_dir():
                        shutil.rmtree(path)
                observe = (lambda *_: (_ for _ in ()).throw(OSError("not ready"))) if mode == "timeout" else None
                stack.enter_context(self.engine_double(observe=observe, stopped=mode != "uncertain"))
                event = threading.Event()
                calls = []

                def tick():
                    calls.append(1)
                    return mode == "cancel" and len(calls) >= 4

                with self.assertRaises(EditorMCPError) as raised:
                    ensure_editor_mcp_ready(self.project, self.evidence, timeout=0.01,
                                            cancel_event=event, tick=tick)
                report = raised.exception.report
                self.assertNotEqual(report["status"], "PASS")
                if mode == "uncertain":
                    self.assertFalse(raised.exception.stopped)
                    self.assertEqual(report["status"], "UNCERTAIN")
                    self.assertTrue((self.evidence / "disposable").exists())
                if mode == "cancel":
                    self.assertTrue(raised.exception.cancelled)

    def test_wrong_editor_identity_is_rejected_before_status_call(self):
        client = mock.Mock()
        client.request.return_value = {"running": True}
        client.rpc.side_effect = [{}, None, {"tools": [{"name": "project_info"}, {"name": "editor_status"}]}]
        client.call.return_value = {"project_path": str(self.root / "another-project")}
        with self.assertRaisesRegex(EditorMCPError, "identity"):
            _observe(client, self.project)
        self.assertEqual(client.call.call_args_list, [mock.call("project_info")])

    def test_report_write_failure_preserves_unconfirmed_editor_stop(self):
        original_write = Path.write_text
        writes = []

        def write(path, *args, **kwargs):
            if path.name == "readiness.pending":
                writes.append(path)
                if len(writes) == 3:
                    raise OSError("readiness volume is full")
            return original_write(path, *args, **kwargs)

        with self.engine_double(stopped=False), mock.patch.object(Path, "write_text", write):
            with self.assertRaises(EditorMCPError) as raised:
                ensure_editor_mcp_ready(self.project, self.evidence, timeout=1)
        self.assertFalse(raised.exception.stopped)
        self.assertEqual(raised.exception.code, "GODOT_MCP_UNCERTAIN")

    def test_editor_output_is_bounded_without_waiting_for_new_data(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
            process = mock.Mock(stdout=reader)
            log = self.root / "bounded.log"
            self.assertEqual(_drain_editor_output(process, log, 0), 0)
            writer.write(b"x" * 32)
            with mock.patch("runners.editor_mcp._MAX_EDITOR_LOG_BYTES", 16):
                with self.assertRaisesRegex(EditorMCPError, "bounded log limit"):
                    _drain_editor_output(process, log, 0)
            self.assertEqual(log.stat().st_size, 16)

    def test_source_drift_or_symlink_is_rejected(self):
        def drift(*_):
            (self.project / "project.godot").write_text("changed while editor was running")
            return {"projectIdentityMatches": True, "toolCount": 74}
        with self.engine_double(observe=drift), self.assertRaises(EditorMCPError) as raised:
            ensure_editor_mcp_ready(self.project, self.evidence, timeout=1)
        self.assertFalse(raised.exception.report["sourceUnchanged"])
        install_godot_mcp(self.root / "other-project")
        (self.root / "other-project/scripts").symlink_to(self.project, target_is_directory=True)
        with mock.patch("runners.editor_mcp.subprocess.Popen") as spawn:
            with self.assertRaises(EditorMCPError):
                ensure_editor_mcp_ready(self.root / "other-project", self.root / "other-evidence")
            spawn.assert_not_called()

    def test_settings_override_is_private_and_preserves_other_application_properties(self):
        original = ('config_version=5\n[application]\nconfig/name="Existing"\n'
                    'config/custom_user_dir="Old"\nrun/main_scene="res://main.tscn"\n')
        changed = _private_project_settings(original, "StudioMCP-Test")
        self.assertIn('run/main_scene="res://main.tscn"', changed)
        self.assertEqual(changed.count('config/name='), 1)
        self.assertEqual(changed.count('config/custom_user_dir='), 1)
        self.assertIn('config/name="StudioMCP-Test"', changed)
        self.assertEqual(verify_godot_mcp(self.project), 70)


class AgentReadinessBoundaryTests(unittest.TestCase):
    def test_gate_precedes_worker_and_preserves_cleanup_uncertainty_and_cancellation(self):
        for mode in ("pass", "fail", "uncertain", "cancel", "late-cancel", "lease-lost"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                class ReadinessAPI(SetupAPI):
                    def request(self, method, route, body=None):
                        if route.endswith("/heartbeat"):
                            if mode == "lease-lost":
                                raise RunnerError("backend unavailable before dispatch")
                            return {"cancelRequested": mode == "late-cancel"}
                        return super().request(method, route, body)
                api = ReadinessAPI()
                journal = LocalJournal(root / "journal.sqlite3")
                journal.bind_store("store-a")
                runner = AgentRunner(api, journal, root / "work", root / "artifacts", root / "protected")
                request = {"attemptId": "attempt-a", "projectId": "project-a", "taskKind": "produce"}
                workspace = root / "work/attempt-a"
                events = []

                def gate(*args, **kwargs):
                    events.append("gate")
                    if mode not in {"pass", "late-cancel", "lease-lost"}:
                        raise EditorMCPError("blocked", report={"editorStopped": mode != "uncertain",
                                                               "cancelled": mode == "cancel"})
                    return {"toolCount": 74, "editorStopped": True}

                def spawn(*args, **kwargs):
                    events.append("worker")
                    raise OSError("deliberate worker exec failure after gate")

                with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                     mock.patch.object(runner, "_prepare_claim", return_value=(
                         {}, workspace, {}, root / "temp", ["worker"], str(root), {})), \
                     mock.patch("runners.agent.ensure_editor_mcp_ready", side_effect=gate), \
                     mock.patch("runners.agent.subprocess.Popen", side_effect=spawn):
                    self.assertFalse(runner.accept_claim(request, "store-a"))
                self.assertEqual(events, ["gate", "worker"] if mode == "pass" else ["gate"])
                report = api.reports[-1]
                self.assertEqual(report["payload"]["stopped"], mode != "uncertain")
                self.assertEqual(report["type"], "stopped" if mode in {"cancel", "late-cancel"} else "failed")
                if mode in {"uncertain", "cancel", "late-cancel"}:
                    self.assertNotIn("launchPrevented", report["payload"])


if __name__ == "__main__":
    unittest.main()

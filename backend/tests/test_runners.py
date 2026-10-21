from __future__ import annotations

import json
import errno
import io
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from unittest import mock

from backend.role_evidence import REQUIRED_ROLE_CHECKS
from runners.common import (LocalJournal, RunnerError, RunnerHTTP, TransportError,
                            process_output_lines, protected_siblings, sandbox_probe,
                            sandboxed_run, service_loop, strict_json,
                            strict_sandbox_rules, stop_process_group)
from runners.agent import AgentRunner, _native_total_tokens, _soft_budget_reached
from runners.project import ProjectRunner, _source_unchanged
from runners.project_role_probe import _classify_expected_errors, _errors
from backend.source_preparation import UIDPreparationResult


class FakeAPI:
    def __init__(self):
        self.reports = []

    def request(self, method, route, body=None):
        self.reports.append(body)
        return {"schemaVersion": "studio.message.v1", "kind": "report_ack",
                **{key: body[key] for key in
                   ("storeId", "projectId", "attemptId", "runnerId", "reportId")},
                "disposition": "recorded"}


class RunnerTests(unittest.TestCase):
    def test_transport_backoff_is_bounded_and_success_resets_service_delay(self):
        from runners.common import retry_transport
        class Stop:
            def __init__(self):
                self.pauses = []
                self.done = False
            def is_set(self):
                return self.done
            def wait(self, delay):
                self.pauses.append(delay)
        stop = Stop()
        count = 0
        def operation():
            nonlocal count
            count += 1
            if count <= 9:
                raise TransportError('offline')
            return 'connected'
        with mock.patch('runners.common.random.uniform', return_value=1):
            self.assertEqual(retry_transport(operation, stop, delay=2), 'connected')
        self.assertEqual(stop.pauses, [2, 4, 8, 16, 32, 60, 60, 60, 60])
        stop.pauses.clear()
        count = 0
        def iteration():
            nonlocal count
            count += 1
            if count in {1, 2, 4}:
                raise TransportError('offline')
            if count == 5:
                stop.done = True
        with mock.patch('runners.common.random.uniform', return_value=1):
            service_loop(iteration, stop, delay=5)
        self.assertEqual(stop.pauses, [5, 10, 5, 5, 5])

    def test_busy_catalog_refresh_uses_real_observations_and_stops_after_failure(self):
        runner = object.__new__(AgentRunner)
        stop = threading.Event()
        calls = []
        def observe():
            calls.append(len(calls))
            if len(calls) == 1:
                raise RunnerError("temporary model/list failure")
            stop.set()
        runner.refresh_catalog = observe
        worker = threading.Thread(target=runner.catalog_refresh_loop, args=(stop, 0.01))
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 2)

    def test_project_role_error_allowlist_is_exact_and_count_bounded(self):
        path = "/private/tmp/project-role-probe/auth-canary.toml"
        occurrences = _errors(
            "\n".join([
                f"ERROR: Cannot open file '{path}'.",
                f"ERROR: Cannot open file '{path}'.",
                f"ERROR: Cannot open file '{path}' for write.",
                "ERROR: Connection to remote host failed!",
                "ERROR: Connection to remote host failed!",
                "SCRIPT ERROR: Unexpected parser failure.",
            ]),
            role="preview",
            command="ProjectRunner.preview",
        )
        classified = _classify_expected_errors(
            occurrences,
            {"auth": ((path,), 1)},
            network_limit=1,
        )
        self.assertEqual([item["expectedDenial"] for item in classified], [True, False, False, True, False, False])
        self.assertTrue(all(item["role"] == "preview" for item in classified))
        self.assertTrue(all(item["command"] == "ProjectRunner.preview" for item in classified))

    def test_project_registration_runs_fresh_probe_and_derives_capabilities_from_required_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / "state.sqlite3")

            class RegistrationAPI:
                def __init__(self):
                    self.request_body = None

                def request(self, method, route, body=None):
                    self.request_body = (method, route, body)
                    return {"registered": True, "runnerId": body["runnerId"]}

            api = RegistrationAPI()
            runner = ProjectRunner(api, journal, root / "artifacts", root / "protected",
                                   godot_path="/Applications/Godot.app/Contents/MacOS/Godot")
            roles = {
                capability: {"checks": {name: True for name in REQUIRED_ROLE_CHECKS[capability]}}
                for capability in ("verification-isolated-v1", "preview-isolated-v1")
            }
            roles["preview-isolated-v1"]["checks"]["preview_process_group_stopped"] = False
            evidence = {
                "schemaVersion": "studio.role-probe.v1",
                "runnerId": journal.runner_id,
                "runnerKind": "project",
                "probeId": "fresh-project-probe",
                "observedAt": datetime.now(timezone.utc).isoformat(
                    timespec="seconds").replace("+00:00", "Z"),
                "policy": "deny-default",
                "roles": roles,
                # This deliberately conflicts with the required checks above;
                # the registration must derive permissions from the checks.
                "verifiedCapabilities": ["preview-isolated-v1"],
            }

            with mock.patch("runners.project_role_probe.run_project_role_probe", return_value=evidence) as probe:
                result = runner.register()

            probe.assert_called_once_with(
                journal.runner_id, "/Applications/Godot.app/Contents/MacOS/Godot"
            )
            self.assertEqual(result["runnerId"], journal.runner_id)
            self.assertEqual(api.request_body[0:2], ("POST", "/internal/v1/register"))
            body = api.request_body[2]
            self.assertEqual(body["capabilities"], ["verification-isolated-v1"])
            self.assertIs(body["sandboxEvidence"], evidence)

    def test_project_registration_probe_exception_sends_empty_roles_to_clear_stale_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / "state.sqlite3")

            class RegistrationAPI:
                def __init__(self):
                    self.request_body = None

                def request(self, method, route, body=None):
                    self.request_body = body
                    return {"registered": True, "runnerId": body["runnerId"]}

            api = RegistrationAPI()
            runner = ProjectRunner(api, journal, root / "artifacts", root / "protected")
            with mock.patch("runners.project_role_probe.run_project_role_probe",
                            side_effect=RuntimeError("synthetic probe failure")):
                runner.register()

            self.assertEqual(api.request_body["capabilities"], [])
            evidence = api.request_body["sandboxEvidence"]
            self.assertEqual(evidence["probeFailureCode"], "RuntimeError")
            for capability, role in evidence["roles"].items():
                self.assertEqual(set(role["checks"]), set(REQUIRED_ROLE_CHECKS[capability]))
                self.assertTrue(all(value is False for value in role["checks"].values()))

    def test_group_shutdown_permission_error_never_proves_stop_and_can_recover(self):
        denied = PermissionError(errno.EPERM, "synthetic signal denial")
        gone = ProcessLookupError(errno.ESRCH, "synthetic observed group exit")
        with mock.patch("runners.common.os.killpg", side_effect=denied):
            self.assertFalse(stop_process_group(12345, grace_seconds=0))
        with mock.patch("runners.common.os.killpg", side_effect=[denied, denied, gone]):
            self.assertTrue(stop_process_group(12345, grace_seconds=0))

    def test_journal_keeps_attempt_identity_and_outbox_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "runner.sqlite3"
            first = LocalJournal(path)
            runner_id = first.runner_id
            request = {"attemptId": "attempt-a", "projectId": "project-a", "storeId": "store-a", "taskKind": "plan"}
            first.start_intent("attempt-a", request)
            identity = {"threadId": None, "turnId": None, "processId": 321,
                        "processGroupId": 321, "processStartTime": "2026-10-12T00:00:00Z"}
            first.set_identity("attempt-a", json.dumps(identity, sort_keys=True))
            report_id = first.add_report("attempt-a", "started", "store-a", "project-a",
                runner_id, {"nativeIdentity": identity, "startedAt": "2026-10-12T00:00:00Z",
                            "requestedProfile": None, "reportedProfile": None,
                            "threadStartReported": None, "turnStartAcknowledged": None,
                            "actualProfile": None})
            restarted = LocalJournal(path)
            self.assertEqual(restarted.runner_id, runner_id)
            self.assertEqual(restarted.pending(), 1)
            api = FakeAPI()
            self.assertEqual(restarted.flush(api), 1)
            self.assertEqual(api.reports[0]["reportId"], report_id)
            self.assertEqual(restarted.pending(), 0)

    def test_journal_rejects_reusing_attempt_for_different_request(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = LocalJournal(Path(directory) / "runner.sqlite3")
            journal.start_intent("attempt-a", {"projectId": "project-a"})
            with self.assertRaises(RunnerError):
                journal.start_intent("attempt-a", {"projectId": "project-b"})

    def test_evidence_only_stopped_report_reconciles_only_absent_original_process(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = LocalJournal(Path(directory) / "runner.sqlite3")
            journal.bind_store('store-a')
            journal.start_intent('attempt-a', {'projectId': 'project-a', 'taskKind': 'plan'})
            identity = {'threadId': 'thread-a', 'turnId': 'turn-a', 'processId': 54321,
                'processGroupId': 54321, 'processStartTime': '2026-10-12T00:00:00Z'}
            journal.set_identity('attempt-a', json.dumps(identity))
            journal.add_report('attempt-a', 'stopped', 'store-a', 'project-a', journal.runner_id,
                {'stopped': True, 'stopReason': 'cancelled', 'diagnosticRef': 'fixture'})

            class ReconcileAPI:
                def __init__(self): self.reconciliations = []
                def request(self, method, route, body):
                    if route.endswith('/reconcile'):
                        self.reconciliations.append(body)
                        return {'storeId': body['storeId'], 'attemptId': body['attemptId'], 'status': 'STOPPED'}
                    return {'schemaVersion': 'studio.message.v1', 'kind': 'report_ack',
                        **{key: body[key] for key in ('storeId', 'projectId', 'attemptId', 'runnerId', 'reportId')},
                        'disposition': 'evidence_only'}

            api = ReconcileAPI()
            absent = ProcessLookupError(errno.ESRCH, 'gone')
            with mock.patch('runners.common.os.kill', side_effect=absent), mock.patch('runners.common.os.killpg', side_effect=absent):
                journal.flush(api)
            self.assertEqual(len(api.reconciliations), 1)
            self.assertEqual(api.reconciliations[0]['nativeIdentity'], identity)
            self.assertIs(api.reconciliations[0]['stopped'], True)
            for uncertain in (None, PermissionError(errno.EPERM, 'cannot inspect')):
                api.reconciliations.clear()
                with mock.patch('runners.common.os.kill', side_effect=uncertain):
                    journal._reconcile_stopped(api, {'runnerId': journal.runner_id, 'storeId': 'store-a', 'attemptId': 'attempt-a'})
                self.assertEqual(api.reconciliations, [])

    def test_restored_store_namespace_is_quarantined_without_flush_or_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runner.sqlite3"
            journal = LocalJournal(path)
            request = {"attemptId": "attempt-a", "projectId": "project-a",
                       "storeId": "store-old", "taskKind": "plan"}
            journal.record_claim(request)
            with self.assertRaises(RunnerError):
                journal.bind_store("store-new")
            with journal._connect() as db:
                self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='quarantinedStoreId'").fetchone()[0], "store-old")
            with self.assertRaises(RunnerError):
                journal.claim_command("store-new")

    def test_ack_identity_mismatch_keeps_report_in_outbox(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = LocalJournal(Path(directory) / "runner.sqlite3")
            request = {"attemptId": "attempt-a", "projectId": "project-a",
                       "storeId": "store-a", "taskKind": "plan"}
            journal.start_intent("attempt-a", request)
            journal.add_report("attempt-a", "failed", "store-a", "project-a", journal.runner_id,
                               {"stopped": False, "stopReason": "unknown"})
            class WrongAck(FakeAPI):
                def request(self, method, route, body=None):
                    ack = super().request(method, route, body)
                    ack["storeId"] = "store-other"
                    return ack
            with self.assertRaises(RunnerError):
                journal.flush(WrongAck())
            self.assertEqual(journal.pending(), 1)

    def test_launch_intent_is_single_use_after_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runner.sqlite3"
            request = {"attemptId": "attempt-a", "projectId": "project-a",
                       "storeId": "store-a", "taskKind": "plan"}
            first = LocalJournal(path)
            first.record_claim(request)
            first.start_intent("attempt-a", request)
            restarted = LocalJournal(path)
            with self.assertRaises(RunnerError):
                restarted.start_intent("attempt-a", request)

    def test_pending_claim_command_replays_after_crash_before_local_claim_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runner.sqlite3"
            first = LocalJournal(path)
            command = first.claim_command("store-a")
            restarted = LocalJournal(path)
            self.assertEqual(restarted.claim_command("store-a"), command)

    def test_service_loop_retries_transport_outage_and_keeps_iteration_state(self):
        stop = threading.Event()
        attempts = []
        durable_intent = {"commandId": "claim-stable"}
        def iteration():
            attempts.append(durable_intent["commandId"])
            if len(attempts) == 1:
                raise TransportError("temporary offline")
            stop.set()
        service_loop(iteration, stop, delay=0)
        self.assertEqual(attempts, ["claim-stable", "claim-stable"])

    def test_process_output_lines_drains_exited_child_and_preserves_partial_multiline_output(self):
        # Run the reader in a bounded harness so a regression to an EOF busy-loop
        # fails this test instead of hanging the full unittest discovery run.
        harness = r"""
import json
import os
import subprocess
import sys
import threading
from runners.common import process_output_lines

def render(lines):
    return list(lines)

# The consumer starts after this real child exits. The final record has no LF.
finished = subprocess.Popen(
    [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'first' + bytes([10]) + b'second' + bytes([10]) + b'final'); sys.stdout.flush()"],
    stdout=subprocess.PIPE,
)
finished_exit = finished.wait(timeout=2)
finished_lines = list(process_output_lines(finished, timeout=0.05))
finished.stdout.close()

# Keep a second real child alive after a partial line. The helper should yield
# None on its read timeout, then resume the same line when the child continues.
ready_read, ready_write = os.pipe()
paused_code = (
    "import os,sys; "
    "sys.stdout.buffer.write(b'begin' + bytes([10]) + b'partial'); "
    "sys.stdout.flush(); "
    "os.write(int(sys.argv[1]), b'r'); "
    "sys.stdin.buffer.readline(); "
    "sys.stdout.buffer.write(b'-done' + bytes([10]) + b'next' + bytes([10]) + b'last'); "
    "sys.stdout.flush()"
)
paused = subprocess.Popen(
    [sys.executable, "-c", paused_code, str(ready_write)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    pass_fds=(ready_write,),
)
os.close(ready_write)
assert os.read(ready_read, 1) == b"r"
os.close(ready_read)
reader = iter(process_output_lines(paused, timeout=0.05))
release_lock = threading.Lock()
released = False
def safety_release():
    global released
    with release_lock:
        if released:
            return
        released = True
    try:
        paused.stdin.write(b"resume" + bytes([10]))
        paused.stdin.flush()
    except BrokenPipeError:
        pass
safety_timer = threading.Timer(1.0, safety_release)
safety_timer.daemon = True
safety_timer.start()
events = [next(reader), next(reader)]
safety_timer.cancel()
safety_release()
events.extend(reader)
paused_exit = paused.wait(timeout=2)
paused.stdout.close()
paused.stdin.close()
print(json.dumps({
    "finishedExit": finished_exit,
    "finishedLines": render(finished_lines),
    "pausedExit": paused_exit,
    "pausedEvents": render(events),
}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", harness],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=8,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["finishedExit"], 0)
        self.assertEqual(result["finishedLines"], ["first\n", "second\n", "final"])
        self.assertEqual(result["pausedExit"], 0)
        self.assertEqual(
            result["pausedEvents"][:2],
            ["begin\n", None],
            "a partial line must yield control for timeout supervision",
        )
        self.assertEqual(
            [line for line in result["pausedEvents"] if line is not None],
            ["begin\n", "partial-done\n", "next\n", "last"],
        )

    def test_native_usage_alias_triggers_soft_budget_boundary(self):
        total = _native_total_tokens({"totalTokens": 12, "inputTokens": 9, "outputTokens": 3})
        self.assertEqual(total, 12)
        self.assertFalse(_soft_budget_reached(total, 13))
        self.assertTrue(_soft_budget_reached(total, 12))
        self.assertFalse(_soft_budget_reached(total, False))

    def test_agent_keeps_raw_planner_json_for_strict_backend_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / 'state.sqlite3')
            journal.bind_store('store-a')

            class API(FakeAPI):
                def request(self, method, route, body=None):
                    return {} if route.endswith('/heartbeat') else super().request(method, route, body)

            class Child:
                pid = 43211
                def __init__(self):
                    self.stdin, self.stdout = io.StringIO(), io.StringIO()
                def poll(self): return 0

            api = API()
            runner = AgentRunner(api, journal, root / 'workspaces', root / 'artifacts', root / 'protected')
            attempt = 'attempt-raw-plan'
            request = {'attemptId': attempt, 'projectId': 'project-a', 'storeId': 'store-a', 'taskKind': 'plan'}
            workspace = root / 'workspaces' / attempt
            temp_root = workspace / '.runner-tmp'
            raw = '{"status":"READY","status":"BLOCKED"}'
            events = [
                {'event': 'started', 'nativeIdentity': {'threadId': 'thread-one', 'turnId': 'turn-one',
                    'processId': None, 'processGroupId': None, 'processStartTime': None}},
                {'event': 'result', 'result': {'status': 'completed', 'response': raw,
                    'diagnostics': {'childTerminationConfirmed': True}}},
            ]
            prepared = ({'packet': {}}, workspace, {}, temp_root, ['fake-worker'], str(root), {})
            def prepare(_request):
                temp_root.mkdir(parents=True)
                return prepared
            with mock.patch('runners.agent.sandbox_probe', return_value={'passed': True}), \
                 mock.patch.object(runner, '_prepare_claim', side_effect=prepare), \
                 mock.patch('runners.agent.subprocess.Popen', return_value=Child()), \
                 mock.patch.object(runner, '_process_group_exists', return_value=False), \
                 mock.patch('runners.agent.process_output_lines', return_value=iter(json.dumps(e) for e in events)):
                self.assertTrue(runner.accept_claim(request, 'store-a'))
            completed = next(body for body in api.reports if body['type'] == 'completed')
            self.assertEqual(completed['payload']['result']['response'], raw)
            self.assertEqual(journal.pending(), 0)

    def test_agent_stops_fake_native_worker_at_soft_budget_and_spools_stop_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / "state.sqlite3")
            journal.bind_store("store-a")
            packet = {"id": "packet-a"}
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-budget",
                        "packet": packet, "assets": []}
            class API(FakeAPI):
                def request(self, method, route, body=None):
                    if method == "GET": return material
                    if route.endswith("/heartbeat"): return {}
                    ack = {"schemaVersion": "studio.message.v1", "kind": "report_ack",
                           **{key: body[key] for key in
                              ("storeId", "projectId", "attemptId", "runnerId", "reportId")},
                           "disposition": "recorded"}
                    self.reports.append(body)
                    return ack
            api = API()
            api.token_path = root / "runner-token"
            request = {"attemptId": "attempt-budget", "projectId": "project-a", "storeId": "store-a",
                       "taskKind": "plan", "profileSnapshot": {"limits": {"softTotalTokens": 50}}}
            lines = [
                {"event": "started", "nativeIdentity": {"threadId": None, "turnId": None,
                    "processId": 43211, "processGroupId": 43211, "processStartTime": "2026-10-12T00:00:00Z"}},
                {"event": "usage", "usage": {"totalTokens": 50}},
                {"event": "result", "result": {"diagnostics": {"childTerminationConfirmed": True}}},
            ]
            read_fd, write_fd = os.pipe()
            os.write(write_fd, "".join(json.dumps(item) + "\n" for item in lines).encode())
            class PipeReader:
                def __init__(self):
                    self.stream = os.fdopen(read_fd, "rb", buffering=0)
                    self.count = 0
                def fileno(self): return self.stream.fileno()
                def close(self): self.stream.close()
                def readline(self):
                    value = self.stream.readline()
                    if value: self.count += 1
                    return value.decode("utf-8")
            class Child:
                pid = 43211
                def __init__(self):
                    self.stdout = PipeReader()
                    self.stdin = io.StringIO()
                def poll(self): return 0
                def wait(self): return 0
            runner = AgentRunner(api, journal, root / "workspaces", root / "artifacts",
                                 root / "protected", require_sandbox=False)
            group_terminated = False
            def fake_killpg(_pid, sig):
                nonlocal group_terminated
                if sig == 0 and group_terminated:
                    raise ProcessLookupError
                if sig == signal.SIGTERM:
                    group_terminated = True
            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", return_value=Child()), \
                 mock.patch("runners.agent.os.killpg", side_effect=fake_killpg) as killpg:
                self.assertFalse(runner.accept_claim(request, "store-a"))
            os.close(write_fd)
            killpg.assert_any_call(43211, signal.SIGTERM)
            self.assertGreaterEqual(journal.pending(), 1)
            with journal._connect() as db:
                pending_bodies = [json.loads(row[0]) for row in db.execute(
                    "SELECT body_json FROM reports WHERE acknowledged=0")]
            self.assertTrue(any(body["type"] == "stopped"
                                and body["payload"]["stopReason"] == "soft_budget"
                                for body in pending_bodies))
            stop_report = next(body for body in pending_bodies if body["type"] == "stopped")
            self.assertEqual(stop_report["payload"]["stopReason"], "soft_budget")
            self.assertIs(stop_report["payload"]["stopped"], True)

    def test_protocol_json_rejects_duplicate_keys_and_nan(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(RunnerError):
                strict_json(raw)

    def test_runner_token_must_be_private(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("secret", encoding="utf-8")
            token.chmod(0o644)
            with self.assertRaises(RunnerError):
                RunnerHTTP("http://127.0.0.1", token, "runner-test")

    def test_http_transient_statuses_retry_but_auth_and_protocol_4xx_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("secret", encoding="utf-8")
            token.chmod(0o600)
            api = RunnerHTTP("http://127.0.0.1", token, "runner-test")
            for status in (429, 503):
                error = HTTPError("http://127.0.0.1/test", status, "temporary",
                                  {}, io.BytesIO(b"retry"))
                with mock.patch("runners.common.urllib.request.urlopen", side_effect=error):
                    with self.assertRaises(TransportError):
                        api.request("GET", "/test")
            error = HTTPError("http://127.0.0.1/test", 401, "unauthorized",
                              {}, io.BytesIO(b"bad token"))
            with mock.patch("runners.common.urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(RunnerError, "HTTP 401"):
                    api.request("GET", "/test")

    def test_journal_capacity_pauses_claim_and_prunes_only_acked_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = LocalJournal(Path(directory) / "runner.sqlite3")
            journal.bind_store("store-a")
            journal.MAX_PENDING_ACTIVITY = 1
            journal.MAX_PENDING_REPORTS = 1
            journal.MAX_ACKED_ACTIVITY = 0
            request = {"attemptId": "attempt-a", "projectId": "project-a",
                       "storeId": "store-a", "taskKind": "plan"}
            journal.start_intent("attempt-a", request)
            self.assertIsNotNone(journal.add_report("attempt-a", "activity", "store-a", "project-a",
                journal.runner_id, {"activityKind": "tick"}))
            self.assertIsNone(journal.add_report("attempt-a", "activity", "store-a", "project-a",
                journal.runner_id, {"activityKind": "overflow"}))
            self.assertFalse(journal.can_claim(max_reports=1))
            self.assertFalse(journal.can_claim(max_bytes=1))
            class NoCallAPI:
                def request(self, *args, **kwargs):
                    raise AssertionError("runner must not request a claim while the outbox is full")
            agent = AgentRunner(NoCallAPI(), journal, Path(directory) / "workspaces",
                               Path(directory) / "artifacts", Path(directory) / "protected")
            self.assertTrue(agent.claim("store-a")["pausedForOutbox"])
            project = ProjectRunner(NoCallAPI(), journal, Path(directory) / "artifacts",
                                    Path(directory) / "protected")
            self.assertTrue(project.claim("store-a")["pausedForOutbox"])
            journal.add_report("attempt-a", "failed", "store-a", "project-a", journal.runner_id,
                               {"stopped": True, "stopReason": "native_error"})
            journal.prune_acknowledged_activity()
            self.assertEqual(journal.pending(), 2)
            journal.flush(FakeAPI())
            with journal._connect() as db:
                stored = [json.loads(row[0]) for row in db.execute("SELECT body_json FROM reports")]
            self.assertEqual([body["type"] for body in stored], ["failed"])
            self.assertTrue(journal.can_claim())

    def test_project_runner_materializes_independent_exact_git_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            repo = vault / "artifact-1" / "repository"
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "project.godot"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "sealed"], check=True)
            commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                    check=True, text=True, capture_output=True).stdout.strip()
            runner = ProjectRunner(None, LocalJournal(root / "state.sqlite3"), vault, root / "projects")
            ref = {"artifactId": "artifact-1", "projectId": "project-a", "jobId": "job-a",
                   "attemptId": "attempt-a", "sourceCommit": commit,
                   "inputCommit": commit, "packetId": "packet-a"}
            clone, exact = runner.materialize(ref, root / "verification" / "copy")
            self.assertEqual(exact, commit)
            self.assertEqual((clone / "project.godot").read_text(), "config_version=5\n")
            self.assertNotEqual((clone / ".git").resolve(), (repo / ".git").resolve())
            self.assertEqual(subprocess.run(["git", "-C", str(clone), "status", "--porcelain"],
                                            check=True, text=True, capture_output=True).stdout, "")

    def test_project_verify_offline_heartbeat_still_enforces_time_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            (vault / "artifact-offline").mkdir(parents=True)
            journal = LocalJournal(root / "state.sqlite3")
            material = {"packet": {"document": {"objects": []}}, "prepared": {}}

            class OfflineAPI(FakeAPI):
                def __init__(self):
                    super().__init__()
                    self.heartbeat_calls = 0

                def request(self, method, route, body=None):
                    if method == "GET" and route.endswith("/input"):
                        return material
                    if route.endswith("/heartbeat"):
                        self.heartbeat_calls += 1
                        raise TransportError("temporary offline")
                    return super().request(method, route, body)

            api = OfflineAPI()
            runner = ProjectRunner(api, journal, vault, root / "protected")
            artifact_ref = {"artifactId": "artifact-offline", "projectId": "project-a",
                            "jobId": "job-a", "attemptId": "attempt-offline",
                            "sourceCommit": "sealed-commit", "inputCommit": "sealed-commit",
                            "packetId": "packet-a"}
            execution = {"attemptId": "attempt-offline", "projectId": "project-a",
                         "inputRefs": {"artifactRef": artifact_ref}}

            def materialize(_artifact_ref, destination):
                destination.mkdir(parents=True)
                return destination, "sealed-commit"

            real_popen = subprocess.Popen
            child_processes = []

            def launch_sleeping_python(_argv, **kwargs):
                child = real_popen(
                    [sys.executable, "-c",
                     "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(4)"],
                    **kwargs,
                )
                child_processes.append(child)
                return child

            with mock.patch("runners.project.sandbox_probe", return_value={"passed": True}), \
                 mock.patch.object(runner, "materialize", side_effect=materialize), \
                 mock.patch("runners.project.subprocess.Popen", side_effect=launch_sleeping_python):
                started_at = time.monotonic()
                runner.verify(execution, "store-a", max_seconds=0.05)
                elapsed = time.monotonic() - started_at

            self.assertLess(elapsed, 3.0, "verification must supervise a partial output line")
            self.assertEqual(api.heartbeat_calls, 1)
            self.assertEqual(len(child_processes), 1)
            child = child_processes[0]
            self.assertIsNotNone(child.poll(), "the time-limited verification child must be terminated")
            child.wait(timeout=1)
            reports = [body for body in api.reports if body.get("attemptId") == "attempt-offline"]
            stopped = [body for body in reports if body["type"] == "stopped"]
            self.assertEqual(len(stopped), 1)
            self.assertEqual(stopped[0]["payload"]["stopReason"], "time_limit")
            self.assertIs(stopped[0]["payload"]["stopped"], True)
            self.assertFalse(any(body["type"] == "completed" for body in reports))
            self.assertFalse((vault / "verification-temp" / "attempt-offline").exists())

    def test_project_verify_loads_external_uid_proof_and_binds_worker_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            artifact_id = "artifact-uid"
            input_commit = "frozen-input-commit"
            source_commit = "sealed-source-commit"
            sidecars = {"scripts/main.gd.uid": b"uid://trustedmain\n"}
            preparation = UIDPreparationResult(input_commit, "4.6.3.stable.mock", sidecars)
            artifact_dir = vault / artifact_id
            evidence_path = artifact_dir / "evidence" / "uid-preparation.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps(preparation.evidence(source_commit)), encoding="utf-8"
            )
            artifact_ref = {
                "artifactId": artifact_id,
                "projectId": "project-a",
                "jobId": "job-a",
                "attemptId": "attempt-uid",
                "sourceCommit": source_commit,
                "inputCommit": input_commit,
                "packetId": "packet-uid",
            }
            material = {
                "packet": {"id": "packet-uid", "document": {"objects": []}},
                "prepared": {"inputCommit": input_commit},
            }

            class API(FakeAPI):
                def request(self, method, route, body=None):
                    if method == "GET" and route.endswith("/input"):
                        return material
                    if route.endswith("/heartbeat"):
                        return {}
                    return super().request(method, route, body)

            api = API()
            runner = ProjectRunner(api, LocalJournal(root / "state.sqlite3"), vault,
                                   root / "protected")
            execution = {
                "attemptId": "attempt-uid",
                "projectId": "project-a",
                "inputRefs": {
                    "artifactRef": artifact_ref,
                    "inputCommit": input_commit,
                    "sourceCommit": source_commit,
                },
            }

            def materialize(_artifact_ref, destination):
                destination.mkdir(parents=True)
                return destination, source_commit

            captured = {}
            real_popen = subprocess.Popen
            worker_script = (
                "import json,sys; request=json.loads(sys.stdin.read()); "
                "print(json.dumps({'status':'PASS','checks':[{'id':'worker-request',"
                "'status':'PASS','summary':json.dumps(request,sort_keys=True)}]}))"
            )

            def launch_worker(argv, **kwargs):
                captured["argv"] = argv
                captured["cwd"] = kwargs["cwd"]
                captured["env"] = dict(kwargs["env"])
                return real_popen([sys.executable, "-c", worker_script], **kwargs)

            with mock.patch("runners.project.sandbox_probe", return_value={"passed": True}), \
                 mock.patch.object(runner, "materialize", side_effect=materialize), \
                 mock.patch("runners.project._git",
                            side_effect=lambda _path, *args: source_commit if args == ("rev-parse", "HEAD") else ""), \
                 mock.patch("runners.project.subprocess.Popen", side_effect=launch_worker), \
                 mock.patch("runners.project.stop_process_group", return_value=True):
                runner.verify(execution, "store-a")

            worker_root = Path(__file__).resolve().parents[2]
            self.assertEqual(captured["cwd"], str(worker_root))
            self.assertEqual(captured["env"]["PYTHONNOUSERSITE"], "1")
            self.assertEqual(captured["env"]["PYTHONPATH"], str(worker_root))
            self.assertEqual(captured["argv"][1:3], ["-m", "runners.project_worker"])
            completed = next(body for body in api.reports if body["type"] == "completed")
            worker_check = completed["payload"]["result"]["checks"][0]
            worker_request = json.loads(worker_check["summary"])
            self.assertEqual(worker_request["baseCommit"], input_commit)
            self.assertEqual(worker_request["preparedUidSidecars"], {
                "scripts/main.gd.uid": "uid://trustedmain\n",
            })
            self.assertEqual(worker_request["expectedUidEngineVersion"], "4.6.3.stable.mock")

    def test_project_verify_rejects_bad_uid_proof_or_commit_bindings_before_worker_launch(self):
        cases = (
            ("proof input binding", {"proof_input_commit": "other-input"}, {}, {},
             "different input or source commit"),
            ("proof source binding", {"proof_source_commit": "other-source"}, {}, {},
             "different input or source commit"),
            ("prepared input binding", {}, {"inputCommit": "other-input"}, {},
             "does not match the prepared input"),
            ("attempt input binding", {}, {}, {"inputCommit": "other-input"},
             "does not match the attempt reference"),
            ("attempt source binding", {}, {}, {"sourceCommit": "other-source"},
             "does not match the attempt reference"),
        )
        for case_name, proof_changes, prepared_changes, ref_changes, message in cases:
            with self.subTest(binding=case_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vault = root / "vault"
                vault.mkdir()
                artifact_id = "artifact-invalid"
                input_commit = "frozen-input-commit"
                source_commit = "sealed-source-commit"
                proof_input_commit = proof_changes.get("proof_input_commit", input_commit)
                proof_source_commit = proof_changes.get("proof_source_commit", source_commit)
                artifact_dir = vault / artifact_id
                evidence_path = artifact_dir / "evidence" / "uid-preparation.json"
                evidence_path.parent.mkdir(parents=True)
                proof = UIDPreparationResult(
                    proof_input_commit,
                    "4.6.3.stable.mock",
                    {"scripts/main.gd.uid": b"uid://trustedmain\n"},
                ).evidence(proof_source_commit)
                evidence_path.write_text(json.dumps(proof), encoding="utf-8")
                artifact_ref = {
                    "artifactId": artifact_id,
                    "projectId": "project-a",
                    "jobId": "job-a",
                    "attemptId": "attempt-invalid",
                    "sourceCommit": source_commit,
                    "inputCommit": input_commit,
                    "packetId": "packet-invalid",
                }
                refs = {"artifactRef": artifact_ref, "inputCommit": input_commit,
                        "sourceCommit": source_commit, **ref_changes}
                material = {
                    "packet": {"id": "packet-invalid", "document": {"objects": []}},
                    "prepared": {"inputCommit": input_commit, **prepared_changes},
                }

                class API(FakeAPI):
                    def request(self, method, route, body=None):
                        if method == "GET" and route.endswith("/input"):
                            return material
                        if route.endswith("/heartbeat"):
                            return {}
                        return super().request(method, route, body)

                runner = ProjectRunner(
                    API(), LocalJournal(root / "state.sqlite3"), vault, root / "protected"
                )
                execution = {"attemptId": "attempt-invalid", "projectId": "project-a",
                             "inputRefs": refs}

                def materialize(_artifact_ref, destination):
                    destination.mkdir(parents=True)
                    return destination, source_commit

                with mock.patch("runners.project.sandbox_probe", return_value={"passed": True}), \
                     mock.patch.object(runner, "materialize", side_effect=materialize), \
                     mock.patch("runners.project.subprocess.Popen") as popen:
                    with self.assertRaisesRegex(RunnerError, message):
                        runner.verify(execution, "store-a")
                popen.assert_not_called()

    def test_preview_keeps_logs_outside_git_copy_and_cleans_private_tmp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            repo = vault / "artifact-1" / "repository"
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "project.godot"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "sealed"], check=True)
            commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                    check=True, text=True, capture_output=True).stdout.strip()
            api = FakeAPI()
            journal = LocalJournal(root / "state.sqlite3")
            runner = ProjectRunner(api, journal, vault, root, godot_path="/usr/bin/true")
            ref = {"artifactId": "artifact-1", "projectId": "project-a", "jobId": "job-a",
                   "attemptId": "attempt-a", "sourceCommit": commit,
                   "inputCommit": commit, "packetId": "packet-a"}
            execution = {"attemptId": "attempt-preview", "projectId": "project-a",
                         "taskKind": "preview", "inputRefs": {"artifactRef": ref}}
            class Child:
                pid = 43210
                def poll(self): return 0
                def wait(self): return 0
            real_popen = subprocess.Popen
            def fake_popen(argv, **kwargs):
                if not argv or argv[0] != "/usr/bin/sandbox-exec":
                    return real_popen(argv, **kwargs)
                project_dir = Path(argv[argv.index("--path") + 1])
                generated_cache = project_dir / ".godot" / "editor" / "cache.txt"
                generated_cache.parent.mkdir(parents=True, exist_ok=True)
                generated_cache.write_text("generated", encoding="utf-8")
                kwargs["stdout"].write("preview log evidence\n")
                return Child()
            with mock.patch("runners.project.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.project.subprocess.Popen", side_effect=fake_popen) as popen, \
                 mock.patch("runners.project.stop_process_group", return_value=True):
                runner.preview(execution, "store-a")
            workspace = vault / "previews" / "attempt-preview"
            self.assertFalse((workspace / ".runner-tmp").exists())
            self.assertTrue((workspace / ".godot/editor/cache.txt").is_file())
            self.assertTrue(_source_unchanged(workspace, commit))
            evidence = vault / "preview-evidence" / "attempt-preview.log"
            self.assertEqual(evidence.read_text(encoding="utf-8"), "preview log evidence\n")
            sandbox_profile = next(call.args[0][2] for call in popen.call_args_list
                                   if call.args[0][0] == "/usr/bin/sandbox-exec")
            self.assertNotIn(".codex", sandbox_profile)
            self.assertIn(str(workspace), sandbox_profile)
            self.assertNotIn(f'(deny file-read* (subpath "{vault.resolve()}"))', sandbox_profile)
            self.assertIn(f'(deny file-read* (subpath "{repo.parent.resolve()}"))', sandbox_profile)
            completed = [body for body in api.reports if body["type"] == "completed"]
            self.assertEqual(completed[0]["payload"]["result"]["evidenceRef"],
                             "preview-evidence/attempt-preview.log")

    def test_preview_reports_missing_godot_ca_compiler_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            repo = vault / "artifact-1" / "repository"
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "project.godot"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "sealed"], check=True)
            commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                    check=True, text=True, capture_output=True).stdout.strip()
            api = FakeAPI()
            journal = LocalJournal(root / "state.sqlite3")
            runner = ProjectRunner(api, journal, vault, root / "protected", godot_path="/usr/bin/true")
            ref = {"artifactId": "artifact-1", "projectId": "project-a", "jobId": "job-a",
                   "attemptId": "attempt-a", "sourceCommit": commit,
                   "inputCommit": commit, "packetId": "packet-a"}
            execution = {"attemptId": "attempt-preview-no-clang", "projectId": "project-a",
                         "taskKind": "preview", "inputRefs": {"artifactRef": ref}}

            with mock.patch("runners.project.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.godot_runtime.sys.platform", "darwin"), \
                 mock.patch("runners.godot_runtime._CLANG", root / "missing-clang"), \
                 mock.patch.object(ProjectRunner, "_prepare_preview_images", return_value={}), \
                 mock.patch.object(ProjectRunner, "materialize", autospec=True,
                                   side_effect=lambda _self, _ref, destination: (
                                       destination.mkdir(parents=True) or destination, commit)), \
                 mock.patch("runners.godot_runtime.GodotRuntime._ensure_system_ca_bundle",
                            return_value=root / "trusted-ca" / "system-ca.pem"), \
                 mock.patch("runners.project.subprocess.Popen") as popen:
                runner.preview(execution, "store-a")

            popen.assert_not_called()
            workspace = vault / "previews" / "attempt-preview-no-clang"
            self.assertFalse((workspace / ".runner-tmp").exists())
            log_path = vault / "preview-evidence" / "attempt-preview-no-clang.log"
            diagnostic_line = log_path.read_text(encoding="utf-8").strip()
            self.assertTrue(diagnostic_line.startswith("STUDIO_PREVIEW_FAILURE="))
            diagnostic = json.loads(diagnostic_line.split("=", 1)[1])
            self.assertEqual(diagnostic["phase"], "trusted_ca_runtime_preparation")
            self.assertIs(diagnostic["processStarted"], False)
            self.assertIs(diagnostic["stopped"], True)
            self.assertIn("Command Line Tools", diagnostic["message"])
            failures = [body for body in api.reports if body["type"] == "failed"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["payload"], {
                "stopped": True,
                "stopReason": "native_error",
                "diagnosticRef": "preview-evidence/attempt-preview-no-clang.log",
            })

    @unittest.skipUnless(platform.system() == "Darwin" and Path("/Applications/Godot.app/Contents/MacOS/Godot").is_file(), "requires local Godot and macOS sandbox")
    def test_real_preview_imports_png_before_runtime_and_preserves_sealed_source(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            repo = vault / "artifact-image" / "repository"
            (repo / "assets").mkdir(parents=True)
            Image.new("RGB", (16, 16), (220, 80, 40)).save(repo / "assets/actor.png")
            (repo / "project.godot").write_text('config_version=5\n[application]\nrun/main_scene="res://main.tscn"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
            (repo / "main.tscn").write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://main.gd" id="1"]\n[node name="Main" type="Node2D"]\nscript=ExtResource("1")\n')
            (repo / "main.gd").write_text('extends Node2D\nfunc _ready():\n\tvar image = load("res://assets/actor.png")\n\tif image == null or image.get_width() != 16:\n\t\tpush_error("Preview texture missing")\n\telse:\n\t\tprint("PREVIEW_TEXTURE_LOADED")\n\tget_tree().create_timer(0.2).timeout.connect(func(): get_tree().quit())\n')
            (repo / "main.gd.uid").write_text("uid://bvk1n8r5tw3a2\n")
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "--quiet", "-m", "sealed image fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            class API(FakeAPI):
                def request(self, method, route, body=None):
                    return {} if route.endswith("heartbeat") else super().request(method, route, body)
            api = API()
            runner = ProjectRunner(api, LocalJournal(root / "state.sqlite3"), vault, root / "protected",
                godot_path="/Applications/Godot.app/Contents/MacOS/Godot")
            ref = {"artifactId": "artifact-image", "projectId": "project-image", "jobId": "job-image", "attemptId": "attempt-source",
                "sourceCommit": commit, "inputCommit": commit, "packetId": "packet-image"}
            runner.preview({"attemptId": "attempt-preview-image", "projectId": "project-image", "taskKind": "preview", "inputRefs": {"artifactRef": ref}}, "store-image", max_seconds=10)
            log = (vault / "preview-evidence/attempt-preview-image.log").read_text()
            self.assertIn("PREVIEW_TEXTURE_LOADED", log)
            self.assertNotIn("ERROR:", log)
            self.assertTrue(_source_unchanged(repo, commit))
            copy = vault / "previews/attempt-preview-image"
            self.assertTrue(_source_unchanged(copy, commit))
            self.assertFalse((copy / "assets/actor.png.import").exists())
            self.assertTrue((copy / ".godot/imported").is_dir())
            self.assertEqual([r["type"] for r in api.reports], ["started", "activity", "completed"])

    @unittest.skipUnless(platform.system() == "Darwin" and Path("/Applications/Godot.app/Contents/MacOS/Godot").is_file(), "requires local Godot and macOS sandbox")
    def test_real_preview_scans_script_classes_without_image_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            repo = vault / "artifact-script" / "repository"
            repo.mkdir(parents=True)
            (repo / "project.godot").write_text('config_version=5\n[application]\nrun/main_scene="res://main.tscn"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
            (repo / "main.tscn").write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://main.gd" id="1"]\n[node name="Main" type="Node2D"]\nscript=ExtResource("1")\n')
            (repo / "runtime.gd").write_text('class_name PreviewScopeRuntime\nextends RefCounted\nvar ready_value: int = 7\n')
            (repo / "main.gd").write_text('extends Node2D\nvar runtime: PreviewScopeRuntime\nfunc _ready():\n\truntime = PreviewScopeRuntime.new()\n\tprint("PREVIEW_CLASS_LOADED=", runtime.ready_value)\n\tget_tree().create_timer(0.2).timeout.connect(func(): get_tree().quit())\n')
            (repo / "main.gd.uid").write_text("uid://bvk1n8r5tw3a2\n")
            (repo / "runtime.gd.uid").write_text("uid://bvk1n8r5tw3a3\n")
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "--quiet", "-m", "sealed script fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            class API(FakeAPI):
                def request(self, method, route, body=None):
                    return {} if route.endswith("heartbeat") else super().request(method, route, body)
            api = API()
            runner = ProjectRunner(api, LocalJournal(root / "state.sqlite3"), vault, root / "protected",
                godot_path="/Applications/Godot.app/Contents/MacOS/Godot")
            ref = {"artifactId": "artifact-script", "projectId": "project-script", "jobId": "job-script", "attemptId": "attempt-source",
                "sourceCommit": commit, "inputCommit": commit, "packetId": "packet-script"}
            runner.preview({"attemptId": "attempt-preview-script", "projectId": "project-script", "taskKind": "preview", "inputRefs": {"artifactRef": ref}}, "store-script", max_seconds=10)
            log = (vault / "preview-evidence/attempt-preview-script.log").read_text()
            self.assertIn("PREVIEW_CLASS_LOADED=7", log)
            self.assertNotIn("ERROR:", log)
            copy = vault / "previews/attempt-preview-script"
            self.assertTrue((copy / ".godot/global_script_class_cache.cfg").is_file())
            self.assertFalse((copy / "assets").exists())
            self.assertTrue(_source_unchanged(repo, commit))
            self.assertTrue(_source_unchanged(copy, commit))

    @unittest.skipUnless(platform.system() == "Darwin", "macOS seatbelt is the supported execution boundary")
    def test_real_sandbox_probe_denies_private_files_and_loopback(self):
        result = sandbox_probe()
        self.assertEqual(result.get("status"), "PASS", result)
        self.assertTrue(result.get("crossProjectDenied"))
        self.assertTrue(result.get("approvalNetworkDenied"))

    def test_protected_siblings_does_not_deny_nested_active_workspace_children(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "artifacts"
            active = root / "artifact-active" / "repository"
            sibling = root / "artifact-sibling"
            active.mkdir(parents=True)
            sibling.mkdir()
            active_children = [active / "scripts", active / ".godot", active / ".runner-tmp"]
            for child in active_children:
                child.mkdir()

            protected = {path.resolve() for path in protected_siblings(root, active=active)}
            self.assertIn(sibling.resolve(), protected)
            self.assertNotIn(active.resolve(), protected)
            for child in active_children:
                self.assertNotIn(child.resolve(), protected)

            rules = strict_sandbox_rules(
                active,
                read_roots=[active],
                write_roots=[active],
                protected_paths=list(protected),
            )
            joined_rules = "\n".join(rules)
            self.assertIn(str(sibling.resolve()), joined_rules)
            for child in active_children:
                self.assertNotIn(str(child.resolve()), joined_rules)

    @unittest.skipUnless(platform.system() == "Darwin", "macOS seatbelt is the supported execution boundary")
    def test_sandboxed_sibling_project_and_loopback_access_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sibling = root / "sibling-project"
            sibling.mkdir()
            secret = sibling / "secret.txt"
            secret.write_text("protected", encoding="utf-8")
            active = root / "active-project"
            active.mkdir()
            rules = strict_sandbox_rules(active, read_roots=[active], write_roots=[active],
                                         protected_paths=[sibling], allow_internet=True)
            self.assertIn('(allow file-read* (literal "/"))', rules)
            self.assertNotIn('(allow file-read* (subpath "/"))', rules)
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            try:
                script = ('use IO::Socket::INET; '
                          'if (open(my $fh, "<", $ARGV[0])) { local $/; <$fh>; print "FILE_ALLOWED\\n"; } '
                          'else { print "FILE_DENIED\\n"; } '
                          'my $socket = IO::Socket::INET->new(PeerAddr=>"127.0.0.1",PeerPort=>$ARGV[1],Proto=>"tcp",Timeout=>0.5); '
                          'print($socket ? "NET_ALLOWED\\n" : "NET_DENIED\\n");')
                result = sandboxed_run(["/usr/bin/perl", "-e", script, str(secret),
                                        str(listener.getsockname()[1])],
                                       cwd=active, deny_paths=[sibling])
            finally:
                listener.close()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FILE_DENIED", result.stdout)
            self.assertIn("NET_DENIED", result.stdout)


if __name__ == "__main__":
    unittest.main()

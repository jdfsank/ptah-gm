from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import runners.common as runner_common
from runners.agent import AgentRunner
from runners.common import LocalJournal
from runners.project import ProjectRunner


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "evidence" / "workflow" / "studio-acceptance-agent-lifecycle-20261012.json"


WORKER_SOURCE = r'''
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

mode = sys.argv[1]
marker = Path(sys.argv[2])
ack_path = Path(sys.argv[3]) if sys.argv[3] != "-" else None
json.loads(sys.stdin.read())

if mode == "setup-failed":
    log = Path(sys.argv[4]) / '.runner-tmp/native-code-host/host.log'
    log.parent.mkdir(parents=True)
    log.write_text('synthetic host bind denied')
    print(json.dumps({"event": "setupFailed", "errorType": "RunnerError"}), flush=True)
    raise SystemExit(0)

if mode == "no-native":
    print(json.dumps({"event": "diagnostic", "providerBridge": {
        "requestCount": 1, "failureCount": 1, "timeoutSeconds": 300,
        "failures": [{"kind": "timeout", "httpStatus": None, "responseStarted": False}],
    }}), flush=True)
    print("intentional worker failure", flush=True)
    raise SystemExit(7)

native_source = r"""
import json
import os
import signal
import sys
import time
from pathlib import Path

mode = sys.argv[1]
marker = Path(sys.argv[2])
leader_exited = Path(sys.argv[3])
ready = Path(sys.argv[4])

def handle_term(_signum, _frame):
    marker.write_text(json.dumps({
        "pid": os.getpid(),
        "signal": "SIGTERM",
        "leaderExitedMarkerObserved": leader_exited.exists(),
    }), encoding="utf-8")
    if mode == "orphan":
        print(json.dumps({
            "event": "result",
            "nativeIdentity": {"threadId": None, "turnId": None},
            "result": {"diagnostics": {"childTerminationConfirmed": True}},
        }), flush=True)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, handle_term)
ready.write_text("ready", encoding="utf-8")
while True:
    time.sleep(1)
"""

native = subprocess.Popen(
    [sys.executable, "-u", "-c", native_source, mode, str(marker),
     str(marker.with_suffix(marker.suffix + ".leader-exited")),
     str(marker.with_suffix(marker.suffix + ".ready"))],
    start_new_session=True,
)
ready_path = marker.with_suffix(marker.suffix + ".ready")
ready_deadline = time.monotonic() + 5.0
while not ready_path.exists() and time.monotonic() < ready_deadline:
    time.sleep(0.01)
if not ready_path.exists():
    raise RuntimeError("native fixture did not become ready")
identity = {
    "threadId": None,
    "turnId": None,
    "processId": native.pid,
    "processGroupId": os.getpgid(native.pid),
    "processStartTime": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}
marker.with_suffix(marker.suffix + ".lease.json").write_text(json.dumps({
    "outerPid": os.getpid(),
    "nativePid": native.pid,
    "nativePgid": identity["processGroupId"],
}), encoding="utf-8")
print(json.dumps({"event": "started", "nativeIdentity": identity}), flush=True)

if mode == "overflow":
    while ack_path is not None and not ack_path.exists():
        time.sleep(0.01)
    sys.stdout.write("X" * 8192 + "\n")
    sys.stdout.flush()
    time.sleep(60)
elif mode == "failed-terminal":
    native.terminate()
    native.wait(timeout=3)
    print(json.dumps({
        "event": "result",
        "nativeIdentity": {"threadId": None, "turnId": None},
        "result": {"status": "failed", "response": "PRIVATE_MODEL_RESPONSE",
                   "diagnostics": {"childTerminationConfirmed": True,
                                   "nativeErrors": [{"message": "stream disconnected PRIVATE_ERROR_BODY", "willRetry": True}],
                                   "nativeTurnError": {"message": "context window exceeded PRIVATE_ERROR_BODY"}}},
    }), flush=True)
elif mode == "successful-terminal":
    native.terminate()
    native.wait(timeout=3)
    print(json.dumps({
        "event": "result",
        "nativeIdentity": {"threadId": None, "turnId": None},
        "result": {"status": "completed", "response": "synthetic success",
                   "diagnostics": {"childTerminationConfirmed": True}},
    }), flush=True)
elif mode == "completed-timeout":
    while ack_path is not None and not ack_path.exists():
        time.sleep(0.01)
    native.terminate()
    native.wait(timeout=3)
    print(json.dumps({
        "event": "result",
        "nativeIdentity": {"threadId": None, "turnId": None},
        "result": {"status": "timeout", "diagnostics": {"childTerminationConfirmed": True}},
    }), flush=True)
    release_path = marker.with_suffix(marker.suffix + ".release")
    while not release_path.exists():
        time.sleep(0.01)
elif mode == "orphan":
    time.sleep(0.05)
    marker.with_suffix(marker.suffix + ".leader-exited").write_text("leader exited", encoding="utf-8")
    raise SystemExit(0)
'''


class FixtureAPI:
    def __init__(self, material: dict, token_path: Path):
        self.material = material
        self.token_path = token_path
        self.reports: list[dict] = []

    def request(self, method, route, body=None):
        if method == "GET" and route.endswith("/input"):
            return self.material
        if route.endswith("/heartbeat"):
            return {"cancelRequested": False}
        if route.endswith("/reports"):
            self.reports.append(body)
            return {"schemaVersion": "studio.message.v1", "kind": "report_ack",
                    **{key: body[key] for key in
                       ("storeId", "projectId", "attemptId", "runnerId", "reportId")},
                    "disposition": "recorded"}
        raise AssertionError(f"unexpected API request: {method} {route}")


class AgentLifecycleProcessTests(unittest.TestCase):
    evidence_cases: list[dict] = []
    worker_dir: tempfile.TemporaryDirectory | None = None
    worker_path: Path

    def test_explicit_prelaunch_failure_reaps_worker_and_discards_generated_workspace(self):
        with tempfile.TemporaryDirectory(prefix='agent-prelaunch-') as directory:
            root = Path(directory)
            material = {'attemptId': 'attempt-prelaunch', 'packet': {'id': 'packet-prelaunch'}, 'assets': []}
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, 'attempt-prelaunch', 'setup-failed', 'plan', 30, material)
            with mock.patch('runners.agent.sandbox_probe', return_value={'passed': True}), \
                    mock.patch('runners.agent.subprocess.Popen', side_effect=launch):
                self.assertFalse(runner.accept_claim(request, 'store-lifecycle'))
            self.assertEqual(launched[0].returncode, 0)
            self.assertTrue(self._wait_group_gone(launched[0].pid))
            self.assertFalse((root / 'workspaces/attempt-prelaunch').exists())
            failure = next(r for r in api.reports if r['type'] == 'failed')
            self.assertTrue(failure['payload']['stopped'])
            self.assertTrue(failure['payload']['launchPrevented'])
            self.assertIsNone(runner._attempt_identity('attempt-prelaunch'))
            with journal._connect() as db:
                diagnostic = json.loads(db.execute('SELECT value FROM metadata WHERE key=?',
                    (failure['payload']['diagnosticRef'],)).fetchone()[0])
            self.assertTrue(diagnostic['workspaceCleanupConfirmed'])
            self.assertIn('synthetic host bind denied', diagnostic['toolHostLog'])

    @classmethod
    def setUpClass(cls):
        cls.worker_dir = tempfile.TemporaryDirectory(prefix="agent-lifecycle-worker-")
        cls.worker_path = Path(cls.worker_dir.name) / "worker.py"
        cls.worker_path.write_text(WORKER_SOURCE, encoding="utf-8")
        cls.evidence_cases = []

    @classmethod
    def tearDownClass(cls):
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps({
            "schemaVersion": "studio.acceptance.agent-lifecycle.v1",
            "date": "2026-10-12",
            "scope": "Real Python subprocess lifecycle checks; no model or Godot process.",
            "cases": cls.evidence_cases,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if cls.worker_dir is not None:
            cls.worker_dir.cleanup()

    @staticmethod
    def _group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            raise

    @classmethod
    def _wait_group_gone(cls, pgid: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not cls._group_exists(pgid):
                return True
            time.sleep(0.025)
        return not cls._group_exists(pgid)

    @staticmethod
    def _kill_group_if_alive(pgid: int):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _reports(journal: LocalJournal) -> list[dict]:
        with journal._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT body_json FROM reports ORDER BY created_at")]

    def _runner(self, root: Path, attempt: str, mode: str, task_kind: str,
                max_duration: float, material: dict, ack_path: Path | None = None):
        journal = LocalJournal(root / "journal.sqlite3")
        journal.bind_store("store-lifecycle")
        api = FixtureAPI(material, root / "runner-token")
        runner = AgentRunner(api, journal, root / "workspaces", root / "artifacts",
                             root / "protected", require_sandbox=False)
        # These tests replace the model adapter with a Python process fixture.
        # Actual editor readiness and dispatch ordering have their own tests.
        runner._ensure_production_mcp = mock.Mock()
        request = {"attemptId": attempt, "projectId": "project-lifecycle",
                   "storeId": "store-lifecycle", "taskKind": task_kind,
                   "profileSnapshot": {"limits": {"maxDurationSeconds": max_duration}}}
        marker = root / f"{mode}-native.json"
        ack = ack_path or root / f"{mode}-started-ack"
        launched = []
        real_popen = subprocess.Popen
        trusted_python_root = Path(__file__).resolve().parents[2]

        def launch_python_worker(command, *args, **kwargs):
            if (len(command) != 4 or command[1:3] != ["-m", "runners.agent_worker"]):
                raise AssertionError("test expected AgentRunner's pinned trusted adapter")
            if Path(kwargs.get("cwd", "")).resolve() != trusted_python_root:
                raise AssertionError("AgentRunner worker cwd must remain in the trusted host checkout")
            if kwargs.get("env", {}).get("PYTHONNOUSERSITE") != "1":
                raise AssertionError("AgentRunner worker must disable user site packages")
            process = real_popen(
                [sys.executable, "-u", str(self.worker_path), mode, str(marker), str(ack), command[3]],
                *args, **kwargs)
            launched.append(process)
            self.addCleanup(self._kill_group_if_alive, process.pid)
            return process

        return runner, api, journal, request, marker, launched, launch_python_worker

    def test_reader_overflow_stops_outer_and_native_groups_and_never_seals(self):
        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-overflow-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-overflow",
                        "packet": {"id": "packet-overflow", "allowedFiles": ["scripts/result.gd"]},
                        "assets": [], "prepared": {"inputArtifactRef": {"artifactId": "input-fixture"},
                                                    "serviceRecords": None}}
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, "attempt-overflow", "overflow", "produce", 30, material)
            runner._seal = mock.Mock(side_effect=AssertionError("overflow must never seal"))
            original_report_started = runner._report_started
            ack = root / "overflow-started-ack"

            def report_started(*args):
                original_report_started(*args)
                ack.write_text("native identity consumed", encoding="utf-8")

            runner._report_started = report_started

            def materialize_fixture(_project_runner, _ref, destination):
                destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                return destination, "input-commit"

            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.agent.process_output_lines", side_effect=lambda process:
                            runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=1024)), \
                 mock.patch.object(ProjectRunner, "materialize", materialize_fixture):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            lease = json.loads(marker.with_suffix(marker.suffix + ".lease.json").read_text(encoding="utf-8"))
            native_pgid = lease["nativePgid"]
            self.addCleanup(self._kill_group_if_alive, native_pgid)
            self.assertEqual(outer.returncode, -signal.SIGTERM)
            self.assertTrue(self._wait_group_gone(outer.pid))
            self.assertTrue(self._wait_group_gone(native_pgid))
            self.assertTrue(marker.exists(), "native process should record that its group received SIGTERM")
            self.assertFalse((root / "workspaces" / "attempt-overflow" / ".runner-tmp").exists())
            runner._seal.assert_not_called()
            kinds = [report["type"] for report in api.reports]
            self.assertIn("failed", kinds)
            self.assertIn("stopped", kinds)
            self.assertNotIn("completed", kinds)
            failure = next(report for report in api.reports if report["type"] == "failed")
            stopped = next(report for report in api.reports if report["type"] == "stopped")
            self.assertEqual(failure["payload"]["diagnosticRef"], "local:native-diagnostics/attempt-overflow")
            self.assertIs(stopped["payload"]["stopped"], True)
            self.evidence_cases.append({
                "name": "reader-output-overflow",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "nativePid": lease["nativePid"],
                "nativePgid": native_pgid,
                "outerGroupGone": True,
                "nativeGroupGone": True,
                "failedAndStoppedReports": True,
                "tempDirectoryRemoved": True,
                "sealCalled": False,
            })

    def test_duration_supervises_native_group_after_worker_leader_exits(self):
        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-orphan-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-orphan",
                        "packet": {"id": "packet-orphan"}, "assets": []}
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, "attempt-orphan", "orphan", "plan", 1.2, material)
            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.agent.process_output_lines", side_effect=lambda process:
                            runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=4096)):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            lease = json.loads(marker.with_suffix(marker.suffix + ".lease.json").read_text(encoding="utf-8"))
            native_pgid = lease["nativePgid"]
            self.addCleanup(self._kill_group_if_alive, native_pgid)
            self.assertEqual(outer.returncode, 0, "worker leader should have exited before duration stop")
            self.assertTrue(marker.with_suffix(marker.suffix + ".leader-exited").exists())
            self.assertTrue(self._wait_group_gone(outer.pid))
            self.assertTrue(self._wait_group_gone(native_pgid))
            termination = json.loads(marker.read_text(encoding="utf-8"))
            self.assertTrue(termination["leaderExitedMarkerObserved"])
            reports = self._reports(journal)
            stopped = next(report for report in reports if report["type"] == "stopped")
            self.assertEqual(stopped["payload"]["stopReason"], "time_limit")
            self.assertIs(stopped["payload"]["stopped"], True)
            self.assertFalse(any(report["type"] == "completed" for report in reports))
            self.evidence_cases.append({
                "name": "max-duration-after-leader-exit",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "outerReturnCode": outer.returncode,
                "nativePid": lease["nativePid"],
                "nativePgid": native_pgid,
                "leaderExitedBeforeNativeSignal": termination["leaderExitedMarkerObserved"],
                "outerGroupGone": True,
                "nativeGroupGone": True,
                "stoppedReason": "time_limit",
                "stopped": True,
            })

    def test_failed_native_terminal_is_reported_without_sealing_producer(self):
        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-failed-terminal-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-failed-terminal",
                        "packet": {"id": "packet-failed-terminal", "allowedFiles": ["scripts/result.gd"]},
                        "assets": [], "prepared": {"inputArtifactRef": {"artifactId": "input-fixture"},
                                                    "serviceRecords": None}}
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, "attempt-failed-terminal", "failed-terminal", "produce", 30, material)
            runner._seal = mock.Mock(side_effect=AssertionError("failed native terminal must never seal"))

            def materialize_fixture(_project_runner, _ref, destination):
                destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                return destination, "input-commit"

            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.project.ProjectRunner.materialize", materialize_fixture), \
                 mock.patch("runners.agent.process_output_lines", side_effect=lambda process:
                            runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=4096)):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            lease = json.loads(marker.with_suffix(marker.suffix + ".lease.json").read_text(encoding="utf-8"))
            native_pgid = lease["nativePgid"]
            self.addCleanup(self._kill_group_if_alive, native_pgid)
            self.assertEqual(outer.returncode, 0)
            self.assertTrue(marker.exists(), "synthetic native child must confirm termination")
            self.assertTrue(self._wait_group_gone(outer.pid))
            self.assertTrue(self._wait_group_gone(native_pgid))
            runner._seal.assert_not_called()
            reports = self._reports(journal)
            failed = next(report for report in reports if report["type"] == "failed")
            self.assertIs(failed["payload"]["stopped"], True)
            self.assertEqual(failed["payload"]["diagnosticRef"], "local:native-diagnostics/attempt-failed-terminal")
            with journal._connect() as db:
                diagnostic = db.execute("SELECT value FROM metadata WHERE key=?",
                                        (failed["payload"]["diagnosticRef"],)).fetchone()[0]
            self.assertNotIn("PRIVATE_", diagnostic)
            self.assertEqual(json.loads(diagnostic)["nativeTurnError"]["reason"], "context_limit")
            self.assertFalse((runner.workspace_root / request["attemptId"] / ".runner-tmp").exists())
            self.assertFalse(any(report["type"] == "completed" for report in reports))
            self.evidence_cases.append({
                "name": "failed-native-terminal-does-not-seal",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "nativePid": lease["nativePid"],
                "nativePgid": native_pgid,
                "nativeTerminationConfirmed": True,
                "failedTerminalReported": True,
                "sealCalled": False,
            })

    def test_seal_verification_error_is_reported_as_stopped_failure(self):
        from backend.general_verification import GeneralVerificationError

        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-seal-error-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-seal-error",
                        "packet": {"id": "packet-seal-error", "allowedFiles": ["scripts/result.gd"]},
                        "assets": [], "prepared": {"inputArtifactRef": {"artifactId": "input-fixture"},
                                                    "serviceRecords": None}}
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, "attempt-seal-error", "successful-terminal", "produce", 30, material)
            runner._seal = mock.Mock(side_effect=GeneralVerificationError("synthetic verification rejection"))

            def materialize_fixture(_project_runner, _ref, destination):
                destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                return destination, "input-commit"

            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.project.ProjectRunner.materialize", materialize_fixture), \
                 mock.patch("runners.agent.process_output_lines", side_effect=lambda process:
                            runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=4096)):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            lease = json.loads(marker.with_suffix(marker.suffix + ".lease.json").read_text(encoding="utf-8"))
            native_pgid = lease["nativePgid"]
            self.addCleanup(self._kill_group_if_alive, native_pgid)
            self.assertEqual(outer.returncode, 0)
            self.assertTrue(marker.exists(), "synthetic native child must confirm termination")
            self.assertTrue(self._wait_group_gone(outer.pid))
            self.assertTrue(self._wait_group_gone(native_pgid))
            runner._seal.assert_called_once()
            reports = self._reports(journal)
            failed = next(report for report in reports if report["type"] == "failed")
            self.assertIs(failed["payload"]["stopped"], True)
            self.assertEqual(failed["payload"]["diagnosticRef"],
                             "local:seal-diagnostics/attempt-seal-error")
            self.assertFalse(any(report["type"] == "completed" for report in reports))
            self.assertFalse((root / "workspaces" / "attempt-seal-error" / ".runner-tmp").exists())
            self.evidence_cases.append({
                "name": "seal-verification-error-is-stopped-failure",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "nativePid": lease["nativePid"],
                "nativePgid": native_pgid,
                "nativeTerminationConfirmed": True,
                "verificationErrorReported": True,
                "sealCalledOnce": True,
                "completedReported": False,
            })

    def test_confirmed_native_timeout_terminal_reports_time_limit_without_signalling_or_sealing(self):
        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-completed-timeout-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-completed-timeout",
                        "packet": {"id": "packet-completed-timeout", "allowedFiles": ["scripts/result.gd"]},
                        "assets": [], "prepared": {"inputArtifactRef": {"artifactId": "input-fixture"},
                                                    "serviceRecords": None}}
            ack = root / "timeout-terminal-ack"
            runner, api, journal, request, marker, launched, launch = self._runner(
                root, "attempt-completed-timeout", "completed-timeout", "produce", 1.0, material,
                ack_path=ack)
            runner._seal = mock.Mock(side_effect=AssertionError("timeout terminal must never seal"))

            def materialize_fixture(_project_runner, _ref, destination):
                destination.mkdir(mode=0o700, parents=True, exist_ok=False)
                return destination, "input-commit"

            original_report_started = runner._report_started
            def report_started(*args):
                original_report_started(*args)
                ack.write_text(str(time.monotonic()), encoding="utf-8")

            runner._report_started = report_started
            release = marker.with_suffix(marker.suffix + ".release")
            def delay_result_until_past_limit(process):
                for line in runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=4096):
                    try:
                        event = json.loads(line) if isinstance(line, str) else {}
                    except (ValueError, TypeError):
                        event = {}
                    if event.get("event") == "result":
                        deadline = float(ack.read_text(encoding="utf-8")) + 1.15
                        while time.monotonic() < deadline:
                            time.sleep(0.005)
                    yield line
                    if event.get("event") == "result":
                        release.write_text("release synthetic worker", encoding="utf-8")

            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.project.ProjectRunner.materialize", materialize_fixture), \
                 mock.patch("runners.agent.process_output_lines", side_effect=delay_result_until_past_limit):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            lease = json.loads(marker.with_suffix(marker.suffix + ".lease.json").read_text(encoding="utf-8"))
            native_pgid = lease["nativePgid"]
            self.addCleanup(self._kill_group_if_alive, native_pgid)
            self.assertEqual(outer.returncode, 0, "worker must exit naturally after reporting the timeout")
            self.assertTrue(release.exists(), "the result event was processed before worker release")
            self.assertTrue(marker.exists(), "synthetic native child confirmed termination")
            self.assertTrue(self._wait_group_gone(outer.pid))
            self.assertTrue(self._wait_group_gone(native_pgid))
            runner._seal.assert_not_called()
            reports = self._reports(journal)
            stopped = next(report for report in reports if report["type"] == "stopped")
            self.assertIs(stopped["payload"]["stopped"], True)
            self.assertEqual(stopped["payload"]["stopReason"], "time_limit")
            self.assertFalse(any(report["type"] in {"failed", "completed"} for report in reports))
            self.assertFalse((root / "workspaces" / "attempt-completed-timeout" / ".runner-tmp").exists())
            self.evidence_cases.append({
                "name": "confirmed-native-timeout-terminal-is-time-limit",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "nativePid": lease["nativePid"],
                "nativePgid": native_pgid,
                "nativeTerminationConfirmed": True,
                "timeoutMappedToTimeLimit": True,
                "workerExitedNaturally": True,
                "tempDirectoryRemoved": True,
                "sealCalled": False,
            })

    def test_failure_without_native_identity_reports_uncertain_and_keeps_temp(self):
        with tempfile.TemporaryDirectory(prefix="agent-lifecycle-unknown-") as directory:
            root = Path(directory)
            material = {"schemaVersion": "studio.message.v1", "attemptId": "attempt-unknown",
                        "packet": {"id": "packet-unknown"}, "assets": []}
            runner, api, journal, request, _marker, launched, launch = self._runner(
                root, "attempt-unknown", "no-native", "plan", 30, material)
            with mock.patch("runners.agent.sandbox_probe", return_value={"passed": True}), \
                 mock.patch("runners.agent.subprocess.Popen", side_effect=launch), \
                 mock.patch("runners.agent.process_output_lines", side_effect=lambda process:
                            runner_common.process_output_lines(process, timeout=0.05,
                                                               max_output_bytes=4096)):
                self.assertFalse(runner.accept_claim(request, "store-lifecycle"))

            self.assertEqual(len(launched), 1)
            outer = launched[0]
            self.assertEqual(outer.returncode, 7)
            self.assertTrue(self._wait_group_gone(outer.pid))
            temp_root = root / "workspaces" / "attempt-unknown" / ".runner-tmp"
            self.assertTrue(temp_root.is_dir(), "unknown native stop outcome must retain its temp directory")
            failed = next(report for report in self._reports(journal) if report["type"] == "failed")
            self.assertIs(failed["payload"]["stopped"], False)
            with journal._connect() as db:
                raw = db.execute("SELECT value FROM metadata WHERE key=?",
                                  ("agentWorkerIdentity:attempt-unknown",)).fetchone()
                diagnostic = db.execute("SELECT value FROM metadata WHERE key=?",
                                        (failed["payload"]["diagnosticRef"],)).fetchone()[0]
            summary = json.loads(diagnostic)
            self.assertIsNone(summary["nativeStatus"])
            self.assertEqual(summary["providerBridge"]["failures"][0]["kind"], "timeout")
            self.assertEqual(summary["workerExitCode"], 7)
            local_identity = json.loads(raw[0])
            self.assertEqual(local_identity["processId"], outer.pid)
            self.assertEqual(local_identity["processGroupId"], outer.pid)
            self.assertTrue(local_identity["processStartTime"])
            self.evidence_cases.append({
                "name": "failure-without-native-identity",
                "status": "passed",
                "outerPid": outer.pid,
                "outerPgid": outer.pid,
                "outerReturnCode": outer.returncode,
                "outerGroupGone": True,
                "failedStopped": False,
                "tempDirectoryRetained": True,
                "localWorkerIdentityRecordedSeparately": True,
            })


if __name__ == "__main__":
    unittest.main()

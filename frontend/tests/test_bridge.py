"""No-inference bridge tests. Run: python -m unittest discover -s tests -p 'test_bridge.py'.

All Codex process/RPC calls and HTTP request transports are mocked. State files
live in temporary directories; these tests never open a socket or a real thread.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import queue
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("workbench_bridge", ROOT / "bridge/server.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def envelope(store=None, **overrides):
    payload = {
        "version": 1,
        "taskId": "velvet-eclipse",
        "submissionId": "submission-1",
        "threadId": "thread-test",
        "baseRevision": 0,
        "draftRevision": 1,
        "sourceBaseline": "baseline-test",
        "storeId": store.identity() if store else "store-test",
        "snapshot": {
            "revision": 1,
            "objects": {"player": {"speed": 100}},
            "sourceManifest": json.loads((ROOT / "tools/velvet-source-lock.json").read_text()),
        },
        "items": [{"id": "project", "instruction": "Review this frozen revision."}],
    }
    payload.update(overrides)
    return payload


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = bridge.Store(self.path, "codex", "thread-test")

    def test_same_id_same_payload_is_idempotent(self):
        payload = envelope(self.store)
        self.assertTrue(self.store.accept(payload))
        self.assertFalse(self.store.accept(copy.deepcopy(payload)))
        self.assertEqual(self.store.revision(), 1)
        self.assertEqual(self.store.get(payload["submissionId"])["payload"], payload)


    def test_reusing_id_for_different_payload_is_rejected(self):
        payload = envelope(self.store)
        self.store.accept(payload)
        changed = copy.deepcopy(payload)
        changed["snapshot"]["objects"]["player"]["speed"] = 999
        with self.assertRaises(bridge.Conflict):
            self.store.accept(changed)
        self.assertEqual(self.store.get(payload["submissionId"])["payload"], payload)

    def test_mutating_callers_snapshot_cannot_mutate_saved_payload(self):
        payload = envelope(self.store)
        self.store.accept(payload)
        payload["snapshot"]["objects"]["player"]["speed"] = 999
        saved = self.store.get(payload["submissionId"])
        self.assertEqual(saved["payload"]["snapshot"]["objects"]["player"]["speed"], 100)

    def test_stale_revision_is_rejected_after_completed_submission(self):
        self.store.accept(envelope(self.store))
        self.store.update("submission-1", "succeeded", {"turnId": "turn-1"})
        with self.assertRaises(bridge.Conflict):
            self.store.accept(envelope(self.store, submissionId="submission-2"))
        self.assertTrue(self.store.accept(envelope(self.store, submissionId="submission-2", baseRevision=1)))
        self.assertEqual(self.store.revision(), 2)

    def test_active_or_uncertain_submission_blocks_new_ids(self):
        self.store.accept(envelope(self.store))
        for state in ("accepted", "processing", "uncertain"):
            with self.subTest(state=state):
                self.store.update("submission-1", state, {})
                with self.assertRaises(bridge.Conflict):
                    self.store.accept(envelope(self.store, submissionId="submission-2", baseRevision=1))

    def test_restart_preserves_payload_identity_revision_and_turn_id(self):
        payload = envelope(self.store)
        self.store.accept(payload)
        self.store.update("submission-1", "processing", {"turnId": "turn-known", "message": "Working"})
        restarted = bridge.Store(self.path, "codex", "thread-test")
        record = restarted.get("submission-1")
        self.assertEqual(record["state"], "uncertain")
        self.assertEqual(record["result"]["turnId"], "turn-known")
        self.assertEqual(record["payload"], payload)
        self.assertEqual(restarted.identity(), self.store.identity())
        self.assertEqual(restarted.revision(), 1)
        self.assertFalse(restarted.accept(payload))

    def test_restart_leaves_terminal_result_unchanged(self):
        self.store.accept(envelope(self.store))
        self.store.update("submission-1", "succeeded", {"turnId": "turn-known"})
        restarted = bridge.Store(self.path, "codex", "thread-test")
        self.assertEqual(restarted.get("submission-1")["state"], "succeeded")

    def test_state_cannot_be_rebound_to_another_mode_or_thread(self):
        for mode, thread in (("demo", "thread-test"), ("codex", "another-thread")):
            with self.subTest(mode=mode, thread=thread), self.assertRaises(ValueError):
                bridge.Store(self.path, mode, thread)


class SourceIdentityTests(unittest.TestCase):
    def test_current_source_change_changes_baseline_without_touching_git_index(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);project=base/'game';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            source=project/'player.gd';source.write_text('speed = 100\n')
            subprocess.run(['git','-C',str(project),'add','player.gd'],check=True)
            index=project/'.git'/'index';index_before=index.read_bytes()
            frontend=base/'frontend';tools=frontend/'tools';tools.mkdir(parents=True)
            expected=bridge.git_baseline.identity_file(source)
            (tools/'velvet-source-lock.json').write_text(json.dumps([{'path':'player.gd','gitBlob':expected}]))
            with mock.patch.object(bridge,'ROOT',frontend):
                baseline_before,matches_before=bridge.source_baseline(project)
                source.write_text('speed = 150\n')
                baseline_after,matches_after=bridge.source_baseline(project)
            self.assertTrue(matches_before)
            self.assertFalse(matches_after)
            self.assertNotEqual(baseline_before,baseline_after)
            self.assertEqual(index.read_bytes(),index_before)


class ProtocolTests(unittest.TestCase):
    def schema_writer(self, compatible=True):
        def write_schema(command, **kwargs):
            folder = Path(command[command.index("--out") + 1]) / "v2"
            folder.mkdir()
            data = {"properties": {"toolOutput": {}} if compatible else {},
                    "definitions": {"TurnToolOutput": {"properties": {"name": {}, "output": {}}}}}
            (folder / "TurnStartParams.json").write_text(json.dumps(data))
        return write_schema

    def test_connect_initializes_and_resumes_but_never_starts_a_turn(self):
        process = mock.Mock(stdin=io.StringIO(), stdout=io.StringIO())
        calls = []
        def rpc(client, method, params):
            calls.append((method, params))
            return {"thread": {"cwd": str(ROOT)}} if method == "thread/resume" else {}
        with mock.patch.object(bridge.subprocess, "run", side_effect=self.schema_writer()), \
             mock.patch.object(bridge.subprocess, "check_output", return_value="codex-cli mocked"), \
             mock.patch.object(bridge.subprocess, "Popen", return_value=process) as popen, \
             mock.patch.object(bridge.threading, "Thread"), \
             mock.patch.object(bridge.Codex, "rpc", rpc):
            client = bridge.Codex("thread-test", ROOT)
        self.assertEqual([method for method, _ in calls], ["initialize", "thread/resume"])
        self.assertEqual(calls[-1][1]["threadId"], "thread-test")
        self.assertEqual(popen.call_args.kwargs["cwd"], str(ROOT))
        self.assertEqual(client.thread, "thread-test")

    def test_missing_tool_output_capability_fails_before_process_start(self):
        with mock.patch.object(bridge.subprocess, "run", side_effect=self.schema_writer(False)), \
             mock.patch.object(bridge.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "toolOutput"):
                bridge.Codex("thread-test", ROOT)
        popen.assert_not_called()

    def test_mismatched_resumed_cwd_fails_closed(self):
        process = mock.Mock(stdin=io.StringIO(), stdout=io.StringIO())
        with mock.patch.object(bridge.subprocess, "run", side_effect=self.schema_writer()), \
             mock.patch.object(bridge.subprocess, "check_output", return_value="codex-cli mocked"), \
             mock.patch.object(bridge.subprocess, "Popen", return_value=process), \
             mock.patch.object(bridge.threading, "Thread"), \
             mock.patch.object(bridge.Codex, "rpc", side_effect=[{}, {"thread": {"cwd": "/different-project"}}]):
            with self.assertRaisesRegex(RuntimeError, "cwd"):
                bridge.Codex("thread-test", ROOT)
        process.terminate.assert_called_once()

    def make_client(self, status="idle"):
        client = bridge.Codex.__new__(bridge.Codex)
        client.thread = "thread-test"
        client.events = queue.Queue()
        client.rpc = mock.Mock(side_effect=[{"thread": {"status": {"type": status}}}, {"turn": {"id": "turn-1"}}])
        return client

    def test_non_idle_or_unknown_status_never_starts_turn(self):
        for status in ("active", "notLoaded", "systemError", None):
            with self.subTest(status=status):
                client = self.make_client(status)
                with self.assertRaises(bridge.Conflict):
                    client.submit(envelope(), mock.Mock())
                self.assertEqual([call.args[0] for call in client.rpc.call_args_list], ["thread/read"])

    def test_submit_starts_same_thread_with_empty_input_and_frozen_tool_output(self):
        client = self.make_client()
        client.events.put({"method": "item/completed", "params": {"threadId": "other-thread", "turnId": "turn-1", "item": {"type": "agentMessage", "text": "Ignore"}}})
        client.events.put({"method": "item/completed", "params": {"threadId": "thread-test", "turnId": "turn-1", "item": {"type": "agentMessage", "text": "Review this result."}}})
        client.events.put({"method": "turn/completed", "params": {"threadId": "thread-test", "turn": {"id": "turn-1", "status": "completed"}}})
        payload, store = envelope(), mock.Mock()
        state, result = client.submit(payload, store)
        method, params = client.rpc.call_args_list[1].args
        self.assertEqual(method, "turn/start")
        self.assertEqual(params["threadId"], "thread-test")
        self.assertEqual(params["input"], [])
        self.assertEqual(params["toolOutput"]["name"], "dna_workbench_submit")
        self.assertIsNone(params["toolOutput"]["namespace"])
        self.assertEqual(json.loads(params["toolOutput"]["output"]), payload)
        self.assertEqual(state, "succeeded")
        self.assertEqual(result["response"], "Review this result.")
        self.assertEqual(result["items"][0]["status"], "review_required")
        self.assertEqual(store.update.call_args.args[2]["turnId"], "turn-1")

    def test_server_request_id_collision_is_rejected_not_a_response(self):
        client = bridge.Codex.__new__(bridge.Codex)
        client.pending, client.events = {1: queue.Queue()}, queue.Queue()
        client.write = mock.Mock()
        request = {"id": 1, "method": "item/commandExecution/requestApproval", "params": {}}
        response = {"id": 1, "result": {"ok": True}}
        client.proc = SimpleNamespace(stdout=io.StringIO(json.dumps(request) + "\n" + json.dumps(response) + "\n"))
        client.read()
        self.assertEqual(client.pending[1].get_nowait(), response)
        client.write.assert_called_once()
        self.assertIn("error", client.write.call_args.args[0])


class HttpValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = bridge.Store(Path(self.temp.name) / "state.sqlite3", "demo", "thread-test")
        self.app = SimpleNamespace(token="session-secret", thread="thread-test", store=self.store,
                                   baseline=lambda: "baseline-test", run=mock.Mock())

    def request(self, payload=None, **headers):
        handler = bridge.Handler.__new__(bridge.Handler)
        handler.server = SimpleNamespace(server_port=8765, app=self.app)
        handler.path = "/api/submit"
        body = json.dumps(payload if payload is not None else envelope(self.store)).encode()
        handler.headers = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765",
                           "X-Workbench-Token": "session-secret", "Content-Type": "application/json",
                           "Content-Length": str(len(body)), **headers}
        handler.rfile = io.BytesIO(body)
        handler.send_json = mock.Mock()
        return handler

    def test_host_origin_and_token_are_enforced_before_processing(self):
        for header, value in (("Host", "attacker.test:8765"), ("Origin", "https://attacker.test"),
                              ("X-Workbench-Token", "wrong-token"), ("Origin", "null")):
            with self.subTest(header=header, value=value):
                handler = self.request(**{header: value})
                handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], 403)
        self.assertIsNone(self.store.last())

    def test_valid_submission_is_durable_before_worker_starts_and_replay_is_not_resent(self):
        payload = envelope(self.store)
        def start_worker(**kwargs):
            self.assertEqual(self.store.get(payload["submissionId"])["state"], "accepted")
            return mock.Mock()
        with mock.patch.object(bridge.threading, "Thread", side_effect=start_worker) as worker:
            first = self.request(payload)
            first.do_POST()
            second = self.request(payload)
            second.do_POST()
        self.assertEqual(first.send_json.call_args.args[0], 202)
        self.assertEqual(second.send_json.call_args.args[0], 202)
        worker.assert_called_once()
        self.assertEqual(self.store.revision(), 1)
        self.app.run.assert_not_called()

    def test_execution_config_cannot_be_supplied_by_browser(self):
        for key in ("cwd", "sandboxPolicy", "approvalPolicy", "config"):
            with self.subTest(key=key):
                handler = self.request(envelope(self.store, **{key: "unsafe"}))
                handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], 400)
        self.assertIsNone(self.store.last())

    def test_wrong_thread_store_or_baseline_is_rejected(self):
        for changes, expected in (({"threadId": "another-thread"}, 400),
                                  ({"storeId": "another-store"}, 409),
                                  ({"sourceBaseline": "stale-source"}, 409)):
            with self.subTest(changes=changes):
                handler = self.request(envelope(self.store, **changes))
                handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], expected)
        self.assertIsNone(self.store.last())

    def test_missing_or_stale_source_manifest_rejects_new_submission(self):
        for stale in (None, [], [{"path": "old-source.gd", "gitBlob": "git:blob:stale"}]):
            with self.subTest(manifest=stale):
                payload = envelope(self.store)
                if stale is None:
                    del payload["snapshot"]["sourceManifest"]
                else:
                    payload["snapshot"]["sourceManifest"] = stale
                handler = self.request(payload)
                with mock.patch.object(bridge.threading, "Thread") as worker:
                    handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], 409)
                self.assertIn("old or unknown source adapter", handler.send_json.call_args.args[1]["error"])
                worker.assert_not_called()
        self.assertIsNone(self.store.last())

    def test_exact_replay_of_existing_old_manifest_returns_record_without_resending(self):
        payload = envelope(self.store, sourceBaseline="original-baseline")
        payload["snapshot"]["sourceManifest"] = [{"path": "old-source.gd", "gitBlob": "git:blob:old"}]
        self.store.accept(payload)
        self.store.update(payload["submissionId"], "succeeded", {"turnId": "original-turn"})
        handler = self.request(payload)
        with mock.patch.object(bridge.threading, "Thread") as worker:
            handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 202)
        self.assertEqual(handler.send_json.call_args.args[1]["result"]["turnId"], "original-turn")
        self.assertEqual(self.store.revision(), 1)
        worker.assert_not_called()

    def test_all_response_headers_block_framing_and_mime_sniffing(self):
        handler = bridge.Handler.__new__(bridge.Handler)
        handler.request_version = "HTTP/1.1"
        handler.wfile = io.BytesIO()
        handler.end_headers()
        headers = handler.wfile.getvalue().decode("latin-1")
        self.assertIn("X-Frame-Options: DENY\r\n", headers)
        self.assertIn("Content-Security-Policy: frame-ancestors 'none'\r\n", headers)
        self.assertIn("X-Content-Type-Options: nosniff\r\n", headers)

    def test_invalid_envelopes_and_content_types_are_rejected(self):
        invalid = [envelope(self.store, items=[]), envelope(self.store, baseRevision=True),
                   envelope(self.store, taskId="another-task"), envelope(self.store, draftRevision=2)]
        for payload in invalid:
            with self.subTest(payload=payload):
                handler = self.request(payload)
                handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], 400)
        handler = self.request(**{"Content-Type": "text/plain"})
        handler.do_POST()
        self.assertEqual(handler.send_json.call_args.args[0], 400)
        self.assertIsNone(self.store.last())


class RecoveryTests(unittest.TestCase):
    def test_completion_timeout_preserves_known_turn_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = bridge.Store(Path(folder) / "state.sqlite3", "codex", "thread-test")
            payload = envelope(store)
            store.accept(payload)
            store.update("submission-1", "processing", {"turnId": "known-turn"})
            app = bridge.App.__new__(bridge.App)
            app.store = store
            app.project_root = ROOT
            app.baseline = lambda: "baseline-test"
            app.codex = mock.Mock()
            app.codex.submit.side_effect = queue.Empty()
            with mock.patch.object(bridge, "source_baseline", return_value=("baseline-test", True)):
                app.run(payload)
            saved = store.get("submission-1")
            self.assertEqual(saved["state"], "uncertain")
            self.assertEqual(saved["result"]["turnId"], "known-turn")

    def test_existing_process_lease_fails_before_store_recovery_or_codex_start(self):
        with tempfile.TemporaryDirectory() as folder:
            state = str(Path(folder) / "state.sqlite3")
            with mock.patch("sys.argv", ["server.py", "--state", state]), \
                 mock.patch.object(bridge, "open", mock.mock_open(), create=True), \
                 mock.patch.object(bridge.os, "umask"), \
                 mock.patch.object(bridge.fcntl, "flock", side_effect=BlockingIOError()), \
                 mock.patch.object(bridge, "Store") as store, \
                 mock.patch.object(bridge, "App") as app, \
                 mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    bridge.main()
            store.assert_not_called()
            app.assert_not_called()


if __name__ == "__main__":
    unittest.main()

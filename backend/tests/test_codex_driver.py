from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.codex_driver import CodexDriver


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / "workspace"
        self.cwd.mkdir()
        self.server = self.root / "fake-codex"
        self.log = self.root / "rpc.jsonl"
        self._write_server("normal")

    def tearDown(self):
        self.temp.cleanup()

    def _write_server(self, mode):
        script = (
            """#!/usr/bin/env python3
import json, subprocess, sys, time
mode = __MODE__
survived = __SURVIVED__
log = __LOG__
def send(o): print(json.dumps(o), flush=True)
for line in sys.stdin:
 m=json.loads(line)
 with open(log,"a") as f: f.write(json.dumps(m)+"\\n")
 method=m.get("method")
 if m.get("id") is not None:
  if method == "initialize": send({"jsonrpc":"2.0","id":m["id"],"result":{}})
  elif method == "thread/start": send({"jsonrpc":"2.0","id":m["id"],"result":{"thread":{"id":"thread-test"}}})
  elif method == "turn/start":
   send({"jsonrpc":"2.0","id":m["id"],"result":{"turn":{"id":"turn-test"}}})
   if mode in ("approval", "unknown_request"):
    request_method = "item/fileChange/requestApproval" if mode == "approval" else "server/unknownRequest"
    send({"jsonrpc":"2.0","id":500,"method":request_method,"params":{"itemId":"item-1"}})
    reply=json.loads(sys.stdin.readline())
    with open(log,"a") as f: f.write(json.dumps(reply)+"\\n")
   if mode in ("hang", "hang_child"):
    if mode == "hang_child":
     subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5); open(" + repr(survived) + ", 'w').write('survived')"])
    while True: time.sleep(.1)
   if mode in ("recoverable_network", "hang_network", "native_failed"):
    error = {"message":"Connection reset while contacting provider","code":"network_error","codexErrorInfo":{"kind":"transport","message":"socket closed","privatePayload":"must not escape"},"willRetry":mode != "native_failed","input":"must not escape"}
    send({"jsonrpc":"2.0","method":"error","params":{"error":error,"request":{"image":"must not escape"}}})
   if mode == "hang_network":
    while True: time.sleep(.1)
   send({"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{"delta":"probe response"}})
   if mode == "lifecycle_sensitive":
    send({"jsonrpc":"2.0","method":"item/started","params":{"item":{"id":"private-id","type":"agentMessage","phase":"commentary","text":"PRIVATE_MESSAGE_BODY","path":"/private/workspace"}}})
    send({"jsonrpc":"2.0","method":"item/completed","params":{"item":{"id":"private-id","type":"agentMessage","phase":"commentary","text":"PRIVATE_MESSAGE_BODY","path":"/private/workspace"}}})
    send({"jsonrpc":"2.0","method":"item/started","params":{"item":{"id":"private-tool-id","type":"mcpToolCall","server":"private-server","tool":"private-tool","arguments":{"secret":"PRIVATE_TOOL_INPUT"}}}})
    send({"jsonrpc":"2.0","method":"item/completed","params":{"item":{"id":"private-tool-id","type":"mcpToolCall","server":"private-server","tool":"private-tool","output":"PRIVATE_TOOL_OUTPUT"}}})
   if mode == "lifecycle_many":
    for _ in range(45):
     send({"jsonrpc":"2.0","method":"item/started","params":{"item":{"type":"plan","phase":"planning","text":"PRIVATE_PLAN_BODY"}}})
   if mode == "final_json":
    send({"jsonrpc":"2.0","method":"item/completed","params":{"item":{"type":"agentMessage","phase":"commentary","text":"Working on a plan"}}})
    send({"jsonrpc":"2.0","method":"item/completed","params":{"item":{"type":"agentMessage","phase":"final_answer","text":json.dumps({"status":"READY"})}}})
   terminal = {"id":"turn-test","status":"failed","error":{"message":"provider rejected request","code":"request_rejected","detail":"preserve this native turn error"}} if mode == "native_failed" else {"id":"turn-test","status":"completed"}
   send({"jsonrpc":"2.0","method":"turn/completed","params":{"threadId":"thread-test","turn":terminal}})
  elif method == "turn/interrupt": send({"jsonrpc":"2.0","id":m["id"],"result":{}})
""".replace("__MODE__", repr(mode))
            .replace("__LOG__", repr(str(self.log)))
            .replace("__SURVIVED__", repr(str(self.root / "child-survived")))
        )
        self.server.write_text(script)
        self.server.chmod(self.server.stat().st_mode | stat.S_IXUSR)

    def _run(self, packet=None, **kwargs):
        disabled = kwargs.pop("disabled_mcp_servers", None)
        profile = kwargs.pop("execution_profile", None)
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        with patch("backend.codex_driver.shutil.which", return_value=str(self.server)):
            return CodexDriver(
                self.cwd,
                timeout=kwargs.pop("timeout", 2),
                disabled_mcp_servers=disabled,
                execution_profile=profile,
                reasoning_effort=reasoning_effort,
            ).run(packet or {"test_data": True}, **kwargs)

    def test_frozen_packet_is_sent_and_turn_completion_is_not_verification(self):
        result = self._run({"test_data": True, "proposalRevision": 7})
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        turn = next(call for call in calls if call.get("method") == "turn/start")
        sent_text = turn["params"]["input"][0]["text"]
        self.assertIn('"proposalRevision":7', sent_text)
        self.assertEqual(result["sessionId"], "thread-test")
        self.assertEqual(result["turnId"], "turn-test")
        self.assertEqual(result["status"], "completed")
        self.assertIn("probe response", result["response"])
        self.assertFalse(result["diagnostics"]["verificationCertified"])
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])

    def test_final_message_boundary_excludes_commentary_for_planner_json(self):
        self._write_server("final_json")
        result = self._run(execution_profile="managed_read_only")
        self.assertEqual(json.loads(result["response"]), {"status": "READY"})
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        start = next(call for call in calls if call.get("method") == "thread/start")
        self.assertEqual(start["params"]["sandbox"], "read-only")
        self.assertEqual(start["params"]["approvalPolicy"], "on-request")
        self.assertFalse(start["params"]["config"]["features"]["multi_agent"])

    def test_recoverable_native_network_error_is_preserved_without_stopping_turn(self):
        self._write_server("recoverable_network")
        result = self._run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["response"], "probe response")
        errors = result["diagnostics"]["nativeErrors"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "network_error")
        self.assertTrue(errors[0]["willRetry"])
        self.assertEqual(errors[0]["codexErrorInfo"]["kind"], "transport")
        self.assertNotIn("privatePayload", str(errors))
        self.assertNotIn("must not escape", str(errors))

    def test_item_lifecycle_keeps_only_safe_type_phase_and_timing(self):
        self._write_server("lifecycle_sensitive")
        result = self._run()
        events = result["diagnostics"]["itemLifecycle"]
        self.assertEqual(
            [(event["event"], event["type"]) for event in events],
            [("started", "agentMessage"), ("completed", "agentMessage"),
             ("started", "mcpToolCall"), ("completed", "mcpToolCall")],
        )
        self.assertEqual(events[0]["phase"], "commentary")
        self.assertTrue(all(isinstance(event["elapsedSeconds"], (int, float)) for event in events))
        # The ordinary response may contain agent text by design; this checks
        # that the newly added lifecycle evidence itself stays metadata-only.
        serialized = json.dumps(result["diagnostics"]["itemLifecycle"])
        for private_value in (
            "PRIVATE_MESSAGE_BODY", "PRIVATE_TOOL_INPUT", "PRIVATE_TOOL_OUTPUT",
            "/private/workspace", "private-server", "private-tool",
        ):
            self.assertNotIn(private_value, serialized)

    def test_item_lifecycle_evidence_is_bounded(self):
        self._write_server("lifecycle_many")
        result = self._run()
        self.assertEqual(len(result["diagnostics"]["itemLifecycle"]), 40)

    def test_nonretryable_native_error_and_failed_turn_are_retained(self):
        self._write_server("native_failed")
        result = self._run()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diagnostics"]["nativeErrors"][0]["willRetry"], False)
        self.assertEqual(
            result["diagnostics"]["nativeTurnError"],
            {"message": "provider rejected request", "code": "request_rejected",
             "detail": "preserve this native turn error"},
        )

    def test_timeout_retains_native_network_error_evidence(self):
        self._write_server("hang_network")
        # Leave enough time for process startup and the initialize/thread/turn
        # handshake under suite load; only the post-error fake stream should
        # consume the timeout being tested here.
        result = self._run(timeout=2.0)
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["diagnostics"]["error"])
        self.assertEqual(result["diagnostics"]["nativeErrors"][0]["code"], "network_error")
        self.assertTrue(result["diagnostics"]["nativeErrors"][0]["willRetry"])

    def test_independent_session_does_not_inherit_parent_context(self):
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "parent-thread",
            "CODEX_SESSION_ID": "parent-session", "CODEX_APP_TOOLS_PIPE_PATH": "/parent/pipe",
            "GM_TEST_PROVIDER_MARKER": "retained-provider-setting"}), patch(
                "backend.codex_driver.subprocess.Popen", wraps=subprocess.Popen
            ) as launch:
            self._run()
        child_env = launch.call_args.kwargs["env"]
        for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_APP_TOOLS_PIPE_PATH"):
            self.assertNotIn(key, child_env)
        self.assertEqual(child_env["GM_TEST_PROVIDER_MARKER"], "retained-provider-setting")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        turn = next(call for call in calls if call.get("method") == "turn/start")
        self.assertIn("Do not spawn subagents", turn["params"]["input"][0]["text"])

    def test_approval_request_is_declined_and_reported(self):
        self._write_server("approval")
        result = self._run()
        requests = result["diagnostics"]["approvalRequests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["status"], "uncertain")
        self.assertTrue(result["diagnostics"]["effectsMayHaveOccurred"])
        self.assertEqual(
            result["diagnostics"]["approvalRequests"][0]["method"],
            "item/fileChange/requestApproval",
        )

    def test_unknown_server_request_fails_closed_and_reports_uncertainty(self):
        self._write_server("unknown_request")
        result = self._run()
        self.assertEqual(result["status"], "uncertain")
        self.assertTrue(result["diagnostics"]["protocolErrors"])
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])
        self.assertEqual(
            result["diagnostics"]["protocolErrors"][0]["error"]["code"], -32601
        )

    def test_uploaded_image_uses_schema_local_image_input_and_process_lease_precedes_rpc(
        self,
    ):
        image = self.root / "reference.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"reference")
        order = []

        def on_started(lease):
            order.append(("lease", lease))

        result = self._run(reference_images=[image], on_process_started=on_started)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        turn = next(call for call in calls if call.get("method") == "turn/start")
        image_inputs = [
            item for item in turn["params"]["input"] if item.get("type") == "localImage"
        ]
        self.assertEqual(
            image_inputs, [{"type": "localImage", "path": str(image.resolve())}]
        )
        self.assertEqual(order[0][0], "lease")
        self.assertIn("executionLease", result["diagnostics"])
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])

    def test_image_paths_fail_closed_before_process_launch(self):
        image = self.root / "reference.png"
        image.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            self._run(reference_images=[image])

    def test_process_lease_callback_failure_prevents_rpc_and_cleans_up(self):
        def fail(_lease):
            raise RuntimeError("durable lease store unavailable")

        result = self._run(on_process_started=fail)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])
        self.assertFalse(self.log.exists())

    def test_timeout_terminates_child_and_marks_uncertain_work(self):
        self._write_server("hang")
        result = self._run(timeout=0.3)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])
        self.assertFalse(result["diagnostics"]["verificationCertified"])

    def test_cancel_terminates_child(self):
        self._write_server("hang")
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        try:
            result = self._run(timeout=3, cancel_event=cancel)
        finally:
            timer.cancel()
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])

    def test_optional_mcp_disable_is_scoped_to_named_server(self):
        self._run(disabled_mcp_servers=["godot-mcp"])
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        start = next(call for call in calls if call.get("method") == "thread/start")
        self.assertEqual(
            start["params"]["config"],
            {"mcp_servers": {"godot-mcp": {"enabled": False}}},
        )
        self.assertNotIn("approvalPolicy", start["params"])
        self.assertNotIn("sandbox", start["params"])

    def test_server_managed_profile_sets_only_declared_sandbox_and_approval(self):
        self._run(execution_profile="managed_workspace_write")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        start = next(call for call in calls if call.get("method") == "thread/start")
        self.assertEqual(start["params"]["sandbox"], "workspace-write")
        self.assertEqual(start["params"]["approvalPolicy"], "on-request")
        self.assertNotIn("danger-full-access", str(start["params"]))

    def test_trusted_reasoning_effort_is_sent_only_on_turn_start(self):
        result = self._run(
            {"test_data": True, "effort": "max", "reasoningEffort": "ultra"},
            reasoning_effort="medium",
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        thread = next(call for call in calls if call.get("method") == "thread/start")
        turn = next(call for call in calls if call.get("method") == "turn/start")
        self.assertNotIn("effort", thread["params"])
        self.assertEqual(turn["params"]["effort"], "medium")
        self.assertEqual(result["commandEvidence"]["reasoningEffort"], "medium")

    def test_reasoning_effort_defaults_to_omitted_despite_packet_fields(self):
        result = self._run({"test_data": True, "effort": "max"})
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        turn = next(call for call in calls if call.get("method") == "turn/start")
        self.assertNotIn("effort", turn["params"])
        self.assertIsNone(result["commandEvidence"]["reasoningEffort"])

    def test_unsupported_reasoning_effort_is_rejected_before_process_launch(self):
        with (
            patch(
                "backend.codex_driver.shutil.which",
                side_effect=AssertionError("must not launch"),
            ),
            self.assertRaises(ValueError),
        ):
            CodexDriver(self.cwd, reasoning_effort="turbo")

    def test_unknown_execution_profile_is_rejected_before_process_launch(self):
        with self.assertRaises(ValueError):
            CodexDriver(self.cwd, execution_profile="danger-full-access")

    def test_timeout_kills_spawned_command_process_group(self):
        self._write_server("hang_child")
        result = self._run(timeout=0.3)
        time.sleep(1.6)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["diagnostics"]["childTerminationConfirmed"])
        self.assertEqual(result["diagnostics"]["terminationScope"], "process_group")
        self.assertFalse(
            (self.root / "child-survived").exists(), "spawned child outlived timeout"
        )

    def test_invalid_workspace_fails_before_process_launch(self):
        with (
            patch(
                "backend.codex_driver.shutil.which",
                side_effect=AssertionError("must not launch"),
            ),
            self.assertRaises(ValueError),
        ):
            CodexDriver(self.root / "missing").run({"test_data": True})


if __name__ == "__main__":
    unittest.main()

"""Bounded live native turn/start ACK-loss experiment.

This harness drops only the successful response to the one outbound
turn/start request. It does not alter production code or synthesize a model
response. The model runs through the normal ManagedNativeContext and typed
StaticToolBroker boundary in a disposable read-only planning workspace.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.codex_driver import CodexDriver
from runners.common import stop_process_group
from runners.native_adapter import ManagedNativeContext
from runners.static_tools import StaticToolBroker


MODEL = "gpt-6-luna"
PROVIDER = "my_proxy"
EFFORT = "max"
PRE_ACK_WATCHDOG_SECONDS = 20
POST_ACK_WATCHDOG_SECONDS = 15
DRIVER_HARD_TIMEOUT_SECONDS = 35


class AckDropState:
    def __init__(self, ack_event: threading.Event):
        self.lock = threading.Lock()
        self.ack_event = ack_event
        self.native_process = None
        self.native_popen_count = 0
        self.method_counts: dict[str, int] = {}
        self.turn_start_request_id = None
        self.turn_start_thread_id = None
        self.turn_start_model = None
        self.turn_start_effort = None
        self.response_seen = False
        self.native_identity = None
        self.response_status = None
        self.ack_observed_monotonic = None

    def sent(self, value: str) -> None:
        for raw in value.splitlines():
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(message, dict):
                continue
            method = message.get("method")
            if not isinstance(method, str):
                continue
            params = message.get("params") or {}
            with self.lock:
                self.method_counts[method] = self.method_counts.get(method, 0) + 1
                if method == "turn/start":
                    self.turn_start_request_id = message.get("id")
                    self.turn_start_thread_id = params.get("threadId") if isinstance(params, dict) else None
                    self.turn_start_model = params.get("model") if isinstance(params, dict) else None
                    self.turn_start_effort = params.get("effort") if isinstance(params, dict) else None

    def received(self, value: str) -> bool:
        """Return True only for the exact successful turn/start response."""
        try:
            message = json.loads(value)
        except (TypeError, ValueError):
            return False
        if not isinstance(message, dict):
            return False
        with self.lock:
            request_id = self.turn_start_request_id
            if request_id is None or message.get("id") != request_id:
                return False
            self.response_seen = True
            result = message.get("result")
            turn = result.get("turn", result) if isinstance(result, dict) else None
            turn_id = (turn.get("id") or turn.get("turnId")) if isinstance(turn, dict) else None
            if not isinstance(turn_id, str) or not turn_id:
                return False
            self.native_identity = {
                "threadId": self.turn_start_thread_id,
                "turnId": turn_id,
            }
            status = turn.get("status") if isinstance(turn.get("status"), str) else None
            self.response_status = status
            self.ack_observed_monotonic = time.monotonic()
        self.ack_event.set()
        return True


class StdinTap:
    def __init__(self, stream, state: AckDropState):
        self._stream, self._state = stream, state

    def write(self, value):
        self._state.sent(value)
        return self._stream.write(value)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class StdoutTap:
    def __init__(self, stream, state: AckDropState):
        self._stream, self._state = stream, state

    def readline(self, *args, **kwargs):
        while True:
            line = self._stream.readline(*args, **kwargs)
            if not line:
                return line
            if self._state.received(line):
                # Consume this exact response inside the trusted wrapper, then
                # continue forwarding every other native event/response.
                continue
            return line

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _native_app_server_command(args, executable: str) -> bool:
    command = args[0] if args else None
    if not isinstance(command, (list, tuple)):
        return False
    return (executable in command and "app-server" in command and "--stdio" in command)


def _group_exists(pgid: int | None) -> bool:
    if not isinstance(pgid, int) or pgid <= 0 or os.name != "posix":
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


def run() -> dict:
    result = {
        "schemaVersion": "studio.native-start-loss.v1",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "one live managed native turn; exact turn/start response dropped by a local stream wrapper",
        "requestedModel": MODEL,
        "requestedProvider": PROVIDER,
        "requestedEffort": EFFORT,
        "modelTurns": 0,
        "formalRoleAuthorizationProven": False,
        "candidateProduced": False,
        "passed": False,
    }
    ack_event = threading.Event()
    cancel_event = threading.Event()
    watchdog_stop = threading.Event()
    state = AckDropState(ack_event)
    context = None
    watchdog_thread = None
    watchdog_facts = {"preAckTimedOut": False, "postAckTimedOut": False}
    real_popen = subprocess.Popen
    context_closed = False

    def popen_tap(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        command = args[0] if args else kwargs.get("args")
        if context is not None and _native_app_server_command((command,), context.executable()):
            with state.lock:
                state.native_popen_count += 1
                state.native_process = process
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("native app-server did not expose expected stdio pipes")
            process.stdin = StdinTap(process.stdin, state)
            process.stdout = StdoutTap(process.stdout, state)
        return process

    def watchdog() -> None:
        pre_deadline = time.monotonic() + PRE_ACK_WATCHDOG_SECONDS
        while not watchdog_stop.is_set() and not ack_event.is_set():
            if time.monotonic() >= pre_deadline:
                watchdog_facts["preAckTimedOut"] = True
                cancel_event.set()
                return
            watchdog_stop.wait(0.05)
        if watchdog_stop.is_set():
            return
        post_deadline = time.monotonic() + POST_ACK_WATCHDOG_SECONDS
        while not watchdog_stop.is_set() and not cancel_event.is_set():
            if time.monotonic() >= post_deadline:
                watchdog_facts["postAckTimedOut"] = True
                cancel_event.set()
                return
            watchdog_stop.wait(0.05)

    try:
        with tempfile.TemporaryDirectory(prefix="studio-native-start-loss-") as folder:
            root = Path(folder).resolve()
            work = root / "work"
            work.mkdir(mode=0o700)
            (work / "planning-input.json").write_text(
                '{"scope":"read-only transport fault probe"}\n', encoding="utf-8")
            tool_tmp = root / "tool-tmp"
            tool_tmp.mkdir(mode=0o700)
            native_root = root / "native"
            context = ManagedNativeContext.create(native_root, PROVIDER, model=MODEL)
            broker = StaticToolBroker(work, "plan", [], tool_tmp)
            packet = {
                "operationKind": "PLANNING",
                "allowedFiles": [],
                "instruction": (
                    "This is a single transport fault probe. Reply with exactly "
                    "NATIVE-START-ACK-LOSS-20261013. Do not call tools, edit files, "
                    "run commands, delegate, or start another turn."
                ),
            }
            driver = CodexDriver(
                context.root,
                timeout=DRIVER_HARD_TIMEOUT_SECONDS,
                model=MODEL,
                model_provider=PROVIDER,
                reasoning_effort=EFFORT,
                execution_profile="managed_read_only",
                managed_native_context=context,
                static_tool_broker=broker,
            )
            watchdog_thread = threading.Thread(target=watchdog, name="ack-loss-watchdog", daemon=True)
            watchdog_thread.start()
            started = time.monotonic()
            with patch.object(subprocess, "Popen", popen_tap):
                native_result = driver.run(packet, cancel_event=cancel_event)
            elapsed = time.monotonic() - started
            watchdog_stop.set()
            watchdog_thread.join(timeout=2)

            with state.lock:
                process = state.native_process
                identity = dict(state.native_identity) if state.native_identity else None
                method_counts = dict(state.method_counts)
                native_popen_count = state.native_popen_count
                response_seen = state.response_seen
                response_status = state.response_status
                ack_elapsed = (state.ack_observed_monotonic - started
                               if state.ack_observed_monotonic is not None else None)
                turn_request_model = state.turn_start_model
                turn_request_effort = state.turn_start_effort

            diagnostics = native_result.get("diagnostics") if isinstance(native_result, dict) else {}
            diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
            native_group_stopped = bool(diagnostics.get("childTerminationConfirmed") is True)
            if process is not None and _group_exists(process.pid):
                stop_process_group(process.pid, process=process, grace_seconds=1.0)
            native_group_absent = process is not None and not _group_exists(process.pid)
            native_stopped = bool(process is not None and process.poll() is not None
                                  and native_group_stopped and native_group_absent)

            host = context.tool_host
            bridge = context.bridge
            context.close()
            context_closed = True
            host_stopped = bool(host is not None and host.process.poll() is not None)
            bridge_stopped = not bridge.thread.is_alive()
            result.update({
                "modelTurns": 1 if identity and identity.get("turnId") else 0,
                "driver": {
                    "status": native_result.get("status"),
                    "error": context.redact(diagnostics.get("error")),
                    "elapsedSeconds": round(elapsed, 3),
                    "hardTimeoutSeconds": DRIVER_HARD_TIMEOUT_SECONDS,
                    "turnStartAcknowledgedByDriver": diagnostics.get("turnStartAcknowledged"),
                    "threadStartReported": context.redact(diagnostics.get("threadStartReported")),
                    "nativeChildTerminationConfirmed": native_group_stopped,
                    "nativeExitCode": process.poll() if process is not None else None,
                    "rpcMethods": native_result.get("commandEvidence", {}).get("rpcMethods", []),
                },
                "injection": {
                    "nativeProcessCount": native_popen_count,
                    "outboundTurnStartCount": method_counts.get("turn/start", 0),
                    "outboundTurnInterruptCount": method_counts.get("turn/interrupt", 0),
                    "turnStartModel": turn_request_model,
                    "turnStartEffort": turn_request_effort,
                    "responseObservedByHarness": response_seen,
                    "responseDroppedBeforeDriver": bool(identity and response_seen),
                    "reportedTurnStatus": response_status,
                    "nativeIdentityObservedByHarness": identity,
                    "secondsFromDriverStartToNativeAck": round(ack_elapsed, 3) if ack_elapsed is not None else None,
                },
                "watchdog": {
                    "maxWaitForNativeAckSeconds": PRE_ACK_WATCHDOG_SECONDS,
                    "stopAfterNativeAckSeconds": POST_ACK_WATCHDOG_SECONDS,
                    "preAckTimedOut": watchdog_facts["preAckTimedOut"],
                    "postAckTimedOut": watchdog_facts["postAckTimedOut"],
                },
                "cleanup": {
                    "nativeProcessExited": bool(process is not None and process.poll() is not None),
                    "nativeProcessGroupAbsent": native_group_absent,
                    "nativeStopped": native_stopped,
                    "routingHostStopped": host_stopped,
                    "providerBridgeStopped": bridge_stopped,
                    "nativeCredentialsPersisted": context.secrets_on_disk(),
                },
                "staticToolCalls": broker.calls,
                "formalRoleAuthorizationProven": False,
                "candidateProduced": False,
            })
            expected = (
                result["modelTurns"] == 1
                and native_popen_count == 1
                and method_counts.get("turn/start", 0) == 1
                and turn_request_model == MODEL
                and turn_request_effort == EFFORT
                and identity is not None
                and diagnostics.get("turnStartAcknowledged") is None
                and response_seen
                and result["injection"]["responseDroppedBeforeDriver"]
                and native_result.get("status") == "cancelled"
                and watchdog_facts["postAckTimedOut"] is True
                and native_stopped
                and host_stopped
                and bridge_stopped
                and not result["cleanup"]["nativeCredentialsPersisted"]
                and result["candidateProduced"] is False
            )
            result["passed"] = bool(expected)
            del native_result
    except Exception as exc:
        error = str(exc)
        result["failure"] = {
            "type": type(exc).__name__,
            "message": context.redact(error) if context is not None else error[:1000],
        }
    finally:
        watchdog_stop.set()
        cancel_event.set()
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=2)
        if context is not None and not context_closed:
            try:
                context.close()
            except Exception as exc:
                result.setdefault("cleanupFailure", type(exc).__name__)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    evidence = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": evidence.get("passed"),
        "modelTurns": evidence.get("modelTurns"),
        "failure": evidence.get("failure"),
        "evidence": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise Studio HTTP/SSE restart and backup recovery on a disposable store.

This acceptance probe owns a temporary test-data store, uses a dynamically
assigned loopback port, and never starts a model, runner process, or Godot.
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.coordinator import Coordinator
from backend.server import REPO_ROOT, make_server
from runners.common import LocalJournal, RunnerError, RunnerLock
from tools.studio_store import backup, restore


EVIDENCE_PATH = REPO_ROOT / "evidence" / "workflow" / "studio-acceptance-transport-20261012.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command(store_id: str, command_id: str, kind: str, payload: dict,
            project_id: str | None = None) -> dict:
    message = {
        "schemaVersion": "studio.message.v1",
        "kind": "command",
        "type": kind,
        "storeId": store_id,
        "commandId": command_id,
        "payload": payload,
    }
    if project_id is not None:
        message["projectId"] = project_id
    return message


class LocalService:
    def __init__(self, coordinator: Coordinator, port: int = 0):
        self.coordinator = coordinator
        self.server = make_server(coordinator, port=port)
        self.handler_errors: list[dict] = []

        def capture_handler_error(_request, _client_address):
            error = sys.exc_info()[1]
            if error is not None:
                self.handler_errors.append({"type": type(error).__name__,
                                            "message": str(error)[:300]})

        self.server.handle_error = capture_handler_error
        self._handler_condition = threading.Condition()
        self.active_handlers = 0
        original_process_request_thread = self.server.process_request_thread

        def track_request_thread(request, client_address):
            with self._handler_condition:
                self.active_handlers += 1
            try:
                return original_process_request_thread(request, client_address)
            finally:
                with self._handler_condition:
                    self.active_handlers -= 1
                    self._handler_condition.notify_all()

        self.server.process_request_thread = track_request_thread
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name="studio-acceptance-http", daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.base = f"http://127.0.0.1:{self.port}"
        self.stopped = False
        self.last_stream_closed_at: float | None = None

    def request_json(self, method: str, path: str, *, body: dict | None = None,
                     token: str | None = None) -> tuple[int, dict]:
        headers = {"Origin": self.base, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if token is not None:
            headers["X-Workbench-Token"] = token
        request = urllib.request.Request(self.base + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def get(self, path: str) -> dict:
        status, value = self.request_json("GET", path)
        if status != 200:
            raise AssertionError(f"GET {path} returned {status}: {value}")
        return value

    def write(self, path: str, body: dict, token: str) -> dict:
        status, value = self.request_json("POST", path, body=body, token=token)
        if status != 200:
            raise AssertionError(f"POST {path} returned {status}: {value}")
        return value

    def runner_json(self, method: str, path: str, runner_id: str,
                    body: dict | None = None) -> tuple[int, dict]:
        headers = {"Origin": self.base, "Accept": "application/json",
                   "X-Runner-Token": self.coordinator.runner_token,
                   "X-Runner-Id": runner_id}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, headers=headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def runner_post_discard_ack(self, path: str, runner_id: str, body: dict) -> int:
        """Send a real runner POST and discard its JSON acknowledgement body."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        headers = {"Origin": self.base, "X-Runner-Token": self.coordinator.runner_token,
                   "X-Runner-Id": runner_id, "Content-Type": "application/json",
                   "Accept": "application/json"}
        try:
            connection.request("POST", path,
                body=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers)
            return connection.getresponse().status
        finally:
            connection.close()

    def stream(self, path: str, token: str, count: int, *,
               last_event_id: str | None = None,
               on_open: threading.Event | None = None) -> list[dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        headers = {"Origin": self.base, "X-Workbench-Token": token,
                   "Accept": "text/event-stream"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = last_event_id
        events = []
        current: dict[str, str] = {}
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            if response.status != 200:
                payload = response.read().decode("utf-8", errors="replace")
                raise AssertionError(f"SSE {path} returned {response.status}: {payload}")
            if not content_type.startswith("text/event-stream"):
                raise AssertionError(f"SSE content type was {content_type!r}")
            if on_open is not None:
                on_open.set()
            while len(events) < count:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if "data" in current:
                        event = json.loads(current["data"])
                        events.append({"id": current.get("id"), "event": event})
                    current = {}
                    continue
                if line.startswith(":"):
                    continue
                key, separator, value = line.partition(":")
                if separator:
                    current[key] = value.lstrip()
            if len(events) != count:
                raise AssertionError(f"SSE expected {count} events, received {len(events)}")
            return events
        finally:
            # Closing after the requested event count deliberately models a
            # client-side disconnect. The server must tolerate that socket loss.
            connection.close()
            self.last_stream_closed_at = time.monotonic()

    def stop(self) -> bool:
        if self.stopped:
            return (not self.thread.is_alive() and self.active_handlers == 0
                    and not self.handler_errors)
        # The current SSE server sends a keepalive at most every 15 seconds.
        # Let it observe the client-side disconnect before closing its database.
        if self.last_stream_closed_at is not None:
            deadline = self.last_stream_closed_at + 16.0
            with self._handler_condition:
                while self.active_handlers and time.monotonic() < deadline:
                    self._handler_condition.wait(timeout=min(0.25, deadline - time.monotonic()))
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)
        if self.active_handlers:
            # The stream itself is bounded at 45 seconds. Keep its coordinator
            # alive until the request thread exits, then close the store.
            deadline = (self.last_stream_closed_at or time.monotonic()) + 46.0
            with self._handler_condition:
                while self.active_handlers and time.monotonic() < deadline:
                    self._handler_condition.wait(timeout=min(0.25, deadline - time.monotonic()))
        self.coordinator.close()
        self.stopped = True
        return (not self.thread.is_alive() and self.active_handlers == 0
                and not self.handler_errors)


def assert_events(events: list[dict], project_id: str, sequences: list[int]) -> None:
    actual = [entry["event"]["sequence"] for entry in events]
    if actual != sequences:
        raise AssertionError(f"expected event sequences {sequences}, got {actual}")
    if any(entry["event"].get("projectId") != project_id for entry in events):
        raise AssertionError("SSE returned an event owned by another project")
    if any(entry.get("id") != str(entry["event"].get("sequence")) for entry in events):
        raise AssertionError("SSE id did not match its persisted sequence")


def write_evidence(evidence: dict) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


def main() -> int:
    evidence = {
        "schemaVersion": "studio.acceptance.transport.v1",
        "createdAt": utc_now(),
        "testData": True,
        "productionAuthorized": False,
        "productionStoreTouched": False,
        "modelStarted": False,
        "godotStarted": False,
        "scenarios": [],
        "services": [],
    }
    temp = tempfile.TemporaryDirectory(prefix="studio-acceptance-transport-")
    root = Path(temp.name)
    store_path = root / "original-store"
    coordinator = None
    service = None
    restored_service = None
    overall_error = None

    def passed(name: str, details: dict) -> None:
        evidence["scenarios"].append({"id": name, "status": "PASS", **details})

    def failed(name: str, error: BaseException) -> None:
        evidence["scenarios"].append({"id": name, "status": "FAIL",
                                      "error": f"{type(error).__name__}: {error}"})

    try:
        coordinator = Coordinator(REPO_ROOT, state_root=store_path, test_data=True)
        initial_workspace = coordinator.workspace_summary()
        if not initial_workspace["testData"] or initial_workspace["productionAuthorized"]:
            raise AssertionError("acceptance store is not isolated as test-only")
        old_store_id = coordinator.store_id
        service = LocalService(coordinator)
        evidence["services"].append({"kind": "http", "host": "127.0.0.1",
                                     "port": service.port, "testData": True})
        handshake = service.get("/api/v1/handshake")
        if handshake["storeId"] != old_store_id or not handshake["writable"]:
            raise AssertionError("initial test-store handshake was inconsistent")
        old_token = handshake["writeToken"]
        passed("test_store_and_loopback_handshake", {
            "storeId": old_store_id, "testData": initial_workspace["testData"],
            "productionAuthorized": initial_workspace["productionAuthorized"],
            "host": "127.0.0.1", "port": service.port,
        })

        # All business writes in the HTTP/SSE scenarios stay in this disposable
        # test-data store; no runner is registered and no model is contacted.
        created_a = service.write("/api/v1/projects",
                                  command(old_store_id, "transport-project-a", "project.create",
                                          {"name": "Transport A"}), old_token)
        project_a = created_a["resource"]["id"]
        created_b = service.write("/api/v1/projects",
                                  command(old_store_id, "transport-project-b", "project.create",
                                          {"name": "Transport B"}), old_token)
        project_b = created_b["resource"]["id"]

        view_path_a = f"/api/v1/projects/{project_a}/view"
        events_path_a = f"/api/v1/projects/{project_a}/events"
        baseline = service.get(view_path_a)
        base_cursor = baseline["throughSequence"]
        service.write(f"/api/v1/projects/{project_a}/commands",
                                command(old_store_id, "transport-update-a1", "project.settings.update",
                                        {"name": "Transport A updated once"}, project_a), old_token)
        after_update1 = service.get(view_path_a)
        first_watermark = after_update1["throughSequence"]
        first_count = first_watermark - base_cursor
        if first_count < 2:
            raise AssertionError("fixture update did not generate the expected project and receipt events")

        # A project view gives its persisted watermark; the command lands after
        # that read but before the SSE subscription, and must be replayed.
        first_read = service.stream(f"{events_path_a}?after={base_cursor}", old_token, 1)
        first_event = first_read[0]
        if first_event["event"]["sequence"] != base_cursor + 1:
            raise AssertionError("SSE did not replay the first event after throughSequence")

        # Break the stream after one delivered event, add another change while
        # disconnected, and reconnect from the event ID received before loss.
        service.write(f"/api/v1/projects/{project_a}/commands",
                      command(old_store_id, "transport-update-a2", "project.settings.update",
                              {"name": "Transport A updated twice"}, project_a), old_token)
        after_disconnect_view = service.get(view_path_a)
        reconnect_watermark = after_disconnect_view["throughSequence"]
        first_seq = first_event["event"]["sequence"]
        reconnect_count = reconnect_watermark - first_seq
        reconnected = service.stream(events_path_a, old_token, reconnect_count,
                                     last_event_id=first_event["id"])
        assert_events(reconnected, project_a, list(range(first_seq + 1, reconnect_watermark + 1)))

        # Repeating the same cursor is safe: the persisted event IDs and payloads
        # are stable, so the client can discard its already-seen prefix.
        all_after_base_count = reconnect_watermark - base_cursor
        duplicate_cursor = service.stream(f"{events_path_a}?after={base_cursor}",
                                          old_token, all_after_base_count)
        first_sequence = list(range(base_cursor + 1, reconnect_watermark + 1))
        assert_events(duplicate_cursor, project_a, first_sequence)
        expected_ids = [first_event["id"], *[item["id"] for item in reconnected]]
        duplicate_ids = [item["id"] for item in duplicate_cursor]
        if duplicate_ids != expected_ids:
            raise AssertionError("repeated cursor did not replay the same stable event IDs")

        status, future_error = service.request_json(
            "GET", f"{events_path_a}?after={reconnect_watermark + 1}", token=old_token)
        if status != 409 or future_error.get("error", {}).get("code") != "RESYNC_REQUIRED":
            raise AssertionError(f"future cursor was not rejected for resynchronization: {status} {future_error}")
        passed("snapshot_gap_disconnect_reconnect_duplicate_and_future_cursor", {
            "projectId": project_a,
            "throughSequence": base_cursor,
            "gapEvents": first_count,
            "disconnectAfterSequence": first_seq,
            "reconnectEvents": len(reconnected),
            "reconnectSequences": [item["event"]["sequence"] for item in reconnected],
            "duplicateCursorStableEventIds": duplicate_ids,
            "futureCursorStatus": status,
            "futureCursorError": future_error["error"]["code"],
        })

        # Make a change to B between two changes to A, then read each stream via
        # HTTP. Per-project sequence streams must not leak B's event into A.
        baseline_b = service.get(f"/api/v1/projects/{project_b}/view")["throughSequence"]
        baseline_a = service.get(view_path_a)["throughSequence"]
        service.write(f"/api/v1/projects/{project_b}/commands",
                      command(old_store_id, "transport-update-b", "project.settings.update",
                              {"name": "Transport B changed"}, project_b), old_token)
        watermark_b = service.get(f"/api/v1/projects/{project_b}/view")["throughSequence"]
        b_events = service.stream(f"/api/v1/projects/{project_b}/events?after={baseline_b}",
                                  old_token, watermark_b - baseline_b)
        service.write(f"/api/v1/projects/{project_a}/commands",
                      command(old_store_id, "transport-update-a3", "project.settings.update",
                              {"name": "Transport A changed after B"}, project_a), old_token)
        watermark_a = service.get(view_path_a)["throughSequence"]
        a_events = service.stream(f"{events_path_a}?after={baseline_a}", old_token,
                                  watermark_a - baseline_a)
        assert_events(a_events, project_a, list(range(baseline_a + 1, watermark_a + 1)))
        b_ids = {item["id"] for item in b_events}
        if b_ids.intersection(item["id"] for item in a_events):
            raise AssertionError("project B event appeared in project A SSE stream")
        if any(item["event"].get("projectId") != project_b for item in b_events):
            raise AssertionError("project B stream returned an event from another project")
        passed("cross_project_events_are_isolated", {
            "projectA": project_a, "projectB": project_b,
            "projectASequences": [item["event"]["sequence"] for item in a_events],
            "projectBSequences": [item["event"]["sequence"] for item in b_events],
            "projectAContainsProjectBEvent": False,
        })

        restart_receipt_message = command(old_store_id, "restart-receipt", "project.create",
                                          {"name": "Receipt survives restart"})
        original_receipt = service.write("/api/v1/projects", restart_receipt_message, old_token)
        previous_instance = handshake["serviceInstanceId"]
        previous_port = service.port
        stopped = service.stop()
        evidence["services"][-1].update(stopped=stopped,
                                        handlerErrors=service.handler_errors,
                                        activeHandlersAtStop=service.active_handlers)
        if not stopped:
            raise AssertionError("first HTTP service did not stop")
        service = None

        coordinator = Coordinator(REPO_ROOT, state_root=store_path, test_data=True)
        restarted_service = LocalService(coordinator, port=previous_port)
        service = restarted_service
        evidence["services"].append({"kind": "http-restart", "host": "127.0.0.1",
                                     "port": service.port, "testData": True})
        restarted_handshake = service.get("/api/v1/handshake")
        if restarted_handshake["storeId"] != old_store_id:
            raise AssertionError("ordinary restart changed the store namespace")
        if restarted_handshake["serviceInstanceId"] == previous_instance:
            raise AssertionError("ordinary restart retained the service instance identity")
        if restarted_handshake["writeToken"] == old_token:
            raise AssertionError("ordinary restart retained the previous write token")
        stale_message = command(old_store_id, "stale-token-write", "project.create",
                                {"name": "Must not be created with old token"})
        stale_status, stale_result = service.request_json("POST", "/api/v1/projects",
                                                          body=stale_message, token=old_token)
        if stale_status != 403:
            raise AssertionError(f"old write token was not rejected after restart: {stale_status}")
        lookup = service.get("/api/v1/commands/restart-receipt")
        if not lookup.get("known") or lookup.get("receipt") != original_receipt:
            raise AssertionError("original command receipt was not recoverable after ordinary restart")
        current_projects = service.get("/api/v1/projects")["projects"]
        if any(project.get("title") == "Must not be created with old token" for project in current_projects):
            raise AssertionError("stale-token command mutated the test store")
        passed("ordinary_restart_rotates_token_and_retains_receipt", {
            "storeIdStable": True, "serviceInstanceChanged": True,
            "oldTokenRejectedStatus": stale_status,
            "oldTokenErrorKind": stale_result.get("kind"),
            "originalReceiptRecovered": True,
            "receiptCommandId": original_receipt["commandId"],
        })

        stopped = service.stop()
        evidence["services"][-1].update(stopped=stopped,
                                        handlerErrors=service.handler_errors,
                                        activeHandlersAtStop=service.active_handlers)
        if not stopped:
            raise AssertionError("restarted HTTP service did not stop")
        service = None
        coordinator = None

        # A runner had durably crossed the start-intent boundary when its store
        # was backed up. Restore must retain that journal but quarantine it from
        # the new store namespace until a human reconciles the old intent.
        journal_path = store_path / "runners" / "agent" / "journal.sqlite3"
        journal = LocalJournal(journal_path)
        journal.bind_store(old_store_id)
        request = {"storeId": old_store_id, "projectId": project_a,
                   "runnerId": journal.runner_id, "attemptId": "attempt-crashed-before-ack",
                   "taskKind": "plan"}
        journal.record_claim(request)
        journal.start_intent(request["attemptId"], request)
        journal = None

        blocked_backup = root / "backup-while-runner-locked"
        with RunnerLock(journal_path.parent / "service.lock"):
            try:
                backup(store_path, blocked_backup)
            except RuntimeError as error:
                if "Stop the backend" not in str(error):
                    raise
            else:
                raise AssertionError("backup proceeded while a runner lock was held")
        if blocked_backup.exists():
            raise AssertionError("refused backup left a partial destination")
        passed("backup_refuses_live_runner_lock", {"destinationCreated": False})

        backup_path = root / "saved-backup"
        manifest = backup(store_path, backup_path)
        restore_path = root / "restored-store"
        restore_result = restore(backup_path, restore_path)
        new_store_id = restore_result["storeId"]
        if manifest["storeId"] != old_store_id or restore_result["oldStoreId"] != old_store_id:
            raise AssertionError("backup/restore lost its source store identity")
        if new_store_id == old_store_id:
            raise AssertionError("restore reused the old store identity")

        restored_journal = LocalJournal(restore_path / "runners" / "agent" / "journal.sqlite3")
        with restored_journal._connect() as db:
            quarantine = db.execute(
                "SELECT value FROM metadata WHERE key='quarantinedStoreId'"
            ).fetchone()
            retained_intent = db.execute(
                "SELECT state FROM attempts WHERE attempt_id=?",
                (request["attemptId"],),
            ).fetchone()
        if not quarantine or quarantine[0] != old_store_id:
            raise AssertionError("restored runner journal did not quarantine its original store")
        if not retained_intent or retained_intent[0] != "launch_intent":
            raise AssertionError("restore did not preserve the runner's unresolved start intent")
        try:
            restored_journal.bind_store(new_store_id)
        except RunnerError as error:
            quarantine_error = str(error)
        else:
            raise AssertionError("quarantined runner journal bound to the restored store")

        restored_coordinator = Coordinator(REPO_ROOT, state_root=restore_path, test_data=True)
        restored_service = LocalService(restored_coordinator)
        evidence["services"].append({"kind": "restored-http", "host": "127.0.0.1",
                                     "port": restored_service.port, "testData": True})
        restored_handshake = restored_service.get("/api/v1/handshake")
        if restored_handshake["storeId"] != new_store_id:
            raise AssertionError("restored HTTP handshake did not expose the new namespace")
        restored_lookup = restored_service.get("/api/v1/commands/restart-receipt")
        if restored_lookup.get("known"):
            raise AssertionError("old command receipt leaked into the restored namespace")
        restored_workspace = restored_service.get("/api/v1/projects")
        if not any(project["id"] == project_a for project in restored_workspace["projects"]):
            raise AssertionError("restore did not retain the source project's public record")
        passed("backup_restore_rotates_namespace_and_quarantines_runner_journal", {
            "oldStoreId": old_store_id, "newStoreId": new_store_id,
            "storeIdChanged": True, "projectPreserved": project_a,
            "oldReceiptKnownInRestoredStore": False,
            "runnerJournalQuarantinedStoreId": quarantine[0],
            "unresolvedRunnerIntentState": retained_intent[0],
            "newStoreBindingRejected": True,
            "journalRejection": quarantine_error,
        })

    except BaseException as error:  # Evidence must be written even when one check fails.
        overall_error = error
        failed("acceptance_run", error)
    finally:
        for name, active in (("restored-http", restored_service), ("http", service)):
            if active is not None:
                try:
                    stopped = active.stop()
                    evidence["services"].append({"kind": name, "stopped": stopped,
                                                 "cleanup": True,
                                                 "handlerErrors": active.handler_errors,
                                                 "activeHandlersAtStop": active.active_handlers})
                    if not stopped and overall_error is None:
                        overall_error = AssertionError(f"{name} service did not stop")
                except BaseException as error:
                    evidence["services"].append({"kind": name, "stopped": False,
                                                 "cleanupError": f"{type(error).__name__}: {error}"})
                    if overall_error is None:
                        overall_error = error
        # If construction failed before a LocalService owned the coordinator,
        # still release the test store lock.
        if coordinator is not None and (service is None or service.coordinator is not coordinator):
            try:
                coordinator.close()
            except BaseException as error:
                evidence["services"].append({"kind": "coordinator", "stopped": False,
                                             "cleanupError": f"{type(error).__name__}: {error}"})
                if overall_error is None:
                    overall_error = error
        temp.cleanup()
        evidence["tempStore"] = True
        evidence["temporaryDirectoryRemoved"] = not root.exists()
        evidence["serviceStopped"] = all(item.get("stopped", True) for item in evidence["services"])
        evidence["status"] = "PASS" if overall_error is None and all(
            item["status"] == "PASS" for item in evidence["scenarios"]
        ) else "FAIL"
        if overall_error is not None:
            evidence["error"] = f"{type(overall_error).__name__}: {overall_error}"
        write_evidence(evidence)

    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""One-off HTTP/SSE recovery acceptance; fixture reports only, no model/Godot."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.coordinator import Coordinator
from backend.server import REPO_ROOT
from backend.tests.test_generic_workflow import plan_result
from backend.tests.test_studio_delivery import StudioDeliveryTests
from tools.studio_acceptance_transport import LocalService, command, utc_now

EVIDENCE = REPO_ROOT / "evidence/workflow/studio-acceptance-remaining-transport-20261013.json"
RUNNER = "agent-test"


def check(value, message):
    if not value:
        raise AssertionError(message)


def record(c, aid, kind, payload, rid):
    a = c._get("attempt", aid)
    return {"schemaVersion": "studio.message.v1", "kind": "execution_report",
            "type": kind, "taskKind": a["taskKind"], "storeId": c.store_id,
            "projectId": a["projectId"], "runnerId": a["runnerId"],
            "attemptId": aid, "reportId": rid, "payload": payload}


def started(suffix):
    now = datetime.now(timezone.utc).isoformat()
    return {"nativeIdentity": {"threadId": "fixture-thread-" + suffix,
            "turnId": "fixture-turn-" + suffix, "processId": None,
            "processGroupId": None, "processStartTime": None}, "startedAt": now,
            "requestedProfile": None, "reportedProfile": None,
            "threadStartReported": None, "turnStartAcknowledged": None,
            "actualProfile": None}


def completed():
    response = {**plan_result(), "schemaVersion": "studio.planner-result.v1",
                "feedbackDecisions": []}
    return {"stopped": True, "result": {"response": response}}


def rev(view):
    return view.get("publicationRevision", view.get("project", {}).get("publicationRevision", 0))


def main():
    ev = {"schemaVersion": "studio.acceptance.remaining-transport.v1", "createdAt": utc_now(),
          "disposableFixtureStore": True, "testData": False, "productionAuthorized": True,
          "productionStoreTouched": False, "modelStarted": False, "godotStarted": False,
          "runnerProcessesStarted": False, "fixtureReportsUsed": True,
          "scenarios": [], "services": []}
    tmp = tempfile.TemporaryDirectory(prefix="studio-acceptance-remaining-transport-")
    root = Path(tmp.name).resolve()
    state = root / "store"
    c = s = None

    def passed(name, **details):
        ev["scenarios"].append({"id": name, "status": "PASS", **details})

    def restart(kind):
        nonlocal c, s
        port = s.port
        stopped = s.stop()
        ev["services"][-1].update(stopped=stopped, handlerErrors=s.handler_errors,
                                  activeHandlersAtStop=s.active_handlers)
        check(stopped, "HTTP service did not stop cleanly")
        s = None
        c = Coordinator(REPO_ROOT, state_root=state)
        s = LocalService(c, port=port)
        ev["services"].append({"kind": kind, "host": "127.0.0.1", "port": s.port,
                               "testData": c.test_data})
        return s.get("/api/v1/handshake")

    try:
        c = Coordinator(REPO_ROOT, state_root=state)
        check(not c.test_data and c.production_authorized and c.state_root.parent == root,
              "expected the existing disposable delivery-fixture store")
        s = LocalService(c)
        ev["services"].append({"kind": "http", "host": "127.0.0.1", "port": s.port,
                               "testData": c.test_data})
        hs = s.get("/api/v1/handshake")
        sid, token = hs["storeId"], hs["writeToken"]
        created = s.write("/api/v1/projects", command(sid, "remaining-project-create",
            "project.create", {"name": "Remaining transport fixture"}), token)
        pid = created["result"]["project"]["id"]

        # The existing no-model delivery fixture prepares only a candidate.
        fixture = StudioDeliveryTests()
        fixture.c, fixture.state, fixture.seq, fixture.pid = c, state, 0, pid
        job, artifact, _repo, ack = fixture.candidate()
        check(ack.get("disposition") == "recorded" and not c._threads,
              "candidate fixture did not settle without a runner process")
        candidate = job["candidate"]
        before = s.get(f"/api/v1/projects/{pid}/view")
        check(rev(before) == 0, "candidate fixture must start at publication revision 0")

        # Window A captures revision 0; window B publishes before A's GET returns.
        captured, release = threading.Event(), threading.Event()
        slow, errors, original = {}, [], c.project_view

        def delayed_view(project_id):
            result = original(project_id)
            captured.set()
            check(release.wait(8), "slow GET was not released")
            return result

        c.project_view = delayed_view

        def get_slow():
            try:
                slow["view"] = s.get(f"/api/v1/projects/{pid}/view")
            except BaseException as e:
                errors.append(str(e))

        thread = threading.Thread(target=get_slow, daemon=True)
        thread.start()
        check(captured.wait(5), "slow GET did not capture its initial snapshot")
        publish = command(sid, "remaining-window-b-accept", "candidate.accept",
            {"candidateId": candidate["id"], "sourceCommit": candidate["sourceCommit"],
             "experienceDecisions": []}, pid)
        publish["expected"] = {"publicationRevision": 0, "preferencesRevision": 0}
        status, receipt = s.request_json("POST", f"/api/v1/projects/{pid}/candidates/"
            f"{candidate['id']}/accept", body=publish, token=token)
        release.set()
        thread.join(8)
        del c.project_view
        check(not thread.is_alive() and not errors, f"slow GET failed: {errors}")
        check(status == 200 and receipt.get("status") == "accepted", "HTTP publication failed")
        late, current = slow["view"], s.get(f"/api/v1/projects/{pid}/view")
        check(rev(late) == 0 and current["publicationRevision"] == 1,
              "slow window did not return the stale publication after window B published")
        text = "Keep this fixture draft and explicitly re-associate it"
        stale = command(sid, "remaining-stale-draft", "concept.submit",
                        {"text": text, "assetRefs": []}, pid)
        stale["expected"] = {"preferencesRevision": 0, "publicationRevision": 0, "sourceCommit": None}
        old_status, old_receipt = s.request_json("POST", f"/api/v1/projects/{pid}/concepts",
                                                  body=stale, token=token)
        check(old_status == 200 and old_receipt.get("status") == "rejected" and
              old_receipt.get("error", {}).get("code") == "STALE_PUBLICATION",
              "stale draft was not rejected")
        fresh = command(sid, "remaining-reassociated-draft", "concept.submit",
                        {"text": text, "assetRefs": []}, pid)
        fresh["expected"] = {"preferencesRevision": 0, "publicationRevision": 1,
                              "sourceCommit": current["snapshot"]["sourceCommit"]}
        new_status, new_receipt = s.request_json("POST", f"/api/v1/projects/{pid}/concepts",
                                                  body=fresh, token=token)
        proposal = new_receipt["result"]["proposal"]
        check(new_status == 200 and new_receipt.get("status") == "accepted" and
              proposal["publicationRevision"] == 1 and
              proposal["baseCommit"] == current["snapshot"]["sourceCommit"],
              "re-associated draft did not bind to the current publication")
        passed("http_multi_window_publication_slow_get_and_draft_reassociation",
               projectId=pid, publishedRevision=1, lateWindowRevision=rev(late),
               staleDraftError=old_receipt["error"]["code"],
               reassociatedRevision=proposal["publicationRevision"],
               reassociatedSourceCommit=proposal["baseCommit"], artifactId=artifact["artifactId"])

        # Live SSE delivery, then a fixture-created retention gap and HTTP resync.
        cursor, opened, events, errors = current["throughSequence"], threading.Event(), [], []

        def stream():
            try:
                events.extend(s.stream(f"/api/v1/projects/{pid}/events?after={cursor}",
                                       token, 1, on_open=opened))
            except BaseException as e:
                errors.append(str(e))

        thread = threading.Thread(target=stream, daemon=True)
        thread.start()
        check(opened.wait(5), "SSE did not open")
        s.write(f"/api/v1/projects/{pid}/commands", command(sid, "remaining-live-event",
            "project.settings.update", {"name": "Live event after subscription"}, pid), token)
        thread.join(8)
        check(not thread.is_alive() and not errors and len(events) == 1,
              f"live SSE event was not delivered: {errors}")
        event = events[0]
        check(event["id"] == str(cursor + 1) and event["event"]["projectId"] == pid,
              "live SSE event did not follow the subscribed cursor")
        view = s.get(f"/api/v1/projects/{pid}/view")
        stale_cursor = max(1, view["throughSequence"] - 2)
        with c.transaction():
            c.db.execute("DELETE FROM project_events WHERE project_id=? AND sequence<=?",
                          (pid, stale_cursor + 1))
        gap_status, gap = s.request_json("GET", f"/api/v1/projects/{pid}/events?after={stale_cursor}", token=token)
        fresh_view = s.get(f"/api/v1/projects/{pid}/view")
        check(gap_status == 409 and gap.get("error", {}).get("code") == "RESYNC_REQUIRED" and
              fresh_view["throughSequence"] == view["throughSequence"], "event gap did not recover by view resync")
        passed("http_live_sse_delivery_and_missing_event_resync", projectId=pid, cursor=cursor,
               lateEventId=event["id"], lateEventSequence=event["event"]["sequence"],
               simulatedGapThrough=stale_cursor + 1, gapHttpStatus=gap_status,
               gapError=gap["error"]["code"], resyncThrough=fresh_view["throughSequence"])

        # Drop a terminal ACK body, restart, recover it and retry the same report ID.
        aid = proposal["attemptId"]
        claim_status, claim = s.runner_json("POST", "/internal/v1/claim", RUNNER,
            {"storeId": sid, "runnerId": RUNNER, "commandId": "remaining-terminal-claim"})
        check(claim_status == 200 and claim["request"]["attemptId"] == aid, "fixture attempt claim failed")
        start = record(c, aid, "started", started("ack-loss"), "remaining-started-ack-loss")
        check(s.runner_json("POST", "/internal/v1/reports", RUNNER, start)[1]["disposition"] == "recorded",
              "fixture start report failed")
        terminal = record(c, aid, "completed", completed(), "remaining-terminal-ack-loss")
        dropped_status = s.runner_post_discard_ack("/internal/v1/reports", RUNNER, terminal)
        check(dropped_status == 200, "terminal HTTP report failed before its ACK body was discarded")
        attempt = c._get("attempt", aid)
        old_lease = attempt["lease"]["expiresAt"]
        attempt["lease"] = {"expiresAt": (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}
        with c.transaction():
            c._put("attempt", attempt)
        old_instance, old_token = c.service_instance_id, token
        hs = restart("http-restart")
        lookup_status, lookup = s.runner_json("GET", f"/internal/v1/reports/{terminal['reportId']}", RUNNER)
        retry_status, retry = s.runner_json("POST", "/internal/v1/reports", RUNNER, terminal)
        view = s.get(f"/api/v1/projects/{pid}/view")
        recovered = next(p for p in view["proposals"] if p["id"] == proposal["id"])
        count = sum(a["id"] == aid for a in c._all_project("attempt", pid))
        check(hs["storeId"] == sid and hs["serviceInstanceId"] != old_instance and
              hs["writeToken"] != old_token and lookup_status == retry_status == 200 and
              lookup["known"] and retry == lookup["ack"] and recovered["status"] == "READY" and count == 1,
              "lost terminal ACK did not recover as the same durable report after restart")
        cancel = command(sid, "remaining-cancel-after-complete", "execution.cancel",
            {"attemptId": aid, "ownerRef": c._get("attempt", aid)["ownerRef"]}, pid)
        cancel_status, cancel_receipt = s.request_json("POST",
            f"/api/v1/projects/{pid}/executions/{aid}/cancel", body=cancel, token=hs["writeToken"])
        check(cancel_status == 200 and cancel_receipt.get("error", {}).get("code") == "EXECUTION_FINISHED",
              "late cancellation revoked the completed report")
        passed("terminal_ack_discard_retry_restart_and_cancel_after_completion", attemptId=aid,
               reportId=terminal["reportId"], ackHttpStatus=dropped_status, lookupKnown=lookup["known"],
               retryAckSame=retry == lookup["ack"], leaseChanged=old_lease != attempt["lease"]["expiresAt"],
               proposalStatus=recovered["status"], attemptCount=count,
               cancelAfterCompleteError=cancel_receipt["error"]["code"])

        # Cancel another live attempt, restart, retain UNKNOWN after late completion,
        # then settle it only with a matching explicit stop reconciliation.
        submit = command(sid, "remaining-cancel-race-submit", "concept.submit",
            {"text": "Fixture plan for cancellation ordering", "assetRefs": []}, pid)
        submit["expected"] = {"preferencesRevision": 0, "publicationRevision": 1,
                               "sourceCommit": view["snapshot"]["sourceCommit"]}
        status, receipt = s.request_json("POST", f"/api/v1/projects/{pid}/concepts",
                                         body=submit, token=hs["writeToken"])
        p2, aid2 = receipt["result"]["proposal"], receipt["result"]["proposal"]["attemptId"]
        check(status == 200 and receipt.get("status") == "accepted", "second plan fixture was not queued")
        claim = s.runner_json("POST", "/internal/v1/claim", RUNNER,
            {"storeId": sid, "runnerId": RUNNER, "commandId": "remaining-cancel-claim"})[1]
        check(claim["request"]["attemptId"] == aid2, "second fixture attempt claim failed")
        start2 = record(c, aid2, "started", started("cancel-race"), "remaining-cancel-race-started")
        check(s.runner_json("POST", "/internal/v1/reports", RUNNER, start2)[1]["disposition"] == "recorded",
              "second start report failed")
        cancel = command(sid, "remaining-cancel-race-command", "execution.cancel",
            {"attemptId": aid2, "ownerRef": c._get("attempt", aid2)["ownerRef"]}, pid)
        status, result = s.request_json("POST", f"/api/v1/projects/{pid}/executions/{aid2}/cancel",
                                        body=cancel, token=hs["writeToken"])
        check(status == 200 and result.get("status") == "accepted", "running cancellation was not recorded")
        old_instance = c.service_instance_id
        hs = restart("http-cancel-restart")
        before = s.get(f"/api/v1/projects/{pid}/view")
        unknown = c._get("attempt", aid2)
        late = record(c, aid2, "completed", completed(), "remaining-cancel-race-late-completed")
        late_status, late_ack = s.runner_json("POST", "/internal/v1/reports", RUNNER, late)
        after = s.get(f"/api/v1/projects/{pid}/view")
        p2_after = next(p for p in after["proposals"] if p["id"] == p2["id"])
        check(before["observations"]["status"] == "UNKNOWN" and unknown["cancelRequested"] and
              late_status == 200 and late_ack["disposition"] == "evidence_only" and
              after["observations"]["status"] == "UNKNOWN" and
              p2_after["status"] == "PLANNING_UNCERTAIN" and not p2_after.get("reviewedPlanRef"),
              "late completion advanced an attempt whose stop was unknown")
        status, stopped = s.runner_json("POST", "/internal/v1/reconcile", RUNNER,
            {"storeId": sid, "runnerId": RUNNER, "attemptId": aid2,
             "nativeIdentity": unknown["nativeIdentity"], "stopped": True})
        final = s.get(f"/api/v1/projects/{pid}/view")
        p2_final = next(p for p in final["proposals"] if p["id"] == p2["id"])
        check(status == 200 and stopped["status"] == "STOPPED" and p2_final["status"] == "CANCELLED",
              "matching stop reconciliation did not settle cancellation")
        passed("cancel_restart_late_completion_and_stop_reconciliation", attemptId=aid2,
               serviceInstanceChanged=hs["serviceInstanceId"] != old_instance,
               statusAfterRestart=before["observations"]["status"],
               lateCompletion=late_ack["disposition"],
               statusAfterLateCompletion=after["observations"]["status"],
               proposalBeforeStop=p2_after["status"], statusAfterReconcile=stopped["status"],
               proposalAfterReconcile=p2_final["status"])

    except BaseException as e:
        ev["error"] = f"{type(e).__name__}: {e}"
        ev["scenarios"].append({"id": "remaining_transport_acceptance", "status": "FAIL",
                                "error": ev["error"]})
    finally:
        if "release" in locals():
            release.set()
        if s is not None:
            try:
                stopped = s.stop()
                ev["services"][-1].update(stopped=stopped, handlerErrors=s.handler_errors,
                                          activeHandlersAtStop=s.active_handlers)
            except BaseException as e:
                ev["services"][-1].update(stopped=False, cleanupError=str(e))
        if c is not None and (s is None or s.coordinator is not c):
            c.close()
        tmp.cleanup()
        ev["temporaryDirectoryRemoved"] = not root.exists()
        ev["serviceStopped"] = all(item.get("stopped", True) for item in ev["services"])
        ev["status"] = "PASS" if ev["serviceStopped"] and ev["temporaryDirectoryRemoved"] and \
            all(x["status"] == "PASS" for x in ev["scenarios"]) else "FAIL"
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(ev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(ev, ensure_ascii=False, indent=2))
    return 0 if ev["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

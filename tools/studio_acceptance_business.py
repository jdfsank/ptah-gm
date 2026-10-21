"""Bounded real-model workflow on one disposable store; no human acceptance claim."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runners.agent as agent_module
from backend.coordinator import Coordinator, git
from backend.tests.test_studio_delivery import StudioDeliveryTests
from runners.agent import AgentRunner
from runners.common import LocalJournal, RunnerHTTP
from runners.project import ProjectRunner
from tools.studio_acceptance_transport import LocalService


def plan_request(comment: str) -> str:
    document = {"schemaVersion": "studio.objects.v1", "dimension": "2d",
        "title": "Bounded Studio acceptance", "summary": "Preserve the original 2D template behavior.",
        "objects": [{"id": "main-scene", "kind": "scene", "name": "Main scene",
            "sourceBindings": ["scenes/main.tscn", "scripts/main.gd"], "fields": []}],
        "requirements": [{"id": "preserve", "text": "Preserve every existing source line and gameplay behavior.",
            "objectIds": ["main-scene"], "verification": "manual"}]}
    return ("This is a bounded technical workflow acceptance, not a new gameplay feature. "
        "Read planning-input.json with studio_read_file. Return strict studio.planner-result.v1 READY JSON. "
        "Use exactly this object document: " + json.dumps(document) + ". "
        "Use one task id source-comment, objectIds [main-scene], requirementIds [preserve]. "
        "Its description must require reading GDD.md, PLAN.md, STRUCTURE.md and design/game.json, "
        "then appending exactly this final source line to scripts/main.gd: " + json.dumps(comment) +
        ". The quotes delimit the line and are not source text. Preserve every existing byte; "
        "append immediately after the existing final newline, with no additional blank line, "
        "and finish the added line with one newline. Preserve every other file, with no gameplay change. "
        "Questions and blockers must be empty. Decide every supplied feedbackId individually; "
        "adopt the request to preserve behavior and link source-comment/preserve; defer cosmetic work "
        "outside this bounded task with a reason. If an image is supplied describe its visible color "
        "in summary, without expanding scope. Do not execute anything.")


def run() -> dict:
    fixture = StudioDeliveryTests(); fixture.setUp()
    out = {"schemaVersion": "studio.business-acceptance.v1", "recordedAt": datetime.now(timezone.utc).isoformat(),
        "passed": False, "modelTurns": 0, "syntheticOperatorDecisions": True,
        "userCandidateAccepted": False, "coordinatorTestData": fixture.c.test_data,
        "requestedModel": "gpt-6-luna", "requestedEffort": "max", "cases": {}, "turns": []}
    service = None; preview_thread = None; preview_stop = threading.Event()
    try:
        service = LocalService(fixture.c)
        token = fixture.state / "acceptance-runner-token"
        token.write_text(fixture.c.runner_token); token.chmod(0o600)
        agent_journal = LocalJournal(fixture.state / "agent.sqlite3")
        project_journal = LocalJournal(fixture.state / "project.sqlite3")
        for journal in (agent_journal, project_journal): journal.bind_store(fixture.c.store_id)
        agent_api = RunnerHTTP(service.base, token, agent_journal.runner_id, timeout=5)
        project_api = RunnerHTTP(service.base, token, project_journal.runner_id, timeout=5)
        agent = AgentRunner(agent_api, agent_journal, fixture.state / "workspaces",
            fixture.state / "artifacts", fixture.state / "projects")
        project = ProjectRunner(project_api, project_journal, fixture.state / "artifacts",
            fixture.state / "projects", "/Applications/Godot.app/Contents/MacOS/Godot", stop_event=preview_stop)
        agent.register(); agent.publish_catalog(); project.register()
        print("Fresh agent/project registrations completed.", flush=True)
        out["registrations"] = [{"runnerKind": r["runnerKind"], "capabilities": r["capabilities"],
            "sandboxEvidence": r["sandboxEvidence"]} for r in fixture.c._all("runner")]
        handshake = service.get("/api/v1/handshake")

        def command(kind, payload, expected=None, pid=None):
            for api, runner in ((agent_api, agent), (project_api, project)):
                api.request("POST", "/internal/v1/heartbeat", {"runnerId": runner.runner_id, "storeId": fixture.c.store_id})
            message = fixture.envelope(kind, payload, pid=pid or fixture.pid, expected=expected)
            receipt = service.write(f"/api/v1/projects/{message['projectId']}/commands", message, handshake["writeToken"])
            if receipt["status"] != "accepted":
                raise AssertionError(f"{kind}: {receipt}")
            return receipt["result"]

        def expected(publication=0, source=None):
            return {"publicationRevision": publication, "preferencesRevision": 2, "sourceCommit": source}

        for revision, role in enumerate(("planner", "producer")):
            command("session.preferences.update", {"role": role, "modelKey": "gpt-6-luna", "effort": "max",
                "limits": {"maxDurationSeconds": 120, "softTotalTokens": None}}, {"preferencesRevision": revision})

        def execute_agent(injection=None):
            request = agent.claim(fixture.c.store_id)["request"]
            if not request: raise AssertionError("No agent claim")
            print(f"Starting real {request['taskKind']} ({injection or 'workflow'}).", flush=True)
            events = []; triggered = False; native_pid = None; worker_pid = None
            candidates_before = sum(bool(j.get("candidate")) for j in fixture.c._all_project("job", request["projectId"]))
            original = agent_module.process_output_lines

            def capture(process):
                nonlocal triggered, native_pid, worker_pid, service, handshake
                worker_pid = process.pid
                for line in original(process):
                    try: event = json.loads(line) if line else {}
                    except ValueError: event = {}
                    if event.get("event") == "started": native_pid = (event.get("nativeIdentity") or {}).get("processId")
                    if event.get("event") in {"nativeObservation", "result", "usage"}: events.append(event)
                    yield line
                    if (not triggered and injection and
                            (event.get("observation") or {}).get("phase") == "turnStartAcknowledged"):
                        triggered = True
                        agent_journal.flush(agent_api)
                        if injection == "restart":
                            previous_store = fixture.c.store_id
                            service.stop()
                            fixture.c = Coordinator(ROOT, state_root=fixture.state)
                            service = LocalService(fixture.c)
                            agent_api.base_url = service.base; project_api.base_url = service.base
                            handshake = service.get("/api/v1/handshake")
                            out["cases"]["activeBackendRestart"] = {
                                "triggeredAfterNativeTurnAcknowledged": True,
                                "sameStoreId": previous_store == fixture.c.store_id,
                                "statusImmediatelyAfterRestart": fixture.c._get("attempt", request["attemptId"])["status"],
                                "unknownKeepsClaimBlocked": agent.claim(fixture.c.store_id)["request"] is None}
                        elif injection == "crash":
                            if type(native_pid) is not int or native_pid == os.getpid():
                                raise AssertionError("Missing owned native PID")
                            os.kill(native_pid, signal.SIGKILL)
                        elif injection == "cancel":
                            cancelled = command("execution.cancel", {"attemptId": request["attemptId"], "ownerRef": request["ownerRef"]})
                            out["cases"]["cancelRace"] = {"cancelAcceptedAfterTurnAcknowledged": True,
                                "statusAtCancellation": cancelled["attempt"]["status"]}
            accepted = False
            try:
                with patch.object(agent_module, "process_output_lines", capture):
                    accepted = agent.accept_claim(request, fixture.c.store_id)
            finally:
                turn_ids = {e["observation"]["turnId"] for e in events
                    if (e.get("observation") or {}).get("phase") == "turnStartAcknowledged"}
                out["modelTurns"] += len(turn_ids)
                out["turns"].append({"taskKind": request["taskKind"], "attemptId": request["attemptId"],
                    "injection": injection, "accepted": accepted, "acknowledgedTurns": len(turn_ids), "events": events})
            agent_journal.flush(agent_api)
            attempt = fixture.c._get("attempt", request["attemptId"])
            out["turns"][-1]["status"] = attempt["status"]
            if injection:
                case_key = {"restart": "activeBackendRestart", "crash": "nativeCrash", "cancel": "cancelRace"}[injection]
                result = out["cases"].setdefault(case_key, {})
                groups_stopped = (type(native_pid) is int and type(worker_pid) is int and
                    not agent._process_group_exists(native_pid) and not agent._process_group_exists(worker_pid))
                result["statusAfterRunnerReports"] = attempt["status"]
                result["ownedProcessGroupsStopped"] = groups_stopped
                result["runnerConfirmedStop"] = attempt["status"] in {"STOPPED", "FAILED"}
                result.update(triggered=triggered, oneNativeTurn=len(turn_ids) == 1,
                    terminalStatus=attempt["status"],
                    noNewCandidate=sum(bool(j.get("candidate")) for j in fixture.c._all_project("job", request["projectId"])) == candidates_before)
                if not triggered or len(turn_ids) != 1 or not groups_stopped or not result["noNewCandidate"] or attempt["status"] not in {"STOPPED", "FAILED"}:
                    raise AssertionError(f"{injection} did not stop: {result}")
            elif not accepted or attempt["status"] != "COMPLETED":
                raise AssertionError(f"Real {request['taskKind']} failed: {attempt}")
            print(f"Real {request['taskKind']} finished: {attempt['status']}.", flush=True)
            return request

        def freeze(proposal, publication=0):
            view = service.get(f"/api/v1/projects/{fixture.pid}/view")
            return command("proposal.freeze", {"proposalId": proposal["id"],
                "reviewedPlanRef": view["proposal"]["reviewedPlanRef"]},
                {"proposalRevision": proposal["revision"], "publicationRevision": publication})["packet"]

        def produce(packet, comment, publication=0):
            job = command("production.start", {"packetId": packet["id"]},
                {"publicationRevision": publication, "preferencesRevision": 2})["job"]
            prepared = fixture.c._get("attempt", job["attemptId"])["prepared"]
            source = fixture.state / "artifacts" / prepared["inputArtifactRef"]["artifactId"] / "repository"
            before = (source / "scripts/main.gd").read_bytes()
            execute_agent()
            job = fixture.c._get("job", job["id"])
            verification = project.claim(fixture.c.store_id)["request"]
            project.verify(verification, fixture.c.store_id); project_journal.flush(project_api)
            job = fixture.c._get("job", job["id"])
            if job["status"] != "READY_FOR_REVIEW": raise AssertionError(f"Candidate not verified: {job}")
            ref = job["candidate"]["artifactRef"]
            sealed = fixture.state / "artifacts" / ref["artifactId"] / "repository"
            exact = (sealed / "scripts/main.gd").read_bytes() == before + (b"" if before.endswith(b"\n") else b"\n") + comment.encode() + b"\n"
            out["cases"].setdefault("deliveries", []).append({"exactCommentEdit": exact,
                "sourceCommit": ref["sourceCommit"], "verification": job["candidate"]["verification"],
                "sourceDiff": git(sealed, "diff", ref["inputCommit"], ref["sourceCommit"], "--", "scripts/main.gd"),
                "changedPaths": git(sealed, "diff", "--name-only", ref["inputCommit"], ref["sourceCommit"]).splitlines()})
            if not exact: raise AssertionError("Producer changed more than approved comment")
            return job, sealed

        comment = "# Studio workflow acceptance first."
        proposal = command("concept.submit", {"text": plan_request(comment), "assetRefs": []}, expected())["proposal"]
        execute_agent(); proposal = fixture.c._get("proposal", proposal["id"])
        old_ref = service.get(f"/api/v1/projects/{fixture.pid}/view")["proposal"]["reviewedPlanRef"]
        feedback = [{"feedbackId": "feedback-preserve", "objectId": "main-scene", "category": "behavior", "message": "Preserve the current behavior."},
            {"feedbackId": "feedback-color", "objectId": "main-scene", "category": "visual", "message": "Defer cosmetic color changes to a later task."},
            {"feedbackId": "feedback-layout", "objectId": "main-scene", "category": "visual", "message": "Defer layout changes to a later task."}]
        # Image support is taken from the fresh native catalog, never declared by this harness.
        row = next(row for row in agent.models if row["modelKey"] == "gpt-6-luna")
        assets = []
        if "image" in row["inputModalities"]:
            from PIL import Image
            buffer = io.BytesIO(); Image.new("RGB", (16, 16), "red").save(buffer, format="PNG")
            asset = fixture.c.upload_asset(operator_id=fixture.c.operator_id, project_id=fixture.pid,
                name="reference.png", mime_type="image/png", data_base64=base64.b64encode(buffer.getvalue()).decode(), purpose="reference")
            assets.append(asset["id"])
        proposal = command("proposal.revise", {"proposalId": proposal["id"], "supplement": plan_request(comment),
            "feedback": feedback, "assetRefs": assets}, {**expected(), "proposalRevision": proposal["revision"]})["proposal"]
        execute_agent(); proposal = fixture.c._get("proposal", proposal["id"])
        stale_msg = fixture.envelope("proposal.freeze", {"proposalId": proposal["id"], "reviewedPlanRef": old_ref},
            expected={"proposalRevision": proposal["revision"], "publicationRevision": 0})
        stale = service.write(f"/api/v1/projects/{fixture.pid}/commands", stale_msg, handshake["writeToken"])
        decisions = proposal["feedbackDecisions"]
        color_observed = any(color in proposal["summary"].lower() for color in ("red", "红", "紅")) if assets else None
        out["cases"]["readyRevision"] = {"status": proposal["status"], "revision": proposal["revision"],
            "feedbackIds": sorted(d["feedbackId"] for d in decisions), "decisions": decisions,
            "staleReviewRejected": stale["status"] == "rejected", "imageSent": bool(assets),
            "imageSummaryColorMatchesReference": color_observed, "modelSummary": proposal["summary"]}
        if proposal["status"] != "READY" or {d["feedbackId"] for d in decisions} != {f["feedbackId"] for f in feedback} or stale["status"] != "rejected":
            raise AssertionError("READY revision or feedback binding failed")
        if assets and not color_observed:
            raise AssertionError("Planner did not describe the reference image color")
        packet = freeze(proposal); first, sealed = produce(packet, comment)
        accepted = command("candidate.accept", {"candidateId": first["candidate"]["id"],
            "sourceCommit": first["candidate"]["sourceCommit"], "experienceDecisions": [{
                "feedbackId": "feedback-preserve", "status": "needs_followup", "reason": "Synthetic operator verifies persistence, not human experience."}]},
            {"publicationRevision": 0, "preferencesRevision": 2})
        snapshot = accepted["snapshot"]
        feedback_state = fixture.c._all_project("feedback", fixture.pid)
        out["cases"]["syntheticAcceptance"] = {"snapshotExact": snapshot["artifactRef"] == first["candidate"]["artifactRef"],
            "experienceStatuses": {f["feedbackId"]: f.get("experienceStatus") for f in feedback_state},
            "syntheticOperator": True, "userAcceptance": False}
        comment2 = "# Studio workflow acceptance iteration."
        proposal = command("iteration.submit", {"text": plan_request(comment2), "assetRefs": [],
            "targetObjectIds": ["main-scene"], "fields": [], "feedback": []}, expected(1, snapshot["sourceCommit"]))["proposal"]
        execute_agent(); proposal = fixture.c._get("proposal", proposal["id"])
        packet2 = freeze(proposal, 1)
        preview = command("preview.start", {"snapshotId": snapshot["id"]}, {"publicationRevision": 1})["preview"]
        preview_request = project.claim(fixture.c.store_id)["request"]
        preview_errors = []
        def play():
            try: project.preview(preview_request, fixture.c.store_id, max_seconds=150)
            except BaseException as exc: preview_errors.append(repr(exc))
        preview_thread = threading.Thread(target=play, daemon=True); preview_thread.start()
        deadline = time.monotonic() + 30
        log = fixture.state / "artifacts/preview-evidence" / (preview_request["attemptId"] + ".log")
        while time.monotonic() < deadline:
            if log.exists() and "OpenGL API" in log.read_text(): break
            if not preview_thread.is_alive(): raise AssertionError("GUI stopped before concurrent production")
            time.sleep(0.2)
        if not log.exists() or "OpenGL API" not in log.read_text(): raise AssertionError("GUI never initialized")
        concurrent_start = time.monotonic()
        # Stop before verification, so one ProjectRunner never serves two claims concurrently.
        second_start = command("production.start", {"packetId": packet2["id"]},
            {"publicationRevision": 1, "preferencesRevision": 2})["job"]
        second_prepared = fixture.c._get("attempt", second_start["attemptId"])["prepared"]
        second_input = fixture.state / "artifacts" / second_prepared["inputArtifactRef"]["artifactId"] / "repository"
        second_original = (second_input / "scripts/main.gd").read_bytes()
        execute_agent()
        producer_end = time.monotonic()
        gui_alive_at_delivery = preview_thread.is_alive()
        command("preview.stop", {"previewId": preview["id"]})
        preview_thread.join(timeout=20); project_journal.flush(project_api)
        if preview_thread.is_alive() or preview_errors: raise AssertionError(f"Preview stop: {preview_errors}")
        verification = project.claim(fixture.c.store_id)["request"]
        project.verify(verification, fixture.c.store_id); project_journal.flush(project_api)
        second = fixture.c._get("job", second_start["id"])
        if second["status"] != "READY_FOR_REVIEW": raise AssertionError("Iteration not independently verified")
        second_sealed = fixture.state / "artifacts" / second["candidate"]["artifactRef"]["artifactId"] / "repository"
        second_exact = (second_sealed / "scripts/main.gd").read_bytes() == second_original + (b"" if second_original.endswith(b"\n") else b"\n") + comment2.encode() + b"\n"
        out["cases"]["deliveries"].append({"exactCommentEdit": second_exact,
            "sourceCommit": second["candidate"]["sourceCommit"], "verification": second["candidate"]["verification"],
            "sourceDiff": git(second_sealed, "diff", second["candidate"]["artifactRef"]["inputCommit"], second["candidate"]["sourceCommit"], "--", "scripts/main.gd")})
        if not second_exact: raise AssertionError("Iteration changed more than approved comment")
        command("candidate.reject", {"candidateId": second["candidate"]["id"],
            "sourceCommit": second["candidate"]["sourceCommit"], "experienceDecisions": []},
            {"publicationRevision": 1, "preferencesRevision": 2})
        preview_source = fixture.state / "artifacts/previews" / preview_request["attemptId"]
        accepted_source = fixture.state / "projects" / fixture.pid
        producer_source = fixture.state / "workspaces" / second_start["attemptId"]
        out["cases"]["concurrentProductionPreview"] = {"overlapSeconds": producer_end - concurrent_start,
            "guiAliveAtProducerDelivery": gui_alive_at_delivery, "distinctSources": len({preview_source, accepted_source, producer_source, sealed}) == 4,
            "previewSourceUnchanged": git(preview_source, "status", "--porcelain", "--untracked-files=all", "--", ".", ":!.godot") == "",
            "acceptedSourceUnchanged": git(accepted_source, "rev-parse", "HEAD") == snapshot["sourceCommit"] and git(accepted_source, "status", "--porcelain") == "",
            "sealedSourceUnchanged": git(sealed, "status", "--porcelain") == "",
            "rejectedCandidateKeepsSnapshot": fixture.c._get("project", fixture.pid)["snapshotId"] == snapshot["id"],
            "guiUnexpectedErrors": [line for line in log.read_text().splitlines() if line.startswith(("ERROR:", "SCRIPT ERROR:"))]}
        for injection in ("restart", "crash", "cancel"):
            proposal = command("iteration.submit", {"text": plan_request("# Never produced fault test"), "assetRefs": [],
                "targetObjectIds": ["main-scene"], "fields": [], "feedback": []}, expected(1, snapshot["sourceCommit"]))["proposal"]
            execute_agent(injection)
        concurrent = out["cases"]["concurrentProductionPreview"]
        out["passed"] = bool(out["cases"]["syntheticAcceptance"]["snapshotExact"] and
            out["cases"]["syntheticAcceptance"]["experienceStatuses"] == {"feedback-preserve": "needs_followup", "feedback-color": "unreviewed", "feedback-layout": "unreviewed"} and
            all(concurrent[key] is True for key in ("guiAliveAtProducerDelivery", "distinctSources", "previewSourceUnchanged", "acceptedSourceUnchanged", "sealedSourceUnchanged", "rejectedCandidateKeepsSnapshot")) and not concurrent["guiUnexpectedErrors"])
    except Exception as exc:
        out["failure"] = {"type": type(exc).__name__, "message": str(exc)[:3000]}
    finally:
        preview_stop.set()
        if preview_thread is not None: preview_thread.join(timeout=20)
        if service is not None: service.stop()
        state = fixture.state; fixture.tearDown()
        out["temporaryStoreDestroyed"] = not state.exists()
        if not out["temporaryStoreDestroyed"]: out["passed"] = False
    return out


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true", required=True); args = parser.parse_args()
    started = time.monotonic(); result = run(); result["durationSeconds"] = time.monotonic() - started
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result.get(key) for key in ("passed", "modelTurns", "failure", "durationSeconds")}, ensure_ascii=False))


if __name__ == "__main__": main()

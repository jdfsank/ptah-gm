"""Disposable approval fixture with real Producer, sealing, verification and GUI.

Synthetic role registration is confined to this temporary store. It never
enables service capabilities or accepts/publishes a user candidate.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runners.agent as agent_module
from backend.coordinator import git
from backend.source_preparation import load_uid_preparation_evidence
from backend.tests.test_generic_workflow import plan_result
from backend.tests.test_studio_delivery import StudioDeliveryTests
from backend.tests.test_object_protocol import sample_document
from backend.tests.test_studio_protocol import fixture_role_evidence
from runners.agent import AgentRunner
from runners.common import LocalJournal, RunnerHTTP
from runners.project import ProjectRunner
from tools.studio_acceptance_transport import LocalService

COMMENT = "# Studio boundary acceptance 20261012"


class Fixture(StudioDeliveryTests):
    def runner(self):
        self.c.register_runner({"runnerId": self.agent_id, "runnerKind": "agent",
            "environment": "disposable acceptance fixture", "nativeVersion": "fixture-registration",
            "capabilities": ["planning-readonly-v1", "production-private-v1"],
            "sandboxEvidence": fixture_role_evidence(self.agent_id, "agent", ["planning-readonly-v1", "production-private-v1"])})
        self.c.update_runner_catalog({"runnerId": self.agent_id, "catalogRevision": 1,
            "observedAt": datetime.now(timezone.utc).isoformat(), "models": [{
                "modelKey": "gpt-6-luna", "modelProvider": "my_proxy",
                "supportedReasoningEfforts": ["max"], "defaultReasoningEffort": "max",
                "inputModalities": ["text"], "isDefault": True}]})

    def ready(self):
        proposal = self.planning()
        self.c.claim_runner({"storeId": self.c.store_id, "runnerId": self.agent_id,
                             "commandId": "claim-planning-fixture"})
        self.started(proposal["attemptId"])
        document = sample_document()
        document["summary"] = "Preserve the original prepared 2D baseline and add one source comment."
        document["objects"] = [document["objects"][0]]
        document["objects"][0]["sourceBindings"].append("scripts/main.gd")
        document["requirements"][0]["objectIds"] = ["main-scene"]
        document["requirements"][0]["text"] = "Preserve original main scene behavior; append only the approved source comment."
        document["requirements"][0]["verification"] = "manual"
        response = {**plan_result(document), "schemaVersion": "studio.planner-result.v1",
            "summary": document["summary"], "feedbackDecisions": [], "tasks": [{
                "id": "source-comment", "objectIds": ["main-scene"], "requirementIds": ["explore"],
                "description": "Read scripts/main.gd and append exactly one final line: " + COMMENT +
                    ". Preserve every existing line and every other file. This approved task changes no gameplay."}]}
        ack = self.report(proposal["attemptId"], "completed", {"stopped": True,
                          "result": {"response": response}})
        self.assertEqual(ack["disposition"], "recorded", ack)
        return self.c._get("proposal", proposal["id"])


def run_chain() -> dict:
    fixture = Fixture()
    fixture.setUp()
    service = None
    output = {"scope": "temporary store; fixture planning/approval/role registration; actual HTTP, "
              "gpt-6-luna/max Producer, trusted UID preparation, sealed Git artifact, ProjectRunner and GUI",
              "capabilitiesEnabled": [], "userCandidateAccepted": False, "modelTurns": 0, "passed": False}
    observed = []
    try:
        journal = LocalJournal(fixture.state / "agent-journal.sqlite3")
        journal.bind_store(fixture.c.store_id)
        fixture.agent_id = journal.runner_id
        packet = fixture.frozen()
        # Fixture role registration is local to this disposable store only.
        project_journal = LocalJournal(fixture.state / "project-journal.sqlite3")
        project_journal.bind_store(fixture.c.store_id)
        project_id = project_journal.runner_id
        fixture.c.register_runner({"runnerId": project_id, "runnerKind": "project", "environment": "fixture",
            "nativeVersion": None, "capabilities": ["verification-isolated-v1", "preview-isolated-v1"],
            "sandboxEvidence": fixture_role_evidence(project_id, "project", ["verification-isolated-v1", "preview-isolated-v1"])})
        receipt = fixture.command("production.start", {"packetId": packet["id"]},
                                  expected={"publicationRevision": 0, "preferencesRevision": 0})
        output["startReceiptStatus"] = receipt["status"]
        if receipt["status"] != "accepted":
            output["startRejection"] = receipt
            return output
        job = fixture.c._get("job", receipt["result"]["job"]["id"])
        # The job still points at its queued production attempt here. The
        # productionAttemptId link is recorded only after a sealed delivery.
        prepared = fixture.c._get("attempt", job["attemptId"])["prepared"]
        source = fixture.state / "artifacts" / prepared["inputArtifactRef"]["artifactId"] / "repository"
        original_script = (source / "scripts/main.gd").read_bytes()
        output["inputCommit"] = prepared["inputCommit"]
        service = LocalService(fixture.c)
        token = fixture.state / "runner-api-token"
        token.write_text(fixture.c.runner_token)
        token.chmod(0o600)
        api = RunnerHTTP(service.base, token, journal.runner_id, timeout=5)
        runner = AgentRunner(api, journal, fixture.state / "workspaces", fixture.state / "artifacts",
                             fixture.state / "projects")
        execution = runner.claim(fixture.c.store_id)["request"]
        actual_output = agent_module.process_output_lines

        def capture(process):
            for line in actual_output(process):
                if line:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict) and event.get("event") in {"result", "nativeObservation", "usage"}:
                        observed.append(event)
                yield line

        with patch.object(agent_module, "process_output_lines", capture):
            output["producerAccepted"] = runner.accept_claim(execution, fixture.c.store_id)
        journal.flush(api)
        output["nativeObservations"] = observed
        output["modelTurns"] = len({e["observation"]["turnId"] for e in observed
            if (e.get("observation") or {}).get("phase") == "turnStartAcknowledged"})
        job = fixture.c._get("job", job["id"])
        output["jobAfterProducer"] = {key: job.get(key) for key in ("status", "message", "errorCode")}
        if not output["producerAccepted"] or not job.get("verificationAttemptId"):
            return output
        ref = fixture.c._get("attempt", job["verificationAttemptId"])["inputRefs"]["artifactRef"]
        sealed = fixture.state / "artifacts" / ref["artifactId"] / "repository"
        output["artifactRef"] = ref
        output["exactApprovedSourceEdit"] = (sealed / "scripts/main.gd").read_bytes() == (
            original_script + (b"" if original_script.endswith(b"\n") else b"\n")
            + COMMENT.encode() + b"\n")
        output["changedFiles"] = git(sealed, "diff", "--name-only", ref["inputCommit"], ref["sourceCommit"]).splitlines()
        output["uidPreparation"] = json.loads((sealed.parent / "evidence/uid-preparation.json").read_text())
        sidecars, _ = load_uid_preparation_evidence(sealed.parent,
            input_commit=ref["inputCommit"], source_commit=ref["sourceCommit"])
        expected_changes = {"scripts/main.gd": "M", **{path: "A" for path in sidecars}}
        changes = [line.split("\t", 1) for line in git(sealed, "diff", "--no-renames", "--name-status",
            ref["inputCommit"], ref["sourceCommit"]).splitlines()]
        output["exactApprovedChangeSet"] = (all(len(row) == 2 for row in changes)
            and {path: status for status, path in changes} == expected_changes)
        expected_summary = {f"create mode 100644 {path}" for path in sidecars}
        output["sourceModesUnchanged"] = {line.strip() for line in git(sealed, "diff", "--no-renames",
            "--summary", ref["inputCommit"], ref["sourceCommit"]).splitlines()} == expected_summary
        project_api = RunnerHTTP(service.base, token, project_id, timeout=5)
        project_runner = ProjectRunner(project_api, project_journal, fixture.state / "artifacts",
            fixture.state / "projects", "/Applications/Godot.app/Contents/MacOS/Godot")
        verification = project_runner.claim(fixture.c.store_id)["request"]
        project_runner.verify(verification, fixture.c.store_id)
        project_journal.flush(project_api)
        evidence = fixture.state / "artifacts/verification-evidence" / (verification["attemptId"] + ".json")
        output["verification"] = json.loads(evidence.read_text()) if evidence.exists() else None
        verified = output["verification"] or {}
        output["verificationSourceBinding"] = (verified.get("sourceCommit") == ref["sourceCommit"]
            and verified.get("artifactRef") == ref and verified.get("sourceUnchanged") is True
            and verified.get("stopped") is True)
        job = fixture.c._get("job", job["id"])
        output["candidateCreated"] = bool(job.get("candidate"))
        if not output["candidateCreated"]:
            return output
        preview_receipt = fixture.command("preview.start", {"candidateId": job["candidate"]["id"]},
                                         expected={"publicationRevision": 0})
        output["previewReceiptStatus"] = preview_receipt["status"]
        if preview_receipt["status"] != "accepted":
            output["previewRejection"] = preview_receipt
            return output
        preview = project_runner.claim(fixture.c.store_id)["request"]
        preview_started = time.monotonic()
        project_runner.preview(preview, fixture.c.store_id, max_seconds=10)
        output["previewCallDurationSeconds"] = time.monotonic() - preview_started
        project_journal.flush(project_api)
        with project_journal._connect() as db:
            output["projectReports"] = [json.loads(row[0]) for row in db.execute("SELECT body_json FROM reports ORDER BY created_at")]
        preview_log = fixture.state / "artifacts/preview-evidence" / (preview["attemptId"] + ".log")
        output["previewLog"] = preview_log.read_text()[-16000:] if preview_log.exists() else ""
        output["guiRendererStarted"] = "OpenGL API" in output["previewLog"]
        output["guiUnexpectedErrors"] = [line for line in output["previewLog"].splitlines()
                                         if line.startswith(("ERROR:", "SCRIPT ERROR:"))]
        terminals = [report for report in output["projectReports"] if report.get("attemptId") == preview["attemptId"]
            and report.get("type") in {"completed", "failed", "stopped"}]
        output["guiWatchdogStopped"] = (len(terminals) == 1 and terminals[0]["type"] == "stopped"
            and terminals[0]["payload"].get("stopped") is True
            and terminals[0]["payload"].get("stopReason") == "time_limit")
        preview_source = fixture.state / "artifacts/previews" / preview["attemptId"]
        output["previewSourceUnchanged"] = (git(preview_source, "rev-parse", "HEAD") == ref["sourceCommit"]
            and git(preview_source, "status", "--porcelain", "--untracked-files=all", "--", ".", ":!.godot") == "")
        output["sealedSourceUnchanged"] = (git(sealed, "rev-parse", "HEAD") == ref["sourceCommit"]
            and git(sealed, "status", "--porcelain", "--untracked-files=all") == "")
        output["passed"] = bool(output["exactApprovedSourceEdit"] and output["exactApprovedChangeSet"]
            and output["sourceModesUnchanged"] and output["verificationSourceBinding"]
            and verified.get("status") == "PASS" and output["previewSourceUnchanged"]
            and output["sealedSourceUnchanged"] and output["guiRendererStarted"]
            and not output["guiUnexpectedErrors"] and output["guiWatchdogStopped"])
        return output
    except Exception as exc:
        output["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        output["nativeObservations"] = observed
        output["modelTurns"] = len({e["observation"]["turnId"] for e in observed
            if (e.get("observation") or {}).get("phase") == "turnStartAcknowledged"})
        return output
    finally:
        if service is not None:
            service.stop()
        temporary_store = fixture.state
        fixture.tearDown()
        output["cleanup"] = {"temporaryStorePath": str(temporary_store),
            "temporaryStoreDestroyed": not temporary_store.exists() and not temporary_store.is_symlink()}
        if not output["cleanup"]["temporaryStoreDestroyed"]:
            output["passed"] = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    result = run_chain()
    result["durationSeconds"] = time.monotonic() - started
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result.get(key) for key in ("passed", "modelTurns", "failure", "durationSeconds")}))


if __name__ == "__main__":
    main()

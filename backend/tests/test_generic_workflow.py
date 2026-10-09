"""Isolated lifecycle contracts for the object-based coordinator workflow."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.coordinator import Coordinator, WorkflowError
from backend.generic_workflow import timeout_clarification
from backend.object_protocol import ObjectProtocolError, parse_planner_response, validate_change_request, validate_document
from backend.tests.test_object_protocol import sample_document


REPO_ROOT = Path(__file__).resolve().parents[2]


def plan_result(document=None, status="READY"):
    if status == "NEEDS_CLARIFICATION":
        return {
            "status": status,
            "summary": "The control scheme needs one decision.",
            "questions": [{"id": "control", "prompt": "Use keyboard or mouse?", "type": "choice",
                           "required": True, "options": [{"value": "keyboard", "label": "Keyboard"},
                                                            {"value": "mouse", "label": "Mouse"}]}],
            "document": None,
            "tasks": [],
            "blockers": [],
        }
    document = copy.deepcopy(document or sample_document())
    return {
        "status": "READY",
        "summary": "Explore the harbor and solve the light puzzle.",
        "questions": [],
        "document": document,
        "tasks": [{"id": "harbor-loop", "description": "Implement exploration and the light puzzle.",
                   "objectIds": ["main-scene", "player"], "requirementIds": ["explore"]}],
        "blockers": [],
    }


class Planner:
    def __init__(self, owner, path):
        self.owner, self.path = owner, Path(path)

    def run(self, packet, cancel_event=None, reference_images=None, on_process_started=None):
        if self.owner.planner_started:
            self.owner.planner_started.set()
        if self.owner.planner_release:
            self.owner.planner_release.wait(5)
        if not self.owner.plans:
            raise AssertionError("test planner has no scripted response")
        result = self.owner.plans.pop(0)
        return {
            "status": self.owner.planner_status,
            "response": json.dumps(result),
            "diagnostics": {**self.owner.planner_diagnostics,
                "childTerminationConfirmed": self.owner.planner_stopped},
        }


class Producer:
    def __init__(self, path, mode):
        self.path, self.mode = Path(path), mode

    def run(self, packet, cancel_event=None, reference_images=None, on_process_started=None):
        if self.mode == "normal":
            script = self.path / "scripts/player.gd"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("extends Node2D\n\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8")
        elif self.mode == "protected":
            (self.path / "design/game.json").write_text('{"modified":true}\n', encoding="utf-8")
        elif self.mode == "out_of_scope":
            (self.path / "README.md").write_text("outside the approved source roots\n", encoding="utf-8")
        elif self.mode == "parent_symlink":
            outside = self.path.parent / "outside-scripts"
            outside.mkdir()
            (self.path / "scripts").rename(self.path / "scripts-original")
            (self.path / "scripts").symlink_to(outside, target_is_directory=True)
            (self.path / "scripts/player.gd").write_text("extends Node2D\n", encoding="utf-8")
        return {"status": "completed", "diagnostics": {"childTerminationConfirmed": True}}


def passing_verifier(project, document, base_commit=None, **kwargs):
    return {"status": "PASS", "requirements": [], "diagnostics": [], "commands": []}


class GenericWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temp.name) / "workbench"
        self.plans = []
        self.planner_started = None
        self.planner_release = None
        self.planner_stopped = True
        self.planner_status = "completed"
        self.planner_diagnostics = {}
        self.producer_mode = "normal"
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id

    def tearDown(self):
        if self.coordinator is not None and not self.coordinator._closed:
            self.coordinator.close()
        self.temp.cleanup()

    def _new_coordinator(self):
        return Coordinator(
            REPO_ROOT,
            state_root=self.state_root,
            test_data=True,
            planner_driver_factory=lambda path: Planner(self, path),
            generic_driver_factory=lambda path: Producer(path, self.producer_mode),
            generic_verifier=passing_verifier,
        )

    def _wait_proposal(self, proposal_id, statuses, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            proposal = self.coordinator.get_proposal(proposal_id)
            if proposal["status"] in statuses:
                return proposal
            time.sleep(0.01)
        self.fail(f"proposal did not reach {statuses}: {self.coordinator.get_proposal(proposal_id)}")

    def _create(self, result=None, text="Explore a harbor and solve a light puzzle."):
        self.plans.append(result or plan_result())
        proposal = self.coordinator.create_concept(operator_id=self.operator, text=text, workflow="objects-v1")
        return self._wait_proposal(proposal["id"], {"READY", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "PLANNING_UNCERTAIN"})

    def _freeze(self, proposal):
        return self.coordinator.freeze_proposal(
            operator_id=self.operator,
            proposal_id=proposal["id"],
            expected_revision=proposal["revision"],
            expected_publication_revision=proposal["publicationRevision"],
            reviewed_proposal=proposal,
        )

    def _dispatch(self, proposal):
        packet = self._freeze(proposal)
        job = self.coordinator.create_job(operator_id=self.operator, packet_id=packet["id"],
                                          idempotency_key="test:" + packet["id"])
        return self.coordinator.wait(job["id"], 12)

    def test_native_network_timeout_preserves_evidence_and_safe_retry_diagnosis(self):
        self.planner_status = "timeout"
        self.planner_diagnostics = {"elapsedSeconds": 420.0, "error": None,
            "stderr": ["stream disconnected before completion; target=codex_core::responses_retry"]}
        proposal = self._create()
        self.assertEqual(proposal["status"], "FAILED")
        self.assertEqual(proposal["planningEvidence"]["status"], "timeout")
        self.assertTrue(proposal["planningTerminationConfirmed"])
        diagnosis = proposal["planningFailure"]
        self.assertEqual(diagnosis["code"], "PLANNER_NETWORK")
        self.assertTrue(diagnosis["retryable"])
        self.assertEqual(diagnosis["elapsedSeconds"], 420)
        self.assertIsNone(proposal["document"])
        self.assertNotIn("packetId", proposal)

        # Existing stored failures from the prior release are enriched only on
        # reads; their original revision, input, status and record stay intact.
        with self.coordinator.transaction():
            original = self.coordinator._get("proposal", proposal["id"])
            for key in ("planningFailure", "planningEvidence", "planningTerminationConfirmed"):
                original.pop(key)
            self.coordinator._put("proposal", original)
        restored = self.coordinator.get_proposal(proposal["id"])
        self.assertEqual(restored["planningFailure"]["code"], "PLANNER_NETWORK")
        self.assertEqual(restored["revision"], original["revision"])
        self.assertEqual(restored["text"], original["text"])
        visible = next(p for p in self.coordinator.workspace()["proposals"] if p["id"] == proposal["id"])
        self.assertEqual(visible["planningEvidence"]["status"], "timeout")
        self.assertNotIn("planningFailure", self.coordinator._get("proposal", proposal["id"]))

    def test_unconfirmed_native_stop_is_not_offered_for_retry(self):
        self.planner_status = "timeout"
        self.planner_stopped = False
        proposal = self._create()
        self.assertEqual(proposal["status"], "PLANNING_UNCERTAIN")
        self.assertFalse(proposal["planningFailure"]["retryable"])
        with self.assertRaises(WorkflowError) as busy:
            self.coordinator.create_concept(operator_id=self.operator, workflow="objects-v1",
                project_id=proposal["projectId"], expected_publication_revision=0, text="Try again.")
        self.assertEqual(busy.exception.code, "PROJECT_BUSY")

    def test_invalid_planner_response_keeps_native_evidence(self):
        result = plan_result()
        result["document"]["dimension"] = "3d"
        proposal = self._create(result=result)
        self.assertEqual(proposal["status"], "FAILED")
        self.assertEqual(proposal["planningFailure"]["code"], "PLANNER_RESPONSE_INVALID")
        self.assertEqual(proposal["planningEvidence"]["status"], "completed")
        self.assertIsNone(proposal["document"])

    def test_stopped_timeout_recovers_only_questions_and_next_round_clears_diagnosis(self):
        self.planner_status = "timeout"
        tentative = plan_result(status="NEEDS_CLARIFICATION")
        tentative.update(document=sample_document(), tasks=plan_result()["tasks"])
        proposal = self._create(result=tentative)
        self.assertEqual(proposal["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(proposal["planningEvidence"]["status"], "timeout")
        self.assertEqual(proposal["planningRecovery"]["kind"], "CLARIFICATION_FROM_TIMEOUT")
        self.assertIsNone(proposal["document"])
        self.assertEqual(proposal["tasks"], [])
        self.assertEqual(proposal["questions"], tentative["questions"])
        self.assertNotIn("gmSpecRef", proposal)
        self.assertNotIn("packetId", proposal)
        with self.assertRaises(WorkflowError):
            self._freeze(proposal)
        self.planner_status = "completed"
        self.plans.append(plan_result())
        next_round = self.coordinator.answer_proposal(operator_id=self.operator, proposal_id=proposal["id"],
            expected_revision=proposal["revision"], answers={"control": "keyboard"})
        for key in ("planningFailure", "planningRecovery", "planningEvidence", "planningTerminationConfirmed", "planningLease"):
            self.assertNotIn(key, next_round)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY")
        self.assertNotIn("planningRecovery", ready)

    def test_timeout_recovery_rejects_non_clarification_invalid_and_restricted_results(self):
        base = {"status": "timeout", "response": json.dumps(plan_result(status="NEEDS_CLARIFICATION")),
            "diagnostics": {"childTerminationConfirmed": True}}
        cases = [
            {**base, "status": "cancelled"},
            {**base, "response": json.dumps(plan_result())},
            {**base, "response": base["response"][:-1]},
            {**base, "diagnostics": {"childTerminationConfirmed": False}},
            {**base, "diagnostics": {"childTerminationConfirmed": True, "approvalRequests": [{"method": "approval"}]}},
            {**base, "diagnostics": {"childTerminationConfirmed": True, "protocolErrors": [{"method": "unsupported"}]}},
            {**base, "commandEvidence": {"executionEvidence": [{"type": "commandExecution"}]}},
        ]
        for result in cases:
            with self.subTest(status=result["status"], diagnostics=result["diagnostics"]):
                self.assertIsNone(timeout_clarification(result))

    def test_timeout_clarification_still_enforces_readonly_workspace(self):
        self.planner_status = "timeout"
        original_run = Planner.run
        def writes_unexpected_file(driver, *args, **kwargs):
            result = original_run(driver, *args, **kwargs)
            (driver.path / "unexpected.txt").write_text("not allowed")
            return result
        with patch.object(Planner, "run", writes_unexpected_file):
            proposal = self._create(result=plan_result(status="NEEDS_CLARIFICATION"))
        self.assertEqual(proposal["status"], "FAILED")
        self.assertEqual(proposal["planningFailure"]["code"], "PLANNER_WRITE")
        self.assertFalse(proposal["planningFailure"]["clarificationAvailable"])
        self.assertIsNone(proposal["document"])

    def test_reconcile_restores_latest_historical_timeout_questions_once(self):
        self.planner_status = "timeout"
        proposal = self._create(result=plan_result(status="NEEDS_CLARIFICATION"))
        folder = self.state_root / "planning" / proposal["id"] / "round-1"
        original = json.loads((folder / "request.json").read_text())
        original.update(status="FAILED", planningEvidence=proposal["planningEvidence"], planningLease={"processGroupId": 999999})
        with self.coordinator.transaction():
            self.coordinator._put("proposal", original)
        visible = self.coordinator.get_proposal(proposal["id"])
        self.assertTrue(visible["planningFailure"]["clarificationAvailable"])
        original_input = (folder / "request.json").read_text()
        for key, value in (("workflow", "collect-loop-v1"), ("testData", False),
                ("productionAuthorized", True), ("templateId", "other-template"), ("unexpected", "extra")):
            changed = json.loads(original_input)
            changed[key] = value
            from backend.coordinator import canonical
            (folder / "request.json").write_text(canonical(changed) + "\n")
            with patch("backend.generic_workflow._require_stopped"), self.assertRaises(WorkflowError) as drift:
                self.coordinator.reconcile_proposal(operator_id=self.operator, proposal_id=proposal["id"])
            self.assertEqual(drift.exception.code, "STALE_PROPOSAL", key)
        (folder / "request.json").write_text(original_input)
        with patch("backend.generic_workflow._require_stopped") as stopped:
            recovered = self.coordinator.reconcile_proposal(operator_id=self.operator, proposal_id=proposal["id"])
        stopped.assert_called_once_with({"processGroupId": 999999})
        self.assertEqual(recovered["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(recovered["document"])
        self.assertEqual(recovered["tasks"], [])
        self.assertEqual(len(recovered["discussion"]), len(original["discussion"]) + 1)
        self.assertEqual(self.coordinator.reconcile_proposal(operator_id=self.operator, proposal_id=proposal["id"]), recovered)
        self.assertEqual(self.coordinator._all("packet"), [])
        self.assertEqual(self.coordinator._all("job"), [])

        with self.coordinator.transaction():
            self.coordinator._put("proposal", original)
        self.plans.append(plan_result(status="NEEDS_CLARIFICATION"))
        newer = self.coordinator.create_concept(operator_id=self.operator, workflow="objects-v1",
            project_id=proposal["projectId"], expected_publication_revision=0, text="A newer concept.")
        self._wait_proposal(newer["id"], {"NEEDS_CLARIFICATION", "FAILED"})
        with self.assertRaises(WorkflowError) as stale:
            self.coordinator.reconcile_proposal(operator_id=self.operator, proposal_id=proposal["id"])
        self.assertEqual(stale.exception.code, "STALE_PROPOSAL")

    def test_planner_clarification_answers_are_revision_bound_and_resolve_to_ready(self):
        self.plans.extend([plan_result(status="NEEDS_CLARIFICATION"), plan_result()])
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="Explore a harbor.", workflow="objects-v1")
        waiting = self._wait_proposal(proposal["id"], {"NEEDS_CLARIFICATION", "FAILED"})
        self.assertEqual(waiting["status"], "NEEDS_CLARIFICATION", waiting)
        self.assertIsNone(waiting["document"])
        with self.assertRaises(WorkflowError):
            self.coordinator.answer_proposal(operator_id=self.operator, proposal_id=waiting["id"],
                expected_revision=waiting["revision"], answers={"control": "touch"})
        next_revision = self.coordinator.answer_proposal(operator_id=self.operator, proposal_id=waiting["id"],
            expected_revision=waiting["revision"], answers={"control": "keyboard"})
        self.assertEqual(next_revision["revision"], waiting["revision"] + 1)
        ready = self._wait_proposal(waiting["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        user_answers = [entry["answers"] for entry in ready["discussion"] if entry.get("role") == "user" and "answers" in entry]
        self.assertEqual(user_answers[-1], {"control": "keyboard"})
        self.assertEqual(parse_planner_response(json.dumps(plan_result()))["status"], "READY")
        with self.assertRaises(WorkflowError):
            self.coordinator.answer_proposal(operator_id=self.operator, proposal_id=waiting["id"],
                expected_revision=waiting["revision"], answers={"control": "mouse"})

    def test_freeze_binds_exact_review_revision_and_publication_baseline(self):
        proposal = self._create()
        self.assertEqual(proposal["status"], "READY", proposal)
        altered = copy.deepcopy(proposal)
        altered["summary"] += " changed after review"
        with self.assertRaises(WorkflowError) as mismatch:
            self.coordinator.freeze_proposal(operator_id=self.operator, proposal_id=proposal["id"],
                expected_revision=proposal["revision"], expected_publication_revision=0, reviewed_proposal=altered)
        self.assertEqual(mismatch.exception.code, "REVIEW_MISMATCH")
        with self.assertRaises(WorkflowError) as stale_revision:
            self.coordinator.freeze_proposal(operator_id=self.operator, proposal_id=proposal["id"],
                expected_revision=proposal["revision"] + 1, expected_publication_revision=0, reviewed_proposal=proposal)
        self.assertEqual(stale_revision.exception.code, "REVIEW_MISMATCH")
        with self.assertRaises(WorkflowError) as stale_publication:
            self.coordinator.freeze_proposal(operator_id=self.operator, proposal_id=proposal["id"],
                expected_revision=proposal["revision"], expected_publication_revision=1, reviewed_proposal=proposal)
        self.assertEqual(stale_publication.exception.code, "STALE_PUBLICATION")
        packet = self._freeze(proposal)
        self.assertEqual(packet["approvedProposal"], proposal)
        self.assertEqual(packet["document"], proposal["document"])
        self.assertEqual(packet["workflow"], "objects-v1")
        repeated = self.coordinator.freeze_proposal(operator_id=self.operator, proposal_id=proposal["id"],
            expected_revision=proposal["revision"], expected_publication_revision=0, reviewed_proposal=proposal)
        self.assertEqual(repeated["id"], packet["id"])

    def test_frozen_gm_spec_and_template_baselines_must_still_match(self):
        proposal = self._create()
        packet = self._freeze(proposal)
        plan_folder = self.state_root / "planning" / proposal["id"] / f"spec-{proposal['revision']}"
        spec_path = plan_folder / "SPEC.md"
        original = spec_path.read_text(encoding="utf-8")
        spec_path.write_text(original + "\nUnreviewed drift.\n", encoding="utf-8")
        job = self.coordinator.create_job(operator_id=self.operator, packet_id=packet["id"],
            idempotency_key="test:gm-spec-drift:" + packet["id"])
        result = self.coordinator.wait(job["id"], 12)
        self.assertEqual(result["status"], "FAILED", result)
        self.assertIn("已冻结规范文件发生变化", result.get("message", ""))
        self.assertNotIn("candidate", result)

        proposal = self._create()
        packet = self._freeze(proposal)
        with self.coordinator.transaction():
            frozen = self.coordinator._get("packet", packet["id"])
            frozen["templateInventory"]["project.godot"] = "stale-git-object-reference"
            self.coordinator._put("packet", frozen)
        job = self.coordinator.create_job(operator_id=self.operator, packet_id=packet["id"],
            idempotency_key="test:template-drift:" + packet["id"])
        result = self.coordinator.wait(job["id"], 12)
        self.assertEqual(result["status"], "FAILED", result)
        self.assertIn("通用基线变化", result.get("message", ""))
        self.assertNotIn("candidate", result)

    def _seed_published_project(self, document):
        project_id = "existing-general-project"
        repo = self.state_root / "projects" / project_id
        shutil.copytree(REPO_ROOT / "backend/templates/general_2d", repo)
        (repo / ".gitignore").write_text(".godot/\n.godotmaker/\n", encoding="utf-8")
        (repo / "design/game.json").write_text(json.dumps(document), encoding="utf-8")
        (repo / "scripts/player.gd").write_text("extends Node2D\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Lifecycle Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "lifecycle-test@localhost"], cwd=repo, check=True)
        subprocess.run(["git", "add", "--all"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "seed generic published fixture"], cwd=repo, capture_output=True, check=True)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
        with self.coordinator.transaction():
            self.coordinator._put("project", {"id": project_id, "title": "Moon Harbor", "workflow": "objects-v1",
                "templateId": "general-2d-v1", "publicationRevision": 3, "snapshotId": "snapshot-existing", "createdAt": "now"})
            self.coordinator._put("snapshot", {"id": "snapshot-existing", "projectId": project_id,
                "publicationRevision": 3, "sourceCommit": commit, "document": document,
                "catalog": {}, "verification": {"status": "PASS"}, "createdAt": "now"})
        return project_id, commit

    def test_change_fields_require_current_revision_source_and_exact_value_preservation(self):
        old = sample_document()
        project_id, commit = self._seed_published_project(old)
        stale_request = {"baseRevision": 2, "sourceCommit": commit, "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}], "feedback": []}
        with self.assertRaises(WorkflowError) as stale:
            self.coordinator.create_concept(operator_id=self.operator, text="Increase movement speed.",
                project_id=project_id, workflow="objects-v1", expected_publication_revision=3,
                change_request=stale_request)
        self.assertEqual(stale.exception.code, "CHANGE_REQUEST")
        bad_value = {**stale_request, "baseRevision": 3, "fields": [
            {"objectId": "player", "fieldId": "speed", "value": 9999}]}
        with self.assertRaises(WorkflowError):
            self.coordinator.create_concept(operator_id=self.operator, text="Increase movement speed.",
                project_id=project_id, workflow="objects-v1", expected_publication_revision=3,
                change_request=bad_value)
        updated = copy.deepcopy(old)
        next(field for field in updated["objects"][1]["fields"] if field["id"] == "speed")["value"] = 240
        request = {**stale_request, "baseRevision": 3, "fields": [
            {"objectId": "player", "fieldId": "speed", "value": 240}],
            "feedback": [{"objectId": "player", "category": "behavior", "message": "Movement feels sluggish."}]}
        self.plans.append(plan_result(updated))
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="Increase movement speed.",
            project_id=project_id, workflow="objects-v1", expected_publication_revision=3,
            change_request=request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        self.assertEqual(ready["changeRequest"]["fields"], request["fields"])
        self.assertEqual(ready["changeRequest"]["feedback"], request["feedback"])
        self.assertEqual(next(f["value"] for o in ready["document"]["objects"] if o["id"] == "player"
                              for f in o["fields"] if f["id"] == "speed"), 240)

    def test_empty_text_value_and_value_only_feedback_are_valid(self):
        document = sample_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        player["fields"].append({"id": "nickname", "label": "Nickname", "type": "text",
                                 "value": "Pilot", "editable": True})
        project_id, commit = self._seed_published_project(document)
        request = {"baseRevision": 3, "sourceCommit": commit, "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "nickname", "value": ""}],
            "feedback": [{"objectId": "player", "category": "general", "message": ""}]}
        updated = copy.deepcopy(document)
        next(f for f in next(o for o in updated["objects"] if o["id"] == "player")["fields"]
             if f["id"] == "nickname")["value"] = ""
        self.plans.append(plan_result(updated))
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="Clear the nickname.",
            project_id=project_id, workflow="objects-v1", expected_publication_revision=3, change_request=request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        self.assertEqual(ready["changeRequest"]["feedback"][0]["message"], "")
        self.assertEqual(next(f["value"] for o in ready["document"]["objects"] if o["id"] == "player"
                              for f in o["fields"] if f["id"] == "nickname"), "")

    def test_choice_updates_require_exact_json_scalar_type(self):
        document = sample_document()
        mood = next(f for o in document["objects"] for f in o["fields"] if f["id"] == "mood")
        mood.update(value=1, options=[1, 2], editable=True)
        request = {"baseRevision": 3, "sourceCommit": "git-commit-123", "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "mood", "value": True}], "feedback": []}
        with self.assertRaises(ObjectProtocolError):
            validate_change_request(request, document, 3, "git-commit-123")

    def test_producer_cannot_edit_backend_owned_document_or_escape_source_scope(self):
        for mode, expected_fragment in (("protected", "后端持有文件"), ("out_of_scope", "outside the general project write policy")):
            with self.subTest(mode=mode):
                self.coordinator.close()
                self.producer_mode = mode
                self.coordinator = self._new_coordinator()
                self.operator = self.coordinator.operator_id
                proposal = self._create(text="Make a harbor exploration prototype.")
                job = self._dispatch(proposal)
                self.assertEqual(job["status"], "FAILED", job)
                self.assertIn(expected_fragment, job.get("message", ""))
                self.assertNotIn("candidate", job)

    def test_producer_cannot_write_through_a_parent_directory_symlink(self):
        self.coordinator.close()
        self.producer_mode = "parent_symlink"
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id
        proposal = self._create(text="Make a harbor exploration prototype.")
        job = self._dispatch(proposal)
        self.assertEqual(job["status"], "FAILED", job)
        self.assertNotIn("candidate", job)

    def test_completed_producer_that_made_no_game_edit_has_no_candidate(self):
        self.coordinator.close()
        self.producer_mode = "no_edit"
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id
        document = sample_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        player["sourceBindings"] = ["scripts/main.gd"]
        proposal = self._create(result=plan_result(document))
        job = self._dispatch(proposal)
        self.assertEqual(job["status"], "FAILED", job)
        self.assertIn("没有实际修改", job.get("message", ""))
        self.assertNotIn("candidate", job)

        # A feedback-only request does not qualify for the field-only exception.
        document = sample_document()
        project_id, commit = self._seed_published_project(document)
        feedback_request = {"baseRevision": 3, "sourceCommit": commit, "targetObjectIds": ["player"],
            "fields": [], "feedback": [{"objectId": "player", "category": "behavior",
                                         "message": "Movement still feels too slow."}]}
        self.plans.append(plan_result(document))
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=project_id,
            workflow="objects-v1", expected_publication_revision=3, change_request=feedback_request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        self.assertFalse(self.coordinator._data_only_update(ready))
        job = self._dispatch(ready)
        self.assertEqual(job["status"], "FAILED", job)
        self.assertIn("没有实际修改", job.get("message", ""))
        self.assertNotIn("candidate", job)

    def test_field_only_no_edit_is_verified_and_published_as_a_new_snapshot(self):
        self.coordinator.close()
        self.producer_mode = "no_edit"
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id
        document = sample_document()
        project_id, commit = self._seed_published_project(document)
        updated = copy.deepcopy(document)
        next(f for f in next(o for o in updated["objects"] if o["id"] == "player")["fields"]
             if f["id"] == "speed")["value"] = 240
        request = {"baseRevision": 3, "sourceCommit": commit, "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}], "feedback": []}
        self.plans.append(plan_result(updated))
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=project_id,
            workflow="objects-v1", expected_publication_revision=3, change_request=request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        packet = self._freeze(ready)
        self.assertTrue(packet["dataOnlyUpdate"])
        job = self.coordinator.create_job(operator_id=self.operator, packet_id=packet["id"],
            idempotency_key="test:data-only:" + packet["id"])
        result = self.coordinator.wait(job["id"], 12)
        self.assertEqual(result["status"], "READY_FOR_REVIEW", result)
        candidate = result["candidate"]
        self.assertEqual(candidate["implementationFiles"], [])
        self.assertIn("design/game.json", candidate["changedFiles"])
        self.assertTrue(candidate["dataOnlyUpdate"])
        self.assertEqual(result["verification"]["status"], "PASS")
        accepted = self.coordinator.decide_job(operator_id=self.operator, job_id=result["id"], decision="accept",
            candidate_commit=candidate["candidateCommit"], expected_publication_revision=3)
        self.assertEqual(accepted["job"]["status"], "PUBLISHED")
        self.assertEqual(accepted["snapshot"]["publicationRevision"], 4)
        self.assertEqual(accepted["snapshot"]["document"], validate_document(updated))

    def test_cancel_stops_planning_without_creating_a_ready_plan(self):
        self.planner_started = threading.Event()
        self.planner_release = threading.Event()
        self.plans.append(plan_result())
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="Explore a harbor.", workflow="objects-v1")
        self.assertTrue(self.planner_started.wait(3))
        cancelling = self.coordinator.cancel_proposal(operator_id=self.operator, proposal_id=proposal["id"])
        self.assertEqual(cancelling["status"], "PLANNING_CANCELLING")
        self.planner_release.set()
        result = self._wait_proposal(proposal["id"], {"CANCELLED", "FAILED"})
        self.assertEqual(result["status"], "CANCELLED", result)
        self.assertIsNone(result.get("document"))

    def test_cancel_during_spec_preparation_finishes_and_releases_project(self):
        preparing = threading.Event()
        release_spec = threading.Event()
        prepare_spec = self.coordinator._prepare_generic_spec

        def delayed_spec(*args):
            references = prepare_spec(*args)
            preparing.set()
            if not release_spec.wait(5):
                raise AssertionError("test did not release specification preparation")
            return references

        self.coordinator._prepare_generic_spec = delayed_spec
        self.plans.append(plan_result())
        proposal = self.coordinator.create_concept(operator_id=self.operator,
            text="Explore a harbor.", workflow="objects-v1")
        self.assertTrue(preparing.wait(3))
        cancelling = self.coordinator.cancel_proposal(operator_id=self.operator,
            proposal_id=proposal["id"])
        self.assertEqual(cancelling["status"], "PLANNING_CANCELLING")
        release_spec.set()
        result = self._wait_proposal(proposal["id"], {"CANCELLED", "FAILED"})
        self.assertEqual(result["status"], "CANCELLED", result)
        self.assertTrue(result["planningTerminationConfirmed"])
        self.assertIsNone(result.get("document"))
        self.assertNotIn("packetId", result)
        self.coordinator._prepare_generic_spec = prepare_spec
        self.plans.append(plan_result())
        next_proposal = self.coordinator.create_concept(operator_id=self.operator,
            text="Try another harbor concept.", workflow="objects-v1",
            project_id=proposal["projectId"], expected_publication_revision=0)
        ready = self._wait_proposal(next_proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)

    def test_restart_fences_active_planning_and_preserves_project_exclusivity(self):
        proposal = self._create(result=plan_result(status="NEEDS_CLARIFICATION"))
        with self.coordinator.transaction():
            current = self.coordinator._get("proposal", proposal["id"])
            current["status"] = "PLANNING"
            self.coordinator._put("proposal", current)
        self.coordinator.close()
        self.coordinator = self._new_coordinator()
        recovered = self.coordinator.get_proposal(proposal["id"])
        self.assertEqual(recovered["status"], "PLANNING_UNCERTAIN")
        with self.assertRaises(WorkflowError) as reconcile:
            self.coordinator.reconcile_proposal(operator_id=self.operator, proposal_id=proposal["id"])
        self.assertEqual(reconcile.exception.code, "LEASE_UNKNOWN")
        with self.assertRaises(WorkflowError) as busy:
            self.coordinator.create_concept(operator_id=self.operator, text="Try again.", workflow="objects-v1",
                project_id=proposal["projectId"], expected_publication_revision=0)
        self.assertEqual(busy.exception.code, "PROJECT_BUSY")


if __name__ == "__main__":
    unittest.main()

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
from backend.generic_workflow import production_failure, timeout_clarification
from backend.object_protocol import ObjectProtocolError, parse_planner_response, validate_change_request, validate_document
from backend.tests.test_object_protocol import sample_document, workbench_document


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
        feedback = packet.get("feedback") or []
        if feedback and "feedbackDecisions" not in result and result.get("status") == "READY":
            task = (result.get("tasks") or [{}])[0]
            requirement = (((result.get("document") or {}).get("requirements") or [{}])[0])
            result = {**result, "schemaVersion": "studio.planner-result.v1", "feedbackDecisions": [
                {"feedbackId": item["feedbackId"], "status": "adopted", "reason": "Captured in the planned work.",
                 "taskIds": [task["id"]] if task.get("id") else [],
                 "requirementIds": [requirement["id"]] if requirement.get("id") else []}
                for item in feedback
            ]}
        return {
            "status": self.owner.planner_status,
            "response": json.dumps(result),
            "diagnostics": {**self.owner.planner_diagnostics,
                "childTerminationConfirmed": self.owner.planner_stopped},
        }


class Producer:
    def __init__(self, owner, path, mode):
        self.owner, self.path, self.mode = owner, Path(path), mode

    def run(self, packet, cancel_event=None, reference_images=None, on_process_started=None):
        self.owner.producer_started.set()
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
        if self.owner.producer_result is not None:
            return copy.deepcopy(self.owner.producer_result)
        return {"status": "completed", "diagnostics": {"childTerminationConfirmed": True}}


def passing_verifier(project, document, base_commit=None, **kwargs):
    return {"status": "PASS", "requirements": [], "diagnostics": [], "commands": []}


class GenericWorkflowTests(unittest.TestCase):
    def setUp(self):
        readiness = patch("runners.editor_mcp.ensure_editor_mcp_ready", return_value={
            "status": "PASS", "testDouble": True, "editorStopped": True, "sourceUnchanged": True})
        readiness.start()
        self.addCleanup(readiness.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temp.name) / "workbench"
        self.plans = []
        self.planner_started = None
        self.planner_release = None
        self.planner_stopped = True
        self.planner_status = "completed"
        self.planner_diagnostics = {}
        self.producer_mode = "normal"
        self.producer_started = threading.Event()
        self.verifier_started = threading.Event()
        self.producer_result = None
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id

    def tearDown(self):
        if self.coordinator is not None and not self.coordinator._closed:
            self.coordinator.close()
        self.temp.cleanup()

    def _new_coordinator(self):
        def verifier(project, document, **kwargs):
            self.verifier_started.set()
            return passing_verifier(project, document, **kwargs)

        return Coordinator(
            REPO_ROOT,
            state_root=self.state_root,
            test_data=True,
            planner_driver_factory=lambda path: Planner(self, path),
            generic_driver_factory=lambda path: Producer(self, path, self.producer_mode),
            generic_verifier=verifier,
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

    def test_public_frozen_input_retains_only_user_discussion(self):
        from backend.studio_protocol import public
        proposal = self._create()
        proposal["discussion"].extend([
            {"role": "user", "text": "  屋檐下改为：这里淋不到雨\n", "answers": [{"questionId": "text", "text": "保持中文"}], "cwd": "private"},
            {"role": "planner", "text": "internal planner trace"},
        ])
        with self.coordinator.transaction():
            self.coordinator._put("proposal", proposal)
        packet = public(self._freeze(proposal))
        self.assertNotIn("approvedProposal", packet)
        self.assertEqual(packet["userDiscussion"][-1]["text"], proposal["discussion"][-2]["text"])
        self.assertEqual(packet["userDiscussion"][-1]["answers"], proposal["discussion"][-2]["answers"])
        self.assertNotIn("cwd", packet["userDiscussion"][-1])
        self.assertTrue(all(turn["role"] == "user" for turn in packet["userDiscussion"]))

    def test_public_frozen_discussion_retains_questions_and_chinese_choice_meaning(self):
        from backend.studio_protocol import public
        proposal = self._create()
        question = {"id": "change-scope", "type": "choice", "prompt": "本次只改速度吗？",
                    "options": [{"value": "speed-only", "label": "仅调整速度至300，其余保持"}]}
        turns = [{"role": "planner", "summary": "private model summary", "questions": [question], "cwd": "private"},
                 {"role": "user", "text": "  保留这条原文\n", "answers": [{"questionId": "change-scope", "text": "speed-only"}], "cwd": "private"}]
        proposal["discussion"].extend(turns)
        with self.coordinator.transaction():
            self.coordinator._put("proposal", proposal)
        packet = public(self._freeze(proposal))
        self.assertEqual(packet["discussion"][-2], {"role": "planner", "questions": [question]})
        self.assertEqual(packet["discussion"][-1], {key: turns[-1][key] for key in ("role", "text", "answers")})
        self.assertTrue(all(turn["role"] == "user" for turn in packet["userDiscussion"]))
        self.assertNotIn("private", json.dumps(packet["discussion"]))
        proposal["discussion"][-2]["questions"][0]["prompt"] = "later draft"
        self.assertEqual(packet["discussion"][-2]["questions"][0]["prompt"], "本次只改速度吗？")

    def test_repair_inherits_exact_visual_references_and_explicit_empty_cancels(self):
        import base64
        proposal = self._create()
        asset = self.coordinator.upload_asset(operator_id=self.operator, project_id=proposal["projectId"],
            name="reference.png", mime_type="image/png", purpose="reference",
            data_base64=base64.b64encode((REPO_ROOT / "frontend/dist/assets/arch.png").read_bytes()).decode())
        reference = {"assetId": asset["id"], "intent": "只采纳暖光", "preserve": "保持操作", "unknown": "不确定坐标", "targetObjectIds": ["player"]}
        proposal.update(assets=[asset], visualReferences=[reference])
        with self.coordinator.transaction():
            self.coordinator._put("proposal", proposal)
        first = self._dispatch(proposal)
        self._reject_candidate(first)
        repair = self.coordinator.repair_context(proposal["projectId"])
        self.assertEqual(repair["visualReferences"], [reference])
        request = {"baseRevision": 0, "sourceCommit": repair["sourceCommit"], "targetObjectIds": [], "fields": [], "feedback": []}
        self.plans.append(plan_result(first["candidate"]["document"]))
        inherited = self.coordinator.create_concept(operator_id=self.operator, project_id=proposal["projectId"],
            text="检查屋檐", expected_publication_revision=0, change_request=request)
        inherited = self._wait_proposal(inherited["id"], {"READY", "FAILED"})
        self.assertEqual(inherited["status"], "READY", inherited)
        self.assertEqual(inherited["visualReferences"], [reference])
        self.assertEqual(inherited["assets"][0]["id"], asset["id"])
        self.plans.append(plan_result(first["candidate"]["document"]))
        cleared = self.coordinator.create_concept(operator_id=self.operator, project_id=proposal["projectId"],
            text="取消视觉参考", expected_publication_revision=0, change_request=request, asset_ids=[], visual_references=[])
        cleared = self._wait_proposal(cleared["id"], {"READY", "FAILED"})
        self.assertEqual(cleared["visualReferences"], [])
        self.assertEqual(cleared["assets"], [])

    def test_legacy_freeze_roundtrips_public_project_view_and_keeps_private_binding(self):
        proposal = self._create()
        visible = self.coordinator.project_view(proposal["projectId"])["proposal"]
        self.assertNotIn("specInventory", visible)
        self.assertNotIn("templateInventory", visible)
        packet = self._freeze(visible)
        self.assertEqual(packet["approvedProposal"], proposal)
        self.assertEqual(packet["specInventory"], proposal["specInventory"])
        self.assertEqual(packet["templateInventory"], proposal["templateInventory"])
        self.assertEqual(self._freeze(visible)["id"], packet["id"])

    def test_readiness_failure_prevents_local_generic_producer_dispatch(self):
        from runners.editor_mcp import EditorMCPError
        for uncertain in (False, True):
            proposal = self._create()
            self.producer_started.clear()
            with patch("runners.editor_mcp.ensure_editor_mcp_ready", side_effect=EditorMCPError(
                    "editor not ready", report={"editorStopped": not uncertain})):
                job = self._dispatch(proposal)
            self.assertFalse(self.producer_started.is_set())
            self.assertEqual(job["status"], "UNCERTAIN" if uncertain else "FAILED")

    def test_legacy_public_review_still_rejects_changed_or_incomplete_content(self):
        proposal = self._create()
        visible = self.coordinator.project_view(proposal["projectId"])["proposal"]
        for mutation in ("summary", "document", "missing", "private"):
            reviewed = copy.deepcopy(visible)
            if mutation == "summary":
                reviewed["summary"] = "Unreviewed change"
            elif mutation == "document":
                reviewed["document"]["objects"][1]["description"] = "Unreviewed mechanic"
            elif mutation == "missing":
                reviewed.pop("tasks")
            else:
                reviewed["specInventory"] = {}
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError) as error:
                self._freeze(reviewed)
            self.assertEqual(error.exception.code, "REVIEW_MISMATCH")
        self.assertEqual(self.coordinator.get_proposal(proposal["id"])["status"], "READY")

    def test_legacy_public_review_still_checks_backend_spec_inventory(self):
        proposal = self._create()
        visible = self.coordinator.project_view(proposal["projectId"])["proposal"]
        spec = self.state_root / "planning" / proposal["id"] / f"spec-{proposal['revision']}" / "SPEC.md"
        spec.write_text(spec.read_text() + "\nUnreviewed specification change.\n")
        with self.assertRaises(WorkflowError) as error:
            self._freeze(visible)
        self.assertEqual(error.exception.code, "REVIEW_SOURCE_DRIFT")

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
        self.assertEqual(ready["changeRequest"]["feedback"], [{**request["feedback"][0], "feedbackId": "legacy-feedback-0"}])
        self.assertEqual(next(f["value"] for o in ready["document"]["objects"] if o["id"] == "player"
                              for f in o["fields"] if f["id"] == "speed"), 240)

    def test_operations_only_iteration_freezes_nonempty_scope_and_specs(self):
        from backend.game_spec import render_spec_documents

        document = sample_document()
        project_id, commit = self._seed_published_project(document)
        updated = copy.deepcopy(document)
        updated["objects"].append({"id": "draft-bonus-scene", "kind": "scene", "name": "Bonus scene",
            "sourceBindings": ["scenes/bonus.tscn"], "fields": []})
        updated["requirements"].append({"id": "bonus-scene-ready", "text": "The bonus scene can be opened.",
            "objectIds": ["draft-bonus-scene"], "verification": "manual"})
        planned = plan_result(updated)
        planned["summary"] = "Add the reviewed bonus scene."
        planned["tasks"][0]["description"] = "Create and connect the bonus scene."
        planned["tasks"][0]["objectIds"].append("draft-bonus-scene")
        planned["tasks"][0]["requirementIds"].append("bonus-scene-ready")
        self.plans.append(planned)
        request = {"baseRevision": 3, "sourceCommit": commit, "targetObjectIds": [], "fields": [],
            "feedback": [], "operations": [{"operationId": "add-bonus-scene", "kind": "new-scene",
                "sceneId": "draft-bonus-scene", "name": "Bonus scene", "template": "minimal", "scope": "a new playable room"}]}
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=project_id,
            workflow="objects-v1", expected_publication_revision=3, change_request=request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        self.assertEqual(ready["changeRequest"]["operations"], request["operations"])
        added = next(change for change in ready["objectChanges"] if change["objectId"] == "draft-bonus-scene")
        self.assertEqual(added["action"], "added")
        self.assertEqual(added["after"]["name"], "Bonus scene")

        spec_files = render_spec_documents(ready["document"], ready["tasks"], ready["changeRequest"])
        for name in ("GDD.md", "PLAN.md", "DESIGN.md"):
            self.assertIn("add-bonus-scene", spec_files[name])
            self.assertIn("Bonus scene", spec_files[name])
        spec_root = self.state_root / "planning" / ready["id"] / f"spec-{ready['revision']}"
        self.assertEqual((spec_root / "PLAN.md").read_text(), spec_files["PLAN.md"])

        packet = self._freeze(ready)
        self.assertEqual(packet["changeRequest"]["operations"], request["operations"])
        self.assertFalse(packet["dataOnlyUpdate"])

    def test_planner_ready_cannot_move_fixed_or_unrequested_locked_instances(self):
        before = workbench_document()
        player = next(obj for obj in before["objects"] if obj["id"] == "player-instance")
        player["workbench"]["lock"] = "fixed"
        moved = copy.deepcopy(before)
        next(obj for obj in moved["objects"] if obj["id"] == "player-instance")["workbench"]["position"] = [31, 40]
        with self.assertRaises(WorkflowError) as fixed:
            Coordinator._check_requested_fields(moved, {"fields": [], "operations": []}, before)
        self.assertEqual(fixed.exception.code, "PLAN_CHANGE_MISMATCH")

        before = workbench_document()
        player = next(obj for obj in before["objects"] if obj["id"] == "player-instance")
        player["workbench"]["lock"] = "nudge"
        request = {"fields": [], "operations": [{"operationId": "nudge-player", "kind": "move",
            "objectId": "player-instance", "before": [30, 40], "requested": [31, 40], "lock": "nudge"}]}
        moved = copy.deepcopy(before)
        next(obj for obj in moved["objects"] if obj["id"] == "player-instance")["workbench"]["position"] = [31, 40]
        Coordinator._check_requested_fields(moved, request, before)
        unlocked = copy.deepcopy(moved)
        next(obj for obj in unlocked["objects"] if obj["id"] == "player-instance")["workbench"]["lock"] = "free"
        with self.assertRaises(WorkflowError) as nudge:
            Coordinator._check_requested_fields(unlocked, request, before)
        self.assertEqual(nudge.exception.code, "PLAN_CHANGE_MISMATCH")

        off_grid = copy.deepcopy(moved)
        next(obj for obj in off_grid["objects"] if obj["id"] == "player-instance")["workbench"]["position"] = [31.5, 40]
        with self.assertRaises(WorkflowError) as nudge_step:
            Coordinator._check_requested_fields(off_grid, request, before)
        self.assertEqual(nudge_step.exception.code, "PLAN_CHANGE_MISMATCH")

        before = workbench_document()
        free = next(obj for obj in before["objects"] if obj["id"] == "player-instance")
        unrequested_move = copy.deepcopy(before)
        next(obj for obj in unrequested_move["objects"] if obj["id"] == "player-instance")["workbench"]["position"] = [31, 40]
        with self.assertRaises(WorkflowError) as free_move:
            Coordinator._check_requested_fields(unrequested_move, {"fields": [], "operations": []}, before)
        self.assertEqual(free_move.exception.code, "PLAN_CHANGE_MISMATCH")

        unrequested_delete = copy.deepcopy(before)
        unrequested_delete["objects"] = [obj for obj in unrequested_delete["objects"] if obj["id"] != "player-instance"]
        with self.assertRaises(WorkflowError) as free_delete:
            Coordinator._check_requested_fields(unrequested_delete, {"fields": [], "operations": []}, before)
        self.assertEqual(free_delete.exception.code, "PLAN_CHANGE_MISMATCH")

        unrequested_unlock = copy.deepcopy(before)
        next(obj for obj in unrequested_unlock["objects"] if obj["id"] == "player-instance")["workbench"]["lock"] = "nudge"
        with self.assertRaises(WorkflowError) as free_unlock:
            Coordinator._check_requested_fields(unrequested_unlock, {"fields": [], "operations": []}, before)
        self.assertEqual(free_unlock.exception.code, "PLAN_CHANGE_MISMATCH")

    def test_planner_honors_only_explicit_lock_changes(self):
        before = workbench_document()
        instance = next(obj for obj in before["objects"] if obj["id"] == "player-instance")
        instance["workbench"]["lock"] = "fixed"
        after = copy.deepcopy(before)
        changed = next(obj for obj in after["objects"] if obj["id"] == "player-instance")
        changed["workbench"].update(lock="nudge", position=[31, 40])
        operations = [
            {"operationId": "unlock", "kind": "set-lock", "objectId": "player-instance", "before": "fixed", "lock": "nudge"},
            {"operationId": "nudge", "kind": "move", "objectId": "player-instance", "before": [30, 40], "requested": [31, 40], "lock": "nudge"},
        ]
        Coordinator._check_requested_fields(after, {"fields": [], "operations": operations}, before,
                                            tasks=[{"objectIds": ["player-instance"]}])
        with self.assertRaises(WorkflowError):
            Coordinator._check_requested_fields(after, {"fields": [], "operations": operations[1:]}, before)
        changed["workbench"]["lock"] = "free"
        with self.assertRaises(WorkflowError):
            Coordinator._check_requested_fields(after, {"fields": [], "operations": operations}, before)
        changed["workbench"].update(lock="nudge", position=[31.5, 40])
        operations[1]["requested"] = [31.5, 40]
        with self.assertRaises(WorkflowError):
            Coordinator._check_requested_fields(after, {"fields": [], "operations": operations}, before)

    def test_planner_ready_must_materialize_declared_scene_and_positioned_instance(self):
        before = workbench_document()
        request = {"fields": [], "operations": [
            {"operationId": "new-room-op", "kind": "new-scene", "sceneId": "draft-room",
             "name": "Bonus room", "template": "blank", "bounds": [200, 160],
             "connections": "Keep this room independent.", "scope": "standalone room"},
            {"operationId": "new-player-op", "kind": "new-instance", "instanceId": "draft-player",
             "name": "Bonus player", "definitionId": "player", "sceneId": "draft-room",
             "requestedPosition": [50, 60], "size": [20, 20], "anchor": [0.5, 0.5], "lock": "free"},
        ]}
        candidate = copy.deepcopy(before)
        candidate["objects"].extend([
            {"id": "draft-room", "kind": "scene", "name": "Bonus room", "description": "Keep this room independent.",
             "workbench": {"role": "scene", "bounds": [200, 160]}},
            {"id": "draft-player", "kind": "entity", "name": "Bonus player", "description": "",
             "workbench": {"role": "instance", "definitionId": "player", "sceneId": "draft-room",
                 "position": [50, 60], "size": [20, 20], "anchor": [0.5, 0.5], "lock": "free"}},
        ])
        tasks = [{"id": "room-task", "description": "Build the bonus room and player.",
            "objectIds": ["draft-room", "draft-player"], "requirementIds": []}]
        Coordinator._check_requested_fields(candidate, request, before, tasks)

        wrong_position = copy.deepcopy(candidate)
        next(obj for obj in wrong_position["objects"] if obj["id"] == "draft-player")["workbench"]["position"] = [51, 60]
        with self.assertRaises(WorkflowError) as mismatch:
            Coordinator._check_requested_fields(wrong_position, request, before, tasks)
        self.assertEqual(mismatch.exception.code, "PLAN_CHANGE_MISMATCH")

        missing_scene = copy.deepcopy(candidate)
        missing_scene["objects"] = [obj for obj in missing_scene["objects"] if obj["id"] != "draft-room"]
        with self.assertRaises(WorkflowError) as missing:
            Coordinator._check_requested_fields(missing_scene, request, before, tasks)
        self.assertEqual(missing.exception.code, "PLAN_CHANGE_MISMATCH")

        omitted_connection = copy.deepcopy(candidate)
        next(obj for obj in omitted_connection["objects"] if obj["id"] == "draft-room")["description"] = ""
        with self.assertRaises(WorkflowError) as connection:
            Coordinator._check_requested_fields(omitted_connection, request, before, tasks)
        self.assertEqual(connection.exception.code, "PLAN_CHANGE_MISMATCH")

        omitted_task_target = [{"id": "room-task", "description": "Build the bonus room.",
            "objectIds": ["draft-room"], "requirementIds": []}]
        with self.assertRaises(WorkflowError) as task_coverage:
            Coordinator._check_requested_fields(candidate, request, before, omitted_task_target)
        self.assertEqual(task_coverage.exception.code, "PLAN_CHANGE_MISMATCH")

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

    def test_gm_inspection_failure_is_saved_and_stops_before_production_driver(self):
        from backend.general_gm_integration import GMIntegrationError

        proposal = self._create(text="Make a harbor exploration prototype.")
        with patch(
            "backend.general_gm_integration.spec_confirmed",
            side_effect=GMIntegrationError("pinned stage event reader is unavailable"),
        ):
            job = self._dispatch(proposal)

        self.assertEqual(job["status"], "FAILED", job)
        self.assertEqual(job["failureCode"], "GM_INTEGRATION")
        self.assertEqual(
            job["gmSpecificationConfirmation"]["status"], "BLOCKED"
        )
        self.assertIn("Synthetic test approval", job["gmSpecificationConfirmation"]["message"])
        self.assertNotIn("candidate", job)
        self.assertNotIn("sessionEvidence", job)
        self.assertFalse(self.producer_started.is_set())

    def test_stopped_production_timeout_keeps_partial_edit_unpublished(self):
        self.producer_result = {
            "status": "timeout",
            "response": "private native response that must remain out of the summary",
            "diagnostics": {
                "elapsedSeconds": 1800.0,
                "childTerminationConfirmed": True,
                "effectsMayHaveOccurred": True,
                "nativeErrors": [{"message": "Reconnecting... 1/5"}],
                "approvalRequests": [],
                "protocolErrors": [],
            },
        }
        proposal = self._create(text="Make a harbor exploration prototype.")
        job = self._dispatch(proposal)

        self.assertEqual(job["status"], "FAILED", job)
        self.assertEqual(job["failureCode"], "PRODUCTION_TIMEOUT")
        self.assertEqual(job["sessionEvidence"]["status"], "timeout")
        failure = job["productionFailure"]
        self.assertEqual(failure["nativeStatus"], "timeout")
        self.assertTrue(failure["terminationConfirmed"])
        self.assertTrue(failure["effectsMayHaveOccurred"])
        self.assertTrue(failure["connectionInterrupted"])
        self.assertEqual(failure["code"], "PRODUCTION_TIMEOUT")
        self.assertIn("重连记录", failure["message"])
        self.assertEqual(failure["nextAction"], "NEW_PLANNING")
        self.assertIn("productionFailure", job)
        job_folder = self.state_root / "jobs" / job["id"]
        self.assertTrue((job_folder / "worktree/scripts/player.gd").is_file())
        self.assertFalse(self.verifier_started.is_set())
        self.assertNotIn("candidate", job)
        self.assertEqual(self.coordinator._get("project", proposal["projectId"])["publicationRevision"], 0)
        self.assertFalse(any(c.get("jobId") == job["id"] for c in self.coordinator._all("candidate")))
        self.assertNotIn(self.producer_result["response"], json.dumps(failure, ensure_ascii=False))

    def test_unconfirmed_production_timeout_keeps_exclusivity_and_requires_reconcile(self):
        self.producer_result = {
            "status": "timeout",
            "diagnostics": {"elapsedSeconds": 1800.0, "childTerminationConfirmed": False},
        }
        proposal = self._create(text="Make a harbor exploration prototype.")
        job = self._dispatch(proposal)

        self.assertEqual(job["status"], "UNCERTAIN", job)
        self.assertEqual(job["failureCode"], "PRODUCTION_UNCERTAIN")
        self.assertEqual(job["productionFailure"]["nextAction"], "RECONCILE")
        with self.assertRaises(WorkflowError) as busy:
            self.coordinator.create_concept(operator_id=self.operator,
                project_id=proposal["projectId"], expected_publication_revision=0,
                text="Do not dispatch while the prior maker session is uncertain.")
        self.assertEqual(busy.exception.code, "PROJECT_BUSY")
        with self.assertRaises(WorkflowError) as reconcile:
            self.coordinator.reconcile_job(operator_id=self.operator, job_id=job["id"])
        self.assertEqual(reconcile.exception.code, "LEASE_UNKNOWN")
        self.assertEqual(self.coordinator.get_job(job["id"])["status"], "UNCERTAIN")
        self.assertFalse(self.verifier_started.is_set())
        self.assertNotIn("candidate", job)

    def test_legacy_failed_job_diagnosis_is_read_only(self):
        proposal = self._create(text="Create a project for historical failure diagnostics.")
        job_id = "job-legacy-generic-timeout"
        legacy = {
            "id": job_id,
            "projectId": proposal["projectId"],
            "workflow": "objects-v1",
            "status": "FAILED",
            "message": "制作 session 没有完成，没有可发布候选。",
            "sessionEvidence": {
                "status": "timeout",
                "diagnostics": {"childTerminationConfirmed": True, "elapsedSeconds": 1800.0},
            },
        }
        with self.coordinator.transaction():
            self.coordinator._put("job", legacy)
        original = self.coordinator.db.execute(
            "SELECT payload FROM entities WHERE kind='job' AND id=?", (job_id,)
        ).fetchone()[0]

        read_job = self.coordinator.get_job(job_id)
        self.assertEqual(read_job["productionFailure"]["code"], "PRODUCTION_TIMEOUT")
        workspace_job = next(j for j in self.coordinator.project_workspace(proposal["projectId"])["jobs"]
                             if j["id"] == job_id)
        self.assertEqual(workspace_job["productionFailure"], read_job["productionFailure"])
        current = self.coordinator.db.execute(
            "SELECT payload FROM entities WHERE kind='job' AND id=?", (job_id,)
        ).fetchone()[0]
        self.assertEqual(current, original)

    def test_production_failure_summary_sanitizes_time_and_ignores_plugin_cache_warning(self):
        secret = "sk-live-do-not-display"
        for elapsed in (float("nan"), float("inf"), True):
            with self.subTest(elapsed=elapsed):
                failure = production_failure({
                    "status": "timeout",
                    "response": secret,
                    "diagnostics": {
                        "elapsedSeconds": elapsed,
                        "childTerminationConfirmed": True,
                        "error": "invalid api key: " + secret,
                        "stderr": ["plugin cache network warning: responses_retry cache refresh failed"],
                    },
                })
                self.assertIsNone(failure["elapsedSeconds"])
                self.assertEqual(failure["code"], "PRODUCTION_AUTH")
                self.assertFalse(failure["connectionInterrupted"])
                self.assertNotIn(secret, json.dumps(failure, ensure_ascii=False))

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

    def _reject_candidate(self, job):
        return self.coordinator.decide_job(operator_id=self.operator, job_id=job["id"], decision="reject",
            candidate_commit=job["candidate"]["candidateCommit"],
            expected_publication_revision=self.coordinator._get("project", job["projectId"])["publicationRevision"])

    def test_first_rejection_repairs_exact_candidate_and_can_produce_again(self):
        first = self._dispatch(self._create())
        self.assertEqual(first["status"], "READY_FOR_REVIEW", first)
        self._reject_candidate(first)
        pid, commit = first["projectId"], first["candidate"]["candidateCommit"]
        view = self.coordinator.project_view(pid)
        self.assertEqual((view["phase"], view["step"]), ("iteration", "repair"))
        self.assertIn("iteration.submit", view["allowedActions"])
        self.assertFalse(view["iterationReady"])
        self.assertIsNone(view["snapshot"])
        self.assertEqual(view["project"]["publicationRevision"], 0)
        self.assertEqual(view["repairContext"]["sourceCommit"], commit)
        self.assertEqual(self.coordinator.workbench(pid)["repairContext"], view["repairContext"])
        self.coordinator.close()
        self.coordinator = self._new_coordinator()
        self.operator = self.coordinator.operator_id
        self.assertEqual(self.coordinator.project_view(pid)["repairContext"], view["repairContext"])
        request = {"baseRevision": 0, "sourceCommit": commit, "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}],
            "feedback": [{"objectId": "player", "category": "behavior", "message": "Improve movement"}]}
        for bad in (None, {**request, "sourceCommit": "stale-candidate"}):
            with self.assertRaises(WorkflowError):
                self.coordinator.create_concept(operator_id=self.operator, text="repair", project_id=pid,
                    expected_publication_revision=0, change_request=bad)
        updated = copy.deepcopy(first["candidate"]["document"])
        next(f for o in updated["objects"] if o["id"] == "player" for f in o["fields"] if f["id"] == "speed")["value"] = 240
        self.plans.append(plan_result(updated))
        proposal = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=pid,
            expected_publication_revision=0, change_request=request)
        ready = self._wait_proposal(proposal["id"], {"READY", "FAILED"})
        self.assertEqual(ready["status"], "READY", ready)
        self.assertEqual(ready["baseCommit"], commit)
        self.assertEqual(ready["currentDocument"], first["candidate"]["document"])
        self.assertEqual(ready["changeRequest"]["feedback"], [{**request["feedback"][0], "feedbackId": "legacy-feedback-0"}])
        self.assertEqual(ready["repairBase"]["candidateId"], first["candidate"]["id"])
        self.producer_mode = "no_edit"
        # Submit a fresh field-only revision through the public workflow.
        self.plans.append(plan_result(updated))
        p = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=pid,
            expected_publication_revision=0, change_request={**request, "feedback": []})
        second = self._dispatch(self._wait_proposal(p["id"], {"READY", "FAILED"}))
        self.assertEqual(second["status"], "READY_FOR_REVIEW", second)
        self.assertEqual(second["originalBaseCommit"], commit)
        self.assertEqual(self.coordinator._get("project", pid)["publicationRevision"], 0)
        self.assertIsNone(self.coordinator._get("project", pid)["snapshotId"])

    def test_rejection_preserves_published_snapshot_but_uses_rejected_candidate_for_repair(self):
        first = self._dispatch(self._create())
        candidate = first["candidate"]
        accepted = self.coordinator.decide_job(operator_id=self.operator, job_id=first["id"], decision="accept",
            candidate_commit=candidate["candidateCommit"], expected_publication_revision=0)
        pid = first["projectId"]
        document = copy.deepcopy(candidate["document"])
        next(f for o in document["objects"] if o["id"] == "player" for f in o["fields"] if f["id"] == "speed")["value"] = 240
        self.plans.append(plan_result(document))
        request = {"baseRevision": 1, "sourceCommit": candidate["candidateCommit"], "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}], "feedback": []}
        p = self.coordinator.create_concept(operator_id=self.operator, text="", project_id=pid,
            expected_publication_revision=1, change_request=request)
        self.producer_mode = "no_edit"
        second = self._dispatch(self._wait_proposal(p["id"], {"READY", "FAILED"}))
        self.assertEqual(second["status"], "READY_FOR_REVIEW", second)
        self._reject_candidate(second)
        view = self.coordinator.project_view(pid)
        from backend.studio_protocol import public
        self.assertEqual(view["snapshot"], public(accepted["snapshot"]))
        self.assertEqual(view["project"]["publicationRevision"], 1)
        self.assertEqual(view["repairContext"]["sourceCommit"], second["candidate"]["candidateCommit"])
        self.assertNotEqual(view["repairContext"]["sourceCommit"], view["snapshot"]["sourceCommit"])
        self.assertTrue(view["iterationReady"])

    def test_v1_repair_command_requires_exact_source_and_retains_artifact_without_publication(self):
        from backend.tests.test_studio_protocol import fixture_role_evidence
        first = self._dispatch(self._create())
        self._reject_candidate(first)
        pid, commit = first["projectId"], first["candidate"]["candidateCommit"]
        # A separate artifact store models the runner protocol, independent of its project copy.
        source = self.state_root / "fixture-artifact"
        subprocess.run(["git", "clone", "--no-hardlinks", str(self.state_root / "jobs" / first["id"] / "worktree"), str(source)], capture_output=True, check=True)
        shutil.rmtree(self.state_root / "projects" / pid)
        with self.coordinator.transaction():
            project = self.coordinator._get("project", pid)
            project.update(protocolVersion=1, executionBackend="runners")
            self.coordinator._put("project", project)
            job = self.coordinator._get("job", first["id"])
            job["candidate"]["artifactRef"] = {"fixture": True}
            self.coordinator._put("job", job)
        caps = ["planning-readonly-v1", "production-private-v1"]
        self.coordinator.register_runner({"runnerId": "repair-agent", "runnerKind": "agent", "environment": "test-fixture",
            "nativeVersion": "fixture", "capabilities": caps,
            "sandboxEvidence": fixture_role_evidence("repair-agent", "agent", caps)})
        self.coordinator.update_runner_catalog({"runnerId": "repair-agent", "catalogRevision": 1, "observedAt": "2026-10-14T00:00:00Z",
            "models": [{"modelKey": "fixture", "modelProvider": "fixture", "supportedReasoningEfforts": ["medium"], "inputModalities": ["text"], "isDefault": True}]})
        message = {"schemaVersion": "studio.message.v1", "kind": "command", "type": "iteration.submit", "storeId": self.coordinator.store_id,
            "projectId": pid, "commandId": "repair-stale", "expected": {"publicationRevision": 0, "preferencesRevision": 0, "sourceCommit": None},
            "payload": {"text": "Fix movement", "assetRefs": [], "targetObjectIds": ["player"], "fields": [],
                "feedback": [{"feedbackId": "movement", "objectId": "player", "category": "behavior", "message": "Too slow"}]}}
        receipt = self.coordinator.submit_command(message, operator_id=self.operator, project_id=pid)
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["error"]["code"], "STALE_SOURCE")
        old_revision = copy.deepcopy(message)
        old_revision.update(type="proposal.revise", commandId="repair-old-plan",
            payload={"proposalId": self.coordinator._get("packet", first["packetId"])["proposalId"], "supplement": "repair"})
        old_revision["expected"].update(sourceCommit=commit, proposalRevision=1)
        old_receipt = self.coordinator.submit_command(old_revision, operator_id=self.operator, project_id=pid)
        self.assertEqual(old_receipt["status"], "rejected")
        self.assertEqual(old_receipt["error"]["code"], "STALE_REPAIR")
        message["commandId"] = "repair-valid"
        message["expected"]["sourceCommit"] = commit
        with patch.object(self.coordinator, "_artifact_repository", return_value=source):
            receipt = self.coordinator.submit_command(message, operator_id=self.operator, project_id=pid)
        self.assertEqual(receipt["status"], "accepted", receipt)
        proposal = receipt["result"]["proposal"]
        self.assertEqual(proposal["baseCommit"], commit)
        self.assertEqual(proposal["changeRequest"]["feedback"][0]["feedbackId"], "movement")
        target = self.state_root / "projects" / pid
        self.assertEqual(subprocess.run(["git", "rev-parse", "refs/heads/studio-repair/" + first["id"]], cwd=target, text=True, capture_output=True, check=True).stdout.strip(), commit)
        self.assertFalse((target / "project.godot").exists())
        self.assertIsNone(self.coordinator._get("project", pid)["snapshotId"])

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

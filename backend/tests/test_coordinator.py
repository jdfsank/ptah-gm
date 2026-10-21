"""Isolated test-mode transitions; these records cannot approve production work."""

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend.coordinator import Coordinator, WorkflowError


class FakeDriver:
    def __init__(self, path, extra=None, started=None, release=None):
        self.path, self.extra, self.started, self.release = (
            Path(path),
            extra,
            started,
            release,
        )

    def run(
        self, packet, cancel_event=None, reference_images=None, on_process_started=None
    ):
        if self.started:
            self.started.set()
        if self.release:
            self.release.wait(5)
        if not cancel_event.is_set():
            (self.path / packet["allowedFiles"][0]).write_text(
                json.dumps(packet["expectedContent"])
            )
            if self.extra:
                (self.path / self.extra).parent.mkdir(parents=True, exist_ok=True)
                (self.path / self.extra).write_text("unauthorized")
        return {
            "sessionId": "test-session",
            "status": "completed",
            "diagnostics": {
                "childTerminationConfirmed": True,
                "verificationCertified": False,
            },
        }


def fake_verify(path, operation, rules):
    return {
        "status": "PASS",
        "requirements": [{"id": "test-fixture-only", "status": "PASS"}],
        "diagnostics": [],
        "commands": [],
    }


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        readiness = mock.patch("runners.editor_mcp.ensure_editor_mcp_ready", return_value={
            "status": "PASS", "testDouble": True, "editorStopped": True, "sourceUnchanged": True})
        readiness.start()
        self.addCleanup(readiness.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        template = self.root / "backend/templates/collect_loop"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "templates/collect_loop",
            template,
            ignore=shutil.ignore_patterns(".godot"),
        )
        self.c = Coordinator(
            self.root, test_data=True, driver_factory=FakeDriver, verifier=fake_verify
        )
        self.op = self.c.operator_id

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def ready(self, project_id=None, text="收集目标调整为 4；时限调整为 20"):
        p = self.c.create_concept(operator_id=self.op, text=text, project_id=project_id)
        answers = {q["id"]: q["options"][0]["value"] for q in p["questions"]}
        return self.c.answer_proposal(
            operator_id=self.op,
            proposal_id=p["id"],
            expected_revision=p["revision"],
            answers=answers,
        )

    def test_readiness_failure_prevents_local_producer_dispatch(self):
        from runners.editor_mcp import EditorMCPError
        for uncertain in (False, True):
            packet = self.freeze(self.ready())
            with mock.patch("runners.editor_mcp.ensure_editor_mcp_ready", side_effect=EditorMCPError(
                    "editor not ready", report={"editorStopped": not uncertain})), \
                 mock.patch.object(self.c, "driver_factory") as factory:
                job = self.run_packet(packet)
            factory.assert_not_called()
            self.assertEqual(job["status"], "UNCERTAIN" if uncertain else "FAILED")

    def test_readiness_editor_lease_is_checked_when_reconciling_local_job(self):
        from runners.editor_mcp import EditorMCPError
        report = {"editorStarted": True, "editorStopped": False, "processGroupId": 987654}
        with mock.patch("runners.editor_mcp.ensure_editor_mcp_ready", side_effect=EditorMCPError(
                "editor not stopped", report=report)):
            job = self.run_packet(self.freeze(self.ready()))
        self.assertEqual(job["status"], "UNCERTAIN")
        with mock.patch("backend.coordinator.os.killpg"):
            with self.assertRaises(WorkflowError) as error:
                self.c.reconcile_job(operator_id=self.op, job_id=job["id"])
            self.assertEqual(error.exception.code, "LEASE_ACTIVE")
        with mock.patch("backend.coordinator.os.killpg", side_effect=ProcessLookupError):
            reconciled = self.c.reconcile_job(operator_id=self.op, job_id=job["id"])
        self.assertEqual(reconciled["status"], "CANCELLED")

    def freeze(self, p):
        return self.c.freeze_proposal(
            operator_id=self.op,
            proposal_id=p["id"],
            expected_revision=p["revision"],
            expected_publication_revision=p["publicationRevision"],
            reviewed_proposal=p,
        )

    def run_packet(self, packet):
        j = self.c.create_job(
            operator_id=self.op,
            packet_id=packet["id"],
            idempotency_key="packet:" + packet["id"],
        )
        return self.c.wait(j["id"], 10)

    def initialize(self):
        job = self.run_packet(self.freeze(self.ready()))
        self.assertEqual(job["status"], "PUBLISHED", job)
        self.assertFalse(job["snapshot"]["playable"])
        self.assertEqual(job["nextProposal"]["decisions"]["goalCount"], 4)
        return job

    def test_complete_snapshots_and_two_iterations(self):
        initial = self.initialize()
        first = self.run_packet(self.freeze(initial["nextProposal"]))
        self.assertEqual(first["status"], "READY_FOR_REVIEW", first)
        before = self.c.workbench(first["projectId"])["snapshot"]
        self.assertEqual(before["publicationRevision"], 1)
        result = self.c.decide_job(
            operator_id=self.op,
            job_id=first["id"],
            decision="accept",
            candidate_commit=first["candidate"]["candidateCommit"],
            expected_publication_revision=1,
        )
        snap = result["snapshot"]
        self.assertTrue(snap["playable"])
        self.assertEqual(snap["sourceCommit"], snap["catalog"]["sourceCommit"])
        self.assertEqual(snap["sourceCommit"], snap["verification"]["sourceCommit"])
        self.assertTrue(snap["testData"])
        self.assertFalse(snap["productionAuthorized"])
        second = self.run_packet(
            self.freeze(
                self.ready(
                    first["projectId"],
                    "收集目标调整为 6；时限调整为 45；移动速度调整为 300",
                )
            )
        )
        self.assertEqual(second["status"], "READY_FOR_REVIEW")
        self.assertNotEqual(
            first["candidate"]["candidateCommit"],
            second["candidate"]["candidateCommit"],
        )
        self.assertEqual(
            self.c.workbench(first["projectId"])["snapshot"]["publicationRevision"], 2
        )
        result = self.c.decide_job(
            operator_id=self.op,
            job_id=second["id"],
            decision="accept",
            candidate_commit=second["candidate"]["candidateCommit"],
            expected_publication_revision=2,
        )
        self.assertEqual(result["snapshot"]["decisions"]["goalCount"], 6)

    def test_idempotent_dispatch_and_replay(self):
        packet = self.freeze(self.ready())
        one = self.c.create_job(
            operator_id=self.op, packet_id=packet["id"], idempotency_key="same"
        )
        two = self.c.create_job(
            operator_id=self.op, packet_id=packet["id"], idempotency_key="same"
        )
        self.assertEqual(one["id"], two["id"])
        with self.assertRaises(WorkflowError):
            self.c.create_job(
                operator_id=self.op, packet_id=packet["id"], idempotency_key="different"
            )
        self.c.wait(one["id"], 10)

    def test_confirmed_timeout_partial_worktree_is_isolated(self):
        initial = self.initialize()
        project_id = initial["projectId"]
        published = self.c.workbench(project_id)["snapshot"]
        published_commit = published["sourceCommit"]
        published_rules = (
            self.c.state_root / "projects" / project_id / "config/rules.json"
        ).read_text()

        calls = []

        class PartialTimeoutDriver:
            def __init__(self, path):
                self.path = Path(path)

            def run(
                self,
                packet,
                cancel_event=None,
                reference_images=None,
                on_process_started=None,
            ):
                rules = self.path / "config/rules.json"
                prior_rules = rules.read_text() if rules.exists() else None
                calls.append((packet, self.path, prior_rules))
                rules.write_text('{"partial": true}')
                return {
                    "sessionId": "timed-out-session",
                    "status": "timeout",
                    "diagnostics": {
                        "childTerminationConfirmed": True,
                        "effectsMayHaveOccurred": True,
                    },
                }

        self.c.driver_factory = PartialTimeoutDriver
        proposal = initial["nextProposal"]
        packet = self.freeze(proposal)
        failed = self.c.create_job(
            operator_id=self.op,
            packet_id=packet["id"],
            idempotency_key="partial-timeout",
        )
        failed = self.c.wait(failed["id"], 10)
        self.assertEqual(failed["status"], "FAILED", failed)
        self.assertNotIn("candidate", failed)
        self.assertEqual(
            self.c.workbench(project_id)["snapshot"]["publicationRevision"], 1
        )
        self.assertEqual(
            self.c.workbench(project_id)["snapshot"]["sourceCommit"], published_commit
        )
        failed_tree = calls[0][1]
        self.assertEqual(
            (failed_tree / "config/rules.json").read_text(), '{"partial": true}'
        )

        replay = self.c.create_job(
            operator_id=self.op,
            packet_id=packet["id"],
            idempotency_key="partial-timeout",
        )
        self.assertEqual(replay["id"], failed["id"])
        self.assertEqual(len(calls), 1)

        next_packet = self.freeze(
            self.ready(project_id, "收集目标调整为 5；时限调整为 30")
        )
        next_job = self.c.create_job(
            operator_id=self.op,
            packet_id=next_packet["id"],
            idempotency_key="after-partial-timeout",
        )
        next_job = self.c.wait(next_job["id"], 10)
        self.assertEqual(next_job["status"], "FAILED", next_job)
        second_packet, second_tree, second_tree_rules = calls[1]
        self.assertEqual(second_packet["baseCommit"], published_commit)
        self.assertEqual(second_tree_rules, published_rules)
        self.assertNotEqual(second_tree, failed_tree)

    def test_stale_review_and_revision(self):
        p = self.ready()
        altered = dict(p, scope="forged")
        with self.assertRaises(WorkflowError):
            self.c.freeze_proposal(
                operator_id=self.op,
                proposal_id=p["id"],
                expected_revision=p["revision"],
                expected_publication_revision=0,
                reviewed_proposal=altered,
            )
        packet = self.freeze(p)
        self.assertEqual(self.freeze(p)["id"], packet["id"])
        self.run_packet(packet)
        with self.assertRaises(WorkflowError):
            self.c.create_concept(
                operator_id=self.op,
                text="调整速度",
                project_id=p["projectId"],
                expected_publication_revision=0,
            )

    def test_unsupported_scope_is_preserved_and_blocked(self):
        p = self.c.create_concept(
            operator_id=self.op, text="我想做 3D 飞行射击", asset_ids=[]
        )
        answers = {q["id"]: q["options"][0]["value"] for q in p["questions"]}
        answers["template"] = "unsupported"
        p = self.c.answer_proposal(
            operator_id=self.op,
            proposal_id=p["id"],
            expected_revision=p["revision"],
            answers=answers,
        )
        self.assertEqual(p["status"], "BLOCKED")
        self.assertIn("3D", p["text"])
        with self.assertRaises(WorkflowError):
            self.freeze(p)

    def test_untracked_and_tracked_write_scope(self):
        for extra in ("extra.txt", "SPEC.md", ".godot/injected.gd"):
            self.c.driver_factory = lambda path, e=extra: FakeDriver(path, extra=e)
            job = self.run_packet(self.freeze(self.ready()))
            self.assertEqual(job["status"], "FAILED", job)
            self.assertNotIn("candidate", job)

    def test_custom_execution_and_verification_are_test_only(self):
        for options in ({"driver_factory": FakeDriver}, {"verifier": fake_verify}):
            with self.assertRaisesRegex(ValueError, "test-only"):
                Coordinator(
                    self.root, state_root=self.root / "invalid-production", **options
                )
        with self.assertRaisesRegex(ValueError, "boolean"):
            Coordinator(
                self.root, state_root=self.root / "invalid-mode", test_data="false"
            )
        self.assertFalse((self.root / "invalid-production").exists())
        self.assertFalse((self.root / "invalid-mode").exists())

    def test_cancellation_keeps_exclusivity_until_stopped(self):
        started, release = threading.Event(), threading.Event()
        self.c.driver_factory = lambda path: FakeDriver(
            path, started=started, release=release
        )
        p = self.ready()
        packet = self.freeze(p)
        job = self.c.create_job(
            operator_id=self.op, packet_id=packet["id"], idempotency_key="cancel"
        )
        self.assertTrue(started.wait(5))
        self.assertEqual(
            self.c.cancel_job(operator_id=self.op, job_id=job["id"])["status"],
            "CANCELLING",
        )
        with self.assertRaises(WorkflowError):
            self.ready(p["projectId"])
        release.set()
        self.assertEqual(self.c.wait(job["id"], 10)["status"], "CANCELLED")
        self.assertIsNone(
            self.c.workbench(p["projectId"])["snapshot"].get("sourceCommit")
        )

    def test_dirty_candidate_and_wrong_commit_cannot_publish(self):
        init = self.initialize()
        job = self.run_packet(self.freeze(init["nextProposal"]))
        with self.assertRaises(WorkflowError):
            self.c.decide_job(
                operator_id=self.op,
                job_id=job["id"],
                decision="accept",
                candidate_commit="wrong",
                expected_publication_revision=1,
            )
        tree = self.c.state_root / "jobs" / job["id"] / "worktree"
        (tree / "config/rules.json").write_text("{}")
        with self.assertRaises(WorkflowError):
            self.c.decide_job(
                operator_id=self.op,
                job_id=job["id"],
                decision="accept",
                candidate_commit=job["candidate"]["candidateCommit"],
                expected_publication_revision=1,
            )
        self.assertEqual(
            self.c.workbench(job["projectId"])["snapshot"]["publicationRevision"], 1
        )

    def test_restart_fences_unknown_execution_and_mode(self):
        init = self.initialize()
        self.c._update(init["id"], status="RUNNING")
        self.c.close()
        self.c = Coordinator(
            self.root, test_data=True, driver_factory=FakeDriver, verifier=fake_verify
        )
        self.assertEqual(self.c.get_job(init["id"])["status"], "UNCERTAIN")
        with self.assertRaises(WorkflowError):
            self.ready(init["projectId"])
        self.assertEqual(
            self.c.cancel_job(operator_id=self.op, job_id=init["id"])["status"],
            "UNCERTAIN",
        )
        self.c.close()
        with self.assertRaises(WorkflowError):
            Coordinator(self.root, test_data=False)

    def test_second_service_cannot_write_same_store(self):
        with self.assertRaises(WorkflowError):
            Coordinator(self.root, test_data=True, verifier=fake_verify)

    def test_limits_nonfinite_and_identity(self):
        with self.assertRaises(WorkflowError):
            self.c.create_concept(operator_id="forged", text="test")
        p = self.c.create_concept(operator_id=self.op, text="test")
        with self.assertRaises(WorkflowError):
            self.c.answer_proposal(
                operator_id=self.op,
                proposal_id=p["id"],
                expected_revision=1,
                answers={"goalCount": float("nan")},
            )
        with self.assertRaises(WorkflowError):
            self.c.answer_proposal(
                operator_id=self.op,
                proposal_id=p["id"],
                expected_revision=1,
                answers={"goalCount": 2.5},
            )

    def test_template_drift_before_confirmation_is_rejected(self):
        p = self.ready()
        template = self.root / "backend/templates/collect_loop/SPEC.md"
        template.write_text(template.read_text() + "\nchanged after review\n")
        with self.assertRaises(WorkflowError) as caught:
            self.freeze(p)
        self.assertEqual(caught.exception.code, "REVIEW_SOURCE_DRIFT")

    def test_reconcile_requires_server_recorded_stopped_group(self):
        import subprocess

        init = self.initialize()
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            self.c._update(
                init["id"],
                status="UNCERTAIN",
                executionLease={"processGroupId": proc.pid},
            )
            with self.assertRaises(WorkflowError) as caught:
                self.c.reconcile_job(operator_id=self.op, job_id=init["id"])
            self.assertEqual(caught.exception.code, "LEASE_ACTIVE")
            proc.terminate()
            proc.wait(3)
            reconciled = self.c.reconcile_job(operator_id=self.op, job_id=init["id"])
            self.assertEqual(reconciled["status"], "CANCELLED")
            self.assertEqual(
                self.c.workbench(init["projectId"])["snapshot"]["publicationRevision"],
                1,
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()

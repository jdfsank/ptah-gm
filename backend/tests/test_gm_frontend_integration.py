from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
GAME_TOOLS = ROOT / "sources/velvet-eclipse/tools"
sys.path.insert(0, str(GAME_TOOLS))
import append_stage_event as stage
import gm_review
import review_support as review

from backend import gm_integration


class FrontendApprovalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        subprocess.run(["git", "-C", str(self.root), "init", "--quiet"], check=True)
        (self.root / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        (self.root / "PLAN.md").write_text(
            """**Tag:** v0.1.0

## Game Description
An interactive demo.
## Iteration Intent
Prove the core loop.
## Tag Mechanics
- [v0.1.0-M1] Basic loop
## Inherited Mechanics
None.
## Playable Unit
| Unit | Result |
|---|---|
| Player | Can act |
## Risk Tasks
Check core interaction.
## Main Build
Build one scene.
## Task Status
Pending.
## Review Notes
Review the demo.
## Platform Commitments
| desktop | required | visible check |
""",
            encoding="utf-8",
        )
        for name in ("GDD.md", "STRUCTURE.md", "DESIGN.md", "SCENES.md", "ASSETS.md"):
            (self.root / name).write_text(f"{name} fixture\n", encoding="utf-8")
        self.godotmaker = self.root / ".godotmaker"
        self.godotmaker.mkdir()
        self.db = Path(self.temp.name) / "approvals.sqlite"
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "CREATE TABLE approvals (id TEXT PRIMARY KEY, payload TEXT, consumed INTEGER NOT NULL DEFAULT 0)"
            )
        finally:
            connection.close()
        self.db.chmod(0o600)
        self.spec = review.extract_spec(self.root)
        self.payload = {
            "schemaVersion": 1,
            "eventId": "evt-integration-1",
            "operatorId": "operator-1",
            "projectId": "velvet-eclipse",
            "phase": "specification",
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "candidateId": "candidate-1",
            "revision": "rev-1",
            "gitSpecRef": review.spec_git_ref(self.spec, self.root),
            "runId": None,
            "action": "approve",
            "createdAt": "2026-10-09T02:03:04Z",
            "provenance": {
                "kind": "interactive_frontend",
                "input": "frontend",
                "recordedBy": "approval_service",
            },
            "testData": False,
            "productionAuthorized": True,
        }
        self.binding = {
            "schemaVersion": 1,
            "storePath": str(self.db),
            "operatorId": "operator-1",
            "projectId": "velvet-eclipse",
            "testData": False,
            "productionAuthorized": True,
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "candidateId": "candidate-1",
            "revision": "rev-1",
        }
        self._write_binding()

    def tearDown(self):
        self.temp.cleanup()

    def _write_binding(self):
        (self.godotmaker / "frontend-approval.json").write_text(
            json.dumps(self.binding), encoding="utf-8"
        )

    def _insert_event(self, **changes):
        payload = {**self.payload, **changes}
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "INSERT INTO approvals(id, payload, consumed) VALUES (?, ?, 0)",
                (payload["eventId"], json.dumps(payload)),
            )
            connection.commit()
        finally:
            connection.close()
        return payload

    def test_registered_frontend_approval_confirms_current_spec_and_consumes_once(self):
        self._insert_event()
        result = review.confirm_spec(self.root, "evt-integration-1")
        self.assertEqual(result["result"], "PASS")
        event = result["event"]
        self.assertEqual(event["provenance"]["kind"], "interactive_frontend")
        self.assertEqual(
            event["git_spec_ref"], review.spec_git_ref(self.spec, self.root)
        )
        self.assertTrue(
            review._spec_confirmation_matches(
                event, self.spec, review.spec_git_ref(self.spec, self.root), self.root
            )
        )
        self.assertTrue(gm_integration.spec_confirmed(self.root))
        connection = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT consumed FROM approvals WHERE id=?", ("evt-integration-1",)
                ).fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_confirm_spec_cli_accepts_only_the_frontend_event_id(self):
        self._insert_event()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = gm_review.main(
                [
                    "confirm-spec",
                    "--project",
                    str(self.root),
                    "--frontend-event-id",
                    "evt-integration-1",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output.getvalue())["event"]["provenance"]["kind"],
            "interactive_frontend",
        )
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            gm_review.main(
                [
                    "confirm-spec",
                    "--project",
                    str(self.root),
                    "--approval-store",
                    str(self.db),
                ]
            )

    def test_stale_git_spec_and_wrong_project_are_rejected_without_consumption(self):
        self._insert_event(gitSpecRef="git:blob:" + "0" * 40)
        with self.assertRaises(review.ReviewError):
            review.confirm_spec(self.root, "evt-integration-1")
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DELETE FROM approvals")
            connection.commit()
        finally:
            connection.close()
        self._insert_event(projectId="other-project")
        with self.assertRaises(review.ReviewError):
            review.confirm_spec(self.root, "evt-integration-1")

    def test_unknown_event_and_unregistered_store_path_are_rejected(self):
        with self.assertRaises(review.ReviewError):
            review.confirm_spec(self.root, "missing-event")
        self.binding["unexpectedStorePath"] = str(self.db)
        self._write_binding()
        with self.assertRaises(review.ReviewError):
            review.confirm_spec(self.root, "evt-integration-1")

    def test_test_environment_confirmation_cannot_pass_production_spec_gate(self):
        self.binding["testData"] = True
        self.binding["productionAuthorized"] = False
        self._write_binding()
        self._insert_event()
        with self.assertRaises(review.ReviewError):
            review.confirm_spec(self.root, "evt-integration-1")
        test_event = {
            "role": "gdd",
            "tag": self.spec["tag"],
            "spec_digest": self.spec["spec_digest"],
            "git_spec_ref": review.spec_git_ref(self.spec, self.root),
            "provenance": {
                "kind": "interactive_frontend",
                "phase": "specification",
                "input": "frontend",
                "recorded_by": "approval_service",
                "event_id": "test-event",
                "operator_id": "test-operator",
                "production_authorized": False,
                "test_data": True,
            },
        }
        self.assertFalse(
            review._spec_confirmation_matches(
                test_event,
                self.spec,
                review.spec_git_ref(self.spec, self.root),
                self.root,
            )
        )
        stage.validate_fields(
            "gdd",
            {
                "tag": self.spec["tag"],
                "spec_digest": self.spec["spec_digest"],
                "git_spec_ref": review.spec_git_ref(self.spec, self.root),
                "provenance": test_event["provenance"],
            },
        )

    def test_manually_appended_frontend_provenance_without_consumed_record_is_not_confirmation(
        self,
    ):
        fabricated = {
            "kind": "interactive_frontend",
            "input": "frontend",
            "recorded_by": "approval_service",
            "event_id": "fabricated",
            "operator_id": "operator-1",
            "phase": "specification",
            "production_authorized": True,
            "test_data": False,
        }
        event = stage.append_event(
            self.root,
            "gdd",
            {
                "tag": self.spec["tag"],
                "spec_digest": self.spec["spec_digest"],
                "git_spec_ref": review.spec_git_ref(self.spec, self.root),
            },
            decision_provenance=fabricated,
        )
        self.assertFalse(
            review._spec_confirmation_matches(
                event, self.spec, review.spec_git_ref(self.spec, self.root), self.root
            )
        )

    def test_legacy_tty_confirm_spec_path_keeps_exact_provenance_and_gate_behavior(
        self,
    ):
        called = []
        original = review.interactive_confirmation
        review.interactive_confirmation = lambda prompt, expected: called.append(
            (prompt, expected)
        )
        try:
            result = review.confirm_spec(self.root)
        finally:
            review.interactive_confirmation = original
        self.assertEqual(len(called), 1)
        self.assertEqual(
            result["event"]["provenance"],
            {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"},
        )
        self.assertNotIn("git_spec_ref", result["event"])
        self.assertTrue(
            review._spec_confirmation_matches(
                result["event"],
                self.spec,
                review.spec_git_ref(self.spec, self.root),
                self.root,
            )
        )
        self.assertEqual(
            stage.LOCAL_PROVENANCE,
            {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"},
        )

    def test_adapter_uses_normalized_spec_ref_and_registers_fixed_binding(self):
        self.assertEqual(
            gm_integration.spec_ref(self.root),
            review.spec_git_ref(self.spec, self.root),
        )
        packet = {
            "projectId": "velvet-eclipse",
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "proposalRevision": 1,
            "testData": False,
            "productionAuthorized": True,
        }
        path = gm_integration.register(
            self.root, self.db, "operator-1", "velvet-eclipse", packet
        )
        self.assertEqual(path, (self.godotmaker / "frontend-approval.json").resolve())
        registered = json.loads(path.read_text())
        self.assertEqual(registered["projectId"], "velvet-eclipse")
        self.assertEqual(registered["proposalId"], "proposal-1")
        self.assertEqual(registered["packetId"], "packet-1")
        self.assertEqual(registered["jobId"], "job-1")
        self.assertEqual(registered["revision"], "1")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_adapter_loads_pinned_gm_modules_in_a_clean_interpreter(self):
        script = "from backend.gm_integration import spec_ref; import sys; print(spec_ref(sys.argv[1]))"
        completed = subprocess.run(
            [sys.executable, "-c", script, str(self.root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(), review.spec_git_ref(self.spec, self.root)
        )

    def test_adapter_skips_test_gate_and_runs_only_pinned_cli_in_production(self):
        packet = {
            "projectId": "velvet-eclipse",
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "proposalRevision": 1,
            "testData": True,
            "productionAuthorized": False,
        }
        gm_integration.register(
            self.root, self.db, "operator-1", "velvet-eclipse", packet
        )
        with self.assertRaises(gm_integration.GMIntegrationError):
            gm_integration.confirm_spec(self.root, "evt-integration-1")
        packet.update(testData=False, productionAuthorized=True)
        gm_integration.register(
            self.root, self.db, "operator-1", "velvet-eclipse", packet
        )
        completed = subprocess.CompletedProcess(
            [], 0, json.dumps({"result": "PASS", "event": {}}), ""
        )
        with mock.patch.object(
            gm_integration.subprocess, "run", return_value=completed
        ) as run:
            result = gm_integration.confirm_spec(self.root, "evt-integration-1")
        self.assertEqual(result["result"], "PASS")
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]).resolve(), gm_integration.GM_REVIEW)
        self.assertEqual(command[-2:], ["--frontend-event-id", "evt-integration-1"])

    def test_adapter_rejects_invalid_packet_flags_and_binding_symlink(self):
        packet = {
            "projectId": "velvet-eclipse",
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "proposalRevision": 1,
            "testData": False,
            "productionAuthorized": False,
        }
        with self.assertRaises(gm_integration.GMIntegrationError):
            gm_integration.register(
                self.root, self.db, "operator-1", "velvet-eclipse", packet
            )
        linked_store = Path(self.temp.name) / "linked-approvals.sqlite"
        linked_store.symlink_to(self.db)
        packet.update(testData=False, productionAuthorized=True)
        with self.assertRaises(gm_integration.GMIntegrationError):
            gm_integration.register(
                self.root, linked_store, "operator-1", "velvet-eclipse", packet
            )


if __name__ == "__main__":
    unittest.main()

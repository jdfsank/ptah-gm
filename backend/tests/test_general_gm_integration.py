"""Pure integration tests for the pinned GodotMaker non-pk approval bridge."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.game_spec import render_spec_documents
from backend.general_gm_integration import (
    APPROVAL_BINDING_REL,
    GM_TOOLS,
    REPO_ROOT,
    GMIntegrationError,
    confirm_spec,
    register,
    spec_confirmed,
    spec_ref,
)
from backend.tests.test_object_protocol import sample_document


class GeneralGMIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        tasks = [{"id": "explore-room", "description": "Explore the harbor and solve its light puzzle.",
                  "objectIds": ["main-scene", "player"], "requirementIds": ["explore"]}]
        documents = render_spec_documents(sample_document(), tasks, revision=1)
        for filename, content in documents.items():
            (self.project / filename).write_text(content, encoding="utf-8")
        self.store = self.root / "approvals.sqlite3"
        connection = sqlite3.connect(self.store)
        connection.execute("CREATE TABLE approvals(id TEXT PRIMARY KEY,payload TEXT NOT NULL,consumed INTEGER NOT NULL DEFAULT 0)")
        connection.commit()
        connection.close()
        self.store.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def _packet(self, *, test_data: bool):
        return {
            "projectId": "project-1",
            "proposalId": "proposal-1",
            "packetId": "packet-1",
            "jobId": "job-1",
            "proposalRevision": 2,
            "candidateId": None,
            "testData": test_data,
            "productionAuthorized": not test_data,
            "gmSpecRef": spec_ref(self.project),
        }

    def test_rendered_general_spec_is_accepted_and_gets_native_git_reference(self):
        plan = (self.project / "PLAN.md").read_text(encoding="utf-8")
        self.assertIn("[main-scene-M1]", plan)
        self.assertIn("requirement IDs: explore", plan)
        self.assertIn("pending human acceptance", plan)
        self.assertIn("automatically", (self.project / "ASSETS.md").read_text(encoding="utf-8"))
        reference = spec_ref(self.project)
        self.assertTrue(reference.startswith("git:blob:"))
        self.assertEqual(reference, spec_ref(self.project))
        self.assertEqual(GM_TOOLS, REPO_ROOT / "sources" / "GodotMaker-non-pk" / "tools")
        with (self.project / "SPEC.md").open("a", encoding="utf-8") as stream:
            stream.write("\nReviewed scope revision marker.\n")
        self.assertNotEqual(reference, spec_ref(self.project))

    def test_test_registration_is_diagnostic_only_and_cannot_confirm_spec(self):
        binding = register(self.project, self.store, "operator-1", "project-1", self._packet(test_data=True))
        self.assertEqual(binding.relative_to(self.project.resolve()), APPROVAL_BINDING_REL)
        saved = json.loads(binding.read_text(encoding="utf-8"))
        self.assertTrue(saved["testData"])
        self.assertFalse(saved["productionAuthorized"])
        with self.assertRaises(GMIntegrationError):
            confirm_spec(self.project, "untrusted-event")
        self.assertFalse(spec_confirmed(self.project))

    def test_unknown_production_event_is_rejected_by_real_nonpk_consumer(self):
        register(self.project, self.store, "operator-1", "project-1", self._packet(test_data=False))
        with self.assertRaises(GMIntegrationError):
            confirm_spec(self.project, "does-not-exist")
        self.assertFalse(spec_confirmed(self.project))


if __name__ == "__main__":
    unittest.main()

"""Pure integration tests for the pinned GodotMaker non-pk approval bridge."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from backend import general_gm_integration, gm_integration
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
        subprocess.run(["git", "-C", str(self.project), "init", "--quiet"], check=True)
        (self.project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
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

    def _approve(self, adapter):
        packet = self._packet(test_data=False)
        packet["gmSpecRef"] = adapter.spec_ref(self.project)
        adapter.register(self.project, self.store, "operator-1", "project-1", packet)
        event_id = "evt-" + adapter.GM_TOOLS.parent.name
        payload = {
            "schemaVersion": 1, "eventId": event_id, "operatorId": "operator-1",
            "projectId": packet["projectId"], "phase": "specification",
            "proposalId": packet["proposalId"], "packetId": packet["packetId"],
            "jobId": packet["jobId"], "candidateId": None,
            "revision": str(packet["proposalRevision"]), "gitSpecRef": packet["gmSpecRef"],
            "runId": None, "action": "approve", "createdAt": "2026-10-10T02:03:04Z",
            "provenance": {"kind": "interactive_frontend", "input": "frontend", "recordedBy": "approval_service"},
            "testData": False, "productionAuthorized": True,
        }
        with sqlite3.connect(self.store) as connection:
            connection.execute("INSERT INTO approvals(id,payload,consumed) VALUES (?,?,0)",
                               (event_id, json.dumps(payload)))
        return event_id

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

    def test_real_cli_confirmation_is_readable_without_host_import_aliases(self):
        # Only the approval CLI runs in these temporary fixtures; no maker session.
        for adapter in (general_gm_integration, gm_integration):
            with self.subTest(adapter=adapter.GM_TOOLS.parent.name):
                event_id = self._approve(adapter)
                self.assertFalse(adapter.spec_confirmed(self.project))
                result = adapter.confirm_spec(self.project, event_id)
                self.assertEqual(result["result"], "PASS")
                with mock.patch.dict(sys.modules, {"append_stage_event": types.ModuleType("host_sentinel")}):
                    self.assertTrue(adapter.spec_confirmed(self.project))
                with sqlite3.connect(self.store) as connection:
                    self.assertEqual(connection.execute("SELECT consumed FROM approvals WHERE id=?", (event_id,)).fetchone()[0], 1)
                    connection.execute("UPDATE approvals SET consumed=0 WHERE id=?", (event_id,))
                self.assertFalse(adapter.spec_confirmed(self.project))
                with sqlite3.connect(self.store) as connection:
                    connection.execute("UPDATE approvals SET consumed=1 WHERE id=?", (event_id,))
                binding = self.project / APPROVAL_BINDING_REL
                original = binding.read_text()
                changed = json.loads(original)
                changed["projectId"] = "other-project"
                binding.write_text(json.dumps(changed))
                self.assertFalse(adapter.spec_confirmed(self.project))
                binding.write_text(original)
                self.assertTrue(adapter.spec_confirmed(self.project))
                # Avoid passing another adapter's prior stage events to this fixture.
                (self.project / ".godotmaker/stage.jsonl").unlink()

    def test_changed_current_spec_invalidates_consumed_confirmation(self):
        for adapter in (general_gm_integration, gm_integration):
            with self.subTest(adapter=adapter.GM_TOOLS.parent.name):
                event_id = self._approve(adapter)
                adapter.confirm_spec(self.project, event_id)
                plan = self.project / "PLAN.md"
                original = plan.read_text()
                plan.write_text(original + "\nChanged approved scope.\n")
                self.assertFalse(adapter.spec_confirmed(self.project))
                plan.write_text(original)
                self.assertTrue(adapter.spec_confirmed(self.project))
                (self.project / ".godotmaker/stage.jsonl").unlink()

    def test_inspection_errors_are_reported_instead_of_missing_user_approval(self):
        folder = self.project / ".godotmaker"
        folder.mkdir()
        for adapter in (general_gm_integration, gm_integration):
            with self.subTest(adapter=adapter.GM_TOOLS.parent.name):
                self.assertFalse(adapter.spec_confirmed(self.project))
                (folder / "stage.jsonl").write_text("{invalid-json}\n")
                with self.assertRaisesRegex(adapter.GMIntegrationError, "记录复核失败"):
                    adapter.spec_confirmed(self.project)
                (folder / "stage.jsonl").unlink()

    def test_concurrent_first_load_pins_each_validator_and_restores_host_aliases(self):
        adapters = (general_gm_integration, gm_integration)
        cache_names = ("_ptah_pinned_general_gm_review_support", "_ptah_pinned_gm_review_support")
        dependencies = ("agent_runtime", "git_baseline", "frontend_approval", "append_stage_event")
        self.assertIs(adapters[0]._LOAD_LOCK, adapters[1]._LOAD_LOCK)
        saved = {name: sys.modules.get(name) for name in cache_names}
        original_path = list(sys.path)
        try:
            for name in cache_names:
                sys.modules.pop(name, None)
            sentinels = {name: types.ModuleType("host_" + name) for name in dependencies}
            with mock.patch.dict(sys.modules, sentinels):
                with ThreadPoolExecutor(max_workers=4) as executor:
                    modules = list(executor.map(lambda adapter: adapter._load_review_support(), adapters * 2))
                for adapter, module in zip(adapters * 2, modules):
                    self.assertEqual(Path(module.validate_fields.__code__.co_filename).parent, adapter.GM_TOOLS)
                self.assertTrue(all(sys.modules[name] is value for name, value in sentinels.items()))
            self.assertEqual(sys.path, original_path)
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()

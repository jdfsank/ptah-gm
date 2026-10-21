"""Durable transport must preserve the legacy execution owner and exact base."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.coordinator import Coordinator
from backend.tests.test_object_protocol import sample_document


class LegacyIterationCommandTests(unittest.TestCase):
    def test_lost_response_replays_one_legacy_iteration_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Coordinator(Path(__file__).resolve().parents[2], state_root=Path(directory), test_data=True)
            try:
                project = c.create_project(operator_id=c.operator_id, title="Legacy transport fixture")
                snapshot = {"id": "snapshot-base", "projectId": project["id"], "kind": "MVP",
                            "publicationRevision": 2, "sourceCommit": "retained-source", "document": sample_document()}
                with c.transaction():
                    c._put("snapshot", snapshot)
                    project.update(snapshotId=snapshot["id"], publicationRevision=2)
                    c._put("project", project)
                message = {"schemaVersion": "studio.message.v1", "kind": "command", "type": "iteration.submit",
                    "storeId": c.store_id, "projectId": project["id"], "commandId": "durable-legacy",
                    "expected": {"publicationRevision": 2, "sourceCommit": "retained-source", "preferencesRevision": 0},
                    "payload": {"text": "", "assetRefs": [], "targetObjectIds": ["player"], "fields": [],
                        "feedback": [{"feedbackId": "player-note", "objectId": "player", "category": "behavior", "message": "移动需要更顺滑。"}]}}
                with patch.object(c, "iteration_status", return_value={"iterationReady": True}), patch.object(c, "_plan_generic") as planner:
                    first = c.submit_command(message, operator_id=c.operator_id, project_id=project["id"])
                    self.assertEqual(first["status"], "accepted", first)
                    for thread in list(c._threads.values()):
                        thread.join(2)
                    replay = c.submit_command(message, operator_id=c.operator_id, project_id=project["id"])
                    self.assertEqual(first, replay)
                    self.assertEqual(planner.call_count, 1)
                self.assertEqual(len(c._all_project("proposal", project["id"])), 1)
                current = c._get("project", project["id"])
                self.assertNotIn("protocolVersion", current)
                self.assertNotIn("executionBackend", current)
                proposal = c._get("proposal", first["resource"]["id"])
                self.assertNotIn("schemaVersion", proposal["changeRequest"])
                self.assertEqual(proposal["changeRequest"]["feedback"][0]["feedbackId"], "player-note")
                stale = copy.deepcopy(message)
                stale["commandId"] = "stale-legacy"
                stale["expected"]["sourceCommit"] = "another-source"
                rejected = c.submit_command(stale, operator_id=c.operator_id, project_id=project["id"])
                self.assertEqual(rejected["error"]["code"], "STALE_SOURCE")
                self.assertEqual(len(c._all_project("proposal", project["id"])), 1)
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()

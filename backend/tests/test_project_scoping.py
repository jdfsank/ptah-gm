import base64
import json
import tempfile
import unittest
from pathlib import Path
import threading
import urllib.error
import urllib.request

from backend.coordinator import Coordinator, WorkflowError, now
from backend.server import REPO_ROOT, make_server


class ProjectScopingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.coordinator = Coordinator(self.root, state_root=self.root / "state", test_data=True)
        self.operator = self.coordinator.operator_id

    def tearDown(self):
        self.coordinator.close()
        self.temp.cleanup()

    def project(self, title):
        return self.coordinator.create_project(operator_id=self.operator, title=title)

    def test_blank_projects_and_scoped_workspace_are_independent(self):
        a, b = self.project("A"), self.project("B")
        proposal = {"id": "proposal-a", "projectId": a["id"], "status": "READY"}
        packet = {"id": "packet-a", "projectId": a["id"], "proposalId": "proposal-a"}
        job = {"id": "job-a", "projectId": a["id"], "status": "FAILED"}
        with self.coordinator.transaction():
            for kind, item in (("proposal", proposal), ("packet", packet), ("job", job)):
                self.coordinator._put(kind, item)
        manager = self.coordinator.workspace_summary()
        self.assertEqual({p["id"] for p in manager["projects"]}, {a["id"], b["id"]})
        self.assertEqual((manager["proposals"], manager["packets"], manager["jobs"]), ([], [], []))
        workspace_a = self.coordinator.project_workspace(a["id"])
        workspace_b = self.coordinator.project_workspace(b["id"])
        self.assertEqual([p["id"] for p in workspace_a["proposals"]], ["proposal-a"])
        self.assertEqual(workspace_b["proposals"], [])
        self.assertEqual(workspace_b["jobs"], [])
        with self.assertRaises(WorkflowError):
            self.coordinator.require_project_resource(b["id"], "proposal", "proposal-a")

    def test_manager_and_project_workspace_do_not_diagnose_other_projects(self):
        a, b = self.project("A"), self.project("B")
        with self.coordinator.transaction():
            self.coordinator._put("proposal", {"id": "proposal-a", "projectId": a["id"], "status": "FAILED"})
            self.coordinator._put("proposal", {"id": "proposal-b", "projectId": b["id"], "status": "FAILED"})
        seen = []
        original = self.coordinator._diagnosed_proposal
        self.coordinator._diagnosed_proposal = lambda proposal: (seen.append(proposal["id"]) or proposal)
        self.coordinator.workspace = lambda: (_ for _ in ()).throw(AssertionError("global hydration"))
        summary = self.coordinator.workspace_summary()
        self.assertEqual(summary["proposals"], [])
        self.assertEqual(seen, [])
        workspace = self.coordinator.project_workspace(a["id"])
        self.assertEqual([item["id"] for item in workspace["proposals"]], ["proposal-a"])
        self.assertEqual(seen, ["proposal-a"])
        self.coordinator._diagnosed_proposal = original

    def test_archive_refuses_live_or_uncertain_project_work(self):
        project = self.project("Named project")
        with self.coordinator.transaction():
            self.coordinator._put("proposal", {"id": "p", "projectId": project["id"], "status": "PLANNING_UNCERTAIN"})
        with self.assertRaises(WorkflowError):
            self.coordinator.update_project_settings(operator_id=self.operator, project_id=project["id"], archived=True)
        renamed = self.coordinator.update_project_settings(operator_id=self.operator, project_id=project["id"], title="Renamed")
        self.assertEqual(renamed["title"], "Renamed")

    def test_legacy_asset_owner_requires_one_unambiguous_project_reference(self):
        a, b = self.project("A"), self.project("B")
        with self.coordinator.transaction():
            self.coordinator._put("asset", {"id": "old-asset", "mimeType": "image/png"})
            self.coordinator._put("proposal", {"id": "p-a", "projectId": a["id"], "assets": [{"id": "old-asset"}]})
        self.assertEqual(self.coordinator.asset_owner("old-asset"), a["id"])
        self.coordinator.require_project_asset(a["id"], "old-asset")
        with self.coordinator.transaction():
            self.coordinator._put("packet", {"id": "packet-b", "projectId": b["id"], "assets": [{"id": "old-asset"}]})
        self.assertIsNone(self.coordinator.asset_owner("old-asset"))
        with self.assertRaises(WorkflowError):
            self.coordinator.require_project_asset(a["id"], "old-asset")

    def test_foreign_snapshot_pointer_is_rejected_by_workbench_and_iteration_gate(self):
        a, b = self.project("A"), self.project("B")
        with self.coordinator.transaction():
            self.coordinator._put("snapshot", {"id": "snapshot-b", "projectId": b["id"],
                "title": "Private B snapshot", "kind": "MVP", "playable": True})
            project_a = self.coordinator._get("project", a["id"])
            project_a["snapshotId"] = "snapshot-b"
            self.coordinator._put("project", project_a)
        with self.assertRaises(WorkflowError):
            self.coordinator.workbench(a["id"])
        with self.assertRaises(WorkflowError):
            self.coordinator.iteration_status(a["id"])

    def test_cross_project_and_ambiguous_legacy_attachments_fail_closed(self):
        a, b = self.project("A"), self.project("B")
        with self.coordinator.transaction():
            self.coordinator._put("asset", {"id": "asset-a", "projectId": a["id"], "mimeType": "image/png"})
            self.coordinator._put("proposal", {"id": "proposal-b", "projectId": b["id"],
                "workflow": "objects-v1", "revision": 1, "status": "READY", "publicationRevision": 0,
                "assets": [{"id": "asset-a"}]})
            self.coordinator._put("packet", {"id": "packet-b", "projectId": b["id"],
                "publicationRevision": 0, "assets": [{"id": "asset-a"}]})
        with self.assertRaises(WorkflowError):
            self.coordinator.project_workspace(b["id"])
        with self.assertRaises(WorkflowError):
            self.coordinator.freeze_generic_proposal(operator_id=self.operator, proposal_id="proposal-b",
                expected_revision=1, expected_publication_revision=0,
                reviewed_proposal=self.coordinator._get("proposal", "proposal-b"))
        legacy_project = self.coordinator.create_project(operator_id=self.operator, title="Legacy", workflow="collect-loop-v1")
        legacy_proposal = {"id": "legacy-proposal", "projectId": legacy_project["id"],
            "workflow": "collect-loop-v1", "revision": 1, "status": "READY",
            "publicationRevision": 0, "assets": [{"id": "asset-a"}]}
        with self.coordinator.transaction():
            self.coordinator._put("proposal", legacy_proposal)
        with self.assertRaises(WorkflowError):
            self.coordinator.freeze_proposal(operator_id=self.operator, proposal_id=legacy_proposal["id"],
                expected_revision=1, expected_publication_revision=0, reviewed_proposal=legacy_proposal)
        with self.assertRaises(WorkflowError):
            self.coordinator.create_job(operator_id=self.operator, packet_id="packet-b", idempotency_key="packet-b")
        self.assertEqual(self.coordinator._all_project("job", b["id"]), [])

        c, d = self.project("C"), self.project("D")
        with self.coordinator.transaction():
            self.coordinator._put("asset", {"id": "legacy-ambiguous", "mimeType": "image/png"})
            self.coordinator._put("proposal", {"id": "proposal-c", "projectId": c["id"],
                "assets": [{"id": "legacy-ambiguous"}]})
            self.coordinator._put("packet", {"id": "packet-d", "projectId": d["id"],
                "assets": [{"id": "legacy-ambiguous"}]})
        self.assertIsNone(self.coordinator.asset_owner("legacy-ambiguous"))
        with self.assertRaises(WorkflowError):
            self.coordinator.validate_project_assets(d["id"], [{"id": "legacy-ambiguous"}])
        self.assertNotIn("projectId", self.coordinator._get("asset", "legacy-ambiguous"))

    def test_iteration_gate_requires_accepted_exact_verified_candidate_and_keeps_name(self):
        project = self.project("My project")
        candidate = {"id": "candidate-a", "candidateCommit": "commit-a", "verification": {"status": "PASS"}}
        packet = {"projectId": project["id"]}
        with self.coordinator.transaction():
            snapshot = self.coordinator._publish_generic(packet, {
                **candidate, "jobId": "job-a", "document": {"title": "AI title"}, "catalog": {},
            }, 0)
        self.assertFalse(self.coordinator.iteration_status(project["id"])["iterationReady"])
        with self.coordinator.transaction():
            event = self.coordinator._event(phase="run_acceptance", action="accept", project_id=project["id"],
                job_id="job-a", candidate_id=candidate["id"])
            self.coordinator._put("job", {"id": "job-a", "projectId": project["id"], "status": "PUBLISHED",
                "decisionEventId": event["eventId"], "candidate": candidate, "snapshot": snapshot})
        status = self.coordinator.iteration_status(project["id"])
        self.assertTrue(status["iterationReady"])
        self.assertTrue(status["iterationReadyTestOnly"])
        self.assertEqual(self.coordinator._get("project", project["id"])["title"], "My project")

    def test_store_identity_is_distinct_and_persists_across_reopen(self):
        store_a = self.root / "store-a"
        store_b = self.root / "store-b"
        first = Coordinator(self.root, state_root=store_a, test_data=True)
        first_id = first.workspace_summary()["storeId"]
        self.assertEqual(first.project_workspace(first.create_project(operator_id=first.operator_id, title="A")["id"])["storeId"], first_id)
        first.close()
        second = Coordinator(self.root, state_root=store_b, test_data=True)
        second_id = second.workspace_summary()["storeId"]
        self.assertNotEqual(first_id, second_id)
        second.close()
        reopened = Coordinator(self.root, state_root=store_a, test_data=True)
        self.assertEqual(reopened.workspace()["storeId"], first_id)
        reopened.close()


class ProjectScopedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.coordinator = Coordinator(REPO_ROOT, state_root=Path(self.temp.name) / "state", test_data=True)
        self.server = make_server(self.coordinator, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.get("/api/session")[1]["token"]
        image = (REPO_ROOT / "frontend/dist/assets/arch.png").read_bytes()
        self.encoded_image = base64.b64encode(image).decode("ascii")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.coordinator.close()
        self.temp.cleanup()

    def request(self, path, method="GET", body=None):
        headers = {"Origin": self.origin}
        data = None
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-Workbench-Token": self.token})
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = response.read()
                try:
                    payload = json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                return response.status, payload
        except urllib.error.HTTPError as error:
            payload = error.read()
            try:
                payload = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            return error.code, payload

    def get(self, path):
        return self.request(path)

    def post(self, path, body):
        return self.request(path, "POST", body)

    def create_project(self, title):
        status, body = self.post("/api/projects", {"title": title, "workflow": "objects-v1"})
        self.assertEqual(status, 201)
        return body["project"]["id"]

    def upload(self, project_id):
        status, body = self.post(f"/api/projects/{project_id}/assets", {
            "name": "arch.png", "mimeType": "image/png", "purpose": "reference",
            "dataBase64": self.encoded_image,
        })
        self.assertEqual(status, 201)
        return body["asset"]["id"]

    def test_blank_create_asset_ownership_and_scoped_reads(self):
        a, b = self.create_project("A"), self.create_project("B")
        self.assertEqual(self.coordinator.project_workspace(a)["proposals"], [])
        self.assertEqual(self.coordinator._threads, {})
        asset = self.upload(a)
        self.assertEqual(self.get(f"/api/projects/{a}/assets/{asset}")[0], 200)
        self.assertEqual(self.get(f"/api/projects/{b}/assets/{asset}")[0], 404)
        self.assertEqual(self.get(f"/api/assets/{asset}")[0], 404)
        status, _ = self.post(f"/api/projects/{b}/concepts", {
            "text": "use this reference", "assetIds": [asset], "expectedPublicationRevision": 0,
        })
        self.assertEqual(status, 404)
        self.assertEqual(self.coordinator.project_workspace(b)["proposals"], [])

    def test_scoped_history_hides_foreign_attachment_metadata(self):
        a, b = self.create_project("A"), self.create_project("B")
        asset = self.upload(a)
        proposal = {"id": "old-proposal-b", "projectId": b, "workflow": "objects-v1",
            "revision": 1, "status": "READY", "publicationRevision": 0, "assets": [{"id": asset}],
            "document": {"title": "B plan"}}
        packet = {"id": "old-packet-b", "projectId": b, "publicationRevision": 0,
            "assets": [{"id": asset}], "approvedProposal": proposal}
        with self.coordinator.transaction():
            self.coordinator._put("proposal", proposal)
            self.coordinator._put("packet", packet)
        self.assertEqual(self.get(f"/api/projects/{b}/workspace")[0], 404)
        self.assertEqual(self.get(f"/api/projects/{b}/proposals/{proposal['id']}")[0], 404)
        self.assertEqual(self.get(f"/api/projects/{b}/packets/{packet['id']}")[0], 404)
        self.assertEqual(self.post(f"/api/projects/{b}/jobs", {
            "packetId": packet["id"], "idempotencyKey": "cross-asset-packet",
        })[0], 404)

    def test_cross_project_and_global_resource_routes_are_denied_before_action(self):
        a, b = self.create_project("A"), self.create_project("B")
        with self.coordinator.transaction():
            self.coordinator._put("proposal", {"id": "proposal-a", "projectId": a, "workflow": "objects-v1", "revision": 1, "status": "READY"})
            self.coordinator._put("packet", {"id": "packet-a", "projectId": a, "proposalId": "proposal-a", "assets": []})
            self.coordinator._put("job", {"id": "job-a", "projectId": a, "packetId": "packet-a", "status": "READY_FOR_REVIEW", "candidate": {"candidateCommit": "commit-a"}})
        for url in (
            f"/api/projects/{b}/proposals/proposal-a",
            f"/api/projects/{b}/packets/packet-a",
            f"/api/projects/{b}/jobs/job-a",
            "/api/proposals/proposal-a",
            "/api/jobs/job-a",
            f"/api/projects/{b}/projects/{a}/workbench",
            f"/api/projects/{a}/projects/{b}/jobs/job-a",
        ):
            self.assertEqual(self.get(url)[0], 404, url)
        denied_posts = (
            (f"/api/projects/{b}/proposals/proposal-a/cancel", {}),
            (f"/api/projects/{b}/proposals/proposal-a/reconcile", {}),
            (f"/api/projects/{b}/proposals/proposal-a/answers", {"expectedRevision": 1, "answers": {}}),
            (f"/api/projects/{b}/proposals/proposal-a/freeze", {"expectedRevision": 1, "expectedPublicationRevision": 0, "reviewedProposal": {"id": "proposal-a", "revision": 1}}),
            (f"/api/projects/{b}/jobs/job-a/preview", {}),
            (f"/api/projects/{b}/jobs/job-a/cancel", {}),
            (f"/api/projects/{b}/jobs/job-a/reconcile", {}),
            (f"/api/projects/{b}/jobs/job-a/decision", {"decision": "reject", "candidateCommit": "commit-a", "expectedPublicationRevision": 0}),
            (f"/api/projects/{b}/jobs", {"packetId": "packet-a", "idempotencyKey": "cross-project"}),
            ("/api/jobs", {"packetId": "packet-a", "idempotencyKey": "legacy-global"}),
        )
        for url, body in denied_posts:
            self.assertEqual(self.post(url, body)[0], 404, url)
        self.assertEqual(self.coordinator._get("job", "job-a")["status"], "READY_FOR_REVIEW")

    def test_archived_project_history_is_readable_and_can_be_restored(self):
        project = self.create_project("Archive test")
        with self.coordinator.transaction():
            self.coordinator._put("proposal", {"id": "failed-archive-proposal", "projectId": project,
                "workflow": "objects-v1", "revision": 1, "status": "FAILED", "assets": []})
        self.assertEqual(self.post(f"/api/projects/{project}/settings", {"archived": True})[0], 200)
        status, workspace = self.get(f"/api/projects/{project}/workspace")
        self.assertEqual(status, 200)
        self.assertTrue(workspace["projects"][0]["archived"])
        self.assertEqual(self.post(f"/api/projects/{project}/assets", {
            "name": "arch.png", "mimeType": "image/png", "purpose": "reference", "dataBase64": self.encoded_image,
        })[0], 409)
        self.assertEqual(self.post(f"/api/projects/{project}/proposals/failed-archive-proposal/cancel", {})[0], 409)
        self.assertEqual(self.coordinator._get("proposal", "failed-archive-proposal")["status"], "FAILED")
        self.assertEqual(self.post(f"/api/projects/{project}/settings", {"archived": False})[0], 200)
        self.assertFalse(self.get(f"/api/projects/{project}/workspace")[1]["projects"][0]["archived"])

    def test_archived_ready_proposal_cannot_be_frozen_or_dispatched(self):
        project = self.create_project("Archived draft")
        proposal = {"id": "ready-proposal", "projectId": project, "workflow": "objects-v1",
            "revision": 1, "status": "READY", "publicationRevision": 0, "questions": [],
            "decisions": {}, "document": {}, "tasks": [], "assets": []}
        packet = {"id": "ready-packet", "projectId": project, "proposalId": proposal["id"],
            "publicationRevision": 0, "proposalRevision": 1, "assets": []}
        with self.coordinator.transaction():
            self.coordinator._put("proposal", proposal)
            self.coordinator._put("packet", packet)
        self.assertEqual(self.post(f"/api/projects/{project}/settings", {"archived": True})[0], 200)
        status, _ = self.post(f"/api/projects/{project}/proposals/{proposal['id']}/freeze", {
            "expectedRevision": 1, "expectedPublicationRevision": 0,
            "reviewedProposal": {"id": proposal["id"], "revision": 1},
        })
        self.assertEqual(status, 409)
        status, _ = self.post(f"/api/projects/{project}/jobs", {
            "packetId": packet["id"], "idempotencyKey": "archived-packet",
        })
        self.assertEqual(status, 409)
        self.assertEqual(self.coordinator._all_project("job", project), [])
        self.assertEqual(self.coordinator._all_project("packet", project), [packet])


if __name__ == "__main__":
    unittest.main()

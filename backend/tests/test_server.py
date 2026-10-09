import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend.server import REPO_ROOT, make_server


class WorkflowError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code

    def as_dict(self):
        return {"message": str(self), "code": self.code}


class FakeCoordinator:
    operator_id = "registered-operator-from-server"

    def __init__(self, root):
        self.root = Path(root)
        self.calls = []
        self.asset = None
        self.fail_conflict = False

    def capabilities(self):
        return {
            key: False
            for key in (
                "interactiveFrontendConfirmation",
                "sessionDispatch",
                "godotVerification",
                "semanticProjection",
            )
        }

    def workspace(self):
        return {
            "workspaceId": "ws-test",
            "projects": [],
            "jobs": [],
            "capabilities": self.capabilities(),
            "testData": True,
        }

    def project_workspace(self, project_id):
        return {"projects": [{"id": project_id}], "jobs": [], "proposals": [], "packets": [], "capabilities": self.capabilities()}

    def create_project(self, **kwargs):
        self.calls.append(("create_project", kwargs))
        return {"id": "project-1", "title": kwargs["title"], "workflow": kwargs["workflow"]}

    def update_project_settings(self, **kwargs):
        self.calls.append(("update_project_settings", kwargs))
        return {"id": kwargs["project_id"], "title": kwargs.get("title") or "Demo"}

    def require_project_resource(self, project_id, kind, entity_id):
        allowed = {"project-1", "proposal-1", "packet-1", "job-1"}
        if project_id != "project-1" or entity_id not in allowed:
            raise WorkflowError(404, "NOT_FOUND", "not found")
        return {"id": entity_id, "projectId": project_id}

    def require_project_asset(self, project_id, asset_id):
        if project_id != "project-1" or asset_id != "asset-test-1":
            raise WorkflowError(404, "NOT_FOUND", "not found")

    def asset_owner(self, asset_id):
        return "project-1" if asset_id == "asset-test-1" else None

    def create_concept(self, **kwargs):
        self.calls.append(("create_concept", kwargs))
        if self.fail_conflict:
            raise WorkflowError(409, "stale_revision", "Publication revision changed.")
        return {
            "proposal": {
                "id": "proposal-1",
                "revision": 1,
                "status": "NEEDS_CLARIFICATION",
            }
        }

    def upload_asset(self, *, operator_id, name, mime_type, data_base64, purpose, project_id=None):
        payload = base64.b64decode(data_base64)
        path = self.root / "stored-image.png"
        path.write_bytes(payload)
        self.asset = (path, mime_type)
        self.calls.append(
            (
                "upload_asset",
                {"operator_id": operator_id, "name": name, "purpose": purpose},
            )
        )
        return {
            "id": "asset-test-1",
            "projectId": project_id,
            "name": name,
            "mimeType": mime_type,
            "purpose": purpose,
            "size": len(payload),
        }

    def asset_file(self, asset_id):
        if asset_id != "asset-test-1" or not self.asset:
            raise WorkflowError(404, "asset_missing", "Image reference is unavailable.")
        return self.asset

    def answer_proposal(self, **kwargs):
        self.calls.append(("answer_proposal", kwargs))
        return {"proposal": {"id": kwargs["proposal_id"], "revision": 2}}

    def freeze_proposal(self, **kwargs):
        self.calls.append(("freeze_proposal", kwargs))
        return {"packet": {"id": "packet-1", "operationKind": "IMPLEMENTATION"}}

    def create_job(self, **kwargs):
        self.calls.append(("create_job", kwargs))
        return {"job": {"id": "job-1", "status": "QUEUED"}}

    def get_job(self, job_id):
        self.calls.append(("get_job", job_id))
        return {"job": {"id": job_id, "status": "READY_FOR_REVIEW"}}

    def preview_job(self, **kwargs):
        self.calls.append(("preview_job", kwargs))
        return {"status": "RUNNING", "sourceCommit": "deadbeef"}

    def reconcile_job(self, **kwargs):
        self.calls.append(("reconcile_job", kwargs))
        return {"job": {"id": kwargs["job_id"], "status": "RUNNING"}}

    def cancel_job(self, **kwargs):
        self.calls.append(("cancel_job", kwargs))
        return {"job": {"id": kwargs["job_id"], "status": "CANCEL_REQUESTED"}}

    def decide_job(self, **kwargs):
        self.calls.append(("decide_job", kwargs))
        return {"job": {"id": kwargs["job_id"], "status": "PUBLISHED"}}

    def workbench(self, project_id):
        return {
            "snapshot": {"projectId": project_id, "publicationRevision": 1},
            "capabilities": {},
            "candidates": [],
        }


class StudioServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        studio = self.root / "studio"
        legacy = self.root / "legacy"
        studio.mkdir()
        legacy.mkdir()
        (studio / "index.html").write_text("<h1>studio fixture</h1>", encoding="utf-8")
        (studio / "studio.js").write_text("export const ready=true;", encoding="utf-8")
        (legacy / "index.html").write_text("<h1>legacy fixture</h1>", encoding="utf-8")
        self.outside = self.root / "private.txt"
        self.outside.write_text("private", encoding="utf-8")
        (studio / "escape.txt").symlink_to(self.outside)
        self.coordinator = FakeCoordinator(self.root)
        self.server = make_server(
            self.coordinator, port=0, studio_root=studio, legacy_root=legacy
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.get_json("/api/session")[1]["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(
        self,
        path,
        *,
        method="GET",
        body=None,
        token=None,
        origin=None,
        host=None,
        content_type="application/json",
    ):
        headers = {} if origin == "omit" else {"Origin": origin or self.origin}
        if token is not None:
            headers["X-Workbench-Token"] = token
        if host is not None:
            headers["Host"] = host
        data = (
            None
            if body is None
            else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        )
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            self.origin + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.headers, error.read()
            finally:
                error.close()

    def get_json(self, path):
        status, _headers, data = self.request(path)
        self.assertEqual(status, 200)
        return status, json.loads(data)

    def post_json(self, path, body, **kwargs):
        status, headers, data = self.request(
            path,
            method="POST",
            body=body,
            token=kwargs.pop("token", self.token),
            **kwargs,
        )
        return status, headers, json.loads(data) if data else {}

    def test_static_roots_and_legacy_are_read_only(self):
        status, headers, body = self.request("/studio/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"studio fixture", body)
        status, headers, _ = self.request("/studio/studio.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertEqual(self.request("/legacy/")[0], 200)
        self.assertEqual(self.request("/studio/../private.txt")[0], 404)
        self.assertEqual(self.request("/studio/escape.txt")[0], 404)
        self.assertEqual(self.request("/api/submit", method="POST", body={})[0], 403)
        status, _, payload = self.post_json("/legacy/", {}, token=self.token)
        self.assertEqual(status, 404)
        self.assertIn("read-only", payload["error"])

    def test_project_stage_links_load_while_api_queries_remain_rejected(self):
        path = "/studio/?project=project-1&stage=iteration"
        status, headers, body = self.request(path)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"studio fixture", body)
        self.assertEqual(self.request(path, method="HEAD")[0], 200)
        self.assertEqual(self.request("/api/workspace?project=project-1")[0], 400)
        self.assertEqual(self.request("/api/projects/project-1/workbench?stage=iteration")[0], 400)

    def test_origin_host_and_token_gate_every_mutation(self):
        body = {"text": "collect stars", "assetIds": []}
        self.assertEqual(
            self.request(
                "/api/projects/project-1/concepts",
                method="POST",
                body=body,
                token=self.token,
                origin="http://evil.test",
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "/api/projects/project-1/concepts",
                method="POST",
                body=body,
                token=self.token,
                origin="omit",
            )[0],
            403,
        )
        self.assertEqual(
            self.request("/api/projects/project-1/concepts", method="POST", body=body, token="wrong")[0],
            403,
        )
        self.assertEqual(
            self.request(
                "/api/projects/project-1/concepts",
                method="POST",
                body=body,
                token=self.token,
                host="evil.test",
            )[0],
            403,
        )
        self.assertFalse(self.coordinator.calls)

    def test_concept_api_passes_server_operator_and_revision_only(self):
        status, _headers, payload = self.post_json(
            "/api/projects/project-1/concepts",
            {
                "text": "collect stars",
                "projectId": "project-1",
                "assetIds": [],
                "expectedPublicationRevision": 7,
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["proposal"]["status"], "NEEDS_CLARIFICATION")
        call = self.coordinator.calls[-1][1]
        self.assertEqual(call["operator_id"], self.coordinator.operator_id)
        self.assertEqual(call["expected_publication_revision"], 7)
        self.assertEqual(
            self.post_json("/api/projects/project-1/concepts", {"text": "x", "cwd": "/tmp"})[0], 400
        )
        self.assertEqual(
            self.post_json("/api/projects/project-1/concepts", {"text": "x", "operatorId": "forged"})[0],
            400,
        )

    def test_json_rejects_duplicate_keys_and_non_finite_constants(self):
        status, _, _ = self.request(
            "/api/projects/project-1/concepts",
            method="POST",
            body=b'{"text":"first","text":"second"}',
            token=self.token,
        )
        self.assertEqual(status, 400)
        status, _, _ = self.request(
            "/api/projects/project-1/concepts",
            method="POST",
            body=b'{"text":"safe","expectedPublicationRevision":NaN}',
            token=self.token,
        )
        self.assertEqual(status, 400)
        status, _, _ = self.request(
            "/api/projects/project-1/proposals/proposal-1/answers",
            method="POST",
            body=b'{"expectedRevision":1,"answers":{"goalCount":1e999}}',
            token=self.token,
        )
        self.assertEqual(status, 400)
        self.assertFalse(self.coordinator.calls)

    def test_proposal_job_and_decision_routes_bind_exact_fields(self):
        status, _, _ = self.post_json(
            "/api/projects/project-1/proposals/proposal-1/answers",
            {"expectedRevision": 1, "answers": {"goalCount": "5"}},
        )
        self.assertEqual(status, 200)
        status, _, _ = self.post_json(
            "/api/projects/project-1/proposals/proposal-1/freeze",
            {
                "expectedRevision": 2,
                "expectedPublicationRevision": 3,
                "reviewedProposal": {"id": "proposal-1", "revision": 2},
            },
        )
        self.assertEqual(status, 201)
        status, _, _ = self.post_json(
            "/api/projects/project-1/jobs", {"packetId": "packet-1", "idempotencyKey": "packet:packet-1"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(self.get_json("/api/projects/project-1/jobs/job-1")[0], 200)
        self.assertEqual(self.post_json("/api/projects/project-1/jobs/job-1/preview", {})[0], 202)
        self.assertEqual(self.post_json("/api/projects/project-1/jobs/job-1/reconcile", {})[0], 200)
        self.assertEqual(self.post_json("/api/projects/project-1/jobs/job-1/cancel", {})[0], 200)
        status, _, payload = self.post_json(
            "/api/projects/project-1/jobs/job-1/decision",
            {
                "decision": "accept",
                "candidateCommit": "cafe1234",
                "expectedPublicationRevision": 3,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["job"]["status"], "PUBLISHED")
        decisions = [
            kwargs for name, kwargs in self.coordinator.calls if name == "decide_job"
        ]
        self.assertEqual(decisions[0]["operator_id"], self.coordinator.operator_id)

    def test_stale_workflow_error_keeps_status_and_code(self):
        self.coordinator.fail_conflict = True
        status, _, payload = self.post_json("/api/projects/project-1/concepts", {"text": "collect stars"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "stale_revision")
        self.assertEqual(payload["message"], "Publication revision changed.")

    def test_image_upload_validates_size_signature_and_serves_only_by_id(self):
        image = (REPO_ROOT / "frontend" / "dist" / "assets" / "arch.png").read_bytes()
        encoded = base64.b64encode(image).decode("ascii")
        status, _, response = self.post_json(
            "/api/projects/project-1/assets",
            {
                "name": "arch.png",
                "mimeType": "image/png",
                "dataBase64": encoded,
                "purpose": "layout",
            },
        )
        self.assertEqual(status, 201)
        asset_id = response["asset"]["id"]
        status, headers, body = self.request(f"/api/projects/project-1/assets/{asset_id}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(body, image)
        self.assertEqual(
            self.post_json(
                "/api/projects/project-1/assets",
                {
                    "name": "fake.png",
                    "mimeType": "image/png",
                    "dataBase64": base64.b64encode(b"not image").decode(),
                    "purpose": "reference",
                },
            )[0],
            415,
        )
        self.assertEqual(
            self.post_json(
                "/api/projects/project-1/assets",
                {
                    "name": "x.png",
                    "mimeType": "image/png",
                    "dataBase64": encoded,
                    "purpose": "runtime_asset",
                },
            )[0],
            400,
        )

    def test_workspace_and_workbench_are_service_owned(self):
        status, workspace = self.get_json("/api/workspace")
        self.assertEqual(status, 200)
        self.assertTrue(workspace["testData"])
        self.assertFalse(workspace["capabilities"]["sessionDispatch"])
        status, workbench = self.get_json("/api/projects/project-1/workbench")
        self.assertEqual(status, 200)
        self.assertEqual(workbench["snapshot"]["projectId"], "project-1")


if __name__ == "__main__":
    unittest.main()

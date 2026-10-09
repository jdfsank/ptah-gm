"""Continue an existing isolated objects-v1 test project using real sessions.

This tool never opens a production store. Its synthetic review/publication is
marked testData and does not assert human gameplay acceptance.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.coordinator import Coordinator, canonical, now
from backend.server import make_server


def run(state_root: Path, project_id: str, object_id: str, message: str, output: Path):
    if state_root == (ROOT / ".workbench").resolve() or not (state_root / "state.sqlite3").is_file():
        raise ValueError("an existing isolated test store is required")
    coordinator = Coordinator(ROOT, state_root=state_root, test_data=True)
    server = make_server(coordinator, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    token = None
    record = {"testData": True, "productionAuthorized": False, "humanAcceptance": "NOT PERFORMED",
              "stateRoot": str(state_root), "projectId": project_id, "status": "FAIL", "startedAt": now()}

    def request(path, body=None):
        headers = {"Accept": "application/json", "Origin": origin}
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-Workbench-Token": token})
        req = urllib.request.Request(origin + "/api" + path,
            data=canonical(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)

    def wait(path, active, timeout):
        end, prior = time.monotonic() + timeout, None
        while time.monotonic() < end:
            value = request(path)
            if value["status"] != prior:
                print(value["status"], value.get("summary", value.get("message", ""))[:250], flush=True)
                prior = value["status"]
            if value["status"] not in active:
                return value
            time.sleep(1)
        raise TimeoutError(path)

    try:
        token = request("/session")["token"]
        snapshot = request("/projects/" + project_id + "/workbench")["snapshot"]
        assert snapshot["testData"] is True and snapshot["productionAuthorized"] is False
        request_body = {"workflow": "objects-v1", "projectId": project_id, "text": "",
            "expectedPublicationRevision": snapshot["publicationRevision"], "changeRequest": {
                "baseRevision": snapshot["publicationRevision"], "sourceCommit": snapshot["sourceCommit"],
                "targetObjectIds": [object_id], "fields": [], "feedback": [
                    {"objectId": object_id, "message": message, "category": "bug"}]}}
        record["request"] = request_body
        proposal = request("/concepts", request_body)
        proposal = wait("/proposals/" + proposal["id"], {"PLANNING", "PLANNING_CANCELLING"}, 450)
        record["proposal"] = proposal
        assert proposal["status"] == "READY", proposal.get("summary")
        packet = request("/proposals/" + proposal["id"] + "/freeze", {
            "expectedRevision": proposal["revision"], "expectedPublicationRevision": proposal["publicationRevision"],
            "reviewedProposal": proposal})
        record["packet"] = packet
        job = request("/jobs", {"packetId": packet["id"], "idempotencyKey": "probe:" + packet["id"]})
        record["jobId"] = job["id"]
        job = wait("/jobs/" + job["id"], {"QUEUED", "DISPATCHING", "RUNNING", "VERIFYING", "PROJECTING"}, 1000)
        record["job"] = job
        assert job["status"] == "READY_FOR_REVIEW", job.get("message")
        published = request("/jobs/" + job["id"] + "/decision", {
            "decision": "accept", "candidateCommit": job["candidate"]["candidateCommit"],
            "expectedPublicationRevision": snapshot["publicationRevision"]})
        record.update(snapshot=published["snapshot"], status="PASS", finishedAt=now())
    except BaseException as exc:
        record.update(error=str(exc), finishedAt=now())
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        server.shutdown()
        server.server_close()
        coordinator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.state_root.resolve(), args.project_id, args.object_id, args.message, args.output.resolve())

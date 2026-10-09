"""Real local API/Codex/Godot probe in an explicitly isolated test workspace.

Synthetic decisions made here never grant production authorization or human
acceptance. No standalone checksum commands are run.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.coordinator import Coordinator, canonical, git, now
from backend.server import make_server


def run(state_root, output):
    coordinator = Coordinator(ROOT, state_root=state_root, test_data=True)
    server = make_server(coordinator, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    token = None
    events = []

    def request(path, body=None):
        headers = {"Accept": "application/json", "Origin": origin}
        if body is not None:
            headers.update(
                {"Content-Type": "application/json", "X-Workbench-Token": token}
            )
        data = canonical(body).encode() if body is not None else None
        req = urllib.request.Request(origin + "/api" + path, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            value = json.load(response)
        events.append(
            {
                "at": now(),
                "method": "POST" if body is not None else "GET",
                "path": path,
                "id": value.get("id"),
                "status": value.get("status"),
            }
        )
        return value

    def clarify(p):
        answers = {q["id"]: q["options"][0]["value"] for q in p["questions"]}
        return request(
            f"/proposals/{p['id']}/answers",
            {"expectedRevision": p["revision"], "answers": answers},
        )

    def dispatch(p):
        packet = request(
            f"/proposals/{p['id']}/freeze",
            {
                "expectedRevision": p["revision"],
                "expectedPublicationRevision": p["publicationRevision"],
                "reviewedProposal": p,
            },
        )
        body = {"packetId": packet["id"], "idempotencyKey": "packet:" + packet["id"]}
        job = request("/jobs", body)
        retry = request("/jobs", body)
        assert job["id"] == retry["id"], "idempotency failed"
        print(f"{packet['operationKind']} {job['id']} dispatched", flush=True)
        deadline = time.monotonic() + 420
        previous = None
        while time.monotonic() < deadline:
            job = request("/jobs/" + job["id"])
            if job["status"] != previous:
                print(job["status"], job.get("message", ""), flush=True)
                previous = job["status"]
            if job["status"] in {
                "PUBLISHED",
                "READY_FOR_REVIEW",
                "FAILED",
                "BLOCKED",
                "CANCELLED",
                "UNCERTAIN",
            }:
                break
            time.sleep(1)
        assert job["status"] in {"PUBLISHED", "READY_FOR_REVIEW"}, job
        return packet, job

    def synthetic_accept(job):
        assert job["testData"] is True and job["productionAuthorized"] is False
        snapshot = request(f"/projects/{job['projectId']}/workbench")["snapshot"]
        return request(
            f"/jobs/{job['id']}/decision",
            {
                "decision": "accept",
                "candidateCommit": job["candidate"]["candidateCommit"],
                "expectedPublicationRevision": snapshot["publicationRevision"],
            },
        )

    record = {
        "schemaVersion": 1,
        "testData": True,
        "productionAuthorized": False,
        "humanAcceptance": "NOT PERFORMED",
        "startedAt": now(),
        "stateRoot": str(state_root),
        "events": events,
        "status": "FAIL",
    }
    try:
        token = request("/session")["token"]
        request("/workspace")
        reference = (
            ROOT
            / "sources/velvet-eclipse/assets/generated/compact-prop-pack/casino_small_props/normalized/chip.png"
        )
        asset = request(
            "/assets",
            {
                "name": "delivered-chip-reference.png",
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(reference.read_bytes()).decode(),
                "purpose": "reference",
            },
        )["asset"]
        proposal = clarify(
            request(
                "/concepts",
                {
                    "text": "用 2D 收集挑战验证最小闭环。收集目标调整为 3；时限调整为 30；移动速度调整为 220",
                    "assetIds": [asset["id"]],
                },
            )
        )
        init_packet, initialization = dispatch(proposal)
        assert (
            initialization["status"] == "PUBLISHED"
            and initialization["snapshot"]["playable"] is False
        )
        record["initialization"] = initialization
        first_packet, first = dispatch(initialization["nextProposal"])
        assert first["verification"]["status"] == "PASS"
        record["firstImplementation"] = first
        first_result = synthetic_accept(first)
        record["firstTestSnapshot"] = first_result["snapshot"]
        proposal = clarify(
            request(
                "/concepts",
                {
                    "projectId": first["projectId"],
                    "expectedPublicationRevision": 2,
                    "text": "收集目标调整为 5；时限调整为 40；移动速度调整为 300",
                },
            )
        )
        second_packet, second = dispatch(proposal)
        assert second["verification"]["status"] == "PASS"
        record["secondImplementation"] = second
        second_result = synthetic_accept(second)
        snapshot = second_result["snapshot"]
        assert snapshot["decisions"] == {
            "goalCount": 5,
            "durationSeconds": 40,
            "playerSpeed": 300,
        }
        assert (
            snapshot["sourceCommit"]
            == snapshot["catalog"]["sourceCommit"]
            == snapshot["verification"]["sourceCommit"]
        )
        repo = state_root / "projects" / first["projectId"]
        record["iterationGitDiff"] = git(
            repo,
            "diff",
            first["candidate"]["candidateCommit"],
            second["candidate"]["candidateCommit"],
            "--",
            "config/rules.json",
        )
        record["finalTestSnapshot"] = snapshot
        record["packets"] = [init_packet, first_packet, second_packet]
        record.update(status="PASS", finishedAt=now(), projectId=first["projectId"])
        print("REAL WORKFLOW PROBE PASS (test data; no human acceptance)", flush=True)
    except BaseException as exc:
        record.update(error=str(exc), finishedAt=now())
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        server.shutdown()
        server.server_close()
        coordinator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.state_root.resolve() == (ROOT / ".workbench").resolve():
        parser.error("the probe must use a separate state directory")
    run(args.state_root.resolve(), args.output.resolve())

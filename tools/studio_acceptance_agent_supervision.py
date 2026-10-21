"""Real AgentRunner supervision against a disposable, offline control plane."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runners.agent as agent_module
from runners.agent import AgentRunner
from runners.common import LocalJournal, TransportError


def probe(mode: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="studio-agent-supervision-") as folder:
        root = Path(folder)
        attempt = "real-supervision-" + mode
        packet = {"request": "Read planning-input.json with studio_read_file, then call "
                  "studio_list_files twice. Return JSON with sentinel supervision-20261012."}

        class OfflineAPI:
            offline_requests = 0

            def request(self, method, route, body=None):
                if method == "GET" and route.endswith("/input"):
                    return {"schemaVersion": "studio.message.v1", "attemptId": attempt,
                            "packet": packet, "assets": []}
                self.offline_requests += 1
                raise TransportError("synthetic control-plane outage")

        api = OfflineAPI()
        journal = LocalJournal(root / "journal.sqlite3")
        journal.bind_store("synthetic-store")
        runner = AgentRunner(api, journal, root / "workspaces", root / "artifacts",
                             root / "protected")
        request = {"attemptId": attempt, "projectId": "synthetic-project", "taskKind": "plan",
                   "profileSnapshot": {"modelKey": "gpt-6-luna", "modelProvider": "my_proxy",
                       "effort": "max", "catalogRevision": 1,
                       "limits": {"maxDurationSeconds": 60 if mode == "soft_budget" else 3,
                                  "softTotalTokens": 1 if mode == "soft_budget" else None}}}
        observed = []
        worker_processes = []
        real_output = agent_module.process_output_lines

        def capture(process):
            worker_processes.append(process)
            for line in real_output(process):
                if line:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict) and event.get("event") in {
                            "result", "nativeObservation", "started", "usage"}:
                        observed.append(event)
                yield line

        started = time.monotonic()
        with patch.object(agent_module, "process_output_lines", capture):
            accepted = runner.accept_claim(request, "synthetic-store")
        with journal._connect() as db:
            reports = [json.loads(row[0]) for row in db.execute(
                "SELECT body_json FROM reports ORDER BY created_at")]
        turns = {(event.get("observation") or {}).get("turnId") for event in observed
                 if (event.get("observation") or {}).get("phase") == "turnStartAcknowledged"}
        turns.discard(None)
        stopped = [r for r in reports if r["type"] == "stopped"]
        cleaned = not (root / "workspaces" / attempt / ".runner-tmp").exists()
        return {"mode": mode, "accepted": accepted, "modelTurns": len(turns),
                "workerExitCode": worker_processes[0].poll() if worker_processes else None,
                "durationSeconds": time.monotonic() - started,
                "offlineRequests": api.offline_requests, "reports": reports,
                "nativeObservations": observed, "privateRuntimeCleaned": cleaned,
                "passed": (not accepted and len(turns) == 1 and cleaned
                    and any(r["payload"].get("stopped") is True
                            and r["payload"].get("stopReason") == mode for r in stopped)
                    and not any(r["type"] == "completed" for r in reports))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--mode", choices=["soft_budget", "time_limit", "both"], default="both")
    args = parser.parse_args()
    modes = ["soft_budget", "time_limit"] if args.mode == "both" else [args.mode]
    cases = [probe(mode) for mode in modes]
    result = {"scope": "actual trusted worker/native/isolated host; synthetic offline API",
              "capabilitiesEnabled": [], "modelTurns": sum(c["modelTurns"] for c in cases),
              "cases": cases, "passed": all(c["passed"] for c in cases),
              "historicalCorrection": {"evidence": "studio-acceptance-native-offline-budget-20261012.json",
                  "actualModelTurns": 0,
                  "reason": "No native turn was acknowledged; private MCP transport config rejected thread/start."}}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "modelTurns": result["modelTurns"],
                      "cases": [{key: c[key] for key in ("mode", "passed", "durationSeconds")}
                                for c in cases], "evidence": str(args.output)}))


if __name__ == "__main__":
    main()

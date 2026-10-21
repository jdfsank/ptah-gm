"""Trusted adapter for one sealed artifact verification.

Candidate project code is executed only in separately sandboxed Godot
processes spawned by the verifier.
"""
from __future__ import annotations

import json
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("expected verification project directory")
    project = sys.argv[1]
    request = json.loads(sys.stdin.read())
    if not isinstance(request, dict) or set(request) != {"document", "baseCommit", "godotPath", "serviceRecords",
                                                     "preparedUidSidecars", "expectedUidEngineVersion"}:
        raise SystemExit("verification request shape is invalid")
    sidecars = request["preparedUidSidecars"]
    if not isinstance(sidecars, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                          for key, value in sidecars.items()):
        raise SystemExit("verification UID preparation is invalid")
    from backend.general_verification import verify_general_project
    result = verify_general_project(project, request["document"], base_commit=request["baseCommit"],
                                    godot_path=request["godotPath"], service_records=request["serviceRecords"],
                                    prepared_uid_sidecars={key: value.encode("ascii") for key, value in sidecars.items()},
                                    expected_uid_engine_version=request["expectedUidEngineVersion"])
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()

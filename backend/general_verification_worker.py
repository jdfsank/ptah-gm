"""Fixed subprocess entry point for the general independent verifier."""

from __future__ import annotations

import json
import sys

from .general_verification import verify_general_project


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-standard JSON constant: {value}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Expected a server-owned project path")
    request = json.loads(
        sys.stdin.read(), object_pairs_hook=_strict_object, parse_constant=_reject_constant
    )
    if not isinstance(request, dict) or set(request) - {
        "document", "baseCommit", "operation", "serviceRecords"
    }:
        raise SystemExit("Verifier request has an invalid shape")
    if not {"document", "baseCommit"} <= set(request):
        raise SystemExit("Verifier request is missing required fields")
    result = verify_general_project(
        sys.argv[1],
        request["document"],
        base_commit=request["baseCommit"],
        operation=request.get("operation", "IMPLEMENTATION"),
        service_records=request.get("serviceRecords"),
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

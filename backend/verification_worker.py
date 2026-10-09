"""Fixed subprocess entry point; its Godot children share the owned process group."""

import json
import sys

from .verification import verify_project


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Expected server-owned project and operation arguments")
    request = json.loads(sys.stdin.read())
    result = verify_project(
        sys.argv[1],
        sys.argv[2],
        request["expectedRules"],
        base_commit=request["baseCommit"],
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()

"""Compatibility command for the fresh ProjectRunner registration probe."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runners.project_role_probe import EVIDENCE, run_acceptance


def run(evidence_path: Path = EVIDENCE) -> dict[str, object]:
    return run_acceptance(evidence_path)


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

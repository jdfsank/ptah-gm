#!/usr/bin/env python3
"""Standard trusted Godot setup: optionally install, then verify editor MCP readiness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runners.editor_mcp import EditorMCPError, ensure_editor_mcp_ready
from tools.godot_mcp_install import InstallError, install_godot_mcp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path,
                        help="new directory outside the project, used for this invocation only")
    parser.add_argument("--install", action="store_true", help="install/enable before the read-only gate")
    parser.add_argument("--godot", type=Path)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    try:
        if args.install:
            install_godot_mcp(args.project)
        result = ensure_editor_mcp_ready(args.project, args.evidence_dir,
                                        godot_path=args.godot, timeout=args.timeout)
    except (EditorMCPError, InstallError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "message": str(exc),
                          "report": getattr(exc, "report", {})}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

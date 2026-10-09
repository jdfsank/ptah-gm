#!/usr/bin/env python3
"""SessionStart hook: initialize metrics for new session.

Clears current session metrics log, resets runtime state, and removes any
stale .godotmaker/current_role left from a previous session. Each gm-* skill
will write its own role on first action.

Displays deployed GodotMaker version + the project's current tag (if any).
Never blocks.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import start_session, state, get_current_tag


def clear_stale_role() -> None:
    """Remove .godotmaker/current_role so the next skill writes a fresh value."""
    try:
        os.remove(os.path.join(".godotmaker", "current_role"))
    except OSError:
        pass


def read_deployed_version() -> str | None:
    """Read the deployed GodotMaker version from .godotmaker/version."""
    try:
        with open(os.path.join(".godotmaker", "version"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def build_banner() -> str | None:
    """Compose the SessionStart additionalContext banner.

    Format: `[GodotMaker vX.Y.Z | tag: vA.B.C]` — tag suffix is omitted
    when no PLAN.md tag header is present (fresh project / between tags
    after gm-finalize cleared root files).
    Returns None if no version file (treat as not-yet-deployed).
    """
    version = read_deployed_version()
    if not version:
        return None
    tag = get_current_tag()
    if tag:
        return f"[GodotMaker v{version} | tag: {tag}]"
    return f"[GodotMaker v{version} | no current tag — run /gm-gdd to start one]"


def main():
    start_session()
    state.reset()
    clear_stale_role()

    banner = build_banner()
    if banner:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": banner,
            }
        }
        print(json.dumps(result))

    sys.exit(0)

if __name__ == "__main__":
    main()

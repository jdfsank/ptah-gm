#!/usr/bin/env python3
"""Stop hook: warn the agent once per dirty episode at end of a SKILL.

Block-once per dirty episode — agent gets reminded, can commit/clean/ignore.
Clean state resets the flag so the next dirty episode gets its own reminder.
Subagents skipped.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import get_current_role, state


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)
    if data.get("agent_id"):
        sys.exit(0)
    role = get_current_role()
    if not role:
        sys.exit(0)

    # Role change between Stop events resets the reminder flag, so the new
    # role gets its own first-dirty-stop reminder instead of inheriting the
    # previous role's "already reminded" state.
    if state.get("dirty_reminder_last_role", None) != role:
        state.put("dirty_reminded", False)
        state.put("dirty_reminder_last_role", role)

    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        sys.exit(0)
    output = r.stdout.strip()
    if not output:
        state.put("dirty_reminded", False)
        sys.exit(0)
    if state.get("dirty_reminded", False):
        sys.exit(0)

    state.put("dirty_reminded", True)
    snippet = output[:800] + ("\n... (truncated)" if len(output) > 800 else "")
    reminder = (
        f"Working tree dirty at end of '{role}':\n{snippet}\n\n"
        f'Run `git add -A && git commit -m "..."`, remove unintended files, '
        f"or exit again to skip."
    )
    print(json.dumps({"decision": "block", "reason": reminder}))
    sys.exit(0)


if __name__ == "__main__":
    main()

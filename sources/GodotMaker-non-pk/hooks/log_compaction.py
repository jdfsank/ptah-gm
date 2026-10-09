#!/usr/bin/env python3
"""PreCompact hook: record context compaction events.

Fires when Claude Code compacts the conversation history, either via
the `/compact` slash command (`trigger="manual"`) or via auto-compaction
at the context limit (`trigger="auto"`). PreCompact is the only
compaction hook event in Claude Code's hook surface — there is no
PostCompact.

Records one `EventType.COMPACTION` entry per fire with `session_id`,
`trigger`, and the project's current pipeline role (read from
`.godotmaker/current_role`) so AAR analysis can correlate compactions
with stage activity without scraping Claude Code's native session jsonl.

Never blocks (always exits 0).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import record_event, EventType


def _read_current_role() -> str:
    """Return `.godotmaker/current_role` content, or empty if missing."""
    path = os.path.join(".godotmaker", "current_role")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)
    if data.get("hook_event_name") != "PreCompact":
        sys.exit(0)

    record_event(
        EventType.COMPACTION,
        session_id=data.get("session_id") or "",
        trigger=data.get("trigger") or "unknown",
        role=_read_current_role(),
    )
    sys.exit(0)


if __name__ == "__main__":
    main()

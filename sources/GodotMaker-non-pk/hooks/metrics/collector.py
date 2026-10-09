"""Metrics collector — dual JSONL event logs.

Two log files:
- metrics.jsonl         — history, append-only across sessions (trend analysis)
- metrics_current.jsonl — current session only, cleared on session start (debug)

Usage:
    from metrics.collector import record_event, start_session
    from metrics.schema import EventType

    start_session()  # Clear current log
    record_event(EventType.SUBAGENT_START, agent_id="w1", agent_type="worker")
"""
import json
import os
from datetime import datetime, timezone
from typing import Any

from .schema import EventType


LOG_DIR = ".godotmaker"
LOG_FILE = os.path.join(LOG_DIR, "metrics.jsonl")
LOG_CURRENT = os.path.join(LOG_DIR, "metrics_current.jsonl")


def start_session() -> None:
    """Clear the current session log. Call at session start."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_CURRENT, "w", encoding="utf-8") as f:
            f.write("")  # Truncate
    except Exception:
        pass


def record_event(event_type: EventType, **details: Any) -> None:
    """Append a metric event to both history and current session logs.

    Args:
        event_type: Event type from schema.EventType
        **details: Arbitrary key-value pairs for this event
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type.value,
        **details,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        with open(LOG_CURRENT, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # Metrics must never break the pipeline


def read_events(log_path: str | None = None) -> list[dict]:
    """Read all events from a JSONL log.

    Args:
        log_path: Override log file path. Defaults to .godotmaker/metrics.jsonl (history)
    """
    path = log_path or LOG_FILE
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except FileNotFoundError:
        pass
    return events


def read_current_events() -> list[dict]:
    """Read events from the current session log only."""
    return read_events(LOG_CURRENT)

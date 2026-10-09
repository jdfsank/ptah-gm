"""Runtime state management for the current session.

Unlike metrics (append-only history), state tracks mutable values
that affect hook behavior in the current session.

State file: .godotmaker/state.json
"""
import json
import os
from typing import Any

STATE_DIR = ".godotmaker"
STATE_FILE = os.path.join(STATE_DIR, "state.json")

DEFAULT_STATE = {
    "stop_block_count": 0,
}


def _read_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def _write_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get(key: str, default: Any = None) -> Any:
    """Get a state value."""
    state = _read_state()
    return state.get(key, default)


def put(key: str, value: Any) -> None:
    """Set a state value."""
    state = _read_state()
    state[key] = value
    _write_state(state)


def increment(key: str) -> int:
    """Increment an integer state value, return new value."""
    state = _read_state()
    state[key] = state.get(key, 0) + 1
    _write_state(state)
    return state[key]


def reset() -> None:
    """Reset state to defaults (call at session start)."""
    _write_state(dict(DEFAULT_STATE))

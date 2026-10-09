#!/usr/bin/env python3
"""Stop hook: verify dispatcher diligence in worker-dispatching roles.

Only enforced when current_role is "build" or "fixgap" — these are the roles
that dispatch workers and require verifier + reviewer rounds. Other roles
(scaffold, gdd, asset, verify, evaluate, accept, finalize) self-enforce via
their SKILL.md Resume Check and skip this hook.

Diligence rule: if workers were dispatched in this session, both verifier
and reviewer must have run too (per gm-build/gm-fixgap Hard Rule 6).

Anti-deadloop: if blocked BLOCK_LIMIT times in the same session, allow with
a warning rather than blocking again.

Only blocks the main agent (the gm-* skill), not subagents.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import (
    record_event, read_current_events, EventType, state, event_has_role,
    get_current_role, WORKER_DISPATCH_ROLES,
)

BLOCK_LIMIT = 5

LIFECYCLE_EVENTS = (EventType.SUBAGENT_START, EventType.SUBAGENT_STOP)


def check_diligence(events: list[dict], require_reviewer: bool = True) -> list[str]:
    """Check that workers had verifiers (and reviewers) dispatched."""
    if not events:
        return []

    worker_count = 0
    verifier_seen = False
    reviewer_seen = False
    for e in events:
        ev = e.get("event")
        if ev == EventType.SUBAGENT_START and event_has_role(e, "worker"):
            worker_count += 1
        if ev in LIFECYCLE_EVENTS:
            if not verifier_seen and event_has_role(e, "verifier"):
                verifier_seen = True
            if not reviewer_seen and event_has_role(e, "reviewer"):
                reviewer_seen = True

    if worker_count == 0:
        return []

    issues = []
    n = worker_count
    if not verifier_seen:
        issues.append(
            f"Dispatched {n} workers but 0 verifiers. "
            "Dispatch a verifier (subagent_type: 'verifier') to confirm "
            "code/tests are real and the build passes."
        )
    if require_reviewer and not reviewer_seen:
        issues.append(
            f"Dispatched {n} workers but 0 reviewers. "
            "Dispatch a reviewer (subagent_type: 'reviewer') to check "
            "code quality and ECS patterns."
        )
    return issues


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if data.get("agent_id", ""):
        sys.exit(0)

    role = get_current_role()
    if role not in WORKER_DISPATCH_ROLES:
        record_event(EventType.GATE_CHECK, gate="completion",
                     result="skip", role=role)
        sys.exit(0)

    block_count = state.get("stop_block_count", 0)
    if block_count >= BLOCK_LIMIT:
        record_event(EventType.GATE_CHECK, gate="completion",
                     result="force_allow", role=role,
                     reason=f"Blocked {block_count} times, allowing to prevent deadloop")
        warning = (
            f"Force-allowing completion after {block_count} failed attempts. "
            "You MUST tell the user that diligence checks did not fully pass. "
            "List the unresolved issues so the user can decide whether to "
            "re-run /gm-build or accept as-is."
        )
        print(json.dumps({"decision": "allow", "reason": warning}), file=sys.stderr)
        sys.exit(0)

    events = read_current_events()
    issues = check_diligence(events, require_reviewer=True)

    if issues:
        state.increment("stop_block_count")
        record_event(EventType.GATE_CHECK, gate="completion",
                     result="fail", role=role, issues=issues[:5])
        reason = (
            f"Cannot finish '{role}' role — diligence issues:\n"
            + "\n".join(f"  - {line}" for line in issues)
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    record_event(EventType.GATE_CHECK, gate="completion", result="pass", role=role)


if __name__ == "__main__":
    main()

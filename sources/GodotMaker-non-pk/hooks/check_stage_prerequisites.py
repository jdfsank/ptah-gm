#!/usr/bin/env python3
"""PreToolUse hook (Agent tool): verify role prerequisites before worker dispatch.

Only enforces for roles that drive worker orchestration:
  - build → requires gdd completed + scaffold artifacts present
  - fixgap → evaluated findings OR valid reproduced user feedback in GAP.md

Scaffold artifacts are checked on disk because gm-finalize truncates
stage.jsonl at every tag boundary, so the scaffold event is no longer
in stage.jsonl after the first finalize.

Other dispatching roles (asset → analyst) self-validate via their SKILL.md
Resume Check; their preconditions don't match this hook's stage-schema model.
"""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import (
    record_event, EventType,
    get_current_role, get_completed_roles,
    load_stage_schemas, WORKER_DISPATCH_ROLES,
)


PREREQ_ROLE = {
    "build": "gdd",
    "fixgap": "evaluate",
}

# Sanity check: PREREQ_ROLE must cover exactly the worker-dispatching roles.
# Use an explicit raise instead of assert so the check survives `python -O`.
if frozenset(PREREQ_ROLE) != WORKER_DISPATCH_ROLES:
    raise RuntimeError(
        f"PREREQ_ROLE keys {sorted(PREREQ_ROLE)} must equal "
        f"WORKER_DISPATCH_ROLES {sorted(WORKER_DISPATCH_ROLES)}"
    )

# Roles that need scaffold artifacts on disk (lifetime-once, not in stage.jsonl
# after the first tag's finalize truncates the log).
SCAFFOLD_REQUIRED = frozenset({"build"})


def _feedback_repair_ready() -> bool:
    """Early user feedback is a narrow alternative, never a blanket bypass."""
    root = Path.cwd()
    try:
        plan = (root / "PLAN.md").read_text(encoding="utf-8")
        gap = (root / "GAP.md").read_text(encoding="utf-8")
    except OSError:
        return False
    tag_match = re.search(r"(?m)^\*\*Tag:\*\*\s*(\S+)", plan)
    if not tag_match or not (root / "project.godot").is_file():
        return False
    tag = tag_match.group(1)
    for path in sorted((root / ".godotmaker" / "feedback").glob("*.json")):
        try:
            if path.is_symlink():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                continue
            feedback_id = record.get("id")
            provenance = record.get("provenance")
            if isinstance(provenance, dict):
                user_source = (provenance == {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"}
                               or (provenance.get("kind") == "host_supplied"
                                   and isinstance(provenance.get("source_ref"), str)
                                   and bool(provenance["source_ref"].strip())))
            else:
                user_source = provenance == "host_supplied" and bool(record.get("source_ref"))
            if (record.get("schema_version") != 1 or record.get("source") != "user"
                    or not user_source or record.get("tag") != tag
                    or not isinstance(feedback_id, str) or feedback_id != path.stem
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", feedback_id)
                    or record.get("gap_task_id") != "F-" + feedback_id
                    or record.get("type") not in {"implementation", "experience"}
                    or not isinstance(record.get("mechanics"), list) or not record["mechanics"]
                    or any(not isinstance(m, str) or not m for m in record["mechanics"])
                    or any(not isinstance(record.get(k), str) or not record[k].strip()
                           for k in ("run_id", "platform", "text", "type", "created_at"))):
                continue
            task_id = "F-" + feedback_id
            # Inspect only this task's block, not an unrelated reproduction.
            blocks = re.split(r"(?m)(?=^#{2,4} )", gap)
            for block in blocks:
                heading = block.splitlines()[0] if block.splitlines() else ""
                task_line = re.search(r"(?m)^- Task: " + re.escape(task_id) + r"\s*$", block)
                if not task_line and not re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(task_id) + r"(?![A-Za-z0-9_.-])", heading):
                    continue
                if ("user_feedback:" + feedback_id not in block
                        and f".godotmaker/feedback/{feedback_id}.json" not in block):
                    continue
                fields = [re.search(r"(?im)^\s*(?:- )?(?:\*\*)?" + label
                                    + r":(?:\*\*)?\s*(.+)$", block)
                          for label in ("Reproduction", "Observed gap", "Expected behavior")]
                if all(match and not re.search(r"(?i)\b(pending|unknown|not yet|todo|blocked)\b", match.group(1))
                       for match in fields):
                    return True
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if data.get("tool_name") != "Agent":
        sys.exit(0)

    # Only check main agent (the gm-* skill orchestrating dispatch)
    if data.get("agent_id", ""):
        sys.exit(0)

    role = get_current_role()
    prereq = PREREQ_ROLE.get(role)
    if not prereq:
        sys.exit(0)  # No worker-dispatch role active, nothing to enforce

    completed = get_completed_roles()
    issues = []

    if role in SCAFFOLD_REQUIRED and not os.path.isfile("project.godot"):
        issues.append("project.godot not found — run /gm-scaffold first")

    feedback_ready = role == "fixgap" and _feedback_repair_ready()

    if prereq not in completed and not feedback_ready:
        issues.append(f"Role '{prereq}' has not completed yet — run /gm-{prereq} first")

    schemas = load_stage_schemas()
    if schemas and not feedback_ready:
        prereq_schema = schemas.get(prereq, {})
        # Inline existence check here (not validate_schema_files) to keep the
        # role-aware "{prereq} output missing: X" message style.
        for filepath in prereq_schema.get("files", []):
            if not os.path.exists(filepath):
                issues.append(f"{prereq} output missing: {filepath}")

    if issues:
        reason = (
            f"Cannot dispatch worker — '{role}' role prerequisites missing:\n"
            + "\n".join(f"  - {m}" for m in issues)
        )
        record_event(EventType.HOOK_BLOCK, hook="check_stage_prerequisites",
                     role=role, missing=issues)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
        sys.exit(0)

    record_event(EventType.HOOK_ALLOW, hook="check_stage_prerequisites", role=role)


if __name__ == "__main__":
    main()

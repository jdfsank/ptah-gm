"""Highlight rules for metrics reports.

Each rule is (name, severity, check_fn) where check_fn(events) -> str|None.
Returns a message string if the anomaly is detected, None otherwise.

Severity levels: "critical" (red), "warning" (orange), "info" (blue).
"""
from collections import Counter
from .schema import event_has_role


def _hl_no_verifiers(events):
    starts = [e for e in events if e.get("event") == "subagent_start"]
    workers = [e for e in starts if event_has_role(e, "worker")]
    verifiers = [e for e in starts if event_has_role(e, "verifier")]
    if len(workers) > 0 and len(verifiers) == 0:
        return f"{len(workers)} workers dispatched, 0 verifiers. Entire build is unverified."


def _hl_no_reviewers(events):
    starts = [e for e in events if e.get("event") == "subagent_start"]
    workers = [e for e in starts if event_has_role(e, "worker")]
    reviewers = [e for e in starts if event_has_role(e, "reviewer")]
    if len(workers) > 0 and len(reviewers) == 0:
        return f"{len(workers)} workers dispatched, 0 reviewers. No code quality review."


def _hl_force_allow(events):
    force = [e for e in events if e.get("event") == "gate_check" and e.get("result") == "force_allow"]
    if force:
        return f"Gate was force-allowed {len(force)} time(s). Completion checks were bypassed."


def _hl_all_status_unknown(events):
    stops = [e for e in events if e.get("event") == "subagent_stop"]
    if stops and all(e.get("status") == "UNKNOWN" for e in stops):
        return f"All {len(stops)} subagents returned UNKNOWN status. Report format detection may be broken."


def _hl_tests_written_not_run(events):
    file_ops = [e for e in events if e.get("event") in ("file_write", "file_edit")]
    test_files = [e for e in file_ops
                  if "test" in str(e.get("file", "")).lower()
                  or "e2e" in str(e.get("file", "")).lower()]
    e2e_runs = [e for e in events if e.get("event") == "e2e_run"]
    unit_runs = [e for e in events if e.get("event") == "unit_test_run"]
    if len(test_files) > 5 and len(e2e_runs) == 0 and len(unit_runs) == 0:
        return f"{len(test_files)} test files written but 0 test runs recorded. Tests were likely never executed."


def _hl_oversized_workers(events):
    agent_files = Counter(e.get("agent_id") for e in events
                          if e.get("event") in ("file_write", "file_edit") and e.get("is_subagent"))
    oversized = [(aid, cnt) for aid, cnt in agent_files.items() if cnt > 20]
    if oversized:
        worst = max(oversized, key=lambda x: x[1])
        return f"{len(oversized)} worker(s) wrote >20 files. Worst: {worst[0][:12]}... ({worst[1]} files). Violates one-system-per-worker rule."


def _hl_high_block_rate(events):
    blocks = sum(1 for e in events if e.get("event") == "hook_block")
    allows = sum(1 for e in events if e.get("event") == "hook_allow")
    total = blocks + allows
    if total > 10 and blocks / total > 0.3:
        return f"{blocks}/{total} hook decisions were blocks ({blocks/total:.0%}). Agents are repeatedly violating rules."


def _hl_completion_fail_loop(events):
    comp_fails = sum(1 for e in events if e.get("event") == "gate_check"
                     and e.get("gate") == "completion" and e.get("result") == "fail")
    if comp_fails >= 3:
        return f"Completion gate failed {comp_fails} times. The active role may be stuck in a retry loop."


HIGHLIGHT_RULES = [
    ("No Verifiers",          "critical", _hl_no_verifiers),
    ("No Reviewers",          "critical", _hl_no_reviewers),
    ("Gate Force-Allowed",    "critical", _hl_force_allow),
    ("All Status UNKNOWN",    "warning",  _hl_all_status_unknown),
    ("Tests Never Executed",  "critical", _hl_tests_written_not_run),
    ("Oversized Workers",     "warning",  _hl_oversized_workers),
    ("High Block Rate",       "warning",  _hl_high_block_rate),
    ("Completion Fail Loop",  "warning",  _hl_completion_fail_loop),
]

SEVERITY_COLORS = {"critical": "#d63031", "warning": "#e17055", "info": "#0984e3"}
SEVERITY_ICONS = {"critical": "&#10060;", "warning": "&#9888;", "info": "&#9432;"}

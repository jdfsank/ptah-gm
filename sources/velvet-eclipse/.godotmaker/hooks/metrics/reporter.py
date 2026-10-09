"""Metrics reporter — generates HTML summary from JSONL event log.

Usage:
    python -m hooks.metrics.reporter .godotmaker/metrics.jsonl -o report.html
    python -m hooks.metrics.reporter .godotmaker/metrics.jsonl  # stdout
"""
import argparse
from collections import Counter
from datetime import datetime

from .collector import read_events
from .schema import EventType, event_has_role
from .highlights import HIGHLIGHT_RULES, SEVERITY_COLORS, SEVERITY_ICONS

_WORKER_LABELS = {
    EventType.WORKER_DONE.value: "DONE",
    EventType.WORKER_PARTIAL.value: "PARTIAL",
    EventType.WORKER_FAILED.value: "FAILED",
}


def _ts(iso: str) -> datetime:
    """Parse ISO timestamp."""
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return datetime.min


def generate_report(events: list[dict]) -> str:
    """Generate HTML report from event list."""
    if not events:
        return _wrap_html("<p>No events recorded.</p>")

    sections = []

    # --- Overview ---
    first_ts = _ts(events[0].get("ts", ""))
    last_ts = _ts(events[-1].get("ts", ""))
    duration = (last_ts - first_ts).total_seconds() if first_ts != datetime.min else 0
    sections.append(f"""
    <div class="section">
        <h2>Overview</h2>
        <table>
            <tr><td>Total events</td><td><strong>{len(events)}</strong></td></tr>
            <tr><td>First event</td><td>{first_ts.strftime('%Y-%m-%d %H:%M:%S') if first_ts != datetime.min else 'N/A'}</td></tr>
            <tr><td>Last event</td><td>{last_ts.strftime('%Y-%m-%d %H:%M:%S') if last_ts != datetime.min else 'N/A'}</td></tr>
            <tr><td>Duration</td><td>{duration:.0f}s ({duration/60:.1f}min)</td></tr>
        </table>
    </div>""")

    # --- Highlights ---
    highlight_items = []
    for name, severity, check_fn in HIGHLIGHT_RULES:
        msg = check_fn(events)
        if msg:
            color = SEVERITY_COLORS.get(severity, "#636e72")
            icon = SEVERITY_ICONS.get(severity, "")
            highlight_items.append(
                f'<div style="background:{color};color:white;padding:10px 14px;'
                f'border-radius:6px;margin:6px 0;font-size:0.95em;">'
                f'{icon} <strong>{_escape(name)}</strong>: {_escape(msg)}</div>'
            )
    if highlight_items:
        sections.append(f"""
    <div class="section">
        <h2>Highlights</h2>
        {"".join(highlight_items)}
    </div>""")

    # --- Subagent Summary ---
    starts = [e for e in events if e.get("event") == EventType.SUBAGENT_START.value]
    stops = [e for e in events if e.get("event") == EventType.SUBAGENT_STOP.value]
    agent_types = Counter(e.get("agent_type", "unknown") for e in starts)

    stop_statuses = Counter(e.get("status", "unknown") for e in stops)

    rows = "".join(
        f"<tr><td>{t}</td><td>{c}</td></tr>" for t, c in agent_types.most_common()
    )
    status_rows = "".join(
        f"<tr><td>{s}</td><td>{c}</td></tr>" for s, c in stop_statuses.most_common()
    )

    # Color-coded warnings for subagent section
    subagent_warnings = ""
    all_unknown = all(s == "unknown" for s in stop_statuses) and stop_statuses
    worker_starts = [e for e in starts if event_has_role(e, "worker") or e.get("agent_type") == "worker"]
    verifier_starts = [e for e in starts if event_has_role(e, "verifier") or e.get("agent_type") == "verifier"]
    if all_unknown:
        subagent_warnings += '<p style="color:white;background:#ff7675;padding:8px;border-radius:4px;">&#9888; All subagent statuses are UNKNOWN — stop events may be missing role/status data.</p>'
    if len(worker_starts) > 0 and len(verifier_starts) == 0:
        subagent_warnings += '<p style="color:white;background:#ff7675;padding:8px;border-radius:4px;">&#9888; Workers were dispatched but 0 verifiers — verification coverage gap!</p>'

    sections.append(f"""
    <div class="section">
        <h2>Subagents</h2>
        {subagent_warnings}
        <div class="grid">
            <div>
                <h3>Dispatched ({len(starts)} total)</h3>
                <table><tr><th>Type</th><th>Count</th></tr>{rows}</table>
            </div>
            <div>
                <h3>Outcomes ({len(stops)} returned)</h3>
                <table><tr><th>Status</th><th>Count</th></tr>{status_rows}</table>
            </div>
        </div>
    </div>""")

    # --- Hook Blocks ---
    blocks = [e for e in events if e.get("event") == EventType.HOOK_BLOCK.value]
    block_by_hook = Counter(e.get("hook", "unknown") for e in blocks)
    block_rows = "".join(
        f"<tr><td>{h}</td><td>{c}</td></tr>" for h, c in block_by_hook.most_common()
    )
    block_detail_rows = "".join(
        f"<tr><td>{e.get('ts', '')[:19]}</td><td>{e.get('hook', '')}</td>"
        f"<td>{_escape(e.get('reason', '')[:120])}</td></tr>"
        for e in blocks[-20:]  # Last 20 blocks
    )

    sections.append(f"""
    <div class="section">
        <h2>Hook Blocks ({len(blocks)} total)</h2>
        <table><tr><th>Hook</th><th>Count</th></tr>{block_rows}</table>
        {'<h3>Recent Blocks</h3><table><tr><th>Time</th><th>Hook</th><th>Reason</th></tr>' + block_detail_rows + '</table>' if blocks else ''}
    </div>""")

    # --- Gate Checks ---
    gates = [e for e in events if e.get("event") == EventType.GATE_CHECK.value]
    gate_results = Counter(
        f"{e.get('gate', '?')}: {e.get('result', '?')}" for e in gates
    )
    gate_rows = "".join(
        f"<tr><td>{g}</td><td>{c}</td></tr>" for g, c in gate_results.most_common()
    )

    sections.append(f"""
    <div class="section">
        <h2>Gate Checks ({len(gates)} total)</h2>
        <table><tr><th>Gate : Result</th><th>Count</th></tr>{gate_rows}</table>
    </div>""")

    # --- Errors & Retries ---
    errors = [e for e in events if e.get("event") in (
        EventType.ERROR.value, EventType.RETRY.value
    )]
    error_types = Counter(e.get("error_type", "unknown") for e in errors)
    error_rows = "".join(
        f"<tr><td>{t}</td><td>{c}</td></tr>" for t, c in error_types.most_common()
    )

    sections.append(f"""
    <div class="section">
        <h2>Errors & Retries ({len(errors)} total)</h2>
        <table><tr><th>Type</th><th>Count</th></tr>{error_rows}</table>
    </div>""")

    # --- Worker Outcomes ---
    worker_events = [e for e in events if e.get("event") in (
        EventType.WORKER_DONE.value, EventType.WORKER_PARTIAL.value,
        EventType.WORKER_FAILED.value
    )]
    worker_outcomes = Counter(e.get("event", "") for e in worker_events)
    worker_rows = "".join(
        f"<tr><td>{_WORKER_LABELS.get(o, o.upper())}</td><td>{c}</td></tr>"
        for o, c in worker_outcomes.most_common()
    )

    sections.append(f"""
    <div class="section">
        <h2>Worker Outcomes ({len(worker_events)} total)</h2>
        <table><tr><th>Outcome</th><th>Count</th></tr>{worker_rows}</table>
    </div>""")

    # --- File Operations ---
    file_ops = [e for e in events if e.get("event") in (
        EventType.FILE_WRITE.value, EventType.FILE_EDIT.value
    )]
    file_freq = Counter(e.get("file", "unknown") for e in file_ops)
    top_files = "".join(
        f"<tr><td>{f}</td><td>{c}</td></tr>" for f, c in file_freq.most_common(15)
    )

    sections.append(f"""
    <div class="section">
        <h2>File Operations ({len(file_ops)} total)</h2>
        <h3>Most Modified Files</h3>
        <table><tr><th>File</th><th>Edits</th></tr>{top_files}</table>
    </div>""")

    # --- Verification Coverage ---
    # Build worker list: use role field if available, fall back to agent_type/report_type
    has_role_data = any(e.get("role") for e in starts)
    if has_role_data:
        coverage_workers = [e for e in starts if event_has_role(e, "worker")]
        coverage_verifiers = [e for e in starts if event_has_role(e, "verifier")]
        coverage_reviewers = [e for e in starts if event_has_role(e, "reviewer")]
    else:
        # Legacy fallback: use agent_type from starts or report_type from stops
        coverage_workers = [e for e in starts if e.get("agent_type") == "worker"]
        coverage_verifiers = [e for e in starts if e.get("agent_type") == "verifier"]
        coverage_reviewers = [e for e in starts if e.get("agent_type") == "reviewer"]
        if not coverage_workers and not coverage_verifiers:
            # Deeper fallback: count by report_type on stop events
            coverage_workers = [e for e in stops if event_has_role(e, "worker")]
            coverage_verifiers = [e for e in stops if event_has_role(e, "verifier")]
            coverage_reviewers = [e for e in stops if event_has_role(e, "reviewer")]

    # Match workers to verifiers: for each worker, check if a verifier started after it
    verif_cov_rows = ""
    verifier_timestamps = sorted(_ts(e.get("ts", "")) for e in coverage_verifiers)
    reviewer_timestamps = sorted(_ts(e.get("ts", "")) for e in coverage_reviewers)
    for w in coverage_workers:
        w_ts = _ts(w.get("ts", ""))
        w_id = w.get("agent_id", "unknown")
        w_task = _escape(str(w.get("task", w.get("brief", "")))[:80])
        has_verifier = "No"
        for v_ts in verifier_timestamps:
            if v_ts > w_ts:
                has_verifier = "Yes"
                break
        has_reviewer = "No"
        for r_ts in reviewer_timestamps:
            if r_ts > w_ts:
                has_reviewer = "Yes"
                break
        verif_cov_rows += (
            f"<tr><td>{_escape(w_id)}</td><td>{w_task}</td>"
            f"<td>{has_verifier}</td><td>{has_reviewer}</td></tr>"
        )

    verif_warnings = ""
    if not has_role_data and (coverage_workers or coverage_verifiers or coverage_reviewers):
        verif_warnings += '<p style="color:#636e72;font-style:italic;">&#9432; Role data not available — falling back to agent_type/report_type detection.</p>'
    if len(coverage_verifiers) == 0:
        verif_warnings += '<p style="color:white;background:#ff7675;padding:8px;border-radius:4px;">&#9888; 0 verifiers dispatched — worker output was not verified!</p>'
    if len(coverage_reviewers) == 0:
        verif_warnings += '<p style="color:white;background:#ff7675;padding:8px;border-radius:4px;">&#9888; 0 reviewers dispatched — no domain review performed.</p>'

    sections.append(f"""
    <div class="section">
        <h2>Verification Coverage</h2>
        {verif_warnings}
        <p>Workers: {len(coverage_workers)} | Verifiers: {len(coverage_verifiers)} | Reviewers: {len(coverage_reviewers)}</p>
        {'<table><tr><th>Worker Agent</th><th>Task</th><th>Verifier?</th><th>Reviewer?</th></tr>' + verif_cov_rows + '</table>' if verif_cov_rows else '<p>No worker dispatch events found.</p>'}
    </div>""")

    # --- Test Execution Summary ---
    e2e_runs = [e for e in events if e.get("event") == "e2e_run"]
    unit_runs = [e for e in events if e.get("event") == "unit_test_run"]
    build_checks = [e for e in events if e.get("event") == "build_check"]
    has_test_events = bool(e2e_runs or unit_runs or build_checks)

    e2e_pass = sum(1 for e in e2e_runs if e.get("result") == "pass" or e.get("status") == "pass")
    e2e_fail = len(e2e_runs) - e2e_pass
    unit_pass = sum(1 for e in unit_runs if e.get("result") == "pass" or e.get("status") == "pass")
    unit_fail = len(unit_runs) - unit_pass
    build_pass = sum(1 for e in build_checks if e.get("result") == "pass" or e.get("status") == "pass")
    build_fail = len(build_checks) - build_pass

    e2e_files_written = sum(
        1 for e in file_ops
        if "test" in str(e.get("file", "")).lower() or "e2e" in str(e.get("file", "")).lower()
    )

    test_no_events_warning = ""
    if not has_test_events:
        test_no_events_warning = '<p style="color:white;background:#ff7675;padding:8px;border-radius:4px;">&#9888; No test execution events recorded. Tests may not have been actually run.</p>'

    sections.append(f"""
    <div class="section">
        <h2>Test Execution Summary</h2>
        {test_no_events_warning}
        <table>
            <tr><th>Category</th><th>Total</th><th>Pass</th><th>Fail</th></tr>
            <tr><td>E2E Runs</td><td>{len(e2e_runs)}</td><td>{e2e_pass}</td><td>{e2e_fail}</td></tr>
            <tr><td>Unit Test Runs</td><td>{len(unit_runs)}</td><td>{unit_pass}</td><td>{unit_fail}</td></tr>
            <tr><td>Build Checks</td><td>{len(build_checks)}</td><td>{build_pass}</td><td>{build_fail}</td></tr>
        </table>
        <p>Test files written: {e2e_files_written} | E2E runs: {len(e2e_runs)} | Unit runs: {len(unit_runs)}</p>
    </div>""")

    # --- Worker Granularity Analysis ---
    # Group file_write/file_edit events by agent_id, then cross-reference with subagent start/stop
    agent_file_counts: dict[str, list[dict]] = {}
    for e in file_ops:
        aid = e.get("agent_id", "")
        if aid:
            agent_file_counts.setdefault(aid, []).append(e)

    # Also consider subagent starts with role=worker
    worker_agents = {}
    for e in starts:
        aid = e.get("agent_id", "")
        if not aid:
            continue
        is_worker = (
            event_has_role(e, "worker")
            or e.get("agent_type") == "worker"
            or len(agent_file_counts.get(aid, [])) > 3
        )
        if is_worker:
            worker_agents[aid] = {"start": e, "stop": None, "files": agent_file_counts.get(aid, [])}

    # Match stops
    for e in stops:
        aid = e.get("agent_id", "")
        if aid in worker_agents:
            worker_agents[aid]["stop"] = e

    granularity_rows = ""
    total_files = 0
    max_files = 0
    for aid, info in worker_agents.items():
        fc = len(info["files"])
        total_files += fc
        max_files = max(max_files, fc)
        start_ts = _ts(info["start"].get("ts", ""))
        stop_ts = _ts(info["stop"].get("ts", "")) if info["stop"] else None
        if stop_ts and stop_ts != datetime.min and start_ts != datetime.min:
            dur = f"{(stop_ts - start_ts).total_seconds():.0f}s"
        else:
            dur = "N/A"
        gd_files = sum(1 for f in info["files"] if str(f.get("file", "")).endswith(".gd"))
        flag = ""
        if gd_files > 10:
            flag = ' <span style="color:white;background:#ff7675;padding:2px 6px;border-radius:3px;font-size:0.85em;">EXCEEDS GUIDELINE</span>'
        granularity_rows += (
            f"<tr><td>{_escape(aid)}</td><td>{fc}</td><td>{dur}</td>"
            f"<td>{gd_files}{flag}</td></tr>"
        )

    avg_files = (total_files / len(worker_agents)) if worker_agents else 0
    granularity_summary = f"<p>Workers analyzed: {len(worker_agents)} | Avg files/worker: {avg_files:.1f} | Max files: {max_files}</p>"

    sections.append(f"""
    <div class="section">
        <h2>Worker Granularity Analysis</h2>
        {granularity_summary}
        {'<table><tr><th>Agent ID</th><th>Files Written</th><th>Duration</th><th>.gd Files (flag if &gt;10)</th></tr>' + granularity_rows + '</table>' if granularity_rows else '<p>No worker agents with file operations found.</p>'}
    </div>""")

    # --- Event Timeline ---
    timeline_rows = "".join(
        f"<tr><td>{e.get('ts', '')[:19]}</td><td><span class='tag {_event_class(e)}'>"
        f"{e.get('event', '')}</span></td>"
        f"<td>{_escape(_event_summary(e))}</td></tr>"
        for e in events[-50:]  # Last 50 events
    )

    sections.append(f"""
    <div class="section">
        <h2>Event Timeline (last 50)</h2>
        <table><tr><th>Time</th><th>Event</th><th>Details</th></tr>{timeline_rows}</table>
    </div>""")

    return _wrap_html("\n".join(sections))


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _event_class(event: dict) -> str:
    """CSS class for event type coloring."""
    e = event.get("event", "")
    if "block" in e or "fail" in e or "error" in e:
        return "red"
    if "pass" in e or "done" in e or "complete" in e:
        return "green"
    if e in ("e2e_run", "unit_test_run", "build_check", "worker_brief"):
        return "blue"
    if "start" in e:
        return "blue"
    return ""


def _event_summary(event: dict) -> str:
    """One-line summary of an event."""
    parts = []
    for key in ("agent_id", "hook", "reason", "file", "gate", "result", "status"):
        if key in event and event[key]:
            val = str(event[key])
            if len(val) > 80:
                val = val[:80] + "..."
            parts.append(f"{key}={val}")
    return ", ".join(parts[:4])


def _wrap_html(body: str) -> str:
    """Wrap body content in full HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GodotMaker Metrics Report</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
    h1 {{ color: #2d3436; border-bottom: 3px solid #6c5ce7; padding-bottom: 10px; }}
    h2 {{ color: #2d3436; margin-top: 30px; }}
    .section {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th, td {{ border: 1px solid #dfe6e9; padding: 8px 12px; text-align: left; }}
    th {{ background: #6c5ce7; color: white; }}
    tr:nth-child(even) {{ background: #f8f9fa; }}
    .tag {{ padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }}
    .red {{ background: #ff7675; color: white; }}
    .green {{ background: #00b894; color: white; }}
    .blue {{ background: #74b9ff; color: white; }}
</style>
</head>
<body>
<h1>GodotMaker Metrics Report</h1>
{body}
<footer style="text-align:center;color:#636e72;margin-top:40px;padding:20px;">
Generated by GodotMaker metrics system
</footer>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML metrics report")
    parser.add_argument("log_file", nargs="?", default=".godotmaker/metrics.jsonl",
                        help="Path to metrics JSONL file")
    parser.add_argument("-o", "--output", help="Output HTML file (default: stdout)")
    args = parser.parse_args()

    events = read_events(args.log_file)
    html = generate_report(events)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Report written to {args.output} ({len(events)} events)")
    else:
        print(html)


if __name__ == "__main__":
    main()

# Local Submit workbench (path 1B)

## Run locally (macOS / Linux)

Install the project dependencies with `npm ci`, then `npm run build`.
Use Python 3.10+ through uv: `uv run python bridge/server.py`.
Open the printed `http://127.0.0.1:8765` URL. This defaults to **demo**:
Submit validates and durably records a frozen snapshot; it makes no model request.
Static hosting also preserves editing, but Submit needs the local bridge.

For real Codex, first select an existing **idle** local Codex thread belonging to
the matching source game directory. Run:

    uv run python bridge/server.py --mode codex --thread THREAD_ID --project-root /absolute/path/to/velvet-eclipse --state /absolute/private/path/workbench.sqlite3

The installed `codex` must support experimental `turn/start.toolOutput`.
The bridge generates the installed JSON schema and checks this capability. It
resumes that exact thread and rejects a cwd mismatch. Browser input cannot set
cwd, model, permissions, approval policy, or configuration. Native thread settings
remain in force; interactive approval requests are denied rather than approved by
the bridge. Complete work requiring approvals in native Codex.

## Contract and boundaries

- Editing, notes, previews, theme changes and page load never start a model turn.
- Submit first opens a complete preview. Only confirmation of the unchanged frozen payload initiates a POST and possible new turn. Cancellation makes no POST and creates no pending record. Payload is durably frozen in
  browser storage before transmission, then saved in SQLite before delivery.
- App-server call is same-thread `turn/start` with `input: []` and the frozen
  envelope in `toolOutput`. An immediate thread/read idle check precedes it.
- IDs are immutable and duplicate IDs return the existing receipt. A mismatched
  payload with the same ID is rejected. One active/uncertain delivery blocks new
  submissions. Server revision protects competing tabs.
- Draft revision, bridge acceptance revision, and source identity are separate.
  The mapped source files must match Git blob identities in
  `tools/velvet-source-lock.json`; both source identity and reviewed adapter
  freshness are checked again before delivery. Formal GM readiness requires the
  bound project to be inside a Git repository. Capability locks using the legacy
  SHA scheme remain BLOCKED until their contents receive an explicit Git review.
  Each frozen draft also carries its source manifest; an older open tab or legacy draft cannot silently adopt a new adapter on refresh. Reload and reapply/review edits when that manifest is missing or stale.
  This is the reviewed Velvet adapter, not a generic source tree validator.
  After source changes, re-extract and review mappings before further submissions.
- Durable store ID prevents reconciling a lost browser attempt against a replaced
  database or different bridge. No automatic resend or replay occurs on restart.
- Results report turn completion and object-level review status, not a claim that
  source edits, game tests or requested changes have succeeded. They never
  overwrite newer browser drafts. Review the Codex response and source diff.
- All 21 definitions, 38 behaviors, placed objects and scene backgrounds have
  scoped natural-language notes. Existing supported typed parameter edits remain
  in the domain editor and are included in the submitted snapshot.

## Recovery

Refresh connection/status after a network interruption. A browser-persisted
attempt is looked up by its exact ID against the original durable store. If absent,
the UI permits an explicitly reviewed new Submit; it never resends automatically.
A received submission is displayed instead. Restarted accepted/processing records
become uncertain and preserve known turn IDs and responses.

If the server cannot establish completion, inspect that submission/turn in native
Codex. Stop the bridge, then explicitly record your inspection:

    uv run python bridge/server.py --mode codex --thread THREAD_ID --project-root /absolute/path/to/velvet-eclipse --state /absolute/private/path/workbench.sqlite3 --resolve-uncertain SUBMISSION_ID --resolution-note "Inspected native thread: turn completed; reviewed its source diff."

This closes the ambiguous delivery as a manually reconciled record, **not** a
certified success, and never resends it. Restart the bridge with the same state.
An OS file lease prevents simultaneous bridge/reconciliation processes from
rewriting another live process's delivery state.

## Security and verification limits

Loopback only, exact Host and same-origin checks, random per-process token,
JSON-only bounded POST bodies, no CORS grants. Database and lease are owner-only.
Use a private state directory; snapshots and replies contain project information.
The bridge is for a trusted local machine, not a multi-user/network service.

Validation consists of existing domain/semantic tests, mocked React fetch tests,
Python Store/protocol/security tests and the actual installed CLI schema check.
Live inference and Godot execution have not been certified by this package. Rendered-browser QA is reported separately from DOM checks; access restrictions are never bypassed. The original private hosted Site is a browser-local simulation, while this local bridge is the explicit route for a bound Codex thread. See REVIEWED-WORKFLOW.md and the current validation report.

# Bounded GM v2 bridge patch

Integration files: replace `bridge/server.py`, add `bridge/gm_contract.py` and
`bridge/gm-capability-lock.json`; add `tests/test_gm_contract.py`. Existing v1
wire shape, durable delivery, idempotency, no auto retry, native approval denial,
source/thread/store binding and old tests are preserved. The copied original
`tests/test_bridge.py` and `tools/velvet-source-lock.json` are staging test aids.
Do not replace the owner's corresponding files from this patch unnecessarily.

## Actual authority checked

Deployed Velvet GM skill/tool content came directly from
`velvet-eclipse-source-v2-delivery.zip`. Controlled review tools are identical to
GodotMaker non-pk c16d4bb8091af784fc801ca6734e79d6b17b136e. This adapter does not
use the separate gm-non-pk-specifications proposal. File SHA-256s pin deployed
skill/tool versions. GM's actual extract_spec/read_events/status/doctor parse the
bound project's PLAN, current specification, prior human provenance, latest
review run and environment. Bytecode writes and stdin are disabled for probes.
Only `thread/read` and `skills/list` are used for live runtime capability checks.
No readiness probe invokes check, play, feedback, confirmation or a writer.

## Explicit project mapping

A local project owner must review and provide
`.godotmaker/workbench-targets.json`, not a browser-supplied map:

```json
{
  "version": 1,
  "sourceBaseline": "THE_CURRENT_BRIDGE_SOURCE_BASELINE",
  "targets": {
    "behavior:player.move": {
      "kind": "behavior",
      "routeKind": "runtime",
      "gm": {
        "tag": "v0.1.0",
        "planRef": "PLAN.md",
        "mechanics": ["v0.1.0-M1"],
        "taskIds": ["R1"]
      },
      "allowedDiffPaths": ["/objects/player/speed"],
      "allowedSourcePaths": ["data/player.json"]
    }
  }
}
```

This is an illustrative schema, NOT an approved map. Exact target IDs and diff
paths must match the reviewed semantic adapter. Unknown IDs, missing maps,
changed baseline, forged mapping, conflicting tag/mechanic/task IDs and
out-of-scope paths block execution. `kind` is semantic navigation identity;
`routeKind` alone selects design, art or runtime. The full snapshot is context,
not authority to rewrite unrelated targets.

## Wire contract

GET status advertises `supportedSubmissionVersions: [1,2]` and `gmReadiness`:
status READY/BLOCKED, readOnly true, named checks, binding, optional humanRequired,
actual GM observations and baseline-bound targetMappings. Demo is BLOCKED for
real GM, not falsely ready. Missing skills/capabilities or unrecognized tool
versions stay BLOCKED with a concrete reason.

v2 preserves all v1 keys and adds resolvedTargets, diff (targetId/path/operation
add/remove/replace/before/after), allowedChangeScope reviewed-targets-only,
executionIntent review-and-apply, planTags, mechanismRefs, reviewedSpecDigest, reviewedAuthorityDigest; optional feedback has
EXACTLY id, mechanics, platform, text, type, source_ref. Feedback requires a real
formal check run. Smoke/play cannot supply it. Delivery starts only after a new
readiness and mapping check at execution time, not a stale browser claim.

## Workflow and confirmation phases

Design routes to gm-gdd/PLAN; art to gm-asset, provider and validated registration.
Runtime routes to gm-build; immutable implementation feedback first reproduces,
then gm-fixgap/verify/evaluate; experience reproduces and classifies; test_error
returns to Evaluator; capability is BLOCKED; design_change stops writes until
GDD/PLAN scope and exact specification are confirmed. Original workers never
write e2e. Single active writer and original PLAN/GAP authority remain mandatory.

Existing exact-spec local-interactive confirmation is reused. Capability readiness
and human phase checks are separate. Read-only design diagnosis/proposals may run
before specification confirmation, but must stop before project writes. Missing
required spec confirmation is needs_human before dependent implementation. Acceptance is
requested only after experience verification; feedback resolution only after
current fix evidence and verified original GAP task. The bridge never produces
TTY answers or treats its Submit click, model prose, actor flags or stage events
as human acceptance. Native existing interactive approval denial is preserved.

## Result honesty and present limits

v2 result schema separates delivery from turn completion, per-item implementation
and verification, human gate, and submission/turn/task/run/report references.
Turn completion alone yields no implementation or verification PASS. The latest
existing run is context, not evidence that a new submission was implemented.

Independent evidence import is implemented with a local operator-only command:

```sh
python bridge/server.py --mode codex --thread ORIGINAL_THREAD \
  --project-root /actual/bound/project --state /original/store.sqlite3 \
  --import-result /path/to/evidence-import.json
```

Stop the running bridge before import; the same process lease prevents concurrent
store use. No browser evidence-import endpoint exists. The import manifest is:

```json
{
  "schemaVersion": 1,
  "submissionId": "EXACT_SUBMITTED_ID",
  "turnId": "EXACT_ACTUAL_TURN_ID",
  "taskId": "velvet-eclipse",
  "sourceBaseline": "EXACT_SUBMITTED_BASELINE",
  "runId": "ACTUAL_FORMAL_CHECK_RUN",
  "items": [{
    "id": "EXACT_RESOLVED_TARGET_ID",
    "taskIds": ["EXACT_SERVER_REVIEWED_TASK_ID"],
    "reportRefs": ["reports/ACTUAL_CHECKSUM_BOUND_REPORT.json"]
  }]
}
```

The manifest selects evidence only; it may not supply PASS/status assertions.
For implementation/experience feedback, taskIds also includes the actual immutable
F-<feedback-id> GAP task after the original PLAN IDs. Every resolved target must
be covered exactly once. The adapter checks original project/thread/submission/
turn/task/baseline bindings, run start after the server-observed turn start,
actual formal check command/schema, checksum, report digests, current exact
spec/source/test identities, snapshot integrity, source changes limited to
server-approved source paths, and pre/post inspection drift. No v2 route, including art or mixed routes, grants normative specification changes. Any specification drift requires a newly reviewed baseline. Read-only design proposals reject all source and test changes during result import. Original GM gate validates raw reports,
nonzero cases, profile evidence and evaluator binding. It is called read-only
without creating/recovering locks; an existing run lock blocks import.

Global run verification returns actual PASS/FAIL/BLOCKED/ERROR from independently checked run evidence, keeping human phase blockers separate. Per-item verification remains BLOCKED until report-internal target/task/assertion coverage is supported; report membership or a global PASS is not a per-item PASS. The item records carry runVerification only as separate global-run context. Exact acceptance is reused;
missing specification, verified-feedback resolution and experience acceptance
remain distinct phases. No import writes source, PLAN/GAP, human events or the
browser draft. Only the durable bridge result is updated.

Implementation remains BLOCKED/review_required unless an authoritative failed
task supports FAIL. SOURCE_CHANGED and task-state observations are shown
separately. A preexisting verified PLAN row, new global passing check, or arbitrary
edit in an allowed source file does NOT prove the requested parameter delta or
note was implemented. Item-specific semantic evidence ingestion is not supported
by this bounded adapter yet. This intentionally avoids false per-item completion.
No real GM integration or game run was certified by the mocked regression tests.

Feedback source_ref is more restrictive here than raw GM's audit-only string: it
must be an actual selected current formal-check manifest or checksum-bound report
path exposed by gmReadiness.gm.runContext. Unknown/external/stale citations block.
Platform must name an explicit current PLAN profile/platform. The six-key GM
feedback format is preserved; run/report metadata is not injected as extra keys.

Readiness proves only its named observations. Godot doctor probes versions and
capability presence; it cannot prove browser/visible/physical-input readiness or
all future provider operations. Dependent GM workflows must still stop BLOCKED
when their required actual capabilities are unavailable. Tools are not installed,
updated, or replaced by this patch. New tool versions require explicit review and
fingerprint refresh. The trust boundary remains cooperating local same-user
processes, not a hostile-user process sandbox.

Run: `python -m unittest discover -s tests -p 'test*.py'`.

## Review bindings and controlled-file audit

V2 freezes the exact server-observed specification digest and authority digest.
The latter covers an independent final-state inventory of project files and the
server-owned adapter baseline. A different PLAN/GAP/config/mapping/skill digest
at execution time requires a new preview; current confirmation cannot silently
upgrade an older payload. The typed diff is independently recomputed from
`dist/adapter-baseline.json` and the submitted snapshot. Every before/after, path,
operation and target must match. Missing baseline or contradictory diff blocks.
The baseline is generated from the source adapter at build time and checked in
regression tests; it is never derived from browser POST data.

The controlled inventory covers Markdown, docs, configuration, mappings, skills,
tests and source/assets. Changes outside explicit server-reviewed allowed file
paths are rejected; PLAN/GAP status edits also require explicit path permission.
Read-only design proposals allow no controlled-file change. No route authorizes
normative spec drift in the same submission.

Explicit generated-runtime exclusions are `.git/`, `.godot/`,
`.godotmaker/runs/`, `.godotmaker/evaluation-runs/`, `.pytest_cache/`,
`tools/__pycache__/`, `tests/__pycache__/`, `test/__pycache__/`,
`hooks/__pycache__/`, and the exact files `.godotmaker/run.lock`,
`.godotmaker/stage.jsonl`, `.godotmaker/latest-review.json`,
`.godotmaker/evaluation.json`. Configuration, feedback records and target maps
under `.godotmaker/` are not blanket-excluded. The status and result expose this
coverage. This is a final-state hash audit, not an OS sandbox or proof that no
transient write occurred and was reverted. Original GM provenance checks still
apply to excluded runtime evidence and human events.

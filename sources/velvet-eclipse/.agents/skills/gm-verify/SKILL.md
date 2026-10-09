---
name: gm-verify
description: |
  Mechanical verification of the built game: headless build, unit tests, lint, static checks.
  Explicit invocation only — use /gm-verify.
disable-model-invocation: true
---

# GodotMaker Verify

$ARGUMENTS

You are performing mechanical verification of a built Godot game project. This is a non-creative, checklist-driven process.

## Session Setup

**FIRST ACTION — before anything else:** Write `verify` to `.godotmaker/current_role`.

**Permission:** Read-only with three exceptions — you may write `.godotmaker/current_role`, append to `.godotmaker/stage.jsonl`, and write `.godotmaker/verify_report.json`. Verify never modifies game code or planning docs.

Read `references/bound-review.md` for version-bound review, platform evidence,
feedback intake, and the single-active-writer boundary.

## Resume Check

Read `.godotmaker/stage.jsonl` (treat as empty if missing) — each line is `{"role": X, "ts": Y}`.

- If **no event with `role == "build"` AND no event with `role == "fixgap"`** exists anywhere in the file → STOP. Tell user to run `/gm-build` first.
- If the **last event** has `role == "verify"` → STOP. Tell the user:
  > "Verify already ran at {timestamp} with no state-changing event since. Recommended next: /gm-evaluate.
  > If you need to redo this step or have other plans, just tell me."
- Otherwise → proceed (verify is naturally re-invoked after each build/fixgap cycle).

## Run the checks

From the project root:

```bash
python tools/run_verify.py
```

`run_verify.py` wraps the four mechanical checks (build / unit tests /
lint / static check) and prints a JSON document matching `Output Format`
Section B to stdout. Capture stdout.

What the script does:

- Reads `godot_path` from `.claude/godotmaker.yaml`; falls back to
  plain `godot` from PATH. A missing or broken binary surfaces as a
  `tooling_notes[].suggested_fallback = "escalate"` entry.
- Runs `<godot_path> --headless --quit` and writes blocking Godot diagnostics
  to `checks.build.errors[]`.
- Runs `<godot_path> --headless ... res://addons/gdUnit4/bin/GdUnitCmdTool.gd
  --ignoreHeadlessMode --add res://test/ --report-directory <temp>` and
  parses the generated JUnit XML into
  `checks.unit_tests.{passed, failed, failures[]}`. Stdout is diagnostic
  only; it never replaces the XML report.
- Emits disabled `checks.lint` as `result: "skipped"`, `required: false`, with an explicit reason. Do NOT call this PASS or re-enable here.
- Delegates `checks.static_check` to
  `python tools/check_project.py <project_dir> --build --ecs --tests --plan --mcp`.
- Exit codes are PASS=0, FAIL=1, BLOCKED=2, ERROR=3. Process completion alone is never success.

## Sanity-check the script output

Validate with `tools/run_verify.py`'s `load_report`, `normalize_report`, or
`validate_report` helpers. Persist the producer's JSON verbatim; never repair
its result by hand. Require schema_version=2 and consistent status/result/exit.
Legacy reports retain their reported_status for history but are effectively
BLOCKED/unverified, never silently upgraded to current proof.

Missing or malformed XML, contradictory counters, or return-code/report
contradictions are ERROR; zero cases or skipped required cases are BLOCKED.
Stdout is diagnostic only and never substitutes for actual JUnit XML. Required
checks must run; lint is optional and explicitly skipped. Keep raw execution
command, cwd, timeout_seconds, returncode, stdout/stderr, and XML evidence.

## Output Format

You produce **two outputs**:

### A. Human-readable report (chat)

Build this from the JSON the script returned — do not re-run any
command for the chat side.

```
## Verification Report

### Build
Result: PASS | FAIL | BLOCKED | ERROR
{If FAIL, one line per checks.build.errors[] entry: `- {file}:{line}: {message}` (file/line may be empty)}

### Unit Tests
Result: PASS | FAIL | BLOCKED | ERROR
{N passed, M failed}
{If FAIL, one line per checks.unit_tests.failures[]: `- {test}: {message}`}

### Lint
Status: SKIP (gdtoolkit disabled — ROADMAP R-112)

### Static Check
Result: PASS | FAIL | BLOCKED | ERROR
{If FAIL, one line per checks.static_check.issues[]: `- {check}: {detail}`}

### Overall: PASS | FAIL | BLOCKED | ERROR

{If tooling_notes is non-empty, append:
## Tooling Notes
- {tool}: {error} (suggested_fallback: {suggested_fallback})
…}
```

### B. Machine-readable report (`.godotmaker/verify_report.json`)

Write this file every run (PASS, FAIL, BLOCKED, or ERROR). `/gm-build` and `/gm-fixgap` read it on their next invocation to translate failures into pending tasks.

The v2 producer (`tools/run_verify.py`) owns the exact schema. Keep:

- `schema_version: 2`, `status: PASS | FAIL | BLOCKED | ERROR`, matching lowercase `result`, matching `exit_code: 0 | 1 | 2 | 3`, `ts`, `checks`, `tooling_notes`.
- Required `checks.build`, `checks.unit_tests`, and `checks.static_check` with `required: true`; each result is `pass | fail | blocked | error`.
- `checks.lint` with `required: false`, `result: skipped`, `reason: gdtoolkit disabled`, `issues: []`, and `format_drift: null`.
- Every executed check's `execution` has the actual command array, cwd, timeout_seconds, returncode, stdout and stderr; unit execution also retains `report_xml`.
- Unit `total`, `passed`, `failed`, `skipped` and per-test XML counters must agree; positive executed tests and zero skipped required tests are necessary for PASS.
- Existing error/failure/issue arrays and fallback operands remain present. A required missing prerequisite is BLOCKED; tool failure or corrupt evidence is ERROR; real failed assertions are FAIL.
- Overall outcome precedence is ERROR > BLOCKED > FAIL > PASS. Warning diagnostics remain warnings alongside pass, never a separate `warn` result.
- Top-level PASS requires every required check to pass with valid evidence. Do not average outcomes or use a missing/optional profile to satisfy a required one.

- **`suggested_fallback`** + matching operand — the producer fills the operand so the consumer can act deterministically:

  | `suggested_fallback` | Required operand |
  |---|---|
  | `exclude_file` | `crashed_on` (already required on every note) |
  | `scope_narrow` | `narrowed_command` (replacement command, e.g. `"gdlint src/"`) |
  | `add_gdlintrc_rule` | `rule_name` (e.g. `"class-name"`) |
  | `skip_check` | `check_name` (e.g. `"missing_unit_test"`) |
  | `escalate` | — (none) |

  **Producer rule:** if you cannot fill the required operand for a non-`escalate` fallback, emit `escalate` instead.

  **Consumer rule** (open-enum forward-compat): a missing required operand or an unknown `suggested_fallback` value MUST be treated as `escalate` (surface to user, do NOT auto-fix). Never crash.

## On Failure

When `status` is FAIL, BLOCKED, or ERROR:

1. Write the script's JSON verbatim to `.godotmaker/verify_report.json`.
2. Distinguish failed assertions from blocked prerequisites and tool errors in the chat report; emit the chat report (Section A) and tell the user which checks failed. Suggest `/gm-build` if the last state-changing event was `build`, `/gm-fixgap` if it was `fixgap`.
3. Do NOT append a `verify` event to `stage.jsonl` — only PASS records a stage event.

## When Done

When the validated script JSON has `status: "PASS"`:

1. Write the script's JSON verbatim to `.godotmaker/verify_report.json`. (Required checks actually passed; optional lint remains skipped. Validate through the shared helper before appending a stage event.)
2. From the project root run `python tools/append_stage_event.py verify` to append a `{"role": "verify", "ts": "<server-generated UTC>"}` line to `.godotmaker/stage.jsonl`. Do NOT hand-write the JSON or the timestamp — the helper exists so the timestamp comes from the system clock, not your own output.
3. `git add -A && git commit -m "chore(verify): <Tag>"`
4. Inform the user: `Verify complete. Recommended next: /gm-evaluate`

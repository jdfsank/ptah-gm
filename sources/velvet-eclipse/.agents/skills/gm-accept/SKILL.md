---
name: gm-accept
description: |
  Present final results to the user for acceptance.
  Shows evaluation results, evaluator screenshots, and asks for confirmation.
  Explicit invocation only — use /gm-accept.
disable-model-invocation: true
---

# GodotMaker Accept

$ARGUMENTS

You are presenting the **current tag's** completed work to the user for acceptance. This is a per-tag gate — accepting now does NOT mean the whole game is done; it means this tag (vX.Y.Z) is ready to be sealed, archived, and git-tagged by `/gm-finalize`. The user can choose to continue to the next tag (`/gm-gdd` again) or stop the project here.

## Session Setup

**FIRST ACTION — before anything else:** Write `accept` to `.godotmaker/current_role`. Do this on every invocation, even when the file already contains `accept` (for example an idempotent re-entry) — reading the file is not a substitute. The write must actually happen and must be your first action.

Read `references/bound-review.md` for version-bound review, platform evidence,
feedback intake, and the single-active-writer boundary.

## Resume Check

Read `.godotmaker/stage.jsonl` (treat as empty if missing) — each line is `{"role": X, "ts": Y}`. Also read `.godotmaker/evaluation.json`.

- If **no event with `role == "evaluate"`** exists anywhere in the file OR `evaluation.json` does not exist → STOP. Tell user to run `/gm-evaluate` first.
- If `evaluation.json` `result` is `"reject"` → STOP. Tell user to run `/gm-fixgap` first.
- For bound runs, use the shared `review_support.gate(project, require_accept=False)` pre-accept check, also called by the controlled decision entry. A stale or missing profile, unresolved feedback, or changed input blocks acceptance.
- If the last acceptance is valid for the current run and input digests → STOP. Tell the user:
  > "Accept already recorded at {timestamp}. Recommended next: /gm-finalize.
  > If you need to redo this step or have other plans, just tell me."
- Otherwise → proceed (re-invocation is valid if the previous accept event recorded a `fix` or `done` decision).

## Process

### 1. Gather Results

Read these files:
- `.godotmaker/evaluation.json` — evaluator results (mandatory)
- `PLAN.md` — task completion status
- `MEMORY.md` — stable architecture decisions and project constraints
- `GDD.md` — original requirements

### 2. Collect Screenshots

Do NOT capture new screenshots. Use the screenshots already captured by the Evaluator:
- For a bound run, use its immutable manifest/report/evidence references under `.godotmaker/runs/<run_id>/`; use `e2e/screenshots/` only for a legacy unbound presentation
- These correspond to reference images in `references/scene_{name}.png`
- If no evaluator screenshots exist, note this as a gap

### 3. Present to User

Format a clear summary:

```
## Tag Summary — {Tag from PLAN.md}

**Project:** {name}
**Tag delivers:** {one-liner from ROADMAP.md entry for this tag}

### What This Tag Built
- {N} new systems, {M} new components added in this tag
- Tag mechanics delivered: {Tag Mechanics list from PLAN.md, all PASS per evaluation.json `tag_mechanics`}
- Inherited mechanics still passing: {list each `<prev>-MN: pass` from evaluation.json `inherited_mechanics`}

### Test Results
- Unit tests: {from gm-verify results or PLAN.md}
- E2E suite: {evaluation.json `e2e_tests.passed`/`e2e_tests.total` — single suite covering both this tag's mechanics and inherited mechanics}

### Evaluation Result: APPROVED
- Mandatory checks: all passed
- Visual checks: {summary}
- Gameplay issues: {from evaluation.json, or "none"}

### Known Limitations
- {from evaluation minor_issues}

### How to Run
{instructions}

### Screenshots
{show evaluator screenshots side-by-side with references}

### What's Next
- After /gm-finalize this tag will be archived to docs/tags/{Tag}/ and `git tag {Tag}` will be created.
- Remaining tags in ROADMAP.md: {list of unshipped tags}
- To start the next tag, re-run /gm-gdd; to stop here, just don't.
```

### 4. Ask for Decision

Use AskUserQuestion to ask:
- **Accept** → I'll record acceptance and recommend /gm-finalize.
- **Fix issues** → tell me what to fix and I'll dispatch /gm-fixgap.
- **Done for now** → progress is saved; you can resume any time."

Do NOT proceed until the user replies. Their reply drives the When Done branch below.

## When Done

Record a bound decision using `python tools/gm_review.py decision --project . --run <run_id>
--choice <accept|changes_requested|design_change|defer> --reviewed-profile <profile>`
(repeat the profile option for every profile actually reviewed) only after the user reviews the named run, spec/source/test digests, the bound evaluator report digest,
evidence reference, and required profiles. Its actual local-interactive input
is the human confirmation boundary. Never pipe an agent-generated answer or
pass `--actor=human`; a generic stage appender cannot accept a new-format run.
If this runtime cannot collect supported human provenance, report `needs_human`.

The event remains `role=accept` with `decision`, `tag`, `run_id`, `spec_digest`,
`source_digest`, `test_digest`, `evaluation_digest`, `evidence_ref`, `reviewed_profiles`, and genuine
confirmation provenance. `changes_requested` is independent of automatic
approve and must create/reference immutable feedback before `/gm-fixgap`.
Legacy `append_stage_event.py accept --decision=<accept|fix|done>` remains an
unbound audit path for old projects; it cannot certify a new-format run.

Then: `git add -A && git commit -m "chore(accept): <Tag> <decision>"`.

Then, based on the decision:
- **accept** → Inform the user: `Accepted. Recommended next: /gm-finalize`
- **fix / changes_requested** → record immutable version-bound feedback, then run `/gm-fixgap`; preserve evaluator approve and reproduce the report first
- **done** → Inform the user: `Progress saved; resume any time`

Note: for new-format runs, only the shared guard can establish acceptance for the current inputs. An old `decision == "accept"` alone is insufficient. Fix/done/changes_requested remain audit records.

<!-- AUTO-GENERATED from skills/core/_shared/bound-review.md. Do NOT edit this deployed copy — it is overwritten on every publish. Edit the source under skills/core/_shared/ instead. -->

# Bound Review and Feedback Contract

PLAN.md remains task and scope authority; GAP.md remains repair authority.
Reports own check facts; stage events own version-bound human decisions.
The original Evaluator retains playable-unit, mechanics, visual, and gameplay
judgment authority; `check` alone cannot replace its approved report. There
is no scheduler, state database, or replacement planner.

## Controlled review entry

Use `python tools/gm_review.py <command> --project .` with `status`, `check`,
`play`, `feedback`, `decision`, and `gate` (see each subcommand's `--help`). Check creates a fixed project
snapshot under `.godotmaker/runs/<run_id>/`; `.godotmaker/latest-review.json`
points to the latest run. A finished process is not a passing check.

The shared guard requires the current confirmed specification, matching
spec/source/test identities, real required profile evidence, and resolution
of blocking user feedback. `gm-accept` uses the guard without requiring a prior
acceptance; `gm-finalize` uses the same guard with acceptance required.
A changed asset, source, test, or normative scope invalidates stale acceptance.
`bind-evaluation` binds the existing evaluator report and real evidence to the
reviewed run; its `evaluation_digest` also belongs to the accepted version.
Legacy unbound approve and a changed evaluator report cannot satisfy the gate.
A PLAN Task Status or Evidence-path update alone does not change scope.

Local-interactive decisions must come from actual terminal input through the
controlled entry. Agent-authored `--actor=human`, an automatic report, roleplay,
or a generic append-stage command is never human approval. Without a supported
human confirmation entry, report `needs_human` and keep the gate blocked.
Self-review is labelled `self_review`; role names do not prove independence.

## Evidence and platforms

PLAN's Platform Commitments is the single platform authority. Required
profiles must actually run and pass. SKIP/BLOCKED/ERROR/UNKNOWN, zero cases,
missing evidence, or stale inputs cannot become PASS. An automatic approve
can coexist with `changes_requested`; preserve both facts.

`semantic_action` only proves action/runtime semantics; `engine_event` proves
the engine event/mapping route; `physical_device` requires real device input.
Do not upgrade headless evidence into visuals, audio, physical devices, or a
claim that a future platform is supported. For experience judgments, ask the
PLAN Review Notes questions at the first playable core, significant feel
changes, new input methods, and major asset integration.

## Feedback before or after evaluation

`feedback` records immutable `.godotmaker/feedback/<id>.json` with source, tag,
run, mechanics, platform, observed text, type, and provenance. `host_supplied`
feedback needs `source_ref`; it records a cited user report, not strong identity.
It can be recorded before `/gm-evaluate`, including after automatic approve.

Before dispatch, recreate or reproduce the report and record the expected
behavior, observed gap, and reproduction/check evidence in its GAP task. If
blocked from reproducing, record the blocker and stop dependent repair rather
than inventing a confirmed bug. A feedback ID maps once to `F-<id>` across root
and archived GAP files; repeated intake resumes that task and never duplicates
or deletes the original feedback. A new run does not close old feedback.

- Existing confirmed runtime behavior broken: dispatch a bounded GAP repair.
- New or changed design requirement: stop the active writer, confirm the
  GDD/PLAN change, reconfirm specification, then dispatch under the new scope.
- Wrong assertion/scenario/capture: hand back to Evaluator; do not weaken
  gameplay to satisfy the test or let workers write `e2e/`.
- Experience or platform evidence missing: ask the specific review question or
  run the missing profile; do not rewrite automatic results.

Keep accepted source requirements and anti-success constraints in every task.
Only explicit disposition with current evidence can resolve blocking feedback.

## One active writer

Keep at most one active game or planning writer across controlled work. A
worker receives one task summary: task ID, mechanic IDs, player value, allowed
files, must-preserve constraints, required checks, and stop condition. Stop on
scope conflict, missing prerequisite, unresolved process ownership, or a change
outside its boundary. Wait for completion/confirmed termination before
changing goals or dispatching the next writer. No hot-switching and no late
results silently merged into a new goal. Read-only reviews may overlap.

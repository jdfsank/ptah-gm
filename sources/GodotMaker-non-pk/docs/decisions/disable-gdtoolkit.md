# Disable gdtoolkit (gdlint + gdformat)

- **Status:** disabled in v0.3.4
- **Tracked as:** [ROADMAP `R-112`](../../ROADMAP.md)
- **Decided:** 2026-05-09

## Why

`gdtoolkit/linter/class_checks.py:144` raises `NotImplementedError` on
common ECS-style GDScript class shapes (e.g. `extends System` with
`class_name` + `@export` mixed with private state). The crash was
recurring on real project code, forcing the build / fixgap loop into
a `.gdlintrc` config-rule patch path each time — solely to silence
the crash, with zero project-code signal extracted in return.

Cost-benefit verdict for an LLM-only authorship pipeline:

- gdtoolkit's contribution is **style consistency only** — formatting
  and stylistic conventions.
- Correctness coverage is already provided by:
  - `godot --headless --quit` (gm-verify Section 1) — compile errors,
    parse errors, runtime startup failures.
  - Reviewer pattern checks (gm-build review pass) — ECS contract
    violations, signal/group misuse, scene-tree manipulation in
    physics callbacks, etc.
- Style is not human-graded in this pipeline. Disabling gdtoolkit
  removes the only failure mode (the crash) without losing any signal
  the pipeline acted on.

## Files modified in v0.3.4

**SKILLs**
- `skills/core/gm-verify/SKILL.md` — Lint section replaced with
  "Currently disabled" banner pointing at R-112; Output Format Lint
  line collapsed to `Status: SKIP`.
- `skills/core/gm-build/SKILL.md` — gdtoolkit row removed from
  Available Skills table.
- `skills/core/gm-fixgap/SKILL.md` — same removal.
- `skills/core/gdtoolkit/SKILL.md` — deprecation banner added at top.
  Reference content (rule docs, command examples) preserved intact for
  ad-hoc / future re-enable use.
- `skills/core/mcp-driver/SKILL.md` — gdtoolkit fast-path row +
  paragraph removed.

**Agents**
- `agents/worker.md` — gdtoolkit removed from skill list.
- `agents/verifier.md` — Lint section removed; `--all` invocation of
  `check_project.py` narrowed to `--build --ecs --tests --plan --mcp`
  (same direction as the gm-verify fix; the `--all` change was
  bundled here because the same edit pass touched these lines).

**Build / CI / Hooks**
- `scripts/install-hooks.sh` — comment about gdlint pre-push step
  cleaned up.
- `scripts/pre-push` — gdlint step removed.
- `.github/workflows/ci.yml` — `lint-gdscript` job removed.

**Wiki / docs (en + zh mirrors)**
- `docs/wiki/02-concepts/the-9-roles.md`
- `docs/wiki/03-skills/core-skills.md` — gdtoolkit row removed from
  the Godot reference table.
- `docs/wiki/07-contributing/codebase-guide.md` — Supporting skills
  list count 12 → 11; gdtoolkit removed.
- `docs/zh/wiki/...` — same as the three above.

**Top-level docs**
- `CLAUDE.md` — gdtoolkit removed from Supporting skills line.
- `CONTRIBUTING.md` — gdlint command removed from contributor
  validation pipeline.

## Behavior preserved (consumer-facing)

- **`verify_report.json` `lint` block schema is unchanged.** Producer
  (`gm-verify`) always emits `result: "pass"`, `issues: []`,
  `format_drift: null`. Downstream consumers (cli core, future
  tooling) continue to work without special-casing the disable. The
  schema contract is the load-bearing compat hook — see
  `gm-verify/SKILL.md` Section 3 for the explicit "still write the
  lint block" instruction.
- **`skills/core/gdtoolkit/SKILL.md` is preserved on disk.** The skill
  is not loaded by any other skill or agent in v0.3.4, but the file
  remains for ad-hoc invocation by humans or future re-enable. The
  deprecation banner at the top of the file signals its current state.

## How to restore

Re-enable when **either** condition holds:

- (a) gdtoolkit upstream ships a release that handles ECS-style class
  shapes without `class_checks.py` crashing.
- (b) The project gains a non-LLM contributor base where style
  enforcement provides value beyond what the reviewer pattern checks
  already cover.

Restore points (reverse the changes listed under "Files modified"):

1. **`gm-verify/SKILL.md`** — replace the "Currently disabled" Lint
   banner with the original Lint command sample. Restore Output
   Format Lint line to its full `Command: ... / Result: ... / Output:
   ...` shape.
2. **`gm-build/SKILL.md`** + **`gm-fixgap/SKILL.md`** — re-add the
   gdtoolkit row to Available Skills tables.
3. **`gdtoolkit/SKILL.md`** — remove the deprecation banner.
4. **`mcp-driver/SKILL.md`** — re-add the gdtoolkit fast-path row +
   paragraph.
5. **`agents/worker.md`** — re-add gdtoolkit to skill list.
6. **`agents/verifier.md`** — re-add Lint section. (The `--all`
   narrowing is independent and stays — that was Fix 4 territory.)
7. **`scripts/pre-push`** — re-add the gdlint step.
8. **`.github/workflows/ci.yml`** — re-add the `lint-gdscript` job.
9. **Wiki / docs** (en + zh) — re-add gdtoolkit to the Supporting
   skills list (count → 12), re-add the table row in
   `docs/wiki/03-skills/core-skills.md`.
10. **`CLAUDE.md`** — re-add gdtoolkit to Supporting skills line.
11. **`CONTRIBUTING.md`** — re-add gdlint command to validation
    pipeline.

After restoring the producer side, the `verify_report.json` `lint`
block will start carrying real values again. Consumers that previously
saw only `result: "pass"` need no schema change — they'll begin to see
the field populated as designed.

The producer-side schema doesn't need migration: the field has been
emitted continuously since v0.3.0; only the values change from
all-pass to real-graded.

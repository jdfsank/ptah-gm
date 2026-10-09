# Version-bound playable review (GM-Non-PK)

This fork keeps the existing gm-* skills and PLAN/GAP documents. It does not
invoke a model, install dependencies, publish a game, or approve on your behalf.
The current validated runtime is Linux, Godot 4.6.3 and Python 3.12.14. Controlled
process-tree execution currently requires POSIX; other platforms are not part
of the real-engine validation claim. `FORK.md` and `config/review-baseline.json`
record the baseline and license. No planner runtime is required.

## Prepare an isolated test environment

Dependency setup is a separate explicit operator action, never a review-command
side effect. With installed uv, run from the framework checkout:

```sh
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements-review.lock
.venv/bin/python -m pytest tests/ -q -m 'not network'
.venv/bin/ruff check .
```

The lock records the versions actually tested. Python test skips are not game
PASS evidence. The opt-in engine test requires an already installed Godot
4.6.3; a missing/wrong engine fails that explicit job. The manual CI workflow
uses a pre-provisioned trusted Linux runner and performs no engine installation.
No hosted CI execution is claimed by a local test run.

## N01: readonly doctor and real fixed smoke

```sh
python tools/gm_review.py doctor --project /absolute/game --json
python tools/gm_review.py smoke --fixture one_room_loop --output /absolute/new-run --json
python tools/gm_review.py smoke --fixture one_room_loop --variant pause_input_leak --output /absolute/new-fault-run --json
GM_REAL_GODOT=1 .venv/bin/python -m pytest tests/integration/test_review_smoke.py -q
```

Doctor reuses the upstream config/version lookup and only probes versions and
capabilities. It neither runs game scripts nor changes the project. Smoke copies
the fixed source into a new directory, isolates imports/user data, runs Godot,
then checks actual assertions and source/test drift. Existing output directories
are refused. All four fault variants use the same test script. The fixture
proves infrastructure behavior only, not generated games, screenshots, audio,
physical devices or enjoyment. Reports/logs live below each output directory.

## Original workflow plus bound review

1. Use the original `gm-gdd`, `gm-asset`, `gm-build` and role-owned tests. PLAN
   adds Iteration Intent, Review Notes and Platform Commitments. Confirm the
   normative requirements with `confirm-spec` in a real terminal.
2. Run `check --project ...`; it creates one isolated source snapshot and runs
   the original verifier plus evaluator-authored `e2e/` tests through installed
   godot-e2e/pytest. It does not invent a generic game oracle. Individual
   `--suite verify`/`--suite e2e` runs are diagnostic and cannot pass the full gate.
3. Evaluator retains all original mechanic/Playable Unit/visual/experience
   requirements. If it changes tests, run `check` again. Inspect the exact
   snapshot and preserve truthful missing-capability results.
4. Add the current manifest's tag, run_id, spec_digest, source_digest and
   test_digest to the original `.godotmaker/evaluation.json`, plus review_kind
   (`self_review` or an independently identified review). Preserve original
   coverage, visual evidence and issues. Run `bind-evaluation --run ...`; it
   validates and appends the bound evaluate event, reusing original
   `evaluation-runs` archives rather than duplicating media. Do not separately
   append the old evaluate event for this bound flow.
5. Use `play --run ...` for a native window of the fixed snapshot. It uses
   independent user data and records process completion, never acceptance.
   Display absence returns BLOCKED. Preview can coexist with later production
   edits, but an old snapshot cannot approve new source.
6. Submit user observations through `feedback --run ... --file feedback.json`.
   The immutable report is routed once to original GAP. Reproduce before
   dispatch. Automatic approve remains unchanged by a human denial.
7. After the original repair/reverify cycle, an actual user can resolve a
   verified GAP feedback item with `resolve-feedback --run ... --id ...`.
   Accept via `decision --choice accept --run ... --reviewed-profile Desktop`.
   Use each exact required profile name from PLAN. Changes requested, design
   change or defer are independent decisions and need no reviewed-profile flag.
8. `gate` rechecks current inputs, actual raw suite evidence, original bound
   evaluator evidence, current user decision and unresolved feedback under the
   same local lock used by `gm-finalize`/`seal_tag`. It refuses missing evidence,
   drift, pending tasks or unresolved user vetoes.

```sh
python tools/gm_review.py status --project /absolute/game --json
python tools/gm_review.py confirm-spec --project /absolute/game
python tools/gm_review.py check --project /absolute/game --json
python tools/gm_review.py bind-evaluation --project /absolute/game --run RUN-...
python tools/gm_review.py play --project /absolute/game --run RUN-...
python tools/gm_review.py decision --project /absolute/game --run RUN-... --choice changes_requested
python tools/gm_review.py gate --project /absolute/game --json
```

Feedback file format:

```json
{"id":"FB01","mechanics":["v0.1.0-M1"],"platform":"Desktop","text":"User's exact observation","type":"experience","source_ref":"actual-user-message-reference"}
```

Types are implementation, experience, design_change, test_error or capability.
A source_ref is audit provenance, not strong identity. The CLI cannot certify a
fabricated source. Human acceptance is only available through real local TTY
input; noninteractive callers get needs_human. Synthetic unit-test decisions
and evidence are confined to temporary test fixtures and are never product
acceptance results. There is no `--actor=human` shortcut.

## Identity, recovery and limits

- Spec digest includes fixed PLAN sections and GDD/DESIGN/SCENES/ASSETS/STRUCTURE;
  Task Status and the Playable Unit Evidence column alone are excluded. Unknown
  sections/malformed or empty requirements block rather than hash as empty.
- Source digest includes dirty/untracked game assets, scripts, scenes, addons and
  project/input config. Tests, actual Python package versions, runner source and
  config have a separate digest. Snapshot docs and normalized configs are bound
  too; file permissions alone are never considered protection from drift.
- Git/import caches, workflow records and screenshot outputs are excluded from
  source identity. Explicit resource references into excluded paths are blocked.
  Symlinks, credential directories/files and unknown runtime config keys block
  snapshots. Supported config scalars are copied with a known-key allowlist;
  no credentials or arbitrary comments are copied to the runtime config.
- A narrow local run.lock coordinates controlled commands. Ctrl-C/timeout
  terminates owned process groups. Unknown/stale owners are never automatically
  adopted. `recover-lock` only permits absent local PIDs plus an explicit human
  confirmation and never reruns unfinished work.
- Same-permission editors/agents can bypass these tools; hashes/locks are
  accidental-misuse controls, not a security sandbox or strong human identity.
  No cross-host or multiple-writer guarantee is made.
- PASS=0, actual assertion FAIL=1, missing/required-skip/zero-case BLOCKED=2,
  malformed/missing/contradictory evidence or timeout ERROR=3. Successful readonly
  status returns 0 even when its content shows pending acceptance.
- The real user generation → rejection → repair → acceptance milestone still
  requires that actual user and game session. It cannot be inferred from the
  fixed fixture or synthetic protocol tests. N06 React and N07 optional device
  work remain outside this implementation until that product gate is met.

# Recovery and Resume

GodotMaker is designed so you can stop after any `/gm-*` command and pick up later. This page explains how that works and what to do when something goes sideways.

---

## The basic resume mechanism

Every `/gm-*` skill starts by reading two things:

1. **`.godotmaker/stage.jsonl`** — an append-only log of completed roles. Each line looks like `{"role": "build", "ts": "2026-04-27T10:00:00Z"}`. The skill scans this to see which roles have run.
2. **Key output files** — for example, `/gm-build` checks that `PLAN.md` exists and reads task statuses; `/gm-fixgap` checks for `GAP.md`; `/gm-evaluate` checks for `.godotmaker/evaluation.json`.

If a role is already complete (the right entry exists in `stage.jsonl` and its outputs are present), the skill will tell you so and recommend the next command. If a prerequisite is missing, it will say exactly which role needs to run first.

You never need to remember where you left off — the skills figure it out from the files on disk.

---

## What `current_role` does

`.godotmaker/current_role` is a small text file containing the name of whichever role is active right now (e.g., `build`, `evaluate`). Every `/gm-*` skill writes its role name to this file as its very first action.

The hook system reads `current_role` on every file write to enforce write permissions — for example, blocking `/gm-build` from directly editing `.gd` files (that has to go through a Worker sub-agent), or blocking `/gm-evaluate` from touching anything outside `e2e/` and `.godotmaker/`.

When you start a new Claude Code session, `session_start.py` clears any stale value in `current_role`. This matters because a crashed session might have left a role name from a previous run — clearing it prevents the wrong permission rules from applying when you pick back up.

---

## Resuming an interrupted `/gm-build`

If you closed Claude Code mid-build:

1. Open a new Claude Code session in the game project folder.
2. Run `/gm-build`.

The skill will read `PLAN.md` and look at each task's status column:

- `pending` — not yet started; will be dispatched.
- `in_progress` — was being worked on when the session died; needs attention.
- `completed` — worker finished, but verifier/reviewer haven't run yet.
- `verified` — fully done; skipped.

If any tasks are stuck at `in_progress`, change them back to `pending` manually before running `/gm-build` — otherwise the skill might skip them assuming they are being handled by a live worker.

```bash
# Open PLAN.md in any text editor and change:
#   | in_progress | Task description |
# to:
#   | pending     | Task description |
```

Then run `/gm-build`. It will dispatch workers for `pending` tasks and a verifier/reviewer round for any `completed` tasks that weren't verified yet.

---

## Resuming an interrupted `/gm-fixgap`

`/gm-fixgap` works from `GAP.md`, which lives at the project root while an iteration is active. The resume logic:

- If `GAP.md` is at the project root — a fixgap iteration is in progress. Running `/gm-fixgap` will resume it.
- If `GAP.md` is absent from the project root (it has been moved to `.godotmaker/gaps/<n>/`) — the last fixgap finished. Running `/gm-fixgap` again will start a new iteration from the current `evaluation.json`.

To check which state you are in:

```bash
ls GAP.md 2>/dev/null && echo "fixgap in progress" || echo "no active fixgap"
```

If a fixgap was interrupted mid-task, apply the same `in_progress` → `pending` fix in `GAP.md` as described for `/gm-build` above.

---

## Restarting from scratch

If the project is in a genuinely broken state — missing files, contradictory `stage.jsonl` entries, or hooks blocking everything — run the project checker first to get a clear picture:

```bash
python tools/check_project.py <path-to-game>
```

This lists missing required files, stale role locks, and other common problems without changing anything.

**Before deleting or resetting anything:** make a git commit or backup of the current state. Most problems can be fixed by editing `PLAN.md` or `GAP.md` directly rather than starting over.

If you decide to restart a specific role (not the whole project), the safest approach is:

1. Remove the relevant entry from `.godotmaker/stage.jsonl` (edit the file, delete the line).
2. Delete the role's output files listed in `.godotmaker/stage_schemas.json` for that role.
3. Run the role's `/gm-*` command again.

Only consider a full project reset (deleting `src/`, `scenes/`, and `stage.jsonl`) if the codebase is irreparably broken and no useful code is worth keeping. This is rare.

---

## Re-running a role you already ran

Most roles are safe to re-run. A few have restrictions:

| Role | Re-runnable? | Notes |
|------|-------------|-------|
| `/gm-scaffold` | Once per project | Creates the Godot project structure and initial git commit. Running it again on an existing project will conflict with existing files. Do not re-run. |
| `/gm-gdd` | Yes | Re-interviews you and rewrites planning docs. Use this at the start of each new tag. |
| `/gm-asset` | Yes | Skips assets already present; only generates missing ones. |
| `/gm-build` | Yes | Resumes from the current `PLAN.md` state. |
| `/gm-verify` | Yes | Mechanical check; always safe to re-run. |
| `/gm-evaluate` | Yes | Overwrites `evaluation.json` with fresh results. |
| `/gm-fixgap` | Yes | Each run creates a new iteration under `.godotmaker/gaps/<n>/`. |
| `/gm-accept` | Yes | Shows current results and asks again. |
| `/gm-finalize` | Once per tag | Archives the tag's working docs and runs `git tag <Tag>`. Re-running on a sealed tag fails because the git tag already exists — if finalize was interrupted before sealing, run it once more; if you want to amend a sealed tag, open a new tag instead. |

After `/gm-finalize`, the next tag begins with `/gm-gdd` (not `/gm-scaffold`).

---

## When the AI is clearly drifting

In normal operation, hooks prevent most violations — wrong file writes are blocked, skipped steps are caught, and malformed reports are rejected. But if something looks off (the AI is ignoring your instructions, writing to places it shouldn't, or producing nonsensical output):

1. **Stop the session** — close Claude Code.
2. **Run the project checker:**

   ```bash
   python tools/check_project.py <path-to-game>
   ```

3. **Check recent metrics** — the `.godotmaker/` directory contains timestamped event logs:

   ```bash
   ls .godotmaker/metrics_*.jsonl
   ```

   Open the latest file and look for `HOOK_BLOCK` events — these show what was blocked and why. If you see unexpected blocks, that's a sign the role state is inconsistent.

4. **Clear `current_role`** if it looks stale:

   ```bash
   echo "" > .godotmaker/current_role
   ```

5. **Start a fresh session** and run the appropriate `/gm-*` command from the last clean state.

If the problem repeats across sessions, check `.godotmaker/config.yaml` for any model or setting overrides that might be affecting behavior, and verify that the installed GodotMaker version matches the repo with:

```bash
cat .godotmaker/version
cat <godotmaker-repo>/VERSION
```

If they differ, re-publish with `python tools/publish.py <target>`.

# Why this approach

GodotMaker is opinionated. This page explains the reasoning behind those opinions, so you understand the trade-offs and can decide if the tool fits your situation.

---

## Why 9 commands instead of one big run

The most obvious alternative would be a single command: describe your game, walk away, come back to a finished project. This sounds appealing but runs into practical problems.

**Context windows are limited.** An AI session has a maximum amount of text it can hold in "working memory" at once. A full game — design, code, tests, screenshots, review comments — easily exceeds that limit. When the context fills up, the AI starts dropping earlier information. That causes drift: later decisions contradict earlier ones, earlier requirements get forgotten.

**Long sessions accumulate assumptions.** Every decision made early in a session implicitly shapes every decision made later. In a single long run, mistakes early on get baked into everything that follows. Splitting into separate commands means each step starts fresh, with only the documents it actually needs.

**You stay in the loop.** Between each command, you can read what was produced, ask questions, edit a document, or redirect. A `/gm-gdd` that goes in the wrong direction can be corrected before the build starts, not after 40 minutes of generated code.

**Each role has its own permission boundary.** The evaluator cannot touch game code. The build step cannot claim approval. These constraints only work because each role is a separate session with its own set of allowed actions.

---

## Why hooks instead of trusting the AI

Hooks are small Python scripts that Claude Code runs automatically on specific events — a file is about to be written, a session is about to end, a session is starting. They enforce rules that the AI cannot override, even accidentally.

The alternative — relying on instructions in the prompt — is unreliable. A long enough session, a complex enough situation, and even a well-intentioned AI will drift from its instructions. Telling the AI "don't write game code while evaluating" is much weaker than having a script that physically blocks the write and returns an error.

Hooks are also cheap to audit. You can open `hooks/check_file_permissions.py` and read exactly what is allowed and what is not — 50 lines of straightforward Python. There is no ambiguity about what "the AI said it would do". The rule is in code.

Some of the key rules hooks enforce:

- You cannot write game code from the evaluator role.
- You cannot start `/gm-build` unless `/gm-gdd` has been completed.
- You cannot start `/gm-fixgap` unless `/gm-evaluate` has run since the last build.
- You cannot end a `/gm-build` session if workers ran but verifier and reviewer did not.
- A worker report that is too short or missing required sections is rejected outright.

These rules exist because experience shows the AI will sometimes try to take shortcuts under pressure — declaring success without running tests, skipping the reviewer when the context is getting long, writing a one-line report. Hooks catch all of these.

---

## Why sub-agents inside `/gm-build`

`/gm-build` does not write code directly. It dispatches Workers — focused helpers that each implement one game system and then report back. This design has three benefits.

**Parallel work.** Workers with non-overlapping files run at the same time, in separate git worktrees (think: separate working folders that share the same repository). Building the `MovementSystem` and the `HealthSystem` in parallel takes roughly half the time of doing them sequentially, and because each system has its own files, they cannot conflict.

**Narrow scope per worker.** Each Worker only sees the task brief and the files it needs. It does not have the whole PLAN.md or weeks of build history in its context. This keeps each Worker's session short, focused, and less likely to drift.

**Specialised review.** After workers complete a batch, a Verifier runs the build and tests (mechanical correctness), and then a Reviewer checks against domain-specific pitfalls — Godot physics constraints, UI layout rules, animation gotchas. These are separate agents with separate prompts specifically tuned for their job. A single agent trying to do all three roles at once would do each one less reliably.

The completion-check hook enforces the full cycle. Workers alone are not enough — verifier and reviewer must also run, or the build session cannot end.

---

## Why ECS specifically

Predictability is the core reason. When AI-written code follows ECS conventions, every system lives in `src/systems/`, every component lives in `src/components/`, and every system reads a defined set of components. A reviewer checking the physics code knows exactly where to look. A worker adding a new feature knows exactly which pattern to follow.

ECS also maps naturally to specialised review. GodotMaker has eight reviewer types: physics, animation, UI, tilemap, navigation, shader, audio, particles. Each knows the conventions and common mistakes for its domain. An ECS structure makes it easy to route a `PhysicsSystem` to the physics reviewer and a `UISystem` to the UI reviewer, without them needing to understand the whole codebase first.

For more about ECS and how it appears in the generated project, see [ecs-in-plain-english.md](ecs-in-plain-english.md).

---

## What we deliberately do not do

**No hidden background loop.** GodotMaker does not run while you are away. Nothing is being built, tested, or submitted in the background. Every step starts when you type a command and stops when the command finishes. You always know exactly what stage the project is at.

**No automatic progression.** The end of `/gm-build` does not automatically trigger `/gm-verify`. You type the next command. This is intentional — it gives you a moment to look at what was produced before moving on.

**No skipping acceptance.** `/gm-finalize` requires a recorded acceptance from `/gm-accept`. The evaluator approving is not enough on its own — you, the human, still have to confirm. Your game, your decision.

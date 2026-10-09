# v0.5 transition contract and local chain boundaries

## What changed

The bounded v2 wire version remains unchanged. A transition is a derived room-exit
configuration, not a new Godot scene, actor or editable global preset. The
snapshot contains an ID-keyed array:

```json
{"transitions":[{"id":"route:lobby:door-gallery","sourceExitRef":{"roomId":"lobby","exitId":"door-gallery"},"config":{"mode":"none"}}]}
```

`unset` means no explicit override; `none` explicitly disables the transition;
`preset` additionally requires exactly `presetId`, currently `black_fade` or
`mask_wipe`. A preset name is an editing contract, not proof of an installed
runtime effect. In particular, an unbound mask asset remains a preview-only
capability gap. This release rejects mask_wipe execution even with an explicit
runtime mapping; only read-only design proposals may discuss it. Source
references prove the door, not an implemented effect.

The derived route IDs and source-exit bindings must exactly match the server
adapter baseline. This submission may edit their configuration, not create,
delete or rewire source exits. New source structure requires a reviewed adapter
baseline. A malformed or unkeyed transition collection cannot fall back to a
whole-project target. Diff paths map `/transitions/<route-id>/...` to precisely
`transition:<route-id>`.

For a real v2 submission, a local owner must independently review the existing
`.godotmaker/workbench-targets.json` mapping. Its transition entry must bind:

- `kind: transition`, explicit `routeKind`, actual GM tag/mechanics/task IDs
- `rangeIntent: single-transition`
- `sourceExitRef: {roomId, exitId}`
- `targetEntryRef: {roomId, spawnId}`, derived from the actual door destination
- `sourceRefs`: the exact nonempty source-reference IDs inherited from that door
- Exact `allowedDiffPaths` and individually reviewed `allowedSourcePaths`

The submitted fields must equal the server mapping. The bridge independently
resolves the original door and target spawn from its adapter baseline and checks
the semantic catalog source references against the reviewed source manifest.
Matching forged browser and mapping references cannot replace these source facts.
Unknown routes, missing
references, forged destinations and wider paths are BLOCKED. The execution plan
retains the reviewed source binding. The mapping is trusted local reviewed
configuration; this is not an automatic universal source-code mapper.

## Necessary GM writes remain explicitly bounded

The existing `allowedSourcePaths` field grants individual file paths, including
necessary workflow files. It never grants a directory, wildcard, traversal,
noncanonical path or an artifact excluded from the controlled audit. For
example, a reviewed task may need `.godotmaker/current_role`,
`.godotmaker/verify_report.json`, its game files, unit tests and `PLAN.md` status
updates. These are examples, not a default authorization list. Enumerate only
what the actual task and original GM role require.

No new broad GM exemption is introduced. Role separation remains mandatory;
allowing a file does not let a worker take ownership of it. A permitted PLAN
status update does not permit normative specification changes: the exact spec
digest must remain unchanged. Unknown document/configuration/skill changes still
reject evidence import. Final-state hashes cannot detect transient changes that
were reverted and are not an operating-system sandbox.

## Evaluator test preparation is a separate reviewed phase

New feature e2e scenarios must be authored by the Evaluator during an explicitly
authorized preparation phase, with their assertion intent reviewed against the
new feature specification. Then establish a fresh server-controlled source/test/
configuration baseline and exact specification confirmation before the bounded
implementation submission. Those prepared tests remain immutable in that
submission. Necessary later test changes require another properly authorized
Evaluator review and baseline, not an invented `test_error` feedback record.

The existing `test_error` route is retained only for genuine formal-check test
errors with its original feedback provenance and authorization. Workers still
cannot write `e2e/`. A baseline fixture or unchanged checksum is not evidence
that the feature passed its tests.

## Where automation currently ends

1. Frontend edits remain browser drafts. Confirming an unchanged frozen preview
   sends a durable submission through the same-origin local bridge.
2. In real Codex mode, the bridge resumes the exact bound thread/cwd and sends
   `turn/start` with the submission in `toolOutput`. This needs an installed
   compatible experimental app-server schema. Thread completion and text are
   collected automatically; the bridge does not directly execute GM skills.
3. A real model turn must demonstrate loading the Codex runtime mapping,
   explicitly invoking the appropriate GM skill and preserving independent
   worker/verifier/Evaluator roles. Skills being listed is insufficient proof.
4. Godot resources need verified clean import, then actual runtime checks.
   Headless tests do not establish rendering, physical input, Web persistence or
   human experience. A room transition surrounds the existing JSON-room/ECS
   rebuild, not an assumed `SceneTree.change_scene` call.
5. Formal evidence is imported by a local operator using the existing
   `--import-result` command after stopping the bridge. There is no automatic
   run discovery, browser evidence endpoint or automatic source merge.
6. Import independently checks run/report identity and scope, but target-level
   implementation and assertion coverage remain BLOCKED. A matching report,
   global PASS, changed allowed file or verified historical task is insufficient.
7. Source re-extraction, adapter review, mapping update and baseline generation
   are explicit. The Velvet extractor contains reviewed hardcoded anchors and
   facts; refreshing hashes alone cannot parse arbitrary new functionality.
   Never silently replace a newer browser draft with execution results.

## First real local sample and stopping rules

Prefer the local 1B deployment: same local project, compatible installed Codex,
idle existing thread, loopback bridge and local browser. The private hosted Site
remains a simulation and cannot automatically reach a user's local project.
Current bridge locking uses `fcntl`; native Windows parity is not established.
Keep the original validated Godot/dependency versions for the first trial;
doctor version/module probes alone do not establish full runtime compatibility.

Use one exit and one simple black fade after design/specification and test
preparation. Validate covering before room replacement, maintaining cover while
loading, no duplicate transition, player/HP/ability/checkpoint preservation,
camera placement, input and AI restoration, disabled/zero-duration behavior and
failure/interruption recovery without permanent black screen. Capture actual
visible frames; a UI timing demonstration is not this evidence.

Stop on unknown scope, changed authority, unavailable required capabilities,
missing actual resource, denied permission, uncertain delivery, missing required
test/visual evidence or missing human confirmation. Native Codex permissions
remain in force; the bridge never grants approvals. GM specification confirmation,
experience acceptance and feedback resolution keep their actual local-interactive
TTY boundaries. A Submit click, an agent's text or generated TTY input cannot
replace the user.

## Verification of this patch

Python regression tests exercise the actual contract/diff/execution-plan code,
including positive and negative transition bindings. Temporary files produce
real controlled inventories to test individually permitted GM artifact updates,
unreviewed configuration rejection and immutable pre-baselined Evaluator tests.
The evidence-import fixtures supply selected formal-run facts; they are not real
GM run evidence and cannot certify live integration. Full Codex→GM→Godot, runtime
resource import, visible play and human acceptance still require local validation.

# Local Game Studio backend

The service hosts the same-origin Studio API and composes the legacy collect-loop workflow with the new `objects-v1` object-based 2D workflow. The authoritative Chinese deployment and user documentation is in [`docs/`](../docs/README.zh-CN.md), including the current capability and verification limits.

A generic project uses a read-only planning session, an explicit user review of the complete object plan, a separate implementation session, and backend-owned technical verification. The object protocol carries stable IDs, typed fields, relations, source bindings, and user acceptance requirements. Current generic production scope is Godot 4, 2D, GDScript, text scenes/resources, and PNG/JPEG/WebP assets.

The verifier runs a fresh temporary import and backend-owned main-scene smoke harness. It does not execute producer-selected tests or infer gameplay acceptance from a successful launch. The isolated native probe at [`evidence/workflow/general/real-object-probe-r3.json`](../evidence/workflow/general/real-object-probe-r3.json) records two distinct non-collect game builds, Godot 4.6.3 import/runtime-smoke passes, and a targeted player iteration changing speed from 220 to 300 px/s with cyan visual feedback. Follow-up fixture-specific viewport probes passed for Bridge Runner and Light Grid; see [`bridge-gameplay-repaired-r2.json`](../evidence/workflow/general/bridge-gameplay-repaired-r2.json), [`puzzle-gameplay.json`](../evidence/workflow/general/puzzle-gameplay.json), and the [`reset-feedback-probe.json`](../evidence/workflow/general/reset-feedback-probe.json) session record. The Bridge Runner defect was that after winning, pressing R teleported the player to spawn but stale exit contact immediately returned the state to WON; its repaired source is `b4d535762b38dbb932c886c4e46db10972d4c762`. These probes are test-only (`testData=true`, `productionAuthorized=false`) and explicitly report `humanAcceptance=NOT PERFORMED`; they do not satisfy gameplay requirements for general production candidates or constitute user approval. Execution remains cooperative local same-user processing without an OS sandbox.

New projects use `objects-v1`; existing collect-loop projects retain their original workflow and approvals. There is no automatic approval migration. The server is local-only and binds to `127.0.0.1`.

Start from the repository root:

```sh
.venv/bin/python -m backend.server --port 8765
```

Open `http://127.0.0.1:8765/studio/`. See the [deployment manual](../docs/DEPLOYMENT-MANUAL.zh-CN.md) for setup, state management, backup, recovery, and troubleshooting.

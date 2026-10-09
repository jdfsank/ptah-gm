# v0.3 frontend validation

- Source: user-provided dna-local-workbench-v0.3(1).zip, React 19 shell.
- `npm run build`, `npm run check`: pass.
- Existing DOM/semantic/React checks: 41 pass.
- Python store/protocol/security tests: 24 pass, no live model or engine.
- Hosted browser-local simulation DOM integration: passes theme, scoped notes,
  typed edit freeze, immediate receipt, double-click block, reload recovery,
  retained notes/theme, and zero fetch/model calls.
- Mobile CSS: existing responsive rules preserved; shell stacks at 450 px,
  controls have 44 px minimum height. Rendered mobile testing NOT completed.
- Real-browser limitation: a static localhost service responds HTTP 200 within
  its own execution shell, but separate shell/cloud browser connections are
  refused. Supported elevated launch encounters a platform sandbox mount error.
  No sites-preview executable or managed-linux profile is present.
- No real Codex/Godot execution, writeback or model use was performed.
- Publication retains the existing owner-only audience.

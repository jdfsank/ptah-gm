# Local execution policy

Strictly forbidden hash check at building.

The user explicitly authorized Git to replace SHA checks. Use Git commits,
scoped inventories, native object identities and diffs for the active local
build/review workflow. Do not invoke standalone SHA/MD5 checks or the legacy
package checksum helpers as a build prerequisite.

Read `LOCAL-SETUP-GIT.zh-CN.md` for the installed Godot path and migrated
metadata. Fields historically named `*_digest` / `report_digests` now carry
Git identities; active run metadata uses `manifest.git` and
`evaluation-binding.git`. Historical SHA manifests, source ZIPs and old
documentation examples remain provenance, not current build instructions.

The reviewed frontend source still differs from the delivered game in
`scripts/ui/hud.gd` and `scripts/ui/title_screen.gd`. Preserve these rejection
checks until their source/adapter differences are explicitly reviewed. Git
migration does not grant new gameplay scope or replace required human decisions.

# Default Godot MCP installation

For every new Godot project created by this repository, install the bundled
`addons/godot_mcp` and enable `res://addons/godot_mcp/plugin.cfg` by default.
Both backend templates include the bundle. For projects created through another
scaffolding path, use `tools/godot_project_ready.py --install` and follow
`docs/GODOT-MCP.zh-CN.md`. Preserve existing plugins and reject conflicting addon
contents instead of overwriting them. Do not copy the source project's caches,
MCP settings, or credentials.

The standard production path is create/materialize the Godot project → verify
the bundled enabled addon → start an isolated ordinary editor → initialize MCP
and verify exact project identity → confirm editor termination → dispatch the
producer. Run `tools/godot_project_ready.py --install` for new scaffold projects
with a unique `--evidence-dir` outside the project. Every initial production,
repair and parameter iteration requires a fresh readiness PASS; installed files
or a recovery-mode import alone do not meet this gate. The trusted AgentRunner
and retained local workflows enforce it before starting the production model.
Missing/disabled/conflicting addons, timeout or unconfirmed cleanup prevent
dispatch. Keep the source project unchanged during the probe.

The editor MCP is a trusted operator control channel. It does not grant managed
planning/production agents access to Godot execution, backend data, or provider
authentication. Keep the addon outside producer write scope and retain the
independent verification sandbox and role capability gates.

# Persistent Studio replication objective

The complete, user-confirmed Studio legacy workbench replication scope lives in
`docs/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.zh-CN.md`. Its verbatim persistent
acceptance baseline is
`docs/acceptance/STUDIO-LEGACY-WORKBENCH-REPLICATION-GOALS.full.zh-CN.md`.
Preserve both documents in full; implementation plans and progress reports must
not narrow or replace them. Follow plan → execute → verify/evaluate steps and
continue until the full scope works in real-user checks through kimi-webbridge.
Verification/evaluation is not user acceptance. Record uncovered capabilities
and real execution evidence honestly; fixture/static checks do not prove real
Agent completion. Prefer GPT-6.1 Sol high for planning/evaluation and GPT-6 Luna
max for execution. Do not add standalone hash checks to builds.

# Addon Installation

Every GodotMaker project requires these dependencies.
Install them after scaffold, before running headless-build or tests.

## Version Compatibility — MANDATORY

Read the active runtime's `config/addon_versions.json` to determine the
correct version for each addon:

- Claude Code: `.claude/config/addon_versions.json`
- Codex: `.agents/config/addon_versions.json`
- OpenCode: `.opencode/config/addon_versions.json`

The JSON maps Godot versions to compatible addon versions. You MUST use the
exact tag specified.

**Steps:**
1. Detect Godot version: `godot --version` (e.g., "4.4.stable")
2. Extract major.minor (e.g., "4.4")
3. Look up the matching entry in `addon_versions.json` → `godot_versions["4.4"]`
4. For each addon, download the exact `tag` from the `repo`

If the Godot version is not in the mapping, use the closest lower version. If no match exists, report to the user — do NOT guess versions.

## Download Method

For each addon in the version mapping, install the addon-only directory:

```bash
# Clone specific tag outside addons/, copy addon subdirectory, clean up.
git clone --depth 1 --branch {tag} https://github.com/{repo}.git .godotmaker/scratch/{addon_name}
cp -r .godotmaker/scratch/{addon_name}/{install_path}/ {install_path}/
rm -rf .godotmaker/scratch/{addon_name}
```

Required copy sources:

- `addons/gecs/` from the source repo's `addons/gecs/`
- `addons/gdUnit4/` from the source repo's `addons/gdUnit4/`
- `addons/godot_e2e/` from the source repo's `addons/godot_e2e/`

Do not clone the full source repository directly into `addons/gecs/`,
`addons/gdUnit4/`, or `addons/godot_e2e/`.

After copying each addon:

1. Confirm `plugin.cfg` exists in the copied addon root.
2. Confirm `project.godot` does not exist in the copied addon root.
3. For gdUnit4, confirm `bin/GdUnitCmdTool.gd` and
   `src/core/runners/GdUnitTestCIRunner.gd` exist.

## Post-Download Configuration

Append these mapped plugin paths to the existing `editor_plugins.enabled`
array. Keep `res://addons/godot_mcp/plugin.cfg` and any other existing entries.

### gecs (ECS Framework)

If `"plugin": true` in the mapping:
- Add to `[editor_plugins]` in project.godot:
  ```
  [editor_plugins]
  enabled=PackedStringArray("res://addons/godot_mcp/plugin.cfg", "res://addons/gecs/plugin.cfg")
  ```

### gdUnit4 (Test Framework)

If `"plugin": true` in the mapping:
- Add to `[editor_plugins]` in project.godot:
  ```
  enabled=PackedStringArray("res://addons/godot_mcp/plugin.cfg", "res://addons/gecs/plugin.cfg", "res://addons/gdUnit4/plugin.cfg")
  ```

### godot-e2e (E2E Testing)

If `"plugin": true` in the mapping:
- Add to `[editor_plugins]` in project.godot alongside gecs and gdUnit4:
  ```
  enabled=PackedStringArray("res://addons/godot_mcp/plugin.cfg", "res://addons/gecs/plugin.cfg", "res://addons/gdUnit4/plugin.cfg", "res://addons/godot_e2e/plugin.cfg")
  ```

Ensure `AutomationServer` is registered once in `[autoload]`:

```
AutomationServer="*res://addons/godot_e2e/automation_server.gd"
```

## Bundled Godot MCP Editor Addon (Default)

Every new project created by this repository's `gm-scaffold` or
`project-scaffold` path installs the project-local editor addon from the
canonical `addons/godot_mcp/` bundle. The scaffold skill invokes
`tools/godot_project_ready.py --install` after writing the project files; the script path is
resolved from the canonical source skill location, not from the shell's current
working directory. Do not add this local bundle to `addon_versions.json`: that
configuration is for version-pinned downloads from upstream repositories.

The installer enables `res://addons/godot_mcp/plugin.cfg` and preserves other
enabled plugins. The standard command then starts a disposable ordinary editor,
checks MCP initialization/tools and exact project identity, confirms unchanged
source and stops the editor. Require a fresh PASS report before production;
use a new evidence directory outside the project via `--evidence-dir`. Do not manually copy another source tree into `addons/`.

## Optional `@coding-solo/godot-mcp` Runtime Server

This npm package is a separate runtime debugging server registered with Claude
Code. It is optional and does not install or replace the project-local Godot
MCP editor addon above.

```bash
claude mcp add godot -e GODOT_PATH="<path_to_godot_executable>" -- npx @coding-solo/godot-mcp
```

Run this only when the user also wants this optional client runtime server.

## Verification

After all addons are installed:

```bash
godot --headless --quit 2>&1
```

No `SCRIPT ERROR:` lines means success. Common errors:
- `World` class not found → gecs not installed or not enabled
- `GdUnitRunner` error → gdUnit4 version mismatch with Godot version
- `GdUnitTestCIRunner` not found -> reinstall the gdUnit4 addon-only
  directory and run `godot --headless --import`
- `AutomationServer` error → godot-e2e plugin not enabled or addon files missing

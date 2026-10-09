# Shared reference docs

Reference docs consumed by more than one skill (e.g. `worker-dispatch.md`,
used by both `gm-build` and `gm-fixgap`) are kept in `skills/core/_shared/`
as a single source of truth. At publish time, `publish_shared_refs()` reads
`_shared/manifest.json` and writes each `_shared/<file>` into
`<consumer-skill>/references/<file>`. Deployed skills are therefore
self-contained — there is no `.claude/skills/_shared/` at runtime.

`_shared/` itself is excluded from `publish_skills()`: any
`skills/core/<dir>` whose name starts with `_` is skipped.

## manifest.json schema

```json
{
  "_doc": "...short description of the mechanism...",
  "files": {
    "<filename>.md": ["<consumer-skill-1>", "<consumer-skill-2>"],
    ...
  }
}
```

- Every key under `"files"` must be a bare filename (no `/`).
- Every value is a list of skill directory names under `skills/core/` that
  should receive a copy.

## Adding a new shared doc

1. Create `skills/core/_shared/<file>.md` with the shared content.
2. Add the entry to `_shared/manifest.json` under `"files"`:
   `"<file>.md": ["<consumer-skill-1>", "<consumer-skill-2>"]`
3. In each consumer `SKILL.md`, reference the doc as `references/<file>.md`
   — the **deployed** path. Do NOT write `_shared/<file>` or
   `.claude/skills/_shared/<file>`; those don't exist at runtime.
4. Run `python -m pytest tests/tools/test_publish_shared.py -q` to verify
   that the manifest is valid and every consumer SKILL.md uses the deployed
   path.
5. Optionally run `python tools/publish.py <test-dir>` to confirm files
   land in `<test-dir>/.claude/skills/<consumer>/references/<file>.md`.

## Removing a shared doc or a consumer

- **Removing a doc:** delete `_shared/<file>.md`, remove its entry from
  `manifest.json`, and remove every `references/<file>` mention from the
  consumer SKILL.md files.
- **Removing one consumer:** drop that skill name from the file's array in
  `manifest.json` and remove the `references/<file>` mention from that
  skill's SKILL.md.
- After either, re-run the test above.

## Editing rules

- Edit shared docs only at `skills/core/_shared/<file>`. Deployed copies
  under `<skill>/references/` carry an `<!-- AUTO-GENERATED -->` header —
  do not edit them; changes are overwritten on every publish.
- Per-skill private references (e.g. `gm-asset/references/visual-target.md`,
  `gm-asset/references/asset-planner.md`) live directly under that skill and
  do NOT carry the AUTO-GENERATED header. No manifest entry is needed;
  private refs are deployed by `publish_skills()` along with the rest of
  the skill.
- Tell shared from private at a glance by looking for the AUTO-GENERATED
  header at the top of the file.

## Debugging publish failures

- `FileNotFoundError: _shared/manifest.json references X, but source file
  does not exist` → the manifest names a file that isn't in `_shared/`.
  Add the source file or remove the manifest entry.
- `FileNotFoundError: _shared/manifest.json maps X -> Y, but skill
  directory Y does not exist` → typo in skill name, or the consumer skill
  was renamed/deleted. Fix the manifest entry.
- `ValueError: Invalid JSON in _shared/manifest.json` → JSON syntax error.
  Validate with any JSON linter; the message includes line and column.

## What the tests enforce

`tests/tools/test_publish_shared.py` covers:

- every file listed in the manifest exists in `_shared/`
- every consumer skill named in the manifest exists under `skills/core/`
- every consumer SKILL.md references its shared docs via `references/<file>`
  (no leftover `orchestrator/<file>` or other legacy paths)
- no consumer SKILL.md mentions the bare filename without the
  `references/` prefix
- deployed copies carry the `<!-- AUTO-GENERATED -->` header
- invalid manifest JSON raises `ValueError` with the manifest path in the
  message

"""Rename `addons/gdunit4/` -> `addons/gdUnit4/` to match upstream casing.

Earlier `config/addon_versions.json` set `install_path: "addons/gdunit4"`
(lowercase), which made `gm-scaffold`'s install copy land in a directory
that does not match the upstream repo layout (`addons/gdUnit4/`, capital
U on every tag of MikeSchulze/gdUnit4 that we pin: v5.1.1, v6.1.0).

Windows is case-insensitive so the verify command `addons/gdUnit4/bin/
GdUnitCmdTool.gd` resolved fine even though the directory was actually
named `gdunit4/` on disk. But Godot's global script class registry
de-duplicates by exact path string -- the same source file reached via
`addons/gdunit4/...` and `addons/gdUnit4/...` registers each class
twice, producing `Class "GdUnitAssertImpl" hides a global script class`
parse errors and a non-zero godot exit (2026-05-09 e2e on
GodotMakerTest1).

This migration:
  - Renames `addons/gdunit4/` (any non-capital-U casing) -> `addons/gdUnit4/`.
    On case-insensitive filesystems (Windows / default macOS), pathlib's
    rename of `foo` -> `Foo` is a no-op, so the rename goes via a
    non-clashing tmp name (`addons/gdunit4__migrating__/`) first.
  - Rewrites the `enabled=PackedStringArray(...)` line in `project.godot`
    to use `res://addons/gdUnit4/plugin.cfg` instead of any non-capital-U
    casing.

Idempotency: every step inspects the current state and skips if already
correct. Re-running on an already-migrated project is a no-op.
"""
import re
from pathlib import Path

ADDONS_DIRNAME = "gdUnit4"
TMP_DIRNAME = "gdunit4__migrating__"


def migrate(target: Path) -> None:
    """target is the absolute path to the game project root."""
    if _rename_addon_dir(target):
        print(f"  [done] rename addons/<lowercase>/ -> addons/{ADDONS_DIRNAME}/")
    else:
        print(f"  [skip] addons/{ADDONS_DIRNAME}/ already at expected casing or absent")

    if _rewrite_project_godot(target):
        print("  [done] rewrite project.godot enabled=PackedStringArray(...) to capital-U casing")
    else:
        print(f"  [skip] project.godot already references {ADDONS_DIRNAME}/ (or no plugin entry)")


def _rename_addon_dir(target: Path) -> bool:
    """Returns True iff a rename actually happened.

    Reads literal stored directory names via iterdir() rather than
    Path.exists()/is_dir() lookups, because case-insensitive filesystems
    (Windows / default macOS) treat `addons/gdunit4` and `addons/gdUnit4`
    as the same path -- we need the literal casing the OS stored at
    creation time, not the caller-typed lookup name.
    """
    addons = target / "addons"
    if not addons.is_dir():
        return False

    names = {p.name for p in addons.iterdir() if p.is_dir()}
    canonical_present = ADDONS_DIRNAME in names
    tmp_present = TMP_DIRNAME in names
    existing_name = next(
        (n for n in names if n.lower() == "gdunit4" and n != ADDONS_DIRNAME),
        None,
    )

    canonical = addons / ADDONS_DIRNAME
    tmp = addons / TMP_DIRNAME

    # Recovery: a previous run crashed after step-1 rename. Finish it.
    if tmp_present and not canonical_present and existing_name is None:
        tmp.rename(canonical)
        return True

    if existing_name is None:
        # Either already canonical or no addon directory at all.
        return False

    if canonical_present:
        # Case-sensitive FS only: two literally distinct dirs coexist.
        # Bail rather than guess which to keep.
        print(
            f"  [warn] both {existing_name}/ and {ADDONS_DIRNAME}/ exist under "
            f"addons/ -- skipping rename to avoid clobber. Resolve manually."
        )
        return False

    if tmp_present:
        # Half-finished previous attempt PLUS a fresh non-canonical dir
        # is ambiguous -- can't tell which is authoritative.
        print(
            f"  [warn] {TMP_DIRNAME}/ leftover alongside {existing_name}/ -- "
            f"resolve manually before re-running migrate."
        )
        return False

    # Normal two-step rename so case-only renames work on case-insensitive FSes.
    (addons / existing_name).rename(tmp)
    tmp.rename(canonical)
    return True


# Match `res://addons/<gdunit4-casing>/` followed by any path tail. We
# look for the directory token only -- the trailing slash is a lookahead
# so the substitution is a clean prefix swap, leaving whatever path
# segment follows (plugin.cfg, bin/GdUnitCmdTool.gd, autoload script
# paths, [autoload]/[input] script_class_icons references, ...) intact.
# Limiting to lowercase variants avoids touching the canonical capital-U
# spelling on re-runs.
_ADDON_REF_RE = re.compile(r'res://addons/(?![gG]dUnit4/)([gG][dD][uU][nN][iI][tT]4)(?=/)')


def _rewrite_project_godot(target: Path) -> bool:
    """Rewrite any `res://addons/<non-canonical-casing>/...` reference
    in project.godot to use the canonical `res://addons/gdUnit4/...`.
    Covers `[editor_plugins]` plugin.cfg paths but also `[autoload]`,
    `[input]` script_class_icons, or any other section that may carry
    a path string into the addon directory.

    Returns True iff the file was modified.
    """
    project_file = target / "project.godot"
    if not project_file.is_file():
        return False

    original = project_file.read_text(encoding="utf-8")
    new_text = _ADDON_REF_RE.sub(f"res://addons/{ADDONS_DIRNAME}", original)
    if new_text == original:
        return False

    project_file.write_text(new_text, encoding="utf-8", newline="\n")
    return True

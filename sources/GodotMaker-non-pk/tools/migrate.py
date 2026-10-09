#!/usr/bin/env python3
"""Version migration runner for GodotMaker publish upgrades.

Migrations are timestamped scripts under `migrations/` that rewrite something
in an existing target project (path fixes, schema changes, file renames,
etc.). Each script is identified by its full filename stem:

    migrations/20260429100000_fix_state_path.py
    → ID = "20260429100000_fix_state_path"

The mechanism is decoupled from GodotMaker's MAJOR.MINOR.PATCH version. A
target project records which migration IDs it has applied in
`.godotmaker/applied_migrations.json`; on each publish, any IDs found on
disk but not in that file are executed in chronological order.

Fresh installs (and MAJOR `--force` re-inits) baseline instead — they mark
all current migrations as applied without running them, since they start
with the latest format and have nothing to migrate from.

Usage:
    python tools/migrate.py <target>              # apply pending migrations
    python tools/migrate.py <target> --baseline   # mark all as applied (no-run)
    python tools/migrate.py --new <slug>          # scaffold a new migration

Typically called from publish.py, not directly.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
APPLIED_FILE_REL = Path(".godotmaker") / "applied_migrations.json"

# Filenames look like: 20260429100000_fix_state_path.py
MIGRATION_RE = re.compile(r"^(\d{14})_([a-z0-9_]+)\.py$")

VALID_SOURCES = {"baseline", "executed"}


class AppliedEntry(TypedDict):
    """One row in applied_migrations.json's `applied` list.

    `source` is a closed enum (`baseline` or `executed`) — narrowed via
    `Literal` so the public type matches the runtime validation in
    `_validate_entry`. The distinction has no behavioural effect — both
    values count as applied — but is useful when diagnosing tracker
    history.
    """
    id: str
    applied_at: str
    source: Literal["baseline", "executed"]


class AppliedTracker(TypedDict):
    """Top-level shape of `.godotmaker/applied_migrations.json`."""
    applied: list[AppliedEntry]


class TrackerCorruptionError(Exception):
    """Raised when applied_migrations.json exists but is unreadable / malformed.

    Distinct from a missing file (which is a legitimate "fresh tracker"
    state). Silent fallback to "empty applied" would re-run every
    historical migration on the next publish — surface the corruption
    explicitly instead.
    """


# ── Filename / discovery ──────────────────────────────────────────


def parse_migration_filename(name: str) -> str | None:
    """Extract the migration ID (full filename stem) from a script filename.

    The ID is the filename without the `.py` extension —
    `20260429100000_fix_state_path.py` → `20260429100000_fix_state_path`.
    Two scripts created in the same UTC second still produce distinct IDs
    because the slug component differs. Returns None for filenames that
    do not match the convention (e.g. `README.md`, `_helpers.py`).
    """
    if MIGRATION_RE.match(name) is None:
        return None
    return name[:-3]


_LEGACY_PAIR_RE = re.compile(r"^\d+\.\d+_to_\d+\.\d+$")


def discover_migrations() -> list[Path]:
    """All valid migration scripts under MIGRATIONS_DIR, sorted chronologically.

    Lexicographic sort is sufficient because the leading 14-digit timestamp
    is fixed-width and high-order-first (YYYYMMDDhhmmss).

    Also emits a stderr warning for any pre-refactor `0.X_to_0.Y/`
    directory found — those are silently ignored by this discovery scan,
    which would mean any V scripts trapped inside them never run. The
    warning gives downstream forks who haven't migrated their layout an
    explicit signal instead of a silent skip.
    """
    if not MIGRATIONS_DIR.is_dir():
        return []
    for p in MIGRATIONS_DIR.iterdir():
        if p.is_dir() and _LEGACY_PAIR_RE.match(p.name):
            print(
                f"  WARNING: legacy migration directory {p.name}/ found "
                f"under {MIGRATIONS_DIR}. The pre-refactor minor-pair "
                f"layout is no longer recognised; any scripts inside "
                f"will be silently skipped. Rename them to flat "
                f"<YYYYMMDDhhmmss>_<slug>.py files directly under "
                f"migrations/ to restore execution.",
                file=sys.stderr,
            )
    files = [
        p for p in MIGRATIONS_DIR.iterdir()
        if p.is_file() and parse_migration_filename(p.name) is not None
    ]
    return sorted(files)


# ── Applied tracking (.godotmaker/applied_migrations.json) ────────


def _now_iso() -> str:
    """Current UTC time as ISO-8601 with second precision and trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_entry(entry: object, index: int, path: Path) -> None:
    """Strict validation of a single applied-tracker entry.

    Raises TrackerCorruptionError on any deviation from the AppliedEntry
    shape. The on-disk file is a contract — partial / unknown shapes are
    not silently accepted.
    """
    if not isinstance(entry, dict):
        raise TrackerCorruptionError(
            f"{path}: entry [{index}] is not a JSON object"
        )
    for key in ("id", "applied_at", "source"):
        if key not in entry:
            raise TrackerCorruptionError(
                f"{path}: entry [{index}] missing required field {key!r}"
            )
        if not isinstance(entry[key], str):
            raise TrackerCorruptionError(
                f"{path}: entry [{index}] field {key!r} must be a string"
            )
    if entry["source"] not in VALID_SOURCES:
        raise TrackerCorruptionError(
            f"{path}: entry [{index}] field 'source' must be one of "
            f"{sorted(VALID_SOURCES)}, got {entry['source']!r}"
        )


def read_applied(target: Path) -> AppliedTracker:
    """Read applied_migrations.json with strict validation.

    Missing file → returns an empty tracker (legitimate fresh state).
    Any other error (invalid JSON, wrong top-level shape, malformed
    entry, unknown source value) → raises TrackerCorruptionError so the
    caller can surface it instead of silently fallback-and-replay-history.
    """
    f = target / APPLIED_FILE_REL
    if not f.exists():
        return {"applied": []}

    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        # UnicodeDecodeError matters specifically for Windows PowerShell 5.1
        # users: its `echo > file` writes UTF-16 LE with BOM by default,
        # which f.read_text(encoding="utf-8") cannot decode. We surface the
        # corruption rather than crashing with a raw decode traceback.
        raise TrackerCorruptionError(
            f"{f}: cannot parse JSON ({e}). Recover from VCS, "
            f"run `python tools/migrate.py <target> --baseline` to restart "
            f"tracking from the current state, or delete the file to treat "
            f"as a legacy target."
        ) from e

    if not isinstance(data, dict):
        raise TrackerCorruptionError(
            f"{f}: top-level JSON must be an object, "
            f"got {type(data).__name__}"
        )
    applied = data.get("applied")
    if not isinstance(applied, list):
        raise TrackerCorruptionError(
            f"{f}: 'applied' must be a list, "
            f"got {type(applied).__name__}"
        )
    for i, entry in enumerate(applied):
        _validate_entry(entry, i, f)

    return {"applied": applied}


def write_applied(target: Path, data: AppliedTracker) -> None:
    """Atomically write applied_migrations.json.

    Writes to a sibling `<file>.tmp` then `os.replace()` to swap into
    place, so an interrupted write cannot leave a truncated JSON file
    that read_applied would treat as corruption (and it cannot leave
    a partial JSON that an even-more-permissive parser would treat
    as empty applied).
    """
    f = target / APPLIED_FILE_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def applied_ids(data: AppliedTracker) -> set[str]:
    """Set of migration IDs already recorded as applied.

    Assumes `data` is a validated AppliedTracker (i.e. came from
    read_applied or was constructed in-process). No additional
    permissiveness — every entry must have an `id`.
    """
    return {entry["id"] for entry in data["applied"]}


# ── Baseline (fresh install / MAJOR re-init) ──────────────────────


def baseline_applied(target: Path) -> int:
    """Mark every current migration as applied without executing it.

    Used on fresh install and after MAJOR `--force` re-init: the target
    starts at the latest format, so there is nothing to migrate from.
    Returns the number of migrations baselined.
    """
    migrations = discover_migrations()
    timestamp = _now_iso()
    entries: list[AppliedEntry] = []
    for m in migrations:
        mid = parse_migration_filename(m.name)
        assert mid is not None  # guaranteed by discover_migrations() filter
        entries.append({
            "id": mid,
            "applied_at": timestamp,
            "source": "baseline",
        })
    write_applied(target, {"applied": entries})
    return len(migrations)


# ── Single-script execution ───────────────────────────────────────


def run_migration_script(script_path: Path, target: Path) -> bool:
    """Load and execute one migration script.

    The script must define a `migrate(target: Path) -> None` function.
    Returns True on success, False on failure (with reason printed).
    """
    migrations_root = str(MIGRATIONS_DIR)
    if migrations_root not in sys.path:
        sys.path.insert(0, migrations_root)

    try:
        spec = importlib.util.spec_from_file_location(
            f"migration_{script_path.stem}", str(script_path)
        )
        if spec is None or spec.loader is None:
            print(f"  [error] Cannot load {script_path.name}")
            return False

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "migrate"):
            print(f"  [error] {script_path.name} has no migrate() function")
            return False

        module.migrate(target)
        return True

    except Exception as e:
        print(f"  [error] {script_path.name} failed: {e}")
        return False


# ── Pending application ───────────────────────────────────────────


def run_migrations(target: Path) -> bool:
    """Apply all pending migrations (those on disk but not yet recorded).

    Legacy target handling — a target that has `.godotmaker/version` but
    no `applied_migrations.json` (created by a pre-tracking GodotMaker
    version) splits into two cases, both auto-handled:

    - **No migrations on disk:** bootstrap an empty tracker. The release
      that introduces applied-tracking should ship with empty
      `migrations/` so legacy targets land here on first contact and
      become "tracked but with zero applied", which makes subsequent
      releases proceed normally through the pending-application path.

    - **Migrations exist on disk:** auto-bootstrap an empty tracker and
      fall through to the pending-application path. By construction, a
      target stamped at `.godotmaker/version` from a pre-tracking release
      pre-dates every migration in `migrations/` (those scripts shipped
      with the same release that introduced tracking, or later), so they
      cannot have been applied to it. The opt-out for the rare hand-applied
      case is `python tools/migrate.py <target> --baseline`, which marks
      every migration as applied without executing — left as a separate
      path so silent re-execution of an already-applied migration cannot
      happen by accident.

    Each successful script is recorded immediately, so a mid-chain failure
    leaves a clean partially-applied state for the next re-run.

    Returns True on success (including no-op), False if any script failed.
    Raises TrackerCorruptionError if applied_migrations.json exists but
    cannot be parsed / validated.
    """
    applied_file = target / APPLIED_FILE_REL
    version_file = target / ".godotmaker" / "version"
    is_legacy = not applied_file.exists() and version_file.exists()
    migrations = discover_migrations()

    if is_legacy:
        write_applied(target, {"applied": []})
        if migrations:
            print(f"  Legacy target detected — auto-created empty applied "
                  f"tracker; {len(migrations)} pending migration(s) will "
                  f"run below. (Use `python tools/migrate.py <target> "
                  f"--baseline` instead if you applied them by hand.)")
            # fall through to the pending-application path
        else:
            print("  Bootstrapped empty applied tracker for legacy target "
                  "(no migrations on disk).")
            return True

    if not migrations:
        return True

    data = read_applied(target)
    already = applied_ids(data)
    pending = [
        m for m in migrations
        if parse_migration_filename(m.name) not in already
    ]

    if not pending:
        return True

    print(f"\n  Running {len(pending)} pending migration(s)")

    for script in pending:
        mid = parse_migration_filename(script.name)
        assert mid is not None  # guaranteed by discover_migrations() filter
        print(f"  [{mid}]")
        if not run_migration_script(script, target):
            print(f"\n  Migration aborted at {script.name}.")
            print("  Target project may be in a partially migrated state.")
            print("  Fix the issue and re-run publish, or use --force for clean install.")
            return False
        # Record success immediately to preserve progress on partial failure
        data["applied"].append({
            "id": mid,
            "applied_at": _now_iso(),
            "source": "executed",
        })
        write_applied(target, data)

    print(f"\n  All {len(pending)} migration(s) completed successfully.")
    return True


# ── Scaffolding helper ────────────────────────────────────────────


_TEMPLATE = '''"""TODO: brief description of what this migration does."""
from pathlib import Path


def migrate(target: Path) -> None:
    """target is the absolute path to the game project root.

    Scripts MUST be idempotent — re-runs after a partial failure must
    not corrupt state. Raise an exception to abort the migration chain.
    """
    # TODO: implement
    pass
'''


def create_migration_template(slug: str) -> Path:
    """Scaffold a new migration script with the current UTC timestamp.

    `slug` is sanitised to `[a-z0-9_]+`. Raises ValueError on empty slug
    after sanitisation, FileExistsError on collision (extremely unlikely
    given second precision plus a slug component).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe = re.sub(r"[^a-z0-9_]+", "_", slug.lower()).strip("_")
    if not safe:
        raise ValueError("Slug must contain at least one alphanumeric character")

    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = MIGRATIONS_DIR / f"{timestamp}_{safe}.py"
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.write_text(_TEMPLATE, encoding="utf-8")
    return path


# ── CLI ───────────────────────────────────────────────────────────


def _detect_legacy_cli_flags() -> str | None:
    """If sys.argv contains the removed --from / --to flags, return the
    first one found; otherwise None. Lets main() emit a targeted error
    instead of argparse's generic 'unrecognized arguments' for any
    external script that hasn't migrated off the old CLI."""
    for a in sys.argv[1:]:
        if a in ("--from", "--to") or a.startswith("--from=") or a.startswith("--to="):
            return a.split("=", 1)[0]
    return None


def main():
    legacy_flag = _detect_legacy_cli_flags()
    if legacy_flag is not None:
        print(
            f"Error: {legacy_flag} is no longer supported. The applied-"
            f"tracking model derives 'what to run' from\n"
            f"  <target>/.godotmaker/applied_migrations.json\n"
            f"instead of a version range. Equivalents:\n"
            f"  Apply pending migrations:    python tools/migrate.py <target>\n"
            f"  Mark all as applied (no-op): python tools/migrate.py <target> --baseline\n"
            f"  Scaffold a new migration:    python tools/migrate.py --new <slug>\n"
            f"See migrations/README.md for the full model.",
            file=sys.stderr,
        )
        sys.exit(2)

    parser = argparse.ArgumentParser(
        description="Apply or scaffold GodotMaker version migrations"
    )
    parser.add_argument("target", nargs="?",
                        help="Path to target game project (omit when using --new)")
    parser.add_argument("--baseline", action="store_true",
                        help="Mark all current migrations as applied without running them")
    parser.add_argument("--new", metavar="SLUG",
                        help="Scaffold a new migration script with the current timestamp")
    args = parser.parse_args()

    if args.new is not None:
        try:
            path = create_migration_template(args.new)
        except (ValueError, FileExistsError) as e:
            print(f"Error: {e}")
            sys.exit(1)
        print(f"Created {path.relative_to(MIGRATIONS_DIR.parent)}")
        sys.exit(0)

    if args.target is None:
        parser.error("target is required unless --new is given")

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"Error: {target} is not a directory")
        sys.exit(1)

    if args.baseline:
        n = baseline_applied(target)
        print(f"Baselined {n} migration(s).")
        sys.exit(0)

    try:
        success = run_migrations(target)
    except TrackerCorruptionError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

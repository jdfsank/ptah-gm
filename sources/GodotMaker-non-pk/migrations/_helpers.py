"""Shared utilities for GodotMaker migration scripts."""
import subprocess
from pathlib import Path


def ensure_git_tracked(target: Path, rel_path: str, label: str) -> None:
    """Stage rel_path in the target git repo if the path exists.

    Uses `git add` directly — it is idempotent, so no ls-files pre-check
    is needed.  Prints a one-line status line ([done]/[skip]/[warn]).
    """
    full_path = target / rel_path
    if not full_path.exists():
        print(f"  [skip] {label} does not exist yet")
        return

    try:
        result = subprocess.run(
            ["git", "add", rel_path],
            cwd=str(target),
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"  [done] git add {rel_path}")
        else:
            print(f"  [warn] git add {rel_path} failed (exit {result.returncode})")
    except subprocess.TimeoutExpired:
        print(f"  [skip] git timed out while adding {rel_path}")
    except FileNotFoundError:
        print(f"  [skip] git not available — skipping {rel_path}")

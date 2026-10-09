#!/usr/bin/env python3
"""Check that user-facing English docs change with their Chinese mirrors."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def required_chinese_mirror(path: str) -> str | None:
    normalized = normalize_path(path)
    if normalized == "README.md":
        return "README.zh-CN.md"
    if normalized == "docs/index.md":
        return "docs/zh/index.md"
    if normalized.startswith("docs/wiki/") and normalized.endswith(".md"):
        return normalized.replace("docs/wiki/", "docs/zh/wiki/", 1)
    return None


def run_git(repo: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [
        normalize_path(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def staged_paths(repo: Path) -> list[str]:
    return run_git(
        repo,
        [
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMRT",
        ],
    )


def diff_paths(repo: Path, base: str, head: str) -> list[str]:
    return run_git(
        repo,
        [
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            f"{base}...{head}",
        ],
    )


def check_paths(paths: list[str], repo: Path) -> list[str]:
    changed = {normalize_path(path) for path in paths}
    errors: list[str] = []

    for path in sorted(changed):
        mirror = required_chinese_mirror(path)
        if mirror is None:
            continue
        if mirror in changed:
            continue
        if not (repo / mirror).exists():
            errors.append(
                f"{path} changed but required Chinese mirror {mirror} does not exist."
            )
        else:
            errors.append(
                f"{path} changed but {mirror} was not changed in the same diff."
            )

    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check user-facing English docs changed together with Chinese mirrors."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository root to inspect. Defaults to the current directory.",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Check staged files for a pre-commit hook.",
    )
    parser.add_argument("--base", help="Base git revision for CI diff checks.")
    parser.add_argument("--head", help="Head git revision for CI diff checks.")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Explicit changed path for tests or ad-hoc checks.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo = Path(args.repo).resolve()

    try:
        if args.path:
            paths = args.path
        elif args.staged:
            paths = staged_paths(repo)
        elif args.base and args.head:
            paths = diff_paths(repo, args.base, args.head)
        else:
            print(
                "Provide --staged, --base/--head, or one or more --path values.",
                file=sys.stderr,
            )
            return 2
    except RuntimeError as exc:
        print(f"doc i18n check failed to inspect git diff: {exc}", file=sys.stderr)
        return 2

    errors = check_paths(paths, repo)
    if not errors:
        return 0

    print("User-facing English docs need matching Chinese doc updates:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

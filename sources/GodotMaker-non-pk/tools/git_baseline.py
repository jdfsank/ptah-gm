"""Git object identities for scoped local review inputs.

All indexing uses a disposable index. The user's real index is never touched.
This is change detection for a cooperative local workflow, not authentication.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class GitBaselineError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path, env: dict | None = None, input: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--literal-pathspecs", *args], cwd=cwd, env=env, input=input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except FileNotFoundError as exc:
        raise GitBaselineError("Git executable is unavailable") from exc
    if result.returncode:
        raise GitBaselineError(result.stderr.decode("utf-8", "replace").strip() or "Git operation failed")
    return result.stdout


def _repo(path: str | Path) -> tuple[Path, str, str]:
    root = Path(path).resolve()
    if root.is_file():
        root = root.parent
    top = Path(_run(["-C", str(root), "rev-parse", "--show-toplevel"], cwd=root).decode().strip()).resolve()
    git_dir_raw = _run(["-C", str(root), "rev-parse", "--absolute-git-dir"], cwd=root).decode().strip()
    prefix = root.relative_to(top).as_posix()
    if prefix == ".":
        prefix = ""
    return top, git_dir_raw, prefix


def _safe_file(root: Path, relative: str) -> Path:
    if not relative or "\0" in relative or "\\" in relative:
        raise GitBaselineError(f"Unsafe inventory path: {relative!r}")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise GitBaselineError(f"Unsafe inventory path: {relative!r}")
    root = root.resolve()
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise GitBaselineError(f"Symlink in inventory path: {relative}")
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise GitBaselineError(f"Inventory path escapes root: {relative}")
    if not candidate.is_file():
        raise GitBaselineError(f"Unsupported or missing inventory file: {relative}")
    return candidate


def repository_state(root: str | Path) -> dict:
    path = Path(root).resolve()
    top, git_dir, prefix = _repo(path)
    head = _run(["-C", str(path), "rev-parse", "HEAD"], cwd=path).decode().strip()
    status_env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    dirty = bool(_run(["-C", str(path), "status", "--porcelain=v1", "--untracked-files=all"], cwd=path, env=status_env))
    return {"head": head, "gitRoot": str(top), "gitDir": git_dir, "prefix": prefix, "dirty": dirty}


def require_repository(root: str | Path) -> dict:
    try:
        return repository_state(root)
    except GitBaselineError as exc:
        raise GitBaselineError(f"A Git repository is required for formal review: {exc}") from exc


def _private_index(top: Path, paths: list[str]) -> dict[str, str]:
    for path in paths:
        _safe_file(top, path)

    with tempfile.TemporaryDirectory(prefix="codex-git-index-") as temp:
        index = Path(temp) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index), "GIT_OPTIONAL_LOCKS": "0",
               "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.filemode", "GIT_CONFIG_VALUE_0": "true"}
        _run(["-C", str(top), "read-tree", "--empty"], cwd=top, env=env)
        if paths:
            # Literal pathspecs in a NUL-delimited stream handle spaces/newlines safely.
            spec = b"".join(p.encode("utf-8") + b"\0" for p in sorted(set(paths)))
            _run(["-C", str(top), "add", "-A", "-f", "--pathspec-from-file=-", "--pathspec-file-nul"], cwd=top, env=env, input=spec)
        raw = _run(["-C", str(top), "ls-files", "--stage", "-z"], cwd=top, env=env)
    result = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        mode, oid, stage = meta.decode("ascii").split(" ")
        if stage != "0" or mode not in {"100644", "100755"}:
            raise GitBaselineError("Unmerged entries, symlinks and submodules are unsupported")
        relative = name.decode("utf-8", "strict")
        result[relative] = f"git:{mode}:blob:{oid}"
    return dict(sorted(result.items()))


def _temporary_inventory(paths: dict[str, Path]) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="codex-git-objects-") as temp:
        top = Path(temp)
        _run(["init", "--quiet", str(top)], cwd=top)
        for relative, source in paths.items():
            destination = top / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        return _private_index(top, list(paths))


def capture_inventory(root: str | Path, exact_paths) -> dict[str, str]:
    """Return identities for precisely the supplied project-relative file paths."""
    base = Path(root).resolve()
    supplied = list(exact_paths)
    for relative in supplied:
        if not isinstance(relative, str) or not relative or "\0" in relative:
            raise GitBaselineError(f"Unsafe inventory path: {relative!r}")
    paths = sorted(set(supplied))
    sources = {}
    for relative in paths:
        source = _safe_file(base, relative)
        sources[relative] = source
    try:
        top, _, _ = _repo(base)
    except GitBaselineError:
        return _temporary_inventory(sources)
    root_relative = base.relative_to(top).as_posix()
    if root_relative == ".":
        root_relative = ""
    git_paths = [(root_relative + "/" if root_relative else "") + item for item in paths]
    captured = _private_index(top, git_paths)
    prefix = root_relative + "/" if root_relative else ""
    return {name[len(prefix):]: value for name, value in captured.items() if name.startswith(prefix)}


def identity_bytes(data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="codex-git-identity-") as temp:
        top = Path(temp)
        _run(["init", "--quiet", str(top)], cwd=top)
        (top / "payload").write_bytes(data)
        identity = _private_index(top, ["payload"])["payload"]
        return "git:blob:" + identity.rsplit(":", 1)[1]


def identity_file(path: str | Path) -> str:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise GitBaselineError(f"Unsupported identity file: {source}")
    with tempfile.TemporaryDirectory(prefix="codex-git-identity-") as temp:
        top = Path(temp)
        _run(["init", "--quiet", str(top)], cwd=top)
        shutil.copyfile(source, top / "payload")
        identity = _private_index(top, ["payload"])["payload"]
        return "git:blob:" + identity.rsplit(":", 1)[1]


def manifest_identity(canonical_bytes: bytes) -> str:
    return identity_bytes(canonical_bytes)

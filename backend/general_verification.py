"""Independent, conservative verification for Studio's general 2D projects.

The verifier owns its smoke harness and never executes producer-selected test
paths or trusts producer-authored PASS markers. Godot still executes candidate
project code; absent a verified OS sandbox this is cooperative local execution,
not isolation from a malicious project.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .object_protocol import ObjectProtocolError, validate_document
except ImportError:  # direct script use in small local harnesses
    from object_protocol import ObjectProtocolError, validate_document


MAX_PROJECT_FILES = 5000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
SERVICE_RECORD_PATHS = frozenset(
    {
        ".godotmaker/frontend-approval.json",
        ".godotmaker/stage.jsonl",
    }
)
ENGINE_ERRORS = re.compile(
    r"(?im)^\s*(?:WARNING|ERROR|SCRIPT ERROR|Parse Error|Compile Error):|Failed to load (?:script|resource)"
)
MAIN_SCENE = re.compile(r'(?m)^run/main_scene\s*=\s*"res://([^"\r\n]+)"\s*$')
GODOT_UID = re.compile(rb"uid://[A-Za-z0-9_-]{1,128}\n")


class GeneralVerificationError(ValueError):
    """A project cannot be safely checked against the general project contract."""


def _run_git(project: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode:
        raise GeneralVerificationError(
            f"Git scope query failed: {completed.stderr.strip() or completed.returncode}"
        )
    return completed.stdout


def _run_git_bytes(
    project: Path, *args: str, input_bytes: bytes | None = None
) -> bytes:
    """Run a bounded Git query without decoding source blob bytes."""
    # Git's batch output can fill its pipe while macOS blocks a stdin write.
    # A file lets Git drain the entire request without competing pipe writes.
    with tempfile.TemporaryFile() as request:
        request.write(input_bytes or b"")
        request.seek(0)
        completed = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True,
            stdin=request,
            timeout=30,
            check=False,
        )
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GeneralVerificationError(
            f"Git UID baseline query failed: {message or completed.returncode}"
        )
    return completed.stdout


def _safe_policy_path(value: str) -> bool:
    """The bounded, user-facing project write surface for v1."""
    if not value or "\\" in value or value.startswith("/") or ":" in value:
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    path = PurePosixPath(value)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        return False
    if value == "project.godot":
        return True
    if len(parts) < 2:
        return False
    root, suffix = parts[0], path.suffix.lower()
    if root == "scripts":
        return suffix == ".gd"
    if root == "scenes":
        return suffix == ".tscn"
    if root == "resources":
        return suffix == ".tres"
    if root == "assets":
        return suffix in {".png", ".jpg", ".jpeg", ".webp"}
    return False


def _relative_path(project: Path, value: str) -> Path:
    if not _safe_policy_path(value):
        raise GeneralVerificationError(f"unsupported or unsafe project path: {value!r}")
    candidate = project.joinpath(*PurePosixPath(value).parts)
    current = project
    for part in PurePosixPath(value).parts:
        current = current / part
        if current.is_symlink():
            raise GeneralVerificationError(f"symlink is forbidden in project path: {value}")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(project):
        raise GeneralVerificationError(f"project path escapes root: {value}")
    return candidate


def _git_changed_paths(project: Path, base_commit: str) -> list[str]:
    if not isinstance(base_commit, str) or not base_commit.strip() or base_commit.startswith("-"):
        raise GeneralVerificationError("base_commit must be a non-empty trusted Git revision")
    _run_git(project, "rev-parse", "--verify", f"{base_commit}^{{commit}}")
    # NUL-delimited output keeps unusual filenames from corrupting the audit.
    changed = _run_git(
        project,
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--name-only",
        "-z",
        base_commit,
        "--",
    )
    untracked = _run_git(
        project, "ls-files", "--others", "--exclude-standard", "-z", "--"
    )
    return sorted({p for p in (changed + untracked).split("\0") if p})


def _check_no_submodules(project: Path) -> None:
    for record in _run_git(project, "ls-files", "--stage", "-z").split("\0"):
        if record and record.split(" ", 1)[0] == "160000":
            raise GeneralVerificationError("Git submodules are not supported in general projects")
    for directory, dirs, _files in os.walk(project, followlinks=False):
        if Path(directory) == project:
            dirs[:] = [d for d in dirs if d != ".git"]
            continue
        if ".git" in dirs or (Path(directory) / ".git").is_file():
            raise GeneralVerificationError("nested Git repositories are not supported")
        dirs[:] = [d for d in dirs if d not in {".git", ".godot", "__pycache__"}]


def _check_tree_links_and_limits(project: Path) -> None:
    count = 0
    total = 0
    for directory, dirs, files in os.walk(project, followlinks=False):
        current = Path(directory)
        if current == project:
            dirs[:] = [d for d in dirs if d != ".git"]
        for dirname in list(dirs):
            path = current / dirname
            if path.is_symlink():
                raise GeneralVerificationError(f"project directory symlink is forbidden: {path.relative_to(project)}")
            if dirname in {".git", ".godot", "__pycache__"}:
                dirs.remove(dirname)
        for filename in files:
            path = current / filename
            if path.is_symlink():
                raise GeneralVerificationError(f"project file symlink is forbidden: {path.relative_to(project)}")
            if filename == ".gitignore":
                continue
            count += 1
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise GeneralVerificationError(f"cannot inspect project file: {exc}") from exc
            if size > MAX_FILE_BYTES:
                raise GeneralVerificationError(f"project file exceeds size limit: {path.relative_to(project)}")
            total += size
            if count > MAX_PROJECT_FILES or total > MAX_TOTAL_BYTES:
                raise GeneralVerificationError("project exceeds file-count or total-size limit")


def _validate_service_records(
    project: Path, service_records: Mapping[str, str] | None
) -> set[str]:
    """Verify explicitly supplied, backend-pinned GM files without removing them."""
    if service_records is None:
        return set()
    if not isinstance(service_records, Mapping):
        raise GeneralVerificationError("service_records must be a mapping of exact GM service file contents")
    if any(not isinstance(path, str) for path in service_records):
        raise GeneralVerificationError("service record paths must be text")
    keys = set(service_records)
    unknown = keys - SERVICE_RECORD_PATHS
    if unknown:
        raise GeneralVerificationError("unsupported service record paths: " + ", ".join(sorted(unknown)))
    if ".godotmaker/frontend-approval.json" not in keys:
        raise GeneralVerificationError("service_records must include the pinned frontend approval binding")
    for relative, expected in service_records.items():
        if not isinstance(relative, str) or relative not in SERVICE_RECORD_PATHS:
            raise GeneralVerificationError("unsupported service record path")
        if not isinstance(expected, str):
            raise GeneralVerificationError(f"service record must be UTF-8 text: {relative}")
        path = project / relative
        current = project
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                raise GeneralVerificationError(f"service record path cannot contain symlinks: {relative}")
        if not path.is_file():
            raise GeneralVerificationError(f"service record is missing or not a regular file: {relative}")
        try:
            actual = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise GeneralVerificationError(f"service record is missing or not UTF-8 text: {relative}") from exc
        if actual != expected:
            raise GeneralVerificationError(f"service record differs from its backend-pinned content: {relative}")
    return keys


def _is_supported_uid_sidecar_path(relative: str) -> bool:
    """Accept UID metadata only for producer GDScript or the server runtime."""
    if not isinstance(relative, str) or not relative.endswith(".gd.uid"):
        return False
    source = relative[:-4]
    if source == "studio/runtime.gd":
        return True
    return _safe_policy_path(source) and PurePosixPath(source).suffix.lower() == ".gd"


def _validate_prepared_uid_sidecars(
    project: Path, prepared_uid_sidecars: Mapping[str, bytes] | None
) -> dict[str, bytes]:
    """Match explicitly prepared UID bytes to regular in-root GDScript files.

    The mapping is evidence from the trusted pre-seal Godot import helper. A
    raw changed ``.gd.uid`` without this exact mapping remains out of policy.
    """
    if prepared_uid_sidecars is None:
        return {}
    if not isinstance(prepared_uid_sidecars, Mapping):
        raise GeneralVerificationError("prepared UID sidecars must map relative paths to exact bytes")
    normalized: dict[str, bytes] = {}
    uid_values: set[bytes] = set()
    for relative, expected in prepared_uid_sidecars.items():
        if not _is_supported_uid_sidecar_path(relative):
            raise GeneralVerificationError(f"unsupported prepared UID sidecar path: {relative!r}")
        if not isinstance(expected, bytes) or GODOT_UID.fullmatch(expected) is None:
            raise GeneralVerificationError(f"prepared UID sidecar has invalid Godot UID content: {relative}")
        if expected in uid_values:
            raise GeneralVerificationError(f"prepared UID sidecars contain a duplicate UID: {relative}")
        uid_values.add(expected)

        source_relative = relative[:-4]
        source_path = _relative_path(project, source_relative) if source_relative != "studio/runtime.gd" else project / source_relative
        sidecar_path = project.joinpath(*PurePosixPath(relative).parts)
        for candidate in (source_path, sidecar_path):
            current = project
            for part in candidate.relative_to(project).parts:
                current = current / part
                if current.is_symlink():
                    raise GeneralVerificationError(f"prepared UID path cannot contain symlinks: {relative}")
        if not source_path.is_file():
            raise GeneralVerificationError(f"prepared UID sidecar has no regular GDScript source: {relative}")
        if not sidecar_path.is_file():
            raise GeneralVerificationError(f"prepared UID sidecar is missing or not a regular file: {relative}")
        try:
            actual = sidecar_path.read_bytes()
        except OSError as exc:
            raise GeneralVerificationError(f"cannot read prepared UID sidecar {relative}: {exc}") from exc
        if actual != expected:
            raise GeneralVerificationError(f"prepared UID sidecar differs from trusted import output: {relative}")
        normalized[relative] = expected
    return normalized


def _git_uid_sidecar_baseline(
    project: Path, base_commit: str
) -> dict[str, tuple[bytes, bool]]:
    """Read regular source UID sidecar blobs from the exact base Git tree."""
    tree = _run_git_bytes(project, "ls-tree", "-r", "-z", "--full-tree", base_commit)
    entries: list[tuple[str, bytes, bool]] = []
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator or not path_bytes.endswith(b".gd.uid") or path_bytes.startswith(b".godot/"):
            continue
        fields = metadata.split()
        if len(fields) != 3:
            raise GeneralVerificationError("Git UID baseline contains a malformed tree entry")
        mode, object_type, object_id = fields
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise GeneralVerificationError(
                "Git UID baseline contains a non-regular UID sidecar: "
                + os.fsdecode(path_bytes)
            )
        entries.append((os.fsdecode(path_bytes), object_id, mode == b"100755"))

    if not entries:
        return {}
    if len(entries) > MAX_PROJECT_FILES:
        raise GeneralVerificationError("Git UID baseline exceeds the project file-count limit")
    request = b"".join(object_id + b"\n" for _, object_id, _ in entries)
    output = _run_git_bytes(project, "cat-file", "--batch", input_bytes=request)
    cursor = 0
    baseline: dict[str, tuple[bytes, bool]] = {}
    total = 0
    for relative, expected_id, executable in entries:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise GeneralVerificationError("Git UID baseline blob output is truncated")
        header = output[cursor:header_end].split()
        if len(header) != 3 or header[0] != expected_id or header[1] != b"blob":
            raise GeneralVerificationError(f"Git UID baseline blob metadata is invalid: {relative}")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise GeneralVerificationError(f"Git UID baseline blob size is invalid: {relative}") from exc
        if size < 0 or size > MAX_FILE_BYTES:
            raise GeneralVerificationError(f"Git UID baseline blob exceeds the file limit: {relative}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise GeneralVerificationError("Git UID baseline sidecars exceed the project byte limit")
        content_start = header_end + 1
        content_end = content_start + size
        if content_end >= len(output) or output[content_end:content_end + 1] != b"\n":
            raise GeneralVerificationError(f"Git UID baseline blob is truncated: {relative}")
        baseline[relative] = (output[content_start:content_end], executable)
        cursor = content_end + 1
    if cursor != len(output):
        raise GeneralVerificationError("Git UID baseline blob output has unexpected trailing data")
    return baseline


def _source_uid_sidecar_inventory(project: Path) -> dict[str, tuple[bytes, bool]]:
    """Capture every source-tree .gd.uid, including Git-ignored files."""
    sidecars: dict[str, tuple[bytes, bool]] = {}
    for directory, dirs, files in os.walk(project, followlinks=False):
        current = Path(directory)
        if current == project:
            dirs[:] = [name for name in dirs if name not in {".git", ".godot"}]
        for name in list(dirs):
            child = current / name
            if child.is_symlink():
                raise GeneralVerificationError(
                    f"UID sidecar tree contains a directory symlink: {child.relative_to(project)}"
                )
        for filename in files:
            if not filename.endswith(".gd.uid"):
                continue
            path = current / filename
            relative = path.relative_to(project).as_posix()
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise GeneralVerificationError(f"cannot inspect UID sidecar {relative}: {exc}") from exc
            if not stat.S_ISREG(mode):
                raise GeneralVerificationError(f"UID sidecar must be a regular file: {relative}")
            try:
                sidecars[relative] = (path.read_bytes(), bool(mode & 0o111))
            except OSError as exc:
                raise GeneralVerificationError(f"cannot read UID sidecar {relative}: {exc}") from exc
    return sidecars


def _validate_uid_sidecars_against_base(
    project: Path,
    base_commit: str,
    prepared_uid_sidecars: Mapping[str, bytes],
) -> None:
    """Require old UID blobs to stay exact and new ones to be explicitly prepared."""
    baseline = _git_uid_sidecar_baseline(project, base_commit)
    current = _source_uid_sidecar_inventory(project)
    removed = sorted(set(baseline) - set(current))
    if removed:
        raise GeneralVerificationError(
            "Git baseline UID sidecars are missing or deleted: " + ", ".join(removed[:40])
        )
    modified = sorted(
        path for path in set(baseline) & set(current)
        if baseline[path] != current[path]
    )
    if modified:
        raise GeneralVerificationError(
            "existing Git UID sidecars must remain byte-for-byte and mode unchanged: "
            + ", ".join(modified[:40])
        )
    prepared_existing = sorted(set(prepared_uid_sidecars) & set(baseline))
    if prepared_existing:
        raise GeneralVerificationError(
            "UID preparation may add sidecars only; existing Git UID sidecars cannot be replaced: "
            + ", ".join(prepared_existing[:40])
        )
    unprepared_new = sorted((set(current) - set(baseline)) - set(prepared_uid_sidecars))
    if unprepared_new:
        raise GeneralVerificationError(
            "unprepared UID sidecars, including ignored files: " + ", ".join(unprepared_new[:40])
        )
    executable_new = sorted(
        path for path in set(current) - set(baseline)
        if current[path][1]
    )
    if executable_new:
        raise GeneralVerificationError(
            "prepared UID sidecars cannot be executable: " + ", ".join(executable_new[:40])
        )
    uid_paths: dict[bytes, str] = {}
    for path, (content, _executable) in current.items():
        if not _is_supported_uid_sidecar_path(path):
            continue
        if GODOT_UID.fullmatch(content) is None:
            raise GeneralVerificationError(f"Godot UID sidecar is malformed: {path}")
        if content in uid_paths:
            raise GeneralVerificationError(
                f"Godot UID sidecars contain a duplicate identifier: {uid_paths[content]}, {path}"
            )
        uid_paths[content] = path
        source = project.joinpath(*PurePosixPath(path[:-4]).parts)
        if source.is_symlink() or not source.is_file():
            raise GeneralVerificationError(f"Godot UID sidecar has no regular GDScript source: {path}")


def audit_general_scope(
    project: str | os.PathLike[str],
    base_commit: str,
    document: Mapping[str, object],
    *,
    allow_engine_cache: bool = False,
    service_records: Mapping[str, str] | None = None,
    prepared_uid_sidecars: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Validate Git write scope and document bindings; return changed paths.

    Design/game.json and studio/runtime.gd are server-owned and are excluded
    from producer write policy. The coordinator must compare their bytes to
    its frozen protected contents before and after producer/verifier stages.
    """
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise GeneralVerificationError("project directory does not exist")
    try:
        normalized = validate_document(dict(document))
    except (ObjectProtocolError, TypeError, ValueError) as exc:
        raise GeneralVerificationError(f"invalid object document: {exc}") from exc

    _check_no_submodules(root)
    _check_tree_links_and_limits(root)
    if not (root / "project.godot").is_file():
        raise GeneralVerificationError("project.godot is missing")

    changed = _git_changed_paths(root, base_commit)
    uid_sidecars = _validate_prepared_uid_sidecars(root, prepared_uid_sidecars)
    _validate_uid_sidecars_against_base(root, base_commit, uid_sidecars)
    changed_uid_sidecars = {path for path in changed if path.endswith(".gd.uid")}
    if changed_uid_sidecars != set(uid_sidecars):
        missing = sorted(changed_uid_sidecars - set(uid_sidecars))
        stale = sorted(set(uid_sidecars) - changed_uid_sidecars)
        details = []
        if missing:
            details.append("unprepared UID sidecars: " + ", ".join(missing[:40]))
        if stale:
            details.append("prepared UID sidecars are not new source changes: " + ", ".join(stale[:40]))
        raise GeneralVerificationError("; ".join(details) or "UID sidecar preparation does not match Git changes")
    unauthorized = [
        path for path in changed
        if not _safe_policy_path(path) and path not in uid_sidecars
    ]
    if unauthorized:
        raise GeneralVerificationError(
            "producer changed files outside the general project write policy: "
            + ", ".join(unauthorized[:40])
        )

    verified_records = _validate_service_records(root, service_records)
    ignored = [
        path
        for path in _run_git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--").split("\0")
        if path
    ]
    missing_records = verified_records - set(ignored)
    if missing_records:
        raise GeneralVerificationError(
            "pinned service records are not Git-ignored files: " + ", ".join(sorted(missing_records))
        )
    unauthorized_ignored = [
        path
        for path in ignored
        if path not in verified_records
        and not (allow_engine_cache and path.startswith(".godot/"))
    ]
    if unauthorized_ignored:
        raise GeneralVerificationError(
            "unauthorized ignored producer files: " + ", ".join(unauthorized_ignored[:40])
        )

    for obj in normalized["objects"]:
        for binding in obj["sourceBindings"]:
            path = _relative_path(root, binding)
            if not path.is_file():
                raise GeneralVerificationError(
                    f"object {obj['id']} source binding is missing: {binding}"
                )

    design_path = root / "design" / "game.json"
    runtime_path = root / "studio" / "runtime.gd"
    if design_path.is_symlink() or runtime_path.is_symlink():
        raise GeneralVerificationError("server-owned design/runtime files must not be symlinks")
    if not design_path.is_file() or not runtime_path.is_file():
        raise GeneralVerificationError("server-owned design/game.json or studio/runtime.gd is missing")
    try:
        stored_document = json.loads(design_path.read_text(encoding="utf-8"))
        stored_document = validate_document(stored_document)
    except (OSError, UnicodeError, json.JSONDecodeError, ObjectProtocolError) as exc:
        raise GeneralVerificationError(f"server-owned design document is invalid: {exc}") from exc
    if stored_document != normalized:
        raise GeneralVerificationError("design/game.json differs from the frozen verifier document")

    project_settings = (root / "project.godot").read_text(encoding="utf-8")
    main_scene_match = MAIN_SCENE.search(project_settings)
    if not main_scene_match:
        raise GeneralVerificationError("project.godot must declare a res:// main scene")
    main_scene = main_scene_match.group(1)
    main_path = _relative_path(root, main_scene)
    if not main_path.is_file() or PurePosixPath(main_scene).suffix.lower() != ".tscn":
        raise GeneralVerificationError("project main scene must be an existing supported .tscn file")
    bound_paths = {path for obj in normalized["objects"] for path in obj["sourceBindings"]}
    unbound_changes = [path for path in changed if path != "project.godot"
                       and path not in bound_paths and path not in uid_sidecars]
    if unbound_changes:
        raise GeneralVerificationError("changed source files have no approved object binding: "
                                       + ", ".join(unbound_changes[:40]))
    if main_scene not in bound_paths:
        raise GeneralVerificationError("main scene must be represented by a document sourceBinding")
    return changed


def _catalog(document: Mapping[str, object], project: Path) -> dict[str, object]:
    objects = []
    for obj in document["objects"]:  # type: ignore[index]
        source_bindings = list(obj["sourceBindings"])
        objects.append(
            {
                "id": obj["id"],
                "kind": obj["kind"],
                "name": obj["name"],
                "description": obj.get("description", ""),
                "parentId": obj.get("parentId"),
                "relations": obj.get("relations", []),
                "sourceBindings": source_bindings,
                "bindingsPresent": all((project / path).is_file() for path in source_bindings),
                "fields": obj.get("fields", []),
            }
        )
    return {
        "catalogVersion": "studio.objects.v1",
        "projectKind": "godot_2d_general",
        "title": document["title"],
        "objects": objects,
    }


def _resolve_godot(godot_path: str | os.PathLike[str] | None) -> str | None:
    if godot_path is not None:
        candidate = Path(godot_path).expanduser().resolve()
        return str(candidate) if candidate.is_file() else None
    configured = os.environ.get("GODOT_BIN")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    located = shutil.which("godot")
    if located:
        return located
    fallback = Path("/Applications/Godot.app/Contents/MacOS/Godot")
    return str(fallback) if fallback.is_file() else None


def _godot_version(godot: str, timeout: float) -> dict[str, object]:
    return _command(godot, [godot, "--version"], None, timeout)


def _command(
    godot: str,
    argv: list[str],
    cwd: Path | None,
    timeout: float,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=None if env is None else dict(env),
        )
        stdout = completed.stdout
        stderr = completed.stderr
        return_code: int | None = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr)
        return_code = None
        timed_out = True
    except OSError as exc:
        stdout = ""
        stderr = str(exc)
        return_code = None
        timed_out = False
    return {
        "argv": argv,
        "cwd": str(cwd) if cwd else None,
        "returnCode": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "engineIssues": ENGINE_ERRORS.findall(stdout + "\n" + stderr),
    }


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _verification_source_inventory(project: Path) -> dict[str, bytes]:
    """Capture exact per-file contents outside Godot's disposable cache.

    This is an in-memory file inventory, not a digest-based integrity check.
    The trusted verifier harness is included after it is created, so a Godot
    invocation cannot silently rewrite it or add any other source file.
    """
    inventory: dict[str, bytes] = {}
    for directory, dirs, files in os.walk(project, followlinks=False):
        current = Path(directory)
        if current == project:
            dirs[:] = [d for d in dirs if d != ".godot"]
        for dirname in list(dirs):
            child = current / dirname
            if child.is_symlink():
                raise GeneralVerificationError(
                    f"verification copy contains a directory symlink: {child.relative_to(project)}"
                )
        for filename in files:
            path = current / filename
            relative = path.relative_to(project).as_posix()
            if path.is_symlink():
                raise GeneralVerificationError(
                    f"verification copy contains a file symlink: {relative}"
                )
            try:
                inventory[relative] = path.read_bytes()
            except OSError as exc:
                raise GeneralVerificationError(
                    f"cannot read verification-copy file {relative}: {exc}"
                ) from exc
    return inventory


def _inventory_changes(before: Mapping[str, bytes], after: Mapping[str, bytes]) -> list[str]:
    return sorted(
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def _smoke_harness() -> str:
    """Trusted harness injected only into a disposable verifier copy."""
    return '''extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var main_scene_path := str(ProjectSettings.get_setting("application/run/main_scene", ""))
	if main_scene_path.is_empty():
		push_error("Verifier: configured main scene is missing")
		quit(2)
		return
	var packed := load(main_scene_path) as PackedScene
	if packed == null:
		push_error("Verifier: configured main scene did not load as PackedScene")
		quit(2)
		return
	var instance := packed.instantiate()
	if instance == null:
		push_error("Verifier: main scene did not instantiate")
		quit(2)
		return
	root.add_child(instance)
	await process_frame
	await process_frame
	if not is_instance_valid(instance) or instance.get_parent() != root:
		push_error("Verifier: main scene did not survive runtime smoke frames")
		quit(2)
		return
	print("STUDIO_BACKEND_RUNTIME_SMOKE_OBSERVED")
	quit(0)
'''


def verify_general_project(
    project: str | os.PathLike[str],
    document: Mapping[str, object],
    *,
    base_commit: str,
    operation: str = "IMPLEMENTATION",
    godot_path: str | os.PathLike[str] | None = None,
    timeout: float = 45.0,
    service_records: Mapping[str, str] | None = None,
    prepared_uid_sidecars: Mapping[str, bytes] | None = None,
    expected_uid_engine_version: str | None = None,
) -> dict[str, object]:
    """Run bounded, backend-owned import and main-scene runtime smoke checks.

    PASS means only that the trusted structural/import/runtime checks passed.
    Every user gameplay/visual requirement remains NOT_TESTED / needsReview.
    """
    root = Path(project).expanduser().resolve()
    report: dict[str, object] = {
        "status": "FAIL",
        "technicalStatus": "FAIL",
        "operation": operation,
        "requirements": [],
        "checks": [],
        "diagnostics": [],
        "commands": [],
        "catalog": None,
        "engine": None,
        "sandbox": {"status": "NOT_APPLIED", "boundary": "no Godot command launched"},
        "userAcceptance": [],
    }
    requirements: list[dict[str, object]] = report["requirements"]  # type: ignore[assignment]
    checks: list[str] = report["checks"]  # type: ignore[assignment]
    diagnostics: list[dict[str, object]] = report["diagnostics"]  # type: ignore[assignment]
    commands: list[dict[str, object]] = report["commands"]  # type: ignore[assignment]

    if operation.upper() != "IMPLEMENTATION":
        diagnostics.append({"stage": "contract", "message": "general verifier supports IMPLEMENTATION only"})
        requirements.append({"id": "operation.supported", "status": "FAIL", "evidence": operation})
        return report
    if expected_uid_engine_version is not None and (
        not isinstance(expected_uid_engine_version, str)
        or not expected_uid_engine_version
        or expected_uid_engine_version != expected_uid_engine_version.strip()
        or "\n" in expected_uid_engine_version
        or "\r" in expected_uid_engine_version
    ):
        message = "expected UID preparation engine version is invalid"
        diagnostics.append({"stage": "uid_preparation", "message": message})
        requirements.append({"id": "uid.preparation.engine_version", "status": "FAIL", "evidence": message})
        return report
    try:
        normalized = validate_document(dict(document))
        paths = audit_general_scope(
            root,
            base_commit,
            normalized,
            service_records=service_records,
            prepared_uid_sidecars=prepared_uid_sidecars,
        )
        requirements.extend(
            [
                {"id": "project.document", "status": "PASS", "evidence": "valid studio.objects.v1 document"},
                {"id": "git.write_scope", "status": "PASS", "evidence": {"baseCommit": base_commit, "changedPaths": paths}},
                {"id": "object.source_bindings", "status": "PASS", "evidence": "all declared bindings resolve to in-root files"},
                {"id": "design.frozen_document", "status": "PASS", "evidence": "server-owned design/game.json matches the frozen object document"},
            ]
        )
        checks.extend(["object document schema", "Git write policy", "source bindings and main scene"])
        report["catalog"] = _catalog(normalized, root)
    except (GeneralVerificationError, ObjectProtocolError, OSError, UnicodeError) as exc:
        diagnostics.append({"stage": "scope", "message": str(exc)})
        requirements.append({"id": "project.scope", "status": "FAIL", "evidence": str(exc)})
        return report

    godot = _resolve_godot(godot_path)
    if godot is None:
        message = "Godot executable was not found"
        requirements.append({"id": "godot.available", "status": "FAIL", "evidence": message})
        diagnostics.append({"stage": "godot", "message": message})
        return report
    with tempfile.TemporaryDirectory(prefix="studio-general-verify-") as temp_name:
        temp_root = Path(temp_name).resolve()
        copy_root = temp_root / "project"
        try:
            shutil.copytree(
                root,
                copy_root,
                ignore=shutil.ignore_patterns(
                    ".git", ".godot", ".godotmaker", "__pycache__", ".studio_verifier"
                ),
            )
            harness_dir = copy_root / ".studio_verifier"
            harness_dir.mkdir()
            harness_path = harness_dir / "runtime_smoke.gd"
            harness_path.write_text(_smoke_harness(), encoding="utf-8")
            source_inventory = _verification_source_inventory(copy_root)
            from runners.image_imports import missing_image_imports, read_generated_imports
            image_import_relatives = missing_image_imports(copy_root, source_inventory)
        except (OSError, ValueError) as exc:
            diagnostics.append({"stage": "prepare", "message": f"could not create clean verifier copy: {exc}"})
            requirements.append({"id": "copy.clean", "status": "FAIL", "evidence": str(exc)})
            return report

        try:
            from runners.godot_runtime import GodotRuntime, sandboxed_godot_argv

            runtime = GodotRuntime.create(str((temp_root / "godot-runtime").resolve()))
            version_argv = sandboxed_godot_argv(
                godot, ["--version"], project_root=copy_root, runtime=runtime
            )
            version = _command(
                godot, version_argv, copy_root, min(timeout, 10.0), env=runtime.environment()
            )
            report["sandbox"] = {
                "status": "APPLIED",
                "policy": "deny-default; source read-only except exact missing image .import paths during recovery import; private .godot/runtime writes; no network",
                "disposableImageImportPaths": list(image_import_relatives),
                "boundary": "Godot child process trees (version, import, runtime smoke)",
            }
        except (OSError, ValueError, RuntimeError) as exc:
            diagnostics.append({"stage": "godot", "message": f"could not prepare a restricted Godot runtime: {exc}"})
            requirements.append({"id": "godot.version", "status": "FAIL", "evidence": str(exc)})
            return report
        commands.append({"name": "version", **version})
        if version["returnCode"] != 0 or version["timedOut"] or version["engineIssues"]:
            requirements.append({"id": "godot.version", "status": "FAIL", "evidence": "version query failed"})
            diagnostics.append({"stage": "godot", "message": "could not determine Godot engine version"})
            return report
        version_text = str(version["stdout"]).strip()
        report["engine"] = {"path": godot, "version": version_text}
        requirements.append({"id": "godot.available", "status": "PASS", "evidence": version_text})
        if expected_uid_engine_version is not None:
            engine_version_matches = version_text == expected_uid_engine_version
            requirements.append({
                "id": "uid.preparation.engine_version",
                "status": "PASS" if engine_version_matches else "FAIL",
                "evidence": {
                    "expected": expected_uid_engine_version,
                    "actual": version_text,
                },
            })
            if not engine_version_matches:
                diagnostics.append({
                    "stage": "uid_preparation",
                    "message": "Godot engine version differs from trusted UID preparation evidence",
                })
                return report

        try:
            editor_settings_path, ca_bundle_path = runtime.configure_editor_tls(version_text, godot)
        except (OSError, ValueError, RuntimeError) as exc:
            message = f"could not prepare private Godot editor TLS settings: {exc}"
            diagnostics.append({"stage": "godot.certificates", "message": message})
            requirements.append({"id": "godot.editor_certificates", "status": "FAIL", "evidence": message})
            return report
        sandbox_evidence = report["sandbox"]
        if isinstance(sandbox_evidence, dict):
            sandbox_evidence["editorCertificateBundle"] = str(ca_bundle_path)
            sandbox_evidence["editorSettings"] = str(editor_settings_path)

        import_argv = sandboxed_godot_argv(
            godot,
            ["--headless", "--path", str(copy_root), "--editor", "--recovery-mode", "--import", "--quit",
             "--log-file", str(runtime.tmp / "import.log")],
            project_root=copy_root,
            runtime=runtime,
            image_import_write_paths=tuple(copy_root / path for path in image_import_relatives),
        )
        import_result = _command(
            godot, import_argv, copy_root, timeout, env=runtime.environment()
        )
        commands.append({"name": "fresh_import", **import_result})
        import_ok = (
            import_result["returnCode"] == 0
            and not import_result["timedOut"]
            and not import_result["engineIssues"]
        )
        generated_imports = {}
        if import_ok:
            try:
                generated_imports = read_generated_imports(copy_root, image_import_relatives)
            except (ValueError, OSError) as exc:
                import_ok = False
                diagnostics.append({"stage": "image_import", "message": str(exc)})
        requirements.append(
            {"id": "godot.fresh_import", "status": "PASS" if import_ok else "FAIL", "evidence": "clean temporary project copy"}
        )
        if not import_ok:
            diagnostics.append({"stage": "fresh_import", "message": "fresh headless import failed or emitted engine errors"})

        if import_ok:
            smoke_argv = sandboxed_godot_argv(
                godot,
                ["--headless", "--path", str(copy_root), "--script", "res://.studio_verifier/runtime_smoke.gd",
                 "--log-file", str(runtime.tmp / "smoke.log")],
                project_root=copy_root,
                runtime=runtime,
            )
            smoke_result = _command(
                godot, smoke_argv, copy_root, timeout, env=runtime.environment()
            )
            commands.append({"name": "backend_runtime_smoke", **smoke_result})
            smoke_ok = (
                smoke_result["returnCode"] == 0
                and not smoke_result["timedOut"]
                and not smoke_result["engineIssues"]
                and "STUDIO_BACKEND_RUNTIME_SMOKE_OBSERVED" in str(smoke_result["stdout"])
            )
            requirements.append(
                {"id": "godot.main_scene_smoke", "status": "PASS" if smoke_ok else "FAIL", "evidence": "backend-owned harness loaded, instantiated, and pumped the configured main scene"}
            )
            if not smoke_ok:
                diagnostics.append({"stage": "runtime_smoke", "message": "main-scene runtime smoke failed or emitted engine errors"})
        else:
            smoke_ok = False
            requirements.append({"id": "godot.main_scene_smoke", "status": "BLOCKED", "evidence": "fresh import did not pass"})

        try:
            after_inventory = _verification_source_inventory(copy_root)
            for path, data in generated_imports.items():
                if after_inventory.get(path) != data:
                    raise GeneralVerificationError("disposable image import metadata changed during runtime: " + path)
                del after_inventory[path]
            changed_copy_paths = _inventory_changes(source_inventory, after_inventory)
        except GeneralVerificationError as exc:
            changed_copy_paths = [str(exc)]
        copy_immutable = not changed_copy_paths
        requirements.append({
            "id": "verification_copy.source_immutable",
            "status": "PASS" if copy_immutable else "FAIL",
            "evidence": {
                "inventory": "per-file exact contents; .godot cache and validated disposable image metadata excluded",
                "disposableImageImports": list(generated_imports),
                "changedPaths": changed_copy_paths[:40],
            },
        })
        if not copy_immutable:
            diagnostics.append({
                "stage": "verification_copy",
                "message": "Godot changed or added files outside the disposable .godot cache: "
                + ", ".join(changed_copy_paths[:40]),
            })

    requirements.append(
        {"id": "user.acceptance", "status": "NOT_TESTED", "evidence": "general gameplay, visual quality, controls, and user-experience requirements require human review unless a trusted adapter provides explicit assertions"}
    )
    report["userAcceptance"] = [
        {
            "id": requirement["id"],
            "text": requirement["text"],
            "status": "NOT_TESTED",
            "verificationRequested": requirement.get("verification", "manual"),
            "needsReview": True,
        }
        for requirement in normalized["requirements"]
    ]
    copy_immutable = all(
        requirement.get("id") != "verification_copy.source_immutable"
        or requirement.get("status") == "PASS"
        for requirement in requirements
    )
    if import_ok and smoke_ok and copy_immutable:
        report["status"] = "PASS"
        report["technicalStatus"] = "PASS"
        checks.extend(["fresh Godot import", "backend-owned main-scene runtime smoke"])
    else:
        report["status"] = "FAIL"
        report["technicalStatus"] = "FAIL"
    report["certificationScope"] = "general-2d technical import and main-scene smoke only; no automatic gameplay or visual acceptance"
    return report

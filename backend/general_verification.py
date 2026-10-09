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


def audit_general_scope(
    project: str | os.PathLike[str],
    base_commit: str,
    document: Mapping[str, object],
    *,
    allow_engine_cache: bool = False,
    service_records: Mapping[str, str] | None = None,
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
    unauthorized = [path for path in changed if not _safe_policy_path(path)]
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
                       and path not in bound_paths]
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


def _command(godot: str, argv: list[str], cwd: Path | None, timeout: float) -> dict[str, object]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
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
        "sandbox": {"status": "NOT_APPLIED", "boundary": "cooperative_local_execution"},
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
    try:
        normalized = validate_document(dict(document))
        paths = audit_general_scope(
            root, base_commit, normalized, service_records=service_records
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
    version = _godot_version(godot, min(timeout, 10.0))
    commands.append({"name": "version", **version})
    if version["returnCode"] != 0 or version["timedOut"]:
        requirements.append({"id": "godot.version", "status": "FAIL", "evidence": "version query failed"})
        diagnostics.append({"stage": "godot", "message": "could not determine Godot engine version"})
        return report
    version_text = str(version["stdout"]).strip()
    report["engine"] = {"path": godot, "version": version_text}
    requirements.append({"id": "godot.available", "status": "PASS", "evidence": version_text})

    with tempfile.TemporaryDirectory(prefix="studio-general-verify-") as temp_name:
        temp_root = Path(temp_name)
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
        except OSError as exc:
            diagnostics.append({"stage": "prepare", "message": f"could not create clean verifier copy: {exc}"})
            requirements.append({"id": "copy.clean", "status": "FAIL", "evidence": str(exc)})
            return report

        import_result = _command(
            godot,
            [godot, "--headless", "--path", str(copy_root), "--editor", "--import", "--quit"],
            copy_root,
            timeout,
        )
        commands.append({"name": "fresh_import", **import_result})
        import_ok = (
            import_result["returnCode"] == 0
            and not import_result["timedOut"]
            and not import_result["engineIssues"]
        )
        requirements.append(
            {"id": "godot.fresh_import", "status": "PASS" if import_ok else "FAIL", "evidence": "clean temporary project copy"}
        )
        if not import_ok:
            diagnostics.append({"stage": "fresh_import", "message": "fresh headless import failed or emitted engine errors"})

        if import_ok:
            smoke_result = _command(
                godot,
                [godot, "--headless", "--path", str(copy_root), "--script", "res://.studio_verifier/runtime_smoke.gd"],
                copy_root,
                timeout,
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
    if import_ok and smoke_ok:
        report["status"] = "PASS"
        report["technicalStatus"] = "PASS"
        checks.extend(["fresh Godot import", "backend-owned main-scene runtime smoke"])
    else:
        report["status"] = "FAIL"
        report["technicalStatus"] = "FAIL"
    report["certificationScope"] = "general-2d technical import and main-scene smoke only; no automatic gameplay or visual acceptance"
    return report

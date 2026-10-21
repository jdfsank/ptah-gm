"""Trusted, bounded preparation of Godot's script UID sidecars before sealing.

Godot may create ``.gd.uid`` files on a first editor import. This module runs
that import against a disposable source copy, permits writes only to the
precomputed missing UID sidecars, exact missing image import metadata and the private engine runtime/cache, and
copies back only exact, valid sidecar bytes. The normal verifier can then keep
its exact source inventory immutable check.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .general_verification import (
    ENGINE_ERRORS,
    GODOT_UID,
    GeneralVerificationError,
    _is_supported_uid_sidecar_path,
    _inventory_changes,
    _verification_source_inventory,
    audit_general_scope,
)


_COPY_IGNORED = frozenset({".git", ".godot", ".godotmaker", "__pycache__", ".studio_verifier"})
_GODOT_VERSION = re.compile(r"(?m)^\s*\d+\.\d+(?:\.\d+)?[^\r\n]*$")
_UID_EVIDENCE_NAME = "uid-preparation.json"
_UID_EVIDENCE_MAX_BYTES = 1024 * 1024
_UID_EVIDENCE_WRITE_BOUNDARY = "Godot child process tree; only listed missing .gd.uid paths writable"
_IMAGE_IMPORT_EVIDENCE_WRITE_BOUNDARY = (
    "Godot child process tree; listed missing .gd.uid and exact missing image .import paths "
    "in quarantine writable; only UID sidecars copied back"
)
_UID_EVIDENCE_METHOD = "quarantine-godot-editor-recovery-import"


@dataclass(frozen=True)
class UIDPreparationResult:
    """Exact output and engine identity from one quarantine import."""

    input_commit: str
    engine_version: str
    sidecars: Mapping[str, bytes]
    image_imports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Keep the trusted byte result stable after construction so a caller
        # cannot silently rewrite the evidence later through a retained dict.
        object.__setattr__(self, "sidecars", MappingProxyType(dict(self.sidecars)))

    def evidence(self, source_commit: str) -> dict[str, object]:
        """Build a persistent record that the caller can store with the artifact."""
        if not isinstance(source_commit, str) or not source_commit.strip():
            raise GeneralVerificationError("source_commit is required to bind UID preparation evidence")
        return {
            "schemaVersion": "studio.uid-preparation.v1",
            "method": _UID_EVIDENCE_METHOD,
            "inputCommit": self.input_commit,
            "sourceCommit": source_commit,
            "engineVersion": self.engine_version,
            "writeBoundary": _IMAGE_IMPORT_EVIDENCE_WRITE_BOUNDARY if self.image_imports else _UID_EVIDENCE_WRITE_BOUNDARY,
            "sidecars": [
                {"path": path, "content": content.decode("ascii")}
                for path, content in sorted(self.sidecars.items())
            ],
        }


def _read_uid_evidence_file(artifact_directory: str | os.PathLike[str]) -> bytes | None:
    """Read the evidence file through no-follow directory/file descriptors."""
    raw_root = Path(artifact_directory).expanduser()
    if raw_root.is_symlink():
        raise GeneralVerificationError("artifact directory cannot be a symlink")
    try:
        root = raw_root.resolve(strict=True)
    except OSError as exc:
        raise GeneralVerificationError(f"artifact directory is unavailable: {exc}") from exc
    if not root.is_dir():
        raise GeneralVerificationError("artifact directory is not a directory")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if (
        nofollow is None
        or directory_flag is None
        or os.open not in getattr(os, "supports_dir_fd", set())
    ):
        raise GeneralVerificationError("platform cannot safely open UID preparation evidence")
    root_flags = os.O_RDONLY | directory_flag | nofollow
    evidence_flags = os.O_RDONLY | directory_flag | nofollow
    file_flags = os.O_RDONLY | nofollow
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise GeneralVerificationError(f"cannot safely open artifact directory: {exc}") from exc
    try:
        try:
            evidence_fd = os.open("evidence", evidence_flags, dir_fd=root_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise GeneralVerificationError(f"artifact evidence directory is unsafe: {exc}") from exc
        try:
            try:
                descriptor = os.open(_UID_EVIDENCE_NAME, file_flags, dir_fd=evidence_fd)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise GeneralVerificationError(f"UID preparation evidence file is unsafe: {exc}") from exc
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise GeneralVerificationError("UID preparation evidence must be a regular file")
                if before.st_nlink != 1:
                    raise GeneralVerificationError("UID preparation evidence cannot be hard-linked")
                if before.st_size > _UID_EVIDENCE_MAX_BYTES:
                    raise GeneralVerificationError("UID preparation evidence exceeds the size limit")
                data = bytearray()
                while len(data) <= _UID_EVIDENCE_MAX_BYTES:
                    chunk = os.read(
                        descriptor,
                        min(64 * 1024, _UID_EVIDENCE_MAX_BYTES + 1 - len(data)),
                    )
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(descriptor)
                identity_before = (
                    before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
                )
                identity_after = (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
                )
                if identity_before != identity_after:
                    raise GeneralVerificationError("UID preparation evidence changed while being read")
                if len(data) > _UID_EVIDENCE_MAX_BYTES:
                    raise GeneralVerificationError("UID preparation evidence exceeds the size limit")
                return bytes(data)
            finally:
                os.close(descriptor)
        finally:
            os.close(evidence_fd)
    finally:
        os.close(root_fd)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise GeneralVerificationError(f"UID preparation evidence has a duplicate JSON key: {key}")
        value[key] = item
    return value


def load_uid_preparation_evidence(
    artifact_directory: str | os.PathLike[str],
    *,
    input_commit: str,
    source_commit: str,
) -> tuple[Mapping[str, bytes], str | None]:
    """Load trusted sidecar bytes bound to one input and sealed source commit.

    Missing evidence remains valid for legacy artifacts that do not contain
    newly introduced UID sidecars. A later scope audit still rejects any such
    sidecar because the returned empty mapping grants no new UID allowance.
    """
    if not isinstance(input_commit, str) or not input_commit.strip():
        raise GeneralVerificationError("input_commit is required to bind UID preparation evidence")
    if not isinstance(source_commit, str) or not source_commit.strip():
        raise GeneralVerificationError("source_commit is required to bind UID preparation evidence")
    raw = _read_uid_evidence_file(artifact_directory)
    if raw is None:
        return MappingProxyType({}), None
    try:
        evidence = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GeneralVerificationError(f"UID preparation evidence is not valid UTF-8 JSON: {exc}") from exc
    expected_keys = {
        "schemaVersion", "method", "inputCommit", "sourceCommit",
        "engineVersion", "writeBoundary", "sidecars",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected_keys:
        raise GeneralVerificationError("UID preparation evidence has an unsupported schema")
    if evidence["schemaVersion"] != "studio.uid-preparation.v1":
        raise GeneralVerificationError("UID preparation evidence schema version is unsupported")
    if evidence["method"] != _UID_EVIDENCE_METHOD:
        raise GeneralVerificationError("UID preparation evidence method is unsupported")
    if evidence["writeBoundary"] not in {_UID_EVIDENCE_WRITE_BOUNDARY, _IMAGE_IMPORT_EVIDENCE_WRITE_BOUNDARY}:
        raise GeneralVerificationError("UID preparation evidence write boundary is unsupported")
    if evidence["inputCommit"] != input_commit or evidence["sourceCommit"] != source_commit:
        raise GeneralVerificationError("UID preparation evidence is bound to a different input or source commit")
    engine_version = evidence["engineVersion"]
    if (
        not isinstance(engine_version, str)
        or not engine_version
        or engine_version != engine_version.strip()
        or _GODOT_VERSION.fullmatch(engine_version) is None
    ):
        raise GeneralVerificationError("UID preparation evidence has an invalid Godot engine version")
    entries = evidence["sidecars"]
    if not isinstance(entries, list) or len(entries) > 5000:
        raise GeneralVerificationError("UID preparation evidence sidecars must be a bounded list")
    sidecars: dict[str, bytes] = {}
    uid_values: set[bytes] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "content"}:
            raise GeneralVerificationError("UID preparation evidence contains an invalid sidecar entry")
        path = entry["path"]
        content = entry["content"]
        if not isinstance(path, str) or not _is_supported_uid_sidecar_path(path):
            raise GeneralVerificationError(f"UID preparation evidence contains an unsupported path: {path!r}")
        if path in sidecars:
            raise GeneralVerificationError(f"UID preparation evidence contains a duplicate path: {path}")
        if not isinstance(content, str):
            raise GeneralVerificationError(f"UID preparation evidence UID content is not text: {path}")
        try:
            encoded = content.encode("ascii")
        except UnicodeEncodeError as exc:
            raise GeneralVerificationError(f"UID preparation evidence UID is not ASCII: {path}") from exc
        if GODOT_UID.fullmatch(encoded) is None:
            raise GeneralVerificationError(f"UID preparation evidence contains an invalid UID: {path}")
        if encoded in uid_values:
            raise GeneralVerificationError(f"UID preparation evidence contains a duplicate UID: {path}")
        uid_values.add(encoded)
        sidecars[path] = encoded
    return MappingProxyType(sidecars), engine_version


def _inventory_for_preparation(project: Path) -> dict[str, bytes]:
    """Capture exact project files while excluding private/cache trees."""
    inventory: dict[str, bytes] = {}
    count = 0
    total = 0
    for directory, dirs, files in os.walk(project, followlinks=False):
        current = Path(directory)
        for dirname in list(dirs):
            child = current / dirname
            if child.is_symlink():
                raise GeneralVerificationError(
                    f"UID preparation project contains a directory symlink: {child.relative_to(project)}"
                )
            if dirname in _COPY_IGNORED:
                dirs.remove(dirname)
        for filename in files:
            path = current / filename
            relative = path.relative_to(project).as_posix()
            if path.is_symlink():
                raise GeneralVerificationError(
                    f"UID preparation project contains a file symlink: {relative}"
                )
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise GeneralVerificationError(f"cannot read project source {relative}: {exc}") from exc
            count += 1
            total += len(data)
            if count > 5000 or len(data) > 64 * 1024 * 1024 or total > 512 * 1024 * 1024:
                raise GeneralVerificationError("UID preparation source inventory exceeds project limits")
            inventory[relative] = data
    return inventory


def _supported_script_uid_paths(inventory: Mapping[str, bytes]) -> tuple[list[str], dict[bytes, str]]:
    """Return missing metadata paths and reject malformed/duplicate existing IDs."""
    missing: list[str] = []
    by_uid: dict[bytes, str] = {}
    scripts = sorted(
        path for path in inventory
        if path.endswith(".gd") and _is_supported_uid_sidecar_path(path + ".uid")
    )
    for source_path in scripts:
        sidecar = source_path + ".uid"
        content = inventory.get(sidecar)
        if content is None:
            missing.append(sidecar)
            continue
        if GODOT_UID.fullmatch(content) is None:
            raise GeneralVerificationError(f"existing Godot UID sidecar is malformed: {sidecar}")
        if content in by_uid:
            raise GeneralVerificationError(
                f"existing Godot UID sidecars duplicate an identifier: {by_uid[content]}, {sidecar}"
            )
        by_uid[content] = sidecar
    return missing, by_uid


def _run_scoped_godot(
    executable: str,
    arguments: list[str],
    *,
    project_root: Path,
    runtime_root: Path,
    timeout: float,
    uid_write_paths: tuple[Path, ...] = (),
    image_import_write_paths: tuple[Path, ...] = (),
    editor_engine_version: str | None = None,
) -> dict[str, object]:
    """Run one Godot command inside the shared strict local runtime sandbox."""
    from runners.godot_runtime import GodotRuntime, sandboxed_godot_argv

    runtime = GodotRuntime.create(str(runtime_root.resolve()))
    if editor_engine_version is not None:
        runtime.configure_editor_tls(editor_engine_version, executable)
    argv = sandboxed_godot_argv(
        executable,
        arguments,
        project_root=project_root,
        runtime=runtime,
        uid_write_paths=uid_write_paths,
        image_import_write_paths=image_import_write_paths,
    )
    try:
        completed = subprocess.run(
            argv,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=runtime.environment(),
        )
        return_code: int | None = completed.returncode
        stdout, stderr, timed_out = completed.stdout, completed.stderr, False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return_code, timed_out = None, True
    except OSError as exc:
        stdout, stderr = "", str(exc)
        return_code, timed_out = None, False
    return {
        "argv": argv,
        "cwd": str(project_root),
        "returnCode": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "engineIssues": ENGINE_ERRORS.findall(stdout + "\n" + stderr),
    }


def _version_or_fail(result: Mapping[str, object]) -> str:
    output = str(result.get("stdout", "")).strip()
    if result.get("returnCode") != 0 or result.get("timedOut") or result.get("engineIssues"):
        raise GeneralVerificationError("quarantine Godot version query failed")
    match = _GODOT_VERSION.search(output)
    if match is None:
        raise GeneralVerificationError("quarantine Godot did not report a recognizable engine version")
    return match.group(0).strip()


def _import_or_fail(result: Mapping[str, object]) -> None:
    if result.get("returnCode") != 0 or result.get("timedOut") or result.get("engineIssues"):
        details = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        raise GeneralVerificationError(
            "quarantine Godot import failed or emitted engine errors: " + details[-3000:]
        )


def _safe_rollback_sidecars(project: Path, sidecars: Mapping[str, bytes]) -> None:
    for relative, expected in sidecars.items():
        path = project.joinpath(*Path(relative).parts)
        try:
            if path.is_file() and not path.is_symlink() and path.read_bytes() == expected:
                path.unlink()
        except OSError:
            # Preserve the original error; incomplete cleanup is visible to the
            # next strict scope audit and cannot be sealed as prepared output.
            pass


def prepare_godot_uid_sidecars(
    project: str | os.PathLike[str],
    *,
    base_commit: str,
    document: Mapping[str, object],
    godot_path: str | os.PathLike[str],
    timeout: float = 45.0,
    service_records: Mapping[str, str] | None = None,
) -> UIDPreparationResult:
    """Generate and validate missing UID sidecars before the artifact commit.

    The input tree is audited before any import, so model-authored or otherwise
    untrusted changed UID sidecars are rejected. Godot runs on a disposable
    project copy; only new, valid `.gd.uid` files for exact missing sidecars are
    applied back to the real workspace.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise GeneralVerificationError("UID preparation timeout must be greater than 0 and at most 120 seconds")
    root = Path(project).expanduser().resolve()
    executable = Path(godot_path).expanduser().resolve(strict=False)
    if not executable.is_file():
        raise GeneralVerificationError("configured Godot executable is missing")

    # This first audit deliberately has no UID allowance. It rejects any
    # producer-created sidecar before a trusted import can observe it.
    audit_general_scope(root, base_commit, document, service_records=service_records)
    initial_inventory = _inventory_for_preparation(root)
    allowed_uid_relatives, existing_uids = _supported_script_uid_paths(initial_inventory)

    generated: dict[str, bytes] = {}
    created_in_workspace: dict[str, bytes] = {}
    engine_version = ""
    try:
        with tempfile.TemporaryDirectory(prefix="studio-uid-prepare-") as temp_name:
            temp_root = Path(temp_name).resolve()
            copy_root = temp_root / "project"
            shutil.copytree(
                root,
                copy_root,
                ignore=shutil.ignore_patterns(*_COPY_IGNORED),
            )
            copy_inventory = _inventory_for_preparation(copy_root)
            if copy_inventory != initial_inventory:
                raise GeneralVerificationError("quarantine copy differs from the pre-import source inventory")

            runtime_root = temp_root / "godot-runtime"
            version_result = _run_scoped_godot(
                str(executable), ["--version"],
                project_root=copy_root, runtime_root=runtime_root,
                timeout=min(float(timeout), 10.0),
            )
            engine_version = _version_or_fail(version_result)
            import_log = runtime_root / "tmp" / "uid-import.log"
            uid_write_paths = tuple(copy_root.joinpath(*Path(path).parts) for path in allowed_uid_relatives)
            from runners.image_imports import missing_image_imports, read_generated_imports
            image_import_relatives = missing_image_imports(copy_root, copy_inventory)
            import_result = _run_scoped_godot(
                str(executable),
                ["--headless", "--path", str(copy_root), "--editor", "--recovery-mode", "--import", "--quit",
                 "--log-file", str(import_log)],
                project_root=copy_root, runtime_root=runtime_root,
                timeout=float(timeout), uid_write_paths=uid_write_paths,
                image_import_write_paths=tuple(copy_root / path for path in image_import_relatives),
                editor_engine_version=engine_version,
            )
            _import_or_fail(import_result)
            after_import = _inventory_for_preparation(copy_root)
            try:
                # These metadata files exist only in quarantine. They are
                # validated and excluded individually, never copied to source.
                generated_imports = read_generated_imports(copy_root, image_import_relatives)
            except (ValueError, OSError) as exc:
                raise GeneralVerificationError(f"invalid quarantine image import metadata: {exc}") from exc
            for path, data in generated_imports.items():
                if after_import.get(path) != data:
                    raise GeneralVerificationError("quarantine image import metadata changed during inventory")
                del after_import[path]
            changed = _inventory_changes(copy_inventory, after_import)
            invalid_changes = [
                path for path in changed
                if path in copy_inventory
                or path not in after_import
                or not _is_supported_uid_sidecar_path(path)
                or path not in allowed_uid_relatives
            ]
            if invalid_changes:
                raise GeneralVerificationError(
                    "quarantine Godot changed files outside the missing UID allowlist: "
                    + ", ".join(invalid_changes[:40])
                )
            generated = {path: after_import[path] for path in changed}
            missing_outputs = sorted(set(allowed_uid_relatives) - set(generated))
            if missing_outputs:
                raise GeneralVerificationError(
                    "quarantine Godot did not generate every missing UID sidecar: "
                    + ", ".join(missing_outputs[:40])
                )
            seen_uids = set(existing_uids)
            for relative, content in generated.items():
                if GODOT_UID.fullmatch(content) is None:
                    raise GeneralVerificationError(f"quarantine Godot generated malformed UID content: {relative}")
                if content in seen_uids:
                    raise GeneralVerificationError(f"quarantine Godot generated a duplicate UID: {relative}")
                seen_uids.add(content)
                source_relative = relative[:-4]
                if source_relative not in after_import:
                    raise GeneralVerificationError(f"quarantine Godot generated a UID without its source: {relative}")

        if not generated:
            # No mutation is necessary; still return the engine identity and
            # let the caller persist a complete, empty preparation record.
            return UIDPreparationResult(base_commit, engine_version, {}, image_import_relatives)

        # The original workspace must still match the exact inventory that was
        # copied before applying any trusted output.
        if _inventory_for_preparation(root) != initial_inventory:
            raise GeneralVerificationError("project source changed during quarantine UID preparation")

        for relative, content in sorted(generated.items()):
            sidecar_path = root.joinpath(*Path(relative).parts)
            current = root
            for part in Path(relative).parts:
                current = current / part
                if current.is_symlink():
                    raise GeneralVerificationError(f"UID destination cannot contain symlinks: {relative}")
            if sidecar_path.exists():
                raise GeneralVerificationError(f"UID destination appeared during preparation: {relative}")
            try:
                with sidecar_path.open("xb") as stream:
                    stream.write(content)
            except OSError as exc:
                raise GeneralVerificationError(f"cannot install prepared UID sidecar {relative}: {exc}") from exc
            created_in_workspace[relative] = content

        expected_inventory = dict(initial_inventory)
        expected_inventory.update(generated)
        if _inventory_for_preparation(root) != expected_inventory:
            raise GeneralVerificationError("applying prepared UID sidecars changed unexpected project files")

        # Confirm the exact output can enter the ordinary audited source commit.
        audit_general_scope(
            root,
            base_commit,
            document,
            service_records=service_records,
            prepared_uid_sidecars=generated,
        )
        return UIDPreparationResult(base_commit, engine_version, dict(generated), image_import_relatives)
    except Exception:
        if created_in_workspace:
            _safe_rollback_sidecars(root, created_in_workspace)
        raise

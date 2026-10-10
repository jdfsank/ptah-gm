"""Narrow adapter to the pinned GodotMaker-non-pk approval consumer.

The legacy Velvet adapter remains independent. Generic projects always use the
repository's exact ``sources/GodotMaker-non-pk/tools`` consumer and fixed
project-relative binding path; callers cannot select alternate tool paths.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from .gm_module_loading import PINNED_MODULE_LOCK

REPO_ROOT = Path(__file__).resolve().parents[1]
GM_TOOLS = REPO_ROOT / "sources" / "GodotMaker-non-pk" / "tools"
GM_REVIEW = GM_TOOLS / "gm_review.py"
APPROVAL_BINDING_REL = Path(".godotmaker") / "frontend-approval.json"
_LOAD_LOCK = PINNED_MODULE_LOCK


class GMIntegrationError(RuntimeError):
    """The project or trusted GM integration could not be safely used."""


def _load_review_support():
    path = GM_TOOLS / "review_support.py"
    if not path.is_file() or path.resolve() != path:
        raise GMIntegrationError("Pinned GM review support is unavailable")
    name = "_ptah_pinned_general_gm_review_support"
    # review_support uses historical bare imports. Temporarily bind those names
    # to the exact pinned sibling modules, then restore the host interpreter's
    # namespace so another project cannot inherit these aliases.
    dependencies = ("agent_runtime", "git_baseline", "frontend_approval", "append_stage_event")
    with _LOAD_LOCK:
        module = sys.modules.get(name)
        if module is not None:
            return module
        saved = {dep: sys.modules.get(dep) for dep in dependencies}
        try:
            for dep in dependencies:
                dep_path = GM_TOOLS / f"{dep}.py"
                if not dep_path.is_file() or dep_path.resolve() != dep_path:
                    raise GMIntegrationError(
                        f"Pinned GM dependency is unavailable: {dep}"
                    )
                dep_spec = importlib.util.spec_from_file_location(dep, dep_path)
                if dep_spec is None or dep_spec.loader is None:
                    raise GMIntegrationError(
                        f"Pinned GM dependency cannot be loaded: {dep}"
                    )
                dep_module = importlib.util.module_from_spec(dep_spec)
                sys.modules[dep] = dep_module
                dep_spec.loader.exec_module(dep_module)
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise GMIntegrationError("Pinned GM review support cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(name, None)
                raise
            return module
        finally:
            for dep, prior in saved.items():
                if prior is None:
                    sys.modules.pop(dep, None)
                else:
                    sys.modules[dep] = prior


def _project(project_dir: Path) -> Path:
    path = Path(project_dir).resolve(strict=True)
    if not path.is_dir():
        raise GMIntegrationError("GM project directory is unavailable")
    return path


def spec_ref(project_dir: Path) -> str:
    """Return the current GM-normalized specification's Git object identity."""
    project = _project(project_dir)
    review = _load_review_support()
    try:
        spec = review.extract_spec(project)
        return review.spec_git_ref(spec, project)
    except Exception as exc:
        raise GMIntegrationError(
            f"Current project specification is not GM-ready: {exc}"
        ) from exc


def _required_packet_value(packet: Mapping[str, object], key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GMIntegrationError(f"Approval packet is missing {key}")
    return value


def register(
    project_dir: Path,
    store_path: Path,
    operator_id: str,
    project_id: str,
    packet: Mapping[str, object],
) -> Path:
    """Register the backend-owned approval DB against a frozen packet."""
    project = _project(project_dir)
    requested_store = Path(store_path)
    if requested_store.is_symlink():
        raise GMIntegrationError("Approval store must not be a symbolic link")
    store = requested_store.resolve(strict=True)
    if not store.is_file():
        raise GMIntegrationError("Approval store must be a regular file")
    info = store.stat()
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise GMIntegrationError("Approval store must be private to its owner")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise GMIntegrationError("Approval store must be owned by the current user")
    if not isinstance(packet, Mapping):
        raise GMIntegrationError("Approval packet is invalid")
    if (
        not isinstance(operator_id, str)
        or not operator_id.strip()
        or not isinstance(project_id, str)
        or not project_id.strip()
    ):
        raise GMIntegrationError("Operator and project identities are required")
    test_data, production_authorized = (
        packet.get("testData"),
        packet.get("productionAuthorized"),
    )
    if type(test_data) is not bool or type(production_authorized) is not bool:
        raise GMIntegrationError("Approval packet authorization flags must be booleans")
    if test_data == production_authorized:
        raise GMIntegrationError(
            "Approval packet flags must identify exactly one environment"
        )
    if packet.get("projectId") != project_id:
        raise GMIntegrationError("Approval packet belongs to a different project")
    packet_spec_ref = packet.get("gmSpecRef")
    if packet_spec_ref is not None and packet_spec_ref != spec_ref(project):
        raise GMIntegrationError("Approval packet GM specification identity is stale")

    # Test mode is deliberately registered for diagnostics only. It cannot
    # enter the production GM gate and cannot call confirm_spec below.
    binding = {
        "schemaVersion": 1,
        "storePath": str(store),
        "operatorId": operator_id,
        "projectId": project_id,
        "testData": test_data,
        "productionAuthorized": production_authorized,
        "proposalId": _required_packet_value(packet, "proposalId"),
        "packetId": _required_packet_value(packet, "packetId"),
        "jobId": _required_packet_value(packet, "jobId"),
        "candidateId": packet.get("candidateId"),
        "revision": str(packet.get("proposalRevision")),
    }
    if binding["candidateId"] is not None and not isinstance(
        binding["candidateId"], str
    ):
        raise GMIntegrationError("Approval packet candidateId is invalid")
    destination = project / APPROVAL_BINDING_REL
    parent = destination.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or destination.is_symlink():
        raise GMIntegrationError("Approval binding path cannot contain symlinks")
    payload = (
        json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
    temporary = parent / ".frontend-approval.json.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return destination


def confirm_spec(project_dir: Path, event_id: str) -> dict:
    """Consume a frontend event through the actual pinned production GM CLI."""
    project = _project(project_dir)
    review = _load_review_support()
    binding = review.frontend_approval_binding(project)
    if binding["testData"] is True or binding["productionAuthorized"] is not True:
        raise GMIntegrationError(
            "Test or unauthorized approvals cannot enter the production GM gate"
        )
    if not isinstance(event_id, str) or not event_id.strip():
        raise GMIntegrationError("Frontend approval event id is required")
    if not GM_REVIEW.is_file() or GM_REVIEW.resolve() != GM_REVIEW:
        raise GMIntegrationError("Pinned GM review command is unavailable")
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(GM_REVIEW),
                "confirm-spec",
                "--project",
                str(project),
                "--frontend-event-id",
                event_id,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GMIntegrationError(
            f"Pinned GM specification confirmation failed to run: {exc}"
        ) from exc
    try:
        response = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GMIntegrationError(
            "Pinned GM specification confirmation returned invalid JSON"
        ) from exc
    if (
        result.returncode != 0
        or not isinstance(response, dict)
        or response.get("result") != "PASS"
    ):
        reason = (
            response.get("reason", "GM specification confirmation was rejected")
            if isinstance(response, dict)
            else "GM specification confirmation was rejected"
        )
        raise GMIntegrationError(str(reason))
    return response


def spec_confirmed(project_dir: Path) -> bool:
    """Ask GM's own matching predicate whether the current spec is confirmed."""
    project = _project(project_dir)
    review = _load_review_support()
    try:
        spec = review.extract_spec(project)
        current_ref = review.spec_git_ref(spec, project)
        events = review.read_events(project)
        return any(
            event.get("role") == "gdd"
            and review._spec_confirmation_matches(event, spec, current_ref, project)
            for event in events
        )
    except Exception as exc:  # noqa: BLE001 - Inspection errors still block production.
        raise GMIntegrationError(f"GM 规格确认记录复核失败：{exc}") from exc


__all__ = [
    "GMIntegrationError",
    "confirm_spec",
    "register",
    "spec_confirmed",
    "spec_ref",
]

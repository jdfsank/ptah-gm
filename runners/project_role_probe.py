"""Fresh deny-default capability probes for ProjectRunner registration."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.role_evidence import REQUIRED_ROLE_CHECKS
from runners.common import LocalJournal
from runners.project import ProjectRunner

GODOT = Path("/Applications/Godot.app/Contents/MacOS/Godot")
EVIDENCE = ROOT / "evidence/workflow/studio-acceptance-project-registration-20261013.json"
PROJECT_CAPABILITIES = ("verification-isolated-v1", "preview-isolated-v1")
PROJECT_ROLE_CHECKS = {
    capability: REQUIRED_ROLE_CHECKS[capability]
    for capability in PROJECT_CAPABILITIES
}


class _AckAPI:
    """A process-local API stub; the probe never contacts the Studio backend."""

    def __init__(self, material: dict | None = None):
        self.reports: list[dict] = []
        self.material = material or {}
        self.registration_body: dict | None = None

    def request(self, method, route, body=None):
        if method == "POST" and route == "/internal/v1/register":
            self.registration_body = body
            return {"registered": True, "runnerId": body["runnerId"]}
        if method == "GET" and route.endswith("/input"):
            return self.material
        if method == "POST" and route == "/internal/v1/reports":
            self.reports.append(body)
            return {
                "schemaVersion": "studio.message.v1",
                "kind": "report_ack",
                **{key: body[key] for key in
                   ("storeId", "projectId", "attemptId", "runnerId", "reportId")},
                "disposition": "recorded",
            }
        if method == "POST" and route == "/internal/v1/heartbeat":
            return {"cancelRequested": False}
        raise RuntimeError(f"unexpected process-local API call: {method} {route}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _gd_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _auth_canary() -> tuple[Path | None, dict[str, bool]]:
    """Use only the configured provider-auth TOML as a physical canary.

    The file bytes stay in memory for before/after equality; no values, provider
    names, or credentials are included in evidence.
    """
    config_exists = False
    configured_provider = False
    has_provider_auth_fields = False
    try:
        auth_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).resolve(strict=True)
        config_path = auth_root / "config.toml"
        if config_path.is_symlink() or not config_path.is_file():
            return None, {
                "configExists": False,
                "configuredProvider": False,
                "containsProviderAuthFields": False,
            }
        config_exists = True
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        provider_key = config.get("model_provider")
        configured_provider = isinstance(provider_key, str) and bool(provider_key.strip())
        provider = (config.get("model_providers") or {}).get(provider_key, {}) if configured_provider else {}
        if isinstance(provider, dict):
            has_provider_auth_fields = any(bool(provider.get(name)) for name in (
                "experimental_bearer_token", "env_key", "http_headers", "env_http_headers",
            ))
        return (config_path if has_provider_auth_fields else None), {
            "configExists": config_exists,
            "configuredProvider": configured_provider,
            "containsProviderAuthFields": has_provider_auth_fields,
        }
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, TypeError, AttributeError):
        return None, {
            "configExists": config_exists,
            "configuredProvider": configured_provider,
            "containsProviderAuthFields": False,
        }


def _listener(family: int, host: str) -> socket.socket:
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, 0))
    listener.listen(8)
    listener.setblocking(False)
    return listener


def _accepted(listener: socket.socket) -> bool:
    try:
        client, _address = listener.accept()
    except BlockingIOError:
        return False
    client.close()
    return True


def _main_script(
    accepted_canary: Path,
    sealed_canary: Path,
    external_canaries: dict[str, Path | None],
    ports: dict[str, dict[str, int]],
) -> str:
    probes = [
        'var source_read := FileAccess.open("res://scripts/main.gd", FileAccess.READ)',
        'facts["sourceReadAllowed"] = source_read != null',
        'if source_read != null: source_read.close()',
        'var source_write := FileAccess.open("res://scripts/main.gd", FileAccess.READ_WRITE)',
        'facts["sourceWriteDenied"] = source_write == null',
        'if source_write != null: source_write.close()',
        'var uid_write := FileAccess.open("res://scripts/main.gd.uid", FileAccess.READ_WRITE)',
        'facts["uidSidecarWriteDenied"] = uid_write == null',
        'if uid_write != null: uid_write.close()',
        'facts["cacheWriteAllowed"] = false',
        'var cache_probe := FileAccess.open("res://.godot/project-role-probe.txt", FileAccess.WRITE)',
        'if cache_probe != null:',
        '    cache_probe.store_string("private cache")',
        '    cache_probe.close()',
        '    facts["cacheWriteAllowed"] = true',
        'facts["privateUserWriteAllowed"] = false',
        'var user_probe := FileAccess.open("user://project-role-probe.txt", FileAccess.WRITE)',
        'if user_probe != null:',
        '    user_probe.store_string("private user data")',
        '    user_probe.close()',
        '    facts["privateUserWriteAllowed"] = true',
    ]
    for label, path in (("acceptedSource", accepted_canary), ("sealedSource", sealed_canary)):
        probes.extend([
            f'var {label}_read := FileAccess.open({_gd_string(str(path))}, FileAccess.READ)',
            f'facts[{_gd_string(label + "ReadDenied")}] = {label}_read == null',
            f'if {label}_read != null: {label}_read.close()',
            f'var {label}_write := FileAccess.open({_gd_string(str(path))}, FileAccess.READ_WRITE)',
            f'facts[{_gd_string(label + "WriteDenied")}] = {label}_write == null',
            f'if {label}_write != null: {label}_write.close()',
        ])
    for label, path in external_canaries.items():
        if path is None:
            probes.extend([
                f'facts[{_gd_string(label + "ReadDenied")}] = false',
                f'facts[{_gd_string(label + "WriteDenied")}] = false',
            ])
            continue
        probes.extend([
            f'var {label}_read := FileAccess.open({_gd_string(str(path))}, FileAccess.READ)',
            f'facts[{_gd_string(label + "ReadDenied")}] = {label}_read == null',
            f'if {label}_read != null: {label}_read.close()',
            f'var {label}_write := FileAccess.open({_gd_string(str(path))}, FileAccess.READ_WRITE)',
            f'facts[{_gd_string(label + "WriteDenied")}] = {label}_write == null',
            f'if {label}_write != null: {label}_write.close()',
        ])
    peers: list[tuple[str, str, str]] = []
    for service, family_ports in ports.items():
        for family, host in (("ipv4", "127.0.0.1"), ("ipv6", "::1")):
            port = family_ports.get(family)
            key = service + family.title() + "ConnectDenied"
            if port is None or port < 0:
                probes.append(f'facts[{_gd_string(key)}] = false')
                continue
            probes.extend([
                f'var peer_{service}_{family} := StreamPeerTCP.new()',
                f'var error_{service}_{family} := peer_{service}_{family}.connect_to_host({_gd_string(host)}, {port})',
            ])
            peers.append((service, family, key))
    if peers:
        probes.append("OS.delay_msec(300)")
        for service, family, key in peers:
            probes.extend([
                f'peer_{service}_{family}.poll()',
                f'facts[{_gd_string(key)}] = error_{service}_{family} != OK or peer_{service}_{family}.get_status() == StreamPeerTCP.STATUS_ERROR',
            ])
    probes.extend([
        'facts["displayServerName"] = DisplayServer.get_name()',
        'facts["guiDisplayServerActive"] = DisplayServer.get_name() != "headless"',
    ])
    return "\n".join([
        "extends Node2D",
        "func _ready() -> void:",
        "    var facts: Dictionary = {}",
        *["    " + line for line in probes],
        '    print("STUDIO_PROJECT_ROLE_FACTS=" + JSON.stringify(facts))',
        '    print("STUDIO_PROJECT_ROLE_READY")',
        "    await get_tree().create_timer(2.0).timeout",
        "    get_tree().quit()",
        "",
    ])


def _document() -> dict:
    return {
        "schemaVersion": "studio.objects.v1",
        "dimension": "2d",
        "title": "Disposable Project Role Boundary Probe",
        "summary": "Synthetic runner isolation canaries.",
        "objects": [{
            "id": "main-scene",
            "kind": "scene",
            "name": "Main Scene",
            "sourceBindings": ["scenes/main.tscn", "scripts/main.gd"],
            "fields": [],
        }],
        "requirements": [{
            "id": "probe",
            "text": "The disposable project scene runs the role isolation probe.",
            "objectIds": ["main-scene"],
            "verification": "automated",
        }],
    }


def _clean_main_script() -> str:
    return "\n".join([
        "extends Node2D",
        "func _ready() -> void:",
        '    print("STUDIO_PROJECT_ROLE_CLEAN_READY")',
        "    var stop_timer := Timer.new()",
        "    stop_timer.wait_time = 2.0",
        "    stop_timer.one_shot = true",
        "    stop_timer.timeout.connect(_finish_clean_runtime)",
        "    add_child(stop_timer)",
        "    stop_timer.start()",
        "func _finish_clean_runtime() -> void:",
        "    get_tree().quit()",
        "",
    ])


def _write_project(
    project: Path,
    accepted_canary: Path,
    sealed_canary: Path,
    external_canaries: dict[str, Path | None],
    ports: dict[str, dict[str, int]],
) -> dict[str, bytes]:
    (project / "scenes").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "studio").mkdir()
    (project / "design").mkdir()
    files = {
        "project.godot": (
            'config_version=5\n\n[application]\n'
            'config/name="Disposable Project Role Boundary Probe"\n'
            'run/main_scene="res://scenes/main.tscn"\n\n'
            '[display]\nwindow/size/viewport_width=640\n'
            'window/size/viewport_height=360\nwindow/size/window_width_override=640\n'
            'window/size/window_height_override=360\n\n'
            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n'
            'renderer/rendering_method.mobile="gl_compatibility"\n'
        ),
        "scenes/main.tscn": (
            '[gd_scene load_steps=2 format=3]\n\n'
            '[ext_resource type="Script" path="res://scripts/main.gd" id="1"]\n\n'
            '[node name="RoleProbe" type="Node2D"]\nscript = ExtResource("1")\n'
        ),
        "scripts/main.gd": _main_script(accepted_canary, sealed_canary, external_canaries, ports),
        "scripts/main.gd.uid": "uid://dr18mkf2wmbba\n",
        "studio/runtime.gd": "extends RefCounted\n",
        "design/game.json": json.dumps(_document(), ensure_ascii=False, indent=2) + "\n",
    }
    for relative, content in files.items():
        (project / relative).write_text(content, encoding="utf-8")
    return {relative: (project / relative).read_bytes() for relative in files}


def _git(*arguments: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        raise RuntimeError("fixture Git operation failed: " + result.stderr.strip())
    return result.stdout.strip()


def _commit_fixture(project: Path) -> str:
    _git("init", "--quiet", cwd=project)
    _git("config", "user.name", "Studio Disposable Role Probe", cwd=project)
    _git("config", "user.email", "role-probe@example.invalid", cwd=project)
    _git("add", "--all", cwd=project)
    _git("commit", "--quiet", "-m", "sealed disposable role probe", cwd=project)
    return _git("rev-parse", "HEAD", cwd=project)


def _byte_equality(before: dict[str, bytes], project: Path) -> dict[str, dict[str, object]]:
    return {
        name: {
            "unchanged": (project / name).is_file() and (project / name).read_bytes() == content,
            "byteCount": len(content),
        }
        for name, content in before.items()
    }


def _canary_bytes(canaries: dict[str, Path | None]) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {}
    for name, path in canaries.items():
        try:
            result[name] = path.read_bytes() if path is not None and path.is_file() else None
        except OSError:
            result[name] = None
    return result


def _canary_comparison(
    canaries: dict[str, Path | None], before: dict[str, bytes | None]
) -> dict[str, bool]:
    result = {}
    for name, path in canaries.items():
        if path is None:
            result[name] = True
            continue
        original = before.get(name)
        try:
            result[name] = original is not None and path.is_file() and path.read_bytes() == original
        except OSError:
            result[name] = False
    return result


def _parse_facts(text: str) -> dict | None:
    for line in text.splitlines():
        if line.startswith("STUDIO_PROJECT_ROLE_FACTS="):
            try:
                value = json.loads(line.partition("=")[2])
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


def _errors(text: str, *, role: str, command: str) -> list[dict[str, object]]:
    occurrences = []
    for line in text.splitlines():
        normalized = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if not normalized.startswith(("ERROR:", "SCRIPT ERROR:")):
            continue
        network_denial = re.fullmatch(r"ERROR: Connection to remote host failed!?", normalized) is not None
        file_match = re.fullmatch(
            r"ERROR: (?:Cannot open file|Can't open file|Failed to open file|Could not open file) ['\"]([^'\"]+)['\"]\.?",
            normalized,
        )
        occurrences.append({
            "role": role,
            "command": command,
            "line": normalized,
            "expectedDenial": False,
            "expectedCandidate": "network" if network_denial else "file" if file_match else None,
            "expectedTarget": file_match.group(1) if file_match else None,
            "expectedKind": None,
        })
    return occurrences


def _classify_expected_errors(
    occurrences: list[dict[str, object]],
    file_limits: dict[str, tuple[tuple[str, ...], int]],
    network_limit: int,
) -> list[dict[str, object]]:
    used_files: dict[str, int] = {}
    used_network = 0
    classified = []
    for raw in occurrences:
        item = dict(raw)
        candidate = item.get("expectedCandidate")
        if candidate == "network" and used_network < network_limit:
            item["expectedDenial"] = True
            item["expectedKind"] = "network"
            used_network += 1
        elif candidate == "file":
            target = item.get("expectedTarget")
            matching = next((
                (name, limit) for name, (aliases, limit) in file_limits.items()
                if target in aliases
            ), None)
            if matching is not None:
                name, limit = matching
                count = used_files.get(name, 0)
                if count < limit:
                    item["expectedDenial"] = True
                    item["expectedKind"] = "file"
                    item["expectedCanary"] = name
                    used_files[name] = count + 1
        item.pop("expectedCandidate", None)
        item.pop("expectedTarget", None)
        classified.append(item)
    return classified


def _policy_facts(profile: str, project: Path, accepted_source: Path,
                  sealed_artifact_root: Path, *, graphics: bool) -> dict[str, bool]:
    return {
        "denyDefault": "(deny default)" in profile,
        "graphicsGrantMatchesRole": ("IOSurfaceRootUserClient" in profile) is graphics,
        "networkOutboundGrant": "(allow network-outbound)" in profile,
        "projectRootWriteGrant": f'(allow file-write* (subpath "{project}")' in profile,
        "projectCacheWriteGrant": f'(allow file-write* (subpath "{project}/.godot")' in profile,
        "acceptedSourceReadGrantAbsent": f'(allow file-read* (subpath "{accepted_source}")' not in profile,
        "acceptedSourceWriteGrantAbsent": f'(allow file-write* (subpath "{accepted_source}")' not in profile,
        "sealedArtifactReadGrantAbsent": f'(allow file-read* (subpath "{sealed_artifact_root}")' not in profile,
        "sealedArtifactWriteGrantAbsent": f'(allow file-write* (subpath "{sealed_artifact_root}")' not in profile,
        "acceptedSourceExplicitReadDeny": f'(deny file-read* (subpath "{accepted_source}")' in profile,
        "acceptedSourceExplicitWriteDeny": f'(deny file-write* (subpath "{accepted_source}")' in profile,
        "sealedArtifactExplicitReadDeny": f'(deny file-read* (subpath "{sealed_artifact_root}")' in profile,
        "sealedArtifactExplicitWriteDeny": f'(deny file-write* (subpath "{sealed_artifact_root}")' in profile,
    }


def _file_error_limits(
    project: Path,
    accepted_canary: Path,
    sealed_canary: Path,
    external_canaries: dict[str, Path | None],
) -> dict[str, tuple[tuple[str, ...], int]]:
    result: dict[str, tuple[tuple[str, ...], int]] = {
        "project_source_write": (
            (str(project / "scripts" / "main.gd"), "res://scripts/main.gd"), 1,
        ),
        "uid_sidecar_write": (
            (str(project / "scripts" / "main.gd.uid"), "res://scripts/main.gd.uid"), 1,
        ),
        "accepted_project_source": ((str(accepted_canary),), 2),
        "artifact_source": ((str(sealed_canary),), 2),
    }
    for name, path in external_canaries.items():
        if path is not None:
            result[name] = ((str(path),), 2)
    return result


def _verification_details(
    report: dict,
    file_error_limits: dict[str, tuple[tuple[str, ...], int]],
    network_error_limit: int,
    *,
    scene_marker: str = "STUDIO_PROJECT_ROLE_READY",
) -> dict[str, object]:
    requirements = report.get("requirements", [])
    requirements_by_id = {
        item.get("id"): item.get("status")
        for item in requirements if isinstance(item, dict)
    } if isinstance(requirements, list) else {}
    commands = report.get("commands", [])
    command_records = [item for item in commands if isinstance(item, dict)] if isinstance(commands, list) else []
    smoke = next((item for item in command_records if item.get("name") == "backend_runtime_smoke"), {})
    smoke_cwd = smoke.get("cwd") if isinstance(smoke, dict) else None
    if isinstance(smoke_cwd, str):
        file_error_limits = dict(file_error_limits)
        file_error_limits["project_source_write"] = (
            (*file_error_limits["project_source_write"][0], str(Path(smoke_cwd) / "scripts" / "main.gd")),
            file_error_limits["project_source_write"][1],
        )
        file_error_limits["uid_sidecar_write"] = (
            (*file_error_limits["uid_sidecar_write"][0], str(Path(smoke_cwd) / "scripts" / "main.gd.uid")),
            file_error_limits["uid_sidecar_write"][1],
        )
    argv = smoke.get("argv", []) if isinstance(smoke, dict) else []
    profile = argv[2] if isinstance(argv, list) and len(argv) > 2 and argv[0] == "/usr/bin/sandbox-exec" else ""
    combined = "\n".join(str(smoke.get(key, "")) for key in ("stdout", "stderr"))
    candidates = [
        occurrence
        for item in command_records
        for key in ("stdout", "stderr")
        for occurrence in _errors(
            str(item.get(key, "")),
            role="verification",
            command=str(item.get("name", "unknown")),
        )
    ]
    errors = _classify_expected_errors(candidates, file_error_limits, network_error_limit)
    unexpected = [item for item in errors if item["expectedDenial"] is not True]
    all_sandboxed = bool(command_records) and all(
        isinstance(item.get("argv"), list)
        and len(item["argv"]) > 2
        and item["argv"][0] == "/usr/bin/sandbox-exec"
        and "(deny default)" in item["argv"][2]
        for item in command_records
    )
    clean = bool(command_records) and all(
        item.get("returnCode") == 0 and item.get("timedOut") is False
        for item in command_records
    ) and not any(str(item.get("line", "")).startswith("SCRIPT ERROR:") for item in errors)
    return {
        "sandboxApplied": report.get("sandbox", {}).get("status") == "APPLIED" and all_sandboxed
        if isinstance(report.get("sandbox"), dict) else False,
        "sandboxStatus": report.get("sandbox", {}).get("status")
        if isinstance(report.get("sandbox"), dict) else None,
        "verificationStatus": report.get("status"),
        "technicalStatus": report.get("technicalStatus"),
        "requirements": requirements_by_id,
        "sceneReadyObserved": scene_marker in combined,
        "roleFacts": _parse_facts(combined),
        "policy": profile,
        "engineErrors": errors,
        "expectedDenialErrors": [item for item in errors if item["expectedDenial"] is True],
        "unexpectedEngineErrors": unexpected,
        "engineErrorsExpectedOnly": not unexpected,
        "engineCleanRuntime": clean and scene_marker in combined and not errors,
        "verificationCopySourceImmutable": requirements_by_id.get("verification_copy.source_immutable") == "PASS",
        "workerGroupStopped": report.get("stopped") is True,
        "commands": command_records,
        "diagnostics": report.get("diagnostics", []),
    }


def _preview_process_alive_watcher(log_path: Path, captured: dict, stop: threading.Event) -> None:
    deadline = time.monotonic() + 60
    while not stop.is_set() and time.monotonic() < deadline:
        if log_path.is_file():
            try:
                log = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                log = ""
            if "STUDIO_PROJECT_ROLE_READY" in log:
                child = captured.get("child")
                captured["sceneReadyObserved"] = True
                captured["aliveAtSceneReady"] = child is not None and child.poll() is None
                return
        time.sleep(0.025)


def _run_clean_runtime_probes(
    root: Path,
    artifact_root: Path,
    protected_root: Path,
    accepted_canary: Path,
    sealed_canary: Path,
    godot: Path,
) -> dict[str, object]:
    """Run a separate, no-denial scene through each production runner path."""
    artifact_id = "role-probe-clean-artifact"
    repository = artifact_root / artifact_id / "repository"
    repository.mkdir(parents=True)
    fixture = _write_project(
        repository,
        accepted_canary,
        sealed_canary,
        {"auth": None, "backend": None, "crossProjectSource": None},
        {"backend": {}, "approval": {}},
    )
    clean_script = _clean_main_script().encode("utf-8")
    (repository / "scripts" / "main.gd").write_bytes(clean_script)
    fixture["scripts/main.gd"] = clean_script
    (repository / ".gitignore").write_text(".godot/\n", encoding="utf-8")
    fixture[".gitignore"] = (repository / ".gitignore").read_bytes()
    source_commit = _commit_fixture(repository)
    document = _document()

    verify_api = _AckAPI({
        "packet": {"id": "packet-role-clean", "document": document},
        "prepared": {"inputCommit": source_commit, "serviceRecords": None},
    })
    verify_runner = ProjectRunner(
        verify_api,
        LocalJournal(root / "clean-verification-state.sqlite3"),
        artifact_root,
        protected_root,
        godot_path=str(godot),
    )
    artifact_ref = {
        "artifactId": artifact_id,
        "projectId": "project-role-probe",
        "jobId": "job-role-clean",
        "attemptId": "attempt-clean-verify",
        "sourceCommit": source_commit,
        "inputCommit": source_commit,
        "packetId": "packet-role-clean",
    }
    verify_execution = {
        "attemptId": "attempt-clean-verify",
        "projectId": "project-role-probe",
        "storeId": "store-role-probe",
        "taskKind": "verify",
        "inputRefs": {"artifactRef": artifact_ref},
    }
    verify_runner.verify(verify_execution, "store-role-probe", max_seconds=150)
    report_path = artifact_root / "verification-evidence" / "attempt-clean-verify.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    verify = _verification_details(
        report,
        _file_error_limits(repository, accepted_canary, sealed_canary, {}),
        0,
        scene_marker="STUDIO_PROJECT_ROLE_CLEAN_READY",
    )
    verify_clean = bool(
        report.get("status") == "PASS"
        and report.get("technicalStatus") == "PASS"
        and report.get("stopped") is True
        and report.get("sourceUnchanged") is True
        and verify.get("sceneReadyObserved") is True
        and verify.get("sandboxApplied") is True
        and not verify.get("engineErrors")
    )

    preview_api = _AckAPI()
    preview_runner = ProjectRunner(
        preview_api,
        LocalJournal(root / "clean-preview-state.sqlite3"),
        artifact_root,
        protected_root,
        godot_path=str(godot),
    )
    preview_execution = {
        "attemptId": "attempt-clean-preview",
        "projectId": "project-role-probe",
        "storeId": "store-role-probe",
        "taskKind": "preview",
        "inputRefs": {"artifactRef": artifact_ref},
    }
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen

    def capture_popen(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        child = real_popen(*args, **kwargs)
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "/usr/bin/sandbox-exec":
            captured["argv"] = list(argv)
            captured["child"] = child
        return child

    import runners.project as project_module
    original_popen = project_module.subprocess.Popen
    project_module.subprocess.Popen = capture_popen
    try:
        preview_runner.preview(preview_execution, "store-role-probe", max_seconds=30)
    finally:
        project_module.subprocess.Popen = original_popen
    preview_log_path = artifact_root / "preview-evidence" / "attempt-clean-preview.log"
    preview_log = preview_log_path.read_text(encoding="utf-8", errors="replace") if preview_log_path.is_file() else ""
    preview_errors = _errors(preview_log, role="preview-clean", command="ProjectRunner.preview")
    preview_reports = [item for item in preview_api.reports if isinstance(item, dict)]
    completed = next((item for item in preview_reports if item.get("type") == "completed"), {})
    payload = completed.get("payload", {}) if isinstance(completed, dict) else {}
    terminal = payload.get("result", {}) if isinstance(payload, dict) else {}
    child = captured.get("child")
    argv = captured.get("argv", [])
    profile = argv[2] if isinstance(argv, list) and len(argv) > 2 else ""
    preview_clean = bool(
        isinstance(terminal, dict)
        and terminal.get("status") == "STOPPED"
        and terminal.get("sourceUnchanged") is True
        and isinstance(payload, dict)
        and payload.get("stopped") is True
        and child is not None
        and child.poll() == 0
        and "STUDIO_PROJECT_ROLE_CLEAN_READY" in preview_log
        and not preview_errors
        and isinstance(argv, list)
        and "--headless" not in argv
        and "(deny default)" in str(profile)
        and "IOSurfaceRootUserClient" in str(profile)
    )
    return {
        "verification": {
            "status": report.get("status"),
            "technicalStatus": report.get("technicalStatus"),
            "sceneMarkerObserved": verify.get("sceneReadyObserved"),
            "sandboxApplied": verify.get("sandboxApplied"),
            "stopped": report.get("stopped") is True,
            "sourceUnchanged": report.get("sourceUnchanged") is True,
            "engineErrors": verify.get("engineErrors", []),
            "engineCleanRuntime": verify_clean,
            "requirements": report.get("requirements", []),
            "diagnostics": report.get("diagnostics", []),
            "commands": [
                {
                    "name": item.get("name"),
                    "returnCode": item.get("returnCode"),
                    "timedOut": item.get("timedOut"),
                    "engineIssues": item.get("engineIssues", []),
                    "issueLines": [
                        line.strip() for line in (
                            str(item.get("stdout", "")) + "\n" + str(item.get("stderr", ""))
                        ).splitlines()
                        if line.lstrip().startswith(("WARNING:", "ERROR:", "SCRIPT ERROR:", "Parse Error:", "Compile Error:"))
                    ],
                    "runtimeSmokeMarker": "STUDIO_BACKEND_RUNTIME_SMOKE_OBSERVED" in str(item.get("stdout", "")),
                }
                for item in report.get("commands", []) if isinstance(item, dict)
            ] if isinstance(report.get("commands"), list) else [],
        },
        "preview": {
            "status": terminal.get("status") if isinstance(terminal, dict) else None,
            "sceneMarkerObserved": "STUDIO_PROJECT_ROLE_CLEAN_READY" in preview_log,
            "sandboxApplied": "(deny default)" in str(profile),
            "graphicsPolicyApplied": "IOSurfaceRootUserClient" in str(profile),
            "processStopped": child is not None and child.poll() is not None,
            "engineErrors": preview_errors,
            "engineCleanRuntime": preview_clean,
        },
        "verificationClean": verify_clean,
        "previewClean": preview_clean,
    }


def _project_facts_to_checks(role_name: str, details: dict[str, object]) -> dict[str, bool]:
    checks = {name: False for name in PROJECT_ROLE_CHECKS[role_name]}
    facts = details.get("roleFacts")
    facts = facts if isinstance(facts, dict) else {}
    unchanged = details.get("externalCanariesUnchanged")
    unchanged = unchanged if isinstance(unchanged, dict) else {}
    checks.update({
        "sandbox_applied": details.get("sandboxApplied") is True and _policy_matches(details, role_name),
        "probe_scene_loaded": details.get("sceneReadyObserved") is True and isinstance(details.get("roleFacts"), dict),
        "source_read_allowed": facts.get("sourceReadAllowed") is True,
        "source_write_denied": facts.get("sourceWriteDenied") is True,
        "uid_sidecar_write_denied": facts.get("uidSidecarWriteDenied") is True,
        "godot_cache_write_allowed": facts.get("cacheWriteAllowed") is True,
        "private_user_write_allowed": facts.get("privateUserWriteAllowed") is True,
        "auth_read_denied": (
            facts.get("authReadDenied") is True
            and details.get("authCanaryAvailable") is True
            and unchanged.get("auth") is True
        ),
        "auth_write_denied": (
            facts.get("authWriteDenied") is True
            and details.get("authCanaryAvailable") is True
            and unchanged.get("auth") is True
        ),
        "backend_read_denied": facts.get("backendReadDenied") is True and unchanged.get("backend") is True,
        "backend_write_denied": facts.get("backendWriteDenied") is True and unchanged.get("backend") is True,
        "cross_project_source_read_denied": (
            facts.get("crossProjectSourceReadDenied") is True and unchanged.get("crossProjectSource") is True
        ),
        "cross_project_source_write_denied": (
            facts.get("crossProjectSourceWriteDenied") is True and unchanged.get("crossProjectSource") is True
        ),
        "accepted_project_source_read_denied": (
            facts.get("acceptedSourceReadDenied") is True and details.get("acceptedCanaryUnchanged") is True
        ),
        "accepted_project_source_write_denied": (
            facts.get("acceptedSourceWriteDenied") is True and details.get("acceptedCanaryUnchanged") is True
        ),
        "artifact_source_read_denied": facts.get("sealedSourceReadDenied") is True,
        "artifact_source_write_denied": facts.get("sealedSourceWriteDenied") is True,
        "backend_ipv4_connection_denied": facts.get("backendIpv4ConnectDenied") is True,
        "backend_ipv6_connection_denied": facts.get("backendIpv6ConnectDenied") is True,
        "approval_ipv4_connection_denied": facts.get("approvalIpv4ConnectDenied") is True,
        "approval_ipv6_connection_denied": facts.get("approvalIpv6ConnectDenied") is True,
        "artifact_source_unchanged": details.get("artifactSourceUnchanged") is True,
        "engine_errors_expected_only": details.get("engineErrorsExpectedOnly") is True,
        "engine_clean_runtime": details.get("engineCleanRuntime") is True,
    })
    if role_name == "verification-isolated-v1":
        checks.update({
            "verification_copy_source_immutable": details.get("verificationCopySourceImmutable") is True,
            "worker_group_stopped": details.get("workerGroupStopped") is True,
        })
    else:
        checks.update({
            "preview_gui_mode": details.get("previewGuiMode") is True,
            "preview_graphics_policy_applied": details.get("previewGraphicsPolicyApplied") is True,
            "preview_process_alive_at_scene_ready": details.get("processAliveAtSceneReady") is True,
            "preview_copy_source_immutable": details.get("previewCopySourceImmutable") is True,
            "preview_process_group_stopped": details.get("previewProcessGroupStopped") is True,
        })
    return {name: checks[name] is True for name in PROJECT_ROLE_CHECKS[role_name]}


def _policy_matches(details: dict[str, object], role_name: str) -> bool:
    facts = details.get("policyFacts")
    if not isinstance(facts, dict):
        return False
    common = (
        facts.get("denyDefault") is True
        and facts.get("networkOutboundGrant") is False
        and facts.get("projectRootWriteGrant") is False
        and facts.get("projectCacheWriteGrant") is True
        and facts.get("acceptedSourceReadGrantAbsent") is True
        and facts.get("acceptedSourceWriteGrantAbsent") is True
        and facts.get("sealedArtifactReadGrantAbsent") is True
        and facts.get("sealedArtifactWriteGrantAbsent") is True
        and facts.get("graphicsGrantMatchesRole") is True
    )
    if role_name != "preview-isolated-v1":
        return common
    return common and all(facts.get(key) is True for key in (
        "acceptedSourceExplicitReadDeny", "acceptedSourceExplicitWriteDeny",
        "sealedArtifactExplicitReadDeny", "sealedArtifactExplicitWriteDeny",
    ))


def _evidence(
    runner_id: str,
    role_details: dict[str, dict[str, object]],
    *,
    engine: str,
    engine_version: str | None,
    auth_observations: dict[str, bool],
    failure_code: str | None = None,
) -> dict[str, object]:
    roles = {
        capability: {"checks": _project_facts_to_checks(capability, role_details.get(capability, {}))}
        for capability in PROJECT_CAPABILITIES
    }
    verified = [
        capability for capability, role in roles.items()
        if all(role["checks"].get(name) is True for name in PROJECT_ROLE_CHECKS[capability])
    ]
    result: dict[str, object] = {
        "schemaVersion": "studio.role-probe.v1",
        "runnerId": runner_id,
        "runnerKind": "project",
        "probeId": str(uuid.uuid4()),
        "observedAt": _utc_now(),
        "policy": "deny-default",
        "status": "PASS" if len(verified) == len(PROJECT_CAPABILITIES) else "NOT_VERIFIED",
        "verifiedCapabilities": verified,
        "roleAssessment": {
            capability: "PASS" if capability in verified else "NOT_VERIFIED"
            for capability in PROJECT_CAPABILITIES
        },
        "roles": roles,
        "engine": engine,
        "engineVersion": engine_version,
        "authCanary": dict(auth_observations),
        "scope": "fresh disposable project executed through ProjectRunner.verify and ProjectRunner.preview",
        "networkGrantExpansion": False,
    }
    if failure_code:
        result["probeFailureCode"] = failure_code
    return result


def run_project_role_probe(runner_id: str, godot_path: str | None = None) -> dict[str, object]:
    """Execute fresh verification and GUI-preview probes; never cache a PASS."""
    if not isinstance(runner_id, str) or not runner_id:
        raise ValueError("project role probe requires the registered runner identity")
    godot = Path(godot_path or os.environ.get("GODOT_BIN") or os.environ.get("GODOT_PATH") or GODOT)
    auth_path, auth_observations = _auth_canary()
    empty_details = {capability: {} for capability in PROJECT_CAPABILITIES}
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        return _evidence(
            runner_id, empty_details, engine=str(godot), engine_version=None,
            auth_observations=auth_observations, failure_code="supported_macos_seatbelt_unavailable",
        )
    if not godot.is_file() or not os.access(godot, os.X_OK):
        return _evidence(
            runner_id, empty_details, engine=str(godot), engine_version=None,
            auth_observations=auth_observations, failure_code="godot_executable_unavailable",
        )

    old_tmp = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = "/tmp"
    role_details: dict[str, dict[str, object]] = empty_details
    engine_version = None
    failure_code = None
    try:
        with tempfile.TemporaryDirectory(prefix="studio-project-role-probe-", dir="/tmp") as raw:
            root = Path(raw).resolve(strict=True)
            accepted_source = root / "protected" / "accepted-project"
            accepted_source.mkdir(parents=True)
            accepted_canary = accepted_source / "accepted-source-canary.txt"
            accepted_canary.write_text("accepted source stays private", encoding="utf-8")
            accepted_canary_before = accepted_canary.read_bytes()
            artifact_root = root / "artifact-vault"
            artifact_source_root = artifact_root / "role-probe-artifact"
            repository = artifact_source_root / "repository"
            repository.mkdir(parents=True)
            sealed_canary = repository / "sealed-source-canary.txt"
            sealed_canary.write_text("sealed source stays private", encoding="utf-8")
            external_canaries: dict[str, Path | None] = {
                "auth": auth_path,
                "backend": (ROOT / "backend" / "__init__.py").resolve(strict=False),
                "crossProjectSource": (ROOT / "sources" / "velvet-eclipse" / "scripts" / "main.gd").resolve(strict=False),
            }
            external_canary_before = _canary_bytes(external_canaries)
            ports: dict[str, dict[str, int]] = {"backend": {}, "approval": {}}
            listeners: dict[str, socket.socket] = {}
            try:
                for service in ports:
                    for family_name, family, host in (
                        ("ipv4", socket.AF_INET, "127.0.0.1"),
                        ("ipv6", socket.AF_INET6, "::1"),
                    ):
                        try:
                            listener = _listener(family, host)
                        except OSError:
                            if family_name == "ipv4":
                                raise
                            ports[service][family_name] = -1
                            continue
                        listeners[service + family_name] = listener
                        ports[service][family_name] = listener.getsockname()[1]

                before = _write_project(repository, accepted_canary, sealed_canary, external_canaries, ports)
                (repository / ".gitignore").write_text(".godot/\n", encoding="utf-8")
                before[".gitignore"] = (repository / ".gitignore").read_bytes()
                source_commit = _commit_fixture(repository)
                file_error_limits = _file_error_limits(
                    repository, accepted_canary, sealed_canary, external_canaries
                )
                network_error_limit = sum(
                    1 for family_ports in ports.values() for port in family_ports.values() if port >= 0
                )
                version = subprocess.run(
                    [str(godot), "--version"], capture_output=True, text=True, timeout=15, check=False
                )
                engine_version = version.stdout.strip() if version.returncode == 0 else None

                verify_api = _AckAPI({
                    "packet": {"id": "packet-role-probe", "document": _document()},
                    "prepared": {"inputCommit": source_commit, "serviceRecords": None},
                })
                verify_journal = LocalJournal(root / "verification-state.sqlite3")
                verify_runner = ProjectRunner(
                    verify_api, verify_journal, artifact_root, root / "protected",
                    godot_path=str(godot),
                )
                verify_ref = {
                    "artifactId": "role-probe-artifact",
                    "projectId": "project-role-probe",
                    "jobId": "job-role-probe",
                    "attemptId": "attempt-verify-role-probe",
                    "sourceCommit": source_commit,
                    "inputCommit": source_commit,
                    "packetId": "packet-role-probe",
                }
                verify_execution = {
                    "attemptId": "attempt-verify-role-probe",
                    "projectId": "project-role-probe",
                    "storeId": "store-role-probe",
                    "taskKind": "verify",
                    "inputRefs": {"artifactRef": verify_ref},
                }
                verify_runner.verify(verify_execution, "store-role-probe", max_seconds=150)
                verify_report_path = artifact_root / "verification-evidence" / "attempt-verify-role-probe.json"
                verify_report = json.loads(verify_report_path.read_text(encoding="utf-8"))
                verify = _verification_details(
                    verify_report, file_error_limits, network_error_limit
                )
                verify_profile = str(verify.pop("policy"))
                smoke_command = next(
                    (item for item in verify.get("commands", [])
                     if isinstance(item, dict) and item.get("name") == "backend_runtime_smoke"),
                    {},
                )
                verify_project_copy = Path(smoke_command["cwd"]) if isinstance(smoke_command.get("cwd"), str) else repository
                verify["policyFacts"] = _policy_facts(
                    verify_profile, verify_project_copy, accepted_source, artifact_source_root, graphics=False,
                )
                verify["authCanaryAvailable"] = external_canary_before.get("auth") is not None and auth_path is not None
                verify["artifactSourceUnchanged"] = (
                    all(item["unchanged"] for item in _byte_equality(before, repository).values())
                    and _git("rev-parse", "HEAD", cwd=repository) == source_commit
                    and _git("status", "--porcelain", "--untracked-files=all", cwd=repository) == ""
                )
                verify["externalCanariesUnchanged"] = _canary_comparison(external_canaries, external_canary_before)
                verify["acceptedCanaryUnchanged"] = (
                    accepted_canary.is_file() and accepted_canary.read_bytes() == accepted_canary_before
                )
                verify["runnerSourceUnchanged"] = verify_report.get("sourceUnchanged") is True
                verify["runnerStoppedConfirmed"] = verify_report.get("stopped") is True
                verify["listenerAcceptedConnections"] = {
                    name: _accepted(listener) for name, listener in listeners.items()
                }
                verify["roleFacts"] = verify.get("roleFacts") or {}
                verify["sandboxApplied"] = verify.get("sandboxApplied") is True
                verify["engineErrorsExpectedOnly"] = not verify.get("unexpectedEngineErrors")
                # The denial scene intentionally produces expected errors, so
                # engine_clean_runtime is filled from a separate clean fixture.
                verify["engineCleanRuntime"] = False
                verify_facts = verify["roleFacts"]
                verify_facts["authReadDenied"] = verify_facts.get("authReadDenied") is True and verify["authCanaryAvailable"]
                verify_facts["authWriteDenied"] = verify_facts.get("authWriteDenied") is True and verify["authCanaryAvailable"]
                verify_facts["backendReadDenied"] = verify_facts.get("backendReadDenied") is True
                verify_facts["backendWriteDenied"] = verify_facts.get("backendWriteDenied") is True
                verify_facts["crossProjectSourceReadDenied"] = verify_facts.get("crossProjectSourceReadDenied") is True
                verify_facts["crossProjectSourceWriteDenied"] = verify_facts.get("crossProjectSourceWriteDenied") is True
                verify_facts["backendIpv4ConnectDenied"] = (
                    verify_facts.get("backendIpv4ConnectDenied") is True
                    and verify["listenerAcceptedConnections"].get("backendipv4") is False
                )
                verify_facts["backendIpv6ConnectDenied"] = (
                    verify_facts.get("backendIpv6ConnectDenied") is True
                    and verify["listenerAcceptedConnections"].get("backendipv6") is False
                )
                verify_facts["approvalIpv4ConnectDenied"] = (
                    verify_facts.get("approvalIpv4ConnectDenied") is True
                    and verify["listenerAcceptedConnections"].get("approvalipv4") is False
                )
                verify_facts["approvalIpv6ConnectDenied"] = (
                    verify_facts.get("approvalIpv6ConnectDenied") is True
                    and verify["listenerAcceptedConnections"].get("approvalipv6") is False
                )
                verify["authCanaryAvailable"] = bool(auth_path is not None and external_canary_before.get("auth") is not None)
                role_details["verification-isolated-v1"] = verify

                preview_api = _AckAPI()
                preview_journal = LocalJournal(root / "runner-state.sqlite3")
                preview_runner = ProjectRunner(
                    preview_api, preview_journal, artifact_root, root / "protected", godot_path=str(godot)
                )
                preview_ref = {
                    "artifactId": "role-probe-artifact",
                    "projectId": "project-role-probe",
                    "jobId": "job-role-probe",
                    "attemptId": "attempt-source-seal",
                    "sourceCommit": source_commit,
                    "inputCommit": source_commit,
                    "packetId": "packet-role-probe",
                }
                preview_execution = {
                    "attemptId": "attempt-preview-role-probe",
                    "projectId": "project-role-probe",
                    "storeId": "store-role-probe",
                    "taskKind": "preview",
                    "inputRefs": {"artifactRef": preview_ref},
                }
                preview_workspace = artifact_root / "previews" / "attempt-preview-role-probe"
                preview_log_path = artifact_root / "preview-evidence" / "attempt-preview-role-probe.log"
                captured: dict[str, object] = {}
                watcher_stop = threading.Event()
                watcher = threading.Thread(
                    target=_preview_process_alive_watcher,
                    args=(preview_log_path, captured, watcher_stop),
                    daemon=True,
                )
                real_popen = subprocess.Popen

                def capture_popen(*args, **kwargs):
                    argv = args[0] if args else kwargs.get("args")
                    child = real_popen(*args, **kwargs)
                    if isinstance(argv, (list, tuple)) and argv and argv[0] == "/usr/bin/sandbox-exec":
                        captured["argv"] = list(argv)
                        captured["child"] = child
                    return child

                import runners.project as project_module
                original_popen = project_module.subprocess.Popen
                watcher.start()
                project_module.subprocess.Popen = capture_popen
                try:
                    preview_runner.preview(preview_execution, "store-role-probe", max_seconds=30)
                finally:
                    project_module.subprocess.Popen = original_popen
                    watcher_stop.set()
                    watcher.join(timeout=2)
                preview_log = preview_log_path.read_text(encoding="utf-8", errors="replace") if preview_log_path.is_file() else ""
                preview_argv = captured.get("argv", [])
                preview_profile = preview_argv[2] if isinstance(preview_argv, list) and len(preview_argv) > 2 else ""
                preview_reports = [body for body in preview_api.reports if isinstance(body, dict)]
                completed = next((body for body in preview_reports if body.get("type") == "completed"), {})
                payload = completed.get("payload", {}) if isinstance(completed, dict) else {}
                terminal = payload.get("result", {}) if isinstance(payload, dict) else {}
                preview_file_error_limits = _file_error_limits(
                    preview_workspace, accepted_canary, sealed_canary, external_canaries
                )
                preview_error_candidates = _errors(
                    preview_log, role="preview", command="ProjectRunner.preview"
                )
                preview_errors = _classify_expected_errors(
                    preview_error_candidates, preview_file_error_limits, network_error_limit
                )
                preview_unexpected_errors = [item for item in preview_errors if item["expectedDenial"] is not True]
                preview_child = captured.get("child")
                preview_profile_facts = _policy_facts(
                    str(preview_profile), preview_workspace, accepted_source, artifact_source_root, graphics=True,
                )
                preview_scene_ready = (
                    captured.get("sceneReadyObserved") is True
                    and _parse_facts(preview_log) is not None
                )
                preview_status = terminal.get("status") if isinstance(terminal, dict) else None
                preview_facts = _parse_facts(preview_log) or {}
                preview_facts.update({
                    "authReadDenied": preview_facts.get("authReadDenied") is True and auth_path is not None,
                    "authWriteDenied": preview_facts.get("authWriteDenied") is True and auth_path is not None,
                    "backendReadDenied": preview_facts.get("backendReadDenied") is True,
                    "backendWriteDenied": preview_facts.get("backendWriteDenied") is True,
                    "crossProjectSourceReadDenied": preview_facts.get("crossProjectSourceReadDenied") is True,
                    "crossProjectSourceWriteDenied": preview_facts.get("crossProjectSourceWriteDenied") is True,
                })
                preview_accepts = {name: _accepted(listener) for name, listener in listeners.items()}
                for service in ("backend", "approval"):
                    for family in ("ipv4", "ipv6"):
                        key = service + family.title() + "ConnectDenied"
                        listener_key = service + family
                        preview_facts[key] = (
                            preview_facts.get(key) is True and preview_accepts.get(listener_key) is False
                        )
                external_after_preview = _canary_comparison(external_canaries, external_canary_before)
                preview_child_stopped = preview_child is not None and preview_child.poll() is not None
                preview_details: dict[str, object] = {
                    "roleFacts": preview_facts,
                    "sandboxApplied": (
                        isinstance(preview_argv, list)
                        and len(preview_argv) > 2
                        and preview_argv[0] == "/usr/bin/sandbox-exec"
                        and "(deny default)" in str(preview_profile)
                    ),
                    "policyFacts": preview_profile_facts,
                    "sceneReadyObserved": preview_scene_ready,
                    "previewGuiMode": (
                        isinstance(preview_argv, list)
                        and "--headless" not in preview_argv
                        and "--editor" not in preview_argv
                        and preview_facts.get("guiDisplayServerActive") is True
                    ),
                    "previewGraphicsPolicyApplied": (
                        preview_profile_facts.get("graphicsGrantMatchesRole") is True
                        and "IOSurfaceRootUserClient" in str(preview_profile)
                    ),
                    "processAliveAtSceneReady": captured.get("aliveAtSceneReady") is True,
                    "previewCopySourceImmutable": (
                        isinstance(terminal, dict)
                        and terminal.get("sourceUnchanged") is True
                        and all(item["unchanged"] for item in _byte_equality(before, preview_workspace).values())
                    ),
                    "artifactSourceUnchanged": (
                        all(item["unchanged"] for item in _byte_equality(before, repository).values())
                        and _git("rev-parse", "HEAD", cwd=repository) == source_commit
                        and _git("status", "--porcelain", "--untracked-files=all", cwd=repository) == ""
                    ),
                    "externalCanariesUnchanged": external_after_preview,
                    "acceptedCanaryUnchanged": (
                        accepted_canary.is_file() and accepted_canary.read_bytes() == accepted_canary_before
                    ),
                    "authCanaryAvailable": auth_path is not None and external_canary_before.get("auth") is not None,
                    "engineErrors": preview_errors,
                    "expectedDenialErrors": [item for item in preview_errors if item["expectedDenial"] is True],
                    "unexpectedEngineErrors": preview_unexpected_errors,
                    "engineErrorsExpectedOnly": not preview_unexpected_errors,
                    # The denial scene intentionally produces expected errors;
                    # a separate clean preview fills engine_clean_runtime.
                    "engineCleanRuntime": False,
                    "previewProcessGroupStopped": (
                        isinstance(payload, dict)
                        and payload.get("stopped") is True
                        and preview_child_stopped
                    ),
                    "previewReports": [body.get("type") for body in preview_reports],
                    "terminalResult": terminal,
                    "previewCacheWriteObserved": (preview_workspace / ".godot/project-role-probe.txt").is_file(),
                    "listenerAcceptedConnections": preview_accepts,
                    "argvHasNoHeadless": isinstance(preview_argv, list) and "--headless" not in preview_argv,
                    "logOutsidePreviewGitCopy": (
                        preview_log_path.is_relative_to(artifact_root)
                        and not preview_log_path.is_relative_to(preview_workspace)
                    ),
                }
                role_details["preview-isolated-v1"] = preview_details
                # Preserve role and command on every occurrence. Do not collapse
                # identical engine errors; each denied socket attempt is evidence.
                role_details["preview-isolated-v1"]["roleFacts"]["backendIpv4ConnectDenied"] = (
                    preview_facts.get("backendIpv4ConnectDenied") is True
                )

                clean_runtime = _run_clean_runtime_probes(
                    root, artifact_root, root / "protected", accepted_canary, sealed_canary, godot,
                )
                verify["engineCleanRuntime"] = clean_runtime["verificationClean"] is True
                preview_details["engineCleanRuntime"] = clean_runtime["previewClean"] is True

                # The verification result intentionally may be FAIL because
                # Godot reports expected denied-access errors. These two checks
                # distinguish those from a dirty runtime or unexpected engine error.
                evidence = _evidence(
                    runner_id,
                    role_details,
                    engine=str(godot),
                    engine_version=engine_version,
                    auth_observations=auth_observations,
                )
                evidence["listeners"] = {
                    name: {
                        "host": listener.getsockname()[0],
                        "port": listener.getsockname()[1],
                        "service": name[:-4],
                        "family": name[-4:],
                    }
                    for name, listener in listeners.items()
                }
                evidence["verification"] = {
                    key: value for key, value in verify.items()
                    if key not in {"roleFacts", "policy", "commands"}
                } | {
                    "roleFacts": verify.get("roleFacts"),
                    "policyFacts": verify.get("policyFacts"),
                    "engineErrors": verify.get("engineErrors"),
                    "expectedDenialErrors": verify.get("expectedDenialErrors"),
                    "unexpectedEngineErrors": verify.get("unexpectedEngineErrors"),
                    "sourceUnchanged": verify.get("runnerSourceUnchanged"),
                    "verificationCopySourceImmutable": verify.get("verificationCopySourceImmutable"),
                    "workerGroupStopped": verify.get("workerGroupStopped"),
                    "verificationStatus": verify.get("verificationStatus"),
                    "technicalStatus": verify.get("technicalStatus"),
                }
                evidence["preview"] = {
                    key: value for key, value in preview_details.items()
                    if key not in {"roleFacts"}
                } | {
                    "roleFacts": preview_facts,
                    "engineErrors": preview_errors,
                    "expectedDenialErrors": [item for item in preview_errors if item["expectedDenial"] is True],
                    "unexpectedEngineErrors": preview_unexpected_errors,
                }
                evidence["cleanRuntime"] = clean_runtime
                evidence["registrationChecks"] = {
                    capability: dict(role["checks"])
                    for capability, role in evidence["roles"].items()
                }
                return evidence
            finally:
                for listener in listeners.values():
                    listener.close()
    except Exception as exc:
        failure_code = type(exc).__name__
        return _evidence(
            runner_id, empty_details, engine=str(godot), engine_version=engine_version,
            auth_observations=auth_observations, failure_code=failure_code,
        )
    finally:
        if old_tmp is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = old_tmp


def run_acceptance(evidence_path: Path = EVIDENCE) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="studio-project-registration-", dir="/tmp") as raw:
        root = Path(raw)
        api = _AckAPI()
        journal = LocalJournal(root / "runner-state.sqlite3")
        runner = ProjectRunner(
            api,
            journal,
            root / "artifact-vault",
            root / "protected",
            godot_path=str(GODOT),
        )
        response = runner.register()
        body = api.registration_body
        result = body.get("sandboxEvidence") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            result = _evidence(
                journal.runner_id,
                {capability: {} for capability in PROJECT_CAPABILITIES},
                engine=str(GODOT),
                engine_version=None,
                auth_observations={
                    "configExists": False,
                    "configuredProvider": False,
                    "containsProviderAuthFields": False,
                },
                failure_code="registration_evidence_missing",
            )
        else:
            result["localRegistration"] = {
                "adapter": "process-local-api-stub",
                "requestCaptured": True,
                "capabilitiesSubmitted": body.get("capabilities", []),
                "responseRunnerIdMatches": (
                    isinstance(response, dict) and response.get("runnerId") == journal.runner_id
                ),
            }
    destination = evidence_path if result.get("status") == "PASS" else evidence_path.with_name(
        "studio-acceptance-project-registration-harness-failure-20261013.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run_acceptance()
    print(json.dumps(result, ensure_ascii=False, indent=2))

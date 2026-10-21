"""Exercise the private Godot runtime with a disposable local fixture.

This probe writes only inside /private/tmp (fixture) and the disposable
runtime/project roots. Godot itself is sandboxed by the same helper used by
the runner; no permission is granted to the real HOME or /var/folders.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runners.common import _seatbelt_quote, stop_process_group
from runners.godot_runtime import GodotRuntime, sandboxed_godot_argv


GODOT_APP = Path("/Applications/Godot.app")
def _fixture_script(auth: Path, backend: Path, other: Path, ipv4_port: int,
                    ipv6_port: int | None, godot_executable: Path) -> str:
    denied_paths = {
        "authCanaryDenied": str(auth / "canary.txt"),
        "backendCanaryDenied": str(backend / "canary.txt"),
        "otherCanaryDenied": str(other / "canary.txt"),
    }
    facts = [
        f'facts["{name}"] = FileAccess.open({json.dumps(path)}, FileAccess.READ) == null'
        for name, path in denied_paths.items()
    ]
    facts += [
        'facts["sourceWriteDenied"] = FileAccess.open("res://source_guard.txt", FileAccess.WRITE) == null',
        f'var executable_write_probe := FileAccess.open({json.dumps(str(godot_executable))}, FileAccess.WRITE)',
        'facts["engineExecutableWriteDenied"] = executable_write_probe == null',
        'if executable_write_probe != null:',
        '    executable_write_probe.close()',
        'facts["cacheWriteAllowed"] = false',
        'var cache_probe := FileAccess.open("res://.godot/runtime-cache-probe.txt", FileAccess.WRITE)',
        'if cache_probe != null:',
        '    cache_probe.store_string("private-cache-write")',
        '    cache_probe.close()',
        '    facts["cacheWriteAllowed"] = true',
        'facts["escapeWriteDenied"] = FileAccess.open("res://.godot/escape/escape.txt", FileAccess.WRITE) == null',
        'var ipv4 := StreamPeerTCP.new()',
        f'var ipv4_error := ipv4.connect_to_host("127.0.0.1", {ipv4_port})',
        'ipv4.poll()',
        'facts["ipv4ConnectDenied"] = ipv4_error != OK or ipv4.get_status() != StreamPeerTCP.STATUS_CONNECTED',
        'var external_exec := OS.execute("/bin/sh", PackedStringArray(["-c", "exit 0"]))',
        'facts["externalProgramExecDenied"] = external_exec != 0',
    ]
    if ipv6_port is not None:
        facts += [
            'var ipv6 := StreamPeerTCP.new()',
            f'var ipv6_error := ipv6.connect_to_host("::1", {ipv6_port})',
            'ipv6.poll()',
            'facts["ipv6ConnectDenied"] = ipv6_error != OK or ipv6.get_status() != StreamPeerTCP.STATUS_CONNECTED',
        ]
    else:
        facts.append('facts["ipv6ConnectDenied"] = true')
    return "\n".join([
        "extends Node",
        "func _ready() -> void:",
        "    var facts: Dictionary = {}",
        *[f"    {line}" for line in facts],
        '    var user_file := FileAccess.open("user://runtime_probe.txt", FileAccess.WRITE)',
        '    facts["privateUserWriteAllowed"] = user_file != null',
        '    if user_file != null:',
        '        user_file.store_string("private-user-write")',
        '        user_file.close()',
        '    print("STUDIO_GODOT_RUNTIME_FACTS=" + JSON.stringify(facts))',
        '    print("STUDIO_GODOT_RUNTIME_READY")',
        "",
    ])


def _listener(family: int, address: str) -> socket.socket | None:
    try:
        server = socket.socket(family, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((address, 0))
        server.listen(4)
        server.setblocking(False)
        return server
    except OSError:
        try:
            server.close()
        except (UnboundLocalError, OSError):
            pass
        return None


def _accepted(listener: socket.socket | None) -> bool:
    if listener is None:
        return False
    try:
        connection, _ = listener.accept()
    except BlockingIOError:
        return False
    except OSError:
        return False
    connection.close()
    return True


def _log_has_issue(text: str) -> bool:
    lowered = text.lower()
    needles = (
        "get_system_ca_certificates",
        "editor temporary directory",
        "failed to create temporary directory",
        "failed to create editor settings",
        "failed to save editor settings",
    )
    return any(needle in lowered for needle in needles)


def _engine_error_lines(text: str, *, unique: bool = True) -> list[str]:
    """Return unique Godot ERROR lines after removing terminal color codes."""
    errors = []
    for line in text.splitlines():
        normalized = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if normalized.startswith(("ERROR:", "SCRIPT ERROR:")):
            errors.append(normalized)
    return list(dict.fromkeys(errors)) if unique else errors


def _source_byte_results(expected: dict[Path, bytes]) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for path, source_bytes in expected.items():
        actual_bytes = path.read_bytes()
        results[path.name if path.parent.name != "scripts" else f"scripts/{path.name}"] = {
            "expectedByteCount": len(source_bytes),
            "actualByteCount": len(actual_bytes),
            "matchesExactBytes": actual_bytes == source_bytes,
        }
    return results


def _run(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> dict[str, object]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            errors="replace", timeout=timeout, check=False)
    return {
        "exitCode": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
    }


def _hardlink_alias_probe(
    production_profile: str,
    runtime: GodotRuntime,
    trusted_paths: list[Path],
) -> dict[str, object]:
    """Check hardlink aliases under production file rules with a test-only process grant."""
    python = Path(sys.executable).resolve(strict=True)
    framework_version = next(
        (parent for parent in python.parents if parent.parent.name == "Versions"), None
    )
    if framework_version is not None:
        app_python = framework_version / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
        if app_python.is_file():
            # Homebrew's bin/python wrapper respawns this executable after
            # calling realpath; the framework binary runs -c directly and
            # needs only the one exact process-exec allowance below.
            python = app_python.resolve(strict=True)
    sources = list(trusted_paths)
    aliases = [runtime.tmp / f"trusted-hardlink-probe-{index}" for index in range(len(sources))]
    for alias in aliases:
        if alias.exists() or alias.is_symlink():
            alias.unlink()

    script = r'''import errno, json, os, sys
result = []
for index in range(1, len(sys.argv), 2):
    source, alias = sys.argv[index], sys.argv[index + 1]
    item = {"source": source, "alias": alias, "linkDenied": False, "linkErrno": None,
            "writeOpenDenied": None, "writeOpenErrno": None}
    try:
        os.link(source, alias)
    except OSError as exc:
        item["linkErrno"] = exc.errno
        item["linkDenied"] = exc.errno in (errno.EPERM, errno.EACCES)
    else:
        try:
            descriptor = os.open(alias, os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            item["writeOpenErrno"] = exc.errno
            item["writeOpenDenied"] = exc.errno in (errno.EPERM, errno.EACCES, errno.EROFS)
        else:
            os.close(descriptor)
            item["writeOpenDenied"] = False
        os.unlink(alias)
    result.append(item)
print("STUDIO_CA_HARDLINK_PROBE=" + json.dumps(result, sort_keys=True))
'''
    probe_profile = production_profile + (
        f'(allow process-exec (literal "{python}"))\n'
    )
    environment = runtime.environment()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            ["/usr/bin/sandbox-exec", "-p", probe_profile, str(python), "-S", "-B", "-c",
             script, *[argument for pair in zip(sources, aliases) for argument in map(str, pair)]],
            cwd=str(runtime.root),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    finally:
        for alias in aliases:
            if alias.exists() or alias.is_symlink():
                alias.unlink()
    marker = "STUDIO_CA_HARDLINK_PROBE="
    line = next((line for line in completed.stdout.splitlines() if line.startswith(marker)), "")
    results = json.loads(line[len(marker):]) if line else []
    passed = bool(
        completed.returncode == 0
        and len(results) == len(sources)
        and all(item.get("linkDenied") or item.get("writeOpenDenied") is True for item in results)
    )
    return {
        "argv": ["/usr/bin/sandbox-exec", "-p", "<production file policy plus test-only Python process/read allowances>",
                 str(python), "-S", "-B", "-c", "<trusted probe>"],
        "returnCode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "processDifference": "The trusted Python framework binary receives one exact process-exec grant; production file-write rules are unchanged.",
        "results": results,
        "passed": passed,
    }


def _write_fixture(project: Path, auth: Path, backend: Path, other: Path,
                   ipv4_port: int, ipv6_port: int | None,
                   godot_executable: Path) -> dict[Path, bytes]:
    (project / "scripts").mkdir(parents=True)
    (project / ".godot").mkdir(mode=0o700)
    (project / ".godot" / "escape").symlink_to(other, target_is_directory=True)
    (auth / "canary.txt").write_text("synthetic auth canary", encoding="utf-8")
    (backend / "canary.txt").write_text("synthetic backend canary", encoding="utf-8")
    (other / "canary.txt").write_text("synthetic other project canary", encoding="utf-8")
    (project / "project.godot").write_text(
        '[application]\nconfig/name="StudioRuntimeProbe"\nrun/main_scene="res://main.tscn"\n\n'
        '[network]\ntls/certificate_bundle_override="res://ca.pem"\n\n'
        '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
        encoding="utf-8",
    )
    (project / "main.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n\n'
        '[ext_resource type="Script" path="res://scripts/runtime_probe.gd" id="1"]\n\n'
        '[node name="RuntimeProbe" type="Node"]\nscript = ExtResource("1")\n',
        encoding="utf-8",
    )
    (project / "source_guard.txt").write_text("SOURCE_MUST_REMAIN_UNCHANGED", encoding="utf-8")
    ca_bundle = Path("/etc/ssl/cert.pem").read_bytes()
    (project / "ca.pem").write_bytes(ca_bundle)
    script = project / "scripts" / "runtime_probe.gd"
    script.write_text(
        _fixture_script(auth, backend, other, ipv4_port, ipv6_port, godot_executable),
        encoding="utf-8",
    )
    return {path: path.read_bytes() for path in (
        project / "project.godot", project / "main.tscn", project / "source_guard.txt",
        project / "ca.pem", script
    )}


def _write_tool_recovery_project(project: Path) -> None:
    """Create a disposable @tool project that must stay inert in recovery import."""
    (project / "scripts").mkdir(parents=True)
    (project / "project.godot").write_text(
        'config_version=5\n\n[application]\n'
        'config/name="StudioToolRecoveryProbe"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    tool_source = r"""@tool
extends Node

static func _static_init() -> void:
	_attempt_write("static_init")

func _init() -> void:
	_attempt_write("init")

func _ready() -> void:
	_attempt_write("ready")

static func _attempt_write(stage: String) -> void:
	var marker := FileAccess.open("res://.godot/tool-executed-marker", FileAccess.WRITE)
	if marker != null:
		marker.store_string(stage)
		marker.close()
	var uid_file := FileAccess.open("res://scripts/tool_probe.gd.uid", FileAccess.WRITE)
	if uid_file != null:
		uid_file.store_string("uid://forgedcanary\n")
		uid_file.close()
"""
    (project / "scripts" / "tool_probe.gd").write_text(tool_source, encoding="utf-8")
    (project / "main.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n\n'
        '[ext_resource type="Script" path="res://scripts/tool_probe.gd" id="1"]\n\n'
        '[node name="ToolRecoveryProbe" type="Node"]\n'
        'script = ExtResource("1")\n',
        encoding="utf-8",
    )


def _run_tool_recovery_probe(project: Path, godot: Path, runtime: GodotRuntime,
                             env: dict[str, str]) -> dict[str, object]:
    uid_path = project / "scripts" / "tool_probe.gd.uid"
    if uid_path.exists():
        raise RuntimeError("synthetic recovery probe UID sidecar must be missing before import")
    log_path = runtime.tmp / "tool-recovery-import.log"
    argv = sandboxed_godot_argv(
        godot,
        ["--headless", "--path", str(project), "--editor", "--recovery-mode", "--import", "--quit",
         "--log-file", str(log_path)],
        project_root=project,
        runtime=runtime,
        uid_write_paths=["scripts/tool_probe.gd.uid"],
    )
    result = _run(argv, project, env, 60)
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    uid_text = uid_path.read_text(encoding="utf-8", errors="replace") if uid_path.is_file() else None
    marker_path = project / ".godot" / "tool-executed-marker"
    issues = _engine_error_lines(result["stdout"] + result["stderr"] + log)
    passed = bool(
        result["exitCode"] == 0
        and not result.get("timedOut")
        and not issues
        and not marker_path.exists()
        and uid_text is not None
        and uid_text != "uid://forgedcanary\n"
    )
    return {
        "argv": argv,
        "result": result,
        "log": log[-12000:],
        "uidSidecarGenerated": uid_text is not None,
        "uidSidecar": uid_text,
        "uidSidecarIsNotForged": uid_text is not None and uid_text != "uid://forgedcanary\n",
        "toolMarkerAbsent": not marker_path.exists(),
        "engineIssues": issues,
        "passed": passed,
    }


def _run_original_template_import(project: Path, godot: Path, runtime: GodotRuntime,
                                 env: dict[str, str]) -> dict[str, object]:
    template = ROOT / "backend" / "templates" / "general_2d"
    if project.exists():
        raise RuntimeError("original-template import project path already exists")
    shutil.copytree(template, project)
    source_files = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*") if path.is_file() and ".godot" not in path.parts
    }
    project_settings = (project / "project.godot").read_text(encoding="utf-8")
    uid_paths = ["scripts/main.gd.uid", "studio/runtime.gd.uid"]
    log_path = runtime.tmp / "original-template-import.log"
    argv = sandboxed_godot_argv(
        godot,
        ["--headless", "--path", str(project), "--editor", "--recovery-mode", "--import", "--quit",
         "--log-file", str(log_path)],
        project_root=project,
        runtime=runtime,
        uid_write_paths=uid_paths,
    )
    result = _run(argv, project, env, 60)
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    runtime_log_path = runtime.tmp / "original-template-game.log"
    runtime_argv = sandboxed_godot_argv(
        godot,
        ["--headless", "--path", str(project), "--quit", "--log-file", str(runtime_log_path)],
        project_root=project,
        runtime=runtime,
    )
    runtime_result = _run(runtime_argv, project, env, 30)
    runtime_log = runtime_log_path.read_text(encoding="utf-8", errors="replace") \
        if runtime_log_path.exists() else ""

    gui_log_path = runtime.tmp / "original-template-gui.stdout.log"
    gui_engine_log_path = runtime.tmp / "original-template-gui.log"
    gui_argv = sandboxed_godot_argv(
        godot,
        ["--path", str(project), "--log-file", str(gui_engine_log_path)],
        project_root=project,
        runtime=runtime,
        allow_graphics=True,
    )
    gui_process = None
    gui_survived_ten_seconds = False
    gui_shutdown_confirmed = False
    gui_started_at = time.monotonic()
    with gui_log_path.open("w", encoding="utf-8") as gui_output:
        gui_process = subprocess.Popen(
            gui_argv,
            cwd=project,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=gui_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while time.monotonic() - gui_started_at < 10.0 and gui_process.poll() is None:
            time.sleep(0.1)
        gui_survived_ten_seconds = (
            gui_process.poll() is None and time.monotonic() - gui_started_at >= 10.0
        )
        if gui_process.poll() is None:
            gui_shutdown_confirmed = stop_process_group(
                gui_process.pid, process=gui_process, grace_seconds=2.0
            )
        else:
            gui_process.wait(timeout=3)
            gui_shutdown_confirmed = stop_process_group(
                gui_process.pid, process=gui_process, grace_seconds=0.1
            )
    if gui_process.poll() is None:
        try:
            gui_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            gui_shutdown_confirmed = False
    gui_output_text = gui_log_path.read_text(encoding="utf-8", errors="replace") \
        if gui_log_path.exists() else ""
    gui_engine_log = gui_engine_log_path.read_text(encoding="utf-8", errors="replace") \
        if gui_engine_log_path.exists() else ""
    gui_engine_issues = _engine_error_lines(gui_output_text + "\n" + gui_engine_log)
    gui_ca_error = 'Condition "ret != noErr" is true' in gui_output_text + gui_engine_log
    gui_renderer_ready = any(
        marker in gui_output_text + gui_engine_log
        for marker in ("OpenGL API", "Vulkan API", "Using renderer", "RenderingDevice", "Metal")
    )
    gui_assertions = [
        marker for marker in ("Assertion failed", "AssertionError", "ASSERTION FAILED")
        if marker in gui_output_text + gui_engine_log
    ]
    changed_sources = [
        relative for relative, expected in source_files.items()
        if not (project / relative).is_file() or (project / relative).read_bytes() != expected
    ]
    issues = _engine_error_lines(result["stdout"] + result["stderr"] + log)
    runtime_issues = _engine_error_lines(
        runtime_result["stdout"] + runtime_result["stderr"] + runtime_log
    )
    generated_uid_paths = [relative for relative in uid_paths if (project / relative).is_file()]
    passed = bool(
        result["exitCode"] == 0
        and not result.get("timedOut")
        and not issues
        and not _log_has_issue(result["stdout"] + result["stderr"] + log)
        and not changed_sources
        and "network/tls/certificate_bundle_override" not in project_settings
        and generated_uid_paths == uid_paths
        and runtime_result["exitCode"] == 0
        and not runtime_result.get("timedOut")
        and not runtime_issues
        and not _log_has_issue(runtime_result["stdout"] + runtime_result["stderr"] + runtime_log)
        and gui_survived_ten_seconds
        and gui_renderer_ready
        and gui_shutdown_confirmed
        and not gui_ca_error
        and not gui_assertions
        and not gui_engine_issues
        and not _log_has_issue(gui_output_text + gui_engine_log)
        and not changed_sources
    )
    return {
        "template": str(template),
        "projectCopy": str(project),
        "projectSettingsHasRuntimeCertificateOverride": "network/tls/certificate_bundle_override" in project_settings,
        "sourceFileCount": len(source_files),
        "sourceFilesUnchanged": not changed_sources,
        "changedSourceFiles": changed_sources,
        "result": result,
        "log": log[-12000:],
        "gameRuntime": {"argv": runtime_argv, "result": runtime_result,
                        "log": runtime_log[-12000:], "engineIssues": runtime_issues},
        "guiGame": {
            "argv": gui_argv,
            "survivedTenSeconds": gui_survived_ten_seconds,
            "shutdownConfirmed": gui_shutdown_confirmed,
            "rendererReady": gui_renderer_ready,
            "usesConfiguredMainScene": "--editor" not in gui_argv and "--path" in gui_argv,
            "exitCode": gui_process.returncode,
            "stdout": gui_output_text[-12000:],
            "engineLog": gui_engine_log[-12000:],
            "engineIssues": gui_engine_issues,
            "caError": gui_ca_error,
            "assertionMarkers": gui_assertions,
        },
        "engineIssues": issues,
        "gameRuntimeEngineIssues": runtime_issues,
        "generatedUidPaths": generated_uid_paths,
        "passed": passed,
    }


def run(evidence_path: Path) -> dict[str, object]:
    if not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("macOS sandbox-exec is unavailable")
    installed_godot = GODOT_APP / "Contents" / "MacOS" / "Godot"
    if not installed_godot.is_file() or not os.access(installed_godot, os.X_OK):
        raise RuntimeError("configured Godot executable is unavailable")

    # /tmp resolves to the system private tmp volume on macOS; the child
    # sandbox receives no write rule for /var/folders or the user's real HOME.
    with tempfile.TemporaryDirectory(prefix="ptah-godot-runtime-", dir="/tmp") as raw_root:
        base = Path(raw_root).resolve(strict=True)
        root = base / "fixture"
        root.mkdir(mode=0o700)
        project = root / "project"
        project.mkdir(mode=0o700)
        auth, backend, other = root / "auth", root / "backend", root / "other-project"
        for directory in (auth, backend, other):
            directory.mkdir(mode=0o700)
        ipv4 = _listener(socket.AF_INET, "127.0.0.1")
        ipv6 = _listener(socket.AF_INET6, "::1")
        if ipv4 is None:
            raise RuntimeError("could not start the local IPv4 network-denial listener")
        runtime = GodotRuntime.create(base / "runtime")
        installed_godot = GODOT_APP / "Contents" / "MacOS" / "Godot"
        godot = runtime.private_executable(installed_godot)
        expected_source = _write_fixture(project, auth, backend, other, ipv4.getsockname()[1],
                                         ipv6.getsockname()[1] if ipv6 else None, godot)
        private_app = godot.parents[2]
        self_contained_marker = godot.parent / "._sc_"
        # On macOS Godot places self-contained editor data outside the .app
        # bundle, beside it, so the copied app's vendor files stay read-only.
        self_contained_data = runtime.root / "editor_data"
        env = runtime.environment()
        protected = [auth, backend, other]
        evidence: dict[str, object] = {
            "godot": str(godot),
            "installedGodot": str(installed_godot),
            "selfContainedAppCopy": str(private_app),
            "version": None,
            "runtimePaths": {name: str(getattr(runtime, name)) for name in
                             ("root", "home", "runtime", "cache", "settings", "data", "tmp", "editor_data")},
            "sandboxEnvironment": {key: env[key] for key in
                                   ("HOME", "CFFIXED_USER_HOME", "TMPDIR", "TMP", "TEMP",
                                    "XDG_RUNTIME_DIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                                    "XDG_DATA_HOME", "XDG_STATE_HOME")},
            "selfContainedMarker": str(self_contained_marker),
            "selfContainedData": str(self_contained_data),
            "protectedCanaries": {
                "auth": str(auth / "canary.txt"),
                "backend": str(backend / "canary.txt"),
                "otherProject": str(other / "canary.txt"),
            },
            "writeGrants": [str(project / ".godot"), str(runtime.root)],
            "privateGodotAppWriteGrant": False,
            "privateGodotAppWriteDeny": str(private_app),
            "networkWriteGrants": False,
            "realHomeWriteGrant": False,
            "varFoldersBroadWriteGrant": False,
            "trustSource": {
                "systemBundle": "/etc/ssl/cert.pem",
                "meaning": "Replaces the public system anchor source with a private copy of the fixed root-owned bundle; Apple user custom trust settings are not read.",
                "interposerSource": str(Path(__file__).resolve().parents[1] / "runners" / "godot_ca_interposer.m"),
                "dyldChildOnly": True,
                "networkIPv4IPv6Denied": True,
            },
        }
        try:
            version_argv = sandboxed_godot_argv(godot, ["--version"], project_root=project,
                                                runtime=runtime, protected_paths=protected)
            version_result = _run(version_argv, project, env, 20)
            evidence["version"] = version_result
            if version_result["exitCode"] != 0:
                return evidence
            engine_version = str(version_result["stdout"]).strip()
            editor_settings, ca_bundle_path = runtime.configure_editor_tls(engine_version, godot)
            evidence["privateEditorSettings"] = str(editor_settings)
            evidence["editorTlsBundleOverride"] = str(ca_bundle_path)
            evidence["editorTlsBundleBytes"] = len((project / "ca.pem").read_bytes())
            ca_support, fixed_ca_bundle, interposer_library = runtime.prepare_trusted_ca_interposer()
            production_profile = version_argv[2]
            expected_dyld_assignment = f"DYLD_INSERT_LIBRARIES={interposer_library}"
            hardlink_probe = _hardlink_alias_probe(
                production_profile,
                runtime,
                [fixed_ca_bundle, interposer_library],
            )
            control_profile = production_profile.replace("(deny file-link)", "", 1)
            control_probe = _hardlink_alias_probe(
                control_profile,
                runtime,
                [fixed_ca_bundle, interposer_library],
            )
            control_denial_is_default = bool(
                control_profile != production_profile
                and control_probe.get("returnCode") == 0
                and len(control_probe.get("results", [])) == 2
                and all(item.get("linkDenied") is True
                        for item in control_probe.get("results", []))
            )
            evidence["trustSource"].update({
                "privateSupportDirectory": str(ca_support),
                "privateBundle": str(fixed_ca_bundle),
                "privateInterposer": str(interposer_library),
                "sandboxProfile": production_profile,
                "bundleWriteDenied": f'(deny file-write* (literal "{fixed_ca_bundle}")' in production_profile,
                "libraryWriteDenied": f'(deny file-write* (literal "{interposer_library}")' in production_profile,
                "supportDirectoryWriteDenied": f'(deny file-write* (subpath "{ca_support}")' in production_profile,
                "configuredEditorBundleMatchesInterposerBundle": ca_bundle_path == fixed_ca_bundle,
                "compiledFromHostSource": True,
                "compileTimeBoundBundlePath": runtime._ca_assets.get("compile_binding") == fixed_ca_bundle,
                "dyldAssignmentAppearsOnlyAfterEnvLauncher": (
                    len(version_argv) > 5
                    and version_argv[3] == "/usr/bin/env"
                    and version_argv[4] == expected_dyld_assignment
                ),
                "runtimeEnvironmentContainsNoDyld": not any(
                    key.startswith("DYLD_") for key in env
                ),
                "networkOutboundGrantAbsent": "(allow network-outbound" not in production_profile,
                "appleUserCustomTrustReadGrantAbsent": "user-preference-read" not in production_profile,
                "hardlinkAliasProbe": hardlink_probe,
                "hardlinkAliasControlWithoutExplicitDeny": {
                    **control_probe,
                    "onlyProductionRuleRemoved": "(deny file-link)",
                    "productionFileWriteRulesUnchanged": True,
                    "confirmsDefaultLinkDenial": control_denial_is_default,
                },
            })

            template_project = root / "original-template-project"
            evidence["originalTemplateImport"] = _run_original_template_import(
                template_project, godot, runtime, env
            )

            tool_project = root / "tool-recovery-project"
            _write_tool_recovery_project(tool_project)
            evidence["toolRecoveryProbe"] = _run_tool_recovery_probe(
                tool_project, godot, runtime, env
            )

            import_argv = sandboxed_godot_argv(
                godot,
                ["--headless", "--verbose", "--path", str(project), "--editor", "--recovery-mode", "--import", "--quit",
                 "--log-file", str(runtime.tmp / "import.log")],
                project_root=project, runtime=runtime, protected_paths=protected,
                uid_write_paths=["scripts/runtime_probe.gd.uid"],
            )
            import_result = _run(import_argv, project, env, 60)
            import_log = (runtime.tmp / "import.log").read_text(encoding="utf-8", errors="replace") \
                if (runtime.tmp / "import.log").exists() else ""
            evidence["import"] = import_result
            evidence["importLog"] = import_log[-12000:]
            evidence["importHasCache"] = any((project / ".godot").rglob("*"))
            evidence["importHasScriptUid"] = (project / "scripts" / "runtime_probe.gd.uid").is_file()
            import_text = import_result["stdout"] + import_result["stderr"] + import_log
            evidence["importEngineErrors"] = _engine_error_lines(import_text)
            evidence["importUnexpectedEngineErrors"] = evidence["importEngineErrors"]
            evidence["editorSettingsLoadObserved"] = "EditorSettings: Load OK!" in import_text
            evidence["importHasRuntimeIssues"] = (_log_has_issue(import_text)
                                                   or bool(evidence["importUnexpectedEngineErrors"]))
            import_source_results = _source_byte_results(expected_source)
            evidence["sourceByteResultsAfterImport"] = import_source_results
            evidence["sourceFilesUnchangedAfterImport"] = all(
                result["matchesExactBytes"] for result in import_source_results.values()
            )
            if import_result["exitCode"] != 0:
                return evidence

            gui_log = runtime.tmp / "gui.stdout.log"
            gui_engine_log = runtime.tmp / "gui.log"
            gui_argv = sandboxed_godot_argv(
                godot,
                ["--path", str(project), "--log-file", str(gui_engine_log)],
                project_root=project, runtime=runtime, protected_paths=protected,
                allow_graphics=True,
            )
            process = None
            stdout_text = ""
            ready = False
            stopped = False
            try:
                with gui_log.open("w", encoding="utf-8") as output:
                    process = subprocess.Popen(gui_argv, cwd=project, env=env,
                                               stdin=subprocess.DEVNULL, stdout=output,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and process.poll() is None:
                        stdout_text = gui_log.read_text(encoding="utf-8", errors="replace")
                        if "STUDIO_GODOT_RUNTIME_READY" in stdout_text:
                            ready = True
                            break
                        time.sleep(0.1)
                    if not ready and gui_log.exists():
                        stdout_text = gui_log.read_text(encoding="utf-8", errors="replace")
            finally:
                if process is not None and process.poll() is None:
                    stopped = stop_process_group(process.pid, process=process, grace_seconds=2.0)
                elif process is not None:
                    process.wait(timeout=3)
                    stopped = stop_process_group(process.pid, process=process, grace_seconds=0.1)
            if gui_log.exists():
                stdout_text = gui_log.read_text(encoding="utf-8", errors="replace")
            gui_engine_text = gui_engine_log.read_text(encoding="utf-8", errors="replace") \
                if gui_engine_log.exists() else ""
            gui_engine_errors = _engine_error_lines(stdout_text + "\n" + gui_engine_text)
            expected_network_error = "ERROR: Connection to remote host failed!"
            gui_stdout_error_lines = _engine_error_lines(stdout_text, unique=False)
            expected_network_error_count = gui_stdout_error_lines.count(expected_network_error)
            unexpected_gui_errors = [error for error in gui_engine_errors
                                     if error != expected_network_error]
            fact_lines = [line.split("=", 1)[1] for line in stdout_text.splitlines()
                          if line.startswith("STUDIO_GODOT_RUNTIME_FACTS=")]
            facts = json.loads(fact_lines[-1]) if fact_lines else {}
            listener_accepted = {"ipv4": _accepted(ipv4), "ipv6": _accepted(ipv6)}
            gui_source_results = _source_byte_results(expected_source)
            private_settings_roots = (
                runtime.home / "Library" / "Application Support" / "Godot",
                runtime.home / "Library" / "Caches" / "Godot",
                runtime.home / "Library" / "Preferences",
                runtime.settings,
                runtime.data,
                self_contained_data,
            )
            private_settings_files = sorted({
                str(path.relative_to(runtime.root))
                for settings_root in private_settings_roots if settings_root.exists()
                for path in settings_root.rglob("*") if path.is_file()
            })
            evidence.update({
                "configuredMainScene": "res://main.tscn",
                "gui": {"ready": ready, "stopped": stopped,
                        "exitCode": process.returncode if process is not None else None,
                        "stdout": stdout_text[-12000:], "engineLog": gui_engine_text[-12000:]},
                "guiEngineErrors": gui_engine_errors,
                "guiExpectedNetworkErrorCount": expected_network_error_count,
                "guiUnexpectedEngineErrors": unexpected_gui_errors,
                "guiFacts": facts,
                "listenerAccepted": listener_accepted,
                "privateUserFileCreated": any(runtime.root.rglob("runtime_probe.txt")),
                "privateSettingsDirectories": [str(path) for path in private_settings_roots],
                "privateSettingsFiles": private_settings_files,
                "guiHasRuntimeIssues": (_log_has_issue(stdout_text + gui_engine_text)
                                        or bool(unexpected_gui_errors)),
                "sourceByteResultsAfterGui": gui_source_results,
                "sourceFilesUnchangedAfterGui": all(
                    result["matchesExactBytes"] for result in gui_source_results.values()
                ),
                "cacheFiles": [str(path.relative_to(project)) for path in
                               (project / ".godot").rglob("*") if path.is_file()],
                "protectedCanariesUnchanged": {
                    "auth": (auth / "canary.txt").read_text(encoding="utf-8") == "synthetic auth canary",
                    "backend": (backend / "canary.txt").read_text(encoding="utf-8") == "synthetic backend canary",
                    "otherProject": (other / "canary.txt").read_text(encoding="utf-8") == "synthetic other project canary",
                },
            })
            evidence["allChecksPass"] = bool(
                version_result["exitCode"] == 0
                and import_result["exitCode"] == 0
                and evidence.get("editorSettingsLoadObserved") is True
                and evidence.get("originalTemplateImport", {}).get("passed") is True
                and evidence.get("originalTemplateImport", {}).get("guiGame", {}).get("survivedTenSeconds") is True
                and evidence.get("originalTemplateImport", {}).get("guiGame", {}).get("shutdownConfirmed") is True
                and evidence.get("originalTemplateImport", {}).get("guiGame", {}).get("rendererReady") is True
                and evidence.get("originalTemplateImport", {}).get("guiGame", {}).get("usesConfiguredMainScene") is True
                and evidence.get("toolRecoveryProbe", {}).get("passed") is True
                and evidence.get("trustSource", {}).get("configuredEditorBundleMatchesInterposerBundle") is True
                and evidence.get("trustSource", {}).get("bundleWriteDenied") is True
                and evidence.get("trustSource", {}).get("libraryWriteDenied") is True
                and evidence.get("trustSource", {}).get("supportDirectoryWriteDenied") is True
                and evidence.get("trustSource", {}).get("dyldAssignmentAppearsOnlyAfterEnvLauncher") is True
                and evidence.get("trustSource", {}).get("runtimeEnvironmentContainsNoDyld") is True
                and evidence.get("trustSource", {}).get("networkOutboundGrantAbsent") is True
                and evidence.get("trustSource", {}).get("appleUserCustomTrustReadGrantAbsent") is True
                and evidence.get("trustSource", {}).get("hardlinkAliasProbe", {}).get("passed") is True
                and evidence.get("trustSource", {}).get(
                    "hardlinkAliasControlWithoutExplicitDeny", {}).get("confirmsDefaultLinkDenial") is True
                and not evidence["importHasRuntimeIssues"]
                and evidence["importHasCache"]
                and evidence["importHasScriptUid"]
                and evidence["sourceFilesUnchangedAfterImport"]
                and ready and stopped
                and expected_network_error_count == (2 if ipv6 is not None else 1)
                and not unexpected_gui_errors
                and all(facts.get(key) is True for key in (
                    "authCanaryDenied", "backendCanaryDenied", "otherCanaryDenied",
                    "sourceWriteDenied", "engineExecutableWriteDenied",
                    "cacheWriteAllowed", "escapeWriteDenied",
                    "ipv4ConnectDenied", "ipv6ConnectDenied", "externalProgramExecDenied",
                    "privateUserWriteAllowed",
                ))
                and not listener_accepted["ipv4"]
                and not listener_accepted["ipv6"]
                and evidence["privateUserFileCreated"]
                and not evidence["guiHasRuntimeIssues"]
                and evidence["sourceFilesUnchangedAfterGui"]
                and all(evidence["protectedCanariesUnchanged"].values())
            )
            return evidence
        finally:
            if ipv4 is not None:
                ipv4.close()
            if ipv6 is not None:
                ipv6.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path,
                        default=ROOT / "evidence" / "workflow" / "studio-acceptance-godot-runtime-20261012.json")
    args = parser.parse_args()
    evidence = run(args.evidence)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(args.evidence), "allChecksPass": evidence.get("allChecksPass"),
                      "importHasRuntimeIssues": evidence.get("importHasRuntimeIssues"),
                      "gui": {key: evidence.get("gui", {}).get(key) for key in ("ready", "stopped", "exitCode")},
                      "guiFacts": evidence.get("guiFacts")}, ensure_ascii=False))
    return 0 if evidence.get("allChecksPass") else 1


if __name__ == "__main__":
    raise SystemExit(main())

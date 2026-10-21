"""Trusted production preflight: verify the bundled MCP in a disposable editor.

This channel belongs to the runner/operator, never to a managed model. The
editor receives a private home, a source copy and one loopback listening port.
No original project writes, backend access or general network access is granted.
"""
from __future__ import annotations

import json
import math
import os
import re
import select
import shutil
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .common import RunnerError, _seatbelt_quote, stop_process_group
from .godot_runtime import GodotRuntime, sandboxed_godot_argv
from tools.godot_mcp_install import _canonicalize_project_path, verify_godot_mcp


class EditorMCPError(RunnerError):
    def __init__(self, message, *, report=None):
        super().__init__(message)
        self.report = report or {}
        self.stopped = self.report.get("editorStopped", True)
        self.cancelled = self.report.get("cancelled", False)
        self.code = "GODOT_MCP_NOT_READY" if self.stopped else "GODOT_MCP_UNCERTAIN"


_EXCLUDED = {".git", ".godot", ".godotmaker", ".runner-tmp", ".runner-assets",
             "__pycache__"}
_MAX_SOURCE_BYTES = 256 * 1024 * 1024
_MAX_EDITOR_LOG_BYTES = 2 * 1024 * 1024


def _drain_editor_output(process, log_path, total):
    """Drain only available bytes so editor output cannot block or fill disk."""
    if process.stdout is None:
        return total
    with log_path.open("ab") as log:
        total = max(total, log.tell())
        while select.select([process.stdout], [], [], 0)[0]:
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            log.write(chunk[:max(0, _MAX_EDITOR_LOG_BYTES - total)])
            total += len(chunk)
            if total > _MAX_EDITOR_LOG_BYTES:
                raise EditorMCPError("Godot editor output exceeded the bounded log limit")
    return total


def _snapshot(project: Path) -> dict[str, bytes]:
    """Bounded byte inventory; reject links and special files before launching."""
    result = {}
    total = 0
    for directory, dirs, files in os.walk(project, followlinks=False):
        parent = Path(directory)
        dirs[:] = [name for name in dirs if name not in _EXCLUDED]
        for name in dirs + files:
            path = parent / name
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise EditorMCPError(f"Godot preflight source must contain only regular files: {path}")
            total += metadata.st_size
            if total > _MAX_SOURCE_BYTES or len(result) >= 30000:
                raise EditorMCPError("Godot preflight source exceeds the bounded copy limit")
            result[path.relative_to(project).as_posix()] = path.read_bytes()
    return result


def _private_project_settings(text: str, user_dir: str) -> str:
    """Give the disposable project a unique name and private user data location."""
    lines = text.splitlines(keepends=True)
    section = ""
    result = []
    seen = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            if section == "application":
                if seen:
                    raise EditorMCPError("project.godot has duplicate application sections")
                seen = True
                result.append(line.rstrip() + "\n")
                result.append(f'config/name="{user_dir}"\n')
                result.append('config/use_custom_user_dir=true\n')
                result.append(f'config/custom_user_dir="{user_dir}"\n')
                continue
        if section == "application" and re.match(
            r"\s*config/(?:name|use_custom_user_dir|custom_user_dir)\s*=", line
        ):
            continue
        result.append(line)
    if not seen:
        result.extend(['\n[application]\n', f'config/name="{user_dir}"\n',
                       'config/use_custom_user_dir=true\n',
                       f'config/custom_user_dir="{user_dir}"\n'])
    return "".join(result)


def _editor_argv(engine, project, runtime, port):
    """Extend the no-network game sandbox only for this editor's inbound port."""
    argv = sandboxed_godot_argv(engine, ["--headless", "--editor", "--path", str(project)],
                              project_root=project, runtime=runtime)
    # This is an expendable copy, so allow editor normalization and generated
    # import/UID sidecars here. The original source is not in the read grants.
    # Bundled plugin code remains immutable even in the copy.
    policy = argv[2]
    policy += f'(allow file-write* (subpath {_seatbelt_quote(project)}))'
    policy += f'(deny file-write* (subpath {_seatbelt_quote(project / "addons")}))'
    policy += f'(allow network-bind (local tcp "localhost:{port}"))'
    policy += f'(allow network-inbound (local tcp "localhost:{port}"))'
    argv[2] = policy
    return argv


class _Client:
    def __init__(self, port, deadline):
        self.endpoint = f"http://127.0.0.1:{port}"
        self.deadline = deadline
        self.sequence = 0
        # Ignore HTTP_PROXY and related ambient proxy configuration.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, route, message=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Godot MCP readiness deadline expired")
        request = urllib.request.Request(self.endpoint + route,
            data=None if message is None else json.dumps(message).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        with self.opener.open(request, timeout=min(1.0, remaining)) as response:
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise EditorMCPError("Godot MCP response exceeds the allowed limit")
            if response.status == 202 and message and "id" not in message:
                return None
            return json.loads(content)

    def rpc(self, method, params, *, notification=False):
        self.sequence += 1
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            message["id"] = self.sequence
        result = self.request("/mcp", message)
        if notification:
            return result
        if not isinstance(result, dict) or result.get("id") != self.sequence or "error" in result:
            raise EditorMCPError("Godot MCP returned an invalid JSON-RPC response")
        return result["result"]

    def call(self, name):
        result = self.rpc("tools/call", {"name": name, "arguments": {"action": "get_info"}})
        content = result.get("content", [])
        if result.get("isError") or len(content) != 1 or content[0].get("type") != "text":
            raise EditorMCPError(f"Godot MCP {name} returned an error")
        value = json.loads(content[0]["text"])
        if value.get("success") is not True or not isinstance(value.get("data"), dict):
            raise EditorMCPError(f"Godot MCP {name} did not succeed")
        return value["data"]


def _observe(client, project):
    health = client.request("/health")
    if health.get("running") is not True:
        raise OSError("editor MCP server is not running")
    initialized = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "studio-production-preflight", "version": "1"}})
    client.rpc("notifications/initialized", {}, notification=True)
    tools = client.rpc("tools/list", {}).get("tools", [])
    names = {item.get("name") for item in tools}
    if not {"project_info", "editor_status"} <= names:
        raise EditorMCPError("editor MCP is missing required readiness tools")
    info = client.call("project_info")
    if Path(info.get("project_path", "")).resolve() != project:
        raise EditorMCPError("editor MCP project identity does not match the isolated project")
    status = client.call("editor_status")
    return {"initialize": initialized, "toolCount": len(tools), "projectInfo": info,
            "editorStatus": status, "projectIdentityMatches": True}


def ensure_editor_mcp_ready(project_dir, evidence_dir, *, godot_path=None,
                            timeout=45.0, cancel_event=None, tick=None, context=None):
    """Gate one production batch; PASS requires exact identity and confirmed stop.

    ``tick`` maintains the caller's lease and may return True for cancellation.
    Every invocation is fresh; a previous report never authorizes another run.
    Failed or uncertain reports are durable and prevent producer dispatch.
    """
    if not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise EditorMCPError("Godot MCP timeout must be between 0 and 120 seconds")
    project = _canonicalize_project_path(Path(project_dir).expanduser())
    evidence = _canonicalize_project_path(Path(evidence_dir).expanduser())
    if evidence == project or evidence.is_relative_to(project) or project.is_relative_to(evidence):
        raise EditorMCPError("readiness evidence must be separate from project source")
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    report_path = evidence / "readiness.json"
    report = {"schemaVersion": "studio.godot-mcp-readiness.v1", "status": "FAIL",
              "sourceProject": str(project), "context": context or {},
              "editorStarted": False, "editorStopped": True, "reportPath": str(report_path)}
    process = None
    snapshot = None
    started = time.monotonic()
    work = evidence / "disposable"
    log_path = evidence / "editor.log"
    log_bytes = 0

    def persist():
        pending = report_path.with_suffix(".pending")
        try:
            pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(pending, report_path)
        except OSError as exc:
            report["status"] = "FAIL" if report["editorStopped"] else "UNCERTAIN"
            raise EditorMCPError(f"Could not persist Godot MCP readiness: {exc}", report=dict(report)) from exc

    def pulse():
        cancelled = bool(cancel_event is not None and cancel_event.is_set())
        if tick is not None:
            cancelled = bool(tick()) or cancelled
        if cancelled:
            report["cancelled"] = True
            raise EditorMCPError("Godot MCP preparation was cancelled")

    persist()
    try:
        pulse()
        report["pluginFileCount"] = verify_godot_mcp(project)
        snapshot = _snapshot(project)
        copied = work / "project"
        copied.mkdir(mode=0o700, parents=True)
        for name, data in snapshot.items():
            target = copied / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
        pulse()
        runtime = GodotRuntime.create(work / "runtime")
        engine = godot_path or os.environ.get("GODOT_BIN") or os.environ.get("GODOT_PATH") or shutil.which("godot")
        engine = engine or "/Applications/Godot.app/Contents/MacOS/Godot"
        engine = runtime.private_executable(engine)
        version = subprocess.run([str(engine), "--version"], env=runtime.environment(),
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        report["engineVersion"] = version
        runtime.configure_editor_tls(version, engine)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        user_dir = "StudioMCP-" + uuid.uuid4().hex
        settings = copied / "project.godot"
        settings.write_text(_private_project_settings(settings.read_text(), user_dir), encoding="utf-8")
        user_data = runtime.home / "Library" / "Application Support" / user_dir
        user_data.mkdir(mode=0o700)
        (user_data / "godot_mcp_settings.json").write_text(json.dumps({
            "host": "127.0.0.1", "port": port, "auto_start": True}), encoding="utf-8")
        report.update(endpoint=f"http://127.0.0.1:{port}", isolatedProject=str(copied))
        argv = _editor_argv(engine, copied, runtime, port)
        pulse()
        process = subprocess.Popen(argv, cwd=copied, env=runtime.environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        report.update(editorStarted=True, editorStopped=False, processGroupId=process.pid,
                      editorStartedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        persist()  # Separate editor lease; never an agent's native identity.
        deadline = time.monotonic() + timeout
        client = _Client(port, deadline)
        last_error = None
        while time.monotonic() < deadline:
            log_bytes = _drain_editor_output(process, log_path, log_bytes)
            pulse()
            if process.poll() is not None:
                raise EditorMCPError(f"Godot editor exited before readiness ({process.returncode})")
            try:
                report.update(_observe(client, copied.resolve()))
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = str(exc)
                time.sleep(0.15)
        else:
            raise EditorMCPError(f"Godot MCP readiness timed out: {last_error}")
        pulse()
        report["status"] = "PASS"
    except Exception as exc:
        report.update(status="FAIL", errorType=type(exc).__name__, message=str(exc)[:2000])
    finally:
        if process is not None:
            try:
                report["editorStopped"] = stop_process_group(process.pid, process=process, grace_seconds=2)
                report["editorExitCode"] = process.poll()
            except Exception as exc:
                report.update(editorStopped=False, cleanupError=str(exc)[:1000])
            try:
                _drain_editor_output(process, log_path, log_bytes)
            except Exception as exc:
                report.update(status="FAIL", message=str(exc)[:2000])
            finally:
                if process.stdout is not None:
                    process.stdout.close()
        if snapshot is not None:
            try:
                report["sourceUnchanged"] = _snapshot(project) == snapshot
                if not report["sourceUnchanged"]:
                    report.update(status="FAIL", message="Godot preflight source changed during preparation")
            except Exception as exc:
                report.update(status="FAIL", sourceUnchanged=False, message=str(exc)[:2000])
        if not report["editorStopped"]:
            report.update(status="UNCERTAIN", message="Godot editor termination is not confirmed")
        report["durationSeconds"] = round(time.monotonic() - started, 3)
        persist()
        if report["editorStopped"] and work.exists():
            try:
                shutil.rmtree(work)
            except OSError as exc:
                report["disposableCleanupError"] = str(exc)[:1000]
                persist()
    if report["status"] != "PASS":
        raise EditorMCPError(report.get("message", "Godot MCP preparation failed"), report=report)
    return report

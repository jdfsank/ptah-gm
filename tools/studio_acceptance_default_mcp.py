"""Probe bundled MCP defaults in disposable ordinary Godot editors.

This uses the user's editor plugin over HTTP JSON-RPC. It is a trusted operator
test, not evidence for the restricted ProjectRunner sandbox or role capabilities.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runners.common import stop_process_group
from runners.godot_runtime import GodotRuntime
from tools.godot_mcp_install import install_godot_mcp

ENDPOINT = "http://127.0.0.1:3000"
ENGINE = "/Applications/Godot.app/Contents/MacOS/Godot"


def port_free() -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", 3000)) != 0


def inventory(project: Path) -> dict[str, bytes]:
    return {path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*") if path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(project).parts)}


def settings_normalization(before: bytes, after: bytes) -> dict:
    """Describe the ordinary editor's known config/features normalization."""
    def directives(data):
        section = ""
        result = {}
        for raw in data.decode().splitlines():
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            key, value = line.split("=", 1)
            identity = (section, key.strip())
            if identity in result:
                raise ValueError("duplicate project setting")
            result[identity] = value.strip()
        return result

    old = directives(before)
    new = directives(after)
    added = {key: value for key, value in new.items() if key not in old}
    allowed_features = {
        'PackedStringArray("4.6")',
        'PackedStringArray("4.6", "GL Compatibility")',
    }
    features = ("application", "config/features")
    return {"onlyKnownNormalization": all(new.get(key) == value for key, value in old.items())
            and all(key == features and value in allowed_features for key, value in added.items()),
            "addedDirectives": [{"section": key[0], "key": key[1], "value": value}
                                for key, value in added.items()],
            "before": before.decode(), "after": after.decode()}


class Client:
    def __init__(self):
        self.next_id = 0
        self.calls = []

    def rpc(self, method, params, *, notification=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.next_id += 1
            message["id"] = self.next_id
        request = urllib.request.Request(ENDPOINT + "/mcp",
            data=json.dumps(message).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            content = response.read()
            if notification:
                assert response.status == 202, response.status
                return response.status
        decoded = json.loads(content)
        if "error" in decoded:
            raise RuntimeError(str(decoded["error"]))
        assert decoded.get("id") == message["id"], decoded
        return decoded["result"]

    def call(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        decoded = [json.loads(item["text"]) for item in result.get("content", [])
                   if item.get("type") == "text"]
        self.calls.append({"name": name, "arguments": arguments,
                           "result": result, "decoded": decoded})
        assert not result.get("isError") and len(decoded) == 1, result
        assert decoded[0].get("success") is True, decoded
        return decoded[0].get("data", {})


def wait_until(check, seconds=35):
    deadline = time.monotonic() + seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise TimeoutError(f"MCP observation timed out: {last_error}")


def run_case(work: Path, kind: str) -> dict:
    case = work / kind
    case.mkdir(mode=0o700)
    project = case / "project"
    if kind == "template":
        shutil.copytree(ROOT / "backend/templates/general_2d", project)
        first_install_changed = False
    else:
        first_install_changed = install_godot_mcp(project)
    before = inventory(project)
    result = {"kind": kind, "project": str(project), "passed": False,
              "firstInstallChanged": first_install_changed,
              "reinstallChanged": install_godot_mcp(project)}
    runtime = GodotRuntime.create(case / "private-runtime")
    executable = runtime.private_executable(ENGINE)
    client = Client()
    process = None
    log_path = case / "editor.log"
    try:
        assert port_free(), "port 3000 is already in use; will not control another editor"
        with log_path.open("w") as log:
            process = subprocess.Popen([str(executable), "--editor", "--path", str(project)],
                env=runtime.environment(), stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
            result["editorPid"] = process.pid

            def health():
                if process.poll() is not None:
                    raise RuntimeError(f"editor exited: {process.returncode}")
                with urllib.request.urlopen(ENDPOINT + "/health", timeout=2) as response:
                    data = json.load(response)
                return data if data.get("running") is True else None

            result["health"] = wait_until(health)
            result["initialize"] = client.rpc("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "studio-default-mcp-acceptance", "version": "1"}})
            result["initializedNotificationStatus"] = client.rpc(
                "notifications/initialized", {}, notification=True)
            definitions = client.rpc("tools/list", {})["tools"]
            result["toolCount"] = len(definitions)
            info = client.call("project_info", {"action": "get_info"})
            result["projectIdentityMatches"] = Path(info["project_path"]).resolve() == project.resolve()
            assert result["projectIdentityMatches"], info
            result["editorStatus"] = client.call("editor_status", {"action": "get_info"})
            if kind == "template":
                client.call("scene_management", {"action": "open", "path": info["main_scene"]})
                tree = client.call("scene_hierarchy", {"action": "get_tree", "depth": 2})
                result["mainSceneOpened"] = tree.get("scene_path") == info["main_scene"]
                client.call("scene_run", {"action": "play_main"})
                result["playingObserved"] = bool(wait_until(
                    lambda: client.call("scene_run", {"action": "get_status"}).get("playing"), 15))
                time.sleep(2)
                client.call("scene_run", {"action": "stop"})
                result["stoppedObserved"] = bool(wait_until(
                    lambda: not client.call("scene_run", {"action": "get_status"}).get("playing"), 15))
    except Exception as exc:
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    finally:
        if process is not None:
            result["editorStopped"] = stop_process_group(process.pid, process=process, grace_seconds=2)
            if result["editorStopped"]:
                process.wait(timeout=5)
            result["editorExitCode"] = process.poll()
        result["calls"] = client.calls
        after = inventory(project)
        result["originalSourceChangedPaths"] = sorted(
            name for name, data in before.items() if after.get(name) != data)
        result["projectSettingsNormalization"] = settings_normalization(
            before["project.godot"], after["project.godot"])
        added = sorted(set(after) - set(before))
        allowed_uid = {name + ".uid" for name in before if name.endswith(".gd")
                       and name + ".uid" not in before}
        result["ordinaryEditorGeneratedUidPaths"] = [name for name in added if name in allowed_uid]
        result["unexpectedAddedSourcePaths"] = [name for name in added if name not in allowed_uid]
        logs = log_path.read_text(errors="replace") if log_path.exists() else ""
        logs = re.sub(r"\x1b\[[0-9;]*m", "", logs)
        result["engineErrors"] = [line.strip() for line in logs.splitlines()
            if line.strip().startswith(("ERROR:", "SCRIPT ERROR:"))]
        result["editorLog"] = logs[-16000:]
        result["passed"] = bool(not result.get("failure") and result.get("editorStopped")
            and result.get("projectIdentityMatches") and result.get("toolCount") == 74
            and result["reinstallChanged"] is False and not result["engineErrors"]
            and set(result["originalSourceChangedPaths"]) <= {"project.godot"}
            and result["projectSettingsNormalization"]["onlyKnownNormalization"]
            and not result["unexpectedAddedSourcePaths"]
            and (kind != "template" or (result.get("mainSceneOpened")
                 and result.get("playingObserved") and result.get("stoppedObserved"))))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix="studio-default-mcp-"))
    result = {"scope": "new installer project and bundled general_2d template; actual ordinary editor MCP",
        "endpoint": ENDPOINT + "/mcp", "work": str(work), "capabilitiesEnabled": [],
        "limitations": ["Not restricted Runner isolation evidence",
            "scene_hierarchy inspects the edited scene, not the running game's Remote Inspector",
            "Ordinary editor may add only known config/features metadata and normalize order/comments/whitespace; before/after settings are recorded",
            "Ordinary editor generated missing UID files in disposable projects; this is not sealed-source verification"],
        "cases": [], "passed": False}
    try:
        assert port_free(), "port 3000 occupied; will not connect to an unrelated editor"
        for kind in ("installer", "template"):
            case = run_case(work, kind)
            result["cases"].append(case)
            if not case["passed"]:
                break
        result["endpointClosed"] = port_free()
        result["passed"] = len(result["cases"]) == 2 and all(
            case["passed"] for case in result["cases"]) and result["endpointClosed"]
    except Exception as exc:
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    result["durationSeconds"] = time.monotonic() - started
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result.get(key) for key in ("passed", "failure", "durationSeconds")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

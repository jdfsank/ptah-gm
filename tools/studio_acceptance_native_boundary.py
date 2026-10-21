"""Disposable native boundary checks; live model tests require --live explicitly."""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.codex_driver import CodexDriver
from runners.common import stop_process_group
from runners.native_adapter import ManagedNativeContext
from runners.static_tools import StaticToolBroker


def native_probes(root, work, tmp):
    context = ManagedNativeContext.create(tmp / "probe-native", "my_proxy", model="gpt-6-luna")
    canary = context.real_auth_root / ("studio-boundary-canary-" + root.name)
    canary.write_text("synthetic-authentication-canary")
    marker = work / "executed.marker"
    script = work / "project-script.py"
    script.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n")
    events = queue.Queue()
    proc = None
    result = {}
    try:
        proc = subprocess.Popen(context.command(context.executable()), cwd=context.root, env=context.environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True)
        def read():
            for line in proc.stdout:
                events.put(json.loads(line))
            events.put(None)
        threading.Thread(target=read, daemon=True).start()
        def rpc(number, method, params):
            proc.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            while True:
                event = events.get(timeout=10)
                if event is None:
                    raise RuntimeError("native closed before response")
                if event.get("id") == number:
                    return event
        initialized = rpc(1, "initialize", {"clientInfo": {"name": "studio-boundary-probe", "version": "1"},
            "capabilities": {"experimentalApi": True}})
        result["initialized"] = "result" in initialized
        proc.stdin.write('{"method":"initialized","params":{}}\n'); proc.stdin.flush()
        for number, (key, path) in enumerate({"auth": canary, "backend": ROOT / "backend/codex_driver.py",
                                              "project": work / "GDD.md", "other": root / "other/canary"}.items(), 2):
            response = rpc(number, "fs/readFile", {"path": str(path)})
            result[key] = {"denied": "error" in response,
                           "error": context.redact(response.get("error"))}
        response = rpc(7, "command/exec", {"command": [sys.executable, str(script)],
            "cwd": str(work), "sandboxPolicy": {"type": "readOnly", "networkAccess": False}, "timeoutMs": 3000})
        result["projectExecution"] = {"denied": "error" in response or (response.get("result") or {}).get("exitCode") != 0,
            "markerAbsent": not marker.exists(), "error": context.redact(response.get("error"))}
        result["secretsPersisted"] = context.secrets_on_disk()
    finally:
        if proc is not None:
            result["nativeStopped"] = stop_process_group(proc.pid, process=proc, grace_seconds=1)
            proc.stdin.close(); proc.stdout.close()
        context.close()
        result["routingHostStopped"] = context.tool_host is not None and context.tool_host.process.poll() is not None
        canary.unlink(missing_ok=True)
    result["passed"] = (result.get("initialized") and all(result[key]["denied"] for key in
        ("auth", "backend", "project", "other", "projectExecution")) and result["projectExecution"]["markerAbsent"]
        and not result["secretsPersisted"] and result["nativeStopped"] and result["routingHostStopped"])
    return result


def live_role(work, tmp, role):
    context = ManagedNativeContext.create(tmp / (role + "-native"), "my_proxy", model="gpt-6-luna")
    broker = StaticToolBroker(work, role, ["scripts/**/*.gd"] if role == "produce" else [], tmp)
    request = ("Read GDD.md with studio_read_file, then return JSON containing its contents as sentinel."
               if role == "plan" else "Read GDD.md. Use studio_write_file to create scripts/acceptance.gd with exactly "
               "extends Node\n\nfunc _ready() -> void:\n\tpass\n. Return JSON with status written. Perform actual static tools.")
    try:
        result = CodexDriver(context.root, timeout=60, model="gpt-6-luna", model_provider="my_proxy",
            reasoning_effort="max", execution_profile="managed_read_only" if role == "plan" else "managed_workspace_write",
            managed_native_context=context, static_tool_broker=broker).run({"test_data": True, "request": request,
                "allowedFiles": ["scripts/**/*.gd"] if role == "produce" else []})
    finally:
        context.close()
    success = ("static-sentinel-acceptance-20261012" in result["response"] if role == "plan"
               else (work / "scripts/acceptance.gd").read_text() == "extends Node\n\nfunc _ready() -> void:\n\tpass\n"
               if (work / "scripts/acceptance.gd").is_file() else False)
    result["acceptance"] = {"passed": success and result["status"] == "completed" and broker.calls > 0,
                            "staticToolCalls": broker.calls,
                            "routingHostStopped": context.tool_host.process.poll() is not None}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    result = {"scope": "temporary synthetic canaries; exact separated native/host/tool processes",
              "modelTurns": 2 if args.live else 0, "capabilitiesEnabled": [], "roles": {}}
    with tempfile.TemporaryDirectory(prefix="studio-native-boundary-") as directory:
        root = Path(directory).resolve(); work = root / "work"; work.mkdir()
        (work / "GDD.md").write_text("static-sentinel-acceptance-20261012")
        (root / "other").mkdir(); (root / "other/canary").write_text("synthetic-other-project")
        tmp = work / ".runner-tmp"; tmp.mkdir()
        result["boundary"] = native_probes(root, work, tmp)
        if args.live:
            # Each context has its own native runtime and isolated routing host.
            for role in ("plan", "produce"):
                result["roles"][role] = live_role(work, tmp, role)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"boundaryPassed": result["boundary"]["passed"],
                      "roles": {key: value["acceptance"] for key, value in result["roles"].items()},
                      "evidence": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

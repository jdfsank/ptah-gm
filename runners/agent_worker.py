"""Sandbox child used for one native planning or production attempt."""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import uuid
from datetime import datetime, timezone


def _emit(event: str, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False), flush=True)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("expected workspace root")
    workspace = os.path.realpath(sys.argv[1])
    request = json.loads(sys.stdin.read())
    if not isinstance(request, dict) or set(request) != {"execution", "material"}:
        raise SystemExit("worker request shape is invalid")
    execution, material = request["execution"], request["material"]
    if not isinstance(execution, dict) or not isinstance(material, dict):
        raise SystemExit("worker request members must be objects")
    profile = execution.get("profileSnapshot") or {}
    task_kind = execution.get("taskKind")
    packet = material.get("packet")
    if not isinstance(packet, dict):
        raise SystemExit("execution input is missing its frozen packet")
    from backend.codex_driver import CodexDriver
    from runners.native_adapter import ManagedNativeContext
    from runners.static_tools import StaticToolBroker

    # This worker is a trusted adapter. Native authentication and project file
    # tools start in separate initial sandboxes; neither inherits the other's
    # filesystem permissions or environment.
    from pathlib import Path
    tmp = Path(workspace) / ".runner-tmp"
    native_context = None
    driver_entered = False
    setup_error_type = None
    cancel_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: cancel_event.set())

    def started(lease):
        _emit("started", nativeIdentity={"threadId": None, "turnId": None,
                    "processId": lease.get("pid"), "processGroupId": lease.get("processGroupId"),
                    "processStartTime": lease.get("startedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})

    def activity(event):
        _emit("activity", activity=event)

    def usage(value):
        _emit("usage", usage=value)

    def native_observation(value):
        _emit("nativeObservation", observation=value)

    try:
        native_context = ManagedNativeContext.create(tmp / "native", profile.get("modelProvider"), model=profile.get("modelKey"))
        images = native_context.stage_images(material.get("referenceImages", []))
        tools = StaticToolBroker(Path(workspace), "plan" if task_kind == "visual-plan" else task_kind, packet.get("allowedFiles", []), tmp)
        profile_name = "managed_read_only" if task_kind in {"plan", "visual-plan"} else "managed_workspace_write"
        driver = CodexDriver(
            native_context.root,
            timeout=float((profile.get("limits") or {}).get("maxDurationSeconds", 420)),
            model=profile.get("modelKey"),
            model_provider=profile.get("modelProvider"),
            reasoning_effort=profile.get("effort"),
            expected_catalog_revision=profile.get("catalogRevision"),
            execution_profile=profile_name,
            disabled_mcp_servers=["godot-mcp"],
            managed_native_context=native_context,
            static_tool_broker=tools,
        )
        # Prepare the routing host before entering any path that can spawn a
        # native app-server. A confirmed failure here is safe to retry later.
        native_context.command(native_context.executable())
        driver_entered = True
        result = driver.run(packet, cancel_event=cancel_event,
                            reference_images=images,
                            on_process_started=started, on_activity=activity, on_usage=usage,
                            on_native_observation=native_observation)
        result.setdefault("diagnostics", {})["providerBridge"] = native_context.bridge.diagnostic_summary()
    except Exception as exc:
        if driver_entered:
            raise
        setup_error_type = type(exc).__name__
    finally:
        # This event precedes teardown and also survives a driver exception;
        # the parent can retain bridge metadata without a terminal result.
        try:
            if native_context is not None:
                _emit("diagnostic", providerBridge=native_context.bridge.diagnostic_summary())
        finally:
            if native_context is not None:
                native_context.close()
    if setup_error_type is not None:
        # Emitted only after successful adapter teardown. No private error body
        # crosses the event channel and no app-server has been started.
        _emit("setupFailed", errorType=setup_error_type)
        return
    native_id = result.get("sessionId")
    _emit("result", nativeIdentity={"threadId": native_id, "turnId": result.get("turnId")}, result=result)


if __name__ == "__main__":
    main()

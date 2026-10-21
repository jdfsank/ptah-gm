"""Deterministic, zero-turn isolation probe for managed agent registration."""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.codex_driver import CodexDriver, CodexDriverError, _configured_model_provider
from backend.role_evidence import REQUIRED_ROLE_CHECKS
from .common import RunnerError
from .native_adapter import ManagedNativeContext
from .static_tools import StaticToolBroker


SCHEMA_VERSION = "studio.role-probe.v1"
PLANNING_CAPABILITY = "planning-readonly-v1"
PRODUCTION_CAPABILITY = "production-private-v1"

# The backend module is the single source of truth for these capability checks.
# Keep the evidence contract in sync by selecting only its agent role entries.
AGENT_REQUIRED_ROLE_CHECKS = {
    cap: REQUIRED_ROLE_CHECKS[cap]
    for cap in (PLANNING_CAPABILITY, PRODUCTION_CAPABILITY)
}
_PLANNER_CHECKS = tuple(name for name in AGENT_REQUIRED_ROLE_CHECKS[PLANNING_CAPABILITY]
                        if name.startswith("planner"))
_PRODUCER_CHECKS = tuple(name for name in AGENT_REQUIRED_ROLE_CHECKS[PRODUCTION_CAPABILITY]
                         if name.startswith("producer"))
_NATIVE_CHECKS = tuple(name for name in AGENT_REQUIRED_ROLE_CHECKS[PLANNING_CAPABILITY]
                       if name.startswith("native") or name.startswith("routing"))
_TOOL_CHECKS = tuple(name for name in AGENT_REQUIRED_ROLE_CHECKS[PLANNING_CAPABILITY]
                    if name.startswith("tool"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _listener(family: int, address: str):
    server = socket.socket(family, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((address, 0))
    server.listen(2)
    server.settimeout(1)
    return server


def _denial_observed(response: dict) -> bool:
    """Recognize an OS sandbox denial without retaining the native response."""
    error = response.get("error") if isinstance(response, dict) else None
    if not isinstance(error, dict):
        return False
    detail = json.dumps(error, ensure_ascii=True).lower()
    return any(marker in detail for marker in
               ("operation not permitted", "permission denied", "eacces", "eperm", "sandbox denied"))


def _run_native_rpc_probe(rpc, context: ManagedNativeContext, project_file: Path,
                          sibling_file: Path, backend_file: Path,
                          auth_file: Path) -> dict:
    """Observe file and command denials through the initialized native RPC."""
    checks = {name: False for name in _NATIVE_CHECKS
              if name not in {"nativeAppServerInitialized", "nativeProcessStopped",
                              "nativeSecretsAbsent", "routingHostStarted", "routingHostStopped"}
              and not name.startswith("nativeSharedPolicy")}
    private_file = context.root / "codex" / "config.toml"
    targets = {
        "nativePrivateReadAllowed": private_file,
        "nativeAuthReadDenied": auth_file,
        "nativeBackendReadDenied": backend_file,
        "nativeProjectReadDenied": project_file,
        "nativeOtherProjectReadDenied": sibling_file,
    }
    for name, path in targets.items():
        try:
            response = rpc("fs/readFile", {"path": str(path)})
            succeeded = isinstance(response, dict) and "result" in response and "error" not in response
            checks[name] = succeeded if name == "nativePrivateReadAllowed" else _denial_observed(response)
        except Exception:
            checks[name] = False

    marker = project_file.parent / "native-command-marker"
    script = project_file.parent / "native-command-probe.py"
    script.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n",
                       encoding="utf-8")
    try:
        response = rpc("command/exec", {
            "command": [sys.executable, str(script)],
            "cwd": str(project_file.parent),
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            "timeoutMs": 2000,
        })
        checks["nativeCommandExecDenied"] = _denial_observed(response)
    except Exception:
        checks["nativeCommandExecDenied"] = False
    checks["nativeCommandMarkerAbsent"] = not marker.exists()
    return checks


def _run_native_shared_policy_probe(context: ManagedNativeContext, timeout: float) -> dict:
    """Exercise only loopback policy through a marked shared-policy worker."""
    result = {name: False for name in _NATIVE_CHECKS if name.startswith("nativeSharedPolicy")}
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        return result
    ipv4_listener = ipv6_listener = None
    try:
        ipv4_listener = _listener(socket.AF_INET, "127.0.0.1")
        ipv6_listener = _listener(socket.AF_INET6, "::1")
        native_executable = context.executable()
        command = context.command(native_executable)
        # Reuse the native policy unchanged in a short worker that applies it
        # to itself before making any network call.
        policy = command[2]
        probe_python = str(Path(sys.executable).resolve(strict=True))
        if "(deny process-exec" not in policy:
            return result
        script = r'''import ctypes, json, socket, sys
lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
lib.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
lib.sandbox_init.restype = ctypes.c_int
error = ctypes.c_char_p()
if lib.sandbox_init(sys.argv[1].encode(), 0, ctypes.byref(error)):
    raise SystemExit(2)
ports = json.loads(sys.argv[2])
out = {}
for name, host, port in ports:
    try:
        sock = socket.create_connection((host, port), timeout=.4)
        sock.close()
        out[name] = True
    except OSError:
        out[name] = False
print(json.dumps(out, sort_keys=True))
'''
        bridge_port = context.bridge.port
        probe_ports = [
            ("ipv4", "127.0.0.1", ipv4_listener.getsockname()[1]),
            ("ipv6", "::1", ipv6_listener.getsockname()[1]),
            ("bridge", "127.0.0.1", bridge_port),
        ]
        proc = subprocess.run(
            [probe_python, "-c", script, policy, json.dumps(probe_ports)],
            cwd=str(context.root), capture_output=True, text=True, timeout=timeout,
            check=False, env=context.environment(),
        )
        if proc.returncode != 0:
            return result
        observed = json.loads(proc.stdout)
        result.update(
            nativeSharedPolicyWorkerExecuted=True,
            nativeSharedPolicyLoopbackIPv4Denied=observed.get("ipv4") is False,
            nativeSharedPolicyLoopbackIPv6Denied=observed.get("ipv6") is False,
            nativeSharedPolicyBridgeAllowed=observed.get("bridge") is True,
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        pass
    finally:
        if ipv4_listener is not None:
            ipv4_listener.close()
        if ipv6_listener is not None:
            ipv6_listener.close()
    return result


def _run_static_boundary_probe(workspace: Path, private_tmp: Path, auth_root: Path,
                               other_project: Path, host_root: Path, timeout: float,
                               role: str, scope: list[str]) -> dict:
    checks = {name: False for name in _TOOL_CHECKS if name != "toolWorkspaceReadAllowed"}
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        return checks
    auth_file = auth_root / "auth-canary"
    backend_file = host_root / "backend" / "codex_driver.py"
    native_runtime = workspace / ".runner-tmp" / "native" / "runtime-canary"
    native_code_host = workspace / ".runner-tmp" / "native-code-host" / "host-canary"
    other_file = other_project / "other-canary"
    for target, content in ((auth_file, "synthetic-auth-canary"),
                            (native_runtime, "synthetic-native-runtime-canary"),
                            (native_code_host, "synthetic-code-host-canary"),
                            (other_file, "synthetic-other-project-canary")):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    listeners = []
    try:
        listeners = [_listener(socket.AF_INET, "127.0.0.1"), _listener(socket.AF_INET6, "::1")]
        request = {"root": str(workspace), "tmp": str(private_tmp), "authRoot": str(auth_root),
                   "role": role, "scope": scope}
        paths = {"auth": str(auth_file), "backend": str(backend_file), "other": str(other_file),
                 "native": str(native_runtime), "codeHost": str(native_code_host)}
        ports = [("ipv4", "127.0.0.1", listeners[0].getsockname()[1]),
                 ("ipv6", "::1", listeners[1].getsockname()[1])]
        program = r'''import json, os, socket, subprocess, sys
from pathlib import Path
from runners.static_tools import _apply_operation_boundary
r=json.loads(sys.argv[1]); paths=json.loads(sys.argv[2]); ports=json.loads(sys.argv[3]); script=sys.argv[4]
_apply_operation_boundary(r)
out={}
for name,path in paths.items():
    try:
        with open(path,"rb") as stream: stream.read(1)
        out[name+"ReadDenied"]=False
    except OSError: out[name+"ReadDenied"]=True
for name in ("auth","backend","other"):
    descriptor=None
    try:
        descriptor=os.open(paths[name],os.O_WRONLY|getattr(os,"O_NOFOLLOW",0))
        out[name+"WriteDenied"]=False
    except OSError: out[name+"WriteDenied"]=True
    finally:
        if descriptor is not None: os.close(descriptor)
try:
    subprocess.run([sys.executable,script],check=True,timeout=1)
    out["execDenied"]=False
except (OSError,subprocess.SubprocessError): out["execDenied"]=True
try:
    pid=os.fork()
except OSError: out["forkDenied"]=True
else:
    if pid==0: os._exit(0)
    os.waitpid(pid,0); out["forkDenied"]=False
for name,host,port in ports:
    try:
        sock=socket.create_connection((host,port),timeout=.4); sock.close(); out[name+"Denied"]=False
    except OSError: out[name+"Denied"]=True
print(json.dumps(out,sort_keys=True))
'''
        command_script = workspace / "probe-command.py"
        command_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c", program, json.dumps(request), json.dumps(paths),
             json.dumps(ports), str(command_script)],
            cwd=str(host_root), capture_output=True, text=True, timeout=timeout, check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": str(private_tmp), "TMPDIR": str(private_tmp),
                 "PYTHONPATH": str(host_root), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
        )
        if proc.returncode != 0:
            return checks
        observed = json.loads(proc.stdout)
        checks.update(
            toolAuthReadDenied=observed.get("authReadDenied") is True,
            toolBackendReadDenied=observed.get("backendReadDenied") is True,
            toolOtherProjectReadDenied=observed.get("otherReadDenied") is True,
            toolAuthWriteDenied=observed.get("authWriteDenied") is True,
            toolBackendWriteDenied=observed.get("backendWriteDenied") is True,
            toolOtherProjectWriteDenied=observed.get("otherWriteDenied") is True,
            toolNetworkIPv4Denied=observed.get("ipv4Denied") is True,
            toolNetworkIPv6Denied=observed.get("ipv6Denied") is True,
            toolProcessExecDenied=observed.get("execDenied") is True,
            toolProcessForkDenied=observed.get("forkDenied") is True,
            toolProtectedNativeRuntimeReadDenied=observed.get("nativeReadDenied") is True,
            toolProtectedCodeHostReadDenied=observed.get("codeHostReadDenied") is True,
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        pass
    finally:
        for listener in listeners:
            listener.close()
    return checks


def _prepare_probe_tree(root: Path):
    project = root / "synthetic-project"
    sibling = root / "synthetic-other-project"
    auth = root / "synthetic-auth"
    private_tmp = root / "static-tmp"
    workspace_tmp = project / ".runner-tmp"
    for folder in (project, sibling, auth, private_tmp, workspace_tmp):
        folder.mkdir(parents=True, exist_ok=True)
    (project / "GDD.md").write_text("role probe workspace", encoding="utf-8")
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (sibling / "other-canary").write_text("synthetic other project", encoding="utf-8")
    return project, sibling, auth, private_tmp


def _probe_static_roles(project: Path, sibling: Path, auth: Path, private_tmp: Path,
                        host_root: Path, timeout: float) -> tuple[dict, dict]:
    checks = {"planning": {name: False for name in _TOOL_CHECKS},
              "production": {name: False for name in _TOOL_CHECKS}}
    planning = {name: False for name in _PLANNER_CHECKS}
    production = {name: False for name in _PRODUCER_CHECKS}
    try:
        planner = StaticToolBroker(project, "plan", [], private_tmp)
        planning["plannerWriteToolNotExposed"] = all(
            spec.get("name") != "studio_write_file" for spec in planner.specifications())
        try:
            planner.call("studio_write_file", {"path": "scripts/probe.gd", "content": "probe"})
        except RunnerError:
            planning["plannerWriteRejected"] = True
        read = planner.call("studio_read_file", {"path": "GDD.md"})
        if read.get("success") and json.loads(read["contentItems"][0]["text"]).get("content") == "role probe workspace":
            checks["planning"]["toolWorkspaceReadAllowed"] = True
        producer = StaticToolBroker(project, "produce", ["scripts/**/*.gd"], private_tmp)
        producer_read = producer.call("studio_read_file", {"path": "GDD.md"})
        if (producer_read.get("success")
                and json.loads(producer_read["contentItems"][0]["text"]).get("content") == "role probe workspace"):
            checks["production"]["toolWorkspaceReadAllowed"] = True
        scoped = producer.call("studio_write_file", {"path": "scripts/probe.gd", "content": "extends Node\n"})
        production["producerScopedWriteAllowed"] = scoped.get("success") is True
        out_of_scope = producer.call("studio_write_file", {"path": "studio/probe.gd", "content": "forbidden"})
        production["producerOutOfScopeWriteDenied"] = out_of_scope.get("success") is False
    except (OSError, RunnerError, ValueError, KeyError, IndexError, TypeError):
        pass
    checks["planning"].update(_run_static_boundary_probe(
        project, private_tmp, auth, sibling, host_root, timeout, "plan", []))
    checks["production"].update(_run_static_boundary_probe(
        project, private_tmp, auth, sibling, host_root, timeout, "produce", ["scripts/**/*.gd"]))
    return checks, {**planning, **production}


def _not_verified_probe(runner_id: str, failure_code: str) -> dict:
    roles = {cap: {"checks": {name: False for name in required}}
             for cap, required in AGENT_REQUIRED_ROLE_CHECKS.items()}
    return {
        "evidence": {
            "schemaVersion": SCHEMA_VERSION,
            "runnerKind": "agent",
            "runnerId": runner_id,
            "probeId": str(uuid.uuid4()),
            "observedAt": _utc_now(),
            "policy": "deny-default",
            "status": "NOT_VERIFIED",
            "verifiedCapabilities": [],
            "roleAssessment": {cap: "NOT_VERIFIED" for cap in roles},
            "roles": roles,
            "nativeNetworkDirectRpcObserved": False,
            "nativeNetworkEvidenceBasis": "shared-policy-self-test-subprocess",
            "probeFailureCode": failure_code,
        },
        "catalog": {"models": [], "nativeVersion": None, "environment": platform.platform()},
    }


def run_agent_role_probe(runner_id: str, workspace_root: Path, *, timeout: float = 12) -> dict:
    """Run the probe and always return fail-closed evidence on probe errors."""
    if not isinstance(runner_id, str) or not runner_id:
        raise RunnerError("role probe requires the registered runner identity")
    try:
        return _run_agent_role_probe(runner_id, workspace_root, timeout=timeout)
    except Exception as exc:
        return _not_verified_probe(runner_id, type(exc).__name__)


def _run_agent_role_probe(runner_id: str, workspace_root: Path, *, timeout: float = 12) -> dict:
    """Run native and static role checks without submitting a model turn.

    The result always carries a closed set of boolean checks. A role is
    verified only when every required observation for that role is true.
    """
    workspace_root = Path(workspace_root).resolve()
    host_root = Path(__file__).resolve().parents[1]
    role_checks = {cap: {name: False for name in required}
                   for cap, required in AGENT_REQUIRED_ROLE_CHECKS.items()}
    catalog = {"models": [], "nativeVersion": None, "environment": platform.platform()}
    native_lifecycle = {}
    failure_code = None
    with tempfile.TemporaryDirectory(prefix="studio-role-probe-") as directory:
        root = Path(directory)
        project, sibling, synthetic_auth, private_tmp = _prepare_probe_tree(root)
        static_checks, role_specific = _probe_static_roles(
            project, sibling, synthetic_auth, private_tmp, host_root, timeout)
        role_checks[PLANNING_CAPABILITY].update(static_checks["planning"])
        role_checks[PRODUCTION_CAPABILITY].update(static_checks["production"])
        role_checks[PLANNING_CAPABILITY].update({k: bool(v) for k, v in role_specific.items()
                                                 if k.startswith("planner")})
        role_checks[PRODUCTION_CAPABILITY].update({k: bool(v) for k, v in role_specific.items()
                                                   if k.startswith("producer")})

        context = None
        native_workspace = root / "native-context"
        native_rpc_checks = {name: False for name in _NATIVE_CHECKS
                             if name not in {"nativeAppServerInitialized", "nativeProcessStopped",
                                             "nativeSecretsAbsent", "routingHostStarted", "routingHostStopped"}
                             and not name.startswith("nativeSharedPolicy")}
        try:
            provider = _configured_model_provider()
            if not provider:
                raise RunnerError("managed provider is not configured")
            context = ManagedNativeContext.create(native_workspace, provider, model=None)
            def observe_native_rpc(rpc):
                native_rpc_checks.update(_run_native_rpc_probe(
                    rpc, context, project / "project.godot", sibling / "other-canary",
                    host_root / "backend" / "codex_driver.py",
                    Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "config.toml",
                ))
            catalog = CodexDriver.model_catalog(context.root, timeout=timeout,
                                                managed_native_context=context,
                                                lifecycle=native_lifecycle,
                                                on_initialized=observe_native_rpc)
        except Exception as exc:
            failure_code = type(exc).__name__
        finally:
            if context is not None:
                checks = {**native_rpc_checks, **_run_native_shared_policy_probe(context, timeout)}
                for capability in role_checks:
                    role_checks[capability].update({name: bool(value) for name, value in checks.items()
                                                    if name in role_checks[capability]})
                role_checks[PLANNING_CAPABILITY]["nativeAppServerInitialized"] = bool(
                    native_lifecycle.get("nativeAppServerInitialized"))
                role_checks[PLANNING_CAPABILITY]["nativeProcessStopped"] = bool(
                    native_lifecycle.get("nativeProcessStopped"))
                role_checks[PRODUCTION_CAPABILITY]["nativeAppServerInitialized"] = bool(
                    native_lifecycle.get("nativeAppServerInitialized"))
                role_checks[PRODUCTION_CAPABILITY]["nativeProcessStopped"] = bool(
                    native_lifecycle.get("nativeProcessStopped"))
                host = context.tool_host
                started = bool(host is not None and host.process.poll() is None)
                for capability in role_checks:
                    role_checks[capability]["routingHostStarted"] = started
                secrets_absent = not context.secrets_on_disk()
                for capability in role_checks:
                    role_checks[capability]["nativeSecretsAbsent"] = secrets_absent
                try:
                    context.close()
                except Exception:
                    pass
                stopped = bool(host is not None and host.process.poll() is not None)
                for capability in role_checks:
                    role_checks[capability]["routingHostStopped"] = stopped

    verified = [capability for capability, checks in role_checks.items()
                if all(checks.get(name) is True for name in AGENT_REQUIRED_ROLE_CHECKS[capability])]
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "runnerKind": "agent",
        "runnerId": runner_id,
        "probeId": str(uuid.uuid4()),
        "observedAt": _utc_now(),
        "policy": "deny-default",
        "status": "PASS" if verified else "NOT_VERIFIED",
        "verifiedCapabilities": verified,
        "roleAssessment": {capability: "PASS" if capability in verified else "NOT_VERIFIED"
                           for capability in role_checks},
        "roles": {capability: {"checks": checks} for capability, checks in role_checks.items()},
        "nativeNetworkDirectRpcObserved": False,
        "nativeNetworkEvidenceBasis": "shared-policy-self-test-subprocess",
    }
    if failure_code:
        evidence["nativeProbeFailureCode"] = failure_code
    if catalog.get("nativeVersion"):
        evidence["nativeVersion"] = catalog["nativeVersion"]
    return {"evidence": evidence, "catalog": catalog}


def managed_model_catalog(workspace_root: Path, *, timeout: float = 10, cancel_event=None) -> dict:
    """Refresh models through the same isolated native profile used at register."""
    provider = _configured_model_provider()
    if not provider:
        raise CodexDriverError("managed provider is not configured")
    with tempfile.TemporaryDirectory(prefix="studio-model-catalog-") as directory:
        context = ManagedNativeContext.create(Path(directory) / "native", provider, model=None)
        try:
            return CodexDriver.model_catalog(context.root, timeout=timeout,
                                            managed_native_context=context, cancel_event=cancel_event)
        finally:
            context.close()

"""ProjectRunner for immutable artifact verification and isolated previews."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import (LocalJournal, RunnerError, RunnerHTTP, protected_siblings,
                     RunnerLock, sandbox_probe, stop_process_group,
                     retry_transport, service_loop, process_output_lines,
                     materialize_service_records)
from .godot_runtime import GodotRuntime, GodotRuntimeError, sandboxed_godot_argv
from .image_imports import missing_image_imports, read_generated_imports


class PreviewImportError(RunnerError):
    def __init__(self, message, *, stopped=True, stop_reason="native_error", process_started=False):
        super().__init__(message)
        self.stopped = stopped
        self.stop_reason = stop_reason
        self.process_started = process_started


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                           text=True, timeout=15, check=False)
    if result.returncode:
        raise RunnerError("artifact Git operation failed: " + result.stderr.strip())
    return result.stdout.strip()


def _source_unchanged(project: Path, commit: str) -> bool:
    if _git(project, "rev-parse", "HEAD") != commit:
        return False
    tracked_cache = _git(project, "ls-files", "--", ".godot")
    if tracked_cache:
        return _git(project, "status", "--porcelain", "--untracked-files=all") == ""
    return _git(project, "status", "--porcelain", "--untracked-files=all", "--", ".", ":!.godot") == ""


def verification_checks(report: dict) -> list[dict]:
    """Project actual per-item verdicts; keep command argv and private logs out."""
    items = report.get("requirements") or report.get("checks") or []
    if not isinstance(items, list):
        items = []
    checks = []
    for index, item in enumerate(items[:180]):
        if isinstance(item, dict):
            status = item.get("status")
            summary = item.get("summary", item.get("evidence", ""))
            if not isinstance(summary, str):
                summary = json.dumps(summary, ensure_ascii=False)
            if status not in {"PASS", "FAIL", "SKIPPED"}:
                summary = f"未执行或未提供逐项结论（{status or 'unknown'}）：{summary}"
                status = "SKIPPED"
            checks.append({"id": str(item.get("id") or f"check-{index + 1}")[:120],
                "status": status, "summary": summary[:400]})
        else:
            checks.append({"id": f"check-{index + 1}", "status": "SKIPPED",
                "summary": ("未提供逐项结论：" + str(item))[:400]})
    # Only error lines from known engine stages are exposed, never whole
    # commands, argv, sandbox profiles or unbounded stdout/stderr.
    errors = []
    for command in report.get("commands", []):
        if not isinstance(command, dict) or command.get("name") not in {"fresh_import", "backend_runtime_smoke"}:
            continue
        for stream in (command.get("stdout"), command.get("stderr")):
            if not isinstance(stream, str):
                continue
            for line in stream[-16000:].splitlines():
                if re.match(r"^\s*(?:SCRIPT )?ERROR:", line) and line.strip() not in errors:
                    errors.append(line.strip())
    for index, message in enumerate(errors[:20]):
        checks.append({"id": f"godot.engine_error.{index + 1}", "status": "FAIL", "summary": message[:400]})
    if not checks:
        checks.append({"id": "verification.result", "status": "SKIPPED", "summary": "验证器未提供逐项检查结果。"})
    return checks


class ProjectRunner:
    def __init__(self, api: RunnerHTTP, journal: LocalJournal, artifact_root: Path,
                 protected_root: Path, godot_path: str | None = None, stop_event=None):
        self.api, self.journal = api, journal
        self.artifact_root = artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.protected_root = protected_root.resolve()
        self.runner_id = journal.runner_id
        self.godot_path = godot_path
        self.stop_event = stop_event

    def register(self):
        from backend.role_evidence import REQUIRED_ROLE_CHECKS, verified_roles

        try:
            from .project_role_probe import run_project_role_probe
            evidence = run_project_role_probe(self.runner_id, self.godot_path)
        except Exception as exc:
            # Registration must also clear previously granted roles if the
            # local probe cannot start or fails before returning evidence.
            now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            evidence = {
                "schemaVersion": "studio.role-probe.v1",
                "runnerId": self.runner_id,
                "runnerKind": "project",
                "probeId": f"project-role-probe-failed-{time.time_ns()}",
                "observedAt": now,
                "policy": "deny-default",
                "status": "NOT_VERIFIED",
                "probeFailureCode": type(exc).__name__,
                "roles": {
                    capability: {"checks": {name: False for name in REQUIRED_ROLE_CHECKS[capability]}}
                    for capability in ("verification-isolated-v1", "preview-isolated-v1")
                },
            }
        capabilities = verified_roles(evidence, self.runner_id, "project")
        return self.api.request("POST", "/internal/v1/register", {
            "runnerId": self.runner_id, "runnerKind": "project",
            "environment": {"os": os.uname().sysname, "artifactRoot": str(self.artifact_root)},
            "nativeVersion": None,
            "capabilities": capabilities,
            "sandboxEvidence": evidence,
        })

    def materialize(self, artifact_ref: dict, destination: Path) -> tuple[Path, str]:
        required = {"artifactId", "projectId", "jobId", "attemptId", "sourceCommit", "inputCommit", "packetId"}
        if not isinstance(artifact_ref, dict) or set(artifact_ref) != required:
            raise RunnerError("artifact reference has an invalid shape")
        artifact_id = artifact_ref["artifactId"]
        if not isinstance(artifact_id, str) or not artifact_id.replace("-", "").replace("_", "").isalnum():
            raise RunnerError("artifact ID is invalid")
        source_raw = self.artifact_root / artifact_id / "repository"
        if source_raw.is_symlink() or (source_raw.parent.is_symlink()):
            raise RunnerError("artifact repository path cannot be a symlink")
        source = source_raw.resolve(strict=True)
        if not source.is_relative_to(self.artifact_root) or not source.is_dir():
            raise RunnerError("artifact repository is outside the configured artifact vault")
        commit = _git(source, "rev-parse", "--verify", "HEAD^{commit}")
        if commit != artifact_ref["sourceCommit"]:
            raise RunnerError("artifact HEAD does not match the sealed sourceCommit")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            raise RunnerError("verification destination already exists")
        clone = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-local",
                                "--no-checkout", str(source), str(destination)],
                               capture_output=True, text=True, timeout=60, check=False)
        if clone.returncode:
            raise RunnerError("cannot create independent verification copy: " + clone.stderr.strip())
        _git(destination, "remote", "remove", "origin")
        _git(destination, "checkout", "--detach", commit)
        if _git(destination, "rev-parse", "HEAD") != commit or _git(destination, "status", "--porcelain"):
            raise RunnerError("verification copy does not match the sealed artifact")
        return destination, commit

    def verify(self, execution: dict, store_id: str, *, max_seconds: float = 180):
        attempt, project_id = execution.get("attemptId"), execution.get("projectId")
        if not isinstance(attempt, str) or not isinstance(project_id, str):
            raise RunnerError("verification request is missing identities")
        self.journal.start_intent(attempt, execution)
        evidence = sandbox_probe()
        if not evidence.get("passed"):
            self.journal.add_report(attempt, "failed", store_id, project_id, self.runner_id,
                {"stopped": True, "stopReason": "sandbox_unavailable", "diagnosticRef": evidence})
            return
        refs = execution.get("inputRefs", {})
        artifact_ref = refs.get("artifactRef") if isinstance(refs, dict) else None
        if not attempt.replace("-", "").replace("_", "").isalnum():
            raise RunnerError("verification attempt ID is unsafe")
        work = self.artifact_root / "verification" / attempt
        if work.exists():
            raise RunnerError("verification evidence workspace already exists")
        project, commit = self.materialize(artifact_ref, work)
        material = self.api.request("GET", f"/internal/v1/attempts/{attempt}/input")
        packet = material.get("packet")
        if not isinstance(packet, dict) or not isinstance(packet.get("document"), dict):
            raise RunnerError("verification input is missing the frozen object document")
        prepared = material.get("prepared") if isinstance(material.get("prepared"), dict) else {}
        input_commit = artifact_ref.get("inputCommit") if isinstance(artifact_ref, dict) else None
        source_commit = artifact_ref.get("sourceCommit") if isinstance(artifact_ref, dict) else None
        if (not isinstance(input_commit, str) or not input_commit.strip()
                or not isinstance(source_commit, str) or not source_commit.strip()):
            raise RunnerError("verification artifact reference is missing its input/source commit binding")
        if prepared.get("inputCommit") is not None and prepared["inputCommit"] != input_commit:
            raise RunnerError("verification artifact inputCommit does not match the prepared input")
        if refs.get("inputCommit") is not None and refs["inputCommit"] != input_commit:
            raise RunnerError("verification artifact inputCommit does not match the attempt reference")
        if refs.get("sourceCommit") is not None and refs["sourceCommit"] != source_commit:
            raise RunnerError("verification artifact sourceCommit does not match the attempt reference")
        if packet.get("id") is not None and artifact_ref.get("packetId") != packet["id"]:
            raise RunnerError("verification artifact packetId does not match the frozen packet")
        materialize_service_records(project, prepared.get("serviceRecords"))
        from backend.source_preparation import load_uid_preparation_evidence
        try:
            prepared_sidecars, prepared_engine_version = load_uid_preparation_evidence(
                self.artifact_root / artifact_ref["artifactId"],
                input_commit=input_commit,
                source_commit=commit,
            )
        except (OSError, ValueError) as exc:
            raise RunnerError(f"sealed artifact UID preparation evidence is invalid: {exc}") from exc
        request = {
            "document": packet["document"],
            "baseCommit": input_commit,
            "godotPath": self.godot_path,
            "serviceRecords": prepared.get("serviceRecords"),
            "preparedUidSidecars": {
                path: content.decode("ascii") for path, content in prepared_sidecars.items()
            },
            "expectedUidEngineVersion": prepared_engine_version,
        }
        temp_root = self.artifact_root / "verification-temp" / attempt
        temp_root.mkdir(mode=0o700, parents=True, exist_ok=False)
        runtime = GodotRuntime.create(temp_root / "godot-runtime")
        command = [sys.executable, "-m", "runners.project_worker", str(project)]
        env = runtime.environment()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        worker_root = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = str(worker_root)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        godot = self.godot_path or os.environ.get("GODOT_BIN") or os.environ.get("GODOT_PATH")
        if godot:
            resolved_godot = Path(godot).expanduser().resolve(strict=True)
            if not resolved_godot.is_file() or not os.access(resolved_godot, os.X_OK):
                raise RunnerError("configured Godot executable is not executable")
            env["GODOT_BIN"] = str(resolved_godot)
        # This process is a trusted adapter that feeds frozen inputs into the
        # verifier. The candidate project is executed only in the independently
        # sandboxed Godot subprocesses created by general_verification.
        # A project's source tree is untrusted input. Keep Python's module
        # search root and cwd in the host-owned runner checkout so a project
        # package (for example runners/__init__.py) cannot shadow this worker.
        child = subprocess.Popen(command, cwd=str(worker_root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                 env=env, start_new_session=True)
        process_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        identity = {"threadId": None, "turnId": None, "processId": child.pid,
                    "processGroupId": child.pid, "processStartTime": process_started_at}
        assert child.stdin and child.stdout
        try:
            self.journal.set_identity(attempt, json.dumps(identity, sort_keys=True))
            self.journal.add_report(attempt, "started", store_id, project_id, self.runner_id, {
                "nativeIdentity": identity,
                "startedAt": process_started_at, "requestedProfile": None, "reportedProfile": None,
                "threadStartReported": None, "turnStartAcknowledged": None, "actualProfile": None})
            child.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            child.stdin.close()
        except (RunnerError, OSError):
            stopped = stop_process_group(child.pid, process=child)
            child.stdin.close()
            child.stdout.close()
            if stopped:
                shutil.rmtree(temp_root, ignore_errors=True)
            self.journal.add_report(attempt, "failed", store_id, project_id, self.runner_id,
                {"stopped": stopped, "stopReason": "native_error", "diagnosticRef": "verification-worker-input"})
            return
        output = []
        last_heartbeat = 0.0
        stop_reason = None
        stop_confirmed = None
        deadline = time.monotonic() + max_seconds
        try:
            for line in process_output_lines(child):
                if ((self.stop_event is not None and self.stop_event.is_set())
                        and stop_reason is None):
                    stop_reason = "cancelled"
                    stop_confirmed = stop_process_group(child.pid, process=child)
                    break
                if time.monotonic() >= deadline and stop_reason is None:
                    stop_reason = "time_limit"
                    stop_confirmed = stop_process_group(child.pid, process=child)
                    break
                if line is not None:
                    output.append(line)
                if time.monotonic() - last_heartbeat >= 5:
                    try:
                        state = self.api.request("POST", "/internal/v1/heartbeat", {
                            "runnerId": self.runner_id, "storeId": store_id, "attemptId": attempt,
                            "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
                        if state.get("cancelRequested"):
                            stop_reason = "cancelled"
                            stop_confirmed = stop_process_group(child.pid, process=child)
                            break
                    except RunnerError:
                        pass
                    try:
                        self.journal.flush(self.api)
                    except RunnerError:
                        pass
                    last_heartbeat = time.monotonic()
        except (RunnerError, OSError) as exc:
            stop_reason = "native_error"
            output.append(str(exc))
            stop_confirmed = stop_process_group(child.pid, process=child)
        finally:
            process_group_stopped = stop_process_group(child.pid, process=child, grace_seconds=1.0)
            try:
                return_code = child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return_code = None
                process_group_stopped = False
            child.stdout.close()
            if process_group_stopped:
                shutil.rmtree(temp_root, ignore_errors=True)
        if stop_reason is not None:
            self.journal.add_report(attempt, "stopped", store_id, project_id, self.runner_id,
                {"stopped": bool(stop_confirmed and process_group_stopped), "stopReason": stop_reason,
                 "diagnosticRef": "verification-process-group-termination"})
            self.journal.flush(self.api)
            return
        raw = "".join(output)
        try:
            report = json.loads(raw.splitlines()[-1]) if return_code == 0 else None
        except (ValueError, IndexError):
            report = None
        if not isinstance(report, dict):
            report = {"status": "FAIL", "diagnostics": [{"stage": "runner", "message": raw[-4000:]}], "checks": []}
        stopped = return_code is not None and process_group_stopped
        if not stopped:
            self.journal.add_report(attempt, "stopped", store_id, project_id, self.runner_id,
                {"stopped": False, "stopReason": "unknown",
                 "diagnosticRef": "verification-process-group-termination"})
            self.journal.flush(self.api)
            return
        source_unchanged = (_git(project, "rev-parse", "HEAD") == commit
                            and _git(project, "status", "--porcelain") == "")
        normalized_checks = verification_checks(report)
        report.update({"artifactRef": artifact_ref, "sourceCommit": commit,
                       "sourceUnchanged": source_unchanged, "stopped": stopped,
                       "sandbox": report.get("sandbox", {
                           "status": "APPLIED",
                           "policy": "deny-default for each Godot command; trusted verifier adapter runs unsandboxed",
                           "boundary": "Godot child process trees (version, import, runtime smoke)",
                           "roleAssessment": "NOT_VERIFIED",
                       })})
        evidence_root = self.artifact_root / "verification-evidence"
        evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        evidence_path = evidence_root / f"{attempt}.json"
        temporary_evidence = evidence_root / f".{attempt}.json.tmp"
        with temporary_evidence.open("x", encoding="utf-8") as stream:
            os.chmod(temporary_evidence, 0o600)
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_evidence, evidence_path)
        directory_fd = os.open(evidence_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        self.journal.add_report(attempt, "completed", store_id, project_id, self.runner_id,
            {"artifactRef": artifact_ref, "sourceCommit": commit,
             "result": {"status": report.get("status"), "sourceCommit": commit,
                        "sourceUnchanged": source_unchanged, "checks": normalized_checks,
                        "evidenceRef": f"verification-evidence/{attempt}.json"}, "stopped": stopped})
        # Keep the exact evidence workspace until the backend has durably acked.
        self.journal.flush(self.api)

    def _prepare_preview_images(self, project, commit, godot, runtime, protected,
                                attempt, project_id, store_id, log, log_path):
        """Prepare textures and script class caches in the disposable copy."""
        tracked = _git(project, "ls-tree", "-r", "--name-only", commit).splitlines()
        paths = missing_image_imports(project, tracked) if (project / "assets").exists() else []
        # Fresh clones also need Godot's global script class scan when there
        # are no textures. Keep all generated caches inside this copy's .godot.
        if not paths and not any(path.endswith((".gd", ".cs")) for path in tracked):
            return {}
        version = subprocess.run(sandboxed_godot_argv(godot, ["--version"],
            project_root=project, runtime=runtime, protected_paths=protected),
            cwd=str(project), capture_output=True, text=True, timeout=10,
            env=runtime.environment(), check=False)
        if version.returncode != 0:
            raise PreviewImportError("preview Godot version query failed")
        runtime.configure_editor_tls(version.stdout.strip(), godot)
        argv = sandboxed_godot_argv(godot,
            ["--headless", "--path", str(project), "--editor", "--recovery-mode", "--import", "--quit",
             "--log-file", str(runtime.tmp / "preview-import.log")],
            project_root=project, runtime=runtime, protected_paths=protected,
            image_import_write_paths=tuple(project / path for path in paths))
        child = subprocess.Popen(argv, cwd=str(project), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, text=True,
            env=runtime.environment(), start_new_session=True)
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        reason = None
        last_heartbeat = 0.0
        deadline = time.monotonic() + 60
        try:
            while child.poll() is None:
                now = time.monotonic()
                if self.stop_event is not None and self.stop_event.is_set():
                    reason = "cancelled"
                    break
                if now >= deadline:
                    reason = "time_limit"
                    break
                if now - last_heartbeat >= 5:
                    try:
                        state = self.api.request("POST", "/internal/v1/heartbeat", {
                            "runnerId": self.runner_id, "storeId": store_id, "attemptId": attempt,
                            "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
                        if state.get("cancelRequested"):
                            reason = "cancelled"
                            break
                    except RunnerError:
                        pass
                    last_heartbeat = now
                time.sleep(0.1)
        finally:
            stopped = stop_process_group(child.pid, process=child, grace_seconds=1.0)
        if not stopped:
            # Retain a live import identity for the normal reconciliation path;
            # never claim that no process started when termination is unknown.
            identity = {"threadId": None, "turnId": None, "processId": child.pid,
                        "processGroupId": child.pid, "processStartTime": started_at}
            self.journal.set_identity(attempt, json.dumps(identity, sort_keys=True))
            self.journal.add_report(attempt, "started", store_id, project_id, self.runner_id, {
                "nativeIdentity": identity, "startedAt": started_at, "requestedProfile": None,
                "reportedProfile": None, "threadStartReported": None,
                "turnStartAcknowledged": None, "actualProfile": None})
        if not stopped or reason is not None:
            raise PreviewImportError("preview image import stopped before runtime launch",
                stopped=stopped, stop_reason=reason or "unknown", process_started=True)
        log.flush()
        if child.returncode != 0 or any(marker in log_path.read_text() for marker in ("SCRIPT ERROR:", "ERROR:")):
            raise PreviewImportError("preview image import failed; see private preview evidence", process_started=True)
        imports = read_generated_imports(project, paths)
        # Generated metadata is the only extra source-adjacent write allowed.
        status = _git(project, "status", "--porcelain", "--untracked-files=all", "--", ".",
                      ":!.godot", ":!.runner-tmp", *[":!" + path for path in paths])
        if _git(project, "rev-parse", "HEAD") != commit or status:
            raise PreviewImportError("preview import changed sealed source")
        return imports

    def preview(self, execution: dict, store_id: str, *, max_seconds: int = 900):
        """Run one immutable artifact copy under supervision until stop/expiry."""
        attempt, project_id = execution.get("attemptId"), execution.get("projectId")
        if not isinstance(attempt, str) or not isinstance(project_id, str):
            raise RunnerError("preview request is missing identities")
        if not attempt.replace("-", "").replace("_", "").isalnum():
            raise RunnerError("preview attempt ID is unsafe")
        self.journal.start_intent(attempt, execution)
        evidence = sandbox_probe()
        if not evidence.get("passed"):
            self.journal.add_report(attempt, "failed", store_id, project_id, self.runner_id,
                {"stopped": True, "stopReason": "native_error", "diagnosticRef": "sandbox_unavailable"})
            self.journal.flush(self.api)
            return
        refs = execution.get("inputRefs", {})
        artifact_ref = refs.get("artifactRef") if isinstance(refs, dict) else None
        root = self.artifact_root / "previews"
        workspace = root / attempt
        if workspace.exists():
            raise RunnerError("preview attempt already has an isolated copy")
        project, commit = self.materialize(artifact_ref, workspace)
        cache = project / ".godot"
        if cache.is_symlink():
            raise RunnerError("preview cache cannot be a symlink")
        cache.mkdir(mode=0o700, exist_ok=True)
        temp_root = project / ".runner-tmp"
        temp_root.mkdir(mode=0o700, exist_ok=False)
        runtime = GodotRuntime.create(temp_root / "godot-runtime")
        protected = protected_siblings(self.protected_root, active=project)
        protected += protected_siblings(self.artifact_root, active=project)
        protected += [Path(self.journal.path)]
        godot = self.godot_path or os.environ.get("GODOT_BIN") or os.environ.get("GODOT_PATH")
        if not godot:
            raise RunnerError("preview requires an explicitly configured Godot executable")
        godot_path = Path(godot).expanduser().resolve(strict=True)
        env = runtime.environment()
        env["GODOT_BIN"] = str(godot_path)
        evidence_root = self.artifact_root / "preview-evidence"
        evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_path = evidence_root / f"{attempt}.log"
        generated_imports = {}
        def clean_imports():
            for name, data in generated_imports.items():
                path = project / name
                if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                    raise RunnerError("disposable preview image import metadata changed")
                path.unlink()
        with log_path.open("x", encoding="utf-8") as log:
            os.chmod(log_path, 0o600)
            try:
                generated_imports = self._prepare_preview_images(project, commit, godot_path,
                    runtime, protected, attempt, project_id, store_id, log, log_path)
                godot_command = sandboxed_godot_argv(
                    godot_path,
                    ["--path", str(project), "--log-file", str(runtime.tmp / "godot.log")],
                    project_root=project,
                    runtime=runtime,
                    protected_paths=protected,
                    allow_graphics=True,
                )
            except (GodotRuntimeError, RunnerError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
                stopped = getattr(exc, "stopped", True)
                diagnostic = {
                    "schemaVersion": "studio.preview.failure.v1",
                    "phase": "preview_image_import" if isinstance(exc, PreviewImportError) else "trusted_ca_runtime_preparation",
                    "processStarted": getattr(exc, "process_started", False),
                    "runtimeProcessStarted": False,
                    "stopped": stopped,
                    "errorType": type(exc).__name__,
                    "message": str(exc)[:1600],
                }
                log.write("STUDIO_PREVIEW_FAILURE=" + json.dumps(
                    diagnostic, ensure_ascii=False, sort_keys=True
                ) + "\n")
                log.flush()
                os.fsync(log.fileno())
                # Preparation failures never launch the graphical runtime.
                # Preserve private state when import termination is uncertain.
                if stopped:
                    clean_imports()
                    shutil.rmtree(temp_root, ignore_errors=True)
                self.journal.add_report(attempt, "failed", store_id, project_id, self.runner_id,
                    {"stopped": stopped, "stopReason": getattr(exc, "stop_reason", "native_error"),
                     "diagnosticRef": f"preview-evidence/{attempt}.log"})
                self.journal.flush(self.api)
                return
            child = subprocess.Popen(godot_command,
                                     cwd=str(project.resolve()), stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, text=True, env=env,
                                     start_new_session=True)
            started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            identity = {"threadId": None, "turnId": None, "processId": child.pid,
                        "processGroupId": child.pid, "processStartTime": started_at}
            self.journal.set_identity(attempt, json.dumps(identity, sort_keys=True))
            self.journal.add_report(attempt, "started", store_id, project_id, self.runner_id, {
                "nativeIdentity": identity, "startedAt": started_at, "requestedProfile": None,
                "reportedProfile": None, "threadStartReported": None,
                "turnStartAcknowledged": None, "actualProfile": None})
            self.journal.add_report(attempt, "activity", store_id, project_id, self.runner_id, {
                "activityKind": "preview_started", "observedAt": started_at,
                "summary": "Godot preview process started in an isolated artifact copy."})
            try:
                self.journal.flush(self.api)
            except RunnerError:
                # Delivery is independent from the local watchdog. Keep the
                # durable report and supervise through a backend outage.
                pass
            stop_reason = None
            last_heartbeat = 0.0
            deadline = time.monotonic() + max_seconds
            while child.poll() is None:
                now = time.monotonic()
                if self.stop_event is not None and self.stop_event.is_set():
                    stop_reason = "cancelled"
                    break
                if now >= deadline:
                    stop_reason = "time_limit"
                    break
                if now - last_heartbeat >= 5:
                    try:
                        state = self.api.request("POST", "/internal/v1/heartbeat", {
                            "runnerId": self.runner_id, "storeId": store_id,
                            "attemptId": attempt,
                            "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
                        if state.get("cancelRequested"):
                            stop_reason = "cancelled"
                            break
                    except RunnerError:
                        pass
                    try:
                        self.journal.flush(self.api)
                    except RunnerError:
                        pass
                    last_heartbeat = time.monotonic()
                time.sleep(0.25)
            if stop_reason is not None:
                stopped = stop_process_group(child.pid, process=child)
                if stopped:
                    clean_imports()
                    shutil.rmtree(temp_root, ignore_errors=True)
                self.journal.add_report(attempt, "stopped", store_id, project_id, self.runner_id,
                    {"stopped": stopped, "stopReason": stop_reason,
                     "diagnosticRef": f"preview-evidence/{attempt}.log"})
                self.journal.flush(self.api)
                if not stopped:
                    raise RunnerError("preview process group termination could not be confirmed")
                return
            return_code = child.wait()
            stopped = stop_process_group(child.pid, process=child, grace_seconds=1.0)
            if stopped:
                clean_imports()
                shutil.rmtree(temp_root, ignore_errors=True)
            if not stopped:
                self.journal.add_report(attempt, "stopped", store_id, project_id, self.runner_id,
                    {"stopped": False, "stopReason": "unknown",
                     "diagnosticRef": f"preview-evidence/{attempt}.log"})
                self.journal.flush(self.api)
                raise RunnerError("preview process group remains alive after exit")
            if not _source_unchanged(project, commit):
                self.journal.add_report(attempt, "failed", store_id, project_id, self.runner_id,
                    {"stopped": True, "stopReason": "native_error",
                     "diagnosticRef": f"preview-evidence/{attempt}.log"})
            else:
                self.journal.add_report(attempt, "completed", store_id, project_id, self.runner_id, {
                    "artifactRef": artifact_ref, "sourceCommit": commit, "stopped": True,
                    "result": {"status": "STOPPED" if return_code == 0 else "FAIL",
                               "sourceCommit": commit, "sourceUnchanged": True,
                               "checks": [], "evidenceRef": f"preview-evidence/{attempt}.log"}})
            self.journal.flush(self.api)

    def claim(self, store_id: str):
        if not self.journal.can_claim():
            return {"request": None, "pausedForOutbox": True}
        command_id = self.journal.claim_command(store_id)
        result = self.api.request("POST", "/internal/v1/claim", {
            "runnerId": self.runner_id, "commandId": command_id,
            "storeId": store_id,
        })
        execution = result.get("request")
        if isinstance(execution, dict):
            self.journal.record_claim(execution)
        self.journal.claim_recorded(store_id)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Standalone Studio ProjectRunner")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--runner-token-file", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--protected-root", required=True)
    parser.add_argument("--godot", default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    import threading
    stop_event = threading.Event()
    previous_handlers = {}
    def request_stop(signum, _frame):
        stop_event.set()
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    with RunnerLock(Path(args.state).resolve().parent / "service.lock"):
        journal = LocalJournal(args.state)
        api = RunnerHTTP(args.url, args.runner_token_file, journal.runner_id)
        runner = ProjectRunner(api, journal, Path(args.artifact_root), Path(args.protected_root), args.godot,
                              stop_event=stop_event)
        handshake = retry_transport(lambda: api.request("GET", "/internal/v1/handshake"), stop_event)
        if handshake is None:
            return
        store_id = handshake.get("storeId")
        if not isinstance(store_id, str):
            raise RunnerError("handshake did not provide storeId")
        journal.bind_store(store_id)
        retry_transport(runner.register, stop_event)
        def iteration():
            journal.flush(api)
            api.request("POST", "/internal/v1/heartbeat", {
                "runnerId": runner.runner_id, "storeId": store_id,
                "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
            execution = runner.claim(store_id).get("request")
            if execution:
                if execution.get("taskKind") == "verify":
                    runner.verify(execution, store_id)
                elif execution.get("taskKind") == "preview":
                    runner.preview(execution, store_id)
                else:
                    raise RunnerError("ProjectRunner received an unsupported execution taskKind")
        service_loop(iteration, stop_event, once=args.once)
    for signum, handler in previous_handlers.items():
        signal.signal(signum, handler)


if __name__ == "__main__":
    main()

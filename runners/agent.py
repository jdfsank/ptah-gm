"""AgentRunner control plane and conservative execution boundary."""
from __future__ import annotations

import argparse
import base64
import errno
import json
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import (LocalJournal, RunnerError, RunnerHTTP,
                    RunnerLock, materialize_service_records, sandbox_probe,
                    strict_sandbox_rules, stop_process_group, retry_transport,
                    service_loop, process_output_lines, MAX_REFERENCE_ASSETS,
                    MAX_REFERENCE_ASSET_BYTES)
from .editor_mcp import EditorMCPError, ensure_editor_mcp_ready


def _read_material(api: RunnerHTTP, attempt_id: str) -> dict:
    material = api.request("GET", f"/internal/v1/attempts/{attempt_id}/input")
    allowed = {"schemaVersion", "attemptId", "packet", "assets", "artifactRef",
               "prepared", "document", "storeId", "projectId", "scope"}
    if set(material) - allowed:
        raise RunnerError("input material contains unsupported fields")
    if material.get("attemptId") != attempt_id:
        raise RunnerError("input material belongs to a different attempt")
    return material


def _native_total_tokens(value) -> int | None:
    if not isinstance(value, dict):
        return None
    total = value.get("totalTokens", value.get("total_tokens"))
    return total if type(total) is int and total >= 0 else None


def _soft_budget_reached(total: int | None, limit) -> bool:
    return type(total) is int and isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 and total >= limit


class AgentRunner:
    def __init__(self, api: RunnerHTTP, journal: LocalJournal, workspace_root: Path,
                 artifact_root: Path, protected_root: Path, require_sandbox: bool = True,
                 stop_event=None):
        self.api, self.journal = api, journal
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifact_root = artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.protected_root = protected_root.resolve()
        self.require_sandbox = require_sandbox
        self.runner_id = journal.runner_id
        self.stop_event = stop_event

    def register(self):
        from .role_probe import run_agent_role_probe
        probe = run_agent_role_probe(self.runner_id, self.workspace_root)
        evidence = probe["evidence"]
        catalog = probe["catalog"]
        self._update_catalog(catalog)
        return self.api.request("POST", "/internal/v1/register", {
            "runnerId": self.runner_id, "runnerKind": "agent",
            "environment": {"os": platform.platform(), "python": platform.python_version()},
            "nativeVersion": catalog.get("nativeVersion"),
            "capabilities": evidence.get("verifiedCapabilities", []),
            "sandboxEvidence": evidence,
        })

    def _update_catalog(self, catalog):
        native_models = catalog.get("models", catalog.get("data"))
        if not isinstance(native_models, list):
            raise RunnerError("native model catalog is invalid")
        models = []
        for row in native_models:
            if not isinstance(row, dict):
                continue
            model = row.get("modelKey", row.get("model", row.get("id")))
            provider = row.get("modelProvider", row.get("provider", row.get("providerKey")))
            efforts = row.get("supportedReasoningEfforts", row.get("reasoningEfforts"))
            modalities = row.get("inputModalities", row.get("input_modalities", []))
            if isinstance(model, str) and isinstance(efforts, list) and isinstance(modalities, list):
                models.append({"modelKey": model, "modelProvider": provider if isinstance(provider, str) else None,
                               "supportedReasoningEfforts": efforts, "inputModalities": modalities,
                               "defaultReasoningEffort": row.get("defaultReasoningEffort"),
                               "isDefault": row.get("isDefault") is True})
        # The native API does not consistently expose a stable revision. Keep a
        # local monotonic revision, advancing only when its observable catalog changes.
        content = json.dumps({"models": models, "nativeVersion": catalog.get("nativeVersion"),
                              "environment": catalog.get("environment")},
                             sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.journal._connect() as db:
            old = db.execute("SELECT value FROM metadata WHERE key='catalogContent'").fetchone()
            rev = db.execute("SELECT value FROM metadata WHERE key='catalogRevision'").fetchone()
            catalog_revision = int(rev[0]) if rev else 0
            if old is None or old[0] != content:
                catalog_revision += 1
                db.execute("INSERT OR REPLACE INTO metadata VALUES('catalogContent',?)", (content,))
                db.execute("INSERT OR REPLACE INTO metadata VALUES('catalogRevision',?)", (str(catalog_revision),))
        self.catalog_revision = catalog_revision
        self.models = models

    def refresh_catalog(self):
        """Refresh model choices from native model/list; this starts no turn."""
        from backend.codex_driver import CodexDriverError
        try:
            from .role_probe import managed_model_catalog
            catalog = managed_model_catalog(self.workspace_root, cancel_event=self.stop_event)
        except CodexDriverError as exc:
            raise RunnerError(f"native catalog refresh failed: {exc}") from exc
        self._update_catalog(catalog)
        return self.publish_catalog()

    def publish_catalog(self):
        # The codex_driver owner can supply live model/list observations through
        # this explicit method; an empty catalog prevents unsafe dispatch.
        return self.api.request("POST", "/internal/v1/catalog", {
            "runnerId": self.runner_id, "catalogRevision": self.catalog_revision,
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": self.models,
        })

    def catalog_refresh_loop(self, stop_event, interval=60):
        """Observe native model/list even while the service loop owns a long turn."""
        while not stop_event.wait(interval):
            try:
                self.refresh_catalog()
            except RunnerError:
                # Keep the last real observation; a heartbeat cannot renew it.
                continue

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

    def accept_claim(self, request: dict, store_id: str):
        attempt = request.get("attemptId")
        project = request.get("projectId")
        if not isinstance(attempt, str) or not isinstance(project, str):
            raise RunnerError("claimed execution is missing its backend identities")
        if not attempt.replace("-", "").replace("_", "").isalnum():
            raise RunnerError("agent attempt ID is unsafe")
        self.journal.start_intent(attempt, request)
        try:
            evidence = sandbox_probe()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self._report_setup_failure(request, store_id, exc)
            return False
        if self.require_sandbox and not evidence.get("passed"):
            diagnostic_ref = "local:sandbox-probe/" + attempt
            with self.journal._connect() as db:
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                           (diagnostic_ref, json.dumps(evidence, ensure_ascii=False, allow_nan=False)))
            self._report(request, store_id, "failed", {"stopped": True,
                "stopReason": "native_error", "launchPrevented": True,
                "diagnosticRef": diagnostic_ref})
            try:
                self.journal.flush(self.api)
            except RunnerError:
                pass
            return False
        prior = self._attempt_identity(attempt)
        if prior:
            raise RunnerError("attempt already has a native identity; reconcile it instead of starting again")
        if (self.workspace_root / attempt).exists():
            raise RunnerError("attempt workspace already exists without a reconciled completion")
        try:
            (material, workspace, worker_request, temp_root,
             argv, python_path, env) = self._prepare_claim(request)
            if request["taskKind"] == "produce":
                self._ensure_production_mcp(request, store_id, workspace, material)
            process = subprocess.Popen(
                argv,
                cwd=python_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                env=env, start_new_session=True,
            )
        except (RunnerError, OSError, ValueError, subprocess.SubprocessError) as exc:
            self._report_setup_failure(request, store_id, exc)
            return False
        kind = request["taskKind"]
        native_identity = None
        native_process_group_id = None
        native_process_group_observed = False
        thread_observation = None
        turn_observation = None
        final_result = None
        provider_diagnostics = None
        worker_setup_failure = None
        last_heartbeat = 0.0
        profile = request.get("profileSnapshot") or {}
        limits = profile.get("limits") or {}
        max_duration = limits.get("maxDurationSeconds", 420)
        soft_budget = limits.get("softTotalTokens")
        started_monotonic = time.monotonic()
        stop_reason = None
        stop_sent_at = None
        group_cleanup_confirmed = None
        output_error = None
        return_code = None
        diagnostic_ref = None

        def begin_stop(reason):
            nonlocal stop_reason, stop_sent_at
            if stop_reason is not None:
                return
            stop_reason = reason
            stop_sent_at = time.monotonic()
            for pgid in (process.pid, native_process_group_id):
                if pgid is None:
                    continue
                try:
                    self._signal_process_group(pgid, signal.SIGTERM)
                except OSError:
                    # A concurrent exit or an inspection/signal race must not
                    # skip the bounded escalation and cleanup path.
                    pass

        try:
            # Keep the local worker lease out of attempts.native_identity: that
            # column is reserved for the immutable native app-server identity.
            self._journal_worker_identity(attempt, process)
            assert process.stdin and process.stdout
            process.stdin.write(json.dumps(worker_request, ensure_ascii=False, separators=(",", ":"),
                                           allow_nan=False))
            process.stdin.close()
            output = iter(process_output_lines(process))
            reader_done = False
            escalation_attempted = False
            while True:
                line = None
                if not reader_done:
                    try:
                        line = next(output)
                    except StopIteration:
                        reader_done = True

                groups_alive = (self._process_group_exists(process.pid)
                                or (native_process_group_id is not None
                                    and self._process_group_exists(native_process_group_id)))
                if (self.stop_event is not None and self.stop_event.is_set()
                        and groups_alive):
                    begin_stop("cancelled")

                if (line is None and not reader_done and process.poll() is not None
                        and not groups_alive):
                    # No tracked group remains and select found no bytes. An
                    # escaped descendant may still hold the inherited pipe;
                    # stop waiting for it instead of letting it pin the claim.
                    reader_done = True
                    break

                if line is not None:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        event = {}
                    if not isinstance(event, dict):
                        event = {}
                    if event.get("event") == "started":
                        native_identity = event.get("nativeIdentity")
                        if not isinstance(native_identity, dict):
                            raise RunnerError("native worker start identity is invalid")
                        (native_process_group_id,
                         native_process_group_observed) = self._trusted_native_process_group(
                            native_identity, process.pid)
                        self.journal.set_identity(attempt, json.dumps(native_identity, sort_keys=True))
                        self._report_started(request, store_id, native_identity,
                                             thread_observation, turn_observation)
                    elif event.get("event") == "nativeObservation":
                        observation = event.get("observation") or {}
                        phase = observation.get("phase")
                        if phase == "threadStartReported":
                            thread_observation = observation
                        elif phase == "turnStartAcknowledged":
                            turn_observation = observation
                        else:
                            continue
                        native_identity = dict(native_identity or {})
                        native_identity["threadId"] = observation.get("threadId")
                        if observation.get("turnId") is not None:
                            native_identity["turnId"] = observation.get("turnId")
                        self.journal.set_identity(attempt, json.dumps(native_identity, sort_keys=True))
                        self._report_started(request, store_id, native_identity,
                                             thread_observation, turn_observation)
                    elif event.get("event") == "activity":
                        activity = event.get("activity") or {}
                        self._report(request, store_id, "activity", {"activityKind": activity.get("method", "native_activity"),
                            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "summary": "已观察到原生执行活动；未提供具体阶段。"})
                    elif event.get("event") == "usage":
                        usage = event.get("usage") or {}
                        total = _native_total_tokens(usage)
                        self._report(request, store_id, "usage", {"totalTokens": total,
                            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "coverage": "native_thread" if isinstance(total, int) else "unknown"})
                        if _soft_budget_reached(total, soft_budget) and groups_alive:
                            begin_stop("soft_budget")
                    elif event.get("event") == "diagnostic":
                        provider_diagnostics = event.get("providerBridge")
                    elif event.get("event") == "setupFailed":
                        worker_setup_failure = str(event.get("errorType", "RunnerError"))[:100]
                    elif event.get("event") == "result":
                        final_result = event
                        result = event.get("result")
                        if (stop_reason is None and isinstance(result, dict)
                                and result.get("status") == "timeout"):
                            # The native supervisor has already finished and
                            # stopped its group. Preserve the time-limit cause
                            # without signalling the adapter during teardown.
                            stop_reason = "time_limit"

                groups_alive = (self._process_group_exists(process.pid)
                                or (native_process_group_id is not None
                                    and self._process_group_exists(native_process_group_id)))
                now = time.monotonic()
                if now - last_heartbeat >= 5:
                    try:
                        response = self.api.request("POST", "/internal/v1/heartbeat", {
                            "runnerId": self.runner_id, "storeId": store_id,
                            "attemptId": attempt, "nativeIdentity": native_identity,
                            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                        if response.get("cancelRequested") and groups_alive:
                            begin_stop("cancelled")
                    except RunnerError:
                        pass
                    try:
                        self.journal.flush(self.api)
                    except RunnerError:
                        pass
                    last_heartbeat = time.monotonic()

                now = time.monotonic()
                groups_alive = (self._process_group_exists(process.pid)
                                or (native_process_group_id is not None
                                    and self._process_group_exists(native_process_group_id)))
                if (isinstance(max_duration, (int, float)) and max_duration > 0
                        and now - started_monotonic >= max_duration and groups_alive
                        and final_result is None):
                    begin_stop("time_limit")

                if stop_reason and groups_alive and stop_sent_at is not None \
                        and now - stop_sent_at >= 8 and not escalation_attempted:
                    escalation_attempted = True
                    # Escalation covers both independently-created sessions;
                    # the helper confirms each group and bounds leader waiting.
                    group_cleanup_confirmed = self._stop_agent_process_groups(
                        process, native_process_group_id, grace_seconds=1.0)
                    break

                if reader_done:
                    if process.poll() is not None and not groups_alive:
                        break
                    time.sleep(0.1)
        except RunnerError as exc:
            output_error = exc
            try:
                group_cleanup_confirmed = self._stop_agent_process_groups(
                    process, native_process_group_id, grace_seconds=1.0)
            except OSError:
                group_cleanup_confirmed = False
        except BaseException:
            try:
                self._stop_agent_process_groups(process, native_process_group_id,
                                                grace_seconds=1.0)
            except OSError:
                pass
            raise
        finally:
            try:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                if process.stdout:
                    process.stdout.close()
            except (OSError, ValueError):
                pass
            if process.poll() is None:
                return_code = self._bounded_wait(process, 1.0)
            else:
                return_code = process.poll()
            native_result = final_result.get("result") if isinstance(final_result, dict) else None
            diagnostics = native_result.get("diagnostics") if isinstance(native_result, dict) else None
            native_stop_confirmed = (isinstance(diagnostics, dict)
                                     and diagnostics.get("childTerminationConfirmed") is True)
            cleanup_confirmed = (
                group_cleanup_confirmed is True and native_process_group_observed
            ) or (output_error is None and return_code == 0 and native_stop_confirmed)
            # Commit bounded metadata before removing the native runtime. A
            # journal failure must preserve the runtime for operator recovery.
            diagnostic_ref = self._persist_native_diagnostics(
                attempt, native_result, return_code, stop_reason, output_error, provider_diagnostics)
            from .native_diagnostics import public_native_failure
            with self.journal._connect() as db:
                summary = json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (diagnostic_ref,)).fetchone()[0])
            native_failure = public_native_failure(summary)
            if cleanup_confirmed:
                import shutil
                shutil.rmtree(temp_root, ignore_errors=True)

        if (worker_setup_failure is not None and output_error is None and return_code == 0
                and native_identity is None and final_result is None
                and not self._process_group_exists(process.pid)):
            self._report_setup_failure(request, store_id,
                RunnerError("native adapter setup failed before app-server launch: " + worker_setup_failure))
            return False
        if output_error is not None:
            # A parser/read-limit failure is never sealable. Record both the
            # execution failure and the separately confirmed stop outcome.
            stopped = bool(group_cleanup_confirmed and native_process_group_observed)
            diagnostic = ("worker-output-limit" if "output exceeded" in str(output_error)
                          else "worker-output-error")
            payload = {"stopped": stopped, "stopReason": "native_error",
                       "diagnosticRef": diagnostic_ref or diagnostic, "nativeFailure": native_failure}
            self._report(request, store_id, "failed", payload)
            self._report(request, store_id, "stopped", payload)
            try:
                self.journal.flush(self.api)
            except RunnerError:
                pass
            return False

        if stop_reason and escalation_attempted:
            stopped = bool(group_cleanup_confirmed and native_process_group_observed)
            self._report(request, store_id, "stopped", {"stopped": stopped,
                "stopReason": stop_reason, "diagnosticRef": diagnostic_ref or "runner-limit-or-cancel"})
            return False
        if not final_result or return_code != 0:
            self._report(request, store_id, "failed", {"stopped": False,
                "stopReason": "native_error", "diagnosticRef": diagnostic_ref or "native-worker-failure", "nativeFailure": native_failure})
            return False
        result_identity = final_result.get("nativeIdentity") if isinstance(final_result, dict) else None
        if isinstance(result_identity, dict) and isinstance(native_identity, dict):
            enriched = dict(native_identity)
            for key in ("threadId", "turnId"):
                if result_identity.get(key) is not None:
                    enriched[key] = result_identity[key]
            self.journal.set_identity(attempt, json.dumps(enriched, sort_keys=True))
            native_identity = enriched
        result = final_result.get("result")
        stopped = isinstance(result, dict) and (result.get("diagnostics") or {}).get("childTerminationConfirmed") is True
        if not stopped:
            self._report(request, store_id, "stopped", {"stopped": False, "stopReason": "unknown",
                "diagnosticRef": diagnostic_ref or "termination-unconfirmed"})
            return False
        if stop_reason:
            self._report(request, store_id, "stopped", {"stopped": True, "stopReason": stop_reason,
                "diagnosticRef": diagnostic_ref or "runner-limit-or-cancel"})
            return False
        if result.get("status") != "completed":
            self._report(request, store_id, "failed", {"stopped": True,
                "stopReason": "native_error", "diagnosticRef": diagnostic_ref or "native-terminal-not-completed", "nativeFailure": native_failure})
            try:
                self.journal.flush(self.api)
            except RunnerError:
                pass
            return False
        if kind in {"plan", "visual-plan"}:
            # Preserve the model's text until the backend's strict parser sees
            # it; json.loads here would silently discard duplicate JSON keys.
            report_payload = {"result": {"response": result.get("response")}, "stopped": True}
        else:
            from backend.general_verification import GeneralVerificationError
            try:
                source_ref = self._seal(request, material, workspace)
            except (RunnerError, GeneralVerificationError, OSError, ValueError,
                    subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                diagnostic_ref = "local:seal-diagnostics/" + attempt
                with self.journal._connect() as db:
                    db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                               (diagnostic_ref, json.dumps({"errorType": type(exc).__name__,
                                                           "message": str(exc)[:4000]})))
                self._report(request, store_id, "failed", {"stopped": True,
                    "stopReason": "native_error", "diagnosticRef": diagnostic_ref})
                try:
                    self.journal.flush(self.api)
                except RunnerError:
                    pass
                return False
            report_payload = {"artifactRef": source_ref, "sourceCommit": source_ref["sourceCommit"],
                              "stopped": True,
                              "result": {"status": result.get("status"), "sourceCommit": source_ref["sourceCommit"],
                                         "sourceUnchanged": False, "checks": []}}
        self._report(request, store_id, "completed", report_payload)
        try:
            self.journal.flush(self.api)
        except RunnerError:
            pass
        return True

    def _persist_native_diagnostics(self, attempt, result, exit_code, stop_reason, output_error,
                                    provider_diagnostics=None):
        from .native_diagnostics import native_diagnostic_summary
        ref = "local:native-diagnostics/" + attempt
        if isinstance(provider_diagnostics, dict):
            result = dict(result) if isinstance(result, dict) else {}
            diagnostics = result.get("diagnostics")
            result["diagnostics"] = {**(diagnostics if isinstance(diagnostics, dict) else {}),
                                     "providerBridge": provider_diagnostics}
        output_failure = ("output_limit" if "output exceeded" in str(output_error) else "read_error") if output_error is not None else None
        summary = native_diagnostic_summary(result, worker_exit_code=exit_code,
                                            stop_reason=stop_reason, output_error=output_failure)
        with self.journal._connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                       (ref, json.dumps(summary, ensure_ascii=False, allow_nan=False)))
        return ref

    def _prepare_claim(self, request):
        """Prepare bounded input and files before creating any child process."""
        attempt = request["attemptId"]
        material = _read_material(self.api, attempt)
        kind = request.get("taskKind")
        if kind not in {"plan", "visual-plan", "produce"}:
            raise RunnerError("AgentRunner cannot execute this task kind")
        workspace = self.workspace_root / attempt
        if workspace.exists():
            raise RunnerError("attempt workspace already exists without a reconciled completion")
        if kind == "produce":
            prepared = material.get("prepared")
            ref = prepared.get("inputArtifactRef") if isinstance(prepared, dict) else None
            if not isinstance(ref, dict):
                raise RunnerError("producer input has no trusted inputArtifactRef")
            from .project import ProjectRunner
            source_runner = ProjectRunner(self.api, self.journal, self.artifact_root, self.protected_root)
            source_runner.materialize(ref, workspace)
            prepared = material.get("prepared") or {}
            materialize_service_records(workspace, prepared.get("serviceRecords"))
        else:
            workspace.mkdir(mode=0o700, parents=True)
            request_data = material.get("packet")
            if not isinstance(request_data, dict):
                raise RunnerError("planner input is missing its bounded planning packet")
            (workspace / "planning-input.json").write_text(
                json.dumps(request_data, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
        references = []
        asset_root = workspace / ".runner-assets"
        assets = material.get("assets", [])
        if not isinstance(assets, list) or len(assets) > MAX_REFERENCE_ASSETS:
            raise RunnerError("reference assets are invalid or exceed the limit")
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict) or set(asset) != {"name", "mimeType", "dataBase64"}:
                raise RunnerError("reference asset has an invalid shape")
            name = Path(asset["name"]).name
            if not name or name != asset["name"]:
                raise RunnerError("reference asset name is unsafe")
            suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(asset["mimeType"])
            if suffix is None:
                raise RunnerError("unsupported reference asset media type")
            asset_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = asset_root / f"{index:02d}-{name}"
            if kind == "produce":
                target = workspace / ".git" / "studio-reference-assets" / target.name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = base64.b64decode(asset["dataBase64"], validate=True)
            if not data or len(data) > MAX_REFERENCE_ASSET_BYTES:
                raise RunnerError("reference asset exceeds the local size limit")
            target.write_bytes(data)
            target.chmod(0o600)
            references.append(str(target))
        packet = material.get("packet")
        if not isinstance(packet, dict):
            raise RunnerError("execution has no typed packet")
        worker_request = {"execution": request, "material": {**material, "packet": packet,
                                                                "referenceImages": references}}
        temp_root = workspace / ".runner-tmp"
        temp_root.mkdir(mode=0o700, exist_ok=False)
        if kind == "produce":
            allowed = packet.get("allowedFiles", [])
            if not isinstance(allowed, list) or len(allowed) > 128:
                raise RunnerError("producer write scope is invalid")
            approved_roots = set()
            for value in allowed:
                if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts or "\\" in value:
                    raise RunnerError("producer write scope contains an unsafe path")
                if value == "project.godot":
                    project_file = workspace / value
                    if project_file.is_symlink() or not project_file.is_file():
                        raise RunnerError("project.godot write root must be a regular non-symlink file")
                elif value.split("/", 1)[0] in {"scripts", "scenes", "resources", "assets"}:
                    approved_roots.add(value.split("/", 1)[0])
            for name in sorted(approved_roots):
                root = workspace / name
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                if root.is_symlink():
                    raise RunnerError("approved write root cannot be a symlink")
        env = {k: v for k, v in os.environ.items()
               if k in {"PATH", "HOME", "LANG", "LC_ALL", "GODOT_BIN", "GODOT_PATH"}}
        from .native_adapter import ManagedNativeContext
        provider = (request.get("profileSnapshot") or {}).get("modelProvider")
        if provider:
            env.update(ManagedNativeContext.authentication_environment(provider))
        env["TMPDIR"] = str(temp_root)
        host_root = Path(__file__).resolve().parents[1]
        python_path = str(host_root)
        env["PYTHONPATH"] = python_path
        env["PYTHONNOUSERSITE"] = "1"
        argv = [str(Path(sys.executable).resolve()), "-m", "runners.agent_worker", str(workspace)]
        # The pinned adapter is trusted and owns authentication. Each native
        # runtime and typed file operation applies its own initial sandbox;
        # sharing an auth-readable parent policy would merge these roles.
        return material, workspace, worker_request, temp_root, argv, python_path, env

    def _ensure_production_mcp(self, request, store_id, workspace, material):
        """The trusted editor exits before any production model is started."""
        attempt = request["attemptId"]
        evidence = self.journal.path.resolve().parent / "editor-mcp" / attempt
        with self.journal._connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                (f"editorMCPReadiness:{attempt}", json.dumps({"reportPath": str(evidence / "readiness.json")})))
        self._report(request, store_id, "activity", {"activityKind": "godot_mcp_preparing",
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": "正在准备 Godot 工程并确认编辑器 MCP 就绪。"})
        last_heartbeat = 0.0
        cancelled = False

        def tick(force=False):
            nonlocal last_heartbeat, cancelled
            if force or time.monotonic() - last_heartbeat >= 5:
                try:
                    response = self.api.request("POST", "/internal/v1/heartbeat", {
                        "runnerId": self.runner_id, "storeId": store_id, "attemptId": attempt,
                        "nativeIdentity": None,
                        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                    cancelled = cancelled or bool(response.get("cancelRequested") or response.get("reconcileRequired"))
                    self.journal.flush(self.api)
                except RunnerError:
                    if force:
                        raise
                last_heartbeat = time.monotonic()
            return cancelled

        report = ensure_editor_mcp_ready(workspace, evidence, cancel_event=self.stop_event, tick=tick,
            context={"attemptId": attempt, "projectId": request["projectId"],
                     "inputArtifactRef": (material.get("prepared") or {}).get("inputArtifactRef")})
        if tick(force=True) or (self.stop_event is not None and self.stop_event.is_set()):
            raise EditorMCPError("Production was cancelled after Godot MCP readiness",
                                 report={**report, "cancelled": True})
        self._report(request, store_id, "activity", {"activityKind": "godot_mcp_ready",
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": f"Godot MCP 已确认工程身份并就绪（{report['toolCount']} 个工具），正在启动制作。"})

    def _report_setup_failure(self, request, store_id, error):
        """Retain editor cleanup uncertainty even when the model never started."""
        diagnostic_ref = "local:setup-diagnostics/" + request["attemptId"]
        host_log = self.workspace_root / request["attemptId"] / '.runner-tmp/native-code-host/host.log'
        host_detail = None
        try:
            if not host_log.is_symlink() and host_log.resolve().is_relative_to(self.workspace_root / request["attemptId"]):
                with host_log.open('rb') as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - 4000))
                    host_detail = stream.read(4000).decode('utf-8', errors='replace')
        except OSError:
            pass
        with self.journal._connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                       (diagnostic_ref, json.dumps({"errorType": type(error).__name__,
                                                  "message": str(error)[:4000],
                                                  "toolHostLog": host_detail,
                                                  "editorMCP": getattr(error, "report", None)})))
        stopped = error.stopped if isinstance(error, EditorMCPError) else True
        cancelled = isinstance(error, EditorMCPError) and error.cancelled
        if stopped:
            # Native launch was prevented; any worker has already been reaped.
            # Discard only this attempt's generated copy. Retained artifacts
            # and diagnostics live outside it; uncertain editor stops retain it.
            import shutil
            workspace = self.workspace_root / request["attemptId"]
            cleanup = {"workspaceCleanupConfirmed": False}
            try:
                if not workspace.is_symlink():
                    if workspace.exists():
                        shutil.rmtree(workspace)
                    cleanup["workspaceCleanupConfirmed"] = True
            except OSError as exc:
                cleanup["workspaceCleanupError"] = type(exc).__name__
            with self.journal._connect() as db:
                row = db.execute("SELECT value FROM metadata WHERE key=?", (diagnostic_ref,)).fetchone()
                db.execute("UPDATE metadata SET value=? WHERE key=?",
                    (json.dumps({**json.loads(row[0]), **cleanup}), diagnostic_ref))
        if isinstance(error, EditorMCPError):
            self._report(request, store_id, "activity", {"activityKind": "godot_mcp_blocked",
                "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "summary": "Godot 工程准备未通过，制作尚未启动：" + str(error)[:300]})
        payload = {"stopped": stopped, "stopReason": "cancelled" if cancelled else "native_error",
                   "diagnosticRef": diagnostic_ref}
        if stopped and not cancelled:
            payload["launchPrevented"] = True
        self._report(request, store_id, "stopped" if cancelled else "failed", payload)
        try:
            self.journal.flush(self.api)
        except RunnerError:
            pass

    def _attempt_identity(self, attempt_id):
        import sqlite3
        with self.journal._connect() as db:
            row = db.execute("SELECT native_identity FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            return row[0] if row else None

    def _journal_worker_identity(self, attempt_id: str, process) -> None:
        """Keep an accounting observation; it never authorizes resume or kill."""
        identity = {"processId": process.pid, "processGroupId": process.pid,
                    "processStartTime": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds").replace("+00:00", "Z")}
        key = f"agentWorkerIdentity:{attempt_id}"
        with self.journal._connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                       (key, json.dumps(identity, sort_keys=True, separators=(",", ":"))))

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            # Permission and other inspection failures are not proof of exit.
            return True

    @staticmethod
    def _signal_process_group(pgid: int, signum: int) -> bool:
        try:
            os.killpg(pgid, signum)
            return True
        except ProcessLookupError:
            return False

    @staticmethod
    def _trusted_native_process_group(identity, outer_pgid: int) -> tuple[int | None, bool]:
        """Accept only the app-server lease shape emitted by CodexDriver."""
        expected = {"threadId", "turnId", "processId", "processGroupId", "processStartTime"}
        if not isinstance(identity, dict) or set(identity) != expected:
            return None, False
        pid, pgid = identity.get("processId"), identity.get("processGroupId")
        started = identity.get("processStartTime")
        if (type(pid) is not int or type(pgid) is not int or pid <= 1 or pgid <= 1
                or pid != pgid or pgid == outer_pgid or not isinstance(started, str)
                or not started):
            return None, False
        try:
            observed_pgid = os.getpgid(pid)
        except ProcessLookupError:
            # The leader may already have exited while other members retain
            # this independently-created process group.
            return (pgid if AgentRunner._process_group_exists(pgid) else None), True
        except OSError:
            return None, False
        return (pgid, True) if observed_pgid == pgid else (None, False)

    @staticmethod
    def _bounded_wait(process, timeout: float) -> int | None:
        try:
            return process.wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired:
            return None
        except TypeError:
            # Keep lightweight process doubles bounded too; never fall back to
            # their potentially unbounded wait() implementation.
            deadline = time.monotonic() + max(0.0, timeout)
            while time.monotonic() < deadline:
                result = process.poll()
                if result is not None:
                    return result
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            return process.poll()

    def _stop_agent_process_groups(self, process, native_pgid: int | None,
                                   *, grace_seconds: float = 1.0) -> bool:
        """Stop and confirm the outer worker and any observed native group."""
        groups = list(dict.fromkeys(
            pgid for pgid in (process.pid, native_pgid)
            if type(pgid) is int and pgid > 1
        ))
        confirmed = True
        for pgid in groups:
            try:
                group_stopped = stop_process_group(
                    pgid, process=process if pgid == process.pid else None,
                    grace_seconds=grace_seconds)
            except ProcessLookupError:
                group_stopped = True
            except OSError:
                group_stopped = False
            confirmed = group_stopped and confirmed

        waited = self._bounded_wait(process, grace_seconds)
        if waited is None:
            for pgid in groups:
                try:
                    self._signal_process_group(pgid, signal.SIGKILL)
                except OSError:
                    confirmed = False
            waited = self._bounded_wait(process, grace_seconds)
        groups_gone = True
        for pgid in groups:
            if self._process_group_exists(pgid):
                groups_gone = False
        return confirmed and waited is not None and groups_gone

    @staticmethod
    def _profile(paths, *, active_root: Path, write_roots: list[Path] | None = None,
                 deny_write_paths: list[Path] | None = None,
                 extra_read_paths: list[Path] | None = None,
                 allow_internet: bool = True, read_roots: list[Path] | None = None):
        return "".join(strict_sandbox_rules(active_root, read_roots=read_roots or [active_root],
            write_roots=write_roots or [], protected_paths=paths,
            deny_write_paths=deny_write_paths,
            list_roots=[Path(__file__).resolve().parents[1]],
            extra_read_paths=extra_read_paths or [], allow_internet=allow_internet))

    def _report(self, request, store_id, kind, payload):
        self.journal.add_report(request["attemptId"], kind, store_id,
                                request["projectId"], self.runner_id, payload)

    def _report_started(self, request, store_id, identity, thread_observation, turn_observation):
        profile = request.get("profileSnapshot") or {}
        requested = {key: profile.get(key) for key in ("modelKey", "modelProvider", "effort")}
        thread_report = thread_observation.get("reported") if isinstance(thread_observation, dict) else None
        self._report(request, store_id, "started", {"nativeIdentity": identity,
            "startedAt": identity.get("processStartTime"), "requestedProfile": requested,
            "reportedProfile": None, "threadStartReported": thread_report,
            "turnStartAcknowledged": None if turn_observation is None else turn_observation.get("reported"),
            "actualProfile": None})

    def _seal(self, request, material, workspace):
        from tools.godot_mcp_install import verify_godot_mcp
        from backend.general_verification import audit_general_scope
        from backend.source_preparation import prepare_godot_uid_sidecars
        import subprocess
        packet = material["packet"]
        input_commit = material["prepared"]["inputCommit"]
        protected_assets = (packet.get("assetBundle") or {}).get("paths", [])
        if protected_assets:
            from backend.general_verification import _git_changed_paths, GeneralVerificationError
            if set(protected_assets) & set(_git_changed_paths(workspace, input_commit)):
                raise GeneralVerificationError("producer changed reviewed ImageGen PNG assets")
        verify_godot_mcp(workspace)
        materialize_service_records(workspace, material["prepared"].get("serviceRecords"))
        godot = os.environ.get("GODOT_BIN") or os.environ.get("GODOT_PATH") or "/Applications/Godot.app/Contents/MacOS/Godot"
        preparation = prepare_godot_uid_sidecars(workspace, base_commit=input_commit,
            document=packet["document"], godot_path=godot,
            service_records=material["prepared"].get("serviceRecords"))
        changed = audit_general_scope(workspace, input_commit, packet["document"],
             service_records=material["prepared"].get("serviceRecords"),
             prepared_uid_sidecars=preparation.sidecars)
        if changed:
            subprocess.run(["git", "-C", str(workspace), "add", "--", *changed], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", str(workspace), "-c", "user.name=Studio AgentRunner",
                            "-c", "user.email=runner@localhost", "commit", "--quiet", "-m",
                            "Seal producer output"], check=True, capture_output=True, text=True)
        commit = subprocess.run(["git", "-C", str(workspace), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        job_id = request["ownerRef"]["id"]
        artifact_id = "artifact-" + job_id
        final = self.artifact_root / artifact_id
        temp = self.artifact_root / (".sealing-" + job_id)
        if final.exists():
            raise RunnerError("sealed artifact ID already exists")
        if temp.exists():
            import shutil
            shutil.rmtree(temp)
        clone = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-local",
                                "--no-checkout", str(workspace), str(temp / "repository")],
                               capture_output=True, text=True, timeout=60, check=False)
        if clone.returncode:
            raise RunnerError("cannot seal private artifact: " + clone.stderr.strip())
        subprocess.run(["git", "-C", str(temp / "repository"), "remote", "remove", "origin"],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(temp / "repository"), "checkout", "--detach", commit],
                       check=True, capture_output=True, text=True)
        materialize_service_records(temp / "repository", material["prepared"].get("serviceRecords"))
        provenance_root = temp / "evidence"
        provenance_root.mkdir(mode=0o700)
        provenance = provenance_root / "uid-preparation.json"
        provenance.write_text(json.dumps(preparation.evidence(commit), ensure_ascii=False,
                                        sort_keys=True, indent=2) + "\n", encoding="utf-8")
        provenance.chmod(0o600)
        temp.rename(final)
        return {"artifactId": artifact_id, "projectId": request["projectId"], "jobId": job_id,
                "attemptId": request["attemptId"], "sourceCommit": commit,
                "inputCommit": input_commit, "packetId": packet["id"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Standalone Studio AgentRunner")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--runner-token-file", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--protected-root", required=True)
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
        runner = AgentRunner(api, journal, Path(args.workspace_root), Path(args.artifact_root),
                             Path(args.protected_root), stop_event=stop_event)
        handshake = retry_transport(lambda: api.request("GET", "/internal/v1/handshake"), stop_event)
        if handshake is None:
            return
        store_id = handshake.get("storeId")
        if not isinstance(store_id, str):
            raise RunnerError("handshake did not provide storeId")
        journal.bind_store(store_id)
        retry_transport(runner.register, stop_event)
        retry_transport(runner.publish_catalog, stop_event)
        catalog_thread = threading.Thread(target=runner.catalog_refresh_loop, args=(stop_event,),
                                          name="studio-model-catalog", daemon=False)
        catalog_thread.start()
        def iteration():
            runner.journal.flush(api)
            api.request("POST", "/internal/v1/heartbeat", {
                "runnerId": runner.runner_id, "storeId": store_id,
                "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            claimed = runner.claim(store_id)
            execution = claimed.get("request")
            if execution:
                runner.accept_claim(execution, store_id)
        try:
            service_loop(iteration, stop_event, once=args.once)
        finally:
            stop_event.set()
            catalog_thread.join(timeout=30)
    for signum, handler in previous_handlers.items():
        signal.signal(signum, handler)


if __name__ == "__main__":
    main()

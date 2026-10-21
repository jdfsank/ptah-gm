"""Transactional Studio v1 commands, projections and execution ownership.

This module owns no processes. Only the authenticated backend decides approval,
publication and attempt occupancy. Runner observations never constitute approval.
"""
from __future__ import annotations

import base64
import copy
import json
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PUBLIC_KINDS = {"project", "proposal", "packet", "job", "snapshot", "preferences", "attempt", "preview", "feedback", "command"}
TERMINAL_ATTEMPTS = {"COMPLETED", "STOPPED", "FAILED"}
MAX_PENDING_AGENT_ATTEMPTS = 8
PRIVATE_FIELDS = {"planningEvidence", "sessionEvidence", "planningLease", "executionLease", "approvedProposal", "approvalEventId", "decisionEventId", "gmSpecificationConfirmation", "operatorId", "storePath", "cwd", "stdout", "stderr", "commandEvidence", "commands", "diagnostics", "specInventory", "templateInventory", "sourceRefs"}
REVIEW_FIELDS = ("id", "projectId", "revision", "publicationRevision", "baseCommit", "repairBase", "text", "discussion", "document", "tasks", "requirements", "feedback", "feedbackDecisions", "changeRequest", "assets", "visualReferences", "assetBundle", "scope", "roles", "acceptance", "gmSpecRef", "specInventory", "templateInventory", "sourceRefs", "objectChanges", "templateId", "testData", "productionAuthorized")


def _core():
    from .coordinator import WorkflowError, canonical, git, identifier, now
    return WorkflowError, canonical, git, identifier, now


def fail(code, message, status=409):
    raise _core()[0](status, code, message)


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [public(item) for item in value]
    return value


def instant():
    return datetime.now(timezone.utc)


class StudioProtocol:
    def _workbench_repository(self, snapshot):
        pid, commit = snapshot["projectId"], snapshot["sourceCommit"]
        paths = [self.state_root / "projects" / pid]
        if snapshot.get("jobId"):
            paths.insert(0, self.state_root / "jobs" / snapshot["jobId"] / "worktree")
        artifact = snapshot.get("artifactRef")
        if artifact:
            try:
                paths.insert(0, self._artifact_repository(artifact, project_id=pid))
            except (RuntimeError, ValueError, OSError):
                pass
        for repo in paths:
            if not (repo / ".git").exists():
                continue
            try:
                _core()[2](repo, "cat-file", "-e", commit + "^{commit}")
            except (RuntimeError, OSError):
                continue
            return repo
        return None

    def workbench_object_source(self, project_id, object_id, *, image=False):
        """Return only the selected target's bound source at its exact version."""
        snapshot = self.planning_baseline(project_id)
        if not snapshot:
            fail("SOURCE_UNAVAILABLE", "当前尚无可查看的工程源版本。", 404)
        obj = next((o for o in snapshot["document"]["objects"] if o["id"] == object_id), None)
        if obj is None:
            fail("TARGET_UNAVAILABLE", "此目标已失效，请重新选择或保留意见后关联。", 404)
        repo = self._workbench_repository(snapshot)
        if repo is None:
            fail("SOURCE_UNAVAILABLE", "精确源版本暂不可用，目标和意见仍保留。", 404)
        bindings = obj.get("sourceBindings", [])
        from .workbench_resources import describe_image, preview_bytes, resource_path

        def read_resource(path, limit):
            path = resource_path(path)
            try:
                size = int(_core()[2](repo, "cat-file", "-s", snapshot["sourceCommit"] + ":" + path))
            except RuntimeError:
                raise ValueError("绑定资源在此源版本中缺失。") from None
            if size > limit:
                raise ValueError("此资源过大，请通过工程资源查看。")
            result = subprocess.run(["git", "show", snapshot["sourceCommit"] + ":" + path], cwd=repo, capture_output=True, timeout=15, check=False)
            if result.returncode:
                raise ValueError("绑定资源在此源版本中缺失。")
            return result.stdout

        description, preview_reason = None, None
        try:
            description = describe_image(obj, read_resource)
            if image:
                return preview_bytes(description, read_resource)
        except (ValueError, OSError, UnicodeError) as exc:
            preview_reason = str(exc)
            if image:
                fail("IMAGE_UNAVAILABLE", preview_reason + " 程序绘制内容请查看语义预览。", 404)
        sources = []
        for path in bindings[:20]:
            if Path(path).suffix.lower() not in {".gd", ".tscn", ".tres"}:
                continue
            try:
                size = int(_core()[2](repo, "cat-file", "-s", snapshot["sourceCommit"] + ":" + path))
                if size > 250_000:
                    sources.append({"path": path, "available": True, "content": None, "reason": "源文件较大，请在工程中查看。"})
                    continue
                source = _core()[2](repo, "show", snapshot["sourceCommit"] + ":" + path)
                sources.append({"path": path, "available": True, "content": source[:20000], "truncated": len(source) > 20000})
            except RuntimeError:
                sources.append({"path": path, "available": False, "content": None, "reason": "此源版本尚无对应文件。"})
        return {"projectId": project_id, "objectId": object_id, "sourceCommit": snapshot["sourceCommit"], "kind": "static_source", "sources": sources,
                "imagePreview": description, "imagePreviewUnavailableReason": preview_reason}

    def _enrich_workbench_snapshot(self, snapshot):
        """Read semantic facts at the retained Git version, without publishing.

        The same projection is used for browsing and iteration validation so
        derived targets remain addressable when a user submits a comment.
        """
        if not snapshot or not snapshot.get("document") or not snapshot.get("sourceCommit"):
            return snapshot
        from .workbench_model import enrich_casino_document
        from .object_protocol import catalog_from_document
        pid, commit = snapshot["projectId"], snapshot["sourceCommit"]
        key = (pid, commit, json.dumps(snapshot["document"], sort_keys=True, ensure_ascii=False))
        cache = getattr(self, "_workbench_projection_cache", {})
        if key in cache:
            document = copy.deepcopy(cache[key])
        else:
            document = snapshot["document"]
            repo = self._workbench_repository(snapshot)
            if repo is not None:
                document = enrich_casino_document(document, repo_path=repo, source_commit=commit)
            if len(cache) >= 12:
                cache.pop(next(iter(cache)))
            cache[key] = copy.deepcopy(document)
            self._workbench_projection_cache = cache
        return {**snapshot, "document": document, "catalog": catalog_from_document(document, commit)}

    def workbench_source_changes(self, project_id, job_id):
        """Show retained candidate changes; a diff is evidence, not acceptance."""
        job = self.require_project_resource(project_id, "job", job_id)
        candidate = job.get("candidate") or {}
        commit = candidate.get("candidateCommit")
        base = job.get("originalBaseCommit") or job.get("baseCommit") or job.get("inputCommit")
        if not commit or not base:
            fail("CHANGES_UNAVAILABLE", "本轮尚无保留的候选源码差异。", 404)
        repo = self._workbench_repository({"projectId": project_id, "jobId": job_id,
            "sourceCommit": commit, "artifactRef": candidate.get("artifactRef")})
        if repo is None:
            fail("SOURCE_UNAVAILABLE", "本轮精确源码暂不可用；申报记录仍保留。", 404)
        try:
            paths = _core()[2](repo, "diff", "--name-only", "--no-renames", base, commit, "--").splitlines()
        except RuntimeError:
            fail("CHANGES_UNAVAILABLE", "本轮原版本暂不可用，无法展示可靠差异。", 404)
        eligible = [path for path in paths if path.startswith(("scripts/", "scenes/", "resources/", "assets/", "design/")) or path == "project.godot"]
        changes, remaining = [], 120000
        for path in eligible[:100]:
            patch = _core()[2](repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=3", base, commit, "--", path)
            limit = min(20000, remaining)
            changes.append({"path": path, "diff": patch[:limit], "truncated": len(patch) > limit})
            remaining -= min(len(patch), limit)
            if remaining <= 0:
                break
        return {"projectId": project_id, "jobId": job_id, "candidateId": candidate.get("id"),
                "baseCommit": base, "baseKind": "production_input" if base == job.get("inputCommit") else "source_baseline",
                "sourceCommit": commit, "kind": "retained_git_diff",
                "changes": changes, "truncated": len(eligible) > len(changes) or any(change["truncated"] for change in changes), "userAcceptance": "NOT_PERFORMED"}

    def _init_studio_protocol(self):
        self.service_instance_id = _core()[3]("instance")
        token_file = self.state_root / "runner-token"
        if token_file.is_symlink():
            fail("RUNNER_TOKEN_PATH", "执行器凭据路径不能是链接。")
        self.runner_token = token_file.read_text().strip() if token_file.is_file() else secrets.token_urlsafe(40)
        if not self.runner_token:
            fail("RUNNER_TOKEN_EMPTY", "执行器凭据为空。")
        token_file.write_text(self.runner_token + "\n")
        token_file.chmod(0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS commands(scope TEXT, command_id TEXT, actor TEXT, content TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(scope,command_id));
            CREATE TABLE IF NOT EXISTS reports(runner_id TEXT, report_id TEXT, content TEXT NOT NULL, ack TEXT NOT NULL, PRIMARY KEY(runner_id,report_id));
            CREATE TABLE IF NOT EXISTS project_events(project_id TEXT, sequence INTEGER, event_id TEXT UNIQUE, payload TEXT NOT NULL, PRIMARY KEY(project_id,sequence));
            CREATE TABLE IF NOT EXISTS claims(runner_id TEXT, command_id TEXT, content TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(runner_id,command_id));
            CREATE INDEX IF NOT EXISTS studio_pending_runner_attempts
                ON entities(json_extract(payload,'$.runnerId'))
                WHERE kind='attempt' AND json_extract(payload,'$.status') NOT IN ('COMPLETED','STOPPED','FAILED');
            CREATE INDEX IF NOT EXISTS studio_project_status
                ON entities(kind,json_extract(payload,'$.projectId'),json_extract(payload,'$.status'));
        """)
        self.db.commit()

    def _record_public_change(self, kind, value):
        if kind not in PUBLIC_KINDS:
            return
        pid = value.get("projectId") or (value["id"] if kind == "project" else None)
        if not pid:
            return
        _, canonical, _, identifier, now = _core()
        row = self.db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()
        if row is None:
            return
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM project_events WHERE project_id=?", (pid,)).fetchone()[0]
        event = {"schemaVersion": "studio.message.v1", "kind": "event", "storeId": row[0], "projectId": pid,
                 "sequence": sequence, "eventId": identifier("event"), "type": "project.changed", "occurredAt": now(),
                 "payload": {"resource": {"kind": kind, "id": value["id"]}}}
        self.db.execute("INSERT INTO project_events VALUES(?,?,?,?)", (pid, sequence, event["eventId"], canonical(event)))

    def events_after(self, project_id, after):
        self._revision(after)
        with self.lock:
            self._get("project", project_id)
            bounds = self.db.execute("SELECT MIN(sequence),MAX(sequence) FROM project_events WHERE project_id=?", (project_id,)).fetchone()
            if (bounds[0] is not None and after and after < bounds[0] - 1) or (after > (bounds[1] or 0)):
                fail("RESYNC_REQUIRED", "状态游标已失效，请重新读取一致项目视图。")
            return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM project_events WHERE project_id=? AND sequence>? ORDER BY sequence LIMIT 256", (project_id, after))]

    def session_preferences(self, project_id):
        self._get("project", project_id)
        values = self._all_project("preferences", project_id)
        return values[0] if values else {"id": "preferences:" + project_id, "projectId": project_id, "revision": 0,
            "roles": {"planner": {"modelKey": None, "effort": None, "limits": {"maxDurationSeconds": 420, "softTotalTokens": None}},
                      "producer": {"modelKey": None, "effort": None, "limits": {"maxDurationSeconds": 1800, "softTotalTokens": None}}}}

    def session_catalog(self, project_id):
        self._get("project", project_id)
        runners = [r for r in self._all("runner") if r.get("runnerKind") == "agent"]
        runner = runners[0] if runners else {}
        catalog = runner.get("catalog") or {}
        online = time.time() - runner.get("lastHeartbeat", 0) <= 30
        fresh = time.time() - catalog.get("receivedAt", 0) <= 600
        return {"schemaVersion": "studio.message.v1", "kind": "catalog", "storeId": self.store_id, "projectId": project_id,
                "runnerId": runner.get("id"), "catalogRevision": catalog.get("catalogRevision"), "observedAt": catalog.get("observedAt"),
                "models": catalog.get("models", []), "available": bool(online and fresh),
                "runnerOnline": bool(online), "catalogFresh": bool(fresh), "nativeVersion": runner.get("nativeVersion"),
                "environment": runner.get("environment"), "capabilities": runner.get("capabilities", [])}

    def _resolve_profile(self, project_id, role, expected, assets):
        preferences = self.session_preferences(project_id)
        if expected.get("preferencesRevision") != preferences["revision"]:
            fail("STALE_PREFERENCES", "执行设置修订已变化，请读取本次设置后重试原命令。")
        catalog = self.session_catalog(project_id)
        if not catalog["available"]:
            fail("RUNNER_UNAVAILABLE", "执行器或模型目录不可用，草稿可保存；本次执行尚未接收。", 423)
        selected = preferences["roles"][role]
        models = catalog["models"]
        model = next((m for m in models if m["modelKey"] == selected["modelKey"]), None)
        if selected["modelKey"] is None:
            model = next((m for m in models if m.get("isDefault")), models[0] if models else None)
        if not model:
            fail("MODEL_UNAVAILABLE", "所选模型不在目标执行器目录中。")
        if model.get("modelProvider") in {None, "", "unknown"}:
            fail("PROVIDER_UNOBSERVED", "目录尚未提供可核对的模型供应方；本次执行保持未启动。", 423)
        efforts = model["supportedReasoningEfforts"]
        effort_values = [e["reasoningEffort"] if isinstance(e, dict) else e for e in efforts]
        effort = selected["effort"] or model.get("defaultReasoningEffort") or (effort_values[0] if effort_values else None)
        if effort not in effort_values:
            fail("EFFORT_UNAVAILABLE", "所选推理档位不受当前模型支持。")
        if assets and "image" not in model["inputModalities"]:
            fail("MODALITY_UNAVAILABLE", "所选模型不能接收参考图片；不会删除参考或替换模型。")
        runner = self._get("runner", catalog["runnerId"])
        policy = "planning-readonly-v1" if role == "planner" else "production-private-v1"
        if policy not in runner.get("capabilities", []):
            fail("ISOLATION_UNAVAILABLE", "当前执行器未通过该角色的进程访问拒绝验证。", 423)
        self._check_session_admission(runner)
        return {"preferencesRevision": preferences["revision"], "catalogRevision": catalog["catalogRevision"],
                "runnerId": catalog["runnerId"], "nativeVersion": catalog["nativeVersion"], "environment": catalog["environment"],
                "modelKey": model["modelKey"], "modelProvider": model["modelProvider"], "effort": effort,
                "rolePolicy": policy, "contextPolicy": "targeted-project-inspection-v1", "limits": copy.deepcopy(selected["limits"])}

    def _check_session_admission(self, runner):
        gate = runner.get("sessionRetryGate") or {}
        remaining = gate.get("notBefore", 0) - time.time()
        if remaining > 0:
            fail("SESSION_COOLDOWN", f"执行器失败后正在冷却，请约 {int(remaining) + 1} 秒后重试；原输入保留，尚未创建新执行。", 429)
        pending = len(self._pending_runner_attempts(runner["id"]))
        if pending >= MAX_PENDING_AGENT_ATTEMPTS:
            fail("SESSION_CAPACITY", "执行器排队已满（最多 8 个未结束任务）；请等待已有执行结束，原输入保留。", 429)

    def _pending_runner_attempts(self, runner_id):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM entities WHERE kind='attempt' "
            "AND json_extract(payload,'$.status') NOT IN ('COMPLETED','STOPPED','FAILED') "
            "AND json_extract(payload,'$.runnerId')=? ORDER BY rowid DESC", (runner_id,))]

    def _record_session_terminal(self, attempt):
        """Count each confirmed terminal outcome once, including after restart."""
        if attempt["taskKind"] not in {"plan", "visual-plan", "produce"} or attempt.get("terminalRecordedAt"):
            return
        if attempt["status"] not in TERMINAL_ATTEMPTS:
            return
        attempt["terminalRecordedAt"] = _core()[4]()
        runner = self._get("runner", attempt["runnerId"])
        if attempt["status"] == "FAILED" or attempt.get("stopReason") in {"time_limit", "soft_budget", "native_error"}:
            previous = runner.get("sessionRetryGate") or {}
            count = previous.get("consecutiveFailures", 0) if time.time() - previous.get("failedAt", 0) < 600 else 0
            count = min(count + 1, 6)
            pause = min(60, 5 * 2 ** (count - 1))
            not_before = time.time() + pause
            runner["sessionRetryGate"] = {"consecutiveFailures": count,
                "failedAt": time.time(), "notBefore": not_before, "attemptId": attempt["id"]}
            attempt["retryNotBefore"] = datetime.fromtimestamp(not_before, timezone.utc).isoformat()
        elif attempt["status"] == "COMPLETED":
            runner.pop("sessionRetryGate", None)
        self._put("runner", runner)

    def _review_payload(self, proposal):
        return {key: copy.deepcopy(proposal[key]) for key in REVIEW_FIELDS if key in proposal}

    def _reviewed_plan(self, proposal):
        if proposal.get("status") not in {"READY", "FROZEN"}:
            return None
        payload = self._review_payload(proposal)
        for item in self._all_project("reviewed_plan", proposal["projectId"]):
            if item["proposalId"] == proposal["id"] and item["payload"] == payload:
                return item
        if proposal.get("protocolVersion") != 1:
            return None
        plan = {"id": _core()[3]("plan"), "projectId": proposal["projectId"], "proposalId": proposal["id"],
                "proposalRevision": proposal["revision"], "payload": payload, "createdAt": _core()[4]()}
        self._put("reviewed_plan", plan)
        return plan

    def project_view(self, project_id):
        # A single read transaction binds the projection to its event watermark.
        with self.transaction():
            workspace = self.project_workspace(project_id)
            for active_attempt in self._all_project("attempt", project_id):
                self._expire_attempt(active_attempt)
            workspace = self.project_workspace(project_id)
            project = workspace["projects"][0]
            proposals, packets, jobs = workspace["proposals"], workspace["packets"], workspace["jobs"]
            proposal, packet, job = (values[0] if values else None for values in (proposals, packets, jobs))
            if proposal:
                ref = self._reviewed_plan(proposal)
                if ref:
                    proposal = {**proposal, "reviewedPlanRef": ref["id"]}
                    proposals[0] = proposal
            snapshot = self._enrich_workbench_snapshot(self.require_project_resource(project_id, "snapshot", project["snapshotId"])) if project.get("snapshotId") else None
            attempts = self._all_project("attempt", project_id)
            # Reconstruct display metadata from the exact retained attempt;
            # do not rewrite historical jobs, approvals, or execution state.
            by_attempt = {item["id"]: item for item in attempts}
            for item in jobs:
                retained = by_attempt.get(item.get("attemptId"))
                if (item.get("status") in {"FAILED", "UNCERTAIN", "CANCELLED"}
                        and retained and retained.get("taskKind") == "produce"):
                    item["productionFailure"] = self._producer_failure(
                        retained, uncertain=item["status"] == "UNCERTAIN", failed=item["status"] == "FAILED")
            attempt = attempts[0] if attempts else None
            repair = self.repair_context(project_id)
            phase, step, attention, actions = self._view_state(project, proposal, packet, job, snapshot, attempt, repair)
            previews = self._all_project("preview", project_id)
            active_previews = [p for p in previews if p.get("status") not in {"STOPPED", "FAILED"}]
            if active_previews:
                actions = [a for a in actions if a != "preview.start"]
                actions.append("preview.stop")
            elif snapshot and not project.get("archived") and "preview.start" not in actions:
                actions.append("preview.start")
            preview_runner_available = any(
                runner.get("runnerKind") == "project"
                and "preview-isolated-v1" in runner.get("capabilities", [])
                and time.time() - runner.get("lastHeartbeat", 0) <= 30
                for runner in self._all("runner")
            )
            if not preview_runner_available:
                actions = [action for action in actions if action != "preview.start"]
            observations = None
            if attempt:
                runner = self._get("runner", attempt["runnerId"])
                observations = {"attemptId": attempt["id"], "taskKind": attempt["taskKind"], "status": attempt["status"],
                    "runner": {"runnerId": runner["id"], "lastHeartbeatAt": runner.get("lastHeartbeatAt"), "online": time.time()-runner.get("lastHeartbeat",0)<=30},
                    "lastActivity": attempt.get("lastActivity"), "requested": attempt.get("profileSnapshot"),
                    "threadStartReported": attempt.get("threadStartReported"), "turnStartAcknowledged": attempt.get("turnStartAcknowledged"),
                    "actualProfile": attempt.get("actualProfile"), "usage": attempt.get("usage", {"totalTokens": None, "observedAt": None, "coverage": "unknown"}),
                    "stopReason": attempt.get("stopReason"), "leaseExpiresAt": (attempt.get("lease") or {}).get("expiresAt")}
            sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM project_events WHERE project_id=?", (project_id,)).fetchone()[0]
            view = {**public(workspace), "schemaVersion": "studio.project-view.v1", "storeId": self.store_id, "serviceInstanceId": self.service_instance_id, "projectId": project_id,
                "throughSequence": sequence, "phase": phase, "step": step, "attention": attention, "allowedActions": actions,
                "project": public(project), "proposal": public(proposal), "packet": public(packet), "job": public(job), "snapshot": public(snapshot),
                "candidates": [public(dict(j["candidate"], status=j["status"])) for j in jobs if j.get("candidate") and j["status"] == "READY_FOR_REVIEW"], "observations": observations,
                "previews": public(previews),
                "sessionPreferences": self.session_preferences(project_id), "sessionCatalog": self.session_catalog(project_id),
                "feedback": public(self._all_project("feedback", project_id)), "repairContext": public(repair)}
            from .workbench_results import iteration_results
            view["workbenchResults"] = public(iteration_results(proposals, packets, jobs, view["feedback"]))
            if snapshot:
                view.update(catalog=snapshot.get("catalog"), document=snapshot.get("document"), publicationRevision=project["publicationRevision"])
            return view

    @staticmethod
    def _view_state(project, proposal, packet, job, snapshot, attempt, repair=None):
        if project.get("archived"):
            return "archived", "archived", "none", ["project.settings.update"]
        if attempt and attempt["status"] in {"UNKNOWN", "UNCERTAIN"}:
            return "execution", "uncertain", "uncertain", ["execution.reconcile", "execution.cancel"]
        if job and job["status"] in {"QUEUED", "DISPATCHING", "RUNNING", "PROJECTING", "VERIFYING", "CANCELLING", "CANCEL_REQUESTED", "UNCERTAIN"}:
            step = "verifying" if job["status"] == "VERIFYING" else "producing"
            return "execution", step, "uncertain" if job["status"] == "UNCERTAIN" else "none", ["execution.cancel", "execution.reconcile"]
        if job and job["status"] == "READY_FOR_REVIEW":
            return "candidate", "candidate_review", "user", ["candidate.accept", "candidate.reject", "preview.start"]
        if proposal and proposal["status"] in {"PLANNING", "PLANNING_CANCELLING", "PLANNING_UNCERTAIN"}:
            return "discussion", "planning", "uncertain" if proposal["status"] == "PLANNING_UNCERTAIN" else "none", ["execution.cancel", "execution.reconcile"]
        if proposal and proposal["status"] == "READY":
            return "discussion", "proposal_review", "user", ["proposal.revise", "proposal.freeze"]
        if proposal and proposal["status"] == "NEEDS_CLARIFICATION":
            return "discussion", "clarification", "user", ["proposal.revise"]
        if proposal and proposal["status"] == "FAILED":
            return "discussion", "planning_failed", "user", ["concept.submit", "session.preferences.update"]
        if proposal and proposal["status"] == "FROZEN" and packet and (not job or job.get("packetId") != packet["id"]):
            return "production", "frozen", "user", ["production.start", "proposal.revise"]
        if repair:
            return "iteration", "repair", "user", ["iteration.submit", "session.preferences.update"]
        return ("iteration" if snapshot else "discussion", "accepted" if snapshot else "concept", "user", ["iteration.submit" if snapshot else "concept.submit", "session.preferences.update"])

    def command_lookup(self, project_id, command_id, actor):
        with self.lock:
            scope = project_id or "@store"
            row = self.db.execute("SELECT actor,receipt FROM commands WHERE scope=? AND command_id=?", (scope, command_id)).fetchone()
            if row and row[0] != actor:
                fail("COMMAND_AUTHORITY", "原命令不属于当前授权来源。", 403)
            return {"schemaVersion": "studio.message.v1", "kind": "command_lookup", "storeId": self.store_id,
                "projectId": project_id, "commandId": command_id, "known": bool(row), "receipt": json.loads(row[1]) if row else None}

    def submit_command(self, message, *, operator_id, project_id=None):
        from .object_protocol import validate_command
        message = validate_command(message)
        self._operator(operator_id)
        if message["storeId"] != self.store_id or message.get("projectId") != project_id:
            fail("COMMAND_IDENTITY", "命令的数据空间或项目身份不匹配。", 409)
        _, canonical, _, _, _ = _core()
        scope, cid = project_id or "@store", message["commandId"]
        # Transport dates are not part of the business intent.
        content = canonical({k: v for k, v in message.items() if k not in {"sentAt"}})
        with self.transaction():
            row = self.db.execute("SELECT actor,content,receipt FROM commands WHERE scope=? AND command_id=?", (scope, cid)).fetchone()
            if row:
                if row[0] != operator_id or row[1] != content:
                    fail("COMMAND_CONFLICT", "同一命令编号已绑定其他内容或授权。")
                return json.loads(row[2])
            rejection = None
            try:
                with self.transaction():
                    result, resource = self._apply_command(message, operator_id)
            except _core()[0] as exc:
                result, resource = None, None
                rejection = {"code": exc.code, "message": exc.message, "status": exc.status}
            receipt = {"schemaVersion": "studio.message.v1", "kind": "receipt", "type": message["type"], "storeId": self.store_id,
                "projectId": project_id, "commandId": cid, "status": "rejected" if rejection else "accepted", "resource": resource, "result": public(result)}
            if rejection:
                receipt["error"] = rejection
            self.db.execute("INSERT INTO commands VALUES(?,?,?,?,?)", (scope, cid, operator_id, content, canonical(receipt)))
            if project_id:
                self._record_public_change("command", {"id": cid, "projectId": project_id})
            return receipt

    def _apply_command(self, message, operator):
        t, p, expected, pid = message["type"], message["payload"], message.get("expected", {}), message.get("projectId")
        _, _, _, identifier, now = _core()
        if t == "project.create":
            project = self.create_project(operator_id=operator, title=p["name"])
            project.update(protocolVersion=1, executionBackend="runners")
            self._put("project", project)
            return {"project": project}, {"kind": "project", "id": project["id"]}
        project = self._get("project", pid)
        if t == "project.settings.update":
            result = self.update_project_settings(operator_id=operator, project_id=pid, title=p.get("name"), archived=p.get("archived"))
            return {"project": result}, {"kind": "project", "id": pid}
        if t == "session.preferences.update":
            pref = self.session_preferences(pid)
            if expected.get("preferencesRevision") != pref["revision"]:
                fail("STALE_PREFERENCES", "设置修订已变化。")
            pref["roles"][p["role"]] = {k: copy.deepcopy(p[k]) for k in ("modelKey", "effort", "limits")}
            pref["revision"] += 1
            self._put("preferences", pref)
            return {"preferences": pref}, {"kind": "preferences", "id": pref["id"]}
        # Only a new iteration may use durable commands on a legacy project.
        # Its existing execution owner and historical approval stay intact.
        legacy_iteration = (t == "iteration.submit" and project.get("protocolVersion") != 1
                            and project.get("executionBackend") != "runners")
        if t in {"concept.submit", "iteration.submit", "proposal.revise", "production.start"}:
            if project.get("protocolVersion") != 1 and not legacy_iteration:
                fail("LEGACY_EXECUTION", "旧执行项目须先结束并核账，不能重写历史批准。")
            if expected.get("publicationRevision") != project["publicationRevision"]:
                fail("STALE_PUBLICATION", "已接受版本变化，请先重关联草稿。")
            if t != "production.start":
                snapshot = self.planning_baseline(pid)
                if expected.get("sourceCommit") != (snapshot or {}).get("sourceCommit"):
                    fail("STALE_SOURCE", "草稿没有绑定精确发布或返修源版本。")
                if snapshot and snapshot.get("materializationStatus") == "PENDING":
                    fail("MATERIALIZATION_PENDING", "精确源副本尚未物化，可保留草稿，待恢复后提交。", 423)
        if t in {"concept.submit", "iteration.submit"}:
            if t == "iteration.submit" and not (self.iteration_status(pid)["iterationReady"] or self.repair_context(pid)):
                fail("ITERATION_NOT_READY", "首个 Demo 经验证并接受后才能开始迭代。")
            snapshot = self.planning_baseline(pid)
            asset_ids = p.get("assetRefs", [a["id"] for a in (snapshot or {}).get("assets", [])])
            references = p.get("visualReferences", (snapshot or {}).get("visualReferences") if "assetRefs" not in p else None)
            profile = None if legacy_iteration else self._resolve_profile(pid, "planner", expected, asset_ids)
            request = None
            if snapshot:
                request = {**({} if legacy_iteration else {"schemaVersion": "studio.change-request.v1"}), "baseRevision": project["publicationRevision"], "sourceCommit": snapshot["sourceCommit"], "targetObjectIds": p.get("targetObjectIds", []), "fields": p.get("fields", []), "feedback": p.get("feedback", []),
                    **({"operations": p["operations"]} if "operations" in p else {})}
            self._command_profile = profile
            try:
                proposal = self.create_generic_concept(operator_id=operator, text=p.get("text", ""), project_id=pid, asset_ids=asset_ids, expected_publication_revision=project["publicationRevision"], change_request=request, visual_references=references)
            finally:
                self._command_profile = None
            # The proposal is queued transactionally by _launch_planning.
            proposal = self._get("proposal", proposal["id"])
            proposal["feedback"] = copy.deepcopy((proposal.get("changeRequest") or {}).get("feedback", p.get("feedback", [])))
            self._save_feedback(pid, proposal, proposal["feedback"])
            self._put("proposal", proposal)
            return {"proposal": proposal}, {"kind": "proposal", "id": proposal["id"]}
        if t == "proposal.revise":
            proposal = self.require_project_resource(pid, "proposal", p["proposalId"])
            repair = self.repair_context(pid)
            if repair and (proposal.get("repairBase") or {}).get("sourceCommit") != repair["sourceCommit"]:
                fail("STALE_REPAIR", "请从候选返修工作台创建新方案，保留已制作的实现。")
            if proposal["revision"] != expected.get("proposalRevision") or proposal["status"] not in {"READY", "NEEDS_CLARIFICATION", "FROZEN", "FAILED", "CANCELLED"}:
                fail("STALE_PROPOSAL", "提案已变化或原执行尚未停止。")
            self._available(pid)
            if proposal["publicationRevision"] != project["publicationRevision"]:
                fail("STALE_PUBLICATION", "方案基线已变化。")
            profile = self._resolve_profile(pid, "planner", expected, p.get("assetRefs", [a["id"] for a in proposal.get("assets", [])]))
            question_ids = {q["id"] for q in proposal.get("questions", [])}
            if any(a["questionId"] not in question_ids for a in p.get("answers", [])):
                fail("ANSWER_REFERENCE", "回答没有引用本修订中的问题。", 400)
            answered = {a["questionId"] for a in p.get("answers", []) if a["text"].strip()}
            if proposal["status"] == "NEEDS_CLARIFICATION" and any(q.get("required", True) and q["id"] not in answered for q in proposal["questions"]):
                fail("ANSWER_REQUIRED", "请完成本轮必答问题。", 400)
            proposal["discussion"].append({"role": "user", "revision": proposal["revision"] + 1, "answers": p.get("answers", []), "text": p.get("supplement", ""), "at": now()})
            proposal["feedback"] = self._merge_feedback(proposal.get("feedback", []), p.get("feedback", []))
            if proposal.get("changeRequest"):
                proposal["changeRequest"]["feedback"] = self._merge_feedback(proposal["changeRequest"].get("feedback", []), p.get("feedback", []))
            self._save_feedback(pid, proposal, proposal["feedback"])
            if "assetRefs" in p:
                proposal["assets"] = [self.require_project_asset(pid, aid) for aid in p["assetRefs"]]
            if "visualReferences" in p or "assetRefs" in p:
                previous = [r for r in proposal.get("visualReferences", []) if r["assetId"] is None or r["assetId"] in {a["id"] for a in proposal["assets"]}]
                proposal["visualReferences"] = self.resolve_visual_references(pid, proposal["assets"], p.get("visualReferences", previous), proposal.get("currentDocument"))
            for key in ("planningEvidence", "planningLease", "planningFailure", "planningRecovery", "planningTerminationConfirmed", "reviewedPlanRef", "packetId", "assetBundle"):
                proposal.pop(key, None)
            proposal.update(revision=proposal["revision"]+1, status="PLANNING", questions=[], updatedAt=now(), profileSnapshot=profile)
            self._put("proposal", proposal)
            self._queue_planning(proposal, profile)
            return {"proposal": proposal}, {"kind": "proposal", "id": proposal["id"]}
        if t == "proposal.assets.attach":
            from .imagegen_assets import load_bundle, ImageAssetError
            proposal = self.require_project_resource(pid, "proposal", p["proposalId"])
            self._available(pid)
            if proposal["status"] not in {"READY", "FROZEN"} or proposal["revision"] != expected.get("proposalRevision"):
                fail("STALE_PROPOSAL", "只能向当前完整且已停止的方案导入素材。")
            if project["publicationRevision"] != expected.get("publicationRevision") or proposal["publicationRevision"] != project["publicationRevision"]:
                fail("STALE_PUBLICATION", "素材包的发布基线已变化。")
            try:
                ref, plan, _ = load_bundle(self.state_root, p["bundleId"])
            except ImageAssetError as exc:
                fail("IMAGE_BUNDLE_INVALID", str(exc))
            if any(plan.get(key) != proposal.get(key) for key in ("id", "projectId", "revision", "publicationRevision", "document", "tasks", "sourceRefs")):
                fail("IMAGE_BUNDLE_BINDING", "素材包没有绑定当前精确方案。")
            proposal.update(revision=proposal["revision"] + 1, status="READY", assetBundle=ref, updatedAt=now())
            for key in ("packetId", "reviewedPlanRef", "attemptId"):
                proposal.pop(key, None)
            proposal.update(self._prepare_generic_spec(proposal, proposal["document"], proposal["tasks"]))
            self._put("proposal", proposal)
            self._reviewed_plan(proposal)
            return {"proposal": proposal}, {"kind": "proposal", "id": proposal["id"]}
        if t == "proposal.freeze":
            proposal = self.require_project_resource(pid, "proposal", p["proposalId"])
            ref = self.require_project_resource(pid, "reviewed_plan", p["reviewedPlanRef"])
            if ref["proposalId"] != proposal["id"] or ref["proposalRevision"] != expected.get("proposalRevision") or ref["payload"] != self._review_payload(proposal):
                fail("REVIEW_MISMATCH", "完整审阅计划或修订已变化。")
            self._check_producer_asset_inputs(proposal)
            packet = self.freeze_generic_proposal(operator_id=operator, proposal_id=proposal["id"], expected_revision=expected["proposalRevision"], expected_publication_revision=expected["publicationRevision"], reviewed_proposal=proposal)
            packet.update(reviewedPlanRef=ref["id"], feedbackDecisions=proposal.get("feedbackDecisions", []), feedback=proposal.get("feedback", []))
            if proposal.get("assetBundle"):
                packet["assetBundle"] = copy.deepcopy(proposal["assetBundle"])
            self._put("packet", packet)
            return {"packet": packet}, {"kind": "packet", "id": packet["id"]}
        if t == "production.recover":
            # Operator-only continuation of finalization, with no new native
            # turn and no new specification approval consumption. The failed
            # native attempt/report stays terminal and retained.
            self._available(pid)
            job = self.require_project_resource(pid, "job", p["jobId"])
            attempt = self.require_project_resource(pid, "attempt", p["attemptId"])
            packet = self.require_project_resource(pid, "packet", job["packetId"])
            proposal = self.require_project_resource(pid, "proposal", packet["proposalId"])
            if self.test_data or not self.production_authorized or project.get("archived"):
                fail("PRODUCTION_AUTHORIZATION", "当前项目不能恢复制作交付。", 403)
            if (job["status"] != "FAILED" or job.get("attemptId") != attempt["id"]
                    or attempt["status"] != "FAILED" or attempt["taskKind"] != "produce"
                    or attempt["ownerRef"] != {"kind": "job", "id": job["id"]}
                    or attempt.get("cancelRequested") or attempt.get("diagnosticRef") != "local:seal-diagnostics/" + attempt["id"]):
                fail("RECOVERY_NOT_ALLOWED", "只可恢复已确认停止、制作回合完成后的封存失败。")
            if (expected.get("publicationRevision") != project["publicationRevision"]
                    or packet["publicationRevision"] != project["publicationRevision"]
                    or proposal["status"] != "FROZEN" or proposal.get("packetId") != packet["id"]
                    or proposal["revision"] != packet["proposalRevision"]):
                fail("STALE_PACKET", "方案或发布基线已变化，不能恢复旧交付。")
            self._project_runner("verification-isolated-v1")
            self._complete_attempt(attempt, {"artifactRef": p["artifactRef"],
                "sourceCommit": p["artifactRef"]["sourceCommit"], "stopped": True})
            job = self._get("job", job["id"])
            job["sealRecovery"] = {"failedAttemptId": attempt["id"], "diagnosticRef": attempt["diagnosticRef"],
                "sourceCommit": p["artifactRef"]["sourceCommit"], "commandId": message["commandId"],
                "operatorId": operator, "recoveredAt": now(), "nativeRerun": False}
            self._put("job", job)
            return {"job": job}, {"kind": "job", "id": job["id"]}
        if t == "production.start":
            packet = self.require_project_resource(pid, "packet", p["packetId"])
            proposal = self.require_project_resource(pid, "proposal", packet["proposalId"])
            if proposal["status"] != "FROZEN" or proposal.get("packetId") != packet["id"] or proposal["revision"] != packet["proposalRevision"]:
                fail("STALE_PACKET", "冻结后的范围已修改，须重新审阅批准。")
            if self.test_data or not self.production_authorized:
                fail("PRODUCTION_AUTHORIZATION", "测试工作区的批准不能启动制作；请在独立正常工作区审阅并确认。", 403)
            self._check_producer_asset_inputs(packet)
            profile = self._resolve_profile(pid, "producer", expected, packet.get("assets", []))
            self._command_profile = profile
            try:
                job = self.create_job(operator_id=operator, packet_id=packet["id"], idempotency_key=message["commandId"])
            finally:
                self._command_profile = None
            return {"job": job}, {"kind": "job", "id": job["id"]}
        if t in {"execution.cancel", "execution.reconcile"}:
            attempt = self.require_project_resource(pid, "attempt", p["attemptId"])
            if attempt["ownerRef"] != p["ownerRef"]:
                fail("ATTEMPT_OWNER", "执行代次与业务归属不符。")
            if t.endswith("cancel"):
                if attempt["status"] in TERMINAL_ATTEMPTS:
                    job = self._get("job", attempt["ownerRef"]["id"]) if attempt["ownerRef"]["kind"] == "job" else None
                    if job and job.get("attemptId") != attempt["id"] and job["status"] == "VERIFYING":
                        attempt = self.require_project_resource(pid, "attempt", job["attemptId"])
                    else:
                        fail("EXECUTION_FINISHED", "执行已结束，请读取当前候选或已接受版本后操作。")
                never_started = attempt["status"] in {"QUEUED", "PREPARING"} and attempt.get("nativeIdentity") is None
                attempt.update(cancelRequested=True, stopReason="user_cancel")
                if never_started:
                    attempt["status"] = "STOPPED"
                    self._owner_state(attempt)
                elif attempt["status"] not in TERMINAL_ATTEMPTS:
                    attempt["status"] = "CANCEL_REQUESTED"
                self._put("attempt", attempt)
            else:
                self._expire_attempt(attempt)
                attempt["reconcileRequested"] = True
                self._put("attempt", attempt)
            return {"attempt": attempt}, {"kind": "attempt", "id": attempt["id"]}
        if t in {"candidate.accept", "candidate.reject"}:
            return self._candidate_decision(pid, p, expected, t.endswith("accept"))
        if t == "preview.start":
            return self._start_preview(pid, p)
        if t == "preview.stop":
            preview = self.require_project_resource(pid, "preview", p["previewId"])
            attempt = self._get("attempt", preview["attemptId"])
            if attempt["status"] not in TERMINAL_ATTEMPTS:
                attempt.update(cancelRequested=True, stopReason="user_cancel")
                if attempt["status"] in {"QUEUED", "PREPARING"} and not attempt.get("nativeIdentity"):
                    attempt["status"] = "STOPPED"
                    preview["status"] = "STOPPED"
                else:
                    if attempt["status"] not in {"UNKNOWN", "UNCERTAIN"}:
                        attempt["status"] = "CANCEL_REQUESTED"
                    preview["status"] = "STOP_REQUESTED"
                self._put("attempt", attempt)
            self._put("preview", preview)
            return {"preview": preview}, {"kind": "preview", "id": preview["id"]}
        fail("COMMAND_TYPE", "不支持的命令类型。", 400)

    def _check_producer_asset_inputs(self, plan):
        # Static producer tools can preserve approved binary source assets,
        # but currently cannot write or generate PNG/JPEG/WebP files.
        existing = dict(plan.get("sourceRefs") or {})
        if plan.get("assetBundle"):
            from .imagegen_assets import load_bundle, ImageAssetError
            try:
                ref, bound, _ = load_bundle(self.state_root, plan["assetBundle"]["bundleId"], expected=plan["assetBundle"])
                if bound["document"] != plan["document"] or bound["tasks"] != plan["tasks"] or bound["projectId"] != plan["projectId"]:
                    raise ImageAssetError("Image bundle intent differs from the current plan.")
                existing.update(ref["sourceRefs"])
            except (ImageAssetError, KeyError) as exc:
                fail("IMAGE_BUNDLE_INVALID", str(exc))
        document = plan.get("document") or {}
        missing = sorted({binding for obj in document.get("objects", [])
                          for binding in obj.get("sourceBindings", [])
                          if binding.startswith("assets/") and binding not in existing})
        if missing:
            fail("PRODUCTION_ASSETS_REQUIRED",
                 "当前制作工具只能写代码和文本资源；方案绑定的图片尚未进入工程："
                 + ", ".join(missing[:20])
                 + "。请使用 tools.studio_imagegen CLI 生成并导入素材包后审阅新修订；参考图上传不会自动成为绑定资源。")

    def image_bundle_image(self, project_id, bundle_id, index):
        from .imagegen_assets import load_bundle, ImageAssetError
        with self.lock:
            self._get("project", project_id)
            refs = [item.get("assetBundle") for kind in ("proposal", "packet")
                    for item in self._all_project(kind, project_id)]
            ref = next((item for item in refs if item and item.get("bundleId") == bundle_id), None)
            if ref is None:
                fail("IMAGE_BUNDLE_OWNER", "素材包不属于此项目。", 404)
            try:
                _, plan, images = load_bundle(self.state_root, bundle_id, expected=ref)
                if plan["projectId"] != project_id or index < 0 or index >= len(ref["paths"]):
                    raise ImageAssetError("Image bundle image index is invalid.")
                return images[ref["paths"][index]]
            except ImageAssetError as exc:
                fail("IMAGE_BUNDLE_INVALID", str(exc), 409)

    @staticmethod
    def _merge_feedback(old, new):
        merged = {f["feedbackId"]: copy.deepcopy(f) for f in old}
        for item in new:
            key = item["feedbackId"]
            if key in merged and merged[key] != item:
                fail("FEEDBACK_IMMUTABLE", "已审阅反馈原文不能覆盖；编辑须建立新的反馈编号。")
            merged[key] = copy.deepcopy(item)
        return list(merged.values())

    def _save_feedback(self, pid, proposal, items):
        for item in items:
            fid = "feedback:" + pid + ":" + item["feedbackId"]
            existing = next((r for r in self._all_project("feedback", pid) if r["id"] == fid), None)
            if existing and existing["input"] != item:
                fail("FEEDBACK_IMMUTABLE", "反馈编号已绑定另一份原文。")
            if not existing:
                self._put("feedback", {"id": fid, "projectId": pid, "feedbackId": item["feedbackId"], "input": item, "proposalId": proposal["id"], "publicationRevision": proposal["publicationRevision"], "experienceStatus": "unreviewed"})

    def _new_attempt(self, pid, task_kind, owner, runner_id, profile=None, input_refs=None, scope=None):
        if task_kind in {"plan", "visual-plan", "produce"}:
            self._check_session_admission(self._get("runner", runner_id))
        attempt = {"id": _core()[3]("attempt"), "projectId": pid, "taskKind": task_kind, "ownerRef": owner,
            "runnerId": runner_id, "status": "QUEUED", "createdAt": _core()[4](), "profileSnapshot": copy.deepcopy(profile),
            "inputRefs": input_refs or {}, "scope": scope or {}, "cancelRequested": False, "nativeIdentity": None}
        self._put("attempt", attempt)
        return attempt

    def _queue_planning(self, proposal, profile):
        proposal.update(protocolVersion=1, profileSnapshot=profile)
        attempt = self._new_attempt(proposal["projectId"], "plan", {"kind": "proposal", "id": proposal["id"], "revision": proposal["revision"]}, profile["runnerId"], profile,
            {"sourceAvailable": bool(proposal.get("baseCommit")), "sourceCommit": proposal.get("baseCommit"),
             "inspectionRef": "inspection:" + proposal["id"] + ":" + str(proposal["revision"]),
             "planningInputRef": "planning:" + proposal["id"] + ":" + str(proposal["revision"]), "assetRefs": [a["id"] for a in proposal.get("assets", [])]},
            {"mode": "inspection_only", "targetObjectIds": (proposal.get("changeRequest") or {}).get("targetObjectIds", []), "allowProjectExecution": False})
        proposal["attemptId"] = attempt["id"]
        self._put("proposal", proposal)

    def _queue_production(self, job, packet):
        profile = getattr(self, "_command_profile", None)
        if profile is None:
            fail("PROFILE_REQUIRED", "独立执行必须由类型化命令冻结本次设置。")
        # Persist the consumption decision before idempotent filesystem preparation.
        event = self.db.execute("SELECT payload,consumed FROM approvals WHERE id=?", (packet["approvalEventId"],)).fetchone()
        if event is None:
            fail("APPROVAL_MISSING", "制作批准记录不存在。")
        if not event[1]:
            self._consume(json.loads(event[0]))
        decision = {"id": "input-decision:" + job["id"], "projectId": job["projectId"], "jobId": job["id"], "packetId": packet["id"], "approvalEventId": packet["approvalEventId"], "reviewedPlanRef": packet.get("reviewedPlanRef"), "status": "APPROVED", "createdAt": _core()[4]()}
        self._put("input_decision", decision)
        attempt = self._new_attempt(job["projectId"], "produce", {"kind": "job", "id": job["id"]}, profile["runnerId"], profile,
            {"packetId": packet["id"], "baseCommit": packet.get("baseCommit"), "inputCommit": None, "inputArtifactRef": None, "gmConfirmationRef": None, "assetRefs": [a["id"] for a in packet.get("assets", [])]},
            {"mode": "private_workspace", "allowedFiles": ["project.godot", "scripts/**/*.gd", "scenes/**/*.tscn", "resources/**/*.tres", "assets/**/*.png", "assets/**/*.jpg", "assets/**/*.jpeg", "assets/**/*.webp"], "allowProjectExecution": False})
        attempt["status"] = "PREPARING"
        self._put("attempt", attempt)
        job.update(attemptId=attempt["id"], profileSnapshot=profile, executionBackend="runners", status="QUEUED", message="已批准并冻结本次制作设置；等待受信输入准备和执行器领取。")
        self._put("job", job)
        self._after_commit.append(lambda: self.prepare_runner_input(attempt["id"]))

    def prepare_runner_input(self, attempt_id):
        from .general_gm_integration import prepare_input, GMIntegrationError
        from .frontend_approval import ApprovalError
        try:
            with self.lock:
                attempt = self._get("attempt", attempt_id)
                if attempt["status"] != "PREPARING":
                    return
                job = self._get("job", attempt["ownerRef"]["id"])
                packet = self._get("packet", job["packetId"])
            prepared = prepare_input(self, packet, job)
            with self.transaction():
                current = self._get("attempt", attempt_id)
                if current["status"] != "PREPARING" or current["cancelRequested"]:
                    return
                current["inputRefs"].update({k: v for k, v in prepared.items() if k in {"inputCommit", "inputArtifactRef", "gmConfirmationRef"}})
                current.update(status="QUEUED", prepared=prepared)
                self._put("attempt", current)
                job = self._get("job", job["id"])
                job.update(inputCommit=prepared["inputCommit"], gmConfirmationRef=prepared["gmConfirmationRef"])
                self._put("job", job)
        except Exception as exc:
            with self.transaction():
                attempt = self._get("attempt", attempt_id)
                attempt["preparationError"] = str(exc)[:500]
                if attempt["status"] == "PREPARING" and isinstance(exc, (ApprovalError, GMIntegrationError)):
                    attempt["status"] = "FAILED"
                    self._owner_state(attempt, failed=True)
                    job = self._get("job", attempt["ownerRef"]["id"])
                    job["message"] = "受信输入准备失败，制作尚未启动：" + attempt["preparationError"]
                    self._put("job", job)
                self._put("attempt", attempt)

    def register_runner(self, body):
        allowed = {"runnerId", "runnerKind", "environment", "nativeVersion", "capabilities", "sandboxEvidence"}
        self._control_fields(body, allowed, allowed)
        supported = {"agent": {"planning-readonly-v1", "production-private-v1"},
                     "project": {"verification-isolated-v1", "preview-isolated-v1"}}
        if body["runnerKind"] not in supported or not isinstance(body["capabilities"], list):
            fail("RUNNER_REGISTRATION", "执行器类型或能力无效。", 400)
        capabilities = body["capabilities"]
        if any(not isinstance(c, str) or c not in supported[body["runnerKind"]] for c in capabilities) or len(set(capabilities)) != len(capabilities):
            fail("RUNNER_REGISTRATION", "执行器能力不属于其角色或存在重复。", 400)
        evidence = body["sandboxEvidence"]
        from .role_evidence import verified_roles
        observed_capabilities = verified_roles(evidence, body["runnerId"], body["runnerKind"])
        if capabilities and set(capabilities) != set(observed_capabilities):
            fail("ISOLATION_UNVERIFIED", "执行能力需要本角色 deny-default 权限和真实进程拒绝证据；基础探针不能放行。", 423)
        with self.transaction():
            old = next((r for r in self._all("runner") if r["id"] == body["runnerId"]), {})
            runner = {**old, **body, "id": body["runnerId"], "lastHeartbeat": time.time(), "lastHeartbeatAt": _core()[4]()}
            self._put("runner", runner)
            return {"storeId": self.store_id, "runnerId": runner["id"], "registered": True}

    @staticmethod
    def _control_fields(body, allowed, required):
        if not isinstance(body, dict) or set(body)-allowed or required-set(body):
            fail("CONTROL_FIELDS", "执行器控制消息字段不符合契约。", 400)
        for k in {"runnerId", "attemptId", "commandId", "reportId", "storeId"} & set(body):
            if not isinstance(body[k], str) or not 1 <= len(body[k]) <= 160 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in body[k]):
                fail("CONTROL_IDENTITY", "执行器消息身份无效。", 400)

    def update_runner_catalog(self, body):
        self._control_fields(body, {"runnerId", "catalogRevision", "observedAt", "models"}, {"runnerId", "catalogRevision", "observedAt", "models"})
        self._revision(body["catalogRevision"])
        if not isinstance(body["models"], list) or len(body["models"]) > 200:
            fail("CATALOG", "模型目录需要有界列表。", 400)
        for model in body["models"]:
            required = {"modelKey", "modelProvider", "supportedReasoningEfforts", "inputModalities"}
            if not isinstance(model, dict) or not required <= set(model) or set(model)-required-{"isDefault", "defaultReasoningEffort", "displayName", "modelProviderSource"}:
                fail("CATALOG", "模型目录字段无效。", 400)
            if not isinstance(model["modelKey"], str) or (model["modelProvider"] is not None and not isinstance(model["modelProvider"], str)) or not isinstance(model["supportedReasoningEfforts"], list) or not isinstance(model["inputModalities"], list):
                fail("CATALOG", "模型目录类型无效。", 400)
        with self.transaction():
            runner = self._get("runner", body["runnerId"])
            old = runner.get("catalog")
            content = {k: v for k, v in body.items() if k != "runnerId"}
            if old and body["catalogRevision"] <= old["catalogRevision"]:
                # A new native model/list observation may refresh the same
                # catalog revision. Its observation time is not catalog content.
                if body["catalogRevision"] < old["catalogRevision"] or (
                    {k: v for k, v in old.items() if k not in {"receivedAt", "observedAt"}}
                    != {k: v for k, v in content.items() if k != "observedAt"}
                ):
                    fail("CATALOG_REVISION", "目录修订不能倒退或覆盖另一份目录。")
            runner["catalog"] = {**content, "receivedAt": time.time()}
            self._put("runner", runner)
            return {"storeId": self.store_id, "catalogRevision": body["catalogRevision"], "recorded": True}

    def _expire_attempt(self, attempt):
        lease = attempt.get("lease")
        if lease and attempt["status"] not in TERMINAL_ATTEMPTS | {"UNKNOWN", "UNCERTAIN"} and instant() > datetime.fromisoformat(lease["expiresAt"]):
            attempt["status"] = "UNKNOWN"
            self._put("attempt", attempt)
            self._owner_state(attempt, uncertain=True)

    def claim_runner(self, body):
        self._control_fields(body, {"runnerId", "commandId", "storeId"}, {"runnerId", "commandId", "storeId"})
        if body["storeId"] != self.store_id:
            fail("STORE_CHANGED", "数据空间变化，必须核查原执行日志。")
        _, canonical, _, _, _ = _core()
        with self.transaction():
            runner = self._get("runner", body["runnerId"])
            old = self.db.execute("SELECT content,receipt FROM claims WHERE runner_id=? AND command_id=?", (runner["id"], body["commandId"])).fetchone()
            if old:
                if old[0] != canonical(body):
                    fail("CLAIM_CONFLICT", "领取编号已绑定另一意图。")
                return json.loads(old[1])
            pending = self._pending_runner_attempts(runner["id"])
            for attempt in pending:
                self._expire_attempt(attempt)
            queued = [a for a in pending if a["status"] == "QUEUED"]
            # One process owner at a time; unknown execution keeps the slot.
            occupied = any(a["status"] in {"LEASED", "RUNNING", "UNKNOWN", "UNCERTAIN", "CANCEL_REQUESTED"} for a in pending)
            cooling = (runner.get("sessionRetryGate") or {}).get("notBefore", 0) > time.time()
            attempt = queued[-1] if queued and not occupied and not cooling else None
            request = None
            if attempt:
                required_capability = {"plan": "planning-readonly-v1", "visual-plan": "planning-readonly-v1", "produce": "production-private-v1", "verify": "verification-isolated-v1", "preview": "preview-isolated-v1"}[attempt["taskKind"]]
                if required_capability not in runner.get("capabilities", []):
                    fail("ISOLATION_UNAVAILABLE", "领取所需的进程隔离能力不可用。", 423)
                profile = attempt.get("profileSnapshot")
                if profile:
                    catalog = runner.get("catalog") or {}
                    if catalog.get("catalogRevision") != profile["catalogRevision"] or runner.get("nativeVersion") != profile["nativeVersion"] or runner.get("environment") != profile["environment"]:
                        fail("PROFILE_CONFLICT", "领取前目录/环境变化；保留原配置，不重新选模型。")
                attempt.update(status="LEASED", lease={"expiresAt": (instant()+timedelta(seconds=30)).isoformat()})
                self._put("attempt", attempt)
                request = {"schemaVersion": "studio.execution.v1", "storeId": self.store_id, "projectId": attempt["projectId"], "taskKind": attempt["taskKind"], "ownerRef": attempt["ownerRef"], "attemptId": attempt["id"], "runnerId": runner["id"], "lease": attempt["lease"], "inputRefs": attempt["inputRefs"], "scope": attempt["scope"]}
                if profile:
                    request["profileSnapshot"] = profile
            receipt = {"storeId": self.store_id, "runnerId": runner["id"], "commandId": body["commandId"], "request": request}
            self.db.execute("INSERT INTO claims VALUES(?,?,?,?)", (runner["id"], body["commandId"], canonical(body), canonical(receipt)))
            return receipt

    def heartbeat_runner(self, body):
        self._control_fields(body, {"runnerId", "storeId", "attemptId", "nativeIdentity", "observedAt"}, {"runnerId", "storeId"})
        if body["storeId"] != self.store_id:
            fail("STORE_CHANGED", "数据空间已变化。")
        with self.transaction():
            runner = self._get("runner", body["runnerId"])
            runner.update(lastHeartbeat=time.time(), lastHeartbeatAt=_core()[4]())
            self._put("runner", runner)
            if not body.get("attemptId"):
                return {"storeId": self.store_id, "cancelRequested": False}
            attempt = self._runner_attempt(body["runnerId"], body["attemptId"])
            self._expire_attempt(attempt)
            if attempt["status"] in {"UNKNOWN", "UNCERTAIN"}:
                return {"storeId": self.store_id, "reconcileRequired": True, "cancelRequested": True, "lease": attempt.get("lease")}
            if attempt["status"] not in TERMINAL_ATTEMPTS:
                attempt["lease"] = {"expiresAt": (instant()+timedelta(seconds=30)).isoformat()}
                self._put("attempt", attempt)
            return {"storeId": self.store_id, "cancelRequested": attempt["cancelRequested"], "reconcileRequired": attempt.get("reconcileRequested", False), "lease": attempt.get("lease")}

    def _runner_attempt(self, runner_id, attempt_id):
        attempt = self._get("attempt", attempt_id)
        if attempt["runnerId"] != runner_id:
            fail("ATTEMPT_RUNNER", "执行代次不属于当前执行器。", 403)
        return attempt

    def runner_input(self, runner_id, attempt_id):
        from .object_protocol import planner_instructions
        with self.lock:
            attempt = self._runner_attempt(runner_id, attempt_id)
            if attempt["status"] not in {"LEASED", "RUNNING"}:
                fail("INPUT_LEASE", "材料只可在有效领取后读取。")
            owner, kind = attempt["ownerRef"], attempt["taskKind"]
            if kind == "visual-plan":
                material = self._visual_plan_input(attempt)
            elif kind == "plan":
                proposal = self.require_project_resource(attempt["projectId"], "proposal", owner["id"])
                # Deterministic bounded static inspection; never execute a project script.
                snippets, omitted, total = [], [], 0
                repo = self.state_root / "projects" / proposal["projectId"]
                if proposal.get("baseCommit"):
                    names = _core()[2](repo, "ls-tree", "-r", "--name-only", proposal["baseCommit"]).splitlines()
                    relevant = set((proposal.get("changeRequest") or {}).get("targetObjectIds", []))
                    doc = proposal.get("currentDocument") or {}
                    bound = {b for o in doc.get("objects", []) if not relevant or o["id"] in relevant for b in o.get("sourceBindings", []) if isinstance(b, str)}
                    for name in names:
                        if name not in bound or not name.endswith((".gd", ".tscn", ".tres", ".json", ".godot")):
                            continue
                        data = _core()[2](repo, "show", proposal["baseCommit"] + ":" + name)
                        if len(snippets) >= 12 or total+len(data) > 50000:
                            omitted.append(name)
                            continue
                        snippets.append({"path": name, "content": data}); total += len(data)
                asset_instruction = ("\nThe managed producer writes only UTF-8 project settings, GDScript, scenes and text resources. "
                    "New raster art is produced separately by the trusted operator ImageGen CLI prompt-to-image tool, "
                    "then imported as a plan-bound bundle before freeze. You may bind required new PNGs under assets/ "
                    "in a READY plan; describe exact art subjects, layouts and action counts in the asset objects. "
                    "Do not generate images or invoke the CLI yourself. Uploaded images remain references. "
                    "Do not silently replace requested art with procedural visuals. Image generation does not establish runtime correctness.")
                available_rasters = [name for name in names if name.startswith("assets/")] if proposal.get("baseCommit") else []
                repair = self.repair_context(proposal["projectId"])
                if not repair or any(repair.get(key) != value for key, value in (proposal.get("repairBase") or {}).items()) or not proposal.get("repairBase"):
                    repair = None
                repair_packet = self._get("packet", self._get("job", repair["jobId"])["packetId"]) if repair else {}
                material = {"packet": {"operationKind": "PLANNING", "allowedFiles": [], "instruction": planner_instructions(expected_feedback=True, initial_build=not proposal.get("baseCommit"))+asset_instruction+"\nApply every workbench operation in changeRequest.operations exactly; do not treat this list as advisory prose. Materialize every new-scene and new-instance with its declared stable ID, name, scene/definition, requested position, bounds, size, anchor and lock. A new-instance lock omitted by the request means free. Include each added scene or instance ID in at least one READY task. For a new-scene, honor its selected blank/minimal template and preserve any connections instruction verbatim in that scene's description; do not add unrequested transitions. Only an explicit set-lock operation authorizes changing an existing instance lock; honor its before/lock exactly and preserve every other protected property.\nReturn strict JSON as final answer. Static inspection only. Do not execute project scripts or use Ptah. Every feedbackId must have an explicit decision.",
                    "productionCapabilities": {"newRasterImages": "operator-cli-before-freeze", "availableRasterPaths": available_rasters},
                    "imageMaterials": self.visual_planning_context(proposal["projectId"], proposal["id"])["imageMaterials"],
                    "concept": proposal["text"], "visualReferences": proposal.get("visualReferences", []), "referenceAssets": proposal.get("assets", []), "discussion": proposal["discussion"][-12:], "currentDocument": proposal.get("currentDocument"), "previousDocument": proposal.get("document"), "changeRequest": proposal.get("changeRequest"), "feedback": proposal.get("feedback", []),
                    "repairDiagnostics": copy.deepcopy((repair or {}).get("verification")),
                    "approvedUserDiscussion": copy.deepcopy((repair_packet.get("approvedProposal") or {}).get("discussion", repair_packet.get("userDiscussion", []))),
                    "inspection": {"sourceAvailable": bool(proposal.get("baseCommit")), "sourceCommit": proposal.get("baseCommit"), "snippets": snippets, "omitted": omitted, "runtimeCoverage": "unknown"}}}
            else:
                job = self._get("job", owner["id"]) if kind in {"produce", "verify"} else None
                packet = self._get("packet", job["packetId"]) if job else None
                material = {"packet": public(packet) if packet else None, "prepared": attempt.get("prepared"), "artifactRef": attempt["inputRefs"].get("artifactRef"), "document": packet.get("document") if packet else None}
                if kind == "produce":
                    material["packet"].update(allowedFiles=attempt["scope"]["allowedFiles"],
                        instruction="Implement the approved Godot 4 GDScript 2D document and tasks. Read GDD.md, PLAN.md, STRUCTURE.md and design/game.json. "
                        "Use protected StudioRuntime.object_value() for editable parameters. Preserve stable object IDs, source bindings and behavior outside approved scope. "
                        "Protocol object/field IDs may contain hyphens; preserve those IDs as dictionary keys. They are not valid Godot property or metadata identifiers. Do not write metadata/body-size or similar invalid keys in .tres/.tscn; use valid Godot identifiers and explicit mapping to the unchanged protocol IDs. "
                        "Use explicit types or casts for Array/Dictionary lookup results; Godot cannot infer a static type from Variant-valued expressions. Actually edit the allowed project.godot/scripts/scenes/resources text paths. Image assets must already exist in the approved input; the static tool cannot write images. Every changed or added file needs an approved source binding. "
                        "Do not modify design/, studio/, documentation, tests, .godotmaker/, .gitignore or Git history. Do not run game scripts, Godot, tests, checksums, "
                        "exports, dependency installation, network services or Ptah skills. Independent technical verification follows after your process stops. "
                        "Use procedural visuals or provided art. Implement failure/reset/feedback described in the frozen plan.")
                    if packet.get("dataOnlyUpdate"):
                        material["packet"]["instruction"] += " This is a field-only update already applied to design/game.json; correct runtime-driven source may require no source edit."
            assets = []
            for aid in attempt["inputRefs"].get("assetRefs", []):
                ref = self.require_project_asset(attempt["projectId"], aid)
                path, mime = self.project_asset_file(attempt["projectId"], ref)
                assets.append({"name": path.name, "mimeType": mime, "dataBase64": base64.b64encode(path.read_bytes()).decode()})
            material["assets"] = assets
            material.update(storeId=self.store_id, projectId=attempt["projectId"], attemptId=attempt_id)
            return material

    def report_lookup(self, runner_id, report_id):
        with self.lock:
            row = self.db.execute("SELECT ack FROM reports WHERE runner_id=? AND report_id=?", (runner_id, report_id)).fetchone()
            return {"known": bool(row), "ack": json.loads(row[0]) if row else None, "storeId": self.store_id}

    def report_runner(self, body):
        from .object_protocol import validate_execution_report
        # Planner JSON is untrusted model output, not a receipt-envelope fact.
        # Parse it inside _complete_attempt's savepoint, after identity checks,
        # so a rejected result still gets a durable ACK and cannot jam outbox replay.
        body = validate_execution_report(body, validate_planner_result=False)
        _, canonical, _, _, _ = _core()
        with self.transaction():
            if body["storeId"] != self.store_id:
                fail("STORE_CHANGED", "报告来自不同数据空间。")
            row = self.db.execute("SELECT content,ack FROM reports WHERE runner_id=? AND report_id=?", (body["runnerId"], body["reportId"])).fetchone()
            if row:
                if row[0] != canonical(body):
                    fail("REPORT_CONFLICT", "报告编号已绑定另一份事实。")
                return json.loads(row[1])
            attempt = self._runner_attempt(body["runnerId"], body["attemptId"])
            if body["projectId"] != attempt["projectId"]:
                fail("REPORT_PROJECT", "报告项目身份不符。", 403)
            if body["taskKind"] != attempt["taskKind"]:
                fail("REPORT_TASK", "报告任务类型与分配代次不符。", 403)
            self._expire_attempt(attempt)
            disposition = "recorded"
            payload, typ = body["payload"], body["type"]
            launch_prevented = typ == "failed" and payload.get("launchPrevented") is True
            if launch_prevented and attempt.get("nativeIdentity"):
                fail("LAUNCH_STATE", "已有原生启动身份，不能认领为启动前失败。")
            if attempt["status"] in {"UNKNOWN", "UNCERTAIN", "QUEUED", "PREPARING"} or (attempt["status"] in TERMINAL_ATTEMPTS and typ != "usage"):
                disposition = "evidence_only"
            # A trusted Agent can report that input preparation prevented any
            # child launch, even after its lease expired. This releases only
            # that failed attempt; it never authorizes a replay or completion.
            if launch_prevented and attempt["status"] in {"UNKNOWN", "UNCERTAIN"}:
                disposition = "recorded"
            if typ == "started" and attempt["status"] in {"UNKNOWN", "UNCERTAIN"}:
                # A start fact can arrive after a backend outage, before its
                # first ACK. Retain the original identity for reconciliation
                # without restoring the expired lease or advancing the owner.
                old_identity = attempt.get("nativeIdentity") or {}
                if any(value is not None and payload["nativeIdentity"].get(key) != value
                       for key, value in old_identity.items()):
                    fail("NATIVE_IDENTITY", "原生身份变化，禁止第二次启动。")
                attempt["nativeIdentity"] = {**old_identity, **payload["nativeIdentity"]}
                attempt["startedAt"] = attempt.get("startedAt") or payload["startedAt"]
            if typ == "usage":
                old = attempt.get("usage") or {}
                total, at = payload.get("totalTokens"), payload.get("observedAt")
                if total is not None and (old.get("observedAt") is None or at > old["observedAt"]):
                    if old.get("totalTokens") is not None and total < old["totalTokens"]:
                        disposition = "evidence_only"
                    else:
                        attempt["usage"] = {"totalTokens": total, "observedAt": at, "coverage": payload.get("coverage", "incomplete")}
            elif disposition == "recorded":
                if typ == "started":
                    old_identity = attempt.get("nativeIdentity") or {}
                    new_identity = payload["nativeIdentity"]
                    if any(value is not None and new_identity.get(key) != value
                           for key, value in old_identity.items()):
                        fail("NATIVE_IDENTITY", "原生身份变化，禁止第二次启动。")
                    # The process is recorded before initialize/thread/start.
                    # Later observations may add thread/turn IDs, never replace
                    # a previously observed identity or the original start time.
                    attempt.update(status="CANCEL_REQUESTED" if attempt["cancelRequested"] else "RUNNING",
                        nativeIdentity={**old_identity, **new_identity},
                        startedAt=attempt.get("startedAt") or payload["startedAt"])
                    if attempt["taskKind"] == "preview":
                        preview = self._get("preview", attempt["ownerRef"]["id"])
                        preview["status"] = "STOP_REQUESTED" if attempt["cancelRequested"] else "RUNNING"
                        self._put("preview", preview)
                    elif attempt["taskKind"] == "produce":
                        job = self._get("job", attempt["ownerRef"]["id"])
                        # Only the current authorized producer can advance its
                        # queued job. A late start must not undo cancellation,
                        # verification, a candidate decision, or a newer attempt.
                        if (job.get("attemptId") == attempt["id"]
                                and not attempt["cancelRequested"]
                                and job["status"] in {"QUEUED", "DISPATCHING", "RUNNING"}):
                            job.update(status="RUNNING", message="制作 session 已启动，正在隔离工程中实现冻结方案。")
                            self._put("job", job)
                    for key in ("threadStartReported", "turnStartAcknowledged", "actualProfile"):
                        if payload.get(key) is not None:
                            attempt[key] = payload[key]
                elif typ == "activity":
                    attempt["lastActivity"] = payload
                elif typ in {"failed", "stopped"}:
                    confirmed = payload.get("stopped") is True
                    attempt.update(status=("FAILED" if typ == "failed" else "STOPPED") if confirmed else "UNCERTAIN", stopReason=payload.get("stopReason"), diagnosticRef=payload.get("diagnosticRef"))
                    if "nativeFailure" in payload:
                        attempt["nativeFailure"] = copy.deepcopy(payload["nativeFailure"])
                    if launch_prevented:
                        attempt["launchPrevented"] = True
                    self._record_session_terminal(attempt)
                    self._owner_state(attempt, uncertain=not confirmed, failed=typ == "failed")
                elif typ == "completed":
                    if not attempt.get("nativeIdentity"):
                        disposition = "evidence_only"
                    elif payload.get("stopped") is not True or attempt["cancelRequested"]:
                        disposition = "evidence_only"
                        attempt["status"] = "STOPPED" if payload.get("stopped") is True else "UNCERTAIN"
                        self._owner_state(attempt, uncertain=payload.get("stopped") is not True)
                    else:
                        # Apply result in a savepoint; invalid output cannot lose its receipt.
                        try:
                            with self.transaction():
                                self._complete_attempt(attempt, payload)
                            attempt["status"] = "COMPLETED"
                            self._record_session_terminal(attempt)
                        except Exception as exc:
                            disposition = "rejected"
                            attempt.update(status="FAILED", resultError=str(exc)[:500])
                            self._record_session_terminal(attempt)
                            self._owner_state(attempt, uncertain=False, failed=True)
            self._put("attempt", attempt)
            ack = {"schemaVersion": "studio.message.v1", "kind": "report_ack", "storeId": self.store_id, "projectId": attempt["projectId"], "attemptId": attempt["id"], "runnerId": body["runnerId"], "reportId": body["reportId"], "disposition": disposition}
            if disposition != "recorded":
                ack["reason"] = attempt.get("resultError") or "当前执行授权不允许此事实推进业务；保留证据供核账。"
            self.db.execute("INSERT INTO reports VALUES(?,?,?,?)", (body["runnerId"], body["reportId"], canonical(body), canonical(ack)))
            return ack

    def _owner_state(self, attempt, uncertain=False, failed=False):
        owner = attempt["ownerRef"]
        if owner["kind"] == "visual-plan":
            self._visual_plan_owner_state(attempt, uncertain=uncertain, failed=failed)
        elif owner["kind"] == "proposal":
            p = self._get("proposal", owner["id"])
            if p["revision"] != owner["revision"]:
                return
            reason = attempt.get("stopReason")
            automatic_stop = reason in {"time_limit", "soft_budget", "native_error"}
            p.update(status="PLANNING_UNCERTAIN" if uncertain else "FAILED" if failed or automatic_stop else "CANCELLED",
                planningTerminationConfirmed=not uncertain, updatedAt=_core()[4]())
            if uncertain or failed or automatic_stop:
                native = attempt.get("nativeFailure") or {}
                code, message = ({
                    "time_limit": ("PLANNER_TIMEOUT", "策划达到本次时间上限，已确认停止；可保留原输入重试或先调整角色时限。"),
                    "soft_budget": ("PLANNER_BUDGET", "策划达到本次用量上限，已确认停止；可保留原输入重试或先调整角色预算。"),
                }.get(reason, ("PLANNER_FAILED", "策划执行失败，已确认停止；可保留原输入重试。")))
                if failed and attempt.get("resultError"):
                    code = "PLANNER_RESPONSE_INVALID"
                    message = "策划结果未通过方案检查，已保存拒收记录并确认停止；可保留原输入重试。"
                p["planningFailure"] = {"code": "PLANNER_UNCERTAIN" if uncertain else code,
                    "message": "策划停止尚未确认，请先对账。" if uncertain else message,
                    "nativeStatus": native.get("nativeStatus"), "elapsedSeconds": native.get("elapsedSeconds"), "sessionId": None,
                    "terminationConfirmed": not uncertain, "retryable": not uncertain, "clarificationAvailable": False}
            if failed and attempt.get("launchPrevented") is True:
                p["planningFailure"] = {"code": "PLANNER_SETUP",
                    "message": ("策划沙箱自检未通过，已确认模型未启动；失败详情已保留。"
                                if str(attempt.get("diagnosticRef", "")).startswith("local:sandbox-probe/")
                                else "策划启动准备失败，已确认模型未启动；可用原输入重试。"),
                    "nativeStatus": None, "elapsedSeconds": None, "sessionId": None,
                    "terminationConfirmed": True, "retryable": True, "clarificationAvailable": False}
            if p.get("planningFailure"):
                p["planningFailure"]["diagnosticRef"] = attempt.get("diagnosticRef")
                p["planningFailure"]["retryNotBefore"] = attempt.get("retryNotBefore")
            self._put("proposal", p)
        elif owner["kind"] == "job":
            job = self._get("job", owner["id"])
            message = ("执行状态待核实，继续保留占用。" if uncertain else
                       "执行失败且已确认停止，没有产生可接受候选。" if failed else
                       "执行已停止，没有产生可接受候选。")
            job.update(status="UNCERTAIN" if uncertain else "FAILED" if failed else "CANCELLED", message=message)
            # Only a producer failure describes an incomplete native maker
            # session. Verification failures remain ordinary job failures.
            if attempt.get("taskKind") == "produce":
                job["productionFailure"] = self._producer_failure(attempt, uncertain=uncertain, failed=failed)
            elif attempt.get("taskKind") == "verify":
                job["verificationFailure"] = {"code": "VERIFICATION_UNCERTAIN" if uncertain else "VERIFICATION_EXECUTION_FAILED",
                    "message": "独立验证停止待核实，请先对账。" if uncertain else "制作交付已封存，但独立验证执行未完成；尚无可试玩候选。",
                    "terminationConfirmed": not uncertain, "stopReason": attempt.get("stopReason")}
                job["message"] = job["verificationFailure"]["message"]
            self._put("job", job)
        elif owner["kind"] == "preview":
            preview = self._get("preview", owner["id"])
            preview["status"] = "UNKNOWN" if uncertain else "STOPPED"
            self._put("preview", preview)

    @staticmethod
    def _producer_failure(attempt, *, uncertain=False, failed=False):
        sealing = (failed and not uncertain and attempt.get("diagnosticRef")
                   == "local:seal-diagnostics/" + attempt["id"])
        native = attempt.get("nativeFailure") or {}
        causes = {"stream_interrupted": "原生响应连接中断", "network_error": "原生服务连接失败", "timeout": "原生服务响应超时", "rate_limit": "原生服务报告请求限额", "authentication": "原生服务报告认证失败", "context_limit": "原生服务报告上下文已达上限", "provider_rejected": "原生服务拒绝请求", "model_unavailable": "原生服务报告模型不可用", "cancelled": "原生回合被中断", "output_error": "原生输出未通过读取检查"}
        cause = causes.get(native.get("reason"))
        reason = attempt.get("stopReason")
        limited = reason in {"time_limit", "soft_budget"} and not uncertain
        return {
            "code": "PRODUCTION_UNCERTAIN" if uncertain else "PRODUCTION_SEAL_FAILED" if sealing else "PRODUCTION_TIMEOUT" if limited and reason == "time_limit" else "PRODUCTION_BUDGET" if limited else "PRODUCTION_FAILED" if failed else "PRODUCTION_STOPPED",
            "message": ("制作停止尚未确认；请先向服务对账。" if uncertain else
                        "制作回合已完成，但交付物未通过封存检查；尚未进入独立验证，没有可发布候选。" if sealing else
                        "制作达到本次时间上限，已确认停止；尚未进入独立验证。可保留已确认要求，重新策划。" if limited and reason == "time_limit" else
                        "制作达到本次用量上限，已确认停止；尚未进入独立验证。可保留已确认要求，重新策划。" if limited else
                        (f"{cause}；制作未完成，尚未进入独立验证，没有可发布候选。" if cause else "制作 session 未完成，后端验证尚未开始，没有可发布候选。") if failed else
                        "制作已停止，后端验证尚未开始，没有可发布候选。"),
            "nativeStatus": "completed" if sealing else native.get("nativeStatus"),
            "stopReason": reason,
            "elapsedSeconds": native.get("elapsedSeconds"),
            "connectionInterrupted": native.get("connectionInterrupted") is True,
            "diagnosticRef": attempt.get("diagnosticRef"),
            "terminationConfirmed": not uncertain,
            "effectsMayHaveOccurred": uncertain or (attempt.get("launchPrevented") is not True and bool(attempt.get("nativeIdentity"))),
            "nextAction": "RECONCILE" if uncertain else "NEW_PLANNING",
        }

    def reconcile_runner(self, body):
        self._control_fields(body, {"runnerId", "storeId", "attemptId", "nativeIdentity", "stopped"}, {"runnerId", "storeId", "attemptId", "nativeIdentity", "stopped"})
        if body["storeId"] != self.store_id or type(body["stopped"]) is not bool:
            fail("RECONCILE_IDENTITY", "核账身份或停止事实无效。")
        with self.transaction():
            attempt = self._runner_attempt(body["runnerId"], body["attemptId"])
            if not attempt.get("nativeIdentity") or attempt["nativeIdentity"] != body["nativeIdentity"]:
                fail("RECONCILE_NATIVE", "不能核实原生身份，保留占用。")
            if attempt["status"] in TERMINAL_ATTEMPTS:
                # A delayed reconciliation is an observation of the original
                # process, never authority to revoke its completed result,
                # current verification or already accepted snapshot.
                return {"storeId": self.store_id, "attemptId": attempt["id"],
                        "status": attempt["status"], "lease": attempt.get("lease")}
            if body["stopped"]:
                attempt["status"] = "STOPPED"
                self._owner_state(attempt)
            elif attempt["status"] in {"UNKNOWN", "UNCERTAIN"}:
                attempt.update(status="CANCEL_REQUESTED" if attempt["cancelRequested"] else "RUNNING", lease={"expiresAt": (instant()+timedelta(seconds=30)).isoformat()})
            self._put("attempt", attempt)
            return {"storeId": self.store_id, "attemptId": attempt["id"], "status": attempt["status"], "lease": attempt.get("lease")}

    def _project_runner(self, capability, require_online=True):
        runner = next((r for r in self._all("runner") if r.get("runnerKind") == "project" and capability in r.get("capabilities", []) and (not require_online or time.time()-r.get("lastHeartbeat", 0)<=30)), None)
        if not runner:
            fail("PROJECT_RUNNER_UNAVAILABLE", "独立项目执行器或已验证隔离能力不可用。", 423)
        return runner

    def _artifact_repository(self, ref, *, project_id, job_id=None, packet_id=None):
        if not isinstance(ref, dict) or not isinstance(ref.get("artifactId"), str):
            fail("ARTIFACT_REF", "封存工件引用无效。")
        self._control_fields({"attemptId": ref["artifactId"]}, {"attemptId"}, {"attemptId"})
        if ref.get("projectId") != project_id or (job_id and ref.get("jobId") != job_id) or (packet_id and ref.get("packetId") != packet_id):
            fail("ARTIFACT_OWNER", "交付物的项目/作业/表单绑定不符。")
        root = self.state_root / "artifacts"
        folder = root / ref["artifactId"]
        repo = folder / "repository"
        if any(p.is_symlink() for p in (root, folder, repo)) or not (repo / ".git").is_dir() or (repo / ".git").is_symlink():
            fail("ARTIFACT_MISSING", "精确交付物尚未封存或不是独立仓库。")
        if (repo / ".git" / "objects" / "info" / "alternates").exists():
            fail("ARTIFACT_SHARED_OBJECTS", "封存交付不能借用另一仓库的对象库。")
        for entry in repo.rglob("*"):
            if entry.is_symlink():
                fail("ARTIFACT_LINK", "工件包含符号链接。")
        git = _core()[2]
        if git(repo, "rev-parse", "HEAD") != ref.get("sourceCommit") or git(repo, "status", "--porcelain"):
            fail("ARTIFACT_DRIFT", "封存源版本已变化。")
        return repo

    def _revalidate_job_approval(self, job, packet):
        record = self.db.execute("SELECT payload,consumed FROM approvals WHERE id=?", (packet["approvalEventId"],)).fetchone()
        if record is None or not record[1]:
            fail("APPROVAL_MISSING", "受信后端没有已消费的制作批准。")
        approval = json.loads(record[0])
        if any(approval.get(key) != value for key, value in {"projectId": job["projectId"], "jobId": job["id"], "packetId": packet["id"], "proposalId": packet["proposalId"]}.items()):
            fail("APPROVAL_BINDING", "持久批准不属于精确制作任务。")
        if approval.get("gitSpecRef") != packet.get("gmSpecRef") or approval.get("revision") != str(packet["proposalRevision"]) or approval.get("phase") != "specification" or approval.get("action") != "approve":
            fail("APPROVAL_SCOPE", "持久批准的精确规格/修订或决定不符。")
        decision = self._get("input_decision", "input-decision:" + job["id"])
        if decision["approvalEventId"] != packet["approvalEventId"] or decision["reviewedPlanRef"] != packet.get("reviewedPlanRef"):
            fail("INPUT_DECISION", "准备输入决定与批准或完整审阅不符。")
        return approval

    def _complete_attempt(self, attempt, payload):
        from .generic_workflow import SPEC_FILES
        from .object_protocol import parse_planner_response, catalog_from_document
        _, _, git, identifier, now = _core()
        pid, owner, kind = attempt["projectId"], attempt["ownerRef"], attempt["taskKind"]
        if kind == "visual-plan":
            self._complete_visual_plan(attempt, payload)
            return
        if kind == "plan":
            proposal = self.require_project_resource(pid, "proposal", owner["id"])
            if proposal["revision"] != owner["revision"] or proposal["status"] not in {"PLANNING", "PLANNING_CANCELLING", "PLANNING_UNCERTAIN"}:
                fail("STALE_PLAN_REPORT", "策划结果不属于当前讨论修订。")
            native = payload["result"]
            response = native["response"] if isinstance(native, dict) and set(native) == {"response"} else native
            response = parse_planner_response(response, expected_feedback=proposal.get("feedback", []),
                current_document=proposal.get("currentDocument"), previous_document=proposal.get("document"),
                initial_build=not proposal.get("baseCommit"))
            has_visual_plan = "visualPlan" in response
            visual_plan = response.pop("visualPlan", None)
            document = response.get("document")
            refs = {}
            if response["status"] == "READY":
                self._check_requested_fields(document, proposal.get("changeRequest"), proposal.get("currentDocument"), response["tasks"])
                refs = self._prepare_generic_spec(proposal, document, response["tasks"])
            proposal.update(response, **refs, planningTerminationConfirmed=True,
                scope="仅在受控 Godot 2D 源码范围内落实完整对象计划。", requirements=document["requirements"] if document else [],
                roles=["read-only planner", "game producer", "independent technical verifier", "user reviewer"],
                acceptance=["独立导入和运行冒烟通过", "对象、源绑定及冻结属性一致", "人工体验计划中的玩法与视觉要求"],
                objectChanges=self._object_changes(proposal.get("currentDocument"), document), updatedAt=now())
            proposal["discussion"].append({"role": "planner", "revision": proposal["revision"], "summary": response["summary"], "questions": response["questions"], "at": now()})
            self._put("proposal", proposal)
            self._reviewed_plan(proposal)
            if has_visual_plan:
                self._store_inline_visual_plan(proposal, visual_plan)
            for feedback in self._all_project("feedback", pid):
                decision = next((d for d in response.get("feedbackDecisions", []) if d["feedbackId"] == feedback["feedbackId"]), None)
                if decision:
                    feedback["planDecision"] = decision
                    self._put("feedback", feedback)
            return
        if kind == "preview":
            preview = self._get("preview", owner["id"])
            preview.update(status="STOPPED", result=public(payload.get("result")))
            self._put("preview", preview)
            return
        job = self.require_project_resource(pid, "job", owner["id"])
        packet = self._get("packet", job["packetId"])
        self._revalidate_job_approval(job, packet)
        ref = payload.get("artifactRef")
        if kind == "produce":
            repo = self._artifact_repository(ref, project_id=pid, job_id=job["id"], packet_id=packet["id"])
            if ref.get("attemptId") != attempt["id"] or ref.get("inputCommit") != job.get("inputCommit") or payload.get("sourceCommit") != ref["sourceCommit"]:
                fail("DELIVERY_BINDING", "交付未绑定本制作代次和精确输入。")
            git(repo, "merge-base", "--is-ancestor", job["inputCommit"], ref["sourceCommit"])
            prepared = attempt.get("prepared") or {}
            protected = prepared.get("protectedFiles", [])
            protected_names = protected if isinstance(protected, list) else list(protected)
            protected_names = list(set([*SPEC_FILES, "design/game.json", "studio/runtime.gd", ".gitignore", *protected_names]))
            if git(repo, "diff", "--name-only", job["inputCommit"], ref["sourceCommit"], "--", *protected_names):
                fail("PROTECTED_DRIFT", "制作修改了保护文件。")
            changed = git(repo, "diff", "--name-only", "--no-renames", job["inputCommit"], ref["sourceCommit"]).splitlines()
            # Audit each committed change, not only dirty workspace files.
            from .general_verification import audit_general_scope
            from .source_preparation import load_uid_preparation_evidence
            uid_sidecars, _uid_engine = load_uid_preparation_evidence(repo.parent,
                input_commit=job["inputCommit"], source_commit=ref["sourceCommit"])
            audit_general_scope(repo, job["inputCommit"], packet["document"],
                service_records=prepared.get("serviceRecords"), prepared_uid_sidecars=uid_sidecars)
            if not any(path not in uid_sidecars for path in changed) and not packet.get("dataOnlyUpdate"):
                fail("PRODUCER_NO_EDIT", "制作未落实源码更改。")
            artifact = {"id": ref["artifactId"], "projectId": pid, "ref": ref, "retained": True, "createdAt": now()}
            self._put("artifact", artifact)
            runner = self._project_runner("verification-isolated-v1", require_online=False)
            verify = self._new_attempt(pid, "verify", {"kind": "job", "id": job["id"]}, runner["id"], input_refs={"artifactRef": ref, "packetId": packet["id"], "inputCommit": job["inputCommit"], "sourceCommit": ref["sourceCommit"]}, scope={"mode": "verification_copy", "sourceReadOnly": True, "cacheScope": ".godot", "allowProjectExecution": True})
            verify["prepared"] = {"serviceRecords": prepared.get("serviceRecords")}
            self._put("attempt", verify)
            job.update(status="VERIFYING", productionAttemptId=attempt["id"], verificationAttemptId=verify["id"], attemptId=verify["id"], artifactRef=ref, changedFiles=changed, message="制作已停止且交付已封存；等待独立精确版本验证。")
            self._put("job", job)
            return
        expected_ref = job.get("artifactRef")
        if ref != expected_ref or payload.get("sourceCommit") != expected_ref.get("sourceCommit"):
            fail("VERIFICATION_BINDING", "验证对象与封存交付不符。")
        self._artifact_repository(ref, project_id=pid, job_id=job["id"], packet_id=packet["id"])
        verification = payload.get("result") or {}
        if verification.get("sourceCommit") != ref["sourceCommit"] or verification.get("sourceUnchanged") is not True:
            fail("VERIFICATION_FAILED", "独立技术验证未通过精确源与停止检查。")
        verification.update(runId=identifier("run"), projectId=pid, jobId=job["id"], packetId=packet["id"], artifactId=ref["artifactId"], productionAttemptId=job["productionAttemptId"], verificationAttemptId=attempt["id"], inputCommit=job["inputCommit"], testData=self.test_data, humanAcceptance="NOT PERFORMED")
        if verification.get("status") != "PASS":
            job.update(status="FAILED", verification=verification, message="制作交付已封存；独立技术验证未通过，尚无可试玩候选。请查看失败项并从保留源码重新策划修复。",
                verificationFailure={"code": "VERIFICATION_FAILED", "message": "独立技术验证未通过；已保留精确源码及逐项结果，等待重新策划修复。", "terminationConfirmed": True})
            job.pop("candidate", None)
            self._put("job", job)
            return
        candidate = {"id": identifier("candidate"), "jobId": job["id"], "projectId": pid, "workflow": "objects-v1", "candidateCommit": ref["sourceCommit"], "sourceCommit": ref["sourceCommit"], "artifactRef": ref,
            "catalog": catalog_from_document(packet["document"], ref["sourceCommit"]), "catalogStatus": "READY", "document": packet["document"], "verification": verification, "summary": "精确候选已通过独立技术验证，等待用户试玩和逐条体验验收。", "previewAvailable": True,
            "objectChanges": packet.get("objectChanges", []), "changedFiles": job.get("changedFiles", []), "rules": {}, "createdAt": now(), "feedbackDecisions": packet.get("feedbackDecisions", []), "testData": self.test_data, "productionAuthorized": self.production_authorized}
        job.update(status="READY_FOR_REVIEW", candidate=candidate, verification=verification)
        self._put("job", job)

    def _candidate_decision(self, pid, payload, expected, accept):
        project = self._get("project", pid)
        job = next((j for j in self._all_project("job", pid) if (j.get("candidate") or {}).get("id") == payload["candidateId"]), None)
        if not job or job["status"] != "READY_FOR_REVIEW":
            fail("CANDIDATE_MISMATCH", "候选不处于当前待验收状态。")
        candidate, packet = job["candidate"], self._get("packet", job["packetId"])
        if candidate["candidateCommit"] != payload["sourceCommit"] or expected.get("publicationRevision") != project["publicationRevision"] or packet["publicationRevision"] != project["publicationRevision"]:
            fail("CANDIDATE_BINDING", "候选源版本或当前发布基线已变化。")
        self._revalidate_job_approval(job, packet)
        ref = candidate["artifactRef"]
        self._artifact_repository(ref, project_id=pid, job_id=job["id"], packet_id=packet["id"])
        verification = candidate["verification"]
        if verification.get("status") != "PASS" or verification.get("artifactId") != ref["artifactId"] or verification.get("sourceCommit") != ref["sourceCommit"] or verification.get("verificationAttemptId") != job["verificationAttemptId"]:
            fail("CANDIDATE_VERIFICATION", "候选没有精确独立验证。")
        decisions = payload.get("experienceDecisions", [])
        known = {f["feedbackId"]: f for f in self._all_project("feedback", pid)}
        if len({d["feedbackId"] for d in decisions}) != len(decisions) or any(d["feedbackId"] not in known for d in decisions):
            fail("FEEDBACK_REFERENCE", "体验决定必须引用本项目的独立反馈。", 400)
        event = self._event(phase="run_acceptance", action="accept" if accept else "changes_requested", project_id=pid, proposal_id=packet["proposalId"], packet_id=packet["id"], job_id=job["id"], candidate_id=candidate["id"], revision=packet["proposalRevision"], git_spec_ref=packet.get("gmSpecRef"), run_id=verification["runId"])
        self._consume(event)
        for decision in decisions:
            feedback = known[decision["feedbackId"]]
            feedback.update(experienceStatus=decision["status"], candidateId=candidate["id"], experienceDecision=decision)
            self._put("feedback", feedback)
        if payload.get("feedback"):
            self._save_feedback(pid, self._get("proposal", packet["proposalId"]), payload["feedback"])
        if accept:
            snapshot = self._publish_generic(packet, candidate, expected["publicationRevision"])
            snapshot["artifactRef"] = ref
            self._put("snapshot", snapshot)
            job.update(status="PUBLISHED", snapshot=snapshot, message="用户已接受精确候选；未明确解决的反馈继续保留。")
        else:
            snapshot = None
            job.update(status="REJECTED", message="用户拒绝候选，原已接受版本继续保留。")
        job["decisionEventId"] = event["eventId"]
        job["experienceDecisions"] = decisions
        self._put("job", job)
        if accept:
            self._after_commit.append(lambda: self.materialize_snapshot(snapshot["id"]))
        return {"job": job, "snapshot": snapshot}, {"kind": "job", "id": job["id"]}

    def materialize_snapshot(self, snapshot_id):
        with self.lock:
            return self._materialize_snapshot_locked(snapshot_id)

    def _materialize_snapshot_locked(self, snapshot_id):
        import subprocess
        snapshot = self._get("snapshot", snapshot_id)
        if self._get("project", snapshot["projectId"]).get("snapshotId") != snapshot_id:
            return
        ref = snapshot["artifactRef"]
        try:
            repo = self._artifact_repository(ref, project_id=snapshot["projectId"], job_id=snapshot["jobId"])
            target = self.state_root / "projects" / snapshot["projectId"]
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(["git", "clone", "--no-hardlinks", str(repo), str(target)], capture_output=True, timeout=30)
                if result.returncode:
                    raise RuntimeError("Accepted source materialization failed")
            else:
                if target.is_symlink() or _core()[2](target, "status", "--porcelain"):
                    fail("MATERIALIZATION_DIRTY", "派生工程包含未知改动，保留快照引用待核查。")
                _core()[2](target, "fetch", str(repo), ref["sourceCommit"])
            _core()[2](target, "checkout", "--detach", ref["sourceCommit"])
            with self.transaction():
                snapshot = self._get("snapshot", snapshot_id)
                snapshot.update(materializationStatus="READY")
                snapshot.pop("materializationError", None)
                self._put("snapshot", snapshot)
        except Exception as exc:
            with self.transaction():
                snapshot = self._get("snapshot", snapshot_id)
                snapshot.update(materializationStatus="PENDING", materializationError=str(exc)[:500])
                self._put("snapshot", snapshot)

    def _start_preview(self, pid, payload):
        if self._get("project", pid).get("archived"):
            fail("PROJECT_ARCHIVED", "已归档项目不能启动试玩。")
        if any(p.get("status") not in {"STOPPED", "FAILED"} for p in self._all_project("preview", pid)):
            fail("PREVIEW_BUSY", "本项目试玩尚未停止或状态待核实，不能重复启动。")
        if payload.get("candidateId"):
            job = next((j for j in self._all_project("job", pid) if (j.get("candidate") or {}).get("id") == payload["candidateId"]), None)
            if not job:
                fail("PREVIEW_CANDIDATE", "试玩候选不属于本项目。")
            ref = job["candidate"]["artifactRef"]
        else:
            snapshot = self.require_project_resource(pid, "snapshot", payload["snapshotId"])
            ref = snapshot["artifactRef"]
        self._artifact_repository(ref, project_id=pid)
        runner = self._project_runner("preview-isolated-v1")
        preview = {"id": _core()[3]("preview"), "projectId": pid, "artifactRef": ref, "status": "QUEUED"}
        attempt = self._new_attempt(pid, "preview", {"kind": "preview", "id": preview["id"]}, runner["id"], input_refs={"artifactRef": ref}, scope={"mode": "preview_copy", "sourceReadOnly": True, "cacheScope": ".godot", "allowProjectExecution": True})
        preview["attemptId"] = attempt["id"]
        self._put("preview", preview)
        return {"preview": preview}, {"kind": "preview", "id": preview["id"]}

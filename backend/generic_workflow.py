"""Object-based 2D planning and production, composed with the legacy coordinator.

The server owns revisions, write scope, approvals and verification. Model output
is a proposal, never approval or a certification of its own game behavior.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .codex_driver import CodexDriver, _terminate_process_group
from .object_protocol import (
    ObjectProtocolError,
    apply_field_changes,
    catalog_from_document,
    parse_planner_response,
    planner_instructions,
    validate_change_request,
)

WORKFLOW = "objects-v1"
PLANNING_ACTIVE = {"PLANNING", "PLANNING_CANCELLING", "PLANNING_UNCERTAIN"}
SPEC_FILES = ("SPEC.md", "GDD.md", "PLAN.md", "STRUCTURE.md", "SCENES.md", "DESIGN.md", "ASSETS.md")


def _core():
    from .coordinator import WorkflowError, canonical, git, identifier, now

    return WorkflowError, canonical, git, identifier, now


def _failure(code, message, status=409):
    error, *_ = _core()
    raise error(status, code, message)


def _require_stopped(lease):
    pgid = (lease or {}).get("processGroupId")
    if type(pgid) is not int or pgid <= 1 or pgid == os.getpgrp():
        _failure("LEASE_UNKNOWN", "策划没有可信进程组记录，请保留项目并由本机操作者检查。")
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        _failure("LEASE_UNOBSERVABLE", "无法核实策划进程，继续保留项目独占。")
    _failure("LEASE_ACTIVE", "原策划进程组仍存在；不会自动重新派发。")


def timeout_clarification(result):
    """Recover questions only, never a production plan, from a stopped timeout."""
    diagnostics = (result or {}).get("diagnostics") or {}
    if (not result or result.get("status") != "timeout"
            or diagnostics.get("childTerminationConfirmed") is not True
            or diagnostics.get("approvalRequests") or diagnostics.get("protocolErrors")
            or (result.get("commandEvidence") or {}).get("executionEvidence")):
        return None
    try:
        response = parse_planner_response(result.get("response", ""))
    except (ObjectProtocolError, TypeError, ValueError):
        return None
    if response["status"] != "NEEDS_CLARIFICATION":
        return None
    # Even a complete JSON value lacks the native final-answer boundary. Its
    # tentative document and tasks cannot become an approved production plan.
    return {**response, "document": None, "tasks": []}


def clarification_recovery():
    return {"kind": "CLARIFICATION_FROM_TIMEOUT", "nativeStatus": "timeout",
        "message": "原生策划在时限内未确认完成；仅恢复已校验的澄清问题，请回答后继续策划。"}


def planning_failure(result, error=None):
    """Safe UI diagnosis; detailed native evidence remains separate and intact."""
    result = result or {}
    diagnostics = result.get("diagnostics") or {}
    stopped = diagnostics.get("childTerminationConfirmed") is True
    status = result.get("status")
    elapsed = diagnostics.get("elapsedSeconds")
    if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
        elapsed = None
    failure = {"code": "PLANNER_FAILED", "message": "原生策划未完成；可用原输入重新策划。",
        "nativeStatus": status, "elapsedSeconds": elapsed, "sessionId": result.get("sessionId"),
        "terminationConfirmed": stopped, "retryable": stopped,
        "clarificationAvailable": timeout_clarification(result) is not None}
    if not result:
        failure.update(code="PLANNER_SETUP", message="策划启动或输入准备失败；请检查本机服务诊断。", retryable=False)
    elif not stopped:
        failure.update(code="PLANNER_UNCERTAIN", message="策划停止状态未确认；请先对账，不会重新派发。", retryable=False)
    elif diagnostics.get("approvalRequests") or diagnostics.get("protocolErrors"):
        failure.update(code="PLANNER_RESTRICTED", message="原生策划请求了当前角色范围外的操作；请检查执行诊断。", retryable=False)
    elif getattr(error, "code", None) == "PLANNER_WRITE":
        failure.update(code="PLANNER_WRITE", message="策划违反只读范围；请检查执行诊断。",
            retryable=False, clarificationAvailable=False)
    elif status != "completed":
        # Plugin-cache warnings are unrelated to the model's response stream.
        messages = [str(diagnostics.get("error") or ""), json.dumps(diagnostics.get("nativeErrors") or []),
                    json.dumps(diagnostics.get("nativeTurnError") or {})]
        messages.extend(str(line) for line in diagnostics.get("stderr", [])
                        if "responses_retry" in str(line) or "stream disconnected" in str(line)
                        or "stream connection failed" in str(line))
        native_text = "\n".join(messages).lower()
        if any(marker in native_text for marker in ("unauthorized", "authentication", "invalid api key")):
            failure.update(code="PLANNER_AUTH", message="原生策划的登录或服务凭据不可用；恢复连接配置后再试。", retryable=False)
        elif any(marker in native_text for marker in ("stream disconnected", "stream connection failed", "transport error",
                "network error", "error sending request", "connection failed", "connection reset")):
            failure.update(code="PLANNER_NETWORK", message="原生策划连接中断，未返回完整计划；进程已停止，可用原输入重试。")
        elif status == "timeout":
            failure.update(code="PLANNER_TIMEOUT", message="原生策划超过运行时限，未返回完整计划；进程已停止，可用原输入重试。")
    else:
        failure.update(code="PLANNER_RESPONSE_INVALID", message="策划返回的结果未通过对象计划校验；保留原输入，可重新策划。")
    return failure


class GenericWorkflow:
    """Mix-in: persistence and concurrency primitives are owned by Coordinator."""

    @staticmethod
    def _template_inventory(template):
        from tools.git_baseline import capture_inventory

        paths = []
        for path in template.rglob("*"):
            if path.is_symlink():
                _failure("TEMPLATE_LINK", "通用工程基线不能包含链接。")
            if path.is_file():
                paths.append(path.relative_to(template).as_posix())
        return capture_inventory(template, paths)

    def get_proposal(self, proposal_id):
        with self.lock:
            return self._diagnosed_proposal(self._get("proposal", proposal_id))

    def _diagnosed_proposal(self, proposal):
        """Expose older failure evidence on reads without rewriting old records."""
        if (proposal.get("workflow") != WORKFLOW or proposal.get("status") not in {"FAILED", "PLANNING_UNCERTAIN"}
                or "clarificationAvailable" in (proposal.get("planningFailure") or {})):
            return proposal
        proposal = copy.deepcopy(proposal)
        result = proposal.get("planningEvidence")
        folder = self.state_root / "planning" / proposal["id"] / f"round-{proposal['revision']}"
        path = folder / "session.json"
        if not result:
            try:
                if (path.is_file() and path.stat().st_size <= 10 * 1024 * 1024
                        and not any(parent.is_symlink() for parent in (path, *folder.parents, folder))):
                    result = json.loads(path.read_text())
                    if not isinstance(result, dict):
                        result = None
            except (OSError, ValueError):
                result = None
        if result:
            proposal["planningEvidence"] = result
            proposal["planningTerminationConfirmed"] = (result.get("diagnostics") or {}).get("childTerminationConfirmed") is True
        if proposal.get("planningFailure"):
            proposal["planningFailure"] = {**proposal["planningFailure"],
                "clarificationAvailable": timeout_clarification(result) is not None
                    and proposal["planningFailure"].get("code") != "PLANNER_WRITE"}
        else:
            proposal["planningFailure"] = planning_failure(result)
        return proposal

    def _planning_update(self, proposal_id, revision, **fields):
        with self.transaction():
            current = self._get("proposal", proposal_id)
            if current["revision"] != revision:
                return False
            current.update(fields)
            current["updatedAt"] = _core()[4]()
            self._put("proposal", current)
            return True

    @staticmethod
    def _check_planning_readonly(folder, request):
        unexpected = [p for p in folder.rglob("*") if p.is_symlink() or
                      p.relative_to(folder).as_posix() not in {"request.json", "session.json"}]
        if folder.is_symlink() or any(parent.is_symlink() for parent in folder.parents) or unexpected:
            _failure("PLANNER_WRITE", "策划产生了未授权文件或链接。")
        if (folder / "request.json").read_text() != _core()[1](request) + "\n":
            _failure("PLANNER_WRITE", "策划改动了只读输入。")

    def create_generic_concept(self, *, operator_id, text, project_id=None,
                               asset_ids=None, expected_publication_revision=None,
                               change_request=None):
        _, _, _, identifier, now = _core()
        self._operator(operator_id)
        has_structured_change = (project_id is not None and isinstance(change_request, dict) and
            bool(change_request.get("fields") or change_request.get("feedback")))
        if not isinstance(text, str) or len(text) > 8000 or (not text.strip() and not has_structured_change):
            _failure("CONCEPT", "请提供有界的游戏概念或修改意图。", 400)
        ids = asset_ids or []
        if not isinstance(ids, list) or len(ids) > 6 or len(set(ids)) != len(ids):
            _failure("ASSETS", "每轮最多六张不同的参考图。", 400)
        if expected_publication_revision is not None:
            self._revision(expected_publication_revision)
        with self.transaction():
            if project_id:
                assets = [self.require_project_asset(project_id, aid) for aid in ids]
            elif ids:
                _failure("PROJECT_REQUIRED", "图片必须属于明确的项目。", 400)
            else:
                assets = []
            if project_id:
                project = self._get("project", project_id)
                if project.get("workflow") != WORKFLOW:
                    _failure("WORKFLOW_MISMATCH", "旧项目不能沿用旧批准自动转换为通用对象工程。")
                self._available(project_id)
                if expected_publication_revision != project["publicationRevision"]:
                    _failure("STALE_DRAFT", "草稿基线已变化，请先检查版本重关联。")
            else:
                if change_request:
                    _failure("CHANGE_BASE", "新概念还没有可修改的发布对象。", 400)
                project = {"id": identifier("project"), "title": text.strip().splitlines()[0][:60],
                           "workflow": WORKFLOW, "templateId": "general-2d-v1",
                           "publicationRevision": 0, "snapshotId": None, "createdAt": now()}
                self._put("project", project)
            snapshot = self._get("snapshot", project["snapshotId"]) if project["snapshotId"] else None
            current_document = snapshot.get("document") if snapshot else None
            if snapshot:
                request = change_request or {"baseRevision": project["publicationRevision"],
                    "sourceCommit": snapshot["sourceCommit"], "targetObjectIds": [], "fields": [], "feedback": []}
                try:
                    request = validate_change_request(request, current_document,
                        project["publicationRevision"], snapshot["sourceCommit"])
                except ObjectProtocolError as exc:
                    _failure("CHANGE_REQUEST", str(exc), 400)
            else:
                request = None
            for old in self._all("proposal"):
                if old["projectId"] == project["id"] and old["status"] in {"READY", "NEEDS_CLARIFICATION"}:
                    old.update(status="SUPERSEDED", updatedAt=now())
                    self._put("proposal", old)
            proposal = {"id": identifier("proposal"), "projectId": project["id"],
                "workflow": WORKFLOW, "revision": 1, "status": "PLANNING", "text": text.strip(),
                "summary": "正在围绕你的概念和目标对象整理问题与制作计划。",
                "publicationRevision": project["publicationRevision"],
                "baseCommit": snapshot["sourceCommit"] if snapshot else None,
                "initializationRequired": False, "templateId": "general-2d-v1",
                "questions": [], "decisions": {}, "document": None, "tasks": [],
                "currentDocument": current_document, "changeRequest": request, "assets": assets,
                "discussion": [{"role": "user", "text": text.strip(), "at": now()}],
                "testData": self.test_data, "productionAuthorized": self.production_authorized,
                "createdAt": now(), "updatedAt": now()}
            self._put("proposal", proposal)
        self._launch_planning(proposal)
        return proposal

    def _launch_planning(self, proposal):
        key = "planning:" + proposal["id"]
        cancel = threading.Event()
        thread = threading.Thread(target=self._plan_generic, args=(copy.deepcopy(proposal), cancel), daemon=True)
        with self.lock:
            self._cancels[key] = cancel
            self._threads[key] = thread
            thread.start()

    def _plan_generic(self, proposal, cancel):
        _, canonical, _, _, _ = _core()
        pid, revision = proposal["id"], proposal["revision"]
        started, stopped, result = False, False, None
        folder = self.state_root / "planning" / pid / f"round-{revision}"
        try:
            folder.mkdir(parents=True, exist_ok=False)
            folder.chmod(0o700)
            (folder / "request.json").write_text(canonical(proposal) + "\n")
            driver = (self.planner_driver_factory(folder) if self.planner_driver_factory else
                      CodexDriver(folder, timeout=420, execution_profile="managed_read_only",
                          reasoning_effort="medium", disabled_mcp_servers=["godot-mcp"]))
            packet = {"operationKind": "PLANNING", "allowedFiles": [],
                "instruction": planner_instructions() + "\nReturn the JSON object as the final response. Do not write files. "
                    "When clarification is needed, return only the unresolved questions and a concise concept summary, "
                    "with document=null and tasks=[]; defer the full object plan until those answers are received. "
                    "Preserve existing object/field IDs. Every explicit field change must appear exactly in the resulting document. "
                    "Ask only questions that the user has not already answered. Retain targeted feedback, risks and omitted scope. "
                    "Only Godot 4 GDScript 2D projects with procedural visuals or supplied references are supported. "
                    "Do not use or activate Ptah skills; the supplied GM non-pk contract and GameStudio design principles are the references. "
                    "Do not promise generated art, exports, network services, audio generation or external plugins. "
                    "Game source reads the frozen fields through StudioRuntime.object_value(). "
                    "For existing projects preserve working behavior outside the requested change. "
                    "Separate simulation, rendering, input actions and interface responsibilities, as in GM non-pk and GameStudio.",
                "concept": proposal["text"], "discussion": proposal["discussion"],
                "currentDocument": proposal["currentDocument"], "changeRequest": proposal["changeRequest"],
                "testData": self.test_data, "productionAuthorized": self.production_authorized}
            if self._field_only_intent(proposal):
                packet["instruction"] += (" This is a field-only iteration: preserve the whole currentDocument exactly "
                    "except the requested field values. Retain requirements, IDs, bindings, descriptions, title and summary. "
                    "Tasks should verify the existing runtime-driven fields without unnecessary game source changes.")
            references = [self.project_asset_file(proposal["projectId"], asset)[0]
                for asset in proposal.get("assets", [])]
            started = True
            result = driver.run(packet, cancel_event=cancel, reference_images=references,
                on_process_started=lambda lease: self._planning_update(pid, revision, planningLease=lease))
            stopped = result.get("diagnostics", {}).get("childTerminationConfirmed") is True
            (folder / "session.json").write_text(canonical(result) + "\n")
            self._planning_update(pid, revision, planningEvidence=result, planningTerminationConfirmed=stopped)
            if not stopped:
                self._planning_update(pid, revision, status="PLANNING_UNCERTAIN", planningEvidence=result,
                    planningFailure=planning_failure(result),
                    summary="策划停止状态未确认；保留项目占用，不会自动重投。")
                return
            if cancel.is_set():
                self._planning_update(pid, revision, status="CANCELLED", planningEvidence=result,
                    summary="策划已停止；没有批准或制作游戏。")
                return
            recovered = result.get("status") != "completed"
            response = timeout_clarification(result) if recovered else None
            if recovered and response is None:
                _failure("PLANNER_FAILED", planning_failure(result)["message"])
            # A read-only planner is not permitted to mutate its input workspace.
            self._check_planning_readonly(folder, proposal)
            if response is None:
                response = parse_planner_response(result.get("response", ""))
            document = response.get("document")
            if response["status"] == "READY":
                self._check_requested_fields(document, proposal.get("changeRequest"))
                references = self._prepare_generic_spec(proposal, document, response["tasks"])
            else:
                references = {}
            with self.transaction():
                current = self._get("proposal", pid)
                if current["revision"] != revision or current["status"] not in PLANNING_ACTIVE:
                    return
                if cancel.is_set():
                    current.update(status="CANCELLED", planningEvidence=result,
                        planningTerminationConfirmed=True,
                        summary="策划已停止；没有批准或制作游戏。", updatedAt=_core()[4]())
                    self._put("proposal", current)
                    return
                current.update(response, planningEvidence=result, planningTerminationConfirmed=True,
                    scope="仅在受控 Godot 2D 项目源码范围内落实完整对象计划。",
                    requirements=document["requirements"] if document else [],
                    roles=["read-only planner", "game producer", "independent technical verifier", "user reviewer"],
                    acceptance=["独立导入和运行冒烟通过", "对象、源绑定及冻结属性一致", "人工体验计划中的玩法与视觉要求"],
                    objectChanges=self._object_changes(proposal.get("currentDocument"), document), **references)
                current.pop("planningFailure", None)
                if recovered:
                    current["planningRecovery"] = clarification_recovery()
                else:
                    current.pop("planningRecovery", None)
                current["discussion"].append({"role": "planner", "summary": response["summary"],
                    "questions": response["questions"], "at": _core()[4]()})
                current["updatedAt"] = _core()[4]()
                self._put("proposal", current)
        except Exception as exc:
            diagnostic = planning_failure(result, exc)
            self._planning_update(pid, revision,
                status="PLANNING_UNCERTAIN" if started and not stopped else ("CANCELLED" if cancel.is_set() else "FAILED"),
                summary=str(exc)[:2000], message=str(exc)[:2000],
                planningFailure=diagnostic, **({"planningEvidence": result,
                    "planningTerminationConfirmed": stopped} if result is not None else {}))

    @staticmethod
    def _field_only_intent(proposal):
        request = proposal.get("changeRequest") or {}
        return bool(proposal.get("currentDocument") and not proposal.get("text", "").strip()
                    and not proposal.get("assets") and request.get("fields") and not request.get("feedback"))

    @staticmethod
    def _data_only_update(proposal):
        if not GenericWorkflow._field_only_intent(proposal):
            return False
        expected = apply_field_changes(proposal["currentDocument"], proposal["changeRequest"])
        return expected != proposal["currentDocument"] and expected == proposal["document"]

    @staticmethod
    def _check_requested_fields(document, request):
        if not request:
            return
        objects = {obj["id"]: obj for obj in document["objects"]}
        for change in request["fields"]:
            obj = objects.get(change["objectId"])
            field = next((f for f in (obj or {}).get("fields", []) if f["id"] == change["fieldId"]), None)
            if field is None or type(field["value"]) is not type(change["value"]) or field["value"] != change["value"]:
                _failure("PLAN_CHANGE_MISMATCH", "策划没有准确保留明确的对象属性修改。")

    @staticmethod
    def _object_changes(previous, current):
        old = {o["id"]: o for o in (previous or {}).get("objects", [])}
        new = {o["id"]: o for o in (current or {}).get("objects", [])}
        return [{"objectId": oid, "action": "added" if oid not in old else "removed" if oid not in new else "modified",
                 "before": old.get(oid), "after": new.get(oid)} for oid in sorted(old.keys() | new.keys()) if old.get(oid) != new.get(oid)]

    def _prepare_generic_spec(self, proposal, document, tasks):
        from .game_spec import render_spec_documents
        from .general_gm_integration import spec_ref
        from tools.git_baseline import capture_inventory

        _, _, git, _, _ = _core()
        folder = self.state_root / "planning" / proposal["id"] / f"spec-{proposal['revision']}"
        folder.mkdir(parents=True, exist_ok=False)
        files = render_spec_documents(document, tasks, proposal.get("changeRequest"), revision=proposal["revision"])
        for name, content in files.items():
            (folder / name).write_text(content)
        git(folder, "init", "-b", "main")
        git(folder, "config", "user.name", "Studio Plan")
        git(folder, "config", "user.email", "studio@localhost")
        git(folder, "add", "--", *sorted(files))
        git(folder, "commit", "-m", "Capture proposed GM non-pk specification")
        template = self.root / "backend/templates/general_2d"
        inventory = self._template_inventory(template)
        source_refs = {}
        if proposal["baseCommit"]:
            repo = self.state_root / "projects" / proposal["projectId"]
            source_refs = {name: "git:blob:" + git(repo, "rev-parse", proposal["baseCommit"] + ":" + name)
                           for name in ("design/game.json", "studio/runtime.gd", "project.godot")}
        return {"gmSpecRef": spec_ref(folder), "specInventory": capture_inventory(folder, sorted(files)),
                "sourceRefs": source_refs, "templateInventory": inventory}

    def answer_generic_proposal(self, *, operator_id, proposal_id, expected_revision, answers):
        self._operator(operator_id)
        self._revision(expected_revision)
        _, _, _, _, now = _core()
        with self.transaction():
            p = self._get("proposal", proposal_id)
            if p["revision"] != expected_revision or p["status"] != "NEEDS_CLARIFICATION":
                _failure("STALE_PROPOSAL", "问题版本已变化，或策划不在等待回答。")
            if not isinstance(answers, dict) or set(answers) - {q["id"] for q in p["questions"]}:
                _failure("ANSWERS", "答案包含未声明的问题。", 400)
            for q in p["questions"]:
                value = answers.get(q["id"])
                if value is None or value == "":
                    if q.get("required", True):
                        _failure("ANSWER_REQUIRED", "请完成本轮必答问题。", 400)
                    continue
                kind = q["type"]
                if kind == "text" and (not isinstance(value, str) or len(value) > 2000):
                    _failure("ANSWER_TYPE", "文字答案需要有界文本。", 400)
                if kind == "number" and (type(value) not in {int, float} or not math.isfinite(value)):
                    _failure("ANSWER_TYPE", "数字问题需要明确数值。", 400)
                if kind == "boolean" and type(value) is not bool:
                    _failure("ANSWER_TYPE", "请回答是或否。", 400)
                if kind == "choice" and not any(type(value) is type(option) and value == option
                    for option in [o.get("value") if isinstance(o, dict) else o for o in q.get("options", [])]):
                    _failure("ANSWER_TYPE", "请使用本题提供的选项。", 400)
            self._available(p["projectId"])
            p["discussion"].append({"role": "user", "answers": copy.deepcopy(answers), "at": now()})
            for key in ("planningFailure", "planningRecovery", "planningEvidence", "planningTerminationConfirmed", "planningLease", "message"):
                p.pop(key, None)
            p.update(revision=expected_revision + 1, status="PLANNING", questions=[], updatedAt=now())
            self._put("proposal", p)
        self._launch_planning(p)
        return p

    def cancel_proposal(self, *, operator_id, proposal_id):
        self._operator(operator_id)
        with self.transaction():
            p = self._get("proposal", proposal_id)
            if p.get("workflow") != WORKFLOW:
                _failure("WORKFLOW_MISMATCH", "此操作只适用于通用策划。")
            if self._get("project", p["projectId"]).get("archived"):
                _failure("PROJECT_ARCHIVED", "已归档项目为只读状态，请先恢复项目。", 409)
            if p["status"] == "PLANNING":
                cancel = self._cancels.get("planning:" + proposal_id)
                if cancel:
                    cancel.set()
                    p["status"] = "PLANNING_CANCELLING"
                else:
                    p["status"] = "PLANNING_UNCERTAIN"
            elif p["status"] in {"READY", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED"}:
                p["status"] = "CANCELLED"
            p["summary"] = "已请求停止策划；确认进程停止前仍保持占用。" if p["status"] in PLANNING_ACTIVE else "本轮策划已取消。"
            self._put("proposal", p)
            return p

    def reconcile_proposal(self, *, operator_id, proposal_id):
        self._operator(operator_id)
        with self.transaction():
            p = self._get("proposal", proposal_id)
            if p.get("workflow") != WORKFLOW:
                _failure("WORKFLOW_MISMATCH", "此操作只适用于通用策划。")
            if p["status"] == "NEEDS_CLARIFICATION" and (p.get("planningRecovery") or {}).get("kind") == "CLARIFICATION_FROM_TIMEOUT":
                return p
            if p["status"] == "FAILED":
                self._available(p["projectId"])
                latest = next(item for item in self._all("proposal") if item["projectId"] == p["projectId"])
                project = self._get("project", p["projectId"])
                if latest["id"] != p["id"] or project["publicationRevision"] != p["publicationRevision"]:
                    _failure("STALE_PROPOSAL", "已有新的策划或发布版本，不能恢复旧问题。")
                diagnosed = self._diagnosed_proposal(p)
                result = diagnosed.get("planningEvidence")
                response = timeout_clarification(result)
                if response is None or (diagnosed.get("planningFailure") or {}).get("code") == "PLANNER_WRITE":
                    _failure("NO_CLARIFICATION", "没有可恢复的完整澄清问题；不会确认计划或重新派发。")
                thread = self._threads.get("planning:" + proposal_id)
                if thread and thread.is_alive():
                    _failure("EXECUTION_ACTIVE", "本次策划线程仍运行。")
                _require_stopped(p.get("planningLease") or (result.get("commandEvidence") or {}).get("executionLease"))
                folder = self.state_root / "planning" / p["id"] / f"round-{p['revision']}"
                if any(path.is_symlink() for path in (folder / "request.json", folder / "session.json", folder, *folder.parents)):
                    _failure("PLANNER_WRITE", "策划记录包含链接。")
                request = json.loads((folder / "request.json").read_text())
                # Failures change only these service fields. Compare every
                # remaining key, including workflow, scope and test authority,
                # rather than treating the file as its own trusted baseline.
                service_fields = {"status", "summary", "updatedAt", "message", "planningLease", "planningEvidence",
                    "planningTerminationConfirmed", "planningFailure"}
                immutable = lambda item: {key: value for key, value in item.items() if key not in service_fields}
                if not isinstance(request, dict) or request.get("status") != "PLANNING" or immutable(request) != immutable(p):
                    _failure("STALE_PROPOSAL", "原输入与当前提案不匹配，不能恢复问题。")
                self._check_planning_readonly(folder, request)
                if json.loads((folder / "session.json").read_text()) != result:
                    _failure("PLANNER_WRITE", "原生结果记录已变化。")
                p.update(response, planningEvidence=result, planningTerminationConfirmed=True,
                    planningRecovery=clarification_recovery(), updatedAt=_core()[4]())
                p.pop("planningFailure", None)
                p["discussion"].append({"role": "planner", "summary": response["summary"],
                    "questions": response["questions"], "recovery": "CLARIFICATION_FROM_TIMEOUT", "at": _core()[4]()})
                self._put("proposal", p)
                return p
            if p["status"] != "PLANNING_UNCERTAIN":
                _failure("NOT_UNCERTAIN", "只有未知策划执行需要对账。")
            thread = self._threads.get("planning:" + proposal_id)
            if thread and thread.is_alive():
                _failure("EXECUTION_ACTIVE", "本次策划线程仍运行。")
            _require_stopped(p.get("planningLease"))
            p.update(status="CANCELLED", summary="已核实原策划进程组退出；没有重新派发。")
            self._put("proposal", p)
            return p

    def freeze_generic_proposal(self, *, operator_id, proposal_id, expected_revision,
                                expected_publication_revision, reviewed_proposal):
        from .general_gm_integration import spec_ref
        from tools.git_baseline import capture_inventory

        _, canonical, git, identifier, now = _core()
        self._operator(operator_id)
        self._revision(expected_revision)
        self._revision(expected_publication_revision)
        with self.transaction():
            p = self._get("proposal", proposal_id)
            if p["status"] == "FROZEN" and p.get("packetId"):
                packet = self._get("packet", p["packetId"])
                if (packet["approvedProposal"] == reviewed_proposal and packet["proposalRevision"] == expected_revision
                    and packet["publicationRevision"] == expected_publication_revision):
                    return packet
            if p != reviewed_proposal or p["revision"] != expected_revision or p["status"] != "READY":
                _failure("REVIEW_MISMATCH", "需要确认当前完整对象计划和精确修订。")
            project = self._get("project", p["projectId"])
            self._available(project["id"])
            self.validate_project_assets(project["id"], p.get("assets", []))
            if project["publicationRevision"] != expected_publication_revision or p["publicationRevision"] != expected_publication_revision:
                _failure("STALE_PUBLICATION", "计划基线已变化。")
            folder = self.state_root / "planning" / p["id"] / f"spec-{p['revision']}"
            if capture_inventory(folder, SPEC_FILES) != p["specInventory"] or spec_ref(folder) != p["gmSpecRef"]:
                _failure("REVIEW_SOURCE_DRIFT", "GM 规格在审阅后已变化。")
            template = self.root / "backend/templates/general_2d"
            if self._template_inventory(template) != p["templateInventory"]:
                _failure("TEMPLATE_DRIFT", "通用工程基线在审阅后已变化。")
            if p["baseCommit"]:
                repo = self.state_root / "projects" / p["projectId"]
                for name, expected in p["sourceRefs"].items():
                    if "git:blob:" + git(repo, "rev-parse", p["baseCommit"] + ":" + name) != expected:
                        _failure("SOURCE_DRIFT", "源版本与对象计划不一致。")
            packet_id, job_id = identifier("packet"), identifier("job")
            event = self._event(phase="specification", action="approve", project_id=project["id"],
                proposal_id=p["id"], packet_id=packet_id, job_id=job_id,
                revision=p["revision"], git_spec_ref=p["gmSpecRef"])
            packet = {"id": packet_id, "packetId": packet_id, "jobId": job_id,
                "projectId": project["id"], "proposalId": p["id"], "proposalRevision": p["revision"],
                "publicationRevision": p["publicationRevision"], "workflow": WORKFLOW,
                "operationKind": "IMPLEMENTATION", "templateId": "general-2d-v1",
                "baseCommit": p["baseCommit"], "document": copy.deepcopy(p["document"]),
                "tasks": copy.deepcopy(p["tasks"]), "changeRequest": copy.deepcopy(p["changeRequest"]),
                "objectChanges": copy.deepcopy(p["objectChanges"]), "assets": p["assets"],
                "gmSpecRef": p["gmSpecRef"], "specInventory": p["specInventory"],
                "templateInventory": p["templateInventory"], "sourceRefs": p["sourceRefs"],
                "scope": p["scope"], "requirements": p["requirements"], "acceptance": p["acceptance"],
                "roles": p["roles"], "decisions": {}, "approvalEventId": event["eventId"],
                "approvedProposal": copy.deepcopy(p), "testData": self.test_data,
                "dataOnlyUpdate": self._data_only_update(p),
                "productionAuthorized": self.production_authorized, "createdAt": now()}
            if len(canonical(packet).encode()) > 2_000_000:
                _failure("PACKET_SIZE", "对象制作表单过大，请拆分本轮范围。", 400)
            self._put("packet", packet)
            p.update(status="FROZEN", packetId=packet_id)
            self._put("proposal", p)
            return packet

    def _execute_generic(self, job_id, cancel):
        from .general_gm_integration import confirm_spec, register, spec_confirmed, spec_ref
        from tools.git_baseline import capture_inventory

        _, canonical, git, identifier, now = _core()
        started, stopped = False, False
        try:
            with self.lock:
                job = self._get("job", job_id)
                packet = self._get("packet", job["packetId"])
            if self._check_cancel(job_id, cancel):
                return
            self._update(job_id, status="DISPATCHING", message="正在准备已批准的对象计划和隔离工程。")
            template = self.root / "backend/templates/general_2d"
            if self._template_inventory(template) != packet["templateInventory"]:
                _failure("TEMPLATE_DRIFT", "通用基线变化，需要重新策划和审阅。")
            repo = self.state_root / "projects" / packet["projectId"]
            if packet["baseCommit"] is None:
                if repo.exists():
                    project = self._get("project", packet["projectId"])
                    if not project.get("trustedBaseline") or git(repo, "rev-parse", "HEAD") != project["trustedBaseline"] or git(repo, "status", "--porcelain"):
                        _failure("INIT_DIRTY", "工程准备目录存在非预期改动。")
                else:
                    shutil.copytree(template, repo, ignore=shutil.ignore_patterns(".godot", "__pycache__"))
                    (repo / ".gitignore").write_text(".godot/\n.godotmaker/\n")
                    git(repo, "init", "-b", "main")
                    git(repo, "config", "user.name", "Studio Local Workflow")
                    git(repo, "config", "user.email", "studio@localhost")
                    paths = [p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
                    git(repo, "add", "--", *sorted(paths))
                    git(repo, "commit", "-m", "Prepare trusted general Godot 2D baseline")
                original_base = git(repo, "rev-parse", "HEAD")
                with self.transaction():
                    project = self._get("project", packet["projectId"])
                    project["trustedBaseline"] = original_base
                    self._put("project", project)
            else:
                original_base = packet["baseCommit"]
                for name, expected in packet["sourceRefs"].items():
                    if "git:blob:" + git(repo, "rev-parse", original_base + ":" + name) != expected:
                        _failure("SOURCE_DRIFT", "发布基线引用不一致。")
            folder = self.state_root / "jobs" / job_id
            folder.mkdir(parents=True)
            worktree = folder / "worktree"
            git(repo, "worktree", "add", "--detach", str(worktree), original_base)
            (folder / "packet.json").write_text(canonical(packet) + "\n")
            plan_folder = self.state_root / "planning" / packet["proposalId"] / f"spec-{packet['proposalRevision']}"
            if capture_inventory(plan_folder, SPEC_FILES) != packet["specInventory"]:
                _failure("SPEC_DRIFT", "已冻结规范文件发生变化。")
            for name in SPEC_FILES:
                (worktree / name).write_bytes((plan_folder / name).read_bytes())
            (worktree / "design/game.json").write_text(canonical(packet["document"]) + "\n")
            git(worktree, "add", "--", *SPEC_FILES, "design/game.json")
            git(worktree, "commit", "--allow-empty", "-m", "Prepare approved object specification " + job_id)
            base = git(worktree, "rev-parse", "HEAD")
            if spec_ref(worktree) != packet["gmSpecRef"]:
                _failure("GM_SPEC_DRIFT", "工程中的 GM 规格与用户批准不一致。")
            register(worktree, self.db_path, self.operator_id, packet["projectId"], packet)
            if self.test_data:
                gm_confirmation = {"status": "BLOCKED", "testData": True, "productionAuthorized": False,
                    "message": "Synthetic test approval cannot pass production GM specification gate."}
                if spec_confirmed(worktree):
                    _failure("TEST_GATE", "测试记录不得进入生产 GM 门。")
            else:
                gm_confirmation = confirm_spec(worktree, packet["approvalEventId"])
                if not spec_confirmed(worktree):
                    _failure("GM_GATE", "GM non-pk 未确认当前用户规格。")
            protected_paths = [*SPEC_FILES, "design/game.json", "studio/runtime.gd", ".gitignore",
                ".godotmaker/frontend-approval.json", ".godotmaker/stage.jsonl"]
            protected = {name: (worktree / name).read_bytes() for name in protected_paths if (worktree / name).exists()}
            production = dict(packet)
            production.update(allowedFiles=["project.godot", "scripts/**/*.gd", "scenes/**/*.tscn", "resources/**/*.tres", "assets/**/*.png", "assets/**/*.jpg", "assets/**/*.jpeg", "assets/**/*.webp"],
                instruction="Implement the approved complete 2D game document and tasks as ordinary Godot 4 GDScript. "
                    "Do not use or activate Ptah skills. Use only the supplied GM non-pk specification and GameStudio design principles. "
                    "Read GDD.md, PLAN.md, STRUCTURE.md and design/game.json. Use the protected StudioRuntime object_value() helper "
                    "to read all editable parameters from design/game.json; do not hardcode duplicate parameter values. "
                    "Preserve object IDs and source bindings, existing behavior outside this change, and implement reset/failure/feedback. "
                    "Edit only project.godot and the allowed game source paths. Do not change design/, studio/, documentation, tests, "
                    "Every added or edited source/resource/asset file must have a sourceBinding in the approved document. "
                    ".gitignore, .godotmaker/, Git history, permission configuration or verification reports. "
                    "Do not run Godot, tests, checksums, exports, install dependencies, generate raster art or access network services. "
                    "Backend independent verification runs afterward. Use procedural shapes when original art is unavailable. "
                    "Actually edit files using tools, then summarize changed objects and files; a prose description is not implementation.")
            if packet["dataOnlyUpdate"]:
                production["instruction"] += (" This is an approved field-only update; the backend has already changed the frozen "
                    "design/game.json values. If existing source correctly reads these fields at runtime, no source edits are "
                    "required. Report that explicitly. Do not make cosmetic edits solely to create a diff.")
            self._update(job_id, status="RUNNING", baseCommit=base, originalBaseCommit=original_base,
                gmSpecificationConfirmation=gm_confirmation, message="新的制作 session 正在落实已批准的对象计划。")
            driver = self.generic_driver_factory(worktree) if self.generic_driver_factory else (
                self.driver_factory(worktree) if self._custom_driver else CodexDriver(worktree, timeout=900,
                    execution_profile="managed_workspace_write", disabled_mcp_servers=["godot-mcp"]))
            reference_images = [self.project_asset_file(packet["projectId"], asset)[0]
                for asset in packet.get("assets", [])]
            started = True
            result = driver.run(production, cancel_event=cancel,
                reference_images=reference_images,
                on_process_started=lambda lease: self._update(job_id, executionLease=lease))
            (folder / "session.json").write_text(canonical(result) + "\n")
            stopped = result.get("diagnostics", {}).get("childTerminationConfirmed") is True
            self._update(job_id, sessionId=result.get("sessionId"), sessionEvidence=result)
            if not stopped:
                self._update(job_id, status="UNCERTAIN", message="制作停止未确认，项目继续独占。")
                return
            if self._check_cancel(job_id, cancel):
                return
            if result.get("status") != "completed":
                _failure("PRODUCTION_FAILED", "制作 session 没有完成，没有可发布候选。")
            self._check_generic_protected(worktree, base, protected)
            changed = self._audit_generic(worktree, base, packet["document"], protected)
            if not changed and not packet["dataOnlyUpdate"]:
                _failure("PRODUCER_NO_EDIT", "制作回合结束，但没有实际修改游戏源码。")
            self._update(job_id, status="VERIFYING", message="后端正在独立检查范围、导入和运行；玩法体验仍需用户审阅。")
            service_records = self._generic_service_records(protected)
            verification = (self.generic_verifier(worktree, packet["document"], base_commit=base,
                service_records=service_records) if self.generic_verifier else
                self._verify_generic_owned(job_id, worktree, packet["document"], base, cancel, service_records))
            verification.update(runId=identifier("run"), testData=self.test_data,
                productionAuthorized=self.production_authorized, humanAcceptance="NOT PERFORMED")
            (folder / "verification.json").write_text(canonical(verification) + "\n")
            self._update(job_id, verification=verification)
            if self._check_cancel(job_id, cancel):
                return
            if verification.get("status") != "PASS":
                _failure("VERIFICATION_FAILED", "独立技术验证未通过，没有候选。")
            self._check_generic_protected(worktree, base, protected)
            self._audit_generic(worktree, base, packet["document"], protected)
            if changed:
                git(worktree, "add", "--", *changed)
                git(worktree, "commit", "-m", "Implement approved object game " + job_id)
            commit = git(worktree, "rev-parse", "HEAD")
            all_changed = git(worktree, "diff", "--name-only", "--no-renames", original_base, commit, "--").splitlines()
            verification["sourceCommit"] = commit
            catalog = catalog_from_document(packet["document"], commit)
            candidate = {"id": identifier("candidate"), "jobId": job_id, "projectId": packet["projectId"],
                "workflow": WORKFLOW, "candidateCommit": commit, "catalog": catalog, "catalogStatus": "READY",
                "capabilities": catalog["capabilities"], "document": packet["document"],
                "verification": verification, "summary": "对象计划已落实并通过独立技术检查；等待你体验玩法和视觉要求。",
                "previewAvailable": True, "objectChanges": packet["objectChanges"], "changedFiles": all_changed,
                "implementationFiles": changed, "dataOnlyUpdate": packet["dataOnlyUpdate"],
                "rules": {}, "createdAt": now(), "testData": self.test_data,
                "productionAuthorized": self.production_authorized}
            (folder / "verification.json").write_text(canonical(verification) + "\n")
            (folder / "candidate.json").write_text(canonical(candidate) + "\n")
            with self.transaction():
                current = self._get("job", job_id)
                if cancel.is_set() or current["status"] in {"CANCELLING", "CANCEL_REQUESTED", "UNCERTAIN"}:
                    current.update(status="CANCELLED", message="取消已生效，迟到候选未发布。")
                else:
                    current.update(status="READY_FOR_REVIEW", candidate=candidate, verification=verification,
                        message=candidate["summary"])
                    self._put("candidate", candidate)
                self._put("job", current)
        except Exception as exc:
            uncertain = (started and not stopped) or getattr(exc, "code", None) == "VERIFICATION_UNCERTAIN"
            self._update(job_id, status="UNCERTAIN" if uncertain else ("CANCELLED" if cancel.is_set() else "FAILED"),
                message=str(exc)[:2000])

    @staticmethod
    def _check_generic_protected(worktree, base, protected):
        _, _, git, _, _ = _core()
        if git(worktree, "rev-parse", "HEAD") != base:
            _failure("GIT_HISTORY", "制作修改了受控 Git 历史。")
        for name, expected in protected.items():
            path = worktree / name
            current = worktree
            for part in Path(name).parts:
                current = current / part
                if current.is_symlink():
                    _failure("PROTECTED_FILE", "后端文件路径包含链接：" + name)
            if not path.is_file() or path.read_bytes() != expected:
                _failure("PROTECTED_FILE", "制作改动了后端持有文件：" + name)

    @staticmethod
    def _generic_service_records(protected):
        return {name: content.decode("utf-8") for name, content in protected.items()
                if name.startswith(".godotmaker/")}

    @staticmethod
    def _audit_generic(worktree, base, document, protected):
        from .general_verification import audit_general_scope

        return audit_general_scope(worktree, base, document,
            service_records=GenericWorkflow._generic_service_records(protected))

    def _verify_generic_owned(self, job_id, worktree, document, base, cancel, service_records):
        _, canonical, _, _, now = _core()
        argv = [sys.executable, "-m", "backend.general_verification_worker", str(worktree)]
        proc = subprocess.Popen(argv, cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self._update(job_id, verificationLease={"pid": proc.pid, "processGroupId": proc.pid,
                "startedAt": now(), "cwd": str(worktree), "argv": argv})
            deadline = time.monotonic() + 180
            input_data = canonical({"document": document, "baseCommit": base,
                "operation": "IMPLEMENTATION", "serviceRecords": service_records})
            while True:
                if cancel.is_set():
                    _failure("VERIFY_CANCELLED", "已请求取消独立验证。")
                if time.monotonic() >= deadline:
                    _failure("VERIFY_TIMEOUT", "独立通用验证超时。")
                try:
                    output, error = proc.communicate(input=input_data, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    input_data = None
            if proc.returncode:
                _failure("VERIFY_PROCESS", "独立验证进程失败：" + error[:1000])
            result = json.loads(output)
            result["workerEvidence"] = {"argv": argv, "returnCode": proc.returncode,
                "stderr": error, "terminationScope": "process_group"}
            return result
        finally:
            _, stopped = _terminate_process_group(proc)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()
            self._update(job_id, verificationTerminationConfirmed=stopped)
            if not stopped:
                _failure("VERIFICATION_UNCERTAIN", "独立验证进程组停止尚未确认。")

    def _publish_generic(self, packet, candidate, expected_revision):
        _, _, _, identifier, now = _core()
        project = self._get("project", packet["projectId"])
        if project["publicationRevision"] != expected_revision:
            _failure("STALE_PUBLICATION", "候选发布基线已过期。")
        snapshot = {"id": identifier("snapshot"), "projectId": project["id"],
            "title": candidate["document"]["title"], "workflow": WORKFLOW,
            "publicationRevision": expected_revision + 1, "sourceCommit": candidate["candidateCommit"],
            "baseCommit": candidate["candidateCommit"], "candidateId": candidate["id"], "jobId": candidate["jobId"],
            "kind": "MVP", "playable": True, "document": candidate["document"], "catalog": candidate["catalog"],
            "verification": candidate["verification"], "decisions": {},
            "summary": "当前对象工程已通过技术检查并被接受为工作台版本。" + ("这是隔离测试结果。" if self.test_data else "用户已记录体验决定。"),
            "testData": self.test_data, "productionAuthorized": self.production_authorized, "createdAt": now()}
        self._put("snapshot", snapshot)
        project.update(snapshotId=snapshot["id"], publicationRevision=snapshot["publicationRevision"])
        if not project.get("titleExplicit"):
            project["title"] = snapshot["title"]
        self._put("project", project)
        return snapshot

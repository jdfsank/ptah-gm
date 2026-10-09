"""Durable local workflow. Browser inputs never choose paths or execution profiles.

The first supported adapter is deliberately bounded to the collect-loop template.
Production decisions originate in the authenticated loopback frontend; probes use
an independent store marked as test data and cannot satisfy a GM production gate.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .codex_driver import CodexDriver, _terminate_process_group
from .frontend_approval import ApprovalContext, consume_frontend_approval

ACTIVE = {
    "QUEUED",
    "DISPATCHING",
    "RUNNING",
    "VERIFYING",
    "PROJECTING",
    "READY_FOR_REVIEW",
    "CANCELLING",
    "CANCEL_REQUESTED",
    "UNCERTAIN",
}
FIELD_MAP = {
    "goalCount": "target_count",
    "durationSeconds": "time_limit",
    "playerSpeed": "player_speed",
}
LIMITS = {
    "goalCount": (1, 8, 3),
    "durationSeconds": (10, 300, 30),
    "playerSpeed": (60, 400, 220),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + "-" + uuid.uuid4().hex


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class WorkflowError(ValueError):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "message": self.message}


def git(path, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Git operation failed: " + result.stderr.strip())
    return result.stdout.strip()


class _ApprovalStore:
    def __init__(self, db):
        self.db = db

    def get(self, event_id):
        row = self.db.execute(
            "SELECT payload FROM approvals WHERE id=?", (event_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def consume_once(self, event_id):
        return (
            self.db.execute(
                "UPDATE approvals SET consumed=1 WHERE id=? AND consumed=0", (event_id,)
            ).rowcount
            == 1
        )


from .generic_workflow import GenericWorkflow


class Coordinator(GenericWorkflow):
    def __init__(
        self, root, state_root=None, test_data=False, driver_factory=None, verifier=None,
        planner_driver_factory=None, generic_driver_factory=None, generic_verifier=None,
    ):
        if type(test_data) is not bool:
            raise ValueError("test_data must be a boolean")
        if not test_data and any(value is not None for value in (
            driver_factory, verifier, planner_driver_factory, generic_driver_factory, generic_verifier
        )):
            raise ValueError("Injected execution and verification are test-only")
        self.root = Path(root).resolve()
        self.state_root = Path(state_root or self.root / ".workbench").resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.state_root.chmod(0o700)
        self.test_data = test_data
        self.production_authorized = not self.test_data
        self._custom_driver = driver_factory is not None
        self.planner_driver_factory = planner_driver_factory
        self.generic_driver_factory = generic_driver_factory
        self.generic_verifier = generic_verifier
        self.driver_factory = driver_factory or (
            lambda path: CodexDriver(
                path,
                timeout=300,
                execution_profile="managed_workspace_write",
                disabled_mcp_servers=["godot-mcp"],
            )
        )
        self._custom_verifier = verifier is not None
        if verifier is None:
            from .verification import verify_project

            verifier = verify_project
        self.verifier = verifier
        self._process_lock = open(self.state_root / "service.lock", "a+")  # noqa: SIM115 -- owned until close()
        try:
            fcntl.flock(self._process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._process_lock.close()
            raise WorkflowError(
                409, "SERVICE_ACTIVE", "同一工作区已有后端运行。"
            ) from exc
        self.lock = threading.RLock()
        self.db_path = self.state_root / "state.sqlite3"
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS entities(kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,payload TEXT NOT NULL,consumed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        self.db.commit()
        self.db_path.chmod(0o600)
        mode = self.db.execute(
            "SELECT value FROM meta WHERE key='test_data'"
        ).fetchone()
        if mode and mode[0] != str(self.test_data):
            self.db.close()
            fcntl.flock(self._process_lock, fcntl.LOCK_UN)
            self._process_lock.close()
            raise WorkflowError(
                409, "MODE_MISMATCH", "测试与生产必须使用不同的工作区存储。"
            )
        with self.transaction():
            identity = self.db.execute(
                "SELECT value FROM meta WHERE key='operator' "
            ).fetchone()
            self.operator_id = identity[0] if identity else identifier("local-operator")
            self.db.execute(
                "INSERT OR IGNORE INTO meta VALUES('operator',?)", (self.operator_id,)
            )
            self.db.execute(
                "INSERT OR IGNORE INTO meta VALUES('test_data',?)",
                (str(self.test_data),),
            )
            for job in self._all("job"):
                if job["status"] in ACTIVE - {"READY_FOR_REVIEW"}:
                    job.update(
                        status="UNCERTAIN",
                        message="服务重启：此前执行的停止状态尚未确认；保留项目独占，禁止重投。",
                    )
                    self._put("job", job)
            for proposal in self._all("proposal"):
                if proposal.get("workflow") == "objects-v1" and proposal["status"] in {
                    "PLANNING", "PLANNING_CANCELLING"
                }:
                    proposal.update(status="PLANNING_UNCERTAIN", summary="服务重启：策划停止状态尚未确认，不自动重新派发。")
                    self._put("proposal", proposal)
        self._threads = {}
        self._cancels = {}
        self._previews = []
        self._closed = False

    @contextlib.contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def _put(self, kind, value):
        self.db.execute(
            "INSERT OR REPLACE INTO entities VALUES(?,?,?)",
            (kind, value["id"], canonical(value)),
        )

    def _get(self, kind, entity_id):
        row = self.db.execute(
            "SELECT payload FROM entities WHERE kind=? AND id=?", (kind, entity_id)
        ).fetchone()
        if row is None:
            raise WorkflowError(404, "NOT_FOUND", "记录不存在。")
        return json.loads(row[0])

    def _all(self, kind):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM entities WHERE kind=? ORDER BY rowid DESC", (kind,)
            )
        ]

    def _operator(self, operator_id):
        if operator_id != self.operator_id:
            raise WorkflowError(403, "OPERATOR", "工作台会话身份不匹配。")

    @staticmethod
    def _revision(value):
        if type(value) is not int or value < 0:
            raise WorkflowError(400, "REVISION", "版本号必须是非负整数。")

    def _available(self, project_id):
        for proposal in self._all("proposal"):
            if proposal["projectId"] == project_id and proposal["status"] in {
                "PLANNING", "PLANNING_CANCELLING", "PLANNING_UNCERTAIN"
            }:
                raise WorkflowError(409, "PROJECT_BUSY", "项目的策划仍在执行或状态待核实。")
        for job in self._all("job"):
            if job["projectId"] == project_id and job["status"] in ACTIVE:
                raise WorkflowError(
                    409,
                    "PROJECT_BUSY",
                    "项目有正在执行、待审阅或状态未知的作业；请先处理该作业。",
                )

    def capabilities(self):
        codex = shutil.which("codex") or next(
            (
                p
                for p in (
                    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                    "/Applications/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                )
                if Path(p).is_file()
            ),
            None,
        )
        ready = lambda enabled, reason: {
            "status": "READY" if enabled else "BLOCKED",
            "reason": reason,
        }
        return {
            "interactiveFrontendConfirmation": ready(
                True,
                "实际工作台确认按版本写入私有 SQLite；测试记录不能进入生产 GM gate。",
            ),
            "sessionDispatch": ready(
                bool(codex),
                "本机新 session，后端预设 workspace-write；权限回调显式拒绝。"
                if codex
                else "Codex CLI 不可用。",
            ),
            "godotVerification": ready(
                Path("/Applications/Godot.app/Contents/MacOS/Godot").is_file(),
                "每个候选独立运行固定引擎测试。",
            ),
            "semanticProjection": ready(
                (self.root / "backend/templates/general_2d/project.godot").is_file()
                or (self.root / "backend/templates/collect_loop/project.godot").is_file(),
                "稳定对象、属性、关系和源绑定；通用 2D 与旧工程分别保持版本契约。",
            ),
        }

    def workspace(self):
        with self.lock:
            packets = self._all("packet")
            packet_lookup = {packet["proposalId"]: packet["id"] for packet in packets}
            proposals = [self._diagnosed_proposal(proposal) for proposal in self._all("proposal")]
            for proposal in proposals:
                if proposal["status"] == "FROZEN" and not proposal.get("packetId"):
                    proposal["packetId"] = packet_lookup.get(proposal["id"])
            return {
                "apiVersion": "objects-v1",
                "workspaceId": "test" if self.test_data else "local",
                "name": "GM 游戏制作工作区",
                "operatorId": self.operator_id,
                "testData": self.test_data,
                "productionAuthorized": self.production_authorized,
                "projects": self._all("project"),
                "jobs": self._all("job"),
                "proposals": proposals,
                "packets": packets,
                "capabilities": self.capabilities(),
            }

    def upload_asset(self, *, operator_id, name, mime_type, data_base64, purpose):
        self._operator(operator_id)
        if purpose not in {"reference", "style", "layout", "asset"}:
            raise WorkflowError(400, "ASSET_PURPOSE", "请指定参考图片的用途。")
        if (
            mime_type not in {"image/png", "image/jpeg", "image/webp"}
            or not isinstance(data_base64, str)
            or len(data_base64) > 8 * 1024 * 1024
        ):
            raise WorkflowError(
                400, "ASSET_TYPE", "只支持不超过 5 MB 的 PNG、JPEG 或 WebP。"
            )
        try:
            raw = base64.b64decode(data_base64, validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError("too large")
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or image.width * image.height > 16000000
                ):
                    raise ValueError("image dimensions")
                actual = {
                    "PNG": "image/png",
                    "JPEG": "image/jpeg",
                    "WEBP": "image/webp",
                }[image.format]
                if actual != mime_type:
                    raise ValueError("mime mismatch")
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise WorkflowError(
                400, "ASSET_INVALID", "图片格式、尺寸或编码不合法。"
            ) from exc
        asset_id = identifier("asset")
        folder = self.state_root / "attachments"
        folder.mkdir(exist_ok=True)
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[
            actual
        ]
        stored = folder / (asset_id + suffix)
        stored.write_bytes(raw)
        stored.chmod(0o600)
        asset = {
            "id": asset_id,
            "name": str(name)[:100],
            "mimeType": actual,
            "purpose": purpose,
            "width": width,
            "height": height,
            "size": len(raw),
            "createdAt": now(),
        }
        with self.transaction():
            self._put("asset", asset)
        return asset

    def asset_file(self, asset_id):
        with self.lock:
            asset = self._get("asset", asset_id)
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[
            asset["mimeType"]
        ]
        return self.state_root / "attachments" / (asset["id"] + suffix), asset[
            "mimeType"
        ]

    def create_concept(
        self,
        *,
        operator_id,
        text,
        project_id=None,
        asset_ids=None,
        expected_publication_revision=None,
        workflow=None,
        change_request=None,
    ):
        self._operator(operator_id)
        with self.lock:
            project_workflow = self._get("project", project_id).get("workflow") if project_id else None
        if workflow not in {None, "objects-v1", "collect-loop-v1"} or (
            project_workflow == "objects-v1" and workflow == "collect-loop-v1"
        ):
            raise WorkflowError(400, "WORKFLOW", "工作流与工程不匹配。")
        if workflow == "objects-v1" or project_workflow == "objects-v1":
            return self.create_generic_concept(operator_id=operator_id, text=text, project_id=project_id,
                asset_ids=asset_ids, expected_publication_revision=expected_publication_revision,
                change_request=change_request)
        if workflow not in {None, "collect-loop-v1"} or change_request is not None:
            raise WorkflowError(400, "WORKFLOW", "不支持的工作流或旧工程的对象修改协议。")
        self._operator(operator_id)
        if expected_publication_revision is not None:
            self._revision(expected_publication_revision)
        if not isinstance(text, str) or len(text) > 8000 or not text.strip():
            raise WorkflowError(400, "CONCEPT", "请提供不超过 8000 字的概念说明。")
        if not isinstance(asset_ids or [], list) or len(asset_ids or []) > 6:
            raise WorkflowError(400, "ASSETS", "每个提案最多六张参考图片。")
        with self.transaction():
            assets = [self._get("asset", aid) for aid in (asset_ids or [])]
            if project_id:
                project = self._get("project", project_id)
                self._available(project_id)
                if (
                    expected_publication_revision is not None
                    and expected_publication_revision != project["publicationRevision"]
                ):
                    raise WorkflowError(
                        409, "STALE_DRAFT", "草稿基线已更新；请先预览并确认重关联。"
                    )
            else:
                project = {
                    "id": identifier("project"),
                    "title": text.strip().splitlines()[0][:60],
                    "templateId": "collect-loop-v1",
                    "publicationRevision": 0,
                    "snapshotId": None,
                    "createdAt": now(),
                }
                self._put("project", project)
            proposal = self._proposal(project, text, assets)
            self._put("proposal", proposal)
            return proposal

    def _proposal(self, project, text, assets):
        initialized = project["snapshotId"] is not None
        snapshot = self._get("snapshot", project["snapshotId"]) if initialized else None
        values = (
            snapshot["decisions"].copy()
            if snapshot
            else {key: limit[2] for key, limit in LIMITS.items()}
        )
        values.update(self._parse(text))
        questions = []
        if not initialized:
            questions.append(
                {
                    "id": "template",
                    "prompt": "当前可制作的 MVP 是 2D 收集挑战：移动、收集、胜负和重试。它能否用于验证你的概念？其他玩法需要新的适配器。",
                    "options": [
                        {"value": "collect-loop", "label": "采用收集挑战验证"},
                        {"value": "unsupported", "label": "保留其他玩法，暂停制作"},
                    ],
                }
            )
        for key, label in (
            ("goalCount", "收集目标数量"),
            ("durationSeconds", "时限（秒）"),
            ("playerSpeed", "移动速度（像素/秒）"),
        ):
            low, high, _ = LIMITS[key]
            questions.append(
                {
                    "id": key,
                    "prompt": f"确认{label}，允许 {low}–{high}；当前建议 {values[key]}。",
                    "options": [{"value": str(values[key]), "label": str(values[key])}],
                }
            )
        if initialized:
            questions.insert(
                0,
                {
                    "id": "scope",
                    "prompt": "本轮只修改收集目标、时限和移动速度。自然语言里的其他要求会保留为未实现意图；是否接受这个精确范围？",
                    "options": [
                        {"value": "parameters", "label": "只制作这三个参数"},
                        {"value": "unsupported", "label": "需要其他能力，暂停制作"},
                    ],
                },
            )
        if assets:
            questions.append(
                {
                    "id": "referenceUse",
                    "prompt": "图片会保留为概念和视觉参考；当前模板用程序图形，无法把图片当成已制作资产。",
                    "options": [
                        {"value": "reference-only", "label": "保留为参考"},
                        {"value": "unsupported", "label": "需要实际美术资产，暂停制作"},
                    ],
                }
            )
        proposal = {
            "id": identifier("proposal"),
            "projectId": project["id"],
            "revision": 1,
            "status": "NEEDS_CLARIFICATION",
            "text": text,
            "summary": "通过收集挑战验证移动、目标、胜负和重试的最小闭环。",
            "templateId": "collect-loop-v1",
            "initializationRequired": not initialized,
            "publicationRevision": project["publicationRevision"],
            "baseCommit": snapshot["sourceCommit"] if snapshot else None,
            "decisions": values,
            "questions": questions,
            "assets": assets,
            "requirements": [
                "方向键/WASD移动",
                "收集全部目标获胜",
                "时限耗尽失败",
                "重试回到初始状态",
            ],
            "acceptance": [
                "独立 Godot 编译/导入及行为测试通过",
                "实际配置与冻结值完全一致",
                "只修改授权文件",
                "候选需要用户决定才发布",
            ],
            "roles": [
                "template initializer"
                if not initialized
                else "bounded parameter producer",
                "independent verifier",
            ],
            "scope": "初始化受控工程；初始化完成后单独确认玩法制作。"
            if not initialized
            else "只修改 config/rules.json 的四个字段。",
            "createdAt": now(),
        }
        proposal.update(self._references(project, snapshot))
        proposal.update(
            testData=self.test_data, productionAuthorized=self.production_authorized
        )
        return proposal

    def _references(self, project, snapshot):
        if snapshot:
            from .gm_integration import spec_ref

            repo = self.state_root / "projects" / project["id"]
            refs = {
                name: "git:blob:"
                + git(repo, "rev-parse", snapshot["sourceCommit"] + ":" + name)
                for name in (
                    "SPEC.md",
                    "PLAN.md",
                    "tests/closed_loop.gd",
                    "project.godot",
                )
            }
            return {
                "sourceRefs": refs,
                "gmSpecRef": spec_ref(repo),
                "templateInventory": {},
            }
        from tools.git_baseline import capture_inventory

        template = self.root / "backend/templates/collect_loop"
        paths = [
            p.relative_to(template).as_posix()
            for p in template.rglob("*")
            if p.is_file() and ".godot" not in p.parts
        ]
        return {
            "sourceRefs": {},
            "gmSpecRef": None,
            "templateInventory": capture_inventory(template, paths),
        }

    @staticmethod
    def _parse(text):
        patterns = {
            "goalCount": r"(?:收集目标|目标数|goalCount|target_count|收集)(?:数量)?\s*(?:调整为|改为|设为|为|[:：=])?\s*(\d+(?:\.\d+)?)",
            "durationSeconds": r"(?:时限|时间限制|durationSeconds|time_limit)(?:[（(]秒[）)])?\s*(?:调整为|改为|设为|为|[:：=])?\s*(\d+(?:\.\d+)?)",
            "playerSpeed": r"(?:移动速度|速度|playerSpeed|player_speed)\s*(?:调整为|改为|设为|为|[:：=])?\s*(\d+(?:\.\d+)?)",
        }
        result = {}
        for key, pattern in patterns.items():
            found = re.findall(pattern, text, re.IGNORECASE)
            if found:
                result[key] = Coordinator._value(key, found[-1])
        return result

    @staticmethod
    def _value(key, value):
        try:
            number = float(value)
        except (ValueError, TypeError) as exc:
            raise WorkflowError(400, "VALUE", "参数需要明确的数字。") from exc
        low, high, _ = LIMITS[key]
        if not low <= number <= high or (
            key == "goalCount" and not number.is_integer()
        ):
            raise WorkflowError(
                400,
                "VALUE_RANGE",
                f"{key} 允许 {low}–{high}"
                + (" 的整数。" if key == "goalCount" else "。"),
            )
        return int(number) if number.is_integer() else number

    def answer_proposal(self, *, operator_id, proposal_id, expected_revision, answers):
        self._operator(operator_id)
        if self.get_proposal(proposal_id).get("workflow") == "objects-v1":
            return self.answer_generic_proposal(operator_id=operator_id, proposal_id=proposal_id,
                expected_revision=expected_revision, answers=answers)
        self._operator(operator_id)
        self._revision(expected_revision)
        if not isinstance(answers, dict) or any(
            type(v) not in (str, int, float) or len(str(v)) > 1000
            for v in answers.values()
        ):
            raise WorkflowError(400, "ANSWERS", "答案格式不合法。")
        with self.transaction():
            proposal = self._get("proposal", proposal_id)
            if (
                proposal["revision"] != expected_revision
                or proposal["status"] != "NEEDS_CLARIFICATION"
            ):
                raise WorkflowError(409, "STALE_PROPOSAL", "提案修订已变化或已经冻结。")
            valid_ids = {q["id"] for q in proposal["questions"]}
            if set(answers) - valid_ids:
                raise WorkflowError(400, "ANSWER_FIELDS", "存在未声明的答案字段。")
            decisions = proposal["decisions"]
            for key, value in answers.items():
                if key in LIMITS:
                    decisions[key] = self._value(key, value)
                elif value == "unsupported":
                    decisions[key] = value
                elif value != {
                    "template": "collect-loop",
                    "scope": "parameters",
                    "referenceUse": "reference-only",
                }.get(key):
                    raise WorkflowError(
                        400,
                        "UNRESOLVED_SCOPE",
                        "请明确选择受支持的范围，或选择暂停制作。",
                    )
                else:
                    decisions[key] = value
            unanswered = [q for q in proposal["questions"] if q["id"] not in answers]
            proposal.update(
                revision=proposal["revision"] + 1,
                questions=unanswered,
                decisions=decisions,
            )
            if "unsupported" in decisions.values():
                proposal.update(
                    status="BLOCKED",
                    questions=[],
                    message="概念超出当前模板能力；已保留意图，没有重新解释为其他玩法。",
                )
            elif not unanswered:
                proposal["status"] = "READY"
            self._put("proposal", proposal)
            return proposal

    def _event(
        self,
        *,
        phase,
        action,
        project_id,
        proposal_id=None,
        packet_id=None,
        job_id=None,
        candidate_id=None,
        revision=None,
        git_spec_ref=None,
        run_id=None,
    ):
        record = {
            "schemaVersion": 1,
            "eventId": identifier("evt"),
            "operatorId": self.operator_id,
            "projectId": project_id,
            "phase": phase,
            "proposalId": proposal_id,
            "packetId": packet_id,
            "jobId": job_id,
            "candidateId": candidate_id,
            "revision": str(revision) if revision is not None else None,
            "gitSpecRef": git_spec_ref,
            "runId": run_id,
            "action": action,
            "createdAt": now(),
            "provenance": {
                "kind": "interactive_frontend",
                "input": "frontend",
                "recordedBy": "approval_service",
            },
        }
        record.update(
            testData=self.test_data, productionAuthorized=self.production_authorized
        )
        self.db.execute(
            "INSERT INTO approvals(id,payload) VALUES(?,?)",
            (record["eventId"], canonical(record)),
        )
        return record

    def _consume(self, record):
        if self.test_data:
            # A test harness may exercise transitions, never production provenance.
            _ApprovalStore(self.db).consume_once(record["eventId"])
            return
        context = ApprovalContext(
            self.operator_id,
            record["projectId"],
            record["phase"],
            record["proposalId"],
            record["packetId"],
            record["jobId"],
            record["candidateId"],
            record["revision"],
            record["gitSpecRef"],
            record["runId"],
        )
        consume_frontend_approval(
            {"eventId": record["eventId"]}, context, _ApprovalStore(self.db)
        )

    def freeze_proposal(
        self,
        *,
        operator_id,
        proposal_id,
        expected_revision,
        expected_publication_revision,
        reviewed_proposal,
    ):
        self._operator(operator_id)
        if self.get_proposal(proposal_id).get("workflow") == "objects-v1":
            return self.freeze_generic_proposal(operator_id=operator_id, proposal_id=proposal_id,
                expected_revision=expected_revision, expected_publication_revision=expected_publication_revision,
                reviewed_proposal=reviewed_proposal)
        self._operator(operator_id)
        self._revision(expected_revision)
        self._revision(expected_publication_revision)
        with self.transaction():
            proposal = self._get("proposal", proposal_id)
            if proposal["status"] == "FROZEN" and proposal.get("packetId"):
                frozen = self._get("packet", proposal["packetId"])
                if (
                    frozen["approvedProposal"] == reviewed_proposal
                    and frozen["proposalRevision"] == expected_revision
                    and frozen["publicationRevision"] == expected_publication_revision
                ):
                    return frozen
            if (
                proposal != reviewed_proposal
                or proposal["revision"] != expected_revision
                or proposal["status"] != "READY"
            ):
                raise WorkflowError(
                    409, "REVIEW_MISMATCH", "当前提案与实际审阅版本不一致。"
                )
            project = self._get("project", proposal["projectId"])
            self._available(project["id"])
            if (
                expected_publication_revision != project["publicationRevision"]
                or proposal["publicationRevision"] != expected_publication_revision
            ):
                raise WorkflowError(409, "STALE_PUBLICATION", "发布基线已变化。")
            packet_id, job_id = identifier("packet"), identifier("job")
            operation = (
                "INITIALIZATION"
                if proposal["initializationRequired"]
                else "IMPLEMENTATION"
            )
            snapshot = (
                self._get("snapshot", project["snapshotId"])
                if project["snapshotId"]
                else None
            )
            current_refs = self._references(project, snapshot)
            if any(proposal.get(key) != value for key, value in current_refs.items()):
                raise WorkflowError(
                    409,
                    "REVIEW_SOURCE_DRIFT",
                    "模板、规格或测试引用在审阅后已变化，请重新生成并审阅提案。",
                )
            source_refs = current_refs["sourceRefs"]
            template_inventory = current_refs["templateInventory"]
            gm_spec_ref = current_refs["gmSpecRef"]
            record = self._event(
                phase="initialize"
                if operation == "INITIALIZATION"
                else "specification",
                action="initialize" if operation == "INITIALIZATION" else "approve",
                project_id=project["id"],
                proposal_id=proposal_id,
                packet_id=packet_id,
                job_id=job_id,
                revision=expected_revision,
                git_spec_ref=gm_spec_ref,
            )
            rules = {FIELD_MAP[key]: proposal["decisions"][key] for key in FIELD_MAP}
            rules["initialized"] = operation == "IMPLEMENTATION"
            desired_rules = rules.copy()
            if operation == "INITIALIZATION":
                rules = {FIELD_MAP[key]: LIMITS[key][2] for key in FIELD_MAP}
                rules["initialized"] = False
            packet = {
                "id": packet_id,
                "packetId": packet_id,
                "jobId": job_id,
                "projectId": project["id"],
                "proposalId": proposal_id,
                "proposalRevision": expected_revision,
                "publicationRevision": expected_publication_revision,
                "operationKind": operation,
                "baseCommit": proposal["baseCommit"],
                "sourceRefs": source_refs,
                "templateInventory": template_inventory,
                "gmSpecRef": gm_spec_ref,
                "templateId": "collect-loop-v1",
                "decisions": proposal["decisions"],
                "expectedRules": rules,
                "desiredImplementationRules": desired_rules,
                "scope": proposal["scope"],
                "requirements": proposal["requirements"],
                "roles": proposal["roles"],
                "acceptance": proposal["acceptance"],
                "assets": proposal["assets"],
                "approvalEventId": record["eventId"],
                "testData": self.test_data,
                "productionAuthorized": self.production_authorized,
                "createdAt": now(),
            }
            packet["approvedProposal"] = proposal.copy()
            if len(canonical(packet).encode()) > 65536:
                raise WorkflowError(400, "PACKET_SIZE", "制作表单超过受控大小。")
            self._put("packet", packet)
            proposal["status"] = "FROZEN"
            proposal["packetId"] = packet_id
            self._put("proposal", proposal)
            return packet

    def create_job(self, *, operator_id, packet_id, idempotency_key):
        self._operator(operator_id)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
            raise WorkflowError(400, "IDEMPOTENCY", "需要固定的派发意图编号。")
        with self.transaction():
            packet = self._get("packet", packet_id)
            for existing in self._all("job"):
                if existing["packetId"] == packet_id:
                    if existing["idempotencyKey"] != idempotency_key:
                        raise WorkflowError(
                            409, "INTENT_REPLAY", "该表单已派发，不能创建第二个作业。"
                        )
                    return existing
                if existing["idempotencyKey"] == idempotency_key:
                    raise WorkflowError(
                        409, "IDEMPOTENCY_CONFLICT", "意图编号已经绑定其他表单。"
                    )
            self._available(packet["projectId"])
            project = self._get("project", packet["projectId"])
            if project["publicationRevision"] != packet["publicationRevision"]:
                raise WorkflowError(
                    409, "STALE_PACKET", "冻结表单基线已变化，请重新审阅。"
                )
            approval = _ApprovalStore(self.db).get(packet["approvalEventId"])
            if self.test_data or packet["operationKind"] == "INITIALIZATION":
                self._consume(approval)
            job = {
                "id": packet["jobId"],
                "packetId": packet_id,
                "projectId": packet["projectId"],
                "operationKind": packet["operationKind"],
                "workflow": packet.get("workflow", "collect-loop-v1"),
                "status": "QUEUED",
                "idempotencyKey": idempotency_key,
                "createdAt": now(),
                "message": "等待建立新的制作 session。",
                "testData": self.test_data,
                "productionAuthorized": self.production_authorized,
            }
            self._put("job", job)
        cancel = threading.Event()
        thread = threading.Thread(
            target=self._execute_generic if packet.get("workflow") == "objects-v1" else self._execute,
            args=(job["id"], cancel), daemon=True
        )
        with self.lock:
            self._cancels[job["id"]] = cancel
            self._threads[job["id"]] = thread
            thread.start()
        return job

    def get_job(self, job_id):
        with self.lock:
            return self._get("job", job_id)

    def _update(self, job_id, **fields):
        with self.transaction():
            job = self._get("job", job_id)
            job.update(fields)
            self._put("job", job)
            return job

    def _check_cancel(self, job_id, cancel):
        if cancel.is_set():
            self._update(
                job_id, status="CANCELLED", message="已确认制作进程停止，没有发布结果。"
            )
            return True
        return False

    def _execute(self, job_id, cancel):
        producer_started = False
        termination_confirmed = False
        try:
            with self.lock:
                job = self._get("job", job_id)
                packet = self._get("packet", job["packetId"])
            if self._check_cancel(job_id, cancel):
                return
            self._update(
                job_id, status="DISPATCHING", message="准备 Git 隔离工程和不可变表单。"
            )
            repo = self.state_root / "projects" / packet["projectId"]
            if packet["operationKind"] == "INITIALIZATION":
                from tools.git_baseline import capture_inventory

                template = self.root / "backend/templates/collect_loop"
                current_paths = [
                    p.relative_to(template).as_posix()
                    for p in template.rglob("*")
                    if p.is_file() and ".godot" not in p.parts
                ]
                if (
                    capture_inventory(template, current_paths)
                    != packet["templateInventory"]
                ):
                    raise WorkflowError(
                        409, "TEMPLATE_DRIFT", "受控模板在确认后已变化，必须重新审阅。"
                    )
                if repo.exists():
                    with self.lock:
                        saved_base = self._get("project", packet["projectId"]).get(
                            "trustedBaseline"
                        )
                    if (
                        not saved_base
                        or git(repo, "rev-parse", "HEAD") != saved_base
                        or git(repo, "status", "--porcelain")
                    ):
                        raise WorkflowError(
                            409, "INIT_DIRTY", "工程准备基线已变化，需要检查前次作业。"
                        )
                else:
                    shutil.copytree(
                        self.root / "backend/templates/collect_loop",
                        repo,
                        ignore=shutil.ignore_patterns(".godot", "__pycache__"),
                    )
                    git(repo, "init", "-b", "main")
                    git(repo, "config", "user.name", "Ptah Local Workflow")
                    git(repo, "config", "user.email", "workflow@localhost")
                    git(repo, "add", ".")
                    git(
                        repo,
                        "commit",
                        "-m",
                        "Prepare trusted nonplayable collect-loop baseline",
                    )
                base = git(repo, "rev-parse", "HEAD")
                with self.transaction():
                    prepared = self._get("project", packet["projectId"])
                    prepared["trustedBaseline"] = base
                    self._put("project", prepared)
            else:
                base = packet["baseCommit"]
                for name, expected in packet["sourceRefs"].items():
                    if (
                        "git:blob:" + git(repo, "rev-parse", base + ":" + name)
                        != expected
                    ):
                        raise WorkflowError(
                            409, "SOURCE_DRIFT", "规格或测试 Git 引用不一致。"
                        )
            job_folder = self.state_root / "jobs" / job_id
            job_folder.mkdir(parents=True)
            worktree = job_folder / "worktree"
            git(repo, "worktree", "add", "--detach", str(worktree), base)
            (job_folder / "packet.json").write_text(canonical(packet) + "\n")
            protected = {}
            if packet["operationKind"] == "IMPLEMENTATION":
                from .gm_integration import confirm_spec, register, spec_confirmed

                register(
                    worktree,
                    self.db_path,
                    self.operator_id,
                    packet["projectId"],
                    packet,
                )
                if self.test_data:
                    gm_confirmation = {
                        "status": "BLOCKED",
                        "testData": True,
                        "productionAuthorized": False,
                        "message": "Test records deliberately cannot confirm the production GM spec gate.",
                    }
                    if spec_confirmed(worktree):
                        raise WorkflowError(
                            409, "TEST_GATE", "测试记录不得通过生产规格确认。"
                        )
                else:
                    gm_confirmation = confirm_spec(worktree, packet["approvalEventId"])
                    if not spec_confirmed(worktree):
                        raise WorkflowError(
                            409, "GM_GATE", "真实 GM 规格确认没有满足当前版本。"
                        )
                self._update(job_id, gmSpecificationConfirmation=gm_confirmation)
                for relative in (
                    ".godotmaker/frontend-approval.json",
                    ".godotmaker/stage.jsonl",
                ):
                    owned = worktree / relative
                    if owned.exists():
                        protected[relative] = owned.read_bytes()
            production_packet = dict(packet)
            if packet["operationKind"] == "INITIALIZATION":
                allowed = "initialization.json"
                content = {
                    "templateId": "collect-loop-v1",
                    "operationKind": "INITIALIZATION",
                    "projectId": packet["projectId"],
                    "prepared": True,
                }
                production_packet["instruction"] = (
                    "Create only initialization.json with the exact expectedContent. Do not implement gameplay or change any other tracked file. Do not run tests or checksum scripts. Reply with changed path."
                )
            else:
                allowed, content = "config/rules.json", packet["expectedRules"]
                production_packet["instruction"] = (
                    "Read SPEC.md and PLAN.md as project requirements. Update only config/rules.json to exact expectedContent. Do not change tests, specs, scenes, permissions, Git history or any other file. Do not run tests or checksum scripts. Verification is a separate backend stage. Reply with changed path."
                )
            production_packet.update(allowedFiles=[allowed], expectedContent=content)
            self._update(
                job_id,
                status="RUNNING",
                baseCommit=base,
                message="已派发新的受控制作 session。",
            )
            driver = self.driver_factory(worktree)
            references = [self.asset_file(asset["id"])[0] for asset in packet["assets"]]
            producer_started = True
            result = driver.run(
                production_packet,
                cancel_event=cancel,
                reference_images=references,
                on_process_started=lambda lease: self._update(
                    job_id, executionLease=lease
                ),
            )
            (job_folder / "session.json").write_text(canonical(result) + "\n")
            diagnostics = result.get("diagnostics", {})
            termination_confirmed = diagnostics.get("childTerminationConfirmed", False)
            self._update(
                job_id, sessionId=result.get("sessionId"), sessionEvidence=result
            )
            if not diagnostics.get("childTerminationConfirmed", False):
                self._update(
                    job_id,
                    status="UNCERTAIN",
                    message="制作进程停止尚未确认，项目继续独占。",
                )
                return
            if self._check_cancel(job_id, cancel):
                return
            if result.get("status") != "completed":
                self._update(
                    job_id,
                    status="BLOCKED"
                    if result.get("status") == "approval_denied"
                    else "FAILED",
                    message="制作 session 未完成；没有运行或发布候选。",
                )
                return
            self._audit(worktree, base, allowed, content, protected)
            self._update(
                job_id,
                status="VERIFYING",
                message="制作已结束，后端独立执行 Godot 验证。",
            )
            verification = (
                self.verifier(
                    worktree, packet["operationKind"], packet["expectedRules"]
                )
                if self._custom_verifier
                else self._verify_owned(
                    job_id,
                    worktree,
                    packet["operationKind"],
                    packet["expectedRules"],
                    base,
                    cancel,
                )
            )
            verification.update(
                runId=identifier("run"),
                testData=self.test_data,
                productionAuthorized=self.production_authorized,
                certificationScope="collect-loop-v1 independent backend verification; not GM-wide certification",
            )
            (job_folder / "verification.json").write_text(
                canonical(verification) + "\n"
            )
            self._update(job_id, verification=verification)
            if self._check_cancel(job_id, cancel):
                return
            if verification.get("status") != "PASS":
                self._update(
                    job_id,
                    status="FAILED",
                    message="独立运行验证未通过，没有发布候选。",
                )
                return
            self._audit(
                worktree, base, allowed, content, protected, allow_engine_cache=True
            )
            git(worktree, "add", "--", allowed)
            git(
                worktree,
                "commit",
                "--allow-empty",
                "-m",
                packet["operationKind"] + " " + job_id,
            )
            commit = git(worktree, "rev-parse", "HEAD")
            verification["sourceCommit"] = commit
            (job_folder / "verification.json").write_text(
                canonical(verification) + "\n"
            )
            catalog = self._catalog(
                commit, packet["expectedRules"], packet["operationKind"]
            )
            candidate = {
                "id": identifier("candidate"),
                "jobId": job_id,
                "projectId": packet["projectId"],
                "candidateCommit": commit,
                "catalog": catalog,
                "catalogStatus": "READY",
                "capabilities": catalog["capabilities"],
                "verification": verification,
                "summary": "工程准备已验证；等待玩法提案。"
                if packet["operationKind"] == "INITIALIZATION"
                else "收集挑战已验证，等待工作台体验决定。",
                "previewAvailable": packet["operationKind"] == "IMPLEMENTATION",
                "rules": packet["expectedRules"],
                "createdAt": now(),
                "testData": self.test_data,
                "productionAuthorized": self.production_authorized,
            }
            with self.transaction():
                current = self._get("job", job_id)
                if cancel.is_set() or current["status"] in {
                    "CANCELLING",
                    "CANCEL_REQUESTED",
                    "UNCERTAIN",
                }:
                    current.update(
                        status="CANCELLED", message="取消已生效，迟到结果没有发布。"
                    )
                else:
                    current.update(
                        status="READY_FOR_REVIEW",
                        candidate=candidate,
                        verification=verification,
                        message=candidate["summary"],
                    )
                    self._put("candidate", candidate)
                    if packet["operationKind"] == "INITIALIZATION":
                        # Initial confirmation authorizes only this nonplayable preparation snapshot.
                        snapshot = self._publish(
                            packet,
                            candidate,
                            expected_revision=packet["publicationRevision"],
                        )
                        current.update(status="PUBLISHED", snapshot=snapshot)
                        project = self._get("project", packet["projectId"])
                        next_proposal = self._proposal(
                            project, "实现已确认的收集挑战 MVP。", packet["assets"]
                        )
                        next_proposal.update(
                            status="READY",
                            questions=[],
                            decisions=packet["decisions"],
                            summary="在已验证工程中实现收集挑战；精确绑定当前规格和测试。",
                        )
                        self._put("proposal", next_proposal)
                        current["nextProposal"] = next_proposal
                self._put("job", current)
            (job_folder / "candidate.json").write_text(canonical(candidate) + "\n")
        except Exception as exc:  # noqa: BLE001 -- job boundary records failures and preserves uncertain leases
            status = (
                "UNCERTAIN"
                if (producer_started and not termination_confirmed)
                or getattr(exc, "code", None) == "VERIFICATION_UNCERTAIN"
                else ("CANCELLED" if cancel.is_set() else "FAILED")
            )
            self._update(job_id, status=status, message=str(exc)[:1000])

    def _verify_owned(self, job_id, worktree, operation, rules, base, cancel):
        argv = [
            sys.executable,
            "-m",
            "backend.verification_worker",
            str(worktree),
            operation,
        ]
        proc = subprocess.Popen(
            argv,
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        verified = None
        output = error = ""
        try:
            self._update(
                job_id,
                verificationLease={
                    "pid": proc.pid,
                    "processGroupId": proc.pid,
                    "startedAt": now(),
                    "cwd": str(worktree),
                    "argv": argv,
                },
            )
            deadline = time.monotonic() + 110
            input_data = canonical({"expectedRules": rules, "baseCommit": base})
            while True:
                if cancel.is_set():
                    raise WorkflowError(
                        409,
                        "VERIFY_CANCELLED",
                        "已请求停止验证进程，等待整个进程组退出。",
                    )
                if time.monotonic() >= deadline:
                    raise WorkflowError(
                        409, "VERIFY_TIMEOUT", "独立验证超时，没有发布结果。"
                    )
                try:
                    output, error = proc.communicate(input=input_data, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    input_data = None
            if proc.returncode:
                raise WorkflowError(
                    409, "VERIFY_PROCESS", "独立验证进程失败：" + error[:500]
                )
            verified = json.loads(output)
            verified["workerEvidence"] = {
                "argv": argv,
                "cwd": str(self.root),
                "returnCode": proc.returncode,
                "stderr": error,
                "terminationScope": "process_group",
            }
            return verified
        finally:
            _, stopped = _terminate_process_group(proc)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()
            self._update(job_id, verificationTerminationConfirmed=stopped)
            if not stopped:
                raise WorkflowError(
                    409,
                    "VERIFICATION_UNCERTAIN",
                    "验证进程组停止尚未确认，项目继续独占。",
                )

    @staticmethod
    def _audit(
        worktree, base, allowed, content, protected=None, *, allow_engine_cache=False
    ):
        protected = protected or {}
        if git(worktree, "rev-parse", "HEAD") != base:
            raise WorkflowError(409, "GIT_HISTORY", "制作过程改动了 Git 基线。")
        changed = set(
            filter(None, git(worktree, "diff", "--name-only", base).splitlines())
        )
        untracked = set(
            filter(
                None,
                git(
                    worktree, "ls-files", "--others", "--exclude-standard"
                ).splitlines(),
            )
        )
        if (changed | untracked) - {allowed}:
            raise WorkflowError(
                409,
                "WRITE_SCOPE",
                "存在越界、增加或删除文件："
                + ", ".join(sorted((changed | untracked) - {allowed})),
            )
        file = worktree / allowed
        if (
            file.is_symlink()
            or not file.is_file()
            or file.resolve().parent != (worktree / allowed).absolute().parent
        ):
            raise WorkflowError(409, "FILE_SCOPE", "授权文件缺失或通过链接越界。")
        if json.loads(file.read_text()) != content:
            raise WorkflowError(409, "CONFIG_MISMATCH", "实际配置与冻结表单不一致。")
        # Only the independent verifier may create ignored Godot caches.
        for ignored in filter(
            None,
            git(
                worktree, "ls-files", "--others", "--ignored", "--exclude-standard"
            ).splitlines(),
        ):
            if (
                not (allow_engine_cache and ignored.startswith(".godot/"))
                and ignored not in protected
            ):
                raise WorkflowError(
                    409, "IGNORED_SCOPE", "出现未授权的忽略文件：" + ignored
                )
        for relative, original in protected.items():
            owned = worktree / relative
            if (
                owned.is_symlink()
                or not owned.is_file()
                or owned.read_bytes() != original
            ):
                raise WorkflowError(
                    409, "APPROVAL_DRIFT", "后端规格确认文件被制作进程改动。"
                )

    @staticmethod
    def _catalog(commit, rules, operation):
        capabilities = [
            {
                "id": key,
                "label": label,
                "editable": operation == "IMPLEMENTATION",
                "supported": True,
                "min": LIMITS[key][0],
                "max": LIMITS[key][1],
                "sourcePath": "config/rules.json",
                "pointer": "/" + FIELD_MAP[key],
            }
            for key, label in (
                ("goalCount", "收集目标"),
                ("durationSeconds", "时限"),
                ("playerSpeed", "移动速度"),
            )
        ]
        return {
            "schemaVersion": 1,
            "sourceCommit": commit,
            "templateId": "collect-loop-v1",
            "resolverRevision": "collect-loop-resolver-v1",
            "objects": [
                {
                    "id": "collect-loop",
                    "name": "收集挑战",
                    "editable": operation == "IMPLEMENTATION",
                }
            ],
            "capabilities": capabilities,
        }

    def _publish(self, packet, candidate, expected_revision):
        if packet.get("workflow") == "objects-v1":
            return self._publish_generic(packet, candidate, expected_revision)
        project = self._get("project", packet["projectId"])
        if project["publicationRevision"] != expected_revision:
            raise WorkflowError(409, "STALE_PUBLICATION", "候选基线已过期，无法发布。")
        snapshot = {
            "id": identifier("snapshot"),
            "projectId": project["id"],
            "title": project["title"],
            "publicationRevision": expected_revision + 1,
            "sourceCommit": candidate["candidateCommit"],
            "baseCommit": candidate["candidateCommit"],
            "candidateId": candidate["id"],
            "jobId": candidate["jobId"],
            "kind": "INITIALIZATION"
            if packet["operationKind"] == "INITIALIZATION"
            else "MVP",
            "playable": packet["operationKind"] == "IMPLEMENTATION",
            "catalog": candidate["catalog"],
            "verification": candidate["verification"],
            "decisions": {key: candidate["rules"][FIELD_MAP[key]] for key in FIELD_MAP},
            "summary": (
                "工程准备已独立验证，下一步是确认 MVP 制作表单。"
                if packet["operationKind"] == "INITIALIZATION"
                else "当前收集挑战版本已通过独立验证。"
                + (
                    "此发布为测试流程结果，尚未得到实际用户体验验收。"
                    if self.test_data
                    else "用户已在工作台接受此版本。"
                )
            ),
            "testData": self.test_data,
            "productionAuthorized": self.production_authorized,
            "createdAt": now(),
        }
        self._put("snapshot", snapshot)
        project.update(
            snapshotId=snapshot["id"],
            publicationRevision=snapshot["publicationRevision"],
        )
        self._put("project", project)
        return snapshot

    def decide_job(
        self,
        *,
        operator_id,
        job_id,
        decision,
        candidate_commit,
        expected_publication_revision,
    ):
        self._operator(operator_id)
        self._revision(expected_publication_revision)
        if decision not in {"accept", "reject"}:
            raise WorkflowError(400, "DECISION", "请选择接受或拒绝。")
        with self.transaction():
            job = self._get("job", job_id)
            candidate = job.get("candidate", {})
            packet = self._get("packet", job["packetId"])
            project = self._get("project", job["projectId"])
            if (
                job["status"] != "READY_FOR_REVIEW"
                or candidate.get("candidateCommit") != candidate_commit
            ):
                raise WorkflowError(
                    409, "CANDIDATE_MISMATCH", "候选版本与实际审阅结果不一致。"
                )
            if (
                project["publicationRevision"] != expected_publication_revision
                or packet["publicationRevision"] != expected_publication_revision
            ):
                raise WorkflowError(409, "STALE_PUBLICATION", "发布基线已变化。")
            worktree = self.state_root / "jobs" / job_id / "worktree"
            if decision == "accept" and (
                git(worktree, "rev-parse", "HEAD") != candidate_commit
                or git(worktree, "status", "--porcelain")
            ):
                raise WorkflowError(
                    409, "CANDIDATE_DIRTY", "候选源文件已变化，需重新验证。"
                )
            event = self._event(
                phase="run_acceptance",
                action="accept" if decision == "accept" else "changes_requested",
                project_id=project["id"],
                proposal_id=packet["proposalId"],
                packet_id=packet["id"],
                job_id=job_id,
                candidate_id=candidate["id"],
                revision=packet["proposalRevision"],
                git_spec_ref=packet.get("gmSpecRef"),
                run_id=candidate["verification"]["runId"],
            )
            self._consume(event)
            job["decisionEventId"] = event["eventId"]
            if decision == "accept":
                job.update(
                    status="PUBLISHED",
                    snapshot=self._publish(
                        packet, candidate, expected_publication_revision
                    ),
                    message="已记录实际工作台决定并原子发布完整版本。",
                )
            else:
                job.update(
                    status="REJECTED", message="候选已拒绝，原发布版本继续有效。"
                )
            self._put("job", job)
            return {"job": job, "snapshot": job.get("snapshot")}

    def workbench(self, project_id):
        with self.lock:
            project = self._get("project", project_id)
            snapshot = (
                self._get("snapshot", project["snapshotId"])
                if project["snapshotId"]
                else {
                    "projectId": project_id,
                    "workflow": project.get("workflow", "collect-loop-v1"),
                    "title": project["title"],
                    "publicationRevision": 0,
                    "kind": "CONCEPT",
                    "playable": False,
                    "summary": "工程尚未初始化。",
                    "decisions": {},
                }
            )
            fields = snapshot.get("catalog", {}).get("capabilities", [])
            candidates = [
                dict(job["candidate"], status=job["status"])
                for job in self._all("job")
                if job["projectId"] == project_id
                and job["status"] == "READY_FOR_REVIEW"
            ]
            return {
                "workflow": project.get("workflow", "collect-loop-v1"),
                "snapshot": snapshot,
                "capabilities": {"fields": fields},
                "candidates": candidates,
            }

    def cancel_job(self, *, operator_id, job_id):
        self._operator(operator_id)
        with self.transaction():
            job = self._get("job", job_id)
            if job["status"] == "READY_FOR_REVIEW":
                job.update(status="CANCELLED", message="候选已取消，没有发布。")
            elif job["status"] in ACTIVE:
                job.update(
                    status="CANCELLING",
                    message="正在请求停止；确认进程退出前保留项目独占。",
                )
                cancel = self._cancels.get(job_id)
                if cancel:
                    cancel.set()
                else:
                    job.update(
                        status="UNCERTAIN",
                        message="前次执行停止尚未确认，项目继续独占；不能自动重投。",
                    )
            self._put("job", job)
            return job

    def reconcile_job(self, *, operator_id, job_id):
        """Observe a recorded process group; the browser cannot attest termination."""
        self._operator(operator_id)
        with self.transaction():
            job = self._get("job", job_id)
            if job["status"] != "UNCERTAIN":
                raise WorkflowError(
                    409, "NOT_UNCERTAIN", "只有执行状态未知的作业需要核实。"
                )
            if job_id in self._threads and self._threads[job_id].is_alive():
                raise WorkflowError(
                    409, "EXECUTION_ACTIVE", "本次执行线程仍在运行，不能解除独占。"
                )
            lease = job.get("executionLease") or {}
            leases = [lease]
            if job.get("verificationLease"):
                leases.append(job["verificationLease"])
            groups = [item.get("processGroupId") for item in leases]
            if any(
                type(pgid) is not int or pgid <= 1 or pgid == os.getpgrp()
                for pgid in groups
            ):
                raise WorkflowError(
                    409,
                    "LEASE_UNKNOWN",
                    "没有可信进程组记录，不能自动确认停止。请保留该项目并由本机操作者检查。",
                )
            for pgid in groups:
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    raise WorkflowError(
                        409,
                        "LEASE_UNOBSERVABLE",
                        "无法核实该进程组，继续保留项目独占。",
                    ) from None
                raise WorkflowError(
                    409,
                    "LEASE_ACTIVE",
                    "记录的进程组仍存在。请停止原制作或验证进程后再核实；后端不会重投或终止无关进程。",
                )
            job.update(
                status="CANCELLED",
                message="后端已核实原制作和验证进程组消失；迟到结果丢弃，项目独占已解除。",
                reconciledAt=now(),
            )
            self._put("job", job)
            return job

    def preview_job(self, *, operator_id, job_id):
        self._operator(operator_id)
        with self.lock:
            job = self._get("job", job_id)
            candidate = job.get("candidate", {})
            if (
                job["status"] not in {"READY_FOR_REVIEW", "PUBLISHED"}
                or not candidate.get("previewAvailable")
                or candidate["verification"]["status"] != "PASS"
            ):
                raise WorkflowError(
                    409, "PREVIEW_UNVERIFIED", "只有通过独立验证的玩法候选可以预览。"
                )
            if any(p.poll() is None for p in self._previews):
                raise WorkflowError(
                    409, "PREVIEW_RUNNING", "已有本机预览窗口，请先关闭。"
                )
            folder = self.state_root / "previews" / identifier("preview")
            folder.mkdir(parents=True)
            repo = self.state_root / "projects" / job["projectId"]
            import tarfile

            archive = subprocess.run(
                ["git", "archive", candidate["candidateCommit"]],
                cwd=repo,
                capture_output=True,
                timeout=30,
                check=True,
            ).stdout
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                # Trusted template contains no links and only bounded project files.
                for member in tar.getmembers():
                    if (
                        member.issym()
                        or member.islnk()
                        or Path(member.name).is_absolute()
                        or ".." in Path(member.name).parts
                    ):
                        raise WorkflowError(
                            409, "ARCHIVE_SCOPE", "Git 预览包含越界路径。"
                        )
                tar.extractall(folder)
            with open(folder / "preview.log", "w") as log:
                proc = subprocess.Popen(
                    [
                        "/Applications/Godot.app/Contents/MacOS/Godot",
                        "--path",
                        str(folder),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            self._previews.append(proc)

            def expire_preview():
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()

            timer = threading.Timer(900, expire_preview)
            timer.daemon = True
            timer.start()
            return {
                "status": "RUNNING",
                "message": "已打开当前 Git 候选的本机 Godot 预览。",
                "sourceCommit": candidate["candidateCommit"],
            }

    def wait(self, job_id, timeout=60):
        thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout)
        return self.get_job(job_id)

    def close(self):
        if self._closed:
            return
        self._closed = True
        for cancel in self._cancels.values():
            cancel.set()
        for thread in self._threads.values():
            thread.join(10)
        for proc in self._previews:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if any(t.is_alive() for t in self._threads.values()):
            # The lock and DB remain until execution exits; never start a second service.
            return
        with self.lock:
            self.db.close()
            fcntl.flock(self._process_lock, fcntl.LOCK_UN)
            self._process_lock.close()

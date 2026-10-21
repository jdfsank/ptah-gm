"""Read-only image planning, with ownership independent of game proposals."""
from __future__ import annotations

import copy
import json
import re

from .visual_planning import validate_image_plan, visual_plan_instructions


class VisualPlans:
    def visual_plans(self, project_id):
        with self.lock:
            self._get("project", project_id)
            return [self._public_visual_plan(p) for p in self._all_project("visual-plan", project_id)]

    @staticmethod
    def _public_visual_plan(record):
        return copy.deepcopy({k: v for k, v in record.items() if k != "inputSnapshot"})

    def _check_visual_source(self, project_id, source):
        from .coordinator import WorkflowError
        if not isinstance(source, dict) or not isinstance(source.get("proposalId"), str):
            raise WorkflowError(400, "REFERENCE_SOURCE", "请提供服务端返回的视觉来源。")
        context = self.visual_planning_context(project_id, source["proposalId"])
        if context["source"] != source:
            raise WorkflowError(409, "REFERENCE_SOURCE_STALE", "策划反馈或方案版本已变化，请重新核对后规划或生成。")
        return context

    def create_visual_plan(self, *, operator_id, project_id, request):
        from .coordinator import WorkflowError, now
        self._operator(operator_id)
        if (not isinstance(request, dict) or set(request) != {"requestId", "source", "preferencesRevision"} or
                not isinstance(request["requestId"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request["requestId"]) or
                type(request["preferencesRevision"]) is not int):
            raise WorkflowError(400, "VISUAL_PLAN_REQUEST", "请提供完整的视觉规划请求及设置版本。")
        with self.transaction():
            row = self.db.execute("SELECT payload FROM entities WHERE kind='visual-plan' AND id=?", (request["requestId"],)).fetchone()
            if row:
                old = json.loads(row[0])
                if old["projectId"] != project_id or old.get("request") != request:
                    raise WorkflowError(409, "VISUAL_PLAN_ID_REUSED", "视觉规划编号已绑定其他内容。")
                return self._public_visual_plan(old)
            if self._get("project", project_id).get("archived"):
                raise WorkflowError(409, "PROJECT_ARCHIVED", "归档项目只允许查看。")
            context = self._check_visual_source(project_id, request["source"])
            if any(a["taskKind"] in {"plan", "visual-plan"} and a["status"] not in {"COMPLETED", "FAILED", "STOPPED"}
                   for a in self._all_project("attempt", project_id)):
                raise WorkflowError(409, "VISUAL_PLAN_PENDING", "本项目已有未结束的策划请求，请先查看或核实原请求。")
            profile = self._resolve_profile(project_id, "planner", {"preferencesRevision": request["preferencesRevision"]}, [])
            record = {"id": request["requestId"], "projectId": project_id, "source": copy.deepcopy(context["source"]),
                      "request": copy.deepcopy(request), "inputSnapshot": context, "status": "QUEUED", "createdAt": now(),
                      "message": "只读视觉规划已排队；尚未生成图片。"}
            attempt = self._new_attempt(project_id, "visual-plan", {"kind": "visual-plan", "id": record["id"]},
                profile["runnerId"], profile, {"visualPlanId": record["id"], "assetRefs": []},
                {"mode": "inspection_only", "targetObjectIds": [], "allowProjectExecution": False})
            record["attemptId"] = attempt["id"]
            self._put("visual-plan", record)
            return self._public_visual_plan(record)

    def _visual_plan_input(self, attempt):
        record = self.require_project_resource(attempt["projectId"], "visual-plan", attempt["ownerRef"]["id"])
        self._check_visual_source(attempt["projectId"], record["source"])
        return {"packet": {"operationKind": "VISUAL_PLANNING", "allowedFiles": [],
                "instruction": "You are a read-only visual planner. Return exactly one strict JSON visualPlan object. "
                    "Do not change the game design or execute any tools." + visual_plan_instructions(),
                "imageMaterials": record["inputSnapshot"]["imageMaterials"]}}

    def _complete_visual_plan(self, attempt, payload):
        from .object_protocol import _strict_json
        from .coordinator import now
        record = self.require_project_resource(attempt["projectId"], "visual-plan", attempt["ownerRef"]["id"])
        native = payload["result"]
        response = native["response"] if isinstance(native, dict) and set(native) == {"response"} else native
        response = _strict_json(response) if isinstance(response, str) else response
        result = validate_image_plan(response, record["inputSnapshot"])
        record.update(status="READY", result=result, completedAt=now(), message="分图计划已完成；请检查并确认要生成的图片。")
        self._put("visual-plan", record)

    def _store_inline_visual_plan(self, proposal, value):
        from .coordinator import identifier, now
        from .object_protocol import ObjectProtocolError
        context = self.visual_planning_context(proposal["projectId"], proposal["id"])
        record = {"id": identifier("visual-plan"), "projectId": proposal["projectId"], "source": context["source"],
                  "inputSnapshot": context, "createdAt": now(), "origin": "planner-feedback"}
        try:
            record.update(result=validate_image_plan(value, context), status="READY", message="本轮策划已提供分图计划。")
        except (ObjectProtocolError, TypeError, ValueError) as exc:
            record.update(status="FAILED", message="文字策划已保留；视觉扩展未通过检查，可主动重新规划。", validationError=str(exc)[:400])
        self._put("visual-plan", record)

    def _visual_plan_owner_state(self, attempt, uncertain=False, failed=False):
        record = self._get("visual-plan", attempt["ownerRef"]["id"])
        record.update(status="UNCERTAIN" if uncertain else "FAILED" if failed or attempt.get("stopReason") in {
            "time_limit", "soft_budget", "native_error"} else "CANCELLED",
            message="视觉规划停止状态待核实，请核实原请求。" if uncertain else "视觉规划已停止；文字方案保持原版本。",
            diagnosticRef=attempt.get("diagnosticRef"), retryNotBefore=attempt.get("retryNotBefore"))
        self._put("visual-plan", record)

"""Trusted, durable concept generation; separate from runtime asset bundles.

Only this coordinator calls the existing prompt-to-image CLI. Restart and HTTP
retry never replay a chargeable request. Proposal references are immutable input
snapshots, rather than pointers to a later editor draft.
"""
from __future__ import annotations

import base64
import copy
import json
import re
import threading
from pathlib import Path

from .reference_batches import ReferenceBatches


def validate_visual_references(value, asset_ids):
    from .object_protocol import ObjectProtocolError

    def fail(message):
        raise ObjectProtocolError(message)

    if not isinstance(value, list) or len(value) > 12:
        fail("visualReferences must contain at most twelve reference intents")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"assetId", "intent", "targetObjectIds", "preserve", "unknown"}:
            fail("visualReferences require assetId, intent, targetObjectIds, preserve and unknown")
        aid = item["assetId"]
        if aid is not None and (not isinstance(aid, str) or aid not in asset_ids or aid in seen):
            fail("visualReferences must name distinct selected project assets")
        if aid is not None:
            seen.add(aid)
        for key in ("intent", "preserve", "unknown"):
            if not isinstance(item[key], str) or len(item[key]) > 2000:
                fail("visualReferences text must be bounded")
        if not item["intent"].strip():
            fail("Selected references need an explicit adoption intent")
        targets = item["targetObjectIds"]
        if not isinstance(targets, list) or len(targets) > 100 or any(
            not isinstance(t, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", t) for t in targets
        ) or len(set(targets)) != len(targets):
            fail("visualReferences targetObjectIds are invalid")
        result.append(copy.deepcopy(item))
    if set(asset_ids) != seen:
        fail("Each selected reference needs an adoption intent")
    return result


class ConceptReferences(ReferenceBatches):
    def resolve_visual_references(self, project_id, assets, value, document=None):
        from .coordinator import WorkflowError
        from .object_protocol import ObjectProtocolError

        # Older clients retain their explicit purpose. New clients send a full
        # intent record. Generated images always require explicit adoption.
        if value is None:
            value = [{"assetId": a["id"], "intent": "用户上传用途：" + a.get("purpose", "reference"),
                      "targetObjectIds": [], "preserve": "", "unknown": "未声明的细节不构成制作要求"}
                     for a in assets if not a.get("generation")]
        try:
            result = validate_visual_references(value, [a["id"] for a in assets])
        except ObjectProtocolError as exc:
            raise WorkflowError(400, "REFERENCE_INTENT", str(exc)) from exc
        generated = {a["id"] for a in assets if a.get("generation", {}).get("provenance")}
        if any(r["assetId"] in generated and (not r["preserve"].strip() or not r["unknown"].strip()) for r in result):
            raise WorkflowError(400, "REFERENCE_INTENT", "视觉策划参考需要填写采纳用途、需要保持和尚未确定的内容。")
        known = {o["id"] for o in (document or {}).get("objects", [])}
        if any(t not in known for r in result for t in r["targetObjectIds"]):
            raise WorkflowError(400, "REFERENCE_TARGET", "参考目标不属于当前对象版本。")
        return result

    def _init_concept_references(self):
        self._image_cancel = threading.Event()
        with self.transaction():
            for request in self._all("concept-generation"):
                if request["status"] in {"QUEUED", "RUNNING"}:
                    request.update(status="UNCERTAIN", message="服务重启；请核实原请求，不会自动再次生成。")
                    self._put("concept-generation", request)
            for batch in self._all("reference-batch"):
                if batch["status"] not in {"COMPLETED", "CANCELLED"}:
                    self._sync_batch_results(batch)
                    batch.update(status="PAUSED", message="服务重启，批次已暂停；请先核实原请求，再显式继续。")
                    self._put("reference-batch", batch)

    def concept_generations(self, project_id):
        with self.lock:
            self._get("project", project_id)
            return copy.deepcopy(self._all_project("concept-generation", project_id))

    def visual_planning_context(self, project_id, proposal_id):
        from .visual_planning import context_for

        with self.lock:
            self._get("project", project_id)
            proposal = self.require_project_resource(project_id, "proposal", proposal_id)
            originals = [p for p in self._all_project("proposal", project_id) if not p.get("changeRequest")]
            original = min(originals, key=lambda p: p.get("createdAt", "")) if originals else proposal
            versions = []
            for owner in (proposal, original):
                row = self.db.execute("SELECT event_id FROM project_events WHERE project_id=? "
                    "AND json_extract(payload,'$.payload.resource.kind')='proposal' "
                    "AND json_extract(payload,'$.payload.resource.id')=? ORDER BY sequence DESC LIMIT 1",
                    (project_id, owner["id"])).fetchone()
                versions.append(row[0] if row else owner.get("updatedAt"))
            return context_for(proposal, original.get("text"), json.dumps(versions, separators=(",", ":")))

    def generate_concept_reference(self, *, operator_id, project_id, request):
        from .coordinator import WorkflowError, now

        self._operator(operator_id)
        required = {"requestId", "sourceText", "interpretation", "size", "quality"}
        contextual = isinstance(request, dict) and "source" in request
        planned = isinstance(request, dict) and "batchId" in request
        if not isinstance(request, dict) or set(request) != required | ({"source", "materialIds"} if contextual else set()) | ({"batchId", "visualPlanId", "imageId"} if planned else set()):
            raise WorkflowError(400, "REFERENCE_REQUEST", "请提供完整的概念生成请求。")
        rid = request["requestId"]
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", rid):
            raise WorkflowError(400, "REFERENCE_REQUEST", "生成请求编号无效。")
        if any(not isinstance(request[k], str) or len(request[k]) > 8000 for k in ("sourceText", "interpretation")) or (not contextual and not request["sourceText"].strip()):
            raise WorkflowError(400, "REFERENCE_REQUEST", "先保留原始想法，再生成概念参考。")
        if contextual and (request["sourceText"] != "" or not isinstance(request["source"], dict) or
                set(request["source"]) != {"proposalId", "proposalRevision", "feedbackId", "contextVersion"} or
                not isinstance(request["source"]["proposalId"], str) or
                type(request["source"]["proposalRevision"]) is not int):
            raise WorkflowError(400, "REFERENCE_SOURCE", "视觉策划只接受服务端定位的已提交材料。")
        if request["size"] not in {"1024x1024", "1536x1024", "1024x1536"} or request["quality"] not in {"low", "medium", "high"}:
            raise WorkflowError(400, "REFERENCE_REQUEST", "请选择支持的图片尺寸和质量。")
        with self.transaction():
            # Global identity prevents accidental reuse across projects.
            row = self.db.execute("SELECT payload FROM entities WHERE kind='concept-generation' AND id=?", (rid,)).fetchone()
            existing = self._get("concept-generation", rid) if row else None
            if existing:
                if existing["projectId"] != project_id or existing["request"] != request:
                    raise WorkflowError(409, "REFERENCE_ID_REUSED", "原请求编号对应其他内容；没有再次生成。")
                return copy.deepcopy(existing)
            if planned:
                raise WorkflowError(409, "REFERENCE_BATCH_ORDER", "逐图请求只由已确认批次派发；请查看原批次。")
            if self._get("project", project_id).get("archived"):
                raise WorkflowError(409, "PROJECT_ARCHIVED", "已归档项目不能生成参考。")
            if self._project_image_pending(project_id):
                raise WorkflowError(409, "REFERENCE_PENDING", "此前生成仍在处理或待核实，请先查看原请求。")
            self._check_image_capacity()
            snapshot = None
            if contextual:
                from .visual_planning import selected_snapshot
                context = self.visual_planning_context(project_id, request["source"]["proposalId"])
                if request["source"] != context["source"]:
                    raise WorkflowError(409, "REFERENCE_SOURCE_STALE", "策划反馈或方案版本已变化，请重新核对已提交依据后生成。")
                snapshot, prompt = selected_snapshot(context, request["materialIds"], request["interpretation"])
            else:
                prompt = ("Create one game concept reference. Express visual style, silhouette, lighting and composition. "
                          "Do not present engine screenshots, UI text, coordinates or gameplay verification as facts.\n"
                          "Original user idea:\n" + request["sourceText"] + "\nVisual interpretation:\n" + request["interpretation"])
            record = {"id": rid, "projectId": project_id, "request": copy.deepcopy(request),
                      "prompt": prompt, "promptVersion": 2 if contextual else 1, "model": "gpt-image-2", "status": "QUEUED",
                      "createdAt": now(), "message": "概念参考排队中；尚未选用或制作。"}
            if snapshot:
                record["sourceSnapshot"] = snapshot
            self._put("concept-generation", record)
        self._kick_concept_scheduler()
        return copy.deepcopy(record)

    def reconcile_concept_reference(self, *, operator_id, project_id, request_id):
        """Recover an existing local result; this method never calls ImageGen."""
        from .coordinator import WorkflowError

        self._operator(operator_id)
        with self.lock:
            record = self._get("concept-generation", request_id)
            if record["projectId"] != project_id:
                raise WorkflowError(404, "NOT_FOUND", "没有找到此项目的生成请求。")
            if record["status"] == "UNCERTAIN":
                self._import_concept_result(record)
                record = self._get("concept-generation", request_id)
            return copy.deepcopy(record)

    def _import_concept_result(self, record):
        from .coordinator import WorkflowError, now

        path = self.state_root / "concept-generations" / record["id"] / "concept.png"
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            return False
        if path.stat().st_size > 5 * 1024 * 1024:
            raise WorkflowError(400, "ASSET_INVALID", "生成图片超过参考上传的 5 MB 限制。")
        # Existing upload boundary performs full image validation and decoding.
        with self.transaction():
            asset = self.upload_asset(operator_id=self.operator_id, project_id=record["projectId"],
                name="concept.png", mime_type="image/png", data_base64=base64.b64encode(path.read_bytes()).decode(), purpose="reference")
            asset["generation"] = {"requestId": record["id"], "model": record["model"], "promptVersion": record["promptVersion"],
                                   "requestedSize": record["request"]["size"], "source": "imagegen"}
            if record.get("sourceSnapshot"):
                asset["generation"]["provenance"] = {k: copy.deepcopy(v) for k, v in record["sourceSnapshot"].items() if k != "materials"}
            self._put("asset", asset)
            record.update(status="GENERATED", asset=asset, completedAt=now(), message="概念图已保存；是否采纳以草稿和方案记录为准，不代表运行效果。")
            self._put("concept-generation", record)
        return True

    def _generate_concept_worker(self, request_id):
        from tools.imagegen_cli import ImageGenerationError, generate_images

        with self.transaction():
            record = self._get("concept-generation", request_id)
            record.update(status="RUNNING", message="正在生成概念参考；不会自动重试。")
            self._put("concept-generation", record)
        try:
            generate_images([{"prompt": record["prompt"], "filename": "concept.png"}],
                output_dir=self.state_root / "concept-generations" / request_id,
                size=record["request"]["size"], quality=record["request"]["quality"], cancel_event=self._image_cancel)
            with self.lock:
                if not self._import_concept_result(record):
                    raise ValueError("Missing concept result")
        except Exception as exc:  # Provider output and credentials remain in private CLI logs.
            # CLI validation runs before it creates its output directory. Once
            # that directory exists a provider request may have been sent.
            local_failure = isinstance(exc, ImageGenerationError) and not (
                self.state_root / "concept-generations" / request_id).exists()
            with self.transaction():
                record.update(status="FAILED" if local_failure else "UNCERTAIN", message=(
                    "本地生成配置未通过，尚未调用图像服务。原文已保留，请修复配置后显式重新生成。"
                    if local_failure else "生成结果待核实。原文已保留；请核实原请求，不会自动重投。"))
                self._put("concept-generation", record)

"""Durable serial image batches; one shared worker, no waiting processes."""
from __future__ import annotations

import copy
import json
import re
import threading
import uuid

from .visual_planning import image_snapshot, validate_image_plan

PENDING_IMAGES = {"QUEUED", "RUNNING", "UNCERTAIN"}
TERMINAL_BATCHES = {"COMPLETED", "CANCELLED"}


class ReferenceBatches:
    def reference_batches(self, project_id):
        with self.lock:
            self._get("project", project_id)
            return copy.deepcopy(self._all_project("reference-batch", project_id))

    def _check_image_capacity(self):
        from .coordinator import WorkflowError
        count = sum(b["status"] not in TERMINAL_BATCHES for b in self._all("reference-batch"))
        count += sum(r["status"] in PENDING_IMAGES and not r["request"].get("batchId") for r in self._all("concept-generation"))
        if count >= 8:
            raise WorkflowError(429, "REFERENCE_CAPACITY", "图像队列已满（最多八个未结束批次），请等待或取消未执行批次。")

    def _project_image_pending(self, project_id):
        return (any(r["status"] in PENDING_IMAGES for r in self._all_project("concept-generation", project_id)) or
                any(b["status"] not in TERMINAL_BATCHES for b in self._all_project("reference-batch", project_id)))

    def create_reference_batch(self, *, operator_id, project_id, request):
        from .coordinator import WorkflowError, now
        from .object_protocol import ObjectProtocolError
        self._operator(operator_id)
        if (not isinstance(request, dict) or set(request) != {"requestId", "source", "visualPlanId", "sharedStyle", "images"} or
                not isinstance(request["requestId"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request["requestId"]) or
                not isinstance(request["images"], list) or not 1 <= len(request["images"]) <= 6):
            raise WorkflowError(400, "REFERENCE_BATCH_REQUEST", "每批请选择一至六张图片，并提供完整分图计划。")
        with self.transaction():
            row = self.db.execute("SELECT payload FROM entities WHERE kind='reference-batch' AND id=?", (request["requestId"],)).fetchone()
            if row:
                old = json.loads(row[0])
                if old["projectId"] != project_id or old["request"] != request:
                    raise WorkflowError(409, "REFERENCE_ID_REUSED", "批次编号已绑定其他内容。")
                return copy.deepcopy(old)
            if self._get("project", project_id).get("archived"):
                raise WorkflowError(409, "PROJECT_ARCHIVED", "归档项目只允许查看。")
            context = self._check_visual_source(project_id, request["source"])
            if request["visualPlanId"] is not None:
                if not isinstance(request["visualPlanId"], str):
                    raise WorkflowError(400, "VISUAL_PLAN_REQUEST", "视觉计划编号无效。")
                plan = self.require_project_resource(project_id, "visual-plan", request["visualPlanId"])
                if plan["source"] != request["source"] or plan["status"] != "READY":
                    raise WorkflowError(409, "REFERENCE_SOURCE_STALE", "分图计划未就绪或已过期，请重新核对。")
            if self._project_image_pending(project_id):
                raise WorkflowError(409, "REFERENCE_PENDING", "本项目已有未结束的图像请求或批次，请先处理原记录。")
            self._check_image_capacity()
            # User edits are explicitly visual instructions, never substituted
            # submitted materials. All material text is resolved on the server.
            try:
                validate_image_plan({"sharedStyle": request["sharedStyle"], "images": request["images"],
                    "coverage": [{"concept": i.get("title", ""), "imageIds": [i.get("id")], "reason": i.get("purpose", "")}
                                 for i in request["images"] if isinstance(i, dict)]}, context)
            except ObjectProtocolError as exc:
                raise WorkflowError(400, "REFERENCE_IMAGE_PLAN", "请核对逐图说明与已提交材料：" + str(exc)) from None
            items = []
            for image in request["images"]:
                try:
                    snapshot, prompt = image_snapshot(context, image, request["sharedStyle"])
                except WorkflowError as exc:
                    raise WorkflowError(exc.status, exc.code, image["title"] + "：" + str(exc)) from None
                rid = str(uuid.uuid4())
                body = {"requestId": rid, "sourceText": "", "interpretation": "", "size": "1536x1024", "quality": "low",
                        "source": copy.deepcopy(context["source"]), "materialIds": list(image["materialIds"]),
                        "batchId": request["requestId"], "visualPlanId": request["visualPlanId"], "imageId": image["id"]}
                items.append({"imageId": image["id"], "requestId": rid, "request": body, "imagePlan": copy.deepcopy(image),
                              "sourceSnapshot": snapshot, "prompt": prompt, "status": "WAITING"})
            batch = {"id": request["requestId"], "projectId": project_id, "request": copy.deepcopy(request),
                     "source": copy.deepcopy(context["source"]), "items": items, "status": "QUEUED", "createdAt": now(),
                     "message": "已确认分图计划；将依次生成，默认仅供检查。"}
            self._put("reference-batch", batch)
            self._after_commit.append(self._kick_concept_scheduler)
        return copy.deepcopy(batch)

    def control_reference_batch(self, *, operator_id, project_id, batch_id, action):
        from .coordinator import WorkflowError
        self._operator(operator_id)
        with self.transaction():
            batch = self.require_project_resource(project_id, "reference-batch", batch_id)
            if self._get("project", project_id).get("archived"):
                raise WorkflowError(409, "PROJECT_ARCHIVED", "归档项目只允许查看。")
            self._sync_batch_results(batch)
            if batch["status"] in TERMINAL_BATCHES:
                return copy.deepcopy(batch)
            if action == "pause":
                batch["pauseRequested"] = True
                if not any(i["status"] == "RUNNING" for i in batch["items"]):
                    batch["status"] = "PAUSED"
                batch["message"] = "批次已请求暂停；已派发图片完成后停止。"
            elif action == "cancel":
                batch["cancelRequested"] = True
                for item in batch["items"]:
                    if item["status"] in {"WAITING", "BLOCKED", "FAILED"}:
                        item["status"] = "CANCELLED"
                batch["status"] = "CANCELLED" if not any(i["status"] == "RUNNING" for i in batch["items"]) else "RUNNING"
                batch["message"] = "已取消未派发图片；原请求记录保留，已派发请求仍可核实。"
            elif action == "resume":
                if batch.get("cancelRequested"):
                    raise WorkflowError(409, "REFERENCE_BATCH_CANCELLED", "已取消的批次不能继续，请保留原记录。")
                if any(i["status"] == "UNCERTAIN" for i in batch["items"]):
                    raise WorkflowError(409, "REFERENCE_PENDING", "请先核实批次中原请求的结果，不会重投。")
                self._check_visual_source(project_id, batch["source"])
                for item in batch["items"]:
                    if item["status"] == "FAILED":
                        item["status"] = "SKIPPED"
                batch.update(status="QUEUED", pauseRequested=False, message="继续尚未派发的图片；已确认失败的图已跳过，不会自动重试。")
                self._after_commit.append(self._kick_concept_scheduler)
            else:
                raise WorkflowError(400, "REFERENCE_BATCH_ACTION", "不支持的批次操作。")
            self._put("reference-batch", batch)
            return copy.deepcopy(batch)

    def _sync_batch_results(self, batch):
        for item in batch["items"]:
            row = self.db.execute("SELECT payload FROM entities WHERE kind='concept-generation' AND id=?", (item["requestId"],)).fetchone()
            if row and item["status"] not in {"SKIPPED", "CANCELLED"}:
                item["status"] = json.loads(row[0])["status"]

    def _kick_concept_scheduler(self):
        with self.lock:
            if self._closed:
                return
            thread = self._threads.get("concept-scheduler")
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=self._run_concept_scheduler, name="studio-imagegen", daemon=True)
            self._threads["concept-scheduler"] = thread
            for record in self._all("concept-generation"):
                if record["status"] == "QUEUED":
                    self._threads["concept:" + record["id"]] = thread
            thread.start()

    def _run_concept_scheduler(self):
        from .coordinator import WorkflowError, now
        while not self._closed:
            with self.transaction():
                candidates = [(r["createdAt"], "single", r) for r in self._all("concept-generation")
                              if r["status"] == "QUEUED" and not r["request"].get("batchId")]
                candidates += [(b.get("lastDispatchAt", b["createdAt"]), "batch", b) for b in self._all("reference-batch")
                               if b["status"] in {"QUEUED", "RUNNING"}]
                if not candidates:
                    # Clear under the same lock used by enqueue: a new request
                    # must never see a worker which has decided to exit.
                    self._threads.pop("concept-scheduler", None)
                    return
                _, kind, owner = min(candidates, key=lambda v: v[0])
                if kind == "single":
                    record = owner
                    try:
                        if self._get("project", record["projectId"]).get("archived"):
                            raise WorkflowError(409, "PROJECT_ARCHIVED", "项目已归档，尚未调用 ImageGen。")
                        if record["request"].get("source"):
                            self._check_visual_source(record["projectId"], record["request"]["source"])
                    except WorkflowError as exc:
                        record.update(status="FAILED", message=str(exc)); self._put("concept-generation", record)
                        continue
                else:
                    batch = owner
                    if batch.get("pauseRequested") or batch.get("cancelRequested"):
                        batch["status"] = "CANCELLED" if batch.get("cancelRequested") else "PAUSED"
                        self._put("reference-batch", batch); continue
                    item = next((i for i in batch["items"] if i["status"] == "WAITING"), None)
                    if item is None:
                        batch.update(status="COMPLETED", message="本批图片已处理完毕；采纳仍需填写用途并提交。")
                        self._put("reference-batch", batch); continue
                    try:
                        self._check_visual_source(batch["projectId"], batch["source"])
                        if self._get("project", batch["projectId"]).get("archived"):
                            raise WorkflowError(409, "PROJECT_ARCHIVED", "项目已归档。")
                    except WorkflowError as exc:
                        item["status"] = "BLOCKED"
                        batch.update(status="PAUSED", message="来源已变化或不可生成，请取消余下图片并重新核对：" + str(exc))
                        self._put("reference-batch", batch); continue
                    record = {"id": item["requestId"], "projectId": batch["projectId"], "request": item["request"],
                              "sourceSnapshot": item["sourceSnapshot"], "prompt": item["prompt"], "promptVersion": 3,
                              "model": "gpt-image-2", "status": "QUEUED", "createdAt": now(), "message": "逐图请求已派发。"}
                    item["status"] = "RUNNING"
                    batch.update(status="RUNNING", lastDispatchAt=now())
                    self._put("reference-batch", batch); self._put("concept-generation", record)
                self._threads["concept:" + record["id"]] = threading.current_thread()
            self._generate_concept_worker(record["id"])
            if kind == "batch":
                with self.transaction():
                    batch = self._get("reference-batch", owner["id"])
                    self._sync_batch_results(batch)
                    if any(i["status"] in {"FAILED", "UNCERTAIN"} for i in batch["items"]):
                        batch.update(status="PAUSED", message="本图失败或结果待核实，批次已暂停；请先查看原请求。")
                    elif batch.get("cancelRequested"):
                        batch["status"] = "CANCELLED"
                    elif batch.get("pauseRequested"):
                        batch["status"] = "PAUSED"
                    elif not any(i["status"] == "WAITING" for i in batch["items"]):
                        batch.update(status="COMPLETED", message="本批图片已生成；尚未自动采纳。")
                    self._put("reference-batch", batch)

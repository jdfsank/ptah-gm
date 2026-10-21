"""Read-only, item-level iteration results from retained workflow facts.

Technical verification and matching document values are evidence with different
limits. Neither is promoted to a user's experience decision or proof that a
natural-language request was implemented.
"""
from __future__ import annotations

import copy


_FAILURE_STATUSES = {"FAIL", "FAILED", "ERROR"}


def _no_candidate_failure_reason(job, verification):
    """Explain a real failed run without turning item-level work into a failure."""
    if job.get("candidate"):
        return None
    failure = job.get("productionFailure") or {}
    failure_code = str(failure.get("code") or "").upper()
    verification_status = str((verification or {}).get("status") or "").upper()
    job_status = str(job.get("status") or "").upper()
    verification_failed = verification_status in _FAILURE_STATUSES or failure_code == "VERIFICATION_FAILED"
    if verification_failed:
        detail = ((verification or {}).get("message") or (verification or {}).get("reason")
                  or failure.get("message") or job.get("message") or "独立技术验证未通过。")
        code = f"（{failure_code}）" if failure_code else ""
        return f"独立技术验证失败：{detail}{code}；没有形成候选。"
    if job_status in {"FAILED", "CANCELLED"}:
        detail = failure.get("message") or job.get("message") or "本轮执行未完成。"
        code = f"（{failure_code}）" if failure_code else ""
        return f"本轮执行未完成：{detail}{code}；没有形成候选。"
    return None


def _append_failure_reason(reason, failure_reason):
    if not failure_reason:
        return reason
    return f"{reason} {failure_reason}" if reason else failure_reason


def iteration_results(proposals, packets, jobs, feedback=()):
    """Project existing records without creating a second task/result store."""
    result = []
    feedback_by_id = {item.get("feedbackId"): item for item in feedback}
    jobs_by_packet = {item.get("packetId"): item for item in reversed(jobs)}
    proposals_by_id = {item["id"]: item for item in proposals}
    frozen_revisions = {(p.get("proposalId"), p.get("proposalRevision", proposals_by_id.get(p.get("proposalId"), {}).get("revision"))) for p in packets}
    submissions = []
    for packet in packets:
        current = proposals_by_id.get(packet.get("proposalId")) or {}
        retained_proposal = packet.get("approvedProposal") or current
        proposal = {**retained_proposal, "id": packet.get("proposalId", packet["id"]),
                    "revision": packet.get("proposalRevision", current.get("revision")),
                    "changeRequest": packet.get("changeRequest", current.get("changeRequest")),
                    "feedbackDecisions": packet.get("feedbackDecisions", retained_proposal.get("feedbackDecisions", [])
                        if packet.get("proposalRevision", current.get("revision")) == current.get("revision") else [])}
        if current.get("revision") != proposal["revision"]:
            proposal.pop("currentDocument", None)
        submissions.append((proposal, packet))
    submissions.extend((p, {}) for p in proposals if (p["id"], p.get("revision")) not in frozen_revisions)
    for proposal, packet in submissions:
        request = proposal.get("changeRequest") or {}
        if not request:
            continue
        job = jobs_by_packet.get(packet.get("id")) or {}
        candidate = job.get("candidate") or {}
        document = candidate.get("document") or {}
        objects = {item["id"]: item for item in document.get("objects", [])}
        decisions = {item["feedbackId"]: item for item in proposal.get("feedbackDecisions", [])}
        verification = candidate.get("verification") if candidate else job.get("verification")
        verification = verification or {}
        technical = verification.get("status")
        no_candidate_failure = _no_candidate_failure_reason(job, verification)
        common = {"proposalId": proposal["id"], "proposalRevision": proposal.get("revision"),
                  "jobId": job.get("id"), "candidateId": candidate.get("id"),
                  "sourceCommit": candidate.get("candidateCommit"),
                  "workflowStatus": job.get("status") or proposal.get("status"),
                  "technicalVerification": technical or "NOT_PERFORMED",
                  "versionDecision": "published" if job.get("status") == "PUBLISHED" else "rejected" if job.get("status") == "REJECTED" else "pending",
                  "userAcceptance": "NOT_PERFORMED"}
        old_objects = {o["id"]: o for o in (proposal.get("currentDocument") or {}).get("objects", [])}
        if proposal.get("text", "").strip() and not request.get("feedback") and not request.get("operations"):
            targets = request.get("targetObjectIds", [])
            result.append({**common, "itemId": proposal["id"] + ":text", "kind": "feedback",
                "objectId": targets[0] if len(targets) == 1 else None,
                "targetObjectIds": list(targets), "originalText": proposal["text"],
                "planSummary": proposal.get("summary"), "status": "requires_item_review" if candidate else "pending",
                "reason": _append_failure_reason("保留本轮原文与原目标；尚无原文到实际实现的逐项映射，等待核对。", no_candidate_failure)})
        for change in request.get("fields", []):
            target = change["objectId"]
            obj = objects.get(target) or {}
            before = next((f.get("value") for f in old_objects.get(target, {}).get("fields", [])
                           if f["id"] == change["fieldId"]), None)
            actual = next((f for f in obj.get("fields", []) if f["id"] == change["fieldId"]), None)
            matches = actual is not None and actual.get("value") == change["value"]
            source_paths = obj.get("sourceBindings", [])
            changed_paths = [p for p in job.get("changedFiles", candidate.get("changedFiles", [])) if p in source_paths]
            result.append({**common, "itemId": f"{proposal['id']}:field:{target}:{change['fieldId']}",
                "kind": "field", "objectId": target, "fieldId": change["fieldId"],
                "before": copy.deepcopy(before), "requested": copy.deepcopy(change["value"]),
                "actual": copy.deepcopy(actual.get("value")) if actual is not None else None,
                "documentValueMatches": matches if candidate else None,
                "changedSourcePaths": changed_paths,
                "status": "candidate_value_matches" if matches else "candidate_value_differs" if candidate else "pending",
                "reason": _append_failure_reason(
                    "候选对象值与申报一致；关联源码差异和技术验证单独列示，体验仍须审阅。" if matches else
                    "候选没有对应值或值不一致，需求保留待处理。" if candidate else "已收单，等待本轮处理结果。",
                    no_candidate_failure)})
        for index, item in enumerate(request.get("feedback", [])):
            retained = feedback_by_id.get(item.get("feedbackId")) or {}
            if retained.get("proposalId") != proposal["id"]:
                retained = {}
            decision = decisions.get(item.get("feedbackId")) or retained.get("planDecision")
            user = next((copy.deepcopy(value) for value in job.get("experienceDecisions", [])
                         if value.get("feedbackId") == item.get("feedbackId")), None)
            if user is None and candidate.get("id") and retained.get("candidateId") == candidate["id"]:
                user = retained.get("experienceDecision")
            task_ids = set((decision or {}).get("taskIds", []))
            linked_tasks = [task for task in proposal.get("tasks", []) if task["id"] in task_ids]
            related_targets = {target for task in linked_tasks for target in task.get("objectIds", [])}
            if item.get("objectId"):
                related_targets.add(item["objectId"])
            related_paths = {path for target in related_targets
                             for path in objects.get(target, {}).get("sourceBindings", [])}
            changed_paths = [path for path in job.get("changedFiles", candidate.get("changedFiles", []))
                             if path in related_paths]
            requirement_ids = set((decision or {}).get("requirementIds", []))
            requirement_ids.update(rid for task in linked_tasks for rid in task.get("requirementIds", []))
            checks = [check for check in verification.get("requirements", [])
                      if check.get("id") in requirement_ids]
            reason = decision.get("reason", "") if decision else "尚无逐项处理决定；整体执行结束不能代替本项实现说明。"
            result.append({**common, "itemId": f"{proposal['id']}:feedback:{item.get('feedbackId') or index}",
                "kind": "feedback", "objectId": item.get("objectId"),
                "feedbackId": item.get("feedbackId"), "originalText": item.get("message", ""),
                "category": item.get("category", "general"), "planDecision": copy.deepcopy(decision),
                "linkedTasks": copy.deepcopy(linked_tasks), "changedSourcePaths": changed_paths,
                "verificationRequirements": copy.deepcopy(checks),
                "experienceDecision": copy.deepcopy(user),
                "userAcceptance": user["status"] if user and user.get("status") in {"accepted", "resolved", "needs_followup"} else "NOT_PERFORMED",
                "status": decision.get("status", "pending") if decision else "pending",
                "reason": _append_failure_reason(reason, no_candidate_failure)})
        for operation in request.get("operations", []):
            target_id = (operation.get("sceneId") if operation.get("kind") == "new-scene" else
                         operation.get("instanceId") if operation.get("kind") == "new-instance" else
                         operation.get("objectId"))
            obj = objects.get(target_id) or {}
            changed_paths = [p for p in job.get("changedFiles", candidate.get("changedFiles", []))
                             if p in obj.get("sourceBindings", [])]
            linked_tasks = [task for task in proposal.get("tasks", [])
                            if target_id and target_id in task.get("objectIds", [])]
            result.append({**common,
                "itemId": f"{proposal['id']}:operation:{operation.get('operationId')}",
                "kind": "operation", "operationId": operation.get("operationId"),
                "objectId": target_id, "requested": copy.deepcopy(operation),
                "actual": copy.deepcopy(obj.get("workbench")) if obj else None,
                "linkedTasks": copy.deepcopy(linked_tasks),
                "changedSourcePaths": changed_paths,
                "status": "requires_item_review" if candidate else "pending",
                "reason": _append_failure_reason(
                    "保留完整结构申报与候选目标信息；请对照相关源变化及预览逐项核对。" if candidate else "结构操作已收单，等待本轮处理。",
                    no_candidate_failure)})
    return result

"""Strict, engine-neutral validation for Studio's versioned object protocol.

This module validates planning and iteration data only. It does not execute a
planner, write project files, approve work, or certify game behavior.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

DOCUMENT_VERSION = "studio.objects.v1"
MAX_DOCUMENT_BYTES = 1_000_000
MAX_REQUEST_BYTES = 128_000
MAX_OBJECTS = 500
MAX_FIELDS_PER_OBJECT = 200
MAX_REQUIREMENTS = 500
MAX_PATHS_PER_OBJECT = 100
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PATH_ROOTS = {"scripts", "scenes", "resources", "assets"}
PATH_EXTENSIONS = {
    ".gd", ".tscn", ".tres", ".png", ".jpg", ".jpeg", ".webp",
}
KINDS = {"project", "scene", "entity", "mechanic", "rule", "interface", "asset", "content"}
FIELD_TYPES = {"number", "integer", "boolean", "text", "choice", "color", "vector2"}
WORKBENCH_ROLES = {"definition", "instance", "entry", "spawn", "behavior", "state", "resource", "transition", "preset", "system", "scene"}
WORKBENCH_SCOPES = {"project", "scene", "shared", "instance", "runtime"}
WORKBENCH_LOCKS = {"fixed", "nudge", "free"}
WORKBENCH_PROVENANCE_KINDS = {"fact", "intent", "inference", "proposal", "runtime"}
WORKBENCH_PREVIEW_TYPES = {"semantic", "image", "motion", "action", "response", "interaction", "rule", "spawn", "transition"}
WORKBENCH_DOCUMENT_ROOTS = {"scripts", "scenes", "resources", "assets", "design", "docs"}
WORKBENCH_DOCUMENT_FILES = {"project.godot", "GDD.md", "DESIGN.md", "PLAN.md", "SCENES.md", "ASSETS.md", "STRUCTURE.md", "SPEC.md", "README.md", "README.zh-CN.md"}
FEEDBACK_CATEGORIES = {"general", "bug", "visual", "behavior"}
PLANNING_STATUSES = {"NEEDS_CLARIFICATION", "READY", "BLOCKED"}
QUESTION_TYPES = {"text", "choice", "number", "boolean"}
MESSAGE_VERSION = "studio.message.v1"
PROJECT_VIEW_VERSION = "studio.project-view.v1"
EXECUTION_VERSION = "studio.execution.v1"
FEEDBACK_DECISIONS = {"adopted", "needs_clarification", "deferred", "rejected"}


class ObjectProtocolError(ValueError):
    """A protocol document or request is malformed or unsafe."""


def _fail(message: str) -> None:
    raise ObjectProtocolError(message)


def _exact_keys(value: Mapping, required: set[str], optional: set[str] = frozenset(), where: str = "object") -> None:
    keys = set(value)
    if not required <= keys or keys - required - optional:
        missing = sorted(required - keys)
        unknown = sorted(keys - required - optional)
        _fail(f"{where} has missing keys {missing} or unknown keys {unknown}")


def _string(value: object, where: str, maximum: int = 4000, minimum: int = 1) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or value != value.strip():
        _fail(f"{where} must be a trimmed string of length {minimum}..{maximum}")
    return value


def _user_text(value: object, where: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        _fail(f"{where} must be a bounded user string")
    return value


def _id(value: object, where: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        _fail(f"{where} is not a valid stable ID")
    return value


def _nonnegative_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{where} must be a non-negative integer")
    return value


def _string_list(value: object, where: str, maximum: int = 100) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(f"{where} must be a bounded list")
    result = [_id(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        _fail(f"{where} contains duplicates")
    return result


def _validate_feedback(value: object, where: str = "feedback") -> list[dict]:
    if not isinstance(value, list) or len(value) > 100:
        _fail(f"{where} must contain at most 100 items")
    result = []
    seen = set()
    for index, item in enumerate(value):
        place = f"{where}[{index}]"
        if not isinstance(item, dict):
            _fail(f"{place} must be an object")
        _exact_keys(item, {"feedbackId", "objectId", "message", "category"}, where=place)
        feedback_id = _id(item["feedbackId"], place + ".feedbackId")
        if feedback_id in seen:
            _fail(f"{where} contains duplicate feedbackId")
        seen.add(feedback_id)
        if item["objectId"] is not None:
            _id(item["objectId"], place + ".objectId")
        message = _string(item["message"], place + ".message", 4000, minimum=0)
        category = item["category"]
        if category not in FEEDBACK_CATEGORIES:
            _fail(f"{place}.category is unsupported")
        result.append({"feedbackId": feedback_id, "objectId": item["objectId"], "message": message, "category": category})
    return result


OPERATION_KINDS = {"move", "set-lock", "new-scene", "new-instance", "delete-instance", "transition"}
TRANSITION_MODES = {"未设置", "无过渡", "共享预设", "unset", "none", "preset"}


def _is_transition_preset(preset_id: str, objects: dict[str, dict]) -> bool:
    preset = objects.get(preset_id) or {}
    metadata = preset.get("workbench") or {}
    if metadata.get("role") != "preset":
        return False
    if (metadata.get("preview") or {}).get("type") == "transition":
        return True
    # Existing directed edges also establish a preset's declared purpose.
    return any(
        (obj.get("workbench") or {}).get("role") == "transition" and (
            (obj.get("workbench") or {}).get("presetId") == preset_id or
            (obj.get("workbench") or {}).get("transitionPresetId") == preset_id or
            any("preset" in str(relation.get("type", "")).lower() and
                relation.get("targetId", relation.get("target")) == preset_id
                for relation in obj.get("relations", [])))
        for obj in objects.values()
    )


def _validate_workbench_operations_shape(value: object, where: str = "operations") -> list[dict]:
    """Validate the UI's stable, type-specific structural proposal envelope."""
    if not isinstance(value, list) or len(value) > 100:
        _fail(f"{where} must contain at most 100 operations")
    result = []
    seen = set()
    for index, operation in enumerate(value):
        place = f"{where}[{index}]"
        if not isinstance(operation, dict):
            _fail(f"{place} must be an object")
        if not {"operationId", "kind"} <= set(operation):
            _fail(f"{place} requires operationId and kind")
        kind = operation["kind"]
        if not isinstance(kind, str) or kind not in OPERATION_KINDS:
            _fail(f"{place}.kind is unsupported")
        operation_id = _id(operation["operationId"], f"{place}.operationId")
        if operation_id in seen:
            _fail(f"{where} contains duplicate operationId")
        seen.add(operation_id)
        schemas = {
            "move": ({"objectId", "requested"}, {"before", "scope", "lock"}),
            "set-lock": ({"objectId", "before", "lock"}, {"scope"}),
            "new-scene": ({"sceneId", "name", "template"}, {"bounds", "connections", "scope"}),
            "new-instance": ({"instanceId", "name", "definitionId", "sceneId", "requestedPosition"},
                              {"size", "anchor", "lock", "description", "scope"}),
            "delete-instance": ({"objectId"}, {"scope"}),
            "transition": (set(), {"objectId", "from", "sceneId", "entryId", "condition", "mode", "presetId", "scope"}),
        }
        required, optional = schemas[kind]
        allowed = {"operationId", "kind"} | required | optional
        _exact_keys(operation, {"operationId", "kind"} | required, optional, place)
        clean = {"operationId": operation_id, "kind": kind}
        if "objectId" in operation:
            clean["objectId"] = _id(operation["objectId"], f"{place}.objectId")
        if kind == "move":
            clean["requested"] = _workbench_pair(operation["requested"], f"{place}.requested")
            if "before" in operation:
                clean["before"] = _workbench_pair(operation["before"], f"{place}.before")
            if "lock" in operation:
                if not isinstance(operation["lock"], str) or operation["lock"] not in WORKBENCH_LOCKS:
                    _fail(f"{place}.lock is unsupported")
                clean["lock"] = operation["lock"]
        elif kind == "set-lock":
            for key in ("before", "lock"):
                if not isinstance(operation[key], str) or operation[key] not in WORKBENCH_LOCKS:
                    _fail(f"{place}.{key} is unsupported")
                clean[key] = operation[key]
        elif kind in {"new-scene", "new-instance"}:
            clean["name"] = _string(operation["name"], f"{place}.name", 160)
            if kind == "new-scene":
                clean["sceneId"] = _id(operation["sceneId"], f"{place}.sceneId")
                if not isinstance(operation["template"], str) or operation["template"] not in {"blank", "minimal"}:
                    _fail(f"{place}.template is unsupported")
                clean["template"] = operation["template"]
                if "bounds" in operation:
                    clean["bounds"] = _workbench_pair(operation["bounds"], f"{place}.bounds", positive=True)
                if "connections" in operation:
                    clean["connections"] = _string(operation["connections"], f"{place}.connections", 2000, minimum=0)
            else:
                clean["instanceId"] = _id(operation["instanceId"], f"{place}.instanceId")
                clean["definitionId"] = _id(operation["definitionId"], f"{place}.definitionId")
                clean["sceneId"] = _id(operation["sceneId"], f"{place}.sceneId")
                clean["requestedPosition"] = _workbench_pair(operation["requestedPosition"], f"{place}.requestedPosition")
                if "size" in operation:
                    clean["size"] = _workbench_pair(operation["size"], f"{place}.size", positive=True)
                if "anchor" in operation:
                    clean["anchor"] = _workbench_pair(operation["anchor"], f"{place}.anchor", normalized=True)
                lock = operation.get("lock", "free")
                if not isinstance(lock, str) or lock not in WORKBENCH_LOCKS:
                    _fail(f"{place}.lock is unsupported")
                clean["lock"] = lock
                if "description" in operation:
                    clean["description"] = _string(operation["description"], f"{place}.description", 2000, minimum=0)
        elif kind == "transition":
            populated = False
            for key in ("from", "sceneId", "entryId", "condition", "mode", "presetId"):
                if key not in operation:
                    continue
                value_item = operation[key]
                if key in {"sceneId", "entryId", "presetId"} and value_item != "":
                    clean[key] = _id(value_item, f"{place}.{key}")
                    populated = True
                elif key in {"sceneId", "entryId", "presetId"}:
                    clean[key] = ""
                else:
                    clean[key] = _string(value_item, f"{place}.{key}", 1000, minimum=0)
                    populated = populated or bool(value_item) and key != "from"
            if "mode" in clean and clean["mode"] not in TRANSITION_MODES:
                _fail(f"{place}.mode is unsupported")
            if not populated:
                _fail(f"{place} must include a destination, entry, condition, mode, or preset")
        if "scope" in operation:
            clean["scope"] = _string(operation["scope"], f"{place}.scope", 160)
        result.append(clean)
    return result


def _scene_bounds(document_objects: dict[str, dict], scene_id: str, where: str) -> list[float] | None:
    scene_metadata = document_objects[scene_id].get("workbench") or {}
    bounds = scene_metadata.get("bounds")
    return _workbench_pair(bounds, f"{where}.sceneBounds", positive=True) if bounds is not None else None


def _check_position_inside_scene(position: list[float], object_meta: dict, scene_id: str,
                                 object_map: dict[str, dict], where: str) -> None:
    bounds = object_meta.get("bounds") or _scene_bounds(object_map, scene_id, where)
    if bounds is None:
        _fail(f"{where} cannot be moved because the scene has no declared bounds")
    x, y = position
    width, height = bounds
    if x < 0 or y < 0 or x > width or y > height:
        _fail(f"{where} position is outside declared scene bounds")
    size = object_meta.get("size", [0, 0])
    anchor = object_meta.get("anchor", [0, 0])
    if (x - size[0] * anchor[0] < 0 or x + size[0] * (1 - anchor[0]) > width or
            y - size[1] * anchor[1] < 0 or y + size[1] * (1 - anchor[1]) > height):
        _fail(f"{where} size and anchor would extend beyond declared scene bounds")


def _validate_workbench_operation_references(operations: list[dict], document: dict,
                                             target_ids: list[str], where: str = "operations") -> list[dict]:
    object_map = {obj["id"]: obj for obj in document["objects"]}
    clean = copy.deepcopy(operations)
    claimed_targets = set()
    lock_operations = {operation["objectId"]: operation for operation in clean if operation["kind"] == "set-lock"}
    if len(lock_operations) != sum(operation["kind"] == "set-lock" for operation in clean):
        _fail(f"{where} contains conflicting lock changes")
    if any(operation["kind"] == "delete-instance" and operation["objectId"] in lock_operations for operation in clean):
        _fail(f"{where} cannot combine removal and a lock change for the same instance")
    draft_targets: dict[str, tuple[str, dict]] = {}
    for index, operation in enumerate(clean):
        place = f"{where}[{index}]"
        if operation["kind"] == "new-scene":
            draft_id, draft_kind = operation["sceneId"], "scene"
        elif operation["kind"] == "new-instance":
            draft_id, draft_kind = operation["instanceId"], "instance"
        else:
            continue
        if draft_id in object_map or draft_id in draft_targets:
            _fail(f"{place} draft target ID collides with an existing or declared object")
        draft_targets[draft_id] = (draft_kind, operation)
    scene_reference_map = dict(object_map)
    for draft_id, (draft_kind, operation) in draft_targets.items():
        if draft_kind == "scene":
            scene_reference_map[draft_id] = {"id": draft_id, "kind": "scene",
                "workbench": {"role": "scene", **({"bounds": operation["bounds"]} if "bounds" in operation else {})}}
    for index, operation in enumerate(clean):
        place = f"{where}[{index}]"
        kind = operation["kind"]
        if kind in {"move", "delete-instance", "transition"} and operation.get("objectId"):
            if operation["objectId"] in claimed_targets:
                _fail(f"{place}.objectId has conflicting structural operations")
            claimed_targets.add(operation["objectId"])
        if kind == "set-lock":
            target = object_map.get(operation["objectId"])
            if (target is None or operation["objectId"] not in target_ids or
                    (target.get("workbench") or {}).get("role") != "instance"):
                _fail(f"{place}.objectId must reference an existing target scene instance")
            if operation["before"] != (target.get("workbench") or {}).get("lock"):
                _fail(f"{place}.before does not match the published instance lock")
        elif kind in {"move", "delete-instance"}:
            object_id = operation["objectId"]
            target = object_map.get(object_id)
            if target is None or object_id not in target_ids:
                _fail(f"{place}.objectId must reference an existing target object")
            metadata = target.get("workbench") or {}
            if metadata.get("role") != "instance":
                _fail(f"{place}.objectId must reference a scene instance")
            if kind == "delete-instance":
                if metadata.get("lock") == "fixed":
                    _fail(f"{place} cannot delete a fixed instance")
            else:
                requested_lock = lock_operations.get(object_id, {}).get("lock", metadata.get("lock"))
                if requested_lock not in {"free", "nudge"}:
                    _fail(f"{place} cannot move an instance without a free or nudge lock")
                if "lock" in operation and operation["lock"] != requested_lock:
                    _fail(f"{place}.lock does not match the explicitly requested instance lock")
                scene_id = metadata.get("sceneId")
                if scene_id not in object_map:
                    _fail(f"{place} instance has no valid scene reference")
                position = metadata.get("position")
                if position is None:
                    _fail(f"{place} instance has no published position")
                if "before" in operation and operation["before"] != position:
                    _fail(f"{place}.before does not match the published instance position")
                _check_position_inside_scene(operation["requested"], metadata, scene_id, object_map, place)
        elif kind == "new-instance":
            definition = object_map.get(operation["definitionId"])
            scene = scene_reference_map.get(operation["sceneId"])
            if definition is None or definition.get("workbench", {}).get("role") != "definition":
                _fail(f"{place}.definitionId must reference a shared definition")
            if scene is None or scene["kind"] != "scene":
                _fail(f"{place}.sceneId must reference an existing or same-request new scene")
            definition_meta = definition.get("workbench") or {}
            instance_meta = {"size": operation.get("size", definition_meta.get("size", [0, 0])),
                             "anchor": operation.get("anchor", definition_meta.get("anchor", [0, 0]))}
            _check_position_inside_scene(operation["requestedPosition"], instance_meta, operation["sceneId"], scene_reference_map, place)
        elif kind == "transition":
            if operation.get("objectId"):
                transition_object = object_map.get(operation["objectId"])
                if (transition_object is None or operation["objectId"] not in target_ids or
                        transition_object.get("workbench", {}).get("role") != "transition"):
                    _fail(f"{place}.objectId must reference an existing target transition")
            source_scene_id = None
            source = operation.get("from", "")
            if source:
                source_object = object_map.get(source)
                if source_object is None:
                    matches = [obj for obj in document["objects"] if obj["name"] == source and obj["kind"] == "scene"]
                    if len(matches) != 1:
                        _fail(f"{place}.from must reference a scene ID or unique scene name")
                    source_object = matches[0]
                if source_object["kind"] == "scene":
                    source_scene_id = source_object["id"]
                elif source_object.get("workbench", {}).get("role") in {"entry", "exit"}:
                    source_scene_id = source_object.get("workbench", {}).get("sceneId")
                else:
                    _fail(f"{place}.from must reference a scene or an exit marker")
            destination_id = operation.get("sceneId", "")
            if destination_id:
                destination = object_map.get(destination_id)
                if destination is None or destination["kind"] != "scene":
                    _fail(f"{place}.sceneId must reference an existing destination scene")
            entry_id = operation.get("entryId", "")
            if entry_id:
                entry = object_map.get(entry_id)
                if entry is None or entry.get("workbench", {}).get("role") != "entry":
                    _fail(f"{place}.entryId must reference an entry marker")
                if destination_id and entry.get("workbench", {}).get("sceneId") != destination_id:
                    _fail(f"{place}.entryId must belong to the destination scene")
            mode = operation.get("mode", "")
            if mode in {"共享预设", "preset"}:
                preset_id = operation.get("presetId", "")
                if not preset_id:
                    _fail(f"{place} preset mode requires presetId")
                if not _is_transition_preset(preset_id, object_map):
                    _fail(f"{place}.presetId must reference a declared transition preset, not an environment configuration")
            elif operation.get("presetId"):
                _fail(f"{place}.presetId requires shared-preset mode")
            if source_scene_id and source_scene_id not in object_map:
                _fail(f"{place}.from does not resolve to a source scene")
    return clean


def _validate_expected(value: object) -> dict:
    if not isinstance(value, dict):
        _fail("expected must be an object")
    _exact_keys(value, set(), {"preferencesRevision", "publicationRevision", "proposalRevision", "sourceCommit"}, "expected")
    result = {}
    for key, item in value.items():
        if key == "sourceCommit":
            if item is not None: _string(item, "expected.sourceCommit", 200)
            result[key] = item
        else:
            result[key] = _nonnegative_int(item, "expected." + key)
    return result


def _validate_command_payload(kind: str, value: object) -> dict:
    if not isinstance(value, dict):
        _fail("payload must be an object")
    if kind == "project.create":
        _exact_keys(value, {"name"}, where="payload")
        return {"name": _string(value["name"], "payload.name", 120)}
    if kind == "session.preferences.update":
        _exact_keys(value, {"role", "modelKey", "effort", "limits"}, where="payload")
        if value["role"] not in {"planner", "producer"}: _fail("payload.role is unsupported")
        effort = value["effort"]
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}: _fail("payload.effort is unsupported")
        limits = value["limits"]
        if not isinstance(limits, dict): _fail("payload.limits must be an object")
        _exact_keys(limits, {"maxDurationSeconds", "softTotalTokens"}, where="payload.limits")
        if not 1 <= _nonnegative_int(limits["maxDurationSeconds"], "payload.limits.maxDurationSeconds") <= 7200: _fail("payload.limits.maxDurationSeconds must be 1..7200")
        tokens = limits["softTotalTokens"]
        if tokens is not None and not 1 <= _nonnegative_int(tokens, "payload.limits.softTotalTokens") <= 2_000_000: _fail("payload.limits.softTotalTokens must be null or 1..2000000")
        return {"role": value["role"], "modelKey": _string(value["modelKey"], "payload.modelKey", 200), "effort": effort,
                "limits": {"maxDurationSeconds": limits["maxDurationSeconds"], "softTotalTokens": tokens}}
    if kind == "project.settings.update":
        _exact_keys(value, set(), {"name", "archived"}, "payload")
        if not value: _fail("payload must include a project setting")
        result = {}
        if "name" in value: result["name"] = _string(value["name"], "payload.name", 120)
        if "archived" in value:
            if type(value["archived"]) is not bool: _fail("payload.archived must be boolean")
            result["archived"] = value["archived"]
        return result
    if kind in {"concept.submit", "iteration.submit"}:
        allowed = {"text", "assetRefs", "visualReferences", "targetObjectIds", "fields", "feedback", "operations"}
        required = {"text", "assetRefs"} if kind == "concept.submit" else {"text", "assetRefs", "targetObjectIds", "fields", "feedback"}
        _exact_keys(value, required, allowed - required, "payload")
        result = {}
        if "text" in value: result["text"] = _user_text(value["text"], "payload.text", 8000)
        if "assetRefs" in value: result["assetRefs"] = _string_list(value["assetRefs"], "payload.assetRefs")
        if "visualReferences" in value:
            from .concept_references import validate_visual_references
            result["visualReferences"] = validate_visual_references(value["visualReferences"], value.get("assetRefs", [r.get("assetId") for r in value["visualReferences"] if isinstance(r, dict)]))
        if "targetObjectIds" in value: result["targetObjectIds"] = _string_list(value["targetObjectIds"], "payload.targetObjectIds", 500)
        if "fields" in value:
            fields = value["fields"]
            if not isinstance(fields, list) or len(fields) > 100: _fail("payload.fields must be bounded")
            clean = []
            for i, field in enumerate(fields):
                if not isinstance(field, dict): _fail(f"payload.fields[{i}] must be an object")
                _exact_keys(field, {"objectId", "fieldId", "value"}, where=f"payload.fields[{i}]")
                clean.append({"objectId": _id(field["objectId"], f"payload.fields[{i}].objectId"), "fieldId": _id(field["fieldId"], f"payload.fields[{i}].fieldId"), "value": copy.deepcopy(field["value"])})
            result["fields"] = clean
        if "feedback" in value: result["feedback"] = _validate_feedback(value["feedback"], "payload.feedback")
        if "operations" in value:
            result["operations"] = _validate_workbench_operations_shape(value["operations"], "payload.operations")
            if kind == "concept.submit":
                _fail("payload.operations requires a published object baseline and is only valid for iteration.submit")
        return result
    if kind == "proposal.revise":
        _exact_keys(value, {"proposalId"}, {"answers", "supplement", "feedback", "assetRefs", "visualReferences"}, "payload")
        answers = value.get("answers", [])
        if not isinstance(answers, list) or len(answers) > 100: _fail("payload.answers must be bounded")
        clean_answers = []
        for i, answer in enumerate(answers):
            if not isinstance(answer, dict): _fail(f"payload.answers[{i}] must be an object")
            _exact_keys(answer, {"questionId", "text"}, where=f"payload.answers[{i}]")
            clean_answers.append({"questionId": _id(answer["questionId"], f"payload.answers[{i}].questionId"), "text": _string(answer["text"], f"payload.answers[{i}].text", 4000, minimum=0)})
        result = {"proposalId": _string(value["proposalId"], "payload.proposalId", 200), "answers": clean_answers}
        if "supplement" in value: result["supplement"] = _string(value["supplement"], "payload.supplement", 8000, minimum=0)
        if "feedback" in value: result["feedback"] = _validate_feedback(value["feedback"], "payload.feedback")
        if "assetRefs" in value: result["assetRefs"] = _string_list(value["assetRefs"], "payload.assetRefs")
        if "visualReferences" in value:
            from .concept_references import validate_visual_references
            result["visualReferences"] = validate_visual_references(value["visualReferences"], value.get("assetRefs", [r.get("assetId") for r in value["visualReferences"] if isinstance(r, dict)]))
        return result
    schemas = {
        "production.recover": ({"jobId", "attemptId", "artifactRef"}, set()),
        "proposal.assets.attach": ({"proposalId", "bundleId"}, set()),
        "proposal.freeze": ({"proposalId", "reviewedPlanRef"}, set()), "production.start": ({"packetId"}, set()),
        "execution.cancel": ({"ownerRef", "attemptId"}, set()), "execution.reconcile": ({"ownerRef", "attemptId"}, set()),
        "preview.start": (set(), {"candidateId", "snapshotId"}), "preview.stop": ({"previewId"}, set()),
        "candidate.accept": ({"candidateId", "sourceCommit"}, {"experienceDecisions"}), "candidate.reject": ({"candidateId", "sourceCommit"}, {"experienceDecisions"}),
    }
    if kind not in schemas:
        _fail("unsupported command type")
    required, optional = schemas[kind]
    _exact_keys(value, required, optional, "payload")
    result = copy.deepcopy(value)
    if kind == "production.recover":
        result["jobId"] = _string(value["jobId"], "payload.jobId", 200)
        result["artifactRef"] = _validate_artifact_ref(value["artifactRef"], "payload.artifactRef")
    if kind == "preview.start":
        if ("candidateId" in value) == ("snapshotId" in value): _fail("preview.start requires exactly one of candidateId or snapshotId")
        key = "candidateId" if "candidateId" in value else "snapshotId"
        return {key: _string(value[key], "payload." + key, 200)}
    for key in required & {"proposalId", "bundleId", "reviewedPlanRef", "packetId", "attemptId", "candidateId", "sourceCommit", "previewId"}:
        result[key] = _string(value[key], "payload." + key, 200)
    if "ownerRef" in required:
        owner = value["ownerRef"]
        if not isinstance(owner, dict): _fail("payload.ownerRef must be an object")
        _exact_keys(owner, {"kind", "id"}, {"revision"}, "payload.ownerRef")
        if owner["kind"] not in {"proposal", "job", "preview", "visual-plan"}: _fail("payload.ownerRef.kind is unsupported")
        result["ownerRef"] = {"kind": owner["kind"], "id": _string(owner["id"], "payload.ownerRef.id", 200)}
        if "revision" in owner: result["ownerRef"]["revision"] = _nonnegative_int(owner["revision"], "payload.ownerRef.revision")
    if "experienceDecisions" in value:
        decisions = value["experienceDecisions"]
        if not isinstance(decisions, list) or len(decisions) > 100: _fail("payload.experienceDecisions must be bounded")
        out=[]
        for i, decision in enumerate(decisions):
            where=f"payload.experienceDecisions[{i}]"
            if not isinstance(decision, dict): _fail(where + " must be an object")
            _exact_keys(decision, {"feedbackId", "status", "reason"}, where=where)
            if decision["status"] not in {"accepted", "needs_followup", "resolved"}: _fail(where + ".status is unsupported")
            out.append({"feedbackId": _id(decision["feedbackId"], where + ".feedbackId"), "status": decision["status"], "reason": _string(decision["reason"], where + ".reason", 2000)})
        if len({item["feedbackId"] for item in out}) != len(out): _fail("experienceDecisions contains duplicate feedbackId")
        result["experienceDecisions"] = out
    return result


COMMAND_TYPES = {"project.create", "project.settings.update", "session.preferences.update", "concept.submit", "iteration.submit", "proposal.revise", "proposal.assets.attach", "proposal.freeze", "production.start", "production.recover", "execution.cancel", "execution.reconcile", "preview.start", "preview.stop", "candidate.accept", "candidate.reject"}


def validate_command(message: object) -> dict:
    """Validate and normalize a strict studio.message.v1 command envelope."""
    if not isinstance(message, dict): _fail("command must be an object")
    _exact_keys(message, {"schemaVersion", "kind", "type", "storeId", "commandId", "payload"}, {"projectId", "expected"}, "command")
    if message["schemaVersion"] != MESSAGE_VERSION or message["kind"] != "command": _fail("command must use studio.message.v1 kind=command")
    command_type = message["type"]
    if command_type not in COMMAND_TYPES: _fail("unsupported command type")
    if command_type == "project.create":
        if "projectId" in message: _fail("project.create must not include projectId")
    elif "projectId" not in message:
        _fail("project-scoped command requires projectId")
    result = {"schemaVersion": MESSAGE_VERSION, "kind": "command", "type": command_type,
              "storeId": _string(message["storeId"], "storeId", 200), "commandId": _string(message["commandId"], "commandId", 200),
              "payload": _validate_command_payload(command_type, message["payload"])}
    if "projectId" in message: result["projectId"] = _string(message["projectId"], "projectId", 200)
    if "expected" in message: result["expected"] = _validate_expected(message["expected"])
    if command_type in {"session.preferences.update", "concept.submit", "iteration.submit", "proposal.revise"}:
        if "expected" not in result or "preferencesRevision" not in result["expected"]: _fail("command requires expected.preferencesRevision")
    expected = result.get("expected", {})
    if command_type in {"concept.submit", "iteration.submit", "proposal.revise", "proposal.assets.attach", "proposal.freeze", "production.start", "production.recover", "candidate.accept", "candidate.reject"} and "publicationRevision" not in expected: _fail(f"{command_type} requires expected.publicationRevision")
    if command_type in {"concept.submit", "iteration.submit", "proposal.revise"} and "sourceCommit" not in expected: _fail(f"{command_type} requires expected.sourceCommit")
    if command_type in {"proposal.revise", "proposal.assets.attach", "proposal.freeze"} and "proposalRevision" not in expected: _fail(f"{command_type} requires expected.proposalRevision")
    if command_type in {"production.start", "candidate.accept", "candidate.reject"} and "preferencesRevision" not in expected: _fail(f"{command_type} requires expected.preferencesRevision")
    if len(canonical_json(result).encode("utf-8")) > MAX_REQUEST_BYTES: _fail("command exceeds maximum serialized size")
    return result


def validate_execution_request(request: object) -> dict:
    """Validate studio.execution.v1, including task-specific closed payloads."""
    if not isinstance(request, dict): _fail("execution request must be an object")
    required = {"schemaVersion", "storeId", "projectId", "taskKind", "ownerRef", "attemptId", "runnerId", "lease", "inputRefs", "scope"}
    _exact_keys(request, required, {"profileSnapshot"}, "executionRequest")
    if request["schemaVersion"] != EXECUTION_VERSION: _fail("execution request must use studio.execution.v1")
    task = request["taskKind"]
    if task not in {"plan", "visual-plan", "produce", "verify", "preview"}: _fail("unsupported execution taskKind")
    for key in ("storeId", "projectId", "attemptId", "runnerId"):
        _string(request[key], "executionRequest." + key, 200)
    owner = request["ownerRef"]
    if not isinstance(owner, dict): _fail("ownerRef must be an object")
    owner_required = {"kind", "id"} if "revision" not in owner else {"kind", "id", "revision"}
    _exact_keys(owner, owner_required, where="ownerRef")
    expected_owner = {"plan":"proposal", "visual-plan":"visual-plan", "produce":"job", "verify":"job", "preview":"preview"}[task]
    if owner["kind"] != expected_owner: _fail("ownerRef.kind does not match taskKind")
    _string(owner["id"], "ownerRef.id", 200)
    if "revision" in owner: _nonnegative_int(owner["revision"], "ownerRef.revision")
    lease = request["lease"]
    if not isinstance(lease, dict): _fail("lease must be an object")
    _exact_keys(lease, {"expiresAt"}, where="lease")
    try:
        datetime.fromisoformat(lease["expiresAt"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError): _fail("lease.expiresAt must be an ISO timestamp")
    profile = request.get("profileSnapshot")
    if task in {"verify", "preview"}:
        if profile is not None: _fail(f"{task} must not use an AI profile")
    else:
        if not isinstance(profile, dict): _fail("AI task requires profileSnapshot")
        _exact_keys(profile, {"preferencesRevision", "catalogRevision", "modelKey", "modelProvider", "effort", "rolePolicy", "contextPolicy", "limits"}, {"runnerId", "nativeVersion", "environment"}, "profileSnapshot")
        _nonnegative_int(profile["preferencesRevision"], "profileSnapshot.preferencesRevision")
        _nonnegative_int(profile["catalogRevision"], "profileSnapshot.catalogRevision")
        for key in ("modelKey", "modelProvider", "rolePolicy", "contextPolicy"):
            _string(profile[key], "profileSnapshot." + key, 200)
        for key in ("runnerId", "nativeVersion", "environment"):
            if key in profile: _string(profile[key], "profileSnapshot." + key, 200)
        if profile.get("runnerId", request["runnerId"]) != request["runnerId"]: _fail("profileSnapshot.runnerId does not match runnerId")
        if profile["effort"] not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}: _fail("profileSnapshot.effort is unsupported")
        limits = profile["limits"]
        if not isinstance(limits, dict): _fail("profileSnapshot.limits must be an object")
        _exact_keys(limits, {"maxDurationSeconds", "softTotalTokens"}, where="profileSnapshot.limits")
        if not 1 <= _nonnegative_int(limits["maxDurationSeconds"], "profileSnapshot.limits.maxDurationSeconds") <= 7200: _fail("profileSnapshot duration out of range")
        token_limit = limits["softTotalTokens"]
        if token_limit is not None and not 1 <= _nonnegative_int(token_limit, "profileSnapshot.limits.softTotalTokens") <= 2_000_000: _fail("profileSnapshot token limit out of range")
    refs = request["inputRefs"]
    scope = request["scope"]
    if not isinstance(refs, dict) or not isinstance(scope, dict): _fail("inputRefs and scope must be objects")
    if task == "visual-plan":
        _exact_keys(refs, {"visualPlanId", "assetRefs"}, where="inputRefs")
        _string(refs["visualPlanId"], "inputRefs.visualPlanId", 200)
        _string_list(refs["assetRefs"], "inputRefs.assetRefs")
        if refs["visualPlanId"] != owner["id"]: _fail("visual plan input and owner disagree")
        _exact_keys(scope, {"mode", "targetObjectIds", "allowProjectExecution"}, where="scope")
        if scope["mode"] != "inspection_only" or scope["allowProjectExecution"] is not False: _fail("visual planner must be read-only")
        _string_list(scope["targetObjectIds"], "scope.targetObjectIds", 500)
    elif task == "plan":
        _exact_keys(refs, {"sourceAvailable", "sourceCommit", "inspectionRef", "planningInputRef", "assetRefs"}, where="inputRefs")
        if type(refs["sourceAvailable"]) is not bool or (refs["sourceAvailable"] != (refs["sourceCommit"] is not None)): _fail("sourceAvailable and sourceCommit disagree")
        if refs["sourceCommit"] is not None: _string(refs["sourceCommit"], "inputRefs.sourceCommit", 200)
        for key in ("inspectionRef", "planningInputRef"): _string(refs[key], "inputRefs." + key, 200)
        _string_list(refs["assetRefs"], "inputRefs.assetRefs")
        _exact_keys(scope, {"mode", "targetObjectIds", "allowProjectExecution"}, where="scope")
        if scope["mode"] != "inspection_only" or scope["allowProjectExecution"] is not False: _fail("planner scope must be inspection_only and non-executing")
        _string_list(scope["targetObjectIds"], "scope.targetObjectIds", 500)
    elif task == "produce":
        _exact_keys(refs, {"packetId", "baseCommit", "inputCommit", "inputArtifactRef", "gmConfirmationRef", "assetRefs"}, where="inputRefs")
        _string(refs["packetId"], "inputRefs.packetId", 200)
        if refs["baseCommit"] is not None: _string(refs["baseCommit"], "inputRefs.baseCommit", 200)
        _string(refs["inputCommit"], "inputRefs.inputCommit", 200)
        _string(refs["gmConfirmationRef"], "inputRefs.gmConfirmationRef", 200)
        _validate_artifact_ref(refs["inputArtifactRef"], "inputRefs.inputArtifactRef")
        _string_list(refs["assetRefs"], "inputRefs.assetRefs")
        _exact_keys(scope, {"mode", "allowedFiles", "allowProjectExecution"}, where="scope")
        if scope["mode"] != "private_workspace" or scope["allowProjectExecution"] is not False: _fail("producer scope must be private_workspace and non-executing")
        if not isinstance(scope["allowedFiles"], list) or not scope["allowedFiles"]: _fail("scope.allowedFiles must be non-empty")
        for i, path in enumerate(scope["allowedFiles"]): _string(path, f"scope.allowedFiles[{i}]", 240)
    elif task == "verify":
        _exact_keys(refs, {"artifactRef", "packetId", "inputCommit", "sourceCommit"}, where="inputRefs")
        _validate_artifact_ref(refs["artifactRef"], "inputRefs.artifactRef")
        for key in ("packetId", "inputCommit", "sourceCommit"): _string(refs[key], "inputRefs." + key, 200)
        _exact_keys(scope, {"mode", "sourceReadOnly", "cacheScope", "allowProjectExecution"}, where="scope")
        if scope["mode"] != "verification_copy" or scope["sourceReadOnly"] is not True or scope["cacheScope"] != ".godot" or scope["allowProjectExecution"] is not True: _fail("verification requires an isolated read-only source copy and bounded cache scope")
    else:
        _exact_keys(refs, {"artifactRef"}, where="inputRefs")
        _validate_artifact_ref(refs["artifactRef"], "inputRefs.artifactRef")
        _exact_keys(scope, {"mode", "sourceReadOnly", "cacheScope", "allowProjectExecution"}, where="scope")
        if scope["mode"] != "preview_copy" or scope["sourceReadOnly"] is not True or scope["cacheScope"] != ".godot" or scope["allowProjectExecution"] is not True: _fail("preview requires a separate read-only preview copy")
    return copy.deepcopy(request)


def _validate_artifact_ref(value: object, where: str) -> dict:
    if not isinstance(value, dict): _fail(f"{where} must be an ArtifactRef object")
    _exact_keys(value, {"artifactId", "projectId", "jobId", "attemptId", "sourceCommit", "inputCommit", "packetId"}, where=where)
    for key in value: _string(value[key], where + "." + key, 200)
    return value


def validate_execution_report(report: object, *, validate_planner_result: bool = True) -> dict:
    """Validate report facts; receipt handling may defer planner semantics.

    Only the trusted receipt handler defers those semantics, so it can retain
    an invalid result and acknowledge rejection after checking report identity.
    Other callers keep strict result validation by default.
    """
    if not isinstance(report, dict): _fail("execution report must be an object")
    _exact_keys(report, {"schemaVersion", "kind", "type", "storeId", "projectId", "runnerId", "reportId", "attemptId", "taskKind", "payload"}, where="executionReport")
    if report["schemaVersion"] != MESSAGE_VERSION or report["kind"] != "execution_report": _fail("report must use studio.message.v1 kind=execution_report")
    if report["type"] not in {"started", "activity", "usage", "completed", "stopped", "failed"}: _fail("unsupported report type")
    if report["taskKind"] not in {"plan", "visual-plan", "produce", "verify", "preview"}: _fail("unsupported report taskKind")
    for key in ("storeId", "projectId", "runnerId", "reportId", "attemptId"): _string(report[key], "report." + key, 200)
    payload = report["payload"]
    if not isinstance(payload, dict): _fail("report.payload must be an object")
    if report["type"] == "started":
        _exact_keys(payload, {"nativeIdentity", "startedAt", "requestedProfile", "reportedProfile", "threadStartReported", "turnStartAcknowledged", "actualProfile"}, where="report.payload")
        if not isinstance(payload["nativeIdentity"], dict): _fail("nativeIdentity must be an object")
        _exact_keys(payload["nativeIdentity"], {"threadId", "turnId", "processId", "processGroupId", "processStartTime"}, where="report.payload.nativeIdentity")
        for key in ("threadId", "turnId", "processStartTime"):
            if payload["nativeIdentity"][key] is not None: _string(payload["nativeIdentity"][key], "report.payload.nativeIdentity." + key, 200)
        for key in ("processId", "processGroupId"):
            if payload["nativeIdentity"][key] is not None: _nonnegative_int(payload["nativeIdentity"][key], "report.payload.nativeIdentity." + key)
        has_thread = payload["nativeIdentity"]["threadId"] is not None and payload["nativeIdentity"]["turnId"] is not None
        has_process = payload["nativeIdentity"]["processId"] is not None and payload["nativeIdentity"]["processGroupId"] is not None and payload["nativeIdentity"]["processStartTime"] is not None
        if not (has_thread or has_process): _fail("nativeIdentity must contain a complete thread or process identity")
        for key in ("requestedProfile", "reportedProfile", "actualProfile"):
            if payload[key] is not None:
                if not isinstance(payload[key], dict): _fail("reported profile fields must be objects or null")
                _exact_keys(payload[key], {"modelKey", "modelProvider", "effort"}, where="report.payload." + key)
                for profile_key in payload[key]:
                    if payload[key][profile_key] is not None: _string(payload[key][profile_key], "report.payload." + key + "." + profile_key, 200)
        for key in ("threadStartReported", "turnStartAcknowledged"):
            if payload[key] is not None and not isinstance(payload[key], dict): _fail("start observation must be object or null")
            if isinstance(payload[key], dict):
                if key == "threadStartReported":
                    _exact_keys(payload[key], {"model", "provider", "reasoningEffort"}, where="report.payload." + key)
                    for field in ("model", "provider", "reasoningEffort"):
                        if payload[key][field] is not None: _string(payload[key][field], "report.payload." + key + "." + field, 200)
                else:
                    _exact_keys(payload[key], {"turnId", "status"}, where="report.payload." + key)
                    for field in ("turnId", "status"):
                        if payload[key][field] is not None: _string(payload[key][field], "report.payload." + key + "." + field, 200)
    elif report["type"] == "activity":
        _exact_keys(payload, {"activityKind", "observedAt", "summary"}, where="report.payload")
        _string(payload["activityKind"], "report.payload.activityKind", 80)
        _string(payload["summary"], "report.payload.summary", 240, minimum=0)
    elif report["type"] == "usage":
        _exact_keys(payload, {"totalTokens", "observedAt", "coverage"}, where="report.payload")
        if payload["totalTokens"] is not None: _nonnegative_int(payload["totalTokens"], "report.payload.totalTokens")
        if payload["coverage"] not in {"unknown", "native_thread", "incomplete"}: _fail("usage coverage is unsupported")
    elif report["type"] == "completed":
        _exact_keys(payload, {"result"}, {"artifactRef", "sourceCommit", "stopped"}, "report.payload")
        if payload.get("stopped", True) is not True: _fail("completed report requires stopped=true")
        if "artifactRef" in payload: _validate_artifact_ref(payload["artifactRef"], "report.payload.artifactRef")
        if "sourceCommit" in payload and payload["sourceCommit"] is not None: _string(payload["sourceCommit"], "report.payload.sourceCommit", 200)
        result = payload["result"]
        if report["taskKind"] == "plan":
            if validate_planner_result:
                if isinstance(result, dict) and set(result) == {"response"}: result = result["response"]
                if isinstance(result, str): result = _strict_json(result)
                _validate_planner_result(result)
        elif report["taskKind"] == "visual-plan":
            if validate_planner_result:
                if isinstance(result, dict) and set(result) == {"response"}: result = result["response"]
                if isinstance(result, str): result = _strict_json(result)
                if not isinstance(result, dict): _fail("visual plan result must be an object")
        elif report["taskKind"] == "verify":
            if not isinstance(result, dict): _fail("verification result must be an object")
            _exact_keys(result, {"status", "sourceCommit", "sourceUnchanged", "checks", "evidenceRef"}, where="report.payload.result")
            if result["status"] not in {"PASS", "FAIL"} or type(result["sourceUnchanged"]) is not bool: _fail("verification result status/source evidence is invalid")
            if not isinstance(result["checks"], list) or len(result["checks"]) > 200: _fail("verification checks must be a bounded list")
            for index, check in enumerate(result["checks"]):
                where = f"report.payload.result.checks[{index}]"
                if not isinstance(check, dict): _fail(where + " must be an object")
                _exact_keys(check, {"id", "status"}, {"summary"}, where)
                _string(check["id"], where + ".id", 120)
                if check["status"] not in {"PASS", "FAIL", "SKIPPED"}: _fail(where + ".status is unsupported")
                if "summary" in check: _string(check["summary"], where + ".summary", 400, minimum=0)
            _string(result["sourceCommit"], "report.payload.result.sourceCommit", 200)
            _string(result["evidenceRef"], "report.payload.result.evidenceRef", 200)
        elif not isinstance(result, dict): _fail("produce/preview result must be an object")
    elif report["type"] in {"stopped", "failed"}:
        optional = {"diagnosticRef", "launchPrevented", "nativeFailure"} if report["type"] == "failed" else {"diagnosticRef", "nativeFailure"}
        _exact_keys(payload, {"stopped", "stopReason"}, optional, "report.payload")
        if type(payload["stopped"]) is not bool: _fail("stopped must be boolean")
        if payload["stopReason"] not in {"cancelled", "time_limit", "soft_budget", "native_error", "requested", "unknown"}: _fail("stopReason is unsupported")
        if "diagnosticRef" in payload: _string(payload["diagnosticRef"], "report.payload.diagnosticRef", 200)
        if "nativeFailure" in payload:
            failure = payload["nativeFailure"]
            if not isinstance(failure, dict): _fail("nativeFailure must be an object")
            _exact_keys(failure, {"reason", "nativeStatus", "elapsedSeconds", "connectionInterrupted"}, where="nativeFailure")
            if not isinstance(failure["reason"], str) or failure["reason"] not in {"unknown", "context_limit", "rate_limit", "authentication", "timeout", "stream_interrupted", "network_error", "provider_rejected", "model_unavailable", "cancelled", "output_error"}:
                _fail("nativeFailure.reason is unsupported")
            if failure["nativeStatus"] is not None and (not isinstance(failure["nativeStatus"], str) or failure["nativeStatus"] not in {"completed", "failed", "timeout", "cancelled", "uncertain", "server_exited"}):
                _fail("nativeFailure.nativeStatus is unsupported")
            if failure["elapsedSeconds"] is not None and _finite_number(failure["elapsedSeconds"], "nativeFailure.elapsedSeconds") < 0:
                _fail("nativeFailure.elapsedSeconds must be nonnegative")
            if type(failure["connectionInterrupted"]) is not bool: _fail("nativeFailure.connectionInterrupted must be boolean")
            if report["taskKind"] not in {"plan", "visual-plan", "produce"} or payload["stopReason"] != "native_error":
                _fail("nativeFailure requires a native Agent failure")
        if "launchPrevented" in payload:
            if (payload["launchPrevented"] is not True or payload["stopped"] is not True
                    or payload["stopReason"] != "native_error" or report["taskKind"] not in {"plan", "visual-plan", "produce"}):
                _fail("launchPrevented requires an Agent setup failure with stopped=true")
    if "observedAt" in payload: _string(payload["observedAt"], "report.payload.observedAt", 80)
    if "startedAt" in payload: _string(payload["startedAt"], "report.payload.startedAt", 80)
    return copy.deepcopy(report)


def _finite_number(value: object, where: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{where} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _fail(f"{where} must be a finite number")
    return value


def _aligns_to_step(value: int | float, base: int | float, step: int | float) -> bool:
    try:
        return (Decimal(str(value)) - Decimal(str(base))) % Decimal(str(step)) == 0
    except (InvalidOperation, ZeroDivisionError):
        return False


def _path(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value:
        _fail(f"{where} is not a safe project-relative path")
    parts = value.split("/")
    if (len(parts) < 2 or parts[0] not in PATH_ROOTS or
            any(p in ("", ".", "..") or p.startswith(".") for p in parts) or
            ":" in value or value.startswith("/")):
        _fail(f"{where} must be under scripts/, scenes/, resources/, or assets/")
    suffix = "." + parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if suffix not in PATH_EXTENSIONS:
        _fail(f"{where} has an unsupported file extension")
    if parts[0] == "scripts" and suffix != ".gd":
        _fail(f"{where}: scripts/ accepts only GDScript files")
    if parts[0] == "scenes" and suffix != ".tscn":
        _fail(f"{where}: scenes/ accepts only text scenes")
    if parts[0] == "resources" and suffix != ".tres":
        _fail(f"{where}: resources/ accepts only native resource files")
    if parts[0] == "assets" and suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        _fail(f"{where}: assets/ currently accepts only PNG, JPEG, and WebP files")
    return value


def _validate_field(field: object, where: str) -> dict:
    if not isinstance(field, dict):
        _fail(f"{where} must be an object")
    required = {"id", "label", "type", "value", "editable"}
    optional = {"min", "max", "step", "unit", "options"}
    _exact_keys(field, required, optional, where)
    result = copy.deepcopy(field)
    result["id"] = _id(result["id"], where + ".id")
    result["label"] = _string(result["label"], where + ".label", 120)
    if "unit" in result:
        result["unit"] = _string(result["unit"], where + ".unit", 40)
    kind = result["type"]
    if kind not in FIELD_TYPES:
        _fail(f"{where}.type is unsupported")
    if type(result["editable"]) is not bool:
        _fail(f"{where}.editable must be boolean")

    if kind in {"number", "integer"}:
        if not {"min", "max"} <= set(result):
            _fail(f"{where} numeric fields require min and max")
        low = _finite_number(result["min"], where + ".min")
        high = _finite_number(result["max"], where + ".max")
        current = _finite_number(result["value"], where + ".value")
        if low > high or not low <= current <= high:
            _fail(f"{where} value must be within ordered bounds")
        if kind == "integer" and any(not float(v).is_integer() for v in (low, high, current)):
            _fail(f"{where} integer values and bounds must be integral")
        if "step" in result:
            step = _finite_number(result["step"], where + ".step")
            if step <= 0 or (kind == "integer" and not float(step).is_integer()):
                _fail(f"{where}.step must be positive and compatible with the field type")
            if current != low and not _aligns_to_step(current, low, step):
                _fail(f"{where}.value must align to the declared step")
        if "options" in result:
            _fail(f"{where} numeric fields cannot have options")
    elif kind == "choice":
        options = result.get("options")
        if not isinstance(options, list) or not options or len(options) > 100:
            _fail(f"{where}.options must be a non-empty list")
        normalized = []
        for i, option in enumerate(options):
            if isinstance(option, bool) or not isinstance(option, (str, int, float)):
                _fail(f"{where}.options[{i}] must be a scalar")
            if isinstance(option, float) and not math.isfinite(option):
                _fail(f"{where}.options[{i}] must be finite")
            normalized.append(option)
        if len({(type(v).__name__, str(v)) for v in normalized}) != len(normalized) or not any(type(v) is type(result["value"]) and v == result["value"] for v in normalized):
            _fail(f"{where}.value must match one unique option")
        if {"min", "max", "step"} & set(result):
            _fail(f"{where} choice fields cannot have numeric bounds")
    elif kind == "boolean":
        if type(result["value"]) is not bool or {"min", "max", "step", "options"} & set(result):
            _fail(f"{where} boolean field has invalid value or constraints")
    elif kind in {"text", "color"}:
        value = result["value"]
        if not isinstance(value, str) or len(value) > 4000:
            _fail(f"{where}.value must be a bounded string")
        if kind == "color" and not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
            _fail(f"{where}.value must be #RRGGBB or #RRGGBBAA")
        if {"min", "max", "step", "options"} & set(result):
            _fail(f"{where} text/color fields cannot have numeric bounds or options")
    elif kind == "vector2":
        value = result["value"]
        if not isinstance(value, list) or len(value) != 2:
            _fail(f"{where}.value must contain exactly two numbers")
        result["value"] = [_finite_number(v, where + ".value") for v in value]
        if {"min", "max", "step", "options"} & set(result):
            _fail(f"{where} vector2 fields cannot have scalar bounds or options")
    return result


def _workbench_source_path(value: object, where: str) -> str:
    """Validate a read-only provenance path without widening sourceBindings."""
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or value.startswith("/") or ":" in value:
        _fail(f"{where} is not a safe project-relative provenance path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        _fail(f"{where} is not a safe project-relative provenance path")
    if len(parts) == 1 and value in WORKBENCH_DOCUMENT_FILES:
        return value
    if len(parts) < 2 or parts[0] not in WORKBENCH_DOCUMENT_ROOTS:
        _fail(f"{where} must reference a project source or document path")
    if parts[0] in PATH_ROOTS:
        return _path(value, where)
    suffix = "." + parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if (parts[0] == "design" and suffix != ".json") or (parts[0] == "docs" and suffix not in {".md", ".txt", ".json"}):
        _fail(f"{where} has an unsupported documentation extension")
    return value


def _workbench_pair(value: object, where: str, *, positive: bool = False, normalized: bool = False) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        _fail(f"{where} must contain exactly two numbers")
    pair = [_finite_number(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if positive and any(item <= 0 for item in pair):
        _fail(f"{where} values must be positive")
    if normalized and any(not 0 <= item <= 1 for item in pair):
        _fail(f"{where} values must be between 0 and 1")
    return pair


def _validate_workbench(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    required = {"role", "scope", "provenance", "preview"}
    optional = {"definitionId", "sceneId", "destinationSceneId", "targetSceneId", "entryId", "exitId", "presetId", "sourceCommit", "overrides",
                "lock", "position", "size", "positionFieldId", "sizeFieldId", "bounds", "anchor", "driver", "lifecycle", "trigger",
                "positionPolicy", "cleanup", "condition", "guard", "fromState", "toState", "mode", "facets", "usage"}
    _exact_keys(value, required, optional, where)
    result = copy.deepcopy(value)
    if result["role"] not in WORKBENCH_ROLES:
        _fail(f"{where}.role is unsupported")
    if result["scope"] not in WORKBENCH_SCOPES:
        _fail(f"{where}.scope is unsupported")
    for key in ("definitionId", "sceneId", "destinationSceneId", "targetSceneId", "entryId", "exitId", "presetId"):
        if key in result and result[key] is not None:
            result[key] = _id(result[key], f"{where}.{key}")
    for key in ("positionFieldId", "sizeFieldId"):
        if key in result:
            result[key] = _id(result[key], f"{where}.{key}")
    if "sourceCommit" in result:
        result["sourceCommit"] = _string(result["sourceCommit"], f"{where}.sourceCommit", 200)
    if "overrides" in result:
        overrides = result["overrides"]
        if not isinstance(overrides, dict):
            _fail(f"{where}.overrides must be an object")
        _exact_keys(overrides, set(), {"role", "scope", "lock", "position", "size", "bounds", "anchor", "lifecycle",
                "trigger", "positionPolicy", "cleanup", "condition", "guard", "mode", "facets", "usage"}, f"{where}.overrides")
        normalized_overrides = copy.deepcopy(overrides)
        if "role" in normalized_overrides and normalized_overrides["role"] not in WORKBENCH_ROLES:
            _fail(f"{where}.overrides.role is unsupported")
        if "scope" in normalized_overrides and normalized_overrides["scope"] not in WORKBENCH_SCOPES:
            _fail(f"{where}.overrides.scope is unsupported")
        if "lock" in normalized_overrides and normalized_overrides["lock"] not in WORKBENCH_LOCKS:
            _fail(f"{where}.overrides.lock is unsupported")
        for key in ("position", "size", "bounds", "anchor"):
            if key in normalized_overrides:
                normalized_overrides[key] = _workbench_pair(normalized_overrides[key], f"{where}.overrides.{key}",
                    positive=key in {"size", "bounds"}, normalized=key == "anchor")
        for key in ("lifecycle", "trigger", "positionPolicy", "cleanup", "condition", "guard", "mode"):
            if key in normalized_overrides:
                normalized_overrides[key] = _string(normalized_overrides[key], f"{where}.overrides.{key}", 1000)
        if "facets" in normalized_overrides:
            facets = normalized_overrides["facets"]
            if not isinstance(facets, dict):
                _fail(f"{where}.overrides.facets must be an object")
            _exact_keys(facets, set(), {"narrative", "art"}, f"{where}.overrides.facets")
            normalized_overrides["facets"] = {key: _string(item, f"{where}.overrides.facets.{key}", 2000, minimum=0)
                                                for key, item in facets.items()}
        if "usage" in normalized_overrides:
            normalized_overrides["usage"] = _string_list(normalized_overrides["usage"], f"{where}.overrides.usage", MAX_OBJECTS)
        result["overrides"] = normalized_overrides
    if "lock" in result and result["lock"] not in WORKBENCH_LOCKS:
        _fail(f"{where}.lock is unsupported")
    for key in ("position", "size", "bounds", "anchor"):
        if key in result:
            result[key] = _workbench_pair(result[key], f"{where}.{key}",
                positive=key in {"size", "bounds"}, normalized=key == "anchor")
    if "driver" in result:
        result["driver"] = _workbench_source_path(result["driver"], f"{where}.driver")
    for key in ("lifecycle", "trigger", "positionPolicy", "cleanup", "condition", "guard", "fromState", "toState", "mode"):
        if key in result:
            result[key] = _string(result[key], f"{where}.{key}", 1000)

    provenance = result["provenance"]
    if not isinstance(provenance, dict):
        _fail(f"{where}.provenance must be an object")
    _exact_keys(provenance, {"kind", "sourcePaths"}, where=f"{where}.provenance")
    if provenance["kind"] not in WORKBENCH_PROVENANCE_KINDS:
        _fail(f"{where}.provenance.kind is unsupported")
    source_paths = provenance["sourcePaths"]
    if not isinstance(source_paths, list) or len(source_paths) > MAX_PATHS_PER_OBJECT:
        _fail(f"{where}.provenance.sourcePaths must be a bounded list")
    provenance["sourcePaths"] = [_workbench_source_path(path, f"{where}.provenance.sourcePaths[{index}]")
                                  for index, path in enumerate(source_paths)]
    if len(provenance["sourcePaths"]) != len(set(provenance["sourcePaths"])):
        _fail(f"{where}.provenance.sourcePaths contains duplicates")

    preview = result["preview"]
    if not isinstance(preview, dict):
        _fail(f"{where}.preview must be an object")
    _exact_keys(preview, {"type", "label", "stages"}, {"speed", "speedFieldId", "imagePath", "resourcePath", "clipName"}, f"{where}.preview")
    if preview["type"] not in WORKBENCH_PREVIEW_TYPES:
        _fail(f"{where}.preview.type is unsupported")
    preview["label"] = _string(preview["label"], f"{where}.preview.label", 160)
    if not isinstance(preview["stages"], list) or len(preview["stages"]) > 100:
        _fail(f"{where}.preview.stages must be a bounded list")
    stages = []
    for index, stage in enumerate(preview["stages"]):
        place = f"{where}.preview.stages[{index}]"
        if not isinstance(stage, dict):
            _fail(f"{place} must be an object")
        _exact_keys(stage, {"label", "duration"}, {"durationFieldId"}, place)
        duration = _finite_number(stage["duration"], place + ".duration")
        if duration < 0:
            _fail(f"{place}.duration must be non-negative")
        normalized_stage = {"label": _string(stage["label"], place + ".label", 160), "duration": duration}
        if "durationFieldId" in stage:
            normalized_stage["durationFieldId"] = _id(stage["durationFieldId"], place + ".durationFieldId")
        stages.append(normalized_stage)
    preview["stages"] = stages
    if "speed" in preview:
        speed = _finite_number(preview["speed"], f"{where}.preview.speed")
        if speed < 0:
            _fail(f"{where}.preview.speed must be non-negative")
        preview["speed"] = speed
    if "speedFieldId" in preview:
        preview["speedFieldId"] = _id(preview["speedFieldId"], f"{where}.preview.speedFieldId")
    if "imagePath" in preview:
        preview["imagePath"] = _path(preview["imagePath"], f"{where}.preview.imagePath")
    if "resourcePath" in preview:
        preview["resourcePath"] = _path(preview["resourcePath"], f"{where}.preview.resourcePath")
        if not preview["resourcePath"].endswith(".tres"):
            _fail(f"{where}.preview.resourcePath must reference a .tres resource")
    if "clipName" in preview:
        if "resourcePath" not in preview:
            _fail(f"{where}.preview.clipName requires resourcePath")
        preview["clipName"] = _string(preview["clipName"], f"{where}.preview.clipName", 160)

    if "facets" in result:
        facets = result["facets"]
        if not isinstance(facets, dict):
            _fail(f"{where}.facets must be an object")
        _exact_keys(facets, set(), {"narrative", "art"}, f"{where}.facets")
        result["facets"] = {key: _string(item, f"{where}.facets.{key}", 2000, minimum=0)
                             for key, item in facets.items()}
    if "usage" in result:
        result["usage"] = _string_list(result["usage"], f"{where}.usage", MAX_OBJECTS)

    role = result["role"]
    if role == "instance" and not {"definitionId", "sceneId", "lock", "position"} <= set(result):
        _fail(f"{where} instance requires definitionId, sceneId, lock, and position")
    if role == "entry" and not {"sceneId", "position"} <= set(result):
        _fail(f"{where} entry requires sceneId and position")
    if role == "transition":
        destination = result.get("destinationSceneId", result.get("targetSceneId"))
        if not result.get("sceneId") or not destination:
            _fail(f"{where} transition requires source and destination scene IDs")
        if result.get("destinationSceneId") and result.get("targetSceneId") and result["destinationSceneId"] != result["targetSceneId"]:
            _fail(f"{where} destinationSceneId and targetSceneId disagree")
        if result.get("mode") == "preset" and not result.get("presetId"):
            _fail(f"{where} preset mode requires presetId")
    return result


def _validate_document(document: object) -> dict:
    if not isinstance(document, dict):
        _fail("document must be a JSON object")
    _exact_keys(document, {"schemaVersion", "dimension", "title", "summary", "objects", "requirements"}, where="document")
    if document["schemaVersion"] != DOCUMENT_VERSION or document["dimension"] != "2d":
        _fail("document must use studio.objects.v1 and dimension 2d")
    result = copy.deepcopy(document)
    result["title"] = _string(result["title"], "document.title", 160)
    result["summary"] = _string(result["summary"], "document.summary", 8000)
    objects = result["objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= MAX_OBJECTS:
        _fail(f"document.objects must contain 1..{MAX_OBJECTS} objects")
    object_map: dict[str, dict] = {}
    for index, obj in enumerate(objects):
        where = f"objects[{index}]"
        if not isinstance(obj, dict):
            _fail(f"{where} must be an object")
        _exact_keys(obj, {"id", "kind", "name", "sourceBindings"}, {"description", "parentId", "relations", "fields", "workbench"}, where)
        obj["id"] = _id(obj["id"], where + ".id")
        if obj["id"] in object_map:
            _fail(f"duplicate object id: {obj['id']}")
        if obj["kind"] not in KINDS:
            _fail(f"{where}.kind is unsupported")
        obj["name"] = _string(obj["name"], where + ".name", 160)
        obj.setdefault("description", "")
        if not isinstance(obj["description"], str) or len(obj["description"]) > 4000:
            _fail(f"{where}.description must be a bounded string")
        obj.setdefault("parentId", None)
        if obj["parentId"] is not None:
            obj["parentId"] = _id(obj["parentId"], where + ".parentId")
        obj.setdefault("relations", [])
        if not isinstance(obj["relations"], list) or len(obj["relations"]) > 500:
            _fail(f"{where}.relations must be a bounded list")
        for j, relation in enumerate(obj["relations"]):
            if not isinstance(relation, dict):
                _fail(f"{where}.relations[{j}] must be an object")
            _exact_keys(relation, {"type", "targetId"}, where=f"{where}.relations[{j}]")
            relation["type"] = _string(relation["type"], f"{where}.relations[{j}].type", 80)
            relation["targetId"] = _id(relation["targetId"], f"{where}.relations[{j}].targetId")
        bindings = obj["sourceBindings"]
        if not isinstance(bindings, list) or len(bindings) > MAX_PATHS_PER_OBJECT:
            _fail(f"{where}.sourceBindings must be a bounded list")
        obj["sourceBindings"] = [_path(p, f"{where}.sourceBindings[{j}]") for j, p in enumerate(bindings)]
        if len(set(obj["sourceBindings"])) != len(obj["sourceBindings"]):
            _fail(f"{where}.sourceBindings contains duplicates")
        obj.setdefault("fields", [])
        fields = obj["fields"]
        if not isinstance(fields, list) or len(fields) > MAX_FIELDS_PER_OBJECT:
            _fail(f"{where}.fields must be a bounded list")
        obj["fields"] = [_validate_field(field, f"{where}.fields[{j}]") for j, field in enumerate(fields)]
        field_ids = [field["id"] for field in obj["fields"]]
        if len(set(field_ids)) != len(field_ids):
            _fail(f"{where}.fields contains duplicate IDs")
        if "workbench" in obj:
            obj["workbench"] = _validate_workbench(obj["workbench"], f"{where}.workbench")
        object_map[obj["id"]] = obj

    # Validate links after collecting IDs, then reject parent cycles.
    for obj in objects:
        if obj["parentId"] is not None and obj["parentId"] not in object_map:
            _fail(f"unknown parent object: {obj['parentId']}")
        for relation in obj["relations"]:
            if relation["targetId"] not in object_map:
                _fail(f"unknown relation target: {relation['targetId']}")
        metadata = obj.get("workbench")
        if metadata is None:
            continue
        for key in ("definitionId", "sceneId", "destinationSceneId", "targetSceneId", "entryId", "exitId", "presetId"):
            target_id = metadata.get(key)
            if target_id is not None and target_id not in object_map:
                _fail(f"unknown workbench {key}: {target_id}")
        for target_id in metadata.get("usage", []):
            if target_id not in object_map:
                _fail(f"unknown workbench usage target: {target_id}")
        for target_id in (metadata.get("overrides") or {}).get("usage", []):
            if target_id not in object_map:
                _fail(f"unknown workbench override usage target: {target_id}")
        role = metadata["role"]
        if role in {"instance", "entry", "spawn", "transition"} and metadata.get("sceneId"):
            if object_map[metadata["sceneId"]]["kind"] != "scene":
                _fail(f"{obj['id']} workbench.sceneId must reference a scene object")
        if role in {"instance", "entry"} and metadata.get("definitionId"):
            if object_map[metadata["definitionId"]].get("workbench", {}).get("role") != "definition":
                _fail(f"{obj['id']} workbench.definitionId must reference a definition")
        if role == "instance" and object_map[metadata["definitionId"]].get("workbench", {}).get("role") != "definition":
            _fail(f"{obj['id']} workbench.definitionId must reference a definition")
        if role == "transition":
            destination_id = metadata.get("destinationSceneId") or metadata.get("targetSceneId")
            if object_map[destination_id]["kind"] != "scene":
                _fail(f"{obj['id']} workbench destination must reference a scene object")
            for key in ("entryId", "exitId"):
                target_id = metadata.get(key)
                if target_id and object_map[target_id].get("workbench", {}).get("role") != "entry":
                    _fail(f"{obj['id']} workbench.{key} must reference an entry/exit marker")
            if metadata.get("entryId") and object_map[metadata["entryId"]]["workbench"].get("sceneId") != destination_id:
                _fail(f"{obj['id']} workbench.entryId must belong to the destination scene")
            if metadata.get("exitId") and object_map[metadata["exitId"]]["workbench"].get("sceneId") != metadata["sceneId"]:
                _fail(f"{obj['id']} workbench.exitId must belong to the source scene")
            if metadata.get("presetId") and object_map[metadata["presetId"]].get("workbench", {}).get("role") != "preset":
                _fail(f"{obj['id']} workbench.presetId must reference a preset")
        preview = metadata["preview"]
        field_types = {field["id"]: field["type"] for field in obj["fields"]}
        for key in ("positionFieldId", "sizeFieldId"):
            field_id = metadata.get(key)
            if field_id is None:
                continue
            if field_types.get(field_id) != "vector2":
                _fail(f"{obj['id']} workbench.{key} must reference a vector2 field on the same object")
            field = next(field for field in obj["fields"] if field["id"] == field_id)
            _workbench_pair(field["value"], f"{obj['id']} workbench.{key} value", positive=key == "sizeFieldId")
        speed_field_id = preview.get("speedFieldId")
        if speed_field_id is not None and field_types.get(speed_field_id) not in {"number", "integer"}:
            _fail(f"{obj['id']} preview.speedFieldId must reference a numeric field on the same object")
        for stage_index, stage in enumerate(preview["stages"]):
            duration_field_id = stage.get("durationFieldId")
            if duration_field_id is not None and field_types.get(duration_field_id) not in {"number", "integer"}:
                _fail(f"{obj['id']} preview.stages[{stage_index}].durationFieldId must reference a numeric field on the same object")
        if preview["type"] == "image" and preview.get("imagePath") is None and preview.get("resourcePath") is None:
            _fail(f"{obj['id']} image preview must use a bound source asset")
        if preview.get("imagePath") is not None and preview["imagePath"] not in obj["sourceBindings"]:
            _fail(f"{obj['id']} preview.imagePath must be in sourceBindings")
        if preview.get("resourcePath") is not None and preview["resourcePath"] not in obj["sourceBindings"]:
            _fail(f"{obj['id']} preview.resourcePath must be in sourceBindings")
    for object_id in object_map:
        seen: set[str] = set()
        current: str | None = object_id
        while current is not None:
            if current in seen:
                _fail("parent hierarchy contains a cycle")
            seen.add(current)
            current = object_map[current]["parentId"]

    scenes = [obj for obj in objects if obj["kind"] == "scene"]
    if not scenes:
        _fail("document must contain at least one scene object")
    if not any(any(path.startswith("scenes/") for path in scene["sourceBindings"]) for scene in scenes):
        _fail("at least one scene object must bind a scenes/*.tscn file")
    requirements = result["requirements"]
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= MAX_REQUIREMENTS:
        _fail(f"document.requirements must contain 1..{MAX_REQUIREMENTS} items")
    requirement_ids: set[str] = set()
    for i, requirement in enumerate(requirements):
        where = f"requirements[{i}]"
        if not isinstance(requirement, dict):
            _fail(f"{where} must be an object")
        _exact_keys(requirement, {"id", "text"}, {"objectIds", "verification"}, where)
        requirement["id"] = _id(requirement["id"], where + ".id")
        if requirement["id"] in requirement_ids:
            _fail(f"duplicate requirement id: {requirement['id']}")
        requirement_ids.add(requirement["id"])
        requirement["text"] = _string(requirement["text"], where + ".text", 2000)
        requirement.setdefault("objectIds", [])
        if not isinstance(requirement["objectIds"], list) or len(requirement["objectIds"]) > MAX_OBJECTS:
            _fail(f"{where}.objectIds must be a bounded list")
        requirement["objectIds"] = [_id(item, where + ".objectIds") for item in requirement["objectIds"]]
        if len(set(requirement["objectIds"])) != len(requirement["objectIds"]) or any(item not in object_map for item in requirement["objectIds"]):
            _fail(f"{where}.objectIds must uniquely reference existing objects")
        requirement.setdefault("verification", "manual")
        if requirement["verification"] not in {"manual", "automated", "human", "runtime"}:
            _fail(f"{where}.verification is unsupported")
    encoded = canonical_json(result).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        _fail("document exceeds the maximum serialized size")
    return result


def validate_document(doc: object) -> dict:
    """Validate and return a normalized deep copy of an object document."""
    return _validate_document(doc)


def _check_typed_value(field: Mapping, value: object, where: str) -> object:
    candidate = copy.deepcopy(value)
    kind = field["type"]
    if kind in {"number", "integer"}:
        candidate = _finite_number(candidate, where)
        if not field["min"] <= candidate <= field["max"] or (kind == "integer" and not float(candidate).is_integer()):
            _fail(f"{where} is outside the field's declared bounds")
        step = field.get("step")
        if step is not None and candidate != field["min"] and not _aligns_to_step(candidate, field["min"], step):
            _fail(f"{where} does not align to the field's declared step")
    elif kind == "boolean":
        if type(candidate) is not bool:
            _fail(f"{where} must be boolean")
    elif kind in {"text", "color"}:
        if not isinstance(candidate, str) or len(candidate) > 4000:
            _fail(f"{where} must be a bounded string")
        if kind == "color" and not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", candidate):
            _fail(f"{where} must be #RRGGBB or #RRGGBBAA")
    elif kind == "choice":
        if not any(type(candidate) is type(option) and candidate == option for option in field["options"]):
            _fail(f"{where} must match a declared choice")
    elif kind == "vector2":
        if not isinstance(candidate, list) or len(candidate) != 2:
            _fail(f"{where} must contain exactly two numbers")
        candidate = [_finite_number(v, where) for v in candidate]
    return candidate


def validate_change_request(request: object, current_document: object, publication_revision: object, source_commit: object) -> dict:
    """Validate an iteration against the current published object baseline."""
    document = validate_document(current_document)
    if isinstance(publication_revision, bool) or not isinstance(publication_revision, int) or publication_revision < 0:
        _fail("publication_revision must be a non-negative integer")
    source_commit = _string(source_commit, "source_commit", 200)
    if not isinstance(request, dict):
        _fail("change request must be an object")
    _exact_keys(request, {"baseRevision", "sourceCommit", "targetObjectIds", "fields", "feedback"}, {"operations"}, "changeRequest")
    base_revision = request["baseRevision"]
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision != publication_revision:
        _fail("changeRequest.baseRevision is stale")
    if request["sourceCommit"] != source_commit:
        _fail("changeRequest.sourceCommit does not match the published commit")
    by_id = {obj["id"]: obj for obj in document["objects"]}
    operations = _validate_workbench_operations_shape(request.get("operations", []), "changeRequest.operations")
    declared_draft_ids = {
        operation["sceneId"] if operation["kind"] == "new-scene" else operation["instanceId"]
        for operation in operations if operation["kind"] in {"new-scene", "new-instance"}
    }
    targets = request["targetObjectIds"]
    if not isinstance(targets, list) or len(targets) > MAX_OBJECTS:
        _fail("changeRequest.targetObjectIds must be a bounded list")
    targets = [_id(value, "changeRequest.targetObjectIds") for value in targets]
    if len(set(targets)) != len(targets) or any(value not in by_id and value not in declared_draft_ids for value in targets):
        _fail("changeRequest.targetObjectIds must uniquely reference existing objects or declared draft targets")
    changes = request["fields"]
    if not isinstance(changes, list) or len(changes) > 100:
        _fail("changeRequest.fields must contain at most 100 changes")
    normalized_changes = []
    changed_keys: set[tuple[str, str]] = set()
    for i, change in enumerate(changes):
        where = f"changeRequest.fields[{i}]"
        if not isinstance(change, dict):
            _fail(f"{where} must be an object")
        _exact_keys(change, {"objectId", "fieldId", "value"}, where=where)
        object_id = _id(change["objectId"], where + ".objectId")
        field_id = _id(change["fieldId"], where + ".fieldId")
        if object_id not in by_id or object_id not in targets:
            _fail(f"{where}.objectId must be an existing target object")
        field = next((f for f in by_id[object_id]["fields"] if f["id"] == field_id), None)
        if field is None or not field["editable"]:
            _fail(f"{where} references a missing or read-only field")
        key = (object_id, field_id)
        if key in changed_keys:
            _fail(f"duplicate field change: {object_id}.{field_id}")
        changed_keys.add(key)
        normalized_changes.append({"objectId": object_id, "fieldId": field_id, "value": _check_typed_value(field, change["value"], where + ".value")})
    feedback = request["feedback"]
    if not isinstance(feedback, list) or len(feedback) > 100:
        _fail("changeRequest.feedback must contain at most 100 items")
    normalized_feedback = []
    feedback_ids = set()
    for i, item in enumerate(feedback):
        where = f"changeRequest.feedback[{i}]"
        if not isinstance(item, dict):
            _fail(f"{where} must be an object")
        _exact_keys(item, {"objectId", "message", "category"}, {"feedbackId"}, where)
        object_id = item["objectId"]
        if object_id is not None:
            object_id = _id(object_id, where + ".objectId")
            if object_id not in by_id and object_id not in declared_draft_ids:
                _fail(f"{where}.objectId must reference a current or same-request draft target object")
            if object_id in declared_draft_ids and object_id not in targets:
                _fail(f"{where}.objectId draft target must be included in targetObjectIds")
            if object_id in by_id and targets and object_id not in targets:
                _fail(f"{where}.objectId must reference a current target object")
        feedback_id = _id(item["feedbackId"], where + ".feedbackId") if item.get("feedbackId") is not None else None
        if feedback_id is None:
            # Legacy clients did not send IDs. A fixed slot ID is stable for
            # retries of the same ordered request and lets the planner return
            # item-level decisions without making those clients upgrade first.
            suffix = i
            feedback_id = f"legacy-feedback-{suffix}"
            while feedback_id in feedback_ids:
                suffix += 1
                feedback_id = f"legacy-feedback-{suffix}"
        if feedback_id in feedback_ids:
            _fail("changeRequest.feedback contains duplicate feedbackId")
        feedback_ids.add(feedback_id)
        # Feedback is structured and object-scoped; an empty message is valid
        # (for example, the user may submit a value-only iteration).
        message = _string(item["message"], where + ".message", 4000, minimum=0)
        category = item["category"]
        if category not in FEEDBACK_CATEGORIES:
            _fail(f"{where}.category is unsupported")
        normalized_feedback.append({"feedbackId": feedback_id, "objectId": object_id, "message": message, "category": category})
    operations = _validate_workbench_operation_references(operations, document, targets, "changeRequest.operations")
    result = {"baseRevision": base_revision, "sourceCommit": source_commit, "targetObjectIds": targets, "fields": normalized_changes, "feedback": normalized_feedback}
    if "operations" in request or operations:
        result["operations"] = operations
    if len(canonical_json(result).encode("utf-8")) > MAX_REQUEST_BYTES:
        _fail("change request exceeds the maximum serialized size")
    return result


def validate_change_request_v1(request: object, current_document: object, publication_revision: object, source_commit: object) -> dict:
    """Validate the explicitly versioned request with stable feedback identities."""
    if not isinstance(request, dict): _fail("changeRequest must be an object")
    _exact_keys(request, {"schemaVersion", "baseRevision", "sourceCommit", "targetObjectIds", "fields", "feedback"}, {"operations"}, "changeRequest")
    if request["schemaVersion"] != "studio.change-request.v1": _fail("changeRequest must use studio.change-request.v1")
    legacy = {key: request[key] for key in ("baseRevision", "sourceCommit", "targetObjectIds", "fields")}
    if "operations" in request:
        legacy["operations"] = request["operations"]
    feedback = _validate_feedback(request["feedback"], "changeRequest.feedback")
    legacy["feedback"] = [{"objectId": item["objectId"], "message": item["message"], "category": item["category"]} for item in feedback]
    normalized = validate_change_request(legacy, current_document, publication_revision, source_commit)
    normalized["schemaVersion"] = "studio.change-request.v1"
    normalized["feedback"] = feedback
    return normalized


def apply_field_changes(document: object, change_request: object) -> dict:
    """Apply only validated field values and return a new object document."""
    result = validate_document(document)
    if not isinstance(change_request, dict):
        _fail("change request must be validated before applying changes")
    validator = validate_change_request_v1 if "schemaVersion" in change_request else validate_change_request
    request = validator(
        change_request, result, change_request.get("baseRevision"), change_request.get("sourceCommit")
    )
    objects = {obj["id"]: obj for obj in result["objects"]}
    for change in request["fields"]:
        if not isinstance(change, dict) or set(change) != {"objectId", "fieldId", "value"}:
            _fail("change request must be validated before applying changes")
        obj = objects.get(change["objectId"])
        field = next((f for f in obj["fields"] if f["id"] == change["fieldId"]), None) if obj else None
        if field is None or not field["editable"]:
            _fail("change request references a missing or read-only field")
        field["value"] = _check_typed_value(field, change["value"], "changeRequest.value")
    return validate_document(result)


def canonical_json(value: object) -> str:
    """Serialize protocol JSON deterministically and reject non-standard values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _strict_json(text: object, maximum: int = MAX_DOCUMENT_BYTES) -> object:
    if not isinstance(text, str) or len(text.encode("utf-8")) > maximum:
        _fail("planner response must be bounded JSON text")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        _fail(f"non-standard JSON constant: {value}")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ObjectProtocolError("planner response is not valid strict JSON") from exc


def _validate_planner_result(value: object, expected_feedback: list[dict] | None = None) -> dict:
    if not isinstance(value, dict):
        _fail("planner response must be a JSON object")
    strict_feedback = expected_feedback is not None
    base_required = {"status", "summary", "questions", "document", "tasks", "blockers"}
    _exact_keys(value, base_required | ({"schemaVersion", "feedbackDecisions"} if strict_feedback else set()),
                {"schemaVersion", "feedbackDecisions", "visualPlan"} if not strict_feedback else {"visualPlan"}, "plannerResponse")
    if strict_feedback and value["schemaVersion"] != "studio.planner-result.v1":
        _fail("planner response must use studio.planner-result.v1")
    status = value["status"]
    if status not in PLANNING_STATUSES:
        _fail("plannerResponse.status is unsupported")
    summary = _string(value["summary"], "plannerResponse.summary", 8000)
    questions = value["questions"]
    if not isinstance(questions, list) or len(questions) > 100:
        _fail("plannerResponse.questions must be a bounded list")
    normalized_questions = []
    seen_questions: set[str] = set()
    for i, question in enumerate(questions):
        where = f"plannerResponse.questions[{i}]"
        if not isinstance(question, dict):
            _fail(f"{where} must be an object")
        _exact_keys(question, {"id", "prompt", "type", "required"}, {"options"}, where)
        qid = _id(question["id"], where + ".id")
        if qid in seen_questions:
            _fail(f"duplicate question id: {qid}")
        seen_questions.add(qid)
        prompt = _string(question["prompt"], where + ".prompt", 2000)
        kind = question["type"]
        if kind not in QUESTION_TYPES or type(question["required"]) is not bool:
            _fail(f"{where} has invalid type or required flag")
        item = {"id": qid, "prompt": prompt, "type": kind, "required": question["required"]}
        if kind == "choice":
            options = question.get("options")
            if not isinstance(options, list) or not 1 <= len(options) <= 100:
                _fail(f"{where}.options is required for choice questions")
            normalized = []
            for j, option in enumerate(options):
                if isinstance(option, str):
                    option = {"value": option, "label": option}
                if not isinstance(option, dict):
                    _fail(f"{where}.options[{j}] must be a string or value/label object")
                _exact_keys(option, {"value", "label"}, where=f"{where}.options[{j}]")
                if isinstance(option["value"], (dict, list)) or option["value"] is None or isinstance(option["value"], bool):
                    _fail(f"{where}.options[{j}].value must be string or number")
                if isinstance(option["value"], float) and not math.isfinite(option["value"]):
                    _fail(f"{where}.options[{j}].value must be finite")
                normalized.append({"value": option["value"], "label": _string(option["label"], f"{where}.options[{j}].label", 200)})
            if len({(type(o["value"]).__name__, str(o["value"])) for o in normalized}) != len(normalized):
                _fail(f"{where}.options contains duplicate values")
            item["options"] = normalized
        elif "options" in question:
            _fail(f"{where}.options is only valid for choice questions")
        normalized_questions.append(item)
    tasks = value["tasks"]
    if not isinstance(tasks, list) or len(tasks) > 500:
        _fail("plannerResponse.tasks must be a bounded list")
    normalized_tasks = []
    task_ids: set[str] = set()
    for i, task in enumerate(tasks):
        where = f"plannerResponse.tasks[{i}]"
        if not isinstance(task, dict):
            _fail(f"{where} must be an object")
        _exact_keys(task, {"id", "description", "objectIds", "requirementIds"}, where=where)
        tid = _id(task["id"], where + ".id")
        if tid in task_ids:
            _fail(f"duplicate task id: {tid}")
        task_ids.add(tid)
        for key in ("objectIds", "requirementIds"):
            if not isinstance(task[key], list) or len(task[key]) > 500:
                _fail(f"{where}.{key} must be a bounded list")
            task[key] = [_id(item, f"{where}.{key}") for item in task[key]]
            if len(task[key]) != len(set(task[key])):
                _fail(f"{where}.{key} contains duplicates")
        task["description"] = _string(task["description"], where + ".description", 4000)
        normalized_tasks.append(copy.deepcopy(task))
    blockers = value["blockers"]
    if not isinstance(blockers, list) or len(blockers) > 100:
        _fail("plannerResponse.blockers must be a bounded list")
    blockers = [_string(item, f"plannerResponse.blockers[{i}]", 2000) for i, item in enumerate(blockers)]
    document = None if value["document"] is None else validate_document(value["document"])
    if status == "NEEDS_CLARIFICATION":
        if not normalized_questions:
            _fail("NEEDS_CLARIFICATION requires at least one question")
    elif status == "BLOCKED":
        if not blockers:
            _fail("BLOCKED requires at least one blocker")
    else:
        if document is None or normalized_questions or blockers or not normalized_tasks:
            _fail("READY requires a valid document and tasks, with no questions or blockers")
        object_ids = {obj["id"] for obj in document["objects"]}
        requirement_ids = {req["id"] for req in document["requirements"]}
        if any(set(task["objectIds"]) - object_ids or set(task["requirementIds"]) - requirement_ids for task in normalized_tasks):
            _fail("READY task references an unknown object or requirement")
    result = {"status": status, "summary": summary, "questions": normalized_questions, "document": document,
              "tasks": normalized_tasks, "blockers": blockers}
    if "visualPlan" in value:
        result["visualPlan"] = copy.deepcopy(value["visualPlan"])
    if strict_feedback:
        feedback = _validate_feedback(expected_feedback, "expectedFeedback")
        decisions = value["feedbackDecisions"]
        if not isinstance(decisions, list) or len(decisions) > 100: _fail("feedbackDecisions must be bounded")
        expected_by_id = {item["feedbackId"]: item for item in feedback}
        seen = set()
        normalized_decisions = []
        for i, decision in enumerate(decisions):
            where = f"feedbackDecisions[{i}]"
            if not isinstance(decision, dict): _fail(where + " must be an object")
            _exact_keys(decision, {"feedbackId", "status", "reason", "taskIds", "requirementIds"}, where=where)
            fid = _id(decision["feedbackId"], where + ".feedbackId")
            if fid not in expected_by_id or fid in seen: _fail(where + ".feedbackId must uniquely reference submitted feedback")
            seen.add(fid)
            if decision["status"] not in FEEDBACK_DECISIONS: _fail(where + ".status is unsupported")
            reason = _string(decision["reason"], where + ".reason", 2000)
            task_ids = _string_list(decision["taskIds"], where + ".taskIds", 500)
            requirement_ids = _string_list(decision["requirementIds"], where + ".requirementIds", 500)
            if decision["status"] == "needs_clarification" and status == "READY": _fail("needs_clarification feedback blocks READY")
            if decision["status"] == "adopted" and status == "READY" and not (task_ids or requirement_ids): _fail("adopted feedback must link a task or requirement")
            normalized_decisions.append({"feedbackId": fid, "status": decision["status"], "reason": reason, "taskIds": task_ids, "requirementIds": requirement_ids})
        if seen != set(expected_by_id): _fail("every submitted feedback item requires exactly one decision")
        task_ids = {item["id"] for item in normalized_tasks}
        requirement_ids = {item["id"] for item in document["requirements"]} if document else set()
        if any(set(item["taskIds"]) - task_ids or set(item["requirementIds"]) - requirement_ids for item in normalized_decisions): _fail("feedback decision references unknown task or requirement")
        result["schemaVersion"] = "studio.planner-result.v1"
        result["feedbackDecisions"] = normalized_decisions
    return result


def parse_planner_response(text: str | dict, expected_feedback: list[dict] | None = None,
                           current_document: dict | None = None,
                           previous_document: dict | None = None, *, initial_build: bool = False) -> dict:
    """Parse strict planner JSON and enforce status-specific invariants."""
    parsed = text if isinstance(text, dict) else _strict_json(text)
    # Existing source mappings are optional in a planner response. Omitting one
    # means retaining it, rather than deleting a definition that instances use.
    # Explicit replacements still pass the complete reference/role validation.
    if (current_document is not None or previous_document is not None) and isinstance(parsed, dict):
        parsed = copy.deepcopy(parsed)
        retained = {}
        # The last reviewed proposal can contain mappings that do not yet exist
        # in a published source baseline. Keep their original provenance.
        for baseline in (current_document, previous_document):
            if baseline is not None:
                retained.update({item["id"]: item["workbench"]
                                 for item in validate_document(baseline)["objects"]
                                 if item.get("workbench")})
        document = parsed.get("document")
        if isinstance(document, dict) and isinstance(document.get("objects"), list):
            for item in document["objects"]:
                if isinstance(item, dict) and "workbench" not in item and retained.get(item.get("id")):
                    item["workbench"] = copy.deepcopy(retained[item["id"]])
    result = _validate_planner_result(parsed, expected_feedback)
    if initial_build and result["status"] == "READY":
        covered = {rid for task in result["tasks"] for rid in task["requirementIds"]}
        missing = {item["id"] for item in result["document"]["requirements"]} - covered
        if missing:
            _fail("首建方案必须包含完整制作任务，以下需求尚无任务覆盖：" + ", ".join(sorted(missing)))
    return result


def planner_instructions(*, expected_feedback: bool = False, initial_build: bool = False) -> str:
    """Return the bounded instruction contract for a read-only planner session."""
    top_level_keys = ("schemaVersion, status, summary, questions, document, tasks, blockers, feedbackDecisions"
                      if expected_feedback else "status, summary, questions, document, tasks, blockers")
    instructions = (
        "You are the read-only planning stage of a general 2D game studio. Do not edit files, run commands, "
        "approve work, or claim behavior is verified. Discuss the user's concept. Do not force the concept into a genre "
        "or preset. "
        "Return exactly one strict JSON object, with no Markdown, comments, duplicate keys, or unknown keys. "
        f"The required top-level keys are {top_level_keys}; visualPlan is an optional extra key. status is one of "
        "NEEDS_CLARIFICATION, READY, BLOCKED; summary is a trimmed non-empty string (max 8000); questions is a list "
        "(max 100); document is null or a document; tasks is a list (max 500); blockers is a list of trimmed non-empty "
        "strings (max 100, each max 2000). NEEDS_CLARIFICATION requires at least one question. BLOCKED requires at least "
        "one blocker. READY requires a document, at least one task, and empty questions and blockers.\n\n"
        "Question keys are exactly id, prompt, type, required, with optional options. id is a stable lowercase ID "
        "(letters/digits followed by letters/digits/_/-; max 64); prompt is trimmed non-empty (max 2000); type is "
        "text, choice, number, or boolean; required is boolean. choice requires 1..100 options, each either a string "
        "(its value and label are that string) or exactly {value,label}; value is a finite string or number (never bool), "
        "label is trimmed non-empty (max 200), and values must be unique. Other question types must omit options.\n\n"
        "A non-null document has exactly schemaVersion, dimension, title, summary, objects, requirements. Use "
        "schemaVersion=studio.objects.v1 and dimension=2d. title is trimmed non-empty (max 160), summary is trimmed "
        "non-empty (max 8000), objects has 1..500 entries, requirements has 1..500 entries. Each object has exactly "
        "id, kind, name, sourceBindings, and may also have description, parentId, relations, fields. id and references "
        "are stable lowercase IDs (max 64); kind is project, scene, entity, mechanic, rule, interface, asset, or content; "
        "name is trimmed non-empty (max 160); description defaults to \"\" and is a string (max 4000); parentId defaults "
        "to null; relations defaults to []; fields defaults to []. Each relation has exactly type,targetId; type is "
        "trimmed non-empty (max 80). sourceBindings is a list (max 100) of unique safe paths under scripts/*.gd, "
        "scenes/*.tscn, resources/*.tres, or assets/*.{png,jpg,jpeg,webp}. Include at least one scene object bound to "
        "scenes/*.tscn. Never bind design/game.json or studio/runtime.gd; those are backend-owned. Each object may also "
        "have optional workbench metadata with exactly role, scope, provenance, preview and any of definitionId, sceneId, "
        "destinationSceneId, targetSceneId, entryId, exitId, presetId, sourceCommit, overrides, lock, position, size, positionFieldId, sizeFieldId, "
        "bounds, anchor, driver, lifecycle, trigger, positionPolicy, cleanup, condition, guard, fromState, toState, mode, facets, usage. "
        "role is definition, instance, entry, spawn, behavior, state, resource, transition, preset, system, or scene; "
        "scope is project, scene, shared, instance, or runtime. provenance is exactly {kind,sourcePaths}; kind is fact, "
        "intent, inference, proposal, or runtime, and sourcePaths are safe project-relative source/document paths. preview "
        "is {type,label,stages}, optionally speed, speedFieldId, imagePath, resourcePath, and clipName; each stage is "
        "{label,duration}, optionally durationFieldId. speedFieldId and durationFieldId must reference number or integer "
        "fields on the same object; field values take priority over static speed/duration. Missing legacy fields may use "
        "the static fallback; invalid or ambiguous drafts remain unknown. positionFieldId and sizeFieldId must reference "
        "vector2 fields on the same object (size values must be positive). Declare these bindings whenever geometry "
        "is controlled by an editable field; do not rely on field names or prose to imply the binding. An instance "
        "without its own sizeFieldId or overrides.size inherits its definitionId's explicit sizeFieldId binding; "
        "its static size is only a legacy fallback when no definition binding exists. An instance with a motion preview "
        "and no own speed/speedFieldId inherits the referenced definition's motion speed binding; absent instance stages "
        "inherit the definition's motion stages with their original field owner. Explicit instance speed (including 0) "
        "or size overrides take priority. These are browser understanding previews, never proof of engine execution. type is "
        "semantic, image, motion, action, response, "
        "interaction, rule, spawn, or transition. An image preview must use an asset already bound by sourceBindings; "
        "otherwise use a truthful semantic preview. A scene instance requires definitionId, sceneId, lock, and position. "
        "lock (including overrides.lock) is exactly fixed, nudge, or free: fixed protects the instance from changes, "
        "nudge permits bounded position changes, and free permits explicit requested edits. Do not use locked, "
        "unlocked, booleans, or any other lock value. A fixed instance can still have explicitly editable fields; "
        "lock does not grant or remove field capabilities. "
        "For an existing object, omitted workbench metadata retains its current source mapping. Supply a complete "
        "replacement only when the requested change requires it; preserve unrelated fields, relations and source bindings. "
        "When previousDocument is supplied it is the previous proposal revision, not verified source: retain its stable "
        "object IDs and still-valid mappings unless a requested change requires replacement. Keep proposal/inference "
        "provenance and never promote it to a source fact. "
        "an entry requires sceneId and position; a transition requires source sceneId and destinationSceneId (or "
        "targetSceneId), and any entry/preset references must resolve to matching objects. position/size/bounds are finite "
        "pairs; anchor is a pair from 0 to 1. Mark uncertain mappings as inference or proposal, and never invent bound "
        "images or runtime observations.\n\n"
        "Each field has exactly id,label,type,value,editable, and may have min,max,step,unit,options. id is a stable "
        "lowercase ID; label is trimmed non-empty (max 120); editable is boolean; unit, when present, is trimmed "
        "non-empty (max 40). type is number, integer, boolean, text, choice, color, or vector2. number/integer require "
        "finite min and max with min<=value<=max; integer values and bounds are integral; optional step is finite, "
        "positive and aligned from min. choice requires 1..100 unique scalar options (string or finite number, never bool), "
        "and value must exactly match one option in type and value. boolean value is boolean. text value is a string "
        "(max 4000; empty allowed). color is #RRGGBB or #RRGGBBAA. vector2 is exactly two finite numbers. unit is "
        "optional for any type. Do not add numeric constraints except min/max/step for number/integer; options only for choice.\n\n"
        "Each requirement has exactly id,text and may have objectIds,verification. id is a stable lowercase ID; text is "
        "trimmed non-empty (max 2000); objectIds defaults to [] and uniquely references existing objects; verification "
        "defaults to manual and is manual, automated, human, or runtime. Keep uncertain gameplay manual. Each task has "
        "exactly id,description,objectIds,requirementIds; IDs are unique stable lowercase IDs, description is trimmed "
        "non-empty (max 4000), and referenced object/requirement IDs must exist and be unique within each list. "
        "Each task has exactly id, description, objectIds, and requirementIds.\n\n"
        "Compliant minimal shape (replace example content while preserving exact keys): "
        "{\"status\":\"READY\",\"summary\":\"A small playable harbor prototype.\",\"questions\":[],"
        "\"document\":{\"schemaVersion\":\"studio.objects.v1\",\"dimension\":\"2d\",\"title\":\"Harbor\","
        "\"summary\":\"Explore and activate a beacon.\",\"objects\":[{\"id\":\"main-scene\",\"kind\":\"scene\","
        "\"name\":\"Main\",\"sourceBindings\":[\"scenes/main.tscn\"]}],\"requirements\":[{\"id\":\"play\","
        "\"text\":\"The player can explore the harbor.\"}]},\"tasks\":[{\"id\":\"build-scene\","
        "\"description\":\"Create the playable harbor scene.\",\"objectIds\":[\"main-scene\"],"
        "\"requirementIds\":[\"play\"]}],\"blockers\":[]}. Unknown keys at every level are forbidden."
    )
    if initial_build:
        instructions += (
            "\n\nINITIAL BUILD: there is no implemented source baseline. previousDocument is only an earlier proposal, "
            "never completed work. After any supplement or answer, READY must still describe the entire first playable "
            "game, not just the latest change. Replace outdated wording rather than restoring it. Every requirement in "
            "the resulting document must be linked by at least one implementation task. Include initial scene, controls, "
            "rules, feedback and reset where requested; preserve the full agreed scope. "
            "Model the known scene intent in workbench metadata: scene role and known bounds; reusable entity "
            "definitions and their concrete scene instances with definitionId, sceneId, lock and planned position. "
            "Use separate stable IDs for definitions and instances. Describe known lifecycle, positionPolicy, cleanup "
            "and driver (a safe planned script path); for rules/states describe known trigger, condition, guard, "
            "fromState and toState as strings. Keep an explicit relation to the relevant scene/entity/rule. "
            "These are plans: use proposal or inference provenance with planned sourcePaths, never fact/runtime. "
            "Do not invent unknown coordinates, images, lifecycle or observed behavior; leave uncertain parts unmapped "
            "or ask a focused question. No unrequested gameplay, scenes or transitions."
        )
    if expected_feedback:
        instructions += (
            "\n\nThis request uses studio.planner-result.v1. Include schemaVersion exactly as that value and include feedbackDecisions. "
            "Return exactly one decision for every supplied feedbackId, with no extras. Each decision has exactly feedbackId, status, reason, taskIds, requirementIds. "
            "status is adopted, needs_clarification, deferred, or rejected. Explain every decision. Adopted feedback in a READY result must link to at least one real task or requirement. "
            "Any needs_clarification decision prevents READY. Experience acceptance results are separate and are not inferred from these planning decisions."
            " The base minimal example above must be extended with schemaVersion=studio.planner-result.v1 and one feedbackDecisions entry per supplied feedback item."
        )
    from .visual_planning import visual_plan_instructions
    return instructions + "\nAn optional top-level visualPlan is allowed and should accompany each feedback when useful." + visual_plan_instructions()


def catalog_from_document(document: object, commit: str) -> dict:
    """Build frontend edit capabilities from a validated, committed document."""
    normalized = validate_document(document)
    commit = _string(commit, "commit", 200)
    type_map = {"number": "scalar", "integer": "scalar", "text": "text", "color": "text",
                "choice": "choice", "boolean": "boolean", "vector2": "vector2"}
    capabilities = []
    for object_index, obj in enumerate(normalized["objects"]):
        for field_index, field in enumerate(obj["fields"]):
            capability = {
                "id": obj["id"] + "." + field["id"],
                "objectId": obj["id"], "fieldId": field["id"],
                "label": field["label"], "type": type_map[field["type"]],
                "editable": field["editable"], "supported": True,
                "currentValue": copy.deepcopy(field["value"]),
                "value": copy.deepcopy(field["value"]),
                "step": field.get("step"),
                "sourcePaths": list(obj["sourceBindings"]),
                "sourcePath": "design/game.json",
                "pointer": f"/objects/{object_index}/fields/{field_index}/value",
            }
            if field["type"] in {"number", "integer"}:
                capability.update(min=field["min"], max=field["max"])
                capability["integer"] = field["type"] == "integer"
                if field.get("unit") is not None:
                    capability["unit"] = field["unit"]
            if field["type"] == "choice":
                capability["options"] = copy.deepcopy(field["options"])
            capabilities.append(capability)
    return {
        "schemaVersion": 1,
        "sourceCommit": commit,
        "documentVersion": DOCUMENT_VERSION,
        "objects": [
            {
                "id": obj["id"], "kind": obj["kind"], "name": obj["name"],
                "description": obj["description"], "parentId": obj["parentId"],
                "relations": copy.deepcopy(obj["relations"]),
                "sourceBindings": list(obj["sourceBindings"]),
                "editable": any(f["editable"] for f in obj["fields"]),
                **({"workbench": copy.deepcopy(obj["workbench"])} if "workbench" in obj else {}),
            }
            for obj in normalized["objects"]
        ],
        "capabilities": capabilities,
    }

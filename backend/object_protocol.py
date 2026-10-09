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
FEEDBACK_CATEGORIES = {"general", "bug", "visual", "behavior"}
PLANNING_STATUSES = {"NEEDS_CLARIFICATION", "READY", "BLOCKED"}
QUESTION_TYPES = {"text", "choice", "number", "boolean"}


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


def _id(value: object, where: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        _fail(f"{where} is not a valid stable ID")
    return value


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
        _exact_keys(obj, {"id", "kind", "name", "sourceBindings"}, {"description", "parentId", "relations", "fields"}, where)
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
        object_map[obj["id"]] = obj

    # Validate links after collecting IDs, then reject parent cycles.
    for obj in objects:
        if obj["parentId"] is not None and obj["parentId"] not in object_map:
            _fail(f"unknown parent object: {obj['parentId']}")
        for relation in obj["relations"]:
            if relation["targetId"] not in object_map:
                _fail(f"unknown relation target: {relation['targetId']}")
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
    _exact_keys(request, {"baseRevision", "sourceCommit", "targetObjectIds", "fields", "feedback"}, where="changeRequest")
    base_revision = request["baseRevision"]
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision != publication_revision:
        _fail("changeRequest.baseRevision is stale")
    if request["sourceCommit"] != source_commit:
        _fail("changeRequest.sourceCommit does not match the published commit")
    by_id = {obj["id"]: obj for obj in document["objects"]}
    targets = request["targetObjectIds"]
    if not isinstance(targets, list) or len(targets) > MAX_OBJECTS:
        _fail("changeRequest.targetObjectIds must be a bounded list")
    targets = [_id(value, "changeRequest.targetObjectIds") for value in targets]
    if len(set(targets)) != len(targets) or any(value not in by_id for value in targets):
        _fail("changeRequest.targetObjectIds must uniquely reference existing objects")
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
    for i, item in enumerate(feedback):
        where = f"changeRequest.feedback[{i}]"
        if not isinstance(item, dict):
            _fail(f"{where} must be an object")
        _exact_keys(item, {"objectId", "message", "category"}, where=where)
        object_id = _id(item["objectId"], where + ".objectId")
        if object_id not in by_id or (targets and object_id not in targets):
            _fail(f"{where}.objectId must reference a current target object")
        # Feedback is structured and object-scoped; an empty message is valid
        # (for example, the user may submit a value-only iteration).
        message = _string(item["message"], where + ".message", 4000, minimum=0)
        category = item["category"]
        if category not in FEEDBACK_CATEGORIES:
            _fail(f"{where}.category is unsupported")
        normalized_feedback.append({"objectId": object_id, "message": message, "category": category})
    result = {"baseRevision": base_revision, "sourceCommit": source_commit, "targetObjectIds": targets, "fields": normalized_changes, "feedback": normalized_feedback}
    if len(canonical_json(result).encode("utf-8")) > MAX_REQUEST_BYTES:
        _fail("change request exceeds the maximum serialized size")
    return result


def apply_field_changes(document: object, change_request: object) -> dict:
    """Apply only validated field values and return a new object document."""
    result = validate_document(document)
    if not isinstance(change_request, dict):
        _fail("change request must be validated before applying changes")
    request = validate_change_request(
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


def _validate_planner_result(value: object) -> dict:
    if not isinstance(value, dict):
        _fail("planner response must be a JSON object")
    _exact_keys(value, {"status", "summary", "questions", "document", "tasks", "blockers"}, where="plannerResponse")
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
    return {"status": status, "summary": summary, "questions": normalized_questions, "document": document,
            "tasks": normalized_tasks, "blockers": blockers}


def parse_planner_response(text: str) -> dict:
    """Parse strict planner JSON and enforce status-specific invariants."""
    return _validate_planner_result(_strict_json(text))


def planner_instructions() -> str:
    """Return the bounded instruction contract for a read-only planner session."""
    return (
        "You are the read-only planning stage of a general 2D game studio. Do not edit files, run commands, "
        "approve work, or claim behavior is verified. Discuss the user's concept. Do not force the concept into a genre "
        "or preset. "
        "Return exactly one strict JSON object, with no Markdown, comments, duplicate keys, or unknown keys. "
        "The top-level keys are exactly status, summary, questions, document, tasks, blockers. status is one of "
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
        "scenes/*.tscn. Never bind design/game.json or studio/runtime.gd; those are backend-owned.\n\n"
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
            }
            for obj in normalized["objects"]
        ],
        "capabilities": capabilities,
    }

"""Render the general object protocol into the real GM non-pk spec documents."""

from __future__ import annotations

import json
import re

from backend.object_protocol import validate_document


def _line(value: object, fallback: str = "Not specified") -> str:
    text = str(value if value is not None else fallback)
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|") or fallback


def _bullet(value: str) -> str:
    return "- " + value.replace("\n", " ")


def _task_ids(task: dict) -> tuple[list[str], list[str]]:
    objects = task.get("objectIds", [])
    requirements = task.get("requirementIds", [])
    return list(objects) if isinstance(objects, list) else [], list(requirements) if isinstance(requirements, list) else []


def render_spec_documents(document: dict, tasks: list, change_request: dict | None = None, revision: int = 1) -> dict[str, str]:
    """Render the object plan as normative GDD/PLAN and supporting GM documents.

    Stable mechanic names are derived from object IDs and each row retains the
    original requirement IDs. This is a presentation adapter only; it does not
    alter the object document or imply automatic approval/verification.
    """
    doc = validate_document(document)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("a READY game specification requires at least one task")
    objects = {item["id"]: item for item in doc["objects"]}
    requirements = {item["id"]: item for item in doc["requirements"]}
    mechanics: list[str] = []
    task_status: list[str] = []
    playable_rows: list[str] = []
    risk_tasks: list[str] = []
    main_build: list[str] = []
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            raise ValueError(f"tasks[{index - 1}] must be an object")
        task_id = _line(task.get("id"), f"task-{index}")
        description = _line(task.get("description"), "Implement the reviewed object behavior.")
        object_ids, requirement_ids = _task_ids(task)
        if any(item not in objects for item in object_ids) or any(item not in requirements for item in requirement_ids):
            raise ValueError(f"task {task_id} references an unknown object or requirement")
        anchor = object_ids[0] if object_ids else "project"
        mechanic_id = f"{anchor}-M{index}"
        mechanics.append(_bullet(
            f"[{mechanic_id}] {description} (task: {task_id}; object IDs: {', '.join(object_ids) or 'none'}; requirement IDs: {', '.join(requirement_ids) or 'none'})."
        ))
        task_status.append(f"| {task_id} | {description} | pending | Await independent verification and user review. |")
        risk_tasks.append(_bullet(f"Check {task_id} against the independent technical smoke and its linked requirements."))
        main_build.append(_bullet(f"Implement {task_id} within the frozen producer file scope; preserve backend-owned design/game.json and studio/runtime.gd."))
        if requirement_ids:
            for requirement_id in requirement_ids:
                req = requirements[requirement_id]
                evidence = "Runtime startup is a technical smoke only; this behavior remains pending human acceptance."
                playable_rows.append(f"| {requirement_id} | {_line(req['text'])} | {evidence} |")
        else:
            playable_rows.append(f"| {task_id} | {_line(description)} | Implementation and gameplay quality remain pending human acceptance. |")
    if not mechanics:
        mechanics.append("- [project-M1] Deliver the reviewed minimum playable unit.")
    if not playable_rows:
        playable_rows.append("| project | The reviewed minimum playable unit is usable. | Pending human acceptance. |")

    object_lines = []
    scene_lines = []
    asset_lines = []
    for obj in doc["objects"]:
        object_lines.append(_bullet(
            f"`{obj['id']}` ({obj['kind']}): {_line(obj['name'])}. {_line(obj.get('description', ''), 'No additional description.')} Sources: {', '.join(obj['sourceBindings']) or 'not bound yet'}."
        ))
        if obj["kind"] == "scene":
            scene_lines.append(_bullet(f"`{obj['id']}`: {_line(obj['name'])}; source {', '.join(obj['sourceBindings']) or 'pending'}; parent `{obj['parentId'] or 'none'}`."))
        if obj["kind"] == "asset":
            asset_lines.append(_bullet(f"`{obj['id']}`: {_line(obj['name'])}; user-provided/source-approved only; no automatic art generation."))
        for field in obj["fields"]:
            object_lines.append(_bullet(
                f"`{obj['id']}.{field['id']}` ({field['type']}): {_line(field['label'])}; current value `{json.dumps(field['value'], ensure_ascii=False)}`; editable `{str(field['editable']).lower()}`."
            ))
    if not scene_lines:
        scene_lines.append("- Scene layout is to be confirmed during planning.")
    if not asset_lines:
        asset_lines = ["- No asset production is authorized by this specification. User-supplied images remain references until separately approved and mapped."]

    requirements_list = "\n".join(
        _bullet(f"`{req['id']}`: {_line(req['text'])} (objects: {', '.join(req['objectIds']) or 'unspecified'}; requested check: {req['verification']}; verification state: pending).")
        for req in doc["requirements"]
    )
    changed = []
    if change_request is not None:
        if not isinstance(change_request, dict):
            raise ValueError("change_request must be an object")
        for field in change_request.get("fields", []):
            if isinstance(field, dict):
                changed.append(_bullet(f"Explicit field request `{field.get('objectId')}.{field.get('fieldId')}` = `{json.dumps(field.get('value'), ensure_ascii=False)}`."))
        for feedback in change_request.get("feedback", []):
            if isinstance(feedback, dict):
                changed.append(_bullet(f"Feedback for `{feedback.get('objectId')}` ({feedback.get('category')}): {_line(feedback.get('message'))}."))
    change_text = "\n".join(changed) if changed else "- No structured field changes or feedback were attached to this planning turn."
    version = f"v0.1.{revision - 1}"
    title = _line(doc["title"])
    summary = _line(doc["summary"])

    plan = f"""# Current Tag Plan

**Tag:** {version}

## Game Description
{summary} This is an open 2D Godot project described by stable object and requirement IDs, not a genre preset.

## Iteration Intent
{summary} This tag implements only the reviewed task list and preserves explicit object-to-source mappings.
{change_text}

## Tag Mechanics
{chr(10).join(mechanics)}

## Inherited Mechanics
Initial object-protocol delivery. No mechanics are inherited unless they appear in the published project baseline.

## Playable Unit
| Requirement | Observable acceptance | Evidence and acceptance boundary |
|---|---|---|
{chr(10).join(playable_rows)}

## Risk Tasks
{chr(10).join(risk_tasks)}
- Technical startup/import smoke does not establish that movement, puzzle logic, visual clarity, or overall experience is correct.
- Object source bindings and protected runtime interfaces must be checked against the committed project before a candidate is offered.

## Main Build
{chr(10).join(main_build)}
- The backend owns `design/game.json` and `studio/runtime.gd`; producer sessions must not edit either file.
- Keep code and scene changes within the frozen, adapter-approved project file scope.
- Preserve user references as references. This specification does not authorize automatic asset generation.

## Task Status
| Task | Work | Status | Notes |
|---|---|---|---|
{chr(10).join(task_status)}

## Review Notes
Technical smoke, import success, and scene launch are separate from gameplay verification and human experience acceptance. Each requirement remains pending until suitable evidence exists; generated plans and producer summaries are not evidence.

## Platform Commitments
| Platform | Status | Profile | Evidence | Manual check |
|---|---|---|---|---|
| Desktop | required | general-2d-desktop | Independent Godot project structure/import/start smoke for the frozen project. | User exercises every listed behavior and reviews readability, controls, and overall experience. |

## Component Coverage
{chr(10).join(object_lines)}
"""
    gdd = f"""# Game Design Document — {title}

## Concept
{summary}

## Object Model
{chr(10).join(object_lines)}

## Requirements
{requirements_list}

## Scope and Evidence
The object document is the structured source of intent. Planning questions must be resolved before implementation. Technical smoke cannot claim unobserved game behavior; human acceptance remains a separate user decision.

## Current Iteration Input
{change_text}
"""
    structure = "# Project Structure\n\n" + "\n".join(object_lines) + "\n\nBackend-owned protocol files: `design/game.json` and `studio/runtime.gd`. Producer-owned paths remain subject to the frozen scope audit.\n"
    scenes = "# Scene Plan\n\n" + "\n".join(scene_lines) + "\n\nScene behavior is described by linked requirements; scene startup alone does not verify behavior.\n"
    design = f"# Design Notes\n\n{summary}\n\n## Object Relationships\n" + "\n".join(
        _bullet(f"`{obj['id']}` parent `{obj['parentId'] or 'none'}`; relations: " + (", ".join(f"{rel['type']} → {rel['targetId']}" for rel in obj["relations"]) or "none"))
        for obj in doc["objects"]
    ) + "\n\n## Field and Feedback Changes\n" + change_text + "\n"
    assets = "# Asset Plan\n\n" + "\n".join(asset_lines) + "\n\n- User-supplied references are not imported as finished assets automatically.\n- Any future asset production requires explicit user authorization and provenance.\n"
    return {
        "SPEC.md": f"# Reviewed Game Specification\n\n{summary}\n\n- Object protocol: `studio.objects.v1`\n- Dimension: 2D\n- Tag: `{version}`\n- Normative plan: `PLAN.md`\n",
        "GDD.md": gdd,
        "PLAN.md": plan,
        "STRUCTURE.md": structure,
        "SCENES.md": scenes,
        "DESIGN.md": design,
        "ASSETS.md": assets,
    }

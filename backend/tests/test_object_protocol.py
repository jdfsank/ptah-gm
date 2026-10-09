"""Pure protocol regressions for the general Studio object contract."""

from __future__ import annotations

import copy
import json
import unittest

from backend.object_protocol import (
    ObjectProtocolError,
    apply_field_changes,
    catalog_from_document,
    parse_planner_response,
    planner_instructions,
    validate_change_request,
    validate_document,
)


def sample_document():
    return {
        "schemaVersion": "studio.objects.v1",
        "dimension": "2d",
        "title": "Moon Harbor",
        "summary": "Explore a small harbor and solve a light puzzle.",
        "objects": [
            {
                "id": "main-scene",
                "kind": "scene",
                "name": "Main scene",
                "sourceBindings": ["scenes/main.tscn"],
                "fields": [],
            },
            {
                "id": "player",
                "kind": "entity",
                "name": "Player",
                "description": "Moves through the harbor.",
                "parentId": "main-scene",
                "relations": [{"type": "appears_in", "targetId": "main-scene"}],
                "sourceBindings": ["scripts/player.gd"],
                "fields": [
                    {"id": "speed", "label": "Move speed", "type": "number", "value": 180, "min": 0, "max": 500, "step": 5, "unit": "px/s", "editable": True},
                    {"id": "visible", "label": "Visible", "type": "boolean", "value": True, "editable": True},
                    {"id": "mood", "label": "Mood", "type": "choice", "value": "calm", "options": ["calm", "alert"], "editable": False},
                    {"id": "tint", "label": "Tint", "type": "color", "value": "#aabbcc", "editable": True},
                    {"id": "spawn", "label": "Spawn", "type": "vector2", "value": [8, 16], "editable": True},
                    {"id": "caption", "label": "Caption", "type": "text", "value": "Look around", "editable": True},
                ],
            },
        ],
        "requirements": [
            {"id": "explore", "text": "The player can move around the harbor.", "objectIds": ["player"], "verification": "runtime"}
        ],
    }


def ready_result():
    document = sample_document()
    return {
        "status": "READY",
        "summary": "A small exploration prototype with one light puzzle.",
        "questions": [],
        "document": document,
        "tasks": [{"id": "scene-and-player", "description": "Build the scene and player movement.", "objectIds": ["main-scene", "player"], "requirementIds": ["explore"]}],
        "blockers": [],
    }


class ObjectProtocolTests(unittest.TestCase):
    def test_document_is_normalized_as_deep_copy_with_defaults(self):
        original = sample_document()
        del original["objects"][0]["fields"]
        original["objects"][0].pop("description", None)
        original["objects"][0].pop("relations", None)
        normalized = validate_document(original)
        self.assertIsNot(normalized, original)
        self.assertEqual(normalized["objects"][0]["fields"], [])
        self.assertEqual(normalized["objects"][0]["relations"], [])
        self.assertEqual(normalized["objects"][0]["description"], "")
        self.assertNotIn("fields", original["objects"][0])

    def test_document_rejects_unknown_keys_duplicate_ids_and_bad_references(self):
        doc = sample_document()
        doc["unexpected"] = True
        with self.assertRaises(ObjectProtocolError):
            validate_document(doc)
        doc = sample_document()
        doc["objects"].append(copy.deepcopy(doc["objects"][1]))
        with self.assertRaises(ObjectProtocolError):
            validate_document(doc)
        doc = sample_document()
        doc["objects"][1]["parentId"] = "missing"
        with self.assertRaises(ObjectProtocolError):
            validate_document(doc)

    def test_document_rejects_parent_cycles_and_unsafe_source_paths(self):
        doc = sample_document()
        doc["objects"][0]["parentId"] = "player"
        with self.assertRaisesRegex(ObjectProtocolError, "cycle"):
            validate_document(doc)
        for unsafe in ("../scripts/player.gd", "/scripts/player.gd", "scripts/.hidden.gd", "assets/link/../../x.png", "studio/runtime.gd", "scripts/player.cs", "assets/entry.gd", "assets/picture.svg", "resources/value.res"):
            doc = sample_document()
            doc["objects"][1]["sourceBindings"] = [unsafe]
            with self.subTest(path=unsafe), self.assertRaises(ObjectProtocolError):
                validate_document(doc)

    def test_document_requires_scene_requirement_and_typed_bounds(self):
        doc = sample_document()
        doc["objects"][0]["kind"] = "entity"
        with self.assertRaises(ObjectProtocolError):
            validate_document(doc)
        doc = sample_document()
        doc["requirements"] = []
        with self.assertRaises(ObjectProtocolError):
            validate_document(doc)
        for value in (True, float("inf"), 501):
            doc = sample_document()
            doc["objects"][1]["fields"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ObjectProtocolError):
                validate_document(doc)
        doc = sample_document()
        doc["objects"][1]["fields"][0]["value"] = 183
        with self.assertRaisesRegex(ObjectProtocolError, "step"):
            validate_document(doc)

    def test_change_request_carries_only_explicit_valid_changes_and_feedback(self):
        doc = sample_document()
        request = {
            "baseRevision": 4,
            "sourceCommit": "git-commit-123",
            "targetObjectIds": ["player"],
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 225}],
            "feedback": [{"objectId": "player", "message": "Movement feels too slow.", "category": "behavior"}],
        }
        normalized = validate_change_request(request, doc, 4, "git-commit-123")
        self.assertEqual(normalized["fields"], request["fields"])
        self.assertEqual(normalized["feedback"], request["feedback"])
        self.assertEqual(doc["objects"][1]["fields"][0]["value"], 180)
        empty = {"baseRevision": 4, "sourceCommit": "git-commit-123", "targetObjectIds": [], "fields": [], "feedback": []}
        self.assertEqual(validate_change_request(empty, doc, 4, "git-commit-123")["fields"], [])

    def test_change_request_rejects_stale_unknown_readonly_duplicate_and_invalid_values(self):
        base = {"baseRevision": 4, "sourceCommit": "git-commit-123", "targetObjectIds": ["player"], "fields": [], "feedback": []}
        doc = sample_document()
        with self.assertRaises(ObjectProtocolError):
            validate_change_request({**base, "baseRevision": 3}, doc, 4, "git-commit-123")
        with self.assertRaises(ObjectProtocolError):
            validate_change_request({**base, "sourceCommit": "other"}, doc, 4, "git-commit-123")
        for fields in (
            [{"objectId": "player", "fieldId": "mood", "value": "calm"}],
            [{"objectId": "player", "fieldId": "speed", "value": 900}],
            [{"objectId": "player", "fieldId": "speed", "value": 223}],
            [{"objectId": "player", "fieldId": "visible", "value": 1}],
            [{"objectId": "player", "fieldId": "speed", "value": 200}, {"objectId": "player", "fieldId": "speed", "value": 210}],
            [{"objectId": "player", "fieldId": "missing", "value": 1}],
        ):
            with self.subTest(fields=fields), self.assertRaises(ObjectProtocolError):
                validate_change_request({**base, "fields": fields}, doc, 4, "git-commit-123")

    def test_apply_field_changes_returns_copy_and_preserves_unspecified_values(self):
        doc = sample_document()
        request = {"baseRevision": 1, "sourceCommit": "c1", "targetObjectIds": ["player"],
                   "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}], "feedback": []}
        changed = apply_field_changes(doc, request)
        self.assertIsNot(changed, doc)
        fields = {field["id"]: field["value"] for field in changed["objects"][1]["fields"]}
        self.assertEqual(fields["speed"], 240)
        self.assertEqual(fields["caption"], "Look around")
        self.assertEqual(doc["objects"][1]["fields"][0]["value"], 180)

    def test_planner_response_enforces_status_contract_and_accepts_need_clarification(self):
        ready = ready_result()
        parsed = parse_planner_response(json.dumps(ready))
        self.assertEqual(parsed["status"], "READY")
        needs = {"status": "NEEDS_CLARIFICATION", "summary": "Which camera view?", "questions": [
            {"id": "camera", "prompt": "Choose a camera view.", "type": "choice", "required": True,
             "options": [{"value": "top_down", "label": "Top down"}, {"value": "side", "label": "Side view"}]}
        ], "document": None, "tasks": [], "blockers": []}
        self.assertEqual(parse_planner_response(json.dumps(needs))["document"], None)

    def test_planner_response_rejects_duplicate_json_keys_invalid_task_refs_and_incomplete_ready(self):
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response('{"status":"BLOCKED","status":"READY"}')
        ready = ready_result()
        ready["tasks"][0]["objectIds"] = ["unknown"]
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(json.dumps(ready))
        ready = ready_result()
        ready["questions"] = [{"id": "q", "prompt": "Question?", "type": "text", "required": True}]
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(json.dumps(ready))
        blocked = {"status": "BLOCKED", "summary": "Cannot proceed.", "questions": [], "document": None, "tasks": [], "blockers": []}
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(json.dumps(blocked))

    def test_catalog_exposes_stable_typed_field_capabilities(self):
        catalog = catalog_from_document(sample_document(), "commit-abc")
        speed = next(cap for cap in catalog["capabilities"] if cap["id"] == "player.speed")
        self.assertEqual(speed["type"], "scalar")
        self.assertEqual(speed["objectId"], "player")
        self.assertEqual(speed["fieldId"], "speed")
        self.assertEqual(speed["value"], 180)
        self.assertEqual(speed["currentValue"], 180)
        self.assertEqual(speed["min"], 0)
        self.assertEqual(speed["max"], 500)
        self.assertEqual(speed["step"], 5)
        self.assertEqual(speed["unit"], "px/s")
        self.assertEqual(speed["sourcePath"], "design/game.json")
        self.assertEqual(speed["sourcePaths"], ["scripts/player.gd"])
        self.assertEqual(speed["pointer"], "/objects/1/fields/0/value")
        player = next(obj for obj in catalog["objects"] if obj["id"] == "player")
        self.assertEqual(player["description"], "Moves through the harbor.")
        self.assertEqual(player["parentId"], "main-scene")
        self.assertEqual(player["sourceBindings"], ["scripts/player.gd"])

    def test_planner_instruction_keeps_planning_readonly_and_genre_open(self):
        instructions = planner_instructions()
        self.assertIn("read-only planning", instructions)
        self.assertIn("Do not force the concept into a genre", instructions)
        self.assertIn("Each task has exactly id, description, objectIds, and requirementIds", instructions)
        self.assertIn("design/game.json", instructions)
        self.assertIn("studio/runtime.gd", instructions)


if __name__ == "__main__":
    unittest.main()

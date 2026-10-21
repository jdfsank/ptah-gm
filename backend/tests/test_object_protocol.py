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
    validate_change_request_v1,
    validate_command,
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


def workbench_document():
    document = sample_document()
    scene = document["objects"][0]
    player = document["objects"][1]
    scene["workbench"] = {"role": "scene", "scope": "scene",
        "provenance": {"kind": "fact", "sourcePaths": ["scenes/main.tscn"]},
        "preview": {"type": "semantic", "label": "Harbor scene", "stages": []}, "bounds": [200, 160]}
    player["workbench"] = {"role": "definition", "scope": "shared",
        "provenance": {"kind": "fact", "sourcePaths": ["scripts/player.gd"]},
        "preview": {"type": "motion", "label": "Player movement", "stages": []}}
    document["objects"].extend([
        {"id": "player-instance", "kind": "entity", "name": "Player instance", "sourceBindings": ["scenes/main.tscn"],
         "parentId": "main-scene", "relations": [{"type": "uses_definition", "targetId": "player"}], "fields": [],
         "workbench": {"role": "instance", "scope": "instance", "definitionId": "player", "sceneId": "main-scene",
             "lock": "free", "position": [30, 40], "bounds": [200, 160], "size": [20, 20], "anchor": [0.5, 0.5],
             "provenance": {"kind": "fact", "sourcePaths": ["scenes/main.tscn"]},
             "preview": {"type": "semantic", "label": "Player placement", "stages": []}}},
        {"id": "harbor-entry", "kind": "rule", "name": "Harbor entry", "sourceBindings": ["scripts/player.gd"], "fields": [],
         "workbench": {"role": "entry", "scope": "scene", "sceneId": "main-scene", "position": [10, 10],
             "provenance": {"kind": "fact", "sourcePaths": ["scripts/player.gd"]},
             "preview": {"type": "semantic", "label": "Entry marker", "stages": []}}},
        {"id": "harbor-transition", "kind": "rule", "name": "To harbor", "sourceBindings": ["scripts/player.gd"], "fields": [],
         "workbench": {"role": "transition", "scope": "scene", "sceneId": "main-scene", "targetSceneId": "main-scene",
             "entryId": "harbor-entry", "provenance": {"kind": "intent", "sourcePaths": ["GDD.md"]},
             "preview": {"type": "transition", "label": "Scene link", "stages": []}}},
        {"id": "fade-preset", "kind": "asset", "name": "Fade", "sourceBindings": ["resources/fade.tres"], "fields": [],
         "workbench": {"role": "preset", "scope": "shared", "provenance": {"kind": "fact", "sourcePaths": ["resources/fade.tres"]},
             "preview": {"type": "transition", "label": "Fade preset", "stages": []}}},
    ])
    return document


class ObjectProtocolTests(unittest.TestCase):
    def test_explicit_lock_request_preserves_baseline_and_movement_constraints(self):
        doc = workbench_document()
        instance = next(obj for obj in doc["objects"] if obj["id"] == "player-instance")
        instance["workbench"]["lock"] = "fixed"
        base = {"baseRevision": 4, "sourceCommit": "git-version", "targetObjectIds": ["player-instance"], "fields": [], "feedback": []}
        unlock = {"operationId": "unlock", "kind": "set-lock", "objectId": "player-instance", "before": "fixed", "lock": "free"}
        move = {"operationId": "move", "kind": "move", "objectId": "player-instance", "before": [30, 40], "requested": [40, 50], "lock": "free"}
        normalized = validate_change_request({**base, "operations": [unlock, move]}, doc, 4, "git-version")
        self.assertEqual(normalized["operations"][0]["lock"], "free")
        with self.assertRaisesRegex(ObjectProtocolError, "cannot move"):
            validate_change_request({**base, "operations": [move]}, doc, 4, "git-version")
        with self.assertRaisesRegex(ObjectProtocolError, "published instance lock"):
            validate_change_request({**base, "operations": [{**unlock, "before": "nudge"}]}, doc, 4, "git-version")
        with self.assertRaisesRegex(ObjectProtocolError, "conflicting lock"):
            validate_change_request({**base, "operations": [unlock, {**unlock, "operationId": "duplicate"}]}, doc, 4, "git-version")
        with self.assertRaisesRegex(ObjectProtocolError, "cannot move"):
            validate_change_request({**base, "operations": [{**unlock, "lock": "fixed"}, move]}, doc, 4, "git-version")

    def test_transition_operation_rejects_environment_preset(self):
        doc = workbench_document()
        environment = copy.deepcopy(next(obj for obj in doc["objects"] if obj["id"] == "fade-preset"))
        environment["id"] = "environment-day"
        environment["workbench"]["preview"]["type"] = "semantic"
        doc["objects"].append(environment)
        request = {"baseRevision": 4, "sourceCommit": "git-commit-123",
                   "targetObjectIds": ["harbor-transition"], "fields": [], "feedback": [],
                   "operations": [{"operationId": "edit-forward", "kind": "transition",
                                   "objectId": "harbor-transition", "sceneId": "main-scene",
                                   "entryId": "harbor-entry", "mode": "preset", "presetId": "fade-preset"}]}
        result = validate_change_request(request, doc, 4, "git-commit-123")
        self.assertEqual(result["operations"][0]["presetId"], "fade-preset")
        request["operations"][0]["presetId"] = "environment-day"
        with self.assertRaisesRegex(ObjectProtocolError, "declared transition preset"):
            validate_change_request(request, doc, 4, "git-commit-123")

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

    def test_preview_resource_reference_is_source_bound_and_clip_requires_tres(self):
        doc = workbench_document()
        player = next(obj for obj in doc["objects"] if obj["id"] == "player")
        resource = "resources/player_frames.tres"
        player["sourceBindings"].append(resource)
        player["workbench"]["preview"].update(type="image", resourcePath=resource)
        self.assertEqual(validate_document(doc)["objects"][1]["workbench"]["preview"]["resourcePath"], resource)

        missing_image_source = copy.deepcopy(doc)
        next(obj for obj in missing_image_source["objects"] if obj["id"] == "player")["workbench"]["preview"].pop("resourcePath")
        with self.assertRaisesRegex(ObjectProtocolError, "image preview must use a bound source asset"):
            validate_document(missing_image_source)

        player["workbench"]["preview"]["clipName"] = "run"
        self.assertEqual(validate_document(doc)["objects"][1]["workbench"]["preview"]["resourcePath"], resource)

        unbound = copy.deepcopy(doc)
        next(obj for obj in unbound["objects"] if obj["id"] == "player")["sourceBindings"].remove(resource)
        with self.assertRaisesRegex(ObjectProtocolError, "resourcePath must be in sourceBindings"):
            validate_document(unbound)
        wrong_extension = copy.deepcopy(doc)
        player_copy = next(obj for obj in wrong_extension["objects"] if obj["id"] == "player")
        player_copy["workbench"]["preview"]["resourcePath"] = "assets/player.png"
        player_copy["sourceBindings"].append("assets/player.png")
        with self.assertRaisesRegex(ObjectProtocolError, "must reference a .tres"):
            validate_document(wrong_extension)
        missing_resource = copy.deepcopy(doc)
        preview = next(obj for obj in missing_resource["objects"] if obj["id"] == "player")["workbench"]["preview"]
        preview.pop("resourcePath")
        with self.assertRaisesRegex(ObjectProtocolError, "clipName requires resourcePath"):
            validate_document(missing_resource)

    def test_geometry_bindings_resolve_only_to_same_object_vectors(self):
        doc = workbench_document()
        player = next(obj for obj in doc["objects"] if obj["id"] == "player")
        player["workbench"].update(positionFieldId="spawn", sizeFieldId="spawn")
        normalized = validate_document(doc)
        self.assertEqual(next(obj for obj in normalized["objects"] if obj["id"] == "player")["workbench"]["sizeFieldId"], "spawn")
        for key in ("positionFieldId", "sizeFieldId"):
            for invalid in ("missing", "speed"):
                broken = copy.deepcopy(doc)
                next(obj for obj in broken["objects"] if obj["id"] == "player")["workbench"][key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaisesRegex(ObjectProtocolError, "vector2 field on the same object"):
                    validate_document(broken)
        next(field for field in player["fields"] if field["id"] == "spawn")["value"] = [0, -1]
        with self.assertRaisesRegex(ObjectProtocolError, "values must be positive"):
            validate_document(doc)
        del player["workbench"]["sizeFieldId"]
        validate_document(doc)

    def test_preview_numeric_bindings_must_resolve_to_same_object_number_fields(self):
        doc = workbench_document()
        player = next(obj for obj in doc["objects"] if obj["id"] == "player")
        player["workbench"]["preview"].update(speed=180, speedFieldId="speed")
        player["workbench"]["preview"]["stages"] = [
            {"label": "Move", "duration": 1.5, "durationFieldId": "speed"},
        ]
        normalized = validate_document(doc)
        preview = next(obj for obj in normalized["objects"] if obj["id"] == "player")["workbench"]["preview"]
        self.assertEqual(preview["speedFieldId"], "speed")
        self.assertEqual(preview["stages"][0]["durationFieldId"], "speed")

        missing_field = copy.deepcopy(doc)
        next(obj for obj in missing_field["objects"] if obj["id"] == "player")["workbench"]["preview"]["speedFieldId"] = "missing"
        with self.assertRaisesRegex(ObjectProtocolError, "speedFieldId must reference a numeric field on the same object"):
            validate_document(missing_field)

        non_numeric_speed = copy.deepcopy(doc)
        next(obj for obj in non_numeric_speed["objects"] if obj["id"] == "player")["workbench"]["preview"]["speedFieldId"] = "visible"
        with self.assertRaisesRegex(ObjectProtocolError, "speedFieldId must reference a numeric field on the same object"):
            validate_document(non_numeric_speed)

        other_object_field = copy.deepcopy(doc)
        next(obj for obj in other_object_field["objects"] if obj["id"] == "main-scene")["fields"] = [
            {"id": "scene-speed", "label": "Scene speed", "type": "number", "value": 2,
             "min": 0, "max": 10, "editable": True},
        ]
        next(obj for obj in other_object_field["objects"] if obj["id"] == "player")["workbench"]["preview"]["speedFieldId"] = "scene-speed"
        with self.assertRaisesRegex(ObjectProtocolError, "speedFieldId must reference a numeric field on the same object"):
            validate_document(other_object_field)

        non_numeric_stage = copy.deepcopy(doc)
        next(obj for obj in non_numeric_stage["objects"] if obj["id"] == "player")["workbench"]["preview"]["stages"][0]["durationFieldId"] = "caption"
        with self.assertRaisesRegex(ObjectProtocolError, "durationFieldId must reference a numeric field on the same object"):
            validate_document(non_numeric_stage)

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
        self.assertEqual(normalized["feedback"], [{**request["feedback"][0], "feedbackId": "legacy-feedback-0"}])
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

    def test_versioned_feedback_requires_stable_ids(self):
        doc = sample_document()
        request = {"schemaVersion":"studio.change-request.v1", "baseRevision":4, "sourceCommit":"git-commit-123",
                   "targetObjectIds":["player"], "fields":[], "feedback":[
                       {"feedbackId":"feedback-1","objectId":"player","message":"Too slow","category":"behavior"}]}
        self.assertEqual(validate_change_request_v1(request, doc, 4, "git-commit-123")["feedback"][0]["feedbackId"], "feedback-1")
        with self.assertRaises(ObjectProtocolError):
            validate_change_request_v1({**request, "feedback":[{"objectId":"player","message":"Too slow","category":"behavior"}]}, doc, 4, "git-commit-123")

    def test_legacy_feedback_keeps_compatibility_and_gains_stable_project_level_ids(self):
        request = {"baseRevision": 4, "sourceCommit": "git-commit-123", "targetObjectIds": [], "fields": [],
                   "feedback": [{"objectId": None, "message": "Add a pause menu", "category": "general"}]}
        first = validate_change_request(request, sample_document(), 4, "git-commit-123")
        retry = validate_change_request(request, sample_document(), 4, "git-commit-123")
        self.assertEqual(first["feedback"][0]["objectId"], None)
        self.assertEqual(first["feedback"][0]["feedbackId"], "legacy-feedback-0")
        self.assertEqual(first["feedback"], retry["feedback"])

    def test_v1_project_level_feedback_and_operations_validate_against_workbench(self):
        doc = workbench_document()
        request = {"schemaVersion": "studio.change-request.v1", "baseRevision": 4, "sourceCommit": "git-commit-123",
                   "targetObjectIds": ["player-instance"], "fields": [],
                   "feedback": [{"feedbackId": "project-note", "objectId": None, "message": "Add a pause menu", "category": "general"}],
                   "operations": [{"operationId": "move-start", "kind": "move", "objectId": "player-instance",
                                   "before": [30, 40], "requested": [50, 60], "scope": "当前实例", "lock": "free"}]}
        normalized = validate_change_request_v1(request, doc, 4, "git-commit-123")
        self.assertEqual(normalized["feedback"][0]["objectId"], None)
        self.assertEqual(normalized["operations"][0]["requested"], [50, 60])

    def test_structural_operations_reject_locked_out_of_bounds_and_bad_references(self):
        doc = workbench_document()
        base = {"baseRevision": 4, "sourceCommit": "git-commit-123", "targetObjectIds": ["player-instance"],
                "fields": [], "feedback": []}
        cases = [
            {"operationId": "fixed-move", "kind": "move", "objectId": "player-instance", "requested": [40, 50], "lock": "fixed"},
            {"operationId": "outside", "kind": "move", "objectId": "player-instance", "requested": [200, 40], "lock": "free"},
            {"operationId": "wrong-def", "kind": "new-instance", "instanceId": "extra-player", "name": "Extra player", "definitionId": "main-scene", "sceneId": "main-scene", "requestedPosition": [50, 60]},
            {"operationId": "unknown-scene", "kind": "new-instance", "instanceId": "extra-player", "name": "Extra player", "definitionId": "player", "sceneId": "missing-scene", "requestedPosition": [50, 60]},
            {"operationId": "missing-position", "kind": "new-instance", "instanceId": "extra-player", "name": "Extra player", "definitionId": "player", "sceneId": "main-scene"},
            {"operationId": "bad-entry", "kind": "transition", "sceneId": "main-scene", "entryId": "player", "condition": "key"},
            {"operationId": "missing-preset", "kind": "transition", "sceneId": "main-scene", "mode": "共享预设"},
        ]
        for operation in cases:
            request = {**base, "operations": [operation]}
            with self.subTest(operation=operation), self.assertRaises(ObjectProtocolError):
                validate_change_request(request, doc, 4, "git-commit-123")
        fixed_doc = workbench_document()
        next(obj for obj in fixed_doc["objects"] if obj["id"] == "player-instance")["workbench"]["lock"] = "fixed"
        with self.assertRaisesRegex(ObjectProtocolError, "cannot delete a fixed instance"):
            validate_change_request({**base, "operations": [{"operationId": "fixed-delete", "kind": "delete-instance",
                "objectId": "player-instance"}]}, fixed_doc, 4, "git-commit-123")

    def test_draft_scene_instance_ids_geometry_and_same_request_feedback(self):
        doc = workbench_document()
        request = {"baseRevision": 4, "sourceCommit": "git-commit-123",
            "targetObjectIds": ["draft-room", "draft-player"], "fields": [],
            "feedback": [{"feedbackId": "draft-note", "objectId": "draft-player",
                "message": "Put the player near the entrance.", "category": "behavior"}],
            "operations": [
                {"operationId": "new-room-op", "kind": "new-scene", "sceneId": "draft-room",
                    "name": "Bonus room", "template": "blank", "bounds": [200, 160],
                    "connections": "Keep this room independent.", "scope": "standalone room"},
                {"operationId": "new-player-op", "kind": "new-instance", "instanceId": "draft-player",
                    "name": "Bonus player", "definitionId": "player", "sceneId": "draft-room",
                    "requestedPosition": [50, 60], "size": [20, 20], "anchor": [0.5, 0.5]},
            ]}
        normalized = validate_change_request(request, doc, 4, "git-commit-123")
        self.assertEqual(normalized["operations"][0]["sceneId"], "draft-room")
        self.assertEqual(normalized["operations"][0]["bounds"], [200, 160])
        self.assertEqual(normalized["operations"][0]["connections"], "Keep this room independent.")
        self.assertEqual(normalized["operations"][0]["scope"], "standalone room")
        self.assertEqual(normalized["operations"][1]["requestedPosition"], [50, 60])
        self.assertEqual(normalized["operations"][1]["lock"], "free", "an omitted new-instance lock defaults to free")
        self.assertEqual(normalized["feedback"][0]["objectId"], "draft-player")

        invalid = copy.deepcopy(request)
        invalid["operations"][1]["sceneId"] = "missing-scene"
        with self.assertRaisesRegex(ObjectProtocolError, "same-request new scene"):
            validate_change_request(invalid, doc, 4, "git-commit-123")
        invalid = copy.deepcopy(request)
        invalid["targetObjectIds"].remove("draft-player")
        with self.assertRaisesRegex(ObjectProtocolError, "included in targetObjectIds"):
            validate_change_request(invalid, doc, 4, "git-commit-123")
        invalid = copy.deepcopy(request)
        invalid["operations"][0]["sceneId"] = "main-scene"
        invalid["targetObjectIds"] = ["main-scene", "draft-player"]
        with self.assertRaisesRegex(ObjectProtocolError, "collides"):
            validate_change_request(invalid, doc, 4, "git-commit-123")

    def test_nudge_move_is_allowed_but_keeps_lock_and_instance_identity(self):
        doc = workbench_document()
        instance = next(obj for obj in doc["objects"] if obj["id"] == "player-instance")
        instance["workbench"]["lock"] = "nudge"
        base = {"baseRevision": 4, "sourceCommit": "git-commit-123", "targetObjectIds": ["player-instance"],
            "fields": [], "feedback": [], "operations": [{"operationId": "nudge-player", "kind": "move",
                "objectId": "player-instance", "before": [30, 40], "requested": [31, 40], "lock": "nudge"}]}
        self.assertEqual(validate_change_request(base, doc, 4, "git-commit-123")["operations"][0]["requested"], [31, 40])

    def test_iteration_command_accepts_typed_workbench_operations(self):
        command = {"schemaVersion": "studio.message.v1", "kind": "command", "type": "iteration.submit",
                   "storeId": "store-1", "projectId": "project-1", "commandId": "cmd-op",
                   "expected": {"preferencesRevision": 1, "publicationRevision": 4, "sourceCommit": "git-commit-123"},
                   "payload": {"text": "", "assetRefs": [], "targetObjectIds": ["player-instance"], "fields": [],
                               "feedback": [], "operations": [{"operationId": "move-start", "kind": "move",
                                   "objectId": "player-instance", "requested": [50, 60], "lock": "free"}]}}
        self.assertEqual(validate_command(command)["payload"]["operations"][0]["kind"], "move")
        invalid = copy.deepcopy(command)
        invalid["payload"]["operations"][0]["kind"] = "teleport"
        with self.assertRaises(ObjectProtocolError):
            validate_command(invalid)

    def test_command_envelope_is_closed_and_binds_project_scope(self):
        command = {"schemaVersion":"studio.message.v1","kind":"command","type":"iteration.submit","storeId":"store-1",
                   "projectId":"project-1","commandId":"cmd-1","expected":{"preferencesRevision":2,"publicationRevision":4,"sourceCommit":"git-c1"},
                   "payload":{"text":"Adjust speed","assetRefs":[],"targetObjectIds":["player"],"fields":[],
                              "feedback":[{"feedbackId":"feedback-1","objectId":"player","message":"Too slow","category":"behavior"}]}}
        self.assertEqual(validate_command(command)["payload"]["feedback"][0]["feedbackId"], "feedback-1")
        with self.assertRaises(ObjectProtocolError):
            validate_command({**command, "payload":{**command["payload"], "cwd":"/tmp"}})
        with self.assertRaises(ObjectProtocolError):
            validate_command({**command, "expected":{"preferencesRevision":2}})

    def test_command_rejects_soft_budget_zero_and_preview_ambiguous_owner(self):
        pref = {"schemaVersion":"studio.message.v1","kind":"command","type":"session.preferences.update","storeId":"s","projectId":"p","commandId":"c","expected":{"preferencesRevision":0},"payload":{"role":"planner","modelKey":"m","effort":"low","limits":{"maxDurationSeconds":60,"softTotalTokens":0}}}
        with self.assertRaises(ObjectProtocolError): validate_command(pref)
        preview = {"schemaVersion":"studio.message.v1","kind":"command","type":"preview.start","storeId":"s","projectId":"p","commandId":"c","payload":{"candidateId":"c1","snapshotId":"s1"}}
        with self.assertRaises(ObjectProtocolError): validate_command(preview)

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

    def test_planner_feedback_decisions_cover_every_id_and_block_ready_on_clarification(self):
        ready = ready_result()
        ready.update({"schemaVersion":"studio.planner-result.v1", "feedbackDecisions":[{"feedbackId":"f1","status":"adopted","reason":"Added movement task","taskIds":["scene-and-player"],"requirementIds":["explore"]}]})
        feedback = [{"feedbackId":"f1","objectId":"player","message":"Slow","category":"behavior"}]
        self.assertEqual(parse_planner_response(json.dumps(ready), expected_feedback=feedback)["feedbackDecisions"][0]["status"], "adopted")
        incomplete = {**ready, "feedbackDecisions":[]}
        with self.assertRaises(ObjectProtocolError): parse_planner_response(json.dumps(incomplete), expected_feedback=feedback)
        blocked = {**ready, "feedbackDecisions":[{"feedbackId":"f1","status":"needs_clarification","reason":"Need speed target","taskIds":[],"requirementIds":[]}]}
        with self.assertRaises(ObjectProtocolError): parse_planner_response(json.dumps(blocked), expected_feedback=feedback)

    def test_iteration_retains_omitted_source_mapping_but_rejects_invalid_replacement(self):
        current = workbench_document()
        ready = ready_result()
        ready["document"] = copy.deepcopy(current)
        del ready["document"]["objects"][1]["workbench"]
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(ready)
        parsed = parse_planner_response(ready, current_document=current)
        self.assertEqual(parsed["document"]["objects"][1]["workbench"], current["objects"][1]["workbench"])
        self.assertNotIn("workbench", ready["document"]["objects"][1])
        ready["document"]["objects"][1]["workbench"] = copy.deepcopy(current["objects"][1]["workbench"])
        ready["document"]["objects"][1]["workbench"]["role"] = "resource"
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(ready, current_document=current)

    def test_initial_revision_retains_previous_proposal_mapping_and_provenance(self):
        previous = workbench_document()
        previous["objects"][1]["workbench"]["provenance"]["kind"] = "proposal"
        ready = ready_result()
        ready["document"] = copy.deepcopy(previous)
        for obj in ready["document"]["objects"]:
            obj.pop("workbench", None)
        parsed = parse_planner_response(ready, previous_document=previous)
        self.assertEqual(parsed["document"]["objects"][1]["workbench"], previous["objects"][1]["workbench"])
        self.assertNotIn("workbench", ready["document"]["objects"][1])
        ready["document"]["objects"][1]["workbench"] = {**previous["objects"][1]["workbench"], "role": "resource"}
        with self.assertRaises(ObjectProtocolError):
            parse_planner_response(ready, previous_document=previous)

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

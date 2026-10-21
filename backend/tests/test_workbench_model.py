"""Casino semantic mapping refreshes facts from the requested source commit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import workbench_model
from backend.object_protocol import catalog_from_document


def casino_document():
    objects = []
    for object_id in workbench_model._CASINO_OBJECTS:
        kind = "project" if object_id == "project-casino" else "scene" if object_id == "arena-scene" else "mechanic"
        binding = "scenes/arena.tscn" if object_id == "arena-scene" else f"scripts/{object_id}.gd"
        objects.append({"id": object_id, "kind": kind, "name": object_id,
                        "sourceBindings": [binding], "fields": []})
    fields = {
        "round-director": [
            ("rounds-per-run", "integer", 5), ("round-duration", "number", 90),
            ("transition-duration", "number", 3)],
        "player": [("move-speed", "number", 240), ("max-health", "integer", 100)],
        "dice-burst": [
            ("warning-duration", "number", 1.5), ("reward-lifetime", "number", 6),
            ("reward-value", "integer", 30)],
        "visual-direction": [
            ("felt-color", "color", "#236B59"), ("gold-color", "color", "#CBA565"),
            ("accent-color", "color", "#A83D4A")],
        "game-interface": [("virtual-stick-enabled", "boolean", False)],
    }
    for obj in objects:
        for field_id, field_type, value in fields.get(obj["id"], []):
            field = {"id": field_id, "label": field_id, "type": field_type,
                     "value": value, "editable": True}
            if field_type in {"number", "integer"}:
                field.update(min=0, max=1000, **({"step": 1} if field_type == "integer" else {}))
            obj["fields"].append(field)
    return {"schemaVersion": "studio.objects.v1", "dimension": "2d", "title": "Casino",
        "summary": "A Casino arena.", "objects": objects,
        "requirements": [{"id": "play", "text": "The player can move."}]}


class WorkbenchModelTests(unittest.TestCase):
    def test_growth_dice_and_combat_semantics_are_pinned_and_distinguish_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source_doc = casino_document()
            source_bindings = {
                "automatic-combat": "scripts/simulation/combat_system.gd",
                "growth-system": "scripts/simulation/growth_system.gd",
                "dice-burst": "scripts/simulation/dice_event.gd",
            }
            for item in source_doc["objects"]:
                if item["id"] in source_bindings:
                    item["sourceBindings"] = [source_bindings[item["id"]]]

            def git_show(_repo, _commit, path):
                if path == workbench_model.CASINO_SOURCE_DOCUMENT:
                    return json.dumps(source_doc)
                if path == "project.godot":
                    return "window/size/viewport_width=640\nwindow/size/viewport_height=480\n"
                if path == "scripts/simulation/round_director.gd":
                    return "const BOUNDS = Rect2(0, 0, 600, 400)\n\tplayer.reset(config, BOUNDS.get_center())\n"
                raise AssertionError(path)

            with patch.object(workbench_model, "_git_show", side_effect=git_show):
                result = workbench_model.enrich_casino_document(
                    casino_document(), repo_path=repo, source_commit=workbench_model.CASINO_SOURCE_COMMIT)

        objects = {item["id"]: item for item in result["objects"]}
        growth = objects["growth-system"]["workbench"]
        self.assertEqual(growth["guard"], "options.is_empty() 且 experience >= cost()；cost() = first_cost + (level - 1) * cost_increment。")
        self.assertIn("scripts/simulation/growth_system.gd", growth["provenance"]["sourcePaths"])
        self.assertIn("scripts/simulation/round_director.gd", growth["provenance"]["sourcePaths"])
        transition_ids = [relation["targetId"] for relation in objects["growth-system"]["relations"]
                          if relation["type"] == "state_transition"]
        self.assertEqual(transition_ids, ["growth-transition-enter-upgrade", "growth-transition-choose-upgrade"])
        for transition_id in transition_ids:
            metadata = objects[transition_id]["workbench"]
            self.assertEqual(metadata["sourceCommit"], workbench_model.CASINO_SOURCE_COMMIT)
            self.assertEqual(metadata["provenance"]["kind"], "inference")
            self.assertEqual(metadata["preview"]["type"], "rule")
        self.assertEqual(objects[transition_ids[0]]["workbench"]["fromState"], "running")
        self.assertEqual(objects[transition_ids[0]]["workbench"]["toState"], "upgrade")
        self.assertIn("upgrade", objects[transition_ids[1]]["workbench"]["fromState"])
        self.assertIn("running", objects[transition_ids[1]]["workbench"]["toState"])
        catalog = catalog_from_document(result, workbench_model.CASINO_SOURCE_COMMIT)
        catalog_objects = {item["id"]: item for item in catalog["objects"]}
        self.assertEqual(catalog_objects["growth-system"]["relations"][-2:], [
            {"type": "state_transition", "targetId": "growth-transition-enter-upgrade"},
            {"type": "state_transition", "targetId": "growth-transition-choose-upgrade"},
        ])
        self.assertEqual(catalog_objects[transition_ids[0]]["workbench"]["fromState"], "running")

        dice = objects["dice-burst"]["workbench"]
        self.assertEqual(dice["sourceCommit"], workbench_model.CASINO_SOURCE_COMMIT)
        self.assertIn("craps", dice["trigger"])
        self.assertIn("0.8 秒", dice["trigger"])
        self.assertIn("场地边界内侧 90 像素", dice["positionPolicy"])
        self.assertIn("有限生命周期", dice["cleanup"])
        self.assertIn("scripts/simulation/dice_event.gd", dice["provenance"]["sourcePaths"])
        self.assertIn("scripts/simulation/round_director.gd", dice["provenance"]["sourcePaths"])

        combat = objects["automatic-combat"]["workbench"]
        self.assertEqual(combat["sourceCommit"], workbench_model.CASINO_SOURCE_COMMIT)
        self.assertEqual(combat["provenance"]["kind"], "fact")
        self.assertIn("scripts/simulation/combat_system.gd", combat["provenance"]["sourcePaths"])
        self.assertEqual(combat["preview"]["stages"], [])
        self.assertIn("未声明统一阶段时间线", combat["preview"]["label"])
        self.assertIn("即时扫击", combat["lifecycle"])
        self.assertIn("投射物命中与寿命", combat["lifecycle"])

    def test_exact_later_source_commit_refreshes_derived_scene_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            versions = {
                "casino-v1": {"viewport": (640, 480), "bounds": (10, 20, 600, 400)},
                "casino-v2": {"viewport": (800, 600), "bounds": (20, 30, 700, 500)},
            }
            source_doc = casino_document()

            def git_show(_repo, commit, path):
                if path == workbench_model.CASINO_SOURCE_DOCUMENT:
                    return json.dumps(source_doc)
                version = versions[commit]
                if path == "project.godot":
                    return (f"window/size/viewport_width={version['viewport'][0]}\n"
                            f"window/size/viewport_height={version['viewport'][1]}\n")
                if path == "scripts/simulation/round_director.gd":
                    return ("const BOUNDS = Rect2(%s)\n"
                            "\tplayer.reset(config, BOUNDS.get_center())\n") % ", ".join(map(str, version["bounds"]))
                raise AssertionError(path)

            with patch.object(workbench_model, "_git_show", side_effect=git_show):
                first = workbench_model.enrich_casino_document(casino_document(), repo_path=repo, source_commit="casino-v1")
                second = workbench_model.enrich_casino_document(first, repo_path=repo, source_commit="casino-v2")

            objects = {item["id"]: item for item in second["objects"]}
            self.assertEqual(len(objects), len(second["objects"]))
            self.assertEqual(objects["arena-scene"]["workbench"]["bounds"], [800.0, 600.0])
            self.assertEqual(objects["player-arena-instance"]["workbench"]["position"], [370.0, 280.0])
            self.assertEqual(objects["player-start-entry"]["workbench"]["position"], [370.0, 280.0])
            self.assertEqual(objects["player"]["workbench"]["sourceCommit"], "casino-v2")
            self.assertEqual(objects["player-arena-instance"]["workbench"]["sourceCommit"], "casino-v2")
            self.assertEqual(objects["enemy-roster"]["workbench"]["provenance"]["sourcePaths"],
                             ["GDD.md", "scripts/enemy-roster.gd"])
            self.assertEqual(objects["environment-texas"]["workbench"]["role"], "preset")
            self.assertEqual(objects["environment-texas"]["kind"], "mechanic")
            self.assertEqual(objects["enemy-kind-0"]["workbench"]["role"], "definition")
            self.assertEqual(objects["player-arena-instance"]["workbench"]["lock"], "fixed")
            self.assertEqual(objects["project-casino"]["workbench"].get("driver"), None)

    def test_later_source_revision_refreshes_field_driven_previews(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source_doc = casino_document()
            version = {"viewport": (640, 480), "bounds": (10, 20, 600, 400)}

            def git_show(_repo, _commit, path):
                if path == workbench_model.CASINO_SOURCE_DOCUMENT:
                    return json.dumps(source_doc)
                if path == "project.godot":
                    return (f"window/size/viewport_width={version['viewport'][0]}\n"
                            f"window/size/viewport_height={version['viewport'][1]}\n")
                if path == "scripts/simulation/round_director.gd":
                    return ("const BOUNDS = Rect2(%s)\n"
                            "\tplayer.reset(config, BOUNDS.get_center())\n") % ", ".join(map(str, version["bounds"]))
                raise AssertionError(path)

            with patch.object(workbench_model, "_git_show", side_effect=git_show):
                first = workbench_model.enrich_casino_document(
                    casino_document(), repo_path=repo, source_commit="casino-v1")
                updated = json.loads(json.dumps(first))
                values = {"warning-duration": 2.25, "reward-lifetime": 8.5, "reward-value": 42}
                for field in next(o for o in updated["objects"] if o["id"] == "dice-burst")["fields"]:
                    if field["id"] in values:
                        field["value"] = values[field["id"]]
                next(f for o in updated["objects"] if o["id"] == "player" for f in o["fields"]
                     if f["id"] == "move-speed")["value"] = 315
                next(f for o in updated["objects"] if o["id"] == "round-director" for f in o["fields"]
                     if f["id"] == "round-duration")["value"] = 75
                version.update(viewport=(960, 540), bounds=(40, 30, 800, 400))
                second = workbench_model.enrich_casino_document(
                    updated, repo_path=repo, source_commit="casino-v2")

            objects = {item["id"]: item for item in second["objects"]}
            dice_stages = objects["dice-burst"]["workbench"]["preview"]["stages"]
            self.assertEqual([stage["duration"] for stage in dice_stages], [2.25, 0.4, 8.5])
            self.assertEqual([stage.get("durationFieldId") for stage in dice_stages],
                             ["warning-duration", None, "reward-lifetime"])
            self.assertIn("42", dice_stages[-1]["label"])
            self.assertEqual(objects["player"]["workbench"]["preview"]["speed"], 315.0)
            self.assertEqual(objects["player"]["workbench"]["preview"]["speedFieldId"], "move-speed")
            self.assertIn("315", objects["player"]["workbench"]["preview"]["label"])
            round_preview = objects["round-director"]["workbench"]["preview"]
            self.assertEqual([stage["duration"] for stage in round_preview["stages"]], [75.0, 3.0])
            self.assertEqual([stage["durationFieldId"] for stage in round_preview["stages"]],
                             ["round-duration", "transition-duration"])
            self.assertIn("casino-v2", objects["dice-burst"]["workbench"]["sourceCommit"])
            self.assertEqual(objects["visual-direction"]["workbench"]["preview"]["label"],
                             "程序绘制配色 · 绒面 #236B59 · 金色 #CBA565 · 强调 #A83D4A")
            self.assertIn("虚拟摇杆未启用", objects["game-interface"]["workbench"]["preview"]["label"])


if __name__ == "__main__":
    unittest.main()

"""A source preview belongs to the selected target and retained Git version."""
import tempfile
import unittest
import io
from pathlib import Path

from backend.coordinator import Coordinator, WorkflowError, git
from backend.tests.test_object_protocol import sample_document


class WorkbenchSourceTests(unittest.TestCase):
    def test_bound_atlas_and_clip_use_actual_retained_resource(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            coordinator = Coordinator(Path(__file__).resolve().parents[2], state_root=Path(directory), test_data=True)
            try:
                project = coordinator.create_project(operator_id=coordinator.operator_id, title="Resource fixture")
                repo = Path(directory) / "projects" / project["id"]
                (repo / "assets").mkdir(parents=True)
                (repo / "resources").mkdir()
                git(repo, "init")
                git(repo, "config", "user.name", "Fixture")
                git(repo, "config", "user.email", "fixture@localhost")
                image = Image.new("RGB", (32, 16), "red")
                image.paste("blue", (16, 0, 32, 16))
                image.save(repo / "assets/sheet.png")
                (repo / "resources/tile.tres").write_text('''[gd_resource type="AtlasTexture" format=3]
[ext_resource type="Texture2D" path="res://assets/sheet.png" id="sheet"]
[resource]
atlas = ExtResource("sheet")
region = Rect2(16, 0, 16, 16)
''')
                (repo / "resources/frames.tres").write_text('''[gd_resource type="SpriteFrames" format=3]
[ext_resource type="Texture2D" path="res://assets/sheet.png" id="sheet"]
[sub_resource type="AtlasTexture" id="first"]
atlas = ExtResource("sheet")
region = Rect2(16, 0, 16, 16)
[resource]
animations = [{"frames": [{"duration": 1.0, "texture": SubResource("first")}, {"duration": 1.0, "texture": ExtResource("sheet")}], "loop": true, "name": &"run", "speed": 8.0}]
''')
                git(repo, "add", ".")
                git(repo, "commit", "-m", "Bound source resources")
                commit = git(repo, "rev-parse", "HEAD")
                doc = sample_document()
                player = next(o for o in doc["objects"] if o["id"] == "player")
                player["sourceBindings"] = ["resources/tile.tres", "resources/frames.tres"]
                player["workbench"] = {"role": "definition", "scope": "shared", "provenance": {"kind": "fact", "sourcePaths": ["resources/tile.tres", "resources/frames.tres"]}, "preview": {"type": "image", "label": "Source region", "stages": [], "resourcePath": "resources/tile.tres"}}
                snapshot = {"id": "snapshot-resource", "projectId": project["id"], "sourceCommit": commit,
                            "document": doc, "kind": "MVP", "publicationRevision": 1}
                with coordinator.transaction():
                    coordinator._put("snapshot", snapshot)
                    project.update(snapshotId=snapshot["id"], publicationRevision=1)
                    coordinator._put("project", project)
                Image.new("RGB", (32, 16), "green").save(repo / "assets/sheet.png")
                metadata = coordinator.workbench_object_source(project["id"], "player")["imagePreview"]
                self.assertEqual(metadata["region"], [16, 0, 16, 16])
                data, mime = coordinator.workbench_object_source(project["id"], "player", image=True)
                with Image.open(io.BytesIO(data)) as cropped:
                    self.assertEqual(cropped.size, (16, 16))
                    self.assertEqual(cropped.getpixel((0, 0)), (0, 0, 255))
                self.assertEqual(mime, "image/png")
                player["workbench"]["preview"].update(resourcePath="resources/frames.tres", clipName="run")
                with coordinator.transaction():
                    coordinator._put("snapshot", snapshot)
                metadata = coordinator.workbench_object_source(project["id"], "player")["imagePreview"]
                self.assertEqual((metadata["clipName"], metadata["frameCount"], metadata["fps"]), ("run", 2, 8))
                data, _ = coordinator.workbench_object_source(project["id"], "player", image=True)
                self.assertEqual(Image.open(io.BytesIO(data)).size, (16, 16))
                player["workbench"]["preview"]["clipName"] = "missing"
                with coordinator.transaction():
                    coordinator._put("snapshot", snapshot)
                with self.assertRaises(WorkflowError):
                    coordinator.workbench_object_source(project["id"], "player", image=True)
            finally:
                coordinator.close()

    def test_static_source_uses_retained_commit_and_target_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = Coordinator(Path(__file__).resolve().parents[2], state_root=Path(directory), test_data=True)
            try:
                project = coordinator.create_project(operator_id=coordinator.operator_id, title="Source fixture")
                repo = Path(directory) / "projects" / project["id"]
                repo.mkdir(parents=True)
                git(repo, "init")
                git(repo, "config", "user.name", "Fixture")
                git(repo, "config", "user.email", "fixture@localhost")
                (repo / "scripts").mkdir()
                script = repo / "scripts/player.gd"
                script.write_text("extends Node2D\n# retained source\n")
                git(repo, "add", ".")
                git(repo, "commit", "-m", "Retained source")
                commit = git(repo, "rev-parse", "HEAD")
                doc = sample_document()
                player = next(o for o in doc["objects"] if o["id"] == "player")
                player["sourceBindings"] = ["scripts/player.gd"]
                snapshot = {"id": "snapshot-source", "projectId": project["id"], "sourceCommit": commit,
                            "document": doc, "kind": "MVP", "publicationRevision": 1}
                with coordinator.transaction():
                    coordinator._put("snapshot", snapshot)
                    project.update(snapshotId=snapshot["id"], publicationRevision=1)
                    coordinator._put("project", project)
                script.write_text("extends Node2D\n# newer dirty text\n")
                preview = coordinator.workbench_object_source(project["id"], "player")
                self.assertEqual(preview["sourceCommit"], commit)
                self.assertIn("retained source", preview["sources"][0]["content"])
                self.assertNotIn("newer dirty text", preview["sources"][0]["content"])
                with self.assertRaises(WorkflowError):
                    coordinator.workbench_object_source(project["id"], "missing")
                script.write_text("extends Node2D\n# candidate implementation\n")
                (repo / "GDD.md").write_text("Unrelated specification change.\n")
                git(repo, "add", "scripts/player.gd", "GDD.md")
                git(repo, "commit", "-m", "Candidate implementation")
                candidate_commit = git(repo, "rev-parse", "HEAD")
                with coordinator.transaction():
                    coordinator._put("job", {"id": "job-source", "projectId": project["id"],
                        "originalBaseCommit": commit, "candidate": {"id": "candidate-source", "candidateCommit": candidate_commit}})
                script.write_text("extends Node2D\n# unsaved unrelated text\n")
                evidence = coordinator.workbench_source_changes(project["id"], "job-source")
                self.assertEqual(evidence["sourceCommit"], candidate_commit)
                self.assertIn("+# candidate implementation", evidence["changes"][0]["diff"])
                self.assertNotIn("unsaved unrelated", evidence["changes"][0]["diff"])
                self.assertFalse(evidence["truncated"], "excluded specification paths do not truncate a complete source diff")
                self.assertEqual(evidence["userAcceptance"], "NOT_PERFORMED")
            finally:
                coordinator.close()


if __name__ == "__main__":
    unittest.main()

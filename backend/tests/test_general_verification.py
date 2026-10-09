from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.general_verification import (
    GeneralVerificationError,
    audit_general_scope,
    verify_general_project,
)
from backend.object_protocol import validate_document


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "general_2d"


def _document() -> dict:
    return {
        "schemaVersion": "studio.objects.v1",
        "dimension": "2d",
        "title": "测试迷宫",
        "summary": "从入口到达出口。",
        "objects": [
            {
                "id": "main-scene",
                "kind": "scene",
                "name": "主场景",
                "sourceBindings": ["scenes/main.tscn", "scripts/main.gd"],
                "fields": [],
            },
            {
                "id": "player",
                "kind": "entity",
                "name": "玩家",
                "parentId": "main-scene",
                "sourceBindings": ["scripts/main.gd"],
                "fields": [
                    {
                        "id": "speed",
                        "label": "速度",
                        "type": "number",
                        "value": 220,
                        "min": 0,
                        "max": 1000,
                        "editable": True,
                    }
                ],
            },
        ],
        "requirements": [
            {
                "id": "reach-exit",
                "text": "玩家可以到达迷宫出口。",
                "objectIds": ["player"],
                "verification": "automated",
            }
        ],
    }


class GeneralVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(TEMPLATE, self.project)
        self.document = validate_document(_document())
        (self.project / "design/game.json").write_text(
            json.dumps(self.document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@localhost"], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "--all"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "trusted baseline"], check=True)
        self.base = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temp.cleanup()

    def _add_pinned_service_records(self):
        approval_path = ".godotmaker/frontend-approval.json"
        stage_path = ".godotmaker/stage.jsonl"
        (self.project / ".gitignore").write_text(".godotmaker/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "ignore pinned service files"], check=True)
        self.base = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        records = {
            approval_path: '{"schemaVersion":1,"projectId":"project-test"}\n',
            stage_path: '{"stage":"SPEC_CONFIRMED"}\n',
        }
        for path, content in records.items():
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return records

    def test_scaffold_exposes_object_value_interface(self):
        runtime = (self.project / "studio/runtime.gd").read_text(encoding="utf-8")
        self.assertIn("static func value(", runtime)
        self.assertIn("func object_value(", runtime)

    def test_scope_accepts_supported_game_source_edits(self):
        source = self.project / "scripts/main.gd"
        source.write_text("extends Node2D\n\nfunc _ready():\n\tposition = Vector2(2, 3)\n", encoding="utf-8")
        self.assertEqual(
            audit_general_scope(self.project, self.base, self.document), ["scripts/main.gd"]
        )

    def test_scope_rejects_unapproved_plugin_and_verifier_changes(self):
        for path in ("addons/plugin.gd", "tests/producer_test.gd", "studio/runtime.gd"):
            with self.subTest(path=path):
                candidate = Path(self.temp.name) / path.replace("/", "_")
                candidate.write_text("producer content", encoding="utf-8")
                target = self.project / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, target)
                with self.assertRaises(GeneralVerificationError):
                    audit_general_scope(self.project, self.base, self.document)
                target.unlink()
                for parent in (target.parent, *target.parents):
                    if parent == self.project:
                        break
                    try:
                        parent.rmdir()
                    except OSError:
                        pass

    def test_scope_rejects_missing_and_external_source_bindings(self):
        missing = validate_document(_document())
        missing["objects"][1]["sourceBindings"] = ["scripts/missing.gd"]
        with self.assertRaisesRegex(GeneralVerificationError, "missing"):
            audit_general_scope(self.project, self.base, missing)
        escaped = validate_document(_document())
        escaped["objects"][1]["sourceBindings"] = ["scripts/../../outside.gd"]
        with self.assertRaises(GeneralVerificationError):
            audit_general_scope(self.project, self.base, escaped)

    def test_scope_rejects_producer_ignored_engine_cache(self):
        with (self.project / ".gitignore").open("a", encoding="utf-8") as stream:
            stream.write("\n.godot/\n")
        subprocess.run(["git", "-C", str(self.project), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "ignore engine cache"], check=True)
        self.base = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (self.project / ".godot").mkdir()
        (self.project / ".godot/user-cache.bin").write_text("producer cache", encoding="utf-8")
        with self.assertRaisesRegex(GeneralVerificationError, "ignored"):
            audit_general_scope(self.project, self.base, self.document)

    def test_changed_source_requires_an_approved_object_binding(self):
        (self.project / "scripts/unmapped.gd").write_text("extends Node\n", encoding="utf-8")
        with self.assertRaisesRegex(GeneralVerificationError, "no approved object binding"):
            audit_general_scope(self.project, self.base, self.document)
        (self.project / "scripts/unmapped.gd").unlink()
        (self.project / "scripts/main.gd").write_text("extends Node2D\n# bound implementation\n", encoding="utf-8")
        self.assertEqual(audit_general_scope(self.project, self.base, self.document), ["scripts/main.gd"])

    def test_deleted_source_requires_an_approved_object_binding(self):
        unbound = self.project / "scripts/unmapped.gd"
        unbound.write_text("extends Node\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "scripts/unmapped.gd"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "add unbound source"], check=True)
        self.base = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        unbound.unlink()

        with self.assertRaisesRegex(GeneralVerificationError, "no approved object binding"):
            audit_general_scope(self.project, self.base, self.document)

    def test_scope_accepts_only_exact_backend_pinned_service_records(self):
        records = self._add_pinned_service_records()
        self.assertEqual(
            audit_general_scope(self.project, self.base, self.document, service_records=records),
            [],
        )

    def test_scope_rejects_tampered_missing_unknown_and_unlisted_service_records(self):
        records = self._add_pinned_service_records()
        approval = self.project / ".godotmaker/frontend-approval.json"
        approval.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(GeneralVerificationError, "differs"):
            audit_general_scope(self.project, self.base, self.document, service_records=records)
        approval.write_text(records[".godotmaker/frontend-approval.json"], encoding="utf-8")
        approval.write_bytes(records[".godotmaker/frontend-approval.json"].replace("\n", "\r\n").encode())
        with self.assertRaisesRegex(GeneralVerificationError, "differs"):
            audit_general_scope(self.project, self.base, self.document, service_records=records)
        approval.write_text(records[".godotmaker/frontend-approval.json"], encoding="utf-8")
        (self.project / ".godotmaker/stage.jsonl").unlink()

        with self.assertRaisesRegex(GeneralVerificationError, "missing"):
            audit_general_scope(
                self.project,
                self.base,
                self.document,
                service_records={".godotmaker/frontend-approval.json": records[".godotmaker/frontend-approval.json"],
                    ".godotmaker/stage.jsonl": "missing\n"},
            )
        (self.project / ".godotmaker/stage.jsonl").write_text(
            records[".godotmaker/stage.jsonl"], encoding="utf-8"
        )
        with self.assertRaisesRegex(GeneralVerificationError, "unsupported"):
            audit_general_scope(
                self.project,
                self.base,
                self.document,
                service_records={**records, ".godotmaker/other.json": "unknown\n"},
            )

        extra_path = self.project / ".godotmaker/producer.json"
        extra_path.write_text("producer\n", encoding="utf-8")
        with self.assertRaisesRegex(GeneralVerificationError, "unauthorized ignored"):
            audit_general_scope(self.project, self.base, self.document, service_records=records)

    def test_verification_report_never_claims_gameplay_acceptance(self):
        fake_godot = Path(self.temp.name) / "godot-mock"
        fake_godot.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "if '--version' in sys.argv:\n print('mock-godot 4.x')\n sys.exit(0)\n"
            "if '--editor' in sys.argv:\n"
            " assert not pathlib.Path('.godotmaker').exists()\n sys.exit(0)\n"
            "if '--script' in sys.argv:\n"
            " assert pathlib.Path('.studio_verifier/runtime_smoke.gd').is_file()\n"
            " print('STUDIO_BACKEND_RUNTIME_SMOKE_OBSERVED')\n sys.exit(0)\n"
            "sys.exit(4)\n",
            encoding="utf-8",
        )
        fake_godot.chmod(0o755)
        records = self._add_pinned_service_records()
        result = verify_general_project(
            self.project,
            self.document,
            base_commit=self.base,
            godot_path=fake_godot,
            timeout=2,
            service_records=records,
        )
        self.assertEqual(result["technicalStatus"], "PASS")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(item["status"] == "NOT_TESTED" for item in result["userAcceptance"]))
        self.assertTrue(all(item["needsReview"] for item in result["userAcceptance"]))
        self.assertEqual(result["sandbox"]["status"], "NOT_APPLIED")
        self.assertIn("fresh_import", [command["name"] for command in result["commands"]])
        self.assertIn("backend_runtime_smoke", [command["name"] for command in result["commands"]])

    def test_unsupported_operation_does_not_launch_engine(self):
        result = verify_general_project(
            self.project, self.document, base_commit=self.base, operation="INITIALIZATION"
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["commands"], [])


if __name__ == "__main__":
    unittest.main()

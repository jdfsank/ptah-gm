from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.verification import (
    DEFAULT_RULES,
    VerificationError,
    read_rules,
    read_rules_baseline,
    semantic_catalog,
    verify_project,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "collect_loop"
GODOT = "/Applications/Godot.app/Contents/MacOS/Godot"


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns(".godot"))
        self._git("init", "-q")
        self._git("config", "user.name", "Verifier Test")
        self._git("config", "user.email", "verifier-test@localhost")
        self._git("add", ".")
        self._git("commit", "-qm", "trusted template baseline")
        self.base = self._git("rev-parse", "HEAD").strip()
        self.fake_godot = Path(self.temp.name) / "godot-fixture"
        self.mode = "template"
        self._write_fake_godot()

    def tearDown(self):
        self.temp.cleanup()

    def _git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def _write_fake_godot(self):
        script = f"""#!/usr/bin/env python3
import sys, time
args = sys.argv[1:]
mode = {self.mode!r}
if mode == "sleep":
    time.sleep(2)
if "--editor" in args:
    print("import fixture output")
else:
    print("COLLECT_LOOP_TEMPLATE_GATE_PASS" if mode == "template" else "COLLECT_LOOP_SCENETREE_PASS")
if mode == "warning":
    print("WARNING: fixture warning")
"""
        self.fake_godot.write_text(script)
        self.fake_godot.chmod(0o755)

    def _initialize(self):
        path = self.root / "initialization.json"
        data = json.loads(path.read_text())
        data.update({"projectId": "project-test", "prepared": True})
        path.write_text(json.dumps(data, indent=2) + "\n")
        result = verify_project(
            self.root,
            "INITIALIZATION",
            DEFAULT_RULES,
            base_commit=self.base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "PASS", result["diagnostics"])
        self._git("add", "initialization.json")
        self._git("commit", "-qm", "prepared project")
        return self._git("rev-parse", "HEAD").strip()

    def _implement(self):
        base = self._initialize()
        self.mode = "pass"
        self._write_fake_godot()
        path = self.root / "config/rules.json"
        rules = json.loads(path.read_text())
        rules.update(
            {
                "initialized": True,
                "target_count": 4,
                "time_limit": 45.0,
                "player_speed": 180.0,
            }
        )
        path.write_text(json.dumps(rules, indent=2) + "\n")
        return base, rules

    def test_template_is_explicitly_nonplayable_and_catalog_exposes_only_rule_controls(
        self,
    ):
        rules = read_rules(self.root)
        catalog = semantic_catalog(self.root)
        self.assertEqual(rules, DEFAULT_RULES)
        self.assertFalse(catalog["playable"])
        self.assertEqual(
            {
                prop["id"]
                for obj in catalog["objects"]
                for prop in obj.get("properties", [])
            },
            {"target_count", "time_limit", "player_speed"},
        )
        self.assertEqual(read_rules_baseline(self.root, self.base), DEFAULT_RULES)

    def test_initialization_can_change_only_initialization_manifest_and_keeps_game_locked(
        self,
    ):
        self.mode = "template"
        self._write_fake_godot()
        path = self.root / "initialization.json"
        data = json.loads(path.read_text())
        data.update({"projectId": "project-test", "prepared": True})
        path.write_text(json.dumps(data, indent=2) + "\n")
        result = verify_project(
            self.root,
            "initialize",
            DEFAULT_RULES,
            base_commit=self.base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "PASS", result["diagnostics"])
        self.assertFalse(result["rules"]["initialized"])
        self.assertEqual(
            result["commands"][-1]["argv"][-1], "res://tests/closed_loop.gd"
        )

    def test_implementation_requires_exact_rules_allowlist_and_server_values(self):
        base, rules = self._implement()
        result = verify_project(
            self.root,
            "implementation",
            rules,
            base_commit=base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "PASS", result["diagnostics"])
        self.assertEqual(result["catalog"]["rules"], rules)
        self.assertIn("COLLECT_LOOP_SCENETREE_PASS", result["commands"][-1]["stdout"])

    def test_second_implementation_uses_previous_playable_rules_as_trusted_baseline(
        self,
    ):
        first_base, first_rules = self._implement()
        first = verify_project(
            self.root,
            "implementation",
            first_rules,
            base_commit=first_base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(first["status"], "PASS", first["diagnostics"])
        self._git("add", "config/rules.json")
        self._git("commit", "-qm", "first playable publication")
        second_base = self._git("rev-parse", "HEAD").strip()
        second_rules = {**first_rules, "target_count": 6, "time_limit": 60.0}
        (self.root / "config/rules.json").write_text(
            json.dumps(second_rules, indent=2) + "\n"
        )
        second = verify_project(
            self.root,
            "IMPLEMENTATION",
            second_rules,
            base_commit=second_base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(second["status"], "PASS", second["diagnostics"])

    def test_implementation_rejects_unapproved_source_file_changes(self):
        base, _rules = self._implement()
        (self.root / "scripts/player.gd").write_text(
            (self.root / "scripts/player.gd").read_text() + "\n# unauthorized\n"
        )
        result = verify_project(
            self.root,
            "implementation",
            None,
            base_commit=base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["commands"], [])
        self.assertIn("outside its allowlist", result["requirements"][2]["evidence"])

    def test_engine_warning_fails_and_complete_output_is_preserved(self):
        base, rules = self._implement()
        self.mode = "warning"
        self._write_fake_godot()
        result = verify_project(
            self.root,
            "implementation",
            rules,
            base_commit=base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("WARNING: fixture warning", result["commands"][0]["stdout"])
        self.assertTrue(
            any(
                "warning or error" in str(d.get("message"))
                for d in result["diagnostics"]
            )
        )

    def test_timeout_is_reported_with_complete_partial_output(self):
        base, rules = self._implement()
        self.mode = "sleep"
        self._write_fake_godot()
        result = verify_project(
            self.root,
            "implementation",
            rules,
            base_commit=base,
            godot_path=self.fake_godot,
            timeout=0.1,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["commands"][0]["timedOut"])
        self.assertEqual(result["commands"][0]["name"], "import")
        self.assertTrue(
            any("timed out" in str(d.get("message")) for d in result["diagnostics"])
        )

    def test_invalid_rules_and_value_mismatch_are_rejected_before_engine(self):
        path = self.root / "config/rules.json"
        rules = json.loads(path.read_text())
        rules["target_count"] = 3.5
        path.write_text(json.dumps(rules))
        with self.assertRaises(VerificationError):
            read_rules(self.root)
        rules["target_count"] = 3
        path.write_text(json.dumps(rules, indent=2) + "\n")
        base, expected = self._implement()
        expected["player_speed"] = 181.0
        result = verify_project(
            self.root,
            "implementation",
            expected,
            base_commit=base,
            godot_path=self.fake_godot,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["commands"], [])


if __name__ == "__main__":
    unittest.main()

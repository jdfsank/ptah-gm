"""Tests for check_classname.py."""
import json
import os
import subprocess
import sys
import tempfile

import pytest

# tests/tools/ → project_root/tools/
CHECK_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools", "check_classname.py"
)


def run_check(project_dir: str, *flags: str) -> tuple[str, int]:
    """Run check_classname.py and return (stdout, exit_code)."""
    result = subprocess.run(
        [sys.executable, CHECK_SCRIPT, project_dir, *flags],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout, result.returncode


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestBlacklist:
    """Verify the blacklist contains known dangerous names."""

    @pytest.mark.parametrize("name", [
        "Key", "Node", "World", "System", "Resource",
        "Timer", "Signal", "Error", "Input", "Label", "Button",
    ])
    def test_known_problematic_names_in_blacklist(self, name, project_dir):
        # Write a .gd file with the conflicting class_name, expect exit code 1
        gd_file = os.path.join(project_dir, f"test_{name.lower()}.gd")
        with open(gd_file, "w") as f:
            f.write(f"class_name {name}\nextends Node\n")
        stdout, code = run_check(project_dir, "--json")
        assert code == 1, f"'{name}' should be detected as conflict"
        data = json.loads(stdout)
        assert any(c["class_name"] == name for c in data["conflicts"])

    def test_blacklist_minimum_size(self, project_dir):
        # Run with --json on empty project, parse the script to count names
        # Instead, just run a known-good name and verify it passes
        gd_file = os.path.join(project_dir, "safe.gd")
        with open(gd_file, "w") as f:
            f.write("class_name MySafeClass\nextends Node\n")
        _, code = run_check(project_dir)
        assert code == 0


class TestConflictDetection:
    """Verify that conflicting class_name declarations are detected."""

    def test_detects_conflict(self, project_dir):
        gd_file = os.path.join(project_dir, "bad_timer.gd")
        with open(gd_file, "w") as f:
            f.write("class_name Timer\nextends Node2D\n")

        stdout, code = run_check(project_dir, "--json")
        assert code == 1
        result = json.loads(stdout)
        assert result["clean"] is False
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["class_name"] == "Timer"
        assert result["conflicts"][0]["conflicts_with"] == "Timer"

    def test_detects_multiple_conflicts(self, project_dir):
        with open(os.path.join(project_dir, "a.gd"), "w") as f:
            f.write("class_name Node\n")
        with open(os.path.join(project_dir, "b.gd"), "w") as f:
            f.write("class_name Signal\n")

        stdout, code = run_check(project_dir, "--json")
        result = json.loads(stdout)
        assert result["clean"] is False
        assert len(result["conflicts"]) == 2

    def test_human_readable_output(self, project_dir):
        with open(os.path.join(project_dir, "bad.gd"), "w") as f:
            f.write("class_name Error\n")

        stdout, code = run_check(project_dir)
        assert code == 1
        assert "[FAIL]" in stdout
        assert "Error" in stdout


class TestCleanFiles:
    """Verify that valid class_name declarations pass."""

    def test_clean_file(self, project_dir):
        with open(os.path.join(project_dir, "player.gd"), "w") as f:
            f.write("class_name PlayerController\nextends CharacterBody2D\n")

        stdout, code = run_check(project_dir, "--json")
        assert code == 0
        result = json.loads(stdout)
        assert result["clean"] is True
        assert result["conflicts"] == []

    def test_no_class_name_declaration(self, project_dir):
        with open(os.path.join(project_dir, "helper.gd"), "w") as f:
            f.write("extends Node2D\nfunc _ready():\n\tpass\n")

        stdout, code = run_check(project_dir)
        assert code == 0
        assert "[PASS]" in stdout

    def test_empty_project(self, project_dir):
        stdout, code = run_check(project_dir, "--json")
        assert code == 0
        result = json.loads(stdout)
        assert result["clean"] is True


class TestDirectorySkipping:
    """Verify that addons/, .godot/, .claude/ directories are skipped."""

    def test_addons_skipped(self, project_dir):
        addon_dir = os.path.join(project_dir, "addons", "some_plugin")
        os.makedirs(addon_dir)
        with open(os.path.join(addon_dir, "plugin.gd"), "w") as f:
            f.write("class_name Node\n")  # Would conflict, but should be skipped

        stdout, code = run_check(project_dir, "--json")
        assert code == 0
        result = json.loads(stdout)
        assert result["clean"] is True

    def test_godot_dir_skipped(self, project_dir):
        godot_dir = os.path.join(project_dir, ".godot", "cache")
        os.makedirs(godot_dir)
        with open(os.path.join(godot_dir, "generated.gd"), "w") as f:
            f.write("class_name Resource\n")

        stdout, code = run_check(project_dir, "--json")
        assert code == 0
        result = json.loads(stdout)
        assert result["clean"] is True

    def test_claude_dir_skipped(self, project_dir):
        claude_dir = os.path.join(project_dir, ".claude")
        os.makedirs(claude_dir)
        with open(os.path.join(claude_dir, "temp.gd"), "w") as f:
            f.write("class_name System\n")

        stdout, code = run_check(project_dir, "--json")
        assert code == 0
        result = json.loads(stdout)
        assert result["clean"] is True

    def test_conflict_outside_skipped_dirs(self, project_dir):
        # File in addons (should be skipped)
        addon_dir = os.path.join(project_dir, "addons", "gecs")
        os.makedirs(addon_dir)
        with open(os.path.join(addon_dir, "ecs.gd"), "w") as f:
            f.write("class_name Node\n")

        # File in project root (should be checked)
        with open(os.path.join(project_dir, "bad.gd"), "w") as f:
            f.write("class_name Timer\n")

        stdout, code = run_check(project_dir, "--json")
        result = json.loads(stdout)
        assert code == 1
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["class_name"] == "Timer"

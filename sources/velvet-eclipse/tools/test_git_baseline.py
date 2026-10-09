from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import git_baseline
import review_support


class GitBaselineTests(unittest.TestCase):
    def git(self, root: Path, *args: str, env=None) -> str:
        return subprocess.check_output(["git", *args], cwd=root, env=env, text=True).strip()

    def test_identity_bytes_uses_git_blob_identity_shape(self):
        first = git_baseline.identity_bytes(b"content")
        self.assertRegex(first, r"^git:blob:[0-9a-f]+$")
        self.assertEqual(first, git_baseline.identity_bytes(b"content"))
        self.assertNotEqual(first, git_baseline.identity_bytes(b"changed"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payload"
            path.write_bytes(b"content")
            self.assertEqual(first, git_baseline.identity_file(path))

    def test_game_helper_is_a_same_source_copy_of_handoff_helper(self):
        handoff = Path(__file__).resolve().parents[3] / "tools" / "git_baseline.py"
        local = Path(git_baseline.__file__).resolve()
        self.assertEqual(local.read_bytes(), handoff.read_bytes())
        self.assertEqual(git_baseline.identity_file(local), git_baseline.identity_file(handoff))

    def test_capture_detects_add_remove_content_and_mode_without_real_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "project.godot").write_text("config")
            (root / "scripts").mkdir()
            script = root / "scripts/player.gd"
            script.write_text("extends Node\n")
            self.git(root, "init", "--quiet")
            env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
            self.git(root, "add", "-f", "project.godot", "scripts/player.gd")
            self.git(root, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "base", env=env)
            index = Path(self.git(root, "rev-parse", "--git-path", "index"))
            if not index.is_absolute():
                index = root / index
            before_index = index.read_bytes()
            self.git(root, "config", "core.filemode", "false")
            baseline = git_baseline.capture_inventory(root, ["project.godot", "scripts/player.gd"])
            self.assertTrue(all(value.startswith("git:100644:blob:") for value in baseline.values()))
            git_baseline.repository_state(root)
            self.assertEqual(before_index, index.read_bytes())
            script.write_text("extends Node\n# changed\n")
            script.chmod(0o755)
            (root / "added.gd").write_text("extends RefCounted\n")
            current = git_baseline.capture_inventory(root, ["project.godot", "scripts/player.gd", "added.gd"])
            self.assertNotEqual(baseline["scripts/player.gd"], current["scripts/player.gd"])
            self.assertTrue(current["scripts/player.gd"].startswith("git:100755:blob:"))
            self.assertIn("added.gd", set(current) - set(baseline))
            del script
            (root / "scripts/player.gd").unlink()
            without_script = git_baseline.capture_inventory(root, ["project.godot", "added.gd"])
            self.assertIn("scripts/player.gd", set(baseline) - set(without_script))
            self.assertEqual(before_index, index.read_bytes())

    def test_inventory_rejects_final_and_intermediate_symlinks(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root, external = Path(temp), Path(outside)
            (external / "secret.txt").write_text("secret")
            (root / "link-dir").symlink_to(external, target_is_directory=True)
            (root / "link-file").symlink_to(external / "secret.txt")
            for relative in ("link-dir/secret.txt", "link-file"):
                with self.subTest(path=relative), self.assertRaises(git_baseline.GitBaselineError):
                    git_baseline.capture_inventory(root, [relative])

    def test_temporary_fixture_without_git_is_supported_by_capture_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_text("A")
            (root / "b.txt").write_text("B")
            first = git_baseline.capture_inventory(root, ["a.txt", "b.txt"])
            self.assertEqual(first, git_baseline.capture_inventory(root, ["a.txt", "b.txt"]))

    def test_game_inventory_captures_subdirectory_project_in_handoff_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            top = Path(temp)
            project = top / "sources" / "game"
            (project / "tests").mkdir(parents=True)
            (project / "project.godot").write_text("config")
            (project / "tests" / "test_logic.py").write_text("def test_ok(): pass\n")
            self.git(top, "init", "--quiet")
            env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
            self.git(top, "add", "-f", "sources/game/project.godot", "sources/game/tests/test_logic.py")
            self.git(top, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "base", env=env)
            source, tests = review_support.inventory(project)
            self.assertEqual(set(source), {"project.godot"})
            self.assertEqual(set(tests), {"tests/test_logic.py"})
            self.assertTrue(source["project.godot"].startswith("git:100644:blob:"))
            self.assertTrue(tests["tests/test_logic.py"].startswith("git:100644:blob:"))


if __name__ == "__main__":
    unittest.main()

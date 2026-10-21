from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.general_verification import GeneralVerificationError, audit_general_scope
from tools.godot_mcp_install import InstallError, install_godot_mcp


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPOSITORY_ROOT / "addons" / "godot_mcp"
TEMPLATES = (
    REPOSITORY_ROOT / "backend" / "templates" / "general_2d",
    REPOSITORY_ROOT / "backend" / "templates" / "collect_loop",
)


def _regular_bundle(root: Path) -> dict[str, bytes]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError(f"unexpected symbolic link: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


class GodotMCPInstallTests(unittest.TestCase):
    def test_canonical_bundle_is_copied_identically_into_both_templates(self):
        expected = _regular_bundle(PLUGIN)
        self.assertEqual(len(expected), 70)
        for template in TEMPLATES:
            with self.subTest(template=template.name):
                self.assertEqual(_regular_bundle(template / "addons" / "godot_mcp"), expected)
                settings = (template / "project.godot").read_text(encoding="utf-8")
                self.assertIn(
                    'enabled=PackedStringArray("res://addons/godot_mcp/plugin.cfg")',
                    settings,
                )

    def test_installer_preserves_existing_plugin_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "existing"
            project.mkdir()
            settings = project / "project.godot"
            settings.write_text(
                'config_version=5\n\n[application]\nconfig/name="Existing"\n\n'
                '[editor_plugins]\nenabled=PackedStringArray("res://addons/other/plugin.cfg")\n',
                encoding="utf-8",
            )
            other_plugin = project / "addons" / "other" / "plugin.cfg"
            other_plugin.parent.mkdir(parents=True)
            other_plugin.write_text('[plugin]\nname="Other"\n', encoding="utf-8")

            self.assertTrue(install_godot_mcp(project))
            installed_settings = settings.read_text(encoding="utf-8")
            self.assertIn('config/name="Existing"', installed_settings)
            self.assertIn('"res://addons/other/plugin.cfg"', installed_settings)
            self.assertIn('"res://addons/godot_mcp/plugin.cfg"', installed_settings)
            self.assertEqual(other_plugin.read_text(encoding="utf-8"), '[plugin]\nname="Other"\n')
            plugin_files = _regular_bundle(project / "addons" / "godot_mcp")
            self.assertEqual(plugin_files, _regular_bundle(PLUGIN))

            self.assertFalse(install_godot_mcp(project))
            self.assertEqual(settings.read_text(encoding="utf-8"), installed_settings)
            self.assertEqual(_regular_bundle(project / "addons" / "godot_mcp"), plugin_files)

    def test_installer_creates_a_new_project_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "new" / "game"
            self.assertTrue(install_godot_mcp(project))
            self.assertTrue((project / "project.godot").is_file())
            self.assertIn(
                'res://addons/godot_mcp/plugin.cfg',
                (project / "project.godot").read_text(encoding="utf-8"),
            )
            self.assertEqual(_regular_bundle(project / "addons" / "godot_mcp"), _regular_bundle(PLUGIN))

    def test_installer_rejects_conflicting_addon_without_changing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            addon = project / "addons" / "godot_mcp"
            addon.mkdir(parents=True)
            (addon / "plugin.cfg").write_text("different plugin", encoding="utf-8")
            settings = project / "project.godot"
            settings.write_text('config_version=5\n', encoding="utf-8")
            with self.assertRaisesRegex(InstallError, "conflicts"):
                install_godot_mcp(project)
            self.assertEqual(settings.read_text(encoding="utf-8"), 'config_version=5\n')
            self.assertEqual((addon / "plugin.cfg").read_text(encoding="utf-8"), "different plugin")

    def test_installer_rejects_symlinked_addon_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            settings = project / "project.godot"
            settings.write_text('config_version=5\n', encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            addons = project / "addons"
            addons.mkdir()
            (addons / "godot_mcp").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(InstallError, "symbolic links"):
                install_godot_mcp(project)
            self.assertEqual(settings.read_text(encoding="utf-8"), 'config_version=5\n')
            self.assertEqual(list(outside.iterdir()), [])

    def test_installer_rejects_symlink_in_existing_project_ancestor_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            requested_project = linked_parent / "new-project"

            with self.assertRaisesRegex(InstallError, "symbolic links in the project path"):
                install_godot_mcp(requested_project)

            self.assertFalse((real_parent / "new-project").exists())
            self.assertFalse((real_parent / "new-project" / "project.godot").exists())
            self.assertEqual(list(real_parent.iterdir()), [])

    def test_general_scope_audit_still_rejects_changes_inside_bundled_addon(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            shutil.copytree(TEMPLATES[0], project)
            document = json.loads((project / "design" / "game.json").read_text(encoding="utf-8"))
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.email", "test@localhost"], check=True)
            subprocess.run(["git", "-C", str(project), "add", "--all"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "trusted template"], check=True)
            base = subprocess.run(
                ["git", "-C", str(project), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            plugin_script = project / "addons" / "godot_mcp" / "plugin.gd"
            plugin_script.write_bytes(plugin_script.read_bytes() + b"\n# producer change\n")
            with self.assertRaisesRegex(GeneralVerificationError, "outside the general project write policy"):
                audit_general_scope(project, base, document)


if __name__ == "__main__":
    unittest.main()

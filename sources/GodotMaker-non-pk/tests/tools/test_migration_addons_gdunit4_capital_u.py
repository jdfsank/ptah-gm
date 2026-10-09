"""Tests for migrations/20260510163525_addons_gdunit4_capital_u.py.

Migration renames addons/gdunit4/ -> addons/gdUnit4/ to match upstream
repo casing, and rewrites project.godot's enabled=PackedStringArray(...)
to use res://addons/gdUnit4/plugin.cfg.

Every step is idempotent.
"""
import importlib.util
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "20260510163525_addons_gdunit4_capital_u.py"
)


@pytest.fixture
def migration_module():
    spec = importlib.util.spec_from_file_location("gdunit4_capital_u", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_lowercase_project(target: Path) -> None:
    """A pre-migration project: addons/gdunit4/ on disk + project.godot
    with the lowercase plugin reference. Mirrors GodotMakerTest1's actual
    state on 2026-05-09.
    """
    (target / "addons" / "gdunit4" / "bin").mkdir(parents=True)
    (target / "addons" / "gdunit4" / "plugin.cfg").write_text(
        '[plugin]\nname="gdUnit4"\nversion="6.1.0"\n', encoding="utf-8"
    )
    (target / "addons" / "gecs").mkdir()
    (target / "addons" / "godot_e2e").mkdir()
    (target / "project.godot").write_text(
        'config_version=5\n\n'
        '[application]\n'
        'config/name="Test"\n\n'
        '[editor_plugins]\n'
        'enabled=PackedStringArray('
        '"res://addons/gecs/plugin.cfg", '
        '"res://addons/gdunit4/plugin.cfg", '
        '"res://addons/godot_e2e/plugin.cfg"'
        ')\n',
        encoding="utf-8",
    )


def _seed_already_capital_project(target: Path) -> None:
    """A project that already has the post-migration shape -- migration
    must be a no-op."""
    (target / "addons" / "gdUnit4" / "bin").mkdir(parents=True)
    (target / "addons" / "gdUnit4" / "plugin.cfg").write_text(
        '[plugin]\nname="gdUnit4"\nversion="6.1.0"\n', encoding="utf-8"
    )
    (target / "addons" / "gecs").mkdir()
    (target / "addons" / "godot_e2e").mkdir()
    (target / "project.godot").write_text(
        'config_version=5\n\n'
        '[application]\n'
        'config/name="Test"\n\n'
        '[editor_plugins]\n'
        'enabled=PackedStringArray('
        '"res://addons/gecs/plugin.cfg", '
        '"res://addons/gdUnit4/plugin.cfg", '
        '"res://addons/godot_e2e/plugin.cfg"'
        ')\n',
        encoding="utf-8",
    )


class TestRenameAddonDir:
    def test_lowercase_dir_renamed_to_capital_u(self, migration_module, tmp_path):
        _seed_lowercase_project(tmp_path)
        migration_module.migrate(tmp_path)

        # Directory now exists with the canonical capital-U casing. We
        # cannot assert "lowercase is gone" on Windows because NTFS is
        # case-insensitive: querying /addons/gdunit4 still resolves to
        # /addons/gdUnit4. So we check via iterdir() which surfaces the
        # literal stored casing.
        names = {p.name for p in (tmp_path / "addons").iterdir() if p.is_dir()}
        assert "gdUnit4" in names
        assert "gdunit4" not in names
        # Plugin contents survive the rename (sanity check).
        assert (tmp_path / "addons" / "gdUnit4" / "plugin.cfg").is_file()
        assert (tmp_path / "addons" / "gdUnit4" / "bin").is_dir()

    def test_no_addons_dir_is_skip(self, migration_module, tmp_path):
        # No addons/ at all -- migration must not blow up.
        (tmp_path / "project.godot").write_text(
            "config_version=5\n", encoding="utf-8"
        )
        migration_module.migrate(tmp_path)
        assert not (tmp_path / "addons").exists()

    def test_already_capital_u_is_noop(self, migration_module, tmp_path):
        _seed_already_capital_project(tmp_path)
        before_plugin_mtime = (
            tmp_path / "addons" / "gdUnit4" / "plugin.cfg"
        ).stat().st_mtime_ns
        before_project_godot = (tmp_path / "project.godot").read_bytes()

        migration_module.migrate(tmp_path)

        names = {p.name for p in (tmp_path / "addons").iterdir() if p.is_dir()}
        assert "gdUnit4" in names
        # plugin.cfg untouched
        after_plugin_mtime = (
            tmp_path / "addons" / "gdUnit4" / "plugin.cfg"
        ).stat().st_mtime_ns
        assert before_plugin_mtime == after_plugin_mtime
        # project.godot untouched (byte-for-byte)
        assert (tmp_path / "project.godot").read_bytes() == before_project_godot

    def test_uppercase_variant_also_renamed(self, migration_module, tmp_path):
        """Defensive: any non-canonical casing (GDUnit4, GDUNIT4, ...) is
        normalised. We can't actually create two distinct case variants
        on Windows so this only fully exercises on case-sensitive FSes;
        on Windows it degrades to "directory created with caller's
        literal casing, then renamed."
        """
        # Use GDUnit4 (deliberate weird casing) as the seed.
        (tmp_path / "addons" / "GDUnit4").mkdir(parents=True)
        (tmp_path / "addons" / "GDUnit4" / "plugin.cfg").write_text(
            '[plugin]\nname="gdUnit4"\n', encoding="utf-8"
        )
        (tmp_path / "project.godot").write_text(
            'enabled=PackedStringArray("res://addons/GDUnit4/plugin.cfg")\n',
            encoding="utf-8",
        )
        migration_module.migrate(tmp_path)

        names = {p.name for p in (tmp_path / "addons").iterdir() if p.is_dir()}
        assert "gdUnit4" in names
        # Lowercase / weird-cased entries are gone.
        assert "GDUnit4" not in names
        assert "gdunit4" not in names

    def test_recovers_from_leftover_tmp_dir(self, migration_module, tmp_path):
        """If a previous migration attempt crashed between step-1 rename
        (lowercase -> tmp) and step-2 rename (tmp -> canonical), only
        the tmp directory remains -- step-1 already moved the original.
        Re-running must finish step-2.
        """
        (tmp_path / "addons" / "gdunit4__migrating__").mkdir(parents=True)
        (tmp_path / "addons" / "gdunit4__migrating__" / "plugin.cfg").write_text(
            '[plugin]\nname="gdUnit4"\n', encoding="utf-8"
        )
        (tmp_path / "project.godot").write_text(
            'enabled=PackedStringArray("res://addons/gdunit4/plugin.cfg")\n',
            encoding="utf-8",
        )

        migration_module.migrate(tmp_path)

        names = {p.name for p in (tmp_path / "addons").iterdir() if p.is_dir()}
        assert "gdUnit4" in names
        assert "gdunit4__migrating__" not in names
        # Plugin contents survived the salvage rename.
        assert (tmp_path / "addons" / "gdUnit4" / "plugin.cfg").is_file()


class TestRewriteProjectGodot:
    def test_rewrites_lowercase_plugin_reference(self, migration_module, tmp_path):
        _seed_lowercase_project(tmp_path)
        migration_module.migrate(tmp_path)

        text = (tmp_path / "project.godot").read_text(encoding="utf-8")
        assert "res://addons/gdUnit4/plugin.cfg" in text
        assert "res://addons/gdunit4/plugin.cfg" not in text
        # Other entries preserved.
        assert "res://addons/gecs/plugin.cfg" in text
        assert "res://addons/godot_e2e/plugin.cfg" in text

    def test_no_project_godot_is_skip(self, migration_module, tmp_path):
        # Just an addons/ directory, no project.godot at all.
        (tmp_path / "addons" / "gdunit4").mkdir(parents=True)
        migration_module.migrate(tmp_path)
        assert not (tmp_path / "project.godot").exists()

    def test_project_godot_without_plugin_entry_is_noop(self, migration_module, tmp_path):
        """No [editor_plugins] section -- file must remain untouched."""
        content = (
            'config_version=5\n\n'
            '[application]\n'
            'config/name="Test"\n'
        )
        (tmp_path / "project.godot").write_text(content, encoding="utf-8")
        migration_module.migrate(tmp_path)
        assert (tmp_path / "project.godot").read_text(encoding="utf-8") == content

    def test_rewrites_non_plugin_references_too(self, migration_module, tmp_path):
        """Defensive: project.godot can reference the addon from sections
        other than [editor_plugins] -- autoloads, script_class_icons,
        per-section script paths. The migration must rewrite all of
        them, not just `plugin.cfg`. gdUnit4 itself does not register an
        autoload at v5.1.1 / v6.1.0, but a hand-edited project or a
        future addon version could; better to be casing-correct
        everywhere than carry mismatched paths into the next version."""
        (tmp_path / "addons" / "gdunit4").mkdir(parents=True)
        (tmp_path / "project.godot").write_text(
            'config_version=5\n\n'
            '[application]\n'
            'config/name="Test"\n\n'
            '[autoload]\n'
            'GdUnitHelper="*res://addons/gdunit4/src/helpers/foo.gd"\n\n'
            '[editor_plugins]\n'
            'enabled=PackedStringArray("res://addons/gdunit4/plugin.cfg")\n\n'
            '[input]\n'
            'some_action={\n'
            '"script": "res://addons/gdunit4/src/Bar.gd"\n'
            '}\n',
            encoding="utf-8",
        )

        migration_module.migrate(tmp_path)

        text = (tmp_path / "project.godot").read_text(encoding="utf-8")
        # All three lowercase references rewritten to capital U.
        assert "res://addons/gdUnit4/src/helpers/foo.gd" in text
        assert "res://addons/gdUnit4/plugin.cfg" in text
        assert "res://addons/gdUnit4/src/Bar.gd" in text
        # No lowercase references survive anywhere in the file.
        assert "res://addons/gdunit4/" not in text


class TestIdempotency:
    def test_second_run_is_byte_for_byte_noop(self, migration_module, tmp_path):
        _seed_lowercase_project(tmp_path)
        migration_module.migrate(tmp_path)
        snapshot = {
            "project.godot": (tmp_path / "project.godot").read_bytes(),
            "plugin.cfg": (tmp_path / "addons" / "gdUnit4" / "plugin.cfg").read_bytes(),
        }
        before_names = sorted(p.name for p in (tmp_path / "addons").iterdir())

        migration_module.migrate(tmp_path)

        assert (tmp_path / "project.godot").read_bytes() == snapshot["project.godot"]
        assert (
            tmp_path / "addons" / "gdUnit4" / "plugin.cfg"
        ).read_bytes() == snapshot["plugin.cfg"]
        after_names = sorted(p.name for p in (tmp_path / "addons").iterdir())
        assert after_names == before_names

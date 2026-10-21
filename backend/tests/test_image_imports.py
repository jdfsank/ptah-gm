"""Regressions for image imports in disposable Godot copies."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.tests import test_source_preparation as preparation_fixture
from backend.tests import test_general_verification as verification_fixture
from backend.source_preparation import prepare_godot_uid_sidecars, load_uid_preparation_evidence
from backend.general_verification import GeneralVerificationError, verify_general_project
from runners.image_imports import missing_image_imports, read_generated_imports, validate_import_path
from runners.godot_runtime import GodotRuntime, sandboxed_godot_argv


def metadata(source='assets/art.png', destination='res://.godot/imported/art.ctex'):
    return ('[remap]\nimporter="texture"\ntype="CompressedTexture2D"\n'
            'path=' + json.dumps(destination) + '\n[deps]\nsource_file=' + json.dumps('res://' + source)
            + '\ndest_files=' + json.dumps([destination]) + '\n[params]\ncompress/mode=0\n')


def bind_image(fixture):
    fixture.document['objects'][0]['sourceBindings'].append('assets/art.png')
    (fixture.project / 'assets').mkdir(exist_ok=True)
    (fixture.project / 'assets/art.png').write_bytes(b'image fixture; importer is mocked')
    (fixture.project / 'design/game.json').write_text(json.dumps(fixture.document))
    for args in (['add', '.'], ['commit', '-qm', 'Bind trusted image fixture']):
        subprocess.run(['git', '-C', str(fixture.project), *args], check=True)
    fixture.base = subprocess.check_output(['git', '-C', str(fixture.project), 'rev-parse', 'HEAD'], text=True).strip()


class ImportMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'assets').mkdir()
        (self.root / 'assets/art.png').write_bytes(b'trusted image')

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_source_cache_binding_and_missing_inventory(self):
        paths = missing_image_imports(self.root, ['assets/art.png', 'scripts/main.gd'])
        self.assertEqual(paths, ('assets/art.png.import',))
        (self.root / paths[0]).write_text(metadata())
        self.assertEqual(read_generated_imports(self.root, paths), {paths[0]: metadata().encode()})
        self.assertEqual(missing_image_imports(self.root, ['assets/art.png']), ())

    def test_rejects_traversal_symlink_and_wrong_sources(self):
        for path in ['assets/../art.png.import', '../assets/art.png.import', 'scripts/main.gd.import', 'assets/absent.png.import']:
            with self.assertRaises(ValueError):
                validate_import_path(self.root, path)
        (self.root / 'assets/art.png.import').symlink_to(self.root / 'assets/art.png')
        with self.assertRaises(ValueError):
            validate_import_path(self.root, 'assets/art.png.import')

    def test_rejects_metadata_for_other_source_or_outside_cache(self):
        path = self.root / 'assets/art.png.import'
        for content in [metadata(source='assets/other.png'), metadata(destination='res://scripts/payload.gd'), metadata() + 'source_file="res://assets/art.png"\n']:
            path.write_text(content)
            with self.assertRaises(ValueError):
                read_generated_imports(self.root, ['assets/art.png.import'])

    def test_sandbox_only_grants_exact_missing_metadata_during_recovery_import(self):
        runtime = GodotRuntime.create(self.root / 'runtime')
        engine = self.root / 'godot'
        engine.write_text('mock engine')
        engine.chmod(0o700)
        support = runtime.root / 'trusted-ca'
        support.mkdir()
        ca, library = support / 'ca.pem', support / 'library.dylib'
        ca.touch(); library.touch()
        path = self.root / 'assets/art.png.import'
        with mock.patch.object(GodotRuntime, 'prepare_trusted_ca_interposer', return_value=(support, ca, library)):
            args = sandboxed_godot_argv(engine, ['--editor', '--recovery-mode', '--import'], project_root=self.root, runtime=runtime, image_import_write_paths=[path])
            profile = args[2]
            self.assertIn(f'(allow file-write* (literal "{path}"))', profile)
            self.assertNotIn(f'(allow file-write* (subpath "{self.root / "assets"}"))', profile)
            for arguments in [['--version'], ['--headless', '--script', 'res://main.gd']]:
                with self.assertRaisesRegex(ValueError, 'recovery'):
                    sandboxed_godot_argv(engine, arguments, project_root=self.root, runtime=runtime, image_import_write_paths=[path])
            path.write_text(metadata())
            with self.assertRaisesRegex(ValueError, 'missing'):
                sandboxed_godot_argv(engine, ['--editor', '--recovery-mode', '--import'], project_root=self.root, runtime=runtime, image_import_write_paths=[path])


class ImportWorkflowTests(unittest.TestCase):
    def test_uid_quarantine_accepts_only_expected_import_metadata_and_never_copies_it_back(self):
        f = preparation_fixture.SourcePreparationTests()
        f.setUp()
        try:
            bind_image(f)
            f._fake_godot("if '--editor' in sys.argv:\n"
                          " pathlib.Path('scripts/main.gd.uid').write_bytes(b'uid://mainfixture\\n')\n"
                          " pathlib.Path('studio/runtime.gd.uid').write_bytes(b'uid://runtimefixture\\n')\n"
                          " pathlib.Path('assets/art.png.import').write_text(" + repr(metadata()) + ")\n sys.exit(0)\n")
            with mock.patch('runners.godot_runtime.sandboxed_godot_argv', side_effect=lambda executable, arguments, **kw: [str(executable), *arguments]) as launch:
                result = prepare_godot_uid_sidecars(f.project, base_commit=f.base, document=f.document, godot_path=f.godot)
            self.assertEqual(len(result.sidecars), 2)
            self.assertEqual(result.image_imports, ('assets/art.png.import',))
            self.assertIn('only UID sidecars copied back', result.evidence('fixture-source')['writeBoundary'])
            artifact = f.root / 'artifact'
            proof = artifact / 'evidence/uid-preparation.json'
            proof.parent.mkdir(parents=True)
            proof.write_text(json.dumps(result.evidence('fixture-source')))
            loaded, engine = load_uid_preparation_evidence(artifact, input_commit=f.base, source_commit='fixture-source')
            self.assertEqual(dict(loaded), dict(result.sidecars))
            self.assertEqual(engine, result.engine_version)
            self.assertFalse((f.project / 'assets/art.png.import').exists())
            self.assertEqual(len(launch.call_args_list[-1].kwargs['image_import_write_paths']), 1)
        finally:
            f.tearDown()

    def test_verifier_preserves_source_and_rejects_runtime_metadata_mutations(self):
        f = verification_fixture.GeneralVerificationTests()
        f.setUp()
        try:
            bind_image(f)
            fake = Path(f.temp.name) / 'godot-image-mock'
            for mutate in [False, True]:
                fake.write_text(f'#!{sys.executable}\nimport pathlib,sys\n'
                    "if '--version' in sys.argv: print('4.6.3.stable.mock'); sys.exit(0)\n"
                    "if '--editor' in sys.argv:\n pathlib.Path('assets/art.png.import').write_text(" + repr(metadata()) + "); sys.exit(0)\n"
                    "if '--script' in sys.argv:\n"
                    + (" pathlib.Path('assets/art.png.import').write_text('runtime mutation')\n" if mutate else '')
                    + " print('STUDIO_BACKEND_RUNTIME_SMOKE_OBSERVED'); sys.exit(0)\n")
                fake.chmod(0o700)
                with mock.patch('runners.godot_runtime.sandboxed_godot_argv', side_effect=lambda executable, arguments, **kw: [str(executable), *arguments]) as launch:
                    report = verify_general_project(f.project, f.document, base_commit=f.base, godot_path=fake)
                self.assertEqual(report['technicalStatus'], 'FAIL' if mutate else 'PASS', report['diagnostics'])
                self.assertTrue(launch.call_args_list[1].kwargs['image_import_write_paths'])
                self.assertFalse(launch.call_args_list[2].kwargs.get('image_import_write_paths'))
                self.assertFalse((f.project / 'assets/art.png.import').exists())
        finally:
            f.tearDown()

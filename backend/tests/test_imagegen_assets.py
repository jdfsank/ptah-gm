import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.imagegen_assets import ImageAssetError, git, import_bundle, load_bundle, requests_for
from backend.tests import test_studio_delivery as delivery_fixture
from tools.imagegen_cli import ImageGenerationError, generate_images


def png():
    stream = io.BytesIO()
    Image.new('RGB', (64, 64), 'navy').save(stream, format='PNG')
    return stream.getvalue()


def bundle(state, plan):
    bid = 'imagegen-' + 'a' * 32
    root = state / 'imagegen/bundles' / bid
    root.mkdir(parents=True)
    jobs = requests_for(plan)
    for job in jobs:
        target = root / job['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png())
    (root / 'manifest.json').write_text(json.dumps({'schemaVersion': 'studio.imagegen-bundle.v1', 'model': 'gpt-image-2', 'plan': plan, 'requests': jobs}))
    git(root, 'init', '--quiet', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@localhost')
    git(root, 'add', '.')
    git(root, 'commit', '--quiet', '-m', 'Synthetic PNG fixture; no image API call')
    return bid, root


class ImageToolTests(unittest.TestCase):
    def test_prompt_tool_has_no_backend_imports(self):
        import tools.imagegen_cli as tool
        self.assertNotIn('from backend', Path(tool.__file__).read_text())

    def test_dry_run_uses_bundled_cli_and_keeps_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_images([{'prompt': 'Visual planning sketch', 'filename': 'concept.png'}], output_dir=Path(tmp).resolve() / 'out', dry_run=True)
            self.assertEqual(result['status'], 'DRY_RUN')
            self.assertEqual(result['images'], [])
            self.assertIn('gpt-image-2', Path(result['log']).read_text())
            self.assertEqual(json.loads(Path(result['prompts']).read_text())[0]['prompt'], 'Visual planning sketch')

    def test_rejects_paths_duplicates_and_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../escape.png', '/escape.png', '.hidden.png'):
                with self.assertRaises(ImageGenerationError):
                    generate_images([{'prompt': 'test', 'filename': name}], output_dir=Path(tmp).resolve() / 'out', dry_run=True)
            with self.assertRaises(ImageGenerationError):
                generate_images([{'prompt': 'test', 'filename': 'a.png'}] * 2, output_dir=Path(tmp).resolve() / 'out', dry_run=True)
            with self.assertRaises(ImageGenerationError):
                generate_images([{'prompt': 'test', 'filename': 'a.png'}], output_dir=Path(tmp), dry_run=True)

    def test_no_partial_success_or_sensitive_errors(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENAI_API_KEY': 'fixture'}):
            with patch('tools.imagegen_cli.subprocess.Popen') as launch:
                launch.return_value.poll.return_value = 0
                launch.return_value.returncode = 0
                with self.assertRaisesRegex(ImageGenerationError, 'every requested image'):
                    generate_images([{'prompt': 'test', 'filename': 'a.png'}], output_dir=Path(tmp).resolve() / 'missing')
                launch.return_value.returncode = 1
                with self.assertRaisesRegex(ImageGenerationError, 'private log'):
                    generate_images([{'prompt': 'test', 'filename': 'a.png'}], output_dir=Path(tmp).resolve() / 'failed')
                self.assertEqual(launch.call_count, 2)
                self.assertTrue(launch.call_args.kwargs['start_new_session'])


class ImageBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name).resolve()
        self.plan = {'id': 'proposal-fixture', 'projectId': 'project-fixture', 'revision': 1,
                     'publicationRevision': 0, 'sourceRefs': {}, 'tasks': [],
                     'document': {'summary': 'concept', 'objects': [{'id': 'art', 'name': 'Art', 'description': 'Casino concept board', 'sourceBindings': ['assets/board.png']}]}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_images_imported_without_overwriting(self):
        bid, root = bundle(self.state, self.plan)
        ref, plan, images = load_bundle(self.state, bid)
        self.assertEqual(plan, self.plan)
        self.assertEqual(images['assets/board.png'], png())
        packet = {**self.plan, 'assetBundle': ref}
        destination = self.state / 'input'
        self.assertEqual(import_bundle(self.state, packet, destination), ['assets/board.png'])
        with self.assertRaisesRegex(ImageAssetError, 'existing'):
            import_bundle(self.state, packet, destination)

    def test_dirty_bundle_and_plan_mismatch_rejected(self):
        bid, root = bundle(self.state, self.plan)
        ref, _, _ = load_bundle(self.state, bid)
        packet = {**self.plan, 'assetBundle': ref, 'tasks': ['different']}
        with self.assertRaisesRegex(ImageAssetError, 'intent'):
            import_bundle(self.state, packet, self.state / 'input')
        (root / 'assets/board.png').write_bytes(b'not image')
        with self.assertRaisesRegex(ImageAssetError, 'dirty'):
            load_bundle(self.state, bid)

    def test_invalid_image_link_and_new_commit_rejected(self):
        bid, root = bundle(self.state, self.plan)
        ref, _, _ = load_bundle(self.state, bid)
        target = root / 'assets/board.png'
        target.write_bytes(b'not image')
        git(root, 'add', '.')
        git(root, 'commit', '--quiet', '-m', 'Invalid bytes')
        with self.assertRaises(ImageAssetError):
            load_bundle(self.state, bid)
        target.unlink()
        target.symlink_to(root / 'manifest.json')
        with self.assertRaisesRegex(ImageAssetError, 'links'):
            load_bundle(self.state, bid)

    def test_ref_cannot_select_another_commit(self):
        bid, root = bundle(self.state, self.plan)
        ref, _, _ = load_bundle(self.state, bid)
        ref['sourceCommit'] = 'wrong'
        with self.assertRaisesRegex(ImageAssetError, 'version'):
            load_bundle(self.state, bid, expected=ref)


class ImageStudioTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery_fixture.StudioDeliveryTests('test_accept_keeps_unreviewed_feedback_and_explicit_followup')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def ready_with_art(self):
        f = self.fixture
        proposal = f.ready()
        proposal['document']['objects'][0]['sourceBindings'].append('assets/board.png')
        # Use a fresh spec revision; original reviewed files remain immutable.
        proposal['revision'] += 1
        proposal.update(f.c._prepare_generic_spec(proposal, proposal['document'], proposal['tasks']))
        with f.c.transaction():
            f.c._put('proposal', proposal)
        return proposal

    def test_missing_art_rejected_before_approval_then_bundle_prepared(self):
        f = self.fixture
        proposal = self.ready_with_art()
        view = f.c.project_view(f.pid)
        receipt = f.command('proposal.freeze', {'proposalId': proposal['id'], 'reviewedPlanRef': view['proposal']['reviewedPlanRef']}, expected={'proposalRevision': proposal['revision'], 'publicationRevision': 0})
        self.assertEqual(receipt['error']['code'], 'PRODUCTION_ASSETS_REQUIRED')
        self.assertEqual(f.c.db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0], 0)
        plan = {key: proposal[key] for key in ('id', 'projectId', 'revision', 'publicationRevision', 'document', 'tasks', 'sourceRefs')}
        bid, _ = bundle(f.state, plan)
        attached = f.command('proposal.assets.attach', {'proposalId': proposal['id'], 'bundleId': bid}, expected={'proposalRevision': proposal['revision'], 'publicationRevision': 0})
        self.assertEqual(attached['status'], 'accepted', attached)
        self.assertEqual(f.c.image_bundle_image(f.pid, bid, 0), png())
        other = f.command('project.create', {'name': 'Other'}, pid=None)['result']['project']['id']
        from backend.coordinator import WorkflowError
        with self.assertRaises(WorkflowError):
            f.c.image_bundle_image(other, bid, 0)

        proposal = attached['result']['proposal']
        view = f.c.project_view(f.pid)
        frozen = f.command('proposal.freeze', {'proposalId': proposal['id'], 'reviewedPlanRef': view['proposal']['reviewedPlanRef']}, expected={'proposalRevision': proposal['revision'], 'publicationRevision': 0})
        self.assertEqual(frozen['status'], 'accepted', frozen)
        packet = frozen['result']['packet']
        self.assertIn('assetBundle', packet)
        started = f.command('production.start', {'packetId': packet['id']}, expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(started['status'], 'accepted', started)
        attempt = f.c._get('attempt', started['result']['job']['attemptId'])
        self.assertEqual(attempt['status'], 'QUEUED', attempt)
        artifact = f.state / 'artifacts' / attempt['prepared']['inputArtifactRef']['artifactId'] / 'repository'
        self.assertEqual((artifact / 'assets/board.png').read_bytes(), png())

    def test_producer_cannot_replace_reviewed_png_before_seal(self):
        from runners.agent import AgentRunner
        from backend.general_verification import GeneralVerificationError
        material = {'packet': {'assetBundle': {'paths': ['assets/board.png']}},
                    'prepared': {'inputCommit': 'fixture'}}
        with patch('backend.general_verification._git_changed_paths', return_value=['assets/board.png']):
            with self.assertRaisesRegex(GeneralVerificationError, 'reviewed ImageGen'):
                AgentRunner._seal(None, {}, material, self.fixture.state)

    def test_seal_diagnostic_distinguishes_completed_producer(self):
        c = self.fixture.c
        failure = c._producer_failure({'id': 'attempt-fixture', 'diagnosticRef': 'local:seal-diagnostics/attempt-fixture'}, failed=True)
        self.assertEqual(failure['code'], 'PRODUCTION_SEAL_FAILED')
        self.assertEqual(failure['nativeStatus'], 'completed')
        self.assertIn('封存', failure['message'])

"""Durable reference lifecycle through real storage, wire commands and inputs.

Provider failures are injected; these tests do not make chargeable API calls.
"""
import base64
import copy
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.coordinator import Coordinator, WorkflowError
from backend.object_protocol import ObjectProtocolError
from backend.concept_references import validate_visual_references
from backend.server import REPO_ROOT, make_server
from backend.tests import test_studio_protocol as wire


class ConceptReferenceTests(unittest.TestCase):
    envelope = wire.StudioProtocolTests.envelope
    command = wire.StudioProtocolTests.command
    runner = wire.StudioProtocolTests.runner
    report = wire.StudioProtocolTests.report
    ready = wire.StudioProtocolTests.ready

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'store'
        self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=False)
        self.seq = 0
        self.pid = self.command('project.create', {'name': 'Reference test'}, pid=None)['result']['project']['id']
        self.calls = 0

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def image(self):
        stream = io.BytesIO()
        Image.new('RGB', (83, 47), '#e6b943').save(stream, format='PNG')
        return stream.getvalue()

    def generate(self, jobs, *, output_dir, **_kwargs):
        self.calls += 1
        output_dir.mkdir(parents=True)
        (output_dir / jobs[0]['filename']).write_bytes(self.image())
        return {'model': 'gpt-image-2', 'status': 'GENERATED'}

    def request(self, rid='request-0123456789'):
        return {'requestId': rid, 'sourceText': '  雨衣下的暖光\n', 'interpretation': '冷暖对比', 'size': '1536x1024', 'quality': 'low'}

    def generated(self):
        with patch('tools.imagegen_cli.generate_images', self.generate):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request())
            self.c._threads['concept:' + record['id']].join(10)
        return self.c.concept_generations(self.pid)[0]

    def intent(self, aid):
        return {'assetId': aid, 'intent': '仅采纳雨衣轮廓与暖光', 'targetObjectIds': [], 'preserve': '保持玩法', 'unknown': '坐标和碰撞未知'}

    def planning(self):
        self.runner()
        # This test runner explicitly supports image input.
        from datetime import datetime, timezone
        self.c.update_runner_catalog({'runnerId': 'agent-test', 'catalogRevision': 2, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'models': [{'modelKey': 'model-fixture', 'modelProvider': 'fixture', 'supportedReasoningEfforts': ['medium'], 'inputModalities': ['text', 'image'], 'isDefault': True}]})
        self.asset = self.c.upload_asset(operator_id=self.c.operator_id, project_id=self.pid, name='rain.png', mime_type='image/png',
            data_base64=base64.b64encode(self.image()).decode(), purpose='reference')
        return self.command('concept.submit', {'text': '  原始想法\n', 'assetRefs': [self.asset['id']], 'visualReferences': [self.intent(self.asset['id'])]},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})['result']['proposal']

    def test_actual_dimensions_and_persisted_request_replay(self):
        record = self.generated()
        self.assertEqual(record['status'], 'GENERATED')
        self.assertEqual((record['asset']['width'], record['asset']['height']), (83, 47))
        self.assertEqual(record['asset']['generation']['requestedSize'], '1536x1024')
        self.assertEqual(record['request']['sourceText'], '  雨衣下的暖光\n')
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('Must not replay')):
            self.c.close()
            self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=False)
            replay = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request())
        self.assertEqual(replay, record)
        self.assertEqual(self.calls, 1)

    def test_cross_project_and_changed_request_id_reuse_rejected(self):
        self.generated()
        other = self.command('project.create', {'name': 'Other'}, pid=None)['result']['project']['id']
        with self.assertRaises(WorkflowError):
            self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=other, request=self.request())
        with self.assertRaises(WorkflowError):
            self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request={**self.request(), 'sourceText': 'Changed'})
        self.assertEqual(self.calls, 1)

    def test_uncertain_restart_and_reconcile_never_generate(self):
        with patch('tools.imagegen_cli.generate_images', side_effect=TimeoutError('private provider error')):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request())
            self.c._threads['concept:' + record['id']].join(10)
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=False)
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('No replay')):
            result = self.c.reconcile_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request_id=record['id'])
            self.assertEqual(result['status'], 'UNCERTAIN')
            with self.assertRaises(WorkflowError):
                self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request('request-1234567890'))
        self.assertNotIn('private provider', str(result))

    def test_completed_file_is_recovered_without_api(self):
        self.test_uncertain_restart_and_reconcile_never_generate()
        output = self.state / 'concept-generations' / self.request()['requestId']
        output.mkdir(parents=True)
        (output / 'concept.png').write_bytes(self.image())
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('No replay')):
            result = self.c.reconcile_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request_id=self.request()['requestId'])
            again = self.c.reconcile_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request_id=self.request()['requestId'])
        self.assertEqual(result, again)
        self.assertEqual(len(self.c._all('asset')), 1)

    def test_corrupt_image_is_not_marked_generated(self):
        def corrupt(jobs, *, output_dir, **kwargs):
            output_dir.mkdir(parents=True)
            (output_dir / 'concept.png').write_bytes(b'not png')
        with patch('tools.imagegen_cli.generate_images', corrupt):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request())
            self.c._threads['concept:' + record['id']].join(10)
        self.assertEqual(self.c.concept_generations(self.pid)[0]['status'], 'UNCERTAIN')
        self.assertEqual(self.c._all('asset'), [])

    def test_invalid_intents_and_text_only_visual(self):
        for values in ([], [self.intent('other')], [{**self.intent('asset'), 'intent': '  '}], [self.intent('asset'), self.intent('asset')]):
            with self.assertRaises(ObjectProtocolError):
                validate_visual_references(values, ['asset'])
        text_only = self.intent(None)
        self.assertEqual(validate_visual_references([text_only], []), [text_only])

    def test_reference_survives_planning_revise_freeze_and_producer_input(self):
        proposal = self.ready()
        expected_intent = [self.intent(self.asset['id'])]
        self.assertEqual(proposal['text'], '  原始想法\n')
        # Supplements omit assetRefs and retain the existing reference snapshot.
        revised = self.command('proposal.revise', {'proposalId': proposal['id'], 'supplement': '保留构图'},
            expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})['result']['proposal']
        self.assertEqual(revised['visualReferences'], expected_intent)
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-revised'})
        delivery = __import__('backend.tests.test_studio_delivery', fromlist=['StudioDeliveryTests']).StudioDeliveryTests
        delivery.started(self, revised['attemptId'])
        material = self.c.runner_input('agent-test', revised['attemptId'])
        self.assertEqual(material['packet']['visualReferences'], expected_intent)
        self.assertEqual(len(material['assets']), 1)
        from backend.tests.test_generic_workflow import plan_result
        self.report(revised['attemptId'], 'completed', {'stopped': True, 'result': {'response': {**plan_result(), 'schemaVersion': 'studio.planner-result.v1', 'feedbackDecisions': []}}})
        ref = self.c.project_view(self.pid)['proposal']['reviewedPlanRef']
        packet = self.command('proposal.freeze', {'proposalId': proposal['id'], 'reviewedPlanRef': ref}, expected={'proposalRevision': 2, 'publicationRevision': 0})['result']['packet']
        self.assertEqual(packet['visualReferences'], expected_intent)
        self.assertEqual(packet['assets'][0]['id'], self.asset['id'])
        self.assertEqual(packet['userText'], '  原始想法\n')
        self.assertEqual(self.c._get('packet', packet['id'])['approvedProposal']['visualReferences'], expected_intent)
        self.c.register_runner({'runnerId': 'project-test', 'runnerKind': 'project', 'environment': 'fixture', 'nativeVersion': None,
            'capabilities': ['verification-isolated-v1', 'preview-isolated-v1'],
            'sandboxEvidence': wire.fixture_role_evidence('project-test', 'project', ['verification-isolated-v1', 'preview-isolated-v1'])})
        receipt = self.command('production.start', {'packetId': packet['id']}, expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        job = self.c._get('job', receipt['result']['job']['id'])
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-production'})
        delivery.started(self, job['attemptId'])
        producer = self.c.runner_input('agent-test', job['attemptId'])
        self.assertEqual(producer['packet']['visualReferences'], expected_intent)
        self.assertEqual(producer['packet']['userText'], '  原始想法\n')
        self.assertEqual(producer['assets'][0]['dataBase64'], base64.b64encode(self.image()).decode())

    def test_legacy_asset_revision_retains_text_visual_requirements(self):
        proposal = self.ready()
        with self.c.transaction():
            proposal['visualReferences'].append(self.intent(None))
            self.c._put('proposal', proposal)
        revised = self.command('proposal.revise', {'proposalId': proposal['id'], 'assetRefs': [], 'supplement': '只保留文字视觉要求'},
            expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})['result']['proposal']
        self.assertEqual(revised['assets'], [])
        self.assertEqual(revised['visualReferences'], [self.intent(None)])

    def test_local_preflight_failure_is_retryable_without_private_error(self):
        from tools.imagegen_cli import ImageGenerationError
        with patch('tools.imagegen_cli.generate_images', side_effect=ImageGenerationError('private key path')):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request())
            self.c._threads['concept:' + record['id']].join(10)
        result = self.c.concept_generations(self.pid)[0]
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('private', str(result))

    def test_truncated_jpeg_is_rejected_by_full_decode(self):
        stream = io.BytesIO(); Image.new('RGB', (100, 100), '#fedcba').save(stream, format='JPEG')
        with self.assertRaises(WorkflowError):
            self.c.upload_asset(operator_id=self.c.operator_id, project_id=self.pid, name='bad.jpg', mime_type='image/jpeg',
                data_base64=base64.b64encode(stream.getvalue()[:-30]).decode(), purpose='reference')

    def test_candidate_capture_binding_idempotence_and_history(self):
        candidate = {'id': 'candidate-capture-test', 'candidateCommit': 'git-candidate'}
        with self.c.transaction():
            self.c._put('packet', {'id': 'packet-capture', 'projectId': self.pid, 'proposalId': 'proposal-capture', 'proposalRevision': 2})
            self.c._put('job', {'id': 'job-capture', 'projectId': self.pid, 'packetId': 'packet-capture', 'status': 'READY_FOR_REVIEW', 'candidate': candidate})
        body = {'requestId': 'capture-request-123456', 'name': 'run.png', 'mimeType': 'image/png', 'dataBase64': base64.b64encode(self.image()).decode(),
                'conditions': {'scene': 'main', 'viewport': '83x47', 'camera': 'fixed', 'state': 'initial', 'capturedAt': 'operator supplied time'}}
        saved = self.c.add_candidate_visual(operator_id=self.c.operator_id, project_id=self.pid, candidate_id=candidate['id'], request=body)
        again = self.c.add_candidate_visual(operator_id=self.c.operator_id, project_id=self.pid, candidate_id=candidate['id'], request=body)
        self.assertEqual(saved, again)
        self.assertFalse(saved['conditionsVerified'])
        self.assertEqual(saved['packetId'], 'packet-capture')
        with self.assertRaises(WorkflowError) as malformed:
            self.c.add_candidate_visual(operator_id=self.c.operator_id, project_id=self.pid, candidate_id=candidate['id'], request={**body, 'dataBase64': '!invalid'})
        self.assertEqual(malformed.exception.status, 400)
        with self.assertRaises(WorkflowError):
            self.c.add_candidate_visual(operator_id=self.c.operator_id, project_id=self.pid, candidate_id=candidate['id'], request={**body, 'conditions': {**body['conditions'], 'state': 'changed'}})
        with self.c.transaction():
            job = self.c._get('job', 'job-capture'); job['status'] = 'PUBLISHED'; self.c._put('job', job)
        self.assertEqual(len(self.c.candidate_visuals(self.pid, candidate['id'])), 1)
        with self.assertRaises(WorkflowError):
            self.c.add_candidate_visual(operator_id=self.c.operator_id, project_id=self.pid, candidate_id=candidate['id'], request={**body, 'requestId': 'capture-request-654321'})

    def test_http_origin_and_project_scope(self):
        import json
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        server = make_server(self.c, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(origin + f'/api/projects/{self.pid}/concept-references', data=json.dumps(self.request()).encode(), headers={'Content-Type': 'application/json'}))
            self.assertEqual(error.exception.code, 403)
            with urlopen(origin + f'/api/projects/{self.pid}/concept-references') as response:
                self.assertEqual(json.load(response), {'requests': []})
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()

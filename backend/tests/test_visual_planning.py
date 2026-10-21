"""Submitted visual context, immutable provenance and atomic revision contracts."""
import copy
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from backend.coordinator import WorkflowError
from backend.server import make_server
from backend.tests import test_concept_references as helpers
from backend.visual_planning import selected_snapshot


class VisualPlanningTests(unittest.TestCase):
    setUp = helpers.ConceptReferenceTests.setUp
    tearDown = helpers.ConceptReferenceTests.tearDown
    envelope = helpers.ConceptReferenceTests.envelope
    command = helpers.ConceptReferenceTests.command
    runner = helpers.ConceptReferenceTests.runner
    report = helpers.ConceptReferenceTests.report
    ready = helpers.ConceptReferenceTests.ready
    planning = helpers.ConceptReferenceTests.planning
    image = helpers.ConceptReferenceTests.image
    generate = helpers.ConceptReferenceTests.generate
    intent = helpers.ConceptReferenceTests.intent

    def context(self, proposal):
        return self.c.visual_planning_context(self.pid, proposal['id'])

    def request(self, context, rid='visual-plan-request-001', **overrides):
        return {**{'requestId': rid, 'sourceText': '', 'interpretation': '核对暖光构图',
                   'size': '1536x1024', 'quality': 'low', 'source': context['source'],
                   'materialIds': [m['id'] for m in context['materials']]}, **overrides}

    def generate_request(self, request):
        with patch('tools.imagegen_cli.generate_images', self.generate):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=request)
            self.c._threads['concept:' + record['id']].join(10)
        return next(r for r in self.c.concept_generations(self.pid) if r['id'] == request['requestId'])

    def test_canonical_materials_and_last_twelve_submitted_turns(self):
        p = self.ready()
        with self.c.transaction():
            p['discussion'] = [{'role': 'user', 'text': f'submitted-{i}', 'at': str(i)} for i in range(15)]
            p['discussion'].append({'role': 'planner', 'summary': '可核对的反馈', 'revision': 1, 'at': 'feedback-time'})
            self.c._put('proposal', p)
        before = copy.deepcopy(self.c._get('proposal', p['id']))
        context = self.context(p)
        turns = [m for m in context['materials'] if m['id'].startswith('discussion:')]
        self.assertEqual(len(turns), 12)
        self.assertEqual(turns[0]['id'], 'discussion:4')
        self.assertEqual(context['source']['feedbackId'], 'discussion:15')
        self.assertIn('原始想法', next(m['text'] for m in context['materials'] if m['id'] == 'original'))
        self.assertEqual(before, self.c._get('proposal', p['id']))
        self.assertFalse(self.c.concept_generations(self.pid))

    def test_immutable_snapshot_replay_after_revision_change_and_no_extra_session(self):
        p = self.ready(); context = self.context(p); request = self.request(context)
        attempts = len(self.c._all('attempt'))
        record = self.generate_request(request)
        expected_snapshot, expected_prompt = selected_snapshot(context, request['materialIds'], request['interpretation'])
        self.assertEqual(record['sourceSnapshot'], expected_snapshot)
        self.assertEqual(record['prompt'], expected_prompt)
        self.assertEqual(record['asset']['generation']['provenance']['source'], context['source'])
        self.assertEqual(len(self.c._all('attempt')), attempts)
        revised = self.command('proposal.revise', {'proposalId': p['id'], 'supplement': '新讨论'},
            expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})['result']['proposal']
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('No replay')):
            replay = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=request)
            self.assertEqual(record, replay)
            with self.assertRaises(WorkflowError) as error:
                self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid,
                    request={**request, 'requestId': 'visual-plan-stale-002'})
        self.assertEqual(error.exception.code, 'REFERENCE_SOURCE_STALE')
        self.assertEqual(self.context(revised)['feedbackRevision'], 1)
        self.assertEqual(self.calls, 1)

    def test_same_revision_feedback_change_rejects_preview(self):
        p = self.ready(); request = self.request(self.context(p))
        with self.c.transaction():
            p['discussion'].append({'role': 'planner', 'revision': 1, 'summary': '同修订新反馈', 'at': 'new-time'})
            self.c._put('proposal', p)
        with self.assertRaises(WorkflowError) as error:
            self.generate_request(request)
        self.assertEqual(error.exception.code, 'REFERENCE_SOURCE_STALE')
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.c.concept_generations(self.pid), [])

    def test_persisted_event_version_detects_content_changes_without_clock_change(self):
        p = self.ready(); request = self.request(self.context(p))
        with self.c.transaction():
            p['document']['summary'] = '仅修改内容，保留原更新时间'
            self.c._put('proposal', p)
        with self.assertRaises(WorkflowError) as error:
            self.generate_request(request)
        self.assertEqual(error.exception.code, 'REFERENCE_SOURCE_STALE')
        self.assertEqual(self.calls, 0)

    def test_material_scope_and_overflow_are_explicit_and_do_not_call_provider(self):
        p = self.ready()
        with self.c.transaction():
            p['document']['summary'] = '长' * 34000
            self.c._put('proposal', p)
        context = self.context(p)
        with self.assertRaises(WorkflowError) as error:
            self.generate_request(self.request(context))
        self.assertEqual(error.exception.code, 'REFERENCE_PROMPT_LIMIT')
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.c.concept_generations(self.pid), [])
        record = self.generate_request(self.request(context, materialIds=['original']))
        self.assertNotIn('长' * 100, record['prompt'])
        self.assertEqual([m['id'] for m in record['sourceSnapshot']['materials']], ['original'])

    def test_cross_project_unsubmitted_text_and_material_injection_rejected(self):
        p = self.ready(); context = self.context(p)
        other = self.command('project.create', {'name': 'Other'}, pid=None)['result']['project']['id']
        with self.assertRaises(WorkflowError):
            self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=other, request=self.request(context))
        for overrides in ({'sourceText': '未提交草稿'}, {'materialIds': ['workbench-draft']}, {'materialIds': ['original', 'original']}, {'materialIds': []}):
            with self.assertRaises(WorkflowError):
                self.generate_request(self.request(context, **overrides))
        self.assertEqual(self.calls, 0)

    def test_pending_request_shared_across_initial_and_proposal_generation(self):
        p = self.ready(); entered = threading.Event(); release = threading.Event()

        def delayed(*args, **kwargs):
            entered.set(); release.wait(5); return self.generate(*args, **kwargs)

        with patch('tools.imagegen_cli.generate_images', delayed):
            record = self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=self.request(self.context(p)))
            self.assertTrue(entered.wait(3))
            try:
                with self.assertRaises(WorkflowError) as error:
                    self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=helpers.ConceptReferenceTests.request(self, 'initial-reference-blocked'))
                self.assertEqual(error.exception.code, 'REFERENCE_PENDING')
            finally:
                release.set(); self.c._threads['concept:' + record['id']].join(10)
        self.assertEqual(self.calls, 1)

    def test_clarification_references_atomic_required_answers_and_ready_reference_only(self):
        p = self.ready(); generated = self.generate_request(self.request(self.context(p))); asset = generated['asset']
        with self.c.transaction():
            p.update(status='NEEDS_CLARIFICATION', questions=[{'id': 'direction', 'prompt': '朝向？', 'type': 'text', 'required': True}])
            self.c._put('proposal', p)
        payload = {'proposalId': p['id'], 'assetRefs': [asset['id']], 'visualReferences': [self.intent(asset['id'])]}
        expected = {'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0}
        before = self.c._get('proposal', p['id'])
        denied = self.command('proposal.revise', payload, expected=copy.deepcopy(expected))
        self.assertEqual(denied['error']['code'], 'ANSWER_REQUIRED')
        self.assertEqual(before, self.c._get('proposal', p['id']))
        payload['answers'] = [{'questionId': 'direction', 'text': '朝向灯光'}]
        revised = self.command('proposal.revise', payload, expected=expected)['result']['proposal']
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(revised['discussion'][-1]['answers'], payload['answers'])
        self.assertEqual(revised['visualReferences'], payload['visualReferences'])

    def test_frozen_packet_unchanged_by_generation_and_later_reference_revision(self):
        p = self.ready(); ref = self.c.project_view(self.pid)['proposal']['reviewedPlanRef']
        packet = self.command('proposal.freeze', {'proposalId': p['id'], 'reviewedPlanRef': ref},
            expected={'proposalRevision': 1, 'publicationRevision': 0})['result']['packet']
        packet = self.c._get('packet', packet['id'])
        frozen = self.c._get('proposal', p['id'])
        generated = self.generate_request(self.request(self.context(frozen)))
        self.assertEqual(self.c._get('packet', packet['id']), packet)
        asset = generated['asset']
        revised = self.command('proposal.revise', {'proposalId': p['id'], 'assetRefs': [asset['id']], 'visualReferences': [self.intent(asset['id'])]},
            expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})['result']['proposal']
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(self.c._get('packet', packet['id']), packet)

    def test_http_context_project_scope_and_archived_read_only(self):
        p = self.ready(); context = self.context(p)
        self.command('project.settings.update', {'archived': True})
        self.assertEqual(self.context(p), context)
        with self.assertRaises(WorkflowError) as error:
            self.generate_request(self.request(context))
        self.assertEqual(error.exception.code, 'PROJECT_ARCHIVED')
        server = make_server(self.c, port=0); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(origin + f'/api/projects/{self.pid}/proposals/{p["id"]}/visual-context') as response:
                self.assertEqual(json.load(response), context)
            other = self.command('project.create', {'name': 'Other'}, pid=None)['result']['project']['id']
            with self.assertRaises(HTTPError) as error:
                urlopen(origin + f'/api/projects/{other}/proposals/{p["id"]}/visual-context')
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()

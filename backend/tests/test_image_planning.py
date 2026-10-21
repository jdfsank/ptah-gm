"""Image planning and serial batches through persisted coordinator boundaries."""
import copy
import json
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.coordinator import Coordinator, WorkflowError
from backend.object_protocol import validate_execution_request, validate_execution_report
from backend.server import REPO_ROOT
from backend.tests import test_concept_references as helpers
from backend.visual_planning import image_snapshot, validate_image_plan


class ImagePlanningTests(unittest.TestCase):
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

    def plan(self, count=2):
        images = [{"id": f"image-{i}", "title": f"概念 {i}", "quickDescription": f"检查第 {i} 个概念的轮廓与构图", "purpose": "检查独立视觉目的",
            "concepts": [f"概念{i}"], "materialIds": ["original"], "subject": f"独立主体{i}", "composition": "清晰的中心构图",
            "style": "赛博朋克插画", "preserve": "保持约定主题", "unknown": "玩法与具体数值未经检查"} for i in range(count)]
        return {"sharedStyle": "青紫霓虹与暗金属", "images": images,
                "coverage": [{"concept": i["concepts"][0], "imageIds": [i["id"]], "reason": i["purpose"]} for i in images]}

    def setup_plan(self, count=2):
        p = self.ready(); context = self.c.visual_planning_context(self.pid, p['id'])
        with self.c.transaction():
            self.c._store_inline_visual_plan(p, self.plan(count))
        stored = self.c.visual_plans(self.pid)[-1]
        return p, context, stored

    def batch_body(self, context, plan, rid='batch-request-number-001'):
        return {"requestId": rid, "source": context['source'], "visualPlanId": plan['id'],
                "sharedStyle": plan['result']['sharedStyle'], "images": copy.deepcopy(plan['result']['images'])}

    def create_batch(self, body, pid=None):
        return self.c.create_reference_batch(operator_id=self.c.operator_id, project_id=pid or self.pid, request=body)

    def join(self):
        worker = self.c._threads.get('concept-scheduler')
        if worker: worker.join(10)
        self.assertFalse(worker and worker.is_alive(), 'bounded serial worker terminated')

    def control(self, batch, action):
        return self.c.control_reference_batch(operator_id=self.c.operator_id, project_id=self.pid, batch_id=batch['id'], action=action)

    def test_fragment_scope_deduplicates_feedback_and_preserves_exact_text(self):
        p, context, plan = self.setup_plan()
        fragments = context['imageMaterials']
        self.assertFalse(any(m['id'] in {'plan', 'feedback'} for m in fragments))
        self.assertEqual(len({m['id'] for m in fragments}), len(fragments))
        image = plan['result']['images'][0]
        snapshot, prompt = image_snapshot(context, image, plan['result']['sharedStyle'])
        self.assertEqual(snapshot['materials'], [next(m for m in fragments if m['id'] == 'original')])
        self.assertNotIn('sourceBindings', prompt)
        self.assertIn('Planned use (not observed verification)', prompt)
        self.assertIn('独立主体0', prompt)
        self.assertNotIn('独立主体1', prompt)

    def test_visual_task_is_read_only_durable_and_does_not_modify_proposal(self):
        p = self.ready(); before = copy.deepcopy(p); context = self.c.visual_planning_context(self.pid, p['id'])
        body = {'requestId': 'visual-planning-request-001', 'source': context['source'], 'preferencesRevision': 0}
        record = self.c.create_visual_plan(operator_id=self.c.operator_id, project_id=self.pid, request=body)
        self.assertEqual(self.c._get('proposal', p['id']), before)
        self.assertEqual(self.c.create_visual_plan(operator_id=self.c.operator_id, project_id=self.pid, request=body)['id'], record['id'])
        request = self.c.claim_runner({'runnerId': 'agent-test', 'storeId': self.c.store_id, 'commandId': 'visual-claim'})['request']
        validate_execution_request(request)
        self.assertEqual(request['taskKind'], 'visual-plan'); self.assertFalse(request['scope']['allowProjectExecution'])
        material = self.c.runner_input('agent-test', request['attemptId'])
        self.assertEqual(material['packet']['allowedFiles'], [])
        self.assertIn('imageMaterials', material['packet'])
        self.report(request['attemptId'], 'started', {'nativeIdentity': {'threadId': 'visual-thread', 'turnId': 'visual-turn', 'processId': None, 'processGroupId': None, 'processStartTime': None},
            'startedAt': datetime.now(timezone.utc).isoformat(), 'requestedProfile': None, 'reportedProfile': None, 'threadStartReported': None, 'turnStartAcknowledged': None, 'actualProfile': None})
        ack = self.report(request['attemptId'], 'completed', {'stopped': True, 'result': {'response': json.dumps(self.plan(), ensure_ascii=False)}})
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertEqual(self.c.visual_plans(self.pid)[-1]['status'], 'READY')
        self.assertEqual(self.c._get('proposal', p['id']), before)
        self.assertEqual(self.c.visual_planning_context(self.pid, p['id'])['source'], context['source'])

    def test_inline_invalid_visual_plan_retains_valid_ready_feedback(self):
        from backend.tests.test_generic_workflow import plan_result
        p = self.ready(); before = copy.deepcopy(p)
        with self.c.transaction():
            self.c._store_inline_visual_plan(p, {'bad': 'shape'})
        self.assertEqual(self.c._get('proposal', p['id']), before)
        self.assertEqual(self.c.visual_plans(self.pid)[-1]['status'], 'FAILED')
        from backend.object_protocol import parse_planner_response
        result = parse_planner_response({**plan_result(), 'visualPlan': {'bad': 'shape'}})
        self.assertEqual(result['status'], 'READY')

    def test_null_visual_extension_reports_error_without_losing_text_plan(self):
        from backend.tests.test_generic_workflow import plan_result
        response = {**plan_result(), 'visualPlan': None}
        with patch('backend.tests.test_generic_workflow.plan_result', return_value=response):
            proposal = self.ready()
        self.assertEqual(proposal['status'], 'READY')
        self.assertEqual(proposal['summary'], response['summary'])
        records = self.c.visual_plans(self.pid)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'FAILED')
        self.assertIn('validationError', records[0])

    def test_serial_batch_idempotency_provenance_and_check_only_results(self):
        p, context, plan = self.setup_plan(); before = copy.deepcopy(p)
        body = self.batch_body(context, plan)
        with patch('tools.imagegen_cli.generate_images', self.generate):
            batch = self.create_batch(body); self.join()
            replay = self.create_batch(body)
        self.assertEqual(replay['id'], batch['id']); self.assertEqual(replay['status'], 'COMPLETED')
        self.assertEqual(self.calls, 2)
        records = self.c.concept_generations(self.pid)
        self.assertEqual(len(records), 2)
        for i, item in enumerate(replay['items']):
            record = next(r for r in records if r['id'] == item['requestId'])
            self.assertEqual(record['sourceSnapshot']['imagePlan']['id'], f'image-{i}')
            self.assertEqual(record['sourceSnapshot']['source'], context['source'])
            self.assertEqual(record['prompt'], item['prompt'])
            self.assertEqual(record['asset']['generation']['provenance']['imagePlan']['quickDescription'], item['imagePlan']['quickDescription'])
            with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('no replay')):
                self.assertEqual(self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=record['request']), record)
        self.assertEqual(self.c._get('proposal', p['id']), before)

    def test_global_worker_has_one_active_image_across_projects_and_legacy(self):
        _, context, plan = self.setup_plan(); other = self.command('project.create', {'name': 'other'}, pid=None)['result']['project']['id']
        entered = threading.Event(); release = threading.Event(); active = 0; maximum = 0
        def generate(jobs, **kwargs):
            nonlocal active, maximum
            active += 1; maximum = max(maximum, active); entered.set(); release.wait(5)
            result = self.generate(jobs, **kwargs); active -= 1; return result
        with patch('tools.imagegen_cli.generate_images', generate):
            self.create_batch(self.batch_body(context, plan)); self.assertTrue(entered.wait(2))
            legacy = helpers.ConceptReferenceTests.request(self, 'legacy-request-number-002')
            self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=other, request=legacy)
            self.assertEqual(active, 1)
            release.set(); self.join()
        self.assertEqual(maximum, 1); self.assertEqual(self.calls, 3)

    def test_source_change_between_images_pauses_without_calling_next(self):
        p, context, plan = self.setup_plan()
        def generate(jobs, **kwargs):
            result = self.generate(jobs, **kwargs)
            with self.c.transaction():
                current = self.c._get('proposal', p['id']); current['discussion'].append({'role': 'planner', 'summary': '同修订新增反馈', 'revision': p['revision']}); self.c._put('proposal', current)
            return result
        with patch('tools.imagegen_cli.generate_images', generate):
            batch = self.create_batch(self.batch_body(context, plan)); self.join()
        saved = self.c.reference_batches(self.pid)[0]
        self.assertEqual(saved['status'], 'PAUSED'); self.assertEqual(self.calls, 1)
        self.assertEqual(saved['items'][1]['status'], 'BLOCKED')
        with self.assertRaises(WorkflowError): self.control(batch, 'resume')
        self.control(batch, 'cancel')

    def test_failure_pauses_and_resume_never_reposts_uncertain(self):
        _, context, plan = self.setup_plan()
        with patch('tools.imagegen_cli.generate_images', side_effect=TimeoutError('private failure')):
            batch = self.create_batch(self.batch_body(context, plan)); self.join()
        saved = self.c.reference_batches(self.pid)[0]
        self.assertEqual(saved['items'][0]['status'], 'UNCERTAIN')
        self.assertEqual(saved['items'][1]['status'], 'WAITING')
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('no retry')):
            with self.assertRaises(WorkflowError): self.control(batch, 'resume')
            first = saved['items'][0]
            output = self.c.state_root/'concept-generations'/first['requestId']; output.mkdir(parents=True)
            (output/'concept.png').write_bytes(self.image())
            self.c.reconcile_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request_id=first['requestId'])
        with patch('tools.imagegen_cli.generate_images', self.generate):
            self.control(batch, 'resume'); self.join()
        self.assertEqual(self.calls, 1); self.assertEqual(self.c.reference_batches(self.pid)[0]['status'], 'COMPLETED')

    def test_pause_cancel_and_restart_keep_waiting_items_unexecuted(self):
        _, context, plan = self.setup_plan()
        with patch.object(self.c, '_kick_concept_scheduler'):
            batch = self.create_batch(self.batch_body(context, plan))
        self.control(batch, 'pause')
        self.c.close(); self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=False)
        self.assertEqual(self.c.reference_batches(self.pid)[0]['status'], 'PAUSED')
        self.assertFalse(self.c.concept_generations(self.pid))
        self.control(batch, 'cancel')
        with patch('tools.imagegen_cli.generate_images', side_effect=AssertionError('cancelled')):
            result = self.control(batch, 'resume')
        self.assertEqual(result['status'], 'CANCELLED')

    def test_cross_project_reused_ids_and_injected_fragments_rejected(self):
        _, context, plan = self.setup_plan(); other = self.command('project.create', {'name': 'other'}, pid=None)['result']['project']['id']
        body = self.batch_body(context, plan)
        with self.assertRaises(WorkflowError): self.create_batch(body, other)
        bad = copy.deepcopy(body); bad['images'][0]['materialIds'] = ['workbench-unsent']
        with self.assertRaises(WorkflowError): self.create_batch(bad)
        with patch.object(self.c, '_kick_concept_scheduler'):
            self.create_batch(body)
        changed = copy.deepcopy(body); changed['images'][0]['subject'] = 'changed'
        with self.assertRaises(WorkflowError): self.create_batch(changed)
        self.assertEqual(len(self.c.reference_batches(self.pid)), 1)

    def test_per_image_limit_reports_title_and_creates_no_batch_or_process(self):
        p, context, plan = self.setup_plan()
        with self.c.transaction():
            p['text'] = '长' * 33000; self.c._put('proposal', p)
        context = self.c.visual_planning_context(self.pid, p['id'])
        body = self.batch_body(context, plan); body['visualPlanId'] = None
        with self.assertRaises(WorkflowError) as error:
            self.create_batch(body)
        self.assertIn('概念 0', str(error.exception)); self.assertEqual(error.exception.code, 'REFERENCE_PROMPT_LIMIT')
        self.assertFalse(self.c.reference_batches(self.pid)); self.assertFalse(self.c.concept_generations(self.pid))

    def test_capacity_and_pending_block_before_process_creation(self):
        _, context, plan = self.setup_plan()
        with patch.object(self.c, '_kick_concept_scheduler'):
            batch = self.create_batch(self.batch_body(context, plan))
        with self.assertRaises(WorkflowError) as error: self.create_batch(self.batch_body(context, plan, 'batch-another-number-002'))
        self.assertEqual(error.exception.code, 'REFERENCE_PENDING')
        with self.assertRaises(WorkflowError): self.c.generate_concept_reference(operator_id=self.c.operator_id, project_id=self.pid, request=helpers.ConceptReferenceTests.request(self))
        for i in range(7):
            with self.c.transaction(): self.c._put('reference-batch', {**batch, 'id': f'capacity-batch-{i}', 'projectId': f'capacity-project-{i}'})
        with self.assertRaises(WorkflowError) as error: self.c._check_image_capacity()
        self.assertEqual(error.exception.status, 429)
        self.assertFalse(self.c._threads)


if __name__ == '__main__': unittest.main()

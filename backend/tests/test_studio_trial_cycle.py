"""C3 regression contracts in disposable stores; fixtures are not user acceptance."""
import copy
import json
import unittest

from backend.object_protocol import (ObjectProtocolError, apply_field_changes,
                                     parse_planner_response, planner_instructions)
from backend.tests import test_studio_delivery as delivery
from backend.tests.test_generic_workflow import plan_result
from backend.workbench_results import iteration_results
from runners.native_diagnostics import native_diagnostic_summary, public_native_failure


class StudioTrialCycleTests(unittest.TestCase):
    setUp = delivery.StudioDeliveryTests.setUp
    tearDown = delivery.StudioDeliveryTests.tearDown
    envelope = delivery.StudioDeliveryTests.envelope
    command = delivery.StudioDeliveryTests.command
    runner = delivery.StudioDeliveryTests.runner
    planning = delivery.StudioDeliveryTests.planning
    report = delivery.StudioDeliveryTests.report
    ready = delivery.StudioDeliveryTests.ready
    started = delivery.StudioDeliveryTests.started
    frozen = delivery.StudioDeliveryTests.frozen
    produced = delivery.StudioDeliveryTests.produced
    candidate = delivery.StudioDeliveryTests.candidate
    accept = delivery.StudioDeliveryTests.accept

    def test_field_only_v1_iteration_freezes_and_prepares_exact_updated_input(self):
        job, ref, _, ack = self.candidate()
        self.assertEqual(ack['disposition'], 'recorded')
        accepted = self.accept(job)
        self.assertEqual(accepted['status'], 'accepted', accepted)
        submitted = self.command('iteration.submit', {'text': '', 'assetRefs': [], 'visualReferences': [],
            'targetObjectIds': ['player'], 'fields': [{'objectId': 'player', 'fieldId': 'speed', 'value': 300}],
            'feedback': [], 'operations': []}, expected={'publicationRevision': 1, 'preferencesRevision': 0,
                'sourceCommit': ref['sourceCommit']})
        self.assertEqual(submitted['status'], 'accepted', submitted)
        proposal = submitted['result']['proposal']
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-parameter-plan'})
        self.started(proposal['attemptId'])
        document = copy.deepcopy(proposal['currentDocument'])
        document['objects'][1]['fields'][0]['value'] = 300
        response = {**plan_result(document), 'schemaVersion': 'studio.planner-result.v1', 'feedbackDecisions': []}
        self.assertEqual(self.report(proposal['attemptId'], 'completed', {'stopped': True,
            'result': {'response': response}})['disposition'], 'recorded')
        proposal = self.c._get('proposal', proposal['id'])
        frozen = self.command('proposal.freeze', {'proposalId': proposal['id'],
            'reviewedPlanRef': self.c.project_view(self.pid)['proposal']['reviewedPlanRef']},
            expected={'proposalRevision': proposal['revision'], 'publicationRevision': 1})
        self.assertEqual(frozen['status'], 'accepted', frozen)
        packet = frozen['result']['packet']
        self.assertEqual(packet['document']['objects'][1]['fields'][0]['value'], 300)
        started = self.command('production.start', {'packetId': packet['id']},
            expected={'publicationRevision': 1, 'preferencesRevision': 0})
        self.assertEqual(started['status'], 'accepted', started)
        attempt = self.c._get('attempt', started['result']['job']['attemptId'])
        self.assertEqual(attempt['status'], 'QUEUED', attempt.get('preparationError'))
        prepared = attempt['prepared']['inputArtifactRef']
        root = self.state/'artifacts'/prepared['artifactId']/'repository'
        self.assertEqual(json.loads((root/'design/game.json').read_text())['objects'][1]['fields'][0]['value'], 300)
        invalid = {**proposal['changeRequest'], 'schemaVersion': 'studio.change-request.v999'}
        with self.assertRaises(ObjectProtocolError):
            apply_field_changes(document, invalid)

    def test_native_failure_report_exposes_only_classified_observations(self):
        packet = self.frozen()
        receipt = self.command('production.start', {'packetId': packet['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        job = receipt['result']['job']
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-native-failure'})
        self.started(job['attemptId'])
        private = 'PRIVATE_PROVIDER_CREDENTIAL_RESPONSE'
        summary = native_diagnostic_summary({'status': 'uncertain', 'response': private, 'diagnostics': {
            'elapsedSeconds': 16.662, 'childTerminationConfirmed': True, 'stderr': [private],
            'providerBridge': {'failures': [{'kind': 'network_error', 'responseStarted': True, 'message': private}]}}})
        payload = {'stopped': True, 'stopReason': 'native_error', 'diagnosticRef': 'local:native-diagnostics/'+job['attemptId'],
                   'nativeFailure': public_native_failure(summary)}
        self.assertEqual(self.report(job['attemptId'], 'failed', payload)['disposition'], 'recorded')
        failure = self.c.project_view(self.pid)['job']['productionFailure']
        self.assertIn('原生响应连接中断', failure['message'])
        self.assertTrue(failure['terminationConfirmed'])
        self.assertEqual(failure['elapsedSeconds'], 16.662)
        self.assertTrue(failure['connectionInterrupted'])
        self.assertNotIn(private, json.dumps(failure))
        self.assertNotIn('candidate', self.c._get('job', job['id']))


class InitialBuildAndExperienceTests(unittest.TestCase):
    def test_initial_revised_plan_requires_full_task_coverage_but_iteration_can_be_incremental(self):
        response = plan_result()
        response['document']['requirements'].append({'id': 'reset', 'text': '按R重开', 'objectIds': ['player'], 'verification': 'manual'})
        with self.assertRaisesRegex(ObjectProtocolError, 'reset'):
            parse_planner_response(response, previous_document=response['document'], initial_build=True)
        self.assertEqual(parse_planner_response(response, initial_build=False)['status'], 'READY')
        response['tasks'].append({'id': 'reset-player', 'description': '实现R重开', 'objectIds': ['player'], 'requirementIds': ['reset']})
        self.assertEqual(parse_planner_response(response, initial_build=True)['status'], 'READY')
        instruction = planner_instructions(initial_build=True)
        self.assertIn('no implemented source baseline', instruction)
        self.assertIn('concrete scene instances', instruction)
        self.assertIn('never fact/runtime', instruction)
        self.assertNotIn('INITIAL BUILD', planner_instructions(initial_build=False))

    def test_historical_experience_uses_exact_job_even_when_feedback_later_changes(self):
        feedback = {'feedbackId': 'note', 'objectId': 'player', 'message': '更清楚', 'category': 'general'}
        proposal = {'id': 'p', 'revision': 1, 'changeRequest': {'feedback': [feedback]}}
        packet = {'id': 'packet', 'proposalId': 'p', 'proposalRevision': 1, 'changeRequest': proposal['changeRequest']}
        decision = {'feedbackId': 'note', 'status': 'resolved', 'reason': '原候选试玩理由\n逐字保留'}
        job = {'id': 'job', 'packetId': 'packet', 'status': 'PUBLISHED', 'candidate': {'id': 'candidate'}, 'experienceDecisions': [decision]}
        later = {**feedback, 'proposalId': 'p', 'candidateId': 'another-candidate', 'experienceDecision': {
            'feedbackId': 'note', 'status': 'needs_followup', 'reason': '另一候选理由'}}
        item = iteration_results([proposal], [packet], [job], [later])[0]
        self.assertEqual(item['experienceDecision'], decision)
        self.assertEqual(item['userAcceptance'], 'resolved')
        job.pop('experienceDecisions')
        item = iteration_results([proposal], [packet], [job], [later])[0]
        self.assertIsNone(item['experienceDecision'])
        self.assertEqual(item['userAcceptance'], 'NOT_PERFORMED')


if __name__ == '__main__':
    unittest.main()

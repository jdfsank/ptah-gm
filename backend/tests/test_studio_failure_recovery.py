"""C5 failure recovery contracts in disposable stores; no model or acceptance."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from backend.tests import test_studio_delivery as delivery
from runners.project import verification_checks


class StudioFailureRecoveryTests(unittest.TestCase):
    for _method in ('setUp', 'tearDown', 'envelope', 'command', 'runner', 'planning',
                    'report', 'ready', 'started', 'frozen', 'produced'):
        locals()[_method] = getattr(delivery.StudioDeliveryTests, _method)

    def failed_verification(self, *, unchanged=True):
        job, ref, repo, ack = self.produced()
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'project-test', 'commandId': 'claim-failed-verify'})
        self.started(job['verificationAttemptId'])
        checks = [{'id': 'project.document', 'status': 'PASS', 'summary': 'valid'},
            {'id': 'godot.main_scene_smoke', 'status': 'FAIL', 'summary': 'invalid metadata body-size'},
            {'id': 'user.acceptance', 'status': 'SKIPPED', 'summary': 'not performed'}]
        ack = self.report(job['verificationAttemptId'], 'completed', {'stopped': True,
            'artifactRef': ref, 'sourceCommit': ref['sourceCommit'], 'result': {'status': 'FAIL',
                'sourceCommit': ref['sourceCommit'], 'sourceUnchanged': unchanged,
                'checks': checks, 'evidenceRef': 'fixture-evidence'}})
        return self.c._get('job', job['id']), ref, repo, ack

    def test_verification_fail_is_completed_execution_without_candidate_or_preview(self):
        job, ref, repo, ack = self.failed_verification()
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertEqual(self.c._get('attempt', job['verificationAttemptId'])['status'], 'COMPLETED')
        self.assertEqual(job['status'], 'FAILED')
        self.assertEqual([c['status'] for c in job['verification']['checks']], ['PASS', 'FAIL', 'SKIPPED'])
        self.assertNotIn('candidate', job)
        view = self.c.project_view(self.pid)
        self.assertNotIn('preview.start', view['allowedActions'])
        self.assertEqual(view['repairContext']['sourceCommit'], ref['sourceCommit'])
        self.assertEqual(view['repairContext']['repairReason'], 'VERIFICATION_FAILED')
        self.assertIsNone(view['repairContext']['candidateId'])
        self.assertFalse(view['repairContext']['playable'])
        self.assertIsNone(self.c._get('project', self.pid)['snapshotId'])

    def test_failed_source_repair_binds_source_and_carries_diagnostics_to_static_planning(self):
        job, ref, repo, ack = self.failed_verification()
        payload = {'text': '修复验证失败', 'assetRefs': [], 'feedback': [], 'fields': [], 'targetObjectIds': []}
        stale = self.command('iteration.submit', payload,
            expected={'publicationRevision': 0, 'preferencesRevision': 0, 'sourceCommit': None})
        self.assertEqual(stale['error']['code'], 'STALE_SOURCE')
        receipt = self.command('iteration.submit', payload,
            expected={'publicationRevision': 0, 'preferencesRevision': 0, 'sourceCommit': ref['sourceCommit']})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        p = receipt['result']['proposal']
        self.assertEqual(p['repairBase'], {'jobId': job['id'], 'candidateId': None, 'sourceCommit': ref['sourceCommit']})
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-repair-plan'})
        material = self.c.runner_input('agent-test', p['attemptId'])['packet']
        self.assertEqual(material['repairDiagnostics']['verificationAttemptId'], job['verificationAttemptId'])
        self.assertEqual(material['approvedUserDiscussion'][0]['text'], 'a bounded game')
        self.assertTrue(material['inspection']['sourceAvailable'])
        self.assertEqual(material['inspection']['sourceCommit'], ref['sourceCommit'])
        self.assertEqual(self.c._get('attempt', p['attemptId'])['scope']['mode'], 'inspection_only')
        self.assertFalse(self.c._get('attempt', p['attemptId'])['scope']['allowProjectExecution'])
        self.assertIsNone(self.c._get('project', self.pid)['snapshotId'])

        # Readiness is still required by the unchanged trusted runner when
        # this newly approved repair is actually executed.
        from backend.tests.test_generic_workflow import plan_result
        self.started(p['attemptId'])
        response = {**plan_result(p['currentDocument']), 'schemaVersion': 'studio.planner-result.v1', 'feedbackDecisions': []}
        result = self.report(p['attemptId'], 'completed', {'stopped': True, 'result': {'response': response}})
        self.assertEqual(result['disposition'], 'recorded', result)
        current = self.c._get('proposal', p['id'])
        frozen = self.command('proposal.freeze', {'proposalId': p['id'],
            'reviewedPlanRef': self.c.project_view(self.pid)['proposal']['reviewedPlanRef']},
            expected={'proposalRevision': current['revision'], 'publicationRevision': 0})
        self.assertEqual(frozen['status'], 'accepted', frozen)
        script = repo / 'scripts/player.gd'
        script.write_text('extends Node2D\n# drift after approval\n')
        started = self.command('production.start', {'packetId': frozen['result']['packet']['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(started['error']['code'], 'STALE_REPAIR')
        self.assertEqual(len(self.c._all('job')), 1, 'stale repair never creates another production job')

    def test_failed_verification_projection_matches_published_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema unavailable')
        self.failed_verification()
        schema = json.loads((delivery.REPO_ROOT / 'contracts/studio/project-view.v1.schema.json').read_text())
        Draft202012Validator(schema).validate(self.c.project_view(self.pid))

    def test_source_drift_and_wrong_verification_identity_cannot_be_repair_base(self):
        job, ref, repo, ack = self.failed_verification(unchanged=False)
        self.assertEqual(ack['disposition'], 'rejected')
        self.assertIsNone(self.c.repair_context(self.pid))

    def test_retained_artifact_drift_or_publication_change_hides_failed_repair(self):
        job, ref, repo, ack = self.failed_verification()
        self.assertIsNotNone(self.c.repair_context(self.pid))
        script = repo / 'scripts/player.gd'
        original = script.read_bytes()
        script.write_text('extends Node2D\n# unsealed drift\n')
        self.assertIsNone(self.c.repair_context(self.pid))
        script.write_bytes(original)
        self.assertIsNotNone(self.c.repair_context(self.pid))
        project = self.c._get('project', self.pid)
        project['publicationRevision'] += 1
        self.c._put('project', project)
        self.assertIsNone(self.c.repair_context(self.pid))

    def test_planning_timeout_keeps_retryable_failure_but_user_cancel_stays_cancelled(self):
        for reason, expected in [('time_limit', 'FAILED'), ('soft_budget', 'FAILED'), ('cancelled', 'CANCELLED')]:
            with self.subTest(reason=reason):
                runner = next((r for r in self.c._all('runner') if r['id'] == 'agent-test'), {})
                ready_at = (runner.get('sessionRetryGate') or {}).get('notBefore', 0)
                with mock.patch('backend.studio_protocol.time.time',
                                return_value=max(datetime.now(timezone.utc).timestamp(), ready_at + 1)):
                    p = self.planning()
                    self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-'+reason})
                self.started(p['attemptId'])
                self.report(p['attemptId'], 'stopped', {'stopped': True, 'stopReason': reason})
                projected = self.c.project_view(self.pid)['proposal']
                self.assertEqual(projected['status'], expected)
                if expected == 'FAILED':
                    self.assertTrue(projected['planningFailure']['retryable'])
                    self.assertTrue(projected['planningFailure']['terminationConfirmed'])
                    self.assertEqual(self.c.project_view(self.pid)['step'], 'planning_failed')

    def test_maker_timeout_is_not_reported_as_user_cancellation(self):
        attempt = {'id': 'timed', 'stopReason': 'time_limit', 'nativeIdentity': {'threadId': 't'}}
        failure = self.c._producer_failure(attempt)
        self.assertEqual(failure['code'], 'PRODUCTION_TIMEOUT')
        self.assertEqual(failure['stopReason'], 'time_limit')
        self.assertIn('时间上限', failure['message'])


class VerificationProjectionTests(unittest.TestCase):
    def test_actual_checks_keep_individual_outcomes_and_bounded_errors(self):
        report = {'status': 'FAIL', 'checks': ['legacy coarse label'], 'requirements': [
            {'id': 'document', 'status': 'PASS', 'evidence': 'valid'},
            {'id': 'smoke', 'status': 'FAIL', 'evidence': 'failed'},
            {'id': 'human', 'status': 'NOT_TESTED', 'evidence': 'human review'},
            {'id': 'blocked', 'status': 'BLOCKED', 'evidence': 'import failed'}],
            'commands': [{'name': 'backend_runtime_smoke', 'argv': ['PRIVATE_SANDBOX_ARGV'],
                'stdout': 'PRIVATE_FULL_LOG\nERROR: Invalid metadata identifier body-size.\n',
                'stderr': 'ERROR: ' + 'x' * 2000}], 'diagnostics': [{'message': 'PRIVATE_DIAGNOSTICS'}]}
        original = copy.deepcopy(report)
        checks = verification_checks(report)
        self.assertEqual([c['status'] for c in checks], ['PASS', 'FAIL', 'SKIPPED', 'SKIPPED', 'FAIL', 'FAIL'])
        self.assertTrue(all(len(c['summary']) <= 400 for c in checks))
        self.assertNotIn('PRIVATE', str(checks))
        self.assertEqual(report, original)

    def test_missing_individual_results_are_not_all_falsely_marked_failed(self):
        checks = verification_checks({'status': 'FAIL', 'checks': ['schema', 'write policy']})
        self.assertEqual([c['status'] for c in checks], ['SKIPPED', 'SKIPPED'])
        checks = verification_checks({'status': 'FAIL', 'requirements': [{'id': str(i), 'status': 'PASS'} for i in range(250)],
            'commands': [{'name': 'fresh_import', 'stderr': '\n'.join('ERROR: ' + str(i) for i in range(50))}]})
        self.assertEqual(len(checks), 200)


if __name__ == '__main__':
    unittest.main()

"""Exact artifact/verification/acceptance failures in disposable stores.

No native model is launched. The fixture reports pass through the same strict
protocol and durable approval gates as independent runners.
"""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.coordinator import Coordinator, WorkflowError, git
from backend.server import REPO_ROOT
from backend.tests import test_studio_protocol as wire
from backend.tests.test_generic_workflow import plan_result


class StudioDeliveryTests(unittest.TestCase):
    envelope = wire.StudioProtocolTests.envelope
    command = wire.StudioProtocolTests.command
    runner = wire.StudioProtocolTests.runner
    planning = wire.StudioProtocolTests.planning
    report = wire.StudioProtocolTests.report
    ready = wire.StudioProtocolTests.ready

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)/'disposable-store'
        self.c = Coordinator(REPO_ROOT, state_root=self.state)
        self.seq = 0
        self.pid = self.command('project.create', {'name': 'Exact fixture'}, pid=None)['result']['project']['id']

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def started(self, attempt_id):
        return self.report(attempt_id, 'started', {
            'nativeIdentity': {'threadId': 'fixture-'+attempt_id, 'turnId': 'turn-'+attempt_id,
                'processId': None, 'processGroupId': None, 'processStartTime': None},
            'startedAt': datetime.now(timezone.utc).isoformat(), 'requestedProfile': None,
            'reportedProfile': None, 'threadStartReported': None,
            'turnStartAcknowledged': None, 'actualProfile': None})

    def frozen(self, feedback=False):
        p = self.ready()
        if feedback:
            items = [{'feedbackId': 'feedback-'+str(i), 'objectId': 'player',
                'category': 'behavior', 'message': 'Original user feedback '+str(i)} for i in range(3)]
            revised = self.command('proposal.revise', {'proposalId': p['id'], 'supplement': 'Review all feedback', 'feedback': items},
                expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})
            self.assertEqual(revised['status'], 'accepted', revised)
            p = revised['result']['proposal']
            self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-revised'})
            self.started(p['attemptId'])
            result = {**plan_result(), 'schemaVersion': 'studio.planner-result.v1',
                'feedbackDecisions': [{'feedbackId': item['feedbackId'], 'status': 'adopted', 'reason': 'Linked to approved task',
                    'taskIds': ['harbor-loop'], 'requirementIds': ['explore']} for item in items]}
            self.assertEqual(self.report(p['attemptId'], 'completed', {'stopped': True, 'result': {'response': result}})['disposition'], 'recorded')
            p = self.c._get('proposal', p['id'])
        ref = self.c.project_view(self.pid)['proposal']['reviewedPlanRef']
        frozen = self.command('proposal.freeze', {'proposalId': p['id'], 'reviewedPlanRef': ref},
            expected={'proposalRevision': p['revision'], 'publicationRevision': 0})
        self.assertEqual(frozen['status'], 'accepted', frozen)
        return frozen['result']['packet']

    def produced(self, feedback=False, protected_drift=False, uid_provenance=None, uid_only=False):
        packet = self.frozen(feedback)
        self.c.register_runner({'runnerId': 'project-test', 'runnerKind': 'project',
            'environment': 'fixture', 'nativeVersion': None,
            'capabilities': ['verification-isolated-v1', 'preview-isolated-v1'],
            'sandboxEvidence': wire.fixture_role_evidence('project-test', 'project', ['verification-isolated-v1', 'preview-isolated-v1'])})
        receipt = self.command('production.start', {'packetId': packet['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        job = self.c._get('job', receipt['result']['job']['id'])
        attempt = self.c._get('attempt', job['attemptId'])
        self.assertEqual(attempt['status'], 'QUEUED', attempt.get('preparationError'))
        prepared = attempt['prepared']
        source = self.state/'artifacts'/prepared['inputArtifactRef']['artifactId']/'repository'
        repo = self.state/'artifacts'/('fixture-artifact-'+job['id'])/'repository'
        repo.parent.mkdir(parents=True)
        git(self.state, 'clone', '--quiet', '--no-hardlinks', '--no-local', str(source), str(repo))
        from runners.common import materialize_service_records
        materialize_service_records(repo, prepared['serviceRecords'])
        script = repo/('design/game.json' if protected_drift else 'scripts/player.gd')
        script.parent.mkdir(exist_ok=True)
        if not uid_only:
            script.write_text('outside approved scope\n' if protected_drift else 'extends Node2D\n\nfunc _ready() -> void:\n\tpass\n')
            git(repo, 'add', '--', script.relative_to(repo).as_posix())
        sidecars = {}
        if uid_provenance is not None:
            for index, path in enumerate(('scripts/main.gd.uid', 'scripts/player.gd.uid', 'studio/runtime.gd.uid')):
                sidecars[path] = f'uid://fixture{index}\n'.encode('ascii')
                (repo/path).write_bytes(sidecars[path])
            git(repo, 'add', '--', *sidecars)
        git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'Fixture sealed output')
        commit = git(repo, 'rev-parse', 'HEAD')
        ref = {'artifactId': repo.parent.name, 'projectId': self.pid, 'jobId': job['id'],
            'attemptId': attempt['id'], 'sourceCommit': commit, 'inputCommit': job['inputCommit'], 'packetId': packet['id']}
        if uid_provenance in {'valid', 'wrong-input'}:
            from backend.source_preparation import UIDPreparationResult
            evidence = UIDPreparationResult(job['inputCommit'], '4.6.3.stable.fixture', sidecars).evidence(commit)
            if uid_provenance == 'wrong-input': evidence['inputCommit'] = 'other-input-commit'
            (repo.parent/'evidence').mkdir()
            (repo.parent/'evidence/uid-preparation.json').write_text(json.dumps(evidence))
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-produce'})
        self.started(attempt['id'])
        self.assertEqual(self.c._get('job', job['id'])['status'], 'RUNNING')
        self.assertEqual(self.c.project_view(self.pid)['job']['status'], 'RUNNING')
        ack = self.report(attempt['id'], 'completed', {'stopped': True, 'result': {}, 'artifactRef': ref, 'sourceCommit': commit})
        return self.c._get('job', job['id']), ref, repo, ack

    def test_prepared_uid_evidence_allows_exact_delivery_with_real_source_edit(self):
        job, ref, repo, ack = self.produced(uid_provenance='valid')
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertEqual(job['status'], 'VERIFYING')
        self.assertEqual(self.c._get('attempt', job['verificationAttemptId'])['inputRefs']['inputCommit'], ref['inputCommit'])

    def test_missing_uid_evidence_never_queues_verification(self):
        job, ref, repo, ack = self.produced(uid_provenance='missing')
        self.assertEqual(ack['disposition'], 'rejected', ack)
        self.assertNotIn('verificationAttemptId', job)

    def test_wrong_uid_input_binding_never_queues_verification(self):
        job, ref, repo, ack = self.produced(uid_provenance='wrong-input')
        self.assertEqual(ack['disposition'], 'rejected', ack)
        self.assertNotIn('verificationAttemptId', job)

    def test_trusted_uid_metadata_alone_is_not_a_producer_source_edit(self):
        job, ref, repo, ack = self.produced(uid_provenance='valid', uid_only=True)
        self.assertEqual(ack['disposition'], 'rejected', ack)
        self.assertNotIn('verificationAttemptId', job)

    def candidate(self, feedback=False, source_unchanged=True):
        job, ref, repo, ack = self.produced(feedback)
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertEqual(job['status'], 'VERIFYING')
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'project-test', 'commandId': 'claim-verify'})
        self.started(job['verificationAttemptId'])
        ack = self.report(job['verificationAttemptId'], 'completed', {'stopped': True, 'artifactRef': ref,
            'sourceCommit': ref['sourceCommit'], 'result': {'status': 'PASS', 'sourceCommit': ref['sourceCommit'],
                'sourceUnchanged': source_unchanged, 'checks': [{'id': 'fixture', 'status': 'PASS'}], 'evidenceRef': 'fixture-evidence'}})
        return self.c._get('job', job['id']), ref, repo, ack

    def accept(self, job, decisions=None):
        return self.command('candidate.accept', {'candidateId': job['candidate']['id'],
            'sourceCommit': job['candidate']['sourceCommit'], 'experienceDecisions': decisions or []}, expected={'publicationRevision': 0, 'preferencesRevision': 0})

    def test_runner_candidate_diff_uses_retained_production_input(self):
        job, ref, repo, ack = self.candidate()
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertNotIn('originalBaseCommit', job)
        self.assertNotIn('baseCommit', job)
        evidence = self.c.workbench_source_changes(self.pid, job['id'])
        self.assertEqual(evidence['baseKind'], 'production_input')
        self.assertEqual(evidence['baseCommit'], ref['inputCommit'])
        self.assertEqual(evidence['sourceCommit'], ref['sourceCommit'])
        self.assertEqual(evidence['candidateId'], job['candidate']['id'])
        self.assertEqual([change['path'] for change in evidence['changes']], ['scripts/player.gd'])
        self.assertIn('+extends Node2D', evidence['changes'][0]['diff'])
        self.assertNotIn('unsaved unrelated', evidence['changes'][0]['diff'])
        self.assertEqual(evidence['userAcceptance'], 'NOT_PERFORMED')
        (repo/'scripts/player.gd').write_text('unsaved unrelated text\n')
        with self.assertRaises(WorkflowError) as rejected:
            self.c.workbench_source_changes(self.pid, job['id'])
        self.assertEqual(rejected.exception.code, 'SOURCE_UNAVAILABLE')

    def test_accept_keeps_unreviewed_feedback_and_explicit_followup(self):
        job, ref, repo, ack = self.candidate(feedback=True)
        self.assertEqual(ack['disposition'], 'recorded', ack)
        receipt = self.accept(job, [{'feedbackId': 'feedback-0', 'status': 'needs_followup', 'reason': 'Still too slow'}])
        self.assertEqual(receipt['status'], 'accepted', receipt)
        snapshot = self.c._get('snapshot', receipt['result']['snapshot']['id'])
        self.assertEqual(snapshot['artifactRef'], ref)
        self.assertEqual(snapshot['sourceCommit'], ref['sourceCommit'])
        feedback = {f['feedbackId']: f for f in self.c._all_project('feedback', self.pid)}
        self.assertEqual(feedback['feedback-0']['experienceStatus'], 'needs_followup')
        self.assertEqual(feedback['feedback-1']['experienceStatus'], 'unreviewed')
        self.assertTrue(self.c._get('artifact', ref['artifactId'])['retained'])

    def test_source_drift_during_verification_never_forms_candidate(self):
        job, ref, repo, ack = self.candidate(source_unchanged=False)
        self.assertEqual(ack['disposition'], 'rejected')
        self.assertNotIn('candidate', job)
        self.assertIsNone(self.c._get('project', self.pid)['snapshotId'])

    def test_delayed_reconcile_cannot_revoke_candidate_or_accepted_snapshot(self):
        job, ref, repo, ack = self.candidate()
        for aid in (job['productionAttemptId'], job['verificationAttemptId']):
            attempt = self.c._get('attempt', aid)
            result = self.c.reconcile_runner({'runnerId': attempt['runnerId'],
                'storeId': self.c.store_id, 'attemptId': aid,
                'nativeIdentity': attempt['nativeIdentity'], 'stopped': True})
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertEqual(self.c._get('job', job['id'])['status'], 'READY_FOR_REVIEW')
        receipt = self.accept(job)
        self.assertEqual(receipt['status'], 'accepted', receipt)
        sid = receipt['result']['snapshot']['id']
        attempt = self.c._get('attempt', job['verificationAttemptId'])
        self.c.reconcile_runner({'runnerId': attempt['runnerId'],
            'storeId': self.c.store_id, 'attemptId': attempt['id'],
            'nativeIdentity': attempt['nativeIdentity'], 'stopped': True})
        self.assertEqual(self.c._get('job', job['id'])['status'], 'PUBLISHED')
        self.assertEqual(self.c._get('project', self.pid)['snapshotId'], sid)

    def test_protected_committed_change_never_queues_verification(self):
        job, ref, repo, ack = self.produced(protected_drift=True)
        self.assertEqual(ack['disposition'], 'rejected')
        self.assertNotIn('verificationAttemptId', job)

    def test_missing_artifact_or_changed_verification_blocks_acceptance(self):
        job, ref, repo, ack = self.candidate()
        verification = copy.deepcopy(job['candidate']['verification'])
        with self.c.transaction():
            bad = self.c._get('job', job['id'])
            bad['candidate']['verification']['verificationAttemptId'] = 'different-attempt'
            self.c._put('job', bad)
        self.assertEqual(self.accept(job)['error']['code'], 'CANDIDATE_VERIFICATION')
        with self.c.transaction():
            fixed = self.c._get('job', job['id'])
            fixed['candidate']['verification'] = verification
            self.c._put('job', fixed)
        shutil.rmtree(repo.parent)
        self.assertEqual(self.accept(job)['error']['code'], 'ARTIFACT_MISSING')
        self.assertEqual(self.c._get('project', self.pid)['publicationRevision'], 0)

    def test_snapshot_materialization_failure_preserves_authoritative_reference(self):
        job, ref, repo, ack = self.candidate()
        real_run = subprocess.run
        def fail_clone(argv, *args, **kwargs):
            if argv[:2] == ['git', 'clone']:
                raise OSError('fixture disk unavailable')
            return real_run(argv, *args, **kwargs)
        with patch('subprocess.run', side_effect=fail_clone):
            receipt = self.accept(job)
        self.assertEqual(receipt['status'], 'accepted', receipt)
        sid = receipt['result']['snapshot']['id']
        self.assertEqual(self.c._get('snapshot', sid)['materializationStatus'], 'PENDING')
        self.assertEqual(self.c._get('snapshot', sid)['artifactRef'], ref)
        self.c.materialize_snapshot(sid)
        self.assertEqual(self.c._get('snapshot', sid)['materializationStatus'], 'READY')

    def test_pending_snapshot_recovers_on_backend_restart_without_new_attempt(self):
        job, ref, repo, ack = self.candidate()
        real_run = subprocess.run
        def fail_clone(argv, *args, **kwargs):
            if argv[:2] == ['git', 'clone']:
                raise OSError('fixture transient failure')
            return real_run(argv, *args, **kwargs)
        with patch('subprocess.run', side_effect=fail_clone):
            receipt = self.accept(job)
        sid = receipt['result']['snapshot']['id']
        attempts = {a['id'] for a in self.c._all('attempt')}
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state)
        self.assertEqual(self.c._get('snapshot', sid)['materializationStatus'], 'READY')
        self.assertEqual({a['id'] for a in self.c._all('attempt')}, attempts)

    def test_cancel_after_production_completion_stops_current_verification(self):
        job, ref, repo, ack = self.produced()
        production = self.c._get('attempt', job['productionAttemptId'])
        receipt = self.command('execution.cancel', {'attemptId': production['id'], 'ownerRef': production['ownerRef']})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        self.assertEqual(receipt['result']['attempt']['id'], job['verificationAttemptId'])
        self.assertEqual(self.c._get('attempt', job['verificationAttemptId'])['status'], 'STOPPED')
        self.assertNotIn('candidate', self.c._get('job', job['id']))

    def test_preparation_crash_reuses_consumed_decision_and_materializes_same_input(self):
        packet = self.c._get('packet', self.frozen()['id'])
        with patch('backend.general_gm_integration.prepare_input', side_effect=OSError('fixture crash after consumption')):
            receipt = self.command('production.start', {'packetId': packet['id']},
                expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(receipt['status'], 'accepted')
        job = self.c._get('job', receipt['result']['job']['id'])
        aid = job['attemptId']
        self.assertEqual(self.c._get('attempt', aid)['status'], 'PREPARING')
        approval = self.c.db.execute('SELECT consumed FROM approvals WHERE id=?', (packet['approvalEventId'],)).fetchone()
        self.assertEqual(approval[0], 1)
        decision = self.c._get('input_decision', 'input-decision:'+job['id'])
        self.c.prepare_runner_input(aid)
        prepared = self.c._get('attempt', aid)['prepared']
        self.c.prepare_runner_input(aid)
        self.assertEqual(self.c._get('attempt', aid)['prepared'], prepared)
        self.assertEqual(self.c._get('input_decision', decision['id']), decision)
        self.assertEqual(len(self.c._all('job')), 1)

    def test_permanent_preparation_rejection_stops_before_runner_launch(self):
        from backend.general_gm_integration import GMIntegrationError
        packet = self.frozen()
        with patch('backend.general_gm_integration.prepare_input', side_effect=GMIntegrationError('fixture permanent approval rejection')):
            receipt = self.command('production.start', {'packetId': packet['id']},
                expected={'publicationRevision': 0, 'preferencesRevision': 0})
        job = self.c._get('job', receipt['result']['job']['id'])
        attempt = self.c._get('attempt', job['attemptId'])
        self.assertEqual(job['status'], 'FAILED')
        self.assertEqual(attempt['status'], 'FAILED')
        self.assertIsNone(attempt['nativeIdentity'])
        self.assertIn('fixture permanent approval rejection', job['message'])
        claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-rejected-preparation'})
        self.assertIsNone(claim['request'])
        self.c.prepare_runner_input(attempt['id'])
        self.assertEqual(self.c._get('attempt', attempt['id'])['status'], 'FAILED')

    def test_confirmed_runner_failure_is_failed_not_user_cancellation(self):
        packet = self.frozen()
        receipt = self.command('production.start', {'packetId': packet['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        job = receipt['result']['job']
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-failure'})
        self.started(job['attemptId'])
        payload = {'stopped': True, 'stopReason': 'native_error', 'diagnosticRef': 'fixture-seal-disk-error'}
        ack = self.report(job['attemptId'], 'failed', payload)
        self.assertEqual(ack['disposition'], 'recorded')
        self.assertEqual(self.c._get('attempt', job['attemptId'])['status'], 'FAILED')
        self.assertEqual(self.c._get('job', job['id'])['status'], 'FAILED')
        self.assertNotIn('candidate', self.c._get('job', job['id']))
        self.report(job['attemptId'], 'stopped', payload)
        self.assertEqual(self.c._get('job', job['id'])['status'], 'FAILED')

    def test_cancel_during_input_preparation_cannot_resurrect_queue(self):
        packet = self.frozen()
        def cancelled_prepare(coordinator, packet, job):
            attempt = coordinator._get('attempt', job['attemptId'])
            self.command('execution.cancel', {'attemptId': attempt['id'], 'ownerRef': attempt['ownerRef']})
            return {'inputCommit': 'never-dispatch-this-input'}
        with patch('backend.general_gm_integration.prepare_input', side_effect=cancelled_prepare):
            receipt = self.command('production.start', {'packetId': packet['id']},
                expected={'publicationRevision': 0, 'preferencesRevision': 0})
        job = self.c._get('job', receipt['result']['job']['id'])
        self.assertEqual(self.c._get('attempt', job['attemptId'])['status'], 'STOPPED')
        self.assertEqual(job['status'], 'CANCELLED')
        claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-after-preparation-cancel'})
        self.assertIsNone(claim['request'])

    def test_prepared_input_replay_rejects_dirty_source_and_changed_commit(self):
        from backend.general_gm_integration import prepare_input, GMIntegrationError
        packet = self.c._get('packet', self.frozen()['id'])
        receipt = self.command('production.start', {'packetId': packet['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        job = self.c._get('job', receipt['result']['job']['id'])
        prepared = self.c._get('attempt', job['attemptId'])['prepared']
        artifact = self.state/'artifacts'/prepared['inputArtifactRef']['artifactId']
        repo = artifact/'repository'
        self.assertEqual(prepare_input(self.c, packet, job), prepared)
        (repo/'project.godot').write_text((repo/'project.godot').read_text()+'\n; unknown change\n')
        with self.assertRaises(GMIntegrationError):
            prepare_input(self.c, packet, job)
        git(repo, 'checkout', '--', 'project.godot')
        git(repo, 'commit', '--quiet', '--allow-empty', '-m', 'Unexpected input revision')
        with self.assertRaises(GMIntegrationError):
            prepare_input(self.c, packet, job)
        git(repo, 'checkout', '--detach', prepared['inputCommit'])
        import json
        (artifact/'prepared.json').write_text(json.dumps({'inputCommit': prepared['inputCommit'], 'extra': True}))
        with self.assertRaises(GMIntegrationError):
            prepare_input(self.c, packet, job)

    def test_preview_view_recovers_identity_and_queued_stop_prevents_launch(self):
        job, ref, repo, ack = self.candidate()
        payload = {'candidateId': job['candidate']['id']}
        receipt = self.command('preview.start', payload)
        self.assertEqual(receipt['status'], 'accepted', receipt)
        preview = receipt['result']['preview']
        view = self.c.project_view(self.pid)
        self.assertEqual(view['previews'][0]['id'], preview['id'])
        self.assertIn('preview.stop', view['allowedActions'])
        self.assertNotIn('preview.start', view['allowedActions'])
        self.assertEqual(self.command('preview.start', payload)['error']['code'], 'PREVIEW_BUSY')
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state)
        self.assertEqual(self.c.project_view(self.pid)['previews'][0]['id'], preview['id'])
        stop = self.command('preview.stop', {'previewId': preview['id']})
        self.assertEqual(stop['result']['preview']['status'], 'STOPPED')
        claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'project-test', 'commandId': 'claim-after-preview-stop'})
        self.assertIsNone(claim['request'])

    def test_running_preview_restart_preserves_unknown_and_stop_action(self):
        job, ref, repo, ack = self.candidate()
        receipt = self.command('preview.start', {'candidateId': job['candidate']['id']})
        preview = receipt['result']['preview']
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'project-test', 'commandId': 'claim-running-preview'})
        self.started(preview['attemptId'])
        self.assertEqual(self.c.project_view(self.pid)['previews'][0]['status'], 'RUNNING')
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state)
        view = self.c.project_view(self.pid)
        self.assertEqual(view['previews'][0]['status'], 'UNKNOWN')
        self.assertEqual(view['observations']['status'], 'UNKNOWN')
        self.assertIn('preview.stop', view['allowedActions'])

    def test_preview_actions_follow_candidate_runner_liveness(self):
        job, ref, repo, ack = self.candidate()
        candidate_view = self.c.project_view(self.pid)
        self.assertIn('preview.start', candidate_view['allowedActions'])

        receipt = self.command('preview.start', {'candidateId': job['candidate']['id']})
        self.assertEqual(receipt['status'], 'accepted', receipt)
        preview_id = receipt['result']['preview']['id']

        with self.c.transaction():
            runner = self.c._get('runner', 'project-test')
            self.assertIn('preview-isolated-v1', runner['capabilities'])
            runner['lastHeartbeat'] = 0
            self.c._put('runner', runner)

        offline_view = self.c.project_view(self.pid)
        self.assertNotIn('preview.start', offline_view['allowedActions'])
        self.assertIn('preview.stop', offline_view['allowedActions'])
        self.assertEqual(offline_view['previews'][0]['id'], preview_id)

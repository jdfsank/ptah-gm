import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.coordinator import Coordinator, WorkflowError
from backend.server import REPO_ROOT, make_server
from backend.object_protocol import validate_execution_request
from backend.role_evidence import REQUIRED_ROLE_CHECKS


def fixture_role_evidence(runner_id, runner_kind, capabilities):
    """Synthetic observations for protocol tests, never production proof."""
    return {"schemaVersion": "studio.role-probe.v1", "runnerId": runner_id,
        "runnerKind": runner_kind, "probeId": "synthetic-protocol-fixture",
        "observedAt": datetime.now(timezone.utc).isoformat(), "policy": "deny-default",
        "status": "PASS", "crossProjectDenied": True, "approvalNetworkDenied": True,
        "verifiedCapabilities": list(capabilities),
        "roleAssessment": {cap: "PASS" for cap in capabilities},
        "roles": {cap: {"checks": {key: True for key in REQUIRED_ROLE_CHECKS[cap]}} for cap in capabilities}}


class StudioProtocolTests(unittest.TestCase):
    def test_claim_uses_pending_index_without_loading_terminal_history(self):
        proposal = self.planning()
        with self.c.transaction():
            for index in range(200):
                self.c._put('attempt', {'id': f'historic-{index}', 'runnerId': 'agent-test',
                    'status': 'FAILED', 'projectId': self.pid})
        self.assertEqual([a['id'] for a in self.c._pending_runner_attempts('agent-test')],
                         [proposal['attemptId']])
        plan = self.c.db.execute("EXPLAIN QUERY PLAN SELECT payload FROM entities WHERE kind='attempt' "
            "AND json_extract(payload,'$.status') NOT IN ('COMPLETED','STOPPED','FAILED') "
            "AND json_extract(payload,'$.runnerId')=? ORDER BY rowid DESC", ('agent-test',)).fetchall()
        self.assertIn('studio_pending_runner_attempts', str([tuple(row) for row in plan]))
        original = self.c._all

        def checked_all(kind):
            self.assertNotEqual(kind, 'attempt', 'claim must not hydrate failed history')
            return original(kind)

        with mock.patch.object(self.c, '_all', side_effect=checked_all):
            claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test',
                                         'commandId': 'indexed-claim'})
        self.assertEqual(claim['request']['attemptId'], proposal['attemptId'])

    def test_session_queue_is_bounded_across_projects_and_claims_remain_single_owner(self):
        from backend.studio_protocol import MAX_PENDING_AGENT_ATTEMPTS
        self.runner()
        proposals = []
        for index in range(MAX_PENDING_AGENT_ATTEMPTS + 1):
            pid = self.command('project.create', {'name': f'queue-{index}'}, pid=None)['result']['project']['id']
            receipt = self.command('concept.submit', {'text': 'bounded session', 'assetRefs': []}, pid=pid,
                                   expected={'preferencesRevision': 0, 'publicationRevision': 0})
            if index == MAX_PENDING_AGENT_ATTEMPTS:
                self.assertEqual(receipt['status'], 'rejected')
                self.assertEqual(receipt['error']['code'], 'SESSION_CAPACITY')
                self.assertEqual(self.c._all_project('proposal', pid), [])
            else:
                proposals.append(receipt['result']['proposal'])
        self.assertEqual(len(self.c._all('attempt')), MAX_PENDING_AGENT_ATTEMPTS)
        first = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'queue-first'})
        self.assertEqual(first['request']['attemptId'], proposals[0]['attemptId'])
        second = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'queue-second'})
        self.assertIsNone(second['request'])

    def test_session_failure_cooldown_is_durable_idempotent_and_blocks_new_admission(self):
        proposal = self.planning()
        other = self.command('project.create', {'name': 'queued'}, pid=None)['result']['project']['id']
        queued = self.command('concept.submit', {'text': 'queued session', 'assetRefs': []}, pid=other,
            expected={'preferencesRevision': 0, 'publicationRevision': 0})['result']['proposal']
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'cooldown-first'})
        failure = {'stopped': True, 'stopReason': 'native_error', 'launchPrevented': True,
                   'diagnosticRef': 'local:sandbox-probe/' + proposal['attemptId']}
        before = datetime.now(timezone.utc).timestamp()
        self.report(proposal['attemptId'], 'failed', failure, report_id='cooldown-failure')
        runner = self.c._get('runner', 'agent-test')
        gate = runner['sessionRetryGate']
        self.assertEqual(gate['consecutiveFailures'], 1)
        self.assertGreaterEqual(gate['notBefore'], before + 5)
        self.report(proposal['attemptId'], 'failed', failure, report_id='cooldown-failure')
        self.assertEqual(self.c._get('runner', 'agent-test')['sessionRetryGate'], gate)
        self.runner()  # A runner restart/registration must preserve the gate.
        self.assertEqual(self.c._get('runner', 'agent-test')['sessionRetryGate'], gate)
        denied = self.command('concept.submit', {'text': proposal['text'], 'assetRefs': []},
            expected={'preferencesRevision': 0, 'publicationRevision': 0})
        self.assertEqual(denied['error']['code'], 'SESSION_COOLDOWN')
        for index in range(20):
            denied = self.command('concept.submit', {'text': proposal['text'], 'assetRefs': []},
                expected={'preferencesRevision': 0, 'publicationRevision': 0}, cid=f'rapid-retry-{index}')
            self.assertEqual(denied['error']['code'], 'SESSION_COOLDOWN')
        self.assertEqual(len(self.c._all('attempt')), 2)
        empty = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'cooldown-held'})
        self.assertIsNone(empty['request'])
        projected = self.c.project_view(self.pid)['proposal']['planningFailure']
        self.assertEqual(projected['code'], 'PLANNER_SETUP')
        self.assertIn('沙箱', projected['message'])
        self.assertTrue(projected['retryNotBefore'])
        with mock.patch('backend.studio_protocol.time.time', return_value=gate['notBefore'] + 1):
            next_claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'cooldown-ready'})
        self.assertEqual(next_claim['request']['attemptId'], queued['attemptId'])

    def test_session_cooldown_is_capped_and_success_releases_failure_gate(self):
        clock = datetime.now(timezone.utc).timestamp()
        for index in range(8):
            with mock.patch('backend.studio_protocol.time.time', return_value=clock):
                proposal = self.planning()
                self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test',
                                     'commandId': f'backoff-claim-{index}'})
                self.report(proposal['attemptId'], 'failed', {'stopped': True, 'stopReason': 'native_error',
                    'launchPrevented': True, 'diagnosticRef': 'local:sandbox-probe/' + proposal['attemptId']})
                gate = self.c._get('runner', 'agent-test')['sessionRetryGate']
                self.assertEqual(gate['notBefore'] - clock, min(60, 5 * 2 ** index))
                clock = gate['notBefore'] + 1
        with mock.patch('backend.studio_protocol.time.time', return_value=clock):
            self.ready()
        self.assertNotIn('sessionRetryGate', self.c._get('runner', 'agent-test'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'state'
        self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=True)
        self.seq = 0
        self.pid = self.command('project.create', {'name': 'A'}, pid=None)['result']['project']['id']

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def envelope(self, typ, payload, pid='current', expected=None, cid=None):
        self.seq += 1
        msg = {'schemaVersion': 'studio.message.v1', 'kind': 'command', 'type': typ,
               'storeId': self.c.store_id, 'commandId': cid or f'command-{self.seq}', 'payload': payload}
        if pid == 'current': pid = self.pid
        if pid is not None: msg['projectId'] = pid
        if expected is not None: msg['expected'] = expected
        if typ in {'concept.submit', 'iteration.submit', 'proposal.revise'} and expected is not None:
            msg['expected'].setdefault('sourceCommit', None)
        return msg

    def command(self, typ, payload, pid='current', expected=None, cid=None):
        msg = self.envelope(typ, payload, pid, expected, cid)
        return self.c.submit_command(msg, operator_id=self.c.operator_id, project_id=msg.get('projectId'))

    def runner(self):
        self.c.register_runner({'runnerId': 'agent-test', 'runnerKind': 'agent', 'environment': 'test-fixture',
            'nativeVersion': 'fixture', 'capabilities': ['planning-readonly-v1', 'production-private-v1'],
            'sandboxEvidence': fixture_role_evidence('agent-test', 'agent', ['planning-readonly-v1', 'production-private-v1'])})
        self.c.update_runner_catalog({'runnerId': 'agent-test', 'catalogRevision': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'models': [{'modelKey': 'model-fixture', 'modelProvider': 'fixture', 'supportedReasoningEfforts': ['medium'], 'inputModalities': ['text'], 'isDefault': True}]})

    def planning(self):
        self.runner()
        return self.command('concept.submit', {'text': 'a bounded game', 'assetRefs': []}, expected={'preferencesRevision': 0, 'publicationRevision': 0})['result']['proposal']

    def test_loss_retry_preserves_original_effect_after_revision_change(self):
        msg = self.envelope('project.create', {'name': 'lost response'}, pid=None, cid='lost')
        first = self.c.submit_command(msg, operator_id=self.c.operator_id)
        self.command('project.settings.update', {'name': 'renamed'}, pid=first['result']['project']['id'])
        replay = self.c.submit_command(msg, operator_id=self.c.operator_id)
        self.assertEqual(first, replay)
        self.assertEqual(len(self.c._all('project')), 2)
        msg['payload']['name'] = 'different'
        with self.assertRaisesRegex(WorkflowError, '另一|其他'):
            self.c.submit_command(msg, operator_id=self.c.operator_id)

    def test_transaction_rollback_removes_receipt_effect_and_event(self):
        before = self.c.project_view(self.pid)['throughSequence']
        with self.assertRaises(RuntimeError):
            with self.c.transaction():
                self.command('project.settings.update', {'name': 'rolled back'}, cid='rollback')
                raise RuntimeError('simulated crash before commit')
        self.assertEqual(self.c._get('project', self.pid)['title'], 'A')
        self.assertFalse(self.c.command_lookup(self.pid, 'rollback', self.c.operator_id)['known'])
        self.assertEqual(before, self.c.project_view(self.pid)['throughSequence'])

    def test_project_snapshot_to_subscription_gap_is_replayed(self):
        view = self.c.project_view(self.pid)
        self.command('project.settings.update', {'name': 'next'})
        other = self.command('project.create', {'name': 'B'}, pid=None)['result']['project']['id']
        self.command('project.settings.update', {'name': 'private B'}, pid=other)
        events = self.c.events_after(self.pid, view['throughSequence'])
        self.assertTrue(events)
        self.assertTrue(all(e['projectId'] == self.pid for e in events))
        self.assertEqual(self.c.project_view(self.pid)['throughSequence'], events[-1]['sequence'])

    def test_preferences_draft_and_views_do_not_create_attempts(self):
        self.runner()
        self.command('session.preferences.update', {'role': 'planner', 'modelKey': 'model-fixture', 'effort': 'medium',
            'limits': {'maxDurationSeconds': 10, 'softTotalTokens': 100}}, expected={'preferencesRevision': 0})
        self.c.project_view(self.pid)
        self.c.session_catalog(self.pid)
        self.assertEqual(self.c._all('attempt'), [])

    def test_test_workspace_production_is_rejected_before_consumption(self):
        proposal = self.ready()
        ref = self.c.project_view(self.pid)['proposal']['reviewedPlanRef']
        frozen = self.command('proposal.freeze', {'proposalId': proposal['id'], 'reviewedPlanRef': ref},
            expected={'proposalRevision': proposal['revision'], 'publicationRevision': 0})['result']['packet']
        before = len(self.c._all('attempt'))
        receipt = self.command('production.start', {'packetId': frozen['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(receipt['error']['code'], 'PRODUCTION_AUTHORIZATION')
        self.assertEqual(self.c._all('job'), [])
        self.assertEqual(len(self.c._all('attempt')), before)
        packet = self.c._get('packet', frozen['id'])
        consumed = self.c.db.execute('SELECT consumed FROM approvals WHERE id=?', (packet['approvalEventId'],)).fetchone()[0]
        self.assertEqual(consumed, 0)

    def test_catalog_refresh_observation_does_not_change_content_revision(self):
        self.runner()
        before = self.c._get('runner', 'agent-test')['catalog']
        refreshed = {'runnerId': 'agent-test', 'catalogRevision': before['catalogRevision'],
            'observedAt': (datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),
            'models': before['models']}
        self.c.update_runner_catalog(refreshed)
        after = self.c._get('runner', 'agent-test')['catalog']
        self.assertEqual(after['observedAt'], refreshed['observedAt'])
        self.assertEqual(after['catalogRevision'], before['catalogRevision'])
        changed = copy.deepcopy(refreshed)
        changed['models'][0]['modelKey'] = 'other-model'
        with self.assertRaisesRegex(WorkflowError, '目录修订'):
            self.c.update_runner_catalog(changed)

    def test_single_claim_replay_and_expired_lease_cannot_revive(self):
        p = self.planning()
        self.assertFalse(self.c._threads)
        claim = {'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-one'}
        result = self.c.claim_runner(claim)
        self.assertEqual(result, self.c.claim_runner(claim))
        request = result['request']
        validate_execution_request(request)
        self.assertEqual(request['attemptId'], p['attemptId'])
        with self.c.transaction():
            attempt = self.c._get('attempt', p['attemptId'])
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        hb = self.c.heartbeat_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'attemptId': p['attemptId']})
        self.assertTrue(hb['reconcileRequired'])
        next_claim = self.c.claim_runner({**claim, 'commandId': 'claim-two'})
        self.assertIsNone(next_claim['request'])
        self.assertEqual(self.c._get('proposal', p['id'])['status'], 'PLANNING_UNCERTAIN')

    def test_profile_frozen_and_modality_conflicts_do_not_start(self):
        p = self.planning()
        frozen = copy.deepcopy(self.c._get('attempt', p['attemptId'])['profileSnapshot'])
        self.command('session.preferences.update', {'role': 'planner', 'modelKey': 'other', 'effort': 'high',
            'limits': {'maxDurationSeconds': 20, 'softTotalTokens': None}}, expected={'preferencesRevision': 0})
        self.assertEqual(frozen, self.c._get('attempt', p['attemptId'])['profileSnapshot'])
        self.assertEqual(len(self.c._all('attempt')), 1)

    def test_unsupported_isolation_fails_before_business_mutation(self):
        self.c.register_runner({'runnerId': 'agent-test', 'runnerKind': 'agent', 'environment': 'test', 'nativeVersion': 'fixture', 'capabilities': [], 'sandboxEvidence': {'status': 'NOT_READY'}})
        self.c.update_runner_catalog({'runnerId': 'agent-test', 'catalogRevision': 1, 'observedAt': '2026-10-12T00:00:00Z', 'models': [{'modelKey': 'model', 'modelProvider': 'fixture', 'supportedReasoningEfforts': ['medium'], 'inputModalities': ['text']}]})
        receipt = self.command('concept.submit', {'text': 'game', 'assetRefs': []}, expected={'preferencesRevision': 0, 'publicationRevision': 0})
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(self.c._all('proposal'), [])

    def test_role_registration_requires_fresh_bound_complete_boolean_observations(self):
        capability = 'planning-readonly-v1'
        evidence = fixture_role_evidence('probe-runner', 'agent', [capability])
        body = {'runnerId': 'probe-runner', 'runnerKind': 'agent', 'environment': 'fixture',
            'nativeVersion': 'fixture', 'capabilities': [capability], 'sandboxEvidence': evidence}
        key = REQUIRED_ROLE_CHECKS[capability][0]
        for name, mutate in (
            ('missing check', lambda e: e['roles'][capability]['checks'].pop(key)),
            ('integer truth', lambda e: e['roles'][capability]['checks'].update({key: 1})),
            ('wrong runner', lambda e: e.update(runnerId='someone-else')),
            ('stale observation', lambda e: e.update(observedAt=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat())),
        ):
            with self.subTest(name=name):
                broken = copy.deepcopy(body); mutate(broken['sandboxEvidence'])
                with self.assertRaisesRegex(WorkflowError, '角色|证据'):
                    self.c.register_runner(broken)
        self.c.register_runner(body)
        self.assertEqual(self.c._get('runner', 'probe-runner')['capabilities'], [capability])
        self.c.register_runner({**body, 'capabilities': [], 'sandboxEvidence': {'status': 'NOT_VERIFIED'}})
        self.assertEqual(self.c._get('runner', 'probe-runner')['capabilities'], [])

    def test_basic_sandbox_probe_cannot_advertise_role_isolation(self):
        with self.assertRaisesRegex(WorkflowError, '基础探针不能放行'):
            self.c.register_runner({'runnerId': 'basic-probe', 'runnerKind': 'agent', 'environment': 'fixture',
                'nativeVersion': 'fixture', 'capabilities': ['planning-readonly-v1'],
                'sandboxEvidence': {'status': 'PASS', 'crossProjectDenied': True, 'approvalNetworkDenied': True}})
        self.assertEqual(self.c._all('runner'), [])

    def test_public_view_omits_native_evidence_and_approval_credentials(self):
        with self.c.transaction():
            self.c._put('proposal', {'id': 'proposal-secret', 'projectId': self.pid, 'status': 'FAILED', 'workflow': 'objects-v1', 'revision': 1,
                'planningEvidence': {'stdout': 'secret native output'}, 'approvalEventId': 'secret-credential'})
        text = json.dumps(self.c.project_view(self.pid))
        self.assertNotIn('secret native output', text)
        self.assertNotIn('secret-credential', text)

    def test_project_view_only_lists_candidates_still_waiting_for_review(self):
        with self.c.transaction():
            for status in ('READY_FOR_REVIEW', 'PUBLISHED', 'REJECTED'):
                self.c._put('job', {'id': 'job-' + status, 'projectId': self.pid,
                    'status': status, 'createdAt': '2026-10-13T00:00:00Z',
                    'candidate': {'id': 'candidate-' + status, 'jobId': 'job-' + status}})
        expected = [{'id': 'candidate-READY_FOR_REVIEW',
            'jobId': 'job-READY_FOR_REVIEW', 'status': 'READY_FOR_REVIEW'}]
        self.assertEqual(self.c.project_view(self.pid)['candidates'], expected)
        self.assertEqual(self.c.workbench(self.pid)['candidates'], expected)
        self.assertEqual(len(self.c.project_view(self.pid)['jobs']), 3,
            'published and rejected jobs remain available in project history')

    def report(self, attempt_id, typ, payload, report_id=None):
        attempt = self.c._get('attempt', attempt_id)
        self.seq += 1
        return self.c.report_runner({'schemaVersion': 'studio.message.v1', 'kind': 'execution_report',
            'type': typ, 'taskKind': attempt['taskKind'], 'storeId': self.c.store_id,
            'projectId': attempt['projectId'], 'runnerId': attempt['runnerId'],
            'attemptId': attempt_id, 'reportId': report_id or f'report-{self.seq}', 'payload': payload})

    def ready(self):
        from backend.tests.test_generic_workflow import plan_result
        proposal = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-ready'})
        self.report(proposal['attemptId'], 'started', {'nativeIdentity': {'threadId': 'fixture-thread', 'turnId': 'fixture-turn', 'processId': None, 'processGroupId': None, 'processStartTime': None},
            'startedAt': datetime.now(timezone.utc).isoformat(), 'requestedProfile': None, 'reportedProfile': None,
            'threadStartReported': None, 'turnStartAcknowledged': None, 'actualProfile': None})
        response = {**plan_result(), 'schemaVersion': 'studio.planner-result.v1', 'feedbackDecisions': []}
        ack = self.report(proposal['attemptId'], 'completed', {'stopped': True, 'result': {'response': response}})
        self.assertEqual(ack['disposition'], 'recorded', ack)
        return self.c._get('proposal', proposal['id'])

    def after_session_cooldown(self):
        # Parser/diagnostic fixtures deliberately perform consecutive failures.
        # Advance their clock instead of bypassing the production admission gate.
        runner = next((r for r in self.c._all('runner') if r['id'] == 'agent-test'), {})
        not_before = (runner.get('sessionRetryGate') or {}).get('notBefore', 0)
        return mock.patch('backend.studio_protocol.time.time',
            return_value=max(datetime.now(timezone.utc).timestamp(), not_before + 1))

    def started_planning(self):
        with self.after_session_cooldown():
            proposal = self.planning()
            self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test',
                'commandId': 'claim-' + proposal['id']})
            self.report(proposal['attemptId'], 'started', {
                'nativeIdentity': {'threadId': 'thread-' + proposal['id'], 'turnId': 'turn-one',
                    'processId': None, 'processGroupId': None, 'processStartTime': None},
                'startedAt': datetime.now(timezone.utc).isoformat(), 'requestedProfile': None,
                'reportedProfile': None, 'threadStartReported': None,
                'turnStartAcknowledged': None, 'actualProfile': None})
        return proposal

    def test_invalid_planner_results_are_receipted_without_weakening_strict_validation(self):
        from backend.object_protocol import validate_execution_report
        from backend.tests.test_generic_workflow import plan_result
        from backend.tests.test_object_protocol import workbench_document

        locked = plan_result(workbench_document())
        locked['document']['objects'][2]['workbench']['lock'] = 'locked'
        unknown = copy.deepcopy(locked)
        unknown['document']['objects'][2]['workbench']['lock'] = 'free'
        unknown['document']['objects'][2]['workbench']['unknown'] = True
        for result in ({'response': locked}, {'response': unknown},
                       {'response': 'not JSON'}, {'response': '{"status":"READY","status":"READY"}'},
                       {'response': None}, {'response': plan_result(), 'extra': True}, [], 7):
            with self.subTest(result=result):
                proposal = self.started_planning()
                payload = {'stopped': True, 'result': result}
                ack = self.report(proposal['attemptId'], 'completed', payload)
                self.assertEqual(ack['disposition'], 'rejected', ack)
                content = json.loads(self.c.db.execute('SELECT content FROM reports WHERE report_id=?',
                    (ack['reportId'],)).fetchone()[0])
                self.assertEqual(content['payload'], payload, 'retain the exact rejected model output')
                with self.assertRaises((ValueError, TypeError)):
                    validate_execution_report(content)
                self.assertEqual(self.c.report_runner(content), ack, 'replay returns the same durable ACK')
                view = self.c.project_view(self.pid)
                failed = view['proposal']
                self.assertEqual(failed['status'], 'FAILED')
                self.assertEqual(failed['planningFailure']['code'], 'PLANNER_RESPONSE_INVALID')
                self.assertTrue(failed['planningFailure']['retryable'])
                self.assertTrue(failed['planningTerminationConfirmed'])
                self.assertEqual(failed['text'], proposal['text'])
                self.assertEqual(view['jobs'], [])
                self.assertEqual(self.c._all('reviewed_plan'), [])

    def test_rejected_planner_outbox_survives_lost_ack_and_allows_explicit_retry(self):
        from runners.common import LocalJournal, TransportError
        from backend.tests.test_generic_workflow import plan_result
        from backend.tests.test_object_protocol import workbench_document

        proposal = self.started_planning()
        journal = LocalJournal(Path(self.tmp.name) / 'outbox.sqlite3')
        journal.bind_store(self.c.store_id)
        attempt = self.c._get('attempt', proposal['attemptId'])
        journal.start_intent(attempt['id'], {**attempt, 'attemptId': attempt['id']})
        response = plan_result(workbench_document())
        response['document']['objects'][2]['workbench']['lock'] = 'locked'
        report_id = journal.add_report(attempt['id'], 'completed', self.c.store_id,
            self.pid, 'agent-test', {'stopped': True, 'result': {'response': response}})
        coordinator = self.c

        class LostAckAPI:
            lose = True
            def request(self, method, route, body):
                ack = coordinator.report_runner(body)
                if self.lose:
                    self.lose = False
                    raise TransportError('simulated lost ACK after recording rejection')
                return ack

        api = LostAckAPI()
        with self.assertRaises(TransportError):
            journal.flush(api)
        self.assertEqual(journal.pending(), 1)
        self.assertEqual(journal.flush(api), 1)
        self.assertEqual(journal.pending(), 0)
        self.assertEqual(self.c.report_lookup('agent-test', report_id)['ack']['disposition'], 'rejected')
        self.assertEqual(self.c._get('attempt', attempt['id'])['status'], 'FAILED')
        self.assertEqual(len(self.c._all('attempt')), 1, 'rejection never starts a replacement model')
        with self.after_session_cooldown():
            retry = self.command('concept.submit', {'text': proposal['text'], 'assetRefs': []},
                expected={'preferencesRevision': 0, 'publicationRevision': 0})['result']['proposal']
        self.assertEqual(retry['status'], 'PLANNING')
        self.assertNotEqual(retry['attemptId'], attempt['id'])
        self.assertEqual(retry['text'], proposal['text'])
        self.assertEqual(self.c._get('attempt', attempt['id'])['status'], 'FAILED')

    def test_invalid_plan_still_requires_exact_envelope_identity_stop_and_live_authority(self):
        from backend.object_protocol import ObjectProtocolError
        proposal = self.started_planning()
        base = {'schemaVersion': 'studio.message.v1', 'kind': 'execution_report', 'type': 'completed',
            'taskKind': 'plan', 'storeId': self.c.store_id, 'projectId': self.pid,
            'runnerId': 'agent-test', 'attemptId': proposal['attemptId'], 'reportId': 'bad-identity',
            'payload': {'stopped': True, 'result': {'response': None}}}
        for changed in ({'storeId': 'other-store'}, {'projectId': 'other-project'},
                        {'taskKind': 'produce'}, {'runnerId': 'other-runner'}, {'unknown': True},
                        {'payload': {**base['payload'], 'stopped': False}}):
            with self.subTest(changed=changed), self.assertRaises((WorkflowError, ObjectProtocolError)):
                self.c.report_runner({**base, **changed})
        self.assertFalse(self.c.report_lookup('agent-test', base['reportId'])['known'])
        self.assertEqual(self.c._get('proposal', proposal['id'])['status'], 'PLANNING')
        with self.c.transaction():
            attempt = self.c._get('attempt', proposal['attemptId'])
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        ack = self.c.report_runner(base)
        self.assertEqual(ack['disposition'], 'evidence_only')
        self.assertEqual(self.c._get('proposal', proposal['id'])['status'], 'PLANNING_UNCERTAIN')
        self.assertEqual(self.c._all('reviewed_plan'), [])

    def test_invalid_planner_report_flushes_over_authenticated_http(self):
        from runners.common import LocalJournal, RunnerHTTP
        proposal = self.started_planning()
        journal = LocalJournal(Path(self.tmp.name) / 'http-outbox.sqlite3')
        journal.bind_store(self.c.store_id)
        journal.start_intent(proposal['attemptId'], {'taskKind': 'plan'})
        report_id = journal.add_report(proposal['attemptId'], 'completed', self.c.store_id,
            self.pid, 'agent-test', {'stopped': True, 'result': {'response': '{"status":"READY","status":"BLOCKED"}'}})
        server = make_server(self.c, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            api = RunnerHTTP(f'http://127.0.0.1:{server.server_port}', self.state / 'runner-token', 'agent-test')
            self.assertEqual(journal.flush(api), 1)
            self.assertEqual(journal.pending(), 0)
            ack = api.request('GET', '/internal/v1/reports/' + report_id)['ack']
            self.assertEqual(ack['disposition'], 'rejected')
            self.assertEqual(self.c.project_view(self.pid)['proposal']['status'], 'FAILED')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_native_planner_feedback_decision_is_in_input_and_saved_per_item(self):
        from backend.tests.test_generic_workflow import plan_result

        ready = self.ready()
        feedback = {"feedbackId": "native-note", "objectId": "player", "category": "behavior",
                    "message": "Keep movement responsive."}
        revised = self.command('proposal.revise', {'proposalId': ready['id'], 'feedback': [feedback]},
            expected={'proposalRevision': ready['revision'], 'publicationRevision': 0,
                      'preferencesRevision': 0})['result']['proposal']
        self.assertEqual(revised['status'], 'PLANNING')
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-feedback'})
        material = self.c.runner_input('agent-test', revised['attemptId'])
        self.assertIn('feedbackDecisions', material['packet']['instruction'])
        self.assertIn('Apply every workbench operation in changeRequest.operations exactly', material['packet']['instruction'])
        self.assertEqual(material['packet']['feedback'][0]['feedbackId'], 'native-note')

        self.report(revised['attemptId'], 'started', {
            'nativeIdentity': {'threadId': 'feedback-thread', 'turnId': 'feedback-turn', 'processId': None,
                'processGroupId': None, 'processStartTime': None},
            'startedAt': datetime.now(timezone.utc).isoformat(), 'requestedProfile': None,
            'reportedProfile': None, 'threadStartReported': None, 'turnStartAcknowledged': None,
            'actualProfile': None})
        response = {**plan_result(), 'schemaVersion': 'studio.planner-result.v1',
            'feedbackDecisions': [{'feedbackId': 'native-note', 'status': 'adopted',
                'reason': 'The movement task preserves responsive control.', 'taskIds': ['harbor-loop'],
                'requirementIds': ['explore']}]}
        task_guard_calls = []
        original_guard = self.c._check_requested_fields
        def recording_guard(document, request, current_document=None, tasks=None):
            task_guard_calls.append(tasks)
            return original_guard(document, request, current_document, tasks)
        self.c._check_requested_fields = recording_guard
        ack = self.report(revised['attemptId'], 'completed', {
            'stopped': True, 'result': {'response': response}})
        self.assertEqual(ack['disposition'], 'recorded', ack)
        self.assertEqual(task_guard_calls, [response['tasks']], 'native planner completion passes the READY tasks into structural checks')

        stored = self.c._get('proposal', ready['id'])
        self.assertEqual(stored['feedbackDecisions'][0]['feedbackId'], 'native-note')
        self.assertEqual(stored['feedbackDecisions'][0]['status'], 'adopted')
        saved_feedback, = self.c._all_project('feedback', self.pid)
        self.assertEqual(saved_feedback['planDecision'], stored['feedbackDecisions'][0])

    def test_exact_review_ignores_diagnostics_and_revise_invalidates_old_packet(self):
        p = self.ready()
        view = self.c.project_view(self.pid)
        ref = view['proposal']['reviewedPlanRef']
        with self.c.transaction():
            changed = self.c._get('proposal', p['id'])
            changed['planningEvidence'] = {'stderr': ['late private diagnostic']}
            self.c._put('proposal', changed)
        frozen = self.command('proposal.freeze', {'proposalId': p['id'], 'reviewedPlanRef': ref},
            expected={'proposalRevision': 1, 'publicationRevision': 0})
        self.assertEqual(frozen['status'], 'accepted', frozen)
        revised = self.command('proposal.revise', {'proposalId': p['id'], 'supplement': 'Change the game goal.'},
            expected={'proposalRevision': 1, 'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(revised['result']['proposal']['revision'], 2)
        old = self.command('production.start', {'packetId': frozen['result']['packet']['id']},
            expected={'publicationRevision': 0, 'preferencesRevision': 0})
        self.assertEqual(old['status'], 'rejected')
        self.assertEqual(self.c._all('job'), [])

    def test_report_ack_survives_lease_change_and_late_usage_only_updates_accounting(self):
        p = self.ready()
        attempt = self.c._get('attempt', p['attemptId'])
        report_row = self.c.db.execute("SELECT content,ack FROM reports WHERE json_extract(content,'$.type')='completed'").fetchone()
        original, ack = json.loads(report_row[0]), json.loads(report_row[1])
        with self.c.transaction():
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        self.assertEqual(self.c.report_runner(original), ack)
        first = self.report(p['attemptId'], 'usage', {'totalTokens': 100, 'observedAt': '2026-10-12T01:00:00Z', 'coverage': 'native_thread'})
        self.report(p['attemptId'], 'usage', {'totalTokens': 100, 'observedAt': '2026-10-12T01:00:01Z', 'coverage': 'native_thread'})
        reset = self.report(p['attemptId'], 'usage', {'totalTokens': 10, 'observedAt': '2026-10-12T01:00:02Z', 'coverage': 'incomplete'})
        self.assertEqual(first['disposition'], 'recorded')
        self.assertEqual(reset['disposition'], 'evidence_only')
        self.assertEqual(self.c._get('attempt', p['attemptId'])['usage']['totalTokens'], 100)
        self.assertEqual(self.c._get('proposal', p['id'])['status'], 'READY')

    def test_producer_failure_diagnostic_is_projected_on_its_job(self):
        self.runner()
        cases = (
            ('confirmed-failure', 'failed', True, 'FAILED', 'PRODUCTION_FAILED', 'NEW_PLANNING'),
            ('unknown-failure', 'failed', False, 'UNCERTAIN', 'PRODUCTION_UNCERTAIN', 'RECONCILE'),
            ('confirmed-stop', 'stopped', True, 'CANCELLED', 'PRODUCTION_STOPPED', 'NEW_PLANNING'),
        )
        for suffix, report_type, stopped, expected_status, expected_code, expected_action in cases:
            with self.subTest(suffix=suffix, stopped=stopped):
                job_id = 'job-diagnostic-' + suffix
                diagnostic_ref = 'local:native-diagnostics/attempt-' + suffix
                with self.after_session_cooldown(), self.c.transaction():
                    self.c._put('job', {'id': job_id, 'projectId': self.pid, 'status': 'RUNNING',
                        'createdAt': datetime.now(timezone.utc).isoformat(), 'message': '制作中'})
                    attempt = self.c._new_attempt(self.pid, 'produce', {'kind': 'job', 'id': job_id},
                        'agent-test', input_refs={'packetId': 'packet-fixture'})
                    attempt.update(status='RUNNING', nativeIdentity={'threadId': 'fixture-thread'},
                        lease={'expiresAt': (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()})
                    self.c._put('attempt', attempt)
                    job = self.c._get('job', job_id)
                    job['attemptId'] = attempt['id']
                    self.c._put('job', job)

                ack = self.report(attempt['id'], report_type, {'stopped': stopped,
                    'stopReason': 'native_error', 'diagnosticRef': diagnostic_ref})
                self.assertEqual(ack['disposition'], 'recorded')
                view = self.c.project_view(self.pid)
                projected = next(item for item in view['jobs'] if item['id'] == job_id)
                self.assertEqual(projected['status'], expected_status)
                self.assertEqual(projected['attemptId'], attempt['id'])
                self.assertEqual(projected['productionFailure']['code'], expected_code)
                self.assertEqual(projected['productionFailure']['diagnosticRef'], diagnostic_ref)
                self.assertEqual(projected['productionFailure']['terminationConfirmed'], stopped)
                self.assertEqual(projected['productionFailure']['nextAction'], expected_action)

    def test_verification_failure_does_not_become_production_failure(self):
        self.runner()
        with self.c.transaction():
            self.c._put('job', {'id': 'job-verification-failure', 'projectId': self.pid,
                'status': 'VERIFYING', 'createdAt': datetime.now(timezone.utc).isoformat()})
            attempt = self.c._new_attempt(self.pid, 'verify', {'kind': 'job', 'id': 'job-verification-failure'},
                'agent-test', input_refs={'packetId': 'packet-fixture'})
            attempt.update(status='RUNNING', nativeIdentity={'threadId': 'fixture-thread'},
                lease={'expiresAt': (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()})
            self.c._put('attempt', attempt)
        self.report(attempt['id'], 'failed', {'stopped': True, 'stopReason': 'native_error'})
        view = self.c.project_view(self.pid)
        job = next(item for item in view['jobs'] if item['id'] == 'job-verification-failure')
        self.assertEqual(job['status'], 'FAILED')
        self.assertNotIn('productionFailure', job)

    def test_cancel_queued_attempt_releases_without_starting_model(self):
        p = self.planning()
        attempt = self.c._get('attempt', p['attemptId'])
        receipt = self.command('execution.cancel', {'attemptId': p['attemptId'], 'ownerRef': attempt['ownerRef']})
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(self.c._get('attempt', p['attemptId'])['status'], 'STOPPED')
        self.assertEqual(self.c._get('proposal', p['id'])['status'], 'CANCELLED')
        self.assertFalse(self.c._threads)

    def test_start_identity_enrichment_preserves_process_and_cancel(self):
        p = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-identity'})
        identity = {'threadId': None, 'turnId': None, 'processId': 8123,
                    'processGroupId': 8123, 'processStartTime': '2026-10-12T01:00:00Z'}
        payload = {'nativeIdentity': identity, 'startedAt': '2026-10-12T01:00:00Z',
                   'requestedProfile': None, 'reportedProfile': None,
                   'threadStartReported': None, 'turnStartAcknowledged': None, 'actualProfile': None}
        self.report(p['attemptId'], 'started', payload)
        attempt = self.c._get('attempt', p['attemptId'])
        self.command('execution.cancel', {'attemptId': p['attemptId'], 'ownerRef': attempt['ownerRef']})
        enriched = {**payload, 'nativeIdentity': {**identity, 'threadId': 'thread-original', 'turnId': 'turn-original'},
                    'startedAt': '2026-10-12T01:00:02Z'}
        self.assertEqual(self.report(p['attemptId'], 'started', enriched)['disposition'], 'recorded')
        attempt = self.c._get('attempt', p['attemptId'])
        self.assertEqual(attempt['nativeIdentity'], enriched['nativeIdentity'])
        self.assertEqual(attempt['startedAt'], payload['startedAt'])
        self.assertEqual(attempt['status'], 'CANCEL_REQUESTED')
        for changed in ({'processId': 9123}, {'turnId': 'second-turn'}, {'threadId': None}):
            with self.assertRaisesRegex(WorkflowError, '原生身份变化'):
                self.report(p['attemptId'], 'started', {**enriched, 'nativeIdentity': {**enriched['nativeIdentity'], **changed}})
        self.assertEqual(self.c._get('attempt', p['attemptId'])['nativeIdentity'], enriched['nativeIdentity'])

    def test_project_summary_retains_protocol_selection(self):
        project = next(p for p in self.c.workspace_summary()['projects'] if p['id'] == self.pid)
        self.assertEqual(project['protocolVersion'], 1)
        self.assertEqual(project['executionBackend'], 'runners')

    def test_input_setup_failure_releases_expired_attempt_without_replaying_it(self):
        proposal = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-setup'})
        with self.c.transaction():
            attempt = self.c._get('attempt', proposal['attemptId'])
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        payload = {'stopped': True, 'stopReason': 'native_error', 'launchPrevented': True,
                   'diagnosticRef': 'local:setup-diagnostics/' + proposal['attemptId']}
        ack = self.report(proposal['attemptId'], 'failed', payload, report_id='setup-failure')
        self.assertEqual(ack['disposition'], 'recorded')
        self.assertEqual(self.report(proposal['attemptId'], 'failed', payload, report_id='setup-failure'), ack)
        attempt = self.c._get('attempt', proposal['attemptId'])
        self.assertEqual(attempt['status'], 'FAILED')
        self.assertIsNone(attempt['nativeIdentity'])
        view = self.c.project_view(self.pid)
        self.assertTrue(view['proposal']['planningFailure']['retryable'])
        self.assertTrue(view['proposal']['planningTerminationConfirmed'])
        self.assertEqual(view['proposal']['text'], proposal['text'])
        self.assertEqual(len(self.c._all('attempt')), 1)
        claim = self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-after-setup'})
        self.assertIsNone(claim['request'], 'a failed setup must wait for an explicit new planning command')

    def test_late_setup_claim_cannot_replace_observed_native_identity(self):
        proposal = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-setup-conflict'})
        identity = {'threadId': 'original-thread', 'turnId': 'original-turn', 'processId': 8123,
                    'processGroupId': 8123, 'processStartTime': '2026-10-12T01:00:00Z'}
        self.report(proposal['attemptId'], 'started', {'nativeIdentity': identity,
            'startedAt': identity['processStartTime'], 'requestedProfile': None, 'reportedProfile': None,
            'threadStartReported': None, 'turnStartAcknowledged': None, 'actualProfile': None})
        with self.c.transaction():
            attempt = self.c._get('attempt', proposal['attemptId'])
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        with self.assertRaisesRegex(WorkflowError, '已有原生启动身份'):
            self.report(proposal['attemptId'], 'failed', {'stopped': True, 'stopReason': 'native_error', 'launchPrevented': True})
        self.assertEqual(self.c._get('attempt', proposal['attemptId'])['nativeIdentity'], identity)
        self.assertFalse(self.c._get('proposal', proposal['id']).get('planningTerminationConfirmed', False))

    def test_late_failure_without_prelaunch_fact_keeps_unknown_occupancy(self):
        proposal = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-unknown-setup'})
        with self.c.transaction():
            attempt = self.c._get('attempt', proposal['attemptId'])
            attempt['lease']['expiresAt'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            self.c._put('attempt', attempt)
        ack = self.report(proposal['attemptId'], 'failed', {'stopped': True, 'stopReason': 'native_error'})
        self.assertEqual(ack['disposition'], 'evidence_only')
        self.assertEqual(self.c._get('attempt', proposal['attemptId'])['status'], 'UNKNOWN')
        self.assertFalse(self.c._get('proposal', proposal['id']).get('planningTerminationConfirmed', False))

    def test_lost_first_start_ack_after_restart_retains_identity_for_reconcile(self):
        p = self.planning()
        self.c.claim_runner({'storeId': self.c.store_id, 'runnerId': 'agent-test', 'commandId': 'claim-outage'})
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=True)
        identity = {'threadId': 'original-thread', 'turnId': 'original-turn', 'processId': 8123,
                    'processGroupId': 8123, 'processStartTime': '2026-10-12T01:00:00Z'}
        ack = self.report(p['attemptId'], 'started', {'nativeIdentity': identity,
            'startedAt': identity['processStartTime'], 'requestedProfile': None, 'reportedProfile': None,
            'threadStartReported': None, 'turnStartAcknowledged': None, 'actualProfile': None})
        self.assertEqual(ack['disposition'], 'evidence_only')
        self.assertEqual(self.c._get('attempt', p['attemptId'])['status'], 'UNKNOWN')
        self.assertEqual(self.c._get('proposal', p['id'])['status'], 'PLANNING_UNCERTAIN')
        result = self.c.reconcile_runner({'runnerId': 'agent-test', 'storeId': self.c.store_id,
            'attemptId': p['attemptId'], 'nativeIdentity': identity, 'stopped': True})
        self.assertEqual(result['status'], 'STOPPED')
        self.assertEqual(self.c._get('proposal', p['id'])['status'], 'CANCELLED')

    def test_restart_preserves_command_namespace_and_changes_service_identity(self):
        old_store, old_instance = self.c.store_id, self.c.service_instance_id
        self.c.close()
        self.c = Coordinator(REPO_ROOT, state_root=self.state, test_data=True)
        self.assertEqual(self.c.store_id, old_store)
        self.assertNotEqual(self.c.service_instance_id, old_instance)
        self.assertTrue(self.c.command_lookup(None, 'command-1', self.c.operator_id)['known'])


class StudioV1HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Coordinator(REPO_ROOT, state_root=Path(self.tmp.name)/'state', test_data=True)
        self.server = make_server(self.c, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.c.close(); self.tmp.cleanup()

    def request(self, path, body=None, token=None):
        headers = {'Origin': self.base}
        if token: headers['X-Workbench-Token'] = token
        if body is not None: headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_handshake_write_auth_and_persistent_creation_receipt(self):
        _, h = self.request('/api/v1/handshake')
        body = {'schemaVersion': 'studio.message.v1', 'kind': 'command', 'type': 'project.create', 'storeId': h['storeId'], 'commandId': 'one', 'payload': {'name': 'HTTP'}}
        status, error = self.request('/api/v1/projects', body, token='stale')
        self.assertEqual(status, 403); self.assertEqual(error['kind'], 'error')
        status, receipt = self.request('/api/v1/projects', body, token=h['writeToken'])
        self.assertEqual(status, 200, receipt)
        _, lookup = self.request('/api/v1/commands/one')
        self.assertEqual(lookup['receipt'], receipt)
        _, view = self.request('/api/v1/projects/'+receipt['resource']['id']+'/view')
        self.assertEqual(view['schemaVersion'], 'studio.project-view.v1')
        self.assertEqual(view['step'], 'concept')

    def test_user_write_token_cannot_call_runner_control(self):
        request = urllib.request.Request(self.base+'/internal/v1/handshake', headers={'X-Runner-Token': self.server.context.token})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)

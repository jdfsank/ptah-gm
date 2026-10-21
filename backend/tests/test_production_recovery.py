import copy
import json
import unittest
from pathlib import Path

from backend.coordinator import git
from backend.tests import test_studio_delivery as delivery_fixture


class ProductionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = delivery_fixture.StudioDeliveryTests()
        self.f.setUp()
        job, self.ref, self.repo, _ = self.f.candidate()
        self.job = job
        self.attempt = self.f.c._get('attempt', job['productionAttemptId'])
        self.attempt.update(status='FAILED', diagnosticRef='local:seal-diagnostics/' + self.attempt['id'])
        self.job.update(status='FAILED', attemptId=self.attempt['id'])
        self.job.pop('candidate', None)
        with self.f.c.transaction():
            self.f.c._put('job', self.job)
            self.f.c._put('attempt', self.attempt)

    def tearDown(self):
        self.f.tearDown()

    def recover(self, **overrides):
        payload = {'jobId': self.job['id'], 'attemptId': self.attempt['id'], 'artifactRef': self.ref}
        payload.update(overrides)
        return self.f.command('production.recover', payload, expected={'publicationRevision': 0})

    def test_retains_failure_and_approval_then_queues_independent_verification(self):
        before = self.f.c.db.execute('SELECT id,payload,consumed FROM approvals').fetchall()
        receipt = self.recover()
        self.assertEqual(receipt['status'], 'accepted', receipt)
        job = receipt['result']['job']
        self.assertEqual(job['status'], 'VERIFYING')
        self.assertNotEqual(job['verificationAttemptId'], self.job['verificationAttemptId'])
        self.assertFalse(job['sealRecovery']['nativeRerun'])
        self.assertEqual(self.f.c._get('attempt', self.attempt['id']), self.attempt)
        self.assertEqual(before, self.f.c.db.execute('SELECT id,payload,consumed FROM approvals').fetchall())
        self.assertNotIn('candidate', job)

    def test_rejects_native_failure_and_cancelled_or_uncertain_execution(self):
        for change in [{'diagnosticRef': 'local:native-diagnostics/' + self.attempt['id']}, {'cancelRequested': True}, {'status': 'UNCERTAIN'}]:
            altered = {**self.attempt, **change}
            with self.f.c.transaction():
                self.f.c._put('attempt', altered)
            receipt = self.recover()
            self.assertEqual(receipt['error']['code'], 'RECOVERY_NOT_ALLOWED', receipt)

    def test_rejects_stale_frozen_scope(self):
        packet = self.f.c._get('packet', self.job['packetId'])
        proposal = self.f.c._get('proposal', packet['proposalId'])
        proposal['status'] = 'READY'
        proposal['revision'] += 1
        with self.f.c.transaction():
            self.f.c._put('proposal', proposal)
        self.assertEqual(self.recover()['error']['code'], 'STALE_PACKET')

    def test_rejects_foreign_artifact_and_protected_design_changes(self):
        foreign = {**self.ref, 'attemptId': 'attempt-other'}
        self.assertEqual(self.recover(artifactRef=foreign)['error']['code'], 'DELIVERY_BINDING')
        (self.repo / 'design/game.json').write_text('{}\n')
        git(self.repo, 'add', '--', 'design/game.json')
        git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@localhost', 'commit', '-qm', 'Forbidden design drift')
        altered = {**self.ref, 'sourceCommit': git(self.repo, 'rev-parse', 'HEAD')}
        self.assertEqual(self.recover(artifactRef=altered)['error']['code'], 'PROTECTED_DRIFT')
        self.assertEqual(self.f.c._get('job', self.job['id'])['status'], 'FAILED')

    def test_recovery_command_matches_published_schema(self):
        from jsonschema import Draft202012Validator
        from backend.object_protocol import validate_command
        message = self.f.envelope('production.recover', {'jobId': self.job['id'], 'attemptId': self.attempt['id'], 'artifactRef': self.ref}, expected={'publicationRevision': 0})
        schema = json.loads((self.f.c.root / 'contracts/studio/message.v1.schema.json').read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(message)), [])
        self.assertEqual(validate_command(message)['payload']['artifactRef'], self.ref)

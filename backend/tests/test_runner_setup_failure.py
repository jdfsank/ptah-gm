import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.object_protocol import validate_execution_report
from runners.agent import AgentRunner
from runners.common import LocalJournal, RunnerError


class SetupAPI:
    def __init__(self, material=None, error=None):
        self.material, self.error, self.reports = material, error, []

    def request(self, method, route, body=None):
        if route.endswith('/input'):
            if self.error:
                raise self.error
            return self.material
        self.reports.append(body)
        validate_execution_report(body)
        return {'schemaVersion': 'studio.message.v1', 'kind': 'report_ack',
                **{key: body[key] for key in ('storeId', 'projectId', 'attemptId', 'runnerId', 'reportId')},
                'disposition': 'recorded'}


class RunnerSetupFailureTests(unittest.TestCase):
    def test_sandbox_failure_is_no_launch_with_durable_diagnostics_and_no_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api = SetupAPI()
            journal = LocalJournal(root / 'journal.sqlite3')
            journal.bind_store('store-setup')
            runner = AgentRunner(api, journal, root / 'workspaces', root / 'artifacts', root / 'protected')
            request = {'attemptId': 'attempt-probe', 'projectId': 'project-setup',
                       'storeId': 'store-setup', 'taskKind': 'plan'}
            evidence = {'passed': False, 'status': 'NOT_READY', 'approvalNetworkDenied': False,
                        'detail': 'NETWORK_ALLOWED:127.0.0.1'}
            with mock.patch('runners.agent.sandbox_probe', return_value=evidence), \
                 mock.patch('runners.agent.subprocess.Popen') as spawn:
                self.assertFalse(runner.accept_claim(request, 'store-setup'))
                spawn.assert_not_called()
                with self.assertRaisesRegex(RunnerError, 'launch-intent'):
                    runner.accept_claim(request, 'store-setup')
            report = api.reports[0]
            self.assertTrue(report['payload']['launchPrevented'])
            self.assertTrue(report['payload']['stopped'])
            self.assertEqual(journal.pending(), 0)
            self.assertFalse((root / 'workspaces/attempt-probe').exists())
            reopened = LocalJournal(root / 'journal.sqlite3')
            with reopened._connect() as db:
                diagnostic = db.execute('SELECT value FROM metadata WHERE key=?',
                    (report['payload']['diagnosticRef'],)).fetchone()[0]
                identity = db.execute('SELECT native_identity FROM attempts').fetchone()[0]
            self.assertEqual(json.loads(diagnostic), evidence)
            self.assertIsNone(identity)

    def test_input_and_spawn_failures_report_no_launch_and_do_not_reuse_attempt(self):
        for mode in ('input', 'invalid-image', 'spawn'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                material = {'attemptId': 'attempt-setup', 'packet': {}, 'assets': []}
                if mode == 'invalid-image':
                    material['assets'] = [{'name': 'image.png', 'mimeType': 'image/png', 'dataBase64': 'invalid!'}]
                api = SetupAPI(material, RunnerError('response exceeds the configured byte limit') if mode == 'input' else None)
                journal = LocalJournal(root / 'journal.sqlite3')
                journal.bind_store('store-setup')
                runner = AgentRunner(api, journal, root / 'workspaces', root / 'artifacts', root / 'protected')
                request = {'attemptId': 'attempt-setup', 'projectId': 'project-setup',
                           'storeId': 'store-setup', 'taskKind': 'plan'}
                with mock.patch('runners.agent.sandbox_probe', return_value={'passed': True}), \
                     mock.patch('runners.agent.subprocess.Popen', side_effect=OSError('worker exec failed')) as spawn:
                    self.assertFalse(runner.accept_claim(request, 'store-setup'))
                    self.assertEqual(spawn.call_count, 1 if mode == 'spawn' else 0)
                    with self.assertRaisesRegex(RunnerError, 'launch-intent'):
                        runner.accept_claim(request, 'store-setup')
                    self.assertEqual(spawn.call_count, 1 if mode == 'spawn' else 0)
                self.assertEqual(len(api.reports), 1)
                report = api.reports[0]
                self.assertEqual(report['type'], 'failed')
                self.assertTrue(report['payload']['launchPrevented'])
                self.assertTrue(report['payload']['stopped'])
                self.assertEqual(journal.pending(), 0)
                self.assertFalse((root / 'workspaces/attempt-setup').exists())
                with journal._connect() as db:
                    identity = db.execute('SELECT native_identity FROM attempts').fetchone()[0]
                    diagnostic = db.execute('SELECT value FROM metadata WHERE key=?',
                                            (report['payload']['diagnosticRef'],)).fetchone()[0]
                self.assertIsNone(identity)
                self.assertTrue(json.loads(diagnostic)['message'])
                self.assertTrue(json.loads(diagnostic)['workspaceCleanupConfirmed'])

    def test_large_reference_is_materialized_without_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'\x89PNG\r\n\x1a\n' + b'x' * (3 * 1024 * 1024)
            material = {'attemptId': 'attempt-image', 'packet': {}, 'assets': [
                {'name': 'image.png', 'mimeType': 'image/png', 'dataBase64': base64.b64encode(data).decode()}]}
            journal = LocalJournal(root / 'journal.sqlite3')
            runner = AgentRunner(SetupAPI(material), journal, root / 'workspaces', root / 'artifacts', root / 'protected')
            prepared = runner._prepare_claim({'attemptId': 'attempt-image', 'taskKind': 'plan'})
            images = prepared[2]['material']['referenceImages']
            self.assertEqual(len(images), 1)
            self.assertEqual(Path(images[0]).read_bytes(), data)

    def test_no_launch_fact_requires_failed_agent_report_and_confirmed_stop(self):
        base = {'schemaVersion': 'studio.message.v1', 'kind': 'execution_report', 'type': 'failed',
                'storeId': 'store-a', 'projectId': 'project-a', 'runnerId': 'runner-a',
                'attemptId': 'attempt-a', 'reportId': 'report-a', 'taskKind': 'plan',
                'payload': {'stopped': True, 'stopReason': 'native_error', 'launchPrevented': True}}
        validate_execution_report(base)
        for changes in ({'launchPrevented': False}, {'launchPrevented': 1}, {'stopped': False}, {'stopReason': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_execution_report({**base, 'payload': {**base['payload'], **changes}})
        for changes in ({'taskKind': 'verify'}, {'taskKind': 'preview'}, {'type': 'stopped'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_execution_report({**base, **changes})


if __name__ == '__main__':
    unittest.main()

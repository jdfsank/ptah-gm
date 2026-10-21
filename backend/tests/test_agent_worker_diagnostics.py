import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runners import agent_worker


class AgentWorkerDiagnosticsTests(unittest.TestCase):
    def test_driver_and_setup_errors_emit_bridge_metadata_before_close(self):
        for stage in ("create", "images", "tools", "driver", "host", "run", "close"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                bridge = mock.Mock()
                bridge.diagnostic_summary.return_value = {
                    "requestCount": 1, "failureCount": 1, "timeoutSeconds": 300,
                    "failures": [{"kind": "timeout", "httpStatus": None, "responseStarted": False}],
                }
                context = SimpleNamespace(root=Path(directory), bridge=bridge,
                                          stage_images=mock.Mock(return_value=[]), close=mock.Mock(),
                                          executable=mock.Mock(return_value='synthetic-native'),
                                          command=mock.Mock())
                exception = RuntimeError("SYNTHETIC_PRIVATE_ERROR_BODY")
                driver = mock.Mock()
                driver.run.return_value = {"status": "failed", "diagnostics": {}}
                if stage == "images":
                    context.stage_images.side_effect = exception
                if stage == "run":
                    driver.run.side_effect = exception
                if stage == "close":
                    context.close.side_effect = exception
                if stage == "host":
                    context.command.side_effect = exception
                request = {"execution": {"taskKind": "produce", "profileSnapshot": {}},
                           "material": {"packet": {"allowedFiles": []}}}
                emitted = []

                def emit(event, **fields):
                    emitted.append({"event": event, **fields})
                    if event == "diagnostic":
                        context.close.assert_not_called()

                with mock.patch("sys.argv", ["agent_worker", directory]), \
                     mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
                     mock.patch("runners.agent_worker.signal.signal"), \
                     mock.patch("runners.agent_worker._emit", side_effect=emit), \
                     mock.patch("runners.native_adapter.ManagedNativeContext.create", return_value=context,
                                side_effect=exception if stage == "create" else None), \
                     mock.patch("runners.static_tools.StaticToolBroker",
                                side_effect=exception if stage == "tools" else None), \
                     mock.patch("backend.codex_driver.CodexDriver", return_value=driver,
                                side_effect=exception if stage == "driver" else None):
                    if stage in ('run', 'close'):
                        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_PRIVATE"):
                            agent_worker.main()
                    else:
                        agent_worker.main()
                if stage == 'create':
                    context.close.assert_not_called()
                else:
                    context.close.assert_called_once()
                expected = ([] if stage == 'create' else ['diagnostic'])
                if stage not in ('run', 'close'):
                    expected.append('setupFailed')
                    driver.run.assert_not_called()
                self.assertEqual([item["event"] for item in emitted], expected)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(emitted))
                if stage != 'create':
                    self.assertEqual(emitted[0]["providerBridge"]["failures"][0]["kind"], "timeout")


if __name__ == "__main__":
    unittest.main()

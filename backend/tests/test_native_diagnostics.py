import json
import tempfile
import unittest
from pathlib import Path

from runners.agent import AgentRunner
from runners.common import LocalJournal
from runners.native_diagnostics import native_diagnostic_summary


class NativeDiagnosticsTests(unittest.TestCase):
    def test_classifies_errors_without_retaining_private_strings_or_error_bodies(self):
        private = "SYNTHETIC_PRIVATE_CREDENTIAL_REQUEST_RESPONSE"
        result = {"status": "failed", "response": private, "diagnostics": {
            "elapsedSeconds": 557.3, "childTerminationConfirmed": True,
            "stderr": [private], "error": private,
            "nativeErrors": [{"message": "stream disconnected " + private,
                              "willRetry": True, "privatePayload": private,
                              "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 502}}}],
            "nativeTurnError": {"message": "context window exceeded " + private,
                                "detail": private},
            "providerBridge": {"requestCount": 3, "failureCount": 2, "timeoutSeconds": 300,
                "failures": [{"kind": "http_error", "httpStatus": 429, "responseStarted": False,
                              "observedAt": "2026-10-13T06:10:52Z", "message": private,
                              "url": private, "headers": {"Authorization": private}}]},
        }}
        summary = native_diagnostic_summary(result, worker_exit_code=0)
        self.assertNotIn(private, json.dumps(summary))
        self.assertEqual(summary["nativeErrors"], [{"reason": "stream_interrupted", "willRetry": True, "httpStatus": 502}])
        self.assertEqual(summary["nativeTurnError"], {"reason": "context_limit"})
        self.assertTrue(summary["childTerminationConfirmed"])
        self.assertEqual(summary["providerBridge"]["failures"][0]["httpStatus"], 429)
        self.assertEqual(summary["providerBridge"]["failures"][0]["observedAt"], "2026-10-13T06:10:52Z")

    def test_unknown_or_malformed_fields_are_bounded_and_never_copied_verbatim(self):
        summary = native_diagnostic_summary({"status": ["failed"], "diagnostics": {
            "elapsedSeconds": float("nan"), "stderr": "private",
            "nativeErrors": [{"message": "private"}] * 100,
            "nativeTurnError": {"message": "private", "code": "private"},
            "providerBridge": {"timeoutSeconds": 2 ** 1000,
                               "failures": [{"kind": [], "httpStatus": True, "observedAt": "private"}] * 100},
        }}, stop_reason=[])
        self.assertIsNone(summary["nativeStatus"])
        self.assertIsNone(summary["elapsedSeconds"])
        self.assertEqual(summary["nativeErrorCount"], 100)
        self.assertEqual(len(summary["nativeErrors"]), 20)
        self.assertEqual(len(summary["providerBridge"]["failures"]), 20)
        self.assertNotIn("private", json.dumps(summary))
        self.assertLess(len(json.dumps(summary)), 8192)

    def test_diagnostic_survives_journal_reopen_at_exact_failure_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / "journal.sqlite3")
            runner = AgentRunner(None, journal, root / "workspaces", root / "artifacts", root / "protected")
            ref = runner._persist_native_diagnostics("attempt-fixture", {"status": "failed", "diagnostics": {
                "childTerminationConfirmed": True, "nativeTurnError": {"message": "provider rejected request"}}},
                0, None, None)
            reopened = LocalJournal(root / "journal.sqlite3")
            with reopened._connect() as db:
                row = db.execute("SELECT value FROM metadata WHERE key=?", (ref,)).fetchone()
            self.assertEqual(ref, "local:native-diagnostics/attempt-fixture")
            self.assertEqual(json.loads(row[0])["nativeTurnError"], {"reason": "provider_rejected"})


if __name__ == "__main__":
    unittest.main()

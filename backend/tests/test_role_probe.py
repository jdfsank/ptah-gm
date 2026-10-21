from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.role_evidence import REQUIRED_ROLE_CHECKS
from runners.agent import AgentRunner
from runners.common import LocalJournal
from runners.role_probe import run_agent_role_probe


class _API:
    def __init__(self):
        self.requests = []

    def request(self, method, route, body=None):
        self.requests.append((method, route, body))
        return {"registered": True}


class RoleProbeTests(unittest.TestCase):
    def test_failure_emits_fresh_runner_bound_false_checks_without_model_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            false_tool_checks = {name: False for name in REQUIRED_ROLE_CHECKS["planning-readonly-v1"]
                                 if name.startswith("tool")}
            false_role_tool_checks = dict(false_tool_checks)
            false_role_checks = {"plannerWriteToolNotExposed": False, "plannerWriteRejected": False,
                                 "producerScopedWriteAllowed": False,
                                 "producerOutOfScopeWriteDenied": False}
            with patch("runners.role_probe._configured_model_provider", return_value="fixture"), \
                 patch("runners.role_probe._probe_static_roles",
                       return_value=({"planning": false_tool_checks,
                                      "production": false_role_tool_checks}, false_role_checks)), \
                 patch("runners.role_probe.ManagedNativeContext.create",
                       side_effect=RuntimeError("unavailable")), \
                 patch("runners.role_probe.CodexDriver.model_catalog") as catalog:
                result = run_agent_role_probe("runner-probe-fixture", root)

        evidence = result["evidence"]
        self.assertEqual(evidence["schemaVersion"], "studio.role-probe.v1")
        self.assertEqual(evidence["runnerKind"], "agent")
        self.assertEqual(evidence["runnerId"], "runner-probe-fixture")
        self.assertTrue(evidence["probeId"])
        self.assertTrue(evidence["observedAt"].endswith("Z"))
        self.assertEqual(evidence["verifiedCapabilities"], [])
        self.assertEqual(evidence["status"], "NOT_VERIFIED")
        for capability in ("planning-readonly-v1", "production-private-v1"):
            checks = evidence["roles"][capability]["checks"]
            self.assertEqual(set(checks), set(REQUIRED_ROLE_CHECKS[capability]))
            self.assertTrue(all(type(value) is bool and value is False for value in checks.values()))
        catalog.assert_not_called()

    def test_registration_posts_only_probe_verified_capabilities_and_runner_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalJournal(root / "runner.sqlite3")
            runner_id = journal.runner_id
            api = _API()
            runner = AgentRunner(api, journal, root / "workspaces", root / "artifacts",
                                 root / "protected")
            evidence = {"schemaVersion": "studio.role-probe.v1", "runnerKind": "agent",
                        "runnerId": runner_id, "probeId": "probe-test", "observedAt": "now",
                        "verifiedCapabilities": ["planning-readonly-v1"],
                        "roles": {}, "status": "PASS"}
            catalog = {"models": [], "nativeVersion": "fixture", "environment": "fixture"}
            with patch("runners.role_probe.run_agent_role_probe",
                       return_value={"evidence": evidence, "catalog": catalog}) as probe:
                runner.register()

        probe.assert_called_once_with(runner_id, runner.workspace_root)
        body = api.requests[0][2]
        self.assertEqual(body["runnerId"], runner_id)
        self.assertEqual(body["capabilities"], ["planning-readonly-v1"])
        self.assertIs(body["sandboxEvidence"], evidence)


if __name__ == "__main__":
    unittest.main()

"""Keep the published Studio JSON Schemas aligned with real backend objects."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

try:
    from jsonschema import Draft202012Validator, RefResolver
except ImportError:  # Schema validation is an optional test extra on minimal installs.
    Draft202012Validator = None
    RefResolver = None

from backend.coordinator import Coordinator
from backend.object_protocol import parse_planner_response
from backend.server import REPO_ROOT, make_server
from backend.tests.test_generic_workflow import plan_result
from backend.tests.test_object_protocol import workbench_document
from backend.tests.test_studio_protocol import fixture_role_evidence
from backend.tests import test_studio_delivery as delivery_fixture


CONTRACTS = REPO_ROOT / "contracts" / "studio"


@unittest.skipIf(Draft202012Validator is None, "install jsonschema to run shared schema parity tests")
class StudioSchemaParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {}
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            cls.schemas[path.name.removesuffix(".schema.json")] = schema
        cls.schema_store = {schema["$id"]: schema for schema in cls.schemas.values() if "$id" in schema}

    def assert_schema(self, name, instance):
        resolver = RefResolver.from_schema(self.schemas[name], store=self.schema_store)
        errors = sorted(Draft202012Validator(self.schemas[name], resolver=resolver).iter_errors(instance),
                        key=lambda error: list(map(str, error.absolute_path)))
        self.assertEqual(errors, [], "\n".join(
            f"{list(error.absolute_path)}: {error.message}" for error in errors
        ))

    def test_image_preview_accepts_a_bound_resource_without_legacy_image_path(self):
        document = workbench_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        resource = "resources/player_frames.tres"
        player["sourceBindings"].append(resource)
        player["workbench"]["preview"].update(type="image", resourcePath=resource)

        self.assert_schema("objects.v1", document)
        player["workbench"]["preview"].pop("resourcePath")
        self.assertFalse(Draft202012Validator(self.schemas["objects.v1"]).is_valid(document))

    def test_geometry_field_bindings_match_the_published_object_schema(self):
        document = workbench_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        player["workbench"].update(positionFieldId="spawn", sizeFieldId="spawn")
        self.assert_schema("objects.v1", document)
        player["workbench"]["positionFieldId"] = "Position Field"
        self.assertFalse(Draft202012Validator(self.schemas["objects.v1"]).is_valid(document))

    def test_preview_field_bindings_match_the_published_object_schema(self):
        document = workbench_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        player["workbench"]["preview"].update(speed=180, speedFieldId="speed", stages=[
            {"label": "Move", "duration": 1.5, "durationFieldId": "speed"},
        ])

        self.assert_schema("objects.v1", document)
        player["workbench"]["preview"]["speedFieldId"] = "Move Speed"
        self.assertFalse(Draft202012Validator(self.schemas["objects.v1"]).is_valid(document))

    def test_state_transition_facts_match_the_published_object_schema(self):
        from backend.object_protocol import validate_document
        document = workbench_document()
        player = next(obj for obj in document["objects"] if obj["id"] == "player")
        player["workbench"].update(fromState="running", toState="upgrade")
        self.assert_schema("objects.v1", document)
        validate_document(document)
        player["workbench"]["toState"] = ""
        self.assertFalse(Draft202012Validator(self.schemas["objects.v1"]).is_valid(document))
        with self.assertRaises(ValueError):
            validate_document(document)

    def test_prelaunch_failure_fact_matches_python_validation(self):
        from backend.object_protocol import validate_execution_report
        report = {'schemaVersion': 'studio.message.v1', 'kind': 'execution_report', 'type': 'failed',
                  'storeId': 'store-a', 'projectId': 'project-a', 'runnerId': 'runner-a',
                  'attemptId': 'attempt-a', 'reportId': 'report-a', 'taskKind': 'plan',
                  'payload': {'stopped': True, 'stopReason': 'native_error', 'launchPrevented': True}}
        self.assert_schema('message.v1', report)
        validate_execution_report(report)
        for invalid in (
            {**report, 'taskKind': 'verify'},
            {**report, 'type': 'stopped'},
            {**report, 'payload': {**report['payload'], 'launchPrevented': False}},
            {**report, 'payload': {**report['payload'], 'stopped': False}},
            {**report, 'payload': {**report['payload'], 'stopReason': 'unknown'}},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(Draft202012Validator(self.schemas['message.v1']).is_valid(invalid))
                with self.assertRaises(ValueError):
                    validate_execution_report(invalid)

    def test_native_failure_summary_is_closed_and_matches_python_validation(self):
        import copy
        from backend.object_protocol import ObjectProtocolError, validate_execution_report
        report = {"schemaVersion": "studio.message.v1", "kind": "execution_report", "type": "failed",
            "storeId": "s", "projectId": "p", "runnerId": "r", "reportId": "report", "attemptId": "attempt",
            "taskKind": "produce", "payload": {"stopped": True, "stopReason": "native_error",
                "nativeFailure": {"reason": "stream_interrupted", "nativeStatus": "uncertain", "elapsedSeconds": 16.662,
                                  "connectionInterrupted": True}}}
        self.assert_schema("message.v1", validate_execution_report(report))
        for change in ({"reason": "RAW_PROVIDER_BODY"}, {"reason": []}, {"nativeStatus": []},
                       {"elapsedSeconds": -1}, {"elapsedSeconds": True}, {"rawBody": "PRIVATE"},
                       {"connectionInterrupted": "yes"}):
            invalid = copy.deepcopy(report)
            invalid["payload"]["nativeFailure"].update(change)
            with self.assertRaises(ObjectProtocolError):
                validate_execution_report(invalid)
            self.assertFalse(Draft202012Validator(self.schemas["message.v1"]).is_valid(invalid))

    def test_schemas_accept_blank_project_command_report_and_planner_result(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = Coordinator(REPO_ROOT, state_root=Path(directory) / "state", test_data=True)
            try:
                create = {
                    "schemaVersion": "studio.message.v1", "kind": "command",
                    "type": "project.create", "storeId": coordinator.store_id,
                    "commandId": "create-parity", "payload": {"name": "Parity fixture"},
                }
                receipt = coordinator.submit_command(create, operator_id=coordinator.operator_id)
                project_id = receipt["result"]["project"]["id"]
                view = coordinator.project_view(project_id)
                self.assertIsNone(view["proposal"])
                self.assert_schema("project-view.v1", view)

                rename = {
                    "schemaVersion": "studio.message.v1", "kind": "command",
                    "type": "project.settings.update", "storeId": coordinator.store_id,
                    "projectId": project_id, "commandId": "rename-parity",
                    "payload": {"name": "Parity fixture renamed"},
                }
                self.assert_schema("message.v1", rename)
                coordinator.submit_command(rename, operator_id=coordinator.operator_id,
                                           project_id=project_id)

                evidence = fixture_role_evidence("schema-runner", "agent", ["planning-readonly-v1"])
                coordinator.register_runner({
                    "runnerId": "schema-runner", "runnerKind": "agent", "environment": "test",
                    "nativeVersion": "fixture", "capabilities": ["planning-readonly-v1"],
                    "sandboxEvidence": evidence,
                })
                coordinator.update_runner_catalog({
                    "runnerId": "schema-runner", "catalogRevision": 1,
                    "observedAt": datetime.now(timezone.utc).isoformat(),
                    "models": [{"modelKey": "schema-model", "modelProvider": "fixture",
                                "supportedReasoningEfforts": ["medium"],
                                "inputModalities": ["text"], "isDefault": True}],
                })
                planning = {
                    "schemaVersion": "studio.message.v1", "kind": "command",
                    "type": "concept.submit", "storeId": coordinator.store_id,
                    "projectId": project_id, "commandId": "plan-parity",
                    "expected": {"preferencesRevision": 0, "publicationRevision": 0,
                                 "sourceCommit": None},
                    "payload": {"text": "A tiny game for schema parity.", "assetRefs": []},
                }
                self.assert_schema("message.v1", planning)
                proposal = coordinator.submit_command(planning, operator_id=coordinator.operator_id,
                                                       project_id=project_id)["result"]["proposal"]
                claim = coordinator.claim_runner({"storeId": coordinator.store_id,
                    "runnerId": "schema-runner", "commandId": "claim-parity"})
                self.assertEqual(claim["request"]["attemptId"], proposal["attemptId"])
                attempt = coordinator._get("attempt", proposal["attemptId"])
                frozen = attempt["profileSnapshot"]
                report = {
                    "schemaVersion": "studio.message.v1", "kind": "execution_report",
                    "type": "started", "storeId": coordinator.store_id, "projectId": project_id,
                    "runnerId": "schema-runner", "reportId": "report-start-parity",
                    "attemptId": proposal["attemptId"], "taskKind": "plan",
                    "payload": {
                        "nativeIdentity": {"threadId": "thread-parity", "turnId": "turn-parity",
                            "processId": None, "processGroupId": None, "processStartTime": None},
                        "startedAt": datetime.now(timezone.utc).isoformat(),
                        "requestedProfile": {"modelKey": frozen["modelKey"],
                            "modelProvider": frozen["modelProvider"], "effort": frozen["effort"]},
                        "reportedProfile": None,
                        "threadStartReported": {"model": frozen["modelKey"],
                            "provider": frozen["modelProvider"], "reasoningEffort": frozen["effort"]},
                        "turnStartAcknowledged": {"turnId": "turn-parity", "status": None},
                        "actualProfile": None,
                    },
                }
                self.assert_schema("message.v1", report)
                coordinator.report_runner(report)

                planner = plan_result()
                planner.update(schemaVersion="studio.planner-result.v1", feedbackDecisions=[])
                planner = parse_planner_response(planner, expected_feedback=[])
                self.assert_schema("planner-result.v1", planner)

                semantic = plan_result()
                semantic["document"] = workbench_document()
                semantic.update(schemaVersion="studio.planner-result.v1", feedbackDecisions=[])
                semantic = parse_planner_response(semantic, expected_feedback=[])
                self.assert_schema("planner-result.v1", semantic)
                self.assert_schema("objects.v1", semantic["document"])

                operation_command = {
                    "schemaVersion": "studio.message.v1", "kind": "command", "type": "iteration.submit",
                    "storeId": coordinator.store_id, "projectId": project_id, "commandId": "operation-parity",
                    "expected": {"preferencesRevision": 0, "publicationRevision": 0, "sourceCommit": None},
                    "payload": {"text": "", "assetRefs": [], "targetObjectIds": ["player-instance", "draft-scene-1", "draft-instance-1"],
                        "fields": [], "feedback": [{"feedbackId": "draft-scene-feedback", "objectId": "draft-scene-1",
                            "message": "Add an entrance note.", "category": "general"}], "operations": [
                            {"operationId": "move-start", "kind": "move", "objectId": "player-instance",
                                "requested": [50, 60], "lock": "free"},
                            {"operationId": "create-scene", "kind": "new-scene", "sceneId": "draft-scene-1",
                                "name": "Bonus room", "template": "blank", "bounds": [800, 600]},
                            {"operationId": "create-instance", "kind": "new-instance", "instanceId": "draft-instance-1",
                                "name": "Bonus player", "definitionId": "player", "sceneId": "draft-scene-1",
                                "requestedPosition": [300, 200], "size": [32, 48], "anchor": [0.5, 0.5], "lock": "free"}]}}
                self.assert_schema("message.v1", operation_command)
                explicit_lock = json.loads(json.dumps(operation_command))
                explicit_lock["payload"]["operations"].append({"operationId": "protect-start", "kind": "set-lock",
                    "objectId": "player-instance", "before": "free", "lock": "nudge"})
                self.assert_schema("message.v1", explicit_lock)
                missing_position = json.loads(json.dumps(operation_command))
                missing_position["payload"]["operations"][-1].pop("requestedPosition")
                self.assertFalse(Draft202012Validator(self.schemas["message.v1"]).is_valid(missing_position),
                    "new-instance operations must declare their world position before submission")
            finally:
                coordinator.close()

    def test_project_view_schema_accepts_full_candidate_projection(self):
        fixture = delivery_fixture.StudioDeliveryTests("test_accept_keeps_unreviewed_feedback_and_explicit_followup")
        fixture.setUp()
        try:
            register_fixture_runner = fixture.runner

            def register_runner_with_native_environment_shape():
                register_fixture_runner()
                fixture.c.register_runner({
                    "runnerId": "agent-test", "runnerKind": "agent",
                    "environment": {"os": "fixture-os", "python": "fixture-python"},
                    "nativeVersion": "fixture",
                    "capabilities": ["planning-readonly-v1", "production-private-v1"],
                    "sandboxEvidence": fixture_role_evidence("agent-test", "agent", ["planning-readonly-v1", "production-private-v1"]),
                })

            fixture.runner = register_runner_with_native_environment_shape
            job, _ref, _repo, ack = fixture.candidate()
            self.assertEqual(ack["disposition"], "recorded", ack)
            view = fixture.c.project_view(fixture.pid)
            self.assertTrue(view["job"]["candidate"])
            self.assert_schema("project-view.v1", view)
            self.assertIsInstance(view["sessionCatalog"]["environment"], dict)
            profile_environments = []
            for (receipt_json,) in fixture.c.db.execute("SELECT receipt FROM claims"):
                request = json.loads(receipt_json).get("request")
                if request is not None:
                    self.assert_schema("execution.v1", request)
                    if request.get("profileSnapshot"):
                        profile_environments.append(request["profileSnapshot"].get("environment"))
            self.assertTrue(any(isinstance(value, dict) for value in profile_environments))
            accepted = fixture.accept(job)
            self.assertEqual(accepted["status"], "accepted", accepted)
            self.assert_schema("project-view.v1", fixture.c.project_view(fixture.pid))
        finally:
            fixture.tearDown()

    def test_browser_can_fetch_only_allowlisted_shared_schema_files(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = Coordinator(REPO_ROOT, state_root=Path(directory) / "state", test_data=True)
            server = make_server(coordinator, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/v1/contracts/message.v1.schema.json") as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "application/json")
                    self.assertEqual(json.loads(response.read()), self.schemas["message.v1"])
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/api/v1/contracts/%2e%2e%2fstate.json")
                self.assertEqual(denied.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                coordinator.close()


if __name__ == "__main__":
    unittest.main()

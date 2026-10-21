"""Item evidence must not turn global technical success into implementation."""
import unittest

from backend.workbench_results import iteration_results


class WorkbenchResultsTests(unittest.TestCase):
    def test_technical_pass_does_not_complete_unmapped_feedback(self):
        proposals = [{"id": "p", "revision": 1, "status": "FROZEN", "changeRequest": {
            "feedback": [{"feedbackId": "note", "objectId": "player", "message": "移动更轻快", "category": "behavior"}]}}]
        packets = [{"id": "packet", "proposalId": "p"}]
        jobs = [{"id": "j", "packetId": "packet", "status": "READY_FOR_REVIEW",
                 "verification": {"status": "FAIL"}, "candidate": {
            "id": "candidate", "candidateCommit": "git-version", "verification": {"status": "PASS"}}}]
        item, = iteration_results(proposals, packets, jobs)
        self.assertEqual(item["originalText"], "移动更轻快")
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["technicalVerification"], "PASS")
        self.assertEqual(item["userAcceptance"], "NOT_PERFORMED")

    def test_failed_job_verification_is_projected_for_every_item_without_inventing_acceptance(self):
        request = {
            "fields": [{"objectId": "player", "fieldId": "speed", "value": 290}],
            "feedback": [{"feedbackId": "note", "objectId": "player", "message": "玩家移动需要更轻快。", "category": "behavior"}],
            "operations": [{"kind": "new-scene", "operationId": "scene-op", "sceneId": "draft-scene", "name": "新大厅"}],
        }
        proposal = {"id": "p", "revision": 2, "currentDocument": {"objects": [
            {"id": "player", "fields": [{"id": "speed", "value": 250}]}]},
            "changeRequest": request,
            "feedbackDecisions": [{"feedbackId": "note", "status": "adopted", "reason": "按玩家移动任务处理。", "taskIds": ["move-player"]}],
            "tasks": [{"id": "move-player", "objectIds": ["player"], "requirementIds": ["movement-responsive"]}],
        }
        packet = {"id": "packet", "proposalId": "p", "proposalRevision": 2, "changeRequest": request}
        job = {"id": "job", "packetId": "packet", "status": "FAILED",
               "verification": {"status": "FAIL", "message": "场景运行检查未通过：资源无法读取。"},
               "productionFailure": {"code": "VERIFICATION_FAILED", "message": "独立技术验证未通过，没有候选。"}}
        feedback = [{"feedbackId": "note", "proposalId": "p", "experienceDecision": {"status": "pending"},
                     "experienceStatus": "NOT_PERFORMED"}]

        items = iteration_results([proposal], [packet], [job], feedback)
        by_kind = {item["kind"]: item for item in items}
        self.assertEqual(set(by_kind), {"field", "feedback", "operation"})
        for item in items:
            self.assertEqual(item["technicalVerification"], "FAIL")
            self.assertEqual(item["candidateId"], None)
            self.assertEqual(item["userAcceptance"], "NOT_PERFORMED")
            self.assertIn("场景运行检查未通过：资源无法读取。", item["reason"])
            self.assertIn("VERIFICATION_FAILED", item["reason"])
            self.assertIn("没有形成候选", item["reason"])

        field = by_kind["field"]
        self.assertEqual(field["status"], "pending")
        self.assertEqual((field["requested"], field["actual"], field["documentValueMatches"]), (290, None, None))
        opinion = by_kind["feedback"]
        self.assertEqual(opinion["originalText"], "玩家移动需要更轻快。")
        self.assertEqual(opinion["planDecision"], proposal["feedbackDecisions"][0])
        self.assertIsNone(opinion["experienceDecision"], "no candidate exists to bind an experience decision")
        self.assertEqual(opinion["status"], "adopted")
        self.assertIn("按玩家移动任务处理。", opinion["reason"])
        operation = by_kind["operation"]
        self.assertEqual(operation["status"], "pending")
        self.assertEqual(operation["requested"], request["operations"][0])

    def test_candidate_field_difference_is_retained(self):
        proposals = [{"id": "p", "revision": 1, "currentDocument": {"objects": [
            {"id": "player", "fields": [{"id": "speed", "value": 200}]}]}, "changeRequest": {
                "fields": [{"objectId": "player", "fieldId": "speed", "value": 240}]}}]
        packets = [{"id": "packet", "proposalId": "p"}]
        jobs = [{"id": "j", "packetId": "packet", "status": "READY_FOR_REVIEW", "candidate": {
            "id": "candidate", "document": {"objects": [{"id": "player", "fields": [
                {"id": "speed", "value": 230}]}]}, "verification": {"status": "PASS"}}}]
        item, = iteration_results(proposals, packets, jobs)
        self.assertEqual((item["before"], item["requested"], item["actual"]), (200, 240, 230))
        self.assertEqual(item["status"], "candidate_value_differs")
        self.assertFalse(item["documentValueMatches"])

    def test_created_targets_keep_structural_identity_and_source_evidence(self):
        operations = [
            {"kind": "new-scene", "operationId": "scene-op", "sceneId": "new-scene"},
            {"kind": "new-instance", "operationId": "instance-op", "instanceId": "new-instance", "sceneId": "new-scene"},
        ]
        proposals = [{"id": "p", "revision": 1, "changeRequest": {"operations": operations},
                      "tasks": [{"id": "create-scene", "objectIds": ["new-scene"]}]}]
        jobs = [{"id": "j", "packetId": "packet", "status": "READY_FOR_REVIEW",
                 "candidate": {"id": "c", "verification": {"status": "PASS"},
                               "changedFiles": ["scenes/new.tscn"], "document": {"objects": [
                                   {"id": "new-scene", "sourceBindings": ["scenes/new.tscn"], "workbench": {"role": "scene", "bounds": [640, 360]}},
                                   {"id": "new-instance", "sourceBindings": ["scenes/new.tscn"], "workbench": {"role": "instance", "sceneId": "new-scene"}},
                               ]}}}]
        scene, instance = iteration_results(proposals, [{"id": "packet", "proposalId": "p"}], jobs)
        self.assertEqual([scene["objectId"], instance["objectId"]], ["new-scene", "new-instance"])
        self.assertEqual(scene["actual"]["bounds"], [640, 360])
        self.assertEqual(instance["actual"]["role"], "instance")
        self.assertEqual(scene["changedSourcePaths"], ["scenes/new.tscn"])
        self.assertEqual(scene["linkedTasks"][0]["id"], "create-scene")
        self.assertEqual(scene["status"], "requires_item_review")
        self.assertEqual(scene["userAcceptance"], "NOT_PERFORMED")


if __name__ == "__main__":
    unittest.main()

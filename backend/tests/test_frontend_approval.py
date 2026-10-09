from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend_approval import (
    ApprovalContext,
    ApprovalError,
    consume_frontend_approval,
)


class Store:
    def __init__(self, record=None):
        self.record = record
        self.consumed = set()

    def get(self, event_id):
        if self.record and self.record["eventId"] == event_id:
            return self.record
        return None

    def consume_once(self, event_id):
        if event_id in self.consumed:
            return False
        self.consumed.add(event_id)
        return True


def approval(**updates):
    result = {
        "schemaVersion": 1,
        "eventId": "evt-1",
        "operatorId": "user-7",
        "projectId": "project-1",
        "phase": "specification",
        "proposalId": "proposal-1",
        "packetId": "packet-1",
        "jobId": "job-1",
        "candidateId": "candidate-1",
        "revision": "rev-4",
        "gitSpecRef": "git:blob:0123456789012345678901234567890123456789",
        "runId": "run-1",
        "action": "approve",
        "createdAt": "2026-10-09T01:02:03Z",
        "provenance": {
            "kind": "interactive_frontend",
            "input": "frontend",
            "recordedBy": "approval_service",
        },
        "testData": False,
        "productionAuthorized": True,
    }
    result.update(updates)
    return result


def context(**updates):
    values = {
        "operator_id": "user-7",
        "project_id": "project-1",
        "phase": "specification",
        "proposal_id": "proposal-1",
        "packet_id": "packet-1",
        "job_id": "job-1",
        "candidate_id": "candidate-1",
        "revision": "rev-4",
        "git_spec_ref": "git:blob:0123456789012345678901234567890123456789",
        "run_id": "run-1",
    }
    values.update(updates)
    return ApprovalContext(**values)


class FrontendApprovalTests(unittest.TestCase):
    def test_accepts_durable_record_and_returns_distinct_provenance(self):
        result = consume_frontend_approval(
            {"eventId": "evt-1"}, context(), Store(approval())
        )
        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["provenance"]["kind"], "interactive_frontend")
        self.assertEqual(result["provenance"]["event_id"], "evt-1")
        self.assertNotEqual(
            result["provenance"],
            {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"},
        )

    def test_client_cannot_assert_actor_or_bindings(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1", "actor": "human", "projectId": "project-1"},
                context(),
                Store(approval()),
            )

    def test_self_contained_client_claim_without_durable_match_is_rejected(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval({"eventId": "evt-1"}, context(), Store())

    def test_stale_bindings_are_rejected(self):
        for key, value in (
            ("revision", "old"),
            ("gitSpecRef", "git:blob:stale"),
            ("proposalId", "other"),
            ("candidateId", "other"),
        ):
            with self.subTest(key=key), self.assertRaises(ApprovalError):
                consume_frontend_approval(
                    {"eventId": "evt-1"}, context(), Store(approval(**{key: value}))
                )

    def test_wrong_project_and_invalid_phase_are_rejected(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"}, context(project_id="other"), Store(approval())
            )
        with self.assertRaises(ApprovalError):
            context(phase="production")

    def test_replay_across_another_run_is_rejected(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"}, context(run_id="run-2"), Store(approval())
            )
        store = Store(approval())
        consume_frontend_approval({"eventId": "evt-1"}, context(), store)
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"}, context(run_id="run-2"), store
            )

    def test_wrong_phase_action_and_untrusted_provenance_are_rejected(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"}, context(), Store(approval(action="initialize"))
            )
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"},
                context(),
                Store(
                    approval(
                        provenance={
                            "kind": "local_interactive",
                            "input": "tty",
                            "recordedBy": "gm_review",
                        }
                    )
                ),
            )

    def test_test_data_and_unauthorized_contexts_cannot_pass_production_gate(self):
        for values in (
            {"test_data": True},
            {"production_authorized": False},
            {"test_data": 0},
            {"production_authorized": 1},
        ):
            with self.subTest(values=values), self.assertRaises(ApprovalError):
                context(**values)

    def test_boolean_schema_version_is_not_integer_version_one(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"}, context(), Store(approval(schemaVersion=True))
            )

    def test_persisted_test_mode_flags_cannot_be_rebound_as_production(self):
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"},
                context(),
                Store(approval(testData=True, productionAuthorized=False)),
            )
        with self.assertRaises(ApprovalError):
            consume_frontend_approval(
                {"eventId": "evt-1"},
                context(),
                Store(approval(testData=0, productionAuthorized=1)),
            )

    def test_legacy_tty_provenance_value_is_preserved_as_distinct_contract(self):
        legacy = {
            "kind": "local_interactive",
            "input": "tty",
            "recorded_by": "gm_review",
        }
        accepted = consume_frontend_approval(
            {"eventId": "evt-1"}, context(), Store(approval())
        )
        self.assertEqual(
            legacy,
            {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"},
        )
        self.assertEqual(accepted["provenance"]["kind"], "interactive_frontend")


if __name__ == "__main__":
    unittest.main()

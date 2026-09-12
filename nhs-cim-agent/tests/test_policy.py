"""The guardrails, one rule at a time."""

import unittest

from helpers import SandboxCase


class TestPolicy(SandboxCase):
    def test_action_without_evidence_is_blocked(self):
        plan = self.plan_one(
            self.action("unlock_smartcard", {"uuid": "555100200313"}, evidence=False)
        )
        self.assertEqual(plan.actions[0].status, "blocked")
        self.assertIn("EVIDENCE_REQUIRED", self.codes(plan.actions[0]))

    def test_organisation_outside_ra_scope_is_blocked(self):
        plan = self.plan_one(
            self.action("close_account", {"uuid": "555100200320"}, {"end_date": "2026-09-04"})
        )
        self.assertEqual(plan.actions[0].status, "blocked")
        self.assertIn("OUT_OF_SCOPE_ODS", self.codes(plan.actions[0]))

    def test_privileged_role_needs_approval(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200315"},
            {"ods_code": "ZZG01", "job_role": "R5090"},
        ))
        self.assertEqual(plan.actions[0].status, "needs_approval")
        self.assertIn("PRIVILEGED_GRANT", self.codes(plan.actions[0]))

    def test_activity_outside_the_national_baseline_needs_approval(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200312"},
            {"ods_code": "ZZG01", "job_role": "R8004", "activities": ["B0090", "B0170"]},
        ))
        self.assertEqual(plan.actions[0].status, "needs_approval")
        self.assertIn("OUTSIDE_BASELINE", self.codes(plan.actions[0]))

    def test_activity_inside_the_baseline_is_ready(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200312"},
            {"ods_code": "ZZG01", "job_role": "R8004", "activities": ["B0090"]},
        ))
        self.assertEqual(plan.actions[0].status, "ready")

    def test_amendment_is_checked_against_the_positions_own_role(self):
        # modify_position_activities carries no job_role, so the baseline check
        # has to take the role from the position being amended.
        plan = self.plan_one(self.action(
            "modify_position_activities", {"uuid": "555100200311"},
            {"add": ["B0170"], "ods_code": "ZZG01"},
        ))
        planned = plan.actions[0]
        self.assertEqual(planned.resolved["position_job_role"], "R8001")
        self.assertEqual(planned.status, "needs_approval")
        self.assertIn("OUTSIDE_BASELINE", self.codes(planned))

    def test_amendment_within_the_positions_baseline_is_ready(self):
        plan = self.plan_one(self.action(
            "modify_position_activities", {"uuid": "555100200311"},
            {"add": ["B0100"], "ods_code": "ZZG01"},
        ))
        self.assertEqual(plan.actions[0].status, "ready")

    def test_amendment_with_no_matching_open_position_asks(self):
        plan = self.plan_one(self.action(
            "modify_position_activities", {"uuid": "555100200311"},
            {"add": ["B0100"], "ods_code": "ZZG02"},
        ))
        self.assertEqual(plan.actions[0].status, "needs_clarification")
        self.assertIn("NO_OPEN_POSITION", self.codes(plan.actions[0]))

    def test_unknown_code_is_blocked(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200312"},
            {"ods_code": "ZZG01", "job_role": "R8004", "activities": ["B9999"]},
        ))
        self.assertEqual(plan.actions[0].status, "blocked")
        self.assertIn("UNKNOWN_CODE", self.codes(plan.actions[0]))

    def test_operator_cannot_act_on_their_own_care_id(self):
        session = self.session
        own_uuid = session.describe_context()
        backend = self.backend
        # Give the operator a Care ID in the directory, then target it.
        backend._db["users"]["555100200300"] = {
            "uuid": "555100200300", "given_name": "Joanne", "family_name": "Parker",
            "email": None, "status": "active",
            "positions": [{"position_id": "P-0099", "ods_code": "ZZG01", "job_role": "R8004",
                           "activities": ["B0090"], "workgroup": "RA", "start_date": "2022-01-01",
                           "end_date": None}],
            "smartcard": {"serial": "SC-70099", "status": "active",
                          "certificate_expiry": "2028-01-01"},
        }
        plan = self.plan_one(self.action(
            "modify_position_activities", {"uuid": "555100200300"}, {"add": ["B0825"]},
        ))
        self.assertEqual(plan.actions[0].status, "blocked")
        self.assertIn("SELF_ACTION", self.codes(plan.actions[0]))
        self.assertTrue(own_uuid["operator_id"])

    def test_registration_without_an_identity_check_is_blocked(self):
        plan = self.plan_one(self.action(
            "create_user", {"given_name": "Aisha", "family_name": "Khan"},
            {"given_name": "Aisha", "family_name": "Khan"},
        ))
        self.assertEqual(plan.actions[0].status, "blocked")
        self.assertIn("UNVERIFIED_IDENTITY", self.codes(plan.actions[0]))

    def test_backdated_leaver_is_applied_but_flagged(self):
        plan = self.plan_one(self.action(
            "close_account", {"uuid": "555100200312"}, {"end_date": "2026-08-28"},
        ))
        self.assertEqual(plan.actions[0].status, "ready")
        self.assertIn("RETROSPECTIVE_REVOCATION", self.codes(plan.actions[0]))

    def test_unresolvable_person_asks_rather_than_guessing(self):
        plan = self.plan_one(self.action("unlock_smartcard", {"family_name": "Nobody"}))
        self.assertEqual(plan.actions[0].status, "needs_clarification")
        self.assertIn("UNRESOLVED_SUBJECT", self.codes(plan.actions[0]))
        self.assertTrue(plan.clarifications)


if __name__ == "__main__":
    unittest.main()

"""Applying a plan: the token, the approvals, idempotency and the audit trail."""

import json
import unittest

from helpers import SandboxCase  # noqa: F401  (puts src/ on sys.path)

from cim_agent.apply import ConfirmationMismatch


class TestApply(SandboxCase):
    def test_wrong_confirmation_token_changes_nothing(self):
        plan = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200313"}))
        with self.assertRaises(ConfirmationMismatch):
            self.session.apply(plan.plan_id, confirm="not-the-token")
        self.assertEqual(self.backend.get_user("555100200313")["smartcard"]["status"], "locked")

    def test_token_changes_when_the_plan_changes(self):
        first = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200313"}))
        second = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200311"}))
        self.assertNotEqual(first.confirmation_token, second.confirmation_token)

    def test_ready_action_applies(self):
        plan = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200313"}))
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        self.assertEqual(len(report.applied), 1)
        self.assertEqual(self.backend.get_user("555100200313")["smartcard"]["status"], "active")

    def test_dry_run_writes_nothing_anywhere(self):
        plan = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200313"}))
        self.session.apply(plan.plan_id, confirm=plan.confirmation_token, dry_run=True)
        self.assertEqual(self.backend.get_user("555100200313")["smartcard"]["status"], "locked")
        self.assertEqual(self.session.audit_tail(50), [])

    def test_privileged_action_is_skipped_without_an_approver(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200315"},
            {"ods_code": "ZZG01", "job_role": "R5090"}))
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        self.assertEqual(len(report.applied), 0)
        self.assertIn("requires named approval", report.skipped[0]["reason"])

    def test_privileged_action_cannot_be_self_approved(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200315"},
            {"ods_code": "ZZG01", "job_role": "R5090"}))
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token,
                                    approvals={0: "j.parker"})
        self.assertEqual(len(report.applied), 0)
        self.assertIn("not authorised", report.skipped[0]["reason"])

    def test_privileged_action_applies_with_an_ra_manager(self):
        plan = self.plan_one(self.action(
            "assign_position", {"uuid": "555100200315"},
            {"ods_code": "ZZG01", "job_role": "R5090"}))
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token,
                                    approvals={0: "s.adeyemi"})
        self.assertEqual(len(report.applied), 1)
        self.assertEqual(report.applied[0]["approver"], "s.adeyemi")

    def test_blocked_action_is_never_applied_even_when_approved(self):
        plan = self.plan_one(self.action(
            "close_account", {"uuid": "555100200320"}, {"end_date": "2026-09-04"}))
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token,
                                    approvals={0: "s.adeyemi"})
        self.assertEqual(len(report.applied), 0)
        self.assertEqual(self.backend.get_user("555100200320")["status"], "active")

    def test_replaying_the_same_request_does_not_reapply_it(self):
        text = (self.session and "Tom Halloway is leaving us, his last day was 2026-08-28.")
        first = self.session.plan_from_text(text, source_ref="hr-1")
        self.session.apply(first.plan_id, confirm=first.confirmation_token)
        second = self.session.plan_from_text(text, source_ref="hr-1-resent")
        report = self.session.apply(second.plan_id, confirm=second.confirmation_token)
        self.assertEqual(len(report.applied), 0)
        self.assertIn("already applied", report.skipped[0]["reason"])

    def test_position_waits_for_the_registration_it_depends_on(self):
        text = ("Dr Aisha Khan is a new starter at ZZG01 starting on 2026-09-21, "
                "she is a clinical practitioner, ID checked under CID-40192.")
        plan = self.session.plan_from_text(text, source_ref="joiner")
        assign = next(a for a in plan.actions if a.action.action_type == "assign_position")
        self.assertIsNotNone(assign.resolved.get("awaits_create_index"))
        self.assertEqual(assign.status, "ready")
        report = self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        self.assertEqual(len(report.applied), 2)
        new_uuid = report.applied[0]["detail"]["uuid"]
        user = self.backend.get_user(new_uuid)
        self.assertEqual(user["positions"][0]["ods_code"], "ZZG01")
        self.assertEqual(user["positions"][0]["job_role"], "R8000")

    def test_audit_record_carries_the_evidence_and_the_source_hash(self):
        plan = self.plan_one(self.action("unlock_smartcard", {"uuid": "555100200313"}))
        self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        entry = self.session.audit_tail(1)[0]
        self.assertEqual(entry["outcome"], "applied")
        self.assertEqual(entry["operator"], "j.parker")
        self.assertEqual(entry["source_sha256"], plan.source_sha256)
        self.assertEqual(entry["evidence"][0]["text"], "please do it")
        self.assertTrue(entry["at"])

    def test_skipped_actions_are_audited_too(self):
        plan = self.plan_one(self.action(
            "close_account", {"uuid": "555100200320"}, {"end_date": "2026-09-04"}))
        self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        outcomes = [e["outcome"] for e in self.session.audit_tail(10)]
        self.assertEqual(outcomes, ["skipped_blocked"])

    def test_audit_file_is_append_only_json_lines(self):
        for uuid in ("555100200313", "555100200311"):
            plan = self.plan_one(self.action("unlock_smartcard", {"uuid": uuid}))
            self.session.apply(plan.plan_id, confirm=plan.confirmation_token)
        lines = self.session.audit.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            json.loads(line)


if __name__ == "__main__":
    unittest.main()

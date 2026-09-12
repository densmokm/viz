"""The rule-based extractor: what it reads, and what it refuses to guess."""

import unittest

from helpers import ROOT, SandboxCase

SAMPLES = ROOT / "samples"


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


class TestExtraction(SandboxCase):
    def plan_sample(self, name: str):
        return self.session.plan_from_text(sample(name), source_ref=name)

    def types(self, plan) -> list[str]:
        return [a.action.action_type for a in plan.actions]

    def test_joiner_pools_facts_split_across_wrapped_lines(self):
        plan = self.plan_sample("01-joiner.txt")
        self.assertEqual(self.types(plan), ["create_user", "assign_position"])
        create, assign = plan.actions
        # "Apply for Care ID reference CID-40192" is three sentences away from
        # the joiner cue, and "clinical practitioner" is split by a line break.
        self.assertEqual(create.action.params["id_verification_ref"], "CID-40192")
        self.assertEqual(assign.action.params["job_role"], "R8000")
        self.assertEqual(assign.action.params["ods_code"], "ZZG01")
        self.assertEqual(assign.action.params["start_date"], "2026-09-21")

    def test_one_joiner_yields_one_registration_not_one_per_sentence(self):
        plan = self.plan_sample("01-joiner.txt")
        self.assertEqual(self.types(plan).count("create_user"), 1)

    def test_leaver_takes_its_date_from_a_later_sentence(self):
        plan = self.plan_sample("02-leaver.txt")
        self.assertEqual(self.types(plan), ["close_account"])
        self.assertEqual(plan.actions[0].action.params["end_date"], "2026-08-28")

    def test_subject_carries_across_sentences_to_the_lockout(self):
        plan = self.plan_sample("03-lockout.txt")
        self.assertEqual(self.types(plan), ["unlock_smartcard"])
        self.assertEqual(plan.actions[0].resolved["uuid"], "555100200313")

    def test_mover_ends_the_old_position_and_opens_the_new_one(self):
        plan = self.plan_sample("04-mover.txt")
        self.assertEqual(sorted(self.types(plan)),
                         ["assign_position", "end_position", "renew_certificates"])
        ends = next(a for a in plan.actions if a.action.action_type == "end_position")
        starts = next(a for a in plan.actions if a.action.action_type == "assign_position")
        self.assertEqual(ends.action.params["ods_code"], "ZZG02")
        self.assertEqual(starts.action.params["ods_code"], "ZZG01")

    def test_vague_request_produces_no_actions_and_says_why(self):
        plan = self.plan_sample("05-vague.txt")
        self.assertEqual(plan.actions, [])
        unrecognised = self.session.plan_view(plan)["unrecognised_text"]
        self.assertTrue(unrecognised)
        self.assertIn("same access as", unrecognised[0]["reason"])

    def test_first_named_person_is_the_subject_not_the_titled_one(self):
        # A titled name later in the sentence must not capture the action: this
        # is about Priya leaving, not about Dr Osei who is only covering.
        plan = self.session.plan_from_text(
            "Priya Nair is leaving on 2026-10-02, Dr Osei will cover her shifts.",
            source_ref="t")
        self.assertEqual(self.types(plan), ["close_account"])
        self.assertEqual(plan.actions[0].resolved["display_name"], "Priya Nair")

    def test_weekday_without_a_date_becomes_a_question(self):
        plan = self.session.plan_from_text(
            "Tom Halloway is leaving, his last day is Friday.", source_ref="t")
        planned = plan.actions[0]
        self.assertEqual(planned.status, "needs_clarification")
        self.assertIn("UNRESOLVED_REFERENCE", {i.code for i in planned.issues})

    def test_batch_email_keeps_three_people_apart(self):
        plan = self.plan_sample("08-mixed-batch.txt")
        subjects = {a.resolved.get("display_name") or a.action.subject.get("family_name")
                    for a in plan.actions}
        self.assertEqual(subjects, {"Daniel Osei", "Priya Nair", "Khan"})

    def test_evidence_offsets_index_the_source_text(self):
        text = sample("03-lockout.txt")
        plan = self.session.plan_from_text(text, source_ref="t")
        for span in plan.actions[0].action.evidence:
            # Offsets are preserved through line unwrapping, so only whitespace
            # may differ between the span and the original slice.
            self.assertEqual(text[span.start:span.end].split(), span.text.split())


if __name__ == "__main__":
    unittest.main()

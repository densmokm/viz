"""Shared fixtures: a throwaway sandbox per test, so nothing touches demo state."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cim_agent.backends import SandboxBackend  # noqa: E402
from cim_agent.model import Action, Span  # noqa: E402
from cim_agent.session import CimAgentSession  # noqa: E402

TODAY = date(2026, 9, 14)


class SandboxCase(unittest.TestCase):
    operator = "j.parker"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.backend = SandboxBackend(state_path=tmp / "directory.json")
        self.session = CimAgentSession(
            operator_id=self.operator,
            backend=self.backend,
            audit_path=tmp / "audit.jsonl",
            today=TODAY,
        )

    def action(self, action_type: str, subject: dict, params: dict | None = None,
               evidence: bool = True) -> Action:
        return Action(
            action_type=action_type,
            subject=subject,
            params=params or {},
            evidence=[Span(0, 12, "please do it")] if evidence else [],
        )

    def plan_one(self, *actions: Action):
        return self.session.plan_from_actions([
            {"action_type": a.action_type, "subject": a.subject, "params": a.params,
             "evidence": [{"start": s.start, "end": s.end, "text": s.text} for s in a.evidence]}
            for a in actions
        ], source_text="please do it", source_ref="test")

    def codes(self, planned) -> set[str]:
        return {i.code for i in planned.issues}

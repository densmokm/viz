"""Domain model: actions, evidence, issues and plans.

Two ideas carry most of the weight:

*Evidence.* Every action must point at the span of source text that caused it.
An action with no evidence is rejected rather than applied - that is the guard
against a language model inventing an access change nobody asked for.

*Two phase.* Planning is pure and never writes. Applying takes a plan id and a
confirmation token derived from the plan's content, so a plan that changed
between being shown and being applied cannot be applied by accident.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# --- action vocabulary ------------------------------------------------------
# These are the CIM activities an RA performs. They map one-to-one onto tasks in
# the Care Identity Management UI; see backends.py for how they reach a system.

ACTION_TYPES = (
    "create_user",
    "assign_position",
    "end_position",
    "modify_position_activities",
    "unlock_smartcard",
    "renew_certificates",
    "replace_smartcard",
    "close_account",
    "update_user_details",
)

# Actions that change what a person can see or do, as opposed to restoring
# access they already hold. These get the stricter treatment in policy.py.
ACCESS_CHANGING = frozenset(
    {
        "create_user",
        "assign_position",
        "end_position",
        "modify_position_activities",
        "close_account",
    }
)

STATUS_READY = "ready"
STATUS_NEEDS_APPROVAL = "needs_approval"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"
STATUS_BLOCKED = "blocked"

SEVERITY_BLOCK = "block"
SEVERITY_APPROVE = "approve"
SEVERITY_CLARIFY = "clarify"
SEVERITY_WARN = "warn"


@dataclass(frozen=True)
class Span:
    """A half-open character range in the source text, with the text itself."""

    start: int
    end: int
    text: str

    @classmethod
    def of(cls, source: str, start: int, end: int) -> "Span":
        return cls(start=start, end=end, text=source[start:end])


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    remedy: str | None = None


@dataclass
class Action:
    """A candidate action, as extracted from text but not yet validated."""

    action_type: str
    subject: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    evidence: list[Span] = field(default_factory=list)
    note: str | None = None

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise ValueError(
                f"unknown action_type {self.action_type!r}; "
                f"expected one of {', '.join(ACTION_TYPES)}"
            )
        self.evidence = [s if isinstance(s, Span) else Span(**s) for s in self.evidence]


@dataclass
class PlannedAction:
    """An action after resolution against the directory and the policy checks."""

    index: int
    action: Action
    resolved: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    status: str = STATUS_READY
    preview: str = ""
    idempotency_key: str = ""

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)
        # Statuses are ordered: a block outranks an approval, which outranks a
        # clarification. Warnings never change the status.
        rank = {
            STATUS_READY: 0,
            STATUS_NEEDS_CLARIFICATION: 1,
            STATUS_NEEDS_APPROVAL: 2,
            STATUS_BLOCKED: 3,
        }
        promoted = {
            SEVERITY_BLOCK: STATUS_BLOCKED,
            SEVERITY_APPROVE: STATUS_NEEDS_APPROVAL,
            SEVERITY_CLARIFY: STATUS_NEEDS_CLARIFICATION,
            SEVERITY_WARN: self.status,
        }[issue.severity]
        if rank[promoted] > rank[self.status]:
            self.status = promoted


@dataclass
class Plan:
    plan_id: str
    created_at: str
    operator: str
    source_sha256: str
    source_ref: str
    actions: list[PlannedAction] = field(default_factory=list)
    confirmation_token: str = ""

    # --- derived views ------------------------------------------------------

    @property
    def ready(self) -> list[PlannedAction]:
        return [a for a in self.actions if a.status == STATUS_READY]

    @property
    def needs_approval(self) -> list[PlannedAction]:
        return [a for a in self.actions if a.status == STATUS_NEEDS_APPROVAL]

    @property
    def clarifications(self) -> list[str]:
        out: list[str] = []
        for a in self.actions:
            for issue in a.issues:
                if issue.severity == SEVERITY_CLARIFY and issue.message not in out:
                    out.append(issue.message)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "operator": self.operator,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "confirmation_token": self.confirmation_token,
            "summary": {
                "total": len(self.actions),
                "ready": len(self.ready),
                "needs_approval": len(self.needs_approval),
                "needs_clarification": sum(
                    1 for a in self.actions if a.status == STATUS_NEEDS_CLARIFICATION
                ),
                "blocked": sum(1 for a in self.actions if a.status == STATUS_BLOCKED),
            },
            "clarifications": self.clarifications,
            "actions": [
                {
                    "index": a.index,
                    "action_type": a.action.action_type,
                    "status": a.status,
                    "preview": a.preview,
                    "subject": a.action.subject,
                    "params": a.action.params,
                    "resolved": a.resolved,
                    "idempotency_key": a.idempotency_key,
                    "evidence": [asdict(s) for s in a.action.evidence],
                    "issues": [asdict(i) for i in a.issues],
                }
                for a in self.actions
            ],
        }


def subject_key(subject: dict[str, Any]) -> str:
    """A stable identity for "the person this action is about".

    Used to pool an email's sentences onto one person, and to link an
    `assign_position` to the `create_user` that will mint the Care ID it needs.
    """
    if subject.get("uuid"):
        return "uuid:" + str(subject["uuid"])
    return "name:" + " ".join(
        str(v).lower() for v in (subject.get("given_name"), subject.get("family_name")) if v
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confirmation_token(plan: Plan) -> str:
    """Bind the token to exactly what an operator would have been shown.

    Anything that changes the effect of applying the plan - the action list,
    the resolved targets, the statuses - changes the token. A stale token is
    therefore rejected at apply time rather than silently applying a plan the
    operator never saw.
    """
    material = canonical_json(
        [
            {
                "index": a.index,
                "action_type": a.action.action_type,
                "resolved": a.resolved,
                "params": a.action.params,
                "status": a.status,
            }
            for a in plan.actions
        ]
    )
    return hashlib.sha256((plan.plan_id + "|" + material).encode("utf-8")).hexdigest()[:16]

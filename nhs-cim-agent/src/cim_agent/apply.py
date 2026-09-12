"""Apply a plan. The only module in the package that writes anything.

Three gates stand between a plan and a change:

  * the confirmation token, which proves the caller is applying the plan that
    was actually reviewed and not a re-planned variant;
  * approvals, which are required per action for anything policy flagged as
    privileged, and must come from a different operator than the one who
    planned it;
  * the idempotency key, checked against the audit log, so replaying the same
    request does not double-apply it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .backends import BackendError, CIMBackend
from .model import (
    Plan,
    subject_key,
    STATUS_BLOCKED,
    STATUS_NEEDS_APPROVAL,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
)


class ConfirmationMismatch(ValueError):
    pass


@dataclass
class ApplyReport:
    plan_id: str
    dry_run: bool
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "dry_run": self.dry_run,
            "counts": {"applied": len(self.applied), "skipped": len(self.skipped),
                       "failed": len(self.failed)},
            "applied": self.applied,
            "skipped": self.skipped,
            "failed": self.failed,
        }


def apply_plan(plan: Plan, *, backend: CIMBackend, audit: AuditLog, confirm: str,
               approvals: dict[int, str] | None = None, dry_run: bool = False) -> ApplyReport:
    if confirm != plan.confirmation_token:
        raise ConfirmationMismatch(
            "Confirmation token does not match this plan. Re-read the plan and confirm "
            "against the token it currently carries - the plan may have changed since "
            "it was shown."
        )
    approvals = {int(k): v for k, v in (approvals or {}).items()}
    report = ApplyReport(plan_id=plan.plan_id, dry_run=dry_run)
    already_applied = audit.applied_keys()
    # Care IDs minted earlier in this plan, so a joiner's position can attach to
    # the registration that only just happened.
    minted: dict[str, str] = {}

    for planned in plan.actions:
        entry = {"index": planned.index, "action_type": planned.action.action_type,
                 "preview": planned.preview, "idempotency_key": planned.idempotency_key}
        approver: str | None = None

        if planned.status == STATUS_BLOCKED:
            reason = "; ".join(i.message for i in planned.issues if i.severity == "block")
            report.skipped.append({**entry, "reason": f"blocked by policy: {reason}"})
            _record(audit, plan, planned, "skipped_blocked", {"reason": reason}, backend, dry_run)
            continue

        if planned.status == STATUS_NEEDS_CLARIFICATION:
            reason = "; ".join(i.message for i in planned.issues if i.severity == "clarify")
            report.skipped.append({**entry, "reason": f"awaiting clarification: {reason}"})
            _record(audit, plan, planned, "skipped_clarification", {"reason": reason}, backend, dry_run)
            continue

        if planned.status == STATUS_NEEDS_APPROVAL:
            approver = approvals.get(planned.index)
            problem = _approval_problem(planned.index, approver, plan, backend)
            if problem:
                report.skipped.append({**entry, "reason": problem})
                _record(audit, plan, planned, "skipped_unapproved", {"reason": problem},
                        backend, dry_run)
                continue

        if planned.status not in (STATUS_READY, STATUS_NEEDS_APPROVAL):
            report.skipped.append({**entry, "reason": f"unexpected status {planned.status}"})
            continue

        if planned.idempotency_key in already_applied:
            report.skipped.append({**entry, "reason": "already applied in an earlier run"})
            _record(audit, plan, planned, "skipped_duplicate", {}, backend, dry_run)
            continue

        if dry_run:
            if planned.action.action_type == "create_user":
                minted[subject_key(planned.action.subject)] = "(would be minted)"
            report.applied.append({**entry, "approver": approver, "detail": {"dry_run": True}})
            continue

        uuid = planned.resolved.get("uuid")
        if not uuid and planned.resolved.get("awaits_create_index") is not None:
            uuid = minted.get(subject_key(planned.action.subject))
            if not uuid:
                reason = ("the registration it depends on did not produce a Care ID")
                report.skipped.append({**entry, "reason": reason})
                _record(audit, plan, planned, "skipped_dependency", {"reason": reason},
                        backend, dry_run)
                continue
            planned.resolved["uuid"] = uuid
        target = {"uuid": uuid} if uuid else {}
        try:
            detail = backend.apply_action(planned.action.action_type, target,
                                          planned.action.params)
        except BackendError as exc:
            report.failed.append({**entry, "error": str(exc)})
            _record(audit, plan, planned, "failed", {"error": str(exc)}, backend, dry_run,
                    approver)
            continue

        if planned.action.action_type == "create_user" and detail.get("uuid"):
            minted[subject_key(planned.action.subject)] = detail["uuid"]
        report.applied.append({**entry, "approver": approver, "detail": detail})
        _record(audit, plan, planned, "applied", detail, backend, dry_run, approver)
        if detail.get("changed"):
            already_applied.add(planned.idempotency_key)

    return report


def _approval_problem(index: int, approver: str | None, plan: Plan,
                      backend: CIMBackend) -> str | None:
    if not approver:
        return "requires named approval, none supplied"
    record = backend.operator(approver)
    if record is None:
        return f"approver {approver!r} is not a known RA operator"
    if not record.get("may_approve_privileged"):
        return f"approver {approver!r} is not authorised to approve privileged grants"
    if approver == plan.operator:
        return (f"approver {approver!r} planned these actions; privileged grants need "
                "a second operator")
    return None


def _record(audit: AuditLog, plan: Plan, planned: Any, outcome: str,
            detail: dict[str, Any], backend: CIMBackend, dry_run: bool,
            approver: str | None = None) -> None:
    if dry_run:
        return
    audit.record(plan=plan, planned=planned, outcome=outcome, detail=detail,
                 backend=getattr(backend, "name", "unknown"), approver=approver)

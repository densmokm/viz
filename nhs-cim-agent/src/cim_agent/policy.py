"""Guardrails applied to every action before it can be applied.

The rules encode the parts of RA practice that a language model should never be
trusted to re-derive from an email: whose organisations you may act in, which
roles need a human, what the national baseline says, and the fact that you do
not grant yourself access.

Each rule appends an `Issue`. Severity decides the outcome: `block` stops the
action outright, `approve` holds it for a named human, `clarify` sends a
question back instead of a guess, `warn` is recorded and applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from .catalogue import Catalogue
from .model import (
    ACCESS_CHANGING,
    PlannedAction,
    Issue,
    SEVERITY_APPROVE,
    SEVERITY_BLOCK,
    SEVERITY_CLARIFY,
    SEVERITY_WARN,
)

# Parameters without which an action cannot be performed at all.
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "create_user": ("given_name", "family_name", "id_verification_ref"),
    "assign_position": ("ods_code", "job_role"),
    "end_position": ("end_date",),
    "modify_position_activities": (),
    "unlock_smartcard": (),
    "renew_certificates": (),
    "replace_smartcard": (),
    "close_account": ("end_date",),
    "update_user_details": (),
}


@dataclass
class PolicyContext:
    operator_id: str
    operator: dict[str, Any]
    catalogue: Catalogue
    today: date
    backend_is_sandbox: bool


Rule = Callable[[PlannedAction, PolicyContext], None]
_RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    _RULES.append(fn)
    return fn


def check(planned: PlannedAction, ctx: PolicyContext) -> None:
    for fn in _RULES:
        fn(planned, ctx)


# --- rules ------------------------------------------------------------------


@rule
def evidence_required(planned: PlannedAction, ctx: PolicyContext) -> None:
    """No action without a span of source text that asked for it.

    This is the rule that makes the rest of the system auditable. An extractor -
    rule-based or a language model - that produces an action it cannot point at
    gets that action rejected, not applied.
    """
    if not planned.action.evidence:
        planned.add(Issue(
            code="EVIDENCE_REQUIRED",
            severity=SEVERITY_BLOCK,
            message=(f"{planned.action.action_type} cites no source text and will not be applied."),
            remedy="Re-plan with the quoted span of the request that asks for this action.",
        ))


@rule
def required_params(planned: PlannedAction, ctx: PolicyContext) -> None:
    missing = [p for p in REQUIRED_PARAMS.get(planned.action.action_type, ())
               if not planned.action.params.get(p)]
    for param in missing:
        planned.add(Issue(
            code="MISSING_PARAM",
            severity=SEVERITY_CLARIFY,
            message=f"{planned.action.action_type} needs {param}, which the request does not give.",
            remedy=f"Ask the requester for {param}.",
        ))


@rule
def subject_resolution(planned: PlannedAction, ctx: PolicyContext) -> None:
    if planned.action.action_type == "create_user":
        return
    matches = planned.resolved.get("candidate_uuids", [])
    if planned.resolved.get("uuid"):
        return
    if planned.resolved.get("awaits_create_index") is not None:
        return  # resolved at apply time from the create_user receipt
    subject = planned.action.subject
    described = subject.get("uuid") or " ".join(
        v for v in (subject.get("given_name"), subject.get("family_name")) if v
    ) or "the person named"
    if len(matches) > 1:
        planned.add(Issue(
            code="AMBIGUOUS_SUBJECT",
            severity=SEVERITY_CLARIFY,
            message=f"{described} matches {len(matches)} Care IDs: {', '.join(matches)}.",
            remedy="Ask the requester for the 12-digit Care ID (UUID).",
        ))
    else:
        planned.add(Issue(
            code="UNRESOLVED_SUBJECT",
            severity=SEVERITY_CLARIFY,
            message=f"No Care ID in scope matches {described}.",
            remedy="Confirm the person's Care ID, or whether this should be a new registration.",
        ))


@rule
def unresolved_reference(planned: PlannedAction, ctx: PolicyContext) -> None:
    """"The same access as Dr Okafor" is a question, not an instruction."""
    for phrase in planned.action.params.get("_unresolved", []):
        planned.add(Issue(
            code="UNRESOLVED_REFERENCE",
            severity=SEVERITY_CLARIFY,
            message=f"The request says {phrase!r}, which does not name a role or activity.",
            remedy="Ask for the job role code, or name the colleague whose position should be copied.",
        ))


@rule
def known_codes(planned: PlannedAction, ctx: PolicyContext) -> None:
    params = planned.action.params
    role = params.get("job_role")
    activities = list(params.get("activities", [])) + list(params.get("add", []))
    for code in ctx.catalogue.unknown_codes(role, activities):
        planned.add(Issue(
            code="UNKNOWN_CODE",
            severity=SEVERITY_BLOCK,
            message=f"{code} is not in the loaded RBAC catalogue.",
            remedy="Check the code against the National RBAC Database.",
        ))


@rule
def ra_scope(planned: PlannedAction, ctx: PolicyContext) -> None:
    """An RA acts only within the organisations its authority covers."""
    scope = set(ctx.operator.get("scope_ods", []))
    targets = set(planned.resolved.get("subject_ods", []))
    if planned.action.params.get("ods_code"):
        targets.add(planned.action.params["ods_code"])
    outside = sorted(targets - scope)
    if outside:
        planned.add(Issue(
            code="OUT_OF_SCOPE_ODS",
            severity=SEVERITY_BLOCK,
            message=(f"{', '.join(outside)} is outside the acting RA's scope "
                     f"({', '.join(sorted(scope)) or 'none'})."),
            remedy="Route this request to the Registration Authority for that organisation.",
        ))


@rule
def separation_of_duties(planned: PlannedAction, ctx: PolicyContext) -> None:
    if planned.resolved.get("uuid") and planned.resolved["uuid"] == ctx.operator.get("uuid"):
        planned.add(Issue(
            code="SELF_ACTION",
            severity=SEVERITY_BLOCK,
            message="The acting RA operator is the subject of this action.",
            remedy="A second RA operator must perform changes to this Care ID.",
        ))


@rule
def privileged_grants(planned: PlannedAction, ctx: PolicyContext) -> None:
    """RA roles and sensitive activities always stop for a named human."""
    if planned.action.action_type not in ACCESS_CHANGING:
        return
    cat = ctx.catalogue
    flagged: list[str] = []
    role_code = planned.action.params.get("job_role")
    role = cat.job_role(role_code) if role_code else None
    if role and role.privileged:
        flagged.append(cat.describe(role.code))
    for code in list(planned.action.params.get("activities", [])) + list(
        planned.action.params.get("add", [])
    ):
        activity = cat.activity(code)
        if activity and activity.privileged:
            flagged.append(cat.describe(activity.code))
    if not flagged:
        return
    who = ("an RA Manager" if not ctx.operator.get("may_approve_privileged")
           else "a second RA Manager")
    planned.add(Issue(
        code="PRIVILEGED_GRANT",
        severity=SEVERITY_APPROVE,
        message=f"Grants privileged access: {'; '.join(sorted(set(flagged)))}.",
        remedy=f"Requires named approval by {who}; this agent will not apply it unapproved.",
    ))


@rule
def baseline_policy(planned: PlannedAction, ctx: PolicyContext) -> None:
    # For an amendment there is no job_role parameter - the role is whatever the
    # position being amended carries, resolved by the planner.
    role_code = (planned.action.params.get("job_role")
                 or planned.resolved.get("position_job_role"))
    activities = list(planned.action.params.get("activities", [])) + list(
        planned.action.params.get("add", [])
    )
    if not role_code or not activities:
        return
    if ctx.catalogue.job_role(role_code) is None:
        return  # already blocked by known_codes
    extra = ctx.catalogue.outside_baseline(role_code, activities)
    if extra:
        described = "; ".join(ctx.catalogue.describe(c) for c in extra)
        planned.add(Issue(
            code="OUTSIDE_BASELINE",
            severity=SEVERITY_APPROVE,
            message=(f"{described} sits outside the national baseline for "
                     f"{ctx.catalogue.describe(role_code)}."),
            remedy="Local RBAC policy must justify the addition, and an RA Manager approve it.",
        ))


@rule
def identity_verified(planned: PlannedAction, ctx: PolicyContext) -> None:
    if planned.action.action_type != "create_user":
        return
    if not planned.action.params.get("id_verification_ref"):
        planned.add(Issue(
            code="UNVERIFIED_IDENTITY",
            severity=SEVERITY_BLOCK,
            message="A Care ID cannot be created without a completed identity check.",
            remedy="Obtain the Apply for Care ID reference, or have the applicant ID-checked first.",
        ))


@rule
def retrospective_revocation(planned: PlannedAction, ctx: PolicyContext) -> None:
    """A leaver dated in the past means access was live after they left."""
    if planned.action.action_type not in ("close_account", "end_position"):
        return
    end_date = planned.action.params.get("end_date")
    if not end_date:
        return
    try:
        when = date.fromisoformat(end_date)
    except ValueError:
        planned.add(Issue(
            code="BAD_DATE",
            severity=SEVERITY_CLARIFY,
            message=f"{end_date!r} is not a date this agent can read.",
            remedy="Confirm the leaving date as YYYY-MM-DD.",
        ))
        return
    if when < ctx.today:
        days = (ctx.today - when).days
        planned.add(Issue(
            code="RETROSPECTIVE_REVOCATION",
            severity=SEVERITY_WARN,
            message=f"Access has remained live for {days} day(s) past the stated leaving date.",
            remedy="Worth recording as an access-control incident as well as revoking.",
        ))


@rule
def illustrative_catalogue(planned: PlannedAction, ctx: PolicyContext) -> None:
    if not ctx.catalogue.is_illustrative:
        return
    severity = SEVERITY_WARN if ctx.backend_is_sandbox else SEVERITY_BLOCK
    planned.add(Issue(
        code="ILLUSTRATIVE_CATALOGUE",
        severity=severity,
        message=(f"RBAC catalogue is '{ctx.catalogue.source}', not an NRD extract."
                 + ("" if ctx.backend_is_sandbox else " Refusing to write to a live backend.")),
        remedy="Load a National RBAC Database extract before running against a real system.",
    ))

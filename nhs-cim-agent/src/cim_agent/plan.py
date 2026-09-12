"""Turn candidate actions into a validated, previewable plan.

Planning is pure: it reads the directory and the catalogue, resolves who and
what each action refers to, runs the policy rules, and returns a plan. It never
writes. Applying a plan is `apply.py`, and it requires the token computed here.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import date
from typing import Any

from .catalogue import Catalogue
from .backends import CIMBackend
from .model import (
    Action,
    Issue,
    SEVERITY_CLARIFY,
    Plan,
    PlannedAction,
    SEVERITY_WARN,
    canonical_json,
    confirmation_token,
    sha256,
    subject_key,
    utc_now,
)
from .policy import PolicyContext, check


class UnknownOperator(ValueError):
    pass


class Planner:
    def __init__(self, backend: CIMBackend, catalogue: Catalogue | None = None,
                 today: date | None = None) -> None:
        self.backend = backend
        self.catalogue = catalogue or Catalogue.load()
        self.today = today or date.today()

    # --- public -------------------------------------------------------------

    def plan(self, actions: list[Action], *, operator_id: str, source_text: str = "",
             source_ref: str = "") -> Plan:
        operator = self.backend.operator(operator_id)
        if operator is None:
            raise UnknownOperator(
                f"{operator_id!r} is not a known RA operator; actions cannot be attributed."
            )
        ctx = PolicyContext(
            operator_id=operator_id,
            operator=operator,
            catalogue=self.catalogue,
            today=self.today,
            backend_is_sandbox=getattr(self.backend, "is_sandbox", False),
        )
        plan = Plan(
            plan_id="plan_" + uuidlib.uuid4().hex[:12],
            created_at=utc_now(),
            operator=operator_id,
            source_sha256=sha256(source_text),
            source_ref=source_ref or "(none)",
        )
        # A joiner's position cannot resolve to a Care ID that does not exist
        # yet. Note which subjects an earlier create_user in this same plan will
        # mint, so the position is held as dependent rather than unanswerable.
        pending_creates = {
            subject_key(a.subject): i
            for i, a in enumerate(actions) if a.action_type == "create_user"
        }

        for index, action in enumerate(actions):
            planned = PlannedAction(index=index, action=action)
            self._resolve_subject(planned)
            self._resolve_position(planned)
            self._link_dependencies(planned, pending_creates)
            self._apply_defaults(planned)
            planned.preview = self._preview(planned)
            check(planned, ctx)
            planned.idempotency_key = self._idempotency_key(planned)
            plan.actions.append(planned)
        plan.confirmation_token = confirmation_token(plan)
        return plan

    # --- resolution ---------------------------------------------------------

    def _resolve_subject(self, planned: PlannedAction) -> None:
        subject = planned.action.subject
        if subject.get("uuid"):
            user = self.backend.get_user(subject["uuid"])
            if user:
                self._record_user(planned, user)
            else:
                planned.resolved["candidate_uuids"] = []
            return

        matches = self.backend.find_users(
            given_name=subject.get("given_name"),
            family_name=subject.get("family_name"),
            email=subject.get("email"),
        )
        planned.resolved["candidate_uuids"] = [u["uuid"] for u in matches]
        if len(matches) == 1:
            self._record_user(planned, matches[0])

    def _resolve_position(self, planned: PlannedAction) -> None:
        """Pin down which existing position an amendment touches.

        Amending activities has no job_role parameter, so without this the
        baseline check has nothing to check against and quietly passes anything.
        The role comes from the position being amended.
        """
        if planned.action.action_type not in ("modify_position_activities", "end_position"):
            return
        uuid = planned.resolved.get("uuid")
        if not uuid:
            return
        user = self.backend.get_user(uuid)
        if not user:
            return
        params = planned.action.params
        candidates = [p for p in user["positions"] if p.get("end_date") is None]
        if params.get("position_id"):
            candidates = [p for p in candidates if p["position_id"] == params["position_id"]]
        if params.get("ods_code"):
            candidates = [p for p in candidates if p["ods_code"] == params["ods_code"]]
        if len(candidates) == 1:
            position = candidates[0]
            planned.resolved["position_id"] = position["position_id"]
            planned.resolved["position_job_role"] = position["job_role"]
            planned.resolved["position_ods"] = position["ods_code"]
            planned.resolved["position_activities"] = list(position["activities"])
        elif candidates:
            planned.add(Issue(
                code="AMBIGUOUS_POSITION",
                severity=SEVERITY_CLARIFY,
                message=(f"{planned.resolved.get('display_name')} holds "
                         f"{len(candidates)} open positions and the request does not say "
                         "which one is meant."),
                remedy="Ask which organisation or position the change applies to.",
            ))
        else:
            planned.add(Issue(
                code="NO_OPEN_POSITION",
                severity=SEVERITY_CLARIFY,
                message=(f"{planned.resolved.get('display_name')} holds no open position "
                         "matching the request."),
                remedy="Confirm the organisation, or whether a new position is intended.",
            ))

    def _link_dependencies(self, planned: PlannedAction,
                           pending_creates: dict[str, int]) -> None:
        key = subject_key(planned.action.subject)
        if planned.action.action_type == "create_user":
            if planned.resolved.get("uuid"):
                planned.add(Issue(
                    code="ALREADY_REGISTERED",
                    severity=SEVERITY_WARN,
                    message=(f"{planned.resolved.get('display_name')} already holds Care ID "
                             f"{planned.resolved['uuid']}; the registration will be a no-op."),
                    remedy="Check this is the same person and not a duplicate registration.",
                ))
            return
        if planned.resolved.get("uuid"):
            return
        creator = pending_creates.get(key)
        if creator is not None and creator < planned.index:
            planned.resolved["awaits_create_index"] = creator
            planned.add(Issue(
                code="DEPENDS_ON_CREATE",
                severity=SEVERITY_WARN,
                message=(f"Applies to the Care ID created by action {creator} in this plan; "
                         "it is skipped if that registration does not go through."),
            ))

    def _record_user(self, planned: PlannedAction, user: dict[str, Any]) -> None:
        planned.resolved["uuid"] = user["uuid"]
        planned.resolved["candidate_uuids"] = [user["uuid"]]
        planned.resolved["display_name"] = f"{user['given_name']} {user['family_name']}"
        planned.resolved["subject_ods"] = sorted(
            {p["ods_code"] for p in user["positions"] if p.get("end_date") is None}
        )
        planned.resolved["account_status"] = user.get("status")
        card = user.get("smartcard")
        if card:
            planned.resolved["smartcard"] = {
                "serial": card["serial"],
                "status": card["status"],
                "certificate_expiry": card["certificate_expiry"],
            }

    def _apply_defaults(self, planned: PlannedAction) -> None:
        """Fill what can be filled safely, and say so where we did."""
        action = planned.action
        if action.action_type == "assign_position":
            role_code = action.params.get("job_role")
            role = self.catalogue.job_role(role_code) if role_code else None
            if role and not action.params.get("activities"):
                action.params["activities"] = sorted(role.baseline_activities)
                planned.add(Issue(
                    code="BASELINE_DEFAULTED",
                    severity=SEVERITY_WARN,
                    message=(f"No activities were requested; defaulted to the national baseline "
                             f"for {self.catalogue.describe(role.code)}."),
                    remedy="Confirm the baseline is what the requester intended.",
                ))
        if action.action_type in ("close_account", "end_position"):
            action.params.setdefault("end_date", None)

    # --- presentation -------------------------------------------------------

    def _preview(self, planned: PlannedAction) -> str:
        a = planned.action
        who = planned.resolved.get("display_name") or planned.resolved.get("uuid") or (
            " ".join(v for v in (a.subject.get("given_name"), a.subject.get("family_name")) if v)
            or "an unidentified person"
        )
        p = a.params
        cat = self.catalogue
        if a.action_type == "create_user":
            return (f"Create a Care ID for {p.get('given_name', '?')} {p.get('family_name', '?')} "
                    f"against identity check {p.get('id_verification_ref') or 'MISSING'}")
        if a.action_type == "assign_position":
            acts = ", ".join(cat.describe(c) for c in p.get("activities", [])) or "no activities"
            return (f"Give {who} a position at {p.get('ods_code') or '(no organisation)'} as "
                    f"{cat.describe(p.get('job_role'))} with {acts}")
        if a.action_type == "end_position":
            where = p.get("ods_code") or p.get("position_id") or "their open position"
            return f"End {who}'s position at {where} on {p.get('end_date') or 'an unstated date'}"
        if a.action_type == "modify_position_activities":
            bits = []
            if p.get("add"):
                bits.append("add " + ", ".join(cat.describe(c) for c in p["add"]))
            if p.get("remove"):
                bits.append("remove " + ", ".join(cat.describe(c) for c in p["remove"]))
            return f"Amend {who}'s activities: {'; '.join(bits) or 'no change'}"
        if a.action_type == "unlock_smartcard":
            card = planned.resolved.get("smartcard", {})
            return (f"Unlock {who}'s smartcard {card.get('serial', '(unknown serial)')} "
                    f"(currently {card.get('status', 'unknown')})")
        if a.action_type == "renew_certificates":
            card = planned.resolved.get("smartcard", {})
            return (f"Renew certificates on {who}'s smartcard "
                    f"{card.get('serial', '(unknown serial)')}, expiring "
                    f"{card.get('certificate_expiry', 'unknown')}")
        if a.action_type == "replace_smartcard":
            return f"Issue {who} a replacement smartcard"
        if a.action_type == "close_account":
            return (f"Close {who}'s Care ID, ending all positions and cancelling the smartcard, "
                    f"effective {p.get('end_date') or 'an unstated date'}")
        if a.action_type == "update_user_details":
            fields = ", ".join(f"{k}={v!r}" for k, v in p.items() if not k.startswith("_"))
            return f"Update {who}: {fields or 'nothing'}"
        return f"{a.action_type} for {who}"

    # --- identity of an action ----------------------------------------------

    def _idempotency_key(self, planned: PlannedAction) -> str:
        """Stable across re-planning the same request, distinct between requests.

        Keyed on the subject *as written*, not on what it resolved to. A joiner
        is an unresolved name the first time the request is planned and a Care
        ID the second time; keying on the resolution would make the replay look
        like a different change and re-apply it.

        Deliberately excludes evidence spans and free-text notes: the same
        instruction phrased differently in two emails is still one change.
        """
        material = canonical_json({
            "action_type": planned.action.action_type,
            "target": subject_key(planned.action.subject),
            "params": {k: v for k, v in planned.action.params.items()
                       if not k.startswith("_")},
        })
        return sha256(material)[:16]

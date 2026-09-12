"""The agent façade: one object that the MCP server and the CLI both drive.

Holds the acting operator's identity, the backend, the catalogue, the audit log
and the plans created so far. Plans live in memory only - if the server
restarts, an outstanding plan id stops resolving and the apply fails closed,
which is the behaviour we want from a thing that changes access rights.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .apply import ApplyReport, apply_plan
from .audit import AuditLog
from .backends import CIMBackend, SandboxBackend
from .catalogue import Catalogue
from .extract import extract
from .model import Action, Plan, Span
from .plan import Planner


class UnknownPlan(KeyError):
    pass


class CimAgentSession:
    def __init__(self, *, operator_id: str, backend: CIMBackend | None = None,
                 catalogue: Catalogue | None = None, audit_path: Path | str | None = None,
                 today: date | None = None, default_ods: str | None = None) -> None:
        self.backend = backend or SandboxBackend()
        self.catalogue = catalogue or Catalogue.load()
        self.audit = AuditLog(audit_path)
        self.today = today or date.today()
        self.operator_id = operator_id
        self.planner = Planner(self.backend, self.catalogue, today=self.today)
        self._plans: dict[str, Plan] = {}
        self._unrecognised: dict[str, list[str]] = {}

        operator = self.backend.operator(operator_id)
        scope = operator.get("scope_ods", []) if operator else []
        self.default_ods = default_ods or (scope[0] if len(scope) == 1 else None)

    # --- reference lookups --------------------------------------------------

    def describe_context(self) -> dict[str, Any]:
        operator = self.backend.operator(self.operator_id) or {}
        return {
            "operator_id": self.operator_id,
            "operator_name": operator.get("name"),
            "operator_job_role": operator.get("job_role"),
            "scope_ods": operator.get("scope_ods", []),
            "may_approve_privileged": operator.get("may_approve_privileged", False),
            "backend": getattr(self.backend, "name", "unknown"),
            "backend_is_sandbox": getattr(self.backend, "is_sandbox", False),
            "catalogue_source": self.catalogue.source,
            "catalogue_is_illustrative": self.catalogue.is_illustrative,
            "today": self.today.isoformat(),
            "organisations": self.backend.organisations(),
        }

    def lookup_codes(self, query: str = "") -> dict[str, Any]:
        q = query.lower().strip()
        def keep(code: str, name: str, synonyms: tuple[str, ...] = ()) -> bool:
            if not q:
                return True
            return q in code.lower() or q in name.lower() or any(q in s for s in synonyms)
        return {
            "job_roles": [
                {"code": r.code, "name": r.name, "privileged": r.privileged,
                 "verified": r.verified, "synonyms": list(r.synonyms),
                 "baseline_activities": sorted(r.baseline_activities)}
                for r in self.catalogue.job_roles.values() if keep(r.code, r.name, r.synonyms)
            ],
            "activities": [
                {"code": a.code, "name": a.name, "sensitive": a.sensitive,
                 "privileged": a.privileged, "verified": a.verified}
                for a in self.catalogue.activities.values() if keep(a.code, a.name)
            ],
            "catalogue_source": self.catalogue.source,
        }

    def find_user(self, **criteria: Any) -> list[dict[str, Any]]:
        uuid = criteria.pop("uuid", None)
        if uuid:
            user = self.backend.get_user(uuid)
            users = [user] if user else []
        else:
            users = self.backend.find_users(**{k: v for k, v in criteria.items() if v})
        return [self._summarise_user(u) for u in users]

    def _summarise_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "uuid": user["uuid"],
            "name": f"{user['given_name']} {user['family_name']}",
            "email": user.get("email"),
            "status": user.get("status"),
            "smartcard": user.get("smartcard"),
            "positions": [
                {**p, "job_role_name": self.catalogue.describe(p["job_role"]),
                 "open": p.get("end_date") is None}
                for p in user["positions"]
            ],
        }

    # --- planning -----------------------------------------------------------

    def plan_from_text(self, text: str, *, source_ref: str = "") -> Plan:
        surnames = {u["family_name"] for u in self.backend.find_users()}
        extraction = extract(
            text,
            catalogue=self.catalogue,
            known_ods=self.backend.organisations().keys(),
            known_surnames=surnames,
            today=self.today,
            default_ods=self.default_ods,
        )
        plan = self.planner.plan(extraction.actions, operator_id=self.operator_id,
                                 source_text=text, source_ref=source_ref)
        self._plans[plan.plan_id] = plan
        self._unrecognised[plan.plan_id] = extraction.unrecognised
        return plan

    def plan_from_actions(self, actions: list[dict[str, Any]], *, source_text: str = "",
                          source_ref: str = "") -> Plan:
        parsed = [
            Action(
                action_type=spec["action_type"],
                subject=spec.get("subject", {}),
                params=spec.get("params", {}),
                evidence=[Span(**s) if isinstance(s, dict) else s
                          for s in spec.get("evidence", [])],
                note=spec.get("note"),
            )
            for spec in actions
        ]
        plan = self.planner.plan(parsed, operator_id=self.operator_id,
                                 source_text=source_text, source_ref=source_ref)
        self._plans[plan.plan_id] = plan
        return plan

    def plan_view(self, plan: Plan) -> dict[str, Any]:
        """The plan as a caller sees it, including text we could not classify.

        Sentences the extractor did not recognise are reported rather than
        dropped: silence about the part of an email you did not understand is
        how a request to revoke someone's access goes missing.
        """
        view = plan.to_dict()
        view["unrecognised_text"] = self._unrecognised.get(plan.plan_id, [])
        return view

    def get_plan(self, plan_id: str) -> Plan:
        try:
            return self._plans[plan_id]
        except KeyError:
            raise UnknownPlan(
                f"No plan {plan_id!r} in this session. Plans are held in memory only; "
                "re-plan the request rather than applying a plan that cannot be shown."
            ) from None

    # --- applying -----------------------------------------------------------

    def apply(self, plan_id: str, *, confirm: str, approvals: dict[int, str] | None = None,
              dry_run: bool = False) -> ApplyReport:
        plan = self.get_plan(plan_id)
        return apply_plan(plan, backend=self.backend, audit=self.audit, confirm=confirm,
                          approvals=approvals, dry_run=dry_run)

    def audit_tail(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.audit.tail(limit)

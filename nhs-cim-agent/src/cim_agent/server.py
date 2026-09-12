"""MCP server exposing Care Identity Management as a set of tools.

The division of labour is the point of the design. The host model reads the
email and decides what was asked for; this server holds the authority, the
reference data and the guardrails, and it is the only thing that can write.
A model cannot talk its way past `policy.py` because the model is not the thing
enforcing it.

Three rules the tool surface enforces rather than requests:

  * every action must carry the span of source text that asked for it;
  * `cim_plan_*` never writes, and returns a confirmation token;
  * `cim_apply_plan` requires that token, so a plan that changed since it was
    shown to a human cannot be applied by mistake.

Run it with `python3 -m cim_agent.server`; the module needs the `mcp` package,
which nothing else in this project does.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from functools import wraps
from typing import Callable, TypeVar

from .apply import ConfirmationMismatch
from .backends import BackendError, SandboxBackend
from .model import ACTION_TYPES
from .plan import UnknownOperator
from .session import CimAgentSession, UnknownPlan

INSTRUCTIONS = """\
Tools for performing Registration Authority work in NHS Care Identity Management.

Work in this order:

1. `cim_context` - read it first. It tells you which RA operator you are acting
   as, which organisations (ODS codes) that operator may act in, and whether the
   backend is a sandbox or a real system.
2. `cim_lookup_codes` and `cim_find_user` - ground what the request says against
   real job roles, activities and Care IDs. Never invent an R code, a B code or
   a 12-digit Care ID; look them up.
3. `cim_plan_actions` - submit the actions you believe the request asks for.
   Every action must carry `evidence`: character offsets into the source text
   that asked for it. Actions without evidence are rejected, not applied.
   If the request is ambiguous - "the same access as Dr Osei", "starting
   Friday" - submit what you are sure of and leave the rest out. The plan comes
   back with clarifying questions you should put to the requester.
4. Show the plan's previews to the human. `cim_apply_plan` needs the plan's
   `confirmation_token`, and privileged grants additionally need a named
   approver who is not the acting operator.

Do not describe an action as done until `cim_apply_plan` reports it applied.
A plan is not a change.
"""


F = TypeVar("F", bound=Callable[..., Any])

# Failures a caller can act on - a stale token, a plan that no longer exists, an
# action type that does not exist. Raised as ToolError so the message reaches the
# model as text it can read, rather than becoming a generic "tool failed".
EXPECTED = (ConfirmationMismatch, UnknownPlan, UnknownOperator, BackendError,
            ValueError, KeyError)


def expected_failures(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except EXPECTED as exc:
            message = str(exc).strip("'\"") or exc.__class__.__name__
            raise ToolError(message) from exc
    return wrapper  # type: ignore[return-value]


def build_session() -> CimAgentSession:
    today = os.environ.get("CIM_TODAY")
    return CimAgentSession(
        operator_id=os.environ.get("CIM_OPERATOR", "j.parker"),
        backend=SandboxBackend(state_path=os.environ.get("CIM_STATE_PATH") or None),
        audit_path=os.environ.get("CIM_AUDIT_PATH") or None,
        today=date.fromisoformat(today) if today else None,
    )


server = MCPServer(
    name="nhs-cim",
    title="NHS Care Identity Management",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)
session = build_session()

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
PLANNING = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                           open_world_hint=False)
WRITING = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                          open_world_hint=False)


@server.tool(
    name="cim_context",
    title="Who am I acting as",
    description=("The acting RA operator, the organisations they may act in, the backend "
                 "in use and the provenance of the RBAC catalogue. Read this before "
                 "planning anything."),
    annotations=READ_ONLY,
)
def cim_context() -> dict[str, Any]:
    return session.describe_context()


@server.tool(
    name="cim_lookup_codes",
    title="Look up job roles and activities",
    description=("Search the loaded RBAC catalogue for job roles (R codes) and activities "
                 "(B codes) by code, name or common phrasing. Pass an empty query for "
                 "everything. Use this instead of recalling codes."),
    annotations=READ_ONLY,
)
def cim_lookup_codes(query: str = "") -> dict[str, Any]:
    return session.lookup_codes(query)


@server.tool(
    name="cim_find_user",
    title="Find a Care ID",
    description=("Find people in the directory by Care ID (UUID), name, email or the ODS "
                 "code of an open position. Returns their positions and smartcard state. "
                 "Several matches means you must ask which person is meant."),
    annotations=READ_ONLY,
)
def cim_find_user(uuid: str = "", given_name: str = "", family_name: str = "",
                  email: str = "", ods_code: str = "") -> dict[str, Any]:
    matches = session.find_user(uuid=uuid, given_name=given_name, family_name=family_name,
                                email=email, ods_code=ods_code)
    return {"count": len(matches), "users": matches}


@server.tool(
    name="cim_plan_actions",
    title="Plan CIM actions (no changes made)",
    description=(
        "Validate actions against the directory, the RBAC catalogue and RA policy, and "
        "return a plan with a preview of each change. Makes no changes.\n\n"
        "Each action is {action_type, subject, params, evidence}:\n"
        "  action_type: create_user | assign_position | end_position | "
        "modify_position_activities | unlock_smartcard | renew_certificates | "
        "replace_smartcard | close_account | update_user_details\n"
        "  subject: {uuid} or {given_name, family_name} - who it is about\n"
        "  params: the action's fields, e.g. {ods_code, job_role, activities, start_date}\n"
        "  evidence: [{start, end, text}] character offsets into source_text. REQUIRED - "
        "an action with no evidence is blocked.\n\n"
        "Returns a confirmation_token that cim_apply_plan will demand."
    ),
    annotations=PLANNING,
)
@expected_failures
def cim_plan_actions(actions: list[dict[str, Any]], source_text: str = "",
                     source_ref: str = "") -> dict[str, Any]:
    for position, spec in enumerate(actions):
        kind = spec.get("action_type")
        if kind not in ACTION_TYPES:
            raise ToolError(
                f"actions[{position}].action_type is {kind!r}. Valid action types are: "
                + ", ".join(ACTION_TYPES)
            )
        if not spec.get("evidence"):
            # Say so now rather than letting it come back blocked, so the model
            # can go and find the span instead of reporting a mysterious refusal.
            raise ToolError(
                f"actions[{position}] ({kind}) has no evidence. Every action needs the "
                "span of source_text that asks for it: "
                '[{"start": <int>, "end": <int>, "text": "<the quoted words>"}]. '
                "If nothing in the text asks for this action, do not submit it."
            )
    plan = session.plan_from_actions(actions, source_text=source_text, source_ref=source_ref)
    return session.plan_view(plan)


@server.tool(
    name="cim_plan_from_text",
    title="Plan from raw text using the built-in rule extractor",
    description=(
        "Run the deterministic rule-based extractor over a request and plan what it finds. "
        "Makes no changes. This is the fallback path and a cross-check on your own reading "
        "- it is conservative and will miss things. Prefer cim_plan_actions, and use this "
        "to compare against what you extracted."
    ),
    annotations=PLANNING,
)
@expected_failures
def cim_plan_from_text(text: str, source_ref: str = "") -> dict[str, Any]:
    plan = session.plan_from_text(text, source_ref=source_ref)
    return session.plan_view(plan)


@server.tool(
    name="cim_get_plan",
    title="Re-read a plan",
    description="Fetch a plan created earlier in this session by its plan_id.",
    annotations=READ_ONLY,
)
@expected_failures
def cim_get_plan(plan_id: str) -> dict[str, Any]:
    return session.plan_view(session.get_plan(plan_id))


@server.tool(
    name="cim_apply_plan",
    title="Apply a plan (changes Care Identity records)",
    description=(
        "Perform the ready actions in a plan. Requires the plan's confirmation_token, "
        "which changes if the plan changes - so you cannot apply a plan a human has not "
        "seen in its current form.\n\n"
        "Blocked actions and actions awaiting clarification are skipped. Actions the "
        "policy flagged as privileged are skipped unless `approvals` names an authorised "
        "approver for them: {\"<action index>\": \"<operator id>\"}. The approver must be "
        "an RA Manager and must not be the operator who planned the actions.\n\n"
        "Set dry_run to see what would happen without changing anything or writing to the "
        "audit log."
    ),
    annotations=WRITING,
)
@expected_failures
def cim_apply_plan(plan_id: str, confirm: str, approvals: dict[str, str] | None = None,
                   dry_run: bool = False) -> dict[str, Any]:
    report = session.apply(
        plan_id,
        confirm=confirm,
        approvals={int(k): v for k, v in (approvals or {}).items()},
        dry_run=dry_run,
    )
    return report.to_dict()


@server.tool(
    name="cim_audit_tail",
    title="Read the audit trail",
    description=("The most recent audit records: what was applied or skipped, by whom, "
                 "under which approval, and the source text that caused it."),
    annotations=READ_ONLY,
)
def cim_audit_tail(limit: int = 20) -> dict[str, Any]:
    return {"entries": session.audit_tail(limit)}


def main() -> None:
    server.run(transport=os.environ.get("CIM_MCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()

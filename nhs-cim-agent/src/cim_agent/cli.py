"""Run the agent without an MCP host.

The MCP server is the real interface; this exists so the prototype can be
demonstrated, tested and diffed from a terminal, and so the extraction can be
inspected without a model in the loop.

    python3 -m cim_agent.cli demo
    python3 -m cim_agent.cli plan samples/01-joiner.txt --apply
    python3 -m cim_agent.cli audit
    python3 -m cim_agent.cli reset
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .backends import SandboxBackend
from .model import (
    STATUS_BLOCKED,
    STATUS_NEEDS_APPROVAL,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
)
from .session import CimAgentSession

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"

# A fixed date so the demo output is stable and the sample dates keep their
# intended relationship to "now" (one leaver in the past, one joiner ahead).
DEMO_TODAY = date(2026, 9, 14)

MARKS = {
    STATUS_READY: "READY  ",
    STATUS_NEEDS_APPROVAL: "APPROVE",
    STATUS_NEEDS_CLARIFICATION: "ASK    ",
    STATUS_BLOCKED: "BLOCKED",
}


def _session(args: argparse.Namespace) -> CimAgentSession:
    return CimAgentSession(
        operator_id=args.operator,
        backend=SandboxBackend(),
        today=args.today,
    )


def _print_plan(session: CimAgentSession, plan) -> None:
    view = session.plan_view(plan)
    summary = view["summary"]
    print(f"  plan {plan.plan_id}   token {plan.confirmation_token}")
    print(f"  {summary['total']} action(s): {summary['ready']} ready, "
          f"{summary['needs_approval']} need approval, "
          f"{summary['needs_clarification']} need clarification, "
          f"{summary['blocked']} blocked")
    print()
    for action in view["actions"]:
        print(f"  [{MARKS[action['status']]}] {action['preview']}")
        for issue in action["issues"]:
            if issue["severity"] == "warn":
                continue
            print(f"             {issue['severity']}: {issue['message']}")
            if issue.get("remedy"):
                print(f"             -> {issue['remedy']}")
        for span in action["evidence"]:
            quoted = " ".join(span["text"].split())
            if len(quoted) > 92:
                quoted = quoted[:89] + "..."
            print(f"             from: “{quoted}”")
        print()
    if view["unrecognised_text"]:
        print("  not classified (reported rather than dropped):")
        for item in view["unrecognised_text"]:
            print(f"    - \u201c{item['text']}\u201d")
            print(f"      {item['reason']}")
        print()


def cmd_plan(args: argparse.Namespace) -> int:
    session = _session(args)
    path = Path(args.path)
    text = path.read_text(encoding="utf-8")
    plan = session.plan_from_text(text, source_ref=path.name)
    print(f"\n=== {path.name} ===\n")
    _print_plan(session, plan)

    if args.json:
        print(json.dumps(session.plan_view(plan), indent=2))

    if not args.apply:
        return 0

    approvals = {}
    for item in args.approve or []:
        index, _, approver = item.partition("=")
        approvals[int(index)] = approver
    report = session.apply(plan.plan_id, confirm=plan.confirmation_token,
                           approvals=approvals, dry_run=args.dry_run)
    result = report.to_dict()
    print(f"  apply{' (dry run)' if args.dry_run else ''}: "
          f"{result['counts']['applied']} applied, {result['counts']['skipped']} skipped, "
          f"{result['counts']['failed']} failed")
    for item in result["applied"]:
        print(f"    applied  {item['preview']} -> {item['detail']}")
    for item in result["skipped"]:
        print(f"    skipped  {item['preview']} ({item['reason']})")
    for item in result["failed"]:
        print(f"    FAILED   {item['preview']} ({item['error']})")
    print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    SandboxBackend().reset()
    session = _session(args)
    context = session.describe_context()
    print(f"\nActing as {context['operator_name']} ({context['operator_id']}, "
          f"{context['operator_job_role']}), scope {', '.join(context['scope_ods'])}")
    print(f"Backend: {context['backend']}   Catalogue: {context['catalogue_source']}   "
          f"Today: {context['today']}")
    for path in sorted(SAMPLES.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        plan = session.plan_from_text(text, source_ref=path.name)
        print(f"\n=== {path.name} ===\n")
        _print_plan(session, plan)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    session = _session(args)
    entries = session.audit_tail(args.limit)
    if not entries:
        print("audit log is empty")
        return 0
    for entry in entries:
        print(f"{entry['at']}  {entry['outcome']:22}  {entry['action_type']:28}  "
              f"{entry['target']}  by {entry['operator']}"
              + (f" approved by {entry['approver']}" if entry.get("approver") else ""))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    backend = SandboxBackend()
    backend.reset()
    audit = ROOT / "data" / ".state" / "audit.jsonl"
    if audit.exists():
        audit.unlink()
    print("sandbox directory and audit log reset")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cim_agent.cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--operator", default="j.parker",
                        help="acting RA operator id (default: j.parker)")
    parser.add_argument("--today", type=date.fromisoformat, default=DEMO_TODAY,
                        help="date to reason from, YYYY-MM-DD (default: the demo date)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="plan one text file, optionally applying it")
    p_plan.add_argument("path")
    p_plan.add_argument("--apply", action="store_true")
    p_plan.add_argument("--dry-run", action="store_true")
    p_plan.add_argument("--approve", action="append", metavar="INDEX=OPERATOR",
                        help="approve a privileged action, e.g. --approve 1=s.adeyemi")
    p_plan.add_argument("--json", action="store_true", help="also print the raw plan")
    p_plan.set_defaults(func=cmd_plan)

    p_demo = sub.add_parser("demo", help="plan every sample, changing nothing")
    p_demo.set_defaults(func=cmd_demo)

    p_audit = sub.add_parser("audit", help="show the tail of the audit log")
    p_audit.add_argument("--limit", type=int, default=20)
    p_audit.set_defaults(func=cmd_audit)

    p_reset = sub.add_parser("reset", help="restore the sandbox and clear the audit log")
    p_reset.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

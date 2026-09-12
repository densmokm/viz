"""Append-only audit trail.

RA activity is auditable by obligation, not by preference: every change to a
Care ID has to be attributable to a named operator with a reason. An agent in
this position needs to leave a better trail than a human would, not a worse
one, so each record carries the source document hash, the span of text that
caused the action, the policy issues raised, and who approved it.

The file is JSON Lines and only ever appended to.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .model import PlannedAction, Plan, utc_now

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / ".state" / "audit.jsonl"


class AuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, plan: Plan, planned: PlannedAction, outcome: str,
               detail: dict[str, Any] | None = None, backend: str = "",
               approver: str | None = None) -> dict[str, Any]:
        entry = {
            "at": utc_now(),
            "plan_id": plan.plan_id,
            "operator": plan.operator,
            "approver": approver,
            "backend": backend,
            "source_ref": plan.source_ref,
            "source_sha256": plan.source_sha256,
            "action_index": planned.index,
            "action_type": planned.action.action_type,
            "idempotency_key": planned.idempotency_key,
            "target": planned.resolved.get("uuid") or planned.action.subject,
            "params": {k: v for k, v in planned.action.params.items() if not k.startswith("_")},
            "evidence": [asdict(s) for s in planned.action.evidence],
            "policy_issues": [asdict(i) for i in planned.issues],
            "outcome": outcome,
            "detail": detail or {},
        }
        line = json.dumps(entry, sort_keys=True, default=str)
        # Open per-write and append: concurrent RA sessions must not be able to
        # truncate each other's trail, and an interrupted run leaves whole lines.
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry

    def entries(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return iter(())
        def _read() -> Iterator[dict[str, Any]]:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield json.loads(line)
        return _read()

    def applied_keys(self) -> set[str]:
        """Idempotency keys of actions that actually changed something."""
        return {
            e["idempotency_key"] for e in self.entries()
            if e["outcome"] == "applied" and e.get("detail", {}).get("changed")
        }

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self.entries())[-limit:]

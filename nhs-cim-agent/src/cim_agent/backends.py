"""The seam between this agent and a system of record.

There is no public write API for Care Identity Management. CIM is a web
application used by Registration Authority staff, so anything that writes to it
in anger has to go through one of:

  1. an RA bulk-operation file, produced here and uploaded by a human;
  2. supervised browser automation driving the CIM UI as a named RA operator;
  3. a national API, if and when one is published.

All three are the same shape from this side - take a validated action, perform
it, return a receipt - so the agent talks to `CIMBackend` and knows nothing
about which of the three is underneath. `SandboxBackend` is the fourth
implementation: a local JSON directory, which is what the prototype ships with
and the only one that exists in this repository.
"""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Protocol

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class BackendError(RuntimeError):
    """The action was understood but could not be performed."""


class CIMBackend(Protocol):
    """What an adapter must provide. Deliberately small."""

    name: str
    is_sandbox: bool

    def get_user(self, uuid: str) -> dict[str, Any] | None: ...

    def find_users(self, *, given_name: str | None = None, family_name: str | None = None,
                   email: str | None = None, ods_code: str | None = None) -> list[dict[str, Any]]: ...

    def organisations(self) -> dict[str, Any]: ...

    def operator(self, operator_id: str) -> dict[str, Any] | None: ...

    def apply_action(self, action_type: str, target: dict[str, Any],
                     params: dict[str, Any]) -> dict[str, Any]: ...


def _years_from(iso_day: str, years: int) -> str:
    d = date.fromisoformat(iso_day)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28).isoformat()


class SandboxBackend:
    """An in-memory Care Identity directory backed by a JSON file.

    Writes land in `state_path` (a copy), never in the seed file, so the
    sandbox resets by deleting one file.
    """

    name = "sandbox"
    is_sandbox = True

    def __init__(self, state_path: Path | str | None = None, seed_path: Path | str | None = None) -> None:
        self.seed_path = Path(seed_path) if seed_path else DATA_DIR / "directory.json"
        self.state_path = Path(state_path) if state_path else DATA_DIR / ".state" / "directory.state.json"
        if not self.state_path.exists():
            self.reset()
        self._db: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))

    def reset(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.seed_path, self.state_path)
        self._db = json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self._db, indent=2) + "\n", encoding="utf-8")

    # --- reads --------------------------------------------------------------

    def get_user(self, uuid: str) -> dict[str, Any] | None:
        user = self._db["users"].get(uuid)
        return deepcopy(user) if user else None

    def find_users(self, *, given_name: str | None = None, family_name: str | None = None,
                   email: str | None = None, ods_code: str | None = None) -> list[dict[str, Any]]:
        out = []
        for user in self._db["users"].values():
            if email and user.get("email", "").lower() != email.lower():
                continue
            if family_name and user["family_name"].lower() != family_name.lower():
                continue
            if given_name and user["given_name"].lower() != given_name.lower():
                continue
            if ods_code and not any(
                p["ods_code"] == ods_code and p.get("end_date") is None for p in user["positions"]
            ):
                continue
            out.append(deepcopy(user))
        return out

    def organisations(self) -> dict[str, Any]:
        return deepcopy(self._db["organisations"])

    def operator(self, operator_id: str) -> dict[str, Any] | None:
        op = self._db["operators"].get(operator_id)
        return deepcopy(op) if op else None

    # --- writes -------------------------------------------------------------

    def apply_action(self, action_type: str, target: dict[str, Any],
                     params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_do_{action_type}", None)
        if handler is None:
            raise BackendError(f"sandbox backend cannot perform {action_type!r}")
        receipt = handler(target, params)
        self._save()
        return receipt

    def _user_or_raise(self, target: dict[str, Any]) -> dict[str, Any]:
        uuid = target.get("uuid")
        user = self._db["users"].get(uuid) if uuid else None
        if user is None:
            raise BackendError(f"no Care ID {uuid!r} in the directory")
        return user

    def _next_uuid(self) -> str:
        highest = max(int(u) for u in self._db["users"])
        return str(highest + 1)

    def _next_position_id(self) -> str:
        used = [p["position_id"] for u in self._db["users"].values() for p in u["positions"]]
        highest = max((int(p.split("-")[1]) for p in used), default=0)
        return f"P-{highest + 1:04d}"

    def _do_create_user(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        existing = self.find_users(
            given_name=params.get("given_name"), family_name=params.get("family_name")
        )
        if existing:
            return {"changed": False, "reason": "user already exists",
                    "uuid": existing[0]["uuid"]}
        uuid = self._next_uuid()
        self._db["users"][uuid] = {
            "uuid": uuid,
            "given_name": params["given_name"],
            "family_name": params["family_name"],
            "email": params.get("email"),
            "status": "active",
            "id_verification_ref": params.get("id_verification_ref"),
            "positions": [],
            "smartcard": None,
        }
        return {"changed": True, "uuid": uuid}

    def _do_assign_position(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        for pos in user["positions"]:
            if (pos["ods_code"] == params["ods_code"]
                    and pos["job_role"] == params["job_role"]
                    and pos.get("end_date") is None):
                return {"changed": False, "reason": "position already held",
                        "position_id": pos["position_id"]}
        position_id = self._next_position_id()
        user["positions"].append({
            "position_id": position_id,
            "ods_code": params["ods_code"],
            "job_role": params["job_role"],
            "activities": list(params.get("activities", [])),
            "workgroup": params.get("workgroup"),
            "start_date": params.get("start_date") or date.today().isoformat(),
            "end_date": None,
        })
        return {"changed": True, "position_id": position_id}

    def _find_position(self, user: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
        if params.get("position_id"):
            return next((p for p in user["positions"]
                         if p["position_id"] == params["position_id"]), None)
        candidates = [p for p in user["positions"] if p.get("end_date") is None]
        if params.get("ods_code"):
            candidates = [p for p in candidates if p["ods_code"] == params["ods_code"]]
        if params.get("job_role"):
            candidates = [p for p in candidates if p["job_role"] == params["job_role"]]
        return candidates[0] if len(candidates) == 1 else None

    def _do_end_position(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        pos = self._find_position(user, params)
        if pos is None:
            raise BackendError("could not identify exactly one open position to end")
        if pos.get("end_date"):
            return {"changed": False, "reason": "position already ended",
                    "position_id": pos["position_id"]}
        pos["end_date"] = params.get("end_date") or date.today().isoformat()
        return {"changed": True, "position_id": pos["position_id"], "end_date": pos["end_date"]}

    def _do_modify_position_activities(self, target: dict[str, Any],
                                       params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        pos = self._find_position(user, params)
        if pos is None:
            raise BackendError("could not identify exactly one open position to modify")
        before = list(pos["activities"])
        for code in params.get("add", []):
            if code not in pos["activities"]:
                pos["activities"].append(code)
        pos["activities"] = [c for c in pos["activities"] if c not in params.get("remove", [])]
        return {"changed": pos["activities"] != before, "position_id": pos["position_id"],
                "activities": list(pos["activities"])}

    def _do_unlock_smartcard(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        card = user.get("smartcard")
        if not card:
            raise BackendError("user holds no smartcard")
        if card["status"] != "locked":
            return {"changed": False, "reason": f"smartcard is {card['status']}, not locked"}
        card["status"] = "active"
        return {"changed": True, "serial": card["serial"]}

    def _do_renew_certificates(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        card = user.get("smartcard")
        if not card:
            raise BackendError("user holds no smartcard")
        new_expiry = _years_from(params.get("effective_date") or date.today().isoformat(), 3)
        if card["certificate_expiry"] >= new_expiry:
            return {"changed": False, "reason": "certificates already valid beyond the new expiry"}
        card["certificate_expiry"] = new_expiry
        return {"changed": True, "serial": card["serial"], "certificate_expiry": new_expiry}

    def _do_replace_smartcard(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        old = user.get("smartcard")
        serials = [u["smartcard"]["serial"] for u in self._db["users"].values() if u.get("smartcard")]
        nxt = max(int(s.split("-")[1]) for s in serials) + 1
        user["smartcard"] = {"serial": f"SC-{nxt}", "status": "active",
                             "certificate_expiry": _years_from(date.today().isoformat(), 3)}
        return {"changed": True, "serial": user["smartcard"]["serial"],
                "replaced": old["serial"] if old else None}

    def _do_close_account(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        if user["status"] == "closed":
            return {"changed": False, "reason": "account already closed"}
        end_date = params.get("end_date") or date.today().isoformat()
        ended = []
        for pos in user["positions"]:
            if pos.get("end_date") is None:
                pos["end_date"] = end_date
                ended.append(pos["position_id"])
        if user.get("smartcard"):
            user["smartcard"]["status"] = "cancelled"
        user["status"] = "closed"
        return {"changed": True, "positions_ended": ended, "end_date": end_date}

    def _do_update_user_details(self, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = self._user_or_raise(target)
        changed = {}
        for field in ("email", "given_name", "family_name"):
            if field in params and params[field] != user.get(field):
                user[field] = params[field]
                changed[field] = params[field]
        return {"changed": bool(changed), "updated": changed}

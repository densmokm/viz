"""Reference data: job roles, activities and the baseline policy.

The shipped `data/rbac.json` is an illustrative subset, not a National RBAC
Database (NRD) extract. Only a handful of its codes are ones I could verify
against NHS England documentation (R8000, R5080, R5090, B0267, B1300, B0825);
the rest are plausible placeholders carrying `"verified": false`.

That distinction is load-bearing rather than decorative: `Catalogue.is_illustrative`
is checked before any write to a non-sandbox backend, so the prototype cannot be
pointed at a real system while it is still reasoning about made-up codes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

R_CODE = re.compile(r"\bR\d{4}\b")
B_CODE = re.compile(r"\bB\d{4}\b")


@dataclass(frozen=True)
class JobRole:
    code: str
    name: str
    synonyms: tuple[str, ...]
    privileged: bool
    baseline_activities: frozenset[str]
    verified: bool


@dataclass(frozen=True)
class Activity:
    code: str
    name: str
    sensitive: bool
    privileged: bool
    verified: bool


class Catalogue:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.source = raw.get("catalogue_source", "unknown")
        self.version = raw.get("version", "0")
        self.job_roles: dict[str, JobRole] = {
            code: JobRole(
                code=code,
                name=spec["name"],
                synonyms=tuple(s.lower() for s in spec.get("synonyms", ())),
                privileged=bool(spec.get("privileged", False)),
                baseline_activities=frozenset(spec.get("baseline_activities", ())),
                verified=bool(spec.get("verified", False)),
            )
            for code, spec in raw.get("job_roles", {}).items()
        }
        self.activities: dict[str, Activity] = {
            code: Activity(
                code=code,
                name=spec["name"],
                sensitive=bool(spec.get("sensitive", False)),
                privileged=bool(spec.get("privileged", False)),
                verified=bool(spec.get("verified", False)),
            )
            for code, spec in raw.get("activities", {}).items()
        }
        # Longest synonym first, so "ra manager" wins over "manager" would-be
        # substrings and "staff nurse" wins over "nurse".
        self._synonym_index: list[tuple[str, str]] = sorted(
            ((syn, role.code) for role in self.job_roles.values() for syn in role.synonyms),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Catalogue":
        path = Path(path) if path else DATA_DIR / "rbac.json"
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @property
    def is_illustrative(self) -> bool:
        return self.source != "nrd-extract"

    # --- lookups ------------------------------------------------------------

    def job_role(self, code: str | None) -> JobRole | None:
        return self.job_roles.get(code.upper()) if code else None

    def activity(self, code: str | None) -> Activity | None:
        return self.activities.get(code.upper()) if code else None

    def match_job_role(self, text: str) -> tuple[str, str] | None:
        """Resolve free text to a job role code.

        Returns (code, matched_phrase), or None. An explicit R code in the text
        always wins over a synonym - if someone wrote the code, use the code.
        """
        explicit = R_CODE.search(text.upper())
        if explicit and explicit.group(0) in self.job_roles:
            return explicit.group(0), explicit.group(0)
        haystack = text.lower()
        for synonym, code in self._synonym_index:
            if re.search(rf"\b{re.escape(synonym)}\b", haystack):
                return code, synonym
        return None

    def find_activities(self, text: str) -> list[str]:
        """Return known B codes written explicitly in the text, in order."""
        seen: list[str] = []
        for match in B_CODE.finditer(text.upper()):
            code = match.group(0)
            if code in self.activities and code not in seen:
                seen.append(code)
        return seen

    # --- policy questions ---------------------------------------------------

    def outside_baseline(self, role_code: str, activities: list[str]) -> list[str]:
        """Activities requested that the role's national baseline does not carry."""
        role = self.job_role(role_code)
        if role is None:
            return list(activities)
        return [a for a in activities if a.upper() not in role.baseline_activities]

    def unknown_codes(self, role_code: str | None, activities: list[str]) -> list[str]:
        unknown = [a for a in activities if a.upper() not in self.activities]
        if role_code and role_code.upper() not in self.job_roles:
            unknown.append(role_code)
        return unknown

    def describe(self, code: str | None) -> str:
        if not code:
            return "(unspecified)"
        role = self.job_role(code)
        if role:
            return f"{role.code} {role.name}"
        activity = self.activity(code)
        if activity:
            return f"{activity.code} {activity.name}"
        return code

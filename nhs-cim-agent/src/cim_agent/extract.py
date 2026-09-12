"""Free text to candidate actions, without a language model.

In the intended deployment the host model does this work: it reads the email,
calls `cim_lookup_*` and `cim_find_user` to ground what it read, and submits
structured actions to `cim_plan_actions`. That is the right division of labour -
language understanding in the model, authority and validation in the server.

This module is the offline fallback, so the prototype can be run and tested
without a model in the loop, and so there is a deterministic baseline to check
the model's extraction against. It is deliberately conservative: where a real
reader would infer, it records an unresolved reference and lets `policy.py`
turn that into a question. "The same access as Dr Osei" and "her last day is
Friday" both come back as clarifications rather than guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from .catalogue import Catalogue
from .model import Action, Span, subject_key

UUID_RE = re.compile(r"\b\d{12}\b")
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
UK_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
LONG_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?"
    r"(?:\s+(\d{4}))?\b", re.IGNORECASE)
WEEKDAY_RE = re.compile(
    r"\b(?:this|next|last)?\s?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE)
TITLED_NAME_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Miss|Sister|Matron|Prof(?:essor)?)\.?\s+"
    r"([A-Z][a-z'’-]+)(?:\s+([A-Z][a-z'’-]+))?\b")
PLAIN_NAME_RE = re.compile(r"\b([A-Z][a-z'’-]+)\s+([A-Z][a-z'’-]+)\b")
ID_CHECK_RE = re.compile(
    r"\b(?:apply for care id|care id|id check(?:ed)?|identity check)[^.\n]{0,40}?"
    r"\b([A-Z]{2,5}[-/]\d{4,10})\b", re.IGNORECASE)
BARE_REF_RE = re.compile(r"\b(CID[-/]\d{4,10})\b", re.IGNORECASE)

PRONOUNS = re.compile(r"\b(?:he|she|they|him|her|them|his|their|hers)\b", re.IGNORECASE)

# Phrases that look like an instruction but do not name anything actionable.
VAGUE_PHRASES = (
    "same access as", "same as", "same permissions as", "same role as",
    "the usual", "usual access", "all the usual", "everything", "full access",
    "whatever", "as before", "like the others", "the standard stuff",
)

# Intent cues, longest first so "no longer needs" beats "needs".
CUES: tuple[tuple[str, str], ...] = (
    ("new starter", "joiner"), ("new start", "joiner"), ("starts with us", "joiner"),
    ("joining us", "joiner"), ("is joining", "joiner"), ("will be joining", "joiner"),
    ("please set up", "joiner"), ("set her up", "joiner"), ("set him up", "joiner"),
    ("set them up", "joiner"), ("onboard", "joiner"), ("starting on", "joiner"),
    ("starts on", "joiner"),
    ("last working day", "leaver"), ("last day", "leaver"), ("is leaving", "leaver"),
    ("has left", "leaver"), ("leaving us", "leaver"), ("resigned", "leaver"),
    ("is a leaver", "leaver"), ("终", "leaver"),
    ("transferring to", "mover"), ("transferring from", "mover"), ("moving to", "mover"),
    ("moves to", "mover"), ("moving from", "mover"), ("rotating to", "mover"),
    ("no longer needs", "revoke"), ("no longer requires", "revoke"),
    ("please remove", "revoke"), ("remove access", "revoke"), ("revoke", "revoke"),
    ("take her off", "revoke"), ("take him off", "revoke"), ("take them off", "revoke"),
    ("locked out", "unlock"), ("locked her card", "unlock"), ("locked his card", "unlock"),
    ("card is locked", "unlock"), ("smartcard is locked", "unlock"),
    ("has locked", "unlock"), ("cannot log in", "unlock"), ("can't log in", "unlock"),
    ("certificates have expired", "renew"), ("certificate has expired", "renew"),
    ("certificates expire", "renew"), ("certificate expires", "renew"),
    ("renew the certificate", "renew"), ("renew her certificate", "renew"),
    ("renew his certificate", "renew"), ("recertify", "renew"), ("re-certify", "renew"),
    ("lost her card", "replace"), ("lost his card", "replace"), ("lost their card", "replace"),
    ("lost smartcard", "replace"), ("damaged", "replace"), ("snapped", "replace"),
    ("replacement card", "replace"), ("replacement smartcard", "replace"),
    ("also needs", "add_activity"), ("additionally needs", "add_activity"),
    ("please add", "add_activity"), ("needs adding", "add_activity"),
)


@dataclass
class Extraction:
    actions: list[Action] = field(default_factory=list)
    unrecognised: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Segment:
    text: str
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    def span(self) -> Span:
        return Span(self.start, self.end, self.text.strip())


def _unwrap(text: str) -> str:
    """Turn hard-wrapped lines into spaces, preserving every offset.

    Email arrives wrapped at 72 columns, which puts "clinical" and
    "practitioner" on different lines and hides the job role from a matcher
    working line by line. Replacing a single newline with a single space is
    length-preserving, so evidence offsets still index the original text.
    Blank lines are left alone - they are real paragraph boundaries.
    """
    return re.sub(r"(?<!\n)\n(?!\n)", " ", text)


def _segments(text: str) -> list[_Segment]:
    """Split into sentence-ish units, keeping absolute offsets for evidence."""
    out: list[_Segment] = []
    for match in re.finditer(r"[^.!?\n]+[.!?]?", text):
        chunk = match.group(0)
        if chunk.strip():
            out.append(_Segment(chunk, match.start()))
    return out


def _parse_date(text: str, today: date) -> tuple[str | None, str | None]:
    """Return (iso_date, unresolved_phrase). Exactly one is non-None, or both None."""
    iso = ISO_DATE_RE.search(text)
    if iso:
        return iso.group(1), None
    uk = UK_DATE_RE.search(text)
    if uk:
        day, month, year = (int(g) for g in uk.groups())
        try:
            return date(year, month, day).isoformat(), None
        except ValueError:
            return None, uk.group(0)
    long = LONG_DATE_RE.search(text)
    if long:
        day = int(long.group(1))
        month = next(i for i, m in enumerate(MONTHS, 1)
                     if m.startswith(long.group(2).lower()))
        year = int(long.group(3)) if long.group(3) else today.year
        try:
            return date(year, month, day).isoformat(), None
        except ValueError:
            return None, long.group(0)
    weekday = WEEKDAY_RE.search(text)
    if weekday:
        # Which Friday? Guessing here is how access stays live after a leaver
        # has gone, so this becomes a question instead.
        return None, weekday.group(0).strip()
    return None, None


def _names(text: str, known_surnames: set[str]) -> list[dict[str, str]]:
    """Names in the order they appear in the text.

    Document order matters: "sort out Priya Nair, she needs the same access as
    Dr Osei" is a request about Priya. Returning the titled name first because
    the titled pattern ran first would silently retarget the action.
    """
    hits: list[tuple[int, dict[str, str]]] = []

    for match in TITLED_NAME_RE.finditer(text):
        first, second = match.group(1), match.group(2)
        given, family = (first, second) if second else ("", first)
        hits.append((match.start(), {k: v for k, v in
                                     {"given_name": given, "family_name": family}.items() if v}))

    for match in PLAIN_NAME_RE.finditer(text):
        given, family = match.group(1), match.group(2)
        # Only trust an untitled name when the surname is one we already hold.
        # Otherwise "Emergency Department" becomes a person.
        if family.lower() not in known_surnames:
            continue
        hits.append((match.start(), {"given_name": given, "family_name": family}))

    out: list[dict[str, str]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for _, name in sorted(hits, key=lambda pair: pair[0]):
        key = (name.get("given_name"), name.get("family_name"))
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _subject(segment: str, known_surnames: set[str]) -> dict[str, str] | None:
    uuid = UUID_RE.search(segment)
    if uuid:
        return {"uuid": uuid.group(0)}
    names = _names(segment, known_surnames)
    return names[0] if names else None


def _cues(segment: str) -> list[str]:
    lowered = segment.lower()
    hits: list[str] = []
    for phrase, intent in CUES:
        if phrase in lowered and intent not in hits:
            hits.append(intent)
    return hits


def _vague(segment: str) -> list[str]:
    lowered = segment.lower()
    return [p for p in VAGUE_PHRASES if p in lowered]


@dataclass
class _Mention:
    """One segment of text, with everything recognised inside it."""

    segment: _Segment
    subject: dict[str, str] | None
    intents: list[str]
    ods: str | None
    job_role: str | None
    activities: list[str]
    iso_date: str | None
    unresolved_date: str | None
    id_ref: str | None
    vague: list[str]
    subject_carried: bool = False

    def has_facts(self) -> bool:
        return any((self.ods, self.job_role, self.activities, self.iso_date, self.id_ref))


def _read_segment(segment: _Segment, catalogue: Catalogue, known_ods: set[str],
                  known_surnames: set[str], today: date) -> _Mention:
    body = segment.text
    role_match = catalogue.match_job_role(body)
    iso, unresolved = _parse_date(body, today)
    ref = ID_CHECK_RE.search(body) or BARE_REF_RE.search(body)
    return _Mention(
        segment=segment,
        subject=_subject(body, known_surnames),
        intents=_cues(body),
        ods=next((o for o in known_ods if o in body.upper()), None),
        job_role=role_match[0] if role_match else None,
        activities=catalogue.find_activities(body),
        iso_date=iso,
        unresolved_date=unresolved,
        id_ref=ref.group(1) if ref else None,
        vague=_vague(body),
    )


def _merge_actions(actions: list[Action]) -> list[Action]:
    """One action per subject per type, with the facts pooled.

    A request rarely arrives in one sentence. "Dr Khan is a new starter at
    ZZG01" and "starting on 21 September" are one joiner, not two, and the
    organisation from the first belongs to the action dated by the second.

    The limitation this buys: a request that genuinely ends two different
    positions for one person collapses into one action. That surfaces as a
    single previewed change for a human to reject, rather than as a silent
    half-application, but it is a real ceiling on the rule-based path.
    """
    merged: dict[tuple[str, str], Action] = {}
    for action in actions:
        key = (subject_key(action.subject), action.action_type)
        existing = merged.get(key)
        if existing is None:
            merged[key] = action
            continue
        for name, value in action.params.items():
            current = existing.params.get(name)
            if isinstance(value, list):
                pooled = list(current or [])
                pooled += [v for v in value if v not in pooled]
                existing.params[name] = pooled
            elif current in (None, "", []) and value not in (None, "", []):
                existing.params[name] = value
        for span in action.evidence:
            if span not in existing.evidence:
                existing.evidence.append(span)
        if action.note and not existing.note:
            existing.note = action.note
    return list(merged.values())


def extract(text: str, *, catalogue: Catalogue, known_ods: Iterable[str],
            known_surnames: Iterable[str], today: date | None = None,
            default_ods: str | None = None) -> Extraction:
    """Read a request into candidate actions.

    Three passes. Read each segment for entities and intent cues; group the
    segments by who they are about, carrying the subject forward across
    sentences that only use a pronoun; then synthesise actions from each
    intent, using that segment's facts first and the rest of the person's
    mentions to fill the gaps.
    """
    today = today or date.today()
    known_ods = set(known_ods)
    known_surnames = {s.lower() for s in known_surnames}
    result = Extraction()

    # Pass 1 - read every segment, and track who the text is currently about.
    mentions: list[_Mention] = []
    carried: dict[str, str] | None = None
    for segment in _segments(_unwrap(text)):
        mention = _read_segment(segment, catalogue, known_ods, known_surnames, today)
        if mention.subject is not None:
            carried = mention.subject
        elif carried is not None and (mention.intents or mention.has_facts()):
            mention.subject = carried
            mention.subject_carried = True
        mentions.append(mention)

    # Pass 2 - group by subject, and pool each person's facts.
    cases: dict[str, list[_Mention]] = {}
    for mention in mentions:
        if mention.subject is None:
            if mention.intents or mention.vague:
                result.unrecognised.append({
                    "text": " ".join(mention.segment.text.split()),
                    "reason": "no person could be identified in or before this sentence",
                })
            continue
        cases.setdefault(subject_key(mention.subject), []).append(mention)

    # Pass 3 - synthesise actions per intent, then pool by action type.
    for group in cases.values():
        subject = group[0].subject or {}
        pooled_ods = next((m.ods for m in group if m.ods), None) or default_ods
        pooled_role = next((m.job_role for m in group if m.job_role), None)
        pooled_ref = next((m.id_ref for m in group if m.id_ref), None)
        pooled_activities: list[str] = []
        for mention in group:
            pooled_activities += [a for a in mention.activities if a not in pooled_activities]
        pooled_vague: list[str] = []
        for mention in group:
            pooled_vague += [v for v in mention.vague if v not in pooled_vague]

        actions: list[Action] = []
        acted_on: set[int] = set()

        for mention in group:
            if not mention.intents:
                continue
            acted_on.add(id(mention))
            ods = mention.ods or pooled_ods
            role = mention.job_role or pooled_role
            activities = mention.activities or pooled_activities
            when = mention.iso_date or next((m.iso_date for m in group if m.iso_date), None)
            evidence = [mention.segment.span()]
            note = ("subject inherited from an earlier sentence"
                    if mention.subject_carried else None)

            def add(action_type: str, params: dict, date_sensitive: bool = False) -> None:
                unresolved = list(pooled_vague)
                if date_sensitive and not when:
                    unresolved += [m.unresolved_date for m in group if m.unresolved_date]
                if unresolved:
                    params = {**params, "_unresolved": sorted(set(unresolved))}
                actions.append(Action(action_type=action_type, subject=dict(subject),
                                      params=params, evidence=list(evidence), note=note))

            for intent in mention.intents:
                if intent == "joiner":
                    add("create_user", {
                        "given_name": subject.get("given_name"),
                        "family_name": subject.get("family_name"),
                        "id_verification_ref": pooled_ref,
                    })
                    add("assign_position", {"ods_code": ods, "job_role": role,
                                            "activities": list(activities),
                                            "start_date": when}, date_sensitive=True)
                elif intent == "leaver":
                    add("close_account", {"end_date": when}, date_sensitive=True)
                elif intent == "mover":
                    add("end_position", {"end_date": when}, date_sensitive=True)
                    add("assign_position", {"ods_code": ods, "job_role": role,
                                            "activities": list(activities),
                                            "start_date": when}, date_sensitive=True)
                elif intent == "revoke":
                    add("end_position", {"ods_code": mention.ods, "end_date": when},
                        date_sensitive=True)
                elif intent == "unlock":
                    add("unlock_smartcard", {})
                elif intent == "renew":
                    add("renew_certificates", {})
                elif intent == "replace":
                    add("replace_smartcard", {})
                elif intent == "add_activity":
                    add("modify_position_activities",
                        {"add": list(activities), "ods_code": ods})

        if not actions and pooled_vague:
            described = ", ".join(repr(v) for v in pooled_vague)
            result.unrecognised.append({
                "text": " ".join(group[0].segment.text.split()),
                "reason": (f"says {described} but names no job role or activity, "
                           "so no action was inferred"),
            })

        result.actions.extend(_merge_actions(actions))

    return result

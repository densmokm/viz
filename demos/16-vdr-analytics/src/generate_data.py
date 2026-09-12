#!/usr/bin/env python3
"""
Synthetic virtual data room telemetry for Project Lantern.

Target: Thornbury Precision Group, a UK precision components manufacturer serving
aerospace and medical, sold by its sponsor through a competitive process. Six
bidders in Phase 2, nine weeks of data room activity.

Every VDR platform (Datasite, Intralinks, Ansarada) logs who opened which document,
when, and for how long. That log is the most honest read available on which bidders
are real -- it is behaviour, not what they tell the banker on a Friday call.

Also emits a register of 60 bidders from PRIOR processes with known outcomes, so
the drop-out model is fitted on history rather than hand-weighted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20260416
rng = np.random.default_rng(SEED)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

DAYS = pd.date_range("2026-01-12", periods=63, freq="D")    # 9 weeks
WEEKS = {d: (d - DAYS[0]).days // 7 + 1 for d in DAYS}

# ---------------------------------------------------------------------------
# Document index
# ---------------------------------------------------------------------------
CATS = {
    "Financial":              (74, 26),   # (documents, mean pages)
    "Commercial & Customers": (58, 18),
    "Legal & Corporate":      (91, 22),
    "HR & Pensions":          (46, 31),
    "Operations & Sites":     (52, 14),
    "Tax":                    (33, 24),
    "IT & Data":              (28, 12),
    "Environmental & H&S":    (24, 19),
    "Insurance":              (18, 16),
}
_DOC = {
    "Financial": ["Divisional trading pack", "Audited statutory accounts", "Trading by product line",
                  "Debtor ageing", "Capex schedule", "Budget and forecast model", "Net debt bridge"],
    "Commercial & Customers": ["Customer contract", "Revenue by customer", "Order book analysis",
                               "Pricing schedule", "Distribution agreement", "Framework agreement", "Tender pipeline"],
    "Legal & Corporate": ["Share register", "Board minutes", "Dispute correspondence", "IP register",
                          "Subsidiary accounts", "Shareholder agreement", "Property lease"],
    "HR & Pensions": ["Scheme member data", "Pension scheme rules", "Employee census", "Bonus scheme rules",
                      "Union agreement", "Senior employment contract", "Redundancy provision"],
    "Operations & Sites": ["Site layout", "Machine register", "Maintenance schedule", "Quality certification",
                           "Supplier agreement", "Inventory ageing"],
    "Tax": ["Corporation tax computation", "VAT return", "Transfer pricing file", "R&D claim", "PAYE settlement"],
    "IT & Data": ["System architecture", "Licence register", "Cyber assessment", "Data processing agreement"],
    "Environmental & H&S": ["Site condition survey", "Permit register", "Accident log", "COSHH assessment"],
    "Insurance": ["Policy schedule", "Claims history", "Broker report"],
}

docs, did = [], 0
for cat, (ndoc, mpages) in CATS.items():
    for _ in range(ndoc):
        did += 1
        docs.append(dict(doc_id=f"D{did:04d}",
                         name=f"{rng.choice(_DOC[cat])} {rng.integers(1, 40)}",
                         category=cat, folder=f"{list(CATS).index(cat)+1:02d} {cat}",
                         pages=int(max(1, rng.poisson(mpages))),
                         uploaded_day=int(rng.integers(0, 18)),
                         relevance=float(rng.uniform(0.004, 0.045) if rng.random() < 0.28
                                         else np.exp(rng.normal(0, 0.5))),
                         heat=1.0))
DOCS = pd.DataFrame(docs)

# A handful of documents carry the issues that will end up in the SPA. They are not
# labelled as such -- the analysis has to find them from how people read them.
HOT = {
    "Actuarial valuation — Thornbury Pension Scheme": ("HR & Pensions", 5.8, 168),
    "Master supply agreement — Halstead Aerospace": ("Commercial & Customers", 5.2, 94),
    "Revenue and margin by customer, FY22–FY25": ("Commercial & Customers", 3.6, 41),
    "Phase I environmental report — Tipton site": ("Environmental & H&S", 3.1, 77),
    "Litigation schedule and counsel opinions": ("Legal & Corporate", 2.7, 53),
    "Working capital: 36-month normalisation": ("Financial", 3.3, 62),
    "Management accounts — December 2025": ("Financial", 2.4, 38),
    "Senior employment contracts and LTIP": ("HR & Pensions", 2.0, 44),
}
for i, (name, (cat, heat, pages)) in enumerate(HOT.items()):
    DOCS.loc[len(DOCS)] = dict(doc_id=f"H{i+1:03d}", name=name, category=cat,
                               folder=f"{list(CATS).index(cat)+1:02d} {cat}",
                               pages=pages, uploaded_day=int(rng.integers(0, 6)),
                               relevance=1.0, heat=heat)
DOCS = DOCS.reset_index(drop=True)

# ---------------------------------------------------------------------------
# Bidders. Each has an attention profile, a team, and an intensity path.
# ---------------------------------------------------------------------------
BAL = {c: 1.0 for c in CATS}
COMMERCIAL = {**BAL, "Commercial & Customers": 3.4, "Operations & Sites": 1.8,
              "Financial": 0.25, "Legal & Corporate": 0.2, "Tax": 0.05, "HR & Pensions": 0.15}
DEEP = {**BAL, "Financial": 1.8, "Commercial & Customers": 1.6, "HR & Pensions": 1.5, "Legal & Corporate": 1.3}
FINLEG = {**BAL, "Financial": 1.7, "Legal & Corporate": 1.6, "Tax": 1.4, "Operations & Sites": 0.6}

BIDDERS = [
    dict(bidder="Marlowe Partners", kind="Sponsor", team=9, advisers=4,
         profile=DEEP, path=("steady", 1.00), senior=0.34),
    dict(bidder="Granton Equity", kind="Sponsor", team=7, advisers=3,
         profile=DEEP, path=("ramp", 0.95), senior=0.30),
    dict(bidder="Aldermoor Industrial", kind="Trade", team=5, advisers=0,
         profile=COMMERCIAL, path=("steady", 0.62), senior=0.11),
    dict(bidder="Pennine Capital", kind="Sponsor", team=6, advisers=2,
         profile=BAL, path=("decay", 0.78), senior=0.26, stop=7),
    dict(bidder="Dunmore Family Office", kind="Family office", team=3, advisers=2,
         profile=FINLEG, path=("steady", 0.42), senior=0.46),
    dict(bidder="Selby Holdings", kind="Trade", team=2, advisers=0,
         profile=COMMERCIAL, path=("fade", 0.32), senior=0.08, stop=4),
]

def intensity(kind, base, t):
    """t is 0..1 through the process."""
    if kind == "steady": return base * (0.85 + 0.3 * np.sin(t * 3.1))
    if kind == "ramp":   return base * np.clip((t - 0.28) / 0.42, 0, 1.25)
    if kind == "decay":  return base * float(np.exp(-3.4 * max(0.0, t - 0.34)))
    if kind == "fade":   return base * float(np.exp(-4.2 * t))
    return base

ROLES = [("Partner / MD", 1.0), ("Director", 0.8), ("Associate", 0.45), ("Analyst", 0.3)]
ADVISER_FIRMS = ["Legal DD", "Financial DD", "Commercial DD", "Insurance & Pensions"]

users, uid = [], 0
for b in BIDDERS:
    for i in range(b["team"]):
        uid += 1
        senior = rng.random() < b["senior"]
        role = ROLES[0][0] if senior and i == 0 else (ROLES[1][0] if senior else
               str(rng.choice([ROLES[2][0], ROLES[3][0]])))
        users.append(dict(user_id=f"U{uid:03d}", bidder=b["bidder"], org=b["bidder"],
                          role=role, is_adviser=0))
    for j in range(b["advisers"]):
        for k in range(int(rng.integers(2, 5))):
            uid += 1
            users.append(dict(user_id=f"U{uid:03d}", bidder=b["bidder"],
                              org=f"{ADVISER_FIRMS[j]} adviser", role=str(rng.choice([r[0] for r in ROLES])),
                              is_adviser=1))
USERS = pd.DataFrame(users)
SENIORITY = dict(ROLES)

# ---------------------------------------------------------------------------
# Access log
# ---------------------------------------------------------------------------
events = []
for b in BIDDERS:
    team = USERS[USERS.bidder == b["bidder"]]
    interest = rng.lognormal(0, 0.85, len(DOCS))          # concentration within a category
    w = (DOCS.category.map(b["profile"]).to_numpy() * DOCS.heat.to_numpy()
         * DOCS.relevance.to_numpy() * interest)
    for di, d in enumerate(DAYS):
        t = di / (len(DAYS) - 1)
        if b.get("stop") and WEEKS[d] > b["stop"]:
            break
        if d.weekday() >= 5 and rng.random() < 0.72:
            continue
        lam = intensity(b["path"][0], b["path"][1], t) * len(team) * 4.6
        n = rng.poisson(max(lam, 0))
        if n == 0:
            continue
        avail = DOCS.uploaded_day.to_numpy() <= di
        p = w * avail
        if p.sum() <= 0:
            continue
        p = p / p.sum()
        picks = rng.choice(len(DOCS), size=int(n), replace=True, p=p)
        who = team.sample(int(n), replace=True, random_state=int(rng.integers(1e9)))
        for doc_i, (_, u) in zip(picks, who.iterrows()):
            doc = DOCS.iloc[doc_i]
            base = 7.5 * doc.pages ** 0.62 * SENIORITY.get(u.role, 0.5)
            dur = float(np.clip(base * np.exp(rng.normal(0, 0.7)), 4, 5400))
            action = "download" if rng.random() < 0.16 else "view"
            events.append((str(d.date()), WEEKS[d], u.user_id, b["bidder"], u.org, u.role,
                           int(u.is_adviser), doc.doc_id, doc.category, int(doc.pages),
                           action, round(dur, 1)))
LOG = pd.DataFrame(events, columns=["date", "week", "user_id", "bidder", "org", "role",
                                    "is_adviser", "doc_id", "category", "pages", "action", "seconds"])

# ---------------------------------------------------------------------------
# Q&A log
# ---------------------------------------------------------------------------
QCAT_W = {"Financial": 1.9, "Commercial & Customers": 1.7, "HR & Pensions": 1.5,
          "Legal & Corporate": 1.3, "Tax": 0.9, "Operations & Sites": 0.8,
          "Environmental & H&S": 0.7, "IT & Data": 0.4, "Insurance": 0.3}
QA_RATE = {"Marlowe Partners": 1.00, "Granton Equity": 0.72, "Pennine Capital": 0.30,
           "Dunmore Family Office": 0.38, "Aldermoor Industrial": 0.16, "Selby Holdings": 0.04}
cats = list(QCAT_W); cw = np.array([QCAT_W[c] for c in cats]); cw = cw / cw.sum()
qa, qid = [], 0
for b in BIDDERS:
    for di, d in enumerate(DAYS):
        t = di / (len(DAYS) - 1)
        lam = intensity(b["path"][0], b["path"][1], t) * QA_RATE[b["bidder"]] * 0.75
        for _ in range(rng.poisson(max(lam, 0))):
            qid += 1
            cat = str(rng.choice(cats, p=cw))
            sla = float(np.clip(rng.gamma(2.4, 1.5) + (2.2 if cat in ("HR & Pensions", "Legal & Corporate") else 0), 0.5, 22))
            qa.append((f"Q{qid:04d}", str(d.date()), WEEKS[d], b["bidder"], cat,
                       round(sla, 1), "Answered" if di < len(DAYS) - 4 else "Open"))
QA = pd.DataFrame(qa, columns=["question_id", "date", "week", "bidder", "category",
                               "days_to_answer", "status"])

# ---------------------------------------------------------------------------
# Prior processes: 60 bidders whose outcomes are known. This is what the
# drop-out model is fitted on, so the coefficients are estimated, not asserted.
# ---------------------------------------------------------------------------
N_HIST = 140
h = pd.DataFrame(dict(
    coverage=np.clip(rng.beta(2.2, 2.6, N_HIST), 0.02, 0.95),
    depth=np.clip(rng.gamma(3.0, 0.33, N_HIST), 0.1, 3.2),
    senior_share=np.clip(rng.beta(2.0, 4.5, N_HIST), 0, 0.8),
    advisers=rng.integers(0, 5, N_HIST).astype(float),
    trend=np.clip(rng.normal(0, 0.55, N_HIST), -1.6, 1.6),
    days_idle=np.clip(rng.gamma(2.0, 3.4, N_HIST), 0, 34),
    qa_count=np.clip(rng.poisson(16, N_HIST), 0, None).astype(float),
))
# true log-odds of WITHDRAWING
z = (2.80 - 2.6 * h.coverage - 0.75 * h.depth - 1.15 * h.senior_share - 0.42 * h.advisers
     - 1.30 * h.trend + 0.105 * h.days_idle - 0.038 * h.qa_count)
h["withdrew"] = (rng.random(N_HIST) < 1 / (1 + np.exp(-z))).astype(int)

DOCS.to_csv(OUT / "documents.csv", index=False)
USERS.to_csv(OUT / "users.csv", index=False)
LOG.to_csv(OUT / "access_log.csv.gz", index=False, compression="gzip")
QA.to_csv(OUT / "qa_log.csv", index=False)
h.to_csv(OUT / "historic_bidders.csv", index=False)

print(f"documents {len(DOCS)}  users {len(USERS)}  access events {len(LOG):,}  questions {len(QA)}")
print(LOG.groupby("bidder").agg(events=("doc_id", "size"), hours=("seconds", lambda s: round(s.sum()/3600))).to_string())
print(f"\nhistoric bidders {N_HIST}, withdrew {int(h.withdrew.sum())}")

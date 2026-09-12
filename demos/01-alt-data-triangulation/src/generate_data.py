#!/usr/bin/env python3
"""
Synthetic outside-in dataset for the Alt Data Triangulation demo.

Target: Kestrel Veterinary Group, a UK vet practice roll-up backed by a mid-market
sponsor and preparing to come to market. Deal codename Project Harrier.

The premise is pre-deal: no data room, no management access beyond the IM. So the
generator produces only what you could actually buy or scrape -- filings, market
data, web panel estimates, reviews, job postings, expert transcripts -- plus a
practice-level "ground truth" panel that the analysis is NOT allowed to use except
to score its own outside-in estimate at the end.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20260912
rng = np.random.default_rng(SEED)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

MONTHS = pd.period_range("2022-10", "2025-03", freq="M")     # 30 months of history
FY = {m: ("FY25" if m >= pd.Period("2024-04", freq="M")
          else "FY24" if m >= pd.Period("2023-04", freq="M") else "FY23") for m in MONTHS}

REGIONS = ["South East", "South West", "Midlands", "North West", "North East", "Scotland", "Wales"]
RW = [0.24, 0.13, 0.19, 0.16, 0.11, 0.10, 0.07]
_P1 = ["Ashgrove", "Bellingham", "Coniston", "Draycott", "Elmswood", "Fairhurst", "Granton", "Harlow",
       "Ingleton", "Kinross", "Langdale", "Marlowe", "Newbold", "Orwell", "Pentland", "Quorn",
       "Redmayne", "Sandhurst", "Tavistock", "Uppingham", "Wraysbury", "Yarrow", "Alderley", "Brackley",
       "Cranfield", "Dunmore", "Ferndale", "Garforth", "Hollinwood", "Ilkley", "Kestrel Vale", "Latimer"]
_P2 = ["Veterinary Centre", "Animal Hospital", "Vets", "Veterinary Surgery", "Pet Clinic",
       "Veterinary Practice", "Animal Care", "Vet Clinic"]

# ---------------------------------------------------------------------------
# Practice estate. 142 practices at the FY24 open; bolt-ons land through both years.
# ---------------------------------------------------------------------------
FY24_OPEN = pd.Period("2023-04", freq="M")
N_LEGACY, N_FY24_ACQ, N_FY25_ACQ = 142, 21, 26
ORGANIC = 0.056          # the true same-store growth rate -- the number to recover

rows, practices = [], []
def make(pid, acquired):
    return dict(practice_id=f"P{pid:03d}",
                name=f"{rng.choice(_P1)} {rng.choice(_P2)}",
                region=str(rng.choice(REGIONS, p=RW)),
                cohort="Legacy" if acquired is None else "Acquired",
                acquired_month=str(acquired) if acquired is not None else "",
                base_rev=float(71_000 * np.exp(rng.normal(0, 0.34)) * (0.80 if acquired is not None else 1.0)),
                quality=float(np.clip(rng.normal(4.42, 0.22), 3.4, 5.0)))

pid = 0
for _ in range(N_LEGACY):
    pid += 1; practices.append(make(pid, None))
for _ in range(N_FY24_ACQ):
    pid += 1; practices.append(make(pid, MONTHS[int(rng.integers(6, 18))]))
for _ in range(N_FY25_ACQ):
    pid += 1; practices.append(make(pid, MONTHS[int(rng.integers(18, 30))]))
PRAC = pd.DataFrame(practices)

SEASON = {1: .98, 2: .94, 3: 1.02, 4: 1.01, 5: 1.06, 6: 1.05, 7: 1.03,
          8: .99, 9: 1.02, 10: 1.01, 11: .97, 12: .92}

for _, p in PRAC.iterrows():
    acq = pd.Period(p.acquired_month, freq="M") if p.acquired_month else None
    for m in MONTHS:
        in_group = acq is None or m >= acq
        t = (m - FY24_OPEN).n / 12.0
        rev = p.base_rev * (1 + ORGANIC) ** t * SEASON[m.month] * float(np.exp(rng.normal(0, 0.07)))
        # Integration disruption: acquired practices lose throughput and rating for
        # roughly a year after the deal, and do not fully recover. This is the
        # signature a review event-study is designed to pick up.
        rating = p.quality
        if acq is not None:
            k = (m - acq).n
            drag = -0.42 * min(1.0, k / 9.0) if k >= 0 else 0.0
            rating = p.quality + drag + rng.normal(0, 0.05)
            rev *= 1 + (-0.06 * min(1.0, k / 8.0))
        visits = rev / 96.0                               # ~GBP 96 average transaction
        n_rev = rng.poisson(max(visits * 0.021, 0.4))     # review propensity
        rows.append((p.practice_id, str(m), FY[m], p.cohort, p.acquired_month, p.region,
                     round(rev if in_group else 0.0, 0), round(visits, 0), int(n_rev),
                     round(float(np.clip(rating, 1, 5)), 2), int(in_group)))

PANEL = pd.DataFrame(rows, columns=["practice_id", "month", "fiscal_year", "cohort",
                                    "acquired_month", "region", "revenue", "visits",
                                    "reviews", "rating", "in_group"])

# ---------------------------------------------------------------------------
# Outside-in signal series. Each is something a subscription actually returns.
# ---------------------------------------------------------------------------
n = len(MONTHS)
tt = np.arange(n) / 12.0
noise = lambda s: rng.normal(0, s, n)

estate = np.array([int(((PRAC.acquired_month == "") |
                        (PRAC.acquired_month <= str(m))).sum()) for m in MONTHS])
acq_filed = np.array([int((PRAC.acquired_month == str(m)).sum()) for m in MONTHS])

sessions = 412_000 * (1 + 0.165 * tt) * (1 + 0.05 * np.sin(tt * 6.3)) * (1 + noise(.035))
paid_share = np.clip(0.118 + 0.092 * tt + noise(.012), 0.05, 0.6)
branded_share = np.clip(0.61 - 0.075 * tt + noise(.014), 0.2, 0.9)

gd_rating = 3.92 - 0.34 * tt + noise(.045)
gd_peer = 3.58 - 0.02 * tt + noise(.035)
gd_clinical = 3.81 - 0.46 * tt + noise(.055)
vacancies = 63 * (1 + 0.56 * tt) * (1 + noise(.09))
time_to_fill = 34 + 15.4 * tt + noise(1.9)
tp_rating = 4.12 - 0.30 * tt + noise(.05)
tp_peer = 4.05 - 0.03 * tt + noise(.045)
price_complaints = np.clip(0.041 + 0.037 * tt + noise(.006), 0.005, 0.4)
price_complaints_peer = np.clip(0.047 + 0.004 * tt + noise(.006), 0.005, 0.4)
indep_share = np.clip(0.624 - 0.046 * tt + noise(.006), 0.2, 0.9)
sector_lfl = 0.052 + 0.004 * np.sin(tt * 4) + noise(.004)
peer_deals = np.round(11 * (1 + 0.30 * tt) * (1 + noise(.13)))
cma_mentions = np.round(np.clip(3 + 9.5 * tt ** 1.7 + noise(1.4), 0, None))
news_sent = 0.21 - 0.30 * tt + noise(.05)
comp_largest_estate = np.round(96 * (1 + 0.12 * tt))
staff_mentions = np.round(np.clip(6 + 11 * tt ** 1.4 + noise(1.6), 0, None))
estate_lead = estate / comp_largest_estate                 # scale vs the nearest rival
corp_share = estate / (estate + comp_largest_estate * 2.4)  # share of corporate-owned estate

SOURCES = {
    "Companies House": ("Regulatory filings", 0.95),
    "S&P Capital IQ":  ("Market data", 0.90),
    "Preqin":          ("Market data", 0.82),
    "Gain.Pro":        ("Market data", 0.75),
    "SimilarWeb":      ("Web panel", 0.62),
    "Google Reviews":  ("User reviews", 0.72),
    "Trustpilot":      ("User reviews", 0.58),
    "Glassdoor":       ("Employee reviews", 0.55),
    "Indeed":          ("Labour market", 0.68),
    "AlphaSense":      ("Expert network", 0.70),
    "Quid":            ("Media", 0.50),
}

# derived from the practice panel -- these are the ones you really can observe
OWNED = PANEL[PANEL.in_group == 1]
by_m = OWNED.groupby("month")
rev_per_prac = (by_m.reviews.sum() / by_m.practice_id.count()).reindex([str(m) for m in MONTHS]).to_numpy()
legacy = OWNED[OWNED.cohort == "Legacy"].groupby("month")
legacy_rev_per_prac = (legacy.reviews.sum() / legacy.practice_id.count()).reindex([str(m) for m in MONTHS]).to_numpy()
grp_rating = by_m.apply(lambda d: np.average(d.rating, weights=d.reviews + 1), include_groups=False)
grp_rating = grp_rating.reindex([str(m) for m in MONTHS]).to_numpy()

SERIES = [
    # key, label, source, unit, target, peer, sample n
    ("acq_filed", "Practice acquisitions filed", "Companies House", "per month", acq_filed, None, None),
    ("estate", "Practices in the estate", "Companies House", "practices", estate, None, None),
    ("comp_estate", "Largest competitor estate", "Companies House", "practices", comp_largest_estate, None, None),
    ("estate_lead", "Estate size vs largest competitor", "Companies House", "x", estate_lead, None, None),
    ("corp_share", "Share of corporate-owned practices", "Gain.Pro", "%", corp_share, None, None),
    ("staff_mentions", "Transcripts citing vet recruitment difficulty", "AlphaSense", "per month", staff_mentions, None, None),
    ("sector_lfl", "Listed comparable like-for-like growth", "S&P Capital IQ", "%", sector_lfl, None, 3),
    ("peer_deals", "Sector transactions completed", "Preqin", "per month", peer_deals, None, None),
    ("indep_share", "Independent share of UK practices", "Gain.Pro", "%", indep_share, None, None),
    ("sessions", "Booking portal sessions", "SimilarWeb", "per month", sessions, None, None),
    ("sessions_pp", "Sessions per practice", "SimilarWeb", "per month", sessions / estate, None, None),
    ("paid_share", "Paid share of sessions", "SimilarWeb", "%", paid_share, None, None),
    ("branded_share", "Branded search share", "SimilarWeb", "%", branded_share, None, None),
    ("rev_vol_pp", "Review volume per practice", "Google Reviews", "per month", legacy_rev_per_prac, None, None),
    ("g_rating", "Google rating, estate weighted", "Google Reviews", "stars", grp_rating, None, None),
    ("tp_rating", "Trustpilot rating", "Trustpilot", "stars", tp_rating, tp_peer, None),
    ("price_cmp", "Reviews mentioning price or billing", "Trustpilot", "%", price_complaints, price_complaints_peer, None),
    ("gd_rating", "Glassdoor overall rating", "Glassdoor", "stars", gd_rating, gd_peer, None),
    ("gd_clinical", "Glassdoor clinical staff rating", "Glassdoor", "stars", gd_clinical, gd_peer, None),
    ("vacancies", "Open veterinary surgeon vacancies", "Indeed", "postings", vacancies, None, None),
    ("time_to_fill", "Median days to fill a vet role", "Indeed", "days", time_to_fill, None, None),
    ("cma_mentions", "Transcripts citing CMA pricing review", "AlphaSense", "per month", cma_mentions, None, None),
    ("news_sent", "Media sentiment, net", "Quid", "index", news_sent, None, None),
]

sig_rows = []
for key, label, source, unit, tgt, peer, nn in SERIES:
    fam, rel = SOURCES[source]
    for i, m in enumerate(MONTHS):
        sig_rows.append((key, label, source, fam, rel, unit, str(m), FY[m],
                         float(tgt[i]), None if peer is None else float(peer[i])))
SIG = pd.DataFrame(sig_rows, columns=["signal", "label", "source", "family", "reliability",
                                      "unit", "month", "fiscal_year", "value", "peer_value"])

# observation counts drive the sample-adequacy haircut
SAMPLE_N = {"acq_filed": 47, "estate": 189, "comp_estate": 189, "sector_lfl": 3, "peer_deals": 284,
            "indep_share": 4100, "sessions": 412, "sessions_pp": 412, "paid_share": 412,
            "branded_share": 412, "rev_vol_pp": 28400, "g_rating": 28400, "tp_rating": 3120,
            "price_cmp": 3120, "gd_rating": 214, "gd_clinical": 96, "vacancies": 1180,
            "time_to_fill": 1180, "cma_mentions": 61, "news_sent": 430,
            "estate_lead": 189, "corp_share": 4100, "staff_mentions": 88}
SIG["n"] = SIG.signal.map(SAMPLE_N)
# how stale each feed is at the point of analysis (months)
SIG["latency"] = SIG.source.map({"Companies House": 2.5, "Gain.Pro": 3.0, "S&P Capital IQ": 1.5,
                                 "Preqin": 2.0, "SimilarWeb": 0.5, "Google Reviews": 0.2,
                                 "Trustpilot": 0.2, "Glassdoor": 0.5, "Indeed": 0.2,
                                 "AlphaSense": 0.5, "Quid": 0.2})

PANEL.to_csv(OUT / "practice_panel.csv", index=False)
PRAC.to_csv(OUT / "practices.csv", index=False)
SIG.to_csv(OUT / "signals.csv", index=False)

g = PANEL.groupby("fiscal_year").revenue.sum()
print(f"practices {len(PRAC)}  panel rows {len(PANEL):,}  signals {SIG.signal.nunique()} x {len(MONTHS)} months")
print(f"estate {estate[6]} -> {estate[-1]}   acquisitions filed {int(acq_filed.sum())}")
print((g / 1e6).round(2).to_string())
print(f"reported growth FY24->FY25 {g['FY25']/g['FY24']-1:.1%}   true same-store {ORGANIC:.1%}")

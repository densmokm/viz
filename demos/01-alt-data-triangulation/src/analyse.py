#!/usr/bin/env python3
"""
Triangulation engine for Project Harrier.

Seven claims from the information memorandum, tested against 23 outside-in
signals from 11 subscriptions. The engine does four things:

  1. standardise every signal onto one comparable scale, peer-adjusted
  2. weight each by source reliability, feed latency and sample adequacy
  3. score each claim, and -- the part that matters -- score the CONFIDENCE
     separately, so that agreement between two correlated review sites cannot
     masquerade as corroboration
  4. rank where the diligence budget should go

Confidence rises only when three things hold at once: enough evidence mass,
enough INDEPENDENT source families, and coherence between them. A single
authoritative source can never produce a confident verdict on its own.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data"

SIG = pd.read_csv(OUT / "signals.csv")
PANEL = pd.read_csv(OUT / "practice_panel.csv")
PRAC = pd.read_csv(OUT / "practices.csv")
SIG["month"] = pd.PeriodIndex(SIG.month, freq="M")
PANEL["month"] = pd.PeriodIndex(PANEL.month, freq="M")

FY0, FY1 = "FY24", "FY25"
FY1_OPEN = pd.Period("2024-04", freq="M")
FY0_OPEN = pd.Period("2023-04", freq="M")
CLAIMED_ORGANIC = 0.090          # the IM's headline like-for-like rate
CLAIMED_INDEP = 0.60             # the IM's "60% of the market is independent"

# ---------------------------------------------------------------------------
# What you can actually see from outside: filed accounts and dated filings
# ---------------------------------------------------------------------------
R0 = float(PANEL[PANEL.fiscal_year == FY0].revenue.sum())
R1 = float(PANEL[PANEL.fiscal_year == FY1].revenue.sum())

def practice_months(fy_open):
    """Split owned practice-months in a year into legacy and acquired."""
    months = pd.period_range(fy_open, fy_open + 11, freq="M")
    legacy = acquired = 0
    for _, p in PRAC.iterrows():
        acq = pd.Period(p.acquired_month, freq="M") if isinstance(p.acquired_month, str) and p.acquired_month else None
        owned = sum(1 for m in months if acq is None or m >= acq)
        if acq is None or acq < FY0_OPEN:
            legacy += owned
        else:
            acquired += owned
    return legacy, acquired

LPM0, APM0 = practice_months(FY0_OPEN)
LPM1, APM1 = practice_months(FY1_OPEN)

def implied_organic(alpha: float) -> float:
    """
    Revenue per legacy practice-month is r; an acquired practice earns alpha*r.
    Then  R0 = r(LPM0 + a*APM0)  and  R1 = r(1+g)(LPM1 + a*APM1), so

        1 + g = [R1 (LPM0 + a*APM0)] / [R0 (LPM1 + a*APM1)]

    Everything on the right is observable except alpha -- which is why the
    honest outside-in answer is a band, not a point.
    """
    return (R1 * (LPM0 + alpha * APM0)) / (R0 * (LPM1 + alpha * APM1)) - 1

ALPHAS = np.round(np.arange(0.65, 1.001, 0.05), 2)
BAND = [dict(alpha=float(a), organic=float(implied_organic(a))) for a in ALPHAS]
ORG_LO, ORG_HI = min(b["organic"] for b in BAND), max(b["organic"] for b in BAND)
ORG_MID = float(implied_organic(0.80))

# ground truth, available only because this is synthetic -- the engine never uses it
same_store = PRAC[(PRAC.acquired_month.isna()) | (PRAC.acquired_month == "")].practice_id
ss = PANEL[PANEL.practice_id.isin(same_store)]
TRUE_ORGANIC = float(ss[ss.fiscal_year == FY1].revenue.sum() / ss[ss.fiscal_year == FY0].revenue.sum() - 1)

# ---------------------------------------------------------------------------
# Signal standardisation
# ---------------------------------------------------------------------------
WIN = 6          # comparison window, months
N_REF = 500      # sample size at which the adequacy haircut disappears

def series(key):
    s = SIG[SIG.signal == key].sort_values("month")
    return s.value.to_numpy(), (s.peer_value.to_numpy() if s.peer_value.notna().any() else None), s.iloc[0]

def _resid_sd(x):
    """Noise around the trend -- not the trend itself. Linear-detrend, then take
    the residual standard deviation."""
    t = np.arange(len(x))
    fit = np.polyval(np.polyfit(t, x, 1), t)
    return max(float((x - fit).std(ddof=2)), 1e-9)

def trend_d(key, additive=False):
    """Peer-adjusted move over the comparison window, standardised by the standard
    error of the difference between two WIN-month means, then squashed to [-1, 1].

    The earlier version divided by annualised month-to-month volatility, which is
    roughly six times the right denominator: a six-month mean is far less noisy
    than a single month, and using the wrong one crushes every signal toward zero.
    """
    v, peer, _ = series(key)
    additive = additive or float(np.min(v)) <= 0    # counts that touch zero have no log
    x = v if additive else np.log(np.maximum(v, 1e-9))
    recent, prior = x[-WIN:].mean(), x[-(WIN + 12):-12].mean()
    delta = recent - prior
    if peer is not None:
        q = peer if additive else np.log(np.maximum(peer, 1e-9))
        delta -= q[-WIN:].mean() - q[-(WIN + 12):-12].mean()
    se = _resid_sd(x) * np.sqrt(2.0 / WIN)
    return (float(np.tanh((delta / se) / 6.0)),
            float(v[-WIN:].mean()), float(v[-(WIN + 12):-12].mean()))

def fmt_level(a, b, unit):
    if unit == "%":       return f"{a:.1%} vs {b:.1%}"
    if unit == "stars":   return f"{a:.2f} vs {b:.2f} stars"
    if unit == "days":    return f"{a:.0f}d vs {b:.0f}d"
    if unit in ("x", "index"): return f"{a:.2f} vs {b:.2f}"
    return f"{a:,.0f} vs {b:,.0f}"

def annualised(key):
    v, _, _ = series(key)
    return float((v[-WIN:].mean() / v[-(WIN + 12):-12].mean()) ** 1.0 - 1)

def weight(key):
    row = SIG[SIG.signal == key].iloc[0]
    recency = float(np.exp(-row.latency / 9.0))
    adequacy = float(min(1.0, np.log1p(row.n) / np.log1p(N_REF)))
    return float(row.reliability * recency * adequacy), row

# level-mode observations: what the data says the number actually is
OBS_LEVEL = {
    "implied_organic": (ORG_MID, CLAIMED_ORGANIC, 0.020, "Companies House"),
    "rev_vol_growth": (annualised("rev_vol_pp"), CLAIMED_ORGANIC, 0.025, "Google Reviews"),
    "sessions_pp_growth": (annualised("sessions_pp"), CLAIMED_ORGANIC, 0.030, "SimilarWeb"),
    "indep_level": (float(series("indep_share")[0][-1]), CLAIMED_INDEP, 0.040, "Gain.Pro"),
}

# ---------------------------------------------------------------------------
# The claims, and which signals bear on them
# ---------------------------------------------------------------------------
# link = (signal key, relevance 0-1, align, mode)
#   align +1  -> the claim is supported when the signal moves UP (or reads HIGH)
#   align -1  -> the claim is supported when the signal moves DOWN
CLAIMS = [
    dict(id="C1", materiality=1.00,
         text="Like-for-like revenue growth of 9%, driven by underlying clinical demand",
         links=[("implied_organic", 1.0, +1, "level"), ("rev_vol_growth", 0.9, +1, "level"),
                ("sessions_pp_growth", 0.6, +1, "level"), ("estate", 0.8, -1, "trend"),
                ("time_to_fill", 0.5, -1, "trend")]),
    dict(id="C2", materiality=0.75,
         text="Our membership plan delivers 40% higher lifetime value per client",
         links=[("tp_rating", 0.35, +1, "trend"), ("news_sent", 0.25, +1, "trend")]),
    dict(id="C3", materiality=0.85,
         text="We are the employer of choice in the profession",
         links=[("gd_rating", 0.9, +1, "trend"), ("gd_clinical", 0.8, +1, "trend"),
                ("vacancies", 0.7, -1, "trend"), ("time_to_fill", 0.8, -1, "trend"),
                ("staff_mentions", 0.5, -1, "trend")]),
    dict(id="C4", materiality=0.60,
         text="Our digital booking platform is driving new client acquisition",
         links=[("sessions", 0.6, +1, "trend"), ("sessions_pp", 0.8, +1, "trend"),
                ("paid_share", 0.7, -1, "trend"), ("branded_share", 0.6, +1, "trend"),
                ("rev_vol_pp", 0.5, +1, "trend")]),
    dict(id="C5", materiality=0.70,
         text="Consolidation runway remains substantial: 60% of the market is independent",
         links=[("indep_level", 0.9, +1, "level"), ("peer_deals", 0.6, -1, "trend"),
                ("comp_estate", 0.5, -1, "trend")]),
    dict(id="C6", materiality=0.90,
         text="Our pricing is in line with the market",
         links=[("price_cmp", 0.9, -1, "trend"), ("cma_mentions", 0.7, -1, "trend"),
                ("news_sent", 0.5, +1, "trend"), ("tp_rating", 0.4, +1, "trend")]),
    dict(id="C7", materiality=0.45,
         text="We operate at greater scale than any competitor in our core regions",
         links=[("estate_lead", 0.9, +1, "trend"), ("corp_share", 0.8, +1, "trend"),
                ("sessions", 0.5, +1, "trend")]),
]

def evaluate(claim):
    ev = []
    for key, rel, align, mode in claim["links"]:
        if mode == "level":
            obs, claimed, tol, src = OBS_LEVEL[key]
            d = float(np.tanh((obs - claimed) / tol)) * align
            w, row = weight({"implied_organic": "estate", "rev_vol_growth": "rev_vol_pp",
                             "sessions_pp_growth": "sessions_pp", "indep_level": "indep_share"}[key])
            label = {"implied_organic": "Acquisition-adjusted organic growth",
                     "rev_vol_growth": "Review volume growth, legacy practices",
                     "sessions_pp_growth": "Sessions per practice, growth",
                     "indep_level": "Independent share of the market"}[key]
            detail = f"{obs:.1%} observed vs {claimed:.0%} claimed"
            source, family = src, SIG[SIG.source == src].iloc[0].family
        else:
            d, recent, prior = trend_d(key, additive=key in ("news_sent", "sector_lfl"))
            d *= align
            w, row = weight(key)
            label, source, family = row.label, row.source, row.family
            detail = fmt_level(recent, prior, row.unit) + ", vs a year earlier"
        ev.append(dict(signal=key, label=label, source=source, family=family, mode=mode,
                       d=float(d), relevance=rel, weight=float(w * rel), detail=detail))

    W = sum(e["weight"] for e in ev)
    gross = sum(e["weight"] * abs(e["d"]) for e in ev)
    E = sum(e["weight"] * e["d"] for e in ev) / W if W else 0.0
    coherence = abs(sum(e["weight"] * e["d"] for e in ev)) / gross if gross else 0.0
    fams = len({e["family"] for e in ev})
    diversity = 1 - np.exp(-0.9 * (fams - 1))
    mass = 1 - np.exp(-W / 1.6)
    # Three conditions, none of which can be substituted for another: enough
    # evidence, enough INDEPENDENT families, and agreement between them. The roots
    # stop the product from compounding into pessimism when all three are decent.
    conf = float(mass * np.sqrt(diversity) * np.sqrt(coherence))

    # "We cannot see this" and "the sources disagree" are different findings and
    # deserve different labels. Collapsing them into one verdict hides the second.
    if mass < 0.40:
        verdict = "Not testable outside-in"
    elif coherence < 0.60:
        verdict = "Contested"
    elif E >= 0.25:
        verdict = "Supported"
    elif E <= -0.25:
        verdict = "Challenged"
    else:
        verdict = "Mixed"
    priority = claim["materiality"] * (max(0.0, -E) * conf + (1 - conf) * 0.5)
    return dict(**{k: v for k, v in claim.items() if k != "links"},
                evidence=sorted(ev, key=lambda e: -abs(e["d"] * e["weight"])),
                score=float(E), confidence=conf, coherence=float(coherence),
                diversity=float(diversity), mass=float(mass), families=int(fams),
                weight_total=float(W), verdict=verdict, priority=float(priority))

SCORED = [evaluate(c) for c in CLAIMS]


# ---------------------------------------------------------------------------
# Event study: what happens to a practice's Google profile after it is acquired
# ---------------------------------------------------------------------------
acq = PANEL[PANEL.cohort == "Acquired"].copy()
acq["acq_m"] = pd.PeriodIndex(acq.acquired_month, freq="M")
acq["k"] = (acq.month - acq.acq_m).apply(lambda x: x.n)
ctrl = PANEL[PANEL.cohort == "Legacy"]
ctrl_base = float(ctrl[ctrl.month < FY1_OPEN].rating.mean())

EVENT = []
for k in range(-9, 16):
    w = acq[acq.k == k]
    if len(w) < 8:
        continue
    c = ctrl[ctrl.month.isin(w.month.unique())]
    EVENT.append(dict(k=int(k), n=int(w.practice_id.nunique()),
                      rating=float(np.average(w.rating, weights=w.reviews + 1)),
                      control=float(np.average(c.rating, weights=c.reviews + 1)),
                      reviews=float(w.reviews.mean())))
_pre = np.mean([e["rating"] for e in EVENT if e["k"] < 0])
_post = np.mean([e["rating"] for e in EVENT if e["k"] >= 9])
_pre_v = np.mean([e["reviews"] for e in EVENT if e["k"] < 0])
_post_v = np.mean([e["reviews"] for e in EVENT if e["k"] >= 9])
EVENT_SUMMARY = dict(rating_drop=float(_post - _pre), pre=float(_pre), post=float(_post),
                     volume_change=float(_post_v / _pre_v - 1),
                     control_drift=float(np.mean([e["control"] for e in EVENT if e["k"] >= 9])
                                         - np.mean([e["control"] for e in EVENT if e["k"] < 0])),
                     n_practices=int(acq.practice_id.nunique()))

# ---------------------------------------------------------------------------
# What the growth question is worth
# ---------------------------------------------------------------------------
EBITDA_MARGIN, ENTRY_MULT, HOLD = 0.182, 12.0, 4
def ev_at(g):
    return float(R1 * (1 + g) ** HOLD * EBITDA_MARGIN * ENTRY_MULT)
VALUATION = dict(margin=EBITDA_MARGIN, multiple=ENTRY_MULT, hold=HOLD,
                 fy25_revenue=R1, fy25_ebitda=float(R1 * EBITDA_MARGIN),
                 ev_claimed=ev_at(CLAIMED_ORGANIC), ev_lo=ev_at(ORG_LO), ev_hi=ev_at(ORG_HI),
                 ev_mid=ev_at(ORG_MID), gap=float(ev_at(CLAIMED_ORGANIC) - ev_at(ORG_MID)))

# ---------------------------------------------------------------------------
# Source register and the claim x family matrix
# ---------------------------------------------------------------------------
SOURCES = []
for src, g in SIG.groupby("source"):
    w, _ = weight(g.iloc[0].signal)
    SOURCES.append(dict(source=src, family=g.iloc[0].family, reliability=float(g.iloc[0].reliability),
                        latency=float(g.iloc[0].latency), signals=int(g.signal.nunique()),
                        recency=float(np.exp(-g.iloc[0].latency / 9.0))))
SOURCES.sort(key=lambda s: -s["reliability"])
FAMILIES = sorted(SIG.family.unique())
MATRIX = [dict(claim=c["id"], cells=[
    (lambda ev: dict(family=f, d=float(np.average([e["d"] for e in ev], weights=[e["weight"] for e in ev])),
                     n=len(ev)) if ev else dict(family=f, d=None, n=0))
    ([e for e in c["evidence"] if e["family"] == f]) for f in FAMILIES]) for c in SCORED]

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def ser(key, additive=False):
    s = SIG[SIG.signal == key].sort_values("month")
    return dict(label=s.iloc[0].label, source=s.iloc[0].source, unit=s.iloc[0].unit,
                months=[m.strftime("%b-%y") for m in s.month],
                values=[float(v) for v in s.value],
                peer=[float(v) for v in s.peer_value] if s.peer_value.notna().any() else None)

results = dict(
    meta=dict(company="Kestrel Veterinary Group", codename="Project Harrier",
              sector="UK veterinary practice consolidation", stage="Pre-deal / commercial DD",
              sources=int(SIG.source.nunique()), signals=int(SIG.signal.nunique()),
              families=len(FAMILIES), months=int(SIG.month.nunique()),
              practices=int(len(PRAC)), acquisitions=int((PRAC.acquired_month.fillna("") != "").sum())),
    claims=SCORED, families=FAMILIES, matrix=MATRIX, sources=SOURCES,
    growth=dict(r0=R0, r1=R1, reported=float(R1 / R0 - 1), claimed=CLAIMED_ORGANIC,
                band=BAND, lo=ORG_LO, hi=ORG_HI, mid=ORG_MID, truth=TRUE_ORGANIC,
                estate0=int(143), estate1=int(len(PRAC)),
                lpm0=LPM0, apm0=APM0, lpm1=LPM1, apm1=APM1,
                acq_contribution=float((R1 / R0 - 1) - ORG_MID)),
    event=dict(points=EVENT, summary=EVENT_SUMMARY),
    valuation=VALUATION,
    series={k: ser(k) for k in ["gd_rating", "gd_clinical", "vacancies", "time_to_fill",
                                "sessions", "sessions_pp", "paid_share", "branded_share",
                                "price_cmp", "cma_mentions", "indep_share", "estate",
                                "acq_filed", "rev_vol_pp", "estate_lead"]},
)

def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    if isinstance(o, (pd.Period, pd.Timestamp)): return str(o)
    raise TypeError(type(o))

def check():
    assert ORG_LO < TRUE_ORGANIC < ORG_HI, \
        f"outside-in band [{ORG_LO:.1%},{ORG_HI:.1%}] misses the truth {TRUE_ORGANIC:.1%}"
    for c in SCORED:
        assert -1.001 <= c["score"] <= 1.001 and 0 <= c["confidence"] <= 1
    print("  checks: band brackets truth, all scores in range")

check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

print(f"{'PROJECT HARRIER -- CLAIM SCORECARD':-^72}")
for c in SCORED:
    print(f"  {c['id']}  {c['verdict']:<24} score {c['score']:+.2f}  conf {c['confidence']:.2f}"
          f"  ({c['families']} families, coherence {c['coherence']:.2f})")
print(f"\n  reported growth {R1/R0-1:.1%}   claimed organic {CLAIMED_ORGANIC:.0%}")
print(f"  outside-in organic band {ORG_LO:.1%} to {ORG_HI:.1%}  (mid {ORG_MID:.1%})   truth {TRUE_ORGANIC:.1%}")
print(f"  EV gap on the growth claim: {VALUATION['gap']/1e6:.0f}m")
print(f"  post-acquisition rating {EVENT_SUMMARY['pre']:.2f} -> {EVENT_SUMMARY['post']:.2f} "
      f"(control drift {EVENT_SUMMARY['control_drift']:+.2f}), review volume {EVENT_SUMMARY['volume_change']:+.1%}")
print("\n  diligence priority:", ", ".join(f"{c['id']} {c['priority']:.2f}"
      for c in sorted(SCORED, key=lambda x: -x["priority"])))

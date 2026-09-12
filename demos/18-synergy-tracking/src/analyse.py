#!/usr/bin/env python3
"""
Project Anvil -- synergy realisation against the deal model, month 14 of 24.

The distinction most trackers miss is between RUN-RATE and IN-YEAR P&L. An
initiative delivered in month 12 carries its full annualised value into the
run-rate and almost none of it into this year's EBITDA. Reporting one as the
other is how a programme looks fine until the audited numbers arrive.

Stage-to-delivery conversion is estimated from 260 initiatives across prior
deals, split by stage AND by cost-versus-revenue, because revenue synergies
convert materially worse at every stage. A PMO's own confidence rating is the
one number in a synergy tracker nobody should accept at face value.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data"
rng = np.random.default_rng(7)

INIT = pd.read_csv(OUT / "initiatives.csv")
MON = pd.read_csv(OUT / "monthly_benefit.csv")
HIST = pd.read_csv(OUT / "historic_initiatives.csv")
DIS = pd.read_csv(OUT / "dissynergies.csv")
MODEL = json.loads((OUT / "deal_model.json").read_text())

TODAY_M, TARGET_M = 14, int(MODEL["target_month"])
STAGES = ["Identified", "Validated", "In execution", "Delivered", "Banked"]
DONE = ("Delivered", "Banked")
CREDIT = {"Identified": 0.0, "Validated": 0.25, "In execution": 0.60, "Delivered": 0.90, "Banked": 1.0}

# ---------------------------------------------------------------------------
# What history says about conversion
# ---------------------------------------------------------------------------
PRIOR = float(HIST.delivered.mean())
ALPHA = 4.0        # smoothing toward the overall rate, for thin cells

CONV = {}
conv_rows = []
for st in STAGES:
    for ty in ("Cost", "Revenue"):
        g = HIST[(HIST.stage == st) & (HIST.type == ty)]
        p = (g.delivered.sum() + ALPHA * PRIOR) / (len(g) + ALPHA)
        CONV[(st, ty)] = float(p)
        conv_rows.append(dict(stage=st, type=ty, n=int(len(g)), raw=float(g.delivered.mean()) if len(g) else None,
                              smoothed=float(p)))

_d = HIST[HIST.delivered == 1].realisation
MU_REAL, SD_REAL = float(_d.mean()), float(_d.std(ddof=1))
# gamma matched on the first two moments, for the simulation
G_SHAPE = (MU_REAL / SD_REAL) ** 2
G_SCALE = SD_REAL ** 2 / MU_REAL

# days-in-stage distribution, used to flag initiatives that have stalled
STAGE_P75 = {st: float(HIST.days_in_stage.quantile(0.75)) for st in STAGES}
STAGE_MED = float(HIST.days_in_stage.median())

# ---------------------------------------------------------------------------
# Current position
# ---------------------------------------------------------------------------
realised_rr = MON[MON.month == TODAY_M].groupby("initiative_id").runrate_recognised.sum()
INIT["realised_runrate"] = INIT.initiative_id.map(realised_rr).fillna(0.0)
INIT["p_convert"] = [1.0 if r.stage in DONE else CONV[(r.stage, r.type)] for _, r in INIT.iterrows()]
INIT["expected"] = [r.realised_runrate if r.stage in DONE else r.current_estimate * r.p_convert * MU_REAL
                    for _, r in INIT.iterrows()]
INIT["credit"] = INIT.stage.map(CREDIT)
INIT["stalled"] = [int(r.days_in_stage > STAGE_P75[r.stage] and r.stage not in DONE) for _, r in INIT.iterrows()]

SECURED = float(INIT[INIT.stage.isin(DONE)].realised_runrate.sum())
GROSS_EST = float(INIT.current_estimate.sum())
EXPECTED = float(INIT.expected.sum())
DIS_TOTAL = float(DIS.annual_impact.sum())
NET_FORECAST = EXPECTED + DIS_TOTAL

und = INIT[~INIT.stage.isin(DONE)]
del_ = INIT[INIT.stage.isin(DONE)]
LOSS_CONV = float((und.current_estimate * (1 - und.p_convert)).sum())
LOSS_REAL = float((und.current_estimate * und.p_convert * (1 - MU_REAL)).sum()
                  + (del_.current_estimate - del_.realised_runrate).sum())
REESTIMATE = GROSS_EST - MODEL["total"]

BRIDGE = [
    dict(label="Deal model", value=float(MODEL["total"]), kind="total"),
    dict(label="Re-estimation", value=float(REESTIMATE), kind="delta",
         note="Current owner estimates against the number in the deal model"),
    dict(label="Conversion risk", value=-LOSS_CONV, kind="delta",
         note="Initiatives that history says will not convert from their current stage"),
    dict(label="Realisation haircut", value=-LOSS_REAL, kind="delta",
         note=f"Delivered initiatives land at {MU_REAL:.0%} of estimate on average"),
    dict(label="Dis-synergy", value=DIS_TOTAL, kind="delta",
         note="Attrition and integration costs the deal model did not carry"),
    dict(label="Risk-adjusted forecast", value=float(NET_FORECAST), kind="total"),
]
RECON = float(MODEL["total"] + sum(b["value"] for b in BRIDGE if b["kind"] == "delta") - NET_FORECAST)

# ---------------------------------------------------------------------------
# Simulation: the distribution of where the programme actually lands
# ---------------------------------------------------------------------------
N_SIM = 20000
est = und.current_estimate.to_numpy()
p = und.p_convert.to_numpy()
draws = (rng.random((N_SIM, len(est))) < p) * rng.gamma(G_SHAPE, G_SCALE, (N_SIM, len(est))) * est
SIM = draws.sum(axis=1) + SECURED + DIS_TOTAL
SIMSTAT = dict(mean=float(SIM.mean()), p10=float(np.percentile(SIM, 10)),
               p50=float(np.percentile(SIM, 50)), p90=float(np.percentile(SIM, 90)),
               p_hit_model=float((SIM >= MODEL["total"]).mean()),
               p_hit_80=float((SIM >= 0.8 * MODEL["total"]).mean()), n=N_SIM)
# The ceiling: every remaining initiative converting, at full estimate. If the deal
# model sits above this line, the gap cannot be closed from the current pipeline at
# all -- which is a different conversation from "we are behind".
CEILING = float(SECURED + und.current_estimate.sum() + DIS_TOTAL)
SHORTFALL = dict(
    ceiling=CEILING, reachable=bool(CEILING >= MODEL["total"]),
    unreachable_by=float(MODEL["total"] - CEILING),
    new_runrate_required=float(max(0.0, (MODEL["total"] - NET_FORECAST) / MU_REAL)),
    required_conversion=float((MODEL["total"] - SECURED - DIS_TOTAL)
                              / max(und.current_estimate.sum() * MU_REAL, 1)),
)

bins = np.linspace(SIM.min(), SIM.max(), 26)
hist_counts, _ = np.histogram(SIM, bins=bins)
SIMHIST = [dict(x=float((bins[i] + bins[i + 1]) / 2), n=int(hist_counts[i])) for i in range(len(hist_counts))]


# ---------------------------------------------------------------------------
# Workstreams: earned value against plan
# ---------------------------------------------------------------------------
LEAD = 6.0    # months a typical initiative takes from mobilisation to delivery

def planned_progress(planned_month):
    """How far an initiative should have got by today, ramped over its delivery window."""
    return float(np.clip((TODAY_M - (planned_month - LEAD)) / LEAD, 0.0, 1.0))

INIT["planned_progress"] = INIT.planned_month.map(planned_progress)

WS = []
for (ty, ws), g in INIT.groupby(["type", "workstream"]):
    pv = float((g.plan_runrate * g.planned_progress).sum())   # planned value to date
    ev = float((g.plan_runrate * g.credit).sum())             # earned value, same value base
    WS.append(dict(workstream=ws, type=ty, n=int(len(g)),
                   plan=float(g.plan_runrate.sum()), estimate=float(g.current_estimate.sum()),
                   secured=float(g[g.stage.isin(DONE)].realised_runrate.sum()),
                   expected=float(g.expected.sum()), pv=pv, ev=ev,
                   spi=float(ev / pv) if pv > 0 else None,
                   cta_budget=float(g.cta_budget.sum()), cta_spent=float(g.cta_spent.sum()),
                   stalled=int(g.stalled.sum()),
                   stages={s: int((g.stage == s).sum()) for s in STAGES}))
WS.sort(key=lambda w: (w["type"], -w["plan"]))

BY_TYPE = []
for ty in ("Cost", "Revenue"):
    g = INIT[INIT.type == ty]
    BY_TYPE.append(dict(type=ty, plan=float(MODEL[ty.lower()]), estimate=float(g.current_estimate.sum()),
                        secured=float(g[g.stage.isin(DONE)].realised_runrate.sum()),
                        expected=float(g.expected.sum()), n=int(len(g)),
                        pct=float(g.expected.sum() / MODEL[ty.lower()])))

# ---------------------------------------------------------------------------
# Run-rate versus what actually reached the P&L
# ---------------------------------------------------------------------------
plan_curve = (INIT.groupby("planned_month").plan_runrate.sum().reindex(range(1, TARGET_M + 1), fill_value=0).cumsum())
rr_curve = MON.groupby("month").runrate_recognised.sum().reindex(range(1, TODAY_M + 1), fill_value=0)
inyear = MON.groupby("month").in_year_benefit.sum().reindex(range(1, TODAY_M + 1), fill_value=0)
CURVE = [dict(month=m, plan=float(plan_curve.get(m, 0)),
              runrate=float(rr_curve.get(m, 0)) if m <= TODAY_M else None,
              in_year_cum=float(inyear.loc[:m].sum()) if m <= TODAY_M else None)
         for m in range(1, TARGET_M + 1)]
LTM = float(inyear.loc[max(1, TODAY_M - 11):TODAY_M].sum())
RR_NOW = float(rr_curve.get(TODAY_M, 0))
PL_GAP = dict(runrate=RR_NOW, ltm_pl=LTM, ratio=float(LTM / RR_NOW) if RR_NOW else 0.0,
              annualisation_gap=float(RR_NOW - LTM))

# ---------------------------------------------------------------------------
# Cost to achieve
# ---------------------------------------------------------------------------
CTA = dict(budget=float(INIT.cta_budget.sum()), spent=float(INIT.cta_spent.sum()),
           ratio=float(INIT.cta_spent.sum() / INIT.cta_budget.sum()),
           per_pound=float(INIT.cta_spent.sum() / SECURED) if SECURED else None,
           by_ws=[dict(workstream=w["workstream"], budget=w["cta_budget"], spent=w["cta_spent"],
                       over=float(w["cta_spent"] - w["cta_budget"])) for w in WS])

# ---------------------------------------------------------------------------
# Escalation list: material, behind, and stalled in stage
# ---------------------------------------------------------------------------
INIT["at_risk"] = INIT.current_estimate * (1 - INIT.p_convert * MU_REAL)
ESCALATE = [dict(initiative_id=r.initiative_id, name=r.name, workstream=r.workstream, type=r.type,
                 owner=r.owner, stage=r.stage, days_in_stage=int(r.days_in_stage),
                 estimate=float(r.current_estimate), p_convert=float(r.p_convert),
                 at_risk=float(r.at_risk), stalled=int(r.stalled),
                 planned_month=int(r.planned_month), overdue=int(r.planned_month < TODAY_M and r.stage not in DONE))
            for _, r in INIT[~INIT.stage.isin(DONE)].nlargest(12, "at_risk").iterrows()]

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
results = dict(
    meta=dict(acquirer="Wexford Industrial Group", target="Pentland Technical Services",
              codename="Project Anvil", sector="Industrial and technical services",
              stage="Post-deal value creation", month=TODAY_M, target_month=TARGET_M,
              initiatives=int(len(INIT)), history=int(len(HIST))),
    model=MODEL, bridge=BRIDGE, recon=RECON,
    position=dict(secured=SECURED, gross_estimate=GROSS_EST, expected=EXPECTED,
                  net_forecast=NET_FORECAST, gap=float(MODEL["total"] - NET_FORECAST),
                  pct_of_model=float(NET_FORECAST / MODEL["total"]),
                  dis_synergy=DIS_TOTAL, mu_real=MU_REAL, sd_real=SD_REAL),
    by_type=BY_TYPE, workstreams=WS, curve=CURVE, pl_gap=PL_GAP,
    simulation=dict(**SIMSTAT, histogram=SIMHIST), shortfall=SHORTFALL,
    conversion=conv_rows, stage_order=STAGES, credit=CREDIT,
    cta=CTA, escalate=ESCALATE,
    dissynergies=[dict(**r) for _, r in DIS.iterrows()],
    stage_counts={s: int((INIT.stage == s).sum()) for s in STAGES},
)

def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    raise TypeError(type(o))

def check():
    assert abs(RECON) < 1.0, f"bridge does not tie: {RECON}"
    got = sum(w["expected"] for w in WS)
    assert abs(got - EXPECTED) < 1.0, "workstream expected values do not sum to the total"
    assert abs(sum(t["expected"] for t in BY_TYPE) - EXPECTED) < 1.0, "type split does not tie"
    assert 0 <= SIMSTAT["p_hit_model"] <= 1
    assert abs(SIMSTAT["p50"] - NET_FORECAST) / max(NET_FORECAST, 1) < 0.15, \
        "simulation median should sit near the analytic expectation"
    print("  checks: bridge ties, splits reconcile, simulation agrees with the point estimate")

check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

m = lambda v: f"{v/1e6:>7.2f}m"
print(f"{'PROJECT ANVIL -- SYNERGY BRIDGE':-^66}")
for b in BRIDGE:
    print(f"  {b['label']:<26}{m(b['value'])}")
print(f"\n  gap to deal model {(MODEL['total']-NET_FORECAST)/1e6:.2f}m "
      f"({NET_FORECAST/MODEL['total']:.0%} of model)")
print(f"  P(hit the model by month {TARGET_M}) {SIMSTAT['p_hit_model']:.1%}   "
      f"P10-P90 {SIMSTAT['p10']/1e6:.1f}m to {SIMSTAT['p90']/1e6:.1f}m")
reach = "reachable" if SHORTFALL["reachable"] else f"unreachable by {SHORTFALL['unreachable_by']/1e6:.2f}m"
print(f"  perfect-execution ceiling {CEILING/1e6:.2f}m -> the model is {reach} from the current pipeline")
print(f"  new initiatives required to close the gap: {SHORTFALL['new_runrate_required']/1e6:.1f}m of run-rate")
print(f"\n  {'workstream':<24}{'plan':>8}{'exp':>8}{'%':>6}{'SPI':>7}{'stalled':>8}")
for w in WS:
    print(f"  {w['workstream']:<24}{w['plan']/1e6:>8.2f}{w['expected']/1e6:>8.2f}"
          f"{w['expected']/w['plan']:>6.0%}{(w['spi'] or 0):>7.2f}{w['stalled']:>8}")
print(f"\n  run-rate recognised {RR_NOW/1e6:.2f}m but only {LTM/1e6:.2f}m reached the last twelve "
      f"months of P&L ({PL_GAP['ratio']:.0%})")
print(f"  cost to achieve {CTA['spent']/1e6:.2f}m against {CTA['budget']/1e6:.2f}m budget ({CTA['ratio']:.0%})")
print(f"  realisation from history: {MU_REAL:.0%} of estimate (sd {SD_REAL:.0%})")

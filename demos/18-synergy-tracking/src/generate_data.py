#!/usr/bin/env python3
"""
Synthetic synergy programme for Project Anvil.

Wexford Industrial Group acquired Pentland Technical Services 14 months ago.
The deal model carried GBP 24.5m of run-rate synergies by month 24. This generates
the initiative register, the monthly realised P&L benefit, and -- critically -- a
library of 260 initiatives from PRIOR deals with known outcomes, so stage-to-
delivery conversion is estimated from history rather than asserted by a PMO.

The failure mode being modelled is the common one: cost synergies land early and
get celebrated, revenue synergies quietly stall, and nobody says so until month 18
when there is no time left to fix it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20260618
rng = np.random.default_rng(SEED)
hrng = np.random.default_rng(SEED + 1)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

TODAY_M = 14          # months since completion
TARGET_M = 24         # the deal model's run-rate date
STAGES = ["Identified", "Validated", "In execution", "Delivered", "Banked"]

WORKSTREAMS = [
    # name, type, plan run-rate GBP, n initiatives, health (1.0 = on plan)
    ("Procurement",          "Cost",    6_200_000, 9, 1.02),
    ("Organisation design",  "Cost",    4_800_000, 6, 0.94),
    ("Property & sites",     "Cost",    2_600_000, 4, 0.88),
    ("IT & systems",         "Cost",    1_900_000, 6, 0.71),
    ("Insurance & risk",     "Cost",    1_000_000, 3, 1.05),
    ("Cross-sell",           "Revenue", 4_400_000, 8, 0.27),
    ("Pricing harmonisation","Revenue", 2_200_000, 5, 0.41),
    ("Geographic expansion", "Revenue", 1_400_000, 5, 0.18),
]

NAMES = {
    "Procurement": ["Consolidate MRO supply base", "Harmonise fleet leasing", "Single-source PPE and consumables",
                    "Renegotiate steel and fixings", "Combine utilities contracts", "Rationalise subcontractor panel",
                    "Consolidate plant hire", "Harmonise telematics contract", "Combine waste and recycling"],
    "Organisation design": ["Rationalise duplicate finance roles", "Merge HR shared services",
                            "Consolidate regional management layer", "Combine health and safety function",
                            "Integrate procurement teams", "Merge bid and estimating teams"],
    "Property & sites": ["Exit Tipton depot", "Consolidate Midlands storage", "Sublet Warrington office floor",
                         "Close duplicate Glasgow branch"],
    "IT & systems": ["Migrate to single ERP instance", "Consolidate field service platform",
                     "Rationalise licence estate", "Merge telephony and network", "Single CRM instance",
                     "Decommission legacy scheduling"],
    "Insurance & risk": ["Combine employer liability cover", "Harmonise fleet insurance",
                         "Single broker appointment"],
    "Cross-sell": ["Mechanical services into Pentland electrical base", "Compliance testing into Wexford accounts",
                   "Bundled planned maintenance offer", "Fire safety into industrial estate portfolio",
                   "HVAC retrofit into public sector base", "Energy monitoring into national accounts",
                   "Water hygiene into Pentland healthcare", "Reactive cover into Wexford framework clients"],
    "Pricing harmonisation": ["Align call-out rate card", "Standardise contract uplift mechanism",
                              "Harmonise parts margin", "Remove legacy discount grandfathering",
                              "Align out-of-hours premium"],
    "Geographic expansion": ["Wexford services into Pentland's South West footprint",
                             "Pentland coverage into Wexford's North East", "Joint Scotland mobilisation",
                             "Shared depot network into East Anglia", "Combined Wales coverage"],
}

# ---------------------------------------------------------------------------
# History: 260 initiatives from prior deals, reviewed at the same point in the
# programme, with what actually happened. This is what the model is fitted on.
# ---------------------------------------------------------------------------
N_HIST = 260
TRUE_CONV = {"Identified": 0.36, "Validated": 0.61, "In execution": 0.86, "Delivered": 0.97, "Banked": 1.0}
hist = []
for _ in range(N_HIST):
    st = str(hrng.choice(STAGES, p=[0.22, 0.26, 0.24, 0.18, 0.10]))
    typ = str(hrng.choice(["Cost", "Revenue"], p=[0.63, 0.37]))
    # revenue initiatives convert worse at every stage -- that is the point
    penalty = 0.74 if (typ == "Revenue" and st in ("Identified", "Validated", "In execution")) else 1.0
    p = TRUE_CONV[st] * penalty
    delivered = int(hrng.random() < p)
    # realisation: what the initiative was eventually worth against its estimate
    real = float(np.clip(hrng.gamma(16.0, 0.0556), 0.1, 1.9)) if delivered else 0.0
    hist.append(dict(stage=st, type=typ, delivered=delivered, realisation=real,
                     days_in_stage=float(np.clip(hrng.gamma(2.4, 26), 3, 420))))
HIST = pd.DataFrame(hist)

# ---------------------------------------------------------------------------
# The live register
# ---------------------------------------------------------------------------
# stage mix depends on how the workstream is actually going
def stage_mix(health):
    if health >= 1.00:   return [0.00, 0.04, 0.14, 0.28, 0.54]
    if health >= 0.90:   return [0.02, 0.08, 0.22, 0.30, 0.38]
    if health >= 0.85:   return [0.04, 0.14, 0.26, 0.30, 0.26]
    if health >= 0.65:   return [0.14, 0.28, 0.34, 0.18, 0.06]
    if health >= 0.35:   return [0.30, 0.38, 0.24, 0.06, 0.02]
    return [0.46, 0.36, 0.14, 0.03, 0.01]

rows, iid = [], 0
for ws, typ, plan, n, health in WORKSTREAMS:
    w = rng.dirichlet(np.full(n, 3.2))
    names = NAMES[ws][:]
    for i in range(n):
        iid += 1
        stage = str(rng.choice(STAGES, p=stage_mix(health)))
        plan_rr = float(plan * w[i])
        # the current estimate drifts from the deal-model number as work is done
        est = float(plan_rr * np.clip(rng.normal(0.93 if typ == "Revenue" else 1.0, 0.17), 0.3, 1.7))
        PLAN_WINDOW = {"Banked": (2, 11), "Delivered": (4, 14), "In execution": (8, 19),
                       "Validated": (11, 23), "Identified": (15, 24)}[stage]
        planned_month = int(np.clip(rng.integers(*PLAN_WINDOW), 1, TARGET_M))
        if stage in ("Delivered", "Banked"):
            delivered_month = int(np.clip(planned_month + rng.integers(-1, 4), 1, TODAY_M))
        else:
            delivered_month = None
        # how long it has been sitting where it is
        base_days = {"Identified": 70, "Validated": 62, "In execution": 88, "Delivered": 40, "Banked": 25}[stage]
        slip = 2.4 if (typ == "Revenue" and stage in ("Identified", "Validated")) else 1.0
        rows.append(dict(
            initiative_id=f"S{iid:03d}", name=names[i % len(names)], workstream=ws, type=typ,
            owner=str(rng.choice(["Integration MD", "CFO", "COO", "CCO", "Group Procurement", "CIO"])),
            plan_runrate=round(plan_rr, -3), current_estimate=round(est, -3), stage=stage,
            days_in_stage=int(np.clip(rng.gamma(2.6, base_days / 2.6) * slip, 4, 430)),
            planned_month=planned_month, delivered_month=delivered_month,
            cta_budget=round(plan_rr * float(np.clip(rng.normal(0.27, 0.08), 0.05, 0.6)), -3),
        ))
INIT = pd.DataFrame(rows)
# cost to achieve overruns where the work is hard
INIT["cta_spent"] = [round(r.cta_budget * float(np.clip(rng.normal(
    1.38 if r.workstream in ("IT & systems", "Property & sites") else 1.12, 0.26), 0.1, 2.6)), -3)
    if r.stage != "Identified" else round(r.cta_budget * float(np.clip(rng.normal(0.22, 0.14), 0, 0.8)), -3)
    for _, r in INIT.iterrows()]

# ---------------------------------------------------------------------------
# Monthly realised P&L benefit. Run-rate is annualised; what hits the P&L in a
# month is one twelfth of run-rate, ramped over the first quarter after delivery.
# ---------------------------------------------------------------------------
RAMP = [0.5, 0.78, 1.0]
mrows = []
for _, r in INIT.iterrows():
    if pd.isna(r.delivered_month):
        continue
    realised_rr = float(r.current_estimate * np.clip(rng.normal(0.88, 0.12), 0.3, 1.4))
    for m in range(int(r.delivered_month), TODAY_M + 1):
        k = m - int(r.delivered_month)
        f = RAMP[k] if k < len(RAMP) else 1.0
        mrows.append((m, r.initiative_id, r.workstream, r.type,
                      round(realised_rr / 12 * f, 0), round(realised_rr * f, 0)))
MONTHLY = pd.DataFrame(mrows, columns=["month", "initiative_id", "workstream", "type",
                                       "in_year_benefit", "runrate_recognised"])

# ---------------------------------------------------------------------------
# Dis-synergy: the deal model did not carry these
# ---------------------------------------------------------------------------
DIS = pd.DataFrame([
    dict(item="Customer overlap attrition", type="Revenue", annual_impact=-1_240_000,
         note="Twelve accounts held with both businesses consolidated volume with a third party"),
    dict(item="Key account manager departures", type="Revenue", annual_impact=-660_000,
         note="Four senior sellers left in the first nine months, two to a direct competitor"),
    dict(item="Retention and duplicate cover", type="Cost", annual_impact=-420_000,
         note="Retention packages and contractor cover during the finance consolidation"),
    dict(item="Contract novation losses", type="Revenue", annual_impact=-310_000,
         note="Three framework contracts not novated on change of control"),
])

DEAL_MODEL = dict(total=24_500_000, cost=16_500_000, revenue=8_000_000, target_month=TARGET_M,
                  cta_budget=int(INIT.cta_budget.sum()))

INIT.to_csv(OUT / "initiatives.csv", index=False)
MONTHLY.to_csv(OUT / "monthly_benefit.csv", index=False)
HIST.to_csv(OUT / "historic_initiatives.csv", index=False)
DIS.to_csv(OUT / "dissynergies.csv", index=False)
pd.Series(DEAL_MODEL).to_json(OUT / "deal_model.json")

print(f"initiatives {len(INIT)}  monthly rows {len(MONTHLY)}  history {len(HIST)}")
print(INIT.groupby(["type", "workstream"]).agg(n=("stage", "size"),
      plan=("plan_runrate", lambda s: round(s.sum()/1e6, 2)),
      est=("current_estimate", lambda s: round(s.sum()/1e6, 2))).to_string())
print(f"\nplan total {INIT.plan_runrate.sum()/1e6:.2f}m  vs deal model {DEAL_MODEL['total']/1e6:.2f}m")
print(INIT.stage.value_counts().to_string())

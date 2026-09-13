#!/usr/bin/env python3
"""
Project Ferryman -- trade area analysis for Tarnbrook Bakehouse.

Four questions, in the order a deal team asks them:

  1. how strong is each catchment REALLY, once the panel bias is undone
  2. does a gravity model calibrated on that data explain how sites actually trade
  3. how much of the 40-site pipeline is new trade and how much is transferred
  4. which sites survive once the pipeline is allowed to cannibalise itself

The analysis sees the panel, Experian demographics, its own estate and competitor
locations. It does not see the true decay parameter, the true visit volumes or the
panel penetration by segment -- those exist only so the build can mark its own work.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data"

OA = pd.read_csv(OUT / "output_areas.csv")
MOS = pd.read_csv(OUT / "mosaic_groups.csv")
SITES = pd.read_csv(OUT / "sites.csv")
PIPE = pd.read_csv(OUT / "pipeline.csv")
COMP = pd.read_csv(OUT / "competitors.csv")
PANEL = pd.read_csv(OUT / "panel_visits.csv.gz")
TOWNS = pd.read_csv(OUT / "towns.csv")
TRUTH = json.loads((OUT / "truth.json").read_text())

ROAD_FACTOR = 1.25          # straight line to road distance; a stand-in for routing
HURDLE = 400_000            # net new revenue a pipeline site must clear to justify capex

OA = OA.merge(MOS[["code", "spend"]], left_on="mosaic", right_on="code").drop(columns="code")
oa_ix = {k: i for i, k in enumerate(OA.oa_id)}
site_ix = {k: i for i, k in enumerate(SITES.site_id)}

# ---------------------------------------------------------------------------
# 1. Undo the panel bias
# ---------------------------------------------------------------------------
# Raw penetration is unusable for a small output area: twelve devices in a
# population of 300 gives an expansion factor that swings on one commuter. Shrink
# each area's penetration toward its Mosaic group mean with a pseudo-population.
M_PSEUDO = 400.0

grp = OA.groupby("mosaic").apply(
    lambda g: g.panel_devices.sum() / g.population.sum(), include_groups=False).rename("pen_group")
OA = OA.join(grp, on="mosaic")
OA["pen_raw"] = OA.panel_devices / OA.population
OA["pen_hat"] = (OA.panel_devices + M_PSEUDO * OA.pen_group) / (OA.population + M_PSEUDO)
OA["expansion"] = 1.0 / OA.pen_hat

PANEL = PANEL.merge(OA[["oa_id", "expansion", "spend", "population", "mosaic"]], on="oa_id")
PANEL["visits"] = PANEL.panel_visits * PANEL.expansion

V_obs = np.zeros((len(OA), len(SITES)))
V_panel = np.zeros_like(V_obs)
for oid, sid, pv, v in zip(PANEL.oa_id, PANEL.site_id, PANEL.panel_visits, PANEL.visits):
    V_obs[oa_ix[oid], site_ix[sid]] = v
    V_panel[oa_ix[oid], site_ix[sid]] = pv

PEN_BY_GROUP = [dict(mosaic=r.code, name=r["name"],
                     penetration=float(OA.loc[OA.mosaic == r.code, "pen_hat"].mean()),
                     areas=int((OA.mosaic == r.code).sum()),
                     population=int(OA.loc[OA.mosaic == r.code, "population"].sum()))
                for _, r in MOS.iterrows()]
PEN_BY_GROUP.sort(key=lambda d: -d["penetration"])

# ---------------------------------------------------------------------------
# 2. Fit the distance decay
# ---------------------------------------------------------------------------
def dmat(oa, sites):
    d = np.hypot(oa.x.to_numpy()[:, None] - sites.x.to_numpy()[None, :],
                 oa.y.to_numpy()[:, None] - sites.y.to_numpy()[None, :])
    return np.maximum(d, 0.35) * ROAD_FACTOR

D_own = dmat(OA, SITES)
A_own = SITES.attract.to_numpy()

def conditional_ll(beta):
    """
    Multinomial log-likelihood of the observed choice shares among OWN sites.

    Panel penetration is a single scalar per output area, so it cancels out of the
    within-area shares entirely -- the decay parameter is identified from the RAW
    panel counts, and only the volumes need expanding.
    """
    util = A_own[None, :] * D_own ** (-beta)
    logp = np.log(util / util.sum(axis=1, keepdims=True))
    return float((V_panel * logp).sum())

# Coarse sweep for the profile chart, then refine. With this many observed visits
# the likelihood is extremely peaked, so a 0.01 grid cannot resolve the interval.
grid = np.arange(0.60, 4.001, 0.01)
lls = np.array([conditional_ll(b) for b in grid])
peak = float(grid[int(np.argmax(lls))])

fine = np.arange(peak - 0.05, peak + 0.05, 0.0005)
flls = np.array([conditional_ll(b) for b in fine])
BETA = float(fine[int(np.argmax(flls))])
inside = fine[flls >= flls.max() - 2.0]          # 2 log-likelihood units
BETA_LO, BETA_HI = float(inside.min()), float(inside.max())

PROFILE = [dict(beta=float(b), ll=float(l)) for b, l in zip(grid[::10], lls[::10])]

# observed decay curve, for the chart that shows the fit is empirical
bins = np.arange(0, 26, 1.5)
dec = []
for lo, hi in zip(bins[:-1], bins[1:]):
    m = (D_own >= lo) & (D_own < hi)
    pop = np.repeat(OA.population.to_numpy()[:, None], len(SITES), axis=1)[m].sum()
    if pop > 0 and m.sum() > 40:
        dec.append(dict(km=float((lo + hi) / 2), rate=float(V_obs[m].sum() / pop),
                        pairs=int(m.sum())))
DECAY = dec

# ---------------------------------------------------------------------------
# 3. Rebuild total demand per area, then the calibrated model
# ---------------------------------------------------------------------------
CHOICE = pd.concat([SITES.assign(own=1), COMP.assign(own=0)], ignore_index=True)

def huff(sites, beta=None):
    b = BETA if beta is None else beta
    util = sites.attract.to_numpy()[None, :] * dmat(OA, sites) ** (-b)
    return util / util.sum(axis=1, keepdims=True)

P_all = huff(CHOICE)
own_mask = CHOICE.own.to_numpy() == 1
own_share = P_all[:, own_mask].sum(axis=1)

# Total demand implied by what we observed: expanded own visits / modelled own capture
DEMAND = V_obs.sum(axis=1) / np.clip(own_share, 1e-6, None)
OA["demand"] = DEMAND
OA["visits_per_adult"] = DEMAND / OA.population

def predict(sites_own):
    """Visits by output area to each own site, given a candidate estate."""
    ch = pd.concat([sites_own.assign(own=1), COMP.assign(own=0)], ignore_index=True)
    P = huff(ch)
    return DEMAND[:, None] * P[:, (ch.own.to_numpy() == 1)]

V_fit = predict(SITES)
SITES["pred_visits"] = V_fit.sum(axis=0)
SITES["pred_revenue"] = (V_fit * OA.spend.to_numpy()[:, None]).sum(axis=0)

# does the model explain how sites actually trade?
x, y = SITES.pred_revenue.to_numpy(), SITES.revenue.to_numpy()
slope, intercept = np.polyfit(x, y, 1)
R2 = float(1 - ((y - (slope * x + intercept)) ** 2).sum() / ((y - y.mean()) ** 2).sum())
MAPE = float(np.mean(np.abs((slope * x + intercept) - y) / y))

# ---------------------------------------------------------------------------
# 4. Catchment metrics per site
# ---------------------------------------------------------------------------
share_of_site = V_fit / np.clip(V_fit.sum(axis=0, keepdims=True), 1e-9, None)
est_prop = (OA.groupby("mosaic").demand.sum() / OA.groupby("mosaic").population.sum())
est_index = (est_prop / (DEMAND.sum() / OA.population.sum())).rename("prop_index")
OA = OA.join(est_index, on="mosaic")

rows = []
for j, s in SITES.iterrows():
    w = share_of_site[:, j]
    order = np.argsort(D_own[:, j])
    cum = np.cumsum(w[order])
    r70 = float(D_own[order, j][np.searchsorted(cum, 0.70)])
    rows.append(dict(
        site_id=s.site_id, name=s["name"], town=s.town, fmt=s.fmt, sqft=int(s.sqft),
        revenue=float(s.revenue), pred_revenue=float(s.pred_revenue),
        catchment_pop=float((w * OA.population.to_numpy()).sum()),
        radius70=r70,
        demo_index=float((w * OA.prop_index.to_numpy()).sum()),
        spend_index=float((w * OA.spend.to_numpy()).sum() / OA.spend.mean()),
        own_within_3km=int(((dmat(SITES.iloc[[j]], SITES)[0] < 3.0).sum()) - 1),
        comp_within_3km=int((dmat(SITES.iloc[[j]], COMP)[0] < 3.0).sum()),
    ))
SITE_METRICS = pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. Cannibalisation, one site at a time and as a portfolio
# ---------------------------------------------------------------------------
spend = OA.spend.to_numpy()
base_rev_by_site = (V_fit * spend[:, None]).sum(axis=0)
BASE_TOTAL = float(base_rev_by_site.sum())

def appraise(new_sites, incumbent=SITES):
    """Revenue at the new sites, and how much of it was taken off the incumbents."""
    before = predict(incumbent)
    after_est = pd.concat([incumbent, new_sites], ignore_index=True)
    after = predict(after_est)
    n_inc = len(incumbent)
    new_rev = (after[:, n_inc:] * spend[:, None]).sum(axis=0)
    transferred_by_inc = ((before - after[:, :n_inc]) * spend[:, None]).sum(axis=0)
    return new_rev, float(transferred_by_inc.sum()), transferred_by_inc

# (a) the seller's appraisal: each site judged on its own against today's estate
solo = []
for i in range(len(PIPE)):
    one = PIPE.iloc[[i]]
    new_rev, transferred, _ = appraise(one)
    gross = float(new_rev[0])
    solo.append(dict(
        site_id=PIPE.site_id.iat[i], name=PIPE.name.iat[i], town=PIPE.town.iat[i],
        fmt=PIPE.fmt.iat[i], sqft=int(PIPE.sqft.iat[i]),
        gross=gross, transferred=transferred, net=gross - transferred,
        cannibalisation=transferred / gross if gross else 0.0))
SOLO = pd.DataFrame(solo)

# (b) the truth: open all forty and let the pipeline compete with itself too
all_new_rev, all_transferred, transfer_by_inc = appraise(PIPE)
PORTFOLIO = dict(
    gross=float(all_new_rev.sum()),
    transferred_from_estate=float(all_transferred),
    net=float(all_new_rev.sum() - all_transferred),
    solo_net_sum=float(SOLO.net.sum()),
    self_cannibalisation=float(SOLO.net.sum() - (all_new_rev.sum() - all_transferred)),
    cannibalisation_rate=float(all_transferred / all_new_rev.sum()),
)

SOLO["portfolio_gross"] = all_new_rev
SOLO = SOLO.sort_values("net", ascending=False).reset_index(drop=True)
SOLO["rank"] = SOLO.index + 1
SOLO["accretive"] = (SOLO.net >= HURDLE).astype(int)

# worst-hit incumbents
SITES["transferred"] = transfer_by_inc
SITES["transferred_pct"] = transfer_by_inc / base_rev_by_site
hit = SITES.assign(base=base_rev_by_site)
hit["pct"] = hit.transferred / hit.base
WORST = [dict(name=r["name"], town=r.town, base=float(r.base),
              transferred=float(r.transferred), pct=float(r.pct))
         for _, r in hit.nlargest(8, "pct").iterrows()]

# ---------------------------------------------------------------------------
# 6. What the panel bias would have cost you
# ---------------------------------------------------------------------------
# The naive expansion everyone reaches for first: scale the whole panel by one
# national penetration figure. It is exactly right on average and wrong everywhere.
global_pen = OA.panel_devices.sum() / OA.population.sum()
V_naive = V_panel / global_pen

naive_site = V_naive.sum(axis=0)
proper_site = V_obs.sum(axis=0)

share_naive = V_naive / np.clip(V_naive.sum(axis=0, keepdims=True), 1e-9, None)
share_proper = V_obs / np.clip(V_obs.sum(axis=0, keepdims=True), 1e-9, None)
pop = OA.population.to_numpy()
catch_naive = (share_naive * pop[:, None]).sum(axis=0)
catch_proper = (share_proper * pop[:, None]).sum(axis=0)

err = catch_naive / catch_proper - 1
BIAS = dict(
    market_naive=float(naive_site.sum()), market_proper=float(proper_site.sum()),
    market_error=float(naive_site.sum() / proper_site.sum() - 1),
    catchment_p10=float(np.percentile(err, 10)), catchment_p90=float(np.percentile(err, 90)),
    understated=int((err < -0.15).sum()), overstated=int((err > 0.15).sum()),
    worst=[dict(name=SITES.name.iat[k], town=SITES.town.iat[k],
                naive=float(catch_naive[k]), proper=float(catch_proper[k]),
                error=float(err[k])) for k in np.argsort(err)[:6]],
    penetration_spread=float(max(p["penetration"] for p in PEN_BY_GROUP)
                             / min(p["penetration"] for p in PEN_BY_GROUP)),
)

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def pts(df, extra=None):
    cols = ["x", "y"] + (extra or [])
    return [{c: (float(r[c]) if c in ("x", "y") else r[c]) for c in cols} for _, r in df.iterrows()]

results = dict(
    meta=dict(company="Tarnbrook Bakehouse", codename="Project Ferryman",
              sector="Food-to-go and bakery-cafe", stage="Commercial due diligence",
              sites=len(SITES), pipeline=len(PIPE), competitors=len(COMP),
              areas=int(len(OA)), population=int(OA.population.sum()),
              panel_devices=int(OA.panel_devices.sum()),
              panel_records=int(len(PANEL)), hurdle=HURDLE),
    model=dict(beta=BETA, beta_lo=BETA_LO, beta_hi=BETA_HI, r2=R2, mape=MAPE,
               slope=float(slope), intercept=float(intercept),
               own_share=float(own_share.mean()), profile=PROFILE, decay=DECAY),
    panel=dict(by_group=PEN_BY_GROUP, bias=BIAS, pseudo=M_PSEUDO,
               mean_expansion=float(OA.expansion.mean())),
    estate=dict(revenue=float(SITES.revenue.sum()), mean=float(SITES.revenue.mean()),
                sites=pts(SITES, ["site_id", "name", "town", "fmt", "revenue",
                                  "transferred", "transferred_pct"])),
    pipeline_pts=pts(PIPE, ["site_id", "name", "town", "fmt"]),
    competitor_pts=pts(COMP.sample(214, random_state=1), ["brand"]),
    areas=[dict(x=float(r.x), y=float(r.y), pop=int(r.population), m=r.mosaic)
           for _, r in OA.iterrows()],
    towns=[dict(x=float(r.x), y=float(r.y), name=r.town, pop=int(r.population))
           for _, r in TOWNS.iterrows()],
    site_metrics=[{k: (float(v) if isinstance(v, (int, float, np.number)) and k not in
                       ("site_id", "name", "town", "fmt") else v)
                   for k, v in r.items()} for _, r in SITE_METRICS.iterrows()],
    solo=[{k: (float(v) if isinstance(v, (int, float, np.number)) and k not in
               ("site_id", "name", "town", "fmt") else v) for k, v in r.items()}
          for _, r in SOLO.iterrows()],
    portfolio=PORTFOLIO, worst_hit=WORST,
    claim=dict(sites=len(PIPE), estate_mean=float(SITES.revenue.mean()),
               seller=float(len(PIPE) * SITES.revenue.mean()),
               model_gross=PORTFOLIO["gross"], model_net=PORTFOLIO["net"],
               gap=float(len(PIPE) * SITES.revenue.mean() - PORTFOLIO["net"])),
    mosaic=[dict(code=r.code, name=r["name"], spend=float(r.spend),
                 prop_index=float(est_index.get(r.code, np.nan)),
                 penetration=float(next(p["penetration"] for p in PEN_BY_GROUP if p["mosaic"] == r.code)))
            for _, r in MOS.iterrows()],
)

def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    raise TypeError(type(o))

def check():
    t = TRUTH["true_beta"]
    assert BETA_LO - 1e-9 <= t <= BETA_HI + 1e-9, (
        f"fitted beta {BETA:.3f} [{BETA_LO:.3f},{BETA_HI:.3f}] misses truth {t}")
    assert R2 > 0.5, f"gravity model explains too little of actual trade (R2 {R2:.2f})"
    assert abs(PORTFOLIO["net"] - (PORTFOLIO["gross"] - PORTFOLIO["transferred_from_estate"])) < 1.0
    assert PORTFOLIO["self_cannibalisation"] > 0, "portfolio net should be below the sum of solo appraisals"
    assert np.allclose(huff(CHOICE).sum(axis=1), 1.0), "Huff probabilities must sum to 1 per area"
    print(f"  checks: beta interval contains truth ({t}), R2 {R2:.2f}, probabilities sum to 1")

check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

m = lambda v: f"{v/1e6:.1f}m"
print(f"{'PROJECT FERRYMAN -- TRADE AREA':-^70}")
print(f"  fitted decay beta {BETA:.3f}  [{BETA_LO:.3f}, {BETA_HI:.3f}]   true {TRUTH['true_beta']}")
print(f"  gravity model explains {R2:.0%} of variance in site revenue (MAPE {MAPE:.1%})")
print(f"  panel penetration spread {BIAS['penetration_spread']:.1f}x across Mosaic groups")
print(f"  single-factor expansion misses the market by {BIAS['market_error']:+.1%}; "
      f"per-site catchment error P10 {BIAS['catchment_p10']:+.0%} to P90 {BIAS['catchment_p90']:+.0%}; "
      f"{BIAS['understated']} sites understated by more than 15%")
print(f"\n  seller's headline: {len(PIPE)} x estate average {SITES.revenue.mean()/1e3:.0f}k "
      f"= {m(len(PIPE) * SITES.revenue.mean())}")
print(f"  seller's pipeline appraised site by site: {m(SOLO.gross.sum())} gross, "
      f"{m(SOLO.net.sum())} net")
print(f"  appraised as a portfolio:                 {m(PORTFOLIO['gross'])} gross, "
      f"{m(PORTFOLIO['net'])} net")
print(f"  cannibalisation of the existing estate    {m(PORTFOLIO['transferred_from_estate'])} "
      f"({PORTFOLIO['cannibalisation_rate']:.0%})")
print(f"  pipeline cannibalising itself             {m(PORTFOLIO['self_cannibalisation'])}")
print(f"  sites clearing the {HURDLE/1000:.0f}k hurdle: {int(SOLO.accretive.sum())} of {len(SOLO)}")
print(f"\n  worst-hit incumbents:")
for w in WORST[:4]:
    print(f"    {w['name'][:34]:<36}{w['pct']:6.1%} of {w['base']/1e3:.0f}k")

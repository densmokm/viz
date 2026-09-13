#!/usr/bin/env python3
"""
Synthetic geography, footfall panel and Experian-style demographics for Project Ferryman.

Target: Tarnbrook Bakehouse, a UK food-to-go and bakery-cafe chain of 84 sites,
sponsor-backed, in market with a 40-site roll-out plan.

The generator builds a WORLD -- output areas with population and Mosaic mix, sites
with floor area and format -- then runs a Huff gravity model with a KNOWN distance
decay to produce true visits and true site revenue. It then samples a mobile-device
panel from those visits, with deliberate demographic bias in panel penetration.

The analysis is only allowed to see the panel, the OA demographics and the site
estate. It has to recover the decay parameter and the underlying visit volumes on
its own; the true values exist purely so the build can check that it did.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20260420
rng = np.random.default_rng(SEED)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Ground truth the analysis never reads
# ---------------------------------------------------------------------------
TRUE_BETA = 1.85          # distance decay exponent in the Huff model
ROAD_FACTOR = 1.25        # straight line -> road distance, a stand-in for routing
PANEL_BASE = 0.034        # share of adults carrying a panel device

# ---------------------------------------------------------------------------
# Experian Mosaic UK groups. Propensity and spend are format-specific: a
# food-to-go bakery is used very differently by a city commuter and a retiree.
# ---------------------------------------------------------------------------
MOSAIC = [
    # code, name,                 propensity, spend, panel bias, urbanity
    ("A", "City Prosperity",          1.55, 6.40, 1.95, 1.00),
    ("B", "Prestige Positions",       0.72, 7.10, 0.85, 0.35),
    ("C", "Country Living",           0.44, 6.80, 0.55, 0.05),
    ("D", "Rural Reality",            0.38, 5.20, 0.48, 0.02),
    ("E", "Senior Security",          0.52, 5.60, 0.42, 0.30),
    ("F", "Suburban Stability",       0.86, 5.90, 0.78, 0.45),
    ("G", "Domestic Success",         1.04, 6.60, 0.95, 0.50),
    ("H", "Aspiring Homemakers",      1.22, 5.40, 1.35, 0.62),
    ("I", "Family Basics",            0.94, 4.60, 1.05, 0.60),
    ("J", "Transient Renters",        1.31, 4.90, 1.72, 0.85),
    ("K", "Municipal Challenge",      0.78, 4.20, 1.18, 0.80),
    ("L", "Vintage Value",            0.46, 4.40, 0.38, 0.40),
    ("M", "Modest Traditions",        0.64, 4.80, 0.62, 0.35),
    ("N", "Urban Cohesion",           1.08, 5.00, 1.42, 0.90),
    ("O", "Rental Hubs",              1.48, 5.30, 2.10, 0.95),
]
MOS = pd.DataFrame(MOSAIC, columns=["code", "name", "propensity", "spend", "panel_bias", "urbanity"])

# ---------------------------------------------------------------------------
# A synthetic region: 220km x 180km, fourteen towns of varying size
# ---------------------------------------------------------------------------
TOWNS = [
    ("Tarnbrook", 96, 132, 292_000), ("Halewood", 44, 108, 178_000),
    ("Ashcombe", 152, 148, 214_000), ("Wrenfield", 118, 66, 141_000),
    ("Oakmere", 28, 54, 96_000),     ("Stanbury", 186, 96, 122_000),
    ("Ledbury Cross", 74, 168, 68_000), ("Pentworth", 138, 24, 54_000),
    ("Marlcombe", 200, 158, 47_000), ("Cotterill", 12, 150, 39_000),
    ("Ravensmoor", 164, 52, 63_000), ("Elmsford", 88, 94, 108_000),
    ("Netherby", 56, 20, 33_000),    ("Quarrydale", 122, 112, 87_000),
]
TOWN = pd.DataFrame(TOWNS, columns=["town", "x", "y", "population"])

rows, oid = [], 0
for _, t in TOWN.iterrows():
    n_oa = int(np.clip(t.population / 3200, 12, 95))
    # population density falls off exponentially from the centre
    r = rng.gamma(1.8, 2.6, n_oa)
    theta = rng.uniform(0, 2 * np.pi, n_oa)
    for k in range(n_oa):
        oid += 1
        urb = float(np.exp(-r[k] / 5.5))                  # 1 at the centre, ~0 rural fringe
        # Mosaic assignment weighted by how urban the area is
        w = np.exp(-4.2 * np.abs(MOS.urbanity.to_numpy() - urb)) * rng.uniform(0.55, 1.45, len(MOS))
        g = MOS.iloc[int(rng.choice(len(MOS), p=w / w.sum()))]
        rows.append(dict(
            oa_id=f"OA{oid:05d}", town=t.town,
            x=float(t.x + r[k] * np.cos(theta[k])), y=float(t.y + r[k] * np.sin(theta[k])),
            population=int(max(180, rng.normal(t.population / n_oa, t.population / n_oa * 0.3))),
            mosaic=g.code, mosaic_name=g["name"], urbanity=round(urb, 3)))

# scattered rural output areas between the towns
for _ in range(120):
    oid += 1
    x, y = rng.uniform(4, 216), rng.uniform(4, 176)
    g = MOS[MOS.code.isin(["C", "D", "L", "M"])].sample(1, random_state=int(rng.integers(1e9))).iloc[0]
    near = TOWN.assign(d=np.hypot(TOWN.x - x, TOWN.y - y)).nsmallest(1, "d").iloc[0]
    rows.append(dict(oa_id=f"OA{oid:05d}", town=near.town, x=float(x), y=float(y),
                     population=int(rng.uniform(220, 1400)), mosaic=g.code,
                     mosaic_name=g["name"], urbanity=0.02))

OA = pd.DataFrame(rows)
OA = OA.merge(MOS[["code", "propensity", "spend", "panel_bias"]],
              left_on="mosaic", right_on="code", how="left").drop(columns="code")

# ---------------------------------------------------------------------------
# The estate, and the pipeline the seller is pitching
# ---------------------------------------------------------------------------
FORMATS = {"High Street": 1.00, "Retail Park": 1.28, "Transport Hub": 0.86}

def place_sites(n, label, jitter, weight_col="population", avoid=None):
    out = []
    w = TOWN[weight_col].to_numpy() ** 0.85
    if avoid is not None:
        served = TOWN.town.map(avoid.town.value_counts()).fillna(0).to_numpy()
        w = w / (1 + served) ** 0.45
    for i in range(n):
        t = TOWN.iloc[int(rng.choice(len(TOWN), p=w / w.sum()))]
        fmt = str(rng.choice(list(FORMATS), p=[0.62, 0.26, 0.12]))
        out.append(dict(
            site_id=f"{label}{i+1:03d}",
            name=f"{t.town} {rng.choice(['High Street','Market Square','Retail Park','Station','Northgate','The Parade','Riverside','Westway'])}",
            town=t.town, x=float(t.x + rng.normal(0, jitter)), y=float(t.y + rng.normal(0, jitter)),
            fmt=fmt, sqft=int(np.clip(rng.normal(1750, 520), 700, 4200)),
            opened_month=int(rng.integers(1, 96))))
    df = pd.DataFrame(out)
    dup = df.groupby("name").cumcount()
    df["name"] = np.where(dup > 0, df.name + " " + (dup + 1).astype(str), df.name)
    return df

SITES = place_sites(84, "S", 3.1)
PIPE = place_sites(40, "P", 5.6, avoid=SITES)

BRANDS = ["Pennington's", "Fold & Crumb", "Marchetti", "The Daily Loaf", "Cobb Street Co"]
COMP = place_sites(214, "C", 5.2)
COMP["brand"] = [str(rng.choice(BRANDS)) for _ in range(len(COMP))]
COMP["name"] = COMP.brand + " " + COMP.town

for df in (SITES, PIPE, COMP):
    df["attract"] = (df.sqft / 1000) ** 0.55 * df.fmt.map(FORMATS)
COMP["attract"] *= 0.92        # the chain trades slightly ahead of the field

# ---------------------------------------------------------------------------
# True visit volumes from a Huff model with a known decay
# ---------------------------------------------------------------------------
def distance_matrix(oa, sites):
    d = np.hypot(oa.x.to_numpy()[:, None] - sites.x.to_numpy()[None, :],
                 oa.y.to_numpy()[:, None] - sites.y.to_numpy()[None, :])
    return np.maximum(d, 0.35) * ROAD_FACTOR      # floor stops a co-located OA exploding

def huff(oa, sites, beta):
    """P(area i chooses site j) proportional to attractiveness / distance^beta."""
    d = distance_matrix(oa, sites)
    util = sites.attract.to_numpy()[None, :] * d ** (-beta)
    return util / util.sum(axis=1, keepdims=True)

CHOICE = pd.concat([SITES.assign(own=1), COMP.assign(own=0)], ignore_index=True)
P_all = huff(OA, CHOICE, TRUE_BETA)
own = CHOICE.own.to_numpy() == 1
P_true = P_all[:, own]
# annual visits per adult, before the gravity split
base_rate = 26.5
demand = (OA.population.to_numpy() * OA.propensity.to_numpy() * base_rate)
V_true = P_true * demand[:, None]                 # true visits, OA x site

site_revenue = (V_true * OA.spend.to_numpy()[:, None]).sum(axis=0)
SITES["true_visits"] = V_true.sum(axis=0).round(0)
execution = rng.lognormal(0, 0.235, len(SITES))    # unobservable site-level quality
SITES["revenue"] = (site_revenue * execution * rng.normal(1.0, 0.06, len(SITES))).round(-2)

# ---------------------------------------------------------------------------
# The mobile panel. Penetration varies by Mosaic group -- young urban devices are
# heavily over-represented, which is the single biggest trap in footfall work.
# ---------------------------------------------------------------------------
panel_rate = np.clip(PANEL_BASE * OA.panel_bias.to_numpy(), 0.002, 0.25)
OA["panel_devices"] = rng.binomial(OA.population.to_numpy(), panel_rate)
OA["panel_rate_observed"] = OA.panel_devices / OA.population

# observed panel visits: true visits thinned by that area's panel penetration
V_panel = rng.poisson(np.clip(V_true * panel_rate[:, None], 0, None))

obs = []
idx = np.argwhere(V_panel > 0)
for i, j in idx:
    obs.append((OA.oa_id.iat[i], SITES.site_id.iat[j], int(V_panel[i, j])))
PANEL = pd.DataFrame(obs, columns=["oa_id", "site_id", "panel_visits"])

OA.drop(columns=["propensity", "spend", "panel_bias"]).to_csv(OUT / "output_areas.csv", index=False)
MOS[["code", "name", "spend"]].to_csv(OUT / "mosaic_groups.csv", index=False)
MOS[["code", "propensity", "panel_bias"]].to_csv(OUT / "truth_mosaic.csv", index=False)
SITES.to_csv(OUT / "sites.csv", index=False)
COMP.to_csv(OUT / "competitors.csv", index=False)
PIPE.to_csv(OUT / "pipeline.csv", index=False)
PANEL.to_csv(OUT / "panel_visits.csv.gz", index=False, compression="gzip")
TOWN.to_csv(OUT / "towns.csv", index=False)
pd.Series(dict(true_beta=TRUE_BETA, road_factor=ROAD_FACTOR,
               panel_base=PANEL_BASE, base_rate=base_rate)).to_json(OUT / "truth.json")

print(f"output areas {len(OA):,}  population {OA.population.sum():,}  sites {len(SITES)}  competitors {len(COMP)}  pipeline {len(PIPE)}")
print(f"own share of modelled demand {P_true.sum(axis=1).mean():.1%}")
print(f"panel devices {OA.panel_devices.sum():,} ({OA.panel_devices.sum()/OA.population.sum():.2%} of adults)")
print(f"panel visit records {len(PANEL):,}  covering {PANEL.panel_visits.sum():,} observed visits")
print(f"true revenue {SITES.revenue.sum()/1e6:.1f}m across {len(SITES)} sites "
      f"(mean {SITES.revenue.mean()/1e3:.0f}k)")
print("\npanel penetration by Mosaic group (the bias the analysis has to undo):")
print(OA.groupby("mosaic").panel_rate_observed.mean().mul(100).round(2).to_string())

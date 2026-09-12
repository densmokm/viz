#!/usr/bin/env python3
"""
Synthetic transaction data for the Revenue Decomposition demo.

Target: Meridian Coatings Ltd, a UK specialty industrial coatings distributor.
Period: FY24 (Apr-2023 -> Mar-2024) and FY25 (Apr-2024 -> Mar-2025).

Nothing in the bridge is hard-coded. We model the *drivers* (raw-material
index, contractual passthrough by segment, customer churn/acquisition, family
mix drift, FX, a one-off project) and let the analysis discover the bridge
from the resulting line-level data -- exactly as it would on a real deal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20250912
rng = np.random.default_rng(SEED)

OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------
MONTHS = pd.period_range("2023-04", "2025-03", freq="M")          # 24 trading months
IDX_MONTHS = pd.period_range("2023-01", "2025-03", freq="M")      # 27 (3-month price lag)

# Resin / TiO2 composite input-cost index. Rebased to 100 = Jan-2022 steady state.
# Rises hard through FY24, plateaus mid-FY25, then starts to ease.
_RAW = [
    96, 97, 99, 101, 103, 105, 107, 109, 111, 113, 114, 115,          # 2023
    116, 117, 118, 119, 120, 121, 122, 123, 123, 122, 121, 120,        # 2024
    119, 118, 117,                                                      # Jan-Mar 2025
]
RAW_INDEX = dict(zip(IDX_MONTHS, _RAW))

# GBP per EUR. EUR strengthens modestly through FY25 -> small positive translation.
_FX = [
    0.8560, 0.8580, 0.8555, 0.8590, 0.8610, 0.8635, 0.8660, 0.8680, 0.8650, 0.8620, 0.8640, 0.8665,
    0.8700, 0.8730, 0.8760, 0.8790, 0.8830, 0.8880, 0.8920, 0.8950, 0.8930, 0.8900, 0.8870, 0.8850,
]
FX = dict(zip(MONTHS, _FX))
FX_REF = round(float(np.mean(_FX[:12])), 5)   # FY24 average: the constant-currency rate

PRICE_LAG = 3          # months between index move and contractual price reset
SCALE = 2.000          # global volume calibration (tuned so FY24 lands near GBP 42m)

def fiscal_year(p: pd.Period) -> str:
    return "FY25" if p >= pd.Period("2024-04", freq="M") else "FY24"

def fiscal_quarter(p: pd.Period) -> str:
    q = ((p.month - 4) % 12) // 3 + 1
    return f"{fiscal_year(p)} Q{q}"

SEASON = {1: 0.82, 2: 0.88, 3: 1.06, 4: 1.02, 5: 1.10, 6: 1.14,
          7: 1.12, 8: 0.96, 9: 1.10, 10: 1.04, 11: 0.98, 12: 0.78}

# --------------------------------------------------------------------------
# Product catalogue
# --------------------------------------------------------------------------
# (family, list price GBP/unit at index 100, gross margin at index 100,
#  annual unit drift, n SKUs)  -- unit = 20L pail / 25kg sack
FAMILIES = [
    ("Industrial Protective",        145.0, 0.34, -0.020, 14),
    ("Marine & Offshore",            265.0, 0.38, -0.120, 10),
    ("Architectural Trade",           62.0, 0.28,  0.050, 16),
    ("Powder Coatings",              118.0, 0.31, -0.030, 14),
    ("Specialty Resins & Additives", 340.0, 0.41, -0.080, 10),
]
FAMILY_SHARE = np.array([0.30, 0.16, 0.26, 0.18, 0.10])

_GRADE = ["Primer", "Topcoat", "Sealer", "Basecoat", "Hardener", "Thinner",
          "Intermediate", "Finish", "Etch Primer", "Clearcoat"]
_CODE = ["MX", "PR", "DX", "ZN", "EP", "PU", "AC", "SI", "VX", "TG"]

skus = []
for fi, (fam, base_px, gm, drift, n) in enumerate(FAMILIES):
    for j in range(n):
        px = float(base_px * np.exp(rng.normal(0, 0.22)))
        gm_j = float(np.clip(gm + rng.normal(0, 0.035), 0.14, 0.55))
        skus.append({
            "sku": f"{_CODE[fi * 2 + j % 2]}-{1000 + fi * 100 + j}",
            "sku_name": f"{fam.split()[0]} {rng.choice(_GRADE)} {rng.integers(100, 999)}",
            "product_family": fam,
            "family_idx": fi,
            "base_price": round(px, 2),
            "base_cost": round(px * 0.88 * (1 - gm_j), 2),
            "family_drift": drift,
        })
SKUS = pd.DataFrame(skus)
FAM_SKUS = {fi: SKUS.index[SKUS.family_idx == fi].to_numpy() for fi in range(len(FAMILIES))}

# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
# segment -> (count, base units/month, orders/month, discount, passthrough,
#             monthly churn hazard, annual unit drift)
SEGMENTS = {
    "Key Account": dict(n=26,  units=280.0, orders=8.0, disc=0.88, pt=0.82, hz=0.0040, drift=-0.015),
    "Mid-Market":  dict(n=95,  units=52.0,  orders=4.0, disc=0.95, pt=0.92, hz=0.0130, drift=-0.010),
    "SME":         dict(n=265, units=7.5,   orders=1.3, disc=1.02, pt=1.00, hz=0.0260, drift=-0.050),
    "Distributor": dict(n=74,  units=140.0, orders=6.0, disc=0.82, pt=0.85, hz=0.0060, drift=0.010),
}
CHANNEL_BY_SEG = {
    "Key Account": (["Direct Sales", "National Accounts"], [0.75, 0.25]),
    "Mid-Market":  (["Direct Sales", "Trade Counter", "E-commerce"], [0.60, 0.28, 0.12]),
    "SME":         (["Trade Counter", "E-commerce", "Direct Sales"], [0.48, 0.40, 0.12]),
    "Distributor": (["Distributor", "National Accounts"], [0.88, 0.12]),
}
REGIONS = ["UK - North", "UK - Midlands", "UK - South", "Ireland", "EU - Benelux", "EU - Nordics"]
REGION_W = [0.20, 0.19, 0.27, 0.06, 0.16, 0.12]
EUR_REGIONS = {"Ireland", "EU - Benelux", "EU - Nordics"}

_PRE = ["Halstead", "Brockwell", "Caldera", "Thornbury", "Ashgrove", "Pennine", "Kestrel", "Marlowe",
        "Ravensworth", "Blackthorn", "Wexford", "Dunmore", "Granton", "Selby", "Cranfield", "Newbold",
        "Latimer", "Fairhurst", "Orwell", "Draycott", "Bellingham", "Coniston", "Harlow", "Stanmore",
        "Ferndale", "Wraysbury", "Tavistock", "Elmsworth", "Kinross", "Brackley", "Alderley", "Quorn",
        "Redmayne", "Sandhurst", "Ilkley", "Pentland", "Garforth", "Whitlock", "Ossett", "Medway",
        "Langdale", "Burnham", "Corby", "Ingleton", "Vandermeer", "Lindholm", "Aalders", "Nystrom"]
_SUF = ["Industrial Supplies", "Coatings Group", "Trade Centre", "Marine Services", "Fabrications",
        "Surface Technologies", "Builders Merchants", "Engineering", "Protective Systems",
        "Paint & Decorating", "Contracting", "Steelworks", "Finishing Ltd", "Distribution"]

_names, _seen = [], set()
while len(_names) < 600:
    nm = f"{rng.choice(_PRE)} {rng.choice(_SUF)}"
    if nm not in _seen:
        _seen.add(nm)
        _names.append(nm)

customers = []
cid = 0
for seg, cfg in SEGMENTS.items():
    chans, cw = CHANNEL_BY_SEG[seg]
    for _ in range(cfg["n"]):
        cid += 1
        region = str(rng.choice(REGIONS, p=REGION_W))
        # Cohort: on the books at FY24 open, won during FY24, or won during FY25
        roll = rng.random()
        if roll < 0.82:
            start, cohort = MONTHS[0], "Existing (pre-FY24)"
        elif roll < 0.90:
            start, cohort = MONTHS[int(rng.integers(1, 12))], "Won in FY24"
        else:
            start, cohort = MONTHS[int(rng.integers(12, 24))], "Won in FY25"

        # FY25 wins skew small and self-serve -- deliberately lower quality
        new_fy25 = cohort == "Won in FY25"
        chan = str(rng.choice(["E-commerce", "Trade Counter"], p=[0.58, 0.42])) if (new_fy25 and seg in ("SME", "Mid-Market")) else str(rng.choice(chans, p=cw))
        size_mult = 0.50 if new_fy25 else 1.0
        hazard = cfg["hz"] * (2.1 if new_fy25 else 1.0)

        customers.append({
            "customer_id": f"C{cid:04d}",
            "customer_name": _names[cid - 1],
            "segment": seg,
            "channel": chan,
            "region": region,
            "currency": "EUR" if region in EUR_REGIONS else "GBP",
            "cohort": cohort,
            "start_month": start,
            "hazard": hazard,
            "base_units": float(cfg["units"] * size_mult * SCALE * np.exp(rng.normal(0, 0.55))),
            "orders_pm": float(cfg["orders"] * np.exp(rng.normal(0, 0.3))),
            "discount": float(cfg["disc"] * np.exp(rng.normal(0, 0.035))),
            "passthrough": float(np.clip(cfg["pt"] + rng.normal(0, 0.05), 0.6, 1.1)),
            "unit_drift": float(cfg["drift"] + rng.normal(0, 0.14)),
        })

CUST = pd.DataFrame(customers)

# One named Key Account carries the FY25 one-off infrastructure programme.
_anchor = CUST.index[(CUST.segment == "Key Account") & (CUST.cohort == "Existing (pre-FY24)")][0]
CUST.loc[_anchor, "customer_name"] = "Caldera Infrastructure Group"
CUST.loc[_anchor, "region"] = "UK - Midlands"
CUST.loc[_anchor, "currency"] = "GBP"
CUST.loc[_anchor, "hazard"] = 0.0
ANCHOR_ID = CUST.loc[_anchor, "customer_id"]

# Churn: draw an end month from the monthly hazard
end_month = []
for _, c in CUST.iterrows():
    m = c["start_month"]
    stop = None
    while m <= MONTHS[-1]:
        if rng.random() < c["hazard"]:
            stop = m
            break
        m += 1
    end_month.append(stop if stop is not None else MONTHS[-1] + 1)
CUST["end_month"] = end_month

# Each customer buys a basket concentrated in a home family
baskets = []
for _, c in CUST.iterrows():
    home = int(rng.choice(len(FAMILIES), p=FAMILY_SHARE))
    fams = [home] + [f for f in rng.choice(len(FAMILIES), size=int(rng.integers(0, 3)), replace=False) if f != home]
    pool = np.concatenate([FAM_SKUS[f] for f in fams])
    k = int(min(len(pool), rng.integers(3, 13)))
    picks = rng.choice(pool, size=k, replace=False)
    w = rng.dirichlet(np.full(k, 1.4))
    baskets.append((picks, w))

# --------------------------------------------------------------------------
# Generate line-level sales
# --------------------------------------------------------------------------
def price_factor(seg_pt: float, m: pd.Period) -> float:
    """Realised selling price vs index-100 base, given a lagged contractual reset."""
    return 1.0 + seg_pt * (RAW_INDEX[m - PRICE_LAG] / 100.0 - 1.0)

def cost_factor(m: pd.Period) -> float:
    return RAW_INDEX[m] / 100.0

rows = []
inv = 0
for ci, c in CUST.iterrows():
    picks, w = baskets[ci]
    for m in MONTHS:
        if m < c["start_month"] or m >= c["end_month"]:
            continue
        t_yrs = (m - MONTHS[0]).n / 12.0
        n_orders = rng.poisson(c["orders_pm"] * SEASON[m.month])
        if n_orders <= 0:
            continue
        month_units = c["base_units"] * SEASON[m.month] * (1 + c["unit_drift"]) ** t_yrs
        month_units *= float(np.exp(rng.normal(0, 0.18)))
        pf = price_factor(c["passthrough"], m)
        cf = cost_factor(m)
        fx = FX[m]
        is_eur = c["currency"] == "EUR"

        for _ in range(n_orders):
            inv += 1
            k = int(min(len(picks), rng.integers(1, 6)))
            sel = rng.choice(len(picks), size=k, replace=False, p=w / w.sum())
            day = int(rng.integers(1, m.days_in_month + 1))
            date = pd.Timestamp(year=m.year, month=m.month, day=day)
            for s in sel:
                sk = SKUS.iloc[picks[s]]
                # family drift is what bends the mix over time
                fam_mult = (1 + sk.family_drift) ** t_yrs
                qty = month_units * w[s] / max(n_orders, 1) * fam_mult * float(np.exp(rng.normal(0, 0.3)))
                qty = int(max(1, round(qty)))
                px_gbp = sk.base_price * pf * c["discount"] * float(np.exp(rng.normal(0, 0.015)))
                if is_eur:
                    px_loc = px_gbp / FX_REF
                    rev_loc = qty * px_loc
                    rev_gbp, rev_cc = rev_loc * fx, rev_loc * FX_REF
                else:
                    px_loc = px_gbp
                    rev_loc = qty * px_loc
                    rev_gbp = rev_cc = rev_loc
                unit_cost = sk.base_cost * cf
                rows.append((date, m, c.customer_id, c.customer_name, c.segment, c.channel,
                             c.region, c.currency, c.cohort, "Standard", f"INV-{inv:06d}",
                             sk.sku, sk.sku_name, sk.product_family, qty,
                             round(px_loc, 2), round(px_gbp, 2), fx,
                             round(rev_loc, 2), round(rev_gbp, 2), round(rev_cc, 2),
                             round(unit_cost, 2), round(qty * unit_cost, 2)))

# --------------------------------------------------------------------------
# One-off project work (lumpy, non-recurring, sits inside existing customers)
# --------------------------------------------------------------------------
def add_project(cust_row, months, total_units, sku_idx, label):
    global inv
    c = cust_row
    wts = rng.dirichlet(np.full(len(months), 2.0))
    for m, wt in zip(months, wts):
        inv += 1
        pf = price_factor(c["passthrough"], m)
        cf = cost_factor(m)
        day = int(rng.integers(1, m.days_in_month + 1))
        date = pd.Timestamp(year=m.year, month=m.month, day=day)
        for s in sku_idx:
            sk = SKUS.iloc[s]
            qty = int(max(1, round(total_units * wt / len(sku_idx) * float(np.exp(rng.normal(0, 0.12))))))
            px_gbp = sk.base_price * pf * c["discount"] * 0.93     # project pricing concession
            unit_cost = sk.base_cost * cf
            rows.append((date, m, c.customer_id, c.customer_name, c.segment, c.channel,
                         c.region, c.currency, c.cohort, "Project", f"INV-{inv:06d}",
                         sk.sku, sk.sku_name, sk.product_family, qty,
                         round(px_gbp, 2), round(px_gbp, 2), FX[m],
                         round(qty * px_gbp, 2), round(qty * px_gbp, 2), round(qty * px_gbp, 2),
                         round(unit_cost, 2), round(qty * unit_cost, 2)))

_proj_skus = list(FAM_SKUS[0][:3]) + list(FAM_SKUS[1][:2])
# FY24: modest, spread over two customers -- project work is lumpy, not absent
_fy24_hosts = CUST.index[(CUST.segment == "Key Account") & (CUST.cohort == "Existing (pre-FY24)")][1:3]
for h in _fy24_hosts:
    add_project(CUST.loc[h], list(pd.period_range("2023-09", "2023-11", freq="M")), 1500, _proj_skus[:3], "FY24 project")
# FY25: the A14 bridge refurbishment programme -- the one that flatters the bridge
add_project(CUST.loc[_anchor], list(pd.period_range("2024-07", "2025-01", freq="M")), 15600, _proj_skus, "A14 programme")

COLS = ["date", "period", "customer_id", "customer_name", "segment", "channel", "region",
        "currency", "cohort", "order_type", "invoice_id", "sku", "sku_name", "product_family",
        "quantity", "unit_price_local", "unit_price_gbp", "fx_rate_gbp_per_eur",
        "revenue_local", "revenue_gbp", "revenue_gbp_cc", "unit_cost_gbp", "cogs_gbp"]
tx = pd.DataFrame(rows, columns=COLS)
tx["fiscal_year"] = tx["period"].map(fiscal_year)
tx["fiscal_quarter"] = tx["period"].map(fiscal_quarter)
tx["period"] = tx["period"].astype(str)
tx = tx.sort_values("date").reset_index(drop=True)

tx.to_csv(OUT / "transactions.csv.gz", index=False, compression="gzip")
tx.head(500).to_csv(OUT / "transactions_sample.csv", index=False)
CUST.assign(start_month=CUST.start_month.astype(str), end_month=CUST.end_month.astype(str)) \
    .drop(columns=["hazard"]).to_csv(OUT / "customers.csv", index=False)

summary = tx.groupby("fiscal_year").agg(
    revenue_gbp=("revenue_gbp", "sum"), cogs=("cogs_gbp", "sum"),
    units=("quantity", "sum"), lines=("sku", "size"),
    customers=("customer_id", "nunique"))
summary["gm_pct"] = 1 - summary.cogs / summary.revenue_gbp
print(f"rows={len(tx):,}  fx_ref={FX_REF}")
print(summary.round(3).to_string())
print(f"\ndelta revenue = {summary.revenue_gbp.diff().iloc[-1]:,.0f} "
      f"({summary.revenue_gbp.pct_change().iloc[-1]:.1%})")

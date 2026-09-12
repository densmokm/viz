#!/usr/bin/env python3
"""
Revenue decomposition for Meridian Coatings Ltd.

Two lenses on the same GBP 7.8m of growth, reconciled to the penny:

  COMMERCIAL   FY24 -> Volume -> Price -> Mix -> One-off -> FX -> FY25
  CUSTOMER     FY24 -> Lost -> Contraction -> Expansion -> New -> FX -> FY25

and a single unified bridge that nests one inside the other:

  FY24 - Lost + New + [retained: Volume + Price + Mix] + One-off + FX = FY25

Every component is derived from line-level data. Nothing is plugged.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA, OUT = BASE / "data", BASE / "data"

FY0, FY1 = "FY24", "FY25"
PRICE_LAG = 3
_RAW = [96, 97, 99, 101, 103, 105, 107, 109, 111, 113, 114, 115,
        116, 117, 118, 119, 120, 121, 122, 123, 123, 122, 121, 120, 119, 118, 117]
RAW_INDEX = dict(zip(pd.period_range("2023-01", "2025-03", freq="M"), _RAW))

tx = pd.read_csv(DATA / "transactions.csv.gz")
cust = pd.read_csv(DATA / "customers.csv")
tx["period"] = pd.PeriodIndex(tx["period"], freq="M")
tx = tx.merge(cust[["customer_id", "passthrough"]], on="customer_id", how="left")

f0, f1 = tx.fiscal_year == FY0, tx.fiscal_year == FY1
R0_act, R1_act = tx.loc[f0, "revenue_gbp"].sum(), tx.loc[f1, "revenue_gbp"].sum()
R0_cc, R1_cc = tx.loc[f0, "revenue_gbp_cc"].sum(), tx.loc[f1, "revenue_gbp_cc"].sum()
FX_EFFECT = (R1_act - R0_act) - (R1_cc - R0_cc)


# ---------------------------------------------------------------------------
# Price / Volume / Mix
# ---------------------------------------------------------------------------
def pvm(df: pd.DataFrame) -> dict:
    """Exact three-way PVM split on constant-currency revenue, grouped by SKU.

        Volume = (Q1 - Q0) * p0_bar          change in units at last year's average price
        Price  = sum q1 * (p1 - p0)          per-SKU realised price change at this year's units
        Mix    = sum q1 * p0 - Q1 * p0_bar   what shifting the basket did, at last year's prices

    Volume + Price + Mix == R1 - R0 identically, for any choice of p0 on SKUs
    that did not trade last year (we use the prior-year average price).
    """
    g = (df.groupby(["sku", "fiscal_year"])
           .agg(q=("quantity", "sum"), r=("revenue_gbp_cc", "sum"))
           .unstack("fiscal_year"))
    q0 = g[("q", FY0)].fillna(0.0) if ("q", FY0) in g else pd.Series(0.0, index=g.index)
    q1 = g[("q", FY1)].fillna(0.0) if ("q", FY1) in g else pd.Series(0.0, index=g.index)
    r0 = g[("r", FY0)].fillna(0.0) if ("r", FY0) in g else pd.Series(0.0, index=g.index)
    r1 = g[("r", FY1)].fillna(0.0) if ("r", FY1) in g else pd.Series(0.0, index=g.index)

    Q0, Q1, R0, R1 = q0.sum(), q1.sum(), r0.sum(), r1.sum()
    if Q0 == 0 or Q1 == 0:
        return dict(volume=0.0, price=0.0, mix=0.0, delta=float(R1 - R0),
                    r0=float(R0), r1=float(R1), q0=float(Q0), q1=float(Q1))
    p0_bar = R0 / Q0
    p0 = np.where(q0 > 0, r0 / q0.replace(0, np.nan), p0_bar)
    p1 = np.where(q1 > 0, r1 / q1.replace(0, np.nan), 0.0)
    p0 = np.nan_to_num(p0, nan=p0_bar)
    p1 = np.nan_to_num(p1, nan=0.0)

    volume = (Q1 - Q0) * p0_bar
    price = float((q1.to_numpy() * (p1 - p0)).sum())
    mix = float((q1.to_numpy() * p0).sum() - Q1 * p0_bar)
    return dict(volume=float(volume), price=price, mix=mix, delta=float(R1 - R0),
                r0=float(R0), r1=float(R1), q0=float(Q0), q1=float(Q1),
                p0_bar=float(p0_bar), p1_bar=float(R1 / Q1))


# ---------------------------------------------------------------------------
# Customer cohorts
# ---------------------------------------------------------------------------
by_cust = (tx.pivot_table(index="customer_id", columns="fiscal_year",
                          values="revenue_gbp_cc", aggfunc="sum")
             .reindex(columns=[FY0, FY1]).fillna(0.0))
active0, active1 = by_cust[FY0] > 0, by_cust[FY1] > 0
retained = by_cust.index[active0 & active1]
lost = by_cust.index[active0 & ~active1]
new = by_cust.index[~active0 & active1]

LOST = -float(by_cust.loc[lost, FY0].sum())
NEW = float(by_cust.loc[new, FY1].sum())
ret_delta = by_cust.loc[retained, FY1] - by_cust.loc[retained, FY0]
EXPANSION = float(ret_delta[ret_delta > 0].sum())
CONTRACTION = float(ret_delta[ret_delta < 0].sum())

# Retained book, split standard vs one-off project work
ret_tx = tx[tx.customer_id.isin(retained)]
std = ret_tx[ret_tx.order_type == "Standard"]
prj = ret_tx[ret_tx.order_type == "Project"]
PVM_RET = pvm(std)
PROJECT = float(prj.loc[prj.fiscal_year == FY1, "revenue_gbp_cc"].sum()
                - prj.loc[prj.fiscal_year == FY0, "revenue_gbp_cc"].sum())

UNIFIED = [
    dict(label=f"{FY0} revenue", value=float(R0_act), kind="total"),
    dict(label="Volume (organic)", value=PVM_RET["volume"], kind="delta", lens="commercial",
         note="Retained book, units at prior-year average price"),
    dict(label="Price", value=PVM_RET["price"], kind="delta", lens="commercial",
         note="Per-SKU realised price change at current-year volumes"),
    dict(label="Mix", value=PVM_RET["mix"], kind="delta", lens="commercial",
         note="Basket shift toward lower-ASP lines, at prior-year prices"),
    dict(label="One-off project", value=PROJECT, kind="delta", lens="commercial",
         note="Non-recurring contract volume, retained accounts"),
    dict(label="New customers", value=NEW, kind="delta", lens="customer",
         note=f"{len(new)} accounts with no {FY0} billings"),
    dict(label="Lost customers", value=LOST, kind="delta", lens="customer",
         note=f"{len(lost)} accounts billed in {FY0} but not in {FY1}"),
    dict(label="FX translation", value=FX_EFFECT, kind="delta", lens="commercial",
         note="EUR book retranslated at actual vs prior-year average rates"),
    dict(label=f"{FY1} revenue", value=float(R1_act), kind="total"),
]
RECON = float(R0_act + sum(s["value"] for s in UNIFIED if s["kind"] == "delta") - R1_act)

COMMERCIAL_ALL = pvm(tx)
CUSTOMER_LENS = [
    dict(label=f"{FY0} revenue", value=float(R0_act), kind="total"),
    dict(label="Lost customers", value=LOST, kind="delta"),
    dict(label="Contraction", value=CONTRACTION, kind="delta",
         note="Retained accounts spending less than last year"),
    dict(label="Expansion", value=EXPANSION, kind="delta",
         note="Retained accounts spending more than last year"),
    dict(label="New customers", value=NEW, kind="delta"),
    dict(label="FX translation", value=FX_EFFECT, kind="delta"),
    dict(label=f"{FY1} revenue", value=float(R1_act), kind="total"),
]


# ---------------------------------------------------------------------------
# Where the expansion actually came from
# ---------------------------------------------------------------------------
expanders = ret_delta.index[ret_delta > 0]
PVM_EXP = pvm(std[std.customer_id.isin(expanders)])


# ---------------------------------------------------------------------------
# Attributable PVM by group (per-group parts sum back to the total)
# ---------------------------------------------------------------------------
def pvm_detail(df: pd.DataFrame, group: str) -> pd.DataFrame:
    """Per-group attribution that a deal partner can actually read.

    Measuring a group's volume and mix against the *book-average* price is exact
    but unreadable (a flat high-ASP family shows a huge 'mix' number purely
    because it sits above the book average). So each group gets:

        volume  (Q1g - Q0g) * p0g          its own units at its own prior price
        price   sum q1 (p1 - p0)           like-for-like price, SKU by SKU
        mix_in  delta - volume - price     SKU mix *within* the group
        mix_bt  (s1g - s0g) * Q1 * (p0g - p0_bar)   the group's share shift

    sum(price) == total Price exactly.  sum(mix_bt) == between-group mix, and
    sum(volume) == total Volume + between-group mix, so the whole thing still
    ties back -- the reconciliation is asserted in check() below.
    """
    g = (df.groupby([group, "sku", "fiscal_year"])
           .agg(q=("quantity", "sum"), r=("revenue_gbp_cc", "sum"))
           .unstack("fiscal_year").fillna(0.0))
    q0, q1 = g[("q", FY0)].to_numpy(), g[("q", FY1)].to_numpy()
    r0, r1 = g[("r", FY0)].to_numpy(), g[("r", FY1)].to_numpy()
    Q0, Q1, p0_bar = q0.sum(), q1.sum(), r0.sum() / q0.sum()
    p0 = np.divide(r0, q0, out=np.full(len(q0), p0_bar), where=q0 > 0)
    p1 = np.divide(r1, q1, out=np.zeros(len(q1)), where=q1 > 0)

    parts = pd.DataFrame({
        "_g": np.asarray(g.index.get_level_values(group)),
        "price": q1 * (p1 - p0),
        "r1_at_p0": q1 * p0,
        "r0": r0, "r1": r1, "q0": q0, "q1": q1,
    })
    out = parts.groupby("_g").sum().reset_index().rename(columns={"_g": group})
    out["delta"] = out.r1 - out.r0
    out["asp0"] = out.r0 / out.q0.replace(0, np.nan)
    out["asp1"] = out.r1 / out.q1.replace(0, np.nan)
    out["volume"] = (out.q1 - out.q0) * out.asp0
    out["mix_within"] = out.delta - out.volume - out.price
    out["share0"], out["share1"] = out.q0 / Q0, out.q1 / Q1
    out["mix_between"] = (out.share1 - out.share0) * Q1 * (out.asp0 - p0_bar)
    out["lfl_price"] = out.price / out.r1_at_p0
    out["unit_change"] = out.q1 / out.q0 - 1
    out["asp_change"] = out.asp1 / out.asp0 - 1
    return out

FAMILY = pvm_detail(std, "product_family").sort_values("r1", ascending=False)
SEGMENT = pvm_detail(std, "segment").sort_values("r1", ascending=False)
CHANNEL = pvm_detail(std, "channel").sort_values("r1", ascending=False)


# ---------------------------------------------------------------------------
# Quarterly trend: mix-neutral price and volume indices
# ---------------------------------------------------------------------------
sku_p0 = (tx[f0].groupby("sku").agg(r=("revenue_gbp_cc", "sum"), q=("quantity", "sum")))
sku_p0 = (sku_p0.r / sku_p0.q).rename("p0")
qt = tx.join(sku_p0, on="sku")
qt["const_price_rev"] = qt.quantity * qt.p0
_std = qt.order_type == "Standard"
qt["revenue_ex_project"] = qt.revenue_gbp.where(_std, 0.0)
qt["const_price_rev_ex_project"] = qt.const_price_rev.where(_std, 0.0)

QUARTERS = (qt.groupby("fiscal_quarter")
              .agg(revenue=("revenue_gbp", "sum"), revenue_cc=("revenue_gbp_cc", "sum"),
                   const_price_rev=("const_price_rev", "sum"), units=("quantity", "sum"),
                   cogs=("cogs_gbp", "sum"), customers=("customer_id", "nunique"),
                   revenue_ex_project=("revenue_ex_project", "sum"),
                   const_price_rev_ex_project=("const_price_rev_ex_project", "sum"))
              .reset_index().sort_values("fiscal_quarter"))
QUARTERS["price_index"] = 100 * QUARTERS.revenue_cc / QUARTERS.const_price_rev
QUARTERS["volume_index"] = 100 * QUARTERS.const_price_rev / QUARTERS.const_price_rev.iloc[0]
QUARTERS["gm_pct"] = 1 - QUARTERS.cogs / QUARTERS.revenue
QUARTERS["yoy"] = QUARTERS.revenue.pct_change(4)
QUARTERS["volume_yoy"] = QUARTERS.const_price_rev.pct_change(4)
QUARTERS["yoy_ex_project"] = QUARTERS.revenue_ex_project.pct_change(4)
QUARTERS["volume_yoy_ex_project"] = QUARTERS.const_price_rev_ex_project.pct_change(4)


# ---------------------------------------------------------------------------
# Passthrough timing: is FY25 gross margin real, or a lag windfall?
# ---------------------------------------------------------------------------
idx_now = tx.period.map(RAW_INDEX).astype(float)
idx_lag = (tx.period - PRICE_LAG).map(RAW_INDEX).astype(float)
pf_lag = 1 + tx.passthrough * (idx_lag / 100 - 1)      # price actually charged
pf_now = 1 + tx.passthrough * (idx_now / 100 - 1)      # price if resets were instant
pf_exit = 1 + tx.passthrough * (_RAW[-1] / 100 - 1)    # price once Mar-25 index feeds through

tx["revenue_norm"] = tx.revenue_gbp * pf_now / pf_lag
tx["revenue_exit"] = tx.revenue_gbp * pf_exit / pf_lag

R0_norm, R1_norm = tx.loc[f0, "revenue_norm"].sum(), tx.loc[f1, "revenue_norm"].sum()
C0, C1 = tx.loc[f0, "cogs_gbp"].sum(), tx.loc[f1, "cogs_gbp"].sum()
MARGIN = dict(
    gm0=float(1 - C0 / R0_act), gm1=float(1 - C1 / R1_act),
    gm0_norm=float(1 - C0 / R0_norm), gm1_norm=float(1 - C1 / R1_norm),
    gp0=float(R0_act - C0), gp1=float(R1_act - C1),
    windfall0=float(R0_act - R0_norm),        # negative = margin squeeze
    windfall1=float(R1_act - R1_norm),        # positive = lag windfall
    swing=float((R1_act - R1_norm) - (R0_act - R0_norm)),
    reversal_exposure=float(tx.loc[f1, "revenue_exit"].sum() - R1_act),
    index_peak=float(max(_RAW)), index_exit=float(_RAW[-1]),
    avg_passthrough=float(np.average(tx.loc[f1, "passthrough"], weights=tx.loc[f1, "revenue_gbp"])),
)


# Monthly: the lag between the cost index and the price actually charged.
# Both rebased to FY24 average = 100 so they sit on one axis honestly.
_m = (qt.groupby("period").agg(rev_cc=("revenue_gbp_cc", "sum"),
                               cpr=("const_price_rev", "sum")).sort_index())
_m["price_index"] = 100 * _m.rev_cc / _m.cpr
_fy24_price_base = _m.loc[[p for p in _m.index if p < pd.Period("2024-04", freq="M")], "price_index"].mean()
_fy24_raw_base = np.mean([RAW_INDEX[p] for p in _m.index if p < pd.Period("2024-04", freq="M")])
MONTHLY = [dict(month=str(p), label=p.strftime("%b-%y"),
                cost_index=float(RAW_INDEX[p] / _fy24_raw_base * 100),
                price_index=float(r.price_index / _fy24_price_base * 100),
                revenue=float(r.rev_cc))
           for p, r in _m.iterrows()]

# Normalised margin by quarter: what GM would have been with instant price resets
_qn = tx.groupby("fiscal_quarter").agg(rn=("revenue_norm", "sum"), c=("cogs_gbp", "sum"),
                                       r=("revenue_gbp", "sum"))
QUARTERS["gm_pct_norm"] = QUARTERS.fiscal_quarter.map(1 - _qn.c / _qn.rn)


# ---------------------------------------------------------------------------
# Quality of the new-logo cohort
# ---------------------------------------------------------------------------
first_bill = tx.groupby("customer_id").period.min()
last_bill = tx.groupby("customer_id").period.max()
h1 = pd.period_range("2024-04", "2024-09", freq="M")
q4 = pd.Period("2025-01", freq="M")

new_h1 = [c for c in new if first_bill[c] in h1]
survivors = [c for c in new_h1 if last_bill[c] >= q4]
SURVIVAL = len(survivors) / max(len(new_h1), 1)

new_tx1 = tx[f1 & tx.customer_id.isin(new)]
ret_tx1 = tx[f1 & tx.customer_id.isin(retained)]
NEW_COHORT = dict(
    count=int(len(new)), revenue=float(new_tx1.revenue_gbp.sum()),
    share_of_fy25=float(new_tx1.revenue_gbp.sum() / R1_act),
    avg_account=float(new_tx1.revenue_gbp.sum() / max(len(new), 1)),
    avg_account_retained=float(ret_tx1.revenue_gbp.sum() / max(len(retained), 1)),
    gm_pct=float(1 - new_tx1.cogs_gbp.sum() / new_tx1.revenue_gbp.sum()),
    gm_pct_retained=float(1 - ret_tx1.cogs_gbp.sum() / ret_tx1.revenue_gbp.sum()),
    h1_cohort=int(len(new_h1)), h1_surviving=int(len(survivors)), survival=float(SURVIVAL),
    channels=[dict(channel=k, revenue=float(v))
              for k, v in new_tx1.groupby("channel").revenue_gbp.sum().sort_values(ascending=False).items()],
)

LOST_DETAIL = dict(
    count=int(len(lost)), revenue=float(-LOST),
    by_segment=[dict(segment=k, revenue=float(v)) for k, v in
                tx[f0 & tx.customer_id.isin(lost)].groupby("segment").revenue_gbp.sum()
                  .sort_values(ascending=False).items()],
)

names = cust.set_index("customer_id").customer_name
mov = (by_cust.assign(delta=by_cust[FY1] - by_cust[FY0]).join(names))
TOP_MOVERS = [dict(name=r.customer_name, fy24=float(r[FY0]), fy25=float(r[FY1]), delta=float(r.delta))
              for _, r in pd.concat([mov.nlargest(6, "delta"), mov.nsmallest(5, "delta")]).iterrows()]

top10_0 = tx[f0].groupby("customer_id").revenue_gbp.sum().nlargest(10).sum() / R0_act
top10_1 = tx[f1].groupby("customer_id").revenue_gbp.sum().nlargest(10).sum() / R1_act
CONCENTRATION = dict(top10_fy24=float(top10_0), top10_fy25=float(top10_1),
                     customers_fy24=int(active0.sum()), customers_fy25=int(active1.sum()))


# ---------------------------------------------------------------------------
# Quality of growth
# ---------------------------------------------------------------------------
DELTA = R1_act - R0_act
PRICE, VOL, MIX = PVM_RET["price"], PVM_RET["volume"], PVM_RET["mix"]
new_sustainable = NEW * SURVIVAL

QUALITY = dict(
    headline_growth=float(DELTA / R0_act),
    ex_oneoff_fx=float((DELTA - PROJECT - FX_EFFECT) / R0_act),
    ex_price=float((DELTA - PROJECT - FX_EFFECT - PRICE) / R0_act),
    underlying=float((VOL + MIX + new_sustainable + LOST) / R0_act),
    new_haircut=float(NEW - new_sustainable),
    components=[
        dict(label="Price", value=float(PRICE), rating="At risk",
             why="Contractual passthrough of resin and TiO2 cost. Resets are symmetric: "
                 f"the index has already eased from {max(_RAW)} at peak to {_RAW[-1]}."),
        dict(label="One-off project", value=float(PROJECT), rating="Non-recurring",
             why="Single infrastructure programme, one account, completes in FY26 Q1."),
        dict(label="FX translation", value=float(FX_EFFECT), rating="Non-recurring",
             why="Translation only. No underlying trading effect."),
        dict(label="New customers", value=float(NEW), rating="Partly recurring",
             why=f"Only {SURVIVAL:.0%} of the FY25 H1 new-logo cohort was still billing in Q4. "
                 "Haircut applied to the annualised contribution."),
        dict(label="Lost customers", value=float(LOST), rating="Recurring",
             why=f"{len(lost)} accounts gone. The loss repeats in FY26 and compounds."),
        dict(label="Volume (organic)", value=float(VOL), rating="Recurring",
             why="True underlying demand on the retained book."),
        dict(label="Mix", value=float(MIX), rating="Recurring",
             why="Structural drift toward lower-ASP architectural lines."),
    ],
)

q4_25 = QUARTERS[QUARTERS.fiscal_quarter == f"{FY1} Q4"].iloc[0]
q4_24 = QUARTERS[QUARTERS.fiscal_quarter == f"{FY0} Q4"].iloc[0]
RUNRATE = dict(q4_fy25=float(q4_25.revenue), q4_fy24=float(q4_24.revenue),
               q4_yoy=float(q4_25.revenue / q4_24.revenue - 1),
               annualised=float(q4_25.revenue * 4),
               volume_yoy_q4=float(q4_25.const_price_rev / q4_24.const_price_rev - 1),
               fy25_reported=float(R1_act))


# ---------------------------------------------------------------------------
# Mix, split into "which families grew" vs "which SKUs inside them grew"
# ---------------------------------------------------------------------------
MIX_SPLIT = dict(total=float(MIX),
                 between_family=float(FAMILY.mix_between.sum()),
                 within_family=float(MIX - FAMILY.mix_between.sum()))


def check():
    """Assert the bridge ties. If any of these fail, nothing else is worth reading."""
    tol = 1.0   # GBP, against a ~50m book
    assert abs(RECON) < tol, f"unified bridge off by {RECON}"
    assert abs((VOL + PRICE + MIX) - PVM_RET["delta"]) < tol, "retained PVM does not tie"
    assert abs((LOST + CONTRACTION + EXPANSION + NEW) - (R1_cc - R0_cc)) < tol, "customer lens does not tie"
    assert abs(FAMILY.price.sum() - PVM_RET["price"]) < tol, "family price does not tie to total"
    assert abs(FAMILY.delta.sum() - PVM_RET["delta"]) < tol, "family delta does not tie to total"
    assert abs(FAMILY.volume.sum() - (VOL + MIX_SPLIT["between_family"])) < tol, "family volume does not tie"
    assert abs(FAMILY.mix_within.sum() - MIX_SPLIT["within_family"]) < tol, "within-family mix does not tie"
    assert abs(SEGMENT.delta.sum() - PVM_RET["delta"]) < tol, "segment delta does not tie"
    print("  reconciliation checks: all pass")


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    if isinstance(o, (pd.Period, pd.Timestamp)): return str(o)
    raise TypeError(type(o))

def frame(df, cols):
    return [{c: (None if pd.isna(r[c]) else r[c]) for c in cols} for _, r in df.iterrows()]

results = dict(
    meta=dict(company="Meridian Coatings Ltd", sector="Specialty industrial coatings distribution",
              fy0=FY0, fy1=FY1, fy0_period="Apr-2023 to Mar-2024", fy1_period="Apr-2024 to Mar-2025",
              currency="GBP", lines=int(len(tx)), skus=int(tx.sku.nunique()),
              reconciliation_error=RECON),
    headline=dict(r0=float(R0_act), r1=float(R1_act), delta=float(DELTA),
                  growth=float(DELTA / R0_act), units0=float(tx.loc[f0, "quantity"].sum()),
                  units1=float(tx.loc[f1, "quantity"].sum()),
                  asp0=float(R0_cc / tx.loc[f0, "quantity"].sum()),
                  asp1=float(R1_cc / tx.loc[f1, "quantity"].sum()),
                  gm0=MARGIN["gm0"], gm1=MARGIN["gm1"]),
    unified_bridge=UNIFIED, customer_bridge=CUSTOMER_LENS,
    commercial_all=COMMERCIAL_ALL, pvm_retained=PVM_RET, pvm_expansion=PVM_EXP,
    expansion_project=float(EXPANSION - PVM_EXP['delta']), project=float(PROJECT),
    expansion=float(EXPANSION), contraction=float(CONTRACTION),
    family=frame(FAMILY, ["product_family"] + ["r0", "r1", "q0", "q1", "asp0", "asp1", "asp_change", "unit_change", "lfl_price", "volume", "price", "mix_within", "mix_between", "share0", "share1", "delta"]),
    segment=frame(SEGMENT, ["segment"] + ["r0", "r1", "q0", "q1", "asp0", "asp1", "asp_change", "unit_change", "lfl_price", "volume", "price", "mix_within", "mix_between", "share0", "share1", "delta"]),
    channel=frame(CHANNEL, ["channel"] + ["r0", "r1", "q0", "q1", "asp0", "asp1", "asp_change", "unit_change", "lfl_price", "volume", "price", "mix_within", "mix_between", "share0", "share1", "delta"]),
    quarters=frame(QUARTERS, ["fiscal_quarter", "revenue", "revenue_ex_project", "const_price_rev", "units",
                              "price_index", "volume_index", "gm_pct", "yoy", "volume_yoy",
                              "yoy_ex_project", "volume_yoy_ex_project", "gm_pct_norm", "customers"]),
    margin=MARGIN, quality=QUALITY, mix_split=MIX_SPLIT, monthly=MONTHLY, runrate=RUNRATE, new_cohort=NEW_COHORT,
    lost=LOST_DETAIL, top_movers=TOP_MOVERS, concentration=CONCENTRATION,
    raw_index=[dict(month=str(m), index=v) for m, v in RAW_INDEX.items()],
)
check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

# ---------------------------------------------------------------------------
m = lambda x: f"{x/1e6:>8.2f}m"
print(f"{'MERIDIAN COATINGS -- REVENUE BRIDGE':-^62}")
for s in UNIFIED:
    mark = "" if s["kind"] == "total" else ("+" if s["value"] >= 0 else "")
    print(f"  {s['label']:<24} {mark}{m(s['value'])}")
print(f"\n  reconciliation error   {RECON:>12.6f}   (must be ~0)")
print(f"  headline growth        {QUALITY['headline_growth']:>11.1%}")
print(f"  ex one-off + FX        {QUALITY['ex_oneoff_fx']:>11.1%}")
print(f"  ex price as well       {QUALITY['ex_price']:>11.1%}")
print(f"  underlying (haircut)   {QUALITY['underlying']:>11.1%}")
print(f"\n  GM  {MARGIN['gm0']:.1%} -> {MARGIN['gm1']:.1%}   lag windfall swing {MARGIN['swing']/1e6:.2f}m"
      f"   FY26 price reversal exposure {MARGIN['reversal_exposure']/1e6:.2f}m")
print(f"  new-logo H1 cohort survival to Q4: {SURVIVAL:.0%}  ({len(survivors)}/{len(new_h1)})")
print(f"  Q4 FY25 YoY revenue {RUNRATE['q4_yoy']:+.1%}   volume {RUNRATE['volume_yoy_q4']:+.1%}")

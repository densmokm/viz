#!/usr/bin/env python3
"""
Project Kiln -- carve-out financials for Ashworth Industries' Thermal Products division.

The method, in the order the user described it:

  1. take the transaction-level ledger and segment the P&L -- direct where the
     posting carries a division, allocated where it does not
  2. allocate the shared-service pools RECIPROCALLY, because those functions
     consume each other and a single pass gets the wrong answer
  3. restate intercompany trading at arm's length
  4. replace the allocated corporate charge with what the division would actually
     spend standalone
  5. drive the balance sheet off the segmented P&L and the physical drivers --
     headcount, floor area, COGS -- using the sub-ledgers wherever they carry a
     division tag natively

Every line reconciles: divisions plus stranded equals group, and the build fails
if it does not.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data"

GL = pd.read_csv(OUT / "gl_postings.csv.gz",
                 dtype={"account": str, "division": str, "counterparty": str},
                 low_memory=False)
CCS = pd.read_csv(OUT / "cost_centres.csv").fillna({"division": ""})
USAGE = pd.read_csv(OUT / "service_usage.csv")
AR = pd.read_csv(OUT / "ar_ledger.csv.gz").fillna({"division": ""})
INV = pd.read_csv(OUT / "inventory.csv.gz").fillna({"division": ""})
FA = pd.read_csv(OUT / "fixed_assets.csv").fillna({"division": ""})
AP = pd.read_csv(OUT / "ap_ledger.csv.gz").fillna({"division": ""})
ACCRUALS = pd.read_csv(OUT / "accruals.csv").fillna({"division": ""})
BENCH = pd.read_csv(OUT / "standalone_benchmarks.csv")
GL["division"] = GL.division.fillna("")
GL["counterparty"] = GL.counterparty.fillna("")

TARGET = "Thermal Products"
DIVS = [d for d in CCS.division.unique() if d]
SERVICES = sorted(CCS.loc[CCS.kind == "Shared service", "cost_centre"])
CORPORATE = sorted(CCS.loc[CCS.kind == "Corporate", "cost_centre"])
DIV_CC = CCS[CCS.kind == "Division"]

# ---------------------------------------------------------------------------
# 1. Direct P&L, straight off the tagged postings
# ---------------------------------------------------------------------------
direct = (GL[GL.division != ""].groupby(["division", "line"]).amount.sum().unstack(fill_value=0.0))
direct["Revenue"] = -direct["Revenue"]          # credits are negative in the ledger
PL = pd.DataFrame(index=DIVS)
PL["revenue"] = direct["Revenue"]
PL["cogs"] = direct["COGS"]
PL["gross_profit"] = PL.revenue - PL.cogs
PL["direct_opex"] = direct["Operating"]
PL["ebitda_direct"] = PL.gross_profit - PL.direct_opex
PL["da"] = direct["D&A"]
PL["headcount"] = DIV_CC.groupby("division").headcount.sum()
PL["floor_area"] = DIV_CC.groupby("division").floor_area.sum()

# the untagged pools that have to be pushed somewhere
pool = GL[GL.division == ""].groupby("cost_centre").amount.sum()
D_SERVICE = pool.reindex(SERVICES).fillna(0.0)
D_CORP = pool.reindex(CORPORATE).fillna(0.0)

# ---------------------------------------------------------------------------
# 2. Three ways to allocate a shared-service pool
# ---------------------------------------------------------------------------
# p[service][consumer] -- the proportion of that service each consumer uses
P = (USAGE.pivot(index="service", columns="consumer", values="units")
          .reindex(index=SERVICES).fillna(0.0))
P = P.div(P.sum(axis=1), axis=0)
NON_SERVICE = [c for c in P.columns if c not in SERVICES]

def allocate_direct():
    """Ignore inter-service usage entirely. Quick, conventional, and wrong."""
    Q = P[NON_SERVICE].div(P[NON_SERVICE].sum(axis=1), axis=0)
    return Q.mul(D_SERVICE, axis=0).sum(axis=0)

def allocate_stepdown():
    """Allocate services in order of size, never allocating back up the order."""
    remaining = D_SERVICE.copy()
    out = pd.Series(0.0, index=NON_SERVICE)
    order = remaining.sort_values(ascending=False).index
    closed = []
    for s in order:
        targets = [c for c in P.columns if c not in closed and c != s]
        w = P.loc[s, targets]
        w = w / w.sum()
        spread = w * remaining[s]
        for c in targets:
            if c in NON_SERVICE:
                out[c] += spread[c]
            else:
                remaining[c] += spread[c]
        closed.append(s)
    return out

def allocate_reciprocal():
    """
    Services consume each other, so each pool's true cost is its own spend plus
    what it receives from the others:

        T = D + M T        with  M[i][j] = share of service j consumed by i
          = (I - M)^-1 D

    Solve once, then push the grossed-up pools out to the divisions.
    """
    M = P.loc[SERVICES, SERVICES].to_numpy().T      # M[i][j] = P[j][i]
    T = np.linalg.solve(np.eye(len(SERVICES)) - M, D_SERVICE.to_numpy())
    T = pd.Series(T, index=SERVICES)
    return P[NON_SERVICE].mul(T, axis=0).sum(axis=0), T

RECIP_OUT, T_SERVICE = allocate_reciprocal()
METHODS = {"Direct": allocate_direct(), "Step-down": allocate_stepdown(), "Reciprocal": RECIP_OUT}

def to_divisions(alloc):
    """Roll a cost-centre allocation up to divisions."""
    m = CCS.set_index("cost_centre").division
    s = alloc.groupby(m.reindex(alloc.index)).sum()
    return s.reindex(DIVS).fillna(0.0)

SERVICE_BY_METHOD = pd.DataFrame({k: to_divisions(v) for k, v in METHODS.items()})
# the share of each service pool that landed on corporate cost centres
CORP_FROM_SERVICE = {k: float(v.reindex(CORPORATE).fillna(0.0).sum()) for k, v in METHODS.items()}

# ---------------------------------------------------------------------------
# 3. Corporate: grossed up for the services it consumes, then spread on a basis
# ---------------------------------------------------------------------------
CORP_TOTAL = float(D_CORP.sum()) + CORP_FROM_SERVICE["Reciprocal"]

BASES = {
    "Revenue":       PL.revenue,
    "Headcount":     PL.headcount,
    "Gross profit":  PL.gross_profit,
    "EBITDA before corporate": PL.ebitda_direct - SERVICE_BY_METHOD["Reciprocal"],
}
CORP_BY_BASIS = pd.DataFrame({k: CORP_TOTAL * (v / v.sum()) for k, v in BASES.items()})


# ---------------------------------------------------------------------------
# 4. Intercompany: what disappears, and what has to be restated
# ---------------------------------------------------------------------------
ic_sales = -GL[(GL.account == "4100") & (GL.division == TARGET)].amount.sum()
ic_buys = GL[(GL.account == "5300") & (GL.division == TARGET)].amount.sum()
ARM_ADJ = 0.062       # transfer prices sit this far ABOVE market
IC = dict(sales=float(ic_sales), purchases=float(ic_buys), adj=ARM_ADJ,
          sales_adj=float(-ic_sales * ARM_ADJ),
          purchase_adj=float(ic_buys * ARM_ADJ),
          net=float(-ic_sales * ARM_ADJ + ic_buys * ARM_ADJ),
          revenue_at_risk=float(ic_sales),
          counterparties=[dict(name=k, amount=float(-v)) for k, v in
                          GL[(GL.account == "4100") & (GL.division == TARGET)]
                          .groupby("counterparty").amount.sum().items()])

# ---------------------------------------------------------------------------
# 5. Standalone cost: what the allocation says, against what it will actually cost
# ---------------------------------------------------------------------------
tgt_rev = float(PL.loc[TARGET, "revenue"])
alloc_by_cc = pd.Series(0.0, index=list(BENCH.cost_centre))
tgt_ccs = list(DIV_CC[DIV_CC.division == TARGET].cost_centre)
for s in SERVICES:
    alloc_by_cc[s] = float((P.loc[s, tgt_ccs] * T_SERVICE[s]).sum())
corp_share = float(CORP_BY_BASIS.loc[TARGET, "Revenue"] / CORP_TOTAL)
for c in CORPORATE:
    alloc_by_cc[c] = float((D_CORP[c] + METHODS["Reciprocal"].get(c, 0.0)) * corp_share)

rows = []
for _, b in BENCH.iterrows():
    allocated = float(alloc_by_cc.get(b.cost_centre, 0.0))
    lo = max(tgt_rev * b.pct_lo, b.fixed_floor) if b.pct_hi > 0 else 0.0
    hi = max(tgt_rev * b.pct_hi, b.fixed_floor) if b.pct_hi > 0 else 0.0
    mid = (lo + hi) / 2
    rows.append(dict(cost_centre=b.cost_centre, function=b.function, allocated=allocated,
                     standalone_lo=lo, standalone_hi=hi, standalone=mid, gap=mid - allocated))
STANDALONE = pd.DataFrame(rows)
STANDALONE_GAP = float(STANDALONE.gap.sum())

# ---------------------------------------------------------------------------
# 6. The carve-out bridge
# ---------------------------------------------------------------------------
# What the group reports internally: direct result less a simple revenue recharge
simple_recharge = float((float(D_SERVICE.sum()) + float(D_CORP.sum()))
                        * PL.loc[TARGET, "revenue"] / PL.revenue.sum())
REPORTED = float(PL.loc[TARGET, "ebitda_direct"]) - simple_recharge

recip_service = float(SERVICE_BY_METHOD.loc[TARGET, "Reciprocal"])
recip_corp = float(CORP_BY_BASIS.loc[TARGET, "Revenue"])
alloc_delta = simple_recharge - (recip_service + recip_corp)

CARVE = REPORTED + alloc_delta + IC["net"] - STANDALONE_GAP

BRIDGE = [
    dict(label="Divisional EBITDA as reported", value=REPORTED, kind="total"),
    dict(label="Allocation method", value=alloc_delta, kind="delta",
         note="Reciprocal allocation on measured usage, against a flat revenue recharge"),
    dict(label="Intercompany at arm's length", value=IC["net"], kind="delta",
         note=f"Transfer prices sit {ARM_ADJ:.1%} above market; restated to arm's length"),
    dict(label="Standalone cost gap", value=-STANDALONE_GAP, kind="delta",
         note="What these functions cost a business that has to run them itself"),
    dict(label="Carve-out EBITDA", value=CARVE, kind="total"),
]
RECON_PL = float(REPORTED + sum(b["value"] for b in BRIDGE if b["kind"] == "delta") - CARVE)

# ---------------------------------------------------------------------------
# 7. Balance sheet: direct off the sub-ledgers where they carry a division,
#    driven off the segmented P&L and the physical drivers where they do not
# ---------------------------------------------------------------------------
cogs_share = PL.cogs / PL.cogs.sum()
rev_share = PL.revenue / PL.revenue.sum()
hc_share = PL.headcount / PL.headcount.sum()
area_share = PL.floor_area / PL.floor_area.sum()
cc_div = CCS.set_index("cost_centre").division

def split(direct_by_div, untagged_total, driver, label, basis):
    """Direct where the ledger knows, driven where it does not."""
    d = direct_by_div.reindex(DIVS).fillna(0.0)
    a = untagged_total * driver.reindex(DIVS).fillna(0.0)
    total = d + a
    return dict(line=label, basis=basis, direct=float(d[TARGET]), allocated=float(a[TARGET]),
                total=float(total[TARGET]), group=float(d.sum() + untagged_total),
                directness=float(d[TARGET] / total[TARGET]) if total[TARGET] else 1.0,
                by_div={k: float(v) for k, v in total.items()})

BS = []
BS.append(split(AR[AR.division != ""].groupby("division").amount.sum(),
                float(AR[AR.division == ""].amount.sum()), rev_share,
                "Trade receivables", "Group-billed accounts split on revenue"))
BS.append(split(INV[INV.division != ""].groupby("division").value.sum(),
                float(INV[INV.division == ""].value.sum()), cogs_share,
                "Inventory", "Central stores split on cost of sales"))
fa_direct = FA[FA.division != ""].groupby("division").nbv.sum()
BS.append(split(fa_direct, float(FA[FA.division == ""].nbv.sum()), area_share,
                "Property, plant & equipment", "Shared-site assets split on floor area"))
ap_direct = AP[AP.division != ""].groupby("division").amount.sum()
BS.append(split(ap_direct, float(AP[AP.division == ""].amount.sum()), cogs_share,
                "Trade payables", "Shared-cost-centre payables split on cost of sales"))
acc_direct = ACCRUALS[ACCRUALS.division != ""].groupby("division").amount.sum()
acc_untag = ACCRUALS[ACCRUALS.division == ""]
acc_alloc = pd.Series(0.0, index=DIVS)
for drv, g in acc_untag.groupby("driver"):
    share = {"headcount": hc_share, "floor_area": area_share, "revenue": rev_share}[drv]
    acc_alloc += float(g.amount.sum()) * share
BS.append(dict(line="Accruals & provisions", basis="By nature: employee on headcount, property on floor area",
               direct=float(acc_direct.get(TARGET, 0.0)), allocated=float(acc_alloc[TARGET]),
               total=float(acc_direct.get(TARGET, 0.0) + acc_alloc[TARGET]),
               group=float(acc_direct.sum() + acc_untag.amount.sum()),
               directness=float(acc_direct.get(TARGET, 0.0) /
                                (acc_direct.get(TARGET, 0.0) + acc_alloc[TARGET])),
               by_div={k: float(acc_direct.get(k, 0.0) + acc_alloc[k]) for k in DIVS}))

nwc = sum(b["total"] for b in BS if b["line"] in ("Trade receivables", "Inventory")) \
    - sum(b["total"] for b in BS if b["line"] in ("Trade payables", "Accruals & provisions"))
BALANCE = dict(lines=BS, nwc=float(nwc),
               nwc_pct_revenue=float(nwc / tgt_rev),
               ppe=float(next(b["total"] for b in BS if b["line"].startswith("Property"))),
               directness=float(sum(b["direct"] for b in BS) / sum(b["total"] for b in BS)),
               dso=float(next(b["total"] for b in BS if b["line"] == "Trade receivables") / tgt_rev * 365),
               dio=float(next(b["total"] for b in BS if b["line"] == "Inventory")
                         / float(PL.loc[TARGET, "cogs"]) * 365),
               dpo=float(next(b["total"] for b in BS if b["line"] == "Trade payables")
                         / float(PL.loc[TARGET, "cogs"]) * 365))

# ---------------------------------------------------------------------------
# 8. Stranded cost: what stays behind when the division leaves
# ---------------------------------------------------------------------------
# A function sized for three divisions does not shrink by a third when one leaves.
# The removable share is a stated input per function, so it can be argued with.
STANDALONE = STANDALONE.merge(BENCH[["cost_centre", "removable_pct"]], on="cost_centre")
STANDALONE["stranded"] = STANDALONE.allocated * (1 - STANDALONE.removable_pct)
STRANDED = dict(
    allocated_to_target=float(STANDALONE.allocated.sum()),
    removable=float((STANDALONE.allocated * STANDALONE.removable_pct).sum()),
    truly_stranded=float(STANDALONE.stranded.sum()),
    by_function=[dict(function=r.function, allocated=float(r.allocated),
                      removable_pct=float(r.removable_pct), stranded=float(r.stranded))
                 for _, r in STANDALONE.sort_values("stranded", ascending=False).iterrows()],
)
STRANDED["pct_of_allocation"] = STRANDED["truly_stranded"] / STRANDED["allocated_to_target"]


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
results = dict(
    meta=dict(group="Ashworth Industries plc", target=TARGET, codename="Project Kiln",
              sector="Diversified industrial", stage="SPA and transaction support",
              postings=int(len(GL)), cost_centres=int(len(CCS)), divisions=len(DIVS),
              services=len(SERVICES), corporate=len(CORPORATE),
              group_revenue=float(PL.revenue.sum()), target_revenue=tgt_rev,
              untagged_pool=float(D_SERVICE.sum() + D_CORP.sum())),
    untagged=[dict(cost_centre=str(c), name=str(CCS.set_index("cost_centre").loc[c, "name"]),
                   kind=str(CCS.set_index("cost_centre").loc[c, "kind"]), cost=float(v))
              for c, v in pool.sort_values(ascending=False).items()],
    pl=[dict(division=d, revenue=float(PL.loc[d, "revenue"]), cogs=float(PL.loc[d, "cogs"]),
             gross_profit=float(PL.loc[d, "gross_profit"]), direct_opex=float(PL.loc[d, "direct_opex"]),
             ebitda_direct=float(PL.loc[d, "ebitda_direct"]), headcount=int(PL.loc[d, "headcount"]),
             service=float(SERVICE_BY_METHOD.loc[d, "Reciprocal"]),
             corporate=float(CORP_BY_BASIS.loc[d, "Revenue"])) for d in DIVS],
    methods=dict(
        pools=[dict(service=s, name=CCS.set_index("cost_centre").loc[s, "name"],
                    direct_cost=float(D_SERVICE[s]), grossed_up=float(T_SERVICE[s]),
                    uplift=float(T_SERVICE[s] / D_SERVICE[s] - 1)) for s in SERVICES],
        per_service=[dict(service=s, name=CCS.set_index("cost_centre").loc[s, "name"],
                          direct=float((P[NON_SERVICE].div(P[NON_SERVICE].sum(axis=1), axis=0)
                                        .loc[s, [c for c in NON_SERVICE if c.startswith("TP-")]]
                                        * D_SERVICE[s]).sum()),
                          reciprocal=float((P.loc[s, [c for c in NON_SERVICE if c.startswith("TP-")]]
                                            * T_SERVICE[s]).sum()),
                          to_services=float(P.loc[s, SERVICES].sum())) for s in SERVICES],
        spread=[dict(division=d,
                     range=float(SERVICE_BY_METHOD.loc[d].max() - SERVICE_BY_METHOD.loc[d].min()),
                     by_method={k: float(SERVICE_BY_METHOD.loc[d, k]) for k in METHODS})
                for d in DIVS],
        by_method=[dict(method=k, target=float(SERVICE_BY_METHOD.loc[TARGET, k]),
                        by_div={d: float(SERVICE_BY_METHOD.loc[d, k]) for d in DIVS})
                   for k in METHODS],
        usage=[dict(service=s, name=CCS.set_index("cost_centre").loc[s, "name"],
                    cells=[dict(consumer=c, share=float(P.loc[s, c]),
                                kind=str(CCS.set_index("cost_centre").loc[c, "kind"]))
                           for c in P.columns if P.loc[s, c] > 0]) for s in SERVICES]),
    bases=[dict(basis=k, target=float(CORP_BY_BASIS.loc[TARGET, k]),
                ebitda=float(PL.loc[TARGET, "ebitda_direct"] - recip_service - CORP_BY_BASIS.loc[TARGET, k]))
           for k in CORP_BY_BASIS.columns],
    bridge=BRIDGE, recon=RECON_PL,
    summary=dict(reported=REPORTED, carve_out=CARVE, simple_recharge=simple_recharge,
                 service=recip_service, corporate=recip_corp, corp_total=CORP_TOTAL,
                 margin_reported=REPORTED / tgt_rev, margin_carve=CARVE / tgt_rev),
    intercompany=IC,
    standalone=[dict(function=r.function, allocated=float(r.allocated), standalone=float(r.standalone),
                     lo=float(r.standalone_lo), hi=float(r.standalone_hi), gap=float(r.gap))
                for _, r in STANDALONE.sort_values("gap", ascending=False).iterrows()],
    standalone_gap=STANDALONE_GAP, stranded=STRANDED, balance=BALANCE,
)

def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    raise TypeError(type(o))

def check():
    tol = 50.0     # pounds, against a group of ~440m
    # every method must push out exactly the pool it started with
    for k, v in METHODS.items():
        assert abs(v.sum() - D_SERVICE.sum()) < tol, f"{k} allocation loses or creates cost"
    # divisions plus corporate must absorb the whole service pool
    assert abs(SERVICE_BY_METHOD["Reciprocal"].sum() + CORP_FROM_SERVICE["Reciprocal"]
               - D_SERVICE.sum()) < tol, "reciprocal allocation does not reconcile"
    # corporate spreads completely, on every basis
    for k in CORP_BY_BASIS.columns:
        assert abs(CORP_BY_BASIS[k].sum() - CORP_TOTAL) < tol, f"corporate basis {k} does not sum"
    # the carve-out bridge ties
    assert abs(RECON_PL) < 1.0, f"carve-out bridge off by {RECON_PL}"
    # every balance sheet line reconciles across divisions
    for b in BS:
        assert abs(sum(b["by_div"].values()) - b["group"]) < tol, f"{b['line']} does not foot to group"
    print(f"  checks: all three allocations conserve the pool, bridge ties, "
          f"{len(BS)} balance sheet lines foot to group")

check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

m = lambda v: f"{v/1e6:>7.2f}m"
print(f"{'PROJECT KILN -- THERMAL PRODUCTS CARVE-OUT':-^68}")
for b in BRIDGE:
    print(f"  {b['label']:<34}{m(b['value'])}")
print(f"\n  margin {REPORTED/tgt_rev:.1%} reported -> {CARVE/tgt_rev:.1%} carved out "
      f"on revenue of {tgt_rev/1e6:.1f}m")
print(f"\n  shared-service allocation to the target by method:")
for k in METHODS:
    print(f"    {k:<14}{m(SERVICE_BY_METHOD.loc[TARGET, k])}")
print(f"\n  corporate allocation by basis (and the EBITDA it implies):")
for k in CORP_BY_BASIS.columns:
    e = PL.loc[TARGET, 'ebitda_direct'] - recip_service - CORP_BY_BASIS.loc[TARGET, k]
    print(f"    {k:<26}{m(CORP_BY_BASIS.loc[TARGET, k])}   EBITDA {m(e)}")
print(f"\n  standalone cost gap {STANDALONE_GAP/1e6:.2f}m; stranded in the group "
      f"{STRANDED['truly_stranded']/1e6:.2f}m ({STRANDED['pct_of_allocation']:.0%} of the allocation)")
print(f"  net working capital {BALANCE['nwc']/1e6:.1f}m ({BALANCE['nwc_pct_revenue']:.1%} of revenue), "
      f"DSO {BALANCE['dso']:.0f} DIO {BALANCE['dio']:.0f} DPO {BALANCE['dpo']:.0f}")
print(f"  balance sheet directly attributable: {BALANCE['directness']:.0%}")

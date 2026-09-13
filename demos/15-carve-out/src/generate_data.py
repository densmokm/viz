#!/usr/bin/env python3
"""
Synthetic group ledger for Project Kiln.

Ashworth Industries plc is divesting Thermal Products, one of three divisions.
The division has never had standalone financial statements: it shares an ERP, a
chart of accounts, five shared-service functions and a corporate centre with the
rest of the group, and it trades with its sister divisions.

The generator emits what a carve-out team actually receives -- a posting-level
general ledger, a cost-centre master, service usage drivers, headcount, and the
sub-ledgers behind the balance sheet. Nothing is pre-segmented; the division tag
is present on only part of the ledger, which is the whole problem.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

SEED = 20260501
rng = np.random.default_rng(SEED)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)

PERIODS = pd.period_range("2024-04", "2025-03", freq="M")     # FY25, year to 31 March
TARGET = "Thermal Products"

# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
DIVISIONS = {
    "Thermal Products":  dict(code="TP", revenue=142_000_000, gm=0.341, hc=612),
    "Flow Control":      dict(code="FC", revenue=186_000_000, gm=0.298, hc=744),
    "Electrical Systems":dict(code="ES", revenue=110_000_000, gm=0.365, hc=431),
}
SHARED = {
    "SH-IT":   dict(name="IT & Digital",        cost= 4_600_000, driver="devices"),
    "SH-HR":   dict(name="HR & Payroll",        cost= 2_400_000, driver="headcount"),
    "SH-FIN":  dict(name="Transactional Finance",cost= 2_900_000, driver="documents"),
    "SH-FAC":  dict(name="Facilities & Estates", cost= 4_000_000, driver="floor_area"),
    "SH-PROC": dict(name="Group Procurement",    cost= 1_600_000, driver="addressable_spend"),
}
CORPORATE = {
    "CO-EXEC":  dict(name="Group executive",     cost=2_900_000),
    "CO-LEGAL": dict(name="Legal & compliance",  cost=1_600_000),
    "CO-TREAS": dict(name="Treasury & tax",      cost=1_200_000),
    "CO-IR":    dict(name="Investor relations",  cost=800_000),
}

CC = []
for div, d in DIVISIONS.items():
    for fn, share in [("OPS", 0.70), ("SALES", 0.18), ("ENG", 0.12)]:
        CC.append(dict(cost_centre=f"{d['code']}-{fn}", name=f"{div} — {fn.title()}",
                       kind="Division", division=div, headcount=int(d["hc"] * share)))
for code, s in SHARED.items():
    CC.append(dict(cost_centre=code, name=s["name"], kind="Shared service", division="",
                   headcount=int(s["cost"] / 78_000)))
for code, c in CORPORATE.items():
    CC.append(dict(cost_centre=code, name=c["name"], kind="Corporate", division="",
                   headcount=int(c["cost"] / 132_000)))
CCS = pd.DataFrame(CC)

# Divisions consume the shared functions very differently, which is what makes the
# choice of allocation method matter at all.
DRIVER_PROFILE = {
    "Thermal Products":   dict(devices=0.72, documents=0.65, floor_area=1.60, spend=1.35),
    "Flow Control":       dict(devices=0.95, documents=1.70, floor_area=0.82, spend=1.05),
    "Electrical Systems": dict(devices=1.75, documents=0.92, floor_area=0.68, spend=0.72),
}
def prof(div, key):
    return DRIVER_PROFILE[div][key] if div in DRIVER_PROFILE else 1.0

# floor area and document volumes, the other two drivers
CCS["fa_mult"] = [prof(r.division, "floor_area") for _, r in CCS.iterrows()]
CCS["dv_mult"] = [prof(r.division, "devices") for _, r in CCS.iterrows()]
CCS["floor_area"] = np.where(CCS.kind == "Division",
                             CCS.headcount * rng.uniform(28, 46, len(CCS)) * CCS.fa_mult,
                             CCS.headcount * rng.uniform(9, 14, len(CCS))).round(0)
CCS["devices"] = np.where(CCS.kind == "Division",
                          CCS.headcount * rng.uniform(0.8, 1.15, len(CCS)) * CCS.dv_mult,
                          CCS.headcount * rng.uniform(1.5, 2.2, len(CCS))).round(0)
CCS = CCS.drop(columns=["fa_mult", "dv_mult"])

# ---------------------------------------------------------------------------
# Service usage matrix. Shared services consume each other -- IT supports HR,
# HR runs payroll for IT -- which is precisely why a single-pass allocation is
# wrong and the reciprocal method exists.
# ---------------------------------------------------------------------------
CONSUMERS = list(CCS.cost_centre)
SERVICES = list(SHARED)

# who leans on whom, beyond what headcount alone would imply
INTER_WEIGHT = {
    "SH-IT":   {"SH-FIN": 11.0, "SH-HR": 8.5, "SH-FAC": 2.4, "SH-PROC": 5.0},
    "SH-HR":   {"SH-IT":  2.2,  "SH-FIN": 1.6, "SH-FAC": 1.1, "SH-PROC": 1.1},
    "SH-FIN":  {"SH-IT":  1.9,  "SH-HR": 1.3,  "SH-FAC": 1.0, "SH-PROC": 3.2},
    "SH-FAC":  {"SH-IT":  0.9,  "SH-HR": 0.7,  "SH-FIN": 0.8, "SH-PROC": 0.6},
    "SH-PROC": {"SH-IT":  4.2,  "SH-FIN": 1.1, "SH-HR": 0.4,  "SH-FAC": 2.3},
}

usage = []
for svc in SERVICES:
    drv = SHARED[svc]["driver"]
    for _, c in CCS.iterrows():
        if c.cost_centre == svc:
            continue
        if drv == "headcount":            base = c.headcount
        elif drv == "devices":            base = c.devices
        elif drv == "floor_area":         base = c.floor_area
        elif drv == "documents":
            base = c.headcount * (5.4 * prof(c.division, "documents") if c.kind == "Division" else 2.1)
        else:                              # addressable spend
            base = c.headcount * (11.0 * prof(c.division, "spend") if c.kind == "Division" else 3.0)
        # a shared service is a far heavier per-head consumer of other services than
        # a division is -- and crucially, not evenly so
        if c.kind == "Shared service":
            intensity = INTER_WEIGHT.get(svc, {}).get(c.cost_centre, 2.0)
        elif c.kind == "Corporate":
            intensity = 1.6
        else:
            intensity = 1.0
        usage.append(dict(service=svc, consumer=c.cost_centre,
                          units=float(max(base, 1) * intensity * rng.uniform(0.82, 1.22))))
USAGE = pd.DataFrame(usage)

# ---------------------------------------------------------------------------
# General ledger. Division-coded where the source system carries it, blank where
# the cost sits in a shared or corporate cost centre.
# ---------------------------------------------------------------------------
ACCOUNTS = [
    ("4000", "Revenue — third party",      "Revenue"),
    ("4100", "Revenue — intercompany",     "Revenue"),
    ("5000", "Materials",                  "COGS"),
    ("5100", "Direct labour",              "COGS"),
    ("5200", "Subcontract & freight",      "COGS"),
    ("5300", "Purchases — intercompany",   "COGS"),
    ("6000", "Employment costs",           "Operating"),
    ("6100", "Travel & entertainment",     "Operating"),
    ("6200", "Professional fees",          "Operating"),
    ("6300", "Property & utilities",       "Operating"),
    ("6400", "IT & communications",        "Operating"),
    ("6500", "Other operating",            "Operating"),
    ("8000", "Depreciation & amortisation","D&A"),
]
ACC = pd.DataFrame(ACCOUNTS, columns=["account", "account_name", "line"])

SEASON = {m: v for m, v in zip(range(1, 13),
          [.92, .96, 1.09, 1.02, 1.05, 1.03, .99, .94, 1.06, .97, 1.01, .96])}

rows, jid = [], 0
LINE_SCALE = 14          # postings per notional line -- a real ledger is granular

def post(period, cc, division, account, amount, n_lines, spread=0.55, counterparty=""):
    """Explode an annual figure into plausible monthly postings."""
    global jid
    n_lines = max(1, int(n_lines * LINE_SCALE))
    for _ in range(n_lines):
        jid += 1
        mult = float(np.exp(rng.normal(0, spread) - spread ** 2 / 2))   # mean 1, not exp(s^2/2)
        rows.append((f"JE{jid:07d}", str(period), cc, division, account,
                     round(float(amount / n_lines * mult), 2), counterparty))

for div, d in DIVISIONS.items():
    code = d["code"]
    ic_rev = d["revenue"] * rng.uniform(0.03, 0.09)          # sales to sister divisions
    tp_rev = d["revenue"] - ic_rev
    for p in PERIODS:
        f = SEASON[p.month] / 12
        post(p, f"{code}-SALES", div, "4000", -tp_rev * f, 34)
        post(p, f"{code}-SALES", div, "4100", -ic_rev * f, 6,
             counterparty=str(rng.choice([x for x in DIVISIONS if x != div])))
        cogs = d["revenue"] * (1 - d["gm"]) * f
        post(p, f"{code}-OPS", div, "5000", cogs * 0.58, 46)
        post(p, f"{code}-OPS", div, "5100", cogs * 0.27, 12)
        post(p, f"{code}-OPS", div, "5200", cogs * 0.11, 18)
        post(p, f"{code}-OPS", div, "5300", cogs * 0.04, 5,
             counterparty=str(rng.choice([x for x in DIVISIONS if x != div])))
        for fn, w in [("OPS", 0.52), ("SALES", 0.31), ("ENG", 0.17)]:
            opex = d["revenue"] * 0.168 * w * f
            post(p, f"{code}-{fn}", div, "6000", opex * 0.66, 9)
            post(p, f"{code}-{fn}", div, "6100", opex * 0.07, 7)
            post(p, f"{code}-{fn}", div, "6200", opex * 0.06, 4)
            post(p, f"{code}-{fn}", div, "6300", opex * 0.09, 3)
            post(p, f"{code}-{fn}", div, "6400", opex * 0.05, 3)
            post(p, f"{code}-{fn}", div, "6500", opex * 0.07, 5)
        post(p, f"{code}-OPS", div, "8000", d["revenue"] * 0.031 * f, 2)

# shared services and corporate carry no division tag -- this is the carve-out problem
for code, s in SHARED.items():
    for p in PERIODS:
        f = SEASON[p.month] / 12
        post(p, code, "", "6000", s["cost"] * 0.58 * f, 6)
        post(p, code, "", "6400", s["cost"] * 0.17 * f, 4)
        post(p, code, "", "6300", s["cost"] * 0.11 * f, 3)
        post(p, code, "", "6200", s["cost"] * 0.08 * f, 3)
        post(p, code, "", "6500", s["cost"] * 0.06 * f, 4)
for code, c in CORPORATE.items():
    for p in PERIODS:
        f = SEASON[p.month] / 12
        post(p, code, "", "6000", c["cost"] * 0.71 * f, 4)
        post(p, code, "", "6200", c["cost"] * 0.19 * f, 3)
        post(p, code, "", "6500", c["cost"] * 0.10 * f, 3)

GL = pd.DataFrame(rows, columns=["journal_id", "period", "cost_centre", "division",
                                 "account", "amount", "counterparty"])
GL = GL.merge(ACC, on="account", how="left")

# ---------------------------------------------------------------------------
# Balance sheet sub-ledgers. The point of each one is how much of it carries a
# division tag natively and how much has to be driven.
# ---------------------------------------------------------------------------
_CUST = ["Brayford", "Halverstock", "Ingleby", "Kestrel", "Marchmont", "Netherfield", "Orrell",
         "Pemberton", "Quayside", "Rothwell", "Sandmoor", "Thurlow", "Uxbridge", "Vale", "Whitmore"]
_SUFF = ["Engineering", "Industrial", "Group", "Systems", "Holdings", "Manufacturing", "Technologies"]

ar, aid = [], 0
for div, d in DIVISIONS.items():
    dso = {"Thermal Products": 63, "Flow Control": 54, "Electrical Systems": 47}[div]
    total_ar = d["revenue"] * dso / 365
    n = int(total_ar / 26_000)
    for _ in range(n):
        aid += 1
        # ~9% of receivables sit on a group-level billing account with no division tag
        grouped = rng.random() < 0.09
        ar.append(dict(invoice=f"AR{aid:06d}",
                       customer=f"{rng.choice(_CUST)} {rng.choice(_SUFF)}",
                       division="" if grouped else div,
                       billing_entity="Ashworth Group plc" if grouped else div,
                       amount=round(float(total_ar / n * np.exp(rng.normal(0, 0.7) - 0.245)), 2),
                       days_outstanding=int(np.clip(rng.gamma(3.0, dso / 3.0), 1, 210))))
AR = pd.DataFrame(ar)

inv, iid = [], 0
for div, d in DIVISIONS.items():
    turns = {"Thermal Products": 4.1, "Flow Control": 5.6, "Electrical Systems": 6.8}[div]
    total_inv = d["revenue"] * (1 - d["gm"]) / turns
    n = int(total_inv / 14_000)
    for _ in range(n):
        iid += 1
        # common raw materials held centrally, not tagged to a division
        common = rng.random() < 0.13
        inv.append(dict(sku=f"SKU{iid:06d}", division="" if common else div,
                        location="Central stores" if common else f"{DIVISIONS[div]['code']} works",
                        category=str(rng.choice(["Raw materials", "WIP", "Finished goods"],
                                                p=[0.34, 0.21, 0.45])),
                        value=round(float(total_inv / n * np.exp(rng.normal(0, 0.8) - 0.320)), 2),
                        months_held=int(np.clip(rng.gamma(2.0, 2.2), 0, 36))))
INV = pd.DataFrame(inv)

fa, fid = [], 0
ASSET_CLASS = ["Plant & machinery", "Fixtures & fittings", "IT equipment", "Motor vehicles",
               "Leasehold improvements"]
for _, c in CCS.iterrows():
    nbv_total = (c.headcount * rng.uniform(9_000, 26_000) if c.kind == "Division"
                 else c.headcount * rng.uniform(4_000, 11_000))
    n = max(3, int(nbv_total / 38_000))
    for _ in range(n):
        fid += 1
        fa.append(dict(asset_id=f"FA{fid:06d}", cost_centre=c.cost_centre,
                       division=c.division, site="Shared site" if c.kind != "Division" else f"{c.cost_centre} site",
                       asset_class=str(rng.choice(ASSET_CLASS, p=[0.42, 0.14, 0.22, 0.08, 0.14])),
                       cost=round(float(nbv_total / n * rng.uniform(1.4, 2.6)), 2),
                       nbv=round(float(nbv_total / n * np.exp(rng.normal(0, 0.5) - 0.125)), 2)))
FA = pd.DataFrame(fa)

ap, pid = [], 0
for _, c in CCS.iterrows():
    spend = GL[(GL.cost_centre == c.cost_centre) & (GL.amount > 0)].amount.sum()
    total_ap = spend * rng.uniform(0.11, 0.17)
    n = max(4, int(total_ap / 21_000))
    for _ in range(n):
        pid += 1
        ap.append(dict(doc=f"AP{pid:06d}", supplier=f"{rng.choice(_CUST)} Supply Co",
                       cost_centre=c.cost_centre, division=c.division,
                       amount=round(float(total_ap / n * np.exp(rng.normal(0, 0.75) - 0.281)), 2),
                       days_outstanding=int(np.clip(rng.gamma(3.0, 14.0), 1, 150))))
AP = pd.DataFrame(ap)

ACCR = []
for _, c in CCS.iterrows():
    for kind, per_head, driver in [("Employee bonus & holiday pay", 4_200, "headcount"),
                                   ("Property & utilities", 0, "floor_area"),
                                   ("Warranty & rectification", 0, "revenue"),
                                   ("Professional fees", 900, "headcount")]:
        if kind == "Property & utilities":
            amt = c.floor_area * rng.uniform(11, 19)
        elif kind == "Warranty & rectification":
            if c.kind != "Division":
                continue
            amt = DIVISIONS[c.division]["revenue"] * 0.004 * (c.headcount / DIVISIONS[c.division]["hc"])
        else:
            amt = c.headcount * per_head * rng.uniform(0.8, 1.2)
        ACCR.append(dict(cost_centre=c.cost_centre, division=c.division, kind=kind,
                         driver=driver, amount=round(float(amt), 2)))
ACCRUALS = pd.DataFrame(ACCR)

# ---------------------------------------------------------------------------
# Standalone benchmarks: what these functions cost a company of this size that
# has to run them itself. Sourced the way you would on a real deal -- comparable
# company filings and benchmarking data, not the vendor's own view.
# ---------------------------------------------------------------------------
BENCH = pd.DataFrame([
    ("SH-IT",   "IT & Digital",           0.0155, 0.0215,  900_000),
    ("SH-HR",   "HR & Payroll",           0.0058, 0.0082,  420_000),
    ("SH-FIN",  "Transactional Finance",  0.0071, 0.0098,  510_000),
    ("SH-FAC",  "Facilities & Estates",   0.0112, 0.0148,  260_000),
    ("SH-PROC", "Group Procurement",      0.0026, 0.0041,  180_000),
    ("CO-EXEC", "Executive & board",      0.0062, 0.0091, 1_150_000),
    ("CO-LEGAL","Legal & compliance",     0.0021, 0.0034,  340_000),
    ("CO-TREAS","Treasury & tax",         0.0018, 0.0029,  290_000),
    ("CO-IR",   "Listed-company costs",   0.0000, 0.0000,        0),
], columns=["cost_centre", "function", "pct_lo", "pct_hi", "fixed_floor"])
BENCH["removable_pct"] = [0.35, 0.55, 0.60, 0.70, 0.45, 0.10, 0.25, 0.15, 0.00]

GL.to_csv(OUT / "gl_postings.csv.gz", index=False, compression="gzip")
CCS.to_csv(OUT / "cost_centres.csv", index=False)
USAGE.to_csv(OUT / "service_usage.csv", index=False)
ACC.to_csv(OUT / "chart_of_accounts.csv", index=False)
AR.to_csv(OUT / "ar_ledger.csv.gz", index=False, compression="gzip")
INV.to_csv(OUT / "inventory.csv.gz", index=False, compression="gzip")
FA.to_csv(OUT / "fixed_assets.csv", index=False)
AP.to_csv(OUT / "ap_ledger.csv.gz", index=False, compression="gzip")
ACCRUALS.to_csv(OUT / "accruals.csv", index=False)
BENCH.to_csv(OUT / "standalone_benchmarks.csv", index=False)

rev = -GL[GL.account.isin(["4000", "4100"])].amount.sum()
print(f"GL postings {len(GL):,}   cost centres {len(CCS)}   group revenue {rev/1e6:.1f}m")
print(f"untagged cost in the ledger {GL[(GL.division == '') & (GL.amount > 0)].amount.sum()/1e6:.1f}m "
      f"across {(CCS.kind != 'Division').sum()} shared and corporate cost centres")
print(f"AR {len(AR):,} invoices {AR.amount.sum()/1e6:.1f}m  ({(AR.division == '').mean():.0%} untagged)")
print(f"Inventory {len(INV):,} lines {INV.value.sum()/1e6:.1f}m  ({(INV.division == '').mean():.0%} untagged)")
print(f"Fixed assets {len(FA):,} {FA.nbv.sum()/1e6:.1f}m  ({(FA.division == '').mean():.0%} on shared sites)")
print(f"AP {len(AP):,} {AP.amount.sum()/1e6:.1f}m   accruals {ACCRUALS.amount.sum()/1e6:.1f}m")

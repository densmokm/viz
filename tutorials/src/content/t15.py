TUTORIAL = {
 "brand": "Balance Sheet Carve-Out",
 "tag": "Technique 15",
 "phase": "SPA and transaction support",
 "title": "How to carve a division out of a group ledger",
 "subtitle": "Segment the P&L from transactions, allocate the shared functions reciprocally, then drive the "
             "balance sheet off the segmented P&L and the physical drivers — with every line footing back to group.",
 "demo_url": "https://claude.ai/code/artifact/03e43f18-74c5-4df8-ae0a-48d3ea9a8bd5",
 "grain": "one row per journal posting",
 "meta": [["Engine", "PySpark for the ledger, NumPy for the allocation"],
          ["Input", "GL postings, cost centre master, sub-ledgers"],
          ["Runtime", "Minutes on millions of postings"],
          ["Output", "Standalone P&L and balance sheet that reconcile"]],
 "intro": "Standalone financial statements for a division that has never had any. The method is short to "
          "describe and easy to get wrong: segment the P&L from transaction data using explicit allocation "
          "bases, then drive the balance sheet off the segmented P&L and drivers like headcount. The "
          "discipline is that every line has to foot back to the group, and every allocation has to conserve "
          "the pool it started with.",
 "input_intro": "A trial balance is not enough. The allocation has to be rebuilt from the postings, because "
                "the whole question is which postings belong to the division and a summarised balance has "
                "already answered it for you.",
 "inputs": [
   ["journal_id, period", "string, date", "The grain. Reconcile the extract to the filed accounts before anything else."],
   ["cost_centre", "string", "<strong>The spine of the whole exercise.</strong> Everything hangs off whether a centre is divisional, shared or corporate."],
   ["division", "string", "Present on divisional postings, blank on shared and corporate ones. The blanks are the problem."],
   ["account, amount", "string, decimal", "Chart of accounts and value. Watch the sign convention on revenue."],
   ["counterparty", "string", "Which sister division, on intercompany postings. Without it you cannot eliminate or restate."],
   ["service usage", "long", "Tickets, payroll runs, documents, square feet. <strong>Measured usage beats a headcount proxy</strong> and is what makes an allocation defensible."],
   ["sub-ledgers", "tables", "AR by customer, inventory by SKU, fixed assets by cost centre, AP by supplier, accruals by nature. These decide how much of the balance sheet is direct."],
   ["standalone benchmarks", "table", "Function cost as a percentage of revenue for comparable independent businesses, with a floor where it cannot scale down."],
 ],
 "walk_intro": "Nine steps. The ledger work is genuinely large and belongs in Spark; the allocation itself is "
               "a five-by-five matrix inversion that runs in microseconds. Knowing that the hard part is the "
               "data and not the maths saves a lot of wasted engineering.",
 "steps": [
  {"title": "Reconcile before you allocate",
   "why": "Every carve-out argument eventually comes back to whether the extract was complete. Settle it on "
          "day one: tie the ledger to the filed accounts, and check that the cost-centre master covers every "
          "centre that appears in a posting. A carve-out built on an extract that is 3% light because "
          "intercompany was excluded will be discovered at the worst possible moment.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.appName("kiln-carveout").getOrCreate()

gl = (spark.read.parquet("s3://kiln/gl/")
        .filter(F.col("period").between("2024-04-01", "2025-03-31")))
cc = spark.read.parquet("s3://kiln/cost_centres/")

# every posted cost centre must exist in the master
orphans = gl.join(F.broadcast(cc), "cost_centre", "left_anti").select("cost_centre").distinct()
assert orphans.count() == 0, f"cost centres missing from the master: {orphans.collect()}"

# and the ledger must tie to the filed numbers
group_revenue = -gl.filter(F.col("account").startswith("4")).agg(F.sum("amount")).first()[0]
assert abs(group_revenue - FILED_REVENUE) / FILED_REVENUE < 0.001, "extract does not tie to the accounts"''',
            "pandas": '''gl = pd.read_parquet("gl.parquet", dtype={"account": str})
cc = pd.read_parquet("cost_centres.parquet")

orphans = set(gl.cost_centre) - set(cc.cost_centre)
assert not orphans, f"cost centres missing from the master: {orphans}"

group_revenue = -gl.loc[gl.account.str.startswith("4"), "amount"].sum()
assert abs(group_revenue - FILED_REVENUE) / FILED_REVENUE < 0.001'''},
   "note": "Read account codes as strings. They look numeric, so pandas and Spark will infer int64 and every "
           "subsequent <code>account == “4100”</code> comparison will silently match nothing. That exact bug "
           "wiped out the intercompany adjustment in this build and produced a clean-looking zero."},

  {"title": "Take the easy 94% first",
   "why": "Most of the P&L segments itself. Revenue and direct costs post to a divisional cost centre and "
          "need no judgement at all. Do that first, size what is left, and you know immediately how much of "
          "the carve-out is arithmetic and how much is negotiation.",
   "code": {"spark": '''tagged = gl.filter(F.col("division") != "")

direct = (tagged.groupBy("division", "line")
                .agg(F.sum("amount").alias("amount"))
                .groupBy("division").pivot("line").sum("amount")
                .toPandas().set_index("division").fillna(0.0))
direct["Revenue"] = -direct["Revenue"]        # credits post negative

# what is left is the carve-out problem, and its size is the first finding
pool = (gl.filter(F.col("division") == "")
          .groupBy("cost_centre").agg(F.sum("amount").alias("cost"))
          .toPandas().set_index("cost_centre").cost)

print(f"untagged {pool.sum()/1e6:.1f}m across {len(pool)} cost centres")''',
            "pandas": '''tagged = gl[gl.division.ne("")]

direct = (tagged.pivot_table(index="division", columns="line", values="amount", aggfunc="sum")
                .fillna(0.0))
direct["Revenue"] = -direct["Revenue"]

pool = gl[gl.division.eq("")].groupby("cost_centre").amount.sum()
print(f"untagged {pool.sum()/1e6:.1f}m across {len(pool)} cost centres")'''},
   "out": "untagged 22.0m across 9 cost centres   (6.0% of the target's cost base)"},

  {"title": "Build the usage matrix from measured consumption",
   "why": "An allocation is only defensible if the driver is something the business actually records. "
          "Tickets raised, payroll runs processed, documents keyed, square feet occupied. Headcount is the "
          "fallback, not the default — and a headcount proxy for every driver has a specific failure mode "
          "covered in the pitfalls below.",
   "code": {"python": '''# p[service][consumer] -- the share of each service's output that consumer takes
P = (usage.pivot(index="service", columns="consumer", values="units")
          .reindex(index=SERVICES).fillna(0.0))
P = P.div(P.sum(axis=1), axis=0)

NON_SERVICE = [c for c in P.columns if c not in SERVICES]

# how circular is this? the share of each pool consumed by the other pools
sigma = P[SERVICES].sum(axis=1)
print(sigma.round(3).to_string())''',
   },
   "out": "SH-FAC   0.018\nSH-FIN   0.051\nSH-HR    0.118\nSH-IT    0.481      <- IT is half-consumed by the other functions\nSH-PROC  0.058"},

  {"title": "Solve the circularity",
   "why": "IT runs the finance and payroll systems; HR runs payroll for IT. Each pool's true cost is its own "
          "spend plus what it receives from the others, which is circular — a linear system, not a sequence. "
          "One matrix inversion settles it.",
   "code": {"python": '''def allocate_reciprocal(P, D, SERVICES, NON_SERVICE):
    """
        T = D + M T        M[i][j] = share of service j consumed by i
          = (I - M)^-1 D

    Then push the grossed-up pools out to everything that is not a service.
    """
    M = P.loc[SERVICES, SERVICES].to_numpy().T          # M[i][j] = P[j][i]
    T = np.linalg.solve(np.eye(len(SERVICES)) - M, D.to_numpy())
    T = pd.Series(T, index=SERVICES)
    return P[NON_SERVICE].mul(T, axis=0).sum(axis=0), T

alloc, T = allocate_reciprocal(P, D_SERVICE, SERVICES, NON_SERVICE)

# the grossed-up pools are internal bookkeeping -- what leaves must equal what went in
assert abs(alloc.sum() - D_SERVICE.sum()) < 1.0''',
   },
   "out": "                own cost   grossed up   uplift\nFacilities        4.01m        4.49m     +12%\n"
          "Transactional Fin 2.86m        4.28m     +50%\nHR & Payroll      2.37m        2.96m     +25%\n"
          "IT & Digital      4.59m        4.94m      +8%\nProcurement       1.58m        1.88m     +19%",
   "note": "The grossed-up column does not add up to anything meaningful — summing it double-counts the "
           "transfers between services. Only the own-cost column is real money, and only the allocation out "
           "to the divisions has to reconcile."},

  {"title": "Test the method rather than assuming it",
   "why": "Direct, step-down and reciprocal will give different answers, and the size of that difference is "
          "itself a finding. Compute all three. “We used a simple allocation because the difference is "
          "immaterial” is only a defensible sentence after you have measured the difference.",
   "code": {"python": '''def allocate_direct(P, D, SERVICES, NON_SERVICE):
    """Ignore inter-service usage; renormalise over the rest. Quick and wrong."""
    Q = P[NON_SERVICE].div(P[NON_SERVICE].sum(axis=1), axis=0)
    return Q.mul(D, axis=0).sum(axis=0)

def allocate_stepdown(P, D, SERVICES, NON_SERVICE):
    """Largest pool first, never allocating back up the order."""
    remaining, out, closed = D.copy(), pd.Series(0.0, index=NON_SERVICE), []
    for s in remaining.sort_values(ascending=False).index:
        targets = [c for c in P.columns if c not in closed and c != s]
        spread = (P.loc[s, targets] / P.loc[s, targets].sum()) * remaining[s]
        for c in targets:
            if c in NON_SERVICE: out[c] += spread[c]
            else:                remaining[c] += spread[c]
        closed.append(s)
    return out

for name, fn in [("Direct", allocate_direct), ("Step-down", allocate_stepdown)]:
    a = fn(P, D_SERVICE, SERVICES, NON_SERVICE)
    assert abs(a.sum() - D_SERVICE.sum()) < 1.0, f"{name} does not conserve the pool"''',
   },
   "out": "allocation to the target        Direct 5.12m   Step-down 5.13m   Reciprocal 5.14m   (range 17k)\n"
          "allocation to Flow Control      Direct 6.25m   Step-down 6.62m   Reciprocal 6.60m   (range 372k)",
   "note": "Read that carefully. For the target the three methods agree to £17k — but per service they "
           "disagree by hundreds of thousands in opposite directions, and for a sister division the range is "
           "£372k. The near-cancellation is a property of this division's usage profile, not a general "
           "result, and you cannot know it without doing the calculation."},

  {"title": "Corporate has no driver, so disclose the basis",
   "why": "Nobody consumes a board. Corporate cost is spread on a basis, and the basis is a negotiating "
          "position rather than a fact. Compute the conventional ones and show them together — presenting "
          "a single basis hides a choice that is usually worth more than the entire allocation-method argument.",
   "code": {"python": '''# corporate, grossed up for the shared services it consumes
corp_total = D_CORP.sum() + alloc.reindex(CORPORATE).fillna(0).sum()

BASES = {
    "Revenue":                 PL.revenue,
    "Headcount":               PL.headcount,
    "Gross profit":            PL.gross_profit,
    "EBITDA before corporate": PL.ebitda_direct - service_alloc,
}
by_basis = pd.DataFrame({k: corp_total * (v / v.sum()) for k, v in BASES.items()})

for k in by_basis:
    assert abs(by_basis[k].sum() - corp_total) < 1.0, f"{k} does not spread completely"''',
   },
   "out": "Revenue                   2.30m   ->  EBITDA 20.07m\nHeadcount                 2.40m   ->  EBITDA 19.97m\n"
          "Gross profit              2.45m   ->  EBITDA 19.91m\nEBITDA before corporate   2.71m   ->  EBITDA 19.66m\n\n"
          "spread: 410k of EBITDA, decided by a choice"},

  {"title": "Eliminate and restate intercompany",
   "why": "Trading between divisions disappears on consolidation but does not disappear on carve-out — it "
          "becomes third-party trade, at third-party prices. Two separate questions: what is the margin "
          "effect of restating to arm's length, and how much revenue depends on counterparties who are under "
          "no obligation to keep buying.",
   "code": {"spark": '''ic = (gl.filter(F.col("account").isin("4100", "5300") & (F.col("division") == TARGET))
        .groupBy("account", "counterparty").agg(F.sum("amount").alias("amount"))
        .toPandas())

ic_sales = -ic.loc[ic.account == "4100", "amount"].sum()
ic_buys  =  ic.loc[ic.account == "5300", "amount"].sum()

ARM_ADJ = 0.062      # benchmarked: transfer prices sit this far above market
net = -ic_sales * ARM_ADJ + ic_buys * ARM_ADJ

print(f"intercompany revenue {ic_sales/1e6:.2f}m "
      f"({ic_sales/target_revenue:.1%} of the division)")
print(f"arm's length restatement {net/1e6:+.2f}m")''',
            "pandas": '''ic = gl[gl.account.isin(["4100", "5300"]) & gl.division.eq(TARGET)]

ic_sales = -ic.loc[ic.account.eq("4100"), "amount"].sum()
ic_buys  =  ic.loc[ic.account.eq("5300"), "amount"].sum()

ARM_ADJ = 0.062
net = -ic_sales * ARM_ADJ + ic_buys * ARM_ADJ'''},
   "out": "intercompany revenue 12.44m (8.6% of the division)\narm's length restatement -0.54m",
   "note": "The restatement is the smaller point. The bigger one is that 8.6% of revenue now depends on a "
           "supply agreement that does not yet exist. That belongs in the SPA with volume and term, or in "
           "the model as revenue at risk — not sitting quietly inside the base."},

  {"title": "Benchmark standalone cost; do not uplift the allocation",
   "why": "The allocated charge is what the group's functions cost spread across the whole group. Standalone, "
          "the division runs them on its own revenue, and some functions do not scale down at all. The "
          "tempting shortcut — take the allocation and add a percentage — assumes the allocation was right "
          "to begin with, which is the thing being tested.",
   "code": {"python": '''rows = []
for _, b in BENCH.iterrows():
    allocated = alloc_by_function.get(b.cost_centre, 0.0)
    lo = max(target_revenue * b.pct_lo, b.fixed_floor)
    hi = max(target_revenue * b.pct_hi, b.fixed_floor)
    rows.append(dict(function=b.function, allocated=allocated,
                     standalone=(lo + hi) / 2, gap=(lo + hi) / 2 - allocated))
standalone = pd.DataFrame(rows)

# the other side of the same coin: what stays behind in the group
standalone["stranded"] = standalone.allocated * (1 - BENCH.removable_pct.to_numpy())''',
   },
   "out": "standalone cost gap      1.86m   (a permanent cost of ownership)\n"
          "stranded in the group    4.15m   (56% of what was allocated to the division)",
   "note": "The fixed floor is what makes this work. A £145m business still needs a finance director, an "
           "audit and a board; those costs do not fall by two thirds because the revenue did."},

  {"title": "Drive the balance sheet off the segmented P&L",
   "why": "Direct from the sub-ledger wherever the sub-ledger carries a division, driven off the segmented "
          "P&L or a physical driver wherever it does not. Report the share that is direct alongside every "
          "line, because a buyer should price a directly-attributed receivable and an allocated accrual "
          "differently.",
   "code": {"python": '''cogs_share = PL.cogs / PL.cogs.sum()
rev_share  = PL.revenue / PL.revenue.sum()
area_share = PL.floor_area / PL.floor_area.sum()

def split(direct_by_div, untagged_total, driver, label, basis):
    d = direct_by_div.reindex(DIVS).fillna(0.0)
    a = untagged_total * driver.reindex(DIVS).fillna(0.0)
    total = d + a
    return dict(line=label, basis=basis, total=float(total[TARGET]),
                directness=float(d[TARGET] / total[TARGET]),
                by_div=dict(total))

BS = [
  split(ar[ar.division != ""].groupby("division").amount.sum(),
        ar[ar.division == ""].amount.sum(), rev_share,
        "Trade receivables", "Group-billed accounts on revenue"),
  split(inv[inv.division != ""].groupby("division").value.sum(),
        inv[inv.division == ""].value.sum(), cogs_share,
        "Inventory", "Central stores on cost of sales"),
  split(fa[fa.division != ""].groupby("division").nbv.sum(),
        fa[fa.division == ""].nbv.sum(), area_share,
        "Property, plant & equipment", "Shared-site assets on floor area"),
]

# cash and external debt do not carve out: the deal is cash-free debt-free''',
   },
   "out": "line                          total   direct\nTrade receivables            21.4m     92%\n"
          "Inventory                    18.3m     89%\nProperty, plant & equipment  10.9m     90%\n"
          "Trade payables               17.9m     94%\nAccruals & provisions         3.6m     96%\n\n"
          "net working capital 23.2m (16.0% of revenue)   DSO 60  DIO 86  DPO 71"},
 ],
 "pitfalls": [
  {"title": "An allocation that does not conserve the pool",
   "body": "The commonest silent error in the whole technique. Renormalising the wrong axis, dropping a "
           "consumer that had no usage, or a step-down that closes a service before its cost has been fully "
           "distributed — each quietly creates or destroys cost, and nothing in the output looks wrong. "
           "Assert that every method pushes out exactly what went in, for every method, every run."},
  {"title": "Reading account codes as numbers",
   "body": "Account codes look numeric and both pandas and Spark will infer int64. Every subsequent "
           "comparison against a string code then matches nothing, silently. In this build that turned the "
           "entire intercompany adjustment into a clean, plausible-looking zero — which is far more dangerous "
           "than an error, because nobody questions a zero."},
  {"title": "Uplifting the allocated charge to get standalone cost",
   "body": "Taking the allocation and adding 25% is quick and assumes the thing under test. Benchmark "
           "independently, as a percentage of the division's own revenue, with a floor for functions that "
           "cannot scale down. The two approaches give very different answers precisely when the allocation "
           "is wrong, which is when it matters."},
  {"title": "Presenting one corporate basis as though it were the answer",
   "body": "Revenue, headcount, gross profit and EBITDA-before-corporate produce EBITDA numbers "
           "£410k apart on this deal — more than the entire allocation-method question. Showing one basis "
           "without the others is not a simplification, it is taking a side in a negotiation without saying "
           "so. Fix the basis in the SPA rather than discovering it in completion accounts."},
 ],
 "validate": {
  "intro": "Four assertions, and they gate the build rather than decorating it. A carve-out whose numbers do "
           "not add up is worse than no carve-out, because it goes into a data room.",
  "why": "Conservation catches the allocation errors, the bridge catches an adjustment applied twice or with "
         "the wrong sign, and the balance sheet check catches a sub-ledger split that lost rows to nulls — "
         "which is easy to do and almost impossible to see.",
  "code": {"python": '''TOL = 50.0      # pounds, against a group of ~440m

def check():
    # 1. every method pushes out exactly what went in
    for name, a in METHODS.items():
        assert abs(a.sum() - D_SERVICE.sum()) < TOL, f"{name} does not conserve the pool"

    # 2. divisions plus corporate absorb the whole service pool
    assert abs(service_by_div.sum() + corp_from_service - D_SERVICE.sum()) < TOL

    # 3. corporate spreads completely, on every basis
    for k in by_basis:
        assert abs(by_basis[k].sum() - corp_total) < TOL, f"basis {k} does not sum"

    # 4. the carve-out bridge ties, and every balance sheet line foots to group
    assert abs(residual) < 1.0, f"bridge off by {residual:,.2f}"
    for b in BS:
        assert abs(sum(b["by_div"].values()) - b["group"]) < TOL, f"{b['line']} does not foot"

    print("checks: allocations conserve the pool, bridge ties, balance sheet foots")''',
   },
  "out": "checks: allocations conserve the pool, bridge ties, balance sheet foots"},
 "scale": {
  "body": "The ledger is the only large object and it is properly large: a mid-market group posts millions "
          "of journal lines a year and a listed group considerably more. Filtering, joining the cost-centre "
          "master and aggregating to division-by-line belongs in Spark. Everything after that is tiny — the "
          "reciprocal allocation is a five-by-five matrix inversion, the corporate bases are four vectors of "
          "length three, and the whole model runs in milliseconds in NumPy. The engineering effort goes into "
          "the data, not the mathematics, and it is worth knowing that before anyone proposes building the "
          "allocation engine in Spark.",
  "notes": [
   "<strong>Read account and cost centre as strings</strong> on every load. It is one dtype argument and it prevents the worst class of silent failure in this technique.",
   "<strong>Broadcast the cost centre master.</strong> Tens of rows joined to millions; without the hint Spark plans a shuffle.",
   "<strong>Snapshot the extract with its date</strong> and keep it. A carve-out is negotiated over months and the ledger keeps moving; an analysis you cannot reproduce against the version the other side is holding is worthless.",
   "<strong>Keep the allocation bases in a config, not in code.</strong> They will be renegotiated, and the difference between rerunning a model and editing a script is the difference between an afternoon and a week.",
   "<strong>Carry the directness percentage all the way to the output.</strong> It is the single most useful credibility signal in the pack, and it costs nothing to compute once the split function returns it.",
  ]},
 "foot_title": "Technique 15 — Balance Sheet Carve-Out.",
 "foot_body": "Tutorial companion to the Project Kiln demo. All figures synthetic.",
}

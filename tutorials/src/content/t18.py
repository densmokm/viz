TUTORIAL = {
 "brand": "Synergy Tracking",
 "tag": "Technique 18",
 "phase": "Post-deal value creation",
 "title": "How to build a synergy tracker a board can act on",
 "subtitle": "Risk-adjusted realisation against the deal model, with conversion rates fitted on prior "
             "integrations — and the one calculation that tells you whether the target is reachable at all.",
 "demo_url": "https://claude.ai/code/artifact/b18eee14-aa3a-497e-8b8c-7c07101062a8",
 "grain": "one row per initiative",
 "meta": [["Engine", "Spark to assemble, NumPy to forecast"],
          ["Input", "Initiative register, GL, deal model"],
          ["Runtime", "Seconds once the register is clean"],
          ["Output", "A forecast, a distribution and a ceiling"]],
 "intro": "Most synergy trackers report one completion percentage against plan. That number averages a cost "
          "programme that is working with a revenue programme that is not, and the blend looks survivable "
          "until month eighteen. This one separates them, weights every initiative by what history says "
          "converts, and reports the thing a PMO almost never puts in front of a board: whether the deal "
          "model can still be reached.",
 "input_intro": "Two tables and a schedule. The field that gets forgotten is the date an initiative entered "
                "its current stage — without it you cannot detect a stall, which is the earliest warning "
                "available and the whole reason for doing this monthly.",
 "inputs": [
   ["initiative_id", "string", "Stable across reporting cycles. Initiatives get renamed constantly; the id must not move."],
   ["workstream, type", "string", "Cost or revenue. <strong>Never report a blended figure across the two</strong> — they behave completely differently."],
   ["plan_runrate", "decimal", "The committed annualised value from the deal model."],
   ["current_estimate", "decimal", "The owner’s number today. Divergence from plan is a bridge line in its own right."],
   ["stage", "string", "Identified / Validated / In execution / Delivered / Banked."],
   ["stage_entered_at", "date", "<strong>The most commonly missing field.</strong> Days in stage against the historical distribution is how you detect a stall."],
   ["delivered_month", "int", "Months since completion. Drives the run-rate to in-year P&L conversion."],
   ["cta_budget, cta_spent", "decimal", "Cost to achieve. Underspend on a revenue workstream is a signal, not a saving."],
   ["prior_outcomes", "table", "Initiatives from past integrations with what each was finally worth. Without it, confidence weighting is opinion."],
 ],
 "walk_intro": "Seven steps. None of the data is large — a register is hundreds of rows — so the engineering "
               "is in the GL join and the definitions, not in the compute. Spark appears once, where it "
               "belongs: attributing actual ledger movements to initiatives.",
 "steps": [
  {"title": "Attribute the ledger to initiatives",
   "why": "The register says what was planned. The general ledger says what happened. Joining them is the "
          "unglamorous step that decides whether the tracker is believed — a synergy number that cannot be "
          "traced to a cost centre and a period is a number the CFO will not sign.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.appName("anvil-synergy").getOrCreate()

gl  = spark.read.parquet("s3://anvil/gl/")           # posted actuals, all entities
tag = spark.read.parquet("s3://anvil/synergy_tags/")  # cost centre + account -> initiative

benefit = (gl.join(F.broadcast(tag), ["cost_centre", "account"])
   .filter(F.col("period") >= F.lit(COMPLETION))
   .withColumn("month", F.months_between("period", F.lit(COMPLETION)).cast("int"))
   .groupBy("initiative_id", "month")
   .agg(F.sum(F.col("amount") * F.col("sign")).alias("in_year_benefit")))

# Anything tagged but not in the register, or vice versa, is a reconciliation break
orphans = benefit.join(register, "initiative_id", "left_anti").count()
assert orphans == 0, f"{orphans} tagged initiatives missing from the register"''',
            "pandas": '''gl  = pd.read_parquet("gl.parquet")
tag = pd.read_parquet("synergy_tags.parquet")

benefit = (gl.merge(tag, on=["cost_centre", "account"])
             .query("period >= @COMPLETION")
             .assign(month=lambda d: ((d.period.dt.year - COMPLETION.year) * 12
                                      + d.period.dt.month - COMPLETION.month),
                     value=lambda d: d.amount * d.sign)
             .groupby(["initiative_id", "month"], as_index=False)
             .value.sum().rename(columns={"value": "in_year_benefit"}))

orphans = set(benefit.initiative_id) - set(register.initiative_id)
assert not orphans, f"{len(orphans)} tagged initiatives missing from the register"'''},
   "note": "Where a benefit cannot be tagged to a cost centre — most revenue synergies — it has to be "
           "evidenced some other way, usually a signed contract with a named cross-sell origin. Say which "
           "method each initiative uses in the register; a board that cannot tell the difference between a "
           "ledger-traced saving and an attested one will eventually discover it the hard way."},

  {"title": "Separate run-rate from in-year P&L",
   "why": "The distinction most trackers collapse, and the one that causes the most damage. An initiative "
          "delivered in month twelve carries its full annualised value into the run-rate and almost none of "
          "it into this year’s EBITDA. Report both, always, and state the gap explicitly.",
   "code": {"python": '''RAMP = [0.5, 0.78, 1.0]      # benefit builds over the first quarter after go-live

def monthly_benefit(realised_runrate, delivered_month, today):
    """One twelfth of run-rate, ramped, from go-live onward."""
    rows = []
    for m in range(delivered_month, today + 1):
        k = m - delivered_month
        f = RAMP[k] if k < len(RAMP) else 1.0
        rows.append((m, realised_runrate / 12 * f, realised_runrate * f))
    return rows        # (month, in_year_benefit, runrate_recognised)

runrate_now = mon.loc[mon.month == TODAY, "runrate_recognised"].sum()
ltm_pl      = mon.loc[mon.month > TODAY - 12, "in_year_benefit"].sum()

print(f"run-rate {runrate_now/1e6:.2f}m   reached P&L {ltm_pl/1e6:.2f}m "
      f"({ltm_pl/runrate_now:.0%})")''',
   },
   "out": "run-rate 10.36m   reached P&L 6.17m (60%)",
   "note": "Sixty percent is not a failure — it is arithmetic, and it is what a phased programme looks like. "
           "The failure is reporting the 10.36 as though it were EBITDA, which is how a board approves a "
           "bonus against money that has not arrived."},

  {"title": "Estimate conversion from prior deals",
   "why": "A PMO’s own confidence rating is the least reliable number in a synergy tracker: it is set by "
          "the person accountable for the initiative. Replace it with an empirical rate — how often did an "
          "initiative at this stage, of this type, actually deliver on past integrations — and smooth thin "
          "cells toward the overall rate so a category with four observations does not swing the forecast.",
   "code": {"python": '''ALPHA = 4.0                          # smoothing strength
PRIOR = float(HIST.delivered.mean())  # overall conversion across all prior initiatives

CONV = {}
for stage in ["Identified", "Validated", "In execution"]:
    for typ in ["Cost", "Revenue"]:
        g = HIST[(HIST.stage == stage) & (HIST.type == typ)]
        CONV[(stage, typ)] = (g.delivered.sum() + ALPHA * PRIOR) / (len(g) + ALPHA)

# Delivered and banked are excluded: they are already counted at realised value,
# and quoting a conversion rate for money in the P&L invites an obvious question.''',
   },
   "out": "                Cost   Revenue    n\n"
          "Identified       30%      26%    51\nValidated        60%      37%    82\n"
          "In execution     84%      67%    51",
   "note": "Revenue converts materially worse from every open stage. That single table is the analytical "
           "justification for governing the two programmes differently, and it is far more persuasive than "
           "asserting the same thing from experience."},

  {"title": "Fit the realisation distribution, do not pick a haircut",
   "why": "Initiatives that do deliver rarely deliver exactly their estimate. Rather than applying a flat "
          "haircut, fit a distribution to what prior initiatives actually landed at and draw from it. "
          "Method of moments on a gamma is enough — two lines, and it gives the forecast a spread instead "
          "of a point.",
   "code": {"python": '''d = HIST.loc[HIST.delivered == 1, "realisation"]
MU, SD = d.mean(), d.std(ddof=1)

# Gamma matched on the first two moments
G_SHAPE = (MU / SD) ** 2
G_SCALE = SD ** 2 / MU

print(f"realisation {MU:.0%} of estimate, sd {SD:.0%} "
      f"-> gamma(shape={G_SHAPE:.1f}, scale={G_SCALE:.3f})")''',
   },
   "out": "realisation 89% of estimate, sd 22% -> gamma(shape=16.4, scale=0.054)",
   "note": "Gamma rather than normal because realisation is strictly positive and right-skewed — the "
           "occasional initiative that lands at 140% of estimate is real, and a normal would put mass below "
           "zero."},

  {"title": "Build the bridge, and make it tie",
   "why": "Four things sit between the number in the deal model and the number that reaches EBITDA. Name "
          "them separately, because they call for completely different responses: re-estimation is a scope "
          "conversation, conversion risk is an execution one, realisation is a planning-assumption one, and "
          "dis-synergy belongs to whoever built the model.",
   "code": {"python": '''done = reg.stage.isin(["Delivered", "Banked"])
und  = reg[~done]

reg["p_convert"] = np.where(done, 1.0,
                            [CONV[(s, t)] for s, t in zip(reg.stage, reg.type)])
reg["expected"]  = np.where(done, reg.realised_runrate,
                            reg.current_estimate * reg.p_convert * MU)

loss_conv = (und.current_estimate * (1 - und.p_convert)).sum()
loss_real = ((und.current_estimate * und.p_convert * (1 - MU)).sum()
             + (reg[done].current_estimate - reg[done].realised_runrate).sum())

bridge = [
    ("Deal model",             DEAL_MODEL,                        "total"),
    ("Re-estimation",          reg.current_estimate.sum() - DEAL_MODEL, "delta"),
    ("Conversion risk",        -loss_conv,                        "delta"),
    ("Realisation haircut",    -loss_real,                        "delta"),
    ("Dis-synergy",            dis_total,                         "delta"),
    ("Risk-adjusted forecast", reg.expected.sum() + dis_total,    "total"),
]''',
   },
   "out": "Deal model              24.50m\nRe-estimation            +0.20m\nConversion risk          -5.40m\n"
          "Realisation haircut      -2.87m\nDis-synergy              -2.63m\n"
          "                       --------\nRisk-adjusted forecast   13.80m"},

  {"title": "Simulate the register, and compute the ceiling",
   "why": "The point estimate is one number; the board needs to know how likely it is. Twenty thousand "
          "draws over the register gives the distribution. Then compute the ceiling — every remaining "
          "initiative converting at full value — because if the deal model sits above that line, being "
          "behind is not the problem.",
   "code": {"python": '''rng = np.random.default_rng(7)
N = 20_000

est = und.current_estimate.to_numpy()
p   = und.p_convert.to_numpy()

converts = rng.random((N, len(est))) < p
lands    = rng.gamma(G_SHAPE, G_SCALE, (N, len(est)))
sim      = (converts * lands * est).sum(axis=1) + secured + dis_total

# The ceiling: perfect conversion, full estimate, no haircut at all
ceiling = secured + est.sum() + dis_total

print(f"P50 {np.median(sim)/1e6:.1f}m  P10-P90 {np.percentile(sim,10)/1e6:.1f}"
      f"-{np.percentile(sim,90)/1e6:.1f}m  P(hit model) {(sim >= DEAL_MODEL).mean():.1%}")
print(f"ceiling {ceiling/1e6:.2f}m -> model is "
      f"{'reachable' if ceiling >= DEAL_MODEL else 'UNREACHABLE'} from this pipeline")''',
   },
   "out": "P50 13.8m  P10-P90 12.3-15.3m  P(hit model) 0.0%\n"
          "ceiling 19.92m -> model is UNREACHABLE from this pipeline",
   "note": "A zero probability looks like a broken model and is not. With 46 largely independent "
           "initiatives the aggregate is tightly distributed, so the honest reading is that this is a "
           "shortfall rather than a variance that might come good. Reporting the ceiling alongside it is "
           "what turns that from a gloomy number into an actionable one: roughly £12m of run-rate has to "
           "come from initiatives that do not yet exist."},

  {"title": "Time-phase the earned value",
   "why": "Schedule performance needs a planned value that moves continuously. Stepping it at the planned "
          "delivery month makes the index explode for any workstream whose work is scheduled late — an "
          "earlier build of this analysis produced an SPI of 3.15, which meant nothing at all. Ramp planned "
          "progress across a typical delivery window instead.",
   "code": {"python": '''LEAD = 6.0        # months from mobilisation to delivery for a typical initiative
CREDIT = {"Identified": 0.0, "Validated": 0.25, "In execution": 0.60,
          "Delivered": 0.90, "Banked": 1.0}

def planned_progress(planned_month):
    return float(np.clip((TODAY - (planned_month - LEAD)) / LEAD, 0.0, 1.0))

reg["planned_progress"] = reg.planned_month.map(planned_progress)
reg["credit"] = reg.stage.map(CREDIT)

for ws, g in reg.groupby("workstream"):
    pv = (g.plan_runrate * g.planned_progress).sum()   # planned value to date
    ev = (g.plan_runrate * g.credit).sum()             # earned value, same value base
    print(f"{ws:<24} SPI {ev / pv:.2f}")''',
   },
   "out": "Procurement              SPI 0.99\nOrganisation design      SPI 0.91\n"
          "IT & systems             SPI 0.64\nCross-sell               SPI 0.47\n"
          "Geographic expansion     SPI 0.36",
   "note": "Earned value uses <code>plan_runrate</code>, not <code>current_estimate</code>, so the index "
           "measures schedule alone. Scope change is already a separate line in the bridge; letting it into "
           "the SPI as well double-counts it and makes a workstream that has quietly inflated its estimates "
           "look like it is ahead."},
 ],
 "pitfalls": [
  {"title": "Reporting run-rate as though it were EBITDA",
   "body": "The most expensive error in this technique. £10.4m of recognised run-rate had delivered £6.2m to "
           "the last twelve months of P&L. Both numbers are correct and they answer different questions. "
           "Put them side by side on every page, every month, and name the gap — the alternative is a board "
           "approving against money that has not arrived."},
  {"title": "Blending cost and revenue into one percentage",
   "body": "A programme at 88% on cost and 36% on revenue reports as roughly 70% complete, which sounds "
           "recoverable and is not. The two convert at materially different rates from every stage and "
           "need different governance. Any number that averages them is hiding the only fact worth acting on."},
  {"title": "Stepping the planned value at the delivery month",
   "body": "Planned value that jumps from zero to full on the planned month makes SPI meaningless for any "
           "workstream scheduled late — this analysis produced an SPI of 3.15 before the fix. Time-phase it "
           "across a delivery window, and hold earned value to the same value base as planned value."},
  {"title": "Quoting a conversion rate for banked initiatives",
   "body": "An early version of the conversion table showed Banked at 64% for revenue, because the "
           "cost-versus-revenue penalty had been applied at every stage. Money already in the P&L converts "
           "at 100% by definition. Exclude delivered and banked from the table entirely — they are counted "
           "at realised value and their conversion rate plays no part in the forecast."},
 ],
 "validate": {
  "intro": "A synergy tracker whose numbers do not add up is worse than no tracker, because it gets "
           "presented to a board. Assert the reconciliations in the run.",
  "why": "Four checks: the bridge ties, both breakdowns foot to the total they claim to explain, and the "
         "simulation agrees with the analytic point estimate — that last one catches a mismatch between the "
         "expectation used in the bridge and the distribution used in the forecast, which is easy to "
         "introduce and almost impossible to spot by eye.",
  "code": {"python": '''TOL = 1.0        # pounds

def check():
    deltas = sum(v for _, v, kind in bridge if kind == "delta")
    residual = DEAL_MODEL + deltas - net_forecast
    assert abs(residual) < TOL, f"bridge does not tie: {residual:,.2f}"

    assert abs(sum(w["expected"] for w in WS) - expected) < TOL, "workstreams do not foot"
    assert abs(sum(t["expected"] for t in BY_TYPE) - expected) < TOL, "type split does not foot"

    # the simulation and the point estimate must be telling the same story
    assert abs(np.median(sim) - net_forecast) / net_forecast < 0.15, (
        "simulation median has drifted from the analytic expectation")

    print("checks: bridge ties, splits reconcile, simulation agrees")''',
   },
  "out": "checks: bridge ties, splits reconcile, simulation agrees"},
 "scale": {
  "body": "Almost nothing here is large. A register is hundreds of rows and the historical library a few "
          "hundred more; the model, the simulation and the bridge all run in NumPy in well under a second. "
          "The one place Spark belongs is the general ledger join — attributing posted actuals to "
          "initiatives across every entity and period since completion, which on a mid-market group is tens "
          "of millions of journal lines and on a large one considerably more. Do that in Spark, write the "
          "initiative-month benefit table, and run everything else on the result.",
  "notes": [
   "<strong>Snapshot the register every month and keep the history.</strong> The most valuable output of this technique is not this month’s forecast — it is the library of outcomes that makes next deal’s forecast credible.",
   "<strong>Version the deal model separately from the register.</strong> When the model is restated mid-programme, the bridge needs both the original and the restated number or the re-estimation line becomes meaningless.",
   "<strong>Broadcast the tag table</strong> in the GL join; it is small and the ledger is not.",
   "<strong>Keep dis-synergies in the same register</strong> with a negative sign and a type, rather than in a side spreadsheet. Anything held outside the model gets forgotten at exactly the point it matters.",
   "<strong>Recompute conversion rates each cycle</strong> as the library grows, and log which version of the rates produced each forecast so a change in the outlook can be attributed to the programme rather than to the model.",
  ]},
 "foot_title": "Technique 18 — Synergy Tracking.",
 "foot_body": "Tutorial companion to the Project Anvil demo. All figures synthetic.",
}

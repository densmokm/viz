TUTORIAL = {
 "brand": "Revenue Decomposition",
 "tag": "Technique 09",
 "phase": "Financial due diligence",
 "title": "How to build a revenue bridge that ties",
 "subtitle": "Decomposing a revenue movement into price, volume, mix, customer flows, one-offs and FX "
             "from an invoice-line extract — with an identity that holds exactly, so there is no residual to explain.",
 "demo_url": "https://claude.ai/code/artifact/230bde63-86eb-44b4-a8fa-d86185f0a70f",
 "grain": "one row per invoice line",
 "meta": [["Engine", "PySpark for the grain reduction, pandas for the maths"],
          ["Input", "Sales day-book or ERP invoice lines"],
          ["Runtime", "Minutes on 50m lines"],
          ["Output", "A bridge with a zero residual"]],
 "intro": "A revenue bridge that explains where a year's growth came from — and, more usefully, how much of "
          "it will still be there next year. The whole technique rests on one arithmetic identity, and the "
          "discipline is refusing to ship anything that does not satisfy it. A bridge with a residual is a "
          "bridge you will spend the management meeting defending instead of using.",
 "input_intro": "Everything below comes from one table. On a live deal this is a sales day-book extract or an "
                "ERP invoice-line dump — usually a single overnight request, and the one dataset worth "
                "escalating for if it does not arrive.",
 "inputs": [
   ["invoice_id, line_no", "string, int", "Together they define the grain. Check this before anything else."],
   ["date", "date", "Drives the fiscal-year split. Use the posting date, not the document date."],
   ["customer_id", "string", "The customer lens needs a stable key across both years — watch for account renumbering after an ERP migration."],
   ["sku", "string", "The price/volume/mix grain. A SKU master change mid-period will wreck the comparison."],
   ["quantity", "decimal", "<strong>Without quantity you cannot separate price from volume</strong>, and that separation is the entire technique."],
   ["revenue_local", "decimal", "Net of discounts and credits. Confirm whether credit notes are in this table or a separate one."],
   ["currency, fx_rate", "string, decimal", "Needed to hold the comparison at constant currency and report FX as its own line."],
   ["order_type", "string", "Standard / project / contract. Isolates one-off work so it can be quantified rather than argued about."],
 ],
 "walk_intro": "Eight steps. The first three run in Spark against the full extract; from step four the frame "
               "is one row per SKU and everything is small-data work in pandas. Knowing where that boundary "
               "sits is most of the engineering.",
 "steps": [
  {"title": "Land the extract and check the grain",
   "why": "Before any analysis, prove the table is what you were told it is. Duplicated lines from a badly "
          "joined extract are the single most common cause of a bridge that will not tie, and they are "
          "invisible in a total — the totals still look plausible, they are just wrong.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.appName("revenue-bridge").getOrCreate()

FY_START = "2024-04-01"          # FY25 opens; anything before is FY24

tx = (spark.read.parquet("s3://project-meridian/daybook/")
        .withColumn("fiscal_year",
                    F.when(F.col("date") >= F.lit(FY_START), F.lit("FY25"))
                     .otherwise(F.lit("FY24"))))

# The grain check that saves you a week. If this fires, stop and fix the extract.
dupes = tx.groupBy("invoice_id", "line_no").count().filter("count > 1").count()
assert dupes == 0, f"{dupes:,} duplicated invoice lines in the extract"

# Nulls in any of these silently drop rows from one side of the bridge
for c in ("customer_id", "sku", "quantity", "revenue_local"):
    n = tx.filter(F.col(c).isNull()).count()
    assert n == 0, f"{n:,} null {c}"''',
            "pandas": '''import pandas as pd

FY_START = pd.Timestamp("2024-04-01")

tx = pd.read_parquet("daybook.parquet")
tx["fiscal_year"] = np.where(tx.date >= FY_START, "FY25", "FY24")

dupes = tx.duplicated(subset=["invoice_id", "line_no"]).sum()
assert dupes == 0, f"{dupes:,} duplicated invoice lines in the extract"

for c in ("customer_id", "sku", "quantity", "revenue_local"):
    assert tx[c].notna().all(), f"nulls in {c}"'''},
   "note": "Also reconcile the extract total to the filed or management accounts before you go further. "
           "A day-book that is 3% light because intercompany was excluded is a conversation to have on day "
           "one, not in the draft report."},

  {"title": "Hold the comparison at constant currency",
   "why": "If you do not isolate FX first, it smears into price and you will spend a week arguing about "
          "which is which. Restate every line at one reference rate — the prior-year average — and carry "
          "the difference between actual and constant currency as a single reconciling line at the end.",
   "code": {"spark": '''FX_REF = 0.86204     # FY24 average GBP per EUR: the rate the comparison is held at

tx = tx.withColumn(
    "revenue_cc",
    F.when(F.col("currency") == "GBP", F.col("revenue_local"))
     .otherwise(F.col("revenue_local") * F.lit(FX_REF)))

# FX becomes one line in the bridge: the difference between the two movements
totals = (tx.groupBy("fiscal_year")
            .agg(F.sum("revenue_gbp").alias("actual"),
                 F.sum("revenue_cc").alias("cc"))
            .toPandas().set_index("fiscal_year"))

delta_actual = totals.loc["FY25", "actual"] - totals.loc["FY24", "actual"]
delta_cc     = totals.loc["FY25", "cc"]     - totals.loc["FY24", "cc"]
fx_effect    = delta_actual - delta_cc''',
            "pandas": '''FX_REF = 0.86204

tx["revenue_cc"] = np.where(tx.currency.eq("GBP"),
                            tx.revenue_local,
                            tx.revenue_local * FX_REF)

totals = tx.groupby("fiscal_year")[["revenue_gbp", "revenue_cc"]].sum()
delta_actual = totals.revenue_gbp.diff().iloc[-1]
delta_cc     = totals.revenue_cc.diff().iloc[-1]
fx_effect    = delta_actual - delta_cc'''},
   "out": "fx_effect = +382,104   # translation only, no trading effect"},

  {"title": "Collapse to the analysis grain — and stop using Spark",
   "why": "This is the step that matters for performance and the one people get wrong in the other "
          "direction. Fifty million invoice lines collapse to a few tens of thousands of SKU rows. Do that "
          "reduction in Spark, then bring the result back and do every subsequent step in pandas. Running "
          "the statistics in Spark buys you nothing and costs you clarity.",
   "code": {"spark": '''# Standard lines only -- one-off project work is carved out separately in step 8
grain = (tx.filter(F.col("order_type") == "Standard")
           .groupBy("sku")
           .pivot("fiscal_year", ["FY24", "FY25"])
           .agg(F.sum("quantity").alias("q"), F.sum("revenue_cc").alias("r"))
           .na.fill(0.0))

# grain columns: sku, FY24_q, FY24_r, FY25_q, FY25_r
print(f"{tx.count():,} lines -> {grain.count():,} SKU rows")

g = grain.toPandas().set_index("sku")     # from here on it is small data''',
            "pandas": '''std = tx[tx.order_type.eq("Standard")]

g = (std.pivot_table(index="sku", columns="fiscal_year",
                     values=["quantity", "revenue_cc"], aggfunc="sum")
        .fillna(0.0))
g.columns = [f"{fy}_{'q' if v == 'quantity' else 'r'}" for v, fy in g.columns]

print(f"{len(std):,} lines -> {len(g):,} SKU rows")'''},
   "out": "51,284,117 lines -> 64 SKU rows",
   "note": "Pivoting with two aggregates gives Spark column names of the form <code>FY24_q</code>, "
           "<code>FY24_r</code>. Name them explicitly rather than relying on the ordering if you are "
           "pinning this into a pack that runs unattended."},

  {"title": "The price / volume / mix identity",
   "why": "Three components, defined so they sum to the movement exactly. Volume is the change in units "
          "valued at last year's average price. Price is the per-SKU price change at this year's volumes. "
          "Mix is what shifting the basket did, valued at last year's prices. There is no fourth term and "
          "no residual — if you find yourself adding one, the definitions are wrong.",
   "code": {"numpy": '''import numpy as np

q0, q1 = g.FY24_q.to_numpy(), g.FY25_q.to_numpy()
r0, r1 = g.FY24_r.to_numpy(), g.FY25_r.to_numpy()

Q0, Q1 = q0.sum(), q1.sum()
R0, R1 = r0.sum(), r1.sum()
p0_bar = R0 / Q0                       # prior-year average price across the whole book

# Per-SKU prices. SKUs absent last year fall back to the book average -- see step 5.
p0 = np.divide(r0, q0, out=np.full_like(r0, p0_bar), where=q0 > 0)
p1 = np.divide(r1, q1, out=np.zeros_like(r1),        where=q1 > 0)

volume = (Q1 - Q0) * p0_bar
price  = (q1 * (p1 - p0)).sum()
mix    = (q1 * p0).sum() - Q1 * p0_bar

assert abs((volume + price + mix) - (R1 - R0)) < 1e-6'''},
   "out": "volume  -32,411\nprice  +4,752,908\nmix      -813,204\n           ---------\n         +3,907,293   == R1 - R0"},

  {"title": "Why the identity survives a moving catalogue",
   "why": "Real ranges churn. SKUs launch, get discontinued, get renumbered. The identity holds for <em>any</em> "
          "choice of prior-year price on a SKU that did not trade last year, which is what makes it safe — "
          "and worth being able to prove on a whiteboard when someone challenges it.",
   "code": {"python": '''# Expand the three definitions and everything cancels except R1 - R0:
#
#   price  + volume            + mix
# = sum q1(p1-p0) + (Q1-Q0)p0_bar + sum q1*p0 - Q1*p0_bar
# = sum q1*p1 - sum q1*p0 + Q1*p0_bar - R0 + sum q1*p0 - Q1*p0_bar
# = sum q1*p1 - R0
# = R1 - R0
#
# Note that p0 appears twice with opposite signs, so whatever you choose for a
# SKU with q0 == 0 cancels. The book average is the conventional choice: it puts
# a genuinely new SKU's whole movement into volume and price, and none into mix.

new_skus = g.index[(g.FY24_q == 0) & (g.FY25_q > 0)]
dead_skus = g.index[(g.FY24_q > 0) & (g.FY25_q == 0)]
print(f"{len(new_skus)} new, {len(dead_skus)} discontinued -- identity unaffected")'''},
   "note": "The one thing that does break it is dropping those rows. A <code>dropna()</code> or an inner "
           "join in step 3 will silently remove them and your bridge will miss by exactly their revenue."},

  {"title": "The customer lens: the same movement, partitioned by account",
   "why": "Price, volume and mix explain the commercial story. They say nothing about whether the customer "
          "base is growing or leaking. Partition the identical movement a second way — accounts that left, "
          "arrived, grew and shrank — and you have two independent readings that must agree on the total.",
   "code": {"spark": '''cust = (tx.groupBy("customer_id")
            .pivot("fiscal_year", ["FY24", "FY25"])
            .agg(F.sum("revenue_cc").alias("r"))
            .na.fill(0.0)
            .toPandas())

r0c, r1c = cust.FY24_r.to_numpy(), cust.FY25_r.to_numpy()
was, now = r0c > 0, r1c > 0

lost        = -r0c[was & ~now].sum()
new         =  r1c[~was & now].sum()
d           = (r1c - r0c)[was & now]
expansion   =  d[d > 0].sum()
contraction =  d[d < 0].sum()

assert abs(lost + new + expansion + contraction - (r1c.sum() - r0c.sum())) < 1e-6''',
            "pandas": '''cust = (tx.pivot_table(index="customer_id", columns="fiscal_year",
                       values="revenue_cc", aggfunc="sum")
          .reindex(columns=["FY24", "FY25"]).fillna(0.0))

was, now = cust.FY24 > 0, cust.FY25 > 0
d = (cust.FY25 - cust.FY24)[was & now]

lost        = -cust.FY24[was & ~now].sum()
new         =  cust.FY25[~was & now].sum()
expansion   =  d[d > 0].sum()
contraction =  d[d < 0].sum()'''},
   "note": "Use the revenue test (<code>&gt; 0</code>), not a customer-master status flag. Accounts get "
           "marked inactive months after they stop buying, and a flag will put churn in the wrong year."},

  {"title": "Nest the two lenses into one bridge",
   "why": "Two bridges that tie to the same number are good. One bridge that carries both readings is "
          "better, because it stops the meeting turning into an argument about which view is right. "
          "Decompose the <em>retained</em> book into price, volume and mix; carry accounts that arrived or "
          "left whole; and keep FX as a single translation line.",
   "code": {"python": '''retained = cust.index[(cust.FY24 > 0) & (cust.FY25 > 0)]

# Re-run step 3 and step 4 restricted to retained customers, standard lines only
ret = tx[tx.customer_id.isin(retained) & tx.order_type.eq("Standard")]
volume_r, price_r, mix_r = pvm(collapse_to_sku(ret))     # the step 3 + 4 functions

bridge = [
    ("FY24 revenue",     R0_actual,  "total"),
    ("Volume (organic)", volume_r,   "delta"),
    ("Price",            price_r,    "delta"),
    ("Mix",              mix_r,      "delta"),
    ("One-off project",  project_d,  "delta"),   # step 8
    ("New customers",    new,        "delta"),
    ("Lost customers",   lost,       "delta"),
    ("FX translation",   fx_effect,  "delta"),
    ("FY25 revenue",     R1_actual,  "total"),
]'''},
   "note": "Expansion and contraction do not appear as separate lines here — they are <em>decomposed</em> "
           "into the retained book's price, volume and mix. That is the point of nesting: expansion of "
           "£9.3m that turns out to be £3.4m of price and £2.9m of a single contract is a very different "
           "fact from £9.3m of customers buying more."},

  {"title": "Carve out the one-off work",
   "why": "Lumpy contract revenue hides inside Volume and flatters it. Compute the identity on standard "
          "lines only, then carry the movement in project revenue as its own bridge line. The arithmetic "
          "stays exact because the two subsets partition the retained book.",
   "code": {"spark": '''ret_ids = spark.createDataFrame([(c,) for c in retained], ["customer_id"])

proj = (tx.join(F.broadcast(ret_ids), "customer_id")
          .filter(F.col("order_type") == "Project")
          .groupBy("fiscal_year").agg(F.sum("revenue_cc").alias("r"))
          .toPandas().set_index("fiscal_year").r)

project_d = proj.get("FY25", 0.0) - proj.get("FY24", 0.0)

# Retained delta = standard-line PVM + project movement, exactly
assert abs((volume_r + price_r + mix_r + project_d) - retained_delta) < 1.0''',
            "pandas": '''proj = (tx[tx.customer_id.isin(retained) & tx.order_type.eq("Project")]
          .groupby("fiscal_year").revenue_cc.sum())

project_d = proj.get("FY25", 0.0) - proj.get("FY24", 0.0)

assert abs((volume_r + price_r + mix_r + project_d) - retained_delta) < 1.0'''},
   "note": "If the source has no order-type flag, ask for one before you model anything. Reconstructing it "
           "from order value or customer name is guesswork, and the number it produces will be the most "
           "contested figure in the report."},
 ],
 "pitfalls": [
  {"title": "Per-group mix measured against the book average price",
   "body": "Splitting mix by product family using the book-wide average price is arithmetically correct and "
           "completely unreadable. In this analysis it showed Marine &amp; Offshore contributing "
           "<strong>+£3.9m of mix on flat revenue</strong>, purely because its average price sits above the "
           "book average. Re-cut each group's volume at <em>its own</em> prior price, report the unit-share "
           "shift separately, and state the between-group and within-group split."},
  {"title": "Letting FX smear into price",
   "body": "Computing the identity on actual-currency revenue puts translation inside the price term, where "
           "it is indistinguishable from commercial pricing. Restate at a single reference rate first and "
           "carry the difference as one line. It costs four lines of code and removes an entire category of "
           "argument."},
  {"title": "A residual you decide to call rounding",
   "body": "Any residual, however small, is the first thing a partner will ask about — and once they do, "
           "nothing else in the bridge gets discussed. Assert the identity in the code and fail the run. "
           "If it does not tie, something upstream is wrong, and the residual is telling you where."},
  {"title": "Truncating the vertical axis silently",
   "body": "A waterfall on a £42m base has to truncate its axis or the movements are invisible. That is "
           "conventional and fine — but label it. An unlabelled truncated axis is the single fastest way to "
           "lose credibility with an audience that reads charts for a living."},
 ],
 "validate": {
  "intro": "Reconciliation is not a final check, it is a gate. Wire it into the run so a bridge that does "
           "not tie never reaches a slide.",
  "why": "Three assertions cover the technique: the commercial identity, the customer partition, and the "
         "nested bridge that carries both. Any per-group breakdown gets a fourth — the parts must sum to "
         "the whole they claim to explain.",
  "code": {"python": '''TOL = 1.0        # pounds, against a book of ~50m

def check(bridge, opening, closing, tol=TOL):
    deltas = sum(v for _, v, kind in bridge if kind == "delta")
    residual = opening + deltas - closing
    assert abs(residual) < tol, f"bridge off by {residual:,.2f}"
    return residual

# 1. the commercial identity
assert abs((volume + price + mix) - (R1 - R0)) < TOL

# 2. the customer partition
assert abs((lost + new + expansion + contraction) - (R1 - R0)) < TOL

# 3. the nested bridge, end to end
residual = check(bridge, R0_actual, R1_actual)

# 4. any per-group cut must foot to the total it decomposes
assert abs(family.price.sum() - price) < TOL
assert abs(family.delta.sum() - (R1 - R0)) < TOL

print(f"reconciliation: residual GBP {residual:,.2f}")''' },
  "out": "reconciliation: residual GBP -0.00"},
 "scale": {
  "body": "The only genuinely large step is the grain reduction. A 50-million-line day-book collapses to a "
          "few tens of thousands of SKU rows and a few hundred thousand customer rows — both comfortably "
          "small. Run the filter, the currency restatement and the two pivots in Spark, then "
          "<code>toPandas()</code> and do the identity, the customer partition and the whole bridge in "
          "NumPy. Trying to express the price/volume/mix arithmetic in Spark is possible and pointless: it "
          "obscures a four-line calculation and gives you nothing back.",
  "notes": [
   "<strong>Partition the source by fiscal year on read</strong> where the layout allows it. Both sides of the bridge scan the whole extract otherwise.",
   "<strong>Watch for skew on customer_id.</strong> One national account can be 20% of the lines; a salted pre-aggregation is worth it if the customer pivot stalls.",
   "<strong>Use <code>decimal</code> for money end to end</strong> if the source does. Casting to double for a 50m-row sum will give you a residual you cannot explain and will waste an afternoon.",
   "<strong>Never <code>collect()</code> the line-level frame.</strong> If a step needs every row in the driver, the step is wrong.",
   "<strong>Cache the filtered frame</strong> if it is reused across the SKU pivot, the customer pivot and the project carve-out — three scans of the same filter is the commonest avoidable cost here.",
   "<strong>Keep the seeded generator in the repo.</strong> Being able to re-run the whole pack against synthetic data is what makes it a template rather than a one-off.",
  ]},
 "foot_title": "Technique 09 — Revenue Decomposition.",
 "foot_body": "Tutorial companion to the Meridian Coatings demo. All figures synthetic.",
}

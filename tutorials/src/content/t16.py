TUTORIAL = {
 "brand": "Data Room Analytics",
 "tag": "Technique 16",
 "phase": "SPA and transaction support",
 "title": "How to read bidder intent from a data room log",
 "subtitle": "Turning VDR telemetry into a fitted view of who is real, who is about to walk, and which "
             "documents will come back as SPA mark-ups — from four exports every platform already produces.",
 "demo_url": "https://claude.ai/code/artifact/b50804ed-996e-472a-9aa8-df7b184ec06c",
 "grain": "one row per document open",
 "meta": [["Engine", "PySpark to sessionise, NumPy to fit"],
          ["Input", "Datasite / Intralinks / Ansarada exports"],
          ["Runtime", "Minutes on tens of millions of events"],
          ["Output", "Fitted withdrawal risk and a bid-count distribution"]],
 "intro": "A bidder board that scores engagement and withdrawal risk from behaviour rather than from what "
          "anyone said on a Friday call, plus a ranked view of where the deal risk sits. The modelling "
          "discipline is that nothing here is hand-weighted: withdrawal probability comes from a logistic "
          "regression fitted on bidders from prior processes whose outcomes are known.",
 "input_intro": "Four exports, all standard. The only one that needs negotiating is the last, and it is the "
                "one that turns a dashboard into a model — without prior outcomes you are guessing at "
                "weights and calling it a framework.",
 "inputs": [
   ["event_ts", "timestamp", "Event time. Needed for sessionisation and for the idle-days feature, which turns out to be the strongest single predictor."],
   ["user_id, org", "string", "Who, and which firm. Adviser organisations are distinguished from the bidder’s own team."],
   ["role", "string", "Partner / Director / Associate / Analyst. Seniority of attention is signal; raw click count is not."],
   ["doc_id, action", "string", "View, download or print. Downloads weigh more than views in practice."],
   ["duration_ms", "long", "Dwell time. Needs cleaning — see step one."],
   ["pages", "int", "From the document index. Dwell must be normalised by length or every long document looks intensely read."],
   ["category, folder", "string", "The taxonomy attention is measured against."],
   ["prior_outcomes", "table", "<strong>The same features from past processes, with who bid and who walked.</strong> This is what makes the model a model."],
 ],
 "walk_intro": "Eight steps. Sessionisation is the only genuinely large operation; from step two onward the "
               "frame is one row per bidder and the whole model fits in memory several times over.",
 "steps": [
  {"title": "Sessionise, and clean the dwell times",
   "why": "Raw VDR durations are dirty in a specific way: a tab left open overnight records eleven hours on "
          "one document. Cap dwell at a plausible per-page ceiling and stitch events into sessions with a "
          "gap threshold, or a single abandoned browser tab becomes your most engaged bidder.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F, Window

spark = SparkSession.builder.appName("vdr").getOrCreate()

log  = spark.read.parquet("s3://lantern/vdr/access/")
docs = spark.read.parquet("s3://lantern/vdr/documents/")

GAP_MIN   = 30      # minutes of inactivity that ends a session
MAX_SEC_PER_PAGE = 240

w = Window.partitionBy("user_id").orderBy("event_ts")

events = (log.join(F.broadcast(docs.select("doc_id", "pages", "category")), "doc_id")
   .withColumn("prev_ts", F.lag("event_ts").over(w))
   .withColumn("gap_min", (F.col("event_ts").cast("long") - F.col("prev_ts").cast("long")) / 60)
   .withColumn("new_session", (F.col("prev_ts").isNull() | (F.col("gap_min") > GAP_MIN)).cast("int"))
   .withColumn("session_id", F.sum("new_session").over(w))
   # a tab left open overnight is not eleven hours of reading
   .withColumn("seconds", F.least(F.col("duration_ms") / 1000,
                                  F.col("pages") * F.lit(MAX_SEC_PER_PAGE)))
   .withColumn("week", F.weekofyear("event_ts")))''',
            "pandas": '''log = pd.read_parquet("access_log.parquet")
docs = pd.read_parquet("documents.parquet")

GAP_MIN, MAX_SEC_PER_PAGE = 30, 240

events = log.merge(docs[["doc_id", "pages", "category"]], on="doc_id")
events = events.sort_values(["user_id", "event_ts"])

gap = events.groupby("user_id").event_ts.diff().dt.total_seconds() / 60
events["session_id"] = (gap.isna() | (gap > GAP_MIN)).groupby(events.user_id).cumsum()
events["seconds"] = np.minimum(events.duration_ms / 1000,
                               events.pages * MAX_SEC_PER_PAGE)'''},
   "note": "Pick the cap from the data, not from intuition: plot dwell per page and cut where the "
           "distribution stops looking like reading. On this process the 99th percentile of genuine reads "
           "sat around 200 seconds a page."},

  {"title": "Build bidder features on the same definitions as history",
   "why": "This is the step that decides whether the model works. Every feature must be computed "
          "identically for the live bidders and for the historical register — same window, same "
          "normalisation, same denominator. A feature that means something slightly different in training "
          "and scoring is worse than no feature.",
   "code": {"spark": '''proc_median = events.selectExpr("percentile_approx(seconds / pages, 0.5)").first()[0]
N_WEEKS = events.agg(F.max("week")).first()[0]

feat = (events.groupBy("bidder").agg(
    (F.countDistinct("doc_id") / F.lit(N_DOCS)).alias("coverage"),
    (F.expr("percentile_approx(seconds / pages, 0.5)") / F.lit(proc_median)).alias("depth"),
    (F.sum(F.when(F.col("role").isin("Partner / MD", "Director"), F.col("seconds")).otherwise(0))
       / F.sum("seconds")).alias("senior_share"),
    F.countDistinct(F.when(F.col("is_adviser") == 1, F.col("org"))).alias("advisers"),
    F.datediff(F.lit(AS_AT), F.max("event_ts")).alias("days_idle"),
    F.sum(F.when(F.col("week") > N_WEEKS - 3, F.col("seconds")).otherwise(0)).alias("recent"),
    F.sum(F.when((F.col("week") > N_WEEKS - 6) & (F.col("week") <= N_WEEKS - 3),
                 F.col("seconds")).otherwise(0)).alias("prior"),
  )
  # +60 keeps the ratio finite for a bidder who has gone completely silent
  .withColumn("trend", F.log((F.col("recent") + 60) / (F.col("prior") + 60)))
  .toPandas().set_index("bidder"))

feat["qa_count"] = qa.groupby("bidder").size()''',
            "pandas": '''proc_median = (events.seconds / events.pages).median()
N_WEEKS = events.week.max()

def features(g):
    recent = g.loc[g.week > N_WEEKS - 3, "seconds"].sum()
    prior  = g.loc[(g.week > N_WEEKS - 6) & (g.week <= N_WEEKS - 3), "seconds"].sum()
    senior = g.role.isin(["Partner / MD", "Director"])
    return pd.Series({
        "coverage":     g.doc_id.nunique() / N_DOCS,
        "depth":        (g.seconds / g.pages).median() / proc_median,
        "senior_share": g.loc[senior, "seconds"].sum() / g.seconds.sum(),
        "advisers":     g.loc[g.is_adviser == 1, "org"].nunique(),
        "days_idle":    (AS_AT - g.event_ts.max()).days,
        "trend":        np.log((recent + 60) / (prior + 60)),
    })

feat = events.groupby("bidder").apply(features)'''},
   "note": "Note <code>depth</code> is indexed to the process median rather than expressed in seconds. "
           "Absolute dwell is not comparable between a 400-document industrials process and a 40-document "
           "software one; a ratio is."},

  {"title": "Fit the withdrawal model by IRLS",
   "why": "Logistic regression, fitted on prior bidders with known outcomes. Fifty lines of NumPy and no "
          "dependency. The point is not that logistic regression is sophisticated — it is that the "
          "coefficients are estimated from evidence, and a partner who asks where the weights came from "
          "gets an answer rather than a shrug.",
   "code": {"python": '''FEATURES = ["coverage", "depth", "senior_share", "advisers",
            "trend", "days_idle", "qa_count"]

mu, sd = HIST[FEATURES].mean(), HIST[FEATURES].std(ddof=0)
standardise = lambda df: ((df[FEATURES] - mu) / sd).to_numpy()

def fit_logistic(X, y, iters=80, ridge=1e-2):
    """Iteratively reweighted least squares. Ridge keeps it stable on small n."""
    X = np.c_[np.ones(len(X)), X]
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = np.clip(p * (1 - p), 1e-8, None)
        A = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(A, X.T @ (y - p) - ridge * b)
        b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b

BETA = fit_logistic(standardise(HIST), HIST.withdrew.to_numpy().astype(float))''',
   },
   "out": "days since last login     +0.63   strongest single predictor\n"
          "activity trend           -1.19\n"
          "document coverage        -0.64\n"
          "questions submitted      -0.51\n"
          "adviser firms engaged    -0.46",
   "note": "Standardise before fitting so the coefficients are comparable — each is the effect of a one "
           "standard deviation move. Unstandardised, <code>days_idle</code> and <code>coverage</code> live "
           "on scales three orders of magnitude apart and the coefficient table tells you nothing."},

  {"title": "Check it separates, and check it is calibrated",
   "why": "AUC says whether the model ranks correctly. Calibration says whether the number it produces can "
          "be read as a probability — which matters more here, because the output gets put in front of "
          "people who will treat 80% as meaning eighty percent.",
   "code": {"python": '''def auc(y, p):
    """Mann-Whitney U, which is exactly the area under the ROC curve."""
    r = pd.Series(p).rank().to_numpy()
    pos, neg = (y == 1).sum(), (y == 0).sum()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))

p_hist = predict(BETA, standardise(HIST))
print(f"AUC {auc(y, p_hist):.3f}  Brier {np.mean((p_hist - y) ** 2):.3f}")

for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]:
    m = (p_hist >= lo) & (p_hist < hi)
    if m.sum():
        print(f"{lo:.0%}-{min(hi,1):.0%}  n={m.sum():3d}  "
              f"predicted {p_hist[m].mean():.0%}  actual {y[m].mean():.0%}")''',
   },
   "out": "AUC 0.832  Brier 0.163\n 0%-20%  n= 27  predicted 11%  actual 10%\n"
          "20%-40%  n= 31  predicted 29%  actual 29%\n40%-60%  n= 29  predicted 49%  actual 52%\n"
          "60%-80%  n= 26  predicted 69%  actual 61%\n80%-100%  n= 27  predicted 91%  actual 94%",
   "note": "This is fitted and evaluated on the same records, which flatters both numbers. On a live desk, "
           "cross-validate — and say in the output that you did. An AUC quoted without saying how it was "
           "measured is not a number, it is a decoration."},

  {"title": "Clip live features into the fitted range",
   "why": "A live bidder with 80 questions when the historical maximum was 44 is not a confident "
          "prediction, it is an extrapolation. Clip to the range the model actually saw, and count how "
          "often you had to — a feature that clips constantly is telling you the training set is not "
          "representative.",
   "code": {"python": '''live = feat.copy()
clipped = {}
for f in FEATURES:
    lo, hi = HIST[f].min(), HIST[f].max()
    clipped[f] = int(((live[f] < lo) | (live[f] > hi)).sum())
    live[f] = live[f].clip(lo, hi)

feat["p_drop"] = predict(BETA, standardise(live))

if any(clipped.values()):
    print("clipped:", {k: v for k, v in clipped.items() if v})''',
   },
   "out": "clipped: {'qa_count': 1}\n\n"
          "Marlowe Partners       p(withdraw) 0.01\nGranton Equity         p(withdraw) 0.01\n"
          "Dunmore Family Office  p(withdraw) 0.18\nPennine Capital        p(withdraw) 0.97\n"
          "Aldermoor Industrial   p(withdraw) 0.80\nSelby Holdings         p(withdraw) 1.00"},

  {"title": "Turn six probabilities into a bid-count distribution",
   "why": "Six names on a process letter is not six-way tension. Treating the withdrawal probabilities as "
          "independent gives the exact distribution of how many bids arrive — a Poisson-binomial, which is "
          "a four-line dynamic program and does not need simulating.",
   "code": {"python": '''def poisson_binomial(p):
    """Exact P(k successes) for independent, non-identical Bernoulli trials."""
    dist = np.zeros(len(p) + 1)
    dist[0] = 1.0
    for pi in p:
        dist[1:] = dist[1:] * (1 - pi) + dist[:-1] * pi
        dist[0] *= (1 - pi)
    return dist

p_bid = 1 - feat.p_drop.to_numpy()
dist  = poisson_binomial(p_bid)

assert abs(dist.sum() - 1) < 1e-9
print(f"expected {p_bid.sum():.1f} bids   "
      f"P(>=2) {dist[2:].sum():.0%}   P(>=3) {dist[3:].sum():.0%}")''',
   },
   "out": "expected 3.0 bids   P(>=2) 100%   P(>=3) 85%\n\n"
          "1 bid   0.3%\n2 bids 15.1%\n3 bids 66.4%\n4 bids 17.7%\n5 bids  0.5%",
   "note": "Independence is an assumption and a slightly generous one — bidders drop for correlated reasons "
           "such as a sector shock or a competitor’s aggressive first-round bid. It biases the spread "
           "narrow, not the mean, so the expected count is sound and the tails are optimistic."},

  {"title": "Score document heat",
   "why": "The documents the room keeps returning to are the issues that come back as SPA mark-ups, and you "
          "can see them weeks before the first draft arrives. Three components: total attention, breadth "
          "across bidders, and how many separate days a bidder came back to it.",
   "code": {"spark": '''revisits = (events.groupBy("doc_id", "bidder")
                  .agg(F.countDistinct(F.to_date("event_ts")).alias("days"))
                  .groupBy("doc_id").agg(F.avg("days").alias("revisits")))

heat = (events.groupBy("doc_id")
    .agg((F.sum("seconds") / 3600).alias("hours"),
         F.countDistinct("bidder").alias("bidders"))
    .join(revisits, "doc_id")
    .join(F.broadcast(docs), "doc_id")
    .toPandas())

z = lambda s: (s - s.mean()) / max(s.std(ddof=0), 1e-9)
heat["sec_per_page"] = heat.hours * 3600 / heat.pages
heat["score"] = (z(np.log1p(heat.hours))
                 + 0.8 * z(heat.bidders.astype(float))
                 + z(np.log1p(heat.revisits))
                 + 0.4 * z(np.log1p(heat.sec_per_page)))''',
            "pandas": '''revisits = (events.groupby(["doc_id", "bidder"])
                  .event_ts.apply(lambda s: s.dt.date.nunique())
                  .groupby("doc_id").mean().rename("revisits"))

heat = (events.groupby("doc_id")
              .agg(hours=("seconds", lambda s: s.sum() / 3600),
                   bidders=("bidder", "nunique"))
              .join(revisits).join(docs.set_index("doc_id")))

z = lambda s: (s - s.mean()) / max(s.std(ddof=0), 1e-9)
heat["sec_per_page"] = heat.hours * 3600 / heat.pages
heat["score"] = (z(np.log1p(heat.hours)) + 0.8 * z(heat.bidders.astype(float))
                 + z(np.log1p(heat.revisits)) + 0.4 * z(np.log1p(heat.sec_per_page)))'''},
   "out": "Master supply agreement - Halstead Aerospace   6/6 bidders  21.7 revisits  5.8h\n"
          "Actuarial valuation - Thornbury Pension Scheme 4/6 bidders  19.0 revisits  4.1h\n"
          "Working capital: 36-month normalisation        5/6 bidders  15.6 revisits  2.9h"},

  {"title": "Profile attention against the right baseline",
   "why": "A bidder deep in customer contracts and absent from financial and legal is not doing diligence. "
          "But measuring that needs care: index each bidder’s category share against the mean of "
          "per-bidder shares, not against the pooled total. The pooled total is dominated by whoever reads "
          "most, so the heaviest reader scores 1.0 everywhere by construction.",
   "code": {"python": '''att   = events.pivot_table(index="bidder", columns="category",
                          values="seconds", aggfunc="sum").fillna(0)
share = att.div(att.sum(axis=1), axis=0)

# The baseline is the TYPICAL bidder, not the pooled room
room = share[share.sum(axis=1) > 0].mean(axis=0)
room = room / room.sum()

index = share.div(room, axis=1)

# A pattern worth a question: heavy commercial, absent financial, no advisers, no Q&A
comm = index[["Commercial & Customers", "Operations & Sites"]].mean(axis=1)
fin  = index[["Financial", "Legal & Corporate", "Tax"]].mean(axis=1)
recon = (np.clip((comm - fin) / 2.2, 0, 1)
         * (feat.advisers == 0) * np.clip(1 - feat.qa_count / 12, 0, 1))''',
   },
   "out": "                        Comm  Envir  Finan  HR&P  Legal    Tax\n"
          "Marlowe Partners        0.49   0.84   1.29  1.74   1.31   1.28\n"
          "Aldermoor Industrial    1.92   1.38   0.16  0.13   0.26   0.08",
   "note": "Report this as a flag, never as a finding. A trade buyer may have a genuine thesis that lives in "
           "the commercial folders. The proportionate action is to confirm their process with their adviser "
           "and stage the pricing detail — not to accuse anyone of anything."},
 ],
 "pitfalls": [
  {"title": "Indexing attention against the pooled total",
   "body": "The obvious baseline — total seconds per category across the room — is dominated by whichever "
           "bidder reads most. In this process Marlowe was 45 of 98 total hours, so Marlowe scored close to "
           "1.0 in every category by construction and the matrix washed out to nothing. Index against the "
           "<em>mean of per-bidder shares</em> instead and the pattern appears immediately."},
  {"title": "Ranking documents by attention per page",
   "body": "Per-page intensity looks like the right normalisation and penalises exactly the documents that "
           "carry the risk. A 168-page actuarial valuation read for six hours by every bidder scores below "
           "a four-page memo someone stared at. Rank on total attention, breadth and revisits, with per-page "
           "intensity as a minor term."},
  {"title": "Trusting an estimate built on thirty events",
   "body": "Median dwell per page is meaningless for a bidder who has barely logged in, and an unshrunk "
           "estimate had a near-absent bidder out-ranking one with six times the hours. Shrink unstable "
           "features toward a stable one in proportion to how much data there is: "
           "<code>depth = depth·r + coverage·(1−r)</code> with <code>r = min(1, events/300)</code>."},
  {"title": "Presenting behavioural inference as fact",
   "body": "A quiet bidder may be waiting on an investment committee. A commercial-only reader may have a "
           "thesis. The output of this analysis is a ranked set of questions for the deal team, and the page "
           "should say so in as many words — the credibility of everything else depends on being visibly "
           "careful about this one."},
 ],
 "validate": {
  "intro": "Three assertions, each catching a different class of error: an arithmetic slip, a model that is "
           "not doing its job, and a normalisation that has gone wrong.",
  "why": "The distribution check catches the dynamic program; the AUC floor catches a model fitted on "
         "features that turned out to be useless; the share check catches a pivot that lost rows to nulls.",
  "code": {"python": '''def check():
    # 1. the exact distribution must be a distribution
    assert abs(dist.sum() - 1) < 1e-9, "bid-count distribution does not sum to 1"

    # 2. a model that cannot separate should fail the build, not ship
    assert AUC > 0.70, f"model separates poorly (AUC {AUC:.2f})"

    # 3. every active bidder's attention shares must sum to 1
    for b in share.index:
        if feat.loc[b, "events"] > 0:
            assert abs(share.loc[b].sum() - 1) < 1e-6, f"{b}: shares do not sum to 1"

    print(f"checks: AUC {AUC:.3f}, distribution sums to 1, shares sum to 1")''',
   },
  "out": "checks: AUC 0.832, distribution sums to 1, shares sum to 1"},
 "scale": {
  "body": "The access log is the only large object, and it is genuinely large: a firm with several years of "
          "processes behind it has tens of millions of events. Sessionisation is a window function over "
          "user and timestamp, which is exactly what Spark is for. Everything downstream operates on one "
          "row per bidder — six rows for the live process, a few hundred for the historical register — so "
          "the model, the simulation and the scoring all run in NumPy in milliseconds.",
  "notes": [
   "<strong>Broadcast the document index.</strong> It is a few hundred rows joined to tens of millions; without the hint Spark will shuffle both sides.",
   "<strong>Partition the log by process</strong> and keep historical processes in the same layout, so building the training set is a filter rather than a migration.",
   "<strong>Watch for skew on user_id.</strong> One adviser analyst working through the room systematically can be a large share of all events.",
   "<strong>Never join the log to itself</strong> to compute revisits — a two-stage groupBy (doc × bidder, then doc) is both faster and easier to read.",
   "<strong>Anonymise before the model sees it.</strong> Bidder identity belongs in the presentation layer; the feature table should key on an opaque id, which also makes historical processes reusable without a confidentiality argument.",
  ]},
 "foot_title": "Technique 16 — Virtual Data Room Analytics.",
 "foot_body": "Tutorial companion to the Project Lantern demo. All figures synthetic.",
}

TUTORIAL = {
 "brand": "Alt Data Triangulation",
 "tag": "Technique 01",
 "phase": "Commercial due diligence",
 "title": "How to triangulate outside-in data into a defensible view",
 "subtitle": "Turning eleven subscriptions into a scored position on a management narrative — with confidence "
             "that depends on how independent the evidence is, not how much of it there is.",
 "demo_url": "https://claude.ai/code/artifact/573d0f94-5d11-4e02-8ed7-064c98752cb3",
 "grain": "one row per signal per month",
 "meta": [["Engine", "PySpark to build signals, NumPy to score them"],
          ["Input", "Vendor feeds, filings, reviews, job boards"],
          ["Runtime", "Minutes, once the feeds land"],
          ["Output", "A claim scorecard with an evidence and a confidence number"]],
 "intro": "A scorecard that tests each claim in the information memorandum against outside-in evidence, and "
          "says how much weight the evidence deserves. The hard part is not gathering signals — vendors sell "
          "those. It is combining sources of wildly different quality without either pretending they are "
          "equal or letting the loudest one dominate.",
 "input_intro": "Signals arrive from eleven subscriptions in completely different shapes: monthly panels, "
                "event-level review text, dated filings, scraped postings. Normalise everything to one long "
                "table before you score anything — the scoring code should never know which vendor a number "
                "came from, only what that vendor is worth.",
 "inputs": [
   ["signal", "string", "Stable key. Everything downstream joins on this, so name it once and never rename it."],
   ["source, family", "string", "The vendor, and the <strong>methodological family</strong> it belongs to. The family is what makes independence measurable."],
   ["month", "date", "Monthly grain. Anything finer is noise at this altitude; anything coarser loses the trend."],
   ["value", "double", "The measurement itself, in its own units."],
   ["peer_value", "double", "The same measurement for a comparable set, where one exists. Null is fine and common."],
   ["n", "long", "Observations behind the measurement. Drives the sample-adequacy haircut."],
   ["latency_months", "double", "How stale the feed is at the point of analysis. Companies House is 2.5 months behind; Trustpilot is same-day."],
   ["reliability", "double", "A stated prior per source, 0 to 1. Write it down so a client can argue with it."],
 ],
 "walk_intro": "Nine steps. Steps one and two are genuinely large — millions of reviews and web-panel rows "
               "collapsing to a few hundred signal-months. Everything after that operates on a table small "
               "enough to print.",
 "steps": [
  {"title": "Collapse event-level sources into monthly signals",
   "why": "This is where Spark earns its place. Review platforms, app stores and job boards arrive as "
          "events — one row per review, per posting, per session. You need them as one row per signal per "
          "month, with an observation count attached, because the count drives how much the signal is worth.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.appName("outside-in").getOrCreate()

reviews = spark.read.parquet("s3://harrier/reviews/")      # ~28m rows, all platforms

PRICE_TERMS = r"(?i)\\b(price|pricing|expensive|cost|bill|billing|charge|overcharg|invoice)\\b"

monthly = (reviews
  .withColumn("month", F.trunc("posted_at", "month"))
  .withColumn("mentions_price", F.col("body").rlike(PRICE_TERMS).cast("int"))
  .groupBy("platform", "month")
  .agg(F.avg("rating").alias("rating"),
       F.avg("mentions_price").alias("price_complaint_rate"),
       F.count("*").alias("n")))

# Reshape to the long signal table the scorer expects
signals = (monthly
  .select("month", "n",
          F.col("platform").alias("source"),
          F.explode(F.array(
            F.struct(F.lit("tp_rating").alias("signal"), F.col("rating").alias("value")),
            F.struct(F.lit("price_cmp").alias("signal"), F.col("price_complaint_rate").alias("value")),
          )).alias("s"))
  .select("month", "n", "source", "s.signal", "s.value"))''',
            "pandas": '''reviews = pd.read_parquet("reviews.parquet")

PRICE_TERMS = r"(?i)\\b(price|pricing|expensive|cost|bill|billing|charge|overcharg|invoice)\\b"
reviews["month"] = reviews.posted_at.dt.to_period("M")
reviews["mentions_price"] = reviews.body.str.contains(PRICE_TERMS, regex=True).astype(int)

monthly = (reviews.groupby(["platform", "month"])
                  .agg(rating=("rating", "mean"),
                       price_complaint_rate=("mentions_price", "mean"),
                       n=("rating", "size"))
                  .reset_index())

signals = monthly.melt(id_vars=["platform", "month", "n"],
                       value_vars=["rating", "price_complaint_rate"],
                       var_name="signal", value_name="value")'''},
   "note": "Do the text matching in Spark, not in a pandas UDF. A regex on 28 million review bodies is the "
           "one part of this analysis that genuinely needs a cluster, and <code>rlike</code> pushes down "
           "properly where a UDF will not."},

  {"title": "Derive per-unit signals rather than absolutes",
   "why": "Absolute totals flatter a business that is growing by acquisition. Booking sessions rose 31% "
          "while the estate grew 32% — per practice, traffic <em>fell</em>. Almost every outside-in trap is "
          "this trap, so build the normalised version as a first-class signal rather than computing it in "
          "your head at the end.",
   "code": {"spark": '''# Estate size comes from dated Companies House filings, not from the vendor
estate = (filings.filter(F.col("event") == "acquisition_completed")
                 .groupBy(F.trunc("filed_at", "month").alias("month"))
                 .agg(F.count("*").alias("acquired"))
                 .withColumn("estate",
                     F.lit(OPENING_ESTATE) +
                     F.sum("acquired").over(Window.orderBy("month")
                                                  .rowsBetween(Window.unboundedPreceding, 0))))

per_practice = (web_panel.join(estate, "month")
                         .withColumn("value", F.col("sessions") / F.col("estate"))
                         .withColumn("signal", F.lit("sessions_pp")))''',
            "pandas": '''estate = (filings[filings.event.eq("acquisition_completed")]
            .groupby(filings.filed_at.dt.to_period("M")).size()
            .rename("acquired").to_frame())
estate["estate"] = OPENING_ESTATE + estate.acquired.cumsum()

per_practice = web_panel.join(estate, on="month")
per_practice["value"] = per_practice.sessions / per_practice.estate
per_practice["signal"] = "sessions_pp"'''},
   "note": "Note the deliberate cross-source construction: the numerator is a web panel, the denominator a "
           "regulatory filing. Signals built this way are far harder for a management team to dismiss than "
           "anything a single vendor produces."},

  {"title": "Compare two windows, peer-adjusted",
   "why": "Compare the last six months to the same six months a year earlier. That kills seasonality "
          "without needing a seasonal model. Where a peer series exists, subtract its movement — a rating "
          "that falls while the whole sector falls is not a company-specific finding.",
   "code": {"python": '''WIN = 6       # months in each comparison window

def window_delta(v, peer=None, additive=False):
    """Peer-adjusted move: last WIN months vs the same WIN months a year earlier."""
    x = v if additive else np.log(np.maximum(v, 1e-9))
    delta = x[-WIN:].mean() - x[-(WIN + 12):-12].mean()
    if peer is not None:
        q = peer if additive else np.log(np.maximum(peer, 1e-9))
        delta -= q[-WIN:].mean() - q[-(WIN + 12):-12].mean()
    return delta'''},
   "note": "Work on logs for anything strictly positive so the result is a proportional change, and "
           "additively for anything that can be zero or negative. Getting this wrong is the subject of the "
           "second pitfall below."},

  {"title": "Standardise by the right denominator",
   "why": "A raw delta is meaningless until you know how noisy the series is. The denominator is the "
          "standard error of the difference between two six-month means — not the month-to-month volatility. "
          "This distinction is worth more than it looks: getting it wrong scaled every signal in this "
          "analysis down by roughly a factor of six and made a tripling of price complaints read as 0.20.",
   "code": {"python": '''def resid_sd(x):
    """Noise AROUND the trend, not the trend itself."""
    t = np.arange(len(x))
    fit = np.polyval(np.polyfit(t, x, 1), t)
    return max(float((x - fit).std(ddof=2)), 1e-9)

def standardise(v, peer=None, additive=False):
    x = v if additive else np.log(np.maximum(v, 1e-9))
    delta = window_delta(v, peer, additive)
    se = resid_sd(x) * np.sqrt(2.0 / WIN)      # two independent WIN-month means
    return float(np.tanh((delta / se) / 6.0))  # squash to [-1, 1]'''},
   "out": "price_cmp   delta +0.42 log   se 0.046   z 9.1   d -0.98\n"
          "gd_rating   delta -0.19 log   se 0.031   z 6.2   d -0.87",
   "note": "Detrend before measuring noise. Taking the standard deviation of a trending series measures the "
           "trend you are trying to detect and guarantees you conclude nothing is happening. The "
           "<code>tanh</code> squash is a presentation choice — it bounds the scale without a hard clip, so "
           "a nine-sigma move reads as decisive without a twelve-sigma move reading as three times more so."},

  {"title": "Two test modes: is it moving, and is it the right number",
   "why": "Direction is not enough when a claim carries a figure. “Like-for-like growth of 9%” is not "
          "tested by observing that review volume is rising — it is tested by observing that review volume "
          "is rising at 5.4%. Add a level mode alongside the trend mode and declare which one each link uses.",
   "code": {"python": '''def level_d(observed, claimed, tolerance):
    """How far the observed value sits from the claimed one, in tolerances."""
    return float(np.tanh((observed - claimed) / tolerance))

LEVEL_TESTS = {
    # key:               (observed,              claimed, tolerance)
    "implied_organic":   (implied_organic(0.80), 0.090,   0.020),
    "rev_vol_growth":    (annualised("rev_vol_pp"), 0.090, 0.025),
    "indep_level":       (indep_share[-1],       0.600,   0.040),
}

# align = +1 means the claim is supported when the signal reads HIGH
d = level_d(*LEVEL_TESTS["implied_organic"]) * align'''},
   "out": "implied_organic   5.1% observed vs 9% claimed   ->  d = -0.96",
   "note": "Set the tolerance to the width of a difference you would actually argue about, not to a "
           "statistical threshold. Two percentage points on an organic growth rate changes the valuation; "
           "0.2 does not."},

  {"title": "Weight each signal by what it is worth",
   "why": "Three multiplicative haircuts, each defensible on its own: how much you trust the source, how "
          "stale the feed is, and how many observations sit behind the number. Write them down. A client "
          "who disagrees with your Glassdoor prior can argue with a number instead of with your judgement.",
   "code": {"python": '''N_REF = 500      # observations at which the sample haircut disappears

def weight(sig):
    recency  = np.exp(-sig.latency_months / 9.0)
    adequacy = min(1.0, np.log1p(sig.n) / np.log1p(N_REF))
    return sig.reliability * recency * adequacy

# Companies House: reliable but lagged      0.95 x 0.76 x 0.84 = 0.61
# Trustpilot:      same-day but self-selecting 0.58 x 0.98 x 1.00 = 0.57
# Glassdoor:       low n, self-selecting    0.55 x 0.95 x 0.86 = 0.45'''},
   "note": "Relevance to the specific claim is a fourth multiplier, set per link rather than per signal. "
           "The same Glassdoor rating is strong evidence about being an employer of choice and weak "
           "evidence about pricing."},

  {"title": "Score the claim — and score the confidence separately",
   "why": "Evidence and confidence are different questions and collapsing them loses the more useful one. "
          "Evidence is which way the data points. Confidence is whether you are entitled to an opinion, and "
          "it depends on three things that cannot substitute for one another: enough evidence, enough "
          "<em>independent</em> sources, and agreement between them.",
   "code": {"python": '''def score(links):
    w = np.array([l.weight for l in links])
    d = np.array([l.d for l in links])

    E = float((w * d).sum() / w.sum())                    # evidence,  -1 .. +1
    C = float(abs((w * d).sum()) / (w * abs(d)).sum())    # coherence,  0 .. 1

    families = len({l.family for l in links})
    F_ = 1 - np.exp(-0.9 * (families - 1))                # independence
    M  = 1 - np.exp(-w.sum() / 1.6)                       # evidence mass

    confidence = float(M * np.sqrt(F_) * np.sqrt(C))
    return E, C, families, confidence'''},
   "out": "C1  E -0.95   coherence 1.00   4 families   confidence 0.75\n"
          "C2  E -0.89   coherence 1.00   2 families   confidence 0.14",
   "note": "The square roots matter. Multiplying three sub-one factors compounds into pessimism fast — an "
           "unsmoothed product rated a hard fact from Gain.Pro, corroborated twice, as not testable."},

  {"title": "Count families, not sources",
   "why": "Trustpilot and Google agreeing is not corroboration: they are the same methodology sampling the "
          "same self-selecting population, and they will be wrong together. Group sources into "
          "methodological families and let only the family count feed independence. This one line is the "
          "difference between a framework and a weighted average with extra steps.",
   "code": {"python": '''FAMILY = {
    "Companies House": "Regulatory filings",
    "S&P Capital IQ":  "Market data",
    "Preqin":          "Market data",      # same family as CapIQ -- adds weight, not independence
    "Gain.Pro":        "Market data",
    "Google Reviews":  "User reviews",
    "Trustpilot":      "User reviews",     # ditto
    "Glassdoor":       "Employee reviews",
    "Indeed":          "Labour market",
    "SimilarWeb":      "Web panel",
    "AlphaSense":      "Expert network",
    "Quid":            "Media",
}

# 4 sources, 2 families -> independence 0.59, not 0.96
families = len({FAMILY[s] for s in sources})'''},
   "note": "The grouping is a judgement and should be visible in the output. Anyone who thinks Preqin and "
           "CapIQ are genuinely independent for a given question is welcome to move one and see what happens "
           "to the score."},

  {"title": "Give the unobservable an honest band",
   "why": "Some claims cannot be seen from outside, and saying so is a finding. Others can be bounded even "
          "though they cannot be measured. Group revenue comes from filed accounts and acquisition dates "
          "from Companies House; the only unknown is how big an acquired unit is relative to an existing "
          "one. That gives a closed form in one parameter — so report a band and name the assumption.",
   "code": {"python": '''def implied_organic(alpha):
    """
    r      = revenue per legacy unit-month
    alpha  = size of an acquired unit relative to a legacy one

        R0 = r * (LPM0 + alpha*APM0)
        R1 = r * (1+g) * (LPM1 + alpha*APM1)

    Everything is observable except alpha, so the honest answer is a band.
    """
    return (R1 * (LPM0 + alpha * APM0)) / (R0 * (LPM1 + alpha * APM1)) - 1

band = {a: implied_organic(a) for a in np.arange(0.65, 1.01, 0.05)}'''},
   "out": "alpha 0.65 -> 7.4%\nalpha 0.80 -> 5.1%\nalpha 1.00 -> 2.3%\n\nclaimed in the IM: 9.0%",
   "note": "The width of the band is itself the deliverable: it names the single number to request first. "
           "An information request built from what outside data could <em>not</em> settle is worth more than "
           "a generic checklist."},
 ],
 "pitfalls": [
  {"title": "Dividing by month-to-month volatility",
   "body": "The comparison is between two six-month means, so the denominator is the standard error of that "
           "difference — roughly <code>sd × √(2/6)</code>. Using annualised single-month volatility instead "
           "is about <strong>six times too large</strong> and crushes every signal toward zero. In this "
           "analysis a tripling of price complaints against a flat peer group scored −0.20, and the whole "
           "scorecard read as inconclusive."},
  {"title": "Log-transforming a count that touches zero",
   "body": "Monthly acquisition filings include months with none. <code>log(0)</code> guarded to "
           "<code>log(1e-9)</code> gives −20.7, which destroys the residual standard deviation and produced "
           "a reported change of <strong>+110,192%</strong>. Detect it — <code>min(v) &lt;= 0</code> — and "
           "switch that series to additive differences automatically rather than remembering to flag it."},
  {"title": "Counting correlated sources as corroboration",
   "body": "Two review platforms, four market-data vendors and three news aggregators can look like nine "
           "independent confirmations. They are three. Confidence must key off family count, or the "
           "framework will be most confident exactly where the vendor market is most crowded."},
  {"title": "Double-counting a signal the level test already carries",
   "body": "The acquisition-count trend was linked to the organic growth claim alongside the "
           "acquisition-adjusted level test — which is computed <em>from</em> that same count. It added "
           "apparent evidence without adding information. When a level test derives from a signal, drop the "
           "signal's trend link."},
 ],
 "validate": {
  "intro": "You cannot check an outside-in view against the truth on a live deal — that is the whole "
           "premise. But you can check the method on data where the truth is known, which is exactly what "
           "the synthetic generator is for.",
  "why": "The generator produces a company whose real same-store growth is known. The engine never reads "
         "it. The assertion is that the band the method produces actually contains the answer — if it stops "
         "doing so, the build fails rather than shipping a confident number.",
  "code": {"python": '''def check():
    # The engine is only allowed to see filings and vendor feeds. This line reads
    # the ground-truth panel, and it is the only place in the codebase that does.
    truth = same_store_growth(panel)

    assert ORG_LO < truth < ORG_HI, (
        f"outside-in band [{ORG_LO:.1%}, {ORG_HI:.1%}] misses the truth {truth:.1%}")

    for c in SCORED:
        assert -1.001 <= c["score"] <= 1.001
        assert 0 <= c["confidence"] <= 1
        assert c["families"] == len({e["family"] for e in c["evidence"]})

    print(f"band {ORG_LO:.1%}-{ORG_HI:.1%} contains truth {truth:.1%}")''',
   },
  "out": "band 2.3%-7.4% contains truth 5.6%   (central estimate 5.1%, error 0.5pp)"},
 "scale": {
  "body": "The weight is all at the front. Review corpora, app-store feeds and web-panel exports run to "
          "tens of millions of rows and want Spark: regex matching, sentiment scoring, sessionisation, and "
          "the joins that build per-unit signals from a vendor numerator and a filings denominator. What "
          "comes out the other side is a few hundred signal-months — a table you could print. Every line of "
          "the scoring engine runs on that, in NumPy, in milliseconds.",
  "notes": [
   "<strong>Persist the signal table with the vendor snapshot date.</strong> Vendors restate history quietly; a scorecard you cannot reproduce six weeks later is worthless in a dispute.",
   "<strong>Cache the review corpus after the text pass.</strong> Theme extraction, rating trend and complaint rate all scan the same rows.",
   "<strong>Keep raw and derived signals in the same table</strong> with a flag, so a reviewer can see that sessions-per-practice is a construction and not something SimilarWeb sells.",
   "<strong>Never put vendor identity into the scoring code.</strong> It should read reliability, latency and family from the table — swapping Trustpilot for Feefo should be a data change, not a code change.",
   "<strong>Log the priors with the output.</strong> The reliability numbers are the most contestable part of the method, which is an argument for exposing them, not burying them.",
  ]},
 "foot_title": "Technique 01 — Alt Data Triangulation.",
 "foot_body": "Tutorial companion to the Project Harrier demo. All figures synthetic.",
}

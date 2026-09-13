TUTORIAL = {
 "brand": "Trade Area & Footfall",
 "tag": "Technique 04",
 "phase": "Commercial due diligence",
 "title": "How to build a trade area model from device data",
 "subtitle": "From raw mobile pings to a calibrated gravity model that forecasts a new site and charges it "
             "for the trade it takes off the ones you already own.",
 "demo_url": "https://claude.ai/code/artifact/5cf358a8-34ea-4190-9b5a-cc7217fd63b4",
 "grain": "billions of pings in, one row per area-site pair out",
 "meta": [["Engine", "PySpark end to end for steps 1-3, NumPy after"],
          ["Input", "Device pings, Experian Mosaic, census, estate"],
          ["Runtime", "Hours on the pings, seconds on the model"],
          ["Output", "A fitted decay, a validated forecast, cannibalisation"]],
 "intro": "A model that says how much trade a site draws, from where, and what a new one would do to the "
          "rest of the estate. Two things separate a credible build from a map with dots on it: expanding "
          "the panel properly, and validating the model against how the existing estate actually trades "
          "before using it to forecast a site that does not exist.",
 "input_intro": "Five inputs, and the first is orders of magnitude larger than the other four combined. "
                "Most of the engineering in this technique is getting from that first input to something "
                "small enough to model.",
 "inputs": [
   ["device_id, ts, lat, lon", "string, ts, double", "Raw pings. Billions of rows a month for a national panel. Everything else is small."],
   ["horizontal_accuracy", "double", "<strong>Filter on this early.</strong> A ping with 500m accuracy cannot be attributed to a venue and will quietly inflate urban catchments."],
   ["venue polygons or points", "geometry", "Your estate and the competing field. Points with a radius are usually enough for a high-street format."],
   ["population by output area", "int", "Census or mid-year estimates. The denominator for penetration and for demand."],
   ["Experian Mosaic", "string, double", "Segment per output area, plus consumer expenditure. Drives spend per visit and the demographic fit."],
   ["site trading revenue", "decimal", "<strong>The calibration target.</strong> A catchment model that cannot explain the estate you can see has no business forecasting one you cannot."],
 ],
 "walk_intro": "Eight steps. The first three are genuinely heavy and belong in Spark; by step four you are "
               "holding a matrix of a few hundred output areas by a few hundred sites, and everything after "
               "that is NumPy.",
 "steps": [
  {"title": "Turn pings into stops",
   "why": "A device sitting in a shop emits a cluster of pings in one place over several minutes. A device "
          "driving past emits a line. Stop detection is what separates a visit from a passer-by, and doing "
          "it badly is the difference between a catchment and a traffic count.",
   "code": {"spark": '''from pyspark.sql import SparkSession, functions as F, Window

spark = SparkSession.builder.appName("ferryman-footfall").getOrCreate()

pings = (spark.read.parquet("s3://ferryman/pings/")
   .filter(F.col("horizontal_accuracy") <= 60)          # metres; drop the rest
   .filter(F.col("lat").between(49.8, 60.9) & F.col("lon").between(-8.2, 2.1)))

w = Window.partitionBy("device_id").orderBy("ts")

# Rough metres between consecutive pings. A local equirectangular approximation is
# accurate enough at these distances and avoids a trig-heavy haversine per row.
stops = (pings
  .withColumn("plat", F.lag("lat").over(w)).withColumn("plon", F.lag("lon").over(w))
  .withColumn("pts",  F.lag("ts").over(w))
  .withColumn("dm", F.sqrt(
      F.pow((F.col("lat") - F.col("plat")) * 111_320, 2) +
      F.pow((F.col("lon") - F.col("plon")) * 111_320 * F.cos(F.radians("lat")), 2)))
  .withColumn("gap_s", F.col("ts").cast("long") - F.col("pts").cast("long"))
  # a new stop starts when the device has moved more than 90m or been silent an hour
  .withColumn("new_stop", (F.col("dm").isNull() | (F.col("dm") > 90) | (F.col("gap_s") > 3600)).cast("int"))
  .withColumn("stop_id", F.sum("new_stop").over(w)))

stop_summary = (stops.groupBy("device_id", "stop_id")
  .agg(F.avg("lat").alias("lat"), F.avg("lon").alias("lon"),
       F.min("ts").alias("arrived"), F.max("ts").alias("left"), F.count("*").alias("pings"))
  .withColumn("dwell_s", F.col("left").cast("long") - F.col("arrived").cast("long"))
  .filter((F.col("dwell_s") >= 240) & (F.col("pings") >= 3)))''',
            "pandas": '''# Only viable on a sampled extract -- a national ping feed will not fit in memory.
pings = pd.read_parquet("pings_sample.parquet")
pings = pings[pings.horizontal_accuracy <= 60].sort_values(["device_id", "ts"])

g = pings.groupby("device_id")
dlat = (pings.lat - g.lat.shift()) * 111_320
dlon = (pings.lon - g.lon.shift()) * 111_320 * np.cos(np.radians(pings.lat))
dm = np.hypot(dlat, dlon)
gap = (pings.ts - g.ts.shift()).dt.total_seconds()

pings["stop_id"] = (dm.isna() | (dm > 90) | (gap > 3600)).groupby(pings.device_id).cumsum()

stop_summary = (pings.groupby(["device_id", "stop_id"])
    .agg(lat=("lat", "mean"), lon=("lon", "mean"), arrived=("ts", "min"),
         left=("ts", "max"), pings=("ts", "size")))
stop_summary["dwell_s"] = (stop_summary.left - stop_summary.arrived).dt.total_seconds()
stop_summary = stop_summary.query("dwell_s >= 240 and pings >= 3")'''},
   "note": "The 90 metre and four minute thresholds are format-specific and worth tuning against a handful "
           "of sites where you know the transaction count. A drive-through needs a much shorter dwell floor; "
           "a garden centre a much longer one."},

  {"title": "Attribute stops to venues without a cross join",
   "why": "Joining a billion stops to a few hundred venues on distance is a cross join, and it will not "
          "finish. Bin both sides onto a grid, join on the bin, then filter on exact distance. Replicate "
          "each venue into its neighbouring cells so a stop just over a boundary still matches.",
   "code": {"spark": '''CELL = 0.0025      # degrees, roughly 275m of latitude

def cell_expr(lat, lon, dlat=0, dlon=0):
    return F.concat_ws("_", (F.floor(lat / CELL) + dlat).cast("int"),
                            (F.floor(lon / CELL) + dlon).cast("int"))

offsets = [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)]
venue_cells = venues.select(
    "venue_id", "lat", "lon", "brand", "own",
    F.explode(F.array(*[cell_expr(F.col("lat"), F.col("lon"), i, j) for i, j in offsets])).alias("cell"))

visits = (stop_summary
  .withColumn("cell", cell_expr(F.col("lat"), F.col("lon")))
  .join(F.broadcast(venue_cells), "cell")               # a few hundred rows: broadcast it
  .withColumn("dm", F.sqrt(
      F.pow((F.col("lat") - F.col("v_lat")) * 111_320, 2) +
      F.pow((F.col("lon") - F.col("v_lon")) * 111_320 * F.cos(F.radians("lat")), 2)))
  .filter(F.col("dm") <= 45)                            # inside the venue footprint
  # a stop can match two venues in a dense parade -- keep the nearest
  .withColumn("rk", F.row_number().over(
      Window.partitionBy("device_id", "stop_id").orderBy("dm")))
  .filter(F.col("rk") == 1))''',
            "pandas": '''from scipy.spatial import cKDTree   # or sklearn BallTree

xy = np.c_[stop_summary.lat * 111_320,
           stop_summary.lon * 111_320 * np.cos(np.radians(stop_summary.lat))]
vxy = np.c_[venues.lat * 111_320,
            venues.lon * 111_320 * np.cos(np.radians(venues.lat))]

dist, idx = cKDTree(vxy).query(xy, k=1, distance_upper_bound=45)
hit = np.isfinite(dist)

visits = stop_summary[hit].assign(venue_id=venues.venue_id.to_numpy()[idx[hit]],
                                  dm=dist[hit])'''},
   "note": "On a platform with Apache Sedona or an H3 UDF available, use those instead — the grid here is "
           "the dependency-free version of the same idea. What matters is that you never write a join "
           "predicate that Spark cannot turn into a hash join."},

  {"title": "Infer where each device lives",
   "why": "A catchment is a statement about where customers come from, so every visit needs a home output "
          "area. The overnight cluster is the standard proxy: the modal location between one and five in "
          "the morning, over a month, is where the device sleeps.",
   "code": {"spark": '''home = (pings
  .withColumn("hour", F.hour("ts"))
  .filter(F.col("hour").between(1, 4))
  .withColumn("cell", cell_expr(F.col("lat"), F.col("lon")))
  .groupBy("device_id", "cell")
  .agg(F.count("*").alias("n"), F.countDistinct(F.to_date("ts")).alias("nights"))
  .withColumn("rk", F.row_number().over(
      Window.partitionBy("device_id").orderBy(F.desc("nights"), F.desc("n"))))
  .filter(F.col("rk") == 1)
  # a device seen on fewer than five separate nights has no reliable home
  .filter(F.col("nights") >= 5)
  .join(F.broadcast(cell_to_oa), "cell")
  .select("device_id", "oa_id"))

panel_visits = (visits.join(home, "device_id")
  .groupBy("oa_id", "venue_id").agg(F.count("*").alias("panel_visits")))''',
            "pandas": '''night = pings[pings.ts.dt.hour.between(1, 4)].copy()
night["cell"] = (np.floor(night.lat / CELL).astype(int).astype(str) + "_"
                 + np.floor(night.lon / CELL).astype(int).astype(str))

by_cell = (night.groupby(["device_id", "cell"])
                .agg(n=("ts", "size"), nights=("ts", lambda s: s.dt.date.nunique()))
                .reset_index())
home = (by_cell.sort_values(["nights", "n"], ascending=False)
               .drop_duplicates("device_id")
               .query("nights >= 5")
               .merge(cell_to_oa, on="cell")[["device_id", "oa_id"]])

panel_visits = (visits.merge(home, on="device_id")
                      .groupby(["oa_id", "venue_id"]).size().rename("panel_visits").reset_index())'''},
   "note": "Devices with no stable overnight cluster are tourists, commercial vehicles or shift workers. "
           "Dropping them is right for a catchment, but count them — if they are a large share of visits at "
           "a transport-hub site, that site's catchment is genuinely different and should be modelled "
           "separately rather than forced into the same framework."},

  {"title": "Expand the panel, and shrink the expansion",
   "why": "This is the step that decides whether the numbers mean anything. The panel is a biased sample: "
          "penetration in this build runs nearly six times higher in young urban segments than in older "
          "rural ones. Expand each output area by its own penetration — but shrink that penetration toward "
          "the segment mean, because twelve devices in a population of three hundred gives a factor that "
          "swings on one commuter.",
   "code": {"python": '''M_PSEUDO = 400.0        # pseudo-population for the shrinkage

pen_group = (oa.groupby("mosaic")
               .apply(lambda g: g.panel_devices.sum() / g.population.sum())
               .rename("pen_group"))
oa = oa.join(pen_group, on="mosaic")

# Empirical Bayes: each area's penetration pulled toward its segment
oa["pen_hat"]   = (oa.panel_devices + M_PSEUDO * oa.pen_group) / (oa.population + M_PSEUDO)
oa["expansion"] = 1.0 / oa.pen_hat

panel = panel.merge(oa[["oa_id", "expansion"]], on="oa_id")
panel["visits"] = panel.panel_visits * panel.expansion''',
   },
   "out": "penetration by Mosaic group\n  Rental Hubs        7.1%\n  City Prosperity    6.8%\n"
          "  ...\n  Senior Security    1.4%\n  Vintage Value      1.2%\n\nspread 5.8x",
   "note": "Pool at the level the bias actually operates on. Mosaic segment is the right choice here because "
           "device ownership tracks age and affluence; if your panel provider skews by handset OS instead, "
           "pool on something that correlates with that."},

  {"title": "Fit the distance decay by maximum likelihood",
   "why": "Do not assume a decay exponent. Estimate it from the choice shares the panel observed, using a "
          "multinomial likelihood. There is a useful property hiding here: panel penetration is a single "
          "scalar per output area, so it cancels out of the within-area shares completely. The decay comes "
          "from the raw counts; only the volumes need expanding.",
   "code": {"python": '''def dmat(oa, sites, road_factor=1.25):
    d = np.hypot(oa.x.to_numpy()[:, None] - sites.x.to_numpy()[None, :],
                 oa.y.to_numpy()[:, None] - sites.y.to_numpy()[None, :])
    return np.maximum(d, 0.35) * road_factor      # floor stops a co-located area exploding

D = dmat(oa, own_sites)
A = own_sites.attract.to_numpy()          # (sqft/1000)**0.55 * format multiplier

def conditional_ll(beta):
    util = A[None, :] * D ** (-beta)
    logp = np.log(util / util.sum(axis=1, keepdims=True))
    return float((V_panel * logp).sum())   # V_panel: RAW counts, area x site

# Coarse sweep, then refine -- with this many observations the peak is very sharp
grid = np.arange(0.60, 4.001, 0.01)
lls  = np.array([conditional_ll(b) for b in grid])
peak = grid[lls.argmax()]

fine  = np.arange(peak - 0.05, peak + 0.05, 0.0005)
flls  = np.array([conditional_ll(b) for b in fine])
BETA  = float(fine[flls.argmax()])
inside = fine[flls >= flls.max() - 2.0]          # 2 log-likelihood units
BETA_LO, BETA_HI = inside.min(), inside.max()''',
   },
   "out": "fitted beta 1.847  [1.844, 1.850]     (true value in the generator: 1.85)",
   "note": "The interval is narrow because the panel is large, and that precision is slightly misleading. "
           "The real uncertainty is not in the value of a single decay parameter — it is whether one decay "
           "applies to every format. Fit it separately for high street, retail park and transport hub before "
           "you trust it on a mixed estate."},

  {"title": "Recover total demand, including what goes to competitors",
   "why": "You observe visits to your own sites. You need total demand in each area, because a new site "
          "draws from competitors as well as from you. Divide expanded own-chain visits by the modelled "
          "own-capture share and the rest follows.",
   "code": {"python": '''choice = pd.concat([own_sites.assign(own=1), competitors.assign(own=0)], ignore_index=True)

def huff(sites, beta=BETA):
    util = sites.attract.to_numpy()[None, :] * dmat(oa, sites) ** (-beta)
    return util / util.sum(axis=1, keepdims=True)

P_all     = huff(choice)
own_share = P_all[:, choice.own.to_numpy() == 1].sum(axis=1)

# total demand implied by what we actually observed
DEMAND = V_expanded.sum(axis=1) / np.clip(own_share, 1e-6, None)

def predict(estate):
    ch = pd.concat([estate.assign(own=1), competitors.assign(own=0)], ignore_index=True)
    P = huff(ch)
    return DEMAND[:, None] * P[:, ch.own.to_numpy() == 1]''',
   },
   "out": "own share of modelled demand  38%\nimplied total market            43.0m visits a year",
   "note": "Leaving competitors out of the choice set is the most common error in applied Huff work. Without "
           "them the chain captures 100% of demand everywhere, catchments are far too large, and displaced "
           "trade has nowhere to go — so cannibalisation comes out enormous."},

  {"title": "Validate against how the estate actually trades",
   "why": "Before forecasting a site that does not exist, show the model explains the ones that do. This is "
          "the step that earns the right to the rest of the analysis, and it is the one most often skipped "
          "because it is the one that can fail.",
   "code": {"python": '''V_fit = predict(own_sites)
own_sites["pred_revenue"] = (V_fit * oa.spend.to_numpy()[:, None]).sum(axis=0)

x, y = own_sites.pred_revenue.to_numpy(), own_sites.revenue.to_numpy()
slope, intercept = np.polyfit(x, y, 1)
resid = y - (slope * x + intercept)
r2   = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
mape = np.mean(np.abs(resid) / y)

print(f"R2 {r2:.2f}   MAPE {mape:.1%}")''',
   },
   "out": "R2 0.82   MAPE 22.1%",
   "note": "Do not expect 0.95. A catchment model cannot see manager quality, frontage, seating or the bus "
           "stop outside, and a model that fits that well on trading revenue is almost certainly overfitted "
           "or leaking the target. Four fifths of the variance from geography and demographics alone is a "
           "good result and a defensible one."},

  {"title": "Charge every new site for what it takes",
   "why": "A new site's forecast is not its gross draw. Recompute the whole choice model with the site "
          "added, and the difference at every existing store is trade the group already had. Then do it "
          "again with the entire pipeline at once, because the proposed sites compete with each other too — "
          "and no seller's appraisal pack has ever been built that way.",
   "code": {"python": '''def appraise(new_sites, incumbent=own_sites):
    before = predict(incumbent)
    after  = predict(pd.concat([incumbent, new_sites], ignore_index=True))
    n = len(incumbent)
    new_rev     = (after[:, n:] * spend[:, None]).sum(axis=0)
    transferred = ((before - after[:, :n]) * spend[:, None]).sum(axis=0)
    return new_rev, transferred.sum()

# (a) how a seller appraises: one at a time against today's estate
solo = [appraise(pipeline.iloc[[i]]) for i in range(len(pipeline))]
solo_net = sum(float(r[0]) - r[1] for r in solo)

# (b) what actually happens: all forty open
gross, transferred = appraise(pipeline)
portfolio_net = gross.sum() - transferred

print(f"solo appraisal  {solo_net/1e6:.1f}m")
print(f"as a portfolio  {portfolio_net/1e6:.1f}m")
print(f"missed by appraising individually  {(solo_net - portfolio_net)/1e6:.1f}m")''',
   },
   "out": "solo appraisal  14.6m\nas a portfolio  13.1m\nmissed by appraising individually  1.5m"},
 ],
 "pitfalls": [
  {"title": "Expanding the panel with one national factor",
   "body": "The obvious first move, and it overstates the market by <strong>19%</strong> in this build — "
           "because the panel over-represents young urban segments and those are also the heaviest users of "
           "the format. Bias in the panel and bias in the behaviour point the same way, so the errors "
           "compound rather than cancel. What makes it dangerous is that it barely moves the relative "
           "ranking of sites: the league table looks fine while every market-size and whitespace number "
           "built on it is a fifth too big."},
  {"title": "A gravity model with no competitors in it",
   "body": "Huff probabilities sum to one across the choice set. If the choice set is only your own estate, "
           "you capture 100% of demand in every area, catchments extend absurdly far, and displaced trade "
           "has nowhere to go — so cannibalisation looks catastrophic. Competitor locations are cheap and "
           "the model is wrong without them."},
  {"title": "Appraising pipeline sites one at a time",
   "body": "Every site appraisal pack evaluates each site against the estate as it stands today. Open all "
           "of them and several compete with each other as well as with the incumbents. Here that gap is "
           "£1.5m — small against the total, large against the marginal sites that decide whether the "
           "back half of a roll-out plan happens at all."},
  {"title": "Straight-line distance where geography bites",
   "body": "A road factor on Euclidean distance is a reasonable approximation across a flat region and a bad "
           "one across an estuary, a motorway with no junction, or a city with a river through it. It will "
           "systematically overstate catchments on the wrong side of the barrier. Use drive-time isochrones "
           "from a routing engine for anything that reaches a valuation."},
 ],
 "validate": {
  "intro": "Two of these check the arithmetic. The third checks the method itself, and it is only possible "
           "because the synthetic world has a known answer.",
  "why": "The generator runs a gravity model with a decay of exactly 1.85 and then hands the analysis a "
         "biased panel sample. If the fitted interval stops containing the true value, something in the "
         "expansion or the likelihood has broken and the build should fail rather than publish.",
  "code": {"python": '''def check():
    # 1. probabilities are probabilities
    assert np.allclose(huff(choice).sum(axis=1), 1.0), "Huff shares must sum to 1 per area"

    # 2. the model earns the right to forecast
    assert r2 > 0.5, f"gravity model explains too little of actual trade (R2 {r2:.2f})"

    # 3. the method recovers the truth it was never shown
    assert BETA_LO <= TRUE_BETA <= BETA_HI, (
        f"fitted beta {BETA:.3f} [{BETA_LO:.3f}, {BETA_HI:.3f}] misses truth {TRUE_BETA}")

    # 4. a portfolio always cannibalises itself at least a little
    assert portfolio_net < solo_net, "portfolio net should sit below the sum of solo appraisals"

    print(f"checks: beta interval contains {TRUE_BETA}, R2 {r2:.2f}, shares sum to 1")''',
   },
  "out": "checks: beta interval contains 1.85, R2 0.82, shares sum to 1"},
 "scale": {
  "body": "This is the one technique in the series where Spark is not a nicety. A national ping feed is "
          "billions of rows a month, and steps one to three — stop detection, venue attribution and home "
          "inference — all run against it. What comes out is one row per output area per venue: a few "
          "hundred thousand rows at most, and in this build twenty thousand. Every model step after that is "
          "a dense matrix of a few hundred by a few hundred, which NumPy handles in milliseconds and Spark "
          "would handle badly.",
  "notes": [
   "<strong>Filter on accuracy before anything else.</strong> It is the cheapest filter available and it removes the rows most likely to produce a false attribution.",
   "<strong>Partition pings by date and bucket by device_id.</strong> Every window function in step one partitions by device; bucketing avoids re-shuffling the largest table in the job.",
   "<strong>Broadcast the venue table.</strong> A few hundred rows against billions — without the hint Spark will plan a sort-merge join and the stage will never finish.",
   "<strong>Never join on a distance predicate.</strong> Bin to a grid (or H3, or Sedona) and join on the bin, then filter exactly. This is the difference between minutes and days.",
   "<strong>Persist the area-venue visit matrix</strong> with the panel snapshot date. Providers restate history, and a catchment you cannot reproduce is worthless in a dispute.",
   "<strong>Keep device-level data out of the deliverable.</strong> Aggregate to output area inside the pipeline; nothing downstream needs a device id, and nothing downstream should have one.",
  ]},
 "foot_title": "Technique 04 — Trade Area & Footfall.",
 "foot_body": "Tutorial companion to the Project Ferryman demo. All figures synthetic.",
}

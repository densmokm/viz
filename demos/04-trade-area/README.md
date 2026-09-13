# 04 — Trade Area & Footfall

**Live demo:** https://claude.ai/code/artifact/5cf358a8-34ea-4190-9b5a-cc7217fd63b4
**Tutorial:** [How to build a trade area model from device data](https://claude.ai/code/artifact/55ce8a12-02a9-4a4f-a926-ec7f7e45ce8d)

Target: *Tarnbrook Bakehouse* (synthetic), a UK food-to-go and bakery-café chain
of 84 sites, sponsor-backed and in market with a 40-site roll-out plan.
Deal codename *Project Ferryman*. Stage: **commercial due diligence.**

---

## 1. What it is

Geospatial analysis of a multi-site estate: how strong each catchment really is,
how well it fits the format, how much competition sits inside it, and — the
question the equity story turns on — how much of a proposed roll-out is genuinely
new trade rather than trade moved from stores the buyer already owns.

## 2. Ingredients

| Input | Scale | Why |
|---|---|---|
| **Mobile device pings** | billions of rows/month | Stop detection and venue attribution turn these into visits; overnight clustering gives each device a home area |
| **Panel penetration by area** | one row per output area | Without it you cannot expand the panel, and expansion is the whole game |
| **Experian Mosaic** | one row per output area | Segment and consumer expenditure — drives spend per visit and demographic fit |
| **Population by output area** | census / mid-year | The denominator for everything |
| **Own estate** | ~100 rows | Location, floor area, format, **trading revenue** — the calibration target |
| **Competitor locations** | ~200 rows | The rest of the choice set. A Huff model without them is wrong |

## 3. Key calculations

**Panel expansion with shrinkage.** Penetration runs 5.8× higher in young urban
segments than older rural ones. Each area is expanded by its own penetration,
shrunk toward its Mosaic-group mean with a pseudo-population of 400 — because
twelve devices in a population of 300 gives a factor that swings on one commuter.

**Distance decay by maximum likelihood.** Not assumed — estimated from the
multinomial choice shares the panel observed. A useful property: penetration is a
single scalar per output area, so it cancels out of within-area shares entirely.
The decay comes from the raw counts; only the volumes need expanding.

**Total demand inferred, not assumed.** Expanded own-chain visits divided by the
modelled own-capture share gives each area's total demand, including trade going
to competitors.

**Cannibalisation, computed twice.** Site by site against today's estate — which
is how sellers appraise — and as a portfolio with all 40 open, which is what
actually happens.

## 4. The demo

```bash
pip install pandas numpy
cd demos/04-trade-area
python3 src/generate_data.py   # 598 output areas, 84 sites, 214 competitors, a biased panel
python3 src/analyse.py         # expansion, MLE fit, validation, cannibalisation, checks
python3 src/build_page.py      # -> trade-area.html
```

The generator runs a gravity model with a **known** decay of 1.85, then hands the
analysis a biased panel sample. `analyse.py` asserts that the fitted likelihood
interval contains that value — if the method stops working, the build fails.

## 5. The "so what"

**The roll-out plan is in the model at £42.6m. It is worth £13.1m.**

| | |
|---|---:|
| 40 sites × estate-average unit revenue | £42.6m |
| Modelled gross draw | £20.1m |
| Taken from existing stores | −£7.0m |
| **Net new group revenue** | **£13.1m** |

Only 12 of the 40 clear a £400k hurdle once cannibalisation is charged to them.
The gap between the first two rows is site quality: the estate average is set by
mature stores in the best catchments, and the remaining whitespace is not those
catchments.

**Three findings that carry:**

- **Panel bias is a level problem, not a ranking problem.** A single national
  expansion factor overstates the market by **19.3%**, but per-site catchment
  error is only −2% to +4%. The site league table looks fine while every
  market-size number built on it is a fifth too big — which is exactly why the
  error survives unnoticed.
- **The model earns its forecast.** It explains **82%** of the variance in how
  the existing 84 sites actually trade (MAPE 22%). A catchment model that cannot
  explain the estate you can see has no business forecasting one you cannot.
- **Site-by-site appraisal misses £1.5m.** Appraised individually the pipeline
  nets £14.6m; opened together it nets £13.1m, because the proposed sites compete
  with each other. Every appraisal pack is built the first way.

**What a deal team does with it.** Ask for the individual site appraisals and two
questions settle the valuation: what unit revenue does each assume, and were they
appraised as a programme or one at a time. Post-close, the calibrated model is
worth more than it was in diligence — it becomes the site-selection tool that
stops the estate opening stores which move trade around the portfolio.

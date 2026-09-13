# 01 — Alt Data Triangulation

**Live demo:** https://claude.ai/code/artifact/573d0f94-5d11-4e02-8ed7-064c98752cb3
**Tutorial:** [How to triangulate outside-in data into a defensible view](https://claude.ai/code/artifact/902859a7-3384-4a18-8c3e-b6d734b3c9f1)

Target: *Kestrel Veterinary Group* (synthetic), a UK veterinary practice roll-up
preparing to come to market. Deal codename *Project Harrier*.
Stage: **pre-deal / commercial DD — no data room access.**

---

## 1. What it is

Before you have internal data you still have to form a view. Alt data
triangulation is the discipline of assembling that view from what you can buy or
observe — filings, market data, web panels, reviews, job boards, expert networks
— and being explicit about how much weight each deserves.

The business question: **which parts of the management narrative does the outside
world corroborate, and which does it contradict?** And, just as important, which
parts cannot be seen from outside at all — because those are precisely the
questions that should dominate the first information request.

Here, seven claims from the IM produce four challenges, one contested verdict,
one supported, and one that outside data cannot reach.

## 2. Ingredients

Eleven subscriptions, grouped into **eight independent source families**. The
grouping matters more than the count — two review platforms agreeing is one
family, not two.

| Source | Family | Reliability | Lag | What it gives you |
|---|---|---:|---:|---|
| Companies House | Regulatory filings | 0.95 | 2.5m | Dated acquisitions, estate size, filed accounts |
| S&P Capital IQ | Market data | 0.90 | 1.5m | Listed comparables, sector growth |
| Preqin | Market data | 0.82 | 2.0m | Sponsor activity, transaction counts |
| Gain.Pro | Market data | 0.75 | 3.0m | Private universe, ownership, market structure |
| Google Reviews | User reviews | 0.72 | 0.2m | Per-site volume and rating — a throughput proxy |
| AlphaSense | Expert network | 0.70 | 0.5m | Broker and expert transcripts, regulatory commentary |
| Indeed | Labour market | 0.68 | 0.2m | Vacancy volume, time-to-fill |
| SimilarWeb | Web panel | 0.62 | 0.5m | Sessions, channel mix, branded search |
| Trustpilot | User reviews | 0.58 | 0.2m | Rating trend, complaint themes |
| Glassdoor | Employee reviews | 0.55 | 0.5m | Staff sentiment, by function |
| Quid | Media | 0.50 | 0.2m | News volume and sentiment |

The generator emits 23 signal series over 30 months, plus a practice-level ground
truth panel the engine is **not** allowed to use — except once, at the end, to
check that its own estimate was honest.

## 3. Key calculations

**Signal standardisation.** Each signal is compared over a six-month window
against the same window a year earlier, peer-adjusted where a peer series exists,
then standardised by *the standard error of that difference* — residual standard
deviation around the trend, scaled by `√(2/window)`. An earlier build divided by
annualised month-to-month volatility, which is roughly six times too large and
crushed every signal toward zero. Series that touch zero are handled additively;
log-transforming a monthly count with zero months produces nonsense.

**Two test modes.** Direction is not enough when a claim carries a number.
*Trend* mode asks whether a series is moving the way the claim implies. *Level*
mode asks whether the observed value matches the claimed one — `d = tanh((observed
− claimed)/tolerance)`.

**Weighting.** `w = reliability × recency × sample adequacy`, where recency is
`exp(−lag/9)` and adequacy is `log(1+n)/log(1+500)` capped at 1.

**Scoring.** For each claim:

```
E = Σ(w·d) / Σw                  evidence,  −1 to +1
C = |Σ(w·d)| / Σ(w·|d|)          coherence, 0 to 1
F = 1 − e^(−0.9(families−1))     independence
M = 1 − e^(−Σw / 1.6)            evidence mass

confidence = M × √F × √C
```

All three must hold. A single authoritative source cannot produce a confident
verdict on its own; nor can two sources that disagree. This is the reason the
framework exists rather than a weighted average — and the reason a verdict
distinguishes *"we cannot see this"* (low mass) from *"the sources disagree"*
(low coherence). Those are different findings and hiding them behind one label
loses the more interesting one.

**Bounding organic growth from filings alone.** The flagship calculation. Let `r`
be revenue per legacy practice-month and `α` the size of an acquired practice
relative to a legacy one:

```
R₀ = r(LPM₀ + α·APM₀)                          R₁(LPM₀ + α·APM₀)
R₁ = r(1+g)(LPM₁ + α·APM₁)        →    1+g = ──────────────────
                                               R₀(LPM₁ + α·APM₁)
```

Every term on the right is observable — group revenue from filed accounts,
practice-months from dated Companies House filings — except `α`. So the honest
answer is a band, not a point, and the width of the band names the single number
to request first.

**Event study.** A practice's Google profile survives a change of ownership, so
acquired practices can be aligned on their completion month and compared against
the never-acquired estate as a control.

## 4. The demo

An interactive page. The centrepiece is a claim scorecard where every row carries
two numbers — evidence and confidence — and expands to show the signals beneath
it, with source, family, observed levels and weight. Alongside it, a claim × family
matrix where the *gaps* are as informative as the colours.

```bash
pip install pandas numpy
cd demos/01-alt-data-triangulation
python3 src/generate_data.py   # 23 signals x 30 months + a 189-practice ground truth panel
python3 src/analyse.py         # triangulation engine + honesty check
python3 src/build_page.py      # → outside-in.html
```

`analyse.py` asserts that its own outside-in band contains the true same-store
growth rate. If the method stops working, the build fails.

## 5. The "so what"

| Claim | Verdict | Confidence |
|---|---|---:|
| Like-for-like growth of 9%, driven by clinical demand | **Challenged** | 75% |
| Membership plan delivers 40% higher lifetime value | *Not testable outside-in* | 14% |
| We are the employer of choice in the profession | **Challenged** | 64% |
| Digital booking platform driving new client acquisition | *Contested* | 33% |
| Consolidation runway substantial: 60% independent | **Challenged** | 39% |
| Pricing is in line with the market | **Challenged** | 50% |
| Greater scale than any regional competitor | Supported | 50% |

The headline: reported group growth of 19.3% decomposes into acquisition
contribution and organic, and the filings imply organic growth of **2.3% to 7.4%**
— central estimate 5.1%, against 9% claimed. On a 12× entry multiple over a
four-year hold that gap is worth about **£70m** of enterprise value. *(The
synthetic ground truth is 5.6%: inside the band, 0.5pp from the central estimate.
On a live deal you never get that check, which is exactly why the method reports
a band and names its assumption.)*

Underneath it, three findings that carry into the model:

- **The clinical engine is staffing-constrained.** Glassdoor rating falls while
  the peer group holds flat; median time-to-fill a vet role goes from 34 to 69
  days. You cannot grow clinical revenue faster than you can hire clinicians.
- **Integration destroys the thing being bought.** Acquired practices lose 0.47
  stars within nine months of completion and do not recover, against zero drift
  in the control estate. Review volume — a throughput proxy — falls 4.2%.
- **Pricing is a regulatory exposure, not a service issue.** Reviews mentioning
  price or billing triple while peers stay flat, alongside a sharp rise in expert
  transcripts citing the CMA's pricing review.

**What a deal team does with it.** Reprice the growth assumption before spending
a penny on confirmatory diligence. Then send an information request built around
what outside data *could not* settle — practice-level revenue with completion
dates, clinician headcount and locum spend, membership cohort economics — rather
than a generic checklist. The output of a good outside-in phase is a sharper
question list, not a view for its own sake.

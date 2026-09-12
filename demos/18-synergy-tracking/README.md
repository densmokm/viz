# 18 — Synergy Tracking

**Live demo:** https://claude.ai/code/artifact/b18eee14-aa3a-497e-8b8c-7c07101062a8

*Wexford Industrial Group* acquired *Pentland Technical Services* (both synthetic)
14 months ago. Deal codename *Project Anvil*. The deal model carried £24.5m of
run-rate synergies by month 24.
Stage: **post-deal value creation.**

---

## 1. What it is

A synergy tracker answers one question for a board: **will the value in the deal
model actually arrive, and if not, when do we need to know?**

Most trackers report a single completion percentage against plan. That number
averages a cost programme that is working with a revenue programme that is not,
and the blend looks survivable until month 18, when there is no time left to act.
This one separates them, weights every initiative by what history says converts,
and reports the one thing a PMO almost never puts in front of a board: whether
the target is reachable at all.

## 2. Ingredients

| Input | Fields | Why |
|---|---|---|
| **Initiative register** | value, owner, workstream, stage, *date entered stage* | The stage date is what makes stall detection possible, and it is the field most often missing |
| **Monthly realised benefit** | actual P&L impact by initiative | So run-rate and in-year can be reported separately |
| **Deal model schedule** | committed value and phasing, by category | The thing being tracked against |
| **Cost to achieve** | budget and spend by initiative | Where underspend is often the real signal |
| **Prior deal outcomes** | the same register from past integrations, with what each initiative was finally worth | Without this, confidence weighting is opinion |

Generated: **46 initiatives** across eight workstreams, plus **260 initiatives
from prior deals** with known outcomes.

## 3. Key calculations

**Run-rate versus in-year P&L.** The distinction most trackers collapse. An
initiative delivered in month 12 carries its full annualised value into the
run-rate and almost none of it into this year's EBITDA. Both are computed and
reported separately; the gap between them is stated explicitly.

**Conversion, estimated not assigned.** Stage-to-delivery rates come from the
260 prior initiatives, split by stage *and* by cost-versus-revenue, smoothed
toward the overall rate where a cell is thin:

```
p(stage, type) = (delivered + α·prior) / (n + α),   α = 4
```

Revenue converts materially worse from every open stage — 37% from Validated
against 60% for cost. Delivered and banked initiatives are excluded from the
table entirely: they are already counted at realised value.

**Realisation as a distribution.** Delivered initiatives land at a mean of 89% of
their own estimate with a standard deviation of 22%. The simulation draws from a
gamma matched to those two moments rather than applying a flat haircut.

**The bridge**, which reconciles to £0.00:

```
Deal model → re-estimation → conversion risk → realisation haircut
           → dis-synergy → risk-adjusted forecast
```

**Earned value.** `SPI = Σ(plan × stage credit) / Σ(plan × planned progress)`,
where planned progress is *time-phased* over a six-month delivery window rather
than stepping at the planned month. A step function makes SPI explode whenever a
workstream's work is scheduled late — an earlier build produced an SPI of 3.15
that meant nothing. Earned value is held to the plan value base so the index
measures schedule, not scope.

**The ceiling.** Give every remaining initiative a 100% conversion rate and full
delivery of its current estimate, and total the register. If the deal model sits
above that line, the gap cannot be closed from the current pipeline — which is a
completely different conversation from being behind.

## 4. The demo

```bash
pip install pandas numpy
cd demos/18-synergy-tracking
python3 src/generate_data.py   # 46 initiatives + 260 from prior deals
python3 src/analyse.py         # conversion model, bridge, 20k simulations, checks
python3 src/build_page.py      # → synergy-tracker.html
```

`analyse.py` asserts the bridge ties, that workstream and category splits
reconcile to the total, and that the simulation median agrees with the analytic
point estimate.

## 5. The "so what"

**Deal model £24.50m. Risk-adjusted forecast £13.80m — 56%.**

| | Deal model | Secured | Risk-adjusted | % |
|---|---:|---:|---:|---:|
| Cost | £16.5m | £9.4m | £14.6m | 88% |
| Revenue | £8.0m | £0.5m | £2.9m | 36% |

Cost is broadly landing. Revenue is not: 13 of 18 revenue initiatives are stalled
in stage beyond the point history says they recover, and cross-sell sits at 35% of
plan with an SPI of 0.47.

**Three findings worth the board's time:**

- **The model is unreachable from this pipeline.** Perfect execution of every
  remaining initiative reaches £19.9m — £4.6m short of the model before any
  discount for reality. Closing the gap needs roughly £12m of run-rate from
  initiatives that do not yet exist, identified and executed inside ten months.
  Across 20,000 simulations the programme reached the model not once.
- **Run-rate is not EBITDA.** £10.4m of run-rate is recognised; £6.2m has actually
  reached the last twelve months of P&L. Reporting the first as the second is how
  a programme looks fine until the audited numbers arrive.
- **The cost-to-achieve underspend is the tell.** Total spend is 97% of budget,
  which looks like control — until you see that all three underspending
  workstreams are revenue. You do not deliver cross-sell without spending on it;
  the underspend is the same stall showing up in a different ledger.

**What a sponsor does with it.** Re-forecast now, at month 14, while there are ten
months to act — a programme that re-forecasts at month 20 has told the board
something it can no longer do anything about. Then treat revenue synergies as a
different governance problem: named accounts, a seller compensated on the
cross-sell, and a monthly pipeline review rather than a quarterly status paper.

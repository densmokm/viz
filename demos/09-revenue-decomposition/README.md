# 09 — Revenue Decomposition

**Live demo:** https://claude.ai/code/artifact/230bde63-86eb-44b4-a8fa-d86185f0a70f
**Tutorial:** [How to build a revenue bridge that ties](https://claude.ai/code/artifact/2ba6fc7e-e46b-4bba-960f-5a281011aea6)

Target: *Meridian Coatings Ltd* (synthetic), a UK specialty industrial coatings
distributor. Comparison: FY24 → FY25, years ending 31 March. Deal codename
*Project Palette*.

---

## 1. What it is

A revenue bridge splits the movement between two periods into the forces that
caused it — price, volume, mix, new and lost customers, one-off work, currency —
so that a buyer can tell the difference between a business that is growing and a
business whose revenue line went up.

The business question in a deals context is blunt: **how much of last year's
growth will still be there next year?** Headline growth is the number in the
teaser. Maintainable growth is the number the multiple should be applied to, and
the two are frequently not close.

On this demo they are not close at all. Management reports **+18.6%**. The
invoice ledger says the underlying rate is **−1.8%**.

## 2. Ingredients

Everything on the page is derived from one table. On a live deal this is a sales
day-book extract or an ERP invoice-line dump — usually a single overnight request.

| Input | Fields | Why it is needed |
|---|---|---|
| **Invoice lines** *(required)* | date, account, SKU, quantity, net value | The only non-negotiable input. Without quantity you cannot separate price from volume — and that separation is the whole technique. |
| **Product master** | SKU → family, list price, standard cost | Drives mix and gross margin |
| **Customer master** | account, segment, channel, region, first order date | Drives the customer lens and cohort work |
| **Order-type flag** | standard / project / contract | Isolates one-off work so it can be quantified rather than argued about |
| **FX rate table** | monthly rates actually used for translation | Separates translation from trading |
| **Input cost index** | the index referenced by passthrough clauses | Tests whether pricing is the company's or the market's |

The synthetic generator produces **75,531 invoice lines** across 64 SKUs, 460
accounts and 24 months, with realistic seasonality, churn and acquisition.

## 3. Key calculations

**Price / volume / mix.** A three-way split defined so it sums to the movement
exactly, with no residual to explain away:

```
Volume = (Q₁ − Q₀) × p̄₀           change in units at prior-year average price
Price  = Σ q₁ × (p₁ − p₀)          per-SKU realised price change at current volumes
Mix    = Σ q₁ × p₀ − Q₁ × p̄₀       basket shift, valued at prior-year prices

       ∴  Volume + Price + Mix ≡ R₁ − R₀
```

The identity holds for *any* choice of `p₀` on SKUs that did not trade in the
prior year (we use `p̄₀`), which is what makes it safe against a moving catalogue.

**Customer lens.** The same movement partitioned by account: lost, new,
expansion, contraction. Also an exact partition.

**Unified bridge.** The two nest — retained accounts are decomposed into
price/volume/mix, accounts that arrived or left are carried whole:

```
R₀ − Lost + New + [retained: Volume + Price + Mix] + One-off + FX = R₁
```

All three views are computed on constant-currency revenue, with FX carried as a
single translation line. `analyse.py` asserts every reconciliation — if the
bridge does not tie, the script fails rather than publishing a number.

**Passthrough normalisation.** Every line is re-priced as if contractual resets
were instant rather than lagged a quarter, giving a normalised margin and a
quantified timing windfall. The same mechanism prices the FY26 reversal exposure
at the exit index.

**Mix, split two ways.** Between-family mix (families trading places, weighted by
how far their price sits from the book average) versus within-family SKU churn —
because "mix" as a single number tells you nothing about whether it is structural.

## 4. The demo

An interactive HTML page. The core interaction is three tabs on one waterfall:
**Unified**, **Commercial lens**, **Customer lens** — the identical £7.80m
movement read three ways, each reconciling to the same closing number. A
*Shade by durability* toggle hatches the components that do not repeat in FY26,
and a table view gives the WCAG-clean equivalent of every chart.

Supporting analysis: the input-cost vs. realised-price lag, reported vs.
normalised gross margin, like-for-like price realisation by segment, quarterly
growth stripped of the one-off contract, product-family mix movement, customer
cohort quality, and a quality-of-growth step-down.

```bash
pip install pandas numpy
python3 src/generate_data.py   # 75,531 synthetic invoice lines (seeded)
python3 src/analyse.py         # bridge + reconciliation assertions → data/results.json
python3 src/build_page.py      # → revenue-bridge.html
```

The seed is fixed, so the figures are reproducible. Change it and every number
on the page rebuilds — the analysis discovers the bridge from the lines without
being told what it should find, which is the point: the same code runs unchanged
against a real day-book.

## 5. The "so what"

What the analysis actually found:

| Component | Movement | Durability |
|---|---:|---|
| Price (raw-material passthrough) | +£4.75m | **At risk** — resets are symmetric and the index has already rolled over |
| One-off infrastructure contract | +£2.85m | **Non-recurring** — one account, completes FY26 Q1 |
| New customers | +£2.61m | **Partly recurring** — 22% of the H1 intake had stopped ordering by Q4 |
| Lost customers | −£1.96m | Recurring — 74 accounts, and the loss compounds |
| Mix | −£0.81m | Recurring — structural drift to lower-ASP product |
| FX translation | +£0.38m | Non-recurring |
| **Volume (organic)** | **−£0.03m** | The business sold no more coating than the year before |

Reported growth **+18.6%** → ex one-off and FX **+10.9%** → ex passthrough price
**−0.5%** → after haircutting new logos for observed attrition **−1.8%**.

And a second finding that falls out of the same normalisation: reported gross
margin improved 200bp, but normalised for reset timing it went *backwards* 52bp.
The improvement is a **£1.61m** passthrough timing swing — roughly £14m of
headline price at a 9× multiple — with a further **£1.14m** of contractual
repricing already scheduled into FY26.

**What a deal team does with it.** Strike any earn-out on gross profit or volume,
never revenue — a revenue-linked mechanism pays the seller for resin inflation.
Normalise the completion-accounts margin rather than taking the FY25 outturn. And
the 100-day plan writes itself: price architecture in the two segments recovering
least, a mix defence in marine, and a concentration strategy for a top 10 that
has gone from 27% to 32% of revenue.

**Why it lands in a meeting.** Nobody argues with a bridge that ties. The three
lenses reconcile to £0.00, which moves the conversation off "is your analysis
right" and onto "what are you going to do about the £2.85m contract that ends
in April".

# 16 — Virtual Data Room Analytics

**Live demo:** https://claude.ai/code/artifact/b50804ed-996e-472a-9aa8-df7b184ec06c
**Tutorial:** [How to read bidder intent from a data room log](https://claude.ai/code/artifact/746bf3be-f3ae-48d2-94bb-8c36f813f3e3)

Target: *Thornbury Precision Group* (synthetic), a UK precision components
manufacturer serving aerospace and medical, sold by its sponsor through a
competitive process. Deal codename *Project Lantern*.
Stage: **SPA and transaction support — sell-side, Phase 2, week 9.**

---

## 1. What it is

Every VDR platform logs who opened which document, when, and for how long. That
log is the most honest read available on bidder intent: it is behaviour, not what
someone tells the banker on a Friday call.

Four questions, in descending order of what they're worth:

1. **Which bidders are actually working the deal?**
2. **Which are about to drop?**
3. **Where is the deal risk?** The documents everyone reads, twice, are the issues
   that come back as SPA mark-ups.
4. **What did the sell-side waste preparing?**

## 2. Ingredients

Four standard platform exports. No bespoke instrumentation, no vendor
cooperation beyond a report request.

| Input | Fields | Why |
|---|---|---|
| **Access log** | timestamp, user, document, action, duration | The whole technique sits on this |
| **Document index** | folder, category, page count | Normalises attention — a 168-page valuation isn't a 4-page memo |
| **User register** | organisation, role, adviser flag | Seniority is the signal; an analyst browsing is not a partner reading |
| **Q&A log** | question, category, bidder, days to answer | Question flow separates buyers from browsers |
| **Prior process outcomes** | same features from past deals + who bid | This is what makes the model a model |

The generator emits **11,500 access events** across 432 documents, 60 users and
six bidders over nine weeks, plus a register of **140 bidders from prior
processes** with known outcomes.

## 3. Key calculations

**Bidder features**, on identical definitions to the historical register:
coverage, dwell time per page (indexed to the room median), share of time by
senior staff, adviser firms engaged, three-week activity trend, days idle, and
questions submitted.

**Withdrawal model.** Logistic regression by IRLS on the 140 prior bidders —
fitted, not hand-weighted. A hand-tuned "bidder health score" is quicker and does
not survive the first partner who asks where the weights came from. Live features
are clipped to the fitted range so no prediction extrapolates beyond the evidence.

**Engagement index.** Percentile-weighted effort against the historical
distribution. Dwell time is *shrunk toward coverage* for bidders with little
activity — thirty page-views is not enough to estimate how carefully someone
reads, and without the shrinkage a near-absent bidder outranked one with six times
the hours.

**Competitive tension.** The exact Poisson-binomial over the six withdrawal
probabilities gives the full distribution of how many bids actually arrive — not
a simulation, and not the number on the process letter.

**Document heat.** Total attention, breadth across bidders and revisit frequency,
each standardised and summed. Per-page intensity alone was tried first and
penalises exactly the long documents that carry the risk.

**Attention profile.** Each bidder's category share indexed against *the mean of
per-bidder shares*, not the pooled total — the pooled total is dominated by
whoever reads most, so the heaviest reader scores ~1.0 everywhere by construction.

## 4. The demo

A bidder board where each row carries engagement, fitted withdrawal probability, a
weekly activity sparkline and behavioural flags; the model's coefficients and
calibration; a bidder × category attention matrix; the hottest documents in the
room; and the vendor's own prep waste.

```bash
pip install pandas numpy
cd demos/16-vdr-analytics
python3 src/generate_data.py   # 11.5k access events, 432 documents, 140 historical bidders
python3 src/analyse.py         # features, fitted model, heat scoring, checks
python3 src/build_page.py      # → dataroom.html
```

## 5. The "so what"

| Bidder | Type | Engagement | p(withdraw) | Read |
|---|---|---:|---:|---|
| Marlowe Partners | Sponsor | 84 | 1% | Full adviser team, 39 questions |
| Granton Equity | Sponsor | 82 | 1% | Late entrant, ramping hard |
| Dunmore Family Office | Family office | 66 | 18% | Small but real |
| Pennine Capital | Sponsor | 63 | 97% | Silent 15 days |
| Aldermoor Industrial | Trade | 24 | 80% | Commercial folders only |
| Selby Holdings | Trade | 21 | 100% | Silent 35 days |

**Six names on the process letter; 3.0 expected live bids.** Probability of fewer
than two — the point at which price discipline collapses — is 0.3%.

**Aldermoor reads like reconnaissance, not diligence.** Commercial & Customers at
1.92× the typical bidder; Financial 0.16×, HR & Pensions 0.13×, Tax 0.08×. No
adviser firms onboarded in nine weeks, five questions. A trade buyer preparing an
offer commissions legal and financial diligence *before* it reads pricing
schedules that closely. This is a flag, not a finding — but staging customer-level
pricing behind a supplementary undertaking costs a genuine buyer nothing.

**The SPA is already visible.** The Halstead Aerospace master supply agreement and
the pension scheme actuarial valuation are the two most-read documents in the
room, by every bidder, an average of 20 separate days each. They will come back as
a change-of-control condition and a pension indemnity. Commission the vendor-side
actuarial position and open the consent conversation now, while it is still
preparation rather than negotiation.

**And the vendor over-prepared.** 14% of uploaded pages were never opened by
anyone — management time to assemble, adviser time to redact, for nothing.

**One caution, stated on the page itself.** This is behavioural inference, not
fact. A quiet bidder may be waiting on an investment committee. The output is a
ranked set of questions for the deal team, not a verdict on anyone's intent.

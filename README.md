# D&A Technique Demos

Working demonstrations of the data and analytics techniques I'd bring to a
transaction advisory practice — built to be walked through, not described.

Each demo is self-contained: a seeded synthetic dataset, the analytical logic as
runnable code, and an interactive artifact aimed at a mixed audience of FDD
partners, PE deal teams and portfolio company CFOs.

**Kevin Densmore** · built with Claude Code

---

## Built

| # | Technique | Stage | Demo | Tutorial |
|---|---|---|---|---|
| — | **Deal lifecycle map** | front door | [Explore all 32](https://claude.ai/code/artifact/8f47772e-1d82-4096-9b06-7aa3de1988da) | — |
| 01 | [Alt Data Triangulation](demos/01-alt-data-triangulation/) | Commercial DD | [Project Harrier](https://claude.ai/code/artifact/573d0f94-5d11-4e02-8ed7-064c98752cb3) | [How-to](https://claude.ai/code/artifact/902859a7-3384-4a18-8c3e-b6d734b3c9f1) |
| 04 | [Trade Area & Footfall](demos/04-trade-area/) | Commercial DD | [Project Ferryman](https://claude.ai/code/artifact/5cf358a8-34ea-4190-9b5a-cc7217fd63b4) | [How-to](https://claude.ai/code/artifact/55ce8a12-02a9-4a4f-a926-ec7f7e45ce8d) |
| 09 | [Revenue Decomposition](demos/09-revenue-decomposition/) | Financial DD | [Meridian Bridge](https://claude.ai/code/artifact/230bde63-86eb-44b4-a8fa-d86185f0a70f) | [How-to](https://claude.ai/code/artifact/2ba6fc7e-e46b-4bba-960f-5a281011aea6) |
| 15 | [Balance Sheet Carve-Out](demos/15-carve-out/) | SPA & completion | [Project Kiln](https://claude.ai/code/artifact/03e43f18-74c5-4df8-ae0a-48d3ea9a8bd5) | [How-to](https://claude.ai/code/artifact/d0efaada-1055-480d-84a0-ec3d4cd00b96) |
| 16 | [Data Room Analytics](demos/16-vdr-analytics/) | SPA & completion | [Project Lantern](https://claude.ai/code/artifact/b50804ed-996e-472a-9aa8-df7b184ec06c) | [How-to](https://claude.ai/code/artifact/746bf3be-f3ae-48d2-94bb-8c36f813f3e3) |
| 18 | [Synergy Tracking](demos/18-synergy-tracking/) | Value creation | [Project Anvil](https://claude.ai/code/artifact/b18eee14-aa3a-497e-8b8c-7c07101062a8) | [How-to](https://claude.ai/code/artifact/58926809-5c81-487f-8011-24b2ebe2cc68) |

Each technique ships as a **pair**: a demo that makes the finding land with a deal team, and a
tutorial that shows how the analysis is actually performed — PySpark for the data work, pandas and
NumPy for the modelling, with the failure modes that produced real bugs in these builds written up
rather than quietly fixed.

**Start here:** the [lifecycle map](https://claude.ai/code/artifact/8f47772e-1d82-4096-9b06-7aa3de1988da) is the front door — every technique in the catalogue placed against the phase of a deal it belongs to, with the built ones linked.

## Catalogue

### Pre-deal and commercial due diligence
1. Alt data triangulation · 2. Web traffic analysis · 3. Sentiment analytics (NLP)
· 4. Trade area analysis · 5. Churn analysis · 6. Deal signal monitoring
· 7. Data subscription rationalisation

### Financial due diligence augmentation
8. Repeatable data analysis packs · **9. Revenue decomposition** ✅
· 10. Working capital analytics · 11. EBITDA adjustments validation
· 12. SKU-level performance analysis · 13. AI-powered document review

### SPA and transaction support
14. SPA automation · 15. Balance sheet data carve-out · 16. Virtual data room analytics
· 17. Post-acquisition dispute investigation

### Post-deal value creation
18. Synergy tracking · 19. Finance close effectiveness · 20. SKU harmonisation
· 21. Raw material passthrough analysis · 22. Customer segmentation and cross-sell
· 23. Procurement and spend analytics · 24. Operational dashboards and KPI frameworks
· 25. Tax operations automation

### AI and emerging technology
26. Text-to-SQL for deal teams · 27. LLM-powered governance
· 28. Computer vision for operational DD · 29. Voice-to-text for field operations
· 30. Agentic deal workflows · 31. Predictive analytics for deal origination

---

## House rules

These hold across every demo in the repo:

- **Synthetic, but honest.** Data generators model *drivers* — cost indices,
  churn hazards, contractual terms, seasonality — and the analysis then discovers
  the answer from the resulting records. Nothing is hard-coded to produce a
  punchy finding, which is why the same code would run against a real extract.
- **It has to tie.** Where an analysis decomposes a movement, the components
  reconcile to the movement exactly, and the reconciliation is asserted in code.
  A demo that fails its own checks fails loudly rather than publishing a number.
- **Built for the room.** Every demo answers the same five questions: what it is,
  what data it needs, how the calculation works, what the output looks like, and
  what a deal team does with it on Monday.
- **Charts are read by people.** One scale per plot, no dual axes, a validated
  colourblind-safe palette, a table view behind every chart, and both light and
  dark themes designed rather than inverted.

## Running a demo

```bash
pip install pandas numpy
cd demos/09-revenue-decomposition
python3 src/generate_data.py   # synthetic source data
python3 src/analyse.py         # analysis + reconciliation checks
python3 src/build_page.py      # interactive page
```

## Repository layout

```
shared/          house.css, viz.js and build.py — one stylesheet and one chart
                 toolkit behind every page, plus catalogue.json as the single
                 source of truth for what exists and what is built
lifecycle/       the front door: 32 techniques against five phases of a deal
demos/<n>/       src/ (generator, analysis, page template), data/, README
tutorials/       src/content/t<n>.py holds each walkthrough; one template
                 renders them all
```

A fix to a scale or a mark specification in `shared/viz.js` lands on every page at once. That is the
same argument for repeatable analysis packs on live deals, made structurally rather than promised.

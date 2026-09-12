# D&A Technique Demos

Working demonstrations of the data and analytics techniques I'd bring to a
transaction advisory practice — built to be walked through, not described.

Each demo is self-contained: a seeded synthetic dataset, the analytical logic as
runnable code, and an interactive artifact aimed at a mixed audience of FDD
partners, PE deal teams and portfolio company CFOs.

**Kevin Densmore** · built with Claude Code

---

## Built

| # | Technique | Stage | Demo | The finding |
|---|---|---|---|---|
| — | **Deal Lifecycle** | front door | [Lifecycle map](https://claude.ai/code/artifact/8f47772e-1d82-4096-9b06-7aa3de1988da) | 32 techniques across five phases of a transaction |
| 01 | [Alt Data Triangulation](demos/01-alt-data-triangulation/) | Commercial DD | [Project Harrier](https://claude.ai/code/artifact/573d0f94-5d11-4e02-8ed7-064c98752cb3) | 4 of 7 IM claims challenged; implied organic growth 5.1% against 9% claimed |
| 09 | [Revenue Decomposition](demos/09-revenue-decomposition/) | Financial DD | [Meridian Bridge](https://claude.ai/code/artifact/230bde63-86eb-44b4-a8fa-d86185f0a70f) | +18.6% reported growth is −1.8% underlying |
| 16 | [Data Room Analytics](demos/16-vdr-analytics/) | SPA & completion | [Project Lantern](https://claude.ai/code/artifact/b50804ed-996e-472a-9aa8-df7b184ec06c) | Six bidders on the process letter, 3.0 expected live bids |
| 18 | [Synergy Tracking](demos/18-synergy-tracking/) | Value creation | [Project Anvil](https://claude.ai/code/artifact/b18eee14-aa3a-497e-8b8c-7c07101062a8) | £13.8m forecast against a £24.5m model — and the model is unreachable |

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

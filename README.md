# D&A Technique Demos

Working demonstrations of the data and analytics techniques I'd bring to a
transaction advisory practice — built to be walked through, not described.

Each demo is self-contained: a seeded synthetic dataset, the analytical logic as
runnable code, and an interactive artifact aimed at a mixed audience of FDD
partners, PE deal teams and portfolio company CFOs.

**Kevin Densmore** · built with Claude Code

---

## Built

| # | Technique | Demo | The finding |
|---|---|---|---|
| 09 | [Revenue Decomposition](demos/09-revenue-decomposition/) | [Meridian Revenue Bridge](https://claude.ai/code/artifact/230bde63-86eb-44b4-a8fa-d86185f0a70f) | +18.6% reported growth is −1.8% underlying once passthrough pricing, a one-off contract and FX come out |

## Also in this repo

| Project | What it is |
|---|---|
| [NHS CIM text-to-action agent](nhs-cim-agent/) | An MCP server that turns NHS Registration Authority correspondence into validated Care Identity Management actions — evidence-bound extraction, policy guardrails, two-phase apply behind a confirmation token, and an append-only audit trail |

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

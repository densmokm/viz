# Tutorials

Each demo in this repository ships with a companion tutorial: the same analysis,
taken apart step by step, with runnable code.

| Technique | Tutorial | What it teaches |
|---|---|---|
| 01 Alt Data Triangulation | [How to triangulate outside-in data](https://claude.ai/code/artifact/902859a7-3384-4a18-8c3e-b6d734b3c9f1) | Standardising signals of unequal quality; weighting by reliability, latency and sample; scoring evidence and confidence separately; independence by source family |
| 09 Revenue Decomposition | [How to build a revenue bridge that ties](https://claude.ai/code/artifact/2ba6fc7e-e46b-4bba-960f-5a281011aea6) | The price/volume/mix identity and why it is exact; the customer partition; nesting two lenses; constant currency and one-off carve-out |
| 16 Data Room Analytics | [How to read bidder intent](https://claude.ai/code/artifact/746bf3be-f3ae-48d2-94bb-8c36f813f3e3) | Sessionising an access log; feature parity between training and scoring; IRLS logistic regression; exact Poisson-binomial |
| 18 Synergy Tracking | [How to build a synergy tracker](https://claude.ai/code/artifact/58926809-5c81-487f-8011-24b2ebe2cc68) | Run-rate versus in-year P&L; conversion estimated from prior deals; realisation as a distribution; time-phased earned value; the ceiling |

## Structure

Every tutorial follows the same shape:

1. **The input** — the schema, with a note on why each column matters and which one people forget
2. **Walkthrough** — numbered steps, each with the reasoning first and then the code, switchable
   between **PySpark** and **pandas**
3. **What goes wrong** — every pitfall listed was an actual bug in this analysis at some point, not
   a hypothetical
4. **Proving it works** — the assertions that gate the build
5. **Running it for real** — where Spark earns its place, and where it does not

## The engineering line

The recurring theme, stated explicitly in each one: **Spark for the grain reduction, pandas and
NumPy for the model.** A 50-million-line day-book collapses to a few thousand rows before any
statistics happen. Expressing a four-line price/volume/mix identity in Spark is possible and
pointless. Knowing where that boundary sits is most of the engineering.

## Authoring

Content lives in `src/content/t<n>.py` as a plain Python dict — code blocks are triple-quoted
strings, so they stay readable and diffable. One template renders all of them:

```bash
python3 tutorials/src/build.py          # all four
python3 tutorials/src/build.py t09      # just one
```

Syntax highlighting is highlight.js from cdnjs with a theme written against the house tokens, so
code reads correctly in both light and dark.

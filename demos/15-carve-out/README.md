# 15 — Balance Sheet Carve-Out

**Live demo:** https://claude.ai/code/artifact/03e43f18-74c5-4df8-ae0a-48d3ea9a8bd5
**Tutorial:** [How to carve a division out of a group ledger](https://claude.ai/code/artifact/d0efaada-1055-480d-84a0-ec3d4cd00b96)

Target: *Ashworth Industries plc* (synthetic) divesting its **Thermal Products**
division. Deal codename *Project Kiln*.
Stage: **SPA and transaction support.**

---

## 1. What it is

Standalone financial statements for a division that has never had any. One ERP,
one chart of accounts, five shared-service functions, a corporate centre and
three-way intercompany trading.

The method is short to describe and easy to get wrong: **segment the P&L from
transaction data using explicit allocation bases, then drive the balance sheet off
the segmented P&L and physical drivers like headcount.** The discipline is that
every line foots back to the group and every allocation conserves the pool it
started with.

## 2. Ingredients

| Input | Why |
|---|---|
| **Posting-level GL** | A trial balance is not enough — the allocation has to be rebuilt from postings, because which postings belong to the division is the whole question |
| **Cost centre master** | Divisional / shared / corporate. The spine of the exercise |
| **Service usage drivers** | Tickets, payroll runs, documents, square feet. Measured usage beats a headcount proxy |
| **Headcount and floor area** | Drivers for anything with no usage record |
| **Sub-ledgers** | AR by customer, inventory by SKU, fixed assets by cost centre, AP by supplier, accruals by nature |
| **Standalone benchmarks** | Function cost as % of revenue for comparable independents, with a floor where it cannot scale down |

Generated: **132,384 postings** across 18 cost centres, plus the five sub-ledgers.

## 3. Key calculations

**Reciprocal allocation.** Shared services consume each other — IT runs the
finance and payroll systems; HR runs payroll for IT. Each pool's true cost is its
own spend plus what it receives from the others, which is circular:

```
T = D + M·T        M[i][j] = share of service j consumed by i
  ⇒  T = (I − M)⁻¹ D
```

Direct and step-down are computed alongside it, and all three are asserted to
conserve the pool.

**Corporate on a disclosed basis.** Nobody consumes a board, so corporate cost is
spread on a basis — and the basis is a negotiating position, not a fact. Four
conventional bases are computed and shown together.

**Standalone cost benchmarked, not uplifted.** Taking the allocation and adding a
percentage assumes the allocation was right, which is the thing being tested.

**Balance sheet driven off the segmented P&L** — receivables on revenue, inventory
and payables on cost of sales, PPE on floor area — with **directness reported per
line**, because a buyer should price a directly-attributed receivable and an
allocated accrual differently.

## 4. The demo

```bash
pip install pandas numpy
cd demos/15-carve-out
python3 src/generate_data.py   # 132k postings, 18 cost centres, five sub-ledgers
python3 src/analyse.py         # allocation, bridge, balance sheet, reconciliation gates
python3 src/build_page.py      # -> carve-out.html
```

## 5. The "so what"

**Divisional EBITDA £20.3m (14.0%) becomes £17.7m (12.2%) carved out.**

| | |
|---|---:|
| Divisional EBITDA as reported | £20.3m |
| Allocation method | −£0.2m |
| Intercompany at arm's length | −£0.5m |
| Standalone cost gap | −£1.9m |
| **Carve-out EBITDA** | **£17.7m** |

**Three findings:**

- **The allocation-method argument is not where the money is — and you only know
  that by doing it.** Direct, step-down and reciprocal agree to within **£17k** for
  this division. But per service they disagree by hundreds of thousands in
  opposite directions (IT alone swings £550k, because 48% of it is consumed by
  other services the direct method never credits), and the same test moves a
  sister division by **£372k**. The near-cancellation is a property of this
  division's usage profile, not a general result.
- **The corporate basis is worth more than the method.** The same pool spread four
  conventional ways produces EBITDA numbers **£410k** apart. Fix it in the SPA
  rather than discovering it in completion accounts.
- **£4.15m is stranded.** 56% of what is currently charged to the division does
  not leave with it. That lands on the two remaining divisions — the vendor's
  problem, not the buyer's, which is exactly why it never appears in the vendor's
  own carve-out pack.

**What a deal team does with it.** Underwrite £17.7m, not £20.3m — at 8× that is
£21m of enterprise value. Spend the diligence hours in reverse order of the three
adjustments. And price the TSA off the same build: every function where standalone
exceeds allocated is one the vendor should provide and the buyer should exit on a
dated plan.

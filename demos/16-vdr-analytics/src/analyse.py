#!/usr/bin/env python3
"""
Project Lantern -- what the data room log says about the bidders.

Four questions, in order of how much money they are worth:

  1. which bidders are actually working the deal, on behaviour rather than talk
  2. which are about to drop, scored by a model FITTED ON PRIOR PROCESSES
  3. where the deal risk sits -- the documents everyone reads, twice
  4. what the sell-side wasted effort preparing

The drop-out model is estimated from 140 bidders in past processes with known
outcomes. Hand-weighting a "bidder health score" would have been quicker and
would not survive the first partner who asked where the weights came from.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data"

LOG = pd.read_csv(OUT / "access_log.csv.gz")
DOCS = pd.read_csv(OUT / "documents.csv")
USERS = pd.read_csv(OUT / "users.csv")
QA = pd.read_csv(OUT / "qa_log.csv")
HIST = pd.read_csv(OUT / "historic_bidders.csv")
LOG["date"] = pd.to_datetime(LOG.date)
QA["date"] = pd.to_datetime(QA.date)

LAST_DAY = LOG.date.max()
N_WEEKS = int(LOG.week.max())
SENIOR = {"Partner / MD", "Director"}
BIDDER_KIND = {"Marlowe Partners": "Sponsor", "Granton Equity": "Sponsor",
               "Aldermoor Industrial": "Trade", "Pennine Capital": "Sponsor",
               "Dunmore Family Office": "Family office", "Selby Holdings": "Trade"}

FEATURES = ["coverage", "depth", "senior_share", "advisers", "trend", "days_idle", "qa_count"]

# ---------------------------------------------------------------------------
# Bidder features, on the same definitions as the historical register
# ---------------------------------------------------------------------------
proc_sec_per_page = float((LOG.seconds / LOG.pages).median())

rows = []
for b, g in LOG.groupby("bidder"):
    recent = g[g.week > N_WEEKS - 3].seconds.sum()
    prior = g[(g.week > N_WEEKS - 6) & (g.week <= N_WEEKS - 3)].seconds.sum()
    rows.append(dict(
        bidder=b, kind=BIDDER_KIND[b],
        coverage=float(g.doc_id.nunique() / len(DOCS)),
        depth=float((g.seconds / g.pages).median() / proc_sec_per_page),
        senior_share=float(g[g.role.isin(SENIOR)].seconds.sum() / g.seconds.sum()),
        advisers=float(g[g.is_adviser == 1].org.nunique()),
        trend=float(np.clip(np.log((recent + 60) / (prior + 60)), -1.6, 1.6)),
        days_idle=float((LAST_DAY - g.date.max()).days),
        qa_count=float((QA.bidder == b).sum()),
        events=int(len(g)), hours=float(g.seconds.sum() / 3600),
        users=int(g.user_id.nunique()), docs=int(g.doc_id.nunique()),
        downloads=int((g.action == "download").sum()),
        last_seen=str(g.date.max().date()),
    ))
BID = pd.DataFrame(rows).set_index("bidder")
for b in BIDDER_KIND:
    if b not in BID.index:
        BID.loc[b] = dict(kind=BIDDER_KIND[b], coverage=0, depth=0, senior_share=0, advisers=0,
                          trend=-1.6, days_idle=99, qa_count=0, events=0, hours=0, users=0,
                          docs=0, downloads=0, last_seen="—")

# ---------------------------------------------------------------------------
# Drop-out model: logistic regression by IRLS, fitted on prior processes
# ---------------------------------------------------------------------------
mu, sd = HIST[FEATURES].mean(), HIST[FEATURES].std(ddof=0)

def z(df):
    return ((df[FEATURES] - mu) / sd).to_numpy()

def fit_logistic(X, y, iters=80, ridge=1e-2):
    X = np.c_[np.ones(len(X)), X]
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = np.clip(p * (1 - p), 1e-8, None)
        A = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(A, X.T @ (y - p) - ridge * b)
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b

def predict(b, X):
    return 1 / (1 + np.exp(-(np.c_[np.ones(len(X)), X] @ b)))

Xh, yh = z(HIST), HIST.withdrew.to_numpy().astype(float)
BETA = fit_logistic(Xh, yh)
p_hist = predict(BETA, Xh)

def auc(y, p):
    pos, neg = p[y == 1], p[y == 0]
    r = pd.Series(p).rank().to_numpy()
    return float((r[y == 1].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))

AUC = auc(yh, p_hist)
ACC = float(((p_hist > 0.5).astype(int) == yh).mean())
BRIER = float(np.mean((p_hist - yh) ** 2))
CAL = []
for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]:
    m = (p_hist >= lo) & (p_hist < hi)
    if m.sum():
        CAL.append(dict(bucket=f"{int(lo*100)}–{int(min(hi,1.0)*100)}%", n=int(m.sum()),
                        predicted=float(p_hist[m].mean()), actual=float(yh[m].mean())))

# Live bidders, clipped into the range the model was actually fitted on
live = BID.copy()
CLIPPED = {}
for f in FEATURES:
    lo, hi = HIST[f].min(), HIST[f].max()
    CLIPPED[f] = int(((live[f] < lo) | (live[f] > hi)).sum())
    live[f] = live[f].clip(lo, hi)
BID["p_drop"] = predict(BETA, z(live))

# Engagement: effort invested, as a percentile against the historical distribution
EW = dict(coverage=.40, depth=.12, senior_share=.16, advisers=.17, qa_count=.15)
def pctile(f, v):
    return float((HIST[f] <= v).mean())

def engagement(r):
    """Percentile-weighted effort. Dwell time is a noisy estimate for a bidder with
    almost no activity, so it is shrunk toward the coverage percentile rather than
    letting thirty lucky page-views outrank six hours of real work."""
    rel = min(1.0, r["events"] / 300)
    p = {f: pctile(f, r[f]) for f in EW}
    p["depth"] = p["depth"] * rel + p["coverage"] * (1 - rel)
    return round(100 * sum(w * p[f] for f, w in EW.items()), 1)

BID["engagement"] = [engagement(r) for _, r in BID.iterrows()]

# Expected live bids at the deadline (Poisson-binomial over independent bidders)
p_bid = (1 - BID.p_drop).to_numpy()
dist = np.zeros(len(p_bid) + 1); dist[0] = 1.0
for p in p_bid:
    dist[1:] = dist[1:] * (1 - p) + dist[:-1] * p
    dist[0] *= (1 - p)
TENSION = dict(headline=int(len(p_bid)), expected=float(p_bid.sum()),
               p_at_least_two=float(dist[2:].sum()), p_at_least_three=float(dist[3:].sum()),
               distribution=[float(x) for x in dist])


# ---------------------------------------------------------------------------
# Attention profile: what each bidder reads, versus what the room reads
# ---------------------------------------------------------------------------
CATS = sorted(DOCS.category.unique())
att = (LOG.pivot_table(index="bidder", columns="category", values="seconds", aggfunc="sum")
          .reindex(index=BID.index, columns=CATS).fillna(0.0))
share = att.div(att.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
active = share[share.sum(axis=1) > 0]
room_share = active.mean(axis=0)
room_share = room_share / room_share.sum()

PROFILE = []
for b in BID.index:
    s = share.loc[b]
    idx = (s / room_share).replace([np.inf, -np.inf], 0).fillna(0)
    div = float(np.abs(s - room_share).sum() / 2)          # total variation distance
    over = idx.sort_values(ascending=False)
    # A bidder deep in commercial and absent from financial, legal and tax is not
    # doing diligence. Score that pattern explicitly rather than eyeballing it.
    comm = float(idx.get("Commercial & Customers", 0) + idx.get("Operations & Sites", 0)) / 2
    fin = float(idx.get("Financial", 0) + idx.get("Legal & Corporate", 0) + idx.get("Tax", 0)) / 3
    recon = float(np.clip((comm - fin) / 2.2, 0, 1)) * float(BID.loc[b, "advisers"] == 0) \
        * float(np.clip(1 - BID.loc[b, "qa_count"] / 12, 0, 1))
    PROFILE.append(dict(bidder=b, divergence=div, recon_score=recon,
                        shares={c: float(s[c]) for c in CATS},
                        index={c: float(idx[c]) for c in CATS},
                        over=[str(x) for x in over.index[:2]],
                        under=[str(x) for x in over.index[-2:]]))

# ---------------------------------------------------------------------------
# Document heat: what the room keeps going back to
# ---------------------------------------------------------------------------
d = LOG.groupby("doc_id").agg(seconds=("seconds", "sum"), opens=("doc_id", "size"),
                              bidders=("bidder", "nunique"))
revisits = (LOG.groupby(["doc_id", "bidder"]).date.nunique()
              .groupby("doc_id").mean().rename("revisits"))
HEAT = DOCS.set_index("doc_id").join(d).join(revisits).fillna(0)
HEAT["sec_per_page"] = HEAT.seconds / HEAT.pages
zc = lambda s: (s - s.mean()) / max(s.std(ddof=0), 1e-9)
HEAT["hours"] = HEAT.seconds / 3600
HEAT["score"] = (zc(np.log1p(HEAT.hours)) + 0.8 * zc(HEAT.bidders.astype(float))
                 + zc(np.log1p(HEAT.revisits)) + 0.4 * zc(np.log1p(HEAT.sec_per_page)))
TOP_DOCS = [dict(name=r["name"], category=r.category, pages=int(r.pages),
                 bidders=int(r.bidders), revisits=float(r.revisits),
                 hours=float(r.hours), score=float(r.score))
            for _, r in HEAT.nlargest(12, "score").iterrows()]

# category-level heat, to line up against Q&A volume
CATHEAT = []
for c in CATS:
    h = HEAT[HEAT.category == c]
    q = QA[QA.category == c]
    CATHEAT.append(dict(category=c, documents=int(len(h)), pages=int(h.pages.sum()),
                        hours=float(h.seconds.sum() / 3600),
                        bidders=float(h.bidders.mean()), revisits=float(h.revisits.mean()),
                        questions=int(len(q)),
                        days_to_answer=float(q.days_to_answer.median()) if len(q) else 0.0,
                        unread_pages=int(h[h.opens == 0].pages.sum())))

# ---------------------------------------------------------------------------
# Sell-side diagnostics: what was prepared and never read
# ---------------------------------------------------------------------------
unread = HEAT[HEAT.opens == 0]
PREP = dict(documents=int(len(DOCS)), pages=int(DOCS.pages.sum()),
            unread_docs=int(len(unread)), unread_pages=int(unread.pages.sum()),
            unread_pct=float(unread.pages.sum() / DOCS.pages.sum()),
            single_bidder_docs=int((HEAT.bidders == 1).sum()),
            all_bidder_docs=int((HEAT.bidders == len(BID)).sum()))

# weekly activity, per bidder
WEEKLY = {b: [float(LOG[(LOG.bidder == b) & (LOG.week == w)].seconds.sum() / 3600)
              for w in range(1, N_WEEKS + 1)] for b in BID.index}
QA_WEEKLY = [int((QA.week == w).sum()) for w in range(1, N_WEEKS + 1)]

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
COEF = [dict(feature=f, beta=float(BETA[i + 1]),
             odds=float(np.exp(BETA[i + 1])),
             label={"coverage": "Document coverage", "depth": "Dwell time per page",
                    "senior_share": "Share of time by senior staff", "advisers": "Adviser firms engaged",
                    "trend": "Activity trend, last 3 weeks", "days_idle": "Days since last login",
                    "qa_count": "Questions submitted"}[f])
        for i, f in enumerate(FEATURES)]
COEF.sort(key=lambda c: -abs(c["beta"]))

bidders_out = []
for b, r in BID.sort_values("engagement", ascending=False).iterrows():
    prof = next(p for p in PROFILE if p["bidder"] == b)
    bidders_out.append(dict(bidder=b, kind=r.kind, engagement=float(r.engagement),
                            p_drop=float(r.p_drop), events=int(r.events), hours=float(r.hours),
                            users=int(r.users), docs=int(r.docs), downloads=int(r.downloads),
                            coverage=float(r.coverage), depth=float(r.depth),
                            senior_share=float(r.senior_share), advisers=int(r.advisers),
                            trend=float(r.trend), days_idle=int(r.days_idle),
                            qa_count=int(r.qa_count), last_seen=r.last_seen,
                            weekly=WEEKLY[b], divergence=prof["divergence"],
                            recon_score=prof["recon_score"], over=prof["over"], under=prof["under"]))

results = dict(
    meta=dict(company="Thornbury Precision Group", codename="Project Lantern",
              sector="Precision components, aerospace and medical", stage="Sell-side / transaction support",
              weeks=N_WEEKS, events=int(len(LOG)), documents=int(len(DOCS)),
              pages=int(DOCS.pages.sum()), users=int(LOG.user_id.nunique()),
              questions=int(len(QA)), bidders=int(len(BID))),
    bidders=bidders_out, categories=CATS, profiles=PROFILE, matrix=[
        dict(bidder=b, cells=[dict(category=c, index=float(share.loc[b, c] / room_share[c])
                                   if room_share[c] > 0 else 0.0,
                                   share=float(share.loc[b, c])) for c in CATS])
        for b in BID.sort_values("engagement", ascending=False).index],
    model=dict(coefficients=COEF, auc=AUC, accuracy=ACC, brier=BRIER, n=int(len(HIST)),
               withdrew=int(HIST.withdrew.sum()), calibration=CAL,
               clipped={k: v for k, v in CLIPPED.items() if v}),
    tension=TENSION, top_docs=TOP_DOCS, category_heat=CATHEAT, prep=PREP,
    qa_weekly=QA_WEEKLY, weeks=list(range(1, N_WEEKS + 1)),
)

def jsonable(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, (np.ndarray,)): return o.tolist()
    raise TypeError(type(o))

def check():
    assert abs(sum(TENSION["distribution"]) - 1) < 1e-9, "bid-count distribution must sum to 1"
    assert AUC > 0.7, f"model separates poorly (AUC {AUC:.2f})"
    for p in PROFILE:
        assert abs(sum(p["shares"].values()) - 1) < 1e-6 or BID.loc[p["bidder"], "events"] == 0
    print(f"  checks: AUC {AUC:.3f}, distribution sums to 1, attention shares sum to 1")

check()
(OUT / "results.json").write_text(json.dumps(results, indent=1, default=jsonable))

print(f"{'PROJECT LANTERN -- BIDDER BOARD':-^74}")
print(f"  {'bidder':<24}{'kind':<15}{'engage':>7}{'p(drop)':>9}{'hours':>7}{'cover':>7}{'idle':>6}{'Q&A':>5}")
for b in bidders_out:
    print(f"  {b['bidder']:<24}{b['kind']:<15}{b['engagement']:>7.0f}{b['p_drop']:>9.2f}"
          f"{b['hours']:>7.0f}{b['coverage']:>7.1%}{b['days_idle']:>6}{b['qa_count']:>5}")
print(f"\n  model fitted on {len(HIST)} prior bidders ({int(HIST.withdrew.sum())} withdrew), "
      f"AUC {AUC:.2f}, accuracy {ACC:.0%}, Brier {BRIER:.3f}")
print(f"  headline bidders {TENSION['headline']}, expected live bids {TENSION['expected']:.1f}, "
      f"P(>=2) {TENSION['p_at_least_two']:.0%}")
print(f"  prep waste: {PREP['unread_pct']:.0%} of pages never opened "
      f"({PREP['unread_docs']} of {PREP['documents']} documents)")
print("\n  hottest documents:")
for t in TOP_DOCS[:5]:
    print(f"    {t['name'][:52]:<54}{t['bidders']}/6 bidders  {t['revisits']:.1f} revisits  {t['hours']:.1f}h")

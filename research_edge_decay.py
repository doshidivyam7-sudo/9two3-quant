"""
Edge-decay study: how long does each price/volume signal keep its edge
in Indian mid & small caps, and which holding period is best after costs?

Conventions
- Signal is known at the close of day t. Entry is the OPEN of day t+1
  (realistic for a manual trader); exit at the CLOSE of day t+h.
- Returns are excess vs the equal-weight average of all eligible stocks
  over the same window (so market moves don't flatter a signal).
- Costs are round-trip delivery costs incl. STT 0.1% each side + slippage,
  higher for small caps.
"""
import json, pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).parent
D = ROOT / "data"
HORIZONS = [1, 2, 3, 5, 10, 20, 40, 60, 120, 250]
COST = {"MID": 0.0045, "SMALL": 0.0075}   # round trip
START = "2015-01-01"

# ---------------------------------------------------------------- data
o = pd.read_parquet(D / "open.parquet")
h = pd.read_parquet(D / "high.parquet")
l = pd.read_parquet(D / "low.parquet")
c = pd.read_parquet(D / "close.parquet")
v = pd.read_parquet(D / "volume.parquet")
seg = pd.read_csv(D / "segments.csv", index_col=0)["segment"].reindex(c.columns)
idx = c.index

# clean daily log returns (bad adjustments -> NaN)
cc = np.log(c / c.shift(1))
cc[cc.abs() > np.log(1.4)] = np.nan
oc = np.log(c / o)
oc[oc.abs() > np.log(1.3)] = np.nan
gap = np.log(o / c.shift(1))
gap[gap.abs() > np.log(1.3)] = np.nan

# eligibility (known at t): price >= 20, 20d median traded value >= Rs 2 Cr
tv = (c * v).rolling(20, min_periods=15).median()
elig = (c >= 20) & (tv >= 2e7) & c.notna()

# ---------------------------------------------------------------- forward returns
# fwd_h(t) = log(close[t+h] / open[t+1]) = oc[t+1] + sum cc[t+2..t+h]
cum_cc = cc.fillna(0).cumsum()
oc_next = oc.shift(-1)
fwd = {}
for H in HORIZONS:
    later = cum_cc.shift(-H) - cum_cc.shift(-1)          # sum cc[t+2..t+H]
    f = oc_next + (later if H > 1 else 0)
    # require the stock to exist through t+H
    f = f.where(c.shift(-H).notna())
    fwd[H] = np.expm1(f)
exc = {}
for H in HORIZONS:
    f = fwd[H].where(elig)
    exc[H] = f.sub(f.mean(axis=1), axis=0)

# stock-demeaned ("strict") excess: subtract each stock's own average excess
# over the sample, so a stock that simply went up a lot (survivorship) gets no credit
_sample = pd.Series(idx >= pd.Timestamp(START), index=idx)
exc_strict = {}
for H in HORIZONS:
    base = exc[H][_sample.values].mean(axis=0)
    exc_strict[H] = exc[H] - base
# entry at the signal-day close (decide in the last 30 minutes)
fwd_close, exc_close = {}, {}
for H in HORIZONS:
    f = np.expm1((cum_cc.shift(-H) - cum_cc).where(c.shift(-H).notna()))
    fwd_close[H] = f
    fe = f.where(elig)
    e = fe.sub(fe.mean(axis=1), axis=0)
    exc_close[H] = e - e[_sample.values].mean(axis=0)
EXC_UNIVERSE = exc

# ---------------------------------------------------------------- regime
ew = cc.where(elig.shift(1)).mean(axis=1).fillna(0)
ew_idx = np.exp(ew.cumsum())
regime = np.where(ew_idx > ew_idx.rolling(200).mean(), "Bull", "Bear")
regime = pd.Series(regime, index=idx)

# ---------------------------------------------------------------- features
ret1 = np.expm1(cc)
rvol = v / v.rolling(50, min_periods=30).median().shift(1)
rng = (h - l).replace(0, np.nan)
clv = (c - l) / rng                                   # close location in day's range
hi20 = c.rolling(20).max(); hi55 = c.rolling(55).max(); hi252 = c.rolling(252, min_periods=200).max()
sma50 = c.rolling(50).mean(); sma200 = c.rolling(200).mean()
r5 = np.expm1(cc.rolling(5).sum()); r21 = np.expm1(cc.rolling(21).sum())
r126 = np.expm1(cc.rolling(126).sum()); r252 = np.expm1(cc.rolling(252).sum())
vol60 = cc.rolling(60).std()
width20 = (c.rolling(20).max() - c.rolling(20).min()) / c
width_rank = width20.rolling(252, min_periods=200).rank(pct=True)
at_hi252 = c >= hi252
no_hi_60 = at_hi252.astype(float).shift(1).rolling(60, min_periods=60).max() == 0  # no 52w high in prior 60 days
gapr = np.expm1(gap)

def dedupe(sig, k=10):
    """keep first signal per stock in any k-day window"""
    s = sig.fillna(False).astype(bool)
    prior = s.shift(1).rolling(k, min_periods=1).max().fillna(0).astype(bool)
    return s & ~prior

EVENTS = {
    "Volume-shock breakout": dict(
        sig=(rvol >= 3) & (ret1 >= 0.04) & (clv >= 0.75) & (c >= hi20),
        desc="Volume ≥3× normal, up ≥4%, closes in top quarter of the day's range at a 20-day high"),
    "Gap-and-hold (results-day proxy)": dict(
        sig=(gapr >= 0.04) & (c >= o) & (rvol >= 2.5),
        desc="Opens ≥4% higher on ≥2.5× volume and closes at or above the open"),
    "Gap-up that fails": dict(
        sig=(gapr >= 0.04) & (c < o * 0.98) & (rvol >= 2.5),
        desc="Opens ≥4% higher on heavy volume but closes 2%+ below the open"),
    "Fresh 52-week-high breakout": dict(
        sig=at_hi252 & no_hi_60 & (rvol >= 1.5),
        desc="First new 52-week high after ≥60 days, on ≥1.5× volume"),
    "Tight-range breakout": dict(
        sig=(width_rank.shift(1) <= 0.2) & (c >= hi55) & (rvol >= 1.5),
        desc="20-day range in the tightest 20% of its own year, then a close at a 55-day high on volume"),
    "Pullback in uptrend": dict(
        sig=(c > sma200) & (sma50 > sma200) & (r5 <= -0.07),
        desc="Above a rising 200-DMA structure (50>200), but down ≥7% in 5 days"),
    "High-volume washout": dict(
        sig=(ret1 <= -0.06) & (rvol >= 3),
        desc="Down ≥6% in a day on ≥3× normal volume"),
    "Large gap-down": dict(
        sig=(gapr <= -0.05),
        desc="Opens ≥5% below the previous close"),
}
RANKS = {
    "12-1 month momentum": (np.expm1(cc.rolling(231).sum().shift(21)), "Return from 12 months ago to 1 month ago"),
    "6-1 month momentum": (np.expm1(cc.rolling(105).sum().shift(21)), "Return from 6 months ago to 1 month ago"),
    "Nearness to 52-week high": (c / hi252, "Close ÷ 52-week high"),
    "Trend strength": (c / sma200 - 1, "Distance above the 200-day average"),
    "1-week reversal": (-r5, "Biggest 5-day losers rank highest"),
    "1-month reversal": (-r21, "Biggest 1-month losers rank highest"),
    "Low volatility": (-vol60, "Calmest 60-day volatility ranks highest"),
    "Rising attention": (v.rolling(20).mean() / v.rolling(120).mean(), "20-day avg volume ÷ 120-day avg volume"),
}

mask_dates = idx >= pd.Timestamp(START)
cost_arr = seg.map(COST).values  # per stock

def newey_west_t(x, lag):
    x = pd.Series(x).dropna().values
    n = len(x)
    if n < 30:
        return np.nan
    m = x.mean(); e = x - m
    s = e @ e / n
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        s += 2 * w * (e[L:] @ e[:-L]) / n
    return m / np.sqrt(s / n) if s > 0 else np.nan

def summarize(series_by_h, cost_by_h, n_by_h, extra=None):
    """series_by_h: H -> daily time series of average excess for that signal"""
    rows = []
    for H in HORIZONS:
        s = series_by_h[H]
        gross = s.mean()
        t = newey_west_t(s, H)
        net = gross - cost_by_h[H]
        sd = series_by_h["sd"][H]
        sharpe = (net / sd) * np.sqrt(252 / H) if sd and sd > 0 else np.nan
        rows.append(dict(h=H, gross=gross, net=net, t=t, n=int(n_by_h[H]), sharpe=sharpe,
                         **({k: v[H] for k, v in extra.items()} if extra else {})))
    return rows

def pick(rows):
    g = np.array([r["gross"] for r in rows]); hs = np.array([r["h"] for r in rows])
    peak_i = int(np.nanargmax(g)); peak = g[peak_i]
    half = None
    if peak > 0:
        for r in rows:
            if r["gross"] >= 0.5 * peak:
                half = r["h"]; break
    valid = [r for r in rows if r["net"] > 0 and (r["t"] or 0) >= 2]
    best = max(valid, key=lambda r: r["sharpe"]) if valid else None
    return dict(peak_h=int(hs[peak_i]), peak=float(peak), half_h=half,
                best_h=best["h"] if best else None,
                best_net=best["net"] if best else None,
                best_sharpe=best["sharpe"] if best else None)

results = {"events": {}, "ranks": {}}
period_masks = {
    "All (2015–26)": mask_dates,
    "2015–2020": (idx >= "2015-01-01") & (idx < "2021-01-01"),
    "2021–2026": idx >= "2021-01-01",
}

def event_study(sig, date_mask, reg=None, exc=exc_strict, fwd=fwd):
    s = dedupe(sig & elig)
    s = s & pd.DataFrame(np.repeat(date_mask[:, None], s.shape[1], 1), index=idx, columns=c.columns)
    if reg is not None:
        s = s & pd.DataFrame(np.repeat((regime.values == reg)[:, None], s.shape[1], 1), index=idx, columns=c.columns)
    by_h, sd_h, n_h, cost_h, raw_h, hit_h = {}, {}, {}, {}, {}, {}
    sv = s.values
    for H in HORIZONS:
        e = exc[H].values; f = fwd[H].values
        m = sv & ~np.isnan(e)
        cnt = m.sum(1)
        daily = np.where(cnt > 0, np.nansum(np.where(m, e, 0), 1) / np.maximum(cnt, 1), np.nan)
        by_h[H] = pd.Series(daily, index=idx)[cnt > 0]
        ev = e[m]; sd_h[H] = np.nanstd(ev); n_h[H] = m.sum()
        cost_h[H] = np.nanmean(np.broadcast_to(cost_arr, e.shape)[m]) if m.any() else 0
        raw = f[m]; raw_h[H] = np.nanmean(raw) if m.any() else np.nan
        hit_h[H] = np.nanmean((raw - cost_h[H]) > 0) if m.any() else np.nan
    by_h["sd"] = sd_h
    return summarize(by_h, cost_h, n_h, extra={"raw": raw_h, "hit": hit_h})

for name, spec in EVENTS.items():
    out = {"desc": spec["desc"], "periods": {}, "regimes": {}}
    for pn, pm in period_masks.items():
        rows = event_study(spec["sig"], pm)
        out["periods"][pn] = dict(rows=rows, **pick(rows))
    for rg in ["Bull", "Bear"]:
        rows = event_study(spec["sig"], mask_dates, rg)
        out["regimes"][rg] = dict(rows=rows, **pick(rows))
    out["universe_rel"] = event_study(spec["sig"], mask_dates, exc=EXC_UNIVERSE)
    out["close_entry"] = event_study(spec["sig"], mask_dates, exc=exc_close, fwd=fwd_close)
    results["events"][name] = out
    a = out["periods"]["All (2015–26)"]
    print(f"{name:35s} n={a['rows'][0]['n']:6d} peak={a['peak']*100:6.2f}% @ {a['peak_h']:3d}d  half@{a['half_h']}  best={a['best_h']}")

# ---------------------------------------------------------------- rank signals
sample = np.arange(len(idx))[mask_dates][::5]     # every 5th day
def rank_study(score, date_mask, reg=None, exc=exc_strict, fwd=fwd):
    sc = score.where(elig)
    pct = sc.rank(axis=1, pct=True)
    top = pct >= 0.8
    rows_by = {H: [] for H in HORIZONS}; ic_by = {H: [] for H in HORIZONS}
    sd_h, n_h, cost_h, raw_h, hit_h = {}, {}, {}, {}, {}
    use = [i for i in sample if date_mask[i] and (reg is None or regime.iloc[i] == reg)]
    for H in HORIZONS:
        E = exc[H].values; F = fwd[H].values; T = top.values; P = pct.values
        vals, ics, allex, allraw, allcost = [], [], [], [], []
        for i in use:
            m = T[i] & ~np.isnan(E[i])
            if m.sum() < 10:
                continue
            vals.append(E[i][m].mean())
            allex.append(E[i][m]); allraw.append(F[i][m]); allcost.append(cost_arr[m])
            mm = ~np.isnan(E[i]) & ~np.isnan(P[i])
            if mm.sum() > 30:
                ics.append(pd.Series(P[i][mm]).corr(pd.Series(E[i][mm]), method="spearman"))
        rows_by[H] = pd.Series(vals); ic_by[H] = float(np.nanmean(ics)) if ics else np.nan
        ex = np.concatenate(allex) if allex else np.array([np.nan])
        rw = np.concatenate(allraw) if allraw else np.array([np.nan])
        co = np.concatenate(allcost) if allcost else np.array([0.0])
        sd_h[H] = np.nanstd(ex); n_h[H] = len(vals); cost_h[H] = float(np.nanmean(co))
        raw_h[H] = float(np.nanmean(rw)); hit_h[H] = float(np.nanmean((rw - co) > 0))
    rows_by["sd"] = sd_h
    # NW lag in sampled units
    out = []
    for H in HORIZONS:
        s = rows_by[H]; gross = s.mean(); t = newey_west_t(s, max(1, H // 5))
        net = gross - cost_h[H]; sd = sd_h[H]
        out.append(dict(h=H, gross=gross, net=net, t=t, n=n_h[H],
                        sharpe=(net / sd) * np.sqrt(252 / H) if sd > 0 else np.nan,
                        ic=ic_by[H], raw=raw_h[H], hit=hit_h[H]))
    return out

for name, (score, desc) in RANKS.items():
    out = {"desc": desc, "periods": {}, "regimes": {}}
    for pn, pm in period_masks.items():
        rows = rank_study(score, pm)
        out["periods"][pn] = dict(rows=rows, **pick(rows))
    for rg in ["Bull", "Bear"]:
        rows = rank_study(score, mask_dates, rg)
        out["regimes"][rg] = dict(rows=rows, **pick(rows))
    out["universe_rel"] = rank_study(score, mask_dates, exc=EXC_UNIVERSE)
    results["ranks"][name] = out
    a = out["periods"]["All (2015–26)"]
    print(f"{name:35s} peak={a['peak']*100:6.2f}% @ {a['peak_h']:3d}d  half@{a['half_h']}  best={a['best_h']}  IC20={a['rows'][5]['ic']:.3f}")

# ---------------------------------------------------------------- context
reg_share = (regime[mask_dates] == "Bull").mean()
results["meta"] = dict(
    horizons=HORIZONS, cost=COST, start=START, end=str(idx[-1].date()),
    n_stocks=int(c.shape[1]), bull_share=float(reg_share),
    eligible_avg=float(elig[mask_dates].sum(1).mean()),
    ew_index=[[str(d.date()), float(x)] for d, x in ew_idx[mask_dates].iloc[::5].items()],
    regime_now=str(regime.iloc[-1]),
)

def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, (np.integer,)): return int(o)
    return o
(ROOT / "results.json").write_text(json.dumps(clean(results), indent=1))
print("saved results.json")

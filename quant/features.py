"""Signals and inputs, same definitions as the edge-decay study."""
import numpy as np
import pandas as pd
from . import config as C


class Features:
    def __init__(self, P, seg):
        o, h, l, c, v = P["o"], P["h"], P["l"], P["c"], P["v"]
        self.index, self.cols = c.index, list(c.columns)
        self.seg = seg.reindex(self.cols).fillna("SMALL").values
        self.seg = np.array(["ETF" if c_ == C.TOM["etf"] else s_ for c_, s_ in zip(self.cols, self.seg)], dtype=object)
        cc = np.log(c / c.shift(1)); cc[cc.abs() > np.log(1.4)] = np.nan
        gap = np.log(o / c.shift(1)); gap[gap.abs() > np.log(1.3)] = np.nan
        gapr = np.expm1(gap); ret1 = np.expm1(cc)
        rvol = v / v.rolling(50, min_periods=30).median().shift(1)
        rng = (h - l).replace(0, np.nan)
        clv = (c - l) / rng
        hi252 = c.rolling(252, min_periods=200).max()
        at_hi = c >= hi252
        no_hi_60 = at_hi.astype(float).shift(1).rolling(60, min_periods=60).max() == 0
        sma200 = c.rolling(200, min_periods=150).mean()
        tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()]).groupby(level=0).max()
        tr = tr.reindex(c.index)
        atr20 = tr.rolling(20, min_periods=15).mean()
        tv = (c * v).rolling(20, min_periods=15).median()
        elig = (c >= C.MIN_PRICE) & (tv >= C.MIN_TRADED_VALUE) & c.notna()
        for x in [C.TOM["etf"]]:
            if x in elig.columns:
                elig[x] = False            # the ETF is only a vehicle, never a stock signal

        mom = np.expm1(cc.rolling(105, min_periods=90).sum().shift(21))
        trend = c / sma200 - 1
        near = c / hi252
        attn = v.rolling(20, min_periods=15).mean() / v.rolling(120, min_periods=90).mean()
        ranks = [s.where(elig).rank(axis=1, pct=True) for s in (mom, trend, near, attn)]
        comp = sum(r.fillna(0) for r in ranks) / 4
        comp = comp.where(elig & ranks[0].notna() & ranks[1].notna())

        ew = cc.where(elig.shift(1)).mean(axis=1).fillna(0)
        idx = np.exp(ew.cumsum())
        avg = idx.rolling(C.REGIME_SMA, min_periods=C.REGIME_SMA).mean()

        self.o, self.h, self.l, self.c, self.v = (x.values for x in (o, h, l, c, v))
        self.elig = elig.values
        self.rvol = rvol.values; self.clv = clv.values; self.gapr = gapr.values; self.ret1 = ret1.values
        self.atr = atr20.values; self.sma200 = sma200.values
        self.comp = comp.values; self.mom = mom.values; self.trend = trend.values
        self.gap_hold = ((gapr >= 0.04) & (c >= o) & (rvol >= 2.5) & elig).values
        self.hi52 = (at_hi & no_hi_60 & (rvol >= 1.5) & elig).values
        self.gap_fail = ((gapr >= 0.04) & (c < o * 0.98) & (rvol >= 2.5)).values
        self.washout = ((ret1 <= -0.06) & (rvol >= 3)).values
        self.gap_down = (gapr <= -0.05).values
        self.regime_idx = idx.values; self.regime_avg = avg.values
        self.bull = (idx > avg).values

    def col(self, name):
        if not hasattr(self, "_colmap"):
            self._colmap = {c: i for i, c in enumerate(self.cols)}
        return self._colmap[name]

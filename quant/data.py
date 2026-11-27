"""Prices from Yahoo Finance (NSE .NS), split/bonus/dividend adjusted."""
import datetime as dt
import pathlib
import time
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load_universe(path=None):
    if path is None:
        from . import config as C
        path = ROOT / getattr(C, "UNIVERSE_FILE", "universe.txt")
    tick, seg = [], {}
    for line in pathlib.Path(path).read_text().splitlines():
        if line.startswith("#") or ":" not in line:
            continue
        s, names = line.split(":", 1)
        for n in names.split():
            tick.append(n)
            seg[n] = s.strip()
    return tick, pd.Series(seg)


def download(tickers, start, chunk=50, pause=1.0):
    import yfinance as yf
    parts = {f: [] for f in ["Open", "High", "Low", "Close", "Volume"]}
    for i in range(0, len(tickers), chunk):
        batch = [t + ".NS" for t in tickers[i:i + chunk]]
        for attempt in range(4):
            try:
                d = yf.download(batch, start=start, progress=False, auto_adjust=True,
                                threads=True, group_by="column")
                break
            except Exception:
                time.sleep(8 * (attempt + 1))
        else:
            raise RuntimeError("Yahoo download failed")
        for f in parts:
            x = d[f]
            if isinstance(x, pd.Series):
                x = x.to_frame(batch[0])
            parts[f].append(x)
        time.sleep(pause)
    out = {}
    for f, p in parts.items():
        df = pd.concat(p, axis=1)
        df.columns = [c.replace(".NS", "") for c in df.columns]
        df = df.reindex(columns=tickers)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        out[f[0].lower()] = df  # o h l c v
    # drop dates where almost nothing traded (holidays that slipped in)
    good = out["c"].notna().sum(axis=1) > 0.5 * len(tickers)
    return {k: v[good] for k, v in out.items()}


def now_ist():
    return dt.datetime.now(IST)


def session_fraction(t=None):
    """Share of the 09:15-15:30 session elapsed, and an estimate of the share of the
    day's volume traded by then (volume is front- and back-loaded)."""
    t = t or now_ist()
    start = t.replace(hour=9, minute=15, second=0, microsecond=0)
    elapsed = (t - start).total_seconds() / (375 * 60)
    elapsed = float(np.clip(elapsed, 0, 1))
    vol_frac = min(1.0, 0.85 * elapsed) if elapsed < 1 else 1.0
    return elapsed, max(vol_frac, 0.05)


def load_cached(study_dir):
    """Use the study's full-history parquet files (for the backtest)."""
    d = pathlib.Path(study_dir)
    return {k: pd.read_parquet(d / f"{n}.parquet") for k, n in
            [("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")]}

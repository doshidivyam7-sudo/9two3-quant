"""Run the live rules day by day over history, with costs, on Rs 1 lakh.

python backtest.py [--start 2015-01-01] [--data path/to/parquet_dir]
Writes out/backtest.json
"""
import argparse, json, pathlib, sys
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from quant import config as C
from quant.data import load_universe, download, load_cached
from quant.features import Features
from quant.engine import Engine


def add_etf_proxy(P, data_dir=None):
    """Backtest stand-in for the midcap ETF: the Nifty Midcap 50 index (Yahoo has little ETF history)."""
    f = pathlib.Path(data_dir or "") / "etf.parquet"
    if data_dir and f.exists():
        x = pd.read_parquet(f)
        c, o = x["idx"], x["idx_o"]
    else:
        import yfinance as yf
        x = yf.download("^NSEMDCP50", start="2014-01-01", progress=False, auto_adjust=True)
        c, o = x["Close"].squeeze(), x["Open"].squeeze()
    c = c.reindex(P["c"].index).ffill(); o = o.reindex(P["c"].index).fillna(c)
    o = o.where(o > 0, c)
    for etf in (C.TOM["etf"], C.CORE["etf"]):
        for k, v in (("o", o), ("h", np.maximum(o, c)), ("l", np.minimum(o, c)), ("c", c), ("v", c * 0 + 1e9)):
            P[k] = P[k].copy(); P[k][etf] = v
    return P


def stats(eq):
    eq = eq.dropna()
    if len(eq) < 30:
        return {}
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": cagr * 100, "vol": vol * 100, "sharpe": (r.mean() * 252) / vol if vol else None,
            "max_dd": dd * 100, "total": (eq.iloc[-1] / eq.iloc[0] - 1) * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--data", default=None, help="folder with open/high/low/close/volume parquet")
    a = ap.parse_args()
    tick, seg = load_universe()
    P = load_cached(a.data) if a.data else download(tick, "2014-01-01")
    P = {k: v.reindex(columns=tick) for k, v in P.items()}
    P = add_etf_proxy(P, a.data)
    F = Features(P, seg)
    e = Engine(F)
    t0 = int(np.searchsorted(F.index, pd.Timestamp(a.start)))
    expo = []
    for t in range(t0, len(F.index)):
        eq = e.step(t)
        inv = eq - e.S["cash"]
        expo.append(inv / eq if eq else 0)
    eq = pd.Series({pd.Timestamp(d): v for d, v in e.S["equity"]})
    bench = pd.Series(F.regime_idx, index=F.index).loc[eq.index]
    bench = bench / bench.iloc[0] * C.CAPITAL
    trades = pd.DataFrame(e.S["trades"])
    y0 = pd.Timestamp(a.start).year
    periods = {"All": (None, None), f"{y0}–2020": (a.start, "2020-12-31"), "2021–2026": ("2021-01-01", None)}
    out = {"periods": [], "books": [], "equity": [], "trades": e.S["trades"][-400:],
           "meta": {"start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
                    "capital": C.CAPITAL, "avg_exposure": float(np.mean(expo) * 100), "n_trades": len(trades)}}
    for name, (s, en) in periods.items():
        sl = slice(s, en)
        st, sb = stats(eq.loc[sl]), stats(bench.loc[sl])
        tr = trades[(trades.exit_date >= (s or "1900")) & (trades.exit_date <= (en or "2100"))] if len(trades) else trades
        out["periods"].append({"period": name, **{f"sys_{k}": v for k, v in st.items()},
                               **{f"bench_{k}": v for k, v in sb.items()},
                               "trades": int(len(tr)), "win_rate": float((tr.pnl > 0).mean() * 100) if len(tr) else None})
    if len(trades):
        for b, g in trades.groupby("book"):
            out["books"].append({"book": b, "trades": int(len(g)), "win_rate": float((g.pnl > 0).mean() * 100),
                                 "avg_pnl_pct": float(g.pnl_pct.mean()), "total_pnl": float(g.pnl.sum()),
                                 "avg_days": float(g.days.mean())})
        out["exit_reasons"] = trades.groupby("reason_out").agg(n=("pnl", "size"), avg=("pnl_pct", "mean")).reset_index().to_dict("records")
    wk = eq.resample("W-FRI").last().dropna()
    bw = bench.resample("W-FRI").last().reindex(wk.index)
    out["equity"] = [{"date": str(d.date()), "system": round(float(v), 0), "benchmark": round(float(bw[d]), 0)} for d, v in wk.items()]
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "backtest.json").write_text(json.dumps(out, default=float, indent=1))
    meta = [{"label": "backtest.py", "value": pathlib.Path(__file__).read_text(), "type": "code", "lang": "python"},
            {"label": "engine.py", "value": (ROOT / "quant" / "engine.py").read_text(), "type": "code", "lang": "python"},
            {"label": "config.py", "value": (ROOT / "quant" / "config.py").read_text(), "type": "code", "lang": "python"},
            {"label": "Data", "value": "Yahoo Finance daily NSE prices; today's Nifty Midcap 150 + Smallcap 250 members"},
            {"label": "Benchmark", "value": "Equal-weight index of the same eligible universe"}]
    def rnd(rows):
        return [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    for name, rows in (("bt_equity", out["equity"]), ("bt_periods", rnd(out["periods"])), ("bt_books", rnd(out["books"]))):
        (ROOT / "out" / f"{name}.json").write_text(json.dumps({"rows": rows, "meta": meta}, default=float))
    for p in out["periods"]:
        print(p)
    for b in out["books"]:
        print(b)
    print(out["meta"])
    print(pd.DataFrame(out.get("exit_reasons", [])).to_string())


if __name__ == "__main__":
    main()

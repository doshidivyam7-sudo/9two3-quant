"""Save the last 7 days of 5-minute bars for the universe (Yahoo keeps only ~60 days).
python tools/archive_intraday.py  ->  data/intraday/YYYY-MM-DD.parquet (long format)"""
import sys, pathlib, time, datetime as dt
import pandas as pd, yfinance as yf
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant.data import load_universe
tick, _ = load_universe()
parts = []
for i in range(0, len(tick), 50):
    b = [t + ".NS" for t in tick[i:i + 50]]
    d = yf.download(b, period="7d", interval="5m", progress=False, auto_adjust=False, threads=True, group_by="ticker")
    for t in b:
        try:
            x = d[t].dropna(how="all")
        except Exception:
            continue
        if len(x):
            x = x[["Open", "High", "Low", "Close", "Volume"]].copy()
            x["ticker"] = t[:-3]
            parts.append(x)
    time.sleep(1)
df = pd.concat(parts)
df.index.name = "time"
out = ROOT / "data" / "intraday" / f"{dt.date.today().isoformat()}.parquet"
out.parent.mkdir(parents=True, exist_ok=True)
df.reset_index().to_parquet(out, index=False)
print("saved", out, len(df), "rows", df["ticker"].nunique(), "stocks")

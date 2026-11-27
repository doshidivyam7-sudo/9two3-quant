"""Rebuild the all-NSE universe and market caps from Yahoo's screener.
python tools/refresh_universe.py  -> universe_all.txt, universe_mcap.csv"""
import pathlib, time
import pandas as pd, yfinance as yf
from yfinance import EquityQuery as Q
ROOT = pathlib.Path(__file__).resolve().parents[1]
q = Q('and', [Q('eq', ['exchange', 'NSI']), Q('gt', ['intradaymarketcap', 1_000_000_000])])
rows, off = [], 0
while True:
    for a in range(3):
        try:
            r = yf.screen(q, size=250, offset=off, sortField='intradaymarketcap', sortAsc=False); break
        except Exception:
            time.sleep(3)
    qs = r.get('quotes', []); rows += qs
    if len(qs) < 250: break
    off += 250
df = pd.DataFrame(rows)
df = df[df.quoteType == 'EQUITY'].drop_duplicates('symbol')
df['tk'] = df.symbol.str.replace('.NS', '', regex=False)
df['mcap_cr'] = (df.marketCap / 1e7).round(0)
seg = pd.cut(df.mcap_cr, [0, 1000, 15000, 1e9], labels=['MICRO', 'SMALL', 'MID']).astype(str)
lines = [f'# All NSE equities with market cap > Rs 100 cr (Yahoo screener, {pd.Timestamp.today().date()}). Segment sets trading costs.']
lines += [s + ': ' + ' '.join(df.tk[seg == s]) for s in ['MID', 'SMALL', 'MICRO']]
(ROOT / 'universe_all.txt').write_text('\n'.join(lines) + '\n')
df[['tk', 'mcap_cr']].rename(columns={'tk': 'ticker'}).to_csv(ROOT / 'universe_mcap.csv', index=False)
print(len(df), 'stocks;', int((df.mcap_cr >= 5000).sum()), 'at or above Rs 5,000 cr')

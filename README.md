# 9two3 Quant Desk

A rules-based engine for Indian mid & small caps (Nifty Midcap 150 + Smallcap 250), cash market only.
It suggests entries, stops and exits; you place every order yourself. It keeps a paper book on ₹1 lakh
so the model's live record builds up day by day.

## Daily cycle (weekdays, run automatically)

| Time (IST) | Command | What it does |
|---|---|---|
| ~14:35 | `python run_daily.py preclose` | Scans today's live prices: what to **buy or sell in the last 30 minutes** (BTST and swing entries, BTST exits, time stops). Writes `state/preclose_orders.json`. |
| ~09:27 | `python run_daily.py morning` | Morning brief: last night's open orders checked against the actual open (buy now or skip), sells due, warnings on holdings, and the watchlist for the 3 PM window. Email only. |
| ~16:45 | `python run_daily.py postclose` | Fills the paper book (today's open and close), checks stops and avoid signals, and lists what to **buy or sell at tomorrow's open** (positional entries, exits). Updates `state/book.json`. |

Both write dashboard files to `out/` and an email body to `out/email.txt`. On NSE holidays they write
`out/SKIP` and do nothing else. See `dashboard/DESK.md` for pushing results to the dashboard.

## The rules (from the edge-decay study, see `research_edge_decay.py`)

- **Regime**: Bull when the equal-weight index of the universe is above its 200-day average.
- **Fast-churn mode (current):** nothing is held more than 5 sessions; the positional book has 0 slots.
  Universe: all NSE equities scanned, trades only in companies >= Rs 5,000 cr (`universe_all.txt`, `universe_mcap.csv`).
- **Positional** (off in fast-churn mode; was 3 slots, 120 sessions): top 20% on a composite of 6-1 month momentum, distance above the
  200-DMA, nearness to the 52-week high and rising volume. Buy at the open (skip if it opens >1.5% above
  the signal close). Stop 3× ATR(20). Bear regime: half risk.
- **Swing** (2 slots, 5 sessions, Bull only): first 52-week high in 60+ days on 1.5× volume. Buy into the close. Stop 2.5× ATR.
- **BTST** (3 slots): gap-up ≥4% on ≥2.5× volume holding at or above the open. Buy into the close, sell into the next close.
- **Exits**: next open on a failed gap-up, high-volume washout, large gap-down, or a close below the stop.
  Cooldown afterwards (10 sessions, 60 after a washout).
- **Sizing**: risk 1% / 0.75% / 0.5% of equity, max 25% in one stock, 5 positions in total. Idle cash is assumed
  parked in a liquid ETF.

All knobs are in `quant/config.py`.

## Backtest

`python backtest.py` (downloads history) or `python backtest.py --data <parquet dir>`.
Fast-churn mode, Nov 2016 – Nov 2026 on ₹1 lakh: about 14.8% a year, worst fall about −18%, Sharpe 1.46
(2016–20 about 3% a year, 2021–26 about 24%). The 6-month-hold version made about 23.6% a year (worst fall −13.5%).
Universes use today's listings (survivorship bias), and the rules were chosen on the same history.

## Upkeep

- Refresh `universe.txt` after the March and September index rebalances.
- Rerun `research_edge_decay.py` and `backtest.py` monthly; drop any signal whose edge has gone.
- Not yet included: delivery %, bulk/block deals, promoter buying, results dates (need NSE files).

Model suggestions for your own decisions, not investment advice.

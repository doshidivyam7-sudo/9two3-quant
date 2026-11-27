# How to use the 9two3 Quant Desk (plain language)

You don't need to code. The model runs itself every trading day and tells you what to do.

## What you get each trading day

0. **~9:30 AM email — "morning brief".** Last night's buys checked against the real opening price
   (buy now, or skip if it opened above the max price), any sells due, warnings on what you hold, and a
   watchlist for the afternoon. It never suggests intraday trades.
1. **~2:40 PM email — "into the close".** Anything to buy or sell between 3:00 and 3:25 PM today.
   Buy with a limit order near the reference price. Skip anything that has fallen below today's low.
2. **~4:50 PM email — "at tomorrow's open".** Anything to buy or sell when the market opens tomorrow.
   For buys, place a limit order at the **max price** shown. If it opens above that, don't chase; skip it.
3. **The dashboard** (9two3 Quant Desk) always shows the latest actions, open positions, stops and results.

If an email says "No actions", do nothing. Quiet days are normal.

## The only rules you follow by hand

- **Stops are on the close, not intraday.** If a stock *closes* below its stop, the evening email will tell
  you to sell at the next open. Don't put a stop-loss order in the system; intraday wicks would shake you out.
- **Never pay above the max price.**
- **Exit when the email says so**: a stop, a warning signal, or the holding time running out.
  There are no price targets; winners are allowed to run.
- **Idle cash**: park it in a liquid ETF (for example LIQUIDBEES) so it earns while it waits.

## The five kinds of trade

| Book | Holding time | How many | When you act |
|---|---|---|---|
| Breakout (first new 52-week high on volume) | up to 5 sessions (1 week) | up to 2 | last 30 minutes |
| BTST (gap-up that holds) | overnight | up to 3 | last 30 minutes, sell next day's close |
| Month-end window (midcap ETF) | 5 sessions around month end | 1 | last 30 minutes |

**Nothing is held longer than 7 calendar days (5 trading sessions).** The 6-month momentum trades are
switched off at your request. Over 10 years this fast version made about 15% a year (worst fall −18%),
against about 24% (worst fall −14%) for the version with 6-month holds. Most of the gap is trading
costs: it trades about 195 times a year.

**Which stocks:** every NSE stock is scanned (about 2,250), but trades are only taken in companies worth
₹5,000 crore or more. Signals in smaller companies are listed in the emails for information only.
| Cash | — | — | sits in a liquid ETF |

## What "risk ₹" means

It's what you lose if the stock hits its stop: about ₹750 on a ₹1 lakh account for a breakout trade, ₹500 for a BTST.
That's why share counts look small. The point is to survive the losers, because even good trades lose
about half the time.

## What the model can't do

- No intraday trading (tested: nothing beat costs).
- No forecasts or news. It follows rules that worked on 2015–2026 data.
- It can be wrong for months. Judge it after 30+ closed trades, not 3.

## Changing settings

Ask Claude, for example: "change capital to ₹5 lakh", "turn off BTST", "add these stocks".
Everything lives in `quant/config.py`.

Model suggestions for your own decisions, not investment advice.

"""All the knobs in one place. Change these, not the code."""

CAPITAL = 100_000            # starting paper capital, Rs

# Risk per trade as a share of current equity (the loss if the stop is hit)
RISK = {"positional": 0.010, "swing": 0.0075, "btst": 0.005}
BEAR_RISK_MULT = 0.5         # positional risk is halved in a bear regime

# How many positions at once
MAX_POS = {"total": 5, "positional": 3, "swing": 2, "btst": 2}
MAX_WEIGHT = 0.25            # no position above 25% of equity

# Holding periods (trading days) — from the edge-decay study
HOLD = {"positional": 120, "swing": 20, "btst": 1, "tom": 5}

# Stops: multiple of 20-day ATR below entry (BTST uses the signal day's low)
ATR_MULT = {"positional": 3.0, "swing": 2.5}
MIN_STOP_PCT = 0.015         # never size off a stop closer than 1.5%

# Don't buy at the open if it gaps more than this above the signal close
CHASE = 0.015

# After an avoid signal fires in a stock: no new entries for this many days
COOLDOWN = {"gap_fail": 10, "washout": 60, "gap_down": 10}

# Tradability
MIN_PRICE = 20
MIN_TRADED_VALUE = 2e7       # 20-day median traded value, Rs (Rs 2 crore)

# Costs: round trip % (STT 0.1% each side + charges + slippage) and DP charge per sell
COST_PCT = {"MID": 0.0045, "SMALL": 0.0075}
DP_CHARGE = 16.0

# Idle cash is parked in a liquid ETF (e.g. LIQUIDBEES); annual yield assumed
LIQUID_YIELD = 0.055
USE_PRICE_STOP = {"positional": True, "swing": True, "btst": False}

# Month-end SIP-flow window: hold a midcap ETF from the close of the 3rd-last trading day
# of the month to the close of the 3rd trading day of the next month (2012-26: 91% of
# Nifty Midcap 50 gains came in these ~5 days a month).
TOM = {"enabled": True, "etf": "MID150BEES", "weight": 0.5, "bull_only": True,
       "enter_days_left": 2, "exit_day": 3}
COST_PCT["ETF"] = 0.002

# Delivery
EMAIL_TO = ""                # the scheduled task holds the address (repo is public)

# Regime: equal-weight universe index vs its N-day average
REGIME_SMA = 200

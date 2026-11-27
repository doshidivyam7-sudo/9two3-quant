"""All the knobs in one place. Change these, not the code."""

CAPITAL = 100_000            # starting paper capital, Rs

# Risk per trade as a share of current equity (the loss if the stop is hit)
RISK = {"positional": 0.010, "swing": 0.0075, "btst": 0.005}
BEAR_RISK_MULT = 0.5         # positional risk is halved in a bear regime

# How many positions at once
MAX_POS = {"total": 5, "positional": 3, "swing": 2, "btst": 2}
MAX_WEIGHT = 0.25            # no position above 25% of equity

# Holding periods (trading days) — from the edge-decay study
HOLD = {"positional": 120, "swing": 20, "btst": 1, "tom": 5, "core": 9999}

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

# Regime filter. mode "sma200": bull when index > 200-day avg.
# "fast": also bull when index > 50-day avg and that avg is rising (re-enters V-shaped recoveries sooner).
# band: hysteresis (e.g. 0.01 = switch only when 1% through the line) to cut whipsaws.
REGIME = {"mode": "sma200", "band": 0.0}

# Swing breakouts only in stocks already ranked this high on the momentum composite (0 = off)
SWING_MIN_COMP = 0.0

# Core: in a bull regime keep part of the idle cash in a broad midcap ETF instead of a liquid fund
CORE = {"enabled": False, "etf": "MIDCAPETF", "weight": 0.4, "reserve": 0.35, "rebalance": 0.10}
COST_PCT["CORE"] = 0.002

# Positional: sell at the next open if the stock's momentum rank falls below this (0 = off),
# checked only after MIN days held so new positions get room
POS_EXIT_COMP = 0.0
POS_EXIT_MIN_DAYS = 20

# Liquidity: never hold more than this share of a stock's 20-day median daily traded value,
# and add market impact that grows with order size (square-root rule, each side).
MAX_ADV_PCT = 0.05
IMPACT_COEF = 0.003          # 0.3% at 10% of a day's value, 0.1% at ~1%

# Delivery
EMAIL_TO = ""                # the scheduled task holds the address (repo is public)

# Regime: equal-weight universe index vs its N-day average
REGIME_SMA = 200

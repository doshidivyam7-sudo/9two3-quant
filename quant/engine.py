"""The trading rules and the paper book. One engine for the backtest and the live runs.

Daily cycle for day t
  1. fill_open(t)          orders queued last night fill at today's open
  2. decide_close(t)       what to buy/sell in the last 30 minutes (pre-close run)
  3. fill_close(t)         those orders fill at the official close
  4. decide_after_close(t) exits and positional buys for tomorrow's open
  5. mark(t)               equity at the close
"""
import copy
import math
import numpy as np
import pandas as pd
from . import config as C


def new_state(capital=C.CAPITAL):
    return {"cash": float(capital), "positions": [], "pending_open": [], "cooldown": {},
            "trades": [], "equity": [], "skipped": [], "last_date": None}


class Engine:
    def __init__(self, F, state=None):
        self.F = F
        self.S = state if state is not None else new_state()
        self.pos_of = {d: i for i, d in enumerate(F.index)}

    # ------------------------------------------------------------ helpers
    def _t_of(self, date_str):
        import pandas as pd
        return self.pos_of.get(pd.Timestamp(date_str))

    def _date(self, t):
        return str(self.F.index[t].date())

    def _px(self, arr, t, j, fallback=None):
        x = arr[t, j]
        return float(x) if np.isfinite(x) else fallback

    def _cost(self, value, seg, side, tv=None):
        c = value * C.COST_PCT.get(seg, C.COST_PCT["SMALL"]) / 2
        if tv and np.isfinite(tv) and tv > 0 and seg not in ("ETF",):
            c += value * C.IMPACT_COEF * math.sqrt(value / (0.1 * tv))
        return c + (C.DP_CHARGE if side == "SELL" else 0.0)

    def equity(self, t):
        F = self.F
        val = 0.0
        for p in self.S["positions"]:
            j = F.col(p["ticker"])
            px = self._px(F.c, t, j, p.get("last_close", p["entry_px"]))
            val += px * p["shares"]
        return self.S["cash"] + val

    def held(self):
        return {p["ticker"] for p in self.S["positions"]}

    def count(self, book=None, exclude=()):
        return sum(1 for p in self.S["positions"]
                   if (p["book"] == book if book else p["book"] not in ("tom", "core")) and p["ticker"] not in exclude)

    def days_held(self, p, t):
        t0 = self._t_of(p["entry_date"])
        return (t - t0) if t0 is not None else p.get("days_held", 0)

    def in_cooldown(self, ticker, t):
        cd = self.S["cooldown"].get(ticker)
        if not cd:
            return False
        t0 = self._t_of(cd["date"])
        if t0 is None:
            return False
        return (t - t0) < C.COOLDOWN[cd["kind"]]

    def month_pos(self, t):
        """(trading day number in month, trading days left after t in month)."""
        idx = self.F.index
        d = idx[t]
        k = sum(1 for x in idx[max(0, t - 25):t + 1] if x.month == d.month and x.year == d.year)
        later = [x for x in idx[t + 1:t + 25] if x.month == d.month and x.year == d.year]
        if t < len(idx) - 1:
            left = len(later)
        else:  # live: future unknown, count weekdays to month end
            nxt = (d + pd.offsets.MonthBegin(1)).date()
            left = int(np.busday_count((d + pd.Timedelta(days=1)).date(), nxt))
        return k, left

    def size(self, book, px, stop, equity, cash, bear=False, tv=None):
        risk = C.RISK[book] * equity * (C.BEAR_RISK_MULT if (bear and book == "positional") else 1)
        dist = max(px - stop, px * C.MIN_STOP_PCT)
        n = min(risk / dist, C.MAX_WEIGHT * equity / px, (cash * 0.995) / px)
        if tv is not None and np.isfinite(tv) and tv > 0:
            n = min(n, C.MAX_ADV_PCT * tv / px)
        return int(math.floor(n)) if n >= 1 else 0

    # ------------------------------------------------------------ 1. open
    def fill_open(self, t):
        F, S = self.F, self.S
        pend, S["pending_open"] = S["pending_open"], []
        for o in [x for x in pend if x["action"] == "SELL"]:
            self._sell(t, o["ticker"], self._px(F.o, t, F.col(o["ticker"])), o["reason"])
        eq = self.equity(t - 1) if t > 0 else S["cash"]
        need = sum(1 for x in pend if x["action"] == "BUY")
        core = next((p for p in S["positions"] if p["book"] == "core"), None)
        if core and need and S["cash"] < need * C.MAX_WEIGHT * eq:
            self._sell(t, core["ticker"], self._px(F.o, t, F.col(core["ticker"])), "Core ETF: cash needed for new buys")
        for o in [x for x in pend if x["action"] == "BUY"]:
            j = F.col(o["ticker"])
            op = self._px(F.o, t, j)
            if op is None or op > o["limit"]:
                S["skipped"].append({"date": self._date(t), "ticker": o["ticker"], "book": o["book"],
                                     "why": "opened above limit" if op else "no price"})
                continue
            if self.count() >= C.MAX_POS["total"] or self.count(o["book"]) >= C.MAX_POS[o["book"]]:
                continue
            stop = op - o["stop_dist"]
            n = self.size(o["book"], op, stop, eq, S["cash"], o.get("bear", False), F.tv[t - 1, j] if t > 0 else None)
            if n < 1:
                continue
            self._buy(t, o["ticker"], o["book"], op, n, stop, o["reason"])

    # ------------------------------------------------------------ 2. close decisions
    def decide_close(self, t):
        """Orders to execute in the last 30 minutes of day t."""
        F, S = self.F, self.S
        orders, selling = [], set()
        k, left = self.month_pos(t)
        for p in S["positions"]:
            if p["book"] == "core":
                continue
            if p["book"] == "tom":
                if p["entry_date"][:7] != self._date(t)[:7] and k >= C.TOM["exit_day"]:
                    orders.append({"action": "SELL", "ticker": p["ticker"], "book": "tom", "shares": p["shares"],
                                   "reason": "Month-end window over (3rd trading day)"})
                    selling.add(p["ticker"])
                continue
            d = self.days_held(p, t)
            if d >= C.HOLD[p["book"]]:
                why = {"btst": "BTST exit at next-day close", "swing": "20-day time stop",
                       "positional": "120-day time stop"}[p["book"]]
                orders.append({"action": "SELL", "ticker": p["ticker"], "book": p["book"],
                               "shares": p["shares"], "reason": why})
                selling.add(p["ticker"])
        held = self.held() - selling
        queued = {o["ticker"] for o in S["pending_open"]}
        n_tot = self.count(exclude=selling)
        n_book = {b: self.count(b, exclude=selling) for b in ("positional", "swing", "btst")}
        eq = self.equity(t)
        cash = S["cash"] + sum(self._px(F.c, t, F.col(o["ticker"]), 0) * o["shares"] for o in orders)
        bull = bool(F.bull[t])
        cands = []
        if bull:
            js = np.where(F.hi52[t])[0]
            cands += [("swing", j, F.rvol[t, j], "Fresh 52-week high on volume") for j in js]
        js = np.where(F.gap_hold[t])[0]
        cands += [("btst", j, F.rvol[t, j], "Gap-up of 4%+ holding on heavy volume") for j in js]
        order_book = {"swing": 0, "btst": 1}
        cands.sort(key=lambda x: (order_book[x[0]], -(x[2] if np.isfinite(x[2]) else 0)))
        for book, j, rv, why in cands:
            tk = F.cols[j]
            if tk in held or tk in queued or self.in_cooldown(tk, t):
                continue
            if book == "swing" and C.SWING_MIN_COMP > 0 and not (F.comp[t, j] >= C.SWING_MIN_COMP):
                continue
            if n_tot >= C.MAX_POS["total"] or n_book[book] >= C.MAX_POS[book]:
                continue
            px = self._px(F.c, t, j)
            if px is None:
                continue
            if book == "btst":
                lo = self._px(F.l, t, j, px)
                stop = min(lo, px * (1 - C.MIN_STOP_PCT))
            else:
                a = self._px(F.atr, t, j)
                if a is None:
                    continue
                stop = px - C.ATR_MULT["swing"] * a
            n = self.size(book, px, stop, eq, cash, tv=F.tv[t, j])
            if n < 1:
                continue
            orders.append({"action": "BUY", "ticker": tk, "book": book, "shares": n, "px": px,
                           "stop": round(stop, 2), "reason": why, "rvol": round(float(rv), 1)})
            held.add(tk); n_tot += 1; n_book[book] += 1; cash -= n * px
        etf = C.TOM["etf"]
        if (C.TOM["enabled"] and left == C.TOM["enter_days_left"] and etf in F.cols
                and not any(p["book"] == "tom" for p in S["positions"])
                and (bull or not C.TOM["bull_only"])):
            px = self._px(F.c, t, F.col(etf))
            if px:
                n = int(min(C.TOM["weight"] * eq, cash * 0.995) // px)
                if n >= 1:
                    orders.append({"action": "BUY", "ticker": etf, "book": "tom", "shares": n, "px": px,
                                   "stop": round(px * 0.5, 2),
                                   "reason": "Month-end SIP-flow window (last 2 + first 3 trading days)"})
                    cash -= n * px
        orders += self._core_orders(t, eq, cash, bull)
        return orders

    def _core_orders(self, t, eq, cash, bull):
        F, S = self.F, self.S
        ce = C.CORE["etf"]
        if not C.CORE["enabled"] or ce not in F.cols:
            return []
        px = self._px(F.c, t, F.col(ce))
        if not px:
            return []
        cur = next((p for p in S["positions"] if p["book"] == "core"), None)
        cur_val = cur["shares"] * px if cur else 0.0
        target = 0.0
        if bull:
            target = max(0.0, min(C.CORE["weight"] * eq, cash + cur_val - C.CORE["reserve"] * eq))
        diff = target - cur_val
        if target == 0 and cur:
            return [{"action": "SELL", "ticker": ce, "book": "core", "shares": cur["shares"],
                     "reason": "Core ETF: regime turned bear" if not bull else "Core ETF: cash needed"}]
        if abs(diff) < C.CORE["rebalance"] * eq:
            return []
        n = int(abs(diff) // px)
        if n < 1:
            return []
        if diff > 0:
            return [{"action": "BUY", "ticker": ce, "book": "core", "shares": n, "px": px, "stop": round(px * 0.5, 2),
                     "reason": "Core ETF: bull regime, idle cash put to work"}]
        return [{"action": "TRIM", "ticker": ce, "book": "core", "shares": n, "reason": "Core ETF: free up cash"}]

    # ------------------------------------------------------------ 3. close fills
    def fill_close(self, t, orders):
        F = self.F
        for o in [x for x in orders if x["action"] == "TRIM"]:
            self._trim(t, o["ticker"], o["shares"], self._px(F.c, t, F.col(o["ticker"])))
        for o in [x for x in orders if x["action"] == "SELL"]:
            if o["ticker"] in self.held():
                self._sell(t, o["ticker"], self._px(F.c, t, F.col(o["ticker"])), o["reason"])
        for o in [x for x in orders if x["action"] == "BUY"]:
            j = F.col(o["ticker"])
            px = self._px(F.c, t, j)
            if px is None:
                continue
            if o["book"] == "core" and o["ticker"] in self.held():
                self._add(t, o["ticker"], px, min(o["shares"], int(self.S["cash"] * 0.995 // px)))
                continue
            if o["ticker"] in self.held():
                continue
            if o["book"] not in ("tom", "core") and (self.count() >= C.MAX_POS["total"] or self.count(o["book"]) >= C.MAX_POS[o["book"]]):
                continue
            n = min(o["shares"], int(self.S["cash"] * 0.995 // px))
            if n < 1:
                continue
            stop = o["stop"] if o["stop"] < px else px * (1 - C.MIN_STOP_PCT)
            self._buy(t, o["ticker"], o["book"], px, n, stop, o["reason"])

    # ------------------------------------------------------------ 4. after-close decisions
    def decide_after_close(self, t):
        F, S = self.F, self.S
        # cooldowns from today's avoid signals, anywhere in the universe
        for name, arr in (("washout", F.washout), ("gap_fail", F.gap_fail), ("gap_down", F.gap_down)):
            for j in np.where(arr[t])[0]:
                S["cooldown"][F.cols[j]] = {"date": self._date(t), "kind": name}
        pend, selling = [], set()
        why_flag = {"gap_fail": "Gap-up failed (avoid signal)", "washout": "High-volume washout (avoid signal)",
                    "gap_down": "Large gap-down (avoid signal)"}
        for p in S["positions"]:
            if p["book"] in ("tom", "core"):
                continue
            j = F.col(p["ticker"])
            reason = None
            for k, arr in (("gap_fail", F.gap_fail), ("washout", F.washout), ("gap_down", F.gap_down)):
                if arr[t, j]:
                    reason = why_flag[k]
            px = self._px(F.c, t, j)
            if (reason is None and p["book"] == "positional" and C.POS_EXIT_COMP > 0
                    and self.days_held(p, t) >= C.POS_EXIT_MIN_DAYS and np.isfinite(F.comp[t, j])
                    and F.comp[t, j] < C.POS_EXIT_COMP):
                reason = "Momentum rank faded"
            if reason is None and px is not None and px < p["stop"] and C.USE_PRICE_STOP.get(p["book"], True):
                reason = "Closed below stop"
            if reason:
                pend.append({"action": "SELL", "ticker": p["ticker"], "book": p["book"], "reason": reason})
                selling.add(p["ticker"])
        n_tot = self.count(exclude=selling)
        n_pos = self.count("positional", exclude=selling)
        free = min(C.MAX_POS["positional"] - n_pos, C.MAX_POS["total"] - n_tot)
        bear = not bool(F.bull[t])
        if free > 0:
            comp = F.comp[t]
            ok = np.isfinite(comp) & (comp >= 0.8) & (F.c[t] > F.sma200[t]) & F.elig[t] \
                & ~F.gap_fail[t] & ~F.washout[t] & ~F.gap_down[t] & np.isfinite(F.atr[t])
            js = [j for j in np.argsort(-np.nan_to_num(comp, nan=-1)) if ok[j]]
            held = self.held()
            eq = self.equity(t)
            for j in js:
                if free <= 0:
                    break
                tk = F.cols[j]
                if tk in held or self.in_cooldown(tk, t):
                    continue
                px = float(F.c[t, j]); dist = C.ATR_MULT["positional"] * float(F.atr[t, j])
                if self.size("positional", px, px - dist, eq, eq, bear, F.tv[t, j]) < 1:
                    continue  # too expensive to size
                pend.append({"action": "BUY", "ticker": tk, "book": "positional",
                             "limit": round(px * (1 + C.CHASE), 2), "stop_dist": dist, "signal_close": px,
                             "bear": bear, "score": round(float(comp[j]), 3),
                             "reason": f"Momentum/trend composite in top {100 - comp[j] * 100:.0f}%"})
                free -= 1
        S["pending_open"] = pend
        return pend

    # ------------------------------------------------------------ 5. mark
    def mark(self, t):
        F, S = self.F, self.S
        if S["cash"] > 0 and S.get("last_date") != self._date(t):
            S["cash"] *= (1 + C.LIQUID_YIELD / 252)
        for p in S["positions"]:
            px = self._px(F.c, t, F.col(p["ticker"]))
            if px is not None:
                p["last_close"] = px
            p["days_held"] = self.days_held(p, t)
        eq = self.equity(t)
        S["equity"].append([self._date(t), round(eq, 2)])
        S["last_date"] = self._date(t)
        return eq

    # ------------------------------------------------------------ fills
    def _buy(self, t, tk, book, px, n, stop, reason):
        S = self.S
        j = self.F.col(tk)
        seg = self.F.seg[j]
        val = px * n
        cost = self._cost(val, seg, "BUY", self.F.tv[t, j])
        S["cash"] -= val + cost
        S["positions"].append({"ticker": tk, "book": book, "entry_date": self._date(t), "entry_px": round(px, 2),
                               "shares": int(n), "stop": round(float(stop), 2), "reason": reason, "seg": seg,
                               "entry_cost": round(cost, 2), "last_close": round(px, 2), "days_held": 0})

    def _add(self, t, tk, px, n):
        if n < 1:
            return
        S = self.S
        p = next(q for q in S["positions"] if q["ticker"] == tk)
        cost = self._cost(px * n, p["seg"], "BUY")
        S["cash"] -= px * n + cost
        tot = p["shares"] + n
        p["entry_px"] = round((p["entry_px"] * p["shares"] + px * n) / tot, 4)
        p["entry_cost"] = round(p["entry_cost"] + cost, 2); p["shares"] = tot

    def _trim(self, t, tk, n, px):
        S = self.S
        p = next((q for q in S["positions"] if q["ticker"] == tk), None)
        if not p or px is None:
            return
        n = min(n, p["shares"])
        if n >= p["shares"]:
            return self._sell(t, tk, px, "Core ETF trimmed out")
        val = px * n; cost = self._cost(val, p["seg"], "SELL")
        S["cash"] += val - cost
        frac = n / p["shares"]
        pnl = (px - p["entry_px"]) * n - p["entry_cost"] * frac - cost
        S["trades"].append({"ticker": tk, "book": p["book"], "entry_date": p["entry_date"], "entry_px": p["entry_px"],
                            "exit_date": self._date(t), "exit_px": round(px, 2), "shares": n, "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl / (p["entry_px"] * n) * 100, 2), "days": self.days_held(p, t),
                            "reason_in": p["reason"], "reason_out": "Core ETF trimmed"})
        p["entry_cost"] = round(p["entry_cost"] * (1 - frac), 2); p["shares"] -= n

    def _sell(self, t, tk, px, reason):
        S = self.S
        for i, p in enumerate(S["positions"]):
            if p["ticker"] != tk:
                continue
            px = px if px is not None else p.get("last_close", p["entry_px"])
            val = px * p["shares"]
            cost = self._cost(val, p["seg"], "SELL", self.F.tv[t, self.F.col(tk)])
            S["cash"] += val - cost
            pnl = (px - p["entry_px"]) * p["shares"] - p["entry_cost"] - cost
            S["trades"].append({"ticker": tk, "book": p["book"], "entry_date": p["entry_date"],
                                "entry_px": p["entry_px"], "exit_date": self._date(t), "exit_px": round(px, 2),
                                "shares": p["shares"], "pnl": round(pnl, 2),
                                "pnl_pct": round(pnl / (p["entry_px"] * p["shares"]) * 100, 2),
                                "days": self.days_held(p, t), "reason_in": p["reason"], "reason_out": reason})
            S["positions"].pop(i)
            return

    # ------------------------------------------------------------ one full day (backtest)
    def step(self, t):
        if t > 0:
            self.fill_open(t)
        orders = self.decide_close(t)
        self.fill_close(t, orders)
        self.decide_after_close(t)
        return self.mark(t)


def preview_close(F, state, t):
    """For the pre-close run: what to do into today's close, without changing the saved book."""
    e = Engine(F, copy.deepcopy(state))
    if state.get("last_date") != str(F.index[t].date()):
        e.fill_open(t)
    return e.decide_close(t), e

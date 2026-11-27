"""Turn the book and today's decisions into dashboard files and an email."""
import json
import pathlib
import numpy as np
from . import config as C

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
BOOK_NAME = {"positional": "Positional (≈6 months)", "swing": "Swing (≈4 weeks)", "btst": "BTST (overnight)",
             "tom": "Month-end window (ETF)"}


def _approx_date(date_str, n):
    return str(np.busday_offset(np.datetime64(date_str), n, roll="forward"))


def build(F, S, t, run, close_orders=None, generated_at=""):
    asof = str(F.index[t].date())
    eq = S["cash"] + sum(p["shares"] * p.get("last_close", p["entry_px"]) for p in S["positions"])
    idx, avg = float(F.regime_idx[t]), float(F.regime_avg[t])
    status = [{
        "asof": asof, "run": run, "generated_at": generated_at,
        "regime": "Bull" if F.bull[t] else "Bear", "regime_gap_pct": round((idx / avg - 1) * 100, 2),
        "equity": round(eq, 2), "cash": round(S["cash"], 2), "invested": round(eq - S["cash"], 2),
        "positions": len(S["positions"]), "capital": C.CAPITAL,
        "return_pct": round((eq / C.CAPITAL - 1) * 100, 2),
        "closed_trades": len(S["trades"]),
    }]
    orders = []
    for o in (close_orders or []):
        px = o.get("px")
        if px is None:
            p = next((q for q in S["positions"] if q["ticker"] == o["ticker"]), None)
            px = p.get("last_close") if p else None
        risk = (px - o["stop"]) * o["shares"] if (o["action"] == "BUY" and o.get("stop") and px) else None
        orders.append({
            "id": f"close-{o['action']}-{o['ticker']}", "when": "Today, last 30 min" if run == "pre-close" else "Filled at today's close",
            "action": o["action"], "ticker": o["ticker"], "book": BOOK_NAME[o["book"]], "shares": int(o["shares"]),
            "ref_price": round(px, 2) if px else None, "limit": None,
            "stop": o.get("stop"), "value": round(px * o["shares"], 0) if px else None,
            "risk_rs": round(risk, 0) if risk else None,
            "exit_plan": _exit_plan(o["book"], asof) if o["action"] == "BUY" else "",
            "reason": o["reason"]})
    if run == "post-close":
        for o in S["pending_open"]:
            j = F.col(o["ticker"]); px = float(F.c[t, j])
            if o["action"] == "BUY":
                stop = px - o["stop_dist"]
                eqv = eq
                risk_amt = C.RISK[o["book"]] * eqv * (C.BEAR_RISK_MULT if o.get("bear") else 1)
                n = int(min(risk_amt / max(px - stop, px * C.MIN_STOP_PCT), C.MAX_WEIGHT * eqv / px, S["cash"] / px))
                orders.append({"id": f"open-BUY-{o['ticker']}", "when": "Next session, at the open", "action": "BUY",
                               "ticker": o["ticker"], "book": BOOK_NAME[o["book"]], "shares": n,
                               "ref_price": round(px, 2), "limit": o["limit"], "stop": round(stop, 2),
                               "value": round(px * n, 0), "risk_rs": round((px - stop) * n, 0),
                               "exit_plan": _exit_plan(o["book"], asof), "reason": o["reason"]})
            else:
                p = next((q for q in S["positions"] if q["ticker"] == o["ticker"]), {})
                orders.append({"id": f"open-SELL-{o['ticker']}", "when": "Next session, at the open", "action": "SELL",
                               "ticker": o["ticker"], "book": BOOK_NAME[o["book"]], "shares": int(p.get("shares", 0)),
                               "ref_price": round(px, 2), "limit": None, "stop": None, "value": round(px * p.get("shares", 0), 0),
                               "risk_rs": None, "exit_plan": "", "reason": o["reason"]})
    positions = []
    for p in S["positions"]:
        last = p.get("last_close", p["entry_px"])
        pnl = (last - p["entry_px"]) * p["shares"] - p.get("entry_cost", 0)
        positions.append({"ticker": p["ticker"], "book": BOOK_NAME[p["book"]], "entry_date": p["entry_date"],
                          "entry_px": p["entry_px"], "shares": p["shares"], "last": round(last, 2),
                          "value": round(last * p["shares"], 0), "pnl_rs": round(pnl, 0),
                          "pnl_pct": round((last / p["entry_px"] - 1) * 100, 2), "stop": p["stop"],
                          "days_held": p.get("days_held", 0),
                          "days_left": max(0, C.HOLD.get(p["book"], 5) - p.get("days_held", 0)),
                          "reason": p["reason"]})
    trades = [{**x, "book": BOOK_NAME[x["book"]], "id": f"{x['ticker']}-{x['entry_date']}"} for x in S["trades"]][::-1]
    equity = [{"date": d, "equity": v} for d, v in S["equity"]]
    return {"status": status, "orders": orders, "positions": positions, "trades": trades, "equity": equity}


def _exit_plan(book, asof):
    if book == "tom":
        return "Sell at the close of the 3rd trading day of next month"
    if book == "btst":
        return "Sell into tomorrow's close"
    n = C.HOLD[book]
    return f"Time stop around {_approx_date(asof, n)} ({n} sessions); exit earlier on an avoid signal or a close below the stop"


def write(files, meta):
    OUT.mkdir(exist_ok=True)
    for name, rows in files.items():
        (OUT / f"{name}.json").write_text(json.dumps({"rows": rows, "meta": meta}, default=float))


def email_text(rep):
    s = rep["status"][0]
    L = [f"9two3 Quant Desk — {s['run']} run, {s['asof']}",
         f"Regime: {s['regime']} (mid/small-cap index {s['regime_gap_pct']:+.1f}% vs 200-day avg)",
         f"Paper book: Rs {s['equity']:,.0f} ({s['return_pct']:+.2f}% since start), {s['positions']} positions, cash Rs {s['cash']:,.0f}", ""]
    if rep["orders"]:
        L.append("ACTIONS")
        for o in rep["orders"]:
            line = f"- {o['when']}: {o['action']} {o['shares']} {o['ticker']} [{o['book']}]"
            if o.get("ref_price"): line += f" ref Rs {o['ref_price']:,.2f}"
            if o.get("limit"): line += f", don't pay above Rs {o['limit']:,.2f}"
            if o.get("stop"): line += f", stop Rs {o['stop']:,.2f}"
            if o.get("risk_rs"): line += f", risk Rs {o['risk_rs']:,.0f}"
            L.append(line)
            L.append(f"    Why: {o['reason']}. {o['exit_plan']}".rstrip())
    else:
        L.append("No actions.")
    if rep["positions"]:
        L += ["", "OPEN POSITIONS"]
        for p in rep["positions"]:
            L.append(f"- {p['ticker']} [{p['book']}] {p['shares']} @ {p['entry_px']:,.2f} → {p['last']:,.2f} "
                     f"({p['pnl_pct']:+.1f}%), stop {p['stop']:,.2f}, {p['days_left']} sessions left")
    L += ["", "Model suggestions for your own decisions, not advice. You place every order yourself."]
    return "\n".join(L)

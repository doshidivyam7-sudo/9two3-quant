"""Daily runs.

python run_daily.py preclose    # ~14:35 IST: what to buy/sell into today's close
python run_daily.py postclose   # after 16:00 IST: fill today's paper trades, plan tomorrow's open

State lives in state/book.json (commit it after each run). Dashboard files and the
email go to out/.
"""
import argparse, datetime as dt, json, os, pathlib, sys
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from quant import config as C
from quant.data import load_universe, download, now_ist, session_fraction
from quant.features import Features
from quant.engine import Engine, new_state, preview_close
from quant import report

STATE = ROOT / "state" / "book.json"
PRECLOSE = ROOT / "state" / "preclose_orders.json"


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else new_state()


def save_state(S):
    STATE.parent.mkdir(exist_ok=True)
    S["skipped"] = S.get("skipped", [])[-200:]
    STATE.write_text(json.dumps(S, indent=1, default=float))


def get_data(partial_ok):
    tick, seg = load_universe()
    if C.TOM["enabled"]:
        tick = tick + [C.TOM["etf"]]
    if C.CORE["enabled"]:
        tick = tick + [C.CORE["etf"]]
    start = (now_ist().date() - dt.timedelta(days=800)).isoformat()
    import pickle
    cache = os.environ.get("QUANT_CACHE")
    if cache and pathlib.Path(cache).exists():
        P = pickle.loads(pathlib.Path(cache).read_bytes())
    else:
        P = download(tick, start)
        if cache:
            pathlib.Path(cache).write_bytes(pickle.dumps(P))
    asof = os.environ.get("QUANT_ASOF")      # testing: pretend today is this date (after close)
    if asof:
        P = {k: v.loc[:asof] for k, v in P.items()}
        return P, seg, False
    today = now_ist().date()
    last = P["c"].index[-1].date()
    is_partial = (last == today) and now_ist().time() < dt.time(15, 40)
    if is_partial and not partial_ok:
        P = {k: v.iloc[:-1] for k, v in P.items()}
        is_partial = False
    if is_partial:
        _, vf = session_fraction()
        P["v"] = P["v"].astype(float)
        P["v"].iloc[-1] = P["v"].iloc[-1] / vf      # project the full day's volume
    return P, seg, is_partial


def adjust_for_splits(F, S):
    """If a held stock split or issued bonus shares, Yahoo rescales history: follow it."""
    if not S.get("last_date"):
        return []
    t0 = F.pos_of.get(pd.Timestamp(S["last_date"])) if hasattr(F, "pos_of") else None
    idx = {d: i for i, d in enumerate(F.index)}
    t0 = idx.get(pd.Timestamp(S["last_date"]))
    notes = []
    if t0 is None:
        return notes
    for p in S["positions"]:
        new = F.c[t0, F.col(p["ticker"])]
        old = p.get("last_close")
        if not (np.isfinite(new) and old):
            continue
        r = new / old
        if abs(np.log(r)) > np.log(1.15):
            p["shares"] = int(round(p["shares"] / r))
            for k in ("entry_px", "stop", "last_close"):
                p[k] = round(p[k] * r, 2)
            notes.append(f"{p['ticker']}: adjusted for a split/bonus (factor {1 / r:.2f})")
    return notes


def meta(run):
    code = (ROOT / "quant" / "engine.py").read_text()
    return [{"label": "engine.py", "value": code, "type": "code", "lang": "python"},{"label": "Run", "value": run},
            {"label": "Generated", "value": now_ist().strftime("%Y-%m-%d %H:%M IST")},
            {"label": "Engine", "value": "run_daily.py + quant/engine.py (rules from the edge-decay study)"},
            {"label": "Prices", "value": "Yahoo Finance daily NSE data, adjusted; intraday values are partial-day"}]


def preclose():
    (ROOT / "out").mkdir(exist_ok=True); (ROOT / "out" / "SKIP").unlink(missing_ok=True)
    S = load_state()
    P, seg, partial = get_data(partial_ok=True)
    if not os.environ.get("QUANT_ASOF") and P["c"].index[-1].date() != now_ist().date():
        print("SKIP: no trading session today (holiday or weekend)")
        (ROOT / "out" / "SKIP").write_text("no session")
        return
    F = Features(P, seg)
    t = len(F.index) - 1
    orders, e = preview_close(F, S, t)
    asof = str(F.index[t].date())
    PRECLOSE.write_text(json.dumps({"date": asof, "partial": partial,
                                    "generated_at": now_ist().isoformat(timespec="minutes"), "orders": orders}, indent=1))
    for p in e.S["positions"]:  # refresh last prices on the preview copy, for the report only
        px = F.c[t, F.col(p["ticker"])]
        if np.isfinite(px):
            p["last_close"] = float(px)
    rep = report.build(F, e.S, t, "pre-close", orders, now_ist().strftime("%H:%M IST"))
    report.write(rep, meta("pre-close"))
    (ROOT / "out" / "email.txt").write_text(report.email_text(rep))
    print(report.email_text(rep))


def postclose():
    (ROOT / "out").mkdir(exist_ok=True); (ROOT / "out" / "SKIP").unlink(missing_ok=True)
    S = load_state()
    P, seg, _ = get_data(partial_ok=False)
    F = Features(P, seg)
    e = Engine(F, S)
    notes = adjust_for_splits(F, S)
    T = len(F.index) - 1
    if not S.get("last_date"):
        todo = [T]                     # first run: start the book today, no fills
        first = True
    else:
        last = pd.Timestamp(S["last_date"])
        todo = [i for i, d in enumerate(F.index) if d > last]
        first = False
        if not todo:
            print("SKIP: no new session since the last run")
            (ROOT / "out" / "SKIP").write_text("no new session")
            return
    pre = json.loads(PRECLOSE.read_text()) if PRECLOSE.exists() else {}
    filled_close = []
    for t in todo:
        d = str(F.index[t].date())
        if not first:
            e.fill_open(t)
        if pre.get("date") == d:
            orders = pre["orders"]
        elif first:
            orders = []
        else:
            orders = e.decide_close(t)       # pre-close run missed: decide on final data
            notes.append(f"{d}: no pre-close run found, close orders decided on final prices")
        if first:
            orders = [o for o in orders if o["action"] == "SELL"]
        e.fill_close(t, orders)
        filled_close = orders
        e.decide_after_close(t)
        e.mark(t)
    save_state(e.S)
    rep = report.build(F, e.S, T, "post-close", filled_close, now_ist().strftime("%H:%M IST"))
    notes = notes[-3:]
    rep["status"][0]["notes"] = "; ".join(notes)
    report.write(rep, meta("post-close"))
    txt = report.email_text(rep) + ("\n\nNotes: " + "; ".join(notes) if notes else "")
    (ROOT / "out" / "email.txt").write_text(txt)
    print(txt)


def morning():
    """~09:27 IST: act on last night's open orders, flag holdings, and build today's watchlist."""
    (ROOT / "out").mkdir(exist_ok=True); (ROOT / "out" / "SKIP").unlink(missing_ok=True)
    S = load_state()
    P, seg, partial = get_data(partial_ok=True)
    if not os.environ.get("QUANT_ASOF") and P["c"].index[-1].date() != now_ist().date():
        print("SKIP: no trading session today (holiday or weekend)")
        (ROOT / "out" / "SKIP").write_text("no session")
        return
    F = Features(P, seg)
    t = len(F.index) - 1
    e = Engine(F, S)
    def px(arr, tk):
        v = arr[t, F.col(tk)]
        return float(v) if np.isfinite(v) else None
    act, warn, watch = [], [], []
    for o in S.get("pending_open", []):
        tk = o["ticker"]; op, last = px(F.o, tk), px(F.c, tk)
        if o["action"] == "BUY":
            if op is None:
                continue
            if op <= o["limit"] and (last or op) <= o["limit"]:
                stop = (last or op) - o["stop_dist"]
                act.append(f"BUY {tk} [{o['book']}] now, limit Rs {o['limit']:,.2f} (opened {op:,.2f}, now {last:,.2f}); "
                           f"stop on a close below Rs {stop:,.2f}. Why: {o['reason']}")
            else:
                act.append(f"SKIP {tk}: opened/trading above the max price Rs {o['limit']:,.2f} (open {op:,.2f}). Don't chase.")
        else:
            act.append(f"SELL {tk} now (at/near the open). Why: {o['reason']}")
    for p in S["positions"]:
        tk = p["ticker"]; g = F.gapr[t, F.col(tk)]; last = px(F.c, tk)
        if np.isfinite(g) and g <= -0.05:
            warn.append(f"{tk}: opened {g*100:.1f}% lower (large gap-down). The model will exit at tomorrow's open unless it recovers; no action needed now.")
        if last and last < p["stop"]:
            warn.append(f"{tk}: trading below its stop Rs {p['stop']:,.2f}. If it CLOSES below, sell at tomorrow's open.")
    # watchlist for the close: big gap-ups on early volume, and top-ranked stocks near a 52-week high
    _, vf = session_fraction()
    for j in np.where((F.gapr[t] >= 0.04) & F.elig[t])[0]:
        tk = F.cols[j]
        if tk in e.held() or tk == C.TOM["etf"]:
            continue
        watch.append(f"{tk}: gapped up {F.gapr[t, j]*100:.1f}%, now {(F.c[t, j]/F.o[t, j]-1)*100:+.1f}% vs open. "
                     f"BTST candidate if it holds above the open with 2.5x volume by 2:35 PM.")
    hi = pd.DataFrame(F.c).rolling(252, min_periods=200).max().shift(1).values[t]
    near = [(F.comp[t, j], j) for j in range(len(F.cols))
            if F.elig[t, j] and np.isfinite(F.comp[t, j]) and F.comp[t, j] >= 0.8 and np.isfinite(hi[j])
            and F.c[t, j] >= 0.98 * hi[j] and F.cols[j] not in e.held()
            and F.cols[j] not in {o["ticker"] for o in S.get("pending_open", [])}]
    for sc, j in sorted(near, reverse=True)[:8]:
        watch.append(f"{F.cols[j]}: top {100 - sc*100:.0f}% momentum, {(F.c[t, j]/hi[j]-1)*100:+.1f}% vs its 52-week high. "
                     f"Swing candidate if it closes at a fresh high on volume.")
    k, left = e.month_pos(t)
    tom = ""
    if C.TOM["enabled"]:
        if left == C.TOM["enter_days_left"]:
            tom = f"Month-end window: entry day. If the regime is Bull at 2:35 PM, the model buys {C.TOM['etf']} into today's close."
        elif any(p["book"] == "tom" for p in S["positions"]) and k >= C.TOM["exit_day"]:
            tom = f"Month-end window: exit day. Sell {C.TOM['etf']} into today's close."
    regime = "Bull" if F.bull[t] else "Bear"
    L = [f"9two3 Quant Desk — morning brief, {F.index[t].date()} ({now_ist().strftime('%H:%M')} IST)",
         f"Regime: {regime} (mid/small-cap index {(F.regime_idx[t]/F.regime_avg[t]-1)*100:+.1f}% vs 200-day avg)", ""]
    L += ["DO NOW"] + ([f"- {x}" for x in act] if act else ["- Nothing to do at the open."])
    if warn:
        L += ["", "HOLDINGS TO WATCH"] + [f"- {x}" for x in warn]
    if tom:
        L += ["", tom]
    L += ["", "WATCHLIST FOR THE 3 PM WINDOW (not buys yet; the 2:35 PM email confirms)"] + \
         ([f"- {x}" for x in watch] if watch else ["- Nothing notable at the open."])
    L += ["", "No intraday trades: none tested beat costs. Model suggestions for your own decisions, not advice."]
    txt = "\n".join(L)
    (ROOT / "out" / "morning.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=["preclose", "postclose", "morning"])
    a = ap.parse_args()
    {"preclose": preclose, "postclose": postclose, "morning": morning}[a.run]()

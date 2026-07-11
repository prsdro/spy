"""
Round 3: trend-following variants of the ES EMA/PO pullback strategy.

Same arm signal (dual-TF bullish EMA stack + 3m PO compression -> bullish
expansion). Sweeps:
  entry : pullback (limit at 3m EMA9)  |  market (buy first in-window minute
          while armed — no pullback wait)
  window: both (09:30-12:00 + 15:00-15:45 ET) | am (09:30-12:00) | fh (09:30-10:30)
  exit  : s5/t8 reference; stop-only ride-to-close s5/s8/s10; wide trails
          a6d6 s5, a8d8 s8; breakeven at +6 then hold to close (s5)

Anti-mining: stats reported full-period AND split — train 2008-2019,
test 2020-2026. A candidate must be positive in BOTH halves.
Matched random-entry baselines computed for any candidate cell.

Output: analyst/es_ema_po_pullback_round3.csv
"""

import os
import numpy as np
import pandas as pd

from backtest_es_ema_po_pullback_round2 import prep, COST_ES, PT_VALUE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_round3.csv")

IDLE, WATCH, ARMED = 0, 1, 2

WINDOWS = {
    "both": [(570, 720), (900, 945)],
    "am":   [(570, 720)],
    "fh":   [(570, 630)],
}

EXITS = {
    "s5/t8":        dict(stop=5,  tgt=8,    mgmt="fixed"),
    "s5/eod":       dict(stop=5,  tgt=None, mgmt="fixed"),
    "s8/eod":       dict(stop=8,  tgt=None, mgmt="fixed"),
    "s10/eod":      dict(stop=10, tgt=None, mgmt="fixed"),
    "trail a6d6 s5": dict(stop=5, tgt=None, mgmt="trail", trail_arm=6, trail_dist=6),
    "trail a8d8 s8": dict(stop=8, tgt=None, mgmt="trail", trail_arm=8, trail_dist=8),
    "be6 s5/eod":   dict(stop=5,  tgt=None, mgmt="be", be_arm=6),
}


def win_mask(A, wname):
    ts = pd.to_datetime(A["ts"])
    mod = ts.hour * 60 + ts.minute
    m = np.zeros(A["n"], dtype=bool)
    for lo, hi in WINDOWS[wname]:
        m |= (mod >= lo) & (mod < hi)
    return m.values if hasattr(m, "values") else m


def simulate(A, in_win, entry_mode, stop=5, tgt=None, mgmt="fixed",
             be_arm=None, trail_arm=None, trail_dist=None):
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    comp, cond, rising = A["comp"], A["cond"], A["rising"]
    e9_3, e21_3, c3 = A["e9_3"], A["e21_3"], A["c3"]
    n = A["n"]

    state, seen3, in_pos = IDLE, -1, False
    entry_px = stp = hi = 0.0
    tgt_px = None
    entry_ts = None
    trades = []

    for i in range(n):
        j = idx3[i]

        if in_pos:
            exit_px = None; reason = None
            if last_of_day[i]:
                exit_px, reason = o1[i], "eod"
            elif l1[i] <= stp:
                exit_px, reason = min(o1[i], stp), "stop"
            elif tgt_px is not None and h1[i] >= tgt_px:
                exit_px, reason = max(o1[i], tgt_px), "target"
            if exit_px is None and mgmt in ("be", "trail"):
                hi = max(hi, h1[i])
                if mgmt == "be" and hi >= entry_px + be_arm:
                    stp = max(stp, entry_px)
                elif mgmt == "trail" and hi >= entry_px + trail_arm:
                    stp = max(stp, entry_px, hi - trail_dist)
            if exit_px is not None:
                trades.append((entry_ts, ts1[i], exit_px - entry_px - COST_ES, reason))
                in_pos = False
            if in_pos:
                continue

        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if comp[k] == 1:
                    state = WATCH
                elif state == WATCH:
                    state = ARMED if (rising[k] and cond[k]) else IDLE
                elif state == ARMED:
                    if (not cond[k]) or (c3[k] < e21_3[k]):
                        state = IDLE
            seen3 = j

        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            fill = None
            if entry_mode == "market":
                fill = o1[i]
            else:
                zone_top = e9_3[j]; zone_bot = e21_3[j]
                if zone_top > zone_bot and l1[i] <= zone_top:
                    fill = min(o1[i], zone_top)
            if fill is not None:
                in_pos = True
                entry_px = fill
                stp = fill - stop
                tgt_px = (fill + tgt) if tgt is not None else None
                hi = fill
                entry_ts = ts1[i]
                state = IDLE

    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])


def baseline(A, in_win, stride=10, stop=5, tgt=None, mgmt="fixed",
             be_arm=None, trail_arm=None, trail_dist=None):
    """Unconditional long at every stride-th eligible minute, same exit."""
    o1, h1, l1 = A["o"], A["h"], A["l"]
    last_of_day = A["last_of_day"]
    n = A["n"]
    pnls = []
    i = 0
    while i < n:
        if in_win[i] and not last_of_day[i]:
            fill = o1[i]
            stp = fill - stop
            tgt_px = (fill + tgt) if tgt is not None else None
            hi = fill
            k = i
            while k < n:
                if last_of_day[k]:
                    pnls.append(o1[k] - fill - COST_ES); break
                if l1[k] <= stp:
                    pnls.append(min(o1[k], stp) - fill - COST_ES); break
                if tgt_px is not None and h1[k] >= tgt_px:
                    pnls.append(max(o1[k], tgt_px) - fill - COST_ES); break
                if mgmt in ("be", "trail"):
                    hi = max(hi, h1[k])
                    if mgmt == "be" and hi >= fill + be_arm:
                        stp = max(stp, fill)
                    elif mgmt == "trail" and hi >= fill + trail_arm:
                        stp = max(stp, fill, hi - trail_dist)
                k += 1
            i += stride
        else:
            i += 1
    return np.array(pnls)


def stats(t, label):
    if len(t) == 0:
        return {"config": label, "n": 0}
    t = t.copy()
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["year"] = t["entry_ts"].dt.year
    pnl = t["pnl_pts"]
    daily = t.groupby(t["entry_ts"].dt.date)["pnl_pts"].sum()
    tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl <= 0].sum()
    eq = pnl.cumsum() * PT_VALUE
    dd = (eq - eq.cummax()).min()
    tr = t[t["year"] <= 2019]; te = t[t["year"] >= 2020]
    dte = te.groupby(te["entry_ts"].dt.date)["pnl_pts"].sum() if len(te) else pd.Series(dtype=float)
    t_te = dte.mean() / (dte.std(ddof=1) / np.sqrt(len(dte))) if len(dte) > 1 else np.nan
    return {
        "config": label, "n": len(t),
        "win_pct": round((pnl > 0).mean() * 100, 1),
        "avg_pts": round(pnl.mean(), 3),
        "tot_pts": round(pnl.sum(), 1),
        "pf": round(wins / losses, 3) if losses > 0 else np.inf,
        "t_day": round(tday, 2),
        "max_dd_usd": round(dd, 0),
        "avg_0819": round(tr["pnl_pts"].mean(), 3) if len(tr) else np.nan,
        "avg_2026": round(te["pnl_pts"].mean(), 3) if len(te) else np.nan,
        "t_day_2026": round(t_te, 2),
    }


def main():
    A = prep()
    masks = {w: win_mask(A, w) for w in WINDOWS}
    rows = []
    for entry_mode in ["pullback", "market"]:
        for wname, m in masks.items():
            for ename, kw in EXITS.items():
                t = simulate(A, m, entry_mode, **kw)
                label = f"{entry_mode}|{wname}|{ename}"
                r = stats(t, label)
                r["entry"], r["window"], r["exit"] = entry_mode, wname, ename
                rows.append(r)
                print(f"  {label}: n={r.get('n',0)} avg={r.get('avg_pts')} "
                      f"pf={r.get('pf')} t_day={r.get('t_day')} "
                      f"train={r.get('avg_0819')} test={r.get('avg_2026')}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)

    cand = out[(out["avg_pts"] > 0) & (out["avg_0819"] > 0) & (out["avg_2026"] > 0)]
    print(f"\ncandidates positive full + both halves: {len(cand)}")
    for _, r in cand.iterrows():
        print(f"  {r['config']}: avg {r['avg_pts']} pf {r['pf']} t_day {r['t_day']}")
        kw = EXITS[r["exit"]]
        b = baseline(A, masks[r["window"]],
                     stop=kw["stop"], tgt=kw["tgt"], mgmt=kw["mgmt"],
                     be_arm=kw.get("be_arm"), trail_arm=kw.get("trail_arm"),
                     trail_dist=kw.get("trail_dist"))
        print(f"    matched baseline: n={len(b)} avg {b.mean():+.3f} pts")

    print(f"\nwritten to {OUT_CSV}")


if __name__ == "__main__":
    main()

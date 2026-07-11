"""
Round 6 (user question, 2026-07-10): does gating the ribbon-riding candidate
on the HOURLY Phase Oscillator help?

Gates tested on the frozen candidate (arm | both windows | exit 2 closes below
10m EMA21 | 2.5xATR stop | 3m ATR>=2), entry allowed only when the last
completed RTH 1h bar satisfies:
  po>50+exp : 1h PO > 50 and 1h in expansion (compression flag off, osc rising)
  po<50+exp : 1h PO < 50 and in expansion
  po>50     : 1h PO > 50
  po<50     : 1h PO < 50
  exp       : 1h expansion only
  none      : (reference — the round-5b candidate)

HONESTY NOTE: every dataset is already burned (ES=search, NQ=holdout,
SPY/QQQ/IWM=replication). Results are descriptive in-sample observations,
not validation. ES full history + halves reported; NQ holdout period
re-scored descriptively.
"""

import numpy as np
import pandas as pd

import backtest_es_ema_po_pullback_round5b as r5b
from backtest_es_ema_po_pullback_round5 import prep5, win_arr, stats5
from backtest_es_ema_po_pullback_round2 import compute_phase_oscillator, build_tf

IDLE, WATCH, ARMED = 0, 1, 2


def hourly_gates(data_path, A):
    """1h RTH PO features mapped to each 3m bar (last completed 1h bar)."""
    df = pd.read_csv(data_path, header=None,
                     names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"]).set_index("ts").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df[(df["h"] - df["l"]) / df["c"] <= 0.03]
    h1 = compute_phase_oscillator(build_tf(df, "60min"))
    h1 = h1.reset_index().rename(columns={"ts": "start"})
    h1["end"] = h1["start"] + pd.Timedelta(minutes=60)
    h1["osc_rising"] = h1["phase_oscillator"].diff() > 0
    # map to 3m bars: last completed 1h bar at each 3m END
    ends3 = pd.DataFrame({"end": A["end3"]}) if "end3" in A else None
    # A doesn't carry end3; rebuild from 3m grid: idx3 maps 1m->3m; reconstruct 3m ends
    # simplest: recompute 3m ends from the same file
    t3 = build_tf(df, "3min").reset_index().rename(columns={"ts": "start"})
    t3["end"] = t3["start"] + pd.Timedelta(minutes=3)
    m = pd.merge_asof(t3[["end"]].sort_values("end"),
                      h1[["end", "phase_oscillator", "po_compression",
                          "osc_rising"]].sort_values("end"),
                      on="end", direction="backward")
    po = m["phase_oscillator"].fillna(0).values.astype(float)
    comp = m["po_compression"].fillna(1).values.astype(int)
    rising = m["osc_rising"].fillna(False).values.astype(bool)
    exp = (comp == 0) & rising
    return {
        "po>50+exp": (po > 50) & exp,
        "po<50+exp": (po < 50) & exp,
        "po>50": po > 50,
        "po<50": po < 50,
        "exp": exp,
        "none": np.ones(len(po), dtype=bool),
    }


def simulate_gated(A, in_win, gate):
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    comp, cond, trig = A["comp"], A["cond_bull"], A["osc_rising"]
    c3, atr3, e21_3, eref = A["c3"], A["atr3"], A["e21_3"], A["e21_10"]
    n = A["n"]
    state, seen3, in_pos = IDLE, -1, False
    entry_px = stop_px = 0.0
    below_ct = 0
    ribbon_exit = False
    entry_ts = None
    trades = []
    for i in range(n):
        j = idx3[i]
        if in_pos:
            exit_px = None; reason = None
            if last_of_day[i]:
                exit_px, reason = o1[i], "eod"
            elif ribbon_exit:
                exit_px, reason = o1[i], "ribbon"
            elif l1[i] <= stop_px:
                exit_px, reason = min(o1[i], stop_px), "stop"
            if exit_px is not None:
                trades.append((entry_ts, ts1[i], exit_px - entry_px - r5b.COST, reason))
                in_pos = False; ribbon_exit = False
        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if in_pos:
                    below_ct = below_ct + 1 if c3[k] < eref[k] else 0
                    if below_ct >= 2:
                        ribbon_exit = True
                if comp[k] == 1:
                    state = WATCH
                elif state == WATCH:
                    state = ARMED if (trig[k] and cond[k]) else IDLE
                elif state == ARMED:
                    if (not cond[k]) or (c3[k] < e21_3[k]):
                        state = IDLE
            seen3 = j
        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            if atr3[j] >= r5b.ATR_MIN and gate[j]:
                entry_px = o1[i]
                stop_px = entry_px - 2.5 * atr3[j]
                entry_ts = ts1[i]
                in_pos = True
                below_ct = 0
                ribbon_exit = False
                state = IDLE
    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])


def run(path, label, cost, atr_min):
    r5b.COST = cost
    r5b.ATR_MIN = atr_min
    A = prep5(path)
    gates = hourly_gates(path, A)
    m = win_arr(A, "both")
    print(f"\n===== {label} =====")
    for gname, g in gates.items():
        t = simulate_gated(A, m, g)
        r = stats5(t, gname)
        print(f"  {gname:10s}: n={r.get('n',0):5d} avg={r.get('avg_pts')} "
              f"pf={r.get('pf')} t={r.get('t_day')} "
              f"tr={r.get('avg_0819')} te={r.get('avg_2026')} "
              f"posyr={r.get('pos_years_pct')}", flush=True)


if __name__ == "__main__":
    run("/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt",
        "ES (search data — descriptive)", 0.31, 2.0)
    run("/srv/ftp/ossicones/futures-data/NQ_full_1min_continuous_ratio_adjusted.txt",
        "NQ (burned holdout — descriptive)", 0.405, 2.6)

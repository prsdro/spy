"""
CBC scalp round 5: does 5-minute CBC beat the 10-minute finalists?

Same machinery as round 4 (long-only CBC confirm + ribbon on the signal TF,
1-min execution, morning-only, conservative fills, 0.31 pts RT cost), but the
signal/management timeframe is 5m. Grid over the neighborhood that won on 10m,
2021-01-01 -> 2026-01-23, then 2008-2020 pseudo-OOS on the best cells, with
the two 10m finalists rerun as the head-to-head benchmark.
"""

import numpy as np
import pandas as pd

import backtest_es_cbc_scalp_round4 as r4
from backtest_es_cbc_scalp import load_minute, COST_PTS
from backtest_es_cbc_scalp_round3 import build_arrays

PT = 50.0
# Absolute take-profit cap in ES points (exit as soon as entry+cap trades);
# forwarded to the round-4 simulator. None = uncapped.
TAKE_PROFIT_PTS = None

ENTRIES = ["ema9_touch", "ema13_touch", "limit_2pt", "limit_0.30atr"]
STOPS = ["candle_low", "atr_1.0", "atr_1.5"]
EXITS = ["trail_1r", "trail_1.5r", "trail_2r", "be_1r_closeagainst"]
TODS = [("0930-1030", 570, 630), ("0930-1100", 570, 660)]


def stats(trades, y0, y1):
    a = np.array(trades)
    a = a[(a[:, 0] >= y0) & (a[:, 0] <= y1)]
    if len(a) < 60:
        return None
    net = a[:, 2] - COST_PTS
    r = net / a[:, 3]
    yrs = a[:, 0].astype(int)
    yv = np.array([r[yrs == y].sum() for y in np.unique(yrs)])
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    ny = (y1 - y0 + 0.05) if y1 == 2026 else (y1 - y0 + 1)
    return dict(n=len(a), avg_r=round(float(r.mean()), 4),
                tot_r=round(float(r.sum()), 1), t=round(float(t), 2),
                win=round(100 * float((net > 0).mean()), 1),
                risk=round(float(a[:, 3].mean()), 1),
                posyrs=f"{(yv > 0).sum()}/{len(yv)}",
                usd_yr=int(net.sum() * PT / ny))


def main():
    print("loading...")
    df1m = load_minute()
    arr5 = build_arrays(df1m, "long", "5min", 5)
    arr10 = build_arrays(df1m, "long", "10min", 10)
    r4.START_YEAR = 2008   # simulate everything, slice eras in stats()
    r4.TAKE_PROFIT_PTS = TAKE_PROFIT_PTS

    print("\n=== 5m grid, IS = 2021-2026, sorted by avg net R ===")
    results = []
    for entry in ENTRIES:
        for stop in STOPS:
            for exit_mode in EXITS:
                for lbl, lo, hi in TODS:
                    tr, ns = r4.simulate4(arr5, entry, stop, exit_mode,
                                          window_min=40, tod_lo=lo, tod_hi=hi)
                    s = stats(tr, 2021, 2026)
                    if s:
                        results.append((s["avg_r"], entry, stop, exit_mode,
                                        lbl, tr, s))
        print(f"done {entry}")
    results.sort(key=lambda x: -x[0])
    for avg, e, st, x, tod, _tr, s in results[:15]:
        print(f"5m {e:13s} {st:10s} {x:18s} {tod}  "
              + " ".join(f"{k}={v}" for k, v in s.items()))

    print("\n=== 2008-2020 pseudo-OOS on top-5 5m cells ===")
    for avg, e, st, x, tod, tr, _s in results[:5]:
        so = stats(tr, 2008, 2020)
        print(f"5m {e:13s} {st:10s} {x:18s} {tod}  OOS: "
              + (" ".join(f"{k}={v}" for k, v in so.items()) if so else "n<60"))

    print("\n=== 10m finalists on identical eras (benchmark) ===")
    for e, st, x, w, lbl, lo, hi in [
            ("ema9_touch", "atr_1.0", "trail_1.5r", 20, "0930-1030", 570, 630),
            ("limit_2pt", "candle_low", "be_1r_closeagainst", 40, "0930-1030",
             570, 630)]:
        tr, ns = r4.simulate4(arr10, e, st, x, window_min=w,
                              tod_lo=lo, tod_hi=hi)
        for y0, y1, tag in [(2021, 2026, "IS "), (2008, 2020, "OOS")]:
            s = stats(tr, y0, y1)
            print(f"10m {e:12s} {st:10s} {x:18s} {lbl} {tag}: "
                  + " ".join(f"{k}={v}" for k, v in s.items()))


if __name__ == "__main__":
    main()

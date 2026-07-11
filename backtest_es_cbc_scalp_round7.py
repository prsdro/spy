"""
CBC scalp round 7: re-entry after stop-out.

Spec under test: 10m long CBC confirm + ribbon, EMA9 pullback fill (20-min
order), 1.0xATR stop, hold to EOD (flat at close, no overnight). If the trade
stops out intraday, resume scanning for a fresh signal (new confirm close +
ribbon + pullback fill) and take up to max_per_day entries.

Grid: max_per_day 1/2/3/unlimited x signal windows 09:30-12:00 and all-day,
hold-EOD and trail@3R exits, eras IS 2021-2026 vs OOS 2008-2020.
Also isolates the re-entry trades (2nd+ of the day) to see if they carry edge.
Costs 0.31 pts RT per trade, conservative fills as before.
"""

import numpy as np

from backtest_es_cbc_scalp import load_minute, TICK, COST_PTS
from backtest_es_cbc_scalp_round3 import build_arrays
from backtest_es_cbc_scalp_round4 import try_fill4, bar_of_minute

PT = 50.0


def simulate_reentry(arr, tod_lo, tod_hi, max_per_day, exit_mode="hold_eod",
                     stop_mult=1.0, window=20):
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    e8, e21, atr = arr["e8"], arr["e21_10"], arr["atr"]
    day, bl, pid = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]
    l1, ends = arr["l1"], arr["ends"]

    trades = []   # (year, pnl, risk, entry_seq)
    busy_until = -1
    cur_day = -1
    entries_today = 0

    for i in range(n):
        if day[i] != cur_day:
            cur_day = day[i]
            entries_today = 0
        if i <= busy_until:
            continue
        if pid[i] < 1 or bl[i] <= 3:
            continue
        if entries_today >= max_per_day:
            continue
        if not (tod_lo <= mod[i] < tod_hi):
            continue
        if not (c10[i] > h10[i - 1] and e8[i] > e21[i]):
            continue
        res = try_fill4(arr, i, "ema9_touch", c10[i], l10[i], atr[i], window)
        if res is None:
            continue
        entry_px, fill_k = res
        entry_bar = bar_of_minute(arr, fill_k, i)
        if day[entry_bar] != day[i]:
            continue
        stop = entry_px - stop_mult * atr[i]
        risk = entry_px - stop
        if risk < TICK:
            continue
        entries_today += 1

        pnl = None
        exit_bar = entry_bar
        for k in range(fill_k, ends[entry_bar]):
            if l1[k] <= stop:
                pnl = stop - entry_px
                break
        if pnl is None:
            trail_on = False
            j = entry_bar
            if exit_mode == "trail_3r" and c10[j] >= entry_px + 3 * risk:
                trail_on = True
                if l10[j] > stop:
                    stop = l10[j]
            while True:
                if bl[j] == 1:
                    pnl = c10[j] - entry_px
                    exit_bar = j
                    break
                j += 1
                if l10[j] <= stop:
                    fill = stop if o10[j] > stop else o10[j]
                    pnl = fill - entry_px
                    exit_bar = j
                    break
                if exit_mode == "trail_3r":
                    if not trail_on and c10[j] >= entry_px + 3 * risk:
                        trail_on = True
                    if trail_on and l10[j] > stop:
                        stop = l10[j]
        trades.append((year[entry_bar], pnl, risk, entries_today))
        busy_until = exit_bar
    return trades


def era_stats(trades, y0, y1, ny, seq_min=1, seq_max=99):
    a = np.array([t for t in trades if seq_min <= t[3] <= seq_max])
    if len(a) == 0:
        return None
    m = (a[:, 0] >= y0) & (a[:, 0] <= y1)
    a = a[m]
    if len(a) < 30:
        return None
    net = a[:, 1] - COST_PTS
    r = net / a[:, 2]
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else np.nan
    return dict(n=len(a), wk=round(len(a) / (ny * 52), 1),
                avg_r=round(float(r.mean()), 4),
                t=round(float(t), 2),
                win=round(100 * float((net > 0).mean()), 1),
                usd_yr=int(net.sum() * PT / ny))


def main():
    print("loading...")
    df1m = load_minute()
    arr = build_arrays(df1m, "long", "10min", 10)

    for exit_mode in ("hold_eod", "trail_3r"):
        for lbl, lo, hi in [("0930-1200", 570, 720), ("all-day", 570, 930)]:
            print(f"\n=== exit={exit_mode}  window={lbl} ===")
            for mpd in (1, 2, 3, 99):
                tr = simulate_reentry(arr, lo, hi, mpd, exit_mode)
                line = f"  max/day={mpd:2d}: "
                for y0, y1, ny, tag in [(2021, 2026, 5.05, "IS"),
                                        (2008, 2020, 13, "OOS")]:
                    s = era_stats(tr, y0, y1, ny)
                    line += f"{tag} n={s['n']:5d}({s['wk']}/wk) avgR={s['avg_r']:+.4f} t={s['t']:+.2f} ${s['usd_yr']:+6d}/yr | "
                print(line)
            # re-entry trades only (2nd+), unlimited version
            tr = simulate_reentry(arr, lo, hi, 99, exit_mode)
            for y0, y1, ny, tag in [(2021, 2026, 5.05, "IS"),
                                    (2008, 2020, 13, "OOS")]:
                s = era_stats(tr, y0, y1, ny, seq_min=2)
                if s:
                    print(f"  re-entries only (2nd+/day) {tag}: n={s['n']} "
                          f"avgR={s['avg_r']:+.4f} t={s['t']:+.2f} "
                          f"win={s['win']}% ${s['usd_yr']:+d}/yr")


if __name__ == "__main__":
    main()

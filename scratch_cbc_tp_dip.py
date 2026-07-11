"""Quick check: final CBC spec + max take-profit cap + dip re-entry after TP.

Spec: 10m long confirm + ribbon, EMA9 pullback fill, 1.0xATR stop, hold EOD,
signals 09:30-12:00, max 2 signal entries/day. Adds: TP cap at entry+N pts;
after a TP exit, limit re-entry N pts below exit price (good till EOD, max
1/day, same stop/TP rules, fresh signal cancels pending dip).
Dip fills/exits are checked at 10m bar level (stop before TP, conservative).
"""

import numpy as np
from backtest_es_cbc_scalp import load_minute, TICK, COST_PTS
from backtest_es_cbc_scalp_round3 import build_arrays
from backtest_es_cbc_scalp_round4 import try_fill4, bar_of_minute

PT = 50.0


def sim(arr, tp_pts, dip_pts, tod_lo=570, tod_hi=720, max_sig=2, max_dip=1):
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    e8, e21, atr = arr["e8"], arr["e21_10"], arr["atr"]
    day, bl, pid = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]
    l1, h1, ends = arr["l1"], arr["h1"], arr["ends"]

    trades = []   # (year, pnl, risk, kind)  kind: 0 signal, 1 dip
    busy_until = -1
    cur_day = -1
    sig_today = dips_today = 0
    dip_level = None

    def manage(entry_bar, entry_px, stop, fill_k, kind):
        """Returns (pnl, exit_bar, tp_hit). 1m stop/TP scan for remainder of
        entry bar when fill_k given, else bar-level from entry_bar."""
        tp = entry_px + tp_pts if tp_pts else None
        if fill_k is not None:
            for k in range(fill_k, ends[entry_bar]):
                if l1[k] <= stop:
                    return stop - entry_px, entry_bar, False
                if tp is not None and h1[k] >= tp:
                    return tp - entry_px, entry_bar, True
        else:
            if l10[entry_bar] <= stop:
                return stop - entry_px, entry_bar, False
            if tp is not None and h10[entry_bar] >= tp:
                return tp - entry_px, entry_bar, True
        if bl[entry_bar] == 1:
            return c10[entry_bar] - entry_px, entry_bar, False
        j = entry_bar + 1
        while True:
            if l10[j] <= stop:
                fill = stop if o10[j] > stop else o10[j]
                return fill - entry_px, j, False
            if tp is not None and h10[j] >= tp:
                return tp - entry_px, j, True
            if bl[j] == 1:
                return c10[j] - entry_px, j, False
            j += 1

    for i in range(n):
        if day[i] != cur_day:
            cur_day = day[i]
            sig_today = dips_today = 0
            dip_level = None
        if i <= busy_until:
            continue

        # pending dip re-entry checked first each bar
        if dip_level is not None and dip_pts is not None:
            if l10[i] <= dip_level:
                entry_px = dip_level if o10[i] > dip_level else o10[i]
                stop = entry_px - 1.0 * atr[i]
                risk = entry_px - stop
                dip_level = None
                if risk >= TICK:
                    dips_today += 1
                    pnl, exit_bar, tp_hit = manage(i, entry_px, stop, None, 1)
                    trades.append((year[i], pnl, risk, 1))
                    busy_until = exit_bar
                    if tp_hit and dips_today < 1e9 and dips_today < max_dip \
                            and bl[exit_bar] > 1:
                        dip_level = (entry_px + tp_pts) - dip_pts \
                            if dips_today < max_dip else None
                    continue

        if pid[i] < 1 or bl[i] <= 3 or sig_today >= max_sig:
            continue
        if not (tod_lo <= mod[i] < tod_hi):
            continue
        if not (c10[i] > h10[i - 1] and e8[i] > e21[i]):
            continue
        dip_level = None            # fresh signal cancels pending dip
        res = try_fill4(arr, i, "ema9_touch", c10[i], l10[i], atr[i], 20)
        if res is None:
            continue
        entry_px, fill_k = res
        entry_bar = bar_of_minute(arr, fill_k, i)
        if day[entry_bar] != day[i]:
            continue
        stop = entry_px - 1.0 * atr[i]
        risk = entry_px - stop
        if risk < TICK:
            continue
        sig_today += 1
        pnl, exit_bar, tp_hit = manage(entry_bar, entry_px, stop, fill_k, 0)
        trades.append((year[entry_bar], pnl, risk, 0))
        busy_until = exit_bar
        if tp_hit and dip_pts is not None and dips_today < max_dip \
                and bl[exit_bar] > 1:
            dip_level = (entry_px + tp_pts) - dip_pts
    return trades


def report(trades, lbl):
    a = np.array(trades)
    out = f"{lbl:26s}"
    for y0, y1, ny, tag in [(2021, 2026, 5.05, "IS"), (2008, 2020, 13, "OOS")]:
        m = (a[:, 0] >= y0) & (a[:, 0] <= y1)
        net = a[m, 1] - COST_PTS
        r = net / a[m, 2]
        t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        out += (f" | {tag} n={m.sum():5d} avgR={r.mean():+.4f} "
                f"t={t:+.2f} ${int(net.sum() * PT / ny):+6d}/yr")
    ndip = int((a[:, 3] == 1).sum())
    print(out + f" | dip trades={ndip}")


def main():
    df1m = load_minute()
    arr = build_arrays(df1m, "long", "10min", 10)

    report(sim(arr, None, None), "no TP (validated spec)")
    for tp in (10.0, 15.0, 20.0):
        report(sim(arr, tp, None), f"TP {tp:.0f}pts, no dip")
    for dip in (3.0, 5.0, 8.0):
        report(sim(arr, 10.0, dip), f"TP 10pts + dip {dip:.0f}pts")
    report(sim(arr, 20.0, 5.0), "TP 20pts + dip 5pts")


if __name__ == "__main__":
    main()

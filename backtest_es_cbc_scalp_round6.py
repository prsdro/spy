"""
CBC scalp round 6: are we exiting winners too soon?

For the two 10m finalists (2021 -> 2026-01, 09:30-10:30 signals):
  A: ema9_touch entry, 1.0xATR stop      (robust finalist)
  C: limit_2pt entry, candle-low stop    (regime-aware option)

1) MFE audit: realized R vs max favorable excursion to EOD on 10m highs.
2) Single-unit longer holds: trail@1.5R (base) / @2R / @3R, BE@1R+hold-EOD,
   raw hold-EOD, BE@1R+close-against (C's base).
3) 10-MES scale-out schemes with per-contract friction:
   ES  = 0.31 pts RT/contract, MES = 0.45 pts RT/contract (3x commission per
   unit notional, same 1-tick slippage). Shared stop across remaining units,
   stop -> BE+1 tick after the first partial fills. Conservative same-bar
   ordering (stop before target). All schemes forced flat EOD.
"""

import numpy as np
import pandas as pd

from backtest_es_cbc_scalp import load_minute, TICK
from backtest_es_cbc_scalp_round3 import build_arrays

ES_COST = 0.31
MES_COST = 0.45
PT = 50.0            # $/pt for 1 ES = 10 MES
YEARS = 5.05
START_YEAR = 2021

FAMILIES = {
    "A(ema9/atr1.0)": dict(entry="ema9_touch", stop="atr_1.0", window=20),
    "C(limit2/clow)": dict(entry="limit_2pt", stop="candle_low", window=40),
}

# scheme -> (legs, be_at, cost)
# leg kinds: ('tgt', R) fixed target, ('trail', actR) trail 10m lows after
# a close >= entry+actR*risk, ('eod', None) hold to EOD, ('ca', None)
# close-against exit. be_at: move stop to BE+tick on a close >= entry+be_at*R
# (independent of partials); partials also move stop to BE when first fills.
SCHEMES = {
    "1ES aiao trail@1.5R":      ([(10, "trail", 1.5)], None, ES_COST),
    "1ES aiao trail@2R":        ([(10, "trail", 2.0)], None, ES_COST),
    "1ES aiao trail@3R":        ([(10, "trail", 3.0)], None, ES_COST),
    "1ES aiao BE@1R hold EOD":  ([(10, "eod", None)], 1.0, ES_COST),
    "1ES aiao hold EOD":        ([(10, "eod", None)], None, ES_COST),
    "1ES aiao BE@1R close-agnst": ([(10, "ca", None)], 1.0, ES_COST),
    "10MES aiao trail@1.5R":    ([(10, "trail", 1.5)], None, MES_COST),
    "10MES 5@1R + 5 trail@1.5R": ([(5, "tgt", 1.0), (5, "trail", 1.5)], None, MES_COST),
    "10MES 3@1R+3@2R+4 trail":  ([(3, "tgt", 1.0), (3, "tgt", 2.0),
                                  (4, "trail", 1.5)], None, MES_COST),
    "10MES 5@1.5R + 5 EOD(BE)": ([(5, "tgt", 1.5), (5, "eod", None)], None, MES_COST),
    "10MES 5@1R + 5 EOD(BE)":   ([(5, "tgt", 1.0), (5, "eod", None)], None, MES_COST),
    "10MES 5@2R + 5 EOD(BE)":   ([(5, "tgt", 2.0), (5, "eod", None)], None, MES_COST),
}


def collect_entries(arr, entry_mode, stop_mode, window, tod_lo=570, tod_hi=630):
    """Round-4 entry logic; busy handled by caller per scheme via day slices.
    One entry per signal; overlapping signals suppressed until prior trade's
    day-EOD (conservative, identical across schemes for comparability)."""
    from backtest_es_cbc_scalp_round4 import try_fill4, bar_of_minute
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    e8, e21, atr = arr["e8"], arr["e21_10"], arr["atr"]
    day, bars_left, pos_in_day = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]

    entries = []
    busy_until = -1
    for i in range(n):
        if year[i] < START_YEAR or i <= busy_until:
            continue
        if pos_in_day[i] < 1 or bars_left[i] <= 3:
            continue
        if not (tod_lo <= mod[i] < tod_hi):
            continue
        if not (c10[i] > h10[i - 1] and e8[i] > e21[i]):
            continue
        res = try_fill4(arr, i, entry_mode, c10[i], l10[i], atr[i], window)
        if res is None:
            continue
        entry_px, fill_k = res
        entry_bar = bar_of_minute(arr, fill_k, i)
        if day[entry_bar] != day[i]:
            continue
        if stop_mode == "candle_low":
            stop0 = l10[i] - TICK
        else:
            stop0 = entry_px - float(stop_mode.split("_")[1]) * atr[i]
        risk = entry_px - stop0
        if risk < TICK:
            continue
        # day end bar
        j = entry_bar
        while bars_left[j] > 1:
            j += 1
        entries.append(dict(sig_i=i, entry_bar=entry_bar, fill_k=fill_k,
                            px=entry_px, stop0=stop0, risk=risk,
                            year=year[entry_bar], day_end=j))
        busy_until = j    # same suppression for every scheme
    return entries


def manage(arr, e, legs, be_at, cost):
    """Return aggregate net pnl in (pts * units/10) for one entry."""
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    l1, ends = arr["l1"], arr["ends"]
    px, risk, stop = e["px"], e["risk"], e["stop0"]
    entry_bar, day_end = e["entry_bar"], e["day_end"]

    legs = [dict(u=u, kind=k, p=p, open=True) for u, k, p in legs]
    units_left = sum(lg["u"] for lg in legs)
    total = 0.0

    def close_units(n_units, price):
        nonlocal total, units_left
        total += n_units * (price - px - cost)
        units_left -= n_units

    # entry-bar remainder: stop only, on 1m lows (conservative: no targets)
    for k in range(e["fill_k"], ends[entry_bar]):
        if l1[k] <= stop:
            close_units(units_left, stop)
            return total / 10.0
    if entry_bar == day_end:
        close_units(units_left, c10[entry_bar])
        return total / 10.0

    trail_on = False
    first_partial_done = False
    be_done = False
    # trail state applies to whichever legs are 'trail'
    j = entry_bar + 1
    while units_left > 0:
        if l10[j] <= stop:
            fill = stop if o10[j] > stop else o10[j]
            close_units(units_left, fill)
            break
        # partial targets (stop had priority)
        for lg in legs:
            if lg["open"] and lg["kind"] == "tgt" \
                    and h10[j] >= px + lg["p"] * risk:
                close_units(lg["u"], px + lg["p"] * risk)
                lg["open"] = False
                if not first_partial_done:
                    first_partial_done = True
                    if px + TICK > stop:
                        stop = px + TICK
        if units_left == 0:
            break
        # close-against legs
        if c10[j] < l10[j - 1]:
            ca = [lg for lg in legs if lg["open"] and lg["kind"] == "ca"]
            for lg in ca:
                close_units(lg["u"], c10[j])
                lg["open"] = False
        if units_left == 0:
            break
        if j == day_end:
            close_units(units_left, c10[j])
            break
        # BE move / trail updates on completed bar
        if be_at is not None and not be_done and c10[j] >= px + be_at * risk:
            be_done = True
            if px + TICK > stop:
                stop = px + TICK
        acts = [lg["p"] for lg in legs if lg["open"] and lg["kind"] == "trail"]
        if acts:
            if not trail_on and c10[j] >= px + min(acts) * risk:
                trail_on = True
            if trail_on and l10[j] > stop:
                stop = l10[j]
        j += 1
    return total / 10.0


def mfe_audit(arr, entries, base_scheme, base_be, cost):
    h10, c10 = arr["h10"], arr["c10"]
    rows = []
    for e in entries:
        realized = manage(arr, e, base_scheme, base_be, cost) / e["risk"]
        mx = max(h10[e["entry_bar"]:e["day_end"] + 1])
        rows.append((realized,
                     (mx - e["px"]) / e["risk"],
                     (c10[e["day_end"]] - e["px"]) / e["risk"]))
    a = np.array(rows)
    real, mfe, eod = a[:, 0], a[:, 1], a[:, 2]
    print(f"  n={len(a)}  realized: mean {real.mean():+.3f}R median {np.median(real):+.3f}R")
    print(f"  MFE(to EOD, 10m highs): mean {mfe.mean():+.3f}R median {np.median(mfe):+.3f}R")
    print(f"  EOD close: mean {eod.mean():+.3f}R median {np.median(eod):+.3f}R")
    for thr in (1, 2, 3, 5):
        m = mfe >= thr
        print(f"  trades with MFE >= {thr}R: {100*m.mean():.1f}%"
              f" | their realized mean: {real[m].mean():+.2f}R"
              f" | left on table vs MFE: {(mfe[m]-real[m]).mean():.2f}R")
    print(f"  avg (EODclose - realized): {(eod-real).mean():+.3f}R"
          f"  -> holding to close would have {'ADDED' if (eod-real).mean()>0 else 'COST'}"
          f" {abs((eod-real).mean()):.3f}R/trade before extra costs")


def scheme_stats(arr, entries, legs, be_at, cost):
    pnls = np.array([manage(arr, e, legs, be_at, cost) for e in entries])
    years = np.array([e["year"] for e in entries])
    risks = np.array([e["risk"] for e in entries])
    r = pnls / risks
    yv = np.array([pnls[years == y].sum() for y in np.unique(years)])
    t = pnls.mean() / (pnls.std(ddof=1) / np.sqrt(len(pnls)))
    cum = np.cumsum(pnls * PT)
    dd = float((np.maximum.accumulate(cum) - cum).max())
    return dict(n=len(pnls),
                win=round(100 * float((pnls > 0).mean()), 1),
                avg_pts=round(float(pnls.mean()), 3),
                avg_r=round(float(r.mean()), 4),
                usd_yr=int(pnls.sum() * PT / YEARS),
                t=round(float(t), 2),
                maxdd_usd=int(dd),
                posyrs=f"{(yv > 0).sum()}/{len(yv)}")


def main():
    print("loading...")
    df1m = load_minute()
    arr = build_arrays(df1m, "long", "10min", 10)

    for fam, cfg in FAMILIES.items():
        entries = collect_entries(arr, cfg["entry"], cfg["stop"], cfg["window"])
        base = [(10, "trail", 1.5)] if fam.startswith("A") else [(10, "ca", None)]
        base_be = None if fam.startswith("A") else 1.0
        print(f"\n################ FAMILY {fam}: {len(entries)} entries 2021-2026 ################")
        print("--- MFE audit (base exit) ---")
        mfe_audit(arr, entries, base, base_be, ES_COST)
        print("\n--- exit schemes ---")
        for name, (legs, be_at, cost) in SCHEMES.items():
            s = scheme_stats(arr, entries, legs, be_at, cost)
            print(f"  {name:28s} " + " ".join(f"{k}={v}" for k, v in s.items()))


if __name__ == "__main__":
    main()

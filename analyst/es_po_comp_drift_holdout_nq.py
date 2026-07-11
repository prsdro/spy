"""Pre-registered NQ holdout for the 3m compression-drift strategy.
Specs and pass criteria frozen in es_po_comp_drift_holdout_prereg.md BEFORE
this script was first run. Reuses the exact ES pipeline functions.

Config A: flat_break/fix10      Config B: aligned_cont/brk10
Cost 0.405 NQ pts RT, ATR filter >= 2.6 NQ pts. Pass: avg net > 0 AND
day-clustered t >= 1.5.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
import backtest_es_po_comp_drift as base
from backtest_es_po_comp_drift import (find_periods, add_indicators,
                                       INIT_BARS, FLAT_THR, DRIFT_THR)
from backtest_es_po_comp_drift_strategy import simulate_exit

DATA = "/srv/ftp/ossicones/futures-data/NQ_full_1min_continuous_ratio_adjusted.txt"
COST_PTS = 0.405
ATR_MIN = 2.6
DOLLARS_PER_PT = 20.0


def load_3m_nq():
    df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index().between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    bad = rng_pct > 0.03
    if bad.any():
        print(f"dropping {bad.sum()} 1-min bars with range > 3% of price")
        df = df[~bad]
    o = df["o"].resample("3min", label="left", closed="left").first()
    h = df["h"].resample("3min", label="left", closed="left").max()
    l = df["l"].resample("3min", label="left", closed="left").min()
    c = df["c"].resample("3min", label="left", closed="left").last()
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()


def scan_episodes(tf):
    """Identical episode logic to backtest_es_po_comp_drift.main()."""
    events = []
    for date, g in tf.groupby("date"):
        if len(g) < base.MIN_COMP_BARS + 4:
            continue
        h = g["h"].values; l = g["l"].values
        o = g["o"].values; c = g["c"].values
        atr = g["atr14"].values; po = g["po"].values
        n = len(g)
        for start, end in find_periods(g["compression"].values):
            if end >= n:
                continue
            atr_e = atr[end]
            if not np.isfinite(atr_e) or atr_e <= 0:
                continue
            init_high = h[start:start + INIT_BARS].max()
            init_low = l[start:start + INIT_BARS].min()
            sub_h = h[start + INIT_BARS:end]
            sub_l = l[start + INIT_BARS:end]
            brk_up = max(0.0, sub_h.max() - init_high) / atr_e
            brk_dn = max(0.0, init_low - sub_l.min()) / atr_e
            if brk_up < FLAT_THR and brk_dn < FLAT_THR:
                cls = "flat"
            elif brk_up >= DRIFT_THR and brk_dn < FLAT_THR:
                cls = "drift_up"
            elif brk_dn >= DRIFT_THR and brk_up < FLAT_THR:
                cls = "drift_dn"
            else:
                cls = "mixed"
            last5_mid = (h[end - 5:end].max() + l[end - 5:end].min()) / 2.0
            exp_c = c[end]
            if exp_c > last5_mid:
                sign = 1
            elif exp_c < last5_mid:
                sign = -1
            else:
                sign = 1 if po[end] > 0 else -1
            drift_dir = 1 if cls == "drift_up" else (-1 if cls == "drift_dn" else 0)
            align = ("n/a" if drift_dir == 0
                     else ("aligned" if sign == drift_dir else "opposed"))
            events.append({"exp_ts": g.index[end], "date": date, "cls": cls,
                           "align": align, "sign": sign, "atr": atr_e})
    return pd.DataFrame(events)


def main():
    print("loading NQ 1m -> 3m RTH...")
    tf = load_3m_nq()
    tf = add_indicators(tf)
    tf["date"] = tf.index.date
    print(f"{len(tf)} 3m bars, {tf.index[0]} -> {tf.index[-1]}, "
          f"compression rate {tf['compression'].mean()*100:.1f}%")

    ev = scan_episodes(tf)
    print(f"{len(ev)} episodes; classes:\n{ev['cls'].value_counts().to_string()}")
    ev = ev[ev["atr"] >= ATR_MIN]
    print(f"after ATR>={ATR_MIN} filter: {len(ev)} episodes")

    o = tf["o"].values; h = tf["h"].values
    l = tf["l"].values; c = tf["c"].values
    dates = tf["date"].values
    pos = {ts: i for i, ts in enumerate(tf.index)}
    day_end = {}
    for d, gi in pd.Series(range(len(tf)), index=dates).groupby(level=0):
        day_end[d] = int(gi.iloc[-1])

    def run(name, sub, mode):
        rows = []
        for _, e in sub.iterrows():
            i = pos.get(e["exp_ts"])
            if i is None:
                continue
            dend = day_end[dates[i]]
            if i + 1 > dend:
                continue
            s = int(e["sign"])
            r = simulate_exit(o, h, l, c, i + 1, dend, s, e["atr"], mode)
            if r is None:
                continue
            gross = s * (r[0] - o[i + 1])
            rows.append({"day": str(e["date"]), "year": e["exp_ts"].year,
                         "side": s, "gross": gross,
                         "net": gross - COST_PTS,
                         "gross_atr": gross / e["atr"]})
        t = pd.DataFrame(rows)
        net = t["net"]
        daily = t.groupby("day")["net"].sum()
        tc = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
        half = len(t) // 2
        yr = t.groupby("year")["net"].sum()
        cum = net.cumsum()
        dd = float((cum.cummax() - cum).max())
        verdict = "PASS" if (net.mean() > 0 and tc >= 1.5) else "FAIL"
        print(f"\n=== {name} — {verdict} ===")
        print(f"  n={len(t)} ({len(t)/t['year'].nunique():.1f}/yr), "
              f"avg net {net.mean():+.3f} NQ pts (${net.mean()*DOLLARS_PER_PT:+.2f}), "
              f"day-clustered t={tc:+.2f}, win {(net>0).mean()*100:.0f}%")
        print(f"  gross in ATR units: {t['gross_atr'].mean():+.3f}")
        print(f"  1st half {net.iloc[:half].mean():+.3f} / "
              f"2nd half {net.iloc[half:].mean():+.3f} | "
              f"pos years {(yr>0).mean()*100:.0f}% of {len(yr)} | "
              f"total {net.sum():+.0f} pts | maxDD {dd:.0f} pts")
        for s, lbl in [(1, "LONG"), (-1, "SHORT")]:
            x = t[t["side"] == s]["net"]
            print(f"  {lbl:5s} n={len(x)}, avg net {x.mean():+.3f}, "
                  f"gross_atr {t[t['side']==s]['gross_atr'].mean():+.3f}")
        return t

    run("Config A: flat_break/fix10", ev[ev["cls"] == "flat"], "fix10")
    run("Config B: aligned_cont/brk10", ev[ev["align"] == "aligned"], "brk10")


if __name__ == "__main__":
    main()

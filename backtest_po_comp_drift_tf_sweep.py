"""Timeframe sweep (1m / 10m) of the compression-drift strategy on ES.

The 3m chart produced the validated Config B (aligned_cont/brk10, ATR>=2.0,
NQ holdout PASS t=2.85). This script runs the identical bar-count-based rules
on 1m and 10m ES to check whether 3m is the right timeframe:
  - episodes: >=8 compression bars, 1-bar gap tolerance, first-5-bar range,
    flat <0.25 ATR both sides, drift >=0.5/<0.25, direction = expansion close
    vs last-5-bar midpoint (all in bars of the target TF)
  - Config B: aligned expansion -> with drift, 1.0 ATR stop else EOD
  - Config A: flat -> expansion direction, exit close of 10th bar
  - cost 0.31 pts RT; ATR filter 2.0 pts (6.45x cost, same rule as 3m)
Also reports the unfiltered event-study diagnostics per TF (flat / aligned /
opposed signed ret_3 in ATR units) so the structure can be compared to 3m.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
sys.path.insert(0, "/root/spy/analyst")
import backtest_es_po_comp_drift as base
from backtest_es_po_comp_drift import add_indicators, DATA
from backtest_es_po_comp_drift_strategy import simulate_exit
from es_po_comp_drift_holdout_nq import scan_episodes

COST = 0.31
ATR_MIN = 2.0


def load_tf(rule):
    df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index().between_time("09:30", "15:59")
    df = df[(df["h"] - df["l"]) / df["c"] <= 0.03]
    o = df["o"].resample(rule, label="left", closed="left").first()
    h = df["h"].resample(rule, label="left", closed="left").max()
    l = df["l"].resample(rule, label="left", closed="left").min()
    c = df["c"].resample(rule, label="left", closed="left").last()
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()


def event_diagnostics(tf, ev):
    """Signed ret_3 (ATR units) by class, matching the 3m event study."""
    pos = {ts: i for i, ts in enumerate(tf.index)}
    c = tf["c"].values
    dates = tf["date"].values
    out = {}
    for lbl, mask in [("flat", ev["cls"] == "flat"),
                      ("aligned", ev["align"] == "aligned"),
                      ("opposed", ev["align"] == "opposed")]:
        vals = []
        for _, e in ev[mask].iterrows():
            i = pos.get(e["exp_ts"])
            if i is None or i + 3 >= len(c) or dates[i + 3] != dates[i]:
                continue
            vals.append(int(e["sign"]) * (c[i + 3] - c[i]) / e["atr"])
        v = pd.Series(vals)
        t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v))) if len(v) > 5 else np.nan
        out[lbl] = (len(v), v.mean(), t)
    return out


def run_tf(rule, name):
    print(f"\n{'='*90}\n  {name} ES\n{'='*90}")
    tf = load_tf(rule)
    tf = add_indicators(tf)
    tf["date"] = tf.index.date
    ev = scan_episodes(tf)
    print(f"  {len(tf)} bars, compression rate {tf['compression'].mean()*100:.1f}%, "
          f"{len(ev)} episodes ({ev['cls'].value_counts().to_dict()})")

    diag = event_diagnostics(tf, ev)
    for lbl, (n, m, t) in diag.items():
        print(f"  event ret_3 [{lbl:7s}]: {m:+.3f} ATR (t={t:+.1f}, n={n})")

    evf = ev[ev["atr"] >= ATR_MIN]
    print(f"  after ATR>={ATR_MIN}: {len(evf)} episodes")

    o = tf["o"].values; h = tf["h"].values
    l = tf["l"].values; c = tf["c"].values
    dates = tf["date"].values
    pos = {ts: i for i, ts in enumerate(tf.index)}
    day_end = {}
    for d, gi in pd.Series(range(len(tf)), index=dates).groupby(level=0):
        day_end[d] = int(gi.iloc[-1])

    for cfg, mask, mode in [("B aligned/brk10", evf["align"] == "aligned", "brk10"),
                            ("A flat/fix10", evf["cls"] == "flat", "fix10")]:
        rows = []
        for _, e in evf[mask].iterrows():
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
            rows.append({"day": str(e["date"]), "year": e["exp_ts"].year,
                         "net": s * (r[0] - o[i + 1]) - COST})
        t = pd.DataFrame(rows)
        if len(t) < 30:
            print(f"  {cfg}: n={len(t)} (too few)")
            continue
        daily = t.groupby("day")["net"].sum()
        tc = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
        half = len(t) // 2
        yr = t.groupby("year")["net"].sum()
        print(f"  {cfg}: n={len(t)} ({len(t)/t['year'].nunique():.0f}/yr) "
              f"avg net {t['net'].mean():+.3f} pts (${t['net'].mean()*50:+.2f}) "
              f"day-clust t={tc:+.2f} win {(t['net']>0).mean()*100:.0f}% "
              f"1st {t['net'].iloc[:half].mean():+.3f}/2nd {t['net'].iloc[half:].mean():+.3f} "
              f"posYrs {(yr>0).mean()*100:.0f}%")


if __name__ == "__main__":
    run_tf("1min", "1-MINUTE")
    run_tf("10min", "10-MINUTE")

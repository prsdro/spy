"""Forward test (2026-01-26 -> 2026-07-10) of the frozen compression-drift
specs on data that did not exist during discovery or the NQ holdout
(FirstRateData files end 2026-01-23; these bars come from the Massive/Polygon
futures API, fetched 2026-07-10).

Frozen specs (see analyst/es_po_comp_drift_holdout_prereg.md):
  Config B (primary, passed holdout): aligned_cont / brk10
  Config A (failed holdout, reported for reference): flat_break / fix10
  ES: cost 0.31 pts RT, ATR>=2.0.  NQ: cost 0.405 pts RT, ATR>=2.6.

Method: per-contract 3m RTH bars with indicators computed on each contract's
own series (no roll splicing); signals taken only on days the contract is
front month (highest daily RTH volume among its root's contracts) and after
2026-01-23. 14 days of pre-front bars retained for indicator warmup.
"""
import os, sys, glob
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
sys.path.insert(0, "/root/spy/analyst")
from backtest_es_po_comp_drift import add_indicators
from backtest_es_po_comp_drift_strategy import simulate_exit
from es_po_comp_drift_holdout_nq import scan_episodes

DIR = "/root/spy/analyst/forward_2026"
FWD_START = pd.Timestamp("2026-01-26").date()
INSTR = {
    "ES": {"contracts": ["ESH6", "ESM6", "ESU6"], "cost": 0.31,
           "atr_min": 2.0, "dpp": 50.0},
    "NQ": {"contracts": ["NQH6", "NQM6", "NQU6"], "cost": 0.405,
           "atr_min": 2.6, "dpp": 20.0},
}


def load_contract(name):
    df = pd.read_csv(os.path.join(DIR, f"{name}_1min.csv"), header=None,
                     names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])
    return df.set_index("ts").sort_index()


def rth_3m(df1m):
    df = df1m.between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    df = df[rng_pct <= 0.03]
    o = df["o"].resample("3min", label="left", closed="left").first()
    h = df["h"].resample("3min", label="left", closed="left").max()
    l = df["l"].resample("3min", label="left", closed="left").min()
    c = df["c"].resample("3min", label="left", closed="left").last()
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()


def main():
    all_trades = []
    for root, cfg in INSTR.items():
        raw = {t: load_contract(t) for t in cfg["contracts"]}
        # front month by daily RTH volume
        vol = pd.DataFrame({
            t: d.between_time("09:30", "15:59")["v"].groupby(
                d.between_time("09:30", "15:59").index.date).sum()
            for t, d in raw.items()}).fillna(0)
        front = vol.idxmax(axis=1)

        for t in cfg["contracts"]:
            f_days = front[front == t].index
            if len(f_days) == 0:
                continue
            f_start, f_end = min(f_days), max(f_days)
            keep_from = pd.Timestamp(f_start) - pd.Timedelta(days=14)
            tf = rth_3m(raw[t].loc[keep_from:])
            if len(tf) < 300:
                continue
            tf = add_indicators(tf)
            tf["date"] = tf.index.date
            ev = scan_episodes(tf)
            f_set = set(f_days)
            ev = ev[[d in f_set and d >= FWD_START for d in ev["date"]]]
            ev = ev[ev["atr"] >= cfg["atr_min"]]

            o = tf["o"].values; h = tf["h"].values
            l = tf["l"].values; c = tf["c"].values
            dates = tf["date"].values
            pos = {ts: i for i, ts in enumerate(tf.index)}
            day_end = {}
            for d, gi in pd.Series(range(len(tf)), index=dates).groupby(level=0):
                day_end[d] = int(gi.iloc[-1])

            for cfg_name, mask, mode in [
                    ("B_aligned_brk10", ev["align"] == "aligned", "brk10"),
                    ("A_flat_fix10", ev["cls"] == "flat", "fix10")]:
                for _, e in ev[mask].iterrows():
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
                    net = s * (r[0] - o[i + 1]) - cfg["cost"]
                    all_trades.append({
                        "root": root, "contract": t, "config": cfg_name,
                        "day": str(e["date"]), "month": str(e["date"])[:7],
                        "side": s, "net_pts": net,
                        "net_usd": net * cfg["dpp"]})

    tr = pd.DataFrame(all_trades)
    print(f"forward window: {FWD_START} -> 2026-07-10")
    for cfg_name in ["B_aligned_brk10", "A_flat_fix10"]:
        print(f"\n=== {cfg_name} ===")
        sub_all = tr[tr["config"] == cfg_name]
        for root in ["ES", "NQ", "BOTH"]:
            s = sub_all if root == "BOTH" else sub_all[sub_all["root"] == root]
            if len(s) < 3:
                print(f"  {root:4s} n={len(s)} (too few)")
                continue
            daily = s.groupby("day")["net_usd"].sum()
            tc = (daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
                  if len(daily) > 2 else np.nan)
            print(f"  {root:4s} n={len(s):4d}  avg net "
                  f"${s['net_usd'].mean():+8.2f}/trade  total "
                  f"${s['net_usd'].sum():+10.0f}  win {(s['net_usd']>0).mean()*100:.0f}%  "
                  f"day-clust t={tc:+.2f}  "
                  f"long n={(s['side']==1).sum()} short n={(s['side']==-1).sum()}")
        if len(sub_all):
            print("  by month ($, both instruments): " + "  ".join(
                f"{m}: {v:+,.0f}" for m, v in
                sub_all.groupby("month")["net_usd"].sum().items()))
    tr.to_csv(os.path.join(DIR, "forward_trades.csv"), index=False)
    print(f"\nwrote {len(tr)} trades -> {DIR}/forward_trades.csv")


if __name__ == "__main__":
    main()

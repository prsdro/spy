"""10m confluence filter for the ES 3m compression-drift strategy.

Pedro's proposal: at 3m signal time, check the 10m chart —
  - 10m in expansion SAME direction  -> good sign (trade / full size)
  - 10m in expansion OPPOSITE dir    -> skip
  - 10m in compression               -> size down

10m state (live-knowable): built from the last COMPLETED 10m bar as of the 3m
signal bar's close (10m bar stamped period-start, completes at start+10min).
State machine per 10m bar:
  compression=1 -> "comp"
  first bar after a squeeze (any run >=2 bars) -> expansion event; direction =
    close vs midpoint of last min(5, run_len) compression bars' range,
    carried forward ("up"/"dn") until the next compression starts.
  compression=0 with no prior event yet -> "unk"

Frozen configs from the strategy layer (cost 0.31 pts RT, ATR>=2 filter):
  flat_break / fix10        aligned_cont / brk10
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
from backtest_es_po_comp_drift import add_indicators, DATA
from backtest_es_po_comp_drift_strategy import simulate_exit, COST_PTS

EV_CSV = "/root/spy/analyst/es_po_comp_drift_events.csv"
ATR_MIN = 2.0


def load_1m():
    df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index().between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    return df[rng_pct <= 0.03]


def build_tf(df1m, rule):
    o = df1m["o"].resample(rule, label="left", closed="left").first()
    h = df1m["h"].resample(rule, label="left", closed="left").max()
    l = df1m["l"].resample(rule, label="left", closed="left").min()
    c = df1m["c"].resample(rule, label="left", closed="left").last()
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()


def tenm_state_series(tf10):
    """State per 10m bar, keyed by the time the bar COMPLETES."""
    comp = tf10["compression"].values
    h = tf10["h"].values; l = tf10["l"].values; c = tf10["c"].values
    n = len(tf10)
    states = []
    cur = 0            # carried expansion direction, 0 = unknown
    in_comp = False
    run_start = 0
    for i in range(n):
        if comp[i] == 1:
            if not in_comp:
                in_comp, run_start = True, i
            states.append("comp")
        else:
            if in_comp:
                run_len = i - run_start
                if run_len >= 2:
                    k = min(5, run_len)
                    mid = (h[i - k:i].max() + l[i - k:i].min()) / 2.0
                    cur = 1 if c[i] > mid else -1
                in_comp = False
            states.append({1: "up", -1: "dn", 0: "unk"}[cur])
    ts_known = tf10.index + pd.Timedelta(minutes=10)
    return pd.DataFrame({"ts_known": ts_known, "state10": states})


def main():
    print("loading 1m, building 3m + 10m...")
    df1m = load_1m()
    tf3 = add_indicators(build_tf(df1m, "3min"))
    tf10 = add_indicators(build_tf(df1m, "10min"))
    print(f"10m compression rate: {tf10['compression'].mean()*100:.1f}%")

    st10 = tenm_state_series(tf10)

    tf3["date"] = tf3.index.date
    o = tf3["o"].values; h = tf3["h"].values
    l = tf3["l"].values; c = tf3["c"].values
    dates = tf3["date"].values
    pos = {ts: i for i, ts in enumerate(tf3.index)}
    day_end = {}
    for d, gi in pd.Series(range(len(tf3)), index=dates).groupby(level=0):
        day_end[d] = int(gi.iloc[-1])

    ev = pd.read_csv(EV_CSV, parse_dates=["exp_ts"])
    ev = ev[ev["atr"] >= ATR_MIN].copy()
    ev["ts_known"] = ev["exp_ts"] + pd.Timedelta(minutes=3)
    ev = ev.sort_values("ts_known")
    ev = pd.merge_asof(ev, st10.sort_values("ts_known"), on="ts_known",
                       direction="backward")

    def bucket(row, sig_dir):
        s = row["state10"]
        if s == "comp":
            return "10m_comp"
        if s == "unk" or pd.isna(s):
            return "unk"
        d = 1 if s == "up" else -1
        return "same" if d == sig_dir else "opposite"

    def run_config(name, sub, dir_col, mode):
        print(f"\n=== {name} (atr>={ATR_MIN}) ===")
        rows = []
        for _, e in sub.iterrows():
            i = pos.get(e["exp_ts"])
            if i is None:
                continue
            dend = day_end[dates[i]]
            if i + 1 > dend:
                continue
            direction = int(e[dir_col])
            r = simulate_exit(o, h, l, c, i + 1, dend, direction, e["atr"], mode)
            if r is None:
                continue
            net = direction * (r[0] - o[i + 1]) - COST_PTS
            rows.append({"net": net, "b": bucket(e, direction),
                         "day": str(e["exp_ts"].date()),
                         "year": e["exp_ts"].year})
        t = pd.DataFrame(rows)
        for b in ["same", "opposite", "10m_comp", "unk"]:
            x = t[t["b"] == b]["net"]
            if len(x) < 5:
                print(f"  {b:9s} n={len(x)}")
                continue
            daily = t[t["b"] == b].groupby("day")["net"].sum()
            tc = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
            half = len(x) // 2
            print(f"  {b:9s} n={len(x):5d} ({len(x)/len(t)*100:4.1f}%)  "
                  f"avg net {x.mean():+.3f} pts (${x.mean()*50:+7.2f})  "
                  f"day-clust t={tc:+.2f}  win {(x>0).mean()*100:.0f}%  "
                  f"1st {x.iloc[:half].mean():+.3f} / 2nd {x.iloc[half:].mean():+.3f}")
        # Pedro's rule vs baseline: same=1x, comp=0.5x, opposite&unk=0
        base = t["net"]
        w = t["b"].map({"same": 1.0, "10m_comp": 0.5,
                        "opposite": 0.0, "unk": 0.0})
        filt = t["net"] * w
        taken = w > 0
        print(f"  -- unfiltered: n={len(base)}, avg {base.mean():+.3f}, "
              f"total {base.sum():+.0f} pts")
        print(f"  -- Pedro rule: n_taken={taken.sum()}, "
              f"avg per taken (size-wtd) {filt[taken].sum()/w[taken].sum():+.3f}, "
              f"total {filt.sum():+.0f} pts (contract-weighted)")
        return t

    run_config("flat_break/fix10", ev[ev["cls"] == "flat"], "sign", "fix10")
    run_config("aligned_cont/brk10", ev[ev["align"] == "aligned"], "sign", "brk10")

    # curiosity: does 10m state predict outcome for ALL 3m expansions?
    print("\n=== all 3m expansions (atr>=2), event ret_10 by 10m confluence ===")
    ev["b"] = [bucket(r, int(r["sign"])) for _, r in ev.iterrows()]
    for b in ["same", "opposite", "10m_comp", "unk"]:
        x = ev[ev["b"] == b]["ret_10"].dropna()
        if len(x) < 5:
            continue
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
        print(f"  {b:9s} n={len(x):5d}  ret_10 {x.mean():+.3f} ATR (t={t:+.1f})")


if __name__ == "__main__":
    main()

"""
ES day-trade: dual-TF bullish EMA stack + 3m Saty PO compression->bullish
expansion arm, pullback-into-ribbon entry, fixed bracket.

Data: FirstRateData ES 1-min continuous ratio-adjusted, 2008-01-02 -> 2026-01-23,
ET wall-clock, period-start timestamps. RTH bars only (09:30-15:59 ET).

Conditions (evaluated on COMPLETED bars only, no lookahead):
  1. 10m EMA21 slope > 0
  2. 10m EMA9 slope > 0 and EMA9 > EMA21
  3. 3m EMA21 slope > 0 and 3m EMA21 > 10m EMA21
  4. 3m EMA9 slope > 0 and 3m EMA9 > 3m EMA21
  5. 3m Saty PO in compression -> WATCH
  6. compression ends with oscillator rising -> ARMED (conds 1-4 must hold)
  7. while ARMED: resting limit at 3m EMA9 (zone top, prev completed bar);
     price trades into the 9/21 zone -> buy 1 ES
Disarm: conds 1-4 fail at a 3m close, or 3m close < 3m EMA21.
New compression while armed -> back to WATCH.
Arm is consumed on entry; a fresh compression->expansion is needed to re-arm.

Exits: stop 5 pts, target 8 pts, simulated on 1-min bars, stop-first if
both touch in one minute; force flat at open of the last RTH minute (15:59).

Entry windows (ET): 09:30-12:00 and 15:00-15:45  (= 8:30-11:00 / 14:00-14:45 CT).
Costs: 0.31 pts round trip (1 tick slippage + ~$3 commission at $50/pt),
same as the ES CBC scalp study.

Baseline: unconditional long with the same 5/8 bracket, entered at market at
every 10th eligible minute in the same windows, same costs.

Output: console summary + analyst/es_ema_po_pullback_trades.csv
"""

import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_trades.csv")

STOP_PTS = 5.0
TGT_PTS = 8.0
COST_PTS = 0.31
PT_VALUE = 50.0
WARMUP_BARS = 100

WIN1 = (9 * 60 + 30, 12 * 60)       # [09:30, 12:00) ET
WIN2 = (15 * 60, 15 * 60 + 45)      # [15:00, 15:45) ET


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, period=14):
    prev_c = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_c).abs(),
                    (df["low"] - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_phase_oscillator(df):
    """Saty Phase Oscillator + compression flag (verbatim logic from indicators.py)."""
    price = df["close"]
    atr_14 = atr(df, 14)
    pivot = ema(price, 21)
    std_21 = price.rolling(21).std()

    raw_signal = ((price - pivot) / (3.0 * atr_14)) * 100
    oscillator = ema(raw_signal, 3)
    df["phase_oscillator"] = oscillator

    above_pivot = price >= pivot
    bband_up = pivot + 2.0 * std_21
    bband_down = pivot - 2.0 * std_21
    comp_thresh_up = pivot + (2.0 * atr_14)
    comp_thresh_down = pivot - (2.0 * atr_14)
    exp_thresh_up = pivot + (1.854 * atr_14)
    exp_thresh_down = pivot - (1.854 * atr_14)

    compression_val = np.where(above_pivot,
                               bband_up - comp_thresh_up,
                               comp_thresh_down - bband_down)
    in_exp_zone = np.where(above_pivot,
                           bband_up - exp_thresh_up,
                           exp_thresh_down - bband_down)

    comp_s = pd.Series(compression_val, index=df.index)
    exp_flag = (comp_s.shift(1) <= comp_s).values
    inexp_arr = in_exp_zone
    comp_arr = compression_val

    po_comp = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        if exp_flag[i] and inexp_arr[i] > 0:
            po_comp[i] = 0
        elif comp_arr[i] <= 0:
            po_comp[i] = 1
        else:
            po_comp[i] = 0
    df["po_compression"] = po_comp
    return df


def load_minute():
    df = pd.read_csv(DATA, header=None,
                     names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    df = df.between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    bad = rng_pct > 0.03
    if bad.any():
        print(f"dropping {bad.sum()} 1-min bars with range > 3% of price")
        df = df[~bad]
    return df


def build_tf(df1m, rule):
    o = df1m["o"].resample(rule, label="left", closed="left").first()
    h = df1m["h"].resample(rule, label="left", closed="left").max()
    l = df1m["l"].resample(rule, label="left", closed="left").min()
    c = df1m["c"].resample(rule, label="left", closed="left").last()
    tf = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()
    tf["ema9"] = ema(tf["close"], 9)
    tf["ema21"] = ema(tf["close"], 21)
    return tf


def main():
    print("loading 1-min ES...", flush=True)
    m1 = load_minute()

    tf3 = build_tf(m1, "3min")
    tf10 = build_tf(m1, "10min")
    tf3 = compute_phase_oscillator(tf3)

    # bar END times for no-lookahead alignment
    tf3 = tf3.reset_index().rename(columns={"ts": "start"})
    tf3["end"] = tf3["start"] + pd.Timedelta(minutes=3)
    tf10 = tf10.reset_index().rename(columns={"ts": "start"})
    tf10["end"] = tf10["start"] + pd.Timedelta(minutes=10)

    tf10["s21_10"] = tf10["ema21"].diff()
    tf10["s9_10"] = tf10["ema9"].diff()
    ten = tf10[["end", "ema9", "ema21", "s9_10", "s21_10"]].rename(
        columns={"ema9": "ema9_10", "ema21": "ema21_10"})

    tf3["s21_3"] = tf3["ema21"].diff()
    tf3["s9_3"] = tf3["ema9"].diff()
    tf3 = pd.merge_asof(tf3.sort_values("end"), ten.sort_values("end"),
                        on="end", direction="backward")

    tf3["cond_all"] = (
        (tf3["s21_10"] > 0) &
        (tf3["s9_10"] > 0) & (tf3["ema9_10"] > tf3["ema21_10"]) &
        (tf3["s21_3"] > 0) & (tf3["ema21"] > tf3["ema21_10"]) &
        (tf3["s9_3"] > 0) & (tf3["ema9"] > tf3["ema21"])
    )
    tf3["osc_rising"] = tf3["phase_oscillator"].diff() > 0
    tf3.loc[:WARMUP_BARS, "cond_all"] = False

    # ---- arrays for the 1-min walk ----
    m1r = m1.reset_index()
    m1r["mod"] = m1r["ts"].dt.hour * 60 + m1r["ts"].dt.minute
    m1r["day"] = pd.factorize(m1r["ts"].dt.date)[0]
    last_of_day = m1r["day"].ne(m1r["day"].shift(-1)).values

    in_win = (((m1r["mod"] >= WIN1[0]) & (m1r["mod"] < WIN1[1])) |
              ((m1r["mod"] >= WIN2[0]) & (m1r["mod"] < WIN2[1]))).values

    # index of last COMPLETED 3m bar at each 1-min bar start
    idx3 = np.searchsorted(tf3["end"].values, m1r["ts"].values, side="right") - 1

    o1 = m1r["o"].values; h1 = m1r["h"].values
    l1 = m1r["l"].values; ts1 = m1r["ts"].values

    comp = tf3["po_compression"].values
    cond = tf3["cond_all"].values
    rising = tf3["osc_rising"].values
    e9_3 = tf3["ema9"].values
    e21_3 = tf3["ema21"].values
    c3 = tf3["close"].values

    IDLE, WATCH, ARMED = 0, 1, 2
    state = IDLE
    seen3 = -1
    in_pos = False
    entry_px = stop = tgt = 0.0
    entry_ts = None
    entry_state_ts = None
    trades = []

    n = len(m1r)
    for i in range(n):
        j = idx3[i]

        # ---- manage open position on this 1-min bar ----
        if in_pos:
            exit_px = None; reason = None
            if last_of_day[i]:
                exit_px, reason = o1[i], "eod"
            elif l1[i] <= stop:
                exit_px, reason = min(o1[i], stop), "stop"
            elif h1[i] >= tgt:
                exit_px, reason = max(o1[i], tgt), "target"
            if exit_px is not None:
                trades.append({
                    "entry_ts": entry_ts, "exit_ts": ts1[i],
                    "entry": entry_px, "exit": exit_px, "reason": reason,
                    "arm_ts": entry_state_ts,
                    "pnl_pts": exit_px - entry_px - COST_PTS,
                })
                in_pos = False
            if in_pos or exit_px is not None:
                # no same-minute re-entry after an exit; skip state/entry below
                if in_pos:
                    continue

        # ---- advance 3m state machine on newly completed bars ----
        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if comp[k] == 1:
                    state = WATCH
                elif state == WATCH:
                    # compression just ended
                    state = ARMED if (rising[k] and cond[k]) else IDLE
                elif state == ARMED:
                    if (not cond[k]) or (c3[k] < e21_3[k]):
                        state = IDLE
            seen3 = j

        # ---- entry: resting limit at zone top while armed, in window ----
        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            zone_top = e9_3[j]
            zone_bot = e21_3[j]
            if zone_top > zone_bot and l1[i] <= zone_top:
                fill = min(o1[i], zone_top)
                if fill > zone_bot - 1e-9 or o1[i] <= zone_top:
                    in_pos = True
                    entry_px = fill
                    stop = fill - STOP_PTS
                    tgt = fill + TGT_PTS
                    entry_ts = ts1[i]
                    entry_state_ts = tf3["end"].values[j]
                    state = IDLE  # arm consumed

    tr = pd.DataFrame(trades)
    tr["entry_ts"] = pd.to_datetime(tr["entry_ts"])
    tr["exit_ts"] = pd.to_datetime(tr["exit_ts"])
    tr["year"] = tr["entry_ts"].dt.year
    tr["window"] = np.where(tr["entry_ts"].dt.hour < 13, "AM", "PM")
    tr["pnl_usd"] = tr["pnl_pts"] * PT_VALUE
    tr["win"] = tr["pnl_pts"] > 0
    tr["mins_held"] = (tr["exit_ts"] - tr["entry_ts"]).dt.total_seconds() / 60
    tr.to_csv(OUT_CSV, index=False)

    def summarize(t, label):
        if len(t) == 0:
            print(f"{label}: no trades"); return
        pnl = t["pnl_pts"]
        tstat = pnl.mean() / (pnl.std(ddof=1) / np.sqrt(len(pnl))) if len(pnl) > 1 else np.nan
        daily = t.groupby(t["entry_ts"].dt.date)["pnl_pts"].sum()
        tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
        print(f"\n== {label} ==")
        print(f"  n={len(t)}  ({len(daily)} distinct days, "
              f"{len(t)/t['year'].nunique():.0f}/yr)")
        print(f"  win rate      : {t['win'].mean()*100:.1f}%")
        print(f"  avg pnl       : {pnl.mean():+.3f} pts (${pnl.mean()*PT_VALUE:+.2f}) net")
        print(f"  median pnl    : {pnl.median():+.3f} pts")
        print(f"  total         : {pnl.sum():+.1f} pts (${pnl.sum()*PT_VALUE:+,.0f})")
        print(f"  t-stat        : {tstat:.2f} (per-trade)  {tday:.2f} (day-clustered)")
        print(f"  exits         : {t['reason'].value_counts().to_dict()}")
        print(f"  avg mins held : {t['mins_held'].mean():.0f}")
        eq = t.sort_values("exit_ts")["pnl_usd"].cumsum()
        dd = (eq - eq.cummax()).min()
        print(f"  max drawdown  : ${dd:,.0f} (1 ES)")

    summarize(tr, f"STRATEGY  stop {STOP_PTS} / tgt {TGT_PTS}, cost {COST_PTS} pts RT")
    for w in ["AM", "PM"]:
        summarize(tr[tr["window"] == w], f"window {w}")

    print("\n  by year (n, win%, avg pts, total pts):")
    g = tr.groupby("year").agg(n=("pnl_pts", "size"), win=("win", "mean"),
                               avg=("pnl_pts", "mean"), tot=("pnl_pts", "sum"))
    for y, r in g.iterrows():
        print(f"    {y}: n={r['n']:>3.0f}  {r['win']*100:5.1f}%  "
              f"{r['avg']:+.3f}  {r['tot']:+7.1f}")

    # ---- baseline: unconditional 5/8 bracket long, every 10th window minute ----
    print("\ncomputing baseline...", flush=True)
    base = []
    i = 0
    while i < n:
        if in_win[i] and not last_of_day[i]:
            fill = o1[i]
            bstop, btgt = fill - STOP_PTS, fill + TGT_PTS
            k = i
            while k < n:
                if last_of_day[k]:
                    base.append(o1[k] - fill - COST_PTS); break
                if l1[k] <= bstop:
                    base.append(min(o1[k], bstop) - fill - COST_PTS); break
                if h1[k] >= btgt:
                    base.append(max(o1[k], btgt) - fill - COST_PTS); break
                k += 1
            i += 10
        else:
            i += 1
    b = np.array(base)
    bt = b.mean() / (b.std(ddof=1) / np.sqrt(len(b)))
    print(f"\n== BASELINE (unconditional long, same bracket/windows/costs) ==")
    print(f"  n={len(b)}  win-ish rate {np.mean(b > 0)*100:.1f}%")
    print(f"  avg pnl {b.mean():+.3f} pts (${b.mean()*PT_VALUE:+.2f})  t={bt:.2f} "
          f"(overlapping entries, t overstated)")

    print(f"\ntrades written to {OUT_CSV}")


if __name__ == "__main__":
    main()

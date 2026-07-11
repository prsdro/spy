"""
ES 3m Compression Drift -> Expansion Study
==========================================

HYPOTHESIS (Pedro, 2026-07-10)
On the ES 3-minute chart, when Saty compression is FLAT (the high/low set by
the first 5 compression candles is not significantly breached by later
compression candles), expansion resolves as an immediate directional move in
the expansion direction. But when the compression DRIFTS (candles keep setting
new highs, e.g. over 15 candles), the first few expansion candles are a mean
reversion rather than an immediate move in the expansion direction.

DATA
FirstRateData ES 1-min continuous ratio-adjusted (2008-01 -> 2026-01, ET,
period-start stamps), RTH 09:30-15:59 only, bad bars (range > 3% of close)
dropped, resampled to 3m. Same pipeline as backtest_es_cbc_scalp.py.

COMPRESSION
Saty Pine logic (identical to indicators.py compute_pivot_ribbon):
BB(21, 2sigma) width vs 2x ATR14 around EMA21, with the expansion-zone
tracker (release at 1.854x ATR while widening). Computed on RTH-only 3m
series (continuous ewm across days, matches prior ES studies).

EPISODES
Contiguous compression=1 runs with 1-bar gap tolerance, entirely within one
RTH session, expansion bar (first compression=0 bar) must exist in-session.
Minimum 8 compression bars: 5 "initial" + >=3 "subsequent" to judge drift.

FLAT vs DRIFT
init_high/init_low = extremes of first 5 compression bars.
Over subsequent bars (6..end):
  brk_up = max(0, max_high - init_high) / ATR14_at_expansion
  brk_dn = max(0, init_low - min_low) / ATR14_at_expansion
  new_high_bars / new_low_bars = # of subsequent bars strictly setting a new
    episode high / low
Classes:
  flat     : brk_up < 0.25 and brk_dn < 0.25   (initial range held, +/- noise)
  drift_up : brk_up >= 0.50 and brk_dn < 0.25  (clear one-way upward creep)
  drift_dn : brk_dn >= 0.50 and brk_up < 0.25
  mixed    : everything else (both sides breached, or moderate breach)
Continuous drift_score = brk_up - brk_dn (ATR units) for quartile analysis.

EXPANSION DIRECTION
Primary: expansion-bar close vs midpoint of the LAST 5 compression bars'
range (full-episode midpoint is mechanically biased for drifting episodes).
Secondary (sensitivity): expansion candle color (close vs open).

OUTCOMES (signed in expansion direction, ATR units, same session only)
  ret_k   : (close[exp+k] - exp_close) * sign / ATR   for k in 1,2,3,5,10,20
  retno_k : same but from next-bar open (tradeable entry)
  mfe3/mae3, mfe10/mae10 : max favorable / adverse excursion over bars
    exp+1..exp+3 and exp+1..exp+10 vs exp_close
Key split: flat vs drift-ALIGNED (expansion same direction as drift) vs
drift-OPPOSED (expansion against the drift).

Output: analyst/es_po_comp_drift_events.csv + console summary.
"""

import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_po_comp_drift_events.csv")

MIN_COMP_BARS = 8      # 5 initial + >=3 subsequent
INIT_BARS = 5
GAP_TOLERANCE = 1
FLAT_THR = 0.25        # ATR units
DRIFT_THR = 0.50       # ATR units
HORIZONS = [1, 2, 3, 5, 10, 20]
WARMUP_BARS = 200


def load_3m():
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

    o = df["o"].resample("3min", label="left", closed="left").first()
    h = df["h"].resample("3min", label="left", closed="left").max()
    l = df["l"].resample("3min", label="left", closed="left").min()
    c = df["c"].resample("3min", label="left", closed="left").last()
    tf = pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()
    return tf


def add_indicators(tf):
    price = tf["c"]
    tf["ema8"] = price.ewm(span=8, adjust=False).mean()
    tf["ema21"] = price.ewm(span=21, adjust=False).mean()
    tf["ema48"] = price.ewm(span=48, adjust=False).mean()

    prev_c = price.shift(1)
    tr = pd.concat([tf["h"] - tf["l"],
                    (tf["h"] - prev_c).abs(),
                    (tf["l"] - prev_c).abs()], axis=1).max(axis=1)
    tf["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # Phase Oscillator (context only)
    po_raw = ((price - tf["ema21"]) / (3.0 * tf["atr14"])) * 100.0
    tf["po"] = po_raw.ewm(span=3, adjust=False).mean()

    # Saty compression tracker (identical to indicators.py compute_pivot_ribbon)
    std21 = price.rolling(21).std(ddof=0)
    pivot = tf["ema21"]
    above = price >= pivot
    bb_up = pivot + 2.0 * std21
    bb_dn = pivot - 2.0 * std21
    comp_thr_up = pivot + 2.0 * tf["atr14"]
    comp_thr_dn = pivot - 2.0 * tf["atr14"]
    exp_thr_up = pivot + 1.854 * tf["atr14"]
    exp_thr_dn = pivot - 1.854 * tf["atr14"]

    compression_s = pd.Series(
        np.where(above, bb_up - comp_thr_up, comp_thr_dn - bb_dn),
        index=tf.index)
    in_exp_s = pd.Series(
        np.where(above, bb_up - exp_thr_up, exp_thr_dn - bb_dn),
        index=tf.index)
    expansion = (compression_s.shift(1) <= compression_s).values

    comp_vals = np.zeros(len(tf), dtype=int)
    comp_arr = compression_s.values
    inexp_arr = in_exp_s.values
    for i in range(1, len(tf)):
        if expansion[i] and inexp_arr[i] > 0:
            comp_vals[i] = 0
        elif comp_arr[i] <= 0:
            comp_vals[i] = 1
        else:
            comp_vals[i] = 0
    tf["compression"] = comp_vals
    return tf.iloc[WARMUP_BARS:]


def find_periods(comp):
    """Contiguous compression runs with 1-bar gap tolerance.
    Returns (start, end) with end = index of first non-compression bar."""
    n = len(comp)
    smoothed = comp.copy()
    for i in range(1, n - 1):
        if smoothed[i] == 0 and smoothed[i - 1] == 1 and smoothed[i + 1] == 1:
            smoothed[i] = 1
    periods = []
    in_run, start = False, 0
    for i in range(n):
        if smoothed[i] == 1 and not in_run:
            start, in_run = i, True
        elif smoothed[i] == 0 and in_run:
            if i - start >= MIN_COMP_BARS:
                periods.append((start, i))
            in_run = False
    return periods


def time_bucket(ts):
    t = ts.time()
    if t < pd.Timestamp("10:30").time():
        return "open"
    if t < pd.Timestamp("14:00").time():
        return "mid"
    return "close"


def main():
    print("loading 1-min ES -> 3m RTH bars...")
    tf = load_3m()
    tf = add_indicators(tf)
    tf["date"] = tf.index.date
    print(f"{len(tf)} 3m bars, {tf.index[0]} -> {tf.index[-1]}, "
          f"compression rate {tf['compression'].mean()*100:.1f}%")

    events = []
    for date, g in tf.groupby("date"):
        if len(g) < MIN_COMP_BARS + 4:
            continue
        h = g["h"].values; l = g["l"].values
        o = g["o"].values; c = g["c"].values
        atr = g["atr14"].values; po = g["po"].values
        ema21 = g["ema21"].values; ema48 = g["ema48"].values
        n = len(g)

        for start, end in find_periods(g["compression"].values):
            if end >= n:          # expansion bar must exist in-session
                continue
            dur = end - start
            atr_e = atr[end]
            if not np.isfinite(atr_e) or atr_e <= 0:
                continue

            init_high = h[start:start + INIT_BARS].max()
            init_low = l[start:start + INIT_BARS].min()
            sub_h = h[start + INIT_BARS:end]
            sub_l = l[start + INIT_BARS:end]
            brk_up = max(0.0, sub_h.max() - init_high) / atr_e
            brk_dn = max(0.0, init_low - sub_l.min()) / atr_e

            # bars strictly setting new episode highs/lows after bar 5
            run_max = init_high; run_min = init_low
            nh = nl = 0
            for j in range(len(sub_h)):
                if sub_h[j] > run_max:
                    nh += 1; run_max = sub_h[j]
                if sub_l[j] < run_min:
                    nl += 1; run_min = sub_l[j]

            if brk_up < FLAT_THR and brk_dn < FLAT_THR:
                cls = "flat"
            elif brk_up >= DRIFT_THR and brk_dn < FLAT_THR:
                cls = "drift_up"
            elif brk_dn >= DRIFT_THR and brk_up < FLAT_THR:
                cls = "drift_dn"
            else:
                cls = "mixed"
            drift_score = brk_up - brk_dn

            # expansion direction: close vs midpoint of last-5-bars range
            last5_mid = (h[end - 5:end].max() + l[end - 5:end].min()) / 2.0
            exp_c = c[end]
            if exp_c > last5_mid:
                sign = 1
            elif exp_c < last5_mid:
                sign = -1
            else:
                sign = 1 if po[end] > 0 else -1
            dir_candle = 1 if c[end] > o[end] else (-1 if c[end] < o[end] else 0)

            full_mid = (h[start:end].max() + l[start:end].min()) / 2.0
            dir_fullmid = 1 if exp_c > full_mid else -1

            drift_dir = 1 if cls == "drift_up" else (-1 if cls == "drift_dn" else 0)
            if drift_dir == 0:
                align = "n/a"
            else:
                align = "aligned" if sign == drift_dir else "opposed"

            ev = {
                "date": date, "exp_ts": g.index[end], "dur_bars": dur,
                "cls": cls, "brk_up": brk_up, "brk_dn": brk_dn,
                "drift_score": drift_score, "new_high_bars": nh,
                "new_low_bars": nl, "sign": sign, "dir_candle": dir_candle,
                "dir_fullmid": dir_fullmid, "align": align,
                "exp_close": exp_c, "atr": atr_e, "po_exp": po[end],
                "ema_trend_bull": int(ema21[end] > ema48[end]),
                "tod": time_bucket(g.index[end]),
                "comp_range_atr": (h[start:end].max() - l[start:end].min()) / atr_e,
            }

            # forward returns from expansion close, signed in expansion dir
            for k in HORIZONS:
                ev[f"ret_{k}"] = (sign * (c[end + k] - exp_c) / atr_e
                                  if end + k < n else np.nan)
            # from next-bar open (tradeable)
            if end + 1 < n:
                no = o[end + 1]
                for k in HORIZONS:
                    ev[f"retno_{k}"] = (sign * (c[end + k] - no) / atr_e
                                        if end + k < n else np.nan)
            else:
                for k in HORIZONS:
                    ev[f"retno_{k}"] = np.nan

            # MFE / MAE over exp+1..exp+3 and exp+1..exp+10 vs exp_close
            for w, tag in [(3, "3"), (10, "10")]:
                if end + 1 < n:
                    e2 = min(end + w + 1, n)
                    wh = h[end + 1:e2]; wl = l[end + 1:e2]
                    if sign == 1:
                        ev[f"mfe{tag}"] = (wh.max() - exp_c) / atr_e
                        ev[f"mae{tag}"] = (exp_c - wl.min()) / atr_e
                    else:
                        ev[f"mfe{tag}"] = (exp_c - wl.min()) / atr_e
                        ev[f"mae{tag}"] = (wh.max() - exp_c) / atr_e
                    ev[f"nbars{tag}"] = e2 - (end + 1)
                else:
                    ev[f"mfe{tag}"] = ev[f"mae{tag}"] = np.nan
                    ev[f"nbars{tag}"] = 0
            events.append(ev)

    df = pd.DataFrame(events)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\n{len(df)} episodes -> {OUT_CSV}")
    print(f"date range: {df['date'].min()} -> {df['date'].max()}")

    def tstat(x):
        x = x.dropna()
        if len(x) < 3 or x.std(ddof=1) == 0:
            return np.nan
        return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))

    def block(sub, label):
        print(f"\n  {label}  (n={len(sub)})")
        if len(sub) == 0:
            return
        row = "    ret  "
        for k in HORIZONS:
            m = sub[f"ret_{k}"].mean()
            t = tstat(sub[f"ret_{k}"])
            row += f"+{k}: {m:+.3f} (t={t:+.1f})  "
        print(row)
        row = "    retno"
        for k in HORIZONS:
            m = sub[f"retno_{k}"].mean()
            t = tstat(sub[f"retno_{k}"])
            row += f"+{k}: {m:+.3f} (t={t:+.1f})  "
        print(row)
        print(f"    mfe3 {sub['mfe3'].mean():+.3f}  mae3 {sub['mae3'].mean():+.3f}  "
              f"mfe10 {sub['mfe10'].mean():+.3f}  mae10 {sub['mae10'].mean():+.3f}  "
              f"| ret_3>0: {(sub['ret_3'] > 0).mean()*100:.1f}%  "
              f"ret_10>0: {(sub['ret_10'] > 0).mean()*100:.1f}%")

    print("\n" + "=" * 100)
    print("  CLASS COUNTS")
    print("=" * 100)
    print(df["cls"].value_counts().to_string())
    print(f"\n  alignment among drift episodes:")
    print(df[df["cls"].isin(['drift_up', 'drift_dn'])]["align"]
          .value_counts().to_string())
    print(f"\n  direction agreement: last5-mid vs candle color "
          f"{(df['sign'] == df['dir_candle']).mean()*100:.1f}%, "
          f"vs full-episode-mid {(df['sign'] == df['dir_fullmid']).mean()*100:.1f}%")

    print("\n" + "=" * 100)
    print("  KEY TEST — signed fwd returns in expansion direction (ATR units)")
    print("=" * 100)
    block(df, "ALL episodes")
    block(df[df["cls"] == "flat"], "FLAT (initial 5-bar range held +/-0.25 ATR)")
    block(df[df["align"] == "aligned"], "DRIFT, expansion ALIGNED with drift")
    block(df[df["align"] == "opposed"], "DRIFT, expansion OPPOSED to drift")
    block(df[df["cls"] == "mixed"], "MIXED / moderate breach")

    print("\n" + "=" * 100)
    print("  DRIFT SCORE QUARTILES (|drift_score|, drift episodes pooled w/ sign flipped to drift dir)")
    print("=" * 100)
    # continuous view: signed fwd ret in DRIFT direction by |drift| quartile
    d = df[df["cls"].isin(["drift_up", "drift_dn"])].copy()
    if len(d) > 40:
        ddir = np.where(d["cls"] == "drift_up", 1, -1)
        for k in HORIZONS:
            d[f"dret_{k}"] = d[f"ret_{k}"] * ddir * d["sign"]  # re-sign to drift dir
        d["absd"] = d["drift_score"].abs()
        d["q"] = pd.qcut(d["absd"], 4, labels=["q1", "q2", "q3", "q4"])
        for q in ["q1", "q2", "q3", "q4"]:
            sub = d[d["q"] == q]
            row = f"  {q} (|drift| {sub['absd'].min():.2f}-{sub['absd'].max():.2f}, n={len(sub)})  fwd in DRIFT dir: "
            for k in [1, 3, 10]:
                row += f"+{k}: {sub[f'dret_{k}'].mean():+.3f} (t={tstat(sub[f'dret_{k}']):+.1f})  "
            print(row)

    print("\n" + "=" * 100)
    print("  SENSITIVITY — direction = expansion candle color")
    print("=" * 100)
    dc = df[df["dir_candle"] != 0].copy()
    flip = dc["dir_candle"] * dc["sign"]  # +1 if same, -1 if flipped
    for k in HORIZONS:
        dc[f"ret_{k}"] = dc[f"ret_{k}"] * flip
        dc[f"retno_{k}"] = dc[f"retno_{k}"] * flip
    # mfe/mae not re-signed cleanly; skip in this view
    for lbl, sub in [("FLAT", dc[dc["cls"] == "flat"]),
                     ("ALIGNED", dc[(dc["align"] == "aligned")]),
                     ("OPPOSED", dc[(dc["align"] == "opposed")])]:
        row = f"  {lbl:8s} (n={len(sub)})  "
        for k in [1, 2, 3, 5, 10, 20]:
            row += f"+{k}: {sub[f'ret_{k}'].mean():+.3f} (t={tstat(sub[f'ret_{k}']):+.1f})  "
        print(row)

    print("\n" + "=" * 100)
    print("  BY DURATION (flat vs aligned)")
    print("=" * 100)
    df["dur_b"] = pd.cut(df["dur_bars"], [7, 11, 15, 24, 999],
                         labels=["8-11", "12-15", "16-24", "25+"])
    for lbl, mask in [("FLAT", df["cls"] == "flat"),
                      ("ALIGNED", df["align"] == "aligned")]:
        for b in ["8-11", "12-15", "16-24", "25+"]:
            sub = df[mask & (df["dur_b"] == b)]
            if len(sub) < 10:
                continue
            row = f"  {lbl:8s} dur {b:6s} (n={len(sub)})  "
            for k in [1, 3, 10]:
                row += f"+{k}: {sub[f'ret_{k}'].mean():+.3f} (t={tstat(sub[f'ret_{k}']):+.1f})  "
            print(row)

    print("\n" + "=" * 100)
    print("  BY TIME OF DAY (flat vs aligned, ret_3 / ret_10)")
    print("=" * 100)
    for lbl, mask in [("FLAT", df["cls"] == "flat"),
                      ("ALIGNED", df["align"] == "aligned"),
                      ("OPPOSED", df["align"] == "opposed")]:
        for tb in ["open", "mid", "close"]:
            sub = df[mask & (df["tod"] == tb)]
            if len(sub) < 10:
                continue
            print(f"  {lbl:8s} {tb:6s} (n={len(sub)})  "
                  f"ret_3 {sub['ret_3'].mean():+.3f} (t={tstat(sub['ret_3']):+.1f})  "
                  f"ret_10 {sub['ret_10'].mean():+.3f} (t={tstat(sub['ret_10']):+.1f})")

    # halves stability
    print("\n" + "=" * 100)
    print("  STABILITY — first half vs second half of sample (ret_3)")
    print("=" * 100)
    med_date = df["date"].astype(str).sort_values().iloc[len(df) // 2]
    for lbl, mask in [("FLAT", df["cls"] == "flat"),
                      ("ALIGNED", df["align"] == "aligned"),
                      ("OPPOSED", df["align"] == "opposed")]:
        a = df[mask & (df["date"].astype(str) <= med_date)]
        b = df[mask & (df["date"].astype(str) > med_date)]
        print(f"  {lbl:8s} 1st half (n={len(a)}) ret_3 {a['ret_3'].mean():+.3f} "
              f"(t={tstat(a['ret_3']):+.1f}) | 2nd half (n={len(b)}) "
              f"ret_3 {b['ret_3'].mean():+.3f} (t={tstat(b['ret_3']):+.1f})")

    print("\nDone.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
SPX vs SPY morning divergence study.

Hypothesis (Pedro):
  After big overnight moves, the Saty Phase Oscillator and Pivot Ribbon EMA
  states on SPX vs SPY can diverge significantly at the cash open. These
  divergences usually resolve by the afternoon. Is *how* they resolve a
  trading signal? Is SPY or SPX dominant for the morning session?

Design:
  - SPY 10m bars from spy.db's ind_10m (includes ETH 04:00-19:50, mirroring
    a TV chart with pre-market on). Pre-market bars absorb the overnight
    gap gradually, so SPY's EMA stack at 09:30 is ALREADY partly adjusted.
  - SPX 10m bars built from FirstRateData 1-min RTH-only data, then we
    compute the same Pivot Ribbon + Phase Oscillator stack from scratch.
    SPX has no ETH session, so the gap hits SPX's EMAs all at once at open.
  - Compare the two on RTH 10m timestamps (09:30..15:50, ET).
  - SPY overnight gap = (SPY 09:30 first-bar open - SPY prior-day RTH close)
    / prior-day RTH close. Prior-day RTH close from candles_1d.

Outputs:
  - analyst/spx_spy_divergence_summary.csv (per-day record)
  - analyst/spx_spy_divergence_by_gap.csv  (aggregated by |gap| bin)
  - analyst/spx_spy_divergence_run.log
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import sqlite3

BASE = Path(__file__).resolve().parent
DB = BASE / "spy.db"
DATA = BASE / "data"
OUT = BASE / "analyst"
OUT.mkdir(exist_ok=True)


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False).mean()


def atr14_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return rma(tr, 14)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Pivot Ribbon EMAs + Phase Oscillator on a continuous OHLC series.

    Mirrors indicators.py for consistency with stored SPY columns. Designed for
    the SPX 10m series; SPY's stored values come straight from ind_10m.
    """
    df = df.copy()
    p = df["close"]
    df["ema_8"] = ema(p, 8)
    df["ema_13"] = ema(p, 13)
    df["ema_21"] = ema(p, 21)
    df["ema_48"] = ema(p, 48)
    df["ema_200"] = ema(p, 200)
    df["fast_cloud_bullish"] = (df["ema_8"] >= df["ema_21"]).astype(int)
    df["slow_cloud_bullish"] = (df["ema_13"] >= df["ema_48"]).astype(int)
    df["longterm_bias_bullish"] = (df["ema_21"] >= df["ema_200"]).astype(int)
    a = atr14_series(df)
    pivot = df["ema_21"]
    raw = ((p - pivot) / (3.0 * a)) * 100
    df["phase_oscillator"] = ema(raw, 3)
    return df


def load_spx_10m_with_indicators() -> pd.DataFrame:
    """Load FirstRateData SPX 1-min, aggregate to 10m RTH, compute indicators."""
    zip_path = next(DATA.glob("SPX_full_1min_*.zip"))
    print(f"[spx] reading {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            df = pd.read_csv(
                f,
                header=None,
                names=["timestamp", "open", "high", "low", "close"],
                parse_dates=["timestamp"],
            )
    print(f"[spx] {len(df):,} 1-min rows  {df['timestamp'].min()} .. {df['timestamp'].max()}")

    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df["date"] = df.index.date

    # Aggregate per-day so each session's first 10m bar starts at 09:30:00.
    parts = []
    for _, g in df.groupby("date", sort=True):
        agg = (
            g.resample("10min", origin="start_day", offset="9h30min")
             .agg(open=("open", "first"), high=("high", "max"),
                  low=("low", "min"), close=("close", "last"))
             .dropna()
        )
        agg = agg.between_time("09:30", "15:50")
        parts.append(agg)
    spx_10m = pd.concat(parts).sort_index()
    print(f"[spx] {len(spx_10m):,} 10-min RTH rows after aggregation")

    spx_ind = compute_indicators(spx_10m)
    spx_ind["date"] = spx_ind.index.date
    return spx_ind


def load_spy_10m_rth(start_date) -> pd.DataFrame:
    """SPY 10m bars + indicators from spy.db, restricted to RTH labels (09:30..15:50)."""
    conn = sqlite3.connect(DB)
    cols = (
        "timestamp, open, high, low, close, "
        "ema_8, ema_13, ema_21, ema_48, ema_200, "
        "fast_cloud_bullish, slow_cloud_bullish, longterm_bias_bullish, "
        "phase_oscillator, candle_bias"
    )
    df = pd.read_sql_query(
        f"SELECT {cols} FROM ind_10m WHERE timestamp >= ? ORDER BY timestamp",
        conn, params=[str(start_date)], parse_dates=["timestamp"],
    )
    conn.close()
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:50")
    df["date"] = df.index.date
    print(f"[spy] {len(df):,} 10-min RTH rows from ind_10m starting {start_date}")
    return df


def load_spy_prev_rth_close() -> pd.Series:
    """Prior trading day's RTH close (from candles_1d). Indexed by date."""
    conn = sqlite3.connect(DB)
    daily = pd.read_sql_query(
        "SELECT timestamp, close FROM candles_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"],
    )
    conn.close()
    daily["date"] = daily["timestamp"].dt.date
    daily = daily.dropna(subset=["close"])
    s = daily.set_index("date")["close"]
    return s


def per_day_record(date, spy_day: pd.DataFrame, spx_day: pd.DataFrame, prev_spy_close: float):
    """Compute open, midday, EOD divergence + return metrics for a single date.

    spy_day / spx_day are RTH 10m bars for the same date. Indices align since
    SPX is RTH-only and SPY is filtered to RTH here.
    """
    if spy_day.empty or spx_day.empty:
        return None

    common = spy_day.index.intersection(spx_day.index)
    if len(common) < 30:  # need most of the session
        return None

    spy = spy_day.loc[common]
    spx = spx_day.loc[common]

    open_ts = pd.Timestamp(date) + pd.Timedelta("9h30min")
    noon_ts = pd.Timestamp(date) + pd.Timedelta("12h00min")
    eod_ts  = pd.Timestamp(date) + pd.Timedelta("15h50min")

    if open_ts not in spy.index or open_ts not in spx.index:
        return None
    if eod_ts not in spy.index or eod_ts not in spx.index:
        return None
    if noon_ts not in spy.index or noon_ts not in spx.index:
        return None

    spy_open_price = float(spy.loc[open_ts, "open"])
    if not np.isfinite(prev_spy_close) or prev_spy_close <= 0:
        return None
    gap_pct = (spy_open_price - prev_spy_close) / prev_spy_close * 100.0

    po_spy_open  = float(spy.loc[open_ts, "phase_oscillator"])
    po_spx_open  = float(spx.loc[open_ts, "phase_oscillator"])
    po_spy_noon  = float(spy.loc[noon_ts, "phase_oscillator"])
    po_spx_noon  = float(spx.loc[noon_ts, "phase_oscillator"])
    po_spy_eod   = float(spy.loc[eod_ts,  "phase_oscillator"])
    po_spx_eod   = float(spx.loc[eod_ts,  "phase_oscillator"])

    # Divergence in PO units
    d_open = po_spy_open - po_spx_open
    d_noon = po_spy_noon - po_spx_noon
    d_eod  = po_spy_eod  - po_spx_eod

    # Movement of each side from open
    dpo_spy_morning = po_spy_noon - po_spy_open
    dpo_spx_morning = po_spx_noon - po_spx_open
    dpo_spy_full    = po_spy_eod  - po_spy_open
    dpo_spx_full    = po_spx_eod  - po_spx_open

    # Ribbon state mismatches at open
    fast_match_open = int(spy.loc[open_ts, "fast_cloud_bullish"]) == int(spx.loc[open_ts, "fast_cloud_bullish"])
    slow_match_open = int(spy.loc[open_ts, "slow_cloud_bullish"]) == int(spx.loc[open_ts, "slow_cloud_bullish"])
    lt_match_open   = int(spy.loc[open_ts, "longterm_bias_bullish"]) == int(spx.loc[open_ts, "longterm_bias_bullish"])

    fast_spy_bull = int(spy.loc[open_ts, "fast_cloud_bullish"])
    fast_spx_bull = int(spx.loc[open_ts, "fast_cloud_bullish"])
    slow_spy_bull = int(spy.loc[open_ts, "slow_cloud_bullish"])
    slow_spx_bull = int(spx.loc[open_ts, "slow_cloud_bullish"])

    # Returns on SPY (the tradable instrument)
    spy_close_open = float(spy.loc[open_ts, "close"])
    spy_close_noon = float(spy.loc[noon_ts, "close"])
    spy_close_eod  = float(spy.loc[eod_ts,  "close"])

    morning_ret_pct = (spy_close_noon - spy_open_price) / spy_open_price * 100.0
    afternoon_ret_pct = (spy_close_eod - spy_close_noon) / spy_close_noon * 100.0
    full_ret_pct = (spy_close_eod - spy_open_price) / spy_open_price * 100.0

    return {
        "date": str(date),
        "gap_pct": gap_pct,
        "abs_gap_pct": abs(gap_pct),
        "po_spy_open": po_spy_open,
        "po_spx_open": po_spx_open,
        "d_open": d_open,
        "abs_d_open": abs(d_open),
        "po_spy_noon": po_spy_noon,
        "po_spx_noon": po_spx_noon,
        "d_noon": d_noon,
        "po_spy_eod": po_spy_eod,
        "po_spx_eod": po_spx_eod,
        "d_eod": d_eod,
        "dpo_spy_morning": dpo_spy_morning,
        "dpo_spx_morning": dpo_spx_morning,
        "dpo_spy_full": dpo_spy_full,
        "dpo_spx_full": dpo_spx_full,
        "fast_spy_bull_open": fast_spy_bull,
        "fast_spx_bull_open": fast_spx_bull,
        "slow_spy_bull_open": slow_spy_bull,
        "slow_spx_bull_open": slow_spx_bull,
        "fast_match_open": int(fast_match_open),
        "slow_match_open": int(slow_match_open),
        "lt_match_open": int(lt_match_open),
        "spy_morning_ret_pct": morning_ret_pct,
        "spy_afternoon_ret_pct": afternoon_ret_pct,
        "spy_full_ret_pct": full_ret_pct,
    }


def gap_bin(abs_gap_pct: float) -> str:
    if abs_gap_pct < 0.25:
        return "<0.25%"
    if abs_gap_pct < 0.50:
        return "0.25-0.5%"
    if abs_gap_pct < 1.00:
        return "0.5-1%"
    return ">=1%"


GAP_BIN_ORDER = ["<0.25%", "0.25-0.5%", "0.5-1%", ">=1%"]


def aggregate_summary(records: pd.DataFrame) -> pd.DataFrame:
    """Bin by |gap| and report central tendencies + simple resolution stats."""
    rows = []
    grouped = records.groupby("gap_bin")
    for label in GAP_BIN_ORDER:
        if label not in grouped.groups:
            continue
        g = grouped.get_group(label)
        n = len(g)
        # Convergence: |d_eod| smaller than |d_open|
        converged = (g["d_eod"].abs() < g["abs_d_open"]).mean() * 100
        converged_half = (g["d_eod"].abs() < 0.5 * g["abs_d_open"]).mean() * 100
        rows.append({
            "gap_bin": label,
            "n_days": n,
            "median_abs_gap_pct": g["abs_gap_pct"].median(),
            "median_abs_d_open": g["abs_d_open"].median(),
            "median_abs_d_noon": g["d_noon"].abs().median(),
            "median_abs_d_eod":  g["d_eod"].abs().median(),
            "pct_converged_eod": converged,
            "pct_converged_half_eod": converged_half,
            "fast_mismatch_open_pct": (1 - g["fast_match_open"]).mean() * 100,
            "slow_mismatch_open_pct": (1 - g["slow_match_open"]).mean() * 100,
            "lt_mismatch_open_pct":   (1 - g["lt_match_open"]).mean() * 100,
            "mean_dpo_spy_full": g["dpo_spy_full"].mean(),
            "mean_dpo_spx_full": g["dpo_spx_full"].mean(),
            "mean_morning_ret_pct": g["spy_morning_ret_pct"].mean(),
            "mean_afternoon_ret_pct": g["spy_afternoon_ret_pct"].mean(),
        })
    return pd.DataFrame(rows)


def signal_test(records: pd.DataFrame, gap_threshold_pct: float = 0.5) -> pd.DataFrame:
    """For days with |gap|>=threshold: split by sign(d_open) and compare returns.

    sign(d_open) > 0 ==> SPY's PO is HIGHER than SPX's at open. After a gap, that
    means SPY looks 'more bullish/less bearish' than SPX (because SPY's pre-mkt
    bars cushioned the EMA shift and the gap surprise hits SPX harder).
    """
    g = records[records["abs_gap_pct"] >= gap_threshold_pct].copy()

    def cohort(name, sub):
        if len(sub) == 0:
            return None
        return {
            "cohort": name,
            "n": len(sub),
            "median_gap_pct": sub["gap_pct"].median(),
            "median_d_open": sub["d_open"].median(),
            "mean_morning_ret_pct": sub["spy_morning_ret_pct"].mean(),
            "median_morning_ret_pct": sub["spy_morning_ret_pct"].median(),
            "morning_up_rate_pct": (sub["spy_morning_ret_pct"] > 0).mean() * 100,
            "mean_afternoon_ret_pct": sub["spy_afternoon_ret_pct"].mean(),
            "median_afternoon_ret_pct": sub["spy_afternoon_ret_pct"].median(),
            "afternoon_up_rate_pct": (sub["spy_afternoon_ret_pct"] > 0).mean() * 100,
            "mean_full_ret_pct": sub["spy_full_ret_pct"].mean(),
            "median_full_ret_pct": sub["spy_full_ret_pct"].median(),
        }

    rows = []
    # Split by gap direction first, then by which side has higher PO at open.
    for gap_dir, gsel in (("gap_up", g[g["gap_pct"] > 0]), ("gap_dn", g[g["gap_pct"] < 0])):
        for d_sign, dsel_name in ((1, "SPY_PO_higher_than_SPX"),
                                  (-1, "SPX_PO_higher_than_SPY")):
            sub = gsel[np.sign(gsel["d_open"]) == d_sign]
            r = cohort(f"|gap|>={gap_threshold_pct}% & {gap_dir} & {dsel_name}", sub)
            if r:
                rows.append(r)
    return pd.DataFrame(rows)


def convergence_decomposition(records: pd.DataFrame, gap_threshold_pct: float = 0.5) -> pd.DataFrame:
    """How much of the open->EOD gap closure was driven by SPY vs SPX movement?

    closure_by_spy = -sign(d_open) * dpo_spy_full   (positive => SPY moved toward SPX)
    closure_by_spx =  sign(d_open) * dpo_spx_full   (positive => SPX moved toward SPY)
    "dominance" = sign of (closure_by_spx - closure_by_spy)
        > 0  => SPX moved more toward closing the gap   (SPX 'caught up to' SPY)
        < 0  => SPY moved more toward closing the gap   (SPY 'caught down to' SPX)
    """
    g = records[records["abs_gap_pct"] >= gap_threshold_pct].copy()
    if g.empty:
        return pd.DataFrame()
    sign_open = np.sign(g["d_open"])
    g["closure_by_spy"] = -sign_open * g["dpo_spy_full"]
    g["closure_by_spx"] =  sign_open * g["dpo_spx_full"]
    g["spx_dominant_closure"] = (g["closure_by_spx"] > g["closure_by_spy"]).astype(int)

    # Cohort returns by who-closed-the-gap, separately for gap-up vs gap-down days.
    rows = []
    for gap_dir, gsel in (("gap_up", g[g["gap_pct"] > 0]), ("gap_dn", g[g["gap_pct"] < 0])):
        for label, sub in (
            ("SPX closed the gap (SPX moved toward SPY)", gsel[gsel["spx_dominant_closure"] == 1]),
            ("SPY closed the gap (SPY moved toward SPX)", gsel[gsel["spx_dominant_closure"] == 0]),
        ):
            if len(sub) == 0:
                continue
            rows.append({
                "regime": f"|gap|>={gap_threshold_pct}% & {gap_dir} & {label}",
                "n": len(sub),
                "median_gap_pct": sub["gap_pct"].median(),
                "median_closure_by_spy": sub["closure_by_spy"].median(),
                "median_closure_by_spx": sub["closure_by_spx"].median(),
                "mean_morning_ret_pct": sub["spy_morning_ret_pct"].mean(),
                "morning_up_rate_pct": (sub["spy_morning_ret_pct"] > 0).mean() * 100,
                "mean_afternoon_ret_pct": sub["spy_afternoon_ret_pct"].mean(),
                "afternoon_up_rate_pct": (sub["spy_afternoon_ret_pct"] > 0).mean() * 100,
                "mean_full_ret_pct": sub["spy_full_ret_pct"].mean(),
            })
    return pd.DataFrame(rows)


def ribbon_signal_test(records: pd.DataFrame, gap_threshold_pct: float = 0.5) -> pd.DataFrame:
    """Conditional return distributions for fast-cloud mismatch days at open."""
    g = records[records["abs_gap_pct"] >= gap_threshold_pct].copy()
    rows = []
    for label, mask in [
        ("SPY_fast_bull & SPX_fast_bear",
         (g["fast_spy_bull_open"] == 1) & (g["fast_spx_bull_open"] == 0)),
        ("SPY_fast_bear & SPX_fast_bull",
         (g["fast_spy_bull_open"] == 0) & (g["fast_spx_bull_open"] == 1)),
        ("Both_fast_bull",
         (g["fast_spy_bull_open"] == 1) & (g["fast_spx_bull_open"] == 1)),
        ("Both_fast_bear",
         (g["fast_spy_bull_open"] == 0) & (g["fast_spx_bull_open"] == 0)),
    ]:
        sub = g[mask]
        if len(sub) == 0:
            continue
        rows.append({
            "regime": label,
            "n": len(sub),
            "median_gap_pct": sub["gap_pct"].median(),
            "mean_morning_ret_pct": sub["spy_morning_ret_pct"].mean(),
            "morning_up_rate_pct": (sub["spy_morning_ret_pct"] > 0).mean() * 100,
            "mean_afternoon_ret_pct": sub["spy_afternoon_ret_pct"].mean(),
            "afternoon_up_rate_pct": (sub["spy_afternoon_ret_pct"] > 0).mean() * 100,
            "mean_full_ret_pct": sub["spy_full_ret_pct"].mean(),
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 78)
    print("SPX vs SPY morning divergence study (10m PO + Pivot Ribbon)")
    print("=" * 78)

    spx = load_spx_10m_with_indicators()
    spy = load_spy_10m_rth(start_date=spx.index.min().date())
    prev_close_by_date = load_spy_prev_rth_close()
    # We want PRIOR-day RTH close, so build a shifted lookup keyed by *next* date.
    daily_idx = sorted(prev_close_by_date.index)
    next_day_close = {}
    for i in range(1, len(daily_idx)):
        next_day_close[daily_idx[i]] = float(prev_close_by_date.loc[daily_idx[i - 1]])

    # Iterate by date
    spy_by_date = dict(tuple(spy.groupby("date", sort=True)))
    spx_by_date = dict(tuple(spx.groupby("date", sort=True)))
    common_dates = sorted(set(spy_by_date.keys()) & set(spx_by_date.keys()))
    print(f"[study] {len(common_dates):,} common RTH dates")

    records = []
    skipped = 0
    for d in common_dates:
        prev_close = next_day_close.get(d)
        if prev_close is None:
            skipped += 1
            continue
        rec = per_day_record(d, spy_by_date[d], spx_by_date[d], prev_close)
        if rec is None:
            skipped += 1
            continue
        records.append(rec)

    print(f"[study] retained {len(records):,} day records (skipped {skipped})")
    if not records:
        print("ERROR: no records produced")
        sys.exit(1)

    df = pd.DataFrame(records)
    df["gap_bin"] = df["abs_gap_pct"].apply(gap_bin)

    # Drop the very-earliest part where indicator EMAs are still warming up.
    # Keep records with at least 200 prior 10m bars of warmup -> drop first 5 days.
    first_5 = sorted(df["date"].unique())[:5]
    df = df[~df["date"].isin(first_5)].copy()

    daily_csv = OUT / "spx_spy_divergence_summary.csv"
    df.to_csv(daily_csv, index=False)
    print(f"[study] wrote {daily_csv}  ({len(df):,} rows)")

    bin_summary = aggregate_summary(df)
    bin_csv = OUT / "spx_spy_divergence_by_gap.csv"
    bin_summary.to_csv(bin_csv, index=False)
    print(f"[study] wrote {bin_csv}")

    print("\n=== Open divergence and convergence by |gap| bin ===")
    print(bin_summary.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))

    print("\n=== Signal test: |gap| >= 0.5%, sign(d_open) cohorts ===")
    sig_05 = signal_test(df, gap_threshold_pct=0.5)
    print(sig_05.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    sig_05.to_csv(OUT / "spx_spy_divergence_signal_05.csv", index=False)

    print("\n=== Signal test: |gap| >= 1.0%, sign(d_open) cohorts ===")
    sig_10 = signal_test(df, gap_threshold_pct=1.0)
    print(sig_10.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    sig_10.to_csv(OUT / "spx_spy_divergence_signal_10.csv", index=False)

    print("\n=== Convergence decomposition: |gap| >= 0.5%, who closed the PO gap? ===")
    conv_05 = convergence_decomposition(df, gap_threshold_pct=0.5)
    print(conv_05.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    conv_05.to_csv(OUT / "spx_spy_divergence_convergence_05.csv", index=False)

    print("\n=== Convergence decomposition: |gap| >= 1.0% ===")
    conv_10 = convergence_decomposition(df, gap_threshold_pct=1.0)
    print(conv_10.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    conv_10.to_csv(OUT / "spx_spy_divergence_convergence_10.csv", index=False)

    print("\n=== Ribbon mismatch test: |gap| >= 0.5%, fast-cloud regimes ===")
    rib_05 = ribbon_signal_test(df, gap_threshold_pct=0.5)
    print(rib_05.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    rib_05.to_csv(OUT / "spx_spy_divergence_ribbon_05.csv", index=False)

    print("\n=== Overall sample ===")
    print(f"  rows: {len(df):,}")
    print(f"  date range: {df['date'].min()} .. {df['date'].max()}")
    print(f"  median |d_open| (PO units): {df['abs_d_open'].median():.2f}")
    print(f"  90th pct |d_open|:          {df['abs_d_open'].quantile(0.9):.2f}")
    print(f"  95th pct |d_open|:          {df['abs_d_open'].quantile(0.95):.2f}")
    print(f"  fast-cloud mismatch rate at open: {(1 - df['fast_match_open']).mean() * 100:.1f}%")
    print(f"  slow-cloud mismatch rate at open: {(1 - df['slow_match_open']).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()

"""
Multiday Put Trigger Reversion Study

Setup:
  For each trading week W, SPY's multiday put trigger is computed from the
  prior completed weekly bar (close of W-1 + weekly ATR14 of W-1) exactly
  per Saty's pine spec with period_index=1.

Question:
  After SPY first taps the multiday put trigger within week W, which side
  resolves first?
  - Reclaim pivot (prior weekly close, the 0% level), then continuation to
    multiday call trigger (+23.6%) and upside GG open (+38.2%)?
  - Break the downside GG open (-38.2%)?

  All outcomes must resolve within the same week W.

Controls:
  - All-weeks base rate: on every week, P(pivot hit | no pre-tap condition)
  - Non-tap weeks: weeks where put trigger is never tapped
  - Near-tap weeks: weeks where price comes within 0.1 ATR of put trigger
    but never touches it (cleanest counterfactual per codex review)

Regime filters (all use LAST COMPLETED period values to avoid lookahead):
  - Weekly PO zone x slope at start of week W (from weekly bar W-1)
  - Quarterly position ATR context: distance from quarterly pivot / trigger

Key methodology points:
  - Levels for week W are recomputed from week W-1 close + week W-1 ATR14,
    NOT from ind_1w.atr_lower_trigger (which combines prev_close with
    current-row ATR -- a subtle lookahead the repo-wide pipeline inherits).
  - 1-minute RTH bars resolve the level race.
  - Downside stop counted from the tap bar itself.
  - Upside recovery counted from bars after the tap bar (avoids same-minute
    ambiguity).
  - Trading-week keys use ISO week of the bar's date, with Monday-Friday
    membership determined by the weekly candle timestamp.

Tap cohorts:
  - intraweek_cross: price crosses DOWN into put trigger during week W
    (tradable; long entry at the trigger)
  - opened_below_trigger: week W opens already at or below put trigger
    (separate cohort; long entry would be at Monday open)
  - opened_below_dgg: week W opens at or below downside GG (-38.2%);
    no clean long entry possible (gap-through-stop)
"""

import os
import sqlite3
import sys

os.environ.setdefault("PANDAS_USE_NUMEXPR", "0")
os.environ.setdefault("PANDAS_USE_BOTTLENECK", "0")
sys.modules.setdefault("numexpr", None)
sys.modules.setdefault("bottleneck", None)

import json
from collections import defaultdict

import numpy as np
import pandas as pd


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
OUTPUT_CSV = os.path.join(BASE_DIR, "multiday_put_trigger_reversion_events.csv")
OUTPUT_JSON = os.path.join(BASE_DIR, "multiday_put_trigger_reversion_results.json")

TRIGGER_PCT = 0.236
GG_OPEN_PCT = 0.382
NEAR_TAP_ATR_BUFFER = 0.10  # within 0.10 ATR of put trigger but never touched


# ──────────────────────────────────────────────────────────────────────────
# Indicator computations (Saty-spec, verbatim)
# ──────────────────────────────────────────────────────────────────────────

def wilder_atr(df, length=14):
    """ATR using RMA (Wilder's smoothing) to match TradingView ta.atr().

    TV seeds the first valid value with an SMA of the first `length` TRs,
    then applies RMA = (prev*(length-1) + tr) / length. `ewm(adjust=False)`
    alone uses TR[0] as seed, which drifts early. Seed explicitly.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = pd.Series(np.nan, index=df.index)
    # First `length` TRs have no prev_close for the very first row; start
    # the SMA window at index 1.
    if len(tr) <= length:
        return atr
    # Seed: SMA of TR[1..length] (skip row 0 which has NaN prev_close)
    seed = tr.iloc[1 : length + 1].mean()
    atr.iloc[length] = seed
    alpha = 1.0 / length
    prev = seed
    for i in range(length + 1, len(tr)):
        prev = prev * (1 - alpha) + tr.iloc[i] * alpha
        atr.iloc[i] = prev
    return atr


def ema(series, length):
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def compute_phase_oscillator(df):
    """Saty PO: EMA(((close - EMA21) / (3 * ATR14)) * 100, 3).

    Computed on the same timeframe df is on.
    """
    atr14 = wilder_atr(df, 14)
    ema21 = ema(df["close"], 21)
    raw = ((df["close"] - ema21) / (3.0 * atr14)) * 100.0
    po = raw.ewm(span=3, adjust=False, min_periods=3).mean()
    return po


def classify_po(po_val, po_prev):
    """Return (zone, slope, bilbo_label) using Saty's ±61.8 zone cutoff."""
    if pd.isna(po_val) or pd.isna(po_prev):
        return None, None, None
    if po_val > 61.8:
        zone = "high"
    elif po_val < -61.8:
        zone = "low"
    else:
        zone = "mid"
    slope = "rising" if po_val > po_prev else "falling"
    # Bilbo convention from export_study_dates.py / server.py
    if zone == "high" and slope == "rising":
        bilbo = "bull_bilbo"
    elif zone == "low" and slope == "falling":
        bilbo = "bear_bilbo"
    else:
        bilbo = f"{zone}_{slope}"
    return zone, slope, bilbo


# ──────────────────────────────────────────────────────────────────────────
# Weekly level computation (the fix — matches Saty period_index=1)
# ──────────────────────────────────────────────────────────────────────────

def build_weekly_levels(weekly_candles):
    """For each weekly bar W, the LEVELS applicable during week W are derived
    from week W-1's close and week W-1's ATR14.

    Returns a DataFrame indexed by week-start timestamp, with:
      - prev_close, prev_atr14  (the two Saty inputs, from W-1)
      - put_trigger, call_trigger, dgg_open, ugg_open, pivot
      - po_prev_period (weekly PO of W-1; used as the "PO at start of W")
      - po_slope_prev (True if W-1 PO > W-2 PO)
    """
    w = weekly_candles.copy()
    w["atr14"] = wilder_atr(w, 14)
    w["po"] = compute_phase_oscillator(w)

    # Shift so week W's row carries W-1's anchor values
    w["prev_close"] = w["close"].shift(1)
    w["prev_atr14"] = w["atr14"].shift(1)
    w["po_prev_period"] = w["po"].shift(1)
    w["po_prev_prev"] = w["po"].shift(2)

    w["pivot"] = w["prev_close"]
    w["put_trigger"] = w["prev_close"] - TRIGGER_PCT * w["prev_atr14"]
    w["call_trigger"] = w["prev_close"] + TRIGGER_PCT * w["prev_atr14"]
    w["dgg_open"] = w["prev_close"] - GG_OPEN_PCT * w["prev_atr14"]
    w["ugg_open"] = w["prev_close"] + GG_OPEN_PCT * w["prev_atr14"]

    w = w.dropna(subset=["prev_close", "prev_atr14"])
    return w


def build_quarterly_context(daily_candles):
    """Aggregate DAILY candles into quarterly candles, compute quarterly ATR
    and levels from prior quarter's close + ATR.

    Using daily candles (not weekly) ensures quarter boundaries align to
    calendar quarter-end daily closes — not to the Sunday-stamped weekly
    bar that most recently preceded the quarter start.

    Returns a DataFrame indexed by quarter-start, with prev_close, prev_atr14,
    and the Saty quarterly (Position) trigger/GG levels.
    """
    d = daily_candles.copy()
    d.index = pd.to_datetime(d.index)

    q = pd.DataFrame({
        "open": d["open"].resample("QS").first(),
        "high": d["high"].resample("QS").max(),
        "low": d["low"].resample("QS").min(),
        "close": d["close"].resample("QS").last(),
    }).dropna()

    q["atr14"] = wilder_atr(q, 14)
    q["prev_close"] = q["close"].shift(1)
    q["prev_atr14"] = q["atr14"].shift(1)
    q["q_pivot"] = q["prev_close"]
    q["q_put_trigger"] = q["prev_close"] - TRIGGER_PCT * q["prev_atr14"]
    q["q_call_trigger"] = q["prev_close"] + TRIGGER_PCT * q["prev_atr14"]
    q["q_dgg_open"] = q["prev_close"] - GG_OPEN_PCT * q["prev_atr14"]
    q["q_ugg_open"] = q["prev_close"] + GG_OPEN_PCT * q["prev_atr14"]
    return q.dropna(subset=["prev_close", "prev_atr14"])


def locate_in_q_band(price, q_row):
    """Classify where a price sits relative to quarterly levels."""
    if price <= q_row["q_dgg_open"]:
        return "below_q_dgg"
    if price <= q_row["q_put_trigger"]:
        return "q_put_to_dgg"
    if price <= q_row["q_pivot"]:
        return "q_pivot_to_put"
    if price <= q_row["q_call_trigger"]:
        return "q_pivot_to_call"
    if price <= q_row["q_ugg_open"]:
        return "q_call_to_ugg"
    return "above_q_ugg"


# ──────────────────────────────────────────────────────────────────────────
# 1m data load (RTH only)
# ──────────────────────────────────────────────────────────────────────────

def load_1m_rth(conn):
    query = """
        SELECT timestamp, open, high, low, close
        FROM candles_1m
        WHERE substr(timestamp, 12, 8) BETWEEN '09:30:00' AND '15:59:59'
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    # Wick clip matching aggregate.py — phantom prints like the 2025-07-03
    # 581.81 low are counted as false taps without this.
    body_high = np.maximum(df["open"], df["close"])
    body_low = np.minimum(df["open"], df["close"])
    df["high"] = np.minimum(df["high"], body_high * 1.02)
    df["low"] = np.maximum(df["low"], body_low * 0.98)
    df["week_end"] = df.index.to_period("W-FRI").end_time.normalize()
    return df


def load_weekly_candles(conn):
    query = "SELECT timestamp, open, high, low, close FROM candles_1w ORDER BY timestamp"
    w = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    w = w.set_index("timestamp").sort_index()
    return w


def load_daily_candles(conn):
    query = "SELECT timestamp, open, high, low, close FROM candles_1d ORDER BY timestamp"
    d = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    d = d.set_index("timestamp").sort_index()
    return d


# ──────────────────────────────────────────────────────────────────────────
# Event detection
# ──────────────────────────────────────────────────────────────────────────

def first_time(frame, mask):
    hits = frame[mask.values]
    if len(hits) == 0:
        return None
    return hits.index[0]


def analyze_week(week_df, levels_row, q_row):
    """Return an event dict for this week, or None if week has no usable data."""
    if len(week_df) == 0:
        return None

    pivot = levels_row["pivot"]
    put_trig = levels_row["put_trigger"]
    call_trig = levels_row["call_trigger"]
    dgg = levels_row["dgg_open"]
    ugg = levels_row["ugg_open"]
    prev_atr = levels_row["prev_atr14"]

    first_bar = week_df.iloc[0]
    open_price = first_bar["open"]
    week_low = week_df["low"].min()
    week_high = week_df["high"].max()

    # Cohort determination
    if open_price <= dgg:
        cohort = "opened_below_dgg"
    elif open_price <= put_trig:
        cohort = "opened_below_trigger"
    elif week_low <= put_trig:
        # Check if the first tap bar actually printed the trigger price,
        # or gap-dumped below it. For a tradable long-at-trigger entry we
        # need the tap bar's range to contain put_trigger (low<=put<=high).
        tap_mask = week_df["low"] <= put_trig
        tap_bar = week_df[tap_mask.values].iloc[0]
        if tap_bar["high"] < put_trig:
            # Bar gapped below trigger without ever trading at or above it.
            # The trigger fill didn't print — this is a gap-through, not a
            # clean cross. Separate cohort, entry at bar open.
            cohort = "gap_through_cross"
        else:
            cohort = "intraweek_cross"
    else:
        cohort = "non_tap"

    # Tap timestamp / entry price
    if cohort == "intraweek_cross":
        tap_time = first_time(week_df, week_df["low"] <= put_trig)
        tap_price = put_trig  # entry fills at trigger price
    elif cohort == "gap_through_cross":
        tap_mask2 = week_df["low"] <= put_trig
        tap_bar = week_df[tap_mask2.values].iloc[0]
        tap_time = tap_bar.name
        # Conservative: entry fills at bar open (worse than trigger)
        tap_price = float(tap_bar["open"])
    elif cohort in ("opened_below_trigger", "opened_below_dgg"):
        tap_time = week_df.index[0]
        tap_price = open_price
    else:
        tap_time = None
        tap_price = None

    # Level race
    dgg_time = pivot_time = call_time = ugg_time = None
    outcome = "no_tap"
    max_adverse_excursion_atr = np.nan
    max_favorable_excursion_atr = np.nan

    if cohort != "non_tap":
        from_tap = week_df[week_df.index >= tap_time]
        after_tap = week_df[week_df.index > tap_time]

        # Downside stop: count from the tap bar itself
        dgg_time = first_time(from_tap, from_tap["low"] <= dgg)

        # Upside recovery: only bars AFTER the tap bar
        if len(after_tap):
            pivot_time = first_time(after_tap, after_tap["high"] >= pivot)
            call_time = first_time(after_tap, after_tap["high"] >= call_trig)
            ugg_time = first_time(after_tap, after_tap["high"] >= ugg)

        # MAE from entry downward in ATR units
        lowest = from_tap["low"].min()
        max_adverse_excursion_atr = (tap_price - lowest) / prev_atr if prev_atr else np.nan
        if len(after_tap):
            highest = after_tap["high"].max()
            max_favorable_excursion_atr = (highest - tap_price) / prev_atr if prev_atr else np.nan

        # Outcome classification (path-dependent race).
        # Every upside target must beat dgg_time to count as a live win
        # (i.e. the stop must not have triggered first).
        def beats_dgg(t):
            return t is not None and (dgg_time is None or t < dgg_time)

        if cohort == "opened_below_dgg":
            outcome = "gap_through_stop"
        elif dgg_time is not None and (pivot_time is None or dgg_time < pivot_time):
            outcome = "breakdown"
        elif pivot_time is not None:
            live_call = beats_dgg(call_time)
            live_ugg = beats_dgg(ugg_time)
            if not live_call:
                outcome = "reversion_only"
            elif not live_ugg:
                outcome = "continuation"
            else:
                outcome = "full_rotation"
        else:
            outcome = "no_resolution"

    # Weekly PO state at start of week (last completed weekly PO)
    zone_w, slope_w, bilbo_w = classify_po(
        levels_row.get("po_prev_period"),
        levels_row.get("po_prev_prev"),
    )

    # Quarterly position context (where does the put trigger sit within
    # the quarterly band? where does the tap price sit?)
    q_band_at_trigger = q_band_at_tap = None
    if q_row is not None and not pd.isna(q_row.get("q_pivot")):
        q_band_at_trigger = locate_in_q_band(put_trig, q_row)
        if tap_price is not None:
            q_band_at_tap = locate_in_q_band(tap_price, q_row)

    # Trading week ends on the Friday before the Sunday-stamped weekly bar
    trading_week_end = (levels_row.name - pd.Timedelta(days=2)).date()
    return {
        "trading_week_end": str(trading_week_end),
        "weekly_bar_ts": str(levels_row.name.date()),
        "cohort": cohort,
        "outcome": outcome,
        "open": float(open_price),
        "prev_close": float(levels_row["prev_close"]),
        "prev_atr14": float(prev_atr),
        "put_trigger": float(put_trig),
        "pivot": float(pivot),
        "call_trigger": float(call_trig),
        "dgg_open": float(dgg),
        "ugg_open": float(ugg),
        "week_low": float(week_low),
        "week_high": float(week_high),
        "tap_time": str(tap_time) if tap_time is not None else None,
        "tap_price": float(tap_price) if tap_price is not None else None,
        "pivot_time": str(pivot_time) if pivot_time is not None else None,
        "call_time": str(call_time) if call_time is not None else None,
        "ugg_time": str(ugg_time) if ugg_time is not None else None,
        "dgg_time": str(dgg_time) if dgg_time is not None else None,
        "mae_atr": float(max_adverse_excursion_atr) if not pd.isna(max_adverse_excursion_atr) else None,
        "mfe_atr": float(max_favorable_excursion_atr) if not pd.isna(max_favorable_excursion_atr) else None,
        "po_weekly_prev": float(levels_row["po_prev_period"]) if not pd.isna(levels_row.get("po_prev_period")) else None,
        "po_weekly_zone": zone_w,
        "po_weekly_slope": slope_w,
        "po_weekly_bilbo": bilbo_w,
        "q_band_at_trigger": q_band_at_trigger,
        "q_band_at_tap": q_band_at_tap,
    }


# ──────────────────────────────────────────────────────────────────────────
# Reporting helpers
# ──────────────────────────────────────────────────────────────────────────

def pct(n, d):
    return n / d * 100 if d else 0.0


def pct_s(n, d):
    return f"{pct(n, d):5.1f}%" if d else "  n/a"


def _near_tap_mask(events_df, atr_col="prev_atr14"):
    """Mask for weeks where price came within NEAR_TAP_ATR_BUFFER ATR of put
    trigger but never touched. Non-tap cohort only."""
    non_tap = events_df["cohort"] == "non_tap"
    low_minus_trigger_atr = (
        events_df["week_low"] - events_df["put_trigger"]
    ) / events_df[atr_col]
    return non_tap & (low_minus_trigger_atr <= NEAR_TAP_ATR_BUFFER)


def print_cohort_funnel(events_df):
    print("\n" + "=" * 78)
    print("COHORT FUNNEL")
    print("=" * 78)
    total_weeks = len(events_df)
    for cohort in ["intraweek_cross", "gap_through_cross", "opened_below_trigger", "opened_below_dgg", "non_tap"]:
        sub = events_df[events_df["cohort"] == cohort]
        print(f"  {cohort:<24s} n={len(sub):5d}  ({pct_s(len(sub), total_weeks)})")

    near = events_df[_near_tap_mask(events_df)]
    print(f"  {'  of which near-tap:':<24s} n={len(near):5d} (within {NEAR_TAP_ATR_BUFFER:.2f} ATR of put trigger)")


def print_outcome_table(events_df, label, cohort_filter=None):
    if cohort_filter is not None:
        sub = events_df[events_df["cohort"] == cohort_filter]
    else:
        sub = events_df[events_df["cohort"].isin(["intraweek_cross", "opened_below_trigger"])]

    n = len(sub)
    print(f"\n{label}  (n={n})")
    print("-" * len(label))
    if n == 0:
        return

    outcomes = ["breakdown", "no_resolution", "reversion_only", "continuation", "full_rotation", "gap_through_stop"]
    for o in outcomes:
        c = int((sub["outcome"] == o).sum())
        print(f"  {o:<22s} {c:5d}/{n:<5d}  {pct_s(c, n)}")

    # Funnel probabilities
    tapped = sub[sub["outcome"] != "gap_through_stop"]
    nt = len(tapped)
    if nt == 0:
        return
    reached_pivot = (tapped["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum()
    reached_call = (tapped["outcome"].isin(["continuation", "full_rotation"])).sum()
    reached_ugg = (tapped["outcome"] == "full_rotation").sum()
    breakdowns = (tapped["outcome"] == "breakdown").sum()
    print(f"\n  Probability funnel (after tap; gap_through_stop excluded):")
    print(f"    P(pivot before dgg | tap)      {pct_s(reached_pivot, nt)}  ({reached_pivot}/{nt})")
    print(f"    P(call trig | pivot reclaimed) {pct_s(reached_call, reached_pivot)}  ({reached_call}/{reached_pivot})")
    print(f"    P(ugg | call trig)             {pct_s(reached_ugg, reached_call)}  ({reached_ugg}/{reached_call})")
    print(f"    Joint P(full rotation | tap)   {pct_s(reached_ugg, nt)}  ({reached_ugg}/{nt})")
    print(f"    P(breakdown | tap)             {pct_s(breakdowns, nt)}  ({breakdowns}/{nt})")


def print_control_comparison(events_df):
    print("\n" + "=" * 78)
    print("CONTROL COMPARISON")
    print("=" * 78)

    # Main tradable cohort (intraweek_cross only — cleanest entry)
    tap = events_df[events_df["cohort"] == "intraweek_cross"]

    # Non-tap: weeks where trigger never touched. For these we compute the
    # analogous probability: did price reach pivot+23.6%*ATR (call trigger)
    # from the week's minimum point? This is a rough analog since we don't
    # have a trigger event; we report it as "baseline rate that price makes
    # a call-trigger-equivalent move starting from the week low."
    non_tap = events_df[events_df["cohort"] == "non_tap"]
    near_tap = events_df[_near_tap_mask(events_df)]

    print(f"\n  TAP cohort (intraweek_cross): n={len(tap)}")
    if len(tap):
        rev = (tap["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum()
        full = (tap["outcome"] == "full_rotation").sum()
        print(f"    P(pivot | tap)        {pct_s(rev, len(tap))}")
        print(f"    P(full rotation | tap){pct_s(full, len(tap))}")

    # For controls: how often did the non-tap week's HIGH exceed the week's pivot?
    # (trivially near 100% since pivot = prev close) — so the better control is
    # how often did the week even test downside at all?
    for name, sub in [("all weeks", events_df), ("non_tap weeks", non_tap), ("near_tap weeks", near_tap)]:
        n = len(sub)
        if n == 0:
            continue
        # "Reached pivot" is trivially true for all non-tap weeks (price is
        # already at/above pivot coming in). The meaningful control is how
        # often price reached the CALL trigger.
        reached_call = (sub["week_high"] >= sub["call_trigger"]).sum()
        reached_ugg = (sub["week_high"] >= sub["ugg_open"]).sum()
        print(f"\n  {name}: n={n}")
        print(f"    Weeks hitting call trigger: {pct_s(reached_call, n)}")
        print(f"    Weeks hitting ugg open:     {pct_s(reached_ugg, n)}")


def print_weekly_po_regime(events_df):
    print("\n" + "=" * 78)
    print("WEEKLY PO REGIME AT START OF WEEK (tap cohort only)")
    print("=" * 78)
    tap = events_df[events_df["cohort"].isin(["intraweek_cross", "opened_below_trigger"])]
    if len(tap) == 0:
        return

    keys = ["bull_bilbo", "bear_bilbo", "mid_rising", "mid_falling",
            "high_falling", "low_rising"]
    print(f"  {'PO bilbo state':<20s} {'N':>5s} {'P(pivot)':>10s} {'P(call)':>10s} {'P(ugg)':>10s}  {'P(breakdown)':>14s}")
    for k in keys:
        sub = tap[tap["po_weekly_bilbo"] == k]
        n = len(sub)
        if n == 0:
            continue
        flag = " " if n >= 20 else "*"
        rev = (sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum()
        call = (sub["outcome"].isin(["continuation", "full_rotation"])).sum()
        ugg = (sub["outcome"] == "full_rotation").sum()
        bd = (sub["outcome"] == "breakdown").sum()
        print(f"  {k:<20s} {n:5d}{flag}{pct_s(rev, n):>10s} {pct_s(call, n):>10s} {pct_s(ugg, n):>10s}  {pct_s(bd, n):>14s}")
    print("  * n < 20 (small sample)")


def print_quarterly_regime(events_df):
    print("\n" + "=" * 78)
    print("QUARTERLY POSITION ATR BAND (where put trigger sits in quarterly range)")
    print("=" * 78)
    tap = events_df[events_df["cohort"].isin(["intraweek_cross", "opened_below_trigger"])]
    if len(tap) == 0:
        return

    order = ["above_q_ugg", "q_call_to_ugg", "q_pivot_to_call", "q_pivot_to_put",
             "q_put_to_dgg", "below_q_dgg"]
    print(f"  {'Q band':<20s} {'N':>5s} {'P(pivot)':>10s} {'P(call)':>10s} {'P(ugg)':>10s}  {'P(breakdown)':>14s}")
    for k in order:
        sub = tap[tap["q_band_at_trigger"] == k]
        n = len(sub)
        if n == 0:
            continue
        flag = " " if n >= 20 else "*"
        rev = (sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum()
        call = (sub["outcome"].isin(["continuation", "full_rotation"])).sum()
        ugg = (sub["outcome"] == "full_rotation").sum()
        bd = (sub["outcome"] == "breakdown").sum()
        print(f"  {k:<20s} {n:5d}{flag}{pct_s(rev, n):>10s} {pct_s(call, n):>10s} {pct_s(ugg, n):>10s}  {pct_s(bd, n):>14s}")
    print("  * n < 20 (small sample)")


def print_decade_splits(events_df):
    print("\n" + "=" * 78)
    print("DECADE SPLITS (tap cohort)")
    print("=" * 78)
    tap = events_df[events_df["cohort"].isin(["intraweek_cross", "opened_below_trigger"])].copy()
    if len(tap) == 0:
        return
    tap["year"] = pd.to_datetime(tap["trading_week_end"]).dt.year
    tap["decade"] = (tap["year"] // 10) * 10

    print(f"  {'Decade':<10s} {'N':>5s} {'P(pivot)':>10s} {'P(call)':>10s} {'P(ugg)':>10s}  {'P(breakdown)':>14s}")
    for decade, sub in tap.groupby("decade"):
        n = len(sub)
        rev = (sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum()
        call = (sub["outcome"].isin(["continuation", "full_rotation"])).sum()
        ugg = (sub["outcome"] == "full_rotation").sum()
        bd = (sub["outcome"] == "breakdown").sum()
        print(f"  {decade:<10d} {n:5d} {pct_s(rev, n):>10s} {pct_s(call, n):>10s} {pct_s(ugg, n):>10s}  {pct_s(bd, n):>14s}")


def print_trade_pnl(events_df):
    """Simulate: long at put trigger tap, stop at dgg, ladder targets pivot
    / call trigger / ugg. Compute win rate and expectancy in R units.

    R = (tap_price - dgg) = 0.146 * prev_atr14 (difference between 23.6 and
    38.2 percent of ATR).
    """
    print("\n" + "=" * 78)
    print("TRADE SIMULATION — long at first tap, stop at dgg_open")
    print("=" * 78)
    tap = events_df[events_df["cohort"] == "intraweek_cross"]  # cleanest entry
    if len(tap) == 0:
        print("  No intraweek_cross events.")
        return

    # R per trade = 0.146 * prev_atr14 (from -23.6% to -38.2%)
    r_size_pct_atr = 0.382 - 0.236
    print(f"  Entry: put_trigger (-23.6% multiday ATR), Stop: dgg_open (-38.2%)")
    print(f"  1R = 0.146 * prev_atr14 ({r_size_pct_atr:.3f} ATR units)")
    print()

    # Three target ladders
    ladders = [
        ("T1 = pivot (0%)",        0.236 / 0.146),    # +1.62R
        ("T2 = call trig (+23.6%)", 0.472 / 0.146),   # +3.23R
        ("T3 = ugg open (+38.2%)",  0.618 / 0.146),   # +4.23R
    ]
    for name, rr in ladders:
        print(f"  {name:<28s} R:R = {rr:.2f}")

    # Compute outcomes for all-or-nothing targeting at each level.
    # Two expectancy views:
    #   (A) Conservative: no_resolution counts as -1R (full stop-out)
    #   (B) Time-stop: no_resolution events exit at Friday close — approximate
    #       with 0R (neither stopped nor target — pass-through).
    outcomes = tap["outcome"]
    n = len(tap)
    for ladder_name, ladder_rr, need_outcomes in [
        ("Target pivot only",   (0.236/0.146), ["reversion_only", "continuation", "full_rotation"]),
        ("Target call trigger", (0.472/0.146), ["continuation", "full_rotation"]),
        ("Target ugg open",     (0.618/0.146), ["full_rotation"]),
    ]:
        wins = int(outcomes.isin(need_outcomes).sum())
        unresolved = int((outcomes == "no_resolution").sum())
        stops = n - wins - unresolved
        win_rate = wins / n
        # Conservative: unresolved = -1R
        exp_cons = win_rate * ladder_rr - (stops / n) * 1.0 - (unresolved / n) * 1.0
        # Time-stop: unresolved = 0R
        exp_time = win_rate * ladder_rr - (stops / n) * 1.0
        print(f"\n  {ladder_name}  win={wins}/{n} ({win_rate*100:.1f}%) "
              f"stop={stops} unresolved={unresolved}  R:R={ladder_rr:.2f}")
        print(f"    exp (conservative, unresolved=-1R): {exp_cons:+.3f}R")
        print(f"    exp (time-stop, unresolved= 0R):    {exp_time:+.3f}R")


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    print("Loading 1m RTH data...", flush=True)
    conn = sqlite3.connect(DB_PATH)
    df = load_1m_rth(conn)
    print(f"  {len(df):,} 1m RTH bars")

    print("Loading weekly candles...", flush=True)
    weekly = load_weekly_candles(conn)
    print(f"  {len(weekly):,} weekly bars")

    print("Loading daily candles (for quarterly context)...", flush=True)
    daily = load_daily_candles(conn)
    conn.close()
    print(f"  {len(daily):,} daily bars")

    print("Computing weekly levels (Saty period_index=1 spec, recomputed)...")
    levels = build_weekly_levels(weekly)
    print(f"  {len(levels):,} weeks with complete anchor data")

    print("Computing quarterly (position) ATR context from daily candles...")
    q_levels = build_quarterly_context(daily)
    print(f"  {len(q_levels):,} quarters with complete anchor data")

    # Group 1m bars by week_end for level alignment
    print("Bucketing 1m bars by weekly period...")
    df_by_week = df.groupby("week_end", sort=True)

    # Prep weekly lookup: weekly candle timestamp (Sunday 00:00 in ind_1w)
    # is the END of that trading week. We need to map our 1m bars' week_end
    # (Friday) to the matching weekly row. The weekly bars use "W" period
    # convention where the stored timestamp is the week-start Sunday; the
    # trading activity for that week is the following Mon-Fri.
    # -> Use merge_asof on date to align.
    weekly_start_dates = levels.index.to_series()

    events = []
    print("Analyzing weeks...")
    # Weekly bar convention: timestamp is the SUNDAY after the trading week
    # ends. For trading week ending Friday F, the weekly bar timestamp is
    # F + 2 days (Sunday). The weekly bar's `prev_close` and `prev_atr14`
    # (built with shift(1)) are then the correct anchors for THAT trading
    # week, sourced from the PRIOR trading week's close.
    for week_end, week_df in df_by_week:
        target_date = pd.Timestamp(week_end).normalize()  # Friday of trading week
        # Look for the weekly bar whose timestamp falls on the weekend AFTER
        # this Friday (target_date + 1 to +3 days covers Sat/Sun/Mon-stamped
        # bars; most weekly bars in this DB are Sunday-stamped).
        forward = levels[
            (levels.index > target_date)
            & (levels.index <= target_date + pd.Timedelta(days=3))
        ]
        if len(forward) == 0:
            continue
        levels_row = forward.iloc[0]

        # Quarterly context at start of this week
        q_candidates = q_levels[q_levels.index <= target_date]
        q_row = q_candidates.iloc[-1] if len(q_candidates) else None

        event = analyze_week(week_df, levels_row, q_row)
        if event is not None:
            events.append(event)

    events_df = pd.DataFrame(events)
    events_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(events_df):,} events to {OUTPUT_CSV}")

    # ───────── Output ─────────
    print("\n" + "=" * 78)
    print("MULTIDAY PUT TRIGGER REVERSION — HEADLINE")
    print("=" * 78)
    print(f"Period: {events_df['trading_week_end'].min()} → {events_df['trading_week_end'].max()}")
    print(f"Total weeks analyzed: {len(events_df):,}")

    print_cohort_funnel(events_df)
    print_outcome_table(events_df, "Tradable cohort (intraweek_cross, clean fill)", cohort_filter="intraweek_cross")
    print_outcome_table(events_df, "Gap-through cross (bar opened below trigger intraweek)", cohort_filter="gap_through_cross")
    print_outcome_table(events_df, "Opened below put trigger (Monday gap)", cohort_filter="opened_below_trigger")
    print_outcome_table(events_df, "Opened below dgg (gap-through-stop)", cohort_filter="opened_below_dgg")

    print_control_comparison(events_df)
    print_weekly_po_regime(events_df)
    print_quarterly_regime(events_df)
    print_decade_splits(events_df)
    print_trade_pnl(events_df)

    # Write JSON results summary
    summary = build_summary(events_df)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved summary to {OUTPUT_JSON}")


def build_summary(events_df):
    """Structured JSON summary for downstream consumption."""
    summary = {
        "period": {
            "start": events_df["trading_week_end"].min(),
            "end": events_df["trading_week_end"].max(),
            "total_weeks": len(events_df),
        },
        "cohorts": {},
        "weekly_po_regime": {},
        "quarterly_band_regime": {},
        "decade_splits": {},
        "trade_simulation": {},
    }

    for cohort in ["intraweek_cross", "opened_below_trigger", "opened_below_dgg", "non_tap"]:
        sub = events_df[events_df["cohort"] == cohort]
        n = len(sub)
        counts = {o: int((sub["outcome"] == o).sum()) for o in sub["outcome"].unique()}
        summary["cohorts"][cohort] = {"n": n, "outcomes": counts}

    tap = events_df[events_df["cohort"] == "intraweek_cross"]
    if len(tap):
        pivot_n = int((tap["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum())
        call_n = int((tap["outcome"].isin(["continuation", "full_rotation"])).sum())
        ugg_n = int((tap["outcome"] == "full_rotation").sum())
        bd_n = int((tap["outcome"] == "breakdown").sum())
        summary["headline"] = {
            "n": len(tap),
            "p_pivot_before_dgg": pct(pivot_n, len(tap)),
            "p_call_given_pivot": pct(call_n, pivot_n),
            "p_ugg_given_call": pct(ugg_n, call_n),
            "p_full_rotation_given_tap": pct(ugg_n, len(tap)),
            "p_breakdown_given_tap": pct(bd_n, len(tap)),
        }

    for cohort in ["intraweek_cross", "opened_below_trigger"]:
        for bilbo, sub in events_df[events_df["cohort"] == cohort].groupby("po_weekly_bilbo"):
            n = len(sub)
            if n == 0:
                continue
            pivot_n = int((sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum())
            call_n = int((sub["outcome"].isin(["continuation", "full_rotation"])).sum())
            ugg_n = int((sub["outcome"] == "full_rotation").sum())
            bd_n = int((sub["outcome"] == "breakdown").sum())
            summary["weekly_po_regime"][f"{cohort}|{bilbo}"] = {
                "n": n,
                "p_pivot": pct(pivot_n, n),
                "p_call": pct(call_n, n),
                "p_ugg": pct(ugg_n, n),
                "p_breakdown": pct(bd_n, n),
            }

    for band, sub in events_df[events_df["cohort"] == "intraweek_cross"].groupby("q_band_at_trigger"):
        n = len(sub)
        if n == 0:
            continue
        pivot_n = int((sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum())
        full_n = int((sub["outcome"] == "full_rotation").sum())
        bd_n = int((sub["outcome"] == "breakdown").sum())
        summary["quarterly_band_regime"][str(band)] = {
            "n": n,
            "p_pivot": pct(pivot_n, n),
            "p_full_rotation": pct(full_n, n),
            "p_breakdown": pct(bd_n, n),
        }

    tap = events_df[events_df["cohort"] == "intraweek_cross"].copy()
    if len(tap):
        tap["year"] = pd.to_datetime(tap["trading_week_end"]).dt.year
        tap["decade"] = (tap["year"] // 10) * 10
        for decade, sub in tap.groupby("decade"):
            n = len(sub)
            pivot_n = int((sub["outcome"].isin(["reversion_only", "continuation", "full_rotation"])).sum())
            call_n = int((sub["outcome"].isin(["continuation", "full_rotation"])).sum())
            ugg_n = int((sub["outcome"] == "full_rotation").sum())
            bd_n = int((sub["outcome"] == "breakdown").sum())
            summary["decade_splits"][str(int(decade))] = {
                "n": n,
                "p_pivot": pct(pivot_n, n),
                "p_call": pct(call_n, n),
                "p_ugg": pct(ugg_n, n),
                "p_breakdown": pct(bd_n, n),
            }

        outcomes = tap["outcome"]
        n = len(tap)
        ladder_configs = [
            ("target_pivot",         0.236/0.146, ["reversion_only", "continuation", "full_rotation"]),
            ("target_call_trigger",  0.472/0.146, ["continuation", "full_rotation"]),
            ("target_ugg_open",      0.618/0.146, ["full_rotation"]),
        ]
        for name, rr, need in ladder_configs:
            wins = int(outcomes.isin(need).sum())
            unresolved = int((outcomes == "no_resolution").sum())
            stops = n - wins - unresolved
            exp_cons = (wins / n) * rr - (stops / n) - (unresolved / n)
            exp_time = (wins / n) * rr - (stops / n)
            summary["trade_simulation"][name] = {
                "n": n,
                "wins": wins,
                "stops": stops,
                "unresolved": unresolved,
                "r_per_win": rr,
                "win_rate_pct": wins / n * 100,
                "expectancy_R_conservative": exp_cons,
                "expectancy_R_time_stop": exp_time,
            }

    return summary


if __name__ == "__main__":
    main()

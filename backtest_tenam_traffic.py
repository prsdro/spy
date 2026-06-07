"""
TenAM Traffic — PO Divergence Backtest (3-minute SPY)
=====================================================

THE INDICATOR
-------------
"Traffic Signal PO Divergence" by TenAMTrader (TradingView).
On a chosen oscillator (Saty Phase Oscillator), it locates pivot highs/lows
and pairs them with the corresponding price extremes to flag four divergences:

    Regular Bullish (🟢): price LL + osc HL  → predicted reversal up
    Hidden  Bullish (🟡): price HL + osc LL  → predicted continuation up
    Regular Bearish (🔴): price HH + osc LH  → predicted reversal down
    Hidden  Bearish (🟡): price LH + osc HH  → predicted continuation down

Default Pine inputs (we mirror these):
    lbL = 1, lbR = 3          (pivot lookback)
    rangeLower = 0, rangeUpper = 60   (pivot must be within 0–60 bars of previous)
    Zone filters A and B OFF  (we test on/off as a cross-cut)


HYPOTHESIS
----------
On 3-minute SPY bars, divergence signals between price and the Saty Phase
Oscillator produce a tradable forward edge. Regular divergences should
produce a reversal beyond the local pivot extreme; hidden divergences
should produce continuation in the prevailing trend.


METHODOLOGY (key choices)
-------------------------
1.  Per-session pivot tracking. Pivots reset each RTH session — we do not
    carry pivots overnight. The 60-bar range filter would cut most cross-day
    pairs anyway, and overnight gaps make the comparison meaningless.

2.  Pine pivot semantics. ta.pivotlow(src, lbL=1, lbR=3) at bar `i` requires:
        osc[i] < osc[i-1]                     (1 bar left, strict)
        osc[i] < osc[i+1], osc[i+2], osc[i+3] (3 bars right, strict)
    The pivot is at bar `i` but is only confirmed at bar `i + lbR`. We
    treat the confirmation bar as the entry bar (close-of-bar entry) so
    the test does not look ahead.

3.  Forward outcomes. Measured from the close of the confirmation bar
    over 5/15/30/60 bars and to RTH close. We track:
       - MFE/MAE in dollars and as % of daily ATR(14)
       - Hit rate to fixed % targets
       - Hit rate to next ATR level in predicted direction
       - Stop-out: did price exceed the local pivot extreme after entry?
       - End-of-day directional bias

4.  Cross-cuts. Time-of-day half-hour buckets; PO zone at signal;
    Pivot Ribbon state (fast & slow cloud); ATR-level location of signal
    price; on/off application of the indicator's optional zone filters.

5.  Baseline. For each time-of-day bucket we compute the "random RTH 3m
    bar" baseline forward MFE / hit rate, so reported edge is signal vs
    base rate.


OUTPUT
------
Console summary tables plus a JSON event cache for downstream viz.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, asdict, field

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")

LB_L = 1
LB_R = 3
RANGE_UPPER = 60
RANGE_LOWER = 0

ZONE_A = (23.6, 61.8)
ZONE_B = (-61.8, -23.6)

FORWARD_WINDOWS = [5, 15, 30, 60]  # in 3-min bars (15, 45, 90, 180 minutes)
PCT_TARGETS = [0.10, 0.25, 0.50, 1.00]  # percent moves

# OCO bracket parameters (primary success metric)
BRACKET_STOP_DOLLAR = 0.50    # $0.50 against the signal = loss
BRACKET_PARTIAL_DOLLAR = 0.50  # $0.50 in direction = at least partial win
BRACKET_FULL_DOLLAR = 1.00     # $1.00 in direction = full win
BRACKET_MAX_BARS = 10          # 10 3-min bars (30 min) → wash


# ────────────────────────────────────────────────────────────────────────────
# Pivot detection
# ────────────────────────────────────────────────────────────────────────────

def detect_pivots(values: np.ndarray, left: int = LB_L, right: int = LB_R) -> tuple[np.ndarray, np.ndarray]:
    """
    Replicate Pine's ta.pivotlow / ta.pivothigh with strict inequality both sides.
    A pivot at index `i` requires it to be strictly less/greater than the `left`
    bars before it AND the `right` bars after it.

    Returns two boolean arrays (pivot_low, pivot_high) of the same length as values.
    Each True is at the pivot bar itself (NOT the confirmation bar).
    """
    n = len(values)
    is_low = np.zeros(n, dtype=bool)
    is_high = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        v = values[i]
        if np.isnan(v):
            continue
        # left side
        ok_low = True
        ok_high = True
        for j in range(i - left, i):
            w = values[j]
            if np.isnan(w):
                ok_low = ok_high = False
                break
            if not (v < w):
                ok_low = False
            if not (v > w):
                ok_high = False
            if not ok_low and not ok_high:
                break
        if not ok_low and not ok_high:
            continue
        # right side
        for j in range(i + 1, i + right + 1):
            w = values[j]
            if np.isnan(w):
                ok_low = ok_high = False
                break
            if not (v < w):
                ok_low = False
            if not (v > w):
                ok_high = False
            if not ok_low and not ok_high:
                break
        is_low[i] = ok_low
        is_high[i] = ok_high
    return is_low, is_high


# ────────────────────────────────────────────────────────────────────────────
# Signal record
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    timestamp: pd.Timestamp           # confirmation bar (entry bar close)
    pivot_timestamp: pd.Timestamp
    kind: str                          # 'reg_bull' | 'hid_bull' | 'reg_bear' | 'hid_bear'
    entry_price: float                 # close of confirmation bar
    pivot_price: float                 # low or high at pivot bar (stop level)
    prev_pivot_price: float            # low or high at previous pivot
    osc_now: float
    osc_prev: float
    bars_since_prev: int
    po_zone: str
    fast_cloud_bull: int
    slow_cloud_bull: int
    atr_14: float                      # daily ATR
    prev_close: float
    atr_upper_trigger: float
    atr_lower_trigger: float
    atr_upper_0382: float
    atr_lower_0382: float
    atr_upper_0618: float
    atr_lower_0618: float
    halfhour: str                      # e.g. '10:00'
    in_zone_a: bool
    in_zone_b: bool
    # outcomes filled later
    mfe_by_window: dict = field(default_factory=dict)
    mae_by_window: dict = field(default_factory=dict)
    hit_pct_targets: dict = field(default_factory=dict)
    hit_atr_levels: dict = field(default_factory=dict)
    stopped_out: bool | None = None
    stop_bar: int | None = None
    eod_close: float | None = None
    eod_pnl_dollar: float | None = None
    eod_dir_correct: bool | None = None
    # OCO bracket outcome (primary success metric)
    # outcome ∈ {'loss', 'wash_loss', 'wash_profit', 'partial', 'full'}
    # loss        = $0.50 stop fired before any in-direction level
    # wash_loss   = neither stop nor partial fired; actual close at bar 10 < entry (in dir)
    # wash_profit = neither stop nor partial fired; actual close at bar 10 > entry (in dir)
    # partial     = $0.50 in-direction first; $1.00 didn't fire by bar 10
    # full        = $1.00 in-direction (with or without partial first)
    bracket_outcome: str | None = None
    bracket_bars: int | None = None  # bars to bracket fire (None for wash_*)
    bracket_pnl: float | None = None  # realized $ P&L in direction (loss=-0.50, full=+1.00, etc.)


def signal_direction(kind: str) -> int:
    return 1 if kind in ("reg_bull", "hid_bull") else -1


def bracket_outcome(entry_price: float, direction: int,
                    highs_after: np.ndarray, lows_after: np.ndarray,
                    closes_after: np.ndarray,
                    max_bars: int = BRACKET_MAX_BARS) -> tuple[str, int | None, float]:
    """OCO-style bracket outcome for a signal entered at entry_price in `direction`.

    Walks bar-by-bar over (highs_after, lows_after, closes_after), starting at the bar
    IMMEDIATELY after the entry bar. Conservative within-bar ordering: if a single bar's
    range contains both the stop and a favorable level, the stop is assumed to fire first.

    Returns (outcome, bars_to_event, realized_pnl):
        'loss'        — $0.50 stop fires before any in-direction level. PnL = -0.50.
        'full'        — $1.00 in-direction (with or after partial). PnL = +1.00.
        'partial'     — $0.50 in-direction first; $1.00 doesn't fire by max_bars. PnL = +0.50.
        'wash_loss'   — neither stop nor partial fires by max_bars; close at last bar in
                         the window is against the signal. PnL = signed close diff (negative).
        'wash_profit' — same as wash_loss but close is in favor of the signal. PnL > 0.
    """
    if direction == 1:
        stop_lvl = entry_price - BRACKET_STOP_DOLLAR
        partial_lvl = entry_price + BRACKET_PARTIAL_DOLLAR
        full_lvl = entry_price + BRACKET_FULL_DOLLAR
    else:
        stop_lvl = entry_price + BRACKET_STOP_DOLLAR
        partial_lvl = entry_price - BRACKET_PARTIAL_DOLLAR
        full_lvl = entry_price - BRACKET_FULL_DOLLAR

    n = min(max_bars, len(highs_after))
    if n == 0:
        return ("wash_profit", None, 0.0)  # degenerate; should not happen in practice

    partial_hit = False
    bars_to_partial: int | None = None

    for k in range(n):
        h = float(highs_after[k])
        l = float(lows_after[k])

        if direction == 1:
            hit_stop = l <= stop_lvl
            hit_partial = h >= partial_lvl
            hit_full = h >= full_lvl
        else:
            hit_stop = h >= stop_lvl
            hit_partial = l <= partial_lvl
            hit_full = l <= full_lvl

        if not partial_hit:
            if hit_stop:
                return ("loss", k + 1, -BRACKET_STOP_DOLLAR)
            if hit_full:
                return ("full", k + 1, BRACKET_FULL_DOLLAR)
            if hit_partial:
                partial_hit = True
                bars_to_partial = k + 1
        else:
            if hit_full:
                return ("full", k + 1, BRACKET_FULL_DOLLAR)

    if partial_hit:
        return ("partial", bars_to_partial, BRACKET_PARTIAL_DOLLAR)

    # No bracket level fired within max_bars — exit at the last available bar's close.
    last_close = float(closes_after[n - 1])
    pnl = (last_close - entry_price) * direction
    if pnl >= 0:
        return ("wash_profit", None, pnl)
    return ("wash_loss", None, pnl)


# ────────────────────────────────────────────────────────────────────────────
# Per-session signal extraction
# ────────────────────────────────────────────────────────────────────────────

def signals_for_session(g: pd.DataFrame) -> list[Signal]:
    """Detect divergences within a single RTH session."""
    if len(g) < (LB_L + LB_R + 2):
        return []

    osc = g["phase_oscillator"].to_numpy()
    low = g["low"].to_numpy()
    high = g["high"].to_numpy()

    is_pl, is_ph = detect_pivots(osc, LB_L, LB_R)

    pl_idx = np.where(is_pl)[0]
    ph_idx = np.where(is_ph)[0]

    out: list[Signal] = []

    # iterate consecutive pivot lows
    for n in range(1, len(pl_idx)):
        i_curr = int(pl_idx[n])
        i_prev = int(pl_idx[n - 1])
        # confirmation bar of CURRENT pivot
        i_conf = i_curr + LB_R
        if i_conf >= len(g):
            continue
        # bars between confirmations
        bars_between = i_curr - i_prev
        if not (RANGE_LOWER <= bars_between <= RANGE_UPPER):
            continue
        osc_now = float(osc[i_curr])
        osc_prev = float(osc[i_prev])
        low_now = float(low[i_curr])
        low_prev = float(low[i_prev])

        kind = None
        if low_now < low_prev and osc_now > osc_prev:
            kind = "reg_bull"
        elif low_now > low_prev and osc_now < osc_prev:
            kind = "hid_bull"
        if kind is None:
            continue
        out.append(_build_signal(g, i_curr, i_conf, kind,
                                 entry_price=float(g["close"].iloc[i_conf]),
                                 pivot_price=low_now, prev_pivot_price=low_prev,
                                 osc_now=osc_now, osc_prev=osc_prev,
                                 bars_since_prev=bars_between))

    # iterate consecutive pivot highs
    for n in range(1, len(ph_idx)):
        i_curr = int(ph_idx[n])
        i_prev = int(ph_idx[n - 1])
        i_conf = i_curr + LB_R
        if i_conf >= len(g):
            continue
        bars_between = i_curr - i_prev
        if not (RANGE_LOWER <= bars_between <= RANGE_UPPER):
            continue
        osc_now = float(osc[i_curr])
        osc_prev = float(osc[i_prev])
        high_now = float(high[i_curr])
        high_prev = float(high[i_prev])

        kind = None
        if high_now > high_prev and osc_now < osc_prev:
            kind = "reg_bear"
        elif high_now < high_prev and osc_now > osc_prev:
            kind = "hid_bear"
        if kind is None:
            continue
        out.append(_build_signal(g, i_curr, i_conf, kind,
                                 entry_price=float(g["close"].iloc[i_conf]),
                                 pivot_price=high_now, prev_pivot_price=high_prev,
                                 osc_now=osc_now, osc_prev=osc_prev,
                                 bars_since_prev=bars_between))

    return out


def _build_signal(g: pd.DataFrame, i_curr: int, i_conf: int, kind: str,
                  entry_price: float, pivot_price: float, prev_pivot_price: float,
                  osc_now: float, osc_prev: float, bars_since_prev: int) -> Signal:
    row_conf = g.iloc[i_conf]
    row_pivot = g.iloc[i_curr]
    ts_conf: pd.Timestamp = row_conf.name
    ts_pivot: pd.Timestamp = row_pivot.name
    return Signal(
        timestamp=ts_conf,
        pivot_timestamp=ts_pivot,
        kind=kind,
        entry_price=entry_price,
        pivot_price=pivot_price,
        prev_pivot_price=prev_pivot_price,
        osc_now=osc_now,
        osc_prev=osc_prev,
        bars_since_prev=bars_since_prev,
        po_zone=str(row_conf["phase_zone"]) if pd.notna(row_conf["phase_zone"]) else "unknown",
        fast_cloud_bull=int(row_conf["fast_cloud_bullish"]) if pd.notna(row_conf["fast_cloud_bullish"]) else -1,
        slow_cloud_bull=int(row_conf["slow_cloud_bullish"]) if pd.notna(row_conf["slow_cloud_bullish"]) else -1,
        atr_14=float(row_conf["atr_14"]),
        prev_close=float(row_conf["prev_close"]),
        atr_upper_trigger=float(row_conf["atr_upper_trigger"]),
        atr_lower_trigger=float(row_conf["atr_lower_trigger"]),
        atr_upper_0382=float(row_conf["atr_upper_0382"]),
        atr_lower_0382=float(row_conf["atr_lower_0382"]),
        atr_upper_0618=float(row_conf["atr_upper_0618"]),
        atr_lower_0618=float(row_conf["atr_lower_0618"]),
        halfhour=f"{ts_conf.hour:02d}:{(ts_conf.minute // 30) * 30:02d}",
        in_zone_a=ZONE_A[0] <= osc_now <= ZONE_A[1],
        in_zone_b=ZONE_B[0] <= osc_now <= ZONE_B[1],
    )


# ────────────────────────────────────────────────────────────────────────────
# Forward outcome computation
# ────────────────────────────────────────────────────────────────────────────

def fill_outcomes(signals: list[Signal], session: pd.DataFrame) -> None:
    """For each signal in this session, compute forward windows / hit rates."""
    if not signals:
        return
    highs = session["high"].to_numpy()
    lows = session["low"].to_numpy()
    closes = session["close"].to_numpy()
    idx_map = {ts: i for i, ts in enumerate(session.index)}
    eod_close = float(closes[-1])
    n = len(session)

    for s in signals:
        i = idx_map[s.timestamp]
        direction = signal_direction(s.kind)

        # forward windows
        for w in FORWARD_WINDOWS:
            j_end = min(i + w, n - 1)
            if j_end <= i:
                s.mfe_by_window[w] = 0.0
                s.mae_by_window[w] = 0.0
                continue
            window_high = float(highs[i + 1:j_end + 1].max())
            window_low = float(lows[i + 1:j_end + 1].min())
            if direction == 1:
                mfe = window_high - s.entry_price
                mae = s.entry_price - window_low
            else:
                mfe = s.entry_price - window_low
                mae = window_high - s.entry_price
            s.mfe_by_window[w] = mfe
            s.mae_by_window[w] = mae

        # to-EOD MFE / MAE
        j_end = n - 1
        if j_end > i:
            window_high = float(highs[i + 1:j_end + 1].max())
            window_low = float(lows[i + 1:j_end + 1].min())
            if direction == 1:
                s.mfe_by_window["eod"] = window_high - s.entry_price
                s.mae_by_window["eod"] = s.entry_price - window_low
            else:
                s.mfe_by_window["eod"] = s.entry_price - window_low
                s.mae_by_window["eod"] = window_high - s.entry_price
        else:
            s.mfe_by_window["eod"] = 0.0
            s.mae_by_window["eod"] = 0.0

        # hit pct targets in predicted direction (any time before RTH close)
        for tgt in PCT_TARGETS:
            tgt_price = s.entry_price * (1 + direction * tgt / 100.0)
            if direction == 1:
                hit = bool((highs[i + 1:] >= tgt_price).any())
            else:
                hit = bool((lows[i + 1:] <= tgt_price).any())
            s.hit_pct_targets[tgt] = hit

        # hit ATR levels in predicted direction
        if direction == 1:
            atr_levels = {
                "upper_trigger": s.atr_upper_trigger,
                "upper_0382": s.atr_upper_0382,
                "upper_0618": s.atr_upper_0618,
            }
            for label, lvl in atr_levels.items():
                if pd.isna(lvl) or lvl <= s.entry_price:
                    s.hit_atr_levels[label] = None  # already past it (or NaN)
                else:
                    s.hit_atr_levels[label] = bool((highs[i + 1:] >= lvl).any())
        else:
            atr_levels = {
                "lower_trigger": s.atr_lower_trigger,
                "lower_0382": s.atr_lower_0382,
                "lower_0618": s.atr_lower_0618,
            }
            for label, lvl in atr_levels.items():
                if pd.isna(lvl) or lvl >= s.entry_price:
                    s.hit_atr_levels[label] = None
                else:
                    s.hit_atr_levels[label] = bool((lows[i + 1:] <= lvl).any())

        # stop-out: did price exceed the pivot extreme against direction?
        if direction == 1:
            stop_idx = np.where(lows[i + 1:] < s.pivot_price)[0]
        else:
            stop_idx = np.where(highs[i + 1:] > s.pivot_price)[0]
        if len(stop_idx) > 0:
            s.stopped_out = True
            s.stop_bar = int(stop_idx[0]) + 1
        else:
            s.stopped_out = False

        # EOD bias
        s.eod_close = eod_close
        s.eod_pnl_dollar = (eod_close - s.entry_price) * direction
        s.eod_dir_correct = bool(s.eod_pnl_dollar > 0)

        # OCO bracket outcome (primary success metric)
        highs_after = highs[i + 1:]
        lows_after = lows[i + 1:]
        closes_after = closes[i + 1:]
        outcome, bars, pnl = bracket_outcome(
            s.entry_price, direction, highs_after, lows_after, closes_after,
        )
        s.bracket_outcome = outcome
        s.bracket_bars = bars
        s.bracket_pnl = pnl


# ────────────────────────────────────────────────────────────────────────────
# Baseline computation
# ────────────────────────────────────────────────────────────────────────────

def compute_baseline(df: pd.DataFrame, halfhours: list[str]) -> dict:
    """For each half-hour bucket, compute the random-bar baseline:
    P(EOD close higher than entry close) for that time of day.
    Vectorized: per-day arrays + numpy ops.
    """
    print("Computing baseline forward stats by half-hour …", flush=True)

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    minutes = df.index.hour * 60 + df.index.minute
    halfhour_key = (minutes // 30) * 30
    hh_str = np.array([f"{m // 60:02d}:{m % 60:02d}" for m in halfhour_key])
    dates = df["date"].values

    # last close per day (positionally), via groupby
    df_idx = pd.DataFrame({"date": dates, "close": closes, "high": highs, "low": lows})
    last_close_per_day = df_idx.groupby("date")["close"].transform("last").to_numpy()
    max_high_per_day = df_idx.groupby("date")["high"].cummax().to_numpy()  # not used directly here

    # for each bar, compare its close vs the day's final close (forward = up by EOD?)
    up_eod = (last_close_per_day > closes).astype(int)

    baseline = {}
    for hh in halfhours:
        mask = hh_str == hh
        n = int(mask.sum())
        if n == 0:
            baseline[hh] = {"n": 0, "p_close_up_eod": None}
            continue
        baseline[hh] = {
            "n": n,
            "p_close_up_eod": float(up_eod[mask].mean()),
        }
    return baseline


# ────────────────────────────────────────────────────────────────────────────
# Reporting helpers
# ────────────────────────────────────────────────────────────────────────────

def pct(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{100.0 * num / den:5.1f}%"


def compute_bracket_baseline(df: pd.DataFrame, sample_size: int = 50000) -> dict:
    """Random-bar OCO bracket baseline: at any RTH 3m bar, what is the
    bracket outcome distribution under each direction? Path-equivalent to
    the signal logic, applied to the unconditional bar.
    Returns: {'bull': {...counts...}, 'bear': {...counts...}}
    """
    print("Computing bracket-outcome baseline …", flush=True)
    rng = np.random.default_rng(42)
    if len(df) > sample_size:
        idxs = rng.choice(len(df), size=sample_size, replace=False)
        idxs.sort()
    else:
        idxs = np.arange(len(df))

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    dates = df["date"].values

    out = {}
    for direction, label in [(1, "bull"), (-1, "bear")]:
        counts = {"loss": 0, "wash_loss": 0, "wash_profit": 0, "partial": 0, "full": 0}
        pnl_total = 0.0
        bars_list = []
        n_evaluated = 0
        for idx in idxs:
            d = dates[idx]
            entry = closes[idx]
            j = idx + 1
            forward_h = []
            forward_l = []
            forward_c = []
            while j < len(df) and dates[j] == d and len(forward_h) < BRACKET_MAX_BARS:
                forward_h.append(highs[j])
                forward_l.append(lows[j])
                forward_c.append(closes[j])
                j += 1
            if len(forward_h) == 0:
                continue
            outcome, bars, pnl = bracket_outcome(
                entry, direction,
                np.array(forward_h), np.array(forward_l), np.array(forward_c),
            )
            counts[outcome] += 1
            pnl_total += pnl
            n_evaluated += 1
            if bars is not None:
                bars_list.append(bars)
        out[label] = {
            "n": n_evaluated,
            **counts,
            **{f"p_{k}": v / n_evaluated for k, v in counts.items()},
            "ev": pnl_total / n_evaluated if n_evaluated else 0.0,
        }
    return out


def summarise(signals: list[Signal]) -> None:
    by_kind = defaultdict(list)
    for s in signals:
        by_kind[s.kind].append(s)

    kinds = ["reg_bull", "hid_bull", "reg_bear", "hid_bear"]
    print("\n=== SIGNAL COUNTS ===")
    for k in kinds:
        print(f"  {k:>9}: {len(by_kind[k]):>6} signals")
    print(f"  {'total':>9}: {len(signals):>6}")

    print("\n=== HEADLINE OUTCOMES BY KIND ===")
    print(f"{'kind':>9}  {'n':>5}  {'eod_dir%':>9}  "
          f"{'+0.25%':>7}  {'+0.50%':>7}  {'+1.00%':>7}  {'stop%':>6}  {'med_mfe$':>9}  {'med_mae$':>9}")
    for k in kinds:
        sigs = by_kind[k]
        n = len(sigs)
        if n == 0:
            continue
        dir_correct = sum(1 for s in sigs if s.eod_dir_correct)
        hit_025 = sum(1 for s in sigs if s.hit_pct_targets.get(0.25))
        hit_050 = sum(1 for s in sigs if s.hit_pct_targets.get(0.50))
        hit_100 = sum(1 for s in sigs if s.hit_pct_targets.get(1.00))
        stops = sum(1 for s in sigs if s.stopped_out)
        med_mfe = np.median([s.mfe_by_window[60] for s in sigs])
        med_mae = np.median([s.mae_by_window[60] for s in sigs])
        print(f"{k:>9}  {n:>5}  {pct(dir_correct, n):>9}  "
              f"{pct(hit_025, n):>7}  {pct(hit_050, n):>7}  {pct(hit_100, n):>7}  "
              f"{pct(stops, n):>6}  {med_mfe:>9.3f}  {med_mae:>9.3f}")

    print("\n=== BRACKET OUTCOME BY KIND (5-bucket; $0.50 stop / $0.50 partial / $1.00 full; 10-bar exit at close) ===")
    print(f"{'kind':>9}  {'n':>5}  {'loss%':>6}  {'wL%':>5}  {'wP%':>5}  {'partial%':>9}  {'full%':>6}  "
          f"{'EV($)':>8}  {'tot_loss%':>9}  {'tot_win%':>9}")
    for k in kinds:
        sigs = by_kind[k]
        n = len(sigs)
        if n == 0:
            continue
        c = {"loss": 0, "wash_loss": 0, "wash_profit": 0, "partial": 0, "full": 0}
        pnl_total = 0.0
        for s in sigs:
            outcome = s.bracket_outcome or "wash_profit"
            c[outcome] += 1
            pnl_total += (s.bracket_pnl if s.bracket_pnl is not None else 0.0)
        ev = pnl_total / n
        tot_loss = c["loss"] + c["wash_loss"]
        tot_win = c["wash_profit"] + c["partial"] + c["full"]
        print(f"{k:>9}  {n:>5}  {pct(c['loss'], n):>6}  {pct(c['wash_loss'], n):>5}  "
              f"{pct(c['wash_profit'], n):>5}  {pct(c['partial'], n):>9}  "
              f"{pct(c['full'], n):>6}  {ev:>+8.4f}  {pct(tot_loss, n):>9}  {pct(tot_win, n):>9}")

    print("\n=== HIT RATE TO ATR LEVELS BY KIND ===")
    for k in kinds:
        sigs = by_kind[k]
        if not sigs:
            continue
        if k.endswith("bull"):
            cols = ("upper_trigger", "upper_0382", "upper_0618")
        else:
            cols = ("lower_trigger", "lower_0382", "lower_0618")
        print(f"  {k}:")
        for col in cols:
            sub = [s for s in sigs if s.hit_atr_levels.get(col) is not None]
            hits = sum(1 for s in sub if s.hit_atr_levels.get(col))
            print(f"    {col:<14} hit={pct(hits, len(sub))} (n={len(sub)})")


def cross_cut_table(signals: list[Signal], dim: str, kinds: list[str]) -> None:
    print(f"\n=== EOD-correct % BY {dim.upper()} ===")
    print(f"{dim:>15}  ", end="")
    for k in kinds:
        print(f"{k:>10} (n)  ", end="")
    print()
    by_dim = defaultdict(lambda: defaultdict(list))
    for s in signals:
        by_dim[getattr(s, dim)][s.kind].append(s)
    for v in sorted(by_dim.keys(), key=lambda x: str(x)):
        print(f"{str(v):>15}  ", end="")
        for k in kinds:
            sigs = by_dim[v][k]
            if not sigs:
                print(f"{'-':>10}     ", end="")
                continue
            n = len(sigs)
            corr = sum(1 for s in sigs if s.eod_dir_correct)
            tag = f"{100*corr/n:>5.1f}% ({n})"
            print(f"{tag:>15}  ", end="")
        print()


def hit_target_xcut(signals: list[Signal], dim: str, kinds: list[str], target: float = 0.25) -> None:
    print(f"\n=== Hit ±{target}% BY {dim.upper()} ===")
    print(f"{dim:>15}  ", end="")
    for k in kinds:
        print(f"{k:>10} (n)  ", end="")
    print()
    by_dim = defaultdict(lambda: defaultdict(list))
    for s in signals:
        by_dim[getattr(s, dim)][s.kind].append(s)
    for v in sorted(by_dim.keys(), key=lambda x: str(x)):
        print(f"{str(v):>15}  ", end="")
        for k in kinds:
            sigs = by_dim[v][k]
            if not sigs:
                print(f"{'-':>10}     ", end="")
                continue
            n = len(sigs)
            hits = sum(1 for s in sigs if s.hit_pct_targets.get(target))
            tag = f"{100*hits/n:>5.1f}% ({n})"
            print(f"{tag:>15}  ", end="")
        print()


def serialize(signals: list[Signal]) -> list[dict]:
    out = []
    for s in signals:
        d = asdict(s)
        d["timestamp"] = s.timestamp.isoformat()
        d["pivot_timestamp"] = s.pivot_timestamp.isoformat()
        # keys with floats / ints survive JSON
        d["mfe_by_window"] = {str(k): v for k, v in s.mfe_by_window.items()}
        d["mae_by_window"] = {str(k): v for k, v in s.mae_by_window.items()}
        d["hit_pct_targets"] = {str(k): v for k, v in s.hit_pct_targets.items()}
        d["hit_atr_levels"] = {str(k): v for k, v in s.hit_atr_levels.items()}
        out.append(d)
    return out


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading ind_3m from {DB_PATH} …")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "phase_oscillator, phase_zone, "
        "fast_cloud_bullish, slow_cloud_bullish, "
        "atr_14, prev_close, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618 "
        "FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"],
    )
    df = df.set_index("timestamp").sort_index()

    # RTH only
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["phase_oscillator", "atr_14", "prev_close",
                            "atr_upper_trigger", "atr_lower_trigger",
                            "atr_upper_0382", "atr_lower_0382",
                            "atr_upper_0618", "atr_lower_0618"])
    df["date"] = df.index.date
    print(f"RTH 3m bars: {len(df):,}  ({df.index.min()} → {df.index.max()})")

    all_signals: list[Signal] = []
    sessions = df.groupby("date", sort=True)
    n_sessions = len(sessions)
    print(f"Sessions: {n_sessions:,}")

    for k, (date, g) in enumerate(sessions, 1):
        if len(g) < (LB_L + LB_R + 4):
            continue
        sigs = signals_for_session(g)
        if sigs:
            fill_outcomes(sigs, g)
            all_signals.extend(sigs)
        if k % 1000 == 0:
            print(f"  processed {k}/{n_sessions} sessions, signals so far: {len(all_signals):,}")

    print(f"\nTotal signals: {len(all_signals):,}")

    summarise(all_signals)

    kinds = ["reg_bull", "hid_bull", "reg_bear", "hid_bear"]

    # cross-cuts
    cross_cut_table(all_signals, "halfhour", kinds)
    hit_target_xcut(all_signals, "halfhour", kinds, target=0.25)
    cross_cut_table(all_signals, "po_zone", kinds)
    hit_target_xcut(all_signals, "po_zone", kinds, target=0.25)

    # zone-filter effect (the indicator's optional filter A and B)
    print("\n=== ZONE-A FILTER EFFECT (signals with osc in 23.6–61.8) ===")
    print("kind          inA_count   inA_eod%   outA_count   outA_eod%   delta")
    for k in kinds:
        in_a = [s for s in all_signals if s.kind == k and s.in_zone_a]
        out_a = [s for s in all_signals if s.kind == k and not s.in_zone_a]
        eod_in = sum(1 for s in in_a if s.eod_dir_correct) / len(in_a) * 100 if in_a else float('nan')
        eod_out = sum(1 for s in out_a if s.eod_dir_correct) / len(out_a) * 100 if out_a else float('nan')
        delta = eod_out - eod_in if (in_a and out_a) else float('nan')
        print(f"  {k:>9}   {len(in_a):>6}   {eod_in:>6.1f}%   {len(out_a):>6}   {eod_out:>6.1f}%   {delta:>+6.1f}")

    print("\n=== ZONE-B FILTER EFFECT (signals with osc in -61.8 to -23.6) ===")
    print("kind          inB_count   inB_eod%   outB_count   outB_eod%   delta")
    for k in kinds:
        in_b = [s for s in all_signals if s.kind == k and s.in_zone_b]
        out_b = [s for s in all_signals if s.kind == k and not s.in_zone_b]
        eod_in = sum(1 for s in in_b if s.eod_dir_correct) / len(in_b) * 100 if in_b else float('nan')
        eod_out = sum(1 for s in out_b if s.eod_dir_correct) / len(out_b) * 100 if out_b else float('nan')
        delta = eod_out - eod_in if (in_b and out_b) else float('nan')
        print(f"  {k:>9}   {len(in_b):>6}   {eod_in:>6.1f}%   {len(out_b):>6}   {eod_out:>6.1f}%   {delta:>+6.1f}")

    # ribbon state cross-cut
    print("\n=== EOD% BY RIBBON STATE (fast,slow) ===")
    print(f"{'fast/slow':>12}  ", end="")
    for k in kinds:
        print(f"{k:>10} (n)  ", end="")
    print()
    for fs in [(1, 1), (1, 0), (0, 1), (0, 0)]:
        label = f"{'bull' if fs[0] else 'bear'}/{'bull' if fs[1] else 'bear'}"
        print(f"{label:>12}  ", end="")
        for k in kinds:
            sigs = [s for s in all_signals if s.kind == k and s.fast_cloud_bull == fs[0] and s.slow_cloud_bull == fs[1]]
            if not sigs:
                print(f"{'-':>10}     ", end="")
                continue
            n = len(sigs)
            corr = sum(1 for s in sigs if s.eod_dir_correct)
            tag = f"{100*corr/n:>5.1f}% ({n})"
            print(f"{tag:>15}  ", end="")
        print()

    # bracket outcome baseline
    bracket_base = compute_bracket_baseline(df)
    print("\n=== BRACKET BASELINE (random RTH 3m bar, OCO + 10-bar close) ===")
    print(f"{'dir':>4}  {'n':>6}  {'loss%':>6}  {'wL%':>5}  {'wP%':>5}  "
          f"{'partial%':>9}  {'full%':>6}  {'tot_loss%':>9}  {'tot_win%':>9}  {'EV($)':>8}")
    for direction in ("bull", "bear"):
        b = bracket_base[direction]
        tot_loss = b["p_loss"] + b["p_wash_loss"]
        tot_win = b["p_wash_profit"] + b["p_partial"] + b["p_full"]
        print(f"{direction:>4}  {b['n']:>6}  {b['p_loss']*100:>5.1f}%  "
              f"{b['p_wash_loss']*100:>4.1f}%  {b['p_wash_profit']*100:>4.1f}%  "
              f"{b['p_partial']*100:>8.1f}%  {b['p_full']*100:>5.1f}%  "
              f"{tot_loss*100:>8.1f}%  {tot_win*100:>8.1f}%  {b['ev']:>+8.4f}")

    print("\n=== BRACKET EDGE: signal EV minus matched-direction baseline EV ===")
    for k in kinds:
        sigs = [s for s in all_signals if s.kind == k]
        if not sigs:
            continue
        c = {"loss": 0, "wash_loss": 0, "wash_profit": 0, "partial": 0, "full": 0}
        pnl_total = 0.0
        for s in sigs:
            c[s.bracket_outcome or "wash_profit"] += 1
            pnl_total += s.bracket_pnl or 0.0
        n = len(sigs)
        ev_sig = pnl_total / n
        base = bracket_base["bull" if k.endswith("bull") else "bear"]
        ev_base = base["ev"]
        edge = ev_sig - ev_base
        tot_loss = (c["loss"] + c["wash_loss"]) / n * 100
        tot_loss_base = (base["p_loss"] + base["p_wash_loss"]) * 100
        tot_win = (c["wash_profit"] + c["partial"] + c["full"]) / n * 100
        tot_win_base = (base["p_wash_profit"] + base["p_partial"] + base["p_full"]) * 100
        print(f"  {k:>9}: EV_sig={ev_sig:+.4f}  EV_base={ev_base:+.4f}  Δ={edge:+.4f}  "
              f"loss%={tot_loss:.1f} (vs {tot_loss_base:.1f}, Δ={tot_loss - tot_loss_base:+.1f})  "
              f"win%={tot_win:.1f} (vs {tot_win_base:.1f}, Δ={tot_win - tot_win_base:+.1f})")

    # baseline comparison (forward 60-bar)
    halfhours = sorted({s.halfhour for s in all_signals})
    baseline = compute_baseline(df, halfhours)

    print("\n=== EDGE vs BASELINE (EOD direction) ===")
    print("base_up = P(RTH close > bar close) for any bar at that half-hour")
    print(f"{'halfhour':>10}  {'base_n':>8}  {'base_up%':>9}  "
          f"{'rb_eod%':>10}  {'hb_eod%':>10}  {'Rb_eod%↓':>10}  {'Hb_eod%↓':>10}")
    by_kind_hh = defaultdict(lambda: defaultdict(list))
    for s in all_signals:
        by_kind_hh[s.kind][s.halfhour].append(s)
    for hh in halfhours:
        b = baseline[hh]
        base_up = b["p_close_up_eod"]
        base_str = f"{100*base_up:5.1f}%" if base_up is not None else "n/a"
        row = [f"{hh:>10}", f"{b['n']:>8}", f"{base_str:>9}"]
        for k in ("reg_bull", "hid_bull"):
            sigs = by_kind_hh[k][hh]
            if not sigs:
                row.append(f"{'-':>10}")
            else:
                up = sum(1 for s in sigs if s.eod_dir_correct)
                row.append(f"{100*up/len(sigs):5.1f}%({len(sigs)})")
        for k in ("reg_bear", "hid_bear"):
            sigs = by_kind_hh[k][hh]
            if not sigs:
                row.append(f"{'-':>10}")
            else:
                # for bear: we want P(close < entry), which equals 1 - P(close > entry)
                dn = sum(1 for s in sigs if s.eod_dir_correct)
                row.append(f"{100*dn/len(sigs):5.1f}%({len(sigs)})")
        print("  ".join(row))

    # write JSON
    out_path = os.path.join(BASE_DIR, "tenam_traffic_events.json")
    with open(out_path, "w") as f:
        json.dump({
            "generated_at": pd.Timestamp.utcnow().isoformat(),
            "n_signals": len(all_signals),
            "n_sessions": n_sessions,
            "params": {
                "lbL": LB_L, "lbR": LB_R,
                "rangeUpper": RANGE_UPPER, "rangeLower": RANGE_LOWER,
                "zone_a": ZONE_A, "zone_b": ZONE_B,
            },
            "baseline": baseline,
            "bracket_baseline": bracket_base,
            "signals": serialize(all_signals),
        }, f, indent=2, default=str)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()

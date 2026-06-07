#!/usr/bin/env python3
"""SPX Open-Band Path: per-day adjacent-rung walk starting from the 09:30 ATR band.

Inputs:
  FirstRateData SPX 1-minute bars aggregated to 3-minute RTH (load_spx()).

Output:
  site/data/spx-open-band-path.json — metadata + per-day path records the
  browser uses to recompute every cohort/cumulative curve client-side.

Semantics (see also: test_open_band_path.py contract tests):
  - The opening "band" is the half-open interval [L, U) of adjacent public
    Saty ATR ladder rungs (hidden +/- 2.236 sentinels excluded). A day is in
    band [L, U) iff (open - PDC) / ATR14 satisfies L <= open_atr < U.
  - From the open band, scan 3-minute RTH bars 09:30..15:57 forward.
    First-event rule per band:
      * upper_hit  = bar range contains upper_rung_price (high >= rung and low <= rung)
      * lower_hit  = bar range contains lower_rung_price (low <= rung and high >= rung)
      * upper_hit AND lower_hit (same 3-min bar)  -> "amb" (path terminates)
      * upper_hit only -> touched upper rung
      * lower_hit only -> touched lower rung
      * neither by RTH close -> "none" (path terminates)
    For the 09:30 bar, when the opening price equals the lower rung exactly,
    the touch requires lower bar.low strictly < lower rung (the open price
    itself does not count as a touch). The upper boundary cannot equal the
    open price because the band is half-open on the right.
  - Side per band (relative to PDC, where PDC sits on the ladder):
      lower_idx >= PDC_idx  -> upside (cont = touch upper rung)
      upper_idx <= PDC_idx  -> downside (cont = touch lower rung)
    Otherwise (band straddles PDC) -> neutral (no cont/retr labels).
    With PDC on the public ladder, neutral never occurs in practice; we
    keep the branch for safety + tests.
  - After a non-ambiguous touch, the new band is the adjacent rung pair
    extending farther from the prior band: touching the upper rung yields
    [upper, upper+1]; touching the lower rung yields [lower-1, lower].
    The next-band scan starts on the bar AFTER the touch bar. OHLC for one
    3-minute bar cannot order multiple adjacent-rung touches, so we never
    chain two events through the same physical bar.
  - Cumulative curves are always computed over the original cohort
    denominator: numerator at minute t = days whose path event of that type
    has occurred by t; denominator stays the cohort's day count. "amb" and
    "none" remain visible as denominator leakage (not dropped).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_atr_cascade import (
    HIDDEN_MEASUREMENT_LABELS,
    LABELS,
    LADDER,
    LEVEL_NAMES,
)
from backtest_atr_cascade_spx_firstrate import load_spx

BASE_DIR = Path(__file__).resolve().parent
JSON_OUT = BASE_DIR / "site" / "data" / "spx-open-band-path.json"
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)

# Public ladder: drop hidden +/- 2.236 sentinel rungs.
PUBLIC = [(lab, col, mult) for lab, col, mult in LADDER if lab not in HIDDEN_MEASUREMENT_LABELS]
PUBLIC_LABELS = [r[0] for r in PUBLIC]
PUBLIC_COLS = [r[1] for r in PUBLIC]
PUBLIC_MULTS = [r[2] for r in PUBLIC]
PUBLIC_PDC_IDX = PUBLIC_LABELS.index("PDC")
N_PUBLIC = len(PUBLIC_LABELS)

EPS = 1e-9

# Cap per-day path length. Any walk this deep is far past the dashboard's
# stated "at least 4 path steps" UI depth and only inflates the static JSON.
# Increase if a study ever needs longer histories.
MAX_PATH_DEPTH = 16


def build_bands() -> list[dict]:
    """Adjacent public-ladder band intervals, lower inclusive, upper exclusive."""
    bands = []
    for i in range(N_PUBLIC - 1):
        lo_lab = PUBLIC_LABELS[i]
        hi_lab = PUBLIC_LABELS[i + 1]
        lo_mult = PUBLIC_MULTS[i]
        hi_mult = PUBLIC_MULTS[i + 1]
        if i + 1 <= PUBLIC_PDC_IDX:
            side = "down"
        elif i >= PUBLIC_PDC_IDX:
            side = "up"
        else:
            side = "neutral"
        bands.append({
            "index": i,
            "lower_label": lo_lab,
            "upper_label": hi_lab,
            "lower_atr": lo_mult,
            "upper_atr": hi_mult,
            "side": side,
            "lower_name": LEVEL_NAMES.get(lo_lab, lo_lab),
            "upper_name": LEVEL_NAMES.get(hi_lab, hi_lab),
        })
    return bands


BANDS = build_bands()


def find_band_index(open_atr: float) -> int | None:
    """Return public band index (0..N_PUBLIC-2) such that lower<=open_atr<upper."""
    if not np.isfinite(open_atr):
        return None
    for b in BANDS:
        if b["lower_atr"] <= open_atr < b["upper_atr"]:
            return b["index"]
    return None


def band_side(lower_idx: int, upper_idx: int) -> str:
    if upper_idx <= PUBLIC_PDC_IDX:
        return "down"
    if lower_idx >= PUBLIC_PDC_IDX:
        return "up"
    return "neutral"


def walk_path(
    timestamps: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    open_price: float,
    open_band_idx: int,
    rung_prices: list[float],
) -> list[dict]:
    """Compute the adjacent-rung path for one RTH day. See module docstring."""
    n = len(timestamps)
    if n == 0:
        return []
    start_ts = timestamps[0]
    lower_idx = open_band_idx
    upper_idx = open_band_idx + 1
    path: list[dict] = []
    bar_pos = 0
    is_first_band = True
    # If the opening price sits exactly on the lower rung, the band's lower
    # boundary coincides with the open. The open itself is not a touch and
    # bars whose low merely re-touches that level (low == lower_p) without
    # strictly crossing below should not register a touch. This stays in
    # effect for the entire first-band scan.
    open_on_lower = abs(open_price - rung_prices[lower_idx]) < EPS

    while bar_pos < n and len(path) < MAX_PATH_DEPTH:
        lower_p = rung_prices[lower_idx]
        upper_p = rung_prices[upper_idx]
        side = band_side(lower_idx, upper_idx)
        lo_lab = PUBLIC_LABELS[lower_idx]
        hi_lab = PUBLIC_LABELS[upper_idx]

        outcome = None
        hit_bar = None
        for i in range(bar_pos, n):
            hi = highs[i]
            lo = lows[i]
            # Spanning touch: a rung is "touched" only if the bar's range
            # contains it. Prevents bars that sit entirely above/below the
            # band from spuriously triggering a boundary event.
            up_hit = (hi >= upper_p) and (lo <= upper_p)
            if is_first_band and open_on_lower:
                lo_hit = (lo < lower_p - EPS) and (hi >= lower_p)
            else:
                lo_hit = (lo <= lower_p) and (hi >= lower_p)
            if up_hit and lo_hit:
                outcome = "amb"
                hit_bar = i
                break
            if up_hit:
                if side == "up":
                    outcome = "cont"
                elif side == "down":
                    outcome = "retr"
                else:
                    outcome = "up"
                hit_bar = i
                break
            if lo_hit:
                if side == "down":
                    outcome = "cont"
                elif side == "up":
                    outcome = "retr"
                else:
                    outcome = "down"
                hit_bar = i
                break

        if outcome is None:
            path.append({
                "o": "none",
                "bi": int(lower_idx),
                "side": side,
                "lo": lo_lab,
                "hi": hi_lab,
            })
            break

        elapsed = float((timestamps[hit_bar] - start_ts).astype("timedelta64[s]").astype(np.int64)) / 60.0
        path.append({
            "o": outcome,
            "m": round(elapsed, 3),
            "bi": int(lower_idx),
            "side": side,
            "lo": lo_lab,
            "hi": hi_lab,
        })

        if outcome == "amb":
            break

        touched_upper = outcome in ("up",) or (outcome == "cont" and side == "up") or (outcome == "retr" and side == "down")
        if touched_upper:
            new_lower, new_upper = upper_idx, upper_idx + 1
        else:
            new_lower, new_upper = lower_idx - 1, lower_idx

        if new_lower < 0 or new_upper >= N_PUBLIC:
            break
        lower_idx, upper_idx = new_lower, new_upper
        is_first_band = False
        # Advance past the touch bar: OHLC of one 3-minute bar cannot order
        # multiple sequential adjacent-rung touches, so the next event must
        # come from a later bar. This matches the same-bar ambiguity rule
        # applied at the open: ambiguity only fires within a single band's
        # first-touch evaluation, not across band transitions.
        bar_pos = hit_bar + 1

    return path


def build_payload(df: pd.DataFrame, diag: dict) -> dict:
    days_out: list[dict] = []
    band_counts = [0] * len(BANDS)
    skipped_outside = 0
    skipped_no_open = 0
    n_total_days = 0

    for date, group in df.groupby("date", sort=True):
        n_total_days += 1
        group = group.sort_index()
        # 09:30 bar must be the first bar.
        first_ts = group.index[0]
        if first_ts.hour != 9 or first_ts.minute != 30:
            skipped_no_open += 1
            continue
        prev_close = float(group["prev_close"].iloc[0])
        atr14 = float(group["atr_14"].iloc[0])
        if not (np.isfinite(prev_close) and np.isfinite(atr14) and atr14 > 0):
            skipped_no_open += 1
            continue
        open_price = float(group["open"].iloc[0])
        open_atr = (open_price - prev_close) / atr14
        band_idx = find_band_index(open_atr)
        if band_idx is None:
            skipped_outside += 1
            continue

        rung_prices = [prev_close + m * atr14 for m in PUBLIC_MULTS]

        ts_arr = group.index.values  # numpy datetime64
        highs = group["high"].to_numpy(dtype=float)
        lows = group["low"].to_numpy(dtype=float)
        path = walk_path(ts_arr, highs, lows, open_price, band_idx, rung_prices)
        if not path:
            skipped_no_open += 1
            continue
        band_counts[band_idx] += 1

        date_s = str(date)
        days_out.append({
            "d": date_s,
            "y": int(date_s[:4]),
            "oa": round(open_atr, 4),
            "p": path,
        })

    metadata = {
        "symbol": "SPX",
        "source": diag.get("source"),
        "source_vendor": diag.get("source_vendor"),
        "timezone": diag.get("timezone"),
        "timestamp_convention": diag.get("timestamp_convention"),
        "bar_minutes": diag.get("bar_minutes"),
        "canonical_source_timeframe": diag.get("canonical_source_timeframe"),
        "intraday_start": diag.get("rth_3m_first"),
        "intraday_end": diag.get("rth_3m_last"),
        "daily_start": diag.get("daily_first"),
        "daily_end": diag.get("daily_last"),
        "rth_3m_days": diag.get("rth_3m_days"),
        "n_total_days": n_total_days,
        "n_days_in_bands": len(days_out),
        "n_skipped_outside_public_ladder": skipped_outside,
        "n_skipped_no_open_or_atr": skipped_no_open,
        "year_range": [int(days_out[0]["y"]), int(days_out[-1]["y"])] if days_out else None,
        "available_years": sorted({d["y"] for d in days_out}),
        "band_open_counts": dict(zip(range(len(BANDS)), band_counts)),
        "rth_minutes_total": 390,
        "bar_grid_minutes": list(range(0, 390, 3)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "definitions": {
            "open_band_cohort": "Days whose 09:30 RTH open price, expressed as ATR offset from previous close, falls in [lower_atr, upper_atr).",
            "first_boundary_touch": "The first 3-minute RTH bar after 09:30 (inclusive) whose range contains the band's upper rung price or lower rung price.",
            "continuation": "First boundary touch is on the rung farther from PDC (away from previous close).",
            "retracement": "First boundary touch is on the rung closer to PDC.",
            "ambiguous_same_3min_bar": "The same 3-minute bar's high reaches the upper rung AND its low reaches the lower rung. Direction cannot be ordered; path terminates.",
            "no_first_boundary_touch": "Neither the upper nor the lower rung was touched before the 15:57 bar's close. Path terminates.",
            "cumulative_curve": "At elapsed RTH minute t, cumulative count of days whose first boundary outcome of that type occurred at minute <= t, divided by the original cohort day count. amb and none stay visible as denominator leakage.",
        },
    }

    return {
        "metadata": metadata,
        "bands": BANDS,
        "ladder": [
            {"label": PUBLIC_LABELS[i], "atr": PUBLIC_MULTS[i]} for i in range(N_PUBLIC)
        ],
        "days": days_out,
    }


def run() -> dict:
    print("Loading FirstRateData SPX 1-minute + daily data ...")
    df, diag = load_spx()
    print(f"  {diag['rth_3m_days']:,} RTH days, {diag['rth_3m_rows']:,} 3-min bars")
    payload = build_payload(df, diag)
    with JSON_OUT.open("w") as f:
        json.dump(payload, f, separators=(",", ":"))
    size_kb = JSON_OUT.stat().st_size / 1024.0
    print(f"Wrote {JSON_OUT} ({size_kb:.1f} KB)")
    md = payload["metadata"]
    print(f"  days_in_bands={md['n_days_in_bands']:,}  outside_public_ladder={md['n_skipped_outside_public_ladder']:,}  skipped_no_open={md['n_skipped_no_open_or_atr']:,}")
    return payload


def main() -> None:
    run()


if __name__ == "__main__":
    main()

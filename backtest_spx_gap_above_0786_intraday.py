"""
Gap-up above +0.786 ATR -- intraday ATR progress by time of day.
================================================================

Widens the rare "+1 ATR gap" universe (see backtest_spx_gap_above_full_atr.py)
by lowering the opening threshold to the +0.786 ATR level, then tracks how the
day *progresses* in ATR units bar-by-bar (10-minute) rather than only at the
close.

Setup (universe): the session OPEN is at or above +0.786 ATR (a strong gap up).
Hold condition: every 10-minute RTH close stays at/above +0.786 ATR (price never
gives back, on a closing basis, the level it gapped above).

For each qualifying day we record a 10-minute trajectory:
  - close_atr     : the bar close in ATR units above PDC
  - runmax_atr    : the running session high so far in ATR units ("progress")
  - holding       : is this bar's close still >= +0.786 ATR?
We aggregate these across days by clock time (09:30 ... 15:50), splitting
HOLDERS vs NON-HOLDERS, to show the median ATR path of each branch through
the day. End-of-day peak / extension / close stats are reported alongside.

Data: SPX (FirstRateData 1m->10m, 2008->2026) primary; SPY (spy.db ind_10m,
2000->2026) cross-check. Levels = prior daily close + one-session-lagged daily
Wilder ATR(14). Timestamps ET (12pm Central = 1:00pm ET).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_gap_above_full_atr import (
    EXT_LABEL,
    EXT_LEVELS,
    load_spx_10m,
    load_spy_10m,
)

BASE_DIR = Path(__file__).resolve().parent
OUT_JSON = BASE_DIR / "site" / "data" / "spx-gap-above-0786-intraday.json"
OUT_CSV = BASE_DIR / "analyst" / "spx_gap_above_0786_events.csv"
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

OPEN_THRESHOLD = 0.786   # gap-up universe: open >= +0.786 ATR
HOLD_LEVEL = 0.786       # hold: every 10m close >= +0.786 ATR

# 10-minute RTH clock grid (left-labeled bars; 15:50 covers 15:50-16:00).
GRID = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 10, 20, 30, 40, 50)]
GRID = [t for t in GRID if "09:30" <= t <= "15:50"]


def analyze_day(g: pd.DataFrame):
    """Return (day_summary, [per-bar trajectory rows]) if the day opens >= the
    threshold, else (None, None)."""
    first = g.iloc[0]
    pdc, atr = first["prev_close"], first["atr_14"]
    open_atr = (first["open"] - pdc) / atr
    if open_atr < OPEN_THRESHOLD:
        return None, None

    hold_lvl_px = pdc + HOLD_LEVEL * atr
    held = bool((g["close"] >= hold_lvl_px).all())

    day_high = g["high"].max()
    close_px = g.iloc[-1]["close"]
    summary = {
        "date": str(g.index[0].date()),
        "open_atr": open_atr,
        "held": held,
        "peak_atr": (day_high - pdc) / atr,
        "trough_atr": (g["low"].min() - pdc) / atr,
        "close_atr": (close_px - pdc) / atr,
        "close_ge_open": close_px >= first["open"],
    }
    for name in EXT_LEVELS:
        summary[f"hit_{name}"] = bool(day_high >= first[f"up_{name}"])

    runmax = g["high"].cummax()
    rows = [{
        "date": summary["date"],
        "t": f"{ts.hour:02d}:{ts.minute:02d}",
        "held": held,
        "close_atr": (c - pdc) / atr,
        "runmax_atr": (rm - pdc) / atr,
        "holding_now": c >= hold_lvl_px,
    } for ts, c, rm in zip(g.index, g["close"], runmax)]
    return summary, rows


def q(s, p):
    return round(float(s.quantile(p)), 3) if len(s) else None


def trajectory(bars: pd.DataFrame):
    """Median/quartile ATR path by clock time over the 10-minute grid."""
    out = []
    for t in GRID:
        sub = bars[bars["t"] == t]
        if len(sub) == 0:
            continue
        out.append({
            "t": t,
            "n": int(len(sub)),
            "close_atr_p25": q(sub["close_atr"], 0.25),
            "close_atr_median": q(sub["close_atr"], 0.50),
            "close_atr_p75": q(sub["close_atr"], 0.75),
            "runmax_atr_median": q(sub["runmax_atr"], 0.50),
            "pct_holding": round(float(sub["holding_now"].mean()) * 100, 1),
        })
    return out


def end_stats(ev: pd.DataFrame):
    n = len(ev)
    if n == 0:
        return {"n": 0}
    out = {
        "n": n,
        "open_atr_median": q(ev["open_atr"], 0.50),
        "peak_atr_median": q(ev["peak_atr"], 0.50),
        "peak_atr_p25": q(ev["peak_atr"], 0.25),
        "peak_atr_p75": q(ev["peak_atr"], 0.75),
        "trough_atr_median": q(ev["trough_atr"], 0.50),
        "close_atr_median": q(ev["close_atr"], 0.50),
        "close_ge_open": round(float(ev["close_ge_open"].mean()) * 100, 1),
    }
    for name in EXT_LEVELS:
        out[f"hit_{name}"] = round(float(ev[f"hit_{name}"].mean()) * 100, 1)
    return out


def run_dataset(name: str, df: pd.DataFrame):
    n_sessions = df["date"].nunique()
    summaries, allbars = [], []
    for _, g in df.groupby("date", sort=True):
        s, rows = analyze_day(g)
        if s is not None:
            summaries.append(s)
            allbars.extend(rows)
    ev = pd.DataFrame(summaries)
    bars = pd.DataFrame(allbars)

    n_uni = len(ev)
    holders = ev[ev["held"]]
    nonhold = ev[~ev["held"]]
    bars_h = bars[bars["held"]] if len(bars) else bars
    bars_n = bars[~bars["held"]] if len(bars) else bars

    print(f"\n{'#' * 80}\n# {name}: {n_sessions:,} sessions "
          f"({df.index.min().date()} -> {df.index.max().date()})\n{'#' * 80}")
    print(f"  Gap-up open >= +{OPEN_THRESHOLD} ATR (universe)   {n_uni:5d}  "
          f"({n_uni / n_sessions * 100:.2f}% of sessions)")
    print(f"  ...HELD +{HOLD_LEVEL} ATR (no 10m close below)    {len(holders):5d}  "
          f"({len(holders) / n_uni * 100:.1f}% of universe)")
    print(f"  ...did NOT hold                            {len(nonhold):5d}  "
          f"({len(nonhold) / n_uni * 100:.1f}% of universe)")

    for tag, sub in [("HELD", holders), ("did NOT hold", nonhold), ("all", ev)]:
        s = end_stats(sub)
        if s["n"] == 0:
            continue
        exts = "  ".join(f"{EXT_LABEL[x]} {s['hit_'+x]}%" for x in EXT_LEVELS)
        print(f"\n  [{tag}] n={s['n']}  open {s['open_atr_median']:+.3f}  "
              f"PEAK {s['peak_atr_median']:+.3f} [p25 {s['peak_atr_p25']:+.3f}, "
              f"p75 {s['peak_atr_p75']:+.3f}]  trough {s['trough_atr_median']:+.3f}  "
              f"CLOSE {s['close_atr_median']:+.3f}  close>=open {s['close_ge_open']}%")
        print(f"        ext (intraday high): {exts}")

    # Time-of-day ATR trajectory (the headline of this study).
    traj_h = trajectory(bars_h)
    traj_n = trajectory(bars_n)
    traj_all = trajectory(bars)

    print(f"\n  --- ATR progress by time of day (median bar close, ATR units) ---")
    print(f"  {'time':<6} {'HELD':>16} {'NOTHELD':>16} {'ALL':>16}")
    print(f"  {'':<6} {'n  med(p25-p75)':>16} {'n  med':>16} {'n  med':>16}")
    th = {r["t"]: r for r in traj_h}
    tn = {r["t"]: r for r in traj_n}
    ta = {r["t"]: r for r in traj_all}
    for t in GRID:
        if t not in ta:
            continue
        h, nn, a = th.get(t), tn.get(t), ta.get(t)
        hs = (f"{h['n']:>3} {h['close_atr_median']:+.2f}({h['close_atr_p25']:+.2f}-{h['close_atr_p75']:+.2f})"
              if h else "")
        ns = f"{nn['n']:>3} {nn['close_atr_median']:+.2f}" if nn else ""
        as_ = f"{a['n']:>3} {a['close_atr_median']:+.2f}" if a else ""
        print(f"  {t:<6} {hs:>16} {ns:>16} {as_:>16}")

    return {
        "n_sessions": int(n_sessions),
        "date_start": str(df.index.min().date()),
        "date_end": str(df.index.max().date()),
        "n_universe": n_uni,
        "n_held": int(len(holders)),
        "n_not_held": int(len(nonhold)),
        "end_stats": {"held": end_stats(holders),
                      "not_held": end_stats(nonhold),
                      "universe": end_stats(ev)},
        "trajectory": {"held": traj_h, "not_held": traj_n, "universe": traj_all},
    }, ev


def main():
    print("Loading SPX 1m->10m ...", flush=True)
    spx = load_spx_10m()
    print("Loading SPY 10m from spy.db ...", flush=True)
    spy = load_spy_10m()

    payload = {
        "meta": {
            "primary": "SPX",
            "open_threshold_atr": OPEN_THRESHOLD,
            "hold_level_atr": HOLD_LEVEL,
            "source_spx": "FirstRateData SPX index 1-minute RTH -> 10-minute",
            "source_spy": "spy.db ind_10m (SPY ETF cross-check / longer history)",
            "tz_note": "Timestamps ET; 12pm Central = 1:00pm ET",
        },
    }
    payload["SPX"], spx_ev = run_dataset("SPX", spx)
    payload["SPY"], _ = run_dataset("SPY (cross-check)", spy)

    spx_ev.to_csv(OUT_CSV, index=False)
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_CSV}  ({len(spx_ev)} SPX gap-up>=+{OPEN_THRESHOLD} events)")


if __name__ == "__main__":
    main()

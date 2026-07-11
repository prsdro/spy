"""
SPX gap-up to +1 ATR that holds the full-ATR line -- "how far does it go?"
==========================================================================

Hypothesis / question:
  When SPX *gaps up* and opens at or just above the +1 ATR (full daily ATR)
  level, and then *never has a 10-minute close below +1 ATR* through the RTH
  session -- how far does it tend to extend, and where does it close?

Saty terminology:
  - +1 ATR / "full ATR" = prior daily close + 100% of the daily Wilder ATR(14).
  - Extension levels above the full ATR: +123.6%, +161.8%, +200%, +261.8%, +300%.

Setup (a "gap-and-hold above full ATR" day):
  1. The session OPEN is at or just above +1 ATR. We parametrize the band; the
     headline band is [+1.000 ATR, +1.236 ATR) -- opened right at / just past
     the full-ATR line, not already extended out to the next Fib.
  2. The HOLD condition: every 10-minute RTH bar closes at or above +1 ATR
     (price never gives back the full-ATR level on a closing basis).

For the qualifying ("holder") days we measure, from PDC in ATR units:
  - the intraday peak high (how far it goes),
  - extension-level hit rates (+123.6% ... +300%),
  - the RTH close location.

We also report the full gap-up-to-+1-ATR universe split into HOLDERS vs
NON-HOLDERS (closed below +1 ATR at some point) so the hold condition can be
evaluated as a filter: does holding the full-ATR line predict more upside?

Data: FirstRateData SPX index, 1-minute RTH bars (2008-01 -> 2026-05),
resampled to 10-minute bars (label-left, 09:30-aligned). Levels from prior
daily close + one-session-lagged daily Wilder ATR(14) -- identical convention
to the other SPX studies in this repo.
Timezone note: timestamps are ET; 12pm Central = 1:00pm ET.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import (
    atr_series,
    find_one,
    read_firstrate_zip,
)

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "spx_gap_above_full_atr_events.csv"
OUT_JSON = BASE_DIR / "site" / "data" / "spx-gap-above-full-atr.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

# Fib-scaled level multipliers (fraction of daily ATR away from PDC).
LEVELS = {
    "trig": 0.236,
    "0382": 0.382,
    "0618": 0.618,
    "0786": 0.786,
    "100": 1.000,
    "1236": 1.236,
    "1618": 1.618,
    "200": 2.000,
    "2618": 2.618,
    "300": 3.000,
}
# Upside extension levels reported as "how far it goes".
EXT_LEVELS = ["1236", "1618", "200", "2618", "300"]
EXT_LABEL = {
    "1236": "+123.6%",
    "1618": "+161.8%",
    "200": "+200%",
    "2618": "+261.8%",
    "300": "+300%",
}


def load_spx_10m() -> pd.DataFrame:
    """SPX 10-minute RTH bars with daily-reference ATR levels (incl. extensions)."""
    intra = read_firstrate_zip(find_one("SPX_full_1min_*.zip"), intraday=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)

    daily["date"] = daily["timestamp"].dt.date
    daily["atr_14"] = atr_series(daily, 14).shift(1)  # one-session-lagged
    daily["prev_close"] = daily["close"].shift(1)
    lookup = daily.set_index("date")[["prev_close", "atr_14"]]

    intra = intra.set_index("timestamp").sort_index()
    intra = intra.between_time("09:30", "15:59")

    # Resample 1-minute -> 10-minute (RTH bins are 09:30-aligned since 09:30 is
    # an exact multiple of 10 minutes from midnight). Drop empty bins.
    bars = intra.resample("10min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna(subset=["open"])
    bars = bars.between_time("09:30", "15:59")

    bars["date"] = bars.index.date
    bars = bars.join(lookup, on="date")
    bars = bars.dropna(subset=["prev_close", "atr_14"])
    bars = bars[bars["atr_14"] > 0]

    pc, atr = bars["prev_close"], bars["atr_14"]
    for name, mult in LEVELS.items():
        bars[f"up_{name}"] = pc + mult * atr
    return bars


def load_spy_10m() -> pd.DataFrame:
    """SPY 10-minute RTH bars from spy.db, normalized to the same column names
    (up_100, up_1236, ...) used by the SPX loader so analyze_day works on both."""
    conn = sqlite3.connect(BASE_DIR / "spy.db")
    name_map = {  # spy.db column -> our level key
        "atr_upper_trigger": "trig", "atr_upper_0382": "0382",
        "atr_upper_0618": "0618", "atr_upper_0786": "0786", "atr_upper_100": "100",
        "atr_upper_1236": "1236", "atr_upper_1618": "1618", "atr_upper_200": "200",
        "atr_upper_2618": "2618", "atr_upper_300": "300",
    }
    cols = ", ".join(["timestamp", "open", "high", "low", "close",
                      "prev_close", "atr_14", *name_map.keys()])
    df = pd.read_sql_query(f"SELECT {cols} FROM ind_10m ORDER BY timestamp",
                           conn, parse_dates=["timestamp"])
    conn.close()
    df = df.set_index("timestamp").sort_index().between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df = df[df["atr_14"] > 0]
    df = df.rename(columns={k: f"up_{v}" for k, v in name_map.items()})
    df["date"] = df.index.date
    return df


def analyze_day(g: pd.DataFrame, band_lo: float, band_hi: float):
    """Classify one session. Returns a record dict if it is a gap-up-to-+1-ATR
    day (open in [band_lo, band_hi) ATR), else None."""
    first = g.iloc[0]
    pdc, atr = first["prev_close"], first["atr_14"]
    open_px = first["open"]
    open_atr = (open_px - pdc) / atr

    # Gap-up requirement: the open lands in the +1 ATR band.
    if not (band_lo <= open_atr < band_hi):
        return None

    full_atr_lvl = first["up_100"]

    # HOLD condition: every 10-minute close stays at/above +1 ATR.
    held = bool((g["close"] >= full_atr_lvl).all())

    day_high = g["high"].max()
    day_low = g["low"].min()
    close_px = g.iloc[-1]["close"]
    peak_atr = (day_high - pdc) / atr
    trough_atr = (day_low - pdc) / atr
    close_atr = (close_px - pdc) / atr
    peak_close_atr = (g["close"].max() - pdc) / atr

    rec = {
        "date": str(g.index[0].date()),
        "pdc": pdc,
        "atr_14": atr,
        "open_atr": open_atr,
        "held": held,
        "peak_atr": peak_atr,
        "trough_atr": trough_atr,
        "peak_close_atr": peak_close_atr,
        "close_atr": close_atr,
        "close_ge_open": close_px >= open_px,
        "n_bars": int(len(g)),
        "n_closes_below_full": int((g["close"] < full_atr_lvl).sum()),
    }
    # Extension-level reach (intraday high).
    for name in EXT_LEVELS:
        rec[f"hit_{name}"] = bool(day_high >= first[f"up_{name}"])
    return rec


def rate(sub: pd.DataFrame, col: str):
    return round(float(sub[col].mean()) * 100, 1) if len(sub) else None


def q(s: pd.Series, p: float):
    return round(float(s.quantile(p)), 3) if len(s) else None


def summarize(ev: pd.DataFrame):
    n = len(ev)
    if n == 0:
        return {"n": 0}
    out = {
        "n": n,
        "open_atr_median": q(ev["open_atr"], 0.50),
        "peak_atr_median": q(ev["peak_atr"], 0.50),
        "peak_atr_p25": q(ev["peak_atr"], 0.25),
        "peak_atr_p75": q(ev["peak_atr"], 0.75),
        "peak_atr_max": round(float(ev["peak_atr"].max()), 3),
        "trough_atr_median": q(ev["trough_atr"], 0.50),
        "trough_atr_min": round(float(ev["trough_atr"].min()), 3),
        "close_atr_median": q(ev["close_atr"], 0.50),
        "close_atr_p25": q(ev["close_atr"], 0.25),
        "close_atr_p75": q(ev["close_atr"], 0.75),
        "close_ge_open": rate(ev, "close_ge_open"),
    }
    for name in EXT_LEVELS:
        out[f"hit_{name}"] = rate(ev, f"hit_{name}")
    return out


def show(tag, s):
    if s["n"] == 0:
        print(f"  [{tag}] n=0")
        return
    print(f"\n  [{tag}]  n={s['n']}")
    print(f"    open  (ATR): median {s['open_atr_median']:+.3f}")
    print(f"    PEAK  high (ATR): median {s['peak_atr_median']:+.3f}  "
          f"[p25 {s['peak_atr_p25']:+.3f}, p75 {s['peak_atr_p75']:+.3f}]  "
          f"max {s['peak_atr_max']:+.3f}")
    print(f"    trough low (ATR): median {s['trough_atr_median']:+.3f}  "
          f"min {s['trough_atr_min']:+.3f}")
    print(f"    CLOSE     (ATR): median {s['close_atr_median']:+.3f}  "
          f"[p25 {s['close_atr_p25']:+.3f}, p75 {s['close_atr_p75']:+.3f}]  "
          f"close>=open {s['close_ge_open']}%")
    exts = "  ".join(f"{EXT_LABEL[name]} {s['hit_'+name]}%" for name in EXT_LEVELS)
    print(f"    extension hit-rate (intraday high):  {exts}")


def run_dataset(name: str, df: pd.DataFrame):
    """Run the band sweep for one dataset. Returns (payload_block, headline_ev)."""
    n_sessions = df["date"].nunique()
    print(f"\n{'#' * 78}\n# {name}: {len(df):,} RTH 10m bars across {n_sessions:,} "
          f"sessions ({df.index.min().date()} -> {df.index.max().date()})\n{'#' * 78}")

    bands = {
        "headline [1.000, 1.236)": (1.000, 1.236),
        "tight    [1.000, 1.100)": (1.000, 1.100),
        "wide     [1.000, inf)  ": (1.000, np.inf),
    }

    block = {"n_sessions": int(n_sessions),
             "date_start": str(df.index.min().date()),
             "date_end": str(df.index.max().date()),
             "bands": {}}
    headline_ev = None

    for label, (lo, hi) in bands.items():
        recs = [r for _, g in df.groupby("date", sort=True)
                if (r := analyze_day(g, lo, hi)) is not None]
        ev = pd.DataFrame(recs)
        n_uni = len(ev)
        holders = ev[ev["held"]] if n_uni else ev
        nonhold = ev[~ev["held"]] if n_uni else ev

        print("\n" + "=" * 78)
        print(f"{name}  GAP-UP OPEN IN BAND  {label}   (open ATR band: [{lo}, {hi}))")
        print("=" * 78)
        print(f"  Gap-up-to-+1ATR days (universe)        {n_uni:5d}  "
              f"({n_uni / n_sessions * 100:.2f}% of sessions)")
        if n_uni == 0:
            block["bands"][label.strip()] = {"n_universe": 0}
            continue
        n_hold = len(holders)
        print(f"  ...HELD +1 ATR (no 10m close below)    {n_hold:5d}  "
              f"({n_hold / n_uni * 100:.1f}% of universe)")
        print(f"  ...did NOT hold                        {len(nonhold):5d}  "
              f"({len(nonhold) / n_uni * 100:.1f}% of universe)")

        s_hold, s_non, s_uni = summarize(holders), summarize(nonhold), summarize(ev)
        show("HELD +1 ATR", s_hold)
        show("did NOT hold", s_non)
        show("all gap-up days", s_uni)

        block["bands"][label.strip()] = {
            "band": [lo, None if hi == np.inf else hi],
            "n_universe": n_uni, "n_held": n_hold, "n_not_held": int(len(nonhold)),
            "held": s_hold, "not_held": s_non, "universe": s_uni,
        }
        if lo == 1.000 and hi == 1.236:
            headline_ev = ev.copy()
    return block, headline_ev


def main():
    print("Loading FirstRateData SPX 1-minute -> 10-minute bars ...", flush=True)
    spx = load_spx_10m()
    print("Loading SPY 10-minute bars from spy.db ...", flush=True)
    spy = load_spy_10m()

    payload = {
        "meta": {
            "primary": "SPX",
            "source_spx": "FirstRateData SPX index, 1-minute RTH resampled to 10-minute",
            "source_spy": "spy.db ind_10m (SPY ETF, cross-check / longer history)",
            "tz_note": "Timestamps ET; 12pm Central = 1:00pm ET",
            "definitions": {
                "gap_up_open": "session open in the +1 ATR band (ATR units above PDC)",
                "hold": "every 10-minute RTH close >= +1 ATR (full-ATR line)",
                "atr": "prior daily close + multiple of one-session-lagged daily Wilder ATR(14)",
            },
        },
    }

    spx_block, headline_ev = run_dataset("SPX", spx)
    spy_block, _ = run_dataset("SPY (cross-check)", spy)
    payload["SPX"] = spx_block
    payload["SPY"] = spy_block

    if headline_ev is not None:
        headline_ev.to_csv(OUT_CSV, index=False)
        h = headline_ev[headline_ev["held"]].copy()
        payload["spx_headline_holder_events"] = [
            {"date": r["date"], "open_atr": round(r["open_atr"], 3),
             "peak_atr": round(r["peak_atr"], 3), "close_atr": round(r["close_atr"], 3)}
            for _, r in h.iterrows()
        ]

    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote {OUT_JSON}")
    if headline_ev is not None:
        print(f"Wrote {OUT_CSV}  ({len(headline_ev)} SPX headline-band events)")


if __name__ == "__main__":
    main()

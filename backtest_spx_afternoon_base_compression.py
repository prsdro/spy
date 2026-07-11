"""
Afternoon "base" via 3-minute compression -> flush or pump?
===========================================================

Trader question (Pedro):
  Is there edge in playing the "afternoon pump"? It happens when SPX finds a
  *base* in the afternoon -- typically by going into 3-minute compression around
  a key Saty level (or between two levels). We look for afternoon sessions with
  a run of at least ten consecutive 3-minute candles in compression. When this
  base forms in the zone between the PUT TRIGGER (-0.236 ATR) and -1 ATR (or at
  levels in between), does price FLUSH (break down) or PUMP (break up), and how
  big is the move?

Definitions (Saty system, Day-trading ATR mode):
  - Levels = prior daily close (PDC) + Fib multiple of the one-session-lagged
    daily Wilder ATR(14). Put trigger = PDC - 0.236*ATR; -1 ATR = PDC - 1.000*ATR.
  - Compression = Saty Pivot-Ribbon Bollinger/Keltner squeeze flag, computed on
    the *continuous* 3-minute close series (same logic as indicators.py /
    TradingView, EMAs do not reset at the day boundary).
  - A "base" = a run of >= MIN_BASE_BARS consecutive 3m bars with compression=1
    (allowing a single 1-bar flicker, GAP_TOLERANCE=1) whose run STARTS in the
    afternoon (>= AFTERNOON_START_ET). One base per run; we take the FIRST
    qualifying afternoon base per session (the first time the session sets up).

Base location:
  base_high / base_low = high/low range during the compression run.
  base_mid  = (base_high + base_low) / 2.
  We express base_mid in ATR units from PDC and bucket it into Saty zones; the
  zone of interest is the downside trigger -> -1 ATR region.

Outcome ("flush or pump"), measured from the END of the base (the bar after the
compression run finishes) forward to the RTH close:
  - break direction: the FIRST 3m bar whose high > base_high (PUMP) or whose
    low < base_low (FLUSH). Whichever edge breaks first labels the resolution.
  - pump_mfe  = (max high after base - base_mid) / ATR   (max favorable up)
  - flush_mfe = (base_mid - min low after base) / ATR    (max adverse down)
  - net_close = (RTH close - base_mid) / ATR
  - continuation beyond the broken edge, in ATR units.

Data: FirstRateData SPX index, 1-minute RTH bars resampled to 3-minute
(label-left, 09:30-aligned), 2008-01 -> 2026. SPY (spy.db, 2000->2026) is run as
a longer-history cross-check using the identical pipeline.
Timezone: source timestamps are ET. Pedro is Central (CT = ET - 1h). 12:00 ET =
11:00 CT; 13:00 ET = 12:00 CT ("noon Central"). Labels below are ET.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import atr_series, find_one, read_firstrate_zip
from indicators import compute_pivot_ribbon

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "spx_afternoon_base_events.csv"
OUT_JSON = BASE_DIR / "site" / "data" / "spx-afternoon-base-compression.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

# ── Parameters ──
MIN_BASE_BARS = 10          # >= ten 3m compression candles (30 minutes)
GAP_TOLERANCE = 1           # allow a single 1-bar flicker inside the run
AFTERNOON_START_ET = "12:00"  # base run must START at/after this time (ET)
MIN_BARS_AFTER = 5          # need >= 5 bars (15 min) of room after base to measure

# Downside Saty levels (fraction of daily ATR below PDC).
DN_LEVELS = {
    "trig": 0.236, "0382": 0.382, "0618": 0.618, "0786": 0.786, "100": 1.000,
    "1236": 1.236, "1618": 1.618,
}
UP_LEVELS = {"trig": 0.236, "0382": 0.382, "0618": 0.618, "100": 1.000}


def zone_of(atr_units: float) -> str:
    """Bucket a base_mid (in ATR units from PDC) into a Saty zone label."""
    a = atr_units
    if a >= 0.236:
        return "above +trigger"
    if a > -0.236:
        return "trigger box [-.236,+.236]"
    if a > -0.382:
        return "put-trig -> .382"
    if a > -0.618:
        return ".382 -> .618 (GG)"
    if a > -0.786:
        return ".618 -> .786"
    if a > -1.000:
        return ".786 -> -1 ATR"
    return "below -1 ATR"


# Order zones top-to-bottom for stable reporting.
ZONE_ORDER = [
    "above +trigger",
    "trigger box [-.236,+.236]",
    "put-trig -> .382",
    ".382 -> .618 (GG)",
    ".618 -> .786",
    ".786 -> -1 ATR",
    "below -1 ATR",
]


def find_afternoon_base(g: pd.DataFrame, afternoon_start: str):
    """Return the FIRST qualifying afternoon compression run in session g.

    g is one RTH session of 3m bars with a 'compression' column and a tz-naive
    DatetimeIndex. Returns (start_iloc, end_iloc) inclusive, or None.
    """
    comp = g["compression"].values
    n = len(comp)
    # Build compression runs with 1-bar gap tolerance.
    i = 0
    runs = []  # (start, end) inclusive iloc
    while i < n:
        if comp[i] != 1:
            i += 1
            continue
        start = i
        j = i
        last_on = i
        while j + 1 < n:
            if comp[j + 1] == 1:
                j += 1
                last_on = j
            elif (j + 1 + 1 < n and comp[j + 1] == 0 and comp[j + 2] == 1
                  and (j + 1 - last_on) <= GAP_TOLERANCE):
                # single-bar flicker bridged
                j += 2
                last_on = j
            else:
                break
        runs.append((start, last_on))
        i = last_on + 1

    afternoon_cut = pd.Timestamp(afternoon_start).time()
    for (s, e) in runs:
        run_len = e - s + 1
        if run_len < MIN_BASE_BARS:
            continue
        if g.index[s].time() < afternoon_cut:
            continue
        return (s, e)
    return None


def analyze_session(g: pd.DataFrame, afternoon_start: str):
    """g: one session's 3m bars w/ compression + level columns. Returns rec|None."""
    res = find_afternoon_base(g, afternoon_start)
    if res is None:
        return None
    s, e = res
    pdc = g["prev_close"].iloc[0]
    atr = g["atr_14"].iloc[0]

    run = g.iloc[s:e + 1]
    base_high = run["high"].max()
    base_low = run["low"].min()
    base_mid = (base_high + base_low) / 2.0
    base_atr = (base_mid - pdc) / atr

    after = g.iloc[e + 1:]
    if len(after) < MIN_BARS_AFTER:
        return None

    # Break direction: first bar exceeding an edge.
    break_dir = "none"
    cont_atr = 0.0
    for _, b in after.iterrows():
        up_break = b["high"] > base_high
        dn_break = b["low"] < base_low
        if up_break and dn_break:
            # both in one bar: use close vs base_mid as tiebreak
            break_dir = "pump" if b["close"] >= base_mid else "flush"
            break
        if up_break:
            break_dir = "pump"
            break
        if dn_break:
            break_dir = "flush"
            break

    max_high = after["high"].max()
    min_low = after["low"].min()
    close_px = after["close"].iloc[-1]
    pump_mfe = (max_high - base_mid) / atr
    flush_mfe = (base_mid - min_low) / atr
    net_close = (close_px - base_mid) / atr
    if break_dir == "pump":
        cont_atr = (max_high - base_high) / atr
    elif break_dir == "flush":
        cont_atr = (base_low - min_low) / atr

    rec = {
        "date": str(g.index[0].date()),
        "base_start_et": g.index[s].strftime("%H:%M"),
        "base_end_et": g.index[e].strftime("%H:%M"),
        "base_bars": int(e - s + 1),
        "pdc": round(float(pdc), 4),
        "atr_14": round(float(atr), 4),
        "base_mid": round(float(base_mid), 4),
        "base_atr": round(float(base_atr), 4),
        "base_width_atr": round(float((base_high - base_low) / atr), 4),
        "zone": zone_of(base_atr),
        "break_dir": break_dir,
        "pump_mfe_atr": round(float(pump_mfe), 4),
        "flush_mfe_atr": round(float(flush_mfe), 4),
        "net_close_atr": round(float(net_close), 4),
        "cont_atr": round(float(cont_atr), 4),
        "bars_after": int(len(after)),
    }
    return rec


# --------------------------------------------------------------------------- #
# Dataset loaders -> continuous 3m frame with compression + daily levels
# --------------------------------------------------------------------------- #
def _attach_levels_and_compression(intra_1m: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """intra_1m: 1m bars (timestamp,open,high,low,close). daily: daily OHLC.
    Returns continuous RTH 3m frame with compression + prev_close/atr_14."""
    daily = daily.copy()
    daily["date"] = daily["timestamp"].dt.date
    daily["atr_14"] = atr_series(daily, 14).shift(1)  # one-session-lagged
    daily["prev_close"] = daily["close"].shift(1)
    lookup = daily.set_index("date")[["prev_close", "atr_14"]]

    intra = intra_1m.set_index("timestamp").sort_index().between_time("09:30", "15:59")
    bars = intra.resample("3min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna(subset=["open"])
    bars = bars.between_time("09:30", "15:59")

    # Compression on the continuous 3m series (EMAs run across day boundaries,
    # matching TradingView intraday behavior).
    bars = compute_pivot_ribbon(bars)

    bars["date"] = bars.index.date
    bars = bars.join(lookup, on="date")
    bars = bars.dropna(subset=["prev_close", "atr_14"])
    bars = bars[bars["atr_14"] > 0]
    return bars


def load_spx_3m() -> pd.DataFrame:
    intra = read_firstrate_zip(find_one("SPX_full_1min_*.zip"), intraday=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
    return _attach_levels_and_compression(intra, daily)


def load_spy_3m() -> pd.DataFrame:
    conn = sqlite3.connect(BASE_DIR / "spy.db")
    intra = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM candles_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"])
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM candles_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"])
    conn.close()
    return _attach_levels_and_compression(intra, daily)


# --------------------------------------------------------------------------- #
# Aggregation / reporting
# --------------------------------------------------------------------------- #
def q(s, p):
    return round(float(s.quantile(p)), 3) if len(s) else None


def med(s):
    return round(float(s.median()), 3) if len(s) else None


def summarize_group(ev: pd.DataFrame) -> dict:
    n = len(ev)
    if n == 0:
        return {"n": 0}
    n_pump = int((ev["break_dir"] == "pump").sum())
    n_flush = int((ev["break_dir"] == "flush").sum())
    n_none = int((ev["break_dir"] == "none").sum())
    pumps = ev[ev["break_dir"] == "pump"]
    flushes = ev[ev["break_dir"] == "flush"]
    return {
        "n": n,
        "pump_pct": round(n_pump / n * 100, 1),
        "flush_pct": round(n_flush / n * 100, 1),
        "none_pct": round(n_none / n * 100, 1),
        "base_atr_median": med(ev["base_atr"]),
        "pump_mfe_median": med(ev["pump_mfe_atr"]),
        "flush_mfe_median": med(ev["flush_mfe_atr"]),
        "net_close_median": med(ev["net_close_atr"]),
        "net_close_p25": q(ev["net_close_atr"], 0.25),
        "net_close_p75": q(ev["net_close_atr"], 0.75),
        "net_close_mean": round(float(ev["net_close_atr"].mean()), 3),
        # conditional continuation after the break, in ATR
        "pump_cont_median": med(pumps["cont_atr"]) if n_pump else None,
        "flush_cont_median": med(flushes["cont_atr"]) if n_flush else None,
        "pump_net_median": med(pumps["net_close_atr"]) if n_pump else None,
        "flush_net_median": med(flushes["net_close_atr"]) if n_flush else None,
    }


def print_summary(tag, s):
    if s["n"] == 0:
        print(f"  [{tag}] n=0")
        return
    print(f"  [{tag}]  n={s['n']:4d}   base@ {s['base_atr_median']:+.3f} ATR")
    print(f"      resolve:  PUMP {s['pump_pct']:.0f}%   FLUSH {s['flush_pct']:.0f}%"
          f"   (no break {s['none_pct']:.0f}%)")
    print(f"      excursion (ATR): pump-MFE {s['pump_mfe_median']:+.3f}   "
          f"flush-MFE {s['flush_mfe_median']:+.3f}")
    print(f"      net close (ATR): median {s['net_close_median']:+.3f}  "
          f"mean {s['net_close_mean']:+.3f}  [p25 {s['net_close_p25']:+.3f}, "
          f"p75 {s['net_close_p75']:+.3f}]")
    pc = s["pump_cont_median"]
    fc = s["flush_cont_median"]
    pn = s["pump_net_median"]
    fn = s["flush_net_median"]
    print(f"      after break:  pump->cont {pc if pc is None else f'{pc:+.3f}'} / "
          f"net {pn if pn is None else f'{pn:+.3f}'}    "
          f"flush->cont {fc if fc is None else f'{fc:+.3f}'} / "
          f"net {fn if fn is None else f'{fn:+.3f}'}  (ATR)")


def near_level(ev: pd.DataFrame, target_atr: float, tol: float = 0.12) -> pd.DataFrame:
    return ev[(ev["base_atr"] - target_atr).abs() <= tol]


def run_dataset(name: str, df: pd.DataFrame) -> dict:
    n_sessions = df["date"].nunique()
    print(f"\n{'#'*78}\n# {name}: {len(df):,} RTH 3m bars across {n_sessions:,} sessions "
          f"({df.index.min().date()} -> {df.index.max().date()})\n{'#'*78}")

    recs = []
    for _, g in df.groupby("date", sort=True):
        r = analyze_session(g, AFTERNOON_START_ET)
        if r is not None:
            recs.append(r)
    ev = pd.DataFrame(recs)
    n = len(ev)
    print(f"\nAfternoon bases (>= {MIN_BASE_BARS} 3m compression bars, run starts "
          f">= {AFTERNOON_START_ET} ET): {n}  "
          f"({n / n_sessions * 100:.1f}% of sessions)")
    if n == 0:
        return {"n_sessions": int(n_sessions), "n_events": 0}

    print("\n--- ALL afternoon bases ---")
    base_s = summarize_group(ev)
    print_summary("all bases", base_s)

    print("\n--- by Saty zone where the base sits ---")
    zone_blocks = {}
    for z in ZONE_ORDER:
        sub = ev[ev["zone"] == z]
        if len(sub) == 0:
            continue
        s = summarize_group(sub)
        zone_blocks[z] = s
        print_summary(z, s)

    print("\n--- the headline pair (base centered within +-0.12 ATR of the level) ---")
    pair_blocks = {}
    for lbl, tgt in [("at put trigger (-0.236)", -0.236),
                     ("at -0.5 ATR", -0.5),
                     ("at -0.618 ATR", -0.618),
                     ("at -0.786 ATR", -0.786),
                     ("at -1 ATR (-1.000)", -1.000)]:
        sub = near_level(ev, tgt)
        s = summarize_group(sub)
        pair_blocks[lbl] = s
        print_summary(lbl, s)

    print("\n--- downside bases only (base_mid < -trigger), by time base STARTS ---")
    down = ev[ev["base_atr"] < -0.236]
    tod_blocks = {}
    for lbl, lo, hi in [("12:00-13:00 ET", "12:00", "13:00"),
                        ("13:00-14:00 ET", "13:00", "14:00"),
                        ("14:00-15:00 ET", "14:00", "15:00"),
                        ("15:00+ ET", "15:00", "16:00")]:
        sub = down[(down["base_start_et"] >= lo) & (down["base_start_et"] < hi)]
        s = summarize_group(sub)
        tod_blocks[lbl] = s
        print_summary(lbl, s)

    return {
        "n_sessions": int(n_sessions),
        "n_events": int(n),
        "date_start": str(df.index.min().date()),
        "date_end": str(df.index.max().date()),
        "all": base_s,
        "by_zone": zone_blocks,
        "by_level": pair_blocks,
        "downside_by_tod": tod_blocks,
        "events": ev.to_dict(orient="records") if name.startswith("SPX") else None,
    }


def main():
    print("Loading FirstRateData SPX 1-minute -> 3-minute bars ...", flush=True)
    spx = load_spx_3m()
    print("Loading SPY 3-minute bars from spy.db ...", flush=True)
    spy = load_spy_3m()

    payload = {
        "meta": {
            "primary": "SPX",
            "question": "afternoon 3m-compression base between put trigger and "
                        "-1 ATR -> flush or pump, and how big",
            "params": {
                "min_base_bars": MIN_BASE_BARS,
                "gap_tolerance": GAP_TOLERANCE,
                "afternoon_start_et": AFTERNOON_START_ET,
                "min_bars_after": MIN_BARS_AFTER,
            },
            "source_spx": "FirstRateData SPX index, 1-minute RTH resampled to 3-minute",
            "source_spy": "spy.db candles_3m (SPY ETF) + candles_1d daily ATR",
            "tz_note": "Timestamps ET; CT = ET-1h. 12:00 ET = 11:00 CT.",
            "definitions": {
                "compression": "Saty pivot-ribbon BB/Keltner squeeze on continuous 3m close",
                "base": "first afternoon run of >= min_base_bars 3m compression bars",
                "pump": "first post-base bar high > base range high",
                "flush": "first post-base bar low < base range low",
                "atr": "PDC + Fib * one-session-lagged daily Wilder ATR(14)",
            },
        },
    }
    payload["SPX"] = run_dataset("SPX", spx)
    payload["SPY"] = run_dataset("SPY (cross-check)", spy)

    # CSV of SPX events for inspection.
    spx_ev = payload["SPX"].get("events")
    if spx_ev:
        pd.DataFrame(spx_ev).to_csv(OUT_CSV, index=False)
        print(f"\nWrote {OUT_CSV} ({len(spx_ev)} SPX events)")
    # Trim heavy event lists from SPY in the JSON (keep SPX events for the viz).
    payload["SPY"]["events"] = None

    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
SPX ATR Level Cascade using FirstRateData historical SPX index files.

This is intentionally separate from the live SPY generator. It reads:
  /root/spy/data/SPX_full_1min_*.zip
  /root/spy/data/SPX_full_1day_*.zip

Canonical study input:
  - FirstRateData 1-minute SPX bars, US Eastern, period-start timestamps
  - Aggregated to 3-minute RTH bars (09:30-15:59 -> labels 09:30..15:57)
  - Daily file for previous close and Wilder ATR(14), shifted one session

Outputs:
  site/data/atr-cascade-spx.json
  analyst/atr_cascade_spx_table.csv
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from pathlib import Path

import pandas as pd

from backtest_atr_cascade import (
    COLUMNS,
    HIST_EDGES,
    HIST_LABELS,
    HOUR_BUCKETS,
    LABELS,
    LEVEL_NAMES,
    REPORT_LABELS,
    analyse_adjacent_walk,
    analyse_day,
    analyse_gg_retrace_case,
    aggregate,
    aggregate_gg_retrace,
    build_json_payload,
    print_by_hour_for_level,
    print_overall,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIX_CACHE = DATA_DIR / "VIX_yahoo_daily.csv"
OUT_DIR = BASE_DIR / "analyst"
JSON_OUT = BASE_DIR / "site" / "data" / "atr-cascade-spx.json"
CSV_OUT = OUT_DIR / "atr_cascade_spx_table.csv"
OUT_DIR.mkdir(exist_ok=True)
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)


def _single_zip_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as z:
        members = [i.filename for i in z.infolist() if not i.is_dir()]
    if len(members) != 1:
        raise ValueError(f"Expected exactly one file inside {zip_path}, found {members}")
    return members[0]


def find_one(pattern: str) -> Path:
    matches = sorted(DATA_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matched {DATA_DIR / pattern}")
    if len(matches) > 1:
        # Prefer the largest/newest-looking file only if names collide would be dangerous.
        raise ValueError(f"Multiple files matched {pattern}: {[m.name for m in matches]}")
    return matches[0]


def read_firstrate_zip(zip_path: str | Path, intraday: bool) -> pd.DataFrame:
    """Read a headerless FirstRateData zip/txt file into normalized OHLC columns."""
    zip_path = Path(zip_path)
    member = _single_zip_member(zip_path)
    rows = []
    with zipfile.ZipFile(zip_path) as z:
        with z.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.reader(text):
                if not row:
                    continue
                if len(row) != 5:
                    raise ValueError(f"Unexpected row with {len(row)} columns in {zip_path.name}: {row[:8]}")
                rows.append(row)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    fmt = "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d"
    df["timestamp"] = pd.to_datetime(df["timestamp"], format=fmt)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    return df.sort_values("timestamp").reset_index(drop=True)


def rma(series: pd.Series, period: int = 14) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def atr_series(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    high = daily["high"]
    low = daily["low"]
    prev_close = daily["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return rma(tr, period)


def aggregate_1m_to_3m(intra_1m: pd.DataFrame) -> pd.DataFrame:
    """Filter RTH and aggregate left-labeled 1-minute SPX bars to 3-minute bars."""
    df = intra_1m.set_index("timestamp").sort_index()
    # FirstRateData includes some 16:00+ update bars. The ATR cascade mirrors the
    # SPY 3-minute study and only uses bars whose period starts during RTH.
    df = df.between_time("09:30", "15:59")
    df["date"] = df.index.date

    parts = []
    for _, group in df.groupby("date", sort=True):
        agg = group.resample("3min", origin="start_day", offset="9h30min").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        agg = agg.dropna(subset=["open", "high", "low", "close"])
        # Keep full RTH 3-minute labels only: 09:30 ... 15:57.
        agg = agg.between_time("09:30", "15:57")
        parts.append(agg)
    if not parts:
        raise ValueError("No RTH intraday bars after 1m -> 3m aggregation")
    return pd.concat(parts).sort_index()


def load_spx() -> tuple[pd.DataFrame, dict]:
    intra_zip = find_one("SPX_full_1min_*.zip")
    daily_zip = find_one("SPX_full_1day_*.zip")

    intra_1m = read_firstrate_zip(intra_zip, intraday=True)
    daily = read_firstrate_zip(daily_zip, intraday=False)

    daily["date"] = daily["timestamp"].dt.date
    daily["atr_14_prev"] = atr_series(daily, 14).shift(1)
    daily["prev_close"] = daily["close"].shift(1)
    daily_lookup = daily.set_index("date")[["prev_close", "atr_14_prev"]].rename(columns={"atr_14_prev": "atr_14"})

    intra_3m = aggregate_1m_to_3m(intra_1m)
    intra_3m["date"] = intra_3m.index.date
    intra_3m = intra_3m.join(daily_lookup, on="date")
    intra_3m = intra_3m.dropna(subset=["prev_close", "atr_14"])

    pc = intra_3m["prev_close"]
    atr14 = intra_3m["atr_14"]
    for _, col, mult in __import__("backtest_atr_cascade").LADDER:
        if col == "prev_close":
            continue
        intra_3m[col] = pc + mult * atr14

    keep = ["open", "high", "low", "close", "prev_close", "atr_14"] + [
        c for _, c, _ in __import__("backtest_atr_cascade").LADDER if c != "prev_close"
    ] + ["date"]
    intra_3m = intra_3m[keep]

    counts = intra_3m.groupby("date").size()
    diag = {
        "symbol": "SPX",
        "source_vendor": "FirstRateData",
        "source": "FirstRateData SPX_full_1min + SPX_full_1day historical index dataset",
        "intraday_zip": str(intra_zip),
        "daily_zip": str(daily_zip),
        "canonical_source_timeframe": "1-minute aggregated to 3-minute",
        "timezone": "US Eastern",
        "timestamp_convention": "period-start",
        "bar_minutes": 3,
        "intraday_raw_rows": int(len(intra_1m)),
        "intraday_raw_first": str(intra_1m["timestamp"].min()),
        "intraday_raw_last": str(intra_1m["timestamp"].max()),
        "daily_rows": int(len(daily)),
        "daily_first": str(daily["timestamp"].min().date()),
        "daily_last": str(daily["timestamp"].max().date()),
        "rth_3m_rows": int(len(intra_3m)),
        "rth_3m_days": int(intra_3m["date"].nunique()),
        "rth_3m_first": str(intra_3m.index.min()),
        "rth_3m_last": str(intra_3m.index.max()),
        "bars_per_day_min": int(counts.min()),
        "bars_per_day_median": float(counts.median()),
        "bars_per_day_max": int(counts.max()),
        "full_130_bar_days": int((counts == 130).sum()),
    }
    return intra_3m, diag



def load_vix_daily(start: str = "2008-01-01", end: str | None = None, refresh: bool = False) -> tuple[dict[str, float], dict]:
    """Load daily VIX close values from Yahoo Finance via yfinance, cached locally.

    VIX is a daily regime filter for the ATR cascade. We use the same trading date
    as the SPX RTH session and the daily VIX close as the regime value.
    """
    if refresh or not VIX_CACHE.exists():
        try:
            import yfinance as yf
            df = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False, threads=False)
            if df.empty:
                raise ValueError("Yahoo returned empty ^VIX dataframe")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            out = df.reset_index()[["Date", "Open", "High", "Low", "Close"]].copy()
            out.columns = ["date", "open", "high", "low", "close"]
            out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
            out.to_csv(VIX_CACHE, index=False)
        except Exception as exc:
            if not VIX_CACHE.exists():
                raise RuntimeError(f"Could not fetch ^VIX from Yahoo and no cache exists: {exc}") from exc
    vix = pd.read_csv(VIX_CACHE)
    vix["date"] = pd.to_datetime(vix["date"]).dt.date.astype(str)
    vix["close"] = pd.to_numeric(vix["close"], errors="coerce")
    vix = vix.dropna(subset=["close"])
    mapping = dict(zip(vix["date"], vix["close"].astype(float)))
    diag = {
        "vix_source": "Yahoo Finance ^VIX daily via yfinance, cached locally",
        "vix_cache": str(VIX_CACHE),
        "vix_rows": int(len(vix)),
        "vix_first": str(vix["date"].min()) if len(vix) else None,
        "vix_last": str(vix["date"].max()) if len(vix) else None,
    }
    return mapping, diag

def run() -> dict:
    print("Loading FirstRateData SPX 1-minute + daily data...")
    df, diag = load_spx()
    vix_by_date, vix_diag = load_vix_daily(start=diag["daily_first"])
    diag.update(vix_diag)
    print("  diagnostics:")
    for k, v in diag.items():
        if k.endswith("zip"):
            print(f"    {k}: {Path(v).name}")
        else:
            print(f"    {k}: {v}")

    print("\nProcessing SPX days...")
    all_events = []
    all_paths = []
    adjacent_walks = []
    gg_cases = []
    day_records = []
    for date, group in df.groupby("date", sort=True):
        date_s = str(date)
        year = int(date_s[:4])
        vix_close = vix_by_date.get(date_s)
        ev, seq = analyse_day(group)
        for e in ev:
            e["date"] = date_s
            e["year"] = year
            e["vix"] = vix_close
        all_events.extend(ev)
        if seq:
            all_paths.append(seq)
        walk = analyse_adjacent_walk(group)
        if walk:
            adjacent_walks.append(walk)
        day_records.append({
            "date": date_s,
            "year": year,
            "path": seq or [],
            "walk": walk or [],
            "vix": vix_close,
        })
        for direction in ("call", "put"):
            case = analyse_gg_retrace_case(group, direction)
            if case is not None:
                case["date"] = date_s
                case["year"] = year
                case["vix"] = vix_close
                gg_cases.append(case)

    print(f"  {len(all_events):,} level first-hit events recorded")
    print(f"  {len(all_paths):,} day-sequences captured")
    print(f"  {len(adjacent_walks):,} adjacent walk sequences captured")
    print(f"  {len(gg_cases):,} GG-open retrace/completion cases captured")

    out = aggregate(all_events)
    out.to_csv(CSV_OUT, index=False)
    print(f"\nWrote {CSV_OUT}")

    gg_retrace = aggregate_gg_retrace(gg_cases)
    payload = build_json_payload(
        all_events,
        all_paths,
        out,
        int(df["date"].nunique()),
        gg_retrace=gg_retrace,
        adjacent_walks=adjacent_walks,
    )
    payload["metadata"].update({
        "symbol": "SPX",
        "source": diag["source"],
        "source_vendor": diag["source_vendor"],
        "timezone": diag["timezone"],
        "timestamp_convention": diag["timestamp_convention"],
        "bar_minutes": diag["bar_minutes"],
        "canonical_source_timeframe": diag["canonical_source_timeframe"],
        "intraday_start": diag["rth_3m_first"],
        "intraday_end": diag["rth_3m_last"],
        "daily_start": diag["daily_first"],
        "daily_end": diag["daily_last"],
        "available_years": sorted({r["year"] for r in day_records}),
        "vix_filter": {
            "source": diag.get("vix_source"),
            "field": "VIX daily close",
            "min": round(min(r["vix"] for r in day_records if r.get("vix") is not None), 2),
            "max": round(max(r["vix"] for r in day_records if r.get("vix") is not None), 2),
            "matched_days": sum(1 for r in day_records if r.get("vix") is not None),
        },
        "year_filter_default": {
            "start": min(r["year"] for r in day_records),
            "end": max(r["year"] for r in day_records),
        },
        "loader_diagnostics": diag,
    })

    # Compact raw records let the browser rebuild every visible cohort for an
    # inclusive year range without requesting a different JSON file. Keep the
    # original aggregate cells/hists as the default all-years view.
    public_event_set = set(REPORT_LABELS) - {"PDC"}
    payload["event_records"] = [
        {
            "y": int(e["year"]),
            "l": e["level"],
            "h": e["hour_bucket"],
            "o": e["outcome"],
            "t": None if e.get("time_to_min") is None else round(float(e["time_to_min"]), 3),
            "v": None if e.get("vix") is None else round(float(e["vix"]), 2),
        }
        for e in all_events
        if e.get("level") in public_event_set
    ]
    public_idx = {LABELS.index(lab): REPORT_LABELS.index(lab) for lab in REPORT_LABELS}
    payload["day_records"] = [
        {
            "y": int(r["year"]),
            "path": [public_idx[i] for i in r["path"] if i in public_idx],
            "walk": r["walk"],
            "v": None if r.get("vix") is None else round(float(r["vix"]), 2),
        }
        for r in day_records
    ]
    payload["gg_records"] = [
        {
            "y": int(c["year"]),
            "direction": c["direction"],
            "bucket": c["bucket"],
            "completed": bool(c["completed"]),
            "minutes_to_completion": None if c.get("minutes_to_completion") is None else round(float(c["minutes_to_completion"]), 3),
            "v": None if c.get("vix") is None else round(float(c["vix"]), 2),
        }
        for c in gg_cases
    ]

    with JSON_OUT.open("w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {JSON_OUT} ({JSON_OUT.stat().st_size/1024:.1f} KB)")

    print_overall(out)
    for lab in [l for l in REPORT_LABELS if l != "PDC"]:
        sub = out[(out["level"] == lab) & (out["hour_bucket"] != "ALL")]
        if sub["n"].max() < 20:
            continue
        print_by_hour_for_level(out, lab)
    print("\n* = n < 50 (treat as low-confidence)")
    return payload


def main():
    run()


if __name__ == "__main__":
    main()

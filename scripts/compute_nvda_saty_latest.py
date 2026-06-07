#!/usr/bin/env python3
"""Compute latest Saty Phase Oscillator and ATR Levels for NVDA.

Sources/formulas:
- /root/spy/indicators.py for EMA/RMA/ATR/Phase Oscillator/ATR-level math.
- /root/spy/KNOWLEDGE.md for Saty ATR timeframe mapping.

Output:
- Prints a compact JSON payload.
- With --persist, upserts latest values into /root/spy/spy.db table saty_indicator_latest.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path("/srv/market-data/massive/us_equities")
DB_PATH = Path("/root/spy/spy.db")
OUT_PATH = Path("/root/spy/outputs/nvda_saty_latest.json")
SYMBOL = "NVDA"
FORMULA_SOURCE = "/root/spy/indicators.py"
FORMULA_VERSION = "saty-rma-atr-period_index_1-po-ema21-atr14-ema3-2026-05-09"

sys.path.insert(0, "/root/spy")
from indicators import atr, compute_phase_oscillator  # noqa: E402

OHLCV = ["open", "high", "low", "close", "volume"]
LEVEL_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.236, 1.382, 1.5, 1.618, 1.786, 2.0, 2.236, 2.382, 2.5, 2.618, 2.786, 3.0]
LEVEL_LABELS = {
    0.236: "trigger",
    0.382: "0382",
    0.5: "050",
    0.618: "0618",
    0.786: "0786",
    1.0: "100",
    1.236: "1236",
    1.382: "1382",
    1.5: "150",
    1.618: "1618",
    1.786: "1786",
    2.0: "200",
    2.236: "2236",
    2.382: "2382",
    2.5: "250",
    2.618: "2618",
    2.786: "2786",
    3.0: "300",
}


def clean_float(x: Any, ndigits: int | None = None) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, ndigits) if ndigits is not None else f


def et_index_from_metric_ts_et(s: pd.Series) -> pd.DatetimeIndex:
    # metric_ts_et is like "2026-05-07 19:55:00-0400". Convert through UTC
    # so DST offsets are handled, then strip tz to match /root/spy's naive ET index.
    return pd.DatetimeIndex(pd.to_datetime(s, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None))


def load_parquet_dataset(dataset: str) -> pd.DataFrame:
    files = sorted((ROOT / dataset).glob(f"year=*/{SYMBOL}.parquet"))
    if not files:
        raise FileNotFoundError(f"No {dataset} parquet files for {SYMBOL} under {ROOT}")
    df = pd.concat((pd.read_parquet(p) for p in files), ignore_index=True)
    df = df[df["symbol"] == SYMBOL].copy()
    df["timestamp"] = et_index_from_metric_ts_et(df["metric_ts_et"])
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[OHLCV].astype(float)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return out.dropna(subset=["open", "high", "low", "close"])


def phase_payload(df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    work = compute_phase_oscillator(df.copy())
    latest = work.dropna(subset=["phase_oscillator"]).iloc[-1]
    prev = work.dropna(subset=["phase_oscillator"]).iloc[-2]
    ts = work.dropna(subset=["phase_oscillator"]).index[-1]
    return {
        "symbol": SYMBOL,
        "indicator_family": "phase_oscillator",
        "timeframe": timeframe,
        "bar_timestamp_et": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "close": clean_float(latest["close"], 4),
        "phase_oscillator": clean_float(latest["phase_oscillator"], 4),
        "previous_phase_oscillator": clean_float(prev["phase_oscillator"], 4),
        "slope": clean_float(latest["phase_oscillator"] - prev["phase_oscillator"], 4),
        "phase_zone": str(latest["phase_zone"]),
        "leaving_accumulation": int(latest["leaving_accumulation"]),
        "leaving_distribution": int(latest["leaving_distribution"]),
        "leaving_extreme_down": int(latest["leaving_extreme_down"]),
        "leaving_extreme_up": int(latest["leaving_extreme_up"]),
        "po_compression": int(latest["po_compression"]),
    }


def atr_levels_payload(ref: pd.DataFrame, variant: str, reference_timeframe: str) -> dict[str, Any]:
    ref = ref.copy()
    ref["atr_14_raw"] = atr(ref, 14)
    ref["atr_14"] = ref["atr_14_raw"].shift(1)
    ref["prev_close"] = ref["close"].shift(1)
    latest = ref.dropna(subset=["atr_14", "prev_close"]).iloc[-1]
    current_ts = ref.dropna(subset=["atr_14", "prev_close"]).index[-1]
    prev_period_ts = ref.loc[:current_ts].iloc[-2].name
    pc = float(latest["prev_close"])
    a = float(latest["atr_14"])
    levels: dict[str, float | None] = {}
    for ratio in LEVEL_RATIOS:
        label = LEVEL_LABELS[ratio]
        levels[f"upper_{label}"] = clean_float(pc + ratio * a, 4)
        levels[f"lower_{label}"] = clean_float(pc - ratio * a, 4)
    close = float(latest["close"])
    return {
        "symbol": SYMBOL,
        "indicator_family": "atr_levels",
        "timeframe": variant,
        "reference_timeframe": reference_timeframe,
        "bar_timestamp_et": current_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_period_for_levels": prev_period_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "current_period_close": clean_float(close, 4),
        "prev_close": clean_float(pc, 4),
        "atr_14": clean_float(a, 4),
        "position_atr_multiple": clean_float((close - pc) / a if a else None, 4),
        **levels,
    }


def ensure_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS saty_indicator_latest (
            symbol TEXT NOT NULL,
            indicator_family TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            reference_timeframe TEXT,
            bar_timestamp_et TEXT NOT NULL,
            source_data_root TEXT NOT NULL,
            formula_source TEXT NOT NULL,
            formula_version TEXT NOT NULL,
            values_json TEXT NOT NULL,
            asof_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, indicator_family, timeframe)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_saty_indicator_latest_symbol ON saty_indicator_latest(symbol, indicator_family, timeframe)"
    )


def persist(payload: dict[str, Any]) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict[str, Any]] = []
    for section in ["phase_oscillator", "atr_levels"]:
        for row in payload[section]:
            rows.append(row)
    with sqlite3.connect(DB_PATH) as con:
        ensure_table(con)
        for row in rows:
            con.execute(
                """
                INSERT INTO saty_indicator_latest (
                    symbol, indicator_family, timeframe, reference_timeframe,
                    bar_timestamp_et, source_data_root, formula_source,
                    formula_version, values_json, asof_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, indicator_family, timeframe) DO UPDATE SET
                    reference_timeframe=excluded.reference_timeframe,
                    bar_timestamp_et=excluded.bar_timestamp_et,
                    source_data_root=excluded.source_data_root,
                    formula_source=excluded.formula_source,
                    formula_version=excluded.formula_version,
                    values_json=excluded.values_json,
                    asof_utc=excluded.asof_utc,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    row["symbol"],
                    row["indicator_family"],
                    row["timeframe"],
                    row.get("reference_timeframe"),
                    row["bar_timestamp_et"],
                    str(ROOT),
                    FORMULA_SOURCE,
                    FORMULA_VERSION,
                    json.dumps(row, sort_keys=True),
                    now,
                    now,
                ),
            )
        con.commit()
        count = con.execute(
            "SELECT COUNT(*) FROM saty_indicator_latest WHERE symbol=?", (SYMBOL,)
        ).fetchone()[0]
    return int(count)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persist", action="store_true", help="upsert latest values into spy.db")
    args = ap.parse_args()

    daily = load_parquet_dataset("bars_1d_adjusted")
    five = load_parquet_dataset("bars_5m_adjusted")
    # Match /root/spy/aggregate.py all-hours intraday behavior: keep bars before 20:00 ET.
    five = five[five.index.time < pd.Timestamp("20:00:00").time()]

    weekly = resample_ohlcv(daily, "1W")
    four_h = resample_ohlcv(five, "4h")
    monthly = resample_ohlcv(daily, "ME")
    quarterly = resample_ohlcv(daily, "QE-DEC")
    yearly = resample_ohlcv(daily, "YE-DEC")

    payload: dict[str, Any] = {
        "symbol": SYMBOL,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_data_root": str(ROOT),
        "formula_source": FORMULA_SOURCE,
        "formula_version": FORMULA_VERSION,
        "data_coverage": {
            "daily_first_et": daily.index.min().strftime("%Y-%m-%d %H:%M:%S"),
            "daily_latest_et": daily.index.max().strftime("%Y-%m-%d %H:%M:%S"),
            "daily_rows": int(len(daily)),
            "five_min_first_et": five.index.min().strftime("%Y-%m-%d %H:%M:%S"),
            "five_min_latest_et": five.index.max().strftime("%Y-%m-%d %H:%M:%S"),
            "five_min_rows": int(len(five)),
            "weekly_latest_label_et": weekly.index.max().strftime("%Y-%m-%d %H:%M:%S"),
            "four_h_latest_label_et": four_h.index.max().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "phase_oscillator": [
            phase_payload(daily, "1d"),
            phase_payload(weekly, "1w"),
            phase_payload(four_h, "4h"),
        ],
        "atr_levels": [
            atr_levels_payload(monthly, "swing", "monthly"),
            atr_levels_payload(quarterly, "position", "quarterly"),
            atr_levels_payload(yearly, "long-term", "yearly"),
        ],
        "caveats": [
            "Daily bars are Massive adjusted daily bars, not re-derived from 5m RTH bars.",
            "Weekly/monthly/quarterly/yearly bars are resampled from adjusted daily bars.",
            "4h PO is resampled from adjusted 5m bars using all available bars before 20:00 ET, matching /root/spy aggregate.py all-hours behavior.",
            "Latest local daily data is 2026-05-07; if TradingView has 2026-05-08, values will differ.",
        ],
    }

    # Basic internal checks.
    checks = []
    checks.append({"check": "no_null_latest_phase", "ok": all(x["phase_oscillator"] is not None for x in payload["phase_oscillator"])})
    checks.append({"check": "no_null_latest_atr", "ok": all(x["atr_14"] is not None and x["prev_close"] is not None for x in payload["atr_levels"])})
    checks.append({"check": "all_timeframes_present", "ok": len(payload["phase_oscillator"]) == 3 and len(payload["atr_levels"]) == 3})
    payload["verification"] = checks

    persisted_symbol_rows = None
    if args.persist:
        persisted_symbol_rows = persist(payload)
        payload["persisted"] = {
            "db_path": str(DB_PATH),
            "table": "saty_indicator_latest",
            "symbol_rows_in_table": persisted_symbol_rows,
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

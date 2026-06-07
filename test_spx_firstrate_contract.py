#!/usr/bin/env python3
"""Contract tests for FirstRateData SPX ATR cascade loader/output."""
from pathlib import Path
import json
import tempfile
import zipfile

BASE = Path(__file__).resolve().parent


def test_firstrate_reader_handles_headerless_zip_txt():
    from backtest_atr_cascade_spx_firstrate import read_firstrate_zip
    with tempfile.TemporaryDirectory() as td:
        zpath = Path(td) / "sample.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("sample.txt", "2024-01-02 09:30:00,100,101,99,100.5\r\n2024-01-02 09:31:00,100.5,102,100,101\r\n")
        df = read_firstrate_zip(zpath, intraday=True)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close"]
    assert len(df) == 2
    assert str(df.iloc[0]["timestamp"]) == "2024-01-02 09:30:00"
    assert float(df.iloc[1]["high"]) == 102.0


def test_spx_loader_uses_1min_aggregated_to_3min_rth_and_daily_atr():
    from backtest_atr_cascade_spx_firstrate import load_spx
    df, diag = load_spx()
    assert diag["source_vendor"] == "FirstRateData"
    assert diag["canonical_source_timeframe"] == "1-minute aggregated to 3-minute"
    assert diag["intraday_raw_first"] == "2008-01-02 09:30:00"
    assert diag["daily_first"] == "2000-11-27"
    assert diag["rth_3m_first"] == "2008-01-02 09:30:00"
    assert diag["rth_3m_last"].startswith("2026-05-01 ")
    assert df.index.min().strftime("%H:%M") == "09:30"
    assert df.index.max().strftime("%H:%M") == "15:57"
    assert set(df.index.strftime("%H:%M")).isdisjoint({"16:00", "16:03", "16:20"})
    counts = df.groupby("date").size()
    assert counts.max() <= 130
    assert counts[counts == 130].shape[0] > 3000
    assert df["prev_close"].notna().all()
    assert df["atr_14"].notna().all()


def test_spx_json_metadata_is_separate_from_spy_and_says_firstrate():
    json_path = BASE / "site" / "data" / "atr-cascade-spx.json"
    if not json_path.exists():
        raise AssertionError("Run backtest_atr_cascade_spx_firstrate.py before this contract")
    data = json.loads(json_path.read_text())
    meta = data["metadata"]
    assert meta["symbol"] == "SPX"
    assert "FirstRateData" in meta["source"]
    assert meta["bar_minutes"] == 3
    assert meta["canonical_source_timeframe"] == "1-minute aggregated to 3-minute"
    assert meta["n_days"] >= 4500
    assert meta["n_events_public"] == sum(c["n"] for c in data["cells"] if c["hour_bucket"] == "ALL")


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    if failed:
        raise SystemExit(failed)
    print(f"OK {len(tests)} tests")

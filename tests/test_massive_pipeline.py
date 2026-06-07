from datetime import date
import pandas as pd

from massive_pipeline.splits import normalize_splits, apply_split_adjustment, factor_for_date
from massive_pipeline.atr import atr_series, attach_saty_levels
from massive_pipeline.bars import aggregate_1m_to_3m, utc_to_et_naive
from backtest_atr_cascade import COLUMNS


def test_split_factor_strictly_before_execution_date():
    splits = normalize_splits(pd.DataFrame([
        {"ticker":"FAKE", "execution_date":"2020-08-31", "split_from":1, "split_to":5},
        {"ticker":"FAKE", "execution_date":"2022-08-25", "split_from":1, "split_to":3},
    ]), "FAKE")
    assert factor_for_date(date(2020,8,28), splits) == 15.0
    assert factor_for_date(date(2020,8,31), splits) == 3.0
    assert factor_for_date(date(2022,8,25), splits) == 1.0


def test_apply_split_adjustment_prices_and_volume():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2020-08-28 09:30", "2020-08-31 09:30"]),
        "date": [date(2020,8,28), date(2020,8,31)],
        "open": [100.0, 20.0], "high": [110.0, 22.0], "low": [90.0, 18.0], "close": [105.0, 21.0], "volume": [1000, 5000]
    })
    splits = normalize_splits(pd.DataFrame([{"ticker":"FAKE", "execution_date":"2020-08-31", "split_from":1, "split_to":5}]), "FAKE")
    out = apply_split_adjustment(df, splits)
    assert out.loc[0, "open"] == 20.0
    assert out.loc[0, "volume"] == 5000
    assert out.loc[1, "open"] == 20.0
    assert out.loc[1, "volume"] == 5000


def test_aggregate_1m_to_3m_full_rth_day():
    idx = pd.date_range("2024-01-02 09:30", "2024-01-02 15:59", freq="1min")
    df = pd.DataFrame({"timestamp": idx, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10})
    out = aggregate_1m_to_3m(df)
    assert len(out) == 130
    assert out.index.min().strftime("%H:%M") == "09:30"
    assert out.index.max().strftime("%H:%M") == "15:57"


def test_utc_to_et_naive_handles_dst_with_zoneinfo():
    s = pd.Series([1710163800000000000, 1730730600000000000])  # 2024-03-11 and 2024-11-04 09:30 ET
    out = utc_to_et_naive(s, unit="ns")
    assert [x.strftime("%H:%M") for x in out] == ["09:30", "09:30"]


def test_attach_saty_levels_uses_prior_close_and_prior_atr():
    daily = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=20, freq="B"),
        "open": range(100,120), "high": range(102,122), "low": range(99,119), "close": range(101,121), "volume": 1000
    })
    intra_idx = pd.date_range(daily.iloc[15]["timestamp"].strftime("%Y-%m-%d") + " 09:30", periods=3, freq="3min")
    intra = pd.DataFrame({"open": 1, "high": 2, "low": 0, "close": 1, "volume": 1}, index=intra_idx)
    out = attach_saty_levels(intra, daily)
    assert not out.empty
    d = daily.copy(); expected_atr = atr_series(d, 14).shift(1).iloc[15]
    assert abs(out.iloc[0]["prev_close"] - daily.iloc[14]["close"]) < 1e-9
    assert abs(out.iloc[0]["atr_14"] - expected_atr) < 1e-9
    for col in COLUMNS:
        assert col in out.columns

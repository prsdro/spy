import pandas as pd


def rma(series, period):
    series = pd.Series(series, copy=False, dtype=float)
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def true_range(df, high_col="high", low_col="low", close_col="close"):
    prev_close = df[close_col].shift(1)
    return pd.concat(
        [
            df[high_col] - df[low_col],
            (df[high_col] - prev_close).abs(),
            (df[low_col] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def compute_resampled_atr_ref(df, rule, period=14):
    resampled = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"})
    atr = rma(true_range(resampled), period)
    return pd.DataFrame(
        {
            "prev_close": resampled["close"].shift(1),
            "atr": atr.shift(1),
        }
    )


def dedupe_records_by_index_gap(records, index_key, min_gap):
    filtered = []
    next_allowed = None
    for record in sorted(records, key=lambda item: item[index_key]):
        current_idx = record[index_key]
        if next_allowed is not None and current_idx < next_allowed:
            continue
        filtered.append(record)
        next_allowed = current_idx + min_gap
    return filtered


def dedupe_signals_by_daily_cooldown(signals, daily_index, cooldown_days):
    filtered = []
    next_allowed_idx = None
    for signal in sorted(signals, key=lambda item: item["signal_time"]):
        signal_day_idx = daily_index.searchsorted(pd.Timestamp(signal["signal_time"]).normalize())
        if signal_day_idx >= len(daily_index):
            continue
        if next_allowed_idx is not None and signal_day_idx < next_allowed_idx:
            continue
        filtered.append(signal)
        next_allowed_idx = signal_day_idx + cooldown_days
    return filtered


def intraday_signal_daily_locs(daily_index, signal_time):
    signal_day = pd.Timestamp(signal_time).normalize()
    current_idx = daily_index.searchsorted(signal_day)
    if current_idx >= len(daily_index):
        return None, None, None
    prior_idx = current_idx - 1 if current_idx > 0 else None
    next_idx = current_idx + 1 if current_idx + 1 < len(daily_index) else None
    return current_idx, prior_idx, next_idx

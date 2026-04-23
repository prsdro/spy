"""
Call Trigger to Put Trigger Morning Reversal Study

Setup:
1. SPY reaches the daily call trigger during the morning.
2. Later in the morning, it crosses below PDC.
3. It reaches the daily put trigger while it is still morning.

Question:
After that full call-trigger-to-put-trigger reversal, what happens by the
RTH close?
- Does price get back to PDC?
- Does the bearish Golden Gate open (-38.2%)?
- Does price get back to the call trigger?
- Which side, PDC recovery or bearish GG, happens first?

Uses 1-minute RTH bars to minimize path-order ambiguity. Rebounds back to
PDC/call trigger are counted only on bars after the first put-trigger touch.
Downside continuation levels are counted from the put-trigger bar onward.
"""

import os
import sqlite3
import sys

# The system pandas install may see optional numexpr/bottleneck wheels that were
# compiled against an older NumPy. Disable those optional accelerators here; this
# study does not need them and pandas otherwise prints noisy import tracebacks.
os.environ.setdefault("PANDAS_USE_NUMEXPR", "0")
os.environ.setdefault("PANDAS_USE_BOTTLENECK", "0")
sys.modules.setdefault("numexpr", None)
sys.modules.setdefault("bottleneck", None)

import numpy as np
import pandas as pd


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
OUTPUT_CSV = os.path.join(BASE_DIR, "call_to_put_reversal_results.csv")


LEVEL_COLUMNS = [
    "atr_upper_trigger",
    "atr_lower_trigger",
    "atr_upper_0382",
    "atr_lower_0382",
    "atr_upper_050",
    "atr_lower_050",
    "atr_upper_0618",
    "atr_lower_0618",
    "atr_upper_0786",
    "atr_lower_0786",
    "atr_upper_100",
    "atr_lower_100",
    "atr_upper_1236",
    "atr_lower_1236",
    "atr_upper_1382",
    "atr_lower_1382",
    "atr_upper_150",
    "atr_lower_150",
    "atr_upper_1618",
    "atr_lower_1618",
    "atr_upper_1786",
    "atr_lower_1786",
    "atr_upper_200",
    "atr_lower_200",
]


def pct(n, d):
    return n / d * 100 if d else 0.0


def pct_s(n, d):
    return f"{pct(n, d):.1f}%" if d else "n/a"


def first_time(frame, mask):
    hits = frame[mask]
    if len(hits) == 0:
        return None
    return hits.index[0]


def minutes_between(start, end):
    if start is None or end is None:
        return np.nan
    return (end - start).total_seconds() / 60.0


def load_1m_data(conn):
    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "atr_14",
        *LEVEL_COLUMNS,
    ]
    query = f"""
        SELECT {", ".join(columns)}
        FROM ind_1m
        WHERE substr(timestamp, 12, 8) BETWEEN '09:30:00' AND '15:59:59'
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df.dropna(subset=["prev_close", "atr_14", "atr_upper_trigger", "atr_lower_trigger"])
    df["date"] = df.index.date
    return df


def load_completed_1h_po_data(conn):
    """Load 1h PO/ribbon state, timestamped by completed-bar time.

    The raw 1h timestamp is the bar start. For an event at 10:20, the latest
    fully completed 1h bar is the 09:00 bar ending at 10:00. Using completed
    time avoids looking ahead into the unfinished hourly candle.
    """
    query = """
        SELECT timestamp, close, ema_21, phase_oscillator, phase_zone,
               compression, po_compression
        FROM ind_1h
        ORDER BY timestamp
    """
    hourly = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    hourly = hourly.dropna(subset=["phase_oscillator"])
    hourly = hourly.rename(
        columns={
            "timestamp": "h1_bar_start",
            "close": "h1_close",
            "ema_21": "h1_ema21",
            "phase_oscillator": "h1_phase_oscillator",
            "phase_zone": "h1_phase_zone",
            "compression": "h1_compression",
            "po_compression": "h1_po_compression",
        }
    )
    hourly["h1_completed_time"] = hourly["h1_bar_start"] + pd.Timedelta(hours=1)
    return hourly.sort_values("h1_completed_time")


def attach_hourly_po_state(events, hourly):
    if len(events) == 0:
        return events

    events = events.copy()
    events["put_time"] = pd.to_datetime(events["put_time"])
    merged = pd.merge_asof(
        events.sort_values("put_time"),
        hourly.sort_values("h1_completed_time"),
        left_on="put_time",
        right_on="h1_completed_time",
        direction="backward",
    ).sort_values("put_time")

    def classify(row):
        if pd.isna(row.get("h1_phase_oscillator")):
            return "unknown"
        if row.get("h1_po_compression", 0) == 1 or row.get("h1_compression", 0) == 1:
            return "compression"
        if row["h1_phase_oscillator"] >= 0:
            return "bullish_expansion"
        return "bearish_expansion"

    merged["h1_po_state"] = merged.apply(classify, axis=1)
    return merged


def analyze(df, morning_cutoff="12:00"):
    cutoff_time = pd.Timestamp(morning_cutoff).time()
    records = []

    for date, group in df.groupby("date", sort=True):
        first = group.iloc[0]
        pdc = first["prev_close"]
        atr = first["atr_14"]
        call_trigger = first["atr_upper_trigger"]
        put_trigger = first["atr_lower_trigger"]

        if pd.isna(pdc) or pd.isna(atr) or atr <= 0:
            continue

        morning = group[group.index.time < cutoff_time]
        if len(morning) == 0:
            continue

        call_time = first_time(morning, morning["high"] >= call_trigger)
        if call_time is None:
            continue

        # Require the PDC/put-trigger reversal to occur after the call-trigger
        # touch. The put-trigger bar may be the same bar as the PDC cross because
        # put trigger sits below PDC.
        after_call = morning[morning.index > call_time]
        pdc_cross_time = first_time(after_call, after_call["low"] <= pdc)
        if pdc_cross_time is None:
            continue

        after_pdc = morning[morning.index >= pdc_cross_time]
        put_time = first_time(after_pdc, after_pdc["low"] <= put_trigger)
        if put_time is None:
            continue

        from_put = group[group.index >= put_time]
        after_put = group[group.index > put_time]

        if len(from_put) == 0:
            continue

        pdc_return_time = first_time(after_put, after_put["high"] >= pdc)
        call_return_time = first_time(after_put, after_put["high"] >= call_trigger)
        bull_gg_return_time = first_time(after_put, after_put["high"] >= first["atr_upper_0382"])

        downside_times = {
            "down_0382": first_time(from_put, from_put["low"] <= first["atr_lower_0382"]),
            "down_050": first_time(from_put, from_put["low"] <= first["atr_lower_050"]),
            "down_0618": first_time(from_put, from_put["low"] <= first["atr_lower_0618"]),
            "down_0786": first_time(from_put, from_put["low"] <= first["atr_lower_0786"]),
            "down_100": first_time(from_put, from_put["low"] <= first["atr_lower_100"]),
            "down_1236": first_time(from_put, from_put["low"] <= first["atr_lower_1236"]),
            "down_1382": first_time(from_put, from_put["low"] <= first["atr_lower_1382"]),
            "down_150": first_time(from_put, from_put["low"] <= first["atr_lower_150"]),
            "down_1618": first_time(from_put, from_put["low"] <= first["atr_lower_1618"]),
            "down_1786": first_time(from_put, from_put["low"] <= first["atr_lower_1786"]),
            "down_200": first_time(from_put, from_put["low"] <= first["atr_lower_200"]),
        }

        gg_time = downside_times["down_0382"]
        if pdc_return_time is not None and gg_time is not None:
            first_resolution = "pdc_first" if pdc_return_time < gg_time else "gg_first"
        elif pdc_return_time is not None:
            first_resolution = "pdc_only"
        elif gg_time is not None:
            first_resolution = "gg_only"
        else:
            first_resolution = "neither"

        close_price = group.iloc[-1]["close"]
        if close_price >= call_trigger:
            close_zone = "above_call_trigger"
        elif close_price >= pdc:
            close_zone = "pdc_to_call"
        elif close_price >= put_trigger:
            close_zone = "put_to_pdc"
        else:
            close_zone = "below_put_trigger"

        day_low_after_put = from_put["low"].min()
        day_high_after_put = after_put["high"].max() if len(after_put) else np.nan
        lowest_atr_after_put = (pdc - day_low_after_put) / atr
        rebound_atr_after_put = (day_high_after_put - pdc) / atr if not pd.isna(day_high_after_put) else np.nan

        records.append(
            {
                "date": str(date),
                "open": first["open"],
                "prev_close": pdc,
                "atr_14": atr,
                "call_trigger": call_trigger,
                "put_trigger": put_trigger,
                "call_time": call_time,
                "pdc_cross_time": pdc_cross_time,
                "put_time": put_time,
                "put_halfhour": f"{put_time.hour:02d}:{0 if put_time.minute < 30 else 30:02d}",
                "opened_above_call": bool(first["open"] >= call_trigger),
                "call_to_put_min": minutes_between(call_time, put_time),
                "pdc_cross_to_put_min": minutes_between(pdc_cross_time, put_time),
                "pdc_return": pdc_return_time is not None,
                "pdc_return_time": pdc_return_time,
                "pdc_return_min": minutes_between(put_time, pdc_return_time),
                "call_return": call_return_time is not None,
                "call_return_time": call_return_time,
                "call_return_min": minutes_between(put_time, call_return_time),
                "bull_gg_return": bull_gg_return_time is not None,
                "bull_gg_return_time": bull_gg_return_time,
                "down_0382": downside_times["down_0382"] is not None,
                "down_050": downside_times["down_050"] is not None,
                "down_0618": downside_times["down_0618"] is not None,
                "down_0786": downside_times["down_0786"] is not None,
                "down_100": downside_times["down_100"] is not None,
                "down_1236": downside_times["down_1236"] is not None,
                "down_1382": downside_times["down_1382"] is not None,
                "down_150": downside_times["down_150"] is not None,
                "down_1618": downside_times["down_1618"] is not None,
                "down_1786": downside_times["down_1786"] is not None,
                "down_200": downside_times["down_200"] is not None,
                "down_0382_time": downside_times["down_0382"],
                "down_0618_time": downside_times["down_0618"],
                "down_100_time": downside_times["down_100"],
                "first_resolution": first_resolution,
                "close": close_price,
                "close_zone": close_zone,
                "lowest_atr_after_put": lowest_atr_after_put,
                "rebound_atr_after_put": rebound_atr_after_put,
            }
        )

    return pd.DataFrame(records)


def print_outcome_table(events, title):
    n = len(events)
    print(f"\n{title}")
    print("-" * len(title))
    print(f"  Events: {n:,}")
    if n == 0:
        return

    print("\n  Upside retrace after put-trigger touch:")
    for col, label in [
        ("pdc_return", "Back to PDC"),
        ("call_return", "Back to call trigger"),
        ("bull_gg_return", "Back to +38.2% / bullish GG"),
    ]:
        count = int(events[col].sum())
        print(f"    {label:<28s} {count:5d}/{n:<5d} {pct_s(count, n):>7s}")

    print("\n  Downside continuation from put-trigger touch:")
    for col, label in [
        ("down_0382", "-38.2% / bearish GG open"),
        ("down_050", "-50%"),
        ("down_0618", "-61.8% / bearish GG complete"),
        ("down_0786", "-78.6%"),
        ("down_100", "-1 ATR"),
        ("down_1236", "-1.236 ATR"),
        ("down_1618", "-1.618 ATR"),
        ("down_200", "-2 ATR"),
    ]:
        count = int(events[col].sum())
        print(f"    {label:<28s} {count:5d}/{n:<5d} {pct_s(count, n):>7s}")


def print_first_resolution(events):
    n = len(events)
    print("\nFirst meaningful outcome after put-trigger touch")
    print("-" * 51)
    for key, label in [
        ("gg_first", "Bearish GG opened before PDC recovery"),
        ("gg_only", "Bearish GG opened; no PDC recovery"),
        ("pdc_first", "PDC recovered before bearish GG"),
        ("pdc_only", "PDC recovered; no bearish GG"),
        ("neither", "Neither PDC recovery nor bearish GG"),
    ]:
        count = int((events["first_resolution"] == key).sum())
        print(f"  {label:<42s} {count:5d}/{n:<5d} {pct_s(count, n):>7s}")


def print_timing(events):
    print("\nTiming")
    print("-" * 6)
    for col, label in [
        ("call_to_put_min", "Call trigger touch -> put trigger"),
        ("pdc_cross_to_put_min", "PDC cross -> put trigger"),
        ("pdc_return_min", "Put trigger -> back to PDC"),
        ("call_return_min", "Put trigger -> back to call trigger"),
    ]:
        series = events[col].dropna()
        if len(series) == 0:
            continue
        print(
            f"  {label:<36s} "
            f"median={series.median():5.0f}m  "
            f"mean={series.mean():5.1f}m  "
            f"p75={series.quantile(0.75):5.0f}m"
        )


def print_by_halfhour(events):
    print("\nBy put-trigger touch time")
    print("-" * 25)
    print(
        f"  {'Time':<8s} {'N':>5s} {'PDC':>7s} {'Call':>7s} "
        f"{'GG open':>8s} {'GG comp':>8s} {'-1 ATR':>7s}"
    )
    for bucket, group in events.groupby("put_halfhour", sort=True):
        n = len(group)
        flag = "*" if n < 30 else " "
        print(
            f"  {bucket:<8s} {n:5d}{flag} "
            f"{pct(int(group['pdc_return'].sum()), n):6.1f}% "
            f"{pct(int(group['call_return'].sum()), n):6.1f}% "
            f"{pct(int(group['down_0382'].sum()), n):7.1f}% "
            f"{pct(int(group['down_0618'].sum()), n):7.1f}% "
            f"{pct(int(group['down_100'].sum()), n):6.1f}%"
        )
    print("  * n < 30")


def print_by_hourly_po_state(events):
    print("\nBy latest completed 1h PO state at put-trigger touch")
    print("-" * 55)
    print("  State uses the last fully completed hourly bar, not the in-progress hour.")
    print(
        f"  {'1h state':<20s} {'N':>5s} {'PDC':>7s} {'Call':>7s} "
        f"{'GG open':>8s} {'GG comp':>8s} {'-1 ATR':>7s} {'Close < put':>11s}"
    )

    order = [
        ("bullish_expansion", "Bullish expansion"),
        ("compression", "Compression"),
        ("bearish_expansion", "Bearish expansion"),
        ("unknown", "Unknown"),
    ]
    for key, label in order:
        sub = events[events["h1_po_state"] == key] if "h1_po_state" in events else events.iloc[0:0]
        n = len(sub)
        if n == 0:
            continue
        close_below_put = int((sub["close_zone"] == "below_put_trigger").sum())
        print(
            f"  {label:<20s} {n:5d} "
            f"{pct(int(sub['pdc_return'].sum()), n):6.1f}% "
            f"{pct(int(sub['call_return'].sum()), n):6.1f}% "
            f"{pct(int(sub['down_0382'].sum()), n):7.1f}% "
            f"{pct(int(sub['down_0618'].sum()), n):7.1f}% "
            f"{pct(int(sub['down_100'].sum()), n):6.1f}% "
            f"{pct(close_below_put, n):10.1f}%"
        )

    print("\n  First resolution by 1h state:")
    print(f"  {'1h state':<20s} {'Bear first/only':>15s} {'PDC first/only':>15s}")
    for key, label in order:
        sub = events[events["h1_po_state"] == key] if "h1_po_state" in events else events.iloc[0:0]
        n = len(sub)
        if n == 0:
            continue
        bear_first = int(sub["first_resolution"].isin(["gg_first", "gg_only"]).sum())
        pdc_first = int(sub["first_resolution"].isin(["pdc_first", "pdc_only"]).sum())
        print(
            f"  {label:<20s} {pct(bear_first, n):14.1f}% "
            f"{pct(pdc_first, n):14.1f}%"
        )


def print_close_distribution(events):
    print("\nClose location")
    print("-" * 14)
    labels = [
        ("above_call_trigger", "Above call trigger"),
        ("pdc_to_call", "Between PDC and call trigger"),
        ("put_to_pdc", "Between put trigger and PDC"),
        ("below_put_trigger", "Below put trigger"),
    ]
    n = len(events)
    for key, label in labels:
        count = int((events["close_zone"] == key).sum())
        print(f"  {label:<30s} {count:5d}/{n:<5d} {pct_s(count, n):>7s}")


def print_context_breakdowns(events):
    print("\nContext breakdown")
    print("-" * 17)
    for opened_above_call, label in [
        (True, "Opened above call trigger"),
        (False, "Touched call trigger intraday"),
    ]:
        sub = events[events["opened_above_call"] == opened_above_call]
        n = len(sub)
        if n == 0:
            continue
        pdc_n = int(sub["pdc_return"].sum())
        call_n = int(sub["call_return"].sum())
        gg_n = int(sub["down_0382"].sum())
        comp_n = int(sub["down_0618"].sum())
        print(
            f"  {label:<29s} n={n:4d}  "
            f"PDC={pct_s(pdc_n, n):>6s}  "
            f"Call={pct_s(call_n, n):>6s}  "
            f"GG open={pct_s(gg_n, n):>6s}  "
            f"GG comp={pct_s(comp_n, n):>6s}"
        )


def print_sensitivity(df):
    print("\nMorning cutoff sensitivity")
    print("-" * 27)
    print(f"  {'Cutoff':<8s} {'N':>5s} {'PDC':>7s} {'Call':>7s} {'GG open':>8s} {'GG comp':>8s} {'-1 ATR':>7s}")
    for cutoff in ["10:30", "11:00", "11:30", "12:00"]:
        events = analyze(df, cutoff)
        n = len(events)
        if n == 0:
            print(f"  {cutoff:<8s} {n:5d}")
            continue
        print(
            f"  {cutoff:<8s} {n:5d} "
            f"{pct(int(events['pdc_return'].sum()), n):6.1f}% "
            f"{pct(int(events['call_return'].sum()), n):6.1f}% "
            f"{pct(int(events['down_0382'].sum()), n):7.1f}% "
            f"{pct(int(events['down_0618'].sum()), n):7.1f}% "
            f"{pct(int(events['down_100'].sum()), n):6.1f}%"
        )


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading 1m RTH indicator data...", flush=True)
    df = load_1m_data(conn)
    print("Loading completed 1h PO state...", flush=True)
    hourly = load_completed_1h_po_data(conn)
    conn.close()

    total_days = df["date"].nunique()
    print(f"Loaded {len(df):,} RTH 1m bars across {total_days:,} trading days.")

    events = analyze(df, "12:00")
    events = attach_hourly_po_state(events, hourly)
    events.to_csv(OUTPUT_CSV, index=False)

    print("\n" + "=" * 78)
    print("CALL TRIGGER -> PDC -> PUT TRIGGER MORNING REVERSAL")
    print("=" * 78)
    print("Definition:")
    print("  Morning = RTH bars before 12:00 ET.")
    print("  Sequence = high >= daily call trigger, then later low <= PDC,")
    print("             then low <= daily put trigger before 12:00.")
    print("  Rebounds are measured after the first put-trigger bar.")
    print("  Downside levels are measured from the first put-trigger bar onward.")

    print_outcome_table(events, "Primary outcomes by RTH close")
    print_first_resolution(events)
    print_by_halfhour(events)
    print_by_hourly_po_state(events)
    print_close_distribution(events)
    print_context_breakdowns(events)
    print_timing(events)

    if len(events):
        lowest = events["lowest_atr_after_put"].dropna()
        rebound = events["rebound_atr_after_put"].dropna()
        print("\nDistance after put-trigger touch")
        print("-" * 32)
        print(
            f"  Lowest downside excursion: median={lowest.median():.3f} ATR  "
            f"mean={lowest.mean():.3f} ATR  p75={lowest.quantile(0.75):.3f} ATR"
        )
        print(
            f"  Best upside rebound:       median={rebound.median():.3f} ATR  "
            f"mean={rebound.mean():.3f} ATR  p75={rebound.quantile(0.75):.3f} ATR"
        )

    print_sensitivity(df)
    print(f"\nSaved event list to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

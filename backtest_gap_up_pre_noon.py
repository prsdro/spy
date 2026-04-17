"""
Gap Up Pre-Noon Strength Study
When SPY gaps up and the intraday high reaches >1% gain (approx +1 ATR) from prev_close
before noon, what are the continuation vs. reversal probabilities for the rest of the day?
Segmented by all days, Fridays, and OpEx Fridays.
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def is_opex_friday(d):
    """Third Friday of each month (US equity options expiration)."""
    return d.weekday() == 4 and 15 <= d.day <= 21


def pct(n, total):
    return f"{n/total*100:5.1f}%" if total > 0 else "  n/a"


def get_val(series, col):
    if col in series.index:
        v = series[col]
        return np.nan if pd.isna(v) else v
    return np.nan


def analyze(label, df):
    n = len(df)
    if n < 10:
        print(f"\n{label}: n={n} (too few to report)")
        return

    print(f"\n{'='*70}")
    print(f"  {label}  (n={n:,})")
    print(f"{'='*70}")

    already_gapped = (df["gap_pct"] >= 0.01).sum()
    ran_up = n - already_gapped
    print(f"  Already >1% at open: {already_gapped:4,} ({pct(already_gapped, n)})  — gap itself was big")
    print(f"  Ran up to 1% intra:  {ran_up:4,} ({pct(ran_up, n)})  — gap < 1%, ran up before noon")
    print(f"  Median gap:         {df['gap_pct'].median()*100:+.2f}%")
    print(f"  Median pre-noon H:  {df['pre_noon_gain'].median()*100:+.2f}% above prev_close")
    print(f"  Median daily ATR:   {df['atr_pct'].median()*100:.2f}% of price")
    print(f"  Hit +1 ATR (100%):  {df['hit_1atr_pre_noon'].sum():,} ({pct(df['hit_1atr_pre_noon'].sum(), n)})")

    print()
    print(f"  WHERE THE DAY CLOSES (vs prev_close):")
    atr = df["atr_pct"]
    c = df["close_pct"]
    buckets = [
        ("Above +2x ATR",                   c >= atr * 2),
        ("Between +1 ATR and +2 ATR",        (c >= atr) & (c < atr * 2)),
        ("Between +61.8% ATR and +1 ATR",    (c >= atr * 0.618) & (c < atr)),
        ("Between +23.6% ATR and +61.8% ATR",(c >= atr * 0.236) & (c < atr * 0.618)),
        ("Between 0% and +23.6% ATR",        (c > 0) & (c < atr * 0.236)),
        ("Flat (closed ≤ 0%)",               c <= 0),
        ("  Closed below -23.6% ATR",        c <= -atr * 0.236),
        ("  Closed below -1 ATR",            c <= -atr),
    ]
    for lbl, mask in buckets:
        cnt = mask.sum()
        print(f"    {lbl:<42s}  {cnt:4,}  {pct(cnt, n)}")
    print(f"    Median close:                             {c.median()*100:+.3f}%")
    print(f"    Closed positive:                {(c > 0).sum():4,}  {pct((c > 0).sum(), n)}")

    print()
    print(f"  CONTINUATION (remaining day touched these upward levels):")
    for col, lbl in [
        ("cont_atr_upper_100",  "+100% ATR (full ATR touched)"),
        ("cont_atr_upper_1236", "+123.6% ATR (1st extension)"),
        ("cont_atr_upper_1618", "+161.8% ATR (2nd extension)"),
        ("cont_atr_upper_200",  "+200% ATR (2x full ATR)"),
    ]:
        if col in df.columns:
            cnt = int(df[col].sum())
            print(f"    {lbl:<40s}  {cnt:4,}  {pct(cnt, n)}")

    print()
    print(f"  RETRACEMENT (remaining day touched these downward levels):")
    for col, lbl in [
        ("ret_prev_close",        "Prev_close — full gap fill (0%)"),
        ("ret_atr_lower_trigger", "-23.6% ATR — lower trigger"),
        ("ret_atr_lower_0382",    "-38.2% ATR — lower GG entry"),
        ("ret_atr_lower_0618",    "-61.8% ATR"),
        ("ret_atr_lower_100",     "-100% ATR — 1 full ATR down"),
        ("ret_atr_lower_200",     "-200% ATR — 2 full ATRs down"),
    ]:
        if col in df.columns:
            cnt = int(df[col].sum())
            print(f"    {lbl:<40s}  {cnt:4,}  {pct(cnt, n)}")


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading 10m indicator data...", flush=True)

    df = pd.read_sql_query(
        """SELECT timestamp, open, high, low, close,
           prev_close, atr_14,
           atr_upper_trigger, atr_lower_trigger,
           atr_upper_0382, atr_lower_0382,
           atr_upper_050, atr_lower_050,
           atr_upper_0618, atr_lower_0618,
           atr_upper_0786, atr_lower_0786,
           atr_upper_100, atr_lower_100,
           atr_upper_1236, atr_lower_1236,
           atr_upper_1618, atr_lower_1618,
           atr_upper_200, atr_lower_200
           FROM ind_10m ORDER BY timestamp""",
        conn, parse_dates=["timestamp"]
    )
    conn.close()

    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date

    records = []

    for date_val, group in df.groupby("date"):
        first = group.iloc[0]
        prev_close = get_val(first, "prev_close")
        atr_14 = get_val(first, "atr_14")
        if pd.isna(prev_close) or prev_close <= 0 or pd.isna(atr_14) or atr_14 <= 0:
            continue

        open_price = first["open"]
        gap_pct = (open_price - prev_close) / prev_close
        if gap_pct <= 0:
            continue  # must gap up

        # Pre-noon bars: RTH open through 11:59 (hours 9, 10, 11)
        pre_noon = group[group.index.hour < 12]
        if len(pre_noon) == 0:
            continue

        max_pre_noon = pre_noon["high"].max()
        pre_noon_gain = (max_pre_noon - prev_close) / prev_close
        if pre_noon_gain < 0.01:
            continue  # must reach >1% before noon

        # Find earliest bar that crossed +1%
        trigger_bars = pre_noon[pre_noon["high"] >= prev_close * 1.01]
        trigger_time = trigger_bars.index[0]
        remaining = group[group.index > trigger_time]

        remaining_low = remaining["low"].min()
        remaining_high = remaining["high"].max()
        day_close = group.iloc[-1]["close"]
        close_pct = (day_close - prev_close) / prev_close

        d = pd.Timestamp(date_val)
        is_friday = d.dayofweek == 4
        is_opex = is_opex_friday(d)

        atr_upper_100 = get_val(first, "atr_upper_100")

        rec = {
            "date": date_val,
            "year": d.year,
            "dow": d.dayofweek,
            "is_friday": is_friday,
            "is_opex": is_opex,
            "gap_pct": gap_pct,
            "pre_noon_gain": pre_noon_gain,
            "hit_1atr_pre_noon": (not pd.isna(atr_upper_100)) and (max_pre_noon >= atr_upper_100),
            "atr_pct": atr_14 / prev_close,
            "close_pct": close_pct,
        }

        # Upward continuation (rest of day from trigger)
        for col in ["atr_upper_100", "atr_upper_1236", "atr_upper_1618", "atr_upper_200"]:
            v = get_val(first, col)
            rec[f"cont_{col}"] = (not pd.isna(v)) and (remaining_high >= v)

        # Downward retracement (rest of day from trigger)
        rec["ret_prev_close"] = remaining_low <= prev_close
        for col in ["atr_lower_trigger", "atr_lower_0382", "atr_lower_0618",
                    "atr_lower_100", "atr_lower_200"]:
            v = get_val(first, col)
            rec[f"ret_{col}"] = (not pd.isna(v)) and (remaining_low <= v)

        records.append(rec)

    df_res = pd.DataFrame(records)
    n_total = len(df_res)
    print(f"\nTotal qualifying days (gap up AND >1% before noon): {n_total:,}")
    print(f"Date range: {df_res['date'].min()} to {df_res['date'].max()}")

    is_opex_mask = df_res["is_opex"]
    is_fri_mask = df_res["is_friday"]

    analyze("ALL QUALIFYING DAYS", df_res)
    analyze("NON-FRIDAY DAYS", df_res[~is_fri_mask])
    analyze("ALL FRIDAYS", df_res[is_fri_mask])
    analyze("OPEX FRIDAYS (3rd Friday of month)", df_res[is_opex_mask])
    analyze("NON-OPEX FRIDAYS", df_res[is_fri_mask & ~is_opex_mask])

    # Era breakdown
    analyze("ERA 2000–2009", df_res[df_res["year"] <= 2009])
    analyze("ERA 2010–2019", df_res[(df_res["year"] >= 2010) & (df_res["year"] <= 2019)])
    analyze("ERA 2020–2025", df_res[df_res["year"] >= 2020])

    # ─── Compact comparison table ───────────────────────────────────────────────
    print(f"\n\n{'='*95}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*95}")
    hdr = f"  {'Category':<26} {'n':>5}  {'Close+':>6}  {'RetPDC':>7}  {'Ret-1ATR':>8}  {'Cont+1ATR':>9}  {'Cont+200%':>9}  {'MedClose':>9}"
    print(f"\n{hdr}")
    print(f"  {'-'*93}")

    rows = [
        ("All days", df_res),
        ("Non-Friday", df_res[~is_fri_mask]),
        ("All Fridays", df_res[is_fri_mask]),
        ("OpEx Friday", df_res[is_opex_mask]),
        ("Non-OpEx Friday", df_res[is_fri_mask & ~is_opex_mask]),
        ("2000–2009", df_res[df_res["year"] <= 2009]),
        ("2010–2019", df_res[(df_res["year"] >= 2010) & (df_res["year"] <= 2019)]),
        ("2020–2025", df_res[df_res["year"] >= 2020]),
    ]

    for lbl, sub in rows:
        n_ = len(sub)
        if n_ < 5:
            continue
        c_pos  = pct((sub["close_pct"] > 0).sum(), n_)
        r_pdc  = pct(sub["ret_prev_close"].sum(), n_)
        r_1atr = pct(sub["ret_atr_lower_100"].sum(), n_)  if "ret_atr_lower_100"  in sub.columns else "  n/a"
        c_1atr = pct(sub["cont_atr_upper_100"].sum(), n_) if "cont_atr_upper_100" in sub.columns else "  n/a"
        c_200  = pct(sub["cont_atr_upper_200"].sum(), n_) if "cont_atr_upper_200" in sub.columns else "  n/a"
        med    = sub["close_pct"].median() * 100
        print(f"  {lbl:<26} {n_:5,}  {c_pos:>6}  {r_pdc:>7}  {r_1atr:>8}  {c_1atr:>9}  {c_200:>9}  {med:>+8.2f}%")

    # ─── Sub-analysis: only days that actually hit +1 ATR before noon ───────────
    df_1atr = df_res[df_res["hit_1atr_pre_noon"]]
    print(f"\n\n{'='*95}")
    print(f"  SUB-ANALYSIS: Days that hit the +1 ATR level (100%) before noon")
    print(f"  (stricter subset of above — price crossed the actual ATR 100% line)")
    print(f"{'='*95}")
    sub_rows = [
        ("All days (hit +1ATR)", df_1atr),
        ("Non-Friday", df_1atr[~df_1atr["is_friday"]]),
        ("All Fridays", df_1atr[df_1atr["is_friday"]]),
        ("OpEx Friday", df_1atr[df_1atr["is_opex"]]),
    ]
    print(f"\n{hdr}")
    print(f"  {'-'*93}")
    for lbl, sub in sub_rows:
        n_ = len(sub)
        if n_ < 5:
            continue
        c_pos  = pct((sub["close_pct"] > 0).sum(), n_)
        r_pdc  = pct(sub["ret_prev_close"].sum(), n_)
        r_1atr = pct(sub["ret_atr_lower_100"].sum(), n_)  if "ret_atr_lower_100"  in sub.columns else "  n/a"
        c_1atr = pct(sub["cont_atr_upper_100"].sum(), n_) if "cont_atr_upper_100" in sub.columns else "  n/a"
        c_200  = pct(sub["cont_atr_upper_200"].sum(), n_) if "cont_atr_upper_200" in sub.columns else "  n/a"
        med    = sub["close_pct"].median() * 100
        print(f"  {lbl:<26} {n_:5,}  {c_pos:>6}  {r_pdc:>7}  {r_1atr:>8}  {c_1atr:>9}  {c_200:>9}  {med:>+8.2f}%")


if __name__ == "__main__":
    main()

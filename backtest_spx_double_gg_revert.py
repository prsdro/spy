"""
SPX Double Golden Gate ("both gates open, neither closes") Study
================================================================

Hypothesis:
  When SPX *opens a downside Golden Gate* and then later *opens an upside
  Golden Gate*, with both opens happening before 12pm Central (= 1:00 pm ET),
  neither gate is likely to *close* (complete to +/-61.8%); instead price is
  likely to revert to the previous day's close (PDC).

Saty terminology used here:
  - A Golden Gate "opens"  when price reaches the +/-38.2% ATR level.
  - A Golden Gate "closes" / "completes" when price reaches the +/-61.8% ATR level.
  - The gate is the zone from 38.2% -> 61.8% of the daily ATR away from PDC.

Setup (a "double-gate whipsaw" day):
  1. Before the noon-CT cutoff, the LOW first reaches the lower 38.2% level
     (downside gate opens).
  2. After that, still before the cutoff, the HIGH reaches the upper 38.2%
     level (upside gate opens). Reaching +38.2% from -38.2% means price has
     crossed back through PDC, so a full reversal has occurred.

Once the second (upside) gate opens, we measure what happens through the RTH
close: does either gate close? does price revert to PDC?

Data:
  FirstRateData SPX index files in /root/spy/data
    - SPX_full_1min_*.zip   (1-minute, US Eastern wall-clock, period-start)
    - SPX_full_1day_*.zip   (daily, for PDC and Wilder ATR(14))
  Intraday coverage starts 2008-01; daily starts 2000-11.

Path order is resolved on 1-minute RTH bars to minimize ambiguity. Levels are
computed from the prior session's close and a one-session-lagged daily Wilder
ATR(14), matching the SPY ATR-cascade SPX loader in this repo.
"""

from __future__ import annotations

import csv
import io
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUT_CSV = BASE_DIR / "analyst" / "spx_double_gg_revert_events.csv"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# Noon Central Time == 1:00 pm Eastern (Central is always ET-1 in wall clock).
# FirstRateData timestamps are ET wall-clock, so the morning cutoff is 13:00.
NOON_CT_AS_ET = "13:00"


# --------------------------------------------------------------------------- #
# Data loading (mirrors backtest_atr_cascade_spx_firstrate.py)
# --------------------------------------------------------------------------- #
def _single_zip_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as z:
        members = [i.filename for i in z.infolist() if not i.is_dir()]
    if len(members) != 1:
        raise ValueError(f"Expected one file in {zip_path}, found {members}")
    return members[0]


def find_one(pattern: str) -> Path:
    matches = sorted(DATA_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matched {DATA_DIR / pattern}")
    if len(matches) > 1:
        raise ValueError(f"Multiple files matched {pattern}: {[m.name for m in matches]}")
    return matches[0]


def read_firstrate_zip(zip_path: Path, intraday: bool) -> pd.DataFrame:
    member = _single_zip_member(zip_path)
    rows = []
    with zipfile.ZipFile(zip_path) as z:
        with z.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.reader(text):
                if not row:
                    continue
                if len(row) != 5:
                    raise ValueError(f"Unexpected row in {zip_path.name}: {row[:8]}")
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
    high, low, prev_close = daily["high"], daily["low"], daily["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return rma(tr, period)


def load_spx() -> pd.DataFrame:
    intra = read_firstrate_zip(find_one("SPX_full_1min_*.zip"), intraday=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)

    daily["date"] = daily["timestamp"].dt.date
    daily["atr_14"] = atr_series(daily, 14).shift(1)
    daily["prev_close"] = daily["close"].shift(1)
    lookup = daily.set_index("date")[["prev_close", "atr_14"]]

    intra = intra.set_index("timestamp").sort_index()
    intra = intra.between_time("09:30", "15:59")
    intra["date"] = intra.index.date
    intra = intra.join(lookup, on="date")
    intra = intra.dropna(subset=["prev_close", "atr_14"])
    intra = intra[intra["atr_14"] > 0]

    pc, atr = intra["prev_close"], intra["atr_14"]
    intra["up_0382"] = pc + 0.382 * atr
    intra["dn_0382"] = pc - 0.382 * atr
    intra["up_0618"] = pc + 0.618 * atr
    intra["dn_0618"] = pc - 0.618 * atr
    intra["up_0786"] = pc + 0.786 * atr
    intra["dn_0786"] = pc - 0.786 * atr
    intra["up_trig"] = pc + 0.236 * atr
    intra["dn_trig"] = pc - 0.236 * atr
    intra["up_100"] = pc + 1.000 * atr
    intra["dn_100"] = pc - 1.000 * atr
    return intra


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
def first_time(frame, mask):
    hits = frame.index[mask.values]
    return hits[0] if len(hits) else None


def analyze(df: pd.DataFrame, cutoff: str = NOON_CT_AS_ET):
    cutoff_t = pd.Timestamp(cutoff).time()
    records = []

    for date, g in df.groupby("date", sort=True):
        first = g.iloc[0]
        pdc = first["prev_close"]
        atr = first["atr_14"]
        up_open_lvl, dn_open_lvl = first["up_0382"], first["dn_0382"]
        up_close_lvl, dn_close_lvl = first["up_0618"], first["dn_0618"]

        morning = g[g.index.time < cutoff_t]
        if len(morning) == 0:
            continue

        # 1. Downside gate opens first (low reaches -38.2%) before noon CT.
        dn_open_t = first_time(morning, morning["low"] <= dn_open_lvl)
        if dn_open_t is None:
            continue

        # 2. Upside gate opens after that, still before noon CT (high reaches +38.2%).
        after_dn = morning[morning.index > dn_open_t]
        up_open_t = first_time(after_dn, after_dn["high"] >= up_open_lvl)
        if up_open_t is None:
            continue

        # --- path segments ---
        first_leg = g[(g.index >= dn_open_t) & (g.index <= up_open_t)]  # the down->up reversal
        after_up = g[g.index > up_open_t]                              # rest of day after 2nd open
        from_up = g[g.index >= up_open_t]

        # Did the downside gate CLOSE on the first leg down (before reversing up)?
        dn_closed_first_leg = bool((first_leg["low"] <= dn_close_lvl).any())

        # Whole-day gate closes (ever, in either direction).
        dn_close_ever = bool((g["low"] <= dn_close_lvl).any())
        up_close_ever = bool((g["high"] >= up_close_lvl).any())
        neither_close_ever = (not dn_close_ever) and (not up_close_ever)

        # Outcomes AFTER the second (upside) gate opens.
        up_close_after = first_time(after_up, after_up["high"] >= up_close_lvl)
        dn_reopen_after = first_time(after_up, after_up["low"] <= dn_open_lvl)
        dn_close_after = first_time(after_up, after_up["low"] <= dn_close_lvl)
        pdc_revert_t = first_time(after_up, after_up["low"] <= pdc)  # pull back down to PDC
        up_trig_revert_t = first_time(after_up, after_up["low"] <= first["up_trig"])

        # First resolution after the upside gate opens.
        events_t = {
            "up_close": up_close_after,
            "dn_close": dn_close_after,
        }
        live = {k: v for k, v in events_t.items() if v is not None}
        if live:
            first_res = min(live, key=lambda k: live[k])
        else:
            first_res = "neither"

        close_price = g.iloc[-1]["close"]
        if close_price >= up_close_lvl:
            close_zone = "above_up_gate(+61.8)"
        elif close_price >= up_open_lvl:
            close_zone = "in_up_gate(+38.2..61.8)"
        elif close_price >= pdc:
            close_zone = "pdc_to_+38.2"
        elif close_price >= dn_open_lvl:
            close_zone = "-38.2_to_pdc"
        elif close_price >= dn_close_lvl:
            close_zone = "in_dn_gate(-38.2..61.8)"
        else:
            close_zone = "below_dn_gate(-61.8)"

        records.append(
            {
                "date": str(date),
                "pdc": pdc,
                "atr_14": atr,
                "dn_open_t": dn_open_t,
                "up_open_t": up_open_t,
                "up_open_hhmm": f"{up_open_t.hour:02d}:{0 if up_open_t.minute < 30 else 30:02d}",
                "reversal_min": (up_open_t - dn_open_t).total_seconds() / 60.0,
                "dn_closed_first_leg": dn_closed_first_leg,
                "dn_close_ever": dn_close_ever,
                "up_close_ever": up_close_ever,
                "neither_close_ever": neither_close_ever,
                "up_close_after": up_close_after is not None,
                "dn_close_after": dn_close_after is not None,
                "dn_reopen_after": dn_reopen_after is not None,
                "pdc_revert_after": pdc_revert_t is not None,
                "up_trig_revert_after": up_trig_revert_t is not None,
                "first_resolution_after_up": first_res,
                "close": close_price,
                "close_zone": close_zone,
                "close_minus_pdc_atr": (close_price - pdc) / atr,
            }
        )

    return pd.DataFrame(records)


def base_rates(df: pd.DataFrame, cutoff: str = NOON_CT_AS_ET):
    """Baselines for context: how often each precursor happens, all RTH days."""
    cutoff_t = pd.Timestamp(cutoff).time()
    n_days = dn_open = both_open = 0
    for _, g in df.groupby("date", sort=True):
        n_days += 1
        first = g.iloc[0]
        morning = g[g.index.time < cutoff_t]
        if len(morning) == 0:
            continue
        dn_open_t = first_time(morning, morning["low"] <= first["dn_0382"])
        if dn_open_t is None:
            continue
        dn_open += 1
        after = morning[morning.index > dn_open_t]
        if first_time(after, after["high"] >= first["up_0382"]) is not None:
            both_open += 1
    return n_days, dn_open, both_open


def pct(n, d):
    return f"{n / d * 100:5.1f}%" if d else "  n/a"


def main():
    print("Loading FirstRateData SPX 1-minute + daily ...", flush=True)
    df = load_spx()
    days = df["date"].nunique()
    print(f"Loaded {len(df):,} RTH 1m SPX bars across {days:,} sessions "
          f"({df.index.min().date()} -> {df.index.max().date()}).")

    n_days, dn_open, both_open = base_rates(df)
    ev = analyze(df)
    ev.to_csv(OUT_CSV, index=False)
    n = len(ev)

    print("\n" + "=" * 74)
    print("SPX DOUBLE GOLDEN GATE  (downside opens, then upside opens, both")
    print("before 12pm Central / 1:00pm ET)")
    print("=" * 74)
    print("\nFunnel (all RTH sessions with valid PDC+ATR):")
    print(f"  Sessions analyzed                         {n_days:6d}")
    print(f"  Downside GG opens (-38.2%) before noon CT {dn_open:6d}  {pct(dn_open, n_days)}")
    print(f"  ...then upside GG opens (+38.2%) too      {both_open:6d}  "
          f"{pct(both_open, n_days)} of all days, {pct(both_open, dn_open)} of dn-open days")
    print(f"  Qualifying setups in event table          {n:6d}")

    if n == 0:
        print("\nNo qualifying setups.")
        return

    print("\n--- HYPOTHESIS TEST: neither gate closes, revert to PDC ---")
    neither = int(ev["neither_close_ever"].sum())
    pdc_rev = int(ev["pdc_revert_after"].sum())
    both_test = int((ev["neither_close_ever"] & ev["pdc_revert_after"]).sum())
    print(f"  Neither gate ever closes (no +/-61.8% all day)   {neither:5d}/{n}  {pct(neither, n)}")
    print(f"  Reverts to PDC after 2nd (upside) gate opens     {pdc_rev:5d}/{n}  {pct(pdc_rev, n)}")
    print(f"  BOTH (neither close AND PDC revert)              {both_test:5d}/{n}  {pct(both_test, n)}")

    print("\n--- What actually happens (whole day) ---")
    dnc = int(ev["dn_close_ever"].sum())
    upc = int(ev["up_close_ever"].sum())
    dnfl = int(ev["dn_closed_first_leg"].sum())
    print(f"  Downside gate closes (-61.8%) at some point      {dnc:5d}/{n}  {pct(dnc, n)}")
    print(f"    ...of which closed on the first leg down       {dnfl:5d}/{n}  {pct(dnfl, n)}")
    print(f"  Upside gate closes (+61.8%) at some point        {upc:5d}/{n}  {pct(upc, n)}")

    print("\n--- After the upside gate opens (the setup completes) ---")
    for col, label in [
        ("up_close_after", "Upside gate CLOSES (+61.8%)"),
        ("pdc_revert_after", "Pulls back to PDC"),
        ("up_trig_revert_after", "Pulls back to +23.6% trigger"),
        ("dn_reopen_after", "Downside gate RE-opens (-38.2%)"),
        ("dn_close_after", "Downside gate closes (-61.8%)"),
    ]:
        c = int(ev[col].sum())
        print(f"  {label:<34s} {c:5d}/{n}  {pct(c, n)}")

    print("\n--- First resolution after upside gate opens ---")
    print("  (which 61.8% completion is reached first, if any)")
    for key, label in [
        ("up_close", "Upside gate closes first (+61.8%)"),
        ("dn_close", "Downside gate closes first (-61.8%)"),
        ("neither", "Neither closes by RTH close"),
    ]:
        c = int((ev["first_resolution_after_up"] == key).sum())
        print(f"  {label:<34s} {c:5d}/{n}  {pct(c, n)}")

    print("\n--- RTH close location ---")
    order = [
        "above_up_gate(+61.8)", "in_up_gate(+38.2..61.8)", "pdc_to_+38.2",
        "-38.2_to_pdc", "in_dn_gate(-38.2..61.8)", "below_dn_gate(-61.8)",
    ]
    for z in order:
        c = int((ev["close_zone"] == z).sum())
        print(f"  {z:<26s} {c:5d}/{n}  {pct(c, n)}")
    cmp_atr = ev["close_minus_pdc_atr"]
    print(f"\n  Close vs PDC:  median={cmp_atr.median():+.3f} ATR   "
          f"mean={cmp_atr.mean():+.3f} ATR   "
          f"within +/-0.236 ATR of PDC: {pct(int((cmp_atr.abs() <= 0.236).sum()), n)}")

    print("\n--- By time the upside (2nd) gate opens ---")
    print(f"  {'Time':<7s} {'N':>4s} {'NeitherClose':>13s} {'PDCrevert':>10s} "
          f"{'UpClose':>8s} {'DnClose':>8s}")
    for bucket, grp in ev.groupby("up_open_hhmm", sort=True):
        m = len(grp)
        flag = "*" if m < 30 else " "
        print(f"  {bucket:<7s}{flag}{m:4d} "
              f"{pct(int(grp['neither_close_ever'].sum()), m):>12s} "
              f"{pct(int(grp['pdc_revert_after'].sum()), m):>10s} "
              f"{pct(int(grp['up_close_after'].sum()), m):>8s} "
              f"{pct(int(grp['dn_close_after'].sum()), m):>8s}")
    print("  * n < 30")

    print(f"\n  Reversal speed (downside open -> upside open): "
          f"median={ev['reversal_min'].median():.0f}m  "
          f"mean={ev['reversal_min'].mean():.0f}m")
    print(f"\nSaved event list to {OUT_CSV}")


if __name__ == "__main__":
    main()

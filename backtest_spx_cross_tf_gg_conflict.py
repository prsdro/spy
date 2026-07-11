"""
SPX Cross-Timeframe Golden Gate Conflict
========================================

Question (verbatim brief)
-------------------------
  When SPX opens a DOWNSIDE *Swing* GG (monthly ATR) that has NOT closed nor
  retraced back above the swing put trigger, but then opens a *Multi-Day* GG to
  the UPSIDE (weekly ATR), which one wins? Do the probabilities of either GG
  closing -- compared to baseline -- change when two GGs are open on different
  timeframes in different directions?

Two timeframes, two gates pointing opposite ways
------------------------------------------------
  Swing mode    -> MONTHLY 14-period Wilder ATR, prior-MONTH close (PMC).
                   Downside gate: open  PMC-38.2%*ATRm  ->  close PMC-61.8%*ATRm
                   Swing put trigger: PMC-23.6%*ATRm
  Multiday mode -> WEEKLY  14-period Wilder ATR, prior-WEEK  close (PWC).
                   Upside gate:   open  PWC+38.2%*ATRw  ->  close PWC+61.8%*ATRw

  After a decline PWC sits well below PMC, so a weekly-frame bounce can OPEN the
  upside weekly gate while price is still far below the monthly put trigger --
  i.e. the monthly downside gate is still wide open. That is the conflict.

Setup (the user's narrative order)
----------------------------------
  1. The downside SWING gate OPENS  (a daily low reaches PMC-38.2%*ATRm).
  2. It is still LIVE: it has not CLOSED (no low <= PMC-61.8%*ATRm) and has not
     RETRACED above the swing put trigger (no high >= PMC-23.6%*ATRm) up to and
     including the entry of the trigger day.
  3. While live, the upside MULTI-DAY gate OPENS (a daily high reaches
     PWC+38.2%*ATRw for that day's week). That day = the TRIGGER day.

"Which wins" race, measured from the trigger day forward
--------------------------------------------------------
  swing_down closes : a low reaches PMC-61.8%*ATRm by month end.
  weekly_up  closes : a high reaches PWC+61.8%*ATRw by that (trigger) week's end.
  Winner = whichever closes on the earlier session; ties flagged.
  (Horizons differ by construction: the monthly gate lives to month end, the
  weekly gate lives to its week end. Both are reported.)

Baseline comparison ("vs baseline")
------------------------------------
  Self-contained, same data, same daily resolution:
    * SWING-DOWN episodes are partitioned into those where an opposite weekly-up
      gate coexists (the setup) vs those where it never does. Completion =
      downside gate ever closes that month (measured identically for both).
    * WEEKLY-UP gates are partitioned into those that open while an opposite
      swing-down gate is live vs those that do not. Completion = upside gate
      closes that same week.
  These two partitions isolate the cross-timeframe-conflict effect directly.

Data: FirstRateData SPX index daily bars (2000-11 -> 2026-05). Daily resolution
means intra-day ordering of a high vs a low is unknown; gates are wide at
weekly/monthly scale so this is rare, and same-day transitions are flagged.

Outputs
-------
  analyst/cross_tf_gg_conflict_events.csv     (one row per setup)
  analyst/cross_tf_gg_conflict_summary.json   (full tables)
  site/data/cross-tf-gg-conflict.json         (compact, for a viz page)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one, atr_series

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "cross_tf_gg_conflict_events.csv"
OUT_JSON = BASE_DIR / "analyst" / "cross_tf_gg_conflict_summary.json"
OUT_SITE = BASE_DIR / "site" / "data" / "cross-tf-gg-conflict.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# Swing gate opens with < this many sessions left in its month cannot fairly
# reach 61.8% before the monthly level resets; their non-completion is a
# calendar artifact. Matches backtest_swing_gg_wom.py.
HORIZON_DAYS = 5


def build_months(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.set_index("timestamp").sort_index()
    mo = d.resample("ME").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    ).dropna(subset=["close"])
    mo["atr_m"] = atr_series(mo, 14).shift(1)
    mo["pmc"] = mo["close"].shift(1)
    return mo


def build_weeks(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.set_index("timestamp").sort_index()
    wk = d.resample("W-FRI").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    ).dropna(subset=["close"])
    wk["atr_w"] = atr_series(wk, 14).shift(1)
    wk["pwc"] = wk["close"].shift(1)
    return wk


def first_idx(mask: np.ndarray):
    """First True position in a boolean array, or None."""
    return int(np.argmax(mask)) if mask.any() else None


def load_daily_with_levels() -> pd.DataFrame:
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
    d = daily.sort_values("timestamp").reset_index(drop=True)
    d["month"] = d["timestamp"].dt.to_period("M")
    d["week"] = d["timestamp"].dt.to_period("W-FRI")

    mo = build_months(daily)
    mo.index = mo.index.to_period("M")
    wk = build_weeks(daily)
    wk.index = wk.index.to_period("W-FRI")

    d["pmc"] = d["month"].map(mo["pmc"])
    d["atr_m"] = d["month"].map(mo["atr_m"])
    d["pwc"] = d["week"].map(wk["pwc"])
    d["atr_w"] = d["week"].map(wk["atr_w"])
    d = d.dropna(subset=["pmc", "atr_m", "pwc", "atr_w"])
    d = d[(d["atr_m"] > 0) & (d["atr_w"] > 0)].reset_index(drop=True)

    # Monthly (swing) levels -- constant within a month.
    d["s_open"] = d["pmc"] - 0.382 * d["atr_m"]    # downside swing open
    d["s_close"] = d["pmc"] - 0.618 * d["atr_m"]   # downside swing close
    d["s_put"] = d["pmc"] - 0.236 * d["atr_m"]     # swing put trigger
    # Weekly (multiday) levels -- constant within a week.
    d["w_up_open"] = d["pwc"] + 0.382 * d["atr_w"]    # upside weekly open
    d["w_up_close"] = d["pwc"] + 0.618 * d["atr_w"]   # upside weekly close
    d["w_up_trig"] = d["pwc"] + 0.236 * d["atr_w"]    # call trigger (weekly)
    return d


# --------------------------------------------------------------------------- #
# Per-month swing-down episode scan + cross-timeframe setup detection
# --------------------------------------------------------------------------- #
def analyze(d: pd.DataFrame):
    d = d.copy().reset_index(drop=True)
    d["sd_live"] = False   # entering-day: a swing-down gate is open & unresolved

    setups = []                      # the cross-tf setup events
    swing_episodes = []              # every first swing-down episode per month
    n_months = 0

    for period, g in d.groupby("month", sort=True):
        n_months += 1
        gi = g.index.to_numpy()
        highs = g["high"].to_numpy()
        lows = g["low"].to_numpy()
        dom = g["timestamp"].dt.day.to_numpy()
        wkper = g["week"].to_numpy()
        w_up_open = g["w_up_open"].to_numpy()
        w_up_close = g["w_up_close"].to_numpy()
        w_up_trig = g["w_up_trig"].to_numpy()
        s_open = g["s_open"].iloc[0]
        s_close = g["s_close"].iloc[0]
        s_put = g["s_put"].iloc[0]
        pmc = g["pmc"].iloc[0]
        atr_m = g["atr_m"].iloc[0]
        n = len(g)

        # First downside swing open this month.
        oi = first_idx(lows <= s_open)
        if oi is None:
            continue

        # Resolution after open: first close (low<=s_close) / first retrace
        # (high>=s_put), each searched from the open day forward.
        rel_close = first_idx(lows[oi:] <= s_close)
        rel_retr = first_idx(highs[oi:] >= s_put)
        closed_idx = (oi + rel_close) if rel_close is not None else None
        retr_idx = (oi + rel_retr) if rel_retr is not None else None
        resolve_idx = min([x for x in (closed_idx, retr_idx) if x is not None],
                          default=n - 1)

        remaining_month = n - oi   # sessions open->month end incl. open day
        clock_trunc = remaining_month < HORIZON_DAYS

        swing_episodes.append({
            "month_end": str(period.end_time.date()),
            "open_dom": int(dom[oi]),
            "remaining_month": int(remaining_month),
            "clock_trunc": bool(clock_trunc),
            "completes": closed_idx is not None,
            "retraces": retr_idx is not None,
        })

        # Mark live-entering days: from open through the resolve day inclusive.
        live_lo, live_hi = oi, resolve_idx
        for j in range(live_lo, live_hi + 1):
            d.at[gi[j], "sd_live"] = True

        # Trigger: first live-entering day whose week's upside gate is open.
        ti = None
        for t in range(oi, resolve_idx + 1):
            if highs[t] >= w_up_open[t]:
                ti = t
                break
        if ti is None:
            continue

        # Same-day transitions on the trigger day.
        same_day_swing_close = (closed_idx == ti)
        same_day_swing_retr = (retr_idx == ti)
        same_day_swing_open = (ti == oi)

        # ---- Swing-down race (horizon = month end) ----
        swing_close_day = closed_idx                       # >= ti by construction
        swing_retr_day = retr_idx                          # >= ti by construction
        swing_closes = swing_close_day is not None

        # ---- Weekly-up race (horizon = trigger week's end) ----
        trig_week = wkper[ti]
        in_week = (wkper == trig_week) & (np.arange(n) >= ti)
        widx = np.where(in_week)[0]
        rel = first_idx(highs[widx] >= w_up_close[ti])
        weekly_close_day = int(widx[rel]) if rel is not None else None
        weekly_closes = weekly_close_day is not None
        remaining_week = int(in_week.sum())   # sessions trigger->week end incl.

        # Does the weekly upside gate get INVALIDATED inside the trigger week --
        # a session AFTER the trigger day pulling back under the weekly call
        # trigger (+23.6% weekly)? (The trigger day itself is excluded: its own
        # low is below the call trigger because price spiked up from a low base.)
        widx_after = widx[widx > ti]
        rel_winv = first_idx(lows[widx_after] <= w_up_trig[ti]) if len(widx_after) else None
        weekly_inv_day = int(widx_after[rel_winv]) if rel_winv is not None else None

        # ---- Winner by earliest closing session ----
        if swing_closes and weekly_closes:
            if weekly_close_day < swing_close_day:
                winner = "weekly_up"
            elif swing_close_day < weekly_close_day:
                winner = "swing_down"
            else:
                winner = "tie_same_day"
        elif swing_closes:
            winner = "swing_down"
        elif weekly_closes:
            winner = "weekly_up"
        else:
            winner = "neither"

        # Close-of-month location relative to monthly frame.
        month_close = g["close"].iloc[-1]
        close_atr_m = (month_close - pmc) / atr_m

        setups.append({
            "month_end": str(period.end_time.date()),
            "trig_date": str(g["timestamp"].iloc[ti].date()),
            "swing_open_dom": int(dom[oi]),
            "days_open_to_trigger": int(ti - oi),
            "remaining_month_at_trigger": int(n - ti),
            "remaining_week_at_trigger": remaining_week,
            "clock_trunc_month": bool(n - ti < HORIZON_DAYS),
            "same_day_swing_open": bool(same_day_swing_open),
            "same_day_swing_close": bool(same_day_swing_close),
            "same_day_swing_retrace": bool(same_day_swing_retr),
            "swing_closes": bool(swing_closes),
            "swing_retraces": bool(swing_retr_day is not None),
            "weekly_closes": bool(weekly_closes),
            "weekly_invalidates": bool(weekly_inv_day is not None),
            "winner": winner,
            "days_trig_to_swing_close": (int(swing_close_day - ti)
                                         if swing_closes else None),
            "days_trig_to_weekly_close": (int(weekly_close_day - ti)
                                          if weekly_closes else None),
            "close_atr_m": round(float(close_atr_m), 3),
            "atr_m": round(float(atr_m), 2),
            "atr_w": round(float(g["atr_w"].iloc[ti]), 2),
        })

    return pd.DataFrame(setups), pd.DataFrame(swing_episodes), d, n_months


# --------------------------------------------------------------------------- #
# Weekly-up gate partition (coexisting swing-down vs not)
# --------------------------------------------------------------------------- #
def weekly_up_partition(d: pd.DataFrame):
    """First upside weekly gate open per week; completion same week; flagged by
    whether a swing-down gate was live entering that open day."""
    rows = []
    for period, g in d.groupby("week", sort=True):
        highs = g["high"].to_numpy()
        w_up_open = g["w_up_open"].to_numpy()
        w_up_close = g["w_up_close"].iloc[0]   # constant within week
        sd_live = g["sd_live"].to_numpy()
        oi = first_idx(highs >= w_up_open)
        if oi is None:
            continue
        completes = bool((highs[oi:] >= w_up_close).any())
        rows.append({
            "week_end": str(period.end_time.date()),
            "remaining_week": int(len(g) - oi),
            "coexist_swing_down": bool(sd_live[oi]),
            "completes": completes,
        })
    return pd.DataFrame(rows)


def rate(sub, col):
    return round(float(sub[col].mean()) * 100, 1) if len(sub) else None


def main():
    print("Loading FirstRateData SPX daily + building levels ...", flush=True)
    d = load_daily_with_levels()
    setups, episodes, d, n_months = analyze(d)
    setups.to_csv(OUT_CSV, index=False)

    n_set = len(setups)
    # --- Swing-down baseline partition (exclude clock-truncated, per swing study) ---
    ep = episodes[~episodes["clock_trunc"]].copy()
    # An episode "has a coexisting weekly-up" iff it produced a setup this month.
    setup_months = set(setups["month_end"])
    ep["coexist_weekly_up"] = ep["month_end"].isin(setup_months)
    ep_yes = ep[ep["coexist_weekly_up"]]
    ep_no = ep[~ep["coexist_weekly_up"]]

    # --- Weekly-up baseline partition ---
    wup = weekly_up_partition(d)
    wup_yes = wup[wup["coexist_swing_down"]]
    wup_no = wup[~wup["coexist_swing_down"]]

    # --- "Which wins" on the setup subset ---
    def winner_share(df, key):
        return round(float((df["winner"] == key).mean()) * 100, 1) if len(df) else None

    setups_fair = setups[~setups["clock_trunc_month"]].copy()

    payload = {
        "meta": {
            "ticker": "SPX",
            "source": "FirstRateData SPX index daily",
            "date_start": str(d["timestamp"].min().date()),
            "date_end": str(d["timestamp"].max().date()),
            "n_months": int(n_months),
            "horizon_days": HORIZON_DAYS,
            "swing_down_episodes": int(len(episodes)),
            "swing_down_episodes_fair": int(len(ep)),
            "n_setups": int(n_set),
            "n_setups_fair": int(len(setups_fair)),
        },
        "which_wins": {
            "n": int(n_set),
            "weekly_up": winner_share(setups, "weekly_up"),
            "swing_down": winner_share(setups, "swing_down"),
            "tie_same_day": winner_share(setups, "tie_same_day"),
            "neither": winner_share(setups, "neither"),
            "swing_closes": rate(setups, "swing_closes"),
            "weekly_closes": rate(setups, "weekly_closes"),
            "swing_retraces": rate(setups, "swing_retraces"),
            "weekly_invalidates": rate(setups, "weekly_invalidates"),
            "close_atr_m_median": round(float(setups["close_atr_m"].median()), 3) if n_set else None,
            "days_open_to_trigger_median": int(setups["days_open_to_trigger"].median()) if n_set else None,
        },
        "which_wins_fair": {
            "n": int(len(setups_fair)),
            "weekly_up": winner_share(setups_fair, "weekly_up"),
            "swing_down": winner_share(setups_fair, "swing_down"),
            "tie_same_day": winner_share(setups_fair, "tie_same_day"),
            "neither": winner_share(setups_fair, "neither"),
            "swing_closes": rate(setups_fair, "swing_closes"),
            "weekly_closes": rate(setups_fair, "weekly_closes"),
        },
        "swing_down_completion": {
            "coexist_weekly_up": {"n": int(len(ep_yes)), "completes": rate(ep_yes, "completes")},
            "no_coexist": {"n": int(len(ep_no)), "completes": rate(ep_no, "completes")},
            "all": {"n": int(len(ep)), "completes": rate(ep, "completes")},
        },
        "weekly_up_completion": {
            "coexist_swing_down": {"n": int(len(wup_yes)), "completes": rate(wup_yes, "completes")},
            "no_coexist": {"n": int(len(wup_no)), "completes": rate(wup_no, "completes")},
            "all": {"n": int(len(wup)), "completes": rate(wup, "completes")},
        },
    }

    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    OUT_SITE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SITE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    # -------------------- console report --------------------
    m = payload["meta"]
    print(f"\nMonths analyzed: {m['n_months']:,}  ({m['date_start']} -> {m['date_end']})")
    print(f"Downside SWING episodes (first open/month): {m['swing_down_episodes']:,}  "
          f"(fair, >= {HORIZON_DAYS} sessions left: {m['swing_down_episodes_fair']:,})")
    print(f"Cross-TF SETUPS (live swing-down + weekly-up opens): {m['n_setups']:,}  "
          f"(fair: {m['n_setups_fair']:,})")

    w = payload["which_wins"]
    print("\n" + "=" * 70)
    print(f"  WHICH WINS  (setup subset, n={w['n']})")
    print("=" * 70)
    print(f"  Weekly-UP closes first (+61.8% weekly): {w['weekly_up']}%")
    print(f"  Swing-DOWN closes first (-61.8% monthly): {w['swing_down']}%")
    print(f"  Tie (same session):                      {w['tie_same_day']}%")
    print(f"  Neither closes in its horizon:           {w['neither']}%")
    print(f"  -- swing-down ever closes (month):  {w['swing_closes']}%")
    print(f"  -- weekly-up  ever closes (week):   {w['weekly_closes']}%")
    print(f"  -- swing-down retraces put trigger after: {w['swing_retraces']}%")
    print(f"  -- weekly-up  pulls back under call trig: {w['weekly_invalidates']}%")
    print(f"  Median days swing-open -> trigger: {w['days_open_to_trigger_median']}")
    print(f"  Month-end close vs PMC (median monthly ATR): {w['close_atr_m_median']:+}")

    sd = payload["swing_down_completion"]
    print("\n" + "=" * 70)
    print("  SWING-DOWN completion vs baseline  (does the opposite weekly-up matter?)")
    print("=" * 70)
    print(f"  With coexisting weekly-up gate (setup): {sd['coexist_weekly_up']['completes']}%  "
          f"(n={sd['coexist_weekly_up']['n']})")
    print(f"  No coexisting weekly-up gate:           {sd['no_coexist']['completes']}%  "
          f"(n={sd['no_coexist']['n']})")
    print(f"  All downside swing episodes (baseline): {sd['all']['completes']}%  "
          f"(n={sd['all']['n']})")

    wu = payload["weekly_up_completion"]
    print("\n" + "=" * 70)
    print("  WEEKLY-UP completion vs baseline  (does a live opposite swing-down matter?)")
    print("=" * 70)
    print(f"  Opens while swing-down is live (setup): {wu['coexist_swing_down']['completes']}%  "
          f"(n={wu['coexist_swing_down']['n']})")
    print(f"  Opens with no live swing-down:          {wu['no_coexist']['completes']}%  "
          f"(n={wu['no_coexist']['n']})")
    print(f"  All upside weekly gates (baseline):     {wu['all']['completes']}%  "
          f"(n={wu['all']['n']})")

    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}\nWrote {OUT_SITE}")


if __name__ == "__main__":
    main()

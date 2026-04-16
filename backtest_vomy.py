"""
3-Minute Vomy Study
===================

WHAT IS A VOMY?
A "vomy" is a momentum failure pattern on the 3-minute chart. It occurs when
the 3m Pivot Ribbon has been fully bullish (all EMAs stacked upward), and then
price loses the 48 EMA — closing below it. Visually, the ribbon compresses,
the Phase Oscillator rolls over, and once the 48 EMA is lost, price often dumps
further as the ribbon flips bearish.

Sometimes, though, the vomy FAILS — price consolidates or recovers the 21 EMA
and continues higher. This study measures how often vomys follow through vs
fail, segmented by market context.

The inverse (bearish ribbon → close above 48 EMA) is also studied.


METHODOLOGY
-----------

1. EVENT IDENTIFICATION — "The Vomy Trigger"

   We scan 3-minute RTH bars (09:30–15:59) looking for:

   a) LOOKBACK CHECK: Within the prior 20 bars (~60 minutes), at least one bar
      had a fully bullish ribbon:
        - fast_cloud_bullish = 1  (EMA 8 >= EMA 21)
        - slow_cloud_bullish = 1  (EMA 13 >= EMA 48)

      This is intentionally loose. In practice the ribbon degrades gradually:
      the fast cloud compresses first, then the slow cloud follows. By the time
      price actually closes below the 48 EMA, the ribbon may already be mixed.
      Requiring the prior bar to be fully bullish would miss most real vomys.

   b) TRIGGER BAR: The current bar closes below the 3m 48 EMA:
        - close < ema_48

   c) DEDUPLICATION: This must be the FIRST close below the 48 EMA since the
      ribbon was last fully bullish. We track state per-day to avoid counting
      the same breakdown multiple times. Once a bullish vomy fires, we require
      the ribbon to return to fully bullish before another can fire.

   For BEARISH VOMYS (inverse), we look for:
   a) Ribbon was fully bearish within 20 bars (both clouds bearish)
   b) Current bar closes ABOVE the 48 EMA
   c) First close above since ribbon was last fully bearish


2. OUTCOME CLASSIFICATION — "What Happens Next"

   After a vomy fires, we look forward up to 40 bars (~120 minutes, or until
   end of RTH, whichever comes first) and classify the outcome:

   a) FOLLOW-THROUGH (vomy works):
      Price makes a sustained move in the breakdown direction.
      Measured as: the lowest low (for bullish vomy) in the forward window
      drops at least 0.15% below the trigger bar's low.

   b) RECOVERY (vomy fails):
      Price recovers the 3m 21 EMA and holds it.
      Measured as: at least 3 consecutive bars close above the 3m 21 EMA
      within the forward window.

   c) COMPRESSION (vomy stalls):
      The 3m Phase Oscillator enters compression before a directional move.
      Measured as: compression=1 appears within the forward window before
      either follow-through or recovery is detected.

   If multiple outcomes occur, priority is: Recovery > Compression > Follow-through.
   (Recovery overrides because if price recovered the 21 EMA for 3+ bars,
   the vomy has functionally failed regardless of any earlier dip.)

   We also measure MAX ADVERSE MOVE: the maximum favorable excursion in the
   breakdown direction (how far price dropped after the vomy), expressed as
   a percentage of price. This gives us magnitude, not just direction.


3. CONTEXT VARIABLES — "Segmentation Dimensions"

   Each vomy event is tagged with context at the moment it fires:

   a) 10-MINUTE RIBBON STATE
      We merge the 3m vomy timestamp against ind_10m using merge_asof
      (backward direction) to get the 10m ribbon state at that moment.
      Categories:
        - "10m bullish":  fast_cloud_bullish=1 AND slow_cloud_bullish=1
        - "10m mixed":    fast_cloud_bullish != slow_cloud_bullish
        - "10m bearish":  fast_cloud_bullish=0 AND slow_cloud_bullish=0

   b) ATR LEVEL POSITION
      Using the daily ATR levels on the 3m bar (broadcast from daily),
      we categorize where the vomy occurred relative to the ATR grid:
        - "above 61.8%":   close > atr_upper_0618 (extended upside)
        - "38.2%–61.8%":   close > atr_upper_0382 (inside bull GG)
        - "trigger–38.2%": close > atr_upper_trigger (above call trigger)
        - "trigger box":   close between prev_close and trigger
        - "below PDC":     close < prev_close (other side of grid)
      (Mirrored for bearish vomys using lower levels.)

   c) PHASE OSCILLATOR LEVEL AT TRIGGER
      The 3m PO value when the vomy fires, bucketed:
        - "PO > 40":    Still elevated — early breakdown
        - "PO 0–40":    Rolling over — typical timing
        - "PO < 0":     Already negative — late breakdown
      (Inverted thresholds for bearish vomys.)

   d) CONVICTION SIGNAL
      Whether the 13/48 EMA crossover (conviction_bear for bullish vomy,
      conviction_bull for bearish vomy) has fired on ANY bar between the
      lookback window start and the trigger bar. This bearish crossover
      often precedes or coincides with the vomy.

   e) TIME OF DAY
      Bucketed into:
        - "open"  (09:30–10:30): First hour
        - "mid"   (10:30–14:00): Midday
        - "close" (14:00–16:00): Last two hours


4. OUTPUT

   For each direction (bullish vomy / bearish vomy):
     - Baseline stats: total events, follow-through %, recovery %, compression %
     - Contingency tables for each segmentation dimension
     - Mean and median max adverse move per outcome category
     - Sample sizes for every cell
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")

# ── Parameters ──
LOOKBACK = 20          # bars to look back for "was bullish" (20 × 3m = 60 min)
FORWARD = 10           # bars to look forward for outcome (10 × 3m = 30 min)
FOLLOW_THROUGH_PCT = 0.15  # minimum % move for follow-through
RECOVERY_BARS = 3      # consecutive bars above 21 EMA to count as recovery


def classify_outcome(trigger_idx, direction, df_day, trigger_bar):
    """
    Classify the outcome of a vomy event.

    Returns (outcome, max_adverse_pct)
      outcome: "follow_through", "recovery", or "compression"
      max_adverse_pct: max favorable excursion in breakdown direction (%)
    """
    start = trigger_idx + 1
    end = min(trigger_idx + 1 + FORWARD, len(df_day))
    forward = df_day.iloc[start:end]

    if len(forward) == 0:
        return "insufficient_data", 0.0

    trigger_low = trigger_bar["low"]
    trigger_high = trigger_bar["high"]
    trigger_price = trigger_bar["close"]

    if direction == "bull":
        # Bullish vomy = breakdown, we expect price to DROP
        max_adverse = forward["low"].min()
        max_adverse_pct = (trigger_low - max_adverse) / trigger_price * 100

        # Check recovery: 3+ consecutive closes above the 21 EMA
        above_21 = (forward["close"] > forward["ema_21"]).values
        recovery = False
        consec = 0
        for val in above_21:
            if val:
                consec += 1
                if consec >= RECOVERY_BARS:
                    recovery = True
                    break
            else:
                consec = 0

        # Check compression
        compression = (forward["compression"] == 1).any()

        # Check follow-through
        follow_through = max_adverse_pct >= FOLLOW_THROUGH_PCT

    else:
        # Bearish vomy = breakUP, we expect price to RISE
        max_adverse = forward["high"].max()
        max_adverse_pct = (max_adverse - trigger_high) / trigger_price * 100

        # Check recovery: 3+ consecutive closes below the 21 EMA
        below_21 = (forward["close"] < forward["ema_21"]).values
        recovery = False
        consec = 0
        for val in below_21:
            if val:
                consec += 1
                if consec >= RECOVERY_BARS:
                    recovery = True
                    break
            else:
                consec = 0

        compression = (forward["compression"] == 1).any()
        follow_through = max_adverse_pct >= FOLLOW_THROUGH_PCT

    # Priority: recovery > compression > follow_through
    if recovery:
        outcome = "recovery"
    elif compression:
        outcome = "compression"
    elif follow_through:
        outcome = "follow_through"
    else:
        outcome = "fade"  # didn't move enough either way

    return outcome, max_adverse_pct


def get_atr_position(bar, direction):
    """Categorize where the vomy occurred on the ATR grid."""
    price = bar["close"]
    pdc = bar["prev_close"]

    if pd.isna(pdc) or pd.isna(bar.get("atr_upper_trigger")):
        return "unknown"

    if direction == "bull":
        # Bullish vomy (losing bullish ribbon) — where was price on the upside grid?
        if price > bar["atr_upper_0618"]:
            return "above 61.8%"
        elif price > bar["atr_upper_0382"]:
            return "38.2%-61.8%"
        elif price > bar["atr_upper_trigger"]:
            return "trigger-38.2%"
        elif price > pdc:
            return "trigger box"
        else:
            return "below PDC"
    else:
        # Bearish vomy (losing bearish ribbon) — where was price on the downside grid?
        if price < bar["atr_lower_0618"]:
            return "below -61.8%"
        elif price < bar["atr_lower_0382"]:
            return "-38.2% to -61.8%"
        elif price < bar["atr_lower_trigger"]:
            return "trigger to -38.2%"
        elif price < pdc:
            return "trigger box"
        else:
            return "above PDC"


def get_po_bucket(po_val, direction):
    """Bucket the Phase Oscillator level at trigger time."""
    if pd.isna(po_val):
        return "unknown"
    if direction == "bull":
        if po_val > 40:
            return "PO > 40"
        elif po_val >= 0:
            return "PO 0-40"
        else:
            return "PO < 0"
    else:
        if po_val < -40:
            return "PO < -40"
        elif po_val <= 0:
            return "PO -40 to 0"
        else:
            return "PO > 0"


def get_time_bucket(timestamp):
    """Bucket time of day."""
    t = timestamp.time()
    if t < pd.Timestamp("10:30").time():
        return "open (9:30-10:30)"
    elif t < pd.Timestamp("14:00").time():
        return "mid (10:30-14:00)"
    else:
        return "close (14:00-16:00)"


def main():
    conn = sqlite3.connect(DB_PATH)

    # ── Load 3m data ──
    print("Loading 3m data...", flush=True)
    df3 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "ema_8, ema_13, ema_21, ema_48, "
        "fast_cloud_bullish, slow_cloud_bullish, "
        "conviction_bull, conviction_bear, "
        "compression, phase_oscillator, "
        "prev_close, atr_14, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618 "
        "FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df3 = df3.set_index("timestamp").sort_index()
    df3 = df3.between_time("09:30", "15:59")
    df3 = df3.dropna(subset=["ema_48", "prev_close", "atr_14"])
    df3["date"] = df3.index.date

    # ── Load 10m data for cross-timeframe context ──
    print("Loading 10m data...", flush=True)
    df10 = pd.read_sql_query(
        "SELECT timestamp, fast_cloud_bullish, slow_cloud_bullish "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df10 = df10.set_index("timestamp").sort_index()
    conn.close()

    print(f"3m bars: {len(df3):,}  |  10m bars: {len(df10):,}")
    print("Scanning for vomy events...\n", flush=True)

    # ── Scan for vomys ──
    for direction, label in [("bull", "BULLISH VOMY"), ("bear", "BEARISH VOMY")]:
        events = []

        for date, group in df3.groupby("date"):
            if len(group) < LOOKBACK + 5:
                continue

            # State machine: track whether we're eligible to fire a vomy
            # Reset each day. Must see a fully-stacked ribbon before a vomy can fire.
            armed = False  # True once we've seen a fully-stacked ribbon
            fired = False  # True once a vomy fires; reset when ribbon re-stacks

            for i in range(len(group)):
                bar = group.iloc[i]

                if direction == "bull":
                    ribbon_full = (bar["fast_cloud_bullish"] == 1 and
                                   bar["slow_cloud_bullish"] == 1)
                    lost_48 = bar["close"] < bar["ema_48"]
                else:
                    ribbon_full = (bar["fast_cloud_bullish"] == 0 and
                                   bar["slow_cloud_bullish"] == 0)
                    lost_48 = bar["close"] > bar["ema_48"]

                # Check lookback for fully-stacked ribbon
                if not armed and not fired:
                    lb_start = max(0, i - LOOKBACK)
                    lb_slice = group.iloc[lb_start:i+1]
                    if direction == "bull":
                        had_full = ((lb_slice["fast_cloud_bullish"] == 1) &
                                    (lb_slice["slow_cloud_bullish"] == 1)).any()
                    else:
                        had_full = ((lb_slice["fast_cloud_bullish"] == 0) &
                                    (lb_slice["slow_cloud_bullish"] == 0)).any()
                    if had_full:
                        armed = True

                # If ribbon restacks, re-arm for the next potential vomy
                if ribbon_full:
                    armed = True
                    fired = False

                # Fire the vomy
                if armed and not fired and lost_48:
                    fired = True
                    armed = False

                    # ── Classify outcome ──
                    outcome, max_adv = classify_outcome(i, direction, group, bar)

                    # ── 10m ribbon context (merge_asof) ──
                    ts = group.index[i]
                    loc = df10.index.searchsorted(ts, side="right") - 1
                    if 0 <= loc < len(df10):
                        r10 = df10.iloc[loc]
                        if r10["fast_cloud_bullish"] == 1 and r10["slow_cloud_bullish"] == 1:
                            tf10_state = "10m bullish"
                        elif r10["fast_cloud_bullish"] == 0 and r10["slow_cloud_bullish"] == 0:
                            tf10_state = "10m bearish"
                        else:
                            tf10_state = "10m mixed"
                    else:
                        tf10_state = "unknown"

                    # ── ATR position ──
                    atr_pos = get_atr_position(bar, direction)

                    # ── PO bucket ──
                    po_bucket = get_po_bucket(bar["phase_oscillator"], direction)

                    # ── Conviction signal in lookback window ──
                    lb_start = max(0, i - LOOKBACK)
                    lb_slice = group.iloc[lb_start:i+1]
                    if direction == "bull":
                        had_conviction = (lb_slice["conviction_bear"] == 1).any()
                    else:
                        had_conviction = (lb_slice["conviction_bull"] == 1).any()

                    # ── Time of day ──
                    time_bucket = get_time_bucket(ts)

                    events.append({
                        "date": date,
                        "time": ts,
                        "price": bar["close"],
                        "outcome": outcome,
                        "max_adverse_pct": max_adv,
                        "tf10_state": tf10_state,
                        "atr_position": atr_pos,
                        "po_bucket": po_bucket,
                        "conviction": had_conviction,
                        "time_bucket": time_bucket,
                    })

        # ── Results ──
        df_ev = pd.DataFrame(events)
        if len(df_ev) == 0:
            print(f"No {label} events found.\n")
            continue

        # Exclude insufficient data
        df_ev = df_ev[df_ev["outcome"] != "insufficient_data"]

        pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"
        total = len(df_ev)
        ft = (df_ev["outcome"] == "follow_through").sum()
        rec = (df_ev["outcome"] == "recovery").sum()
        comp = (df_ev["outcome"] == "compression").sum()
        fade = (df_ev["outcome"] == "fade").sum()

        print(f"{'='*75}")
        print(f"  {label} (3m ribbon was bullish → close below 48 EMA)"
              if direction == "bull" else
              f"  {label} (3m ribbon was bearish → close above 48 EMA)")
        print(f"{'='*75}")
        print(f"  Total events:    {total:,}")
        print(f"  Date range:      {df_ev['date'].min()} to {df_ev['date'].max()}")
        print()
        print(f"  --- Baseline Outcomes ---")
        print(f"  Follow-through:  {pct(ft, total):>6}  ({ft:,}/{total:,})  ← vomy works, price dumps")
        print(f"  Recovery:        {pct(rec, total):>6}  ({rec:,}/{total:,})  ← vomy fails, price recovers 21 EMA")
        print(f"  Compression:     {pct(comp, total):>6}  ({comp:,}/{total:,})  ← stalls, PO compresses")
        print(f"  Fade:            {pct(fade, total):>6}  ({fade:,}/{total:,})  ← weak move, no clear outcome")
        print()

        # Max adverse move by outcome
        print(f"  --- Max Adverse Move (% of price, in breakdown direction) ---")
        for oc in ["follow_through", "recovery", "compression", "fade"]:
            subset = df_ev[df_ev["outcome"] == oc]["max_adverse_pct"]
            if len(subset) > 0:
                print(f"  {oc:18s}  mean={subset.mean():.3f}%  median={subset.median():.3f}%  (n={len(subset):,})")
        print()

        # ── Segmentation tables ──
        dimensions = [
            ("10m Ribbon State",     "tf10_state",   ["10m bullish", "10m mixed", "10m bearish"]),
            ("ATR Level Position",   "atr_position",
             (["above 61.8%", "38.2%-61.8%", "trigger-38.2%", "trigger box", "below PDC"]
              if direction == "bull" else
              ["below -61.8%", "-38.2% to -61.8%", "trigger to -38.2%", "trigger box", "above PDC"])),
            ("PO at Trigger",        "po_bucket",
             (["PO > 40", "PO 0-40", "PO < 0"] if direction == "bull" else
              ["PO < -40", "PO -40 to 0", "PO > 0"])),
            ("Conviction Signal",    "conviction",   [True, False]),
            ("Time of Day",          "time_bucket",
             ["open (9:30-10:30)", "mid (10:30-14:00)", "close (14:00-16:00)"]),
        ]

        for dim_label, dim_col, categories in dimensions:
            print(f"  --- By {dim_label} ---")
            print(f"  {'Category':24s} {'Total':>6}  {'Follow%':>8}  {'Recov%':>8}  {'Compr%':>8}  {'Fade%':>8}  {'MeanAdv%':>9}")
            print(f"  {'-'*24} {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*9}")
            for cat in categories:
                sub = df_ev[df_ev[dim_col] == cat]
                n = len(sub)
                if n == 0:
                    print(f"  {str(cat):24s} {n:>6}")
                    continue
                f = (sub["outcome"] == "follow_through").sum()
                r = (sub["outcome"] == "recovery").sum()
                c = (sub["outcome"] == "compression").sum()
                d = (sub["outcome"] == "fade").sum()
                ma = sub["max_adverse_pct"].mean()
                print(f"  {str(cat):24s} {n:>6}  {pct(f,n):>8}  {pct(r,n):>8}  {pct(c,n):>8}  {pct(d,n):>8}  {ma:>8.3f}%")
            print()

        # ── Cross-tab: 10m state × ATR position (most actionable combo) ──
        print(f"  --- Cross-tab: 10m Ribbon × ATR Position (Follow-through %) ---")
        atr_cats = (["above 61.8%", "38.2%-61.8%", "trigger-38.2%", "trigger box", "below PDC"]
                    if direction == "bull" else
                    ["below -61.8%", "-38.2% to -61.8%", "trigger to -38.2%", "trigger box", "above PDC"])
        tf10_cats = ["10m bullish", "10m mixed", "10m bearish"]

        header = f"  {'':16s}" + "".join(f"{a:>16s}" for a in atr_cats)
        print(header)
        for tf in tf10_cats:
            row = f"  {tf:16s}"
            for atr in atr_cats:
                sub = df_ev[(df_ev["tf10_state"] == tf) & (df_ev["atr_position"] == atr)]
                n = len(sub)
                if n < 5:
                    row += f"{'—':>16s}"
                else:
                    ft_pct = (sub["outcome"] == "follow_through").sum() / n * 100
                    row += f"{ft_pct:>10.1f}% n={n:<3d}"
            print(row)
        print()

    print("Done.")


if __name__ == "__main__":
    main()

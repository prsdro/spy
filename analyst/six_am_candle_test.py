#!/usr/bin/env python3
"""Backtest the '6AM candle predicts NY session direction' claim on ES 1-min.

Rules under test (verbatim from the viral post):
  - Mark yesterday's high and low (PDH/PDL).
  - 6AM (ET) hourly candle:
      * sweeps PDH but closes back below it  -> reversal day, short at 9:30
      * sweeps PDL but closes back above it  -> reversal day, long at 9:30
      * closes beyond PDH                    -> trend day, long bias
      * closes below PDL                     -> trend day, short bias
  - Outcome: NY session direction = 16:00 close vs 9:30 open.

Two PDH/PDL definitions tested: RTH-only (9:30-16:00) and full session
(18:00 prev -> 17:00). Baselines: coin flip and always-long.
"""
import csv
import math
from collections import defaultdict
from datetime import datetime, timedelta

PATH = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"

# ---- load and bucket by calendar date (ET) and by futures session ----
# per-day stores
rth_hl = {}          # date -> [hi, lo] over 09:30-15:59
full_hl = {}         # session_date -> [hi, lo] over 18:00 prev day .. 16:59
six = {}             # date -> dict(open, high, low, close) over 06:00-06:59
open_930 = {}        # date -> open of 09:30 bar
close_1600 = {}      # date -> close of last bar in [09:30, 16:00)

with open(PATH) as f:
    for line in f:
        ts, o, h, l, c, v = line.rstrip("\n").split(",")
        d = ts[:10]
        hm = ts[11:16]
        o = float(o); h = float(h); l = float(l); c = float(c)
        if "09:30" <= hm <= "15:59":
            r = rth_hl.get(d)
            if r is None:
                rth_hl[d] = [h, l]
            else:
                if h > r[0]: r[0] = h
                if l < r[1]: r[1] = l
            if hm == "09:30":
                open_930[d] = o
            close_1600[d] = c  # last write in window wins
        if "06:00" <= hm <= "06:59":
            s = six.get(d)
            if s is None:
                six[d] = {"open": o, "high": h, "low": l, "close": c}
            else:
                if h > s["high"]: s["high"] = h
                if l < s["low"]: s["low"] = l
                s["close"] = c
        # full-session H/L: session labeled by its RTH date (18:00 rolls forward)
        if hm >= "18:00":
            sd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        elif hm < "17:00":
            sd = d
        else:
            sd = None
        if sd:
            r = full_hl.get(sd)
            if r is None:
                full_hl[sd] = [h, l]
            else:
                if h > r[0]: r[0] = h
                if l < r[1]: r[1] = l

days = sorted(set(rth_hl) & set(open_930) & set(close_1600))
print(f"days with RTH data: {len(days)}  ({days[0]} .. {days[-1]})")

def classify(s, pdh, pdl):
    """Return (signal_name, predicted_direction) or (None, 0)."""
    swept_hi = s["high"] > pdh
    swept_lo = s["low"] < pdl
    close = s["close"]
    if swept_hi and swept_lo:
        return ("both_sweep", 0)
    if swept_hi:
        return ("break_high_hold", +1) if close > pdh else ("sweep_high_reject", -1)
    if swept_lo:
        return ("break_low_hold", -1) if close < pdl else ("sweep_low_reject", +1)
    return ("inside", 0)

def tstat(xs):
    n = len(xs)
    if n < 3: return float("nan")
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m / math.sqrt(var / n) if var > 0 else float("nan")

def binom_z(k, n):
    if n == 0: return float("nan")
    return (k - n * 0.5) / math.sqrt(n * 0.25)

for defname, hl_map, prior_lookup in (
    ("RTH prior-day H/L", rth_hl, "prev_rth"),
    ("Full-session prior-day H/L", full_hl, "prev_full"),
):
    print(f"\n================ PDH/PDL definition: {defname} ================")
    rows = []
    prev_day = None
    for d in days:
        if d not in six:
            prev_day = d
            continue
        # prior day's H/L
        if prior_lookup == "prev_rth":
            ref = rth_hl.get(prev_day) if prev_day else None
        else:
            # prior full session = full_hl of previous trading day label
            ref = full_hl.get(prev_day) if prev_day else None
        if ref is None:
            prev_day = d
            continue
        pdh, pdl = ref
        sig, pred = classify(six[d], pdh, pdl)
        sess_ret = close_1600[d] - open_930[d]
        rows.append((d, sig, pred, sess_ret, open_930[d]))
        prev_day = d

    # unconditional baseline
    all_rets = [r[3] for r in rows]
    up_days = sum(1 for r in rows if r[3] > 0)
    print(f"all days n={len(rows)}  up-session rate={up_days/len(rows):.1%}  "
          f"mean session pts={sum(all_rets)/len(all_rets):+.2f}  t={tstat(all_rets):.2f}")

    by_sig = defaultdict(list)
    for d, sig, pred, ret, o in rows:
        by_sig[sig].append((pred, ret, o, d))

    print(f"\n{'signal':<20}{'n':>6}{'hit%':>8}{'z':>7}{'mean pts':>10}{'mean bps':>10}{'t':>7}")
    for sig in ("sweep_high_reject", "sweep_low_reject", "break_high_hold",
                "break_low_hold", "inside", "both_sweep"):
        grp = by_sig.get(sig, [])
        n = len(grp)
        if n == 0:
            continue
        if sig in ("inside", "both_sweep"):
            print(f"{sig:<20}{n:>6}{'--':>8}{'--':>7}{'--':>10}{'--':>10}{'--':>7}")
            continue
        hits = sum(1 for p, r, o, d in grp if p * r > 0)
        signed_pts = [p * r for p, r, o, d in grp]
        signed_bps = [p * r / o * 1e4 for p, r, o, d in grp]
        nonzero = sum(1 for p, r, o, d in grp if r != 0)
        print(f"{sig:<20}{n:>6}{hits/nonzero:>8.1%}{binom_z(hits, nonzero):>7.2f}"
              f"{sum(signed_pts)/n:>+10.2f}{sum(signed_bps)/n:>+10.1f}{tstat(signed_bps):>7.2f}")

    # pooled all-signal
    pooled = [(p, r, o, d) for sig in ("sweep_high_reject","sweep_low_reject",
              "break_high_hold","break_low_hold") for (p, r, o, d) in by_sig.get(sig, [])]
    hits = sum(1 for p, r, o, d in pooled if p * r > 0)
    nz = sum(1 for p, r, o, d in pooled if r != 0)
    sb = [p * r / o * 1e4 for p, r, o, d in pooled]
    print(f"{'ALL SIGNALS':<20}{len(pooled):>6}{hits/nz:>8.1%}{binom_z(hits, nz):>7.2f}"
          f"{'':>10}{sum(sb)/len(sb):>+10.1f}{tstat(sb):>7.2f}")

    # per-year hit rate, pooled signals
    by_year = defaultdict(lambda: [0, 0])
    for p, r, o, d in pooled:
        if r != 0:
            by_year[d[:4]][0] += 1 if p * r > 0 else 0
            by_year[d[:4]][1] += 1
    print("\nper-year pooled hit rate:")
    for y in sorted(by_year):
        k, n = by_year[y]
        print(f"  {y}: {k:>3}/{n:<3} = {k/n:.0%}")

    # best 15-day streak check (the '14 of 15' claim), pooled signals in date order
    seq = [(d, 1 if p * r > 0 else 0) for p, r, o, d in sorted(pooled, key=lambda x: x[3]) if r != 0]
    best = 0
    for i in range(len(seq) - 14):
        s = sum(x[1] for x in seq[i:i+15])
        if s > best:
            best = s
    print(f"\nbest hit-count in any 15 consecutive signal days: {best}/15")

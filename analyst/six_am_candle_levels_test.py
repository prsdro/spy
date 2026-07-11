#!/usr/bin/env python3
"""6AM candle sweep/reject vs break/hold — tested against Saty ATR levels
and significant swing highs/lows instead of PDH/PDL.

Levels per day (from prior RTH data only, live-knowable at 6AM):
  - Saty ladder: pivot (prior close) +/- {0.236, 0.382, 0.618, 1.0, 1.236,
    1.618} x 14d Wilder ATR (recomputed from daily RTH bars, per memory:
    never trust stored ind_* columns)
  - Swing levels: rolling 5-day and 20-day prior RTH high/low

Event per (day, level): 6AM hourly candle CROSSES the level
  up-cross   (open < L, high > L):  close > L -> hold (pred +1)
                                    close < L -> reject (pred -1)
  down-cross (open > L, low < L):   close < L -> hold (pred -1)
                                    close > L -> reject (pred +1)
Grade: NY session direction, 9:30 open -> 16:00 close. Baseline: 53.8% up.
"""
import math
from collections import defaultdict

PATH = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"

rth = {}             # date -> [open, high, low, close] RTH
six = {}             # date -> dict(open, high, low, close) 06:00-06:59
open_930 = {}
close_1600 = {}

with open(PATH) as f:
    for line in f:
        ts, o, h, l, c, v = line.rstrip("\n").split(",")
        d = ts[:10]; hm = ts[11:16]
        o = float(o); h = float(h); l = float(l); c = float(c)
        if "09:30" <= hm <= "15:59":
            r = rth.get(d)
            if r is None:
                rth[d] = [o, h, l, c]
                open_930[d] = o
            else:
                if h > r[1]: r[1] = h
                if l < r[2]: r[2] = l
                r[3] = c
            close_1600[d] = c
        elif "06:00" <= hm <= "06:59":
            s = six.get(d)
            if s is None:
                six[d] = {"open": o, "high": h, "low": l, "close": c}
            else:
                if h > s["high"]: s["high"] = h
                if l < s["low"]: s["low"] = l
                s["close"] = c

days = sorted(rth)
# Wilder ATR-14 from daily RTH bars
atr = {}
prev_close = None
cur = None
trs = []
for i, d in enumerate(days):
    o, h, l, c = rth[d]
    tr = h - l if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
    if cur is None:
        trs.append(tr)
        if len(trs) == 14:
            cur = sum(trs) / 14
    else:
        cur = (cur * 13 + tr) / 14
    if cur is not None:
        atr[d] = cur          # ATR as of end of day d (usable next day)
    prev_close = c

FIBS = [0.236, 0.382, 0.618, 1.0, 1.236, 1.618]

def tstat(xs):
    n = len(xs)
    if n < 3: return float("nan")
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m / math.sqrt(var / n) if var > 0 else float("nan")

# build events
events = defaultdict(list)   # (level_name, cross_dir, kind) -> list of (pred, ret_pts, o930, date)
for i, d in enumerate(days):
    if i < 21 or d not in six or d not in open_930:
        continue
    pd_ = days[i - 1]
    if pd_ not in atr:
        continue
    pc = rth[pd_][3]
    a = atr[pd_]
    levels = {"pivot": pc}
    for f in FIBS:
        levels[f"+{f}atr"] = pc + f * a
        levels[f"-{f}atr"] = pc - f * a
    hist5 = [rth[days[j]] for j in range(i - 5, i)]
    hist20 = [rth[days[j]] for j in range(i - 20, i)]
    levels["hi5"] = max(b[1] for b in hist5)
    levels["lo5"] = min(b[2] for b in hist5)
    levels["hi20"] = max(b[1] for b in hist20)
    levels["lo20"] = min(b[2] for b in hist20)

    s = six[d]
    ret = close_1600[d] - open_930[d]
    o930 = open_930[d]
    for name, L in levels.items():
        if s["open"] < L < s["high"]:      # up-cross
            kind = "hold" if s["close"] > L else "reject"
            pred = +1 if kind == "hold" else -1
            events[(name, "up", kind)].append((pred, ret, o930, d))
        elif s["open"] > L > s["low"]:     # down-cross
            kind = "hold" if s["close"] < L else "reject"
            pred = -1 if kind == "hold" else +1
            events[(name, "dn", kind)].append((pred, ret, o930, d))

def report(key, grp):
    n = len(grp)
    nz = [(p, r, o) for p, r, o, d in grp if r != 0]
    hits = sum(1 for p, r, o in nz if p * r > 0)
    bps = [p * r / o * 1e4 for p, r, o, d in grp]
    hr = hits / len(nz) if nz else float("nan")
    z = (hits - len(nz) * 0.5) / math.sqrt(len(nz) * 0.25) if nz else float("nan")
    print(f"{key:<28}{n:>5}{hr:>8.1%}{z:>7.2f}{sum(bps)/n:>+10.1f}{tstat(bps):>7.2f}")

print(f"{'level / cross / kind':<28}{'n':>5}{'hit%':>8}{'z50':>7}{'mean bps':>10}{'t':>7}")
order = (["pivot"] + [f"+{f}atr" for f in FIBS] + [f"-{f}atr" for f in FIBS]
         + ["hi5", "lo5", "hi20", "lo20"])
for name in order:
    for cd in ("up", "dn"):
        for kind in ("reject", "hold"):
            grp = events.get((name, cd, kind), [])
            if len(grp) >= 20:
                report(f"{name} {cd}-cross {kind}", grp)

# pooled groups
pools = {
    "ATR-lvl rejects (all)": [(n, c, "reject") for n in order if "atr" in n or n == "pivot" for c in ("up", "dn")],
    "ATR-lvl holds (all)":   [(n, c, "hold") for n in order if "atr" in n or n == "pivot" for c in ("up", "dn")],
    "Swing rejects (all)":   [(n, c, "reject") for n in ("hi5", "lo5", "hi20", "lo20") for c in ("up", "dn")],
    "Swing holds (all)":     [(n, c, "hold") for n in ("hi5", "lo5", "hi20", "lo20") for c in ("up", "dn")],
}
print("\npooled:")
for label, keys in pools.items():
    grp = [e for k in keys for e in events.get(k, [])]
    if grp:
        report(label, grp)

# directional split of pooled rejects/holds: long-pred vs short-pred (drift check)
print("\npooled by predicted direction (drift check):")
for label, keys in pools.items():
    grp = [e for k in keys for e in events.get(k, [])]
    for sign, tag in ((+1, "long-pred"), (-1, "short-pred")):
        sub = [e for e in grp if e[0] == sign]
        if len(sub) >= 20:
            report(f"{label} {tag}", sub)

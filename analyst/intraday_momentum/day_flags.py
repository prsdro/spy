"""Pre-open day flags for filtering the intraday momentum engine.

All flags are computable before 09:30 ET on the flagged day:
  - saty_comp_1h: Saty PO compression flag on the last COMPLETED ETH 1h bar
    (the 08:00-09:00 ET bar), same indicator as the Bilbo studies.
  - comp_run_1h: length of the current consecutive po_compression run as of
    that bar (0 if not compressed).
  - rr6_60: mean true range of last 6 completed ETH 1h bars / mean of last 60
    ("hourly expansion vs compression" as realized range ratio).
  - nr4 / nr7: prior RTH day's range is the narrowest of last 4 / 7 days.
  - prev_day_ret: prior RTH close-to-close return (context).
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
from indicators import compute_phase_oscillator

DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"

print("loading...")
df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])
df = df.set_index("ts").sort_index()

# ---- ETH hourly bars (all sessions), completed on the hour
h1 = df.resample("1h").agg(
    open=("o", "first"), high=("h", "max"), low=("l", "min"),
    close=("c", "last"), volume=("v", "sum")).dropna(subset=["close"])
h1 = compute_phase_oscillator(h1.rename(columns=str.lower))

# true range on 1h
prev_c = h1["close"].shift(1)
tr = np.maximum(h1["high"], prev_c) - np.minimum(h1["low"], prev_c)
h1["tr"] = tr
h1["rr6_60"] = tr.rolling(6).mean() / tr.rolling(60).mean()

# compression run length
comp = h1["po_compression"].fillna(0).astype(int).to_numpy()
run = np.zeros(len(comp), dtype=int)
for i in range(1, len(comp)):
    run[i] = run[i - 1] + 1 if comp[i] else 0
h1["comp_run"] = run

# ---- RTH days
df["date"] = df.index.date
df["hm"] = df.index.hour * 60 + df.index.minute
rth = df[(df["hm"] >= 570) & (df["hm"] <= 959)]
daily = rth.groupby("date").agg(hi=("h", "max"), lo=("l", "min"), cl=("c", "last"))
daily["rng"] = daily["hi"] - daily["lo"]
daily["nr4"] = daily["rng"] == daily["rng"].rolling(4).min()
daily["nr7"] = daily["rng"] == daily["rng"].rolling(7).min()
daily["prev_day_ret"] = daily["cl"].pct_change()
# flags known at next day's open -> shift
flags = pd.DataFrame(index=daily.index)
flags["nr4_prior"] = daily["nr4"].shift(1)
flags["nr7_prior"] = daily["nr7"].shift(1)
flags["prev_day_ret"] = daily["prev_day_ret"].shift(0)  # yesterday's ret known today
# fix: prev_day_ret as known at today's open = yesterday's close-to-close
flags["prev_day_ret"] = daily["prev_day_ret"]
flags = flags.reset_index().rename(columns={"date": "day"})
flags["day"] = pd.to_datetime(flags["day"])

# map each RTH day -> last completed 1h bar before 09:30 (bar stamped 08:00)
h1r = h1.reset_index().rename(columns={"ts": "bar_ts"})
h1r["bar_end"] = h1r["bar_ts"] + pd.Timedelta(hours=1)
h1r = h1r.sort_values("bar_end")
days = flags["day"]
cutoffs = days + pd.Timedelta(hours=9, minutes=30)
idx = np.searchsorted(h1r["bar_end"].to_numpy(), cutoffs.to_numpy(), side="right") - 1
ok = idx >= 0
flags["saty_comp_1h"] = np.where(ok, h1r["po_compression"].to_numpy()[idx], np.nan)
flags["comp_run_1h"] = np.where(ok, h1r["comp_run"].to_numpy()[idx], np.nan)
flags["rr6_60"] = np.where(ok, h1r["rr6_60"].to_numpy()[idx], np.nan)
flags["phase_zone_1h"] = np.where(ok, h1r["phase_zone"].to_numpy()[idx], None)

# note: prev_day_ret above intentionally equals yesterday's close-to-close
# (daily index row for day D holds ret from D-1 close to D close, which is NOT
# known at D open). Shift so day D carries D-1's value.
flags["prev_day_ret"] = flags["prev_day_ret"].shift(1)

flags.to_csv("es_day_flags.csv", index=False)
print(flags.tail(3).to_string())
print("comp share:", flags["saty_comp_1h"].mean().round(3),
      "| rr6_60 quantiles:", flags["rr6_60"].quantile([.2, .5, .8]).round(2).tolist())

"""Validate the engine on SPY 1-min with the paper's cost assumptions.

Paper (Table 2, Size=100%, Stop=Curr.Band+VWAP, 2007-05..2024-04):
IRR 9.7%, Vol 7.7%, Sharpe 1.24, Hit 43%, ~7,668 trades (~0.9 RT/day).
"""
import glob
import pandas as pd
import numpy as np
from engine import run, summarize

files = sorted(glob.glob("/root/spy/data/massive_spy_1min/csv_by_year/SPY_1min_*.csv"))
files = [f for f in files if 2007 <= int(f[-8:-4]) <= 2024]
dfs = []
for f in files:
    d = pd.read_csv(f, usecols=["time", "open", "high", "low", "close", "volume"])
    dfs.append(d)
df = pd.concat(dfs, ignore_index=True)
df["ts"] = (pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert("America/New_York").dt.tz_localize(None))
df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
df = df[["ts", "o", "h", "l", "c", "v"]].sort_values("ts")

# paper window: May 2007 - Apr 2024
df = df[(df["ts"] >= "2007-04-01") & (df["ts"] <= "2024-04-30")]

# paper costs: $0.0035/share commission + $0.001/share slippage, per side
cost_rt = 2 * (0.0035 + 0.001)
res, _ = run(df, vm=1.0, cost_rt_price_units=cost_rt)
res = res[(res["date"] >= "2007-05-01")]

print(summarize(res, "SPY 2007-05..2024-04 net (paper costs)"))
print(summarize(res, "gross", col="gross_ret_frac"))
yearly = res.groupby("year")["ret_frac"].agg(["sum", "size"])
yearly["sum"] = (yearly["sum"] * 100).round(1)
print(yearly.to_string())
res.to_csv("spy_validation_daily.csv", index=False)

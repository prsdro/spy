"""SPY engine 2022-2026: is the edge alive post-publication (near-zero costs)?"""
import glob
import pandas as pd
from engine import run, summarize

files = sorted(glob.glob("/root/spy/data/massive_spy_1min/csv_by_year/SPY_1min_*.csv"))
files = [f for f in files if int(f[-8:-4]) >= 2021]
dfs = [pd.read_csv(f, usecols=["time", "open", "high", "low", "close", "volume"]) for f in files]
df = pd.concat(dfs, ignore_index=True)
df["ts"] = (pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert("America/New_York").dt.tz_localize(None))
df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
df = df[["ts", "o", "h", "l", "c", "v"]].sort_values("ts")

cost_rt = 2 * (0.0035 + 0.001)
res, _ = run(df, vm=1.0, cost_rt_price_units=cost_rt)
res = res[res["date"] >= "2022-01-01"]

for y in sorted(res["year"].unique()):
    print(summarize(res[res["year"] == y], f"SPY {y} net"))
print(summarize(res[res["date"] >= "2024-05-01"], "SPY 2024-05..2026-04 (post-paper) net"))
res.to_csv("spy_recent_daily.csv", index=False)

"""Train/holdout analysis of the tuning grid + day-filter interactions.

Protocol (fixed before looking at holdout):
  train      = 2008-07 .. 2024-04  (paper window)
  train_rec  = 2022-01 .. 2024-04  (recency emphasis for selection)
  holdout    = 2024-05 .. 2026-01  (post-publication)
Selection: configs with full-train t >= 2.0, ranked by train_rec t; top 5
evaluated on holdout. Filters evaluated on the paper-base spec + top configs.
"""
import numpy as np
import pandas as pd

d = pd.read_parquet("tune_grid_daily.parquet")
d["date"] = pd.to_datetime(d["date"])
flags = pd.read_csv("es_day_flags.csv", parse_dates=["day"])
d = d.merge(flags, left_on="date", right_on="day", how="left")

TRAIN = (d["date"] >= "2008-07-01") & (d["date"] <= "2024-04-30")
TRAIN_REC = (d["date"] >= "2022-01-01") & (d["date"] <= "2024-04-30")
HOLD = d["date"] >= "2024-05-01"

def stats(sub):
    n = len(sub); mu = sub["net_usd"].mean(); sd = sub["net_usd"].std()
    return pd.Series({"n": n, "avg": mu, "t": mu / sd * np.sqrt(n) if sd > 0 else np.nan,
                      "sharpe": mu / sd * np.sqrt(252) if sd > 0 else np.nan,
                      "rts": sub["round_trips"].mean()})

key = ["vm", "lb", "interval", "stop"]
g_train = d[TRAIN].groupby(key).apply(stats, include_groups=False)
g_rec = d[TRAIN_REC].groupby(key).apply(stats, include_groups=False)
g_hold = d[HOLD].groupby(key).apply(stats, include_groups=False)

tab = g_train.join(g_rec, rsuffix="_rec").join(g_hold, rsuffix="_hold")
tab = tab.round({"avg": 1, "t": 2, "sharpe": 2, "rts": 2,
                 "avg_rec": 1, "t_rec": 2, "sharpe_rec": 2, "rts_rec": 2,
                 "avg_hold": 1, "t_hold": 2, "sharpe_hold": 2, "rts_hold": 2})
tab.to_csv("tune_grid_summary.csv")

elig = tab[tab["t"] >= 2.0].sort_values("t_rec", ascending=False)
print(f"eligible (train t>=2): {len(elig)}/96")
cols = ["avg", "t", "avg_rec", "t_rec", "avg_hold", "t_hold", "rts"]
print("=== TOP 10 by train_rec t (holdout shown for top 5 only in report) ===")
print(elig[cols].head(10).to_string())
print()
print("=== paper base (vm1.0 lb14 int30 band_vwap) ===")
print(tab.loc[(1.0, 14, 30, "band_vwap")][cols].to_string())

# ---- knob marginals on train (avoid holdout) ----
print("\n=== knob marginals, train avg $/day (net) ===")
for k in ["vm", "lb", "interval", "stop"]:
    m = d[TRAIN].groupby(k)["net_usd"].mean().round(1)
    r = d[TRAIN_REC].groupby(k)["net_usd"].mean().round(1)
    print(k, "train:", m.to_dict(), "| train_rec:", r.to_dict())

# ---- day filters on selected configs ----
def filter_table(sub_all, label):
    out = {}
    sub = sub_all
    out["all"] = stats(sub)
    out["saty_comp=1"] = stats(sub[sub["saty_comp_1h"] == 1])
    out["saty_comp=0"] = stats(sub[sub["saty_comp_1h"] == 0])
    out["comp_run>=6"] = stats(sub[sub["comp_run_1h"] >= 6])
    out["rr6_60<0.79"] = stats(sub[sub["rr6_60"] < 0.79])
    out["rr6_60>1.21"] = stats(sub[sub["rr6_60"] > 1.21])
    out["nr4_prior"] = stats(sub[sub["nr4_prior"] == True])
    out["nr7_prior"] = stats(sub[sub["nr7_prior"] == True])
    t = pd.DataFrame(out).T.round({"n": 0, "avg": 1, "t": 2, "sharpe": 2, "rts": 2})
    print(f"--- {label} ---"); print(t.to_string())
    return t

top5 = list(elig.head(5).index)
sel = [(1.0, 14, 30, "band_vwap")] + top5
print("\n=== FILTERS (train, then holdout) ===")
store = {}
for cfg in sel:
    m = (d["vm"] == cfg[0]) & (d["lb"] == cfg[1]) & (d["interval"] == cfg[2]) & (d["stop"] == cfg[3])
    print(f"\nCONFIG vm={cfg[0]} lb={cfg[1]} int={cfg[2]} stop={cfg[3]}")
    tr = filter_table(d[m & TRAIN], "train 2008-2024/04")
    ho = filter_table(d[m & HOLD], "HOLDOUT 2024-05+")
    store[str(cfg)] = {"train": tr, "hold": ho}

with pd.ExcelWriter("tune_filters.xlsx") as w:  # noqa - convenience dump
    for k, v in store.items():
        v["train"].to_excel(w, sheet_name=(k[:24] + "_tr").replace("'", ""))
        v["hold"].to_excel(w, sheet_name=(k[:24] + "_ho").replace("'", ""))

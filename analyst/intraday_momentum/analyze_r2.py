"""Round-2 analysis, TRAIN ONLY (2008-07 .. 2024-04, recency 2022-01 .. 2024-04).

Ranks engine variants, then vol-gate and rr-filter stacks on the best variants.
Holdout is not touched; at the end we pre-declare <=3 stacks for one holdout read.
"""
import numpy as np
import pandas as pd

d = pd.read_parquet("tune_r2_daily.parquet")
d["date"] = pd.to_datetime(d["date"])
f = pd.read_csv("es_day_flags.csv", parse_dates=["day"])
d = d.merge(f, left_on="date", right_on="day", how="left")

TR = (d["date"] >= "2008-07-01") & (d["date"] <= "2024-04-30")
REC = (d["date"] >= "2022-01-01") & (d["date"] <= "2024-04-30")

def stats(s):
    n = len(s); mu = s.mean(); sd = s.std()
    return pd.Series({"n": n, "avg": mu, "t": mu / sd * np.sqrt(n) if sd > 0 else np.nan,
                      "sharpe": mu / sd * np.sqrt(252) if sd > 0 else np.nan})

key = ["vm", "interval", "stop", "window", "confirm", "max_rts"]
tr = d[TR].groupby(key)["net_usd"].apply(lambda s: stats(s)).unstack()
rc = d[REC].groupby(key)["net_usd"].apply(lambda s: stats(s)).unstack()
tab = tr.join(rc, rsuffix="_rec").round(2)
tab.to_csv("tune_r2_summary.csv")

elig = tab[tab["t"] >= 2.0].sort_values("t_rec", ascending=False)
print(f"eligible train t>=2: {len(elig)}/160")
print(elig[["avg", "t", "avg_rec", "t_rec"]].head(12).to_string())

print("\n=== marginals (train / train_rec avg $/day) ===")
for k in ["window", "confirm", "max_rts"]:
    print(k, d[TR].groupby(k)["net_usd"].mean().round(1).to_dict(),
          "|", d[REC].groupby(k)["net_usd"].mean().round(1).to_dict())

# ---- vol gates + rr stacks on top-3 engine variants (train only) ----
GATES = {
    "all": lambda x: pd.Series(True, index=x.index),
    "vix>=20": lambda x: x["vix_open"] >= 20,
    "vix>=25": lambda x: x["vix_open"] >= 25,
    "vix<15": lambda x: x["vix_open"] < 15,
    "rvol_hi(>1.4%)": lambda x: x["rvol14"] >= 0.014,
    "rvol_lo(<0.92%)": lambda x: x["rvol14"] < 0.0092,
    "rr<=1.0": lambda x: x["rr6_60"] <= 1.0,
    "no_expansion(rr<=1.21)": lambda x: x["rr6_60"] <= 1.21,
    "vix>=20 & rr<=1.0": lambda x: (x["vix_open"] >= 20) & (x["rr6_60"] <= 1.0),
    "rvol_hi & rr<=1.0": lambda x: (x["rvol14"] >= 0.014) & (x["rr6_60"] <= 1.0),
    "vix>=20 & no_exp": lambda x: (x["vix_open"] >= 20) & (x["rr6_60"] <= 1.21),
}
top3 = list(elig.head(3).index)
for cfg in top3:
    m = np.ones(len(d), dtype=bool)
    for kk, vv in zip(key, cfg):
        m &= (d[kk] == vv).to_numpy()
    sub_tr = d[m & TR.to_numpy()]; sub_rc = d[m & REC.to_numpy()]
    print(f"\nCONFIG {dict(zip(key, cfg))}")
    out = {}
    for gname, gfn in GATES.items():
        a = sub_tr[gfn(sub_tr).fillna(False)]
        b = sub_rc[gfn(sub_rc).fillna(False)]
        out[gname] = pd.concat([stats(a["net_usd"]).add_suffix("_tr"),
                                stats(b["net_usd"]).add_suffix("_rec")])
    print(pd.DataFrame(out).T.round(2).to_string())

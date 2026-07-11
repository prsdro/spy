"""NQ run: paper base spec (clean OOS — new instrument, untuned) + small
variant set under train/holdout protocol. Also builds NQ day flags (rr6_60,
rvol14) for gate checks.
"""
import numpy as np
import pandas as pd

DATA = "/srv/ftp/ossicones/futures-data/NQ_full_1min_continuous_ratio_adjusted.txt"
PV = 20.0
COST_RT_PTS = 0.5 + 4.30 / PV   # 0.715 NQ points per round trip

print("loading NQ...")
df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])
df["date"] = df["ts"].dt.date
df["hm"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
rth = df[(df["hm"] >= 570) & (df["hm"] <= 959)].copy()
opens = rth[rth["hm"] == 570].set_index("date")["o"]
rth = rth[rth["date"].isin(opens.index)]
closes = rth.groupby("date")["c"].last()
last_hm = rth.groupby("date")["hm"].max()
days = sorted(opens.index)
prev_close = {days[i]: closes[days[i - 1]] for i in range(1, len(days))}

rth["move"] = (rth["c"] / rth["date"].map(opens) - 1.0).abs()
mv = rth.pivot_table(index="date", columns="hm", values="move")
sigma14 = mv.shift(1).rolling(14, min_periods=14).mean()
cpx = rth.pivot_table(index="date", columns="hm", values="c")
opx = rth.pivot_table(index="date", columns="hm", values="o")
tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
rth["pv"] = tp * rth["v"]
g = rth.groupby("date")
rth["vwap"] = g["pv"].cumsum() / g["v"].cumsum().replace(0, np.nan)
vwp = rth.pivot_table(index="date", columns="hm", values="vwap")

all_hm = np.array(sorted(cpx.columns))
C = cpx.reindex(columns=all_hm).to_numpy()
O = opx.reindex(columns=all_hm).to_numpy()
V = vwp.reindex(columns=all_hm).to_numpy()
S14 = sigma14.reindex(columns=all_hm).to_numpy()
day_list = list(cpx.index)
hm_pos = {h: i for i, h in enumerate(all_hm)}
lhm_arr = np.array([last_hm[d] for d in day_list])
open_arr = np.array([opens[d] for d in day_list])
pc_arr = np.array([prev_close.get(d, np.nan) for d in day_list])

def run_config(vm, interval, stop_mode):
    checks = list(range(600, 960, interval))
    out = []
    for di in range(len(day_list)):
        if di < 15 or np.isnan(pc_arr[di]):
            continue
        lhm = lhm_arr[di]
        o0, pc = open_arr[di], pc_arr[di]
        hi_a, lo_a = max(o0, pc), min(o0, pc)
        pos = 0; ent = 0.0; cash = 0.0; rts = 0
        for chk in checks:
            if chk > lhm:
                break
            j = hm_pos.get(chk - 1); jf = hm_pos.get(chk)
            if j is None or jf is None:
                continue
            px = C[di, j]; sg = S14[di, j]; vw = V[di, j]; fill = O[di, jf]
            if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
                continue
            ub = hi_a * (1 + vm * sg); lbnd = lo_a * (1 - vm * sg)
            if pos == 1:
                trail = (max(ub, vw) if not np.isnan(vw) else ub) if stop_mode == "band_vwap" \
                        else (vw if not np.isnan(vw) else ub)
                if px < trail:
                    cash += (fill - ent) - COST_RT_PTS; rts += 1; pos = 0
            elif pos == -1:
                trail = (min(lbnd, vw) if not np.isnan(vw) else lbnd) if stop_mode == "band_vwap" \
                        else (vw if not np.isnan(vw) else lbnd)
                if px > trail:
                    cash += (ent - fill) - COST_RT_PTS; rts += 1; pos = 0
            if pos == 0:
                if px > ub:
                    pos = 1; ent = fill
                elif px < lbnd:
                    pos = -1; ent = fill
        if pos != 0:
            j_end = hm_pos[lhm]
            cash += pos * (C[di, j_end] - ent) - COST_RT_PTS; rts += 1
        out.append((day_list[di], cash, rts))
    r = pd.DataFrame(out, columns=["date", "net_pts", "round_trips"])
    r["net_usd"] = r["net_pts"] * PV
    return r

# ---- NQ day flags (rr6_60 on ETH 1h true range, rvol14 daily) ----
d1 = df.set_index("ts")
h1 = d1.resample("1h").agg(high=("h", "max"), low=("l", "min"), close=("c", "last")).dropna()
pc1 = h1["close"].shift(1)
tr1 = np.maximum(h1["high"], pc1) - np.minimum(h1["low"], pc1)
rr = (tr1.rolling(6).mean() / tr1.rolling(60).mean()).rename("rr6_60").reset_index()
rr["bar_end"] = rr["ts"] + pd.Timedelta(hours=1)
daily = rth.groupby("date").agg(hi=("h", "max"), lo=("l", "min"), cl=("c", "last"))
pcd = daily["cl"].shift(1)
trd = (np.maximum(daily["hi"], pcd) - np.minimum(daily["lo"], pcd)) / daily["cl"]
rvol = trd.rolling(14).mean().shift(1).rename("rvol14").reset_index()
rvol["day"] = pd.to_datetime(rvol["date"])
day_dt = pd.to_datetime(pd.Series(day_list))
cut = day_dt + pd.Timedelta(hours=9, minutes=30)
idx = np.searchsorted(rr["bar_end"].to_numpy(), cut.to_numpy(), side="right") - 1
flags = pd.DataFrame({"day": day_dt,
                      "rr6_60": np.where(idx >= 0, rr["rr6_60"].to_numpy()[idx], np.nan)})
flags = flags.merge(rvol[["day", "rvol14"]], on="day", how="left")
flags.to_csv("nq_day_flags.csv", index=False)

def st(s, lab):
    n = len(s); mu = s.mean(); sd = s.std()
    print(f"{lab:48s} n={n:5d} avg=${mu:7.1f} t={mu/sd*np.sqrt(n):5.2f} "
          f"shp={mu/sd*np.sqrt(252):5.2f}")

results = {}
for vm in [1.0, 1.25]:
    for interval in [15, 30]:
        for stop in ["band_vwap", "vwap"]:
            r = run_config(vm, interval, stop)
            r["date"] = pd.to_datetime(r["date"])
            r = r.merge(flags, left_on="date", right_on="day", how="left")
            results[(vm, interval, stop)] = r
            r.to_csv(f"nq_vm{vm}_i{interval}_{stop}_daily.csv", index=False)

TRW = lambda r: (r["date"] >= "2008-07-01") & (r["date"] <= "2024-04-30")
RECW = lambda r: (r["date"] >= "2022-01-01") & (r["date"] <= "2024-04-30")
HOW = lambda r: r["date"] >= "2024-05-01"

print("\n=== NQ paper base spec (vm1.0 i30 band_vwap) — clean OOS ===")
r = results[(1.0, 30, "band_vwap")]
st(r[TRW(r)]["net_usd"], "train 2008-2024/04")
st(r[RECW(r)]["net_usd"], "train_rec 2022-2024/04")
st(r[HOW(r)]["net_usd"], "HOLDOUT 2024-05+")
for y in [2024, 2025, 2026]:
    sub = r[HOW(r) & (r["date"].dt.year == y)]
    if len(sub):
        st(sub["net_usd"], f"  holdout {y}")

print("\n=== all 8 configs, TRAIN + REC only (no holdout) ===")
for k, r in results.items():
    st(r[TRW(r)]["net_usd"], f"{k} train")
    st(r[RECW(r)]["net_usd"], f"{k} rec")

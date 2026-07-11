"""BeatTheMarket (NQ base spec + skip-expansion filter) on 2026 forward data.

Data: analyst/forward_2026/NQ{H,M,U}6_1min.csv (Massive futures API, ET,
2026-01-05 -> 2026-07-10). Front month by daily RTH volume; per-contract
indicators with warmup buffer. Engine: vm1.0 / lb14 / 30-min checkpoints /
band+VWAP trail, flat at close; costs 1 tick/side + $4.30 RT (0.715 NQ pts).
Output: btm_forward_daily.csv (date, net_usd, round_trips, rr6_60, traded_ok).
"""
import numpy as np
import pandas as pd
import os

DIR = "/root/spy/analyst/forward_2026"
PV = 20.0
COST = 0.5 + 4.30 / PV
FWD_START = pd.Timestamp("2026-01-26").date()

def load(name):
    df = pd.read_csv(os.path.join(DIR, f"{name}_1min.csv"), header=None,
                     names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])
    return df.sort_values("ts").drop_duplicates(subset="ts", keep="last")

raw = {t: load(t) for t in ["NQH6", "NQM6", "NQU6"]}
volmap = {}
for t, d in raw.items():
    r = d[(d["ts"].dt.hour * 60 + d["ts"].dt.minute >= 570) &
          (d["ts"].dt.hour * 60 + d["ts"].dt.minute <= 959)]
    volmap[t] = r.groupby(r["ts"].dt.date)["v"].sum()
vol = pd.DataFrame(volmap).fillna(0)
front = vol.idxmax(axis=1)

rows = []
for t in raw:
    f_days = sorted(front[front == t].index)
    if not f_days:
        continue
    keep_from = pd.Timestamp(f_days[0]) - pd.Timedelta(days=30)
    df = raw[t][raw[t]["ts"] >= keep_from].copy()
    df["date"] = df["ts"].dt.date
    df["hm"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute

    # rr6_60 from ETH hourly true range, known at 09:30
    h1 = df.set_index("ts").resample("1h").agg(
        high=("h", "max"), low=("l", "min"), close=("c", "last")).dropna()
    pc1 = h1["close"].shift(1)
    tr1 = np.maximum(h1["high"], pc1) - np.minimum(h1["low"], pc1)
    rr = (tr1.rolling(6).mean() / tr1.rolling(60).mean()).reset_index()
    rr.columns = ["bar_ts", "rr6_60"]
    rr["bar_end"] = rr["bar_ts"] + pd.Timedelta(hours=1)

    rth = df[(df["hm"] >= 570) & (df["hm"] <= 959)]
    opens = rth[rth["hm"] == 570].set_index("date")["o"]
    rth = rth[rth["date"].isin(opens.index)]
    closes = rth.groupby("date")["c"].last()
    last_hm = rth.groupby("date")["hm"].max()
    days = sorted(opens.index)
    prev_close = {days[i]: closes[days[i - 1]] for i in range(1, len(days))}

    rth = rth.copy()
    rth["move"] = (rth["c"] / rth["date"].map(opens) - 1.0).abs()
    mv = rth.pivot_table(index="date", columns="hm", values="move")
    sigma = mv.shift(1).rolling(14, min_periods=14).mean()
    cpx = rth.pivot_table(index="date", columns="hm", values="c")
    opx = rth.pivot_table(index="date", columns="hm", values="o")
    tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
    rth["pv"] = tp * rth["v"]
    g = rth.groupby("date")
    rth["vwap"] = g["pv"].cumsum() / g["v"].cumsum().replace(0, np.nan)
    vwp = rth.pivot_table(index="date", columns="hm", values="vwap")

    f_set = set(f_days)
    for d in days:
        if d not in f_set or d < FWD_START or d not in prev_close:
            continue
        sig_row = sigma.loc[d] if d in sigma.index else None
        if sig_row is None or sig_row.isna().all():
            continue
        O = opens[d]; PC = prev_close[d]
        hi_a, lo_a = max(O, PC), min(O, PC)
        crow = cpx.loc[d]; vrow = vwp.loc[d]; orow = opx.loc[d]
        lhm = last_hm[d]
        cutoff = pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=30)
        rrv = rr[rr["bar_end"] <= cutoff]["rr6_60"]
        rr_flag = rrv.iloc[-1] if len(rrv) else np.nan
        pos = 0; ent = 0.0; cash = 0.0; rts = 0
        for chk in range(600, 960, 30):
            if chk > lhm:
                break
            px = crow.get(chk - 1, np.nan)
            sg = sig_row.get(chk - 1, np.nan)
            vw = vrow.get(chk - 1, np.nan)
            fill = orow.get(chk, np.nan)
            if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
                continue
            ub = hi_a * (1 + sg); lb = lo_a * (1 - sg)
            if pos == 1:
                trail = max(ub, vw) if not np.isnan(vw) else ub
                if px < trail:
                    cash += (fill - ent) - COST; rts += 1; pos = 0
            elif pos == -1:
                trail = min(lb, vw) if not np.isnan(vw) else lb
                if px > trail:
                    cash += (ent - fill) - COST; rts += 1; pos = 0
            if pos == 0:
                if px > ub:
                    pos = 1; ent = fill
                elif px < lb:
                    pos = -1; ent = fill
        if pos != 0:
            cash += pos * (crow[lhm] - ent) - COST; rts += 1
        rows.append({"date": d, "contract": t, "net_usd": cash * PV,
                     "round_trips": rts, "rr6_60": rr_flag})

out = pd.DataFrame(rows).sort_values("date")
out.to_csv("btm_forward_daily.csv", index=False)
out["date"] = pd.to_datetime(out["date"])
flt = out[out["rr6_60"] <= 1.21]
print(f"days: {len(out)}, filtered-in: {len(flt)}")
print(f"unfiltered: total ${out['net_usd'].sum():,.0f}, avg ${out['net_usd'].mean():.1f}/day")
print(f"filtered:   total ${flt['net_usd'].sum():,.0f}, avg ${flt['net_usd'].mean():.1f}/day")
print(out.groupby(out["date"].dt.to_period("M"))["net_usd"].sum().round(0).to_string())

"""Execution-mechanics variant on ES: intrabar stop orders vs semi-hourly checks.

entry_mode:
  checkpoint — signal at check-minute close, fill at next bar open (paper)
  intrabar   — resting stop at the band level; fills the minute price crosses it
               (fill = max(band, bar open) +/- 1 tick). Re-arms only after a
               minute closes back inside the band (no instant re-entry loops).
exit_mode:
  checkpoint — trail evaluated at semi-hourly checks (paper)
  intrabar   — resting stop at the trailing level, fills the minute it's hit.
Costs: 1 tick/side slippage + $4.30 RT. VM=1.0, LB=14, checks every 30 min.
Train/rec reported for all 4 combos; holdout read only for one pre-declared
variant (top train_rec) + the paper base already known.
"""
import numpy as np
import pandas as pd

DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
PV = 50.0
TICK = 0.25
COMM_RT_PTS = 4.30 / PV

print("loading ES...")
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

piv = {}
for col in ["o", "h", "l", "c"]:
    piv[col] = rth.pivot_table(index="date", columns="hm", values=col)
tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
rth["pv"] = tp * rth["v"]
g = rth.groupby("date")
rth["vwap"] = g["pv"].cumsum() / g["v"].cumsum().replace(0, np.nan)
piv["vwap"] = rth.pivot_table(index="date", columns="hm", values="vwap")

all_hm = np.array(sorted(piv["c"].columns))
A = {k: v.reindex(columns=all_hm).to_numpy() for k, v in piv.items()}
S = sigma14.reindex(columns=all_hm).to_numpy()
day_list = list(piv["c"].index)
hm_pos = {h: i for i, h in enumerate(all_hm)}
lhm_arr = np.array([last_hm[d] for d in day_list])
open_arr = np.array([opens[d] for d in day_list])
pc_arr = np.array([prev_close.get(d, np.nan) for d in day_list])
CHECKS = set(range(600, 960, 30))

def run(entry_mode, exit_mode, vm=1.0):
    out = []
    for di in range(len(day_list)):
        if di < 15 or np.isnan(pc_arr[di]):
            continue
        lhm = lhm_arr[di]
        o0, pc = open_arr[di], pc_arr[di]
        hi_a, lo_a = max(o0, pc), min(o0, pc)
        pos = 0; ent = 0.0; cash = 0.0; rts = 0
        armed_long = True; armed_short = True
        j0 = hm_pos[600]  # trading starts 10:00 as in paper
        j_end = hm_pos[lhm]
        for j in range(j0, j_end + 1):
            hm = all_hm[j]
            if hm > lhm:
                break
            o, h, l, c = A["o"][di, j], A["h"][di, j], A["l"][di, j], A["c"][di, j]
            vw = A["vwap"][di, j]; sg = S[di, j]
            if np.isnan(c) or np.isnan(sg):
                continue
            ub = hi_a * (1 + vm * sg); lb = lo_a * (1 - vm * sg)
            trail_l = max(ub, vw) if not np.isnan(vw) else ub
            trail_s = min(lb, vw) if not np.isnan(vw) else lb
            # ---- exits first
            if pos == 1:
                if exit_mode == "intrabar":
                    if l <= trail_l:
                        fill = min(trail_l, o) - TICK
                        cash += (fill - ent) - COMM_RT_PTS; rts += 1; pos = 0
                        armed_long = False
                elif hm in CHECKS:
                    px_prev = A["c"][di, j - 1] if j > j0 else c
                    if px_prev < trail_l:
                        cash += (o - TICK - ent) - COMM_RT_PTS; rts += 1; pos = 0
                        armed_long = False
            elif pos == -1:
                if exit_mode == "intrabar":
                    if h >= trail_s:
                        fill = max(trail_s, o) + TICK
                        cash += (ent - fill) - COMM_RT_PTS; rts += 1; pos = 0
                        armed_short = False
                elif hm in CHECKS:
                    px_prev = A["c"][di, j - 1] if j > j0 else c
                    if px_prev > trail_s:
                        cash += (ent - (o + TICK)) - COMM_RT_PTS; rts += 1; pos = 0
                        armed_short = False
            # ---- re-arm when price closes back inside the noise area
            if c <= ub:
                armed_long = True
            if c >= lb:
                armed_short = True
            # ---- entries
            if pos == 0:
                if entry_mode == "intrabar":
                    if armed_long and h >= ub:
                        pos = 1; ent = max(ub, o) + TICK
                    elif armed_short and l <= lb:
                        pos = -1; ent = min(lb, o) - TICK
                elif hm in CHECKS:
                    px_prev = A["c"][di, j - 1] if j > j0 else c
                    if px_prev > ub:
                        pos = 1; ent = o + TICK
                    elif px_prev < lb:
                        pos = -1; ent = o - TICK
        if pos != 0:
            cash += pos * (A["c"][di, j_end] - ent) - COMM_RT_PTS; rts += 1
        out.append((day_list[di], cash, rts))
    r = pd.DataFrame(out, columns=["date", "net_pts", "round_trips"])
    r["date"] = pd.to_datetime(r["date"]); r["net_usd"] = r["net_pts"] * PV
    return r

def st(r, mask, lab):
    s = r[mask]["net_usd"]
    n = len(s); mu = s.mean(); sd = s.std()
    print(f"{lab:44s} n={n:5d} avg=${mu:7.1f} t={mu/sd*np.sqrt(n):5.2f} "
          f"shp={mu/sd*np.sqrt(252):5.2f} rts={r[mask]['round_trips'].mean():.2f}")

res = {}
for em in ["checkpoint", "intrabar"]:
    for xm in ["checkpoint", "intrabar"]:
        r = run(em, xm)
        res[(em, xm)] = r
        r.to_csv(f"es_exec_{em}_{xm}_daily.csv", index=False)
        TR = (r["date"] >= "2008-07-01") & (r["date"] <= "2024-04-30")
        RC = (r["date"] >= "2022-01-01") & (r["date"] <= "2024-04-30")
        print(f"--- entry={em} exit={xm} ---")
        st(r, TR, "train"); st(r, RC, "train_rec")
print("(holdout deliberately not printed; single read after variant selection)")

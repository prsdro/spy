"""Parameter grid for the intraday momentum engine on ES.

Knobs: check interval (15/30/60 min), volatility multiplier (band width),
sigma lookback (14/90), trailing stop mode (band+vwap / band / vwap / opp_band).
Precomputes shared pivots once; runs the state machine per config.
Output: tune_grid_daily.parquet (one row per config x day).
"""
import numpy as np
import pandas as pd

DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
COST_RT_PTS = 0.5 + 4.30 / 50.0

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

print("pivots...")
rth["move"] = (rth["c"] / rth["date"].map(opens) - 1.0).abs()
mv = rth.pivot_table(index="date", columns="hm", values="move")
sigmas = {lb: mv.shift(1).rolling(lb, min_periods=lb).mean() for lb in (14, 90)}
cpx = rth.pivot_table(index="date", columns="hm", values="c")
opx = rth.pivot_table(index="date", columns="hm", values="o")
tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
rth["pv"] = tp * rth["v"]
g = rth.groupby("date")
rth["vwap"] = g["pv"].cumsum() / g["v"].cumsum().replace(0, np.nan)
vwp = rth.pivot_table(index="date", columns="hm", values="vwap")

# to numpy for speed
all_hm = np.array(sorted(cpx.columns))
C = cpx.reindex(columns=all_hm).to_numpy()
O = opx.reindex(columns=all_hm).to_numpy()
V = vwp.reindex(columns=all_hm).to_numpy()
S = {lb: s.reindex(columns=all_hm).to_numpy() for lb, s in sigmas.items()}
day_list = list(cpx.index)
day_pos = {d: i for i, d in enumerate(day_list)}
hm_pos = {h: i for i, h in enumerate(all_hm)}
lhm_arr = np.array([last_hm[d] for d in day_list])
open_arr = np.array([opens[d] for d in day_list])
pc_arr = np.array([prev_close.get(d, np.nan) for d in day_list])

def run_config(vm, lb, interval, stop_mode, min_day_idx):
    Sg = S[lb]
    checks = list(range(600, 960, interval))
    out_dates, out_net, out_rts = [], [], []
    for di in range(len(day_list)):
        if di < min_day_idx or np.isnan(pc_arr[di]):
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
            px = C[di, j]; sg = Sg[di, j]; vw = V[di, j]; fill = O[di, jf]
            if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
                continue
            ub = hi_a * (1 + vm * sg)
            lbnd = lo_a * (1 - vm * sg)
            if pos == 1:
                if stop_mode == "band_vwap":
                    trail = max(ub, vw) if not np.isnan(vw) else ub
                elif stop_mode == "band":
                    trail = ub
                elif stop_mode == "vwap":
                    trail = vw if not np.isnan(vw) else ub
                else:  # opp_band
                    trail = lbnd
                if px < trail:
                    cash += (fill - ent); cash -= COST_RT_PTS; rts += 1; pos = 0
            elif pos == -1:
                if stop_mode == "band_vwap":
                    trail = min(lbnd, vw) if not np.isnan(vw) else lbnd
                elif stop_mode == "band":
                    trail = lbnd
                elif stop_mode == "vwap":
                    trail = vw if not np.isnan(vw) else lbnd
                else:
                    trail = ub
                if px > trail:
                    cash += (ent - fill); cash -= COST_RT_PTS; rts += 1; pos = 0
            if pos == 0:
                if px > ub:
                    pos = 1; ent = fill
                elif px < lbnd:
                    pos = -1; ent = fill
        if pos != 0:
            j_end = hm_pos[lhm]
            cash += pos * (C[di, j_end] - ent); cash -= COST_RT_PTS; rts += 1
        out_dates.append(day_list[di]); out_net.append(cash); out_rts.append(rts)
    return pd.DataFrame({"date": out_dates, "net_pts": out_net, "round_trips": out_rts})

rows = []
min_idx = 91  # enough history for LB=90
total = 0
for vm in [0.75, 1.0, 1.25, 1.5]:
    for lb in [14, 90]:
        for interval in [15, 30, 60]:
            for stop in ["band_vwap", "band", "vwap", "opp_band"]:
                r = run_config(vm, lb, interval, stop, min_idx)
                r["vm"] = vm; r["lb"] = lb; r["interval"] = interval; r["stop"] = stop
                rows.append(r)
                total += 1
                print(f"{total}/96 vm={vm} lb={lb} int={interval} stop={stop} "
                      f"avg=${r['net_pts'].mean()*50:.1f}/d rts={r['round_trips'].mean():.2f}")
out = pd.concat(rows, ignore_index=True)
out["net_usd"] = out["net_pts"] * 50
out.to_parquet("tune_grid_daily.parquet", index=False)
print("saved", len(out))

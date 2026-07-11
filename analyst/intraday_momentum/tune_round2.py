"""Tuning round 2 — theory-motivated variants, evaluated on TRAIN only.

In-engine dims (all supported by the paper's own findings):
  entry_window: all / am (10:00-11:30) / am_ext (10:00-13:00) /
                skip_lunch (no new entries 12:00-13:59) / pm (13:00-15:30)
  confirm: 1 or 2 consecutive out-of-band checks required to enter
  max_rts: unlimited or stop new entries after 2 completed round trips
Base configs: vm {1.0,1.25} x lb 14 x interval {15,30} x stop {band_vwap,vwap}.

Output: tune_r2_daily.parquet. Holdout is NOT examined here.
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

WINDOWS = {
    "all": lambda hm: 600 <= hm <= 930,
    "am": lambda hm: 600 <= hm <= 690,
    "am_ext": lambda hm: 600 <= hm <= 780,
    "skip_lunch": lambda hm: (600 <= hm < 720) or (840 <= hm <= 930),
    "pm": lambda hm: 780 <= hm <= 930,
}

def run_config(vm, interval, stop_mode, window, confirm, max_rts):
    can_enter = WINDOWS[window]
    checks = list(range(600, 960, interval))
    out = []
    for di in range(len(day_list)):
        if di < 15 or np.isnan(pc_arr[di]):
            continue
        lhm = lhm_arr[di]
        o0, pc = open_arr[di], pc_arr[di]
        hi_a, lo_a = max(o0, pc), min(o0, pc)
        pos = 0; ent = 0.0; cash = 0.0; rts = 0
        sig_run = 0; sig_side = 0
        for chk in checks:
            if chk > lhm:
                break
            j = hm_pos.get(chk - 1); jf = hm_pos.get(chk)
            if j is None or jf is None:
                continue
            px = C[di, j]; sg = S14[di, j]; vw = V[di, j]; fill = O[di, jf]
            if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
                continue
            ub = hi_a * (1 + vm * sg)
            lbnd = lo_a * (1 - vm * sg)
            # exits always active
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
            # signal tracking for confirmation
            side = 1 if px > ub else (-1 if px < lbnd else 0)
            if side != 0 and side == sig_side:
                sig_run += 1
            else:
                sig_side = side; sig_run = 1 if side != 0 else 0
            if pos == 0 and side != 0 and sig_run >= confirm and rts < max_rts \
                    and can_enter(chk):
                pos = side; ent = fill
        if pos != 0:
            j_end = hm_pos[lhm]
            cash += pos * (C[di, j_end] - ent) - COST_RT_PTS; rts += 1
        out.append((day_list[di], cash, rts))
    r = pd.DataFrame(out, columns=["date", "net_pts", "round_trips"])
    return r

rows = []
n = 0
for vm in [1.0, 1.25]:
    for interval in [15, 30]:
        for stop in ["band_vwap", "vwap"]:
            for window in WINDOWS:
                for confirm in [1, 2]:
                    for max_rts in [99, 2]:
                        r = run_config(vm, interval, stop, window, confirm, max_rts)
                        for k, v in [("vm", vm), ("interval", interval), ("stop", stop),
                                     ("window", window), ("confirm", confirm),
                                     ("max_rts", max_rts)]:
                            r[k] = v
                        rows.append(r); n += 1
                        if n % 20 == 0:
                            print(f"{n}/160")
out = pd.concat(rows, ignore_index=True)
out["net_usd"] = out["net_pts"] * 50
out.to_parquet("tune_r2_daily.parquet", index=False)
print("saved", len(out))

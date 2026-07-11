"""Replicate Zarattini/Aziz/Barbon (SSRN 4824172) intraday momentum on ES futures.

Strategy (paper base rules, VWAP + current-band trailing stop variant):
  - Noise area per minute-of-day: sigma_m = mean over prior 14 sessions of |C_m/O_day - 1|
  - UB_m = max(Open, PrevClose) * (1 + VM * sigma_m); LB_m = min(Open, PrevClose) * (1 - VM * sigma_m)
  - Decisions only at semi-hourly checkpoints 10:00 ... 15:30 (signal on close of prior
    minute, fill at open of checkpoint bar, matching the paper's execution study).
  - Flat -> long if px > UB, flat -> short if px < LB.
  - Long trailing stop = max(UB, VWAP); short = min(LB, VWAP). Cross -> exit;
    cross of opposite band -> flip.
  - All positions closed at session close (last RTH bar close).

Output: per-day net PnL (points and $ for 1 ES contract), trade count, and
minute-level intraday equity path (points) for drawdown Monte Carlo.
"""
import numpy as np
import pandas as pd
import json, os

DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
VM = 1.0
LOOKBACK = 14
POINT_VALUE = 50.0          # $ per ES point
COMMISSION_RT = 4.30        # $ round-trip per contract (all-in exchange+clearing+broker)
SLIP_TICKS_PER_SIDE = 1     # 1 tick = 0.25 pt slippage each side
SLIP_RT_PTS = SLIP_TICKS_PER_SIDE * 0.25 * 2
COST_RT_PTS = SLIP_RT_PTS + COMMISSION_RT / POINT_VALUE  # points per round trip

print("loading...")
df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])
df["date"] = df["ts"].dt.date
df["hm"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute

# RTH: 09:30 (570) .. 15:59 (959)
rth = df[(df["hm"] >= 570) & (df["hm"] <= 959)].copy()

# require a true 09:30 open bar
opens = rth[rth["hm"] == 570].set_index("date")["o"]
valid_days = opens.index
rth = rth[rth["date"].isin(valid_days)]

# prev session close = last RTH bar close of previous valid day
closes = rth.groupby("date")["c"].last()
last_hm = rth.groupby("date")["hm"].max()

days = sorted(valid_days)
day_idx = {d: i for i, d in enumerate(days)}
prev_close = {days[i]: closes[days[i - 1]] for i in range(1, len(days))}

# pivot: |C_m / O_day - 1| per (day, minute)
rth["move"] = (rth["c"] / rth["date"].map(opens) - 1.0).abs()
mv = rth.pivot_table(index="date", columns="hm", values="move")
sigma = mv.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).mean()

# close pivot + vwap pivot
cpx = rth.pivot_table(index="date", columns="hm", values="c")
tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
rth["pv"] = tp * rth["v"]
g = rth.groupby("date")
rth["cum_pv"] = g["pv"].cumsum()
rth["cum_v"] = g["v"].cumsum()
rth["vwap"] = rth["cum_pv"] / rth["cum_v"].replace(0, np.nan)
vwp = rth.pivot_table(index="date", columns="hm", values="vwap")
opx = rth.pivot_table(index="date", columns="hm", values="o")

CHECK_HM = [600 + 30 * k for k in range(12)]  # 10:00 .. 15:30

records = []
paths = {}   # date -> (minutes array, cum pnl points array marked at close)

for d in days:
    i = day_idx[d]
    if i < LOOKBACK + 1 or d not in prev_close:
        continue
    sig_row = sigma.loc[d]
    if sig_row.isna().all():
        continue
    O = opens[d]; PC = prev_close[d]
    anchor_hi = max(O, PC); anchor_lo = min(O, PC)
    crow = cpx.loc[d]; vrow = vwp.loc[d]; orow = opx.loc[d]
    lhm = last_hm[d]
    # skip half days entirely? keep them but checkpoints beyond close just don't exist
    pos = 0; entry = np.nan; rts = 0
    fills = []  # (hm, price, delta_pos) for path building
    for chk in CHECK_HM:
        s_hm = chk - 1
        if s_hm > lhm or chk > lhm:
            break
        px = crow.get(s_hm, np.nan)
        sg = sig_row.get(s_hm, np.nan)
        vw = vrow.get(s_hm, np.nan)
        fill = orow.get(chk, np.nan)
        if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
            continue
        ub = anchor_hi * (1 + VM * sg)
        lb = anchor_lo * (1 - VM * sg)
        if pos == 1:
            trail = max(ub, vw) if not np.isnan(vw) else ub
            if px < trail:
                fills.append((chk, fill, -1)); rts += 1; pos = 0
        elif pos == -1:
            trail = min(lb, vw) if not np.isnan(vw) else lb
            if px > trail:
                fills.append((chk, fill, +1)); rts += 1; pos = 0
        if pos == 0:
            if px > ub:
                fills.append((chk, fill, +1)); pos = 1
            elif px < lb:
                fills.append((chk, fill, -1)); pos = -1
    # close out at last bar close
    if pos != 0:
        fills.append((lhm, crow[lhm], -pos)); rts += 1; pos = 0

    # build minute-level cum pnl path (points, gross) then subtract costs at exit fills
    hms = [hm for hm in cpx.columns if hm <= lhm and not np.isnan(crow.get(hm, np.nan))]
    hms = sorted(hms)
    pnl = np.zeros(len(hms))
    p = 0; cash = 0.0; ent = 0.0; cost_acc = 0.0
    fi = 0
    for j, hm in enumerate(hms):
        while fi < len(fills) and fills[fi][0] <= hm:
            fhm, fpx, dpos = fills[fi]
            if p != 0 and (p + dpos == 0 or np.sign(dpos) != np.sign(p)):
                cash += p * (fpx - ent)
                cost_acc += COST_RT_PTS
                p += dpos
                if p != 0:
                    ent = fpx
            else:
                ent = fpx
                p += dpos
            fi += 1
        m2m = p * (crow[hm] - ent) if p != 0 else 0.0
        pnl[j] = cash + m2m - cost_acc
    net_pts = pnl[-1] if len(pnl) else 0.0
    records.append({
        "date": d, "net_pts": net_pts, "net_usd": net_pts * POINT_VALUE,
        "gross_pts": net_pts + rts * COST_RT_PTS, "round_trips": rts,
        "open": O, "close": crow[lhm], "ret_frac": net_pts / O,
        "half_day": lhm < 950,
    })
    paths[str(d)] = (np.array(hms, dtype=np.int16), pnl.astype(np.float32))

res = pd.DataFrame(records)
res.to_csv(os.path.join(OUT_DIR, "es_intraday_momentum_daily.csv"), index=False)
np.savez_compressed(
    os.path.join(OUT_DIR, "es_intraday_momentum_paths.npz"),
    **{f"{k}_hm": v[0] for k, v in paths.items()},
    **{f"{k}_pnl": v[1] for k, v in paths.items()},
)

res["date"] = pd.to_datetime(res["date"])
res["year"] = res["date"].dt.year

def summarize(sub, label):
    n = len(sub)
    mu = sub["net_usd"].mean(); sd = sub["net_usd"].std()
    tstat = mu / sd * np.sqrt(n) if sd > 0 else np.nan
    mu_bps = sub["ret_frac"].mean() * 1e4
    sharpe = sub["ret_frac"].mean() / sub["ret_frac"].std() * np.sqrt(252)
    hit = (sub["net_usd"] > 0).mean()
    traded = (sub["round_trips"] > 0).mean()
    return {
        "label": label, "days": n, "avg_usd_per_day": round(mu, 2),
        "sd_usd": round(sd, 2), "t_stat": round(tstat, 2),
        "avg_bps": round(mu_bps, 2), "sharpe": round(sharpe, 2),
        "hit_rate_all_days": round(hit, 3), "pct_days_traded": round(traded, 3),
        "avg_rts_per_day": round(sub["round_trips"].mean(), 2),
        "worst_day_usd": round(sub["net_usd"].min(), 2),
        "best_day_usd": round(sub["net_usd"].max(), 2),
    }

summ = [summarize(res, "full 2008-2026")]
for y0, y1, lab in [(2008, 2015, "2008-2015"), (2016, 2021, "2016-2021"),
                    (2022, 2026, "2022-2026"), (2023, 2026, "2023-2026 (recent regime)"),
                    (2024, 2024, "2024"), (2025, 2026, "2025-2026 (post-publication)")]:
    sub = res[(res["year"] >= y0) & (res["year"] <= y1)]
    if len(sub):
        summ.append(summarize(sub, lab))

yearly = res.groupby("year").agg(net_usd=("net_usd", "sum"), days=("net_usd", "size"),
                                 avg_bps=("ret_frac", lambda s: s.mean() * 1e4)).round(1)
print(yearly.to_string())
print()
for s in summ:
    print(s)
with open(os.path.join(OUT_DIR, "es_intraday_momentum_summary.json"), "w") as f:
    json.dump({"summaries": summ, "yearly": yearly.reset_index().to_dict("records"),
               "cost_rt_pts": COST_RT_PTS}, f, indent=2, default=str)
print("done")

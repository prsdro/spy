"""Shared engine for the SSRN-4824172 intraday momentum replication.

Input df: columns ts (ET, tz-naive), o, h, l, c, v — 1-minute bars.
Only RTH (09:30-15:59 ET) is used. Returns (daily DataFrame, paths dict).
"""
import numpy as np
import pandas as pd

def run(df, vm=1.0, cost_rt_price_units=0.0, first_check="10:00", lookback=14):
    LOOKBACK = lookback
    df = df.copy()
    df["date"] = df["ts"].dt.date
    df["hm"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute

    rth = df[(df["hm"] >= 570) & (df["hm"] <= 959)].copy()
    opens = rth[rth["hm"] == 570].set_index("date")["o"]
    valid_days = opens.index
    rth = rth[rth["date"].isin(valid_days)]

    closes = rth.groupby("date")["c"].last()
    last_hm = rth.groupby("date")["hm"].max()

    days = sorted(valid_days)
    day_idx = {d: i for i, d in enumerate(days)}
    prev_close = {days[i]: closes[days[i - 1]] for i in range(1, len(days))}

    rth["move"] = (rth["c"] / rth["date"].map(opens) - 1.0).abs()
    mv = rth.pivot_table(index="date", columns="hm", values="move")
    sigma = mv.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).mean()

    cpx = rth.pivot_table(index="date", columns="hm", values="c")
    opx = rth.pivot_table(index="date", columns="hm", values="o")
    tp = (rth["h"] + rth["l"] + rth["c"]) / 3.0
    rth["pv"] = tp * rth["v"]
    g = rth.groupby("date")
    rth["cum_pv"] = g["pv"].cumsum()
    rth["cum_v"] = g["v"].cumsum()
    rth["vwap"] = rth["cum_pv"] / rth["cum_v"].replace(0, np.nan)
    vwp = rth.pivot_table(index="date", columns="hm", values="vwap")

    fc = int(first_check.split(":")[0]) * 60 + int(first_check.split(":")[1])
    check_hm = list(range(fc, 960, 30))

    records, paths = [], {}
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
        pos = 0; rts = 0
        fills = []
        for chk in check_hm:
            s_hm = chk - 1
            if s_hm > lhm or chk > lhm:
                break
            px = crow.get(s_hm, np.nan)
            sg = sig_row.get(s_hm, np.nan)
            vw = vrow.get(s_hm, np.nan)
            fill = orow.get(chk, np.nan)
            if np.isnan(px) or np.isnan(sg) or np.isnan(fill):
                continue
            ub = anchor_hi * (1 + vm * sg)
            lb = anchor_lo * (1 - vm * sg)
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
        if pos != 0:
            fills.append((lhm, crow[lhm], -pos)); rts += 1; pos = 0

        hms = sorted(hm for hm in cpx.columns
                     if hm <= lhm and not np.isnan(crow.get(hm, np.nan)))
        pnl = np.zeros(len(hms))
        p = 0; cash = 0.0; ent = 0.0; cost_acc = 0.0
        fi = 0
        for j, hm in enumerate(hms):
            while fi < len(fills) and fills[fi][0] <= hm:
                fhm, fpx, dpos = fills[fi]
                if p != 0 and np.sign(dpos) != np.sign(p):
                    cash += p * (fpx - ent)
                    cost_acc += cost_rt_price_units
                    p += dpos
                    if p != 0:
                        ent = fpx
                else:
                    ent = fpx
                    p += dpos
                fi += 1
            m2m = p * (crow[hm] - ent) if p != 0 else 0.0
            pnl[j] = cash + m2m - cost_acc
        net = pnl[-1] if len(pnl) else 0.0
        records.append({
            "date": d, "net": net, "gross": net + rts * cost_rt_price_units,
            "round_trips": rts, "open": O, "close": crow[lhm],
            "ret_frac": net / O, "gross_ret_frac": (net + rts * cost_rt_price_units) / O,
            "half_day": lhm < 950,
        })
        paths[str(d)] = (np.array(hms, dtype=np.int16), pnl.astype(np.float32))

    res = pd.DataFrame(records)
    res["date"] = pd.to_datetime(res["date"])
    res["year"] = res["date"].dt.year
    return res, paths


def summarize(sub, label, col="ret_frac"):
    n = len(sub)
    mu = sub[col].mean(); sd = sub[col].std()
    return {
        "label": label, "days": n,
        "avg_bps": round(mu * 1e4, 2),
        "t_stat": round(mu / sd * np.sqrt(n), 2) if sd > 0 else np.nan,
        "sharpe": round(mu / sd * np.sqrt(252), 2) if sd > 0 else np.nan,
        "ann_ret_simple": round(mu * 252 * 100, 1),
        "hit_traded": round((sub[sub["round_trips"] > 0][col] > 0).mean(), 3),
        "pct_days_traded": round((sub["round_trips"] > 0).mean(), 3),
        "avg_rts": round(sub["round_trips"].mean(), 2),
    }

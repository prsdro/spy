#!/usr/bin/env python3
"""Bilbo stock-directional variation: first TP at next Swing ATR level.

Keeps the existing strict stock-directional entry/exit universe:
  - entries from theta_entries.parquet, intraday only
  - strict execution: fill entry at the next RTH 5m close after signal
  - exits evaluated on RTH 5m bars only
  - baseline remaining-exit logic: opposite box-edge invalidation, or after
    +0.75 daily-ATR favorable excursion a 50% retrace, or 5-trading-day cap

Variation:
  - compute monthly/Swing ATR ladder from the ticker's own RTH daily bars
    using prior completed month's close and prior completed monthly ATR(14)
  - in trade direction, the next Swing ATR rung beyond entry price is T1
  - if T1 is touched, exit 2/3 of position at the level
  - remaining 1/3 follows the existing underlying-keyed exit logic
  - if T1 is not touched, full position follows existing exit logic

Outputs:
  analyst/po_comp_options/theta/theta_stock_directional_swingtp.parquet
  analyst/po_comp_options/theta/swingtp_summary.csv
"""
from __future__ import annotations

import math
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from indicators import atr

warnings.filterwarnings("ignore")

STUDY = Path("/root/spy/analyst/po_comp_options")
OUTDIR = STUDY / "theta"
P5 = "/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet"
COST = 0.0004
ARM_DATR = 0.75
RETRACE = 0.50
CAP_S = 5 * 86400 * 7 // 5  # existing convention: 5 trading days ~ 7 calendar days
TP_WEIGHT = float(os.environ.get("SWING_TP_WEIGHT", str(2.0 / 3.0)))
RUNNER_WEIGHT = 1.0 - TP_WEIGHT
TARGET_OFFSET = max(1, int(os.environ.get("SWING_TP_TARGET_OFFSET", "1")))
OUTPUT_TAG = os.environ.get("SWING_TP_TAG", "swingtp")
MIN_N = 50

# Saty ATR ladder rungs. Swing mode = monthly ATR and prior monthly close.
FIBS = [
    0.0,
    0.236,
    0.382,
    0.500,
    0.618,
    0.786,
    1.000,
    1.236,
    1.618,
    2.000,
    2.618,
    3.000,
]


def load5(tkr: str) -> pd.DataFrame:
    frames = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            frames.append(pd.read_parquet(
                p, columns=["metric_ts_et", "open", "high", "low", "close"]
            ))
    for top in ["underlying_5m_topup_v2.parquet", "underlying_5m_topup_new12.parquet"]:
        p = STUDY / top
        if not p.exists():
            continue
        t = pd.read_parquet(p)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={"ts": "metric_ts_et"})
            frames.append(t[["metric_ts_et", "open", "high", "low", "close"]])
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df.metric_ts_et, utc=True).dt.tz_convert("America/New_York")
    df = df.drop_duplicates(subset="ts").sort_values("ts").set_index("ts")
    return df[["open", "high", "low", "close"]]


def strict_rth_arrays(df5: pd.DataFrame):
    rth = df5.between_time("09:30", "15:55").copy()
    return (
        rth.index.map(lambda x: int(x.timestamp())).to_numpy(),
        rth.high.to_numpy(float),
        rth.low.to_numpy(float),
        rth.close.to_numpy(float),
        rth.index.to_numpy(),
    )


def swing_month_refs(df5: pd.DataFrame) -> pd.DataFrame:
    """Return month-indexed prior close + prior monthly ATR for Swing levels."""
    rth = df5.between_time("09:30", "15:55")
    dly = rth.resample("1D").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).dropna()
    mo = dly.resample("ME").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).dropna(subset=["close"])
    mo["atr_14"] = atr(mo, 14)
    # Levels for current calendar month are from prior completed month.
    refs = pd.DataFrame({"pmc": mo["close"].shift(1), "atr_m": mo["atr_14"].shift(1)})
    refs["period"] = refs.index.to_period("M")
    return refs.set_index("period")[["pmc", "atr_m"]]


def next_swing_level(entry_px: float, direction: int, ts_et, refs: pd.DataFrame, offset: int = 1):
    period = pd.Timestamp(ts_et).to_period("M")
    if period not in refs.index:
        return math.nan, "missing"
    pmc = float(refs.loc[period, "pmc"])
    atr_m = float(refs.loc[period, "atr_m"])
    if not np.isfinite(pmc) or not np.isfinite(atr_m) or atr_m <= 0:
        return math.nan, "missing"

    levels = []
    for f in FIBS:
        if f == 0:
            levels.append((pmc, "0"))
        else:
            levels.append((pmc + f * atr_m, f"+{f:.3f}"))
            levels.append((pmc - f * atr_m, f"-{f:.3f}"))
    levels.sort(key=lambda x: x[0])
    eps = max(abs(entry_px) * 1e-7, 1e-5)
    if direction == 1:
        cands = [(px, label) for px, label in levels if px > entry_px + eps]
        if not cands:
            return math.nan, "above_ladder"
        if len(cands) < offset:
            return math.nan, "above_ladder"
        return float(cands[offset - 1][0]), cands[offset - 1][1]
    cands = [(px, label) for px, label in levels if px < entry_px - eps]
    if not cands:
        return math.nan, "below_ladder"
    if len(cands) < offset:
        return math.nan, "below_ladder"
    return float(cands[-offset][0]), cands[-offset][1]


def run_trade(r, arrays, refs):
    t, hi, lo, cl, idx = arrays
    entry_s = int(pd.Timestamp(r.entry_ts).timestamp())
    i0 = np.searchsorted(t, entry_s, side="right")
    if i0 >= len(t):
        return None
    entry_px = float(cl[i0])  # strict delayed fill at next RTH 5m close
    entry_idx = i0
    i0 += 1
    if i0 >= len(t):
        return None

    target_px, target_label = next_swing_level(entry_px, int(r.direction), idx[entry_idx], refs, TARGET_OFFSET)
    has_target = np.isfinite(target_px)
    best = 0.0
    base_exit_px = None
    base_exit_j = None
    tp_hit = False
    tp_j = None

    end = np.searchsorted(t, entry_s + CAP_S)
    end = min(end, len(t))
    for j in range(i0, end):
        if r.direction == 1:
            if has_target and not tp_hit and hi[j] >= target_px:
                tp_hit = True
                tp_j = j
            best = max(best, hi[j] - entry_px)
            exit_now = cl[j] < r.box_lo or (best >= ARM_DATR * r.datr14_prior and cl[j] <= entry_px + RETRACE * best)
        else:
            if has_target and not tp_hit and lo[j] <= target_px:
                tp_hit = True
                tp_j = j
            best = max(best, entry_px - lo[j])
            exit_now = cl[j] > r.box_hi or (best >= ARM_DATR * r.datr14_prior and cl[j] >= entry_px - RETRACE * best)
        if exit_now:
            base_exit_px = float(cl[j])
            base_exit_j = j
            break

    if base_exit_px is None:
        j = end - 1
        if j < i0:
            return None
        base_exit_px = float(cl[j])
        base_exit_j = j

    base_ret = int(r.direction) * (base_exit_px - entry_px) / entry_px - COST
    if tp_hit:
        tp_ret_gross = int(r.direction) * (target_px - entry_px) / entry_px
        runner_ret_gross = int(r.direction) * (base_exit_px - entry_px) / entry_px
        swingtp_ret = TP_WEIGHT * tp_ret_gross + RUNNER_WEIGHT * runner_ret_gross - COST
        tp_ret = tp_ret_gross - COST
    else:
        swingtp_ret = base_ret
        tp_ret = math.nan

    boxw = (float(r.box_hi) - float(r.box_lo)) / float(r.datr14_prior)
    return {
        "pop": r.pop,
        "ticker": r.ticker,
        "direction": int(r.direction),
        "date": str(pd.Timestamp(r.entry_ts).date()),
        "year": int(pd.Timestamp(r.entry_ts).year),
        "grey": min(int(r.grey_bars), 8),
        "boxw": boxw,
        "datr_pct": float(r.datr14_prior) / entry_px * 100,
        "entry_s": int(t[entry_idx]),
        "entry_px": entry_px,
        "base_exit_s": int(t[base_exit_j]),
        "base_exit_px": base_exit_px,
        "pnl_base": base_ret,
        "pnl_swingtp": swingtp_ret,
        "delta": swingtp_ret - base_ret,
        "target_px": target_px if has_target else math.nan,
        "target_label": target_label,
        "target_offset": TARGET_OFFSET,
        "tp_weight": TP_WEIGHT,
        "tp_hit": bool(tp_hit),
        "tp_s": int(t[tp_j]) if tp_hit else np.nan,
        "tp_ret": tp_ret,
        "target_dist_bps": int(r.direction) * (target_px - entry_px) / entry_px * 10000 if has_target else math.nan,
    }


def tstat(v: pd.Series) -> float:
    v = v.dropna()
    if len(v) < 2 or v.std(ddof=1) == 0:
        return math.nan
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def tcluster(g: pd.DataFrame, col: str) -> float:
    by = g.groupby("date")[col].mean().dropna()
    if len(by) < 2 or by.std(ddof=1) == 0:
        return math.nan
    return float(by.mean() / (by.std(ddof=1) / math.sqrt(len(by))))


def stat_row(label: str, g: pd.DataFrame) -> dict:
    if len(g) == 0:
        return {"label": label, "n": 0}
    out = {"label": label, "n": int(len(g))}
    for col in ["pnl_base", "pnl_swingtp", "delta"]:
        v = g[col].dropna()
        out[f"{col}_bps"] = float(10000 * v.mean()) if len(v) else math.nan
        out[f"{col}_med_bps"] = float(10000 * v.median()) if len(v) else math.nan
        out[f"{col}_t"] = tstat(v)
        out[f"{col}_tclust"] = tcluster(g, col) if col in g else math.nan
    out["win_base_pct"] = float(100 * (g.pnl_base > 0).mean())
    out["win_swingtp_pct"] = float(100 * (g.pnl_swingtp > 0).mean())
    out["tp_hit_pct"] = float(100 * g.tp_hit.mean())
    out["avg_target_dist_bps"] = float(g.target_dist_bps.mean())
    out["median_target_dist_bps"] = float(g.target_dist_bps.median())
    return out


def main():
    ent = pd.read_parquet(OUTDIR / "theta_entries.parquet")
    ent = ent[ent.intraday].copy().sort_values(["ticker", "entry_ts"])
    print(f"entries: {len(ent):,} intraday")
    print(f"variant: TP_WEIGHT={TP_WEIGHT:.4f}, RUNNER_WEIGHT={RUNNER_WEIGHT:.4f}, TARGET_OFFSET={TARGET_OFFSET}, OUTPUT_TAG={OUTPUT_TAG}")
    data = {}
    refs = {}
    rows = []
    for tkr in sorted(ent.ticker.unique()):
        df5 = load5(tkr)
        if df5.empty:
            print(f"{tkr}: missing 5m data")
            continue
        data[tkr] = strict_rth_arrays(df5)
        refs[tkr] = swing_month_refs(df5)
        sub = ent[ent.ticker == tkr]
        kept = 0
        for r in sub.itertuples(index=False):
            rec = run_trade(r, data[tkr], refs[tkr])
            if rec is not None:
                rows.append(rec)
                kept += 1
        print(f"{tkr}: {kept}/{len(sub)}")
    d = pd.DataFrame(rows)
    out = OUTDIR / f"theta_stock_directional_{OUTPUT_TAG}.parquet"
    d.to_parquet(out)

    summaries = []
    summaries.append(stat_row("ALL", d))
    for pop in ["hourly", "box30"]:
        gp = d[d["pop"] == pop]
        summaries.append(stat_row(f"{pop} all", gp))
        summaries.append(stat_row(f"{pop} bull", gp[gp.direction == 1]))
        summaries.append(stat_row(f"{pop} bear", gp[gp.direction == -1]))
        summaries.append(stat_row(f"{pop} bull grey5+", gp[(gp.direction == 1) & (gp.grey >= 5)]))
        summaries.append(stat_row(f"{pop} bull boxw<0.3 grey5+", gp[(gp.direction == 1) & (gp.grey >= 5) & (gp.boxw < 0.3)]))
    # era split for main family from prior blind-selection sheet
    hb = d[(d["pop"] == "hourly") & (d.direction == 1) & (d.grey >= 5)]
    summaries.append(stat_row("PRIMARY hourly bull grey5+ 2019-22", hb[hb.year <= 2022]))
    summaries.append(stat_row("PRIMARY hourly bull grey5+ 2023-26", hb[hb.year >= 2023]))
    hb3 = hb[hb.boxw < 0.3]
    summaries.append(stat_row("TOP hourly bull boxw<0.3 grey5+ 2019-22", hb3[hb3.year <= 2022]))
    summaries.append(stat_row("TOP hourly bull boxw<0.3 grey5+ 2023-26", hb3[hb3.year >= 2023]))

    s = pd.DataFrame(summaries)
    summary_path = OUTDIR / f"{OUTPUT_TAG}_summary.csv"
    s.to_csv(summary_path, index=False)
    print(f"wrote {out} rows={len(d):,}")
    print(f"wrote {summary_path}")
    cols = [
        "label", "n", "pnl_base_bps", "pnl_swingtp_bps", "delta_bps",
        "pnl_base_tclust", "pnl_swingtp_tclust", "win_base_pct", "win_swingtp_pct", "tp_hit_pct",
        "median_target_dist_bps",
    ]
    print("\nSUMMARY")
    print(s[cols].to_string(index=False, float_format=lambda x: f"{x:+.2f}"))


if __name__ == "__main__":
    main()

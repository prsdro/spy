"""Afternoon behavior of gap-up>=+0.786 ATR HOLDERS: small dip vs sideways?

For each holder day (open>=+0.786 ATR, every 10m close>=+0.786 ATR), anchor at
the noon close (last bar <= 12:00) and examine the afternoon (>12:00):
  - afternoon trough close and afternoon peak close (ATR units),
  - drawdown from noon anchor to afternoon trough (positive = a dip),
  - net change noon->final close.
Distinguishes a genuine pullback from flat consolidation.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from backtest_spx_gap_above_full_atr import load_spx_10m, load_spy_10m

NOON = pd.Timestamp("12:00").time()


def afternoon_stats(df, label):
    rows = []
    for _, g in df.groupby("date", sort=True):
        first = g.iloc[0]
        pdc, atr = first["prev_close"], first["atr_14"]
        open_atr = (first["open"] - pdc) / atr
        if open_atr < 0.786:
            continue
        hold_px = pdc + 0.786 * atr
        if not bool((g["close"] >= hold_px).all()):
            continue  # holders only

        c_atr = (g["close"] - pdc) / atr
        am = g.index.time <= NOON
        pm = g.index.time > NOON
        if not pm.any() or not am.any():
            continue
        noon_anchor = c_atr[am].iloc[-1]          # close at/just before noon
        noon_runmax = c_atr[am].max()             # best close reached by noon
        pm_close = c_atr[pm]
        rows.append({
            "date": str(g.index[0].date()),
            "noon_anchor": noon_anchor,
            "noon_runmax": noon_runmax,
            "pm_trough": pm_close.min(),
            "pm_peak": pm_close.max(),
            "final": c_atr.iloc[-1],
            "dip_from_anchor": noon_anchor - pm_close.min(),     # >0 = afternoon dip
            "dip_from_runmax": noon_runmax - pm_close.min(),
            "net_noon_to_close": c_atr.iloc[-1] - noon_anchor,
        })
    ev = pd.DataFrame(rows)
    n = len(ev)
    print(f"\n=== {label}  (holders, n={n}) ===")
    if n == 0:
        return
    def m(col): return ev[col].median()
    print(f"  noon anchor close (median ATR):      {m('noon_anchor'):+.3f}")
    print(f"  afternoon trough close (median):     {m('pm_trough'):+.3f}")
    print(f"  afternoon peak close (median):       {m('pm_peak'):+.3f}")
    print(f"  final close (median):                {m('final'):+.3f}")
    print(f"  DIP noon->pm trough (median ATR):    {m('dip_from_anchor'):+.3f}  "
          f"[p75 {ev['dip_from_anchor'].quantile(0.75):+.3f}, max {ev['dip_from_anchor'].max():+.3f}]")
    print(f"  net noon->close (median ATR):        {m('net_noon_to_close'):+.3f}")
    print(f"  afternoon dips >0.10 ATR below noon: "
          f"{(ev['dip_from_anchor']>0.10).mean()*100:4.1f}%  "
          f">0.25 ATR: {(ev['dip_from_anchor']>0.25).mean()*100:4.1f}%")
    print(f"  closes >= noon anchor:               {(ev['net_noon_to_close']>=0).mean()*100:4.1f}%")
    print(f"  closes >= noon RUNMAX (no give-back): {(ev['final']>=ev['noon_runmax']).mean()*100:4.1f}%")


if __name__ == "__main__":
    afternoon_stats(load_spx_10m(), "SPX")
    afternoon_stats(load_spy_10m(), "SPY")

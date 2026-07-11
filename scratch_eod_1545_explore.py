"""
EOD exploration: SPX 1-minute, final 15 minutes (15:45-16:00 ET = 2:45-3:00pm CT)
=================================================================================

Question (Pedro): is there an edge trading the last 15 minutes of the SPX
session? Candidate signal families, all measured as of the 15:44 ET bar close
(no lookahead), entry at the 15:45 bar open, exit at the 15:59 bar close:

  A. Baseline drift 15:45 -> close.
  B. Phase-oscillator (1m Saty PO, continuous EMAs) zone at 15:44.
  C. PO divergence: afternoon price lower-low / PO higher-low (bull) and
     price higher-high / PO lower-high (bear). Leg 1 = 13:00-15:14 extreme,
     leg 2 = 15:15-15:44 extreme.
  D. PO mean-reversion signals (leaving accumulation/distribution) firing
     15:30-15:44.
  E. Day trend continuation: (15:44 - RTH open) in daily-ATR units.
  F. Last-hour momentum: (15:44 - 14:44) in ATR units.
  G. Position in the Saty ladder: (15:44 - PDC) / daily ATR.
  H. Proximity to session high/low at 15:44.

Data: FirstRateData SPX index 1-min RTH (ET), 2008-01 -> 2026. Daily ATR(14)
is the one-session-lagged Wilder ATR from the daily file (Saty spec).
Forward return unit: index points and daily-ATR units. No costs (SPX index).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import load_spx
from indicators import compute_phase_oscillator

SIG_T = "15:44"   # last completed bar used for signals
ENTRY_T = "15:45"
EXIT_T = "15:59"

ERAS = [("2008-2012", 2008, 2012), ("2013-2019", 2013, 2019), ("2020-2026", 2020, 2026)]


def build_sessions() -> pd.DataFrame:
    df = load_spx()
    df = compute_phase_oscillator(df)
    df["time"] = df.index.strftime("%H:%M")

    rows = []
    for date, g in df.groupby("date", sort=True):
        tt = g["time"]
        if ENTRY_T not in tt.values or EXIT_T not in tt.values or "09:30" not in tt.values:
            continue  # half day / partial session
        sig = g[tt <= SIG_T]
        if len(sig) < 300:
            continue

        p_sig = sig["close"].iloc[-1]
        entry = g.loc[tt == ENTRY_T, "open"].iloc[0]
        exit_ = g.loc[tt == EXIT_T, "close"].iloc[0]
        atr = g["atr_14"].iloc[0]
        pdc = g["prev_close"].iloc[0]
        o = g["open"].iloc[0]

        # afternoon divergence legs
        aft = sig[tt[tt <= SIG_T] >= "13:00"]
        leg1 = aft[aft["time"] <= "15:14"]
        leg2 = aft[aft["time"] >= "15:15"]
        div = {}
        if len(leg1) > 10 and len(leg2) > 5:
            i_lo1, i_lo2 = leg1["low"].idxmin(), leg2["low"].idxmin()
            i_hi1, i_hi2 = leg1["high"].idxmax(), leg2["high"].idxmax()
            div = dict(
                lo1=leg1.at[i_lo1, "low"], lo2=leg2.at[i_lo2, "low"],
                po_lo1=leg1.at[i_lo1, "phase_oscillator"], po_lo2=leg2.at[i_lo2, "phase_oscillator"],
                hi1=leg1.at[i_hi1, "high"], hi2=leg2.at[i_hi2, "high"],
                po_hi1=leg1.at[i_hi1, "phase_oscillator"], po_hi2=leg2.at[i_hi2, "phase_oscillator"],
            )

        late = sig[sig["time"] >= "15:30"]
        p1444 = sig.loc[tt == "14:44", "close"]
        p1529 = sig.loc[tt == "15:29", "close"]

        rows.append(dict(
            date=pd.Timestamp(date),
            year=pd.Timestamp(date).year,
            atr=atr,
            fwd_pts=exit_ - entry,
            fwd_atr=(exit_ - entry) / atr,
            fwd_bps=(exit_ - entry) / entry * 1e4,
            po=sig["phase_oscillator"].iloc[-1],
            day_ret=(p_sig - o) / atr,
            last_hr=(p_sig - p1444.iloc[0]) / atr if len(p1444) else np.nan,
            last15=(p_sig - p1529.iloc[0]) / atr if len(p1529) else np.nan,
            atr_pos=(p_sig - pdc) / atr,
            dist_hi=(sig["high"].max() - p_sig) / atr,
            dist_lo=(p_sig - sig["low"].min()) / atr,
            leave_acc=int(late["leaving_accumulation"].sum() > 0),
            leave_dist=int(late["leaving_distribution"].sum() > 0),
            **div,
        ))
    return pd.DataFrame(rows)


def bucket_report(s: pd.DataFrame, col: str, edges: list[float], labels: list[str]) -> pd.DataFrame:
    b = pd.cut(s[col], edges, labels=labels)
    out = []
    for lab, g in s.groupby(b, observed=True):
        out.append(summarize(g, str(lab)))
    return pd.DataFrame(out)


def summarize(g: pd.DataFrame, label: str) -> dict:
    n = len(g)
    m = g["fwd_pts"].mean()
    sem = g["fwd_pts"].std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    row = dict(
        bucket=label, n=n,
        win_pct=round(100 * (g["fwd_pts"] > 0).mean(), 1),
        mean_pts=round(m, 3), med_pts=round(g["fwd_pts"].median(), 3),
        mean_atr=round(g["fwd_atr"].mean(), 4), mean_bps=round(g["fwd_bps"].mean(), 2),
        t=round(m / sem, 2) if sem and sem > 0 else np.nan,
    )
    for era, y0, y1 in ERAS:
        e = g[(g["year"] >= y0) & (g["year"] <= y1)]
        row[f"atr_{era}"] = round(e["fwd_atr"].mean(), 4) if len(e) else np.nan
        row[f"n_{era}"] = len(e)
    return row


def main() -> None:
    s = build_sessions()
    print(f"sessions: {len(s)}  ({s['date'].min().date()} -> {s['date'].max().date()})")
    pd.set_option("display.width", 250)

    print("\n== A. Baseline 15:45 -> close ==")
    print(pd.DataFrame([summarize(s, "all")]).to_string(index=False))

    print("\n== B. PO zone at 15:44 ==")
    print(bucket_report(
        s, "po", [-np.inf, -100, -61.8, -23.6, 23.6, 61.8, 100, np.inf],
        ["ext_down", "accum", "neut_dn", "neutral", "neut_up", "distrib", "ext_up"],
    ).to_string(index=False))

    print("\n== C. PO divergence (afternoon legs) ==")
    has = s.dropna(subset=["lo1"])
    bull = has[(has["lo2"] < has["lo1"]) & (has["po_lo2"] > has["po_lo1"])]
    bull_str = bull[bull["po_lo2"] > bull["po_lo1"] + 15]
    bear = has[(has["hi2"] > has["hi1"]) & (has["po_hi2"] < has["po_hi1"])]
    bear_str = bear[bear["po_hi2"] < bear["po_hi1"] - 15]
    ll_conf = has[(has["lo2"] < has["lo1"]) & (has["po_lo2"] <= has["po_lo1"])]   # lower low, PO confirms
    hh_conf = has[(has["hi2"] > has["hi1"]) & (has["po_hi2"] >= has["po_hi1"])]
    print(pd.DataFrame([
        summarize(bull, "bull_div (LL price, HL po)"),
        summarize(bull_str, "bull_div strong (+15)"),
        summarize(ll_conf, "lower_low, po confirms"),
        summarize(bear, "bear_div (HH price, LH po)"),
        summarize(bear_str, "bear_div strong (-15)"),
        summarize(hh_conf, "higher_high, po confirms"),
    ]).to_string(index=False))

    print("\n== D. PO mean-reversion signal fired 15:30-15:44 ==")
    print(pd.DataFrame([
        summarize(s[s["leave_acc"] == 1], "leaving_accumulation"),
        summarize(s[s["leave_dist"] == 1], "leaving_distribution"),
    ]).to_string(index=False))

    print("\n== E. Day trend (15:44 - open, ATR units) ==")
    print(bucket_report(
        s, "day_ret", [-np.inf, -1, -0.5, -0.15, 0.15, 0.5, 1, np.inf],
        ["<-1", "-1..-0.5", "-0.5..-0.15", "flat", "0.15..0.5", "0.5..1", ">1"],
    ).to_string(index=False))

    print("\n== F. Last-hour momentum (15:44 - 14:44, ATR units) ==")
    print(bucket_report(
        s, "last_hr", [-np.inf, -0.5, -0.25, -0.1, 0.1, 0.25, 0.5, np.inf],
        ["<-0.5", "-0.5..-0.25", "-0.25..-0.1", "flat", "0.1..0.25", "0.25..0.5", ">0.5"],
    ).to_string(index=False))

    print("\n== G. Saty ladder position (15:44 - PDC, ATR units) ==")
    print(bucket_report(
        s, "atr_pos", [-np.inf, -1, -0.618, -0.236, 0.236, 0.618, 1, np.inf],
        ["<-1", "-1..-0.618", "-0.618..-trig", "inside trig", "trig..0.618", "0.618..1", ">1"],
    ).to_string(index=False))

    print("\n== H. Distance from session extremes at 15:44 ==")
    print(pd.DataFrame([
        summarize(s[s["dist_hi"] <= 0.05], "at session HIGH (<=0.05 ATR)"),
        summarize(s[s["dist_lo"] <= 0.05], "at session LOW (<=0.05 ATR)"),
        summarize(s[(s["dist_hi"] > 0.05) & (s["dist_lo"] > 0.05)], "mid-range"),
    ]).to_string(index=False))

    s.to_csv("analyst/spx_eod_1545_sessions.csv", index=False)
    print("\nwrote analyst/spx_eod_1545_sessions.csv")


if __name__ == "__main__":
    main()

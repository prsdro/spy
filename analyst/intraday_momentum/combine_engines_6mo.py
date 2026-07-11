"""Combined 3-engine portfolio, 2026-01-26 -> 2026-07-10 (all forward data).

Engines (frozen specs, native 1-lot units):
  CompressionDrift — Config B aligned_cont/brk10/ATR-filter, 1 ES + 1 NQ
                     (analyst/forward_2026/forward_trades.csv)
  RibbonRider      — arm-entry ribbon cell on SPY, 1 ES-equivalent
                     (SPY pts x $500; analyst/es_ema_po_ribbon_forward_spy_trades.csv)
  BeatTheMarket    — NQ base spec + skip-expansion, 1 NQ (btm_forward_daily.csv)

Outputs combined_engines_daily.csv + stats printout.
"""
import numpy as np
import pandas as pd

START, END = "2026-01-26", "2026-07-10"

# --- CompressionDrift
dr = pd.read_csv("/root/spy/analyst/forward_2026/forward_trades.csv", parse_dates=["day"])
dr = dr[dr["config"] == "B_aligned_brk10"]
drift = dr.groupby("day")["net_usd"].sum()

# --- RibbonRider (SPY pts -> ES-equivalent $)
rb = pd.read_csv("/root/spy/analyst/es_ema_po_ribbon_forward_spy_trades.csv",
                 parse_dates=["entry_ts", "exit_ts"])
rb["day"] = rb["exit_ts"].dt.normalize()
rb["net_usd"] = rb["pnl_pts"] * 500.0
ribbon = rb.groupby("day")["net_usd"].sum()

# --- BeatTheMarket (filtered = frozen spec; skipped days = 0)
bt = pd.read_csv("btm_forward_daily.csv", parse_dates=["date"])
bt["net_usd_f"] = np.where(bt["rr6_60"] <= 1.21, bt["net_usd"], 0.0)
btm = bt.set_index("date")["net_usd_f"]

cal = pd.date_range(START, END, freq="B")
port = pd.DataFrame(index=cal)
port["CompressionDrift"] = drift.reindex(cal).fillna(0.0)
port["RibbonRider"] = ribbon.reindex(cal).fillna(0.0)
port["BeatTheMarket"] = btm.reindex(cal).fillna(0.0)
port["Combined"] = port.sum(axis=1)

# equal-risk version: scale each engine to $1,000/day realized sd over window
w = {c: 1000.0 / port[c].std() for c in ["CompressionDrift", "RibbonRider", "BeatTheMarket"]}
port["Combined_eqrisk"] = sum(port[c] * w[c] for c in w)

def stats(s, lab):
    eq = s.cumsum()
    dd = (eq - eq.cummax()).min()
    n = (s != 0).sum()
    mu, sd = s.mean(), s.std()
    print(f"{lab:22s} total=${s.sum():9,.0f} avg/day=${mu:7.1f} sd=${sd:7.0f} "
          f"sharpe={mu/sd*np.sqrt(252):5.2f} maxDD=${dd:9,.0f} active_days={n}")

print(f"window {START} -> {END}, {len(cal)} business days\n")
for c in ["CompressionDrift", "RibbonRider", "BeatTheMarket", "Combined"]:
    stats(port[c], c)
print("\nequal-risk weights (contracts-equivalent):",
      {k: round(v, 2) for k, v in w.items()})
stats(port["Combined_eqrisk"], "Combined_eqrisk($1k)")
print("\ndaily PnL correlations:")
print(port[["CompressionDrift", "RibbonRider", "BeatTheMarket"]].corr().round(2).to_string())
print("\nmonthly combined:")
print(port["Combined"].groupby(port.index.to_period("M")).sum().round(0).to_string())
port.to_csv("combined_engines_daily.csv")

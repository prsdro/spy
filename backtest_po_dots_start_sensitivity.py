"""
Start-date sensitivity for the PO-dots accumulation study (KNOWLEDGE.md #10).

For every start year 2000-2021 (all windows end at the last session, 2026-04-09),
re-run each capital model and compare against its like-for-like SPY benchmark:

  A. $1,000/month to cash, deploy all cash on buy dot   vs  immediate monthly DCA
  B. $10,000 fresh per buy dot                          vs  even-spaced DCA (same n, same $)
  C. $100,000 lump at start, deploy 20% of cash per dot vs  lump-sum SPY day one

Edge metric: money-weighted XIRR for A/B (contribution streams), TWR CAGR for C
(single inflow, so XIRR == TWR). Same mechanics as backtest_po_dots_buyhold.py:
next-open execution, real dividends reinvested while holding, cash at 0%.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

conn = sqlite3.connect(os.path.join(BASE_DIR, "spy.db"))
df0 = pd.read_sql_query(
    "SELECT timestamp, open, close, leaving_accumulation la, leaving_distribution ld "
    "FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
conn.close()
df0["buy"] = df0["la"].shift(1).fillna(0).astype(int)
df0["sell"] = df0["ld"].shift(1).fillna(0).astype(int)

div_by_date = {}
with open(os.path.join(BASE_DIR, "spy_dividends.json")) as f:
    for d in json.load(f):
        dt = datetime.fromtimestamp(d["ts"], tz=timezone.utc).date()
        div_by_date[dt] = div_by_date.get(dt, 0.0) + d["amount"]

# 13-week T-bill yield (^IRX) forward-filled onto the full session index
with open(os.path.join(BASE_DIR, "tbill_irx.json")) as f:
    irx = pd.DataFrame(json.load(f), columns=["ts", "rate"])
irx["date"] = (pd.to_datetime(irx["ts"], unit="s", utc=True)
               .dt.tz_localize(None).dt.normalize().astype(df0["timestamp"].dtype))
df0 = pd.merge_asof(df0, irx[["date", "rate"]], left_on="timestamp", right_on="date",
                    direction="backward").drop(columns=["date"])
df0["tbill"] = df0["rate"].fillna(0.0) / 100.0


def xirr(flows):
    t0 = flows[0][0]
    ts = np.array([(d - t0).days / 365.25 for d, _ in flows])
    amts = np.array([a for _, a in flows])

    def npv(r):
        return float(np.sum(amts / (1 + r) ** ts))

    lo, hi = -0.95, 5.0
    if npv(lo) * npv(hi) > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def simulate(df, model, rule, even_idx=None, cash_interest=False):
    """Same engine as the main study, compact. Returns dict of metrics."""
    dates = df["timestamp"].dt.date.to_numpy()
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    buy_e = df["buy"].to_numpy()
    sell_e = df["sell"].to_numpy()
    tbill = df["tbill"].to_numpy()
    gaps = np.diff([d.toordinal() for d in dates], prepend=dates[0].toordinal())
    month_key = df["timestamp"].dt.to_period("M")
    is_ms = (month_key != month_key.shift(1)).to_numpy()
    n = len(df)

    cash = shares = prev_sh = 0.0
    lots = []
    flows = []
    invested = 0.0
    if model in ("lump", "lump_bench"):
        cash = invested = 100_000.0
        flows.append((dates[0], 100_000.0))

    for i in range(n):
        o, c, dt = opens[i], closes[i], dates[i]
        if cash_interest and i > 0 and cash > 0:
            cash *= 1 + tbill[i] * gaps[i] / 365.0
        if model in ("monthly", "dca_monthly") and is_ms[i]:
            cash += 1_000.0; invested += 1_000.0; flows.append((dt, 1_000.0))
        if model == "per_dot" and buy_e[i]:
            cash += 10_000.0; invested += 10_000.0; flows.append((dt, 10_000.0))
        if model == "dca_even" and i in even_idx:
            cash += 10_000.0; invested += 10_000.0; flows.append((dt, 10_000.0))

        if model not in ("dca_monthly", "dca_even", "lump_bench") and sell_e[i] and shares > 0:
            if rule == "full_exit":
                cash += shares * o; shares = 0.0; lots = []
            elif rule == "one_lot" and lots:
                lot = min(lots.pop(), shares)
                cash += lot * o; shares -= lot

        buy_now = (cash > 0) if model in ("dca_monthly", "dca_even") else \
                  (i == 0) if model == "lump_bench" else bool(buy_e[i])
        if buy_now and cash > 0:
            deploy = cash * 0.20 if model == "lump" else cash
            shares += deploy / o; cash -= deploy
            lots.append(deploy / o)

        if dt in div_by_date and prev_sh > 0:
            pay = prev_sh * div_by_date[dt]
            if shares > 0:
                shares += pay / c
            else:
                cash += pay
        prev_sh = shares

    final = cash + shares * closes[-1]
    flows.append((dates[-1], -final))
    yrs = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days / 365.25
    return {"xirr": xirr(flows), "final": final, "invested": invested,
            "multiple": final / invested,
            "cagr": (final / invested) ** (1 / yrs) - 1}


rows = []
for year in range(2000, 2022):
    df = df0[df0["timestamp"] >= f"{year}-01-01"].reset_index(drop=True)
    n_dots = int(df["buy"].sum())
    even_idx = set(np.linspace(0, len(df) - 1, n_dots).round().astype(int).tolist())

    a_b = simulate(df, "dca_monthly", "acc")
    a_s = simulate(df, "monthly", "acc")
    a_f = simulate(df, "monthly", "full_exit")
    b_b = simulate(df, "dca_even", "acc", even_idx)
    b_s = simulate(df, "per_dot", "acc")
    b_f = simulate(df, "per_dot", "full_exit")
    c_b = simulate(df, "lump_bench", "acc")
    c_s = simulate(df, "lump", "acc")
    c_f = simulate(df, "lump", "full_exit")
    # benchmarks hold no cash, so only strategies change under T-bill accrual
    a_s_t = simulate(df, "monthly", "acc", cash_interest=True)
    a_f_t = simulate(df, "monthly", "full_exit", cash_interest=True)
    b_f_t = simulate(df, "per_dot", "full_exit", cash_interest=True)
    c_s_t = simulate(df, "lump", "acc", cash_interest=True)
    c_f_t = simulate(df, "lump", "full_exit", cash_interest=True)

    rows.append({
        "start": year, "yrs": round((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days / 365.25, 1),
        "dots": n_dots,
        "A_bench": a_b["xirr"], "A_acc": a_s["xirr"], "A_fx": a_f["xirr"],
        "B_bench": b_b["xirr"], "B_acc": b_s["xirr"], "B_fx": b_f["xirr"],
        "C_bench": c_b["cagr"], "C_acc": c_s["cagr"], "C_fx": c_f["cagr"],
        "A_acc_tb": a_s_t["xirr"], "A_fx_tb": a_f_t["xirr"],
        "B_fx_tb": b_f_t["xirr"],
        "C_acc_tb": c_s_t["cagr"], "C_fx_tb": c_f_t["cagr"],
    })

t = pd.DataFrame(rows)
for m in ["A", "B", "C"]:
    t[f"{m}_edge"] = t[f"{m}_acc"] - t[f"{m}_bench"]
    t[f"{m}_fx_edge"] = t[f"{m}_fx"] - t[f"{m}_bench"]
t["A_edge_tb"] = t["A_acc_tb"] - t["A_bench"]
t["A_fx_edge_tb"] = t["A_fx_tb"] - t["A_bench"]
t["B_fx_edge_tb"] = t["B_fx_tb"] - t["B_bench"]
t["C_edge_tb"] = t["C_acc_tb"] - t["C_bench"]
t["C_fx_edge_tb"] = t["C_fx_tb"] - t["C_bench"]

pct = lambda x: f"{x*100:6.2f}"
print("Accumulate-only edge vs benchmark (percentage points of annual return) by start year")
print("A = monthly XIRR vs DCA | B = per-dot XIRR vs even-DCA | C = lump CAGR vs lump-sum")
print()
print("start  yrs dots |  A_bench  A_acc  A_edge |  B_bench  B_acc  B_edge |  C_bench  C_acc  C_edge")
for _, r in t.iterrows():
    print(f"{int(r['start'])}  {r['yrs']:4.1f}  {int(r['dots']):3d} | "
          f"{pct(r['A_bench'])} {pct(r['A_acc'])} {pct(r['A_edge'])} | "
          f"{pct(r['B_bench'])} {pct(r['B_acc'])} {pct(r['B_edge'])} | "
          f"{pct(r['C_bench'])} {pct(r['C_acc'])} {pct(r['C_edge'])}")

print()
print("Full-exit edge vs benchmark (pp/yr) by start year")
print("start |  A_fx_edge  B_fx_edge  C_fx_edge")
for _, r in t.iterrows():
    print(f"{int(r['start'])} | {pct(r['A_fx_edge'])}  {pct(r['B_fx_edge'])}  {pct(r['C_fx_edge'])}")

print()
print("T-bill cash: accumulate-only edge vs benchmark (pp/yr) by start year")
print("start |  A_edge(0%)  A_edge(tb) |  C_edge(0%)  C_edge(tb)")
for _, r in t.iterrows():
    print(f"{int(r['start'])} |  {pct(r['A_edge'])}   {pct(r['A_edge_tb'])}  |  "
          f"{pct(r['C_edge'])}   {pct(r['C_edge_tb'])}")

print()
print("Summary across the 22 start years (accumulate-only edge, pp/yr):")
for col, lbl in [("A_edge", "A monthly, 0% cash"), ("A_edge_tb", "A monthly, T-bill"),
                 ("B_edge", "B per-dot $ (no cash held)"),
                 ("C_edge", "C lump tranches, 0% cash"), ("C_edge_tb", "C lump tranches, T-bill")]:
    e = t[col] * 100
    print(f"  {lbl:27s} median {e.median():+5.2f} | mean {e.mean():+5.2f} | "
          f"min {e.min():+5.2f} ({int(t.loc[e.idxmin(),'start'])}) | "
          f"max {e.max():+5.2f} ({int(t.loc[e.idxmax(),'start'])}) | "
          f"wins {int((e>0).sum())}/22 starts")
print("Full-exit:")
for col, lbl in [("A_fx_edge", "A full-exit, 0%"), ("A_fx_edge_tb", "A full-exit, T-bill"),
                 ("B_fx_edge", "B full-exit, 0%"), ("B_fx_edge_tb", "B full-exit, T-bill"),
                 ("C_fx_edge", "C full-exit, 0%"), ("C_fx_edge_tb", "C full-exit, T-bill")]:
    e = t[col] * 100
    print(f"  {lbl:27s} median {e.median():+5.2f} | max {e.max():+5.2f} "
          f"({int(t.loc[e.idxmax(),'start'])}) | wins {int((e>0).sum())}/22 starts")

t.to_csv(os.path.join(BASE_DIR, "analyst", "po_dots_start_sensitivity.csv"), index=False)
print("\nsaved analyst/po_dots_start_sensitivity.csv")

"""
Saty Phase Oscillator "dots" as a long-term SPY accumulation strategy.

Signals (daily ind_1d):
  - leaving_accumulation (osc crosses above -61.8)  -> BUY dot
  - leaving_distribution (osc crosses below +61.8)  -> SELL dot (variants only)

Execution: a dot observed at the close of day t executes at the OPEN of day t+1.
Dividends: real SPY dividend history (spy_dividends.json, Yahoo ex-dates).
  Shares held at the prior close receive the payout, reinvested at the ex-date close.
  Cash earns 0% (stated caveat).

Capital models:
  A. monthly  - $1,000 arrives at the first trading day of each month (at open).
               Strategies hold it as cash and deploy ALL cash on a buy dot.
               Benchmark: identical $1,000/month invested immediately (DCA).
  B. per_dot  - $10,000 of fresh cash arrives only on buy-dot execution days.
               Benchmarks: same n x $10,000 on an even-spaced schedule (DCA-even),
               and a lump sum of the same total on day one.
  C. lump     - $100,000 cash on day one; every buy dot deploys 20% of current cash.
               Benchmark: $100,000 lump-sum SPY on day one.

Sell rules (each run against accumulate-only and the benchmark):
  acc       - never sell.
  full_exit - sell entire position on a sell dot; next buy dot redeploys per model.
  one_lot   - sell the most recently bought lot (LIFO, one lot per sell dot).

All strategies are unitized like a fund: external cash buys "units" at the current
NAV, so the NAV path gives clean time-weighted CAGR / vol / Sharpe / max drawdown
even with irregular contributions. Money-weighted XIRR is computed from the actual
external cash-flow dates.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
DIV_PATH = os.path.join(BASE_DIR, "spy_dividends.json")

MONTHLY_AMT = 1_000.0
PER_DOT_AMT = 10_000.0
LUMP_AMT = 100_000.0
LUMP_FRACTION = 0.20

# ---------------------------------------------------------------- data loading

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query(
    "SELECT timestamp, open, close, leaving_accumulation, leaving_distribution "
    "FROM ind_1d ORDER BY timestamp",
    conn,
    parse_dates=["timestamp"],
)
conn.close()
df["date"] = df["timestamp"].dt.date
df = df.dropna(subset=["open", "close"]).reset_index(drop=True)

assert not ((df["leaving_accumulation"] == 1) & (df["leaving_distribution"] == 1)).any()

# signal on day t executes at open of day t+1
df["buy_exec"] = df["leaving_accumulation"].shift(1).fillna(0).astype(int)
df["sell_exec"] = df["leaving_distribution"].shift(1).fillna(0).astype(int)

with open(DIV_PATH) as f:
    raw_divs = json.load(f)
div_by_date = {}
for d in raw_divs:
    dt = datetime.fromtimestamp(d["ts"], tz=timezone.utc).date()
    div_by_date[dt] = div_by_date.get(dt, 0.0) + d["amount"]

dates = df["date"].tolist()
opens = df["open"].to_numpy()
closes = df["close"].to_numpy()
buy_exec = df["buy_exec"].to_numpy()
sell_exec = df["sell_exec"].to_numpy()
n_days = len(df)

# 13-week T-bill yield (^IRX, % annualized) forward-filled to each session,
# plus the calendar-day gap since the prior session for accrual.
with open(os.path.join(BASE_DIR, "tbill_irx.json")) as f:
    irx = pd.DataFrame(json.load(f), columns=["ts", "rate"])
irx["date"] = pd.to_datetime(irx["ts"], unit="s", utc=True).dt.date
irx_map = pd.merge_asof(
    pd.DataFrame({"date": pd.to_datetime(dates)}),
    irx[["date", "rate"]].assign(date=lambda x: pd.to_datetime(x["date"])),
    on="date", direction="backward",
)
tbill_rate = (irx_map["rate"].fillna(0.0) / 100.0).to_numpy()
gap_days = np.diff([d.toordinal() for d in dates], prepend=dates[0].toordinal())

# first trading day of each month -> contribution days for model A
month_key = df["timestamp"].dt.to_period("M")
is_month_start = (month_key != month_key.shift(1)).to_numpy()

# even-spaced schedule for benchmark B: same count as buy dots, spread over sample
n_buy_dots = int(buy_exec.sum())
even_idx = set(np.linspace(0, n_days - 1, n_buy_dots).round().astype(int).tolist())

# ------------------------------------------------------------------- simulator


def simulate(model, rule, cash_interest=False):
    """model: monthly|per_dot|lump|dca_monthly|dca_even|lump_bench
    rule:  acc|full_exit|one_lot (ignored by benchmarks)
    cash_interest: accrue idle cash at the prevailing 13-week T-bill yield"""
    cash = 0.0
    shares = 0.0
    lots = []  # share counts per buy, LIFO for one_lot
    units = 0.0
    nav_unit = 100.0
    prev_close_shares = 0.0

    flows = []  # (date, external amount in) for XIRR
    navs, equities, dts = [], [], []
    n_buys = n_sells = 0
    days_in_market = 0
    invested_total = 0.0

    if model in ("lump", "lump_bench"):
        flows.append((dates[0], LUMP_AMT))
        invested_total = LUMP_AMT
        cash = LUMP_AMT
        units = LUMP_AMT / nav_unit

    for i in range(n_days):
        o, c, dt = opens[i], closes[i], dates[i]

        if cash_interest and i > 0 and cash > 0:
            cash *= 1 + tbill_rate[i] * gap_days[i] / 365.0

        def add_external(amount, price):
            nonlocal cash, units, nav_unit, invested_total
            equity_before = cash + shares * price
            if units > 0 and equity_before > 0:
                nav_unit = equity_before / units
            units += amount / nav_unit
            cash += amount
            invested_total += amount
            flows.append((dt, amount))

        # --- external contributions at the open ---
        if model in ("monthly", "dca_monthly") and is_month_start[i]:
            add_external(MONTHLY_AMT, o)
        if model == "per_dot" and buy_exec[i]:
            add_external(PER_DOT_AMT, o)
        if model == "dca_even" and i in even_idx:
            add_external(PER_DOT_AMT, o)

        # --- trades at the open ---
        buy_now = False
        if model in ("dca_monthly", "dca_even"):
            buy_now = cash > 0
        elif model == "lump_bench":
            buy_now = i == 0
        elif buy_exec[i]:
            buy_now = True

        if model not in ("dca_monthly", "dca_even", "lump_bench") and sell_exec[i] and shares > 0:
            if rule == "full_exit":
                cash += shares * o
                shares = 0.0
                lots = []
                n_sells += 1
            elif rule == "one_lot" and lots:
                lot = lots.pop()
                lot = min(lot, shares)
                cash += lot * o
                shares -= lot
                n_sells += 1

        if buy_now and cash > 0:
            deploy = cash * LUMP_FRACTION if model == "lump" else cash
            bought = deploy / o
            shares += bought
            cash -= deploy
            lots.append(bought)
            n_buys += 1

        # --- dividend on ex-date: entitled by shares held at prior close ---
        if dt in div_by_date and prev_close_shares > 0:
            payout = prev_close_shares * div_by_date[dt]
            cash += payout
            if shares > 0:  # reinvest at the close while holding
                shares += payout / c
                cash -= payout

        # --- mark at the close ---
        equity = cash + shares * c
        if units > 0:
            nav_unit = equity / units
        navs.append(nav_unit)
        equities.append(equity)
        dts.append(dt)
        if shares * c > equity * 0.5:
            days_in_market += 1
        prev_close_shares = shares

    final_equity = equities[-1]
    flows.append((dates[-1], -final_equity))

    nav = pd.Series(navs, index=pd.to_datetime(dts))
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    twr_cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    monthly = nav.resample("ME").last().pct_change().dropna()
    vol = monthly.std() * np.sqrt(12)
    sharpe = (monthly.mean() * 12) / vol if vol > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()

    return {
        "model": model,
        "rule": rule,
        "invested": invested_total,
        "final": final_equity,
        "multiple": final_equity / invested_total,
        "xirr": xirr(flows),
        "twr_cagr": twr_cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_dd": dd,
        "pct_in_market": days_in_market / n_days,
        "n_buys": n_buys,
        "n_sells": n_sells,
        "equity_curve": (dts, equities),
        "nav_curve": (dts, navs),
    }


def xirr(flows):
    """Annualized money-weighted return. flows: (date, amount), inflows +, terminal -."""
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


# ------------------------------------------------------------------------ runs

RULES = ["acc", "full_exit", "one_lot"]
results = {}
results_tb = {}

for rule in RULES:
    for model in ("monthly", "per_dot", "lump"):
        results[(model, rule)] = simulate(model, rule)
        results_tb[(model, rule)] = simulate(model, rule, cash_interest=True)
for model in ("dca_monthly", "dca_even", "lump_bench"):
    results[(model, "-")] = simulate(model, "acc")
    results_tb[(model, "-")] = simulate(model, "acc", cash_interest=True)

LABELS = {
    "acc": "accumulate only (never sell)",
    "full_exit": "full exit on sell dot",
    "one_lot": "sell last lot on sell dot",
    "-": "benchmark",
}


def fmt(r):
    return (
        f"  invested ${r['invested']:>11,.0f} -> final ${r['final']:>13,.0f} "
        f"({r['multiple']:.2f}x) | XIRR {r['xirr']*100:5.2f}% | TWR CAGR {r['twr_cagr']*100:5.2f}% "
        f"| vol {r['vol']*100:4.1f}% | Sharpe {r['sharpe']:.2f} | maxDD {r['max_dd']*100:5.1f}% "
        f"| in-mkt {r['pct_in_market']*100:4.1f}% | buys {r['n_buys']:>3} sells {r['n_sells']:>3}"
    )


def show(key, bench_key=None):
    r0, rt = results[key], results_tb[key]
    d = (rt["xirr"] - r0["xirr"]) * 100
    print(f"  0%:    {fmt(r0).strip()}")
    print(f"  tbill: {fmt(rt).strip()}  (XIRR {d:+.2f}pp vs 0% cash)")


print(f"SPY {dates[0]} -> {dates[-1]} | {n_days:,} sessions | "
      f"{n_buy_dots} buy dots, {int(sell_exec.sum())} sell dots (daily PO)")
print("Cash regimes: 0% vs 13-week T-bill yield (^IRX, mean 2.00% over the period)\n")

print("=" * 134)
print(f"MODEL A - $1,000/month contributions ({results[('dca_monthly','-')]['invested']:,.0f} total)")
print("=" * 134)
print("DCA benchmark (invest immediately every month — holds no cash)")
show(("dca_monthly", "-"))
for rule in RULES:
    print(LABELS[rule])
    show(("monthly", rule))

print()
print("=" * 134)
print(f"MODEL B - $10,000 per buy dot (fresh cash only on dots)")
print("=" * 134)
print(f"Even-spaced DCA benchmark ({n_buy_dots} x $10k spread uniformly)")
show(("dca_even", "-"))
for rule in RULES:
    print(LABELS[rule])
    show(("per_dot", rule))

print()
print("=" * 134)
print(f"MODEL C - $100,000 lump at start, deploy {LUMP_FRACTION:.0%} of cash per buy dot")
print("=" * 134)
print("Lump-sum SPY benchmark (all in day one)")
show(("lump_bench", "-"))
for rule in RULES:
    print(LABELS[rule])
    show(("lump", rule))

# ---------------------------------------------------------- sell-dot diagnosis
# Does it pay to sell and redeploy on the next buy dot?
# For each sell dot -> next buy dot pair: price change between the two executions.
pairs = []
last_sell = None
for i in range(n_days):
    if sell_exec[i]:
        last_sell = i
    if buy_exec[i] and last_sell is not None:
        pairs.append((dates[last_sell], dates[i], opens[i] / opens[last_sell] - 1,
                      (df["timestamp"].iloc[i] - df["timestamp"].iloc[last_sell]).days))
        last_sell = None

pp = pd.DataFrame(pairs, columns=["sell_date", "rebuy_date", "px_change", "cal_days"])
print()
print("=" * 130)
print(f"SELL -> NEXT BUY DOT round trips (n={len(pp)}): does the rebuy come cheaper?")
print("=" * 130)
print(f"rebuy price LOWER than sell price: {(pp['px_change'] < 0).mean()*100:.1f}% "
      f"({(pp['px_change'] < 0).sum()}/{len(pp)})")
print(f"median price change sell->rebuy: {pp['px_change'].median()*100:+.2f}% | "
      f"mean {pp['px_change'].mean()*100:+.2f}%")
print(f"median wait: {pp['cal_days'].median():.0f} calendar days "
      f"(p25 {pp['cal_days'].quantile(.25):.0f}, p75 {pp['cal_days'].quantile(.75):.0f})")
print(f"worst miss (rebuy higher): {pp['px_change'].max()*100:+.1f}% on {pp.loc[pp['px_change'].idxmax(),'rebuy_date']}")
print(f"best save  (rebuy lower):  {pp['px_change'].min()*100:+.1f}% on {pp.loc[pp['px_change'].idxmin(),'rebuy_date']}")

# ------------------------------------------------------------------- save JSON
out = {
    "meta": {
        "start": str(dates[0]), "end": str(dates[-1]), "sessions": n_days,
        "buy_dots": n_buy_dots, "sell_dots": int(sell_exec.sum()),
        "monthly_amt": MONTHLY_AMT, "per_dot_amt": PER_DOT_AMT,
        "lump_amt": LUMP_AMT, "lump_fraction": LUMP_FRACTION,
        "dividends": "real SPY ex-dates, reinvested at close while holding",
        "cash_regimes": "0% and 13-week T-bill yield (^IRX)",
    },
    "strategies": {},
    "strategies_tbill": {},
    "sell_rebuy_pairs": [
        {"sell": str(a), "rebuy": str(b), "px_change": round(c, 5), "days": int(d)}
        for a, b, c, d in pairs
    ],
}
for slot, res in [("strategies", results), ("strategies_tbill", results_tb)]:
    for (model, rule), r in res.items():
        key = f"{model}|{rule}"
        dts_, eqs = r["equity_curve"]
        _, navs_ = r["nav_curve"]
        step = max(1, len(dts_) // 1500)  # thin curves for the JSON
        out[slot][key] = {
            k: (round(float(r[k]), 6) if isinstance(r[k], (int, float, np.floating)) else r[k])
            for k in ["invested", "final", "multiple", "xirr", "twr_cagr", "vol",
                       "sharpe", "max_dd", "pct_in_market", "n_buys", "n_sells"]
        }
        out[slot][key]["curve"] = [
            [str(dts_[j]), round(float(eqs[j]), 2), round(float(navs_[j]), 4)]
            for j in range(0, len(dts_), step)
        ] + [[str(dts_[-1]), round(float(eqs[-1]), 2), round(float(navs_[-1]), 4)]]

os.makedirs(os.path.join(BASE_DIR, "analyst"), exist_ok=True)
with open(os.path.join(BASE_DIR, "analyst", "po_dots_buyhold.json"), "w") as f:
    json.dump(out, f)
print("\nsaved analyst/po_dots_buyhold.json")

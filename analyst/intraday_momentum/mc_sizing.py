"""Prop-eval position sizing Monte Carlo for the intraday momentum engine.

Bootstraps whole trading days (minute-level intraday equity paths, in ES points
per 1 contract) from a chosen historical window, then simulates prop-account
mechanics:

  - trailing max drawdown (intraday marks or EOD marks), grid of $ amounts
  - profit target $4,500
  - Phase 1 (eval): P(hit target within 5 trading days) vs P(DD breach)
  - Phase 2 (funded): P(DD breach) over horizons + distribution of 10-day PnL

Sizing policies:
  - fixed N contracts
  - cushion-scaled: N_t = clip(floor(cushion_t / unit), 1, nmax), re-set daily
"""
import numpy as np
import pandas as pd
import json, sys

POINT_VALUE = 50.0
RNG = np.random.default_rng(42)
N_TRIALS = 20000

def load_paths(npz_file, csv_file, date_lo, date_hi):
    daily = pd.read_csv(csv_file, parse_dates=["date"])
    daily = daily[(daily["date"] >= date_lo) & (daily["date"] <= date_hi)]
    z = np.load(npz_file)
    days = []
    for d in daily["date"].dt.strftime("%Y-%m-%d"):
        k = f"{d}_pnl"
        if k in z:
            days.append(z[k])  # cumulative net points path for the day
    return days  # list of float32 arrays

def simulate(days, n_trials, policy, dd_amount, dd_mode, target, max_days,
             point_value=POINT_VALUE, seed=0):
    """policy(cushion_usd) -> contracts for the coming day.
    dd_mode: 'intraday' or 'eod' trailing high-water drawdown.
    Returns dict of outcome stats."""
    rng = np.random.default_rng(seed)
    n_days_hist = len(days)
    passes = np.zeros(n_trials, dtype=bool)
    blows = np.zeros(n_trials, dtype=bool)
    days_used = np.full(n_trials, np.nan)
    final_pnl = np.zeros(n_trials)
    for t in range(n_trials):
        eq = 0.0          # cumulative pnl vs start
        hwm = 0.0         # high-water mark for trailing dd
        outcome = 0
        d_count = 0
        while d_count < max_days:
            cushion = eq - (hwm - dd_amount)
            n = policy(cushion)
            path = days[rng.integers(n_days_hist)] * n * point_value
            day_eq = eq + path
            if dd_mode == "intraday":
                run_hwm = np.maximum.accumulate(np.maximum(day_eq, hwm))
                breach = day_eq <= run_hwm - dd_amount
            else:
                run_hwm = np.full(len(day_eq), hwm)
                breach = np.zeros(len(day_eq), dtype=bool)
            hit = day_eq >= target
            b_i = np.argmax(breach) if breach.any() else 10**9
            h_i = np.argmax(hit) if hit.any() else 10**9
            d_count += 1
            if h_i < b_i:
                outcome = 1; eq = day_eq[h_i]; break
            if b_i < h_i:
                outcome = -1; eq = day_eq[b_i]; break
            eq = day_eq[-1]
            if dd_mode == "intraday":
                hwm = max(hwm, day_eq.max())
            else:
                hwm = max(hwm, eq)
                if eq <= hwm - dd_amount:
                    outcome = -1; break
        passes[t] = outcome == 1
        blows[t] = outcome == -1
        days_used[t] = d_count
        final_pnl[t] = eq
    return {
        "p_pass": passes.mean(), "p_blow": blows.mean(),
        "p_neither": 1 - passes.mean() - blows.mean(),
        "med_days_to_resolve": float(np.nanmedian(days_used)),
        "avg_final_pnl": float(final_pnl.mean()),
    }

def fixed(n):
    return lambda cushion: n

def cushion_scaled(unit, nmax, nmin=1):
    return lambda cushion: int(np.clip(cushion // unit, nmin, nmax))

if __name__ == "__main__":
    npz, csv, lo, hi, out_json = sys.argv[1:6]
    days = load_paths(npz, csv, lo, hi)
    print(f"{len(days)} historical days in window {lo}..{hi}")
    results = []

    TARGET = 4500.0
    # ---- Phase 1: eval, want pass within 5 days, blowup tolerance ~50%
    for dd in [2000, 2500, 3000, 4000, 5000]:
        for mode in ["intraday", "eod"]:
            for n in [1, 2, 3, 5, 8, 12, 15, 20]:
                r = simulate(days, N_TRIALS, fixed(n), dd, mode, TARGET, 5, seed=n)
                r.update({"phase": "eval5d", "dd": dd, "mode": mode, "policy": f"fixed{n}"})
                results.append(r)
            # cushion-scaled: unit such that initial N ~ dd/unit
            for unit in [250, 400, 600, 1000]:
                r = simulate(days, N_TRIALS, cushion_scaled(unit, 25), dd, mode,
                             TARGET, 5, seed=unit)
                r.update({"phase": "eval5d", "dd": dd, "mode": mode,
                          "policy": f"cushion/{unit}"})
                results.append(r)

    # ---- Phase 1b: eval, no 5-day limit (pass whenever, or blow)
    for dd in [2500, 3000, 4000, 5000]:
        for mode in ["intraday", "eod"]:
            for n in [1, 2, 3, 5, 8]:
                r = simulate(days, 5000, fixed(n), dd, mode, TARGET, 60, seed=n)
                r.update({"phase": "eval_60d", "dd": dd, "mode": mode, "policy": f"fixed{n}"})
                results.append(r)

    # ---- Phase 2: funded. Target $4500 / 10 days repeatedly; measure P(blow) over 60d
    #      and E[pnl/10d]. Use huge target so only DD ends the sim.
    for dd in [2500, 3000, 4000, 5000]:
        for mode in ["intraday", "eod"]:
            for n in [1, 2, 3, 5]:
                r = simulate(days, 5000, fixed(n), dd, mode, 10**12, 60, seed=n)
                r["pnl_per_10d"] = r["avg_final_pnl"] / 6.0
                r.update({"phase": "funded60d", "dd": dd, "mode": mode, "policy": f"fixed{n}"})
                results.append(r)

    out = pd.DataFrame(results)
    out.to_csv(out_json.replace(".json", ".csv"), index=False)
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(out.head(30).to_string(index=False))
    print("saved", out_json)

"""
Independent validation of the Swing GG week-of-month + retrace study.

Re-runs the EXACT analyze() from backtest_swing_gg_wom.py — same level math,
same week-of-month buckets, same retrace ladder — but on a fully independent
data source: Yahoo Finance ^GSPC daily OHLC (vs the FirstRateData SPX file the
published page uses). If the patterns reproduce, the findings are not an
artifact of the FirstRate dataset or our loader.

Note: Yahoo daily bars are still OHLC, so they do NOT resolve the within-day
high-vs-low ordering caveat on the retrace ladder (no daily source can). This
validates the data/pipeline, not the intraday-ordering question.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

from backtest_swing_gg_wom import analyze, wom_table, retrace_table, overall

BASE_DIR = Path(__file__).resolve().parent
FIRSTRATE_JSON = BASE_DIR / "analyst" / "swing_gg_wom_summary.json"
OUT_JSON = BASE_DIR / "analyst" / "swing_gg_wom_validate_yahoo.json"

# Match the FirstRate window so the comparison is apples-to-apples.
WINDOW_START = "2000-11-27"
WINDOW_END = "2026-05-01"


def fetch_yahoo_gspc() -> pd.DataFrame:
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
           "?period1=0&period2=99999999999&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(ts, unit="s", utc=True)
                       .tz_convert("America/New_York").normalize().tz_localize(None),
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
    })
    # Yahoo can leave nulls on holidays / the live bar; drop them.
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def fmt(rows, keys):
    return {r[keys[0]]: {k: r[k] for k in keys[1:]} for r in rows}


def main():
    print("Fetching Yahoo ^GSPC daily ...", flush=True)
    daily = fetch_yahoo_gspc()
    print(f"  Yahoo full range: {daily['timestamp'].min().date()} -> {daily['timestamp'].max().date()} "
          f"({len(daily):,} bars)")
    daily = daily[(daily["timestamp"] >= WINDOW_START) & (daily["timestamp"] <= WINDOW_END)].copy()
    print(f"  Trimmed to FirstRate window: {daily['timestamp'].min().date()} -> "
          f"{daily['timestamp'].max().date()} ({len(daily):,} bars)")

    ev, n_months = analyze(daily)
    up = ev[ev["direction"] == "up"].copy()
    dn = ev[ev["direction"] == "down"].copy()

    yahoo = {
        "meta": {"n_months": n_months,
                 "date_start": str(daily["timestamp"].min().date()),
                 "date_end": str(daily["timestamp"].max().date()),
                 "up_opens": int(up["month_end"].nunique()),
                 "dn_opens": int(dn["month_end"].nunique())},
        "up": {"overall": overall(up), "by_wom": wom_table(up), "retrace": retrace_table(up)},
        "down": {"overall": overall(dn), "by_wom": wom_table(dn), "retrace": retrace_table(dn)},
    }
    with open(OUT_JSON, "w") as f:
        json.dump(yahoo, f, indent=2)

    fr = json.load(open(FIRSTRATE_JSON))

    def line(label, a, b):
        da = "—" if a is None else f"{a:5.1f}"
        db = "—" if b is None else f"{b:5.1f}"
        diff = "" if (a is None or b is None) else f"  Δ{a-b:+5.1f}"
        return f"    {label:<34}{da}  {db}{diff}"

    print(f"\n{'='*72}")
    print("  VALIDATION — Yahoo ^GSPC daily  vs  FirstRateData SPX (published)")
    print(f"{'='*72}")
    print(f"  Months analyzed:  Yahoo {yahoo['meta']['n_months']}  |  FirstRate {fr['meta']['n_months']}")
    print(f"  Up gate opens:    Yahoo {yahoo['meta']['up_opens']}  |  FirstRate {fr['meta']['months_up_gate_opens']}")
    print(f"  Dn gate opens:    Yahoo {yahoo['meta']['dn_opens']}  |  FirstRate {fr['meta']['months_dn_gate_opens']}")

    for d, lbl in [("up", "UPSIDE"), ("down", "DOWNSIDE")]:
        y, f0 = yahoo[d], fr[d]
        print(f"\n  --- {lbl} GATE ---            Yahoo  First   (Δ = Yahoo − FirstRate)")
        print(line("baseline completes", y["overall"]["completes"], f0["overall"]["completes"]))
        print(line("same-day complete", y["overall"]["same_day_complete"], f0["overall"]["same_day_complete"]))
        print("    by week-of-month (completes %):")
        yb = fmt(y["by_wom"], ["wom_name", "completes", "n"])
        fb = fmt(f0["by_wom"], ["wom_name", "completes", "n"])
        for wk in ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"]:
            if wk in yb or wk in fb:
                a = yb.get(wk, {}).get("completes"); b = fb.get(wk, {}).get("completes")
                na = yb.get(wk, {}).get("n", 0); nb = fb.get(wk, {}).get("n", 0)
                print(line(f"  {wk} (n {na}/{nb})", a, b))
        print("    retrace ladder (completes %):")
        yr = fmt(y["retrace"], ["retrace", "completes", "n"])
        fr_ = fmt(f0["retrace"], ["retrace", "completes", "n"])
        for k in ["none", "trigger", "pivot", "opposite"]:
            a = yr.get(k, {}).get("completes"); b = fr_.get(k, {}).get("completes")
            na = yr.get(k, {}).get("n", 0); nb = fr_.get(k, {}).get("n", 0)
            print(line(f"  {k} (n {na}/{nb})", a, b))

    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()

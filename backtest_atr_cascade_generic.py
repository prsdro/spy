#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from backtest_atr_cascade import (
    REPORT_LABELS, aggregate, aggregate_gg_retrace, analyse_adjacent_walk,
    analyse_day, analyse_gg_retrace_case, build_json_payload, print_by_hour_for_level, print_overall
)
from massive_pipeline.ticker_dataset import build_ticker_3m

BASE_DIR = Path(__file__).resolve().parent


def run(ticker: str, start: str, end: str, massive_root=None, splits_path=None, source="auto", out_json=None, out_csv=None, api_key=None):
    ticker = ticker.upper()
    print(f"Loading {ticker} Massive data {start}..{end} ({source})...")
    df, diag = build_ticker_3m(ticker, start, end, massive_root=massive_root, splits_path=splits_path, source=source, api_key=api_key)
    print("  diagnostics:")
    for k, v in diag.items():
        if k == "splits_applied":
            print(f"    {k}: {len(v)} split(s)")
        else:
            print(f"    {k}: {v}")

    print(f"\nProcessing {ticker} days...")
    all_events=[]; all_paths=[]; adjacent_walks=[]; gg_cases=[]
    for _, group in df.groupby("date", sort=True):
        ev, seq = analyse_day(group)
        all_events.extend(ev)
        if seq: all_paths.append(seq)
        walk = analyse_adjacent_walk(group)
        if walk: adjacent_walks.append(walk)
        for direction in ("call", "put"):
            case = analyse_gg_retrace_case(group, direction)
            if case is not None: gg_cases.append(case)
    print(f"  {len(all_events):,} level first-hit events recorded")
    print(f"  {len(all_paths):,} day-sequences captured")
    print(f"  {len(adjacent_walks):,} adjacent walk sequences captured")
    print(f"  {len(gg_cases):,} GG-open retrace/completion cases captured")

    out = aggregate(all_events)
    csv_path = Path(out_csv) if out_csv else BASE_DIR / "analyst" / f"atr_cascade_{ticker.lower()}_table.csv"
    json_path = Path(out_json) if out_json else BASE_DIR / "site" / "data" / f"atr-cascade-{ticker.lower()}.json"
    csv_path.parent.mkdir(parents=True, exist_ok=True); json_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(csv_path, index=False)
    gg_retrace = aggregate_gg_retrace(gg_cases)
    payload = build_json_payload(all_events, all_paths, out, int(df["date"].nunique()), gg_retrace=gg_retrace, adjacent_walks=adjacent_walks)
    payload["metadata"].update({
        "symbol": ticker,
        "source": diag["source"],
        "source_vendor": diag["source_vendor"],
        "timezone": diag["timezone"],
        "timestamp_convention": diag["timestamp_convention"],
        "bar_minutes": diag["bar_minutes"],
        "canonical_source_timeframe": diag["canonical_source_timeframe"],
        "intraday_start": diag["rth_3m_first"],
        "intraday_end": diag["rth_3m_last"],
        "daily_start": diag["daily_first"],
        "daily_end": diag["daily_last"],
        "loader_diagnostics": diag,
    })
    json_path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"\nWrote {csv_path}")
    print(f"Wrote {json_path} ({json_path.stat().st_size/1024:.1f} KB)")
    print_overall(out)
    for lab in [l for l in REPORT_LABELS if l != "PDC"]:
        sub = out[(out["level"] == lab) & (out["hour_bucket"] != "ALL")]
        if sub["n"].max() < 20: continue
        print_by_hour_for_level(out, lab)
    return payload


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ticker", required=True)
    p.add_argument("--start", default="2010-06-29")
    p.add_argument("--end", required=True)
    p.add_argument("--massive-root")
    p.add_argument("--splits")
    p.add_argument("--source", choices=["auto","flat","rest"], default="auto")
    p.add_argument("--out-json")
    p.add_argument("--out-csv")
    args=p.parse_args()
    run(args.ticker, args.start, args.end, massive_root=args.massive_root, splits_path=args.splits, source=args.source, out_json=args.out_json, out_csv=args.out_csv)
if __name__ == "__main__": main()

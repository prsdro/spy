"""Fetch 2026 forward 1-min bars for ES/NQ quarterly contracts from the
Massive/Polygon futures API (futures/v1/aggs). Saves per-contract CSVs
(ts,o,h,l,c,v; ET wall-clock, period-start) to analyst/forward_2026/.
Window: 2026-01-05 -> now (warmup buffer before the 2026-01-23 file cutoff)."""
import os, time, json, urllib.request

KEY = None
with open("/root/spx-chart-app/.env") as f:
    for line in f:
        if line.startswith("POLYGON_API_KEY"):
            KEY = line.strip().split("=", 1)[1]
OUT_DIR = "/root/spy/analyst/forward_2026"
os.makedirs(OUT_DIR, exist_ok=True)

CONTRACTS = ["ESH6", "ESM6", "ESU6", "NQH6", "NQM6", "NQU6"]
BASE = ("https://api.polygon.io/futures/v1/aggs/{t}?resolution=1min"
        "&window_start.gte=2026-01-05&limit=50000&sort=window_start.asc")

import datetime, zoneinfo
ET = zoneinfo.ZoneInfo("America/New_York")

for t in CONTRACTS:
    url = BASE.format(t=t) + f"&apiKey={KEY}"
    rows = []
    pages = 0
    while url:
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.load(r)
        res = d.get("results", [])
        for b in res:
            ts = datetime.datetime.fromtimestamp(
                b["window_start"] / 1e9, tz=datetime.timezone.utc
            ).astimezone(ET).replace(tzinfo=None)
            rows.append(f"{ts},{b['open']},{b['high']},{b['low']},"
                        f"{b['close']},{b['volume']}")
        pages += 1
        nxt = d.get("next_url")
        url = (nxt + f"&apiKey={KEY}") if nxt else None
        time.sleep(0.15)
    path = os.path.join(OUT_DIR, f"{t}_1min.csv")
    with open(path, "w") as f:
        f.write("\n".join(rows) + "\n")
    print(f"{t}: {len(rows)} bars in {pages} pages -> {path}, "
          f"first={rows[0].split(',')[0] if rows else '-'}, "
          f"last={rows[-1].split(',')[0] if rows else '-'}")

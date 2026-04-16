"""
Fetch SPY 1-minute data from MASSIVE API and insert into the database.
Fills the gap from Oct 22, 2025 to present.
"""

import os
import sqlite3
import requests
import time
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("SPY_DB_PATH", os.path.join(os.path.dirname(__file__), "spy.db"))
API_KEY = os.environ["MASSIVE_API_KEY"]
BASE_URL = "https://api.massive.com/v2/aggs/ticker/SPY/range/1/minute"

# UTC to ET offset: EDT (Mar-Nov) = UTC-4, EST (Nov-Mar) = UTC-5
# We'll convert each timestamp individually using the offset
def utc_ms_to_et_str(ts_ms):
    """Convert Unix millisecond timestamp to ET datetime string."""
    utc_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    # Determine EDT vs EST: EDT is Mar second Sun to Nov first Sun
    year = utc_dt.year
    # Approximate DST boundaries
    # 2025: Mar 9 - Nov 2 EDT
    # 2026: Mar 8 - Nov 1 EDT
    mar_dst = datetime(year, 3, 8 + (6 - datetime(year, 3, 1).weekday()) % 7, 2, tzinfo=timezone.utc)
    nov_dst = datetime(year, 11, 1 + (6 - datetime(year, 11, 1).weekday()) % 7, 2, tzinfo=timezone.utc)

    if mar_dst <= utc_dt < nov_dst:
        offset = timedelta(hours=-4)  # EDT
    else:
        offset = timedelta(hours=-5)  # EST

    et_dt = utc_dt + offset
    return et_dt.strftime("%Y-%m-%d %H:%M:%S")


def fetch_range(from_date, to_date):
    """Fetch 1-minute bars for a date range. Returns list of (timestamp_et, o, h, l, c, v)."""
    url = f"{BASE_URL}/{from_date}/{to_date}"
    params = {
        "apiKey": API_KEY,
        "limit": 50000,
        "sort": "asc",
        "adjusted": "true",
    }

    all_bars = []
    while url:
        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            print(f"  Error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        results = data.get("results", [])

        for bar in results:
            ts_et = utc_ms_to_et_str(bar["t"])
            all_bars.append((
                ts_et,
                bar["o"],
                bar["h"],
                bar["l"],
                bar["c"],
                int(bar["v"]),
            ))

        # Pagination
        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": API_KEY}  # next_url has other params embedded
            time.sleep(0.5)  # rate limit
        else:
            url = None

    return all_bars


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # Find where our data ends
    max_ts = conn.execute("SELECT MAX(timestamp) FROM candles_1m").fetchone()[0]
    print(f"Current data ends: {max_ts}")

    # Fetch from Oct 22, 2025 to today
    start_date = "2025-10-22"
    end_date = datetime.now().strftime("%Y-%m-%d")
    print(f"Fetching: {start_date} to {end_date}")

    # Batch by 2-week chunks to stay under 50K limit
    from datetime import date
    current = date(2025, 10, 22)
    end = datetime.now().date()
    total_inserted = 0

    while current <= end:
        chunk_end = min(current + timedelta(days=13), end)
        from_str = current.strftime("%Y-%m-%d")
        to_str = chunk_end.strftime("%Y-%m-%d")

        print(f"  Fetching {from_str} to {to_str}...", end=" ", flush=True)
        bars = fetch_range(from_str, to_str)

        if bars:
            # Filter out any bars we already have
            new_bars = [b for b in bars if b[0] > max_ts]

            if new_bars:
                conn.executemany(
                    "INSERT OR IGNORE INTO candles_1m (timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?)",
                    new_bars
                )
                conn.commit()
                total_inserted += len(new_bars)
                print(f"{len(new_bars)} new bars (total: {total_inserted:,})")
            else:
                print(f"{len(bars)} bars fetched, all duplicates")
        else:
            print("no data")

        current = chunk_end + timedelta(days=1)
        time.sleep(1)  # rate limit between chunks

    # Verify
    new_max = conn.execute("SELECT MAX(timestamp) FROM candles_1m").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM candles_1m").fetchone()[0]
    print(f"\nDone. Inserted {total_inserted:,} new bars.")
    print(f"Data now ends: {new_max}")
    print(f"Total 1m bars: {total:,}")

    conn.close()


if __name__ == "__main__":
    main()

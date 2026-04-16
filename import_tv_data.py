#!/usr/bin/env python3
"""
Import TradingView CSV exports into spy.db:
  1. Create tv_1h_multiday table from 84-column multi-day ATR files
  2. Update ind_1h Phase Oscillator values from file (1) for April 10-15 2025
"""

import csv
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = "/root/spy/spy.db"
ET = ZoneInfo("America/New_York")

# Multi-day ATR files in priority order (longest first = base, others fill gaps)
MULTIDAY_FILES = [
    "/root/spy/AMEX_SPY, 60 (8).csv",  # Apr 2022 - Apr 2026 (longest)
    "/root/spy/AMEX_SPY, 60 (7).csv",  # Nov 2022 - Apr 2026
    "/root/spy/AMEX_SPY, 60 (5).csv",  # Dec 2023 - Apr 2026
    "/root/spy/AMEX_SPY, 60 (4).csv",  # Jul 2024 - Apr 2026
    "/root/spy/AMEX_SPY, 60 (3).csv",  # Feb 2025 - Apr 2026
    "/root/spy/AMEX_SPY, 60 (2).csv",  # Aug 2025 - Apr 2026
    "/root/spy/AMEX_SPY, 60 (6).csv",  # Jun 2023 - Nov 2025 (OLDER, ends earlier)
]

# Day mode file for PO update
DAY_MODE_FILE = "/root/spy/AMEX_SPY, 60 (1).csv"


def parse_timestamp(ts_str: str) -> str:
    """Parse ISO timestamp with tz offset, convert to naive ET string."""
    dt = datetime.fromisoformat(ts_str)
    dt_et = dt.astimezone(ET)
    return dt_et.strftime("%Y-%m-%d %H:%M:%S")


def safe_float(val: str) -> float | None:
    """Convert string to float, returning None for empty/NaN."""
    if not val or val.strip() == "" or val.strip().lower() == "nan":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def safe_int(val: str) -> int | None:
    """Convert string to int (for leaving signals: 0/1 or empty)."""
    if not val or val.strip() == "":
        return None
    try:
        f = float(val)
        return int(f)
    except ValueError:
        return None


def parse_multiday_row(row: list) -> dict:
    """Parse a row from an 84-column multi-day ATR CSV."""
    return {
        "timestamp": parse_timestamp(row[0]),
        "open": safe_float(row[1]),
        "high": safe_float(row[2]),
        "low": safe_float(row[3]),
        "close": safe_float(row[4]),
        # Multi-day ATR levels
        "prev_close": safe_float(row[20]),
        "atr_upper_trigger": safe_float(row[21]),
        "atr_upper_0382": safe_float(row[22]),
        "atr_upper_050": safe_float(row[23]),
        "atr_upper_0618": safe_float(row[24]),
        "atr_upper_0786": safe_float(row[25]),
        "atr_upper_100": safe_float(row[26]),
        "atr_upper_1236": safe_float(row[27]),
        "atr_lower_trigger": safe_float(row[19]),
        "atr_lower_0382": safe_float(row[18]),
        "atr_lower_050": safe_float(row[17]),
        "atr_lower_0618": safe_float(row[16]),
        "atr_lower_0786": safe_float(row[15]),
        "atr_lower_100": safe_float(row[14]),
        "atr_lower_1236": safe_float(row[13]),
        # 1h EMAs
        "ema_8": safe_float(row[43]),
        "ema_13": safe_float(row[44]),
        "ema_21": safe_float(row[45]),
        "ema_48": safe_float(row[46]),
        "ema_200": safe_float(row[47]),
        # Daily EMA overlay (col 58 = Pivot EMA.1 = daily EMA21)
        "daily_ema_21": safe_float(row[58]),
        # Phase Oscillator
        "phase_oscillator": safe_float(row[76]),
        "leaving_accumulation": safe_int(row[77]),
        "leaving_extreme_down": safe_int(row[78]),
        "leaving_distribution": safe_int(row[79]),
        "leaving_extreme_up": safe_int(row[80]),
    }


def task1_create_multiday_table():
    """Create tv_1h_multiday table from multi-day ATR CSV files."""
    print("=" * 60)
    print("TASK 1: Creating tv_1h_multiday table")
    print("=" * 60)

    # Collect all rows keyed by timestamp. First file wins (base = file 8).
    all_rows = {}

    for fpath in MULTIDAY_FILES:
        fname = fpath.split("/")[-1]
        count_new = 0
        count_skip = 0

        with open(fpath, "r") as f:
            reader = csv.reader(f)
            header = next(reader)  # skip header
            ncols = len(header)
            if ncols != 84:
                print(f"  WARNING: {fname} has {ncols} columns, expected 84. Skipping.")
                continue

            for line_num, row in enumerate(reader, start=2):
                if len(row) < 81:
                    continue
                try:
                    parsed = parse_multiday_row(row)
                except Exception as e:
                    print(f"  WARNING: {fname} line {line_num}: {e}")
                    continue

                ts = parsed["timestamp"]
                if ts not in all_rows:
                    all_rows[ts] = parsed
                    count_new += 1
                else:
                    count_skip += 1

        print(f"  {fname}: {count_new} new rows, {count_skip} duplicates skipped")

    print(f"\nTotal unique rows: {len(all_rows)}")

    # Create table and insert
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS tv_1h_multiday")
    cur.execute("""
        CREATE TABLE tv_1h_multiday (
            timestamp TEXT PRIMARY KEY,
            open REAL, high REAL, low REAL, close REAL,
            prev_close REAL,
            atr_upper_trigger REAL,
            atr_upper_0382 REAL,
            atr_upper_050 REAL,
            atr_upper_0618 REAL,
            atr_upper_0786 REAL,
            atr_upper_100 REAL,
            atr_upper_1236 REAL,
            atr_lower_trigger REAL,
            atr_lower_0382 REAL,
            atr_lower_050 REAL,
            atr_lower_0618 REAL,
            atr_lower_0786 REAL,
            atr_lower_100 REAL,
            atr_lower_1236 REAL,
            ema_8 REAL,
            ema_13 REAL,
            ema_21 REAL,
            ema_48 REAL,
            ema_200 REAL,
            daily_ema_21 REAL,
            phase_oscillator REAL,
            leaving_accumulation INTEGER,
            leaving_extreme_down INTEGER,
            leaving_distribution INTEGER,
            leaving_extreme_up INTEGER
        )
    """)
    cur.execute("CREATE INDEX idx_tv_1h_multiday_ts ON tv_1h_multiday(timestamp)")

    cols = [
        "timestamp", "open", "high", "low", "close",
        "prev_close", "atr_upper_trigger", "atr_upper_0382", "atr_upper_050",
        "atr_upper_0618", "atr_upper_0786", "atr_upper_100", "atr_upper_1236",
        "atr_lower_trigger", "atr_lower_0382", "atr_lower_050", "atr_lower_0618",
        "atr_lower_0786", "atr_lower_100", "atr_lower_1236",
        "ema_8", "ema_13", "ema_21", "ema_48", "ema_200",
        "daily_ema_21",
        "phase_oscillator", "leaving_accumulation", "leaving_extreme_down",
        "leaving_distribution", "leaving_extreme_up",
    ]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO tv_1h_multiday ({','.join(cols)}) VALUES ({placeholders})"

    # Sort by timestamp for insertion
    sorted_rows = sorted(all_rows.values(), key=lambda r: r["timestamp"])
    batch = []
    for r in sorted_rows:
        batch.append(tuple(r[c] for c in cols))

    cur.executemany(sql, batch)
    conn.commit()

    # Verify
    cur.execute("SELECT COUNT(*) FROM tv_1h_multiday")
    total = cur.fetchone()[0]
    cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM tv_1h_multiday")
    mn, mx = cur.fetchone()
    print(f"\nInserted {total} rows into tv_1h_multiday")
    print(f"Date range: {mn} -> {mx}")

    # Validation: check a few prev_close values
    print("\n--- Validation: prev_close samples (should be weekly prev close) ---")
    cur.execute("""
        SELECT timestamp, close, prev_close, atr_upper_100, atr_lower_100
        FROM tv_1h_multiday
        WHERE timestamp LIKE '2025-04-14%'
        ORDER BY timestamp
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"  {row}")

    cur.execute("""
        SELECT timestamp, close, prev_close, atr_upper_100, atr_lower_100
        FROM tv_1h_multiday
        WHERE timestamp LIKE '2025-01-06%'
        ORDER BY timestamp
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"  {row}")

    # Check for any NULL prev_close in the data (excluding warmup period)
    cur.execute("""
        SELECT COUNT(*) FROM tv_1h_multiday
        WHERE prev_close IS NULL AND timestamp > '2022-06-01'
    """)
    null_count = cur.fetchone()[0]
    print(f"\nRows with NULL prev_close after 2022-06-01: {null_count}")

    conn.close()


def task2_update_ind_1h_po():
    """Update Phase Oscillator values in ind_1h from file (1) for April 10-15."""
    print("\n" + "=" * 60)
    print("TASK 2: Updating ind_1h Phase Oscillator from file (1)")
    print("=" * 60)

    # Parse file (1) - 115 columns, day mode
    # PO is at col 107, leaving signals at 108-111
    po_data = {}

    with open(DAY_MODE_FILE, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        ncols = len(header)
        print(f"  File (1) has {ncols} columns")

        # Verify column header
        print(f"  Col 107 header: '{header[107]}'")
        print(f"  Col 108 header: '{header[108]}'")

        for row in reader:
            if len(row) < 112:
                continue
            ts = parse_timestamp(row[0])
            po_data[ts] = {
                "phase_oscillator": safe_float(row[107]),
                "leaving_accumulation": safe_int(row[108]),
                "leaving_extreme_down": safe_int(row[109]),
                "leaving_distribution": safe_int(row[110]),
                "leaving_extreme_up": safe_int(row[111]),
            }

    print(f"  Parsed {len(po_data)} rows from file (1)")

    # Find the date range
    sorted_ts = sorted(po_data.keys())
    print(f"  Date range: {sorted_ts[0]} -> {sorted_ts[-1]}")

    # Now check what's in ind_1h for the April 10-15 range
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check current PO values vs file (1) for Apr 10-15
    print("\n--- Comparison: ind_1h vs file (1) PO for April 10-15 2025 ---")
    cur.execute("""
        SELECT timestamp, phase_oscillator
        FROM ind_1h
        WHERE timestamp >= '2025-04-10 00:00:00'
          AND timestamp <= '2025-04-15 23:59:59'
        ORDER BY timestamp
    """)
    db_rows = cur.fetchall()

    mismatches = 0
    updates = 0
    for ts, db_po in db_rows:
        if ts in po_data:
            tv_po = po_data[ts]["phase_oscillator"]
            if db_po != tv_po:
                if mismatches < 10:
                    print(f"  {ts}: DB={db_po:.4f}  TV={tv_po:.4f}" if db_po and tv_po else f"  {ts}: DB={db_po}  TV={tv_po}")
                mismatches += 1

    print(f"\n  Total rows in Apr 10-15 range: {len(db_rows)}")
    print(f"  Rows with PO mismatch: {mismatches}")

    # Update the rows from file (1) that overlap with ind_1h
    # We'll update ALL overlapping timestamps from file(1) into ind_1h
    update_sql = """
        UPDATE ind_1h
        SET phase_oscillator = ?,
            leaving_accumulation = ?,
            leaving_extreme_down = ?,
            leaving_distribution = ?,
            leaving_extreme_up = ?
        WHERE timestamp = ?
    """

    batch = []
    for ts, vals in po_data.items():
        batch.append((
            vals["phase_oscillator"],
            vals["leaving_accumulation"],
            vals["leaving_extreme_down"],
            vals["leaving_distribution"],
            vals["leaving_extreme_up"],
            ts,
        ))

    cur.executemany(update_sql, batch)
    updated = cur.rowcount
    conn.commit()

    print(f"\n  Updated {updated} rows in ind_1h with TV PO values from file (1)")

    # Verify a few rows after update
    print("\n--- Verification: ind_1h PO after update (Apr 10-15) ---")
    cur.execute("""
        SELECT timestamp, phase_oscillator, leaving_accumulation, leaving_distribution
        FROM ind_1h
        WHERE timestamp >= '2025-04-10 09:00:00'
          AND timestamp <= '2025-04-10 19:00:00'
        ORDER BY timestamp
    """)
    for row in cur.fetchall():
        print(f"  {row}")

    # Cross-check with tv_1h_multiday PO for same timestamps
    print("\n--- Cross-check: tv_1h_multiday PO vs ind_1h for a few bars ---")
    cur.execute("""
        SELECT m.timestamp, m.phase_oscillator AS multiday_po, i.phase_oscillator AS ind_po
        FROM tv_1h_multiday m
        JOIN ind_1h i ON m.timestamp = i.timestamp
        WHERE m.timestamp >= '2025-04-14 09:00:00'
          AND m.timestamp <= '2025-04-14 16:00:00'
        ORDER BY m.timestamp
    """)
    for row in cur.fetchall():
        print(f"  {row}")

    conn.close()

    print("\nNOTE: Historical ind_1h PO values (before file (1) coverage) are ETH-computed")
    print(f"  File (1) covers {sorted_ts[0]} to {sorted_ts[-1]}")
    print("  Only rows within this range now have correct RTH PO values.")


if __name__ == "__main__":
    task1_create_multiday_table()
    task2_update_ind_1h_po()
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

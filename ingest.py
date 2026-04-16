"""
Ingest all SPY 1-minute CSV files into a SQLite database.
Usage: python3 ingest.py [--test]  (--test loads only one file for validation)
"""

import sqlite3
import glob
import os
import sys
import time

DB_PATH = "/root/spy/spy.db"
CSV_DIR = "/root/spy/spy_contents/spy"

def create_db(conn):
    conn.execute("DROP TABLE IF EXISTS candles_1m")
    conn.execute("""
        CREATE TABLE candles_1m (
            timestamp TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_1m_ts ON candles_1m(timestamp)")

def ingest_csv(conn, filepath):
    """Load a single CSV into the database. Returns row count inserted."""
    count = 0
    with open(filepath, "r") as f:
        header = f.readline()  # skip header
        batch = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) != 6:
                continue
            ts, o, h, l, c, v = parts
            batch.append((ts, float(o), float(h), float(l), float(c), int(v)))
            if len(batch) >= 10000:
                conn.executemany(
                    "INSERT INTO candles_1m (timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?)",
                    batch
                )
                count += len(batch)
                batch = []
        if batch:
            conn.executemany(
                "INSERT INTO candles_1m (timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?)",
                batch
            )
            count += len(batch)
    return count

def main():
    test_mode = "--test" in sys.argv

    csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*_SPY_1M.csv")))
    if not csv_files:
        print("No CSV files found!")
        return

    if test_mode:
        csv_files = csv_files[-1:]  # just the latest file
        print(f"TEST MODE: loading only {csv_files[0]}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    create_db(conn)

    total_rows = 0
    t0 = time.time()
    for i, filepath in enumerate(csv_files):
        fname = os.path.basename(filepath)
        rows = ingest_csv(conn, filepath)
        total_rows += rows
        if (i + 1) % 20 == 0 or test_mode:
            print(f"  [{i+1}/{len(csv_files)}] {fname}: {rows} rows (total: {total_rows})")

    conn.commit()

    # Sort guarantee: create a sorted view or just verify index works
    row_count = conn.execute("SELECT COUNT(*) FROM candles_1m").fetchone()[0]
    min_ts = conn.execute("SELECT MIN(timestamp) FROM candles_1m").fetchone()[0]
    max_ts = conn.execute("SELECT MAX(timestamp) FROM candles_1m").fetchone()[0]

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Total rows: {row_count}")
    print(f"Date range: {min_ts} -> {max_ts}")

    conn.close()

if __name__ == "__main__":
    main()

"""
SPX Friday -2% selloffs -> what happens next.

Finds every session where the SPX cash index closed DOWN 2% or more ON A FRIDAY,
and tabulates the close-to-close path around it:

  - the 3 trading days BEFORE the Friday (context, "off to the left")
  - the Friday itself (the trigger)
  - the next 10 trading days (D+1 is the following session — usually Monday —
    through D+10)

Two views are emitted for the forward window:
  daily      : each day's own close-to-close return
  cumulative : return measured from the Friday CLOSE to that day's close

The 3 prior days are shown as daily returns in both views.

Data: FirstRateData SPX index daily (2000-11 -> 2026-05).
Output: site/data/spx-friday-drop.json
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one

BASE_DIR = Path(__file__).resolve().parent
OUT_JSON = BASE_DIR / "site" / "data" / "spx-friday-drop.json"

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
N_PREV = 3
N_FWD = 10
THRESH = -2.0
# trailing return windows in trading days (approx calendar months)
TRAIL = {"1m": 21, "3m": 63, "6m": 126}


ES_45_CSV = BASE_DIR / "analyst" / "es_post_close_45.csv"
VIX_CSV = BASE_DIR / "data" / "VIX_yahoo_daily.csv"


def load_vix():
    """date 'YYYY-MM-DD' -> CBOE VIX daily close (Yahoo ^VIX, 2008 ->)."""
    if not VIX_CSV.exists():
        print(f"  (VIX file missing: {VIX_CSV}; VIX columns blank)")
        return {}
    v = pd.read_csv(VIX_CSV, dtype={"date": str})
    return dict(zip(v["date"], v["close"]))


def fetch_yahoo_vix():
    """Best-effort recent ^VIX daily closes (date -> close) for the live row."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1mo&interval=1d"
    out = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.load(r)["chart"]["result"][0]
        ts = res["timestamp"]
        c = res["indicators"]["quote"][0]["close"]
        for t, cc in zip(ts, c):
            if cc is not None:
                out[pd.Timestamp(t, unit="s").strftime("%Y-%m-%d")] = float(cc)
    except Exception as e:
        print(f"  (live ^VIX fetch skipped: {e})")
    return out


def load_es_45():
    """date -> ES futures % move 4:00pm->5:00pm ET (16:00 open -> 16:59 close),
    precomputed from the FirstRateData ES 1-min continuous file (2008 -> 2026-01)."""
    if not ES_45_CSV.exists():
        print(f"  (ES 4-5pm map missing: {ES_45_CSV}; column will be blank)")
        return {}
    df = pd.read_csv(ES_45_CSV, dtype={"date": str})
    return dict(zip(df["date"], df["es_45"]))


def fetch_yahoo_es_45(date_str):
    """Best-effort ES=F 4:00pm->5:00pm ET move for a recent date (the static ES
    file lags). Uses 1-minute bars: 16:00 open -> 16:59 close. Guards against
    Yahoo stuffing the *final* bar's close with regularMarketPrice (which on a
    Friday lands on the 16:59 bar) by falling back to that bar's open."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/ES%3DF"
           "?range=5d&interval=1m&includePrePost=true")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.load(r)
        res = payload["chart"]["result"][0]
        gmt = res["meta"]["gmtoffset"]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        o, c = q["open"], q["close"]
        import datetime as _dt
        pre = post = None
        for i, t in enumerate(ts):
            et = _dt.datetime.utcfromtimestamp(t) + _dt.timedelta(seconds=gmt)
            if et.strftime("%Y-%m-%d") != date_str:
                continue
            if et.hour == 16 and et.minute == 0 and o[i]:
                pre = o[i]                      # 4:00pm print
            if et.hour == 16 and et.minute == 59 and o[i]:
                # use the 16:59 OPEN (clean ~4:59pm print). Yahoo stuffs the
                # *close* of the session's final bar with regularMarketPrice,
                # which on a Friday corrupts the 16:59 close.
                post = o[i]
        if pre and post:
            return round((post / pre - 1.0) * 100.0, 3)
    except Exception as e:
        print(f"  (live ES=F fetch skipped for {date_str}: {e})")
    return None


def fetch_yahoo_gspc(range_="1y"):
    """Best-effort recent ^GSPC daily closes from Yahoo (for still-unfolding rows
    past the static data file's end date). Returns a DataFrame or None."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
           f"?range={range_}&interval=1d")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.load(r)
        res = payload["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(ts, unit="s").normalize(),
            "close": closes,
        }).dropna(subset=["close"]).reset_index(drop=True)
        return df
    except Exception as e:  # network/parse issues -> skip live augmentation
        print(f"  (live Yahoo fetch skipped: {e})")
        return None


def build_event(df, i, n_prev, n_fwd, thresh, dow, r2, live=False):
    """Build one event dict from a daily df with a 'ret' column at integer index i."""
    closes = df["close"].to_numpy()
    rets = df["ret"].to_numpy()
    ts = df["timestamp"]
    fri_close = closes[i]
    # daily 21 EMA on the drop day: slope direction + close's distance from it
    ema_slope, ema_pct, ema_slope_pct = None, None, None
    if "ema21" in df.columns:
        ema = df["ema21"].to_numpy()
        if not pd.isna(ema[i]):
            ema_pct = r2((closes[i] / ema[i] - 1.0) * 100.0)   # close vs 21-EMA on the dump day
            # slope = the EMA's actual daily % change heading INTO the day
            # (i-1 vs i-2), so the dump's own close doesn't distort it. The
            # arrow on the page is tilted proportionally to this value.
            if i > 1 and not pd.isna(ema[i - 2]):
                ema_slope_pct = round((ema[i - 1] / ema[i - 2] - 1.0) * 100.0, 3)
                ema_slope = "up" if ema_slope_pct >= 0 else "down"
    # CBOE VIX: close the day before the dump, close on the dump, and the
    # dump-day % change.
    vix_pre = vix_post = vix_chg = None
    if "vix" in df.columns:
        vx = df["vix"].to_numpy()
        if not pd.isna(vx[i]):
            vix_post = round(float(vx[i]), 2)
        if i > 0 and not pd.isna(vx[i - 1]):
            vix_pre = round(float(vx[i - 1]), 2)
        if vix_pre and vix_post:
            vix_chg = round((vix_post / vix_pre - 1.0) * 100.0, 1)
    # trailing 1/3/6-month returns INTO this Friday close
    trail = {}
    for key, nd in TRAIL.items():
        j = i - nd
        trail[key] = r2((fri_close / closes[j] - 1.0) * 100.0) if j >= 0 else None
    prev = []
    for k in range(n_prev, 0, -1):
        j = i - k
        ok = j >= 0
        prev.append({
            "label": f"−{k}",
            "date": ts[j].strftime("%Y-%m-%d") if ok else None,
            "dow": dow[ts[j].weekday()] if ok else None,
            "daily": r2(rets[j]) if ok else None,
        })
    fwd = []
    for k in range(1, n_fwd + 1):
        j = i + k
        if j < len(df):
            fwd.append({
                "label": f"+{k}", "date": ts[j].strftime("%Y-%m-%d"),
                "dow": dow[ts[j].weekday()], "daily": r2(rets[j]),
                "cum": r2((closes[j] / fri_close - 1.0) * 100.0),
            })
        else:
            fwd.append({"label": f"+{k}", "date": None, "dow": None, "daily": None, "cum": None})
    n_avail = sum(1 for f in fwd if f["daily"] is not None)
    return {
        "date": ts[i].strftime("%Y-%m-%d"), "dow": dow[ts[i].weekday()],
        "dow_idx": int(ts[i].weekday()),
        "fri_ret": r2(rets[i]), "trail": trail, "prev": prev, "fwd": fwd,
        "ema_slope": ema_slope, "ema_slope_pct": ema_slope_pct, "ema_pct": ema_pct,
        "vix_pre": vix_pre, "vix_post": vix_post, "vix_chg": vix_chg,
        "live": live, "n_fwd_avail": n_avail,
    }


def main():
    d = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False).reset_index(drop=True)
    d["ret"] = d["close"].pct_change() * 100.0
    d["ema21"] = d["close"].ewm(span=21, adjust=False).mean()   # daily 21 EMA
    vixmap = load_vix()
    d["vix"] = d["timestamp"].dt.strftime("%Y-%m-%d").map(vixmap)
    closes = d["close"].to_numpy()
    rets = d["ret"].to_numpy()
    ts = d["timestamp"]

    # every session that closed down >=2% (any weekday; the page defaults to Friday)
    triggers = d.index[d["ret"] <= THRESH].tolist()

    def r2(x):
        return None if x is None or pd.isna(x) else round(float(x), 2)

    rows = [build_event(d, i, N_PREV, N_FWD, THRESH, DOW, r2) for i in triggers]
    zip_last = ts.max()

    # --- live augmentation: qualifying Fridays AFTER the static file's end date ---
    # (still-unfolding selloffs; forward cells fill in as Yahoo data extends).
    n_live = 0
    src = "FirstRateData SPX cash index, daily"
    y = fetch_yahoo_gspc()
    if y is not None and len(y):
        y["ret"] = y["close"].pct_change() * 100.0
        y["ema21"] = y["close"].ewm(span=21, adjust=False).mean()  # ~1y of closes = ample warmup
        vixmap.update(fetch_yahoo_vix())                           # extend VIX past the csv's end
        y["vix"] = y["timestamp"].dt.strftime("%Y-%m-%d").map(vixmap)
        yts = y["timestamp"]
        live_idx = y.index[(yts > zip_last) & (y["ret"] <= THRESH)].tolist()
        for i in live_idx:
            rows.append(build_event(y, i, N_PREV, N_FWD, THRESH, DOW, r2, live=True))
            n_live += 1
        if n_live:
            src += "; most-recent row(s) from Yahoo ^GSPC (live, still unfolding)"
        live_end = yts.max().strftime("%Y-%m-%d")
    else:
        live_end = None

    # --- attach ES futures 4:00pm->5:00pm ET move to each event ---
    es_map = load_es_45()
    es_start = min(es_map) if es_map else None
    n_es = 0
    for e in rows:
        v = es_map.get(e["date"])
        if v is None and e.get("live"):
            v = fetch_yahoo_es_45(e["date"])   # recent rows past the ES file's end
        e["es45"] = None if v is None else round(float(v), 3)
        if e["es45"] is not None:
            n_es += 1

    payload = {
        "meta": {
            "ticker": "SPX",
            "source": src,
            "date_start": ts.min().strftime("%Y-%m-%d"),
            "date_end": ts.max().strftime("%Y-%m-%d"),
            "live_through": live_end,
            "threshold_pct": THRESH,
            "n_events": len(rows),
            "n_live": n_live,
            "n_prev": N_PREV,
            "n_fwd": N_FWD,
            "default_dow": 4,   # page defaults the day-of-week filter to Friday
            "by_dow": {k: int(sum(1 for r in rows if r["dow_idx"] == k)) for k in range(5)},
            "return_basis": "close-to-close",
            "es_source": "FirstRateData ES 1-min continuous (ratio-adjusted), 4:00pm->5:00pm ET; live row via Yahoo ES=F",
            "es_start": es_start,
            "n_es": n_es,
        },
        # newest first — most relevant on top
        "events": sorted(rows, key=lambda r: r["date"], reverse=True),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    nm = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    bd = payload["meta"]["by_dow"]
    print(f"{len(rows)} SPX −2%+ days  ({payload['meta']['date_start']} -> {payload['meta']['date_end']})")
    print("  by weekday: " + "  ".join(f"{nm[k]} {bd[k]}" for k in range(5)))
    print(f"Wrote {OUT_JSON}")
    # quick console peek at the most recent 3
    for r in payload["events"][:3]:
        fwd_daily = " ".join(f"{c['daily']:+.1f}" if c["daily"] is not None else "  ·" for c in r["fwd"])
        print(f"  {r['date']} {r['dow']} ({r['fri_ret']:+.1f}%) | fwd daily: {fwd_daily}")


if __name__ == "__main__":
    main()

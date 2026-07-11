"""
Focused tests for the Bilbo scanner Telegram alert quality gate.

Run:  python3 -m pytest test_bilbo_scanner_alerts.py -q
  or: python3 test_bilbo_scanner_alerts.py          (no pytest needed)

BILBO_SCANNER_PATH env var points the tests at a staged copy of the
scanner before it is swapped over the live file.
"""

import os
import importlib.util
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

MOD_PATH = os.environ.get(
    "BILBO_SCANNER_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bilbo_scanner.py"))
spec = importlib.util.spec_from_file_location("bilbo_scanner_under_test", MOD_PATH)
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

ET = ZoneInfo("America/New_York")


def make_df(bars):
    """bars: list of (compression, open, high, low, close)."""
    idx = pd.date_range("2026-07-06 09:00", periods=len(bars), freq="h", tz=ET)
    return pd.DataFrame(
        {"compression": [b[0] for b in bars], "open": [b[1] for b in bars],
         "high": [b[2] for b in bars], "low": [b[3] for b in bars],
         "close": [b[4] for b in bars]}, index=idx)


def breakout_row(df, st, now, **extra):
    """Minimal row the way scan_ticker builds it for a breakout."""
    row = {"sym": "TEST", "status": st["status"], "lock_ts": "LOCK",
           "break_dir": st.get("break_dir"), "break_session": "rth",
           "box_width_atr": 1.0}
    row.update(bs.breakout_quality_fields(df, st, now=now))
    row.update(extra)
    bs.annotate_alert_quality([row])
    return row


# ── 1. wick-only / in-compression break: raw status fires, Telegram blocked ──

def test_wick_only_in_compression_break_detected_but_blocked():
    # 2 lead-in bars, then a 6-bar squeeze: box locks at 5 bars while
    # compression continues; bar 7 (still comp=1, still forming) wicks
    # above the box high but closes back inside.
    bars = [(0, 100, 100.5, 99.5, 100)] * 2 + \
           [(1, 100, 101, 99, 100)] * 5 + \
           [(1, 100.5, 101.8, 99.5, 100.5)]
    df = make_df(bars)
    st = bs.current_box_state(df)
    assert st["status"] == "breakout" and st["break_dir"] == "up"  # raw semantics intact
    assert st["break_bar"] == 7

    now = df.index[7] + pd.Timedelta(minutes=30)  # break bar still forming
    row = breakout_row(df, st, now)
    assert row["break_bar_closed"] is False
    assert row["break_expansion_confirmed"] is False
    assert row["break_close_confirmed"] is False
    assert row["alert_quality"] == "blocked"
    assert set(row["alert_blockers"]) == {
        "break_bar_still_forming", "break_bar_in_compression",
        "no_close_outside_box"}

    # No Telegram alert, but the raw sighting is still reported once.
    state = {}
    new_raw, new_alerts = bs.detect_new_breakouts([row], state)
    assert [r["sym"] for r in new_raw] == ["TEST"]
    assert new_alerts == []

    # Hour rolls over: bar is now closed, but wick-only stays blocked.
    row2 = breakout_row(df, st, df.index[7] + pd.Timedelta(hours=2))
    assert row2["break_bar_closed"] is True
    assert "no_close_outside_box" in row2["alert_blockers"]


# ── 2. closed, expansion, close-outside break passes the gate ──

def test_closed_expansion_close_outside_break_passes():
    # 3-bar squeeze ends early, bar 5 is the first expansion bar and
    # closes above the box high; bar 6 exists so the break bar is closed.
    bars = [(0, 100, 100.5, 99.5, 100)] * 2 + \
           [(1, 100, 101, 99, 100)] * 3 + \
           [(0, 100.8, 101.6, 100.4, 101.4)] + \
           [(0, 101.4, 102, 101.2, 101.8)]
    df = make_df(bars)
    st = bs.current_box_state(df)
    assert st["status"] == "breakout" and st["break_dir"] == "up"
    assert st["break_bar"] == 5

    row = breakout_row(df, st, df.index[-1] + pd.Timedelta(minutes=5))
    assert row["break_bar_closed"] is True
    assert row["break_expansion_confirmed"] is True
    assert row["break_close_confirmed"] is True
    assert row["alert_quality"] == "pass" and row["alert_blockers"] == []

    state = {}
    new_raw, new_alerts = bs.detect_new_breakouts([row], state)
    assert [r["sym"] for r in new_alerts] == ["TEST"]

    # Width cap: same break on a too-wide box is blocked.
    wide = breakout_row(df, st, df.index[-1] + pd.Timedelta(minutes=5),
                        box_width_atr=bs.MAX_ALERT_BOX_WIDTH_ATR + 0.1)
    assert wide["alert_blockers"] == ["box_too_wide"]
    # Session gate still applies on top of quality.
    eth = breakout_row(df, st, df.index[-1] + pd.Timedelta(minutes=5),
                       break_session="afterhours")
    assert "session_not_rth" in eth["alert_blockers"]


# ── 3. near-break suppression ──

def near_row(**kw):
    row = {"sym": kw.pop("sym", "TEST"), "status": "locked", "lock_ts": "LOCK",
           "in_compression": False, "box_width_atr": 2.0,
           "near_break": "up", "near_dist_atr": 0.10}
    row.update(kw)
    bs.annotate_alert_quality([row])
    return row


def test_near_break_suppression():
    rth_now = datetime(2026, 7, 8, 11, 0, tzinfo=ET)  # Wed, RTH

    still_comp = near_row(in_compression=True)
    too_wide = near_row(box_width_atr=bs.MAX_ALERT_BOX_WIDTH_ATR + 0.5)
    too_far = near_row(near_dist_atr=bs.ALERT_PROXIMITY_ATR + 0.05)
    good = near_row(sym="GOOD")

    assert still_comp["alert_blockers"] == ["still_in_compression"]
    assert too_wide["alert_blockers"] == ["box_too_wide"]
    assert too_far["alert_blockers"] == ["outside_alert_proximity"]
    assert good["alert_quality"] == "pass"

    state = {}
    new = bs.detect_new_pre_breakouts(
        [still_comp, too_wide, too_far, good], state, now=rth_now)
    assert [r["sym"] for r in new] == ["GOOD"]
    # Blocked rows must NOT consume their dedup key…
    assert all("|pre" not in k or k.startswith("GOOD") for k in state)
    # …so once compression ends the same box can still pre-alert.
    still_comp2 = near_row(in_compression=False)
    assert bs.detect_new_pre_breakouts([still_comp2], state, now=rth_now)[0]["sym"] == "TEST"
    # Outside RTH nothing fires.
    assert bs.detect_new_pre_breakouts(
        [near_row(sym="AH")], state,
        now=datetime(2026, 7, 8, 17, 0, tzinfo=ET)) == []


# ── 4. dedup state ──

def test_breakout_dedup_blocked_then_pass_alerts_once():
    blocked = {"sym": "TEST", "status": "breakout", "lock_ts": "LOCK",
               "break_dir": "up", "alert_quality": "blocked"}
    state = {}
    new_raw, new_alerts = bs.detect_new_breakouts([blocked], state)
    assert len(new_raw) == 1 and new_alerts == []

    # Next scan: same break now confirms — alerts exactly once, raw not re-logged.
    passed = dict(blocked, alert_quality="pass")
    new_raw, new_alerts = bs.detect_new_breakouts([passed], state)
    assert new_raw == [] and len(new_alerts) == 1
    new_raw, new_alerts = bs.detect_new_breakouts([passed], state)
    assert new_raw == [] and new_alerts == []

    # Migration seeding: a pre-gate '|alerted' key suppresses re-alerting.
    seeded = {"OLD|L|up": "2026-07-08T14:00:00+00:00",
              "OLD|L|up|alerted": "2026-07-08T14:00:00+00:00"}
    old = {"sym": "OLD", "status": "breakout", "lock_ts": "L",
           "break_dir": "up", "alert_quality": "pass"}
    assert bs.detect_new_breakouts([old], seeded) == ([], [])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} tests passed")

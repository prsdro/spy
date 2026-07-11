import pandas as pd

import bilbo_scanner as bs


def _df(comp, highs, lows, closes):
    idx = pd.date_range(
        "2026-07-08 10:00",
        periods=len(comp),
        freq="1h",
        tz=bs.ET,
    )
    return pd.DataFrame(
        {
            "compression": comp,
            "high": highs,
            "low": lows,
            "close": closes,
        },
        index=idx,
    )


def _row_from_state(df, st, **overrides):
    bb = st["break_bar"]
    row = {
        "sym": "TEST",
        "status": st["status"],
        "break_dir": st["break_dir"],
        "break_session": bs.bar_session(df.index[bb]),
        "box_width_atr": 1.0,
    }
    row.update(bs.breakout_quality_fields(df, st, now=overrides.pop("now", None)))
    row.update(overrides)
    return row


def test_second_bar_still_in_compression_keeps_box_forming_not_breakout():
    df = _df(
        comp=[1, 1],
        highs=[100, 101],  # would exceed the first bar, but still part of the box
        lows=[99, 99.2],
        closes=[99.5, 100.0],
    )
    st = bs.current_box_state(df)
    assert st["status"] == "forming"
    assert st["box_bars"] == 2


def test_intrabar_expansion_wick_break_passes_without_close_confirmation():
    df = _df(
        comp=[1, 0],
        highs=[100, 101],
        lows=[99, 99.2],
        closes=[99.5, 100.0],  # wick above box, close not outside
    )
    st = bs.current_box_state(df)
    assert st["status"] == "breakout"
    row = _row_from_state(df, st, now=df.index[-1] + pd.Timedelta(minutes=30))
    assert row["break_bar_closed"] is False
    assert row["break_expansion_confirmed"] is True
    assert row["break_close_confirmed"] is False
    assert bs.breakout_alert_gate(row) == []


def test_closed_expansion_close_outside_break_passes_alert_gate():
    df = _df(
        comp=[1, 0, 0],
        highs=[100, 101, 101.5],
        lows=[99, 99.2, 100.5],
        closes=[99.5, 100.8, 101.2],
    )
    st = bs.current_box_state(df)
    assert st["status"] == "breakout"
    row = _row_from_state(df, st)
    assert row["break_bar_closed"] is True
    assert row["break_expansion_confirmed"] is True
    assert row["break_close_confirmed"] is True
    assert bs.breakout_alert_gate(row) == []


def test_break_while_compression_continues_after_five_bar_cap_is_blocked():
    df = _df(
        comp=[1, 1, 1, 1, 1, 1, 0],
        highs=[100, 100.2, 100.1, 100.3, 100.25, 101, 101.1],
        lows=[99, 99.1, 99.0, 99.2, 99.15, 99.4, 100.4],
        closes=[99.5, 99.6, 99.7, 99.8, 99.9, 100.8, 100.9],
    )
    st = bs.current_box_state(df)
    assert st["status"] == "breakout"
    assert st["break_bar"] == 5
    row = _row_from_state(df, st)
    blockers = bs.breakout_alert_gate(row)
    assert "break_bar_in_compression" in blockers


def test_near_break_gate_blocks_still_compressing_or_wide_boxes_and_passes_tight_expansion():
    still_comp = {
        "status": "locked",
        "in_compression": True,
        "box_width_atr": 2.0,
        "near_dist_atr": 0.10,
    }
    wide = {
        "status": "locked",
        "in_compression": False,
        "box_width_atr": bs.MAX_ALERT_BOX_WIDTH_ATR + 0.1,
        "near_dist_atr": 0.10,
    }
    loose = {
        "status": "locked",
        "in_compression": False,
        "box_width_atr": 2.0,
        "near_dist_atr": bs.ALERT_PROXIMITY_ATR + 0.01,
    }
    good = {
        "status": "locked",
        "in_compression": False,
        "box_width_atr": 2.0,
        "near_dist_atr": 0.10,
    }
    assert "still_in_compression" in bs.near_break_alert_gate(still_comp)
    assert "box_too_wide" in bs.near_break_alert_gate(wide)
    assert "outside_alert_proximity" in bs.near_break_alert_gate(loose)
    assert bs.near_break_alert_gate(good) == []


def test_alert_dedup_allows_blocked_raw_break_to_alert_later_after_quality_passes():
    state = {}
    blocked = {
        "sym": "TEST",
        "status": "breakout",
        "lock_ts": "2026-07-08T10:00:00-04:00",
        "break_dir": "up",
        "alert_quality": "blocked",
    }
    raw, alerts = bs.detect_new_breakouts([blocked], state)
    assert [r["sym"] for r in raw] == ["TEST"]
    assert alerts == []

    passed = dict(blocked, alert_quality="pass")
    raw, alerts = bs.detect_new_breakouts([passed], state)
    assert raw == []
    assert [r["sym"] for r in alerts] == ["TEST"]

    raw, alerts = bs.detect_new_breakouts([passed], state)
    assert raw == []
    assert alerts == []

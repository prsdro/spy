import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_module():
    spec = importlib.util.spec_from_file_location("backtest_atr_cascade", ROOT / "backtest_atr_cascade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def empty_df(mod):
    return mod.pd.DataFrame(columns=[
        "level", "hour_bucket", "n", "p_beyond", "p_behind", "p_last", "p_ambig",
        "avg_min_to_beyond", "med_min_to_beyond", "avg_min_to_behind", "med_min_to_behind"
    ])


def synthetic_gg_group(mod, rows):
    """Build a tiny OHLC group with stable ATR ladder prices for GG tests.

    Rows may be (high, low) or (open, high, low). Older GG tests omit opens so
    first-hit behavior stays focused on intraday touches; gap-open tests include
    opens explicitly.
    """
    base = 100.0
    atr = 10.0
    data = []
    idx = []
    for i, values in enumerate(rows):
        if len(values) == 2:
            high, low = values
            row = {"high": high, "low": low, "date": "2026-01-02"}
        elif len(values) == 3:
            open_, high, low = values
            row = {"open": open_, "high": high, "low": low, "date": "2026-01-02"}
        else:
            raise ValueError(values)
        for label, col, mult in mod.LADDER:
            row[col] = base + atr * mult
        data.append(row)
        idx.append(mod.pd.Timestamp("2026-01-02 09:30") + mod.pd.Timedelta(minutes=3*i))
    return mod.pd.DataFrame(data, index=idx)


def test_hidden_outer_rungs_exist_for_measurement_but_not_report():
    mod = load_module()
    assert mod.LABELS[0] == "-2.236"
    assert mod.LABELS[-1] == "+2.236"
    assert "-2.236" not in mod.REPORT_LABELS
    assert "+2.236" not in mod.REPORT_LABELS
    assert "-2.00" in mod.REPORT_LABELS
    assert "+2.00" in mod.REPORT_LABELS


def test_public_ladder_excludes_hidden_outer_rungs():
    mod = load_module()
    payload = mod.build_json_payload([], [], empty_df(mod), 0)
    assert "-2.236" not in payload["metadata"]["ladder"]
    assert "+2.236" not in payload["metadata"]["ladder"]
    assert payload["metadata"]["measurement_ladder"][0] == "-2.236"
    assert payload["metadata"]["measurement_ladder"][-1] == "+2.236"


def test_public_metadata_includes_canonical_atr_level_names():
    mod = load_module()
    payload = mod.build_json_payload([], [], empty_df(mod), 0)
    names = payload["metadata"]["level_names"]
    assert names["+0.236"] == "Call Trigger"
    assert names["-0.236"] == "Put Trigger"
    assert names["+0.382"] == "Call GG Open"
    assert names["+0.618"] == "Call GG Closed"
    assert names["+1.382"] == "Momo Call GG Open"
    assert "+2.236" not in names
    assert "-2.236" not in names


def test_json_payload_includes_gg_retrace_rows():
    mod = load_module()
    payload = mod.build_json_payload(
        [], [], empty_df(mod), 0,
        gg_retrace=[{"direction": "call", "bucket": "retraced_to_trigger_first", "n": 1}],
    )
    assert payload["gg_retrace"]
    assert payload["gg_retrace"][0]["bucket"] == "retraced_to_trigger_first"


def test_gg_stays_open_after_same_bar_trigger_retest_until_later_completion():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (103.9, 102.2),  # +0.382 GG opens and retests +0.236 trigger, but does not hit +0.618
        (104.5, 103.0),
        (106.4, 104.0),  # GG completes later; open remains valid all day
    ])
    case = mod.analyse_gg_retrace_case(group, "call")
    assert case["bucket"] == "retraced_to_trigger_first"
    assert case["completed"] is True
    assert case["minutes_to_completion"] == 6.0


def test_gg_same_open_bar_completion_without_trigger_retest_is_direct_completion():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (106.4, 102.8),  # +0.382 opens and +0.618 completes, but low stays above +0.236 trigger
    ])
    case = mod.analyse_gg_retrace_case(group, "call")
    assert case["bucket"] == "completed_before_trigger_retrace"
    assert case["completed"] is True
    assert case["minutes_to_completion"] == 0.0


def test_call_gap_open_with_gg_open_but_not_completed_counts_as_gg_case():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (104.0, 105.0, 102.2),  # opens above +0.382 GG open but below +0.618 completion, retests trigger
        (105.2, 106.4, 104.2),  # completes later
    ])
    case = mod.analyse_gg_retrace_case(group, "call")
    assert case["bucket"] == "retraced_to_trigger_first"
    assert case["completed"] is True
    assert case["minutes_to_completion"] == 3.0


def test_put_gap_open_with_gg_open_but_not_completed_counts_as_gg_case():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (96.0, 97.8, 95.0),  # opens below -0.382 GG open but above -0.618 completion, retests trigger
        (94.8, 95.8, 93.6),  # completes later
    ])
    case = mod.analyse_gg_retrace_case(group, "put")
    assert case["bucket"] == "retraced_to_trigger_first"
    assert case["completed"] is True
    assert case["minutes_to_completion"] == 3.0


def test_cheatsheet_plus_minus_2_rows_use_hidden_sentinel_beyond_values():
    html = (ROOT / "site" / "cheatsheet-atr-cascade.html").read_text()
    assert '<tr><td>+2.00</td><td>38</td><td class="bull">26%</td><td class="blue">55%</td><td class="bear">13%</td><td>—</td></tr>' in html
    assert '<tr><td>-2.00</td><td>123</td><td class="bull">32%</td><td class="blue">61%</td><td>5%</td><td>9m</td></tr>' in html


def test_json_payload_includes_adjacent_walks_for_path_explorer():
    mod = load_module()
    payload = mod.build_json_payload(
        [], [], empty_df(mod), 0,
        adjacent_walks=[[mod.REPORT_LABELS.index("PDC"), mod.REPORT_LABELS.index("+0.236"), mod.REPORT_LABELS.index("PDC")]],
    )
    assert payload["adjacent_walks"]
    assert payload["metadata"]["n_adjacent_walks"] == 1



def test_opening_gap_above_level_does_not_count_lower_rungs_as_reached():
    mod = load_module()
    base = 100.0
    atr = 10.0
    rows = []
    idx = []
    for i, (open_, high, low, close) in enumerate([
        (104.0, 104.9, 103.9, 104.6),  # opens above +0.236 and +0.382, then reaches +0.50
        (104.6, 105.2, 104.0, 105.0),
    ]):
        row = {"open": open_, "high": high, "low": low, "close": close, "date": "2026-01-02"}
        for label, col, mult in mod.LADDER:
            row[col] = base + atr * mult
        rows.append(row)
        idx.append(mod.pd.Timestamp("2026-01-02 09:30") + mod.pd.Timedelta(minutes=3*i))
    group = mod.pd.DataFrame(rows, index=idx)

    events, sequence = mod.analyse_day(group)
    levels = {e["level"] for e in events}
    sequence_labels = [mod.LABELS[i] for i in sequence]

    assert "+0.236" not in levels
    assert "+0.382" not in levels
    assert "+0.50" in levels
    assert "+0.236" not in sequence_labels
    assert "+0.382" not in sequence_labels
    assert "+0.50" in sequence_labels


def test_opening_gap_below_level_does_not_count_upper_negative_rungs_as_reached():
    mod = load_module()
    base = 100.0
    atr = 10.0
    rows = []
    idx = []
    for i, (open_, high, low, close) in enumerate([
        (96.0, 96.1, 95.1, 95.4),  # opens below -0.236 and -0.382, then reaches -0.50
        (95.4, 96.0, 94.8, 95.0),
    ]):
        row = {"open": open_, "high": high, "low": low, "close": close, "date": "2026-01-02"}
        for label, col, mult in mod.LADDER:
            row[col] = base + atr * mult
        rows.append(row)
        idx.append(mod.pd.Timestamp("2026-01-02 09:30") + mod.pd.Timedelta(minutes=3*i))
    group = mod.pd.DataFrame(rows, index=idx)

    events, sequence = mod.analyse_day(group)
    levels = {e["level"] for e in events}
    sequence_labels = [mod.LABELS[i] for i in sequence]

    assert "-0.236" not in levels
    assert "-0.382" not in levels
    assert "-0.50" in levels
    assert "-0.236" not in sequence_labels
    assert "-0.382" not in sequence_labels
    assert "-0.50" in sequence_labels


def test_adjacent_walk_starts_at_pdc_when_open_bar_touches_multiple_levels():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (103.9, 96.0),  # Same opening bar spans PDC and nearby trigger levels.
        (104.0, 99.0),
    ])
    walk = mod.analyse_adjacent_walk(group)
    assert walk[0] == mod.REPORT_LABELS.index("PDC")


def test_adjacent_walk_stops_instead_of_tiebreaking_same_bar_adjacent_cross():
    mod = load_module()
    group = synthetic_gg_group(mod, [
        (100.2, 99.8),  # PDC only
        (104.0, 96.0),  # both +0.236 and -0.236 crossed in same 3-min bar
        (106.5, 94.0),
    ])
    walk = mod.analyse_adjacent_walk(group)
    assert walk == [mod.REPORT_LABELS.index("PDC")]

def test_atr_cascade_table_marks_negative_atr_rows_red():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "atr-negative" in html
    assert "lvl.startsWith('-')" in html


def test_atr_cascade_table_renders_level_name_column():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "<th>Level</th><th>Name</th>" in html
    assert "levelName(lvl)" in html
    assert "metadata.level_names" in html


def test_histogram_is_labeled_side_by_side_not_stacked():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "hist-bin" in html
    assert "hist-frame" in html
    assert "hist-y-axis" in html
    assert "hist-scale-note" in html
    assert "hist-values" in html
    assert "bucket probability, % of full cohort" in html
    assert "minutes to next adjacent level" in html
    assert "Bucket mode and cumulative mode must use the same denominator: the full cohort" in html
    assert "of cohort" in html
    assert "of each outcome group" not in html
    assert "Avoid native selector escaping" in html
    assert "if (c.dataset.key === CURRENT_KEY) c.classList.add('selected')" in html
    assert "CSS.escape" not in html
    assert "bar beyond" in html
    assert "bar behind" in html


def test_time_to_next_has_bucket_and_cumulative_modes():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "HIST_MODE = 'bucket'" in html
    assert "function setHistMode(mode)" in html
    assert "function renderCumulativeChart" in html
    assert "<polyline class=\"cum-line beyond\"" in html
    assert "<polyline class=\"cum-line behind\"" in html
    assert "conditional cumulative from ${Math.round(cutoff)} min" in html
    assert "function setHistCutoff(value)" in html
    assert "HIST_CUTOFF_MIN = 0" in html
    assert "type=\"range\" min=\"0\" max=\"${sliderMax}\" step=\"3\"" in html
    assert "function minuteTicks(maxMinute, step = 3)" in html
    assert "function renderMinuteAxis(ticks, maxMinute, cls, includeFinal = false)" in html
    assert "y-axis 0-${yMax}% · final G ${Math.round(finalBeyond)}% / B ${Math.round(finalBehind)}%" in html
    assert "linePoints(beyondCum, yMax)" in html
    assert "linePoints(behindCum, yMax)" in html
    assert "const yMax = Math.min(100, Math.max(10" in html
    assert "cum-slider-range" in html
    assert "--slider-pct:${sliderPct.toFixed(3)}%" in html
    assert "minutes forward after selected condition point" in html
    assert "cum-slider-track" in html
    assert "cum-slider-ticks" in html
    assert "both lines restart from x=0 / y=0" in html
    assert "one final endpoint showing the full remaining-session cumulative probability" in html
    assert "countBeforeMinute" in html
    assert "countBetweenMinutes" in html
    assert "renderCumulativeChart(labels, beyondCounts, behindCounts, c.n)" in html
    assert "@media(max-width:760px){.cum-chart{height:284px}.cum-frame .hist-y-axis{height:284px}}" in html
    assert "vector-effect:non-scaling-stroke" in html
    assert "margin:.35rem 0 0;font-family" in html
    assert "${pointDots(beyondCum" not in html
    assert "cum-dot" not in html
    assert "onclick=\"setHistMode('cumulative')\"" in html
    assert "onclick=\"setHistMode('bucket')\"" in html
    assert "DATA.adjacent_walks || DATA.paths || []" in html
    assert "const current = path[path.length - 1]" in html
    assert "next === current + 1" in html
    assert "next === current - 1" in html
    assert "adjacent-level walk, including revisits" in html



def test_page_derives_headline_counts_from_json_and_links_static_chart():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "function updateHeadlineStats()" in html
    assert "m.outcome_summary" in html
    assert 'data-stat="days"' in html
    assert 'data-stat="events"' in html
    assert 'data-stat="median-next"' in html
    assert "atr-levels-probabilities-spy.html" in html
    assert "Hidden ±2.236 sentinel rungs" in html
    assert "Static Saty chart" in html or "static Saty-style chart" in html
    assert "/ 6,582" not in html


def test_nav_waits_for_body_before_injecting():
    nav = (ROOT / "site" / "nav.js").read_text()
    assert "document.addEventListener('DOMContentLoaded', injectNav" in nav
    assert "function injectNav()" in nav

def test_heatmap_uses_high_contrast_directional_colors():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "function heatmapHue(metric, level)" in html
    assert "level.startsWith('-')) return 0" in html
    assert "function heatmapIntensity(p)" in html
    assert "<40% very dark, 40-60% muted, >60% bright, >70% super bright" in html
    assert "if (x < 0.40)" in html
    assert "if (x < 0.60)" in html
    assert "if (x < 0.70)" in html
    assert "return 0.86 + ((x - 0.70) / 0.30) * 0.14" in html
    assert "colorFor(CURRENT_METRIC, v, lvl)" in html
    assert "cell.style.color = '#ffffff'" in html
    assert "upper hue / lower red" in html


def test_gg_retrace_panel_exists():
    html = (ROOT / "site" / "atr-cascade.html").read_text()
    assert "gg-retrace-panel" in html
    assert "renderGGRetrace" in html
    assert "retraced_to_trigger_first" in html
    assert "Overall GG completion rate" in html
    assert "Completion rate if trigger is retested before GG completion" in html
    assert "Direct GG completion before trigger retest" in html
    assert "This does <strong>not</strong> measure smaller pullbacks like 50% back to 38.2% GG Open" in html
    assert "Retrace-cohort completion vs direct path" not in html

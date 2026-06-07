#!/usr/bin/env python3
"""Build a dynamic Saty-style ATR probability ladder for SPX.

The chart uses same-day range-inclusion semantics: if an ATR level sits inside the
RTH high-low range, including gap-open-passed levels, that level counts as hit.
The embedded JavaScript listens for parent-page year-filter messages and shows
red percentage-point deltas versus the all-years baseline.
"""
import html
import json
from pathlib import Path

from backtest_atr_cascade import LADDER, PDC_IDX
from backtest_atr_cascade_spx_firstrate import load_spx, load_vix_daily

BASE = Path(__file__).resolve().parent
DATA = json.loads((BASE / 'site/data/atr-cascade-spx.json').read_text())
OUT = BASE / 'site/atr-levels-probabilities-spx.html'
ASSET_DIR = BASE / 'site/assets'
ASSET_DIR.mkdir(exist_ok=True)

ladder = DATA['metadata']['ladder']
idx = {lab: i for i, lab in enumerate(ladder)}
_COL_BY_LABEL = {label: col for label, col, _ in LADDER}
_DIRECTION_BY_LABEL = {label: (1 if i > PDC_IDX else -1 if i < PDC_IDX else 0) for i, (label, _, _) in enumerate(LADDER)}


def build_range_inclusion_records():
    df, diag = load_spx()
    vix_by_date, _vix_diag = load_vix_daily(start=diag['daily_first'])
    records = []
    for date, group in df.groupby('date', sort=True):
        row0 = group.iloc[0]
        highs = group['high'].values
        lows = group['low'].values
        seq = []
        for lab in ladder:
            L = row0[_COL_BY_LABEL[lab]]
            direction = _DIRECTION_BY_LABEL[lab]
            if direction == 0:
                m = (lows <= L) & (highs >= L)
            elif direction > 0:
                m = highs >= L
            else:
                m = lows <= L
            if m.any():
                seq.append((int(m.argmax()), idx[lab]))
        if seq:
            date_s = str(date)
            vix_close = vix_by_date.get(date_s)
            records.append({'y': int(date_s[:4]), 'v': None if vix_close is None else round(float(vix_close), 2), 'hits': [i for _, i in sorted(seq)]})
    return records, int(df['date'].nunique())


records, N_DAYS = build_range_inclusion_records()
paths = [r['hits'] for r in records]
N_PATH_DAYS = len(paths)

def hit_count(level, paths_=None):
    paths_ = paths if paths_ is None else paths_
    i = idx[level]
    return sum(1 for path in paths_ if i in path)


def conditional_pct(start, target, paths_=None):
    paths_ = paths if paths_ is None else paths_
    si = idx[start]; ti = idx[target]
    den = sum(1 for path in paths_ if si in path)
    num = sum(1 for path in paths_ if si in path and ti in path)
    return num, den, 100 * num / den if den else 0.0


def target_pct(target, paths_=None):
    paths_ = paths if paths_ is None else paths_
    h = hit_count(target, paths_)
    return h, len(paths_), 100 * h / len(paths_) if paths_ else 0.0


def fmt_pct(x):
    if x < 1:
        return f"{x:.1f}%"
    return f"{x:.0f}%"


def fmt_frac(num, den):
    return f"{num:,}/{den:,}"

# Coordinates: 1280x720 chart, matching the supplied 16:9 reference.
W, H = 1280, 720
left_x = 245
right_x = 930
plot_top = 64
plot_bottom = 700
scale = (plot_bottom - plot_top) / 4.0  # -2 ATR to +2 ATR


def y(val):
    return plot_bottom - (val + 2.0) * scale


levels = [
    (2.0, '200% +2 ATR', True),
    (1.786, '178.6%', False),
    (1.618, '161.8%', False),
    (1.5, '150%', False),
    (1.382, '138.2%', False),
    (1.236, '123.6%', False),
    (1.0, '100% +1 ATR', True),
    (0.786, '78.6%', False),
    (0.618, '61.8% Midrange', False),
    (0.5, '50%', False),
    (0.382, '38.2% Golden Gate', False),
    (0.236, '23.6% Call Trigger', False),
    (0.0, '0 Previous Close', True),
    (-0.236, '-23.6% Put Trigger', False),
    (-0.382, '-38.2% Golden Gate', False),
    (-0.5, '-50%', False),
    (-0.618, '-61.8% Midrange', False),
    (-0.786, '-78.6%', False),
    (-1.0, '-100% -1 ATR', True),
    (-1.236, '-123.6%', False),
    (-1.382, '-138.2%', False),
    (-1.5, '-150%', False),
    (-1.618, '-161.8%', False),
    (-1.786, '-178.6%', False),
    (-2.0, '-200% -2 ATR', True),
]

value_to_label = {
    0.236: '+0.236', 0.382: '+0.382', 0.5: '+0.50', 0.618: '+0.618', 0.786: '+0.786', 1.0: '+1.00',
    1.236: '+1.236', 1.382: '+1.382', 1.5: '+1.50', 1.618: '+1.618', 1.786: '+1.786', 2.0: '+2.00',
    -0.236: '-0.236', -0.382: '-0.382', -0.5: '-0.50', -0.618: '-0.618', -0.786: '-0.786', -1.0: '-1.00',
    -1.236: '-1.236', -1.382: '-1.382', -1.5: '-1.50', -1.618: '-1.618', -1.786: '-1.786', -2.0: '-2.00'
}

specs = []
baseline = {}

def safe_key(*parts):
    return '_'.join(str(p).replace('+','p').replace('-','m').replace('.','').replace(' ', '').replace('→','_') for p in parts)


def add_spec(kind, key, **kwargs):
    specs.append({'kind': kind, 'key': key, **kwargs})
    if kind == 'conditional':
        num, den, pct = conditional_pct(kwargs['start'], kwargs['target'])
    else:
        num, den, pct = target_pct(kwargs['target'])
    baseline[key] = {'num': num, 'den': den, 'pct': pct}
    return num, den, pct


def label_for(key, suffix=''):
    pct = baseline[key]['pct']
    return f"{fmt_pct(pct)}{suffix}"


def arrow(x, start_val, end_val, label, color, side='right', small='', label_x=None, label_y=None, label_anchor=None, key=None):
    """Draw a perfectly vertical arrow whose tip lands exactly on end_val's level line."""
    ys, ye = y(start_val), y(end_val)
    midy = (ys + ye) / 2
    text_x = label_x if label_x is not None else (x + 20 if side == 'right' else x - 20)
    text_y = label_y if label_y is not None else (midy + 4)
    anchor = label_anchor or ('start' if side == 'right' else 'end')
    extra = f'<title>{html.escape(small)}</title>' if small else ''
    head = 7.0
    half = 4.2
    if ye < ys:  # upward arrow: tip at ye, base below it
        shaft_end = ye + head
        head_path = f'M {x:.1f} {ye:.1f} L {x-half:.1f} {ye+head:.1f} L {x+half:.1f} {ye+head:.1f} Z'
    else:        # downward arrow: tip at ye, base above it
        shaft_end = ye - head
        head_path = f'M {x:.1f} {ye:.1f} L {x-half:.1f} {ye-head:.1f} L {x+half:.1f} {ye-head:.1f} Z'
    label_id = f' id="label-{key}"' if key else ''
    delta = f'<text x="{text_x}" y="{text_y:.1f}" text-anchor="start" class="delta-label" id="delta-{key}"></text>' if key else ''
    return f'''
    <g class="prob-arrow"{f' data-key="{key}"' if key else ''}>
      {extra}
      <line x1="{x:.1f}" y1="{ys:.1f}" x2="{x:.1f}" y2="{shaft_end:.1f}" stroke="{color}" stroke-width="1.45" opacity=".92" shape-rendering="geometricPrecision" />
      <path d="{head_path}" fill="{color}" opacity=".96" />
      <text x="{text_x}" y="{text_y:.1f}" text-anchor="{anchor}" class="prob-label"{label_id}>{html.escape(label)}</text>
      {delta}
    </g>'''


def cpair(a_val, b_val):
    a = value_to_label[a_val]
    b = value_to_label[b_val]
    key = safe_key(a, b)
    num, den, pct = add_spec('conditional', key, start=a, target=b, suffix='')
    return key, fmt_pct(pct), fmt_frac(num, den), pct


parts = []
up_pairs = [(0.236,0.382, 276), (0.382,0.5, 322), (0.5,0.618, 370), (0.618,0.786, 418), (0.786,1.0, 470), (1.0,1.236, 524)]
for a,b,x in up_pairs:
    key, pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#75c84a','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%', key=key))

down_pairs = [(-0.236,-0.382, 276), (-0.382,-0.5, 322), (-0.5,-0.618, 370), (-0.618,-0.786, 418), (-0.786,-1.0, 470), (-1.0,-1.236, 524)]
for a,b,x in down_pairs:
    key, pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#c83d36','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%', key=key))

# GG spans and momo spans.
def cond_key(start, target, suffix=''):
    key = safe_key(start, target)
    num, den, pct = add_spec('conditional', key, start=start, target=target, suffix=suffix)
    return key, num, den, pct

call_gg_key, call_gg_num, call_gg_den, call_gg = cond_key('+0.382','+0.618',' (Golden Gate)')
put_gg_key, put_gg_num, put_gg_den, put_gg = cond_key('-0.382','-0.618',' (Golden Gate)')
call_momo_key, call_momo_num, call_momo_den, call_momo = cond_key('+1.382','+1.618',' (Momentum Golden Gate)')
put_momo_key, put_momo_num, put_momo_den, put_momo = cond_key('-1.382','-1.618',' (Momentum Golden Gate)')
parts.append(arrow(592,0.382,0.618,f"{fmt_pct(call_gg)} (Golden Gate)",'#75c84a','right',f'+0.382 to +0.618: {fmt_frac(call_gg_num, call_gg_den)} = {call_gg:.1f}%', key=call_gg_key))
parts.append(arrow(592,-0.382,-0.618,f"{fmt_pct(put_gg)} (Golden Gate)",'#c83d36','right',f'-0.382 to -0.618: {fmt_frac(put_gg_num, put_gg_den)} = {put_gg:.1f}%', key=put_gg_key))
parts.append(arrow(592,1.382,1.618,f"{fmt_pct(call_momo)} (Momentum Golden Gate)",'#75c84a','right',f'+1.382 to +1.618: {fmt_frac(call_momo_num, call_momo_den)} = {call_momo:.1f}%', key=call_momo_key))
parts.append(arrow(592,-1.382,-1.618,f"{fmt_pct(put_momo)} (Momentum Golden Gate)",'#c83d36','right',f'-1.382 to -1.618: {fmt_frac(put_momo_num, put_momo_den)} = {put_momo:.1f}%', key=put_momo_key))

# Right-side major 0-to-target arrows.
major_label_overrides = {
    '+2.00': dict(label_x=946, label_y=76, label_anchor='start'),
    '-2.00': dict(label_x=946, label_y=602, label_anchor='start'),
    '+1.00': dict(label_y=y(1.0) + 14),
    '-1.00': dict(label_y=y(-1.0) - 8),
}
major_label_text = {
    '+1.00': '0 to +1 ATR',
    '-1.00': '0 to -1 ATR',
    '+2.00': '0 to +2 ATR',
    '-2.00': '0 to -2 ATR',
}
for target, x, _txt_y_offset, color in [('+1.00', 782, 0, '#75c84a'), ('-1.00', 782, 0, '#c83d36'), ('+2.00', 930, 0, '#75c84a'), ('-2.00', 930, 0, '#c83d36')]:
    key = safe_key('PDC', target)
    num, den, pct = add_spec('target', key, target=target, suffix=f" ({major_label_text[target]})")
    end_val = float(target.replace('+',''))
    label = f"{fmt_pct(pct)} ({major_label_text[target]})"
    parts.append(arrow(x,0,end_val,label,color,'right',f'PDC to {target}: {fmt_frac(num, den)} = {pct:.1f}%', key=key, **major_label_overrides.get(target, {})))

# Momentum adjacent rung small arrows on the right.
for a,b,x in [(1.236,1.382,525),(-1.236,-1.382,525)]:
    key, pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#75c84a' if a>0 else '#c83d36','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%', key=key))

# SVG grid and labels.
grid = []
for val, label, major in levels:
    yy = y(val)
    stroke = '#8a969d' if major else '#3c454c'
    width = 1.15 if major else .72
    opacity = .58 if major else .56
    grid.append(f'<line x1="{left_x}" y1="{yy:.1f}" x2="{W-28}" y2="{yy:.1f}" stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"/>')
    grid.append(f'<text x="{left_x-10}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{html.escape(label)}</text>')

legend = f'''
<g class="legend">
  <rect x="1010" y="248" width="244" height="230" rx="5" fill="#0d1316" fill-opacity=".94" stroke="#344047" stroke-width=".85"/>
  <text x="1018" y="266" class="legend-title">SPX ATR Levels Probabilities</text>
  <text x="1018" y="284" class="legend-line" id="chart-window">Window: all years</text>
  <text x="1018" y="304" class="legend-line">Dataset: SPX 1m → 3m RTH</text>
  <text x="1018" y="322" class="legend-line">FirstRateData · 2008-01-02 to 2026-05-01</text>
  <text x="1018" y="340" class="legend-line" id="chart-n">N = {N_DAYS:,} trading days</text>
  <text x="1018" y="366" class="legend-line">Red delta under each arrow:</text>
  <text x="1018" y="384" class="legend-line">percentage points vs all-years</text>
  <text x="1018" y="412" class="legend-line">Methodology:</text>
  <text x="1018" y="430" class="legend-line">Range-hit, not sequence-based.</text>
  <text x="1018" y="448" class="legend-line">Counts any level inside RTH range.</text>
  <text x="1018" y="466" class="legend-line">Gap-open-passed levels count.</text>
</g>'''

footer = '''
<text x="940" y="646" class="footer">Overall chart: range-hit probability, not sequence-based GG completion</text>
<text x="940" y="664" class="footer">Filtered by parent page year + VIX controls; gap-open-passed levels count as hits</text>
<a href="https://satyland.com" target="_blank" rel="noopener noreferrer">
  <text x="940" y="684" class="footer credit">ATR level framework: Saty Mahajan · satyland.com</text>
</a>
'''

svg = f'''<svg id="probability-svg" viewBox="0 0 {W} {H}" role="img" aria-label="SPX ATR Levels Probabilities dynamic chart">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#10171a"/><stop offset="1" stop-color="#191f22"/></linearGradient>
  </defs>
  <rect width="1280" height="720" fill="#000"/>
  <text x="{left_x}" y="28" class="chart-title">SPX ATR Levels Probabilities</text>
  <text x="{left_x}" y="50" class="chart-subtitle" id="chart-subtitle">Year range: all years · Same-day range-hit P(target inside RTH | start inside RTH)</text>
  <rect x="{left_x}" y="{plot_top}" width="{W-left_x-28}" height="{plot_bottom-plot_top}" fill="url(#bg)"/>
  {''.join(grid)}
  <line x1="{left_x}" y1="{y(0):.1f}" x2="{W-28}" y2="{y(0):.1f}" stroke="#e4e9ee" stroke-width="1.65" opacity=".95"/>
  <line x1="{left_x}" y1="{y(0.236):.1f}" x2="{W-28}" y2="{y(0.236):.1f}" stroke="#19a6a6" stroke-width="1.0" opacity=".55"/>
  <line x1="{left_x}" y1="{y(-0.236):.1f}" x2="{W-28}" y2="{y(-0.236):.1f}" stroke="#b8a31f" stroke-width="1.0" opacity=".55"/>
  {''.join(parts)}
  {legend}
  {footer}
</svg>'''

js = f'''
<script>
const RANGE_RECORDS = {json.dumps(records, separators=(',', ':'))};
const LADDER = {json.dumps(ladder, separators=(',', ':'))};
const IDX = Object.fromEntries(LADDER.map((x,i)=>[x,i]));
const SPECS = {json.dumps(specs, separators=(',', ':'))};
const BASELINE = {json.dumps(baseline, separators=(',', ':'))};
const DEFAULT_START = {min(r['y'] for r in records)};
const DEFAULT_END = {max(r['y'] for r in records)};
function fmtPct(x) {{ return x < 1 ? x.toFixed(1) + '%' : Math.round(x) + '%'; }}
function fmtDelta(x) {{ const sign = x >= 0 ? '+' : ''; return '(' + sign + x.toFixed(1) + ' pp)'; }}
function deltaColor(x) {{ return x > 0 ? '#48d17f' : (x < 0 ? '#ff514c' : '#a9b4bd'); }}
function positionDelta(label, delta) {{
  if (!label || !delta || !delta.textContent) return;
  try {{
    const box = label.getBBox();
    delta.setAttribute('x', (box.x + box.width + 5).toFixed(1));
    delta.setAttribute('y', label.getAttribute('y'));
    delta.setAttribute('text-anchor', 'start');
  }} catch (e) {{}}
}}
function inVixRange(v, minVix, maxVix) {{
  if (minVix === null && maxVix === null) return true;
  if (v === null || v === undefined || Number.isNaN(Number(v))) return false;
  const x = Number(v);
  return (minVix === null || x >= minVix) && (maxVix === null || x <= maxVix);
}}
function pathsFor(start, end, minVix = null, maxVix = null) {{ return RANGE_RECORDS.filter(r => r.y >= start && r.y <= end && inVixRange(r.v, minVix, maxVix)).map(r => r.hits); }}
function has(path, label) {{ return path.includes(IDX[label]); }}
function calc(spec, paths) {{
  let num = 0, den = 0;
  if (spec.kind === 'conditional') {{
    for (const p of paths) {{ if (has(p, spec.start)) {{ den++; if (has(p, spec.target)) num++; }} }}
  }} else {{
    den = paths.length;
    for (const p of paths) if (has(p, spec.target)) num++;
  }}
  return {{num, den, pct: den ? 100 * num / den : 0}};
}}
function applyFilter(start, end, minVix = null, maxVix = null) {{
  if (start > end) [start, end] = [end, start];
  if (minVix !== null && maxVix !== null && minVix > maxVix) [minVix, maxVix] = [maxVix, minVix];
  const paths = pathsFor(start, end, minVix, maxVix);
  const isAll = start === DEFAULT_START && end === DEFAULT_END && minVix === null && maxVix === null;
  const yearText = start === DEFAULT_START && end === DEFAULT_END ? 'all years' : `${{start}}-${{end}}`;
  const vixText = minVix === null && maxVix === null ? 'all VIX' : `VIX ${{minVix === null ? 'any' : minVix.toFixed(1)}}-${{maxVix === null ? 'any' : maxVix.toFixed(1)}}`;
  const windowText = isAll ? 'all years / all VIX' : `${{yearText}} · ${{vixText}}`;
  document.getElementById('chart-window').textContent = `Window: ${{windowText}}`;
  document.getElementById('chart-subtitle').textContent = `Cohort: ${{windowText}} · Same-day range-hit P(target inside RTH | start inside RTH)`;
  document.getElementById('chart-n').textContent = `N = ${{paths.length.toLocaleString()}} trading days`;
  document.body.dataset.yearRange = windowText.replace(/[^0-9A-Za-z-]+/g, '-');
  for (const spec of SPECS) {{
    const stat = calc(spec, paths);
    const suffix = spec.suffix || '';
    const label = document.getElementById('label-' + spec.key);
    const delta = document.getElementById('delta-' + spec.key);
    if (label) label.textContent = fmtPct(stat.pct) + suffix;
    if (delta) {{
      const d = stat.pct - BASELINE[spec.key].pct;
      delta.textContent = isAll ? '' : fmtDelta(d);
      delta.setAttribute('data-delta', d.toFixed(3));
      delta.style.fill = deltaColor(d);
      positionDelta(label, delta);
    }}
  }}
}}
window.setYearRange = (start, end) => applyFilter(start, end, null, null);
window.setFilter = applyFilter;
window.addEventListener('message', ev => {{
  const msg = ev.data || {{}};
  if (msg.type === 'SPX_FILTER') applyFilter(Number(msg.start), Number(msg.end), msg.vixMin === null || msg.vixMin === undefined ? null : Number(msg.vixMin), msg.vixMax === null || msg.vixMax === undefined ? null : Number(msg.vixMax));
  if (msg.type === 'SPX_YEAR_FILTER') applyFilter(Number(msg.start), Number(msg.end), null, null);
}});
applyFilter(DEFAULT_START, DEFAULT_END, null, null);

async function downloadPng() {{
  const svg = document.getElementById('probability-svg').cloneNode(true);
  const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  style.textContent = `
    .axis-label {{ fill:#f5f7fa; font-size:12px; font-weight:650; letter-spacing:-.01em; font-variant-numeric:tabular-nums; }}
    .prob-label {{ fill:#f7fafc; font-size:12px; font-weight:720; letter-spacing:-.02em; paint-order:stroke; stroke:#121819; stroke-width:3.4px; stroke-linejoin:round; font-variant-numeric:tabular-nums; }}
    .delta-label {{ fill:#ff514c; font-size:9.6px; font-weight:780; letter-spacing:-.02em; paint-order:stroke; stroke:#121819; stroke-width:3.2px; stroke-linejoin:round; font-variant-numeric:tabular-nums; }}
    .legend-title {{ fill:#eef5f7; font-size:12.5px; font-weight:760; letter-spacing:-.01em; }}
    .legend-line {{ fill:#b7c2c8; font-size:10.5px; font-weight:590; font-variant-numeric:tabular-nums; }}
    .footer {{ fill:#aebac0; font-size:9.8px; font-weight:700; text-anchor:start; paint-order:stroke; stroke:#080c0e; stroke-width:.9px; letter-spacing:-.01em; }}
    .credit {{ fill:#cdd7dc; text-decoration:underline; }}
    .chart-title {{ fill:#f7fafc; font-size:24px; font-weight:820; letter-spacing:-.03em; }}
    .chart-subtitle {{ fill:#b7c2c8; font-size:12.5px; font-weight:680; letter-spacing:-.01em; }}
  `;
  svg.insertBefore(style, svg.firstChild);
  const xml = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([xml], {{type: 'image/svg+xml;charset=utf-8'}});
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.decoding = 'async';
  await new Promise((resolve, reject) => {{ img.onload = resolve; img.onerror = reject; img.src = url; }});
  const canvas = document.createElement('canvas');
  canvas.width = 1280; canvas.height = 720;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, 1280, 720);
  URL.revokeObjectURL(url);
  const pngUrl = canvas.toDataURL('image/png');
  const a = document.createElement('a');
  const yr = document.body.dataset.yearRange || 'all-years';
  a.href = pngUrl;
  a.download = `spx-atr-levels-probabilities-${{yr}}.png`;
  document.body.appendChild(a); a.click(); a.remove();
}}
document.getElementById('download-png').addEventListener('click', downloadPng);
</script>
'''

html_doc = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SPX ATR Levels Probabilities</title>
  <style>
    :root {{ color-scheme: dark; }}
    html, body {{ margin:0; background:#050606; color:#f4f7f8; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .wrap {{ min-height:100vh; display:grid; place-items:center; padding:0; box-sizing:border-box; overflow:hidden; }}
    .download-png {{ position:fixed; top:12px; right:14px; z-index:10; appearance:none; border:1px solid rgba(255,255,255,.18); border-radius:999px; background:rgba(9,13,15,.82); color:#f7fafc; font-size:12px; font-weight:760; padding:8px 12px; cursor:pointer; box-shadow:0 10px 30px rgba(0,0,0,.45); backdrop-filter:blur(8px); }}
    .download-png:hover {{ border-color:rgba(255,255,255,.34); background:rgba(23,32,36,.92); }}
    .chart {{ width:min(1280px, 100vw); aspect-ratio:16/9; max-height:100vh; box-shadow:0 20px 70px rgba(0,0,0,.55); }}
    svg {{ display:block; width:100%; height:100%; }}
    .axis-label {{ fill:#f5f7fa; font-size:12px; font-weight:650; letter-spacing:-.01em; font-variant-numeric:tabular-nums; }}
    .prob-label {{ fill:#f7fafc; font-size:12px; font-weight:720; letter-spacing:-.02em; paint-order:stroke; stroke:#121819; stroke-width:3.4px; stroke-linejoin:round; font-variant-numeric:tabular-nums; }}
    .delta-label {{ fill:#ff514c; font-size:9.6px; font-weight:780; letter-spacing:-.02em; paint-order:stroke; stroke:#121819; stroke-width:3.2px; stroke-linejoin:round; font-variant-numeric:tabular-nums; }}
    .legend-title {{ fill:#eef5f7; font-size:12.5px; font-weight:760; letter-spacing:-.01em; }}
    .chart-title {{ fill:#f7fafc; font-size:24px; font-weight:820; letter-spacing:-.03em; }}
    .chart-subtitle {{ fill:#b7c2c8; font-size:12.5px; font-weight:680; letter-spacing:-.01em; }}
    .legend-line {{ fill:#b7c2c8; font-size:10.5px; font-weight:590; font-variant-numeric:tabular-nums; }}
    .footer {{ fill:#aebac0; font-size:9.8px; font-weight:700; text-anchor:start; paint-order:stroke; stroke:#080c0e; stroke-width:.9px; letter-spacing:-.01em; }}
    .credit {{ fill:#cdd7dc; text-decoration:underline; }}
  </style>
</head>
<body>
  <button class="download-png" id="download-png" type="button">Download PNG</button>
  <main class="wrap">
    <div><div class="chart">{svg}</div></div>
  </main>
  {js}
</body>
</html>
'''
OUT.write_text(html_doc)
print(OUT)
print(f'N={N_DAYS:,} trading days; path days={N_PATH_DAYS:,}')
print(f'+0.236→+0.382 {conditional_pct("+0.236","+0.382")[2]:.1f}%')
print(f'-0.236→-0.382 {conditional_pct("-0.236","-0.382")[2]:.1f}%')
print(f'0→+1 ATR {target_pct("+1.00")[2]:.1f}%')
print(f'0→-1 ATR {target_pct("-1.00")[2]:.1f}%')
print(f'0→+2 ATR {target_pct("+2.00")[2]:.1f}%')
print(f'0→-2 ATR {target_pct("-2.00")[2]:.1f}%')

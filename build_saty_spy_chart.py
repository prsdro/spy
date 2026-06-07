#!/usr/bin/env python3
"""Build a static Saty-style ATR probability ladder using measured SPY probabilities."""
import html
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = json.loads((BASE / 'site/data/atr-cascade.json').read_text())
OUT = BASE / 'site/atr-levels-probabilities-spy.html'
ASSET_DIR = BASE / 'site/assets'
ASSET_DIR.mkdir(exist_ok=True)

ladder = DATA['metadata']['ladder']
paths = DATA['paths']
N = len(paths)
idx = {lab: i for i, lab in enumerate(ladder)}

def hit_count(level):
    i = idx[level]
    return sum(1 for path in paths if i in path)

def conditional_pct(start, target):
    si = idx[start]; ti = idx[target]
    den = sum(1 for path in paths if si in path)
    num = sum(1 for path in paths if si in path and ti in path)
    return num, den, 100 * num / den if den else 0.0

def target_pct(target):
    h = hit_count(target)
    return h, N, 100 * h / N

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
plot_top = 18
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
    (0.236, '23.6% Bullish/Long/Call Trigger', False),
    (0.0, '0 Previous Close', True),
    (-0.236, '-23.6% Bearish/Short/Put Trigger', False),
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

def arrow(x, start_val, end_val, label, color, side='right', small=''):
    """Draw a perfectly vertical arrow whose tip lands exactly on end_val's level line."""
    ys, ye = y(start_val), y(end_val)
    midy = (ys + ye) / 2
    text_x = x + 20 if side == 'right' else x - 20
    anchor = 'start' if side == 'right' else 'end'
    extra = f'<title>{html.escape(small)}</title>' if small else ''
    head = 7.0
    half = 4.2
    if ye < ys:  # upward arrow: tip at ye, base below it
        shaft_end = ye + head
        head_path = f'M {x:.1f} {ye:.1f} L {x-half:.1f} {ye+head:.1f} L {x+half:.1f} {ye+head:.1f} Z'
    else:        # downward arrow: tip at ye, base above it
        shaft_end = ye - head
        head_path = f'M {x:.1f} {ye:.1f} L {x-half:.1f} {ye-head:.1f} L {x+half:.1f} {ye-head:.1f} Z'
    return f'''
    <g class="prob-arrow">
      {extra}
      <line x1="{x:.1f}" y1="{ys:.1f}" x2="{x:.1f}" y2="{shaft_end:.1f}" stroke="{color}" stroke-width="1.45" opacity=".92" shape-rendering="geometricPrecision" />
      <path d="{head_path}" fill="{color}" opacity=".96" />
      <text x="{text_x}" y="{midy + 4:.1f}" text-anchor="{anchor}" class="prob-label">{html.escape(label)}</text>
    </g>'''

def cpair(a_val, b_val):
    a = value_to_label[a_val]
    b = value_to_label[b_val]
    num, den, pct = conditional_pct(a, b)
    return fmt_pct(pct), fmt_frac(num, den), pct

# Left staircase arrows, positioned like the reference.
parts = []
up_pairs = [(0.236,0.382, 276), (0.382,0.5, 322), (0.5,0.618, 370), (0.618,0.786, 418), (0.786,1.0, 470), (1.0,1.236, 524)]
for a,b,x in up_pairs:
    pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#75c84a','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%'))

down_pairs = [(-0.236,-0.382, 276), (-0.382,-0.5, 322), (-0.5,-0.618, 370), (-0.618,-0.786, 418), (-0.786,-1.0, 470), (-1.0,-1.236, 524)]
for a,b,x in down_pairs:
    pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#c83d36','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%'))

# GG spans and momo spans.
call_gg_num, call_gg_den, call_gg = conditional_pct('+0.382','+0.618')
put_gg_num, put_gg_den, put_gg = conditional_pct('-0.382','-0.618')
call_momo_num, call_momo_den, call_momo = conditional_pct('+1.382','+1.618')
put_momo_num, put_momo_den, put_momo = conditional_pct('-1.382','-1.618')
parts.append(arrow(592,0.382,0.618,f"{fmt_pct(call_gg)} (Golden Gate Setup)",'#75c84a','right',f'+0.382 to +0.618: {fmt_frac(call_gg_num, call_gg_den)} = {call_gg:.1f}%'))
parts.append(arrow(592,-0.382,-0.618,f"{fmt_pct(put_gg)} (Golden Gate Setup)",'#c83d36','right',f'-0.382 to -0.618: {fmt_frac(put_gg_num, put_gg_den)} = {put_gg:.1f}%'))
parts.append(arrow(592,1.382,1.618,f"{fmt_pct(call_momo)} (Momentum Golden Gate)",'#75c84a','right',f'+1.382 to +1.618: {fmt_frac(call_momo_num, call_momo_den)} = {call_momo:.1f}%'))
parts.append(arrow(592,-1.382,-1.618,f"{fmt_pct(put_momo)} (Momentum Golden Gate)",'#c83d36','right',f'-1.382 to -1.618: {fmt_frac(put_momo_num, put_momo_den)} = {put_momo:.1f}%'))

# Right-side major 0-to-target arrows.
for target, x, txt_y_offset, color in [('+1.00', 782, 0, '#75c84a'), ('-1.00', 782, 0, '#c83d36'), ('+2.00', 930, 0, '#75c84a'), ('-2.00', 930, 0, '#c83d36')]:
    num, den, pct = target_pct(target)
    end_val = float(target.replace('+',''))
    label = f"{fmt_pct(pct)} 0 to {target.replace('.00','')} ATR"
    label = label.replace('+-','-')
    if target == '+1.00': label = f"{fmt_pct(pct)} 0 to +1 ATR"
    if target == '-1.00': label = f"{fmt_pct(pct)} 0 to -1 ATR"
    if target == '+2.00': label = f"{fmt_pct(pct)} 0 to +2 ATR"
    if target == '-2.00': label = f"{fmt_pct(pct)} 0 to -2 ATR"
    label_side = 'left' if target in ('+2.00', '-2.00') else 'right'
    parts.append(arrow(x,0,end_val,label,color,label_side,f'PDC to {target}: {fmt_frac(num, den)} = {pct:.1f}%'))

# Momentum adjacent rung small arrows on the right, subtle.
for a,b,x in [(1.236,1.382,525),(-1.236,-1.382,525)]:
    pct, frac, raw = cpair(a,b)
    parts.append(arrow(x,a,b,pct,'#75c84a' if a>0 else '#c83d36','right',f'{value_to_label[a]} to {value_to_label[b]}: {frac} = {raw:.1f}%'))

# SVG grid and labels.
grid = []
for val, label, major in levels:
    yy = y(val)
    stroke = '#d7dde2' if major else '#4a555d'
    width = 1.35 if major else .8
    opacity = .86 if major else .72
    grid.append(f'<line x1="{left_x}" y1="{yy:.1f}" x2="{W-28}" y2="{yy:.1f}" stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"/>')
    grid.append(f'<text x="{left_x-10}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{html.escape(label)}</text>')

legend = f'''
<g class="legend">
  <rect x="1022" y="276" width="226" height="158" rx="0" fill="#ffffff" stroke="#a3a3a3" stroke-width="1"/>
  <text x="1029" y="294" class="legend-title">SPY ATR Levels Probabilities</text>
  <text x="1029" y="312" class="legend-line">Measured within the same RTH day</text>
  <text x="1029" y="340" class="legend-line">Dataset: SPY 3m RTH</text>
  <text x="1029" y="358" class="legend-line">Period: 2000-01-03 to 2026-04-09</text>
  <text x="1029" y="376" class="legend-line">N = {N:,} trading days</text>
  <text x="1029" y="404" class="legend-line">Conditional arrows:</text>
  <text x="1029" y="422" class="legend-line">P(farther rung hit | current rung hit)</text>
</g>'''

footer = '''
<text x="990" y="664" class="footer">Static remake using measured SPY 3-min RTH data</text>
<a href="https://satyland.com" target="_blank" rel="noopener noreferrer">
  <text x="990" y="684" class="footer credit">ATR level framework: Saty Mahajan · satyland.com</text>
</a>
'''

svg = f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="SPY ATR Levels Probabilities static chart">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#10171a"/><stop offset="1" stop-color="#191f22"/></linearGradient>
  </defs>
  <rect width="1280" height="720" fill="#000"/>
  <rect x="{left_x}" y="{plot_top}" width="{W-left_x-28}" height="{plot_bottom-plot_top}" fill="url(#bg)"/>
  {''.join(grid)}
  <line x1="{left_x}" y1="{y(0):.1f}" x2="{W-28}" y2="{y(0):.1f}" stroke="#e4e9ee" stroke-width="1.65" opacity=".95"/>
  <line x1="{left_x}" y1="{y(0.236):.1f}" x2="{W-28}" y2="{y(0.236):.1f}" stroke="#19a6a6" stroke-width="1.2" opacity=".8"/>
  <line x1="{left_x}" y1="{y(-0.236):.1f}" x2="{W-28}" y2="{y(-0.236):.1f}" stroke="#b8a31f" stroke-width="1.2" opacity=".8"/>
  {''.join(parts)}
  {legend}
  {footer}
</svg>'''

html_doc = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SPY ATR Levels Probabilities</title>
  <style>
    :root {{ color-scheme: dark; }}
    html, body {{ margin:0; background:#050606; color:#f4f7f8; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .wrap {{ min-height:100vh; display:grid; place-items:center; padding:0; box-sizing:border-box; overflow:hidden; }}
    .chart {{ width:min(1280px, 100vw); aspect-ratio:16/9; max-height:100vh; box-shadow:0 20px 70px rgba(0,0,0,.55); }}
    svg {{ display:block; width:100%; height:100%; }}
    .axis-label {{ fill:#f5f7fa; font-size:12px; font-weight:650; letter-spacing:-.01em; }}
    .prob-label {{ fill:#f7fafc; font-size:12px; font-weight:720; letter-spacing:-.01em; paint-order:stroke; stroke:#121819; stroke-width:3px; stroke-linejoin:round; }}
    .legend-title {{ fill:#111; font-size:12px; font-weight:760; letter-spacing:-.01em; }}
    .legend-line {{ fill:#111; font-size:10.5px; font-weight:590; }}
    .footer {{ fill:#f5f7fa; font-size:9.8px; font-weight:700; text-anchor:start; paint-order:stroke; stroke:#111; stroke-width:1.7px; letter-spacing:-.01em; }}
    .credit {{ fill:#cdd7dc; text-decoration:underline; }}
    .caption {{ max-width:1280px; margin:10px auto 0; color:#a9b5ba; font-size:13px; line-height:1.35; }}
    .caption b {{ color:#fff; }}
  </style>
</head>
<body>
  <main class="wrap">
    <div>
      <div class="chart">{svg}</div>
    </div>
  </main>
</body>
</html>
'''
OUT.write_text(html_doc)
print(OUT)
print(f'N={N:,}')
print(f'+0.236→+0.382 {conditional_pct("+0.236","+0.382")[2]:.1f}%')
print(f'-0.236→-0.382 {conditional_pct("-0.236","-0.382")[2]:.1f}%')
print(f'0→+1 ATR {target_pct("+1.00")[2]:.1f}%')
print(f'0→-1 ATR {target_pct("-1.00")[2]:.1f}%')
print(f'0→+2 ATR {target_pct("+2.00")[2]:.1f}%')
print(f'0→-2 ATR {target_pct("-2.00")[2]:.1f}%')

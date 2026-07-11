#!/usr/bin/env python3
"""Bilbo Box Breakout — one-page PNG cheat sheet -> site/cheatsheet-bilbo-breakout.png.
Beginner-oriented: rules & takeaways up top, mechanics diagram, exit/VIX charts,
VIX + ticker stats tables. Data: analyst/po_comp_options/{vix_bucket_stats,ticker_stats}.json.
Layout follows a strict grid (Codex design review 2026-07-08): outer margin 0.025,
gutter 0.015, per-row column splits aligned, uniform panel padding."""
import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

STUDY = Path('/root/spy/analyst/po_comp_options')
OUT = Path('/root/spy/site/cheatsheet-bilbo-breakout.png')
VS = json.loads((STUDY / 'vix_bucket_stats.json').read_text())
TS = json.loads((STUDY / 'ticker_stats.json').read_text())
BUCKETS = ['<16', '16-18', '18-20', '20-22', '>22']
TOP = ['AMD', 'MU', 'TSLA', 'INTC', 'COIN', 'NVDA', 'PLTR', 'BAC']
AVOID = ['AAPL', 'JPM', 'DIS']

BG, PANEL, EDGE = '#0b0e14', '#0f1524', '#1f2a44'
GRID = '#182136'                             # lighter than EDGE: table gridlines
INK, MUT, FAINT = '#e5edf7', '#93a4b8', '#7b8ba1'
BLUE, AMBER = '#3987e5', '#c98500'           # validated series pair on BG
GREEN, RED, GRAY = '#22c55e', '#ef4444', '#8a94a6'
RED_DIM = '#c95b5b'
YELLOW = '#facc15'
BASELINE = '#46536b'

# grid tokens
M = 0.025            # outer margin
GUT = 0.015          # gutter
PAD = 0.013          # panel internal left/top padding
SPLIT_A = 0.610      # rows 1-2: left col ends / right col starts +GUT
SPLIT_B = 0.500      # rows 3-4

plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'text.color': INK,
    'axes.edgecolor': EDGE, 'axes.labelcolor': MUT,
    'xtick.color': MUT, 'ytick.color': MUT, 'mathtext.default': 'regular'})

FW, FH = 12.0, 15.6
fig = plt.figure(figsize=(FW, FH), dpi=150)
fig.patch.set_facecolor(BG)
LH = lambda fs, sp=1.35: fs * sp / 72 / FH


def panel(x, y, w, h, title=None, major=False):
    fig.add_artist(FancyBboxPatch((x, y), w, h, transform=fig.transFigure,
                   boxstyle='round,pad=0.004,rounding_size=0.005',
                   fc=PANEL, ec=EDGE, lw=1, zorder=0))
    if title:
        fig.text(x + PAD, y + h - 0.014, title, fontsize=13.5 if major else 12.0,
                 fontweight='bold', color=INK if major else '#c9d4e3', va='top')


def bar_label(axx, x, v, dy=0.5, fs=8.6):
    axx.text(x, v + dy, f'+{v:.1f}%', ha='center', fontsize=fs,
             fontweight='bold', color=INK)


# ------------------------------------------------------------------ header
fig.text(M + 0.005, 0.9890, 'BILBO BOX BREAKOUT', fontsize=27, fontweight='bold',
         color=INK, va='top')
fig.text(M + 0.005, 0.9630, 'options cheat sheet — hourly compression boxes → weekly options',
         fontsize=12, color=MUT, va='top')
fig.text(1 - M - 0.004, 0.9838, '20 stocks × 2 years × 2,345 boxes · real option trade prints',
         fontsize=8.7, color=FAINT, va='top', ha='right')
fig.text(1 - M - 0.004, 0.9722, 'milkmantrades.com/bilbo-box-options.html',
         fontsize=8.7, color=FAINT, va='top', ha='right')
fig.add_artist(plt.Line2D([M, 1 - M], [0.9555, 0.9555], transform=fig.transFigure,
               color=EDGE, lw=1))

# ------------------------------------------------------------------ row 1: rules | why
RY, RH = 0.678, 0.263
panel(M, RY, SPLIT_A - M, RH, 'THE RULES', major=True)
rules = [
    ('1. SPOT THE BOX', 'On the 1-hour chart (extended hours), compression paints gray candles. '
     'The first 5 draw the box: top = highest high, bottom = lowest low.'),
    ('2. WAIT FOR A MARKET-HOURS BREAK', 'Price pokes out of the box between 9:30–4:00 ET. Overnight or '
     'premarket gap breaks = NO TRADE (zero edge, tested on 2,064 of them).'),
    ('3. BUY IMMEDIATELY', "This-Friday ATM option. Don't wait for a pullback or retest — it usually "
     'never comes. Within 5 min of the break is free; 15 min late costs a third of the edge.'),
    ('4. PICK A VERSION', 'Directional: call on up-break, put on down-break — +13.5%/trade, 36% win. '
     'Straddle: buy BOTH sides — +12.0%/trade, 57% win, the most reliable stats (t=8.4).'),
    ('5. EXIT — STOP, ARM, TRAIL', 'Stop −50% of premium. When the option doubles (+100%), drop the '
     'target and TRAIL 30% below its high. Avoid taking profits early — the runners carry the average.'),
    ('6. VIX RULE', 'VIX under 18 → either version. VIX over 20 → STRADDLE ONLY (directional results go flat there).'),
    ('7. TICKERS & SIZE', 'High-beta movers only — see the table below. Skip the sleepy megas. '
     'Risk no more than 5% per trade — losing streaks are normal.'),
]
y = RY + RH - 0.0295
for head, body in rules:
    wrapped = textwrap.fill(body, width=102)
    fig.text(M + PAD, y, head, fontsize=10.0, fontweight='bold', color=YELLOW, va='top')
    y -= LH(10.0) + 0.0008
    fig.text(M + PAD + 0.008, y, wrapped, fontsize=8.6, color=INK, va='top', linespacing=1.26)
    y -= LH(8.6, 1.26) * (wrapped.count('\n') + 1) + 0.0040

panel(SPLIT_A + GUT, RY, 1 - M - SPLIT_A - GUT, RH, 'WHY IT WORKS', major=True)
tk = [
    ('Movement matters more than direction.', GREEN,
     'After a box breaks, price travels ~1.2 daily-ATRs within a week — in every market era since '
     '2004 — while the break direction is right only about half the time. Most of the payoff comes '
     'from the size of the move, not the side.'),
    ('The exit does the heavy lifting.', GREEN,
     'Same entries, two exits: a fixed +100%/−50% bracket earns +2.8% per trade; arm-then-trail '
     'earns +13.5%. Most of the return comes from how you exit.'),
    ('Lose often, win big.', YELLOW,
     'The median directional trade is a −50% stop-out. The average is carried by +300–500% runners. '
     'Cut the runners short and there is no strategy.'),
    ('Costs are real.', RED,
     'Backtest uses trade prints with no bid/ask spread — knock 2–4 points off every average; '
     'straddles pay the spread twice.'),
]
y = RY + RH - 0.0300
for head, col, body in tk:
    wrapped = textwrap.fill(body, width=52)
    fig.text(SPLIT_A + GUT + PAD, y, '●', fontsize=9, color=col, va='top')
    fig.text(SPLIT_A + GUT + PAD + 0.013, y, head, fontsize=10.0, fontweight='bold',
             color=INK, va='top')
    y -= LH(10.0) + 0.0008
    fig.text(SPLIT_A + GUT + PAD + 0.013, y, wrapped, fontsize=8.6, color=MUT,
             va='top', linespacing=1.3)
    y -= LH(8.6, 1.3) * (wrapped.count('\n') + 1) + 0.0062

# ------------------------------------------------------------------ row 2: diagram | exit chart
DY, DH = 0.468, RY - GUT - 0.468
panel(M, DY, SPLIT_A - M, DH, 'THE TRADE, START TO FINISH')
ax = fig.add_axes([M + 0.020, DY + 0.014, SPLIT_A - M - 0.042, DH - 0.048])
ax.set_facecolor(PANEL)
[s.set_visible(False) for s in ax.spines.values()]
ax.set_xticks([]); ax.set_yticks([])

candles = [(0, 100.0, 101.8, 99.2, 101.2, 'n'), (1, 101.2, 102.4, 100.6, 100.9, 'n'),
           (2, 100.9, 102.0, 100.1, 101.5, 'c'), (3, 101.5, 102.1, 100.4, 100.8, 'c'),
           (4, 100.8, 101.9, 100.2, 101.4, 'c'), (5, 101.4, 102.2, 100.5, 100.9, 'c'),
           (6, 100.9, 101.8, 100.3, 101.3, 'c'), (7, 101.3, 101.9, 100.4, 101.0, 'c'),
           (8, 101.0, 101.7, 100.3, 101.2, 'c'), (9, 101.2, 103.6, 101.0, 103.3, 'b'),
           (10, 103.3, 104.6, 102.9, 104.2, 'n'), (11, 104.2, 105.4, 103.8, 105.0, 'n')]
box_hi, box_lo = 102.4, 100.1
for x, o, h, l, c, kind in candles:
    col = {'n': GREEN if c >= o else RED, 'c': GRAY, 'b': GREEN}[kind]
    ax.plot([x, x], [l, h], color=col, lw=1.3, zorder=2)
    ax.add_patch(Rectangle((x - 0.30, min(o, c)), 0.60, abs(c - o) + 0.02,
                 fc=col, ec=col, zorder=3))
ax.add_patch(Rectangle((1.6, box_lo), 7.0, box_hi - box_lo, fc='none',
             ec=YELLOW, lw=1.6, ls=(0, (5, 3)), zorder=4))
ax.set_xlim(-0.8, 17.4); ax.set_ylim(98.2, 106.8)
ax.axvline(12.0, color=EDGE, lw=1)
ax.annotate('first 5 gray (compression)\ncandles = THE BOX', (4.9, box_lo - 0.15),
            xytext=(4.4, 98.45), fontsize=8.6, color=YELLOW, ha='center',
            arrowprops=dict(arrowstyle='-', color=YELLOW, lw=0.8))
ax.annotate('BREAK during market hours\n→ BUY ATM weekly (or straddle)', (9, 103.8),
            xytext=(3.9, 105.6), fontsize=9.0, color=GREEN, fontweight='bold', ha='center',
            arrowprops=dict(arrowstyle='->', color=GREEN, lw=1.4))

x0 = 12.8
px = [x0, x0 + .5, x0 + .9, x0 + 1.4, x0 + 1.9, x0 + 2.4, x0 + 2.9, x0 + 3.3]
py = [100.2, 100.9, 100.5, 101.6, 102.6, 103.8, 104.9, 104.05]
ax.plot(px, py, color=AMBER, lw=2.2, solid_capstyle='round', zorder=3)
ax.plot([x0 - 0.2, x0 + 3.7], [99.2, 99.2], color=RED, lw=1.1, ls=':')
ax.plot([x0 - 0.2, x0 + 3.7], [102.2, 102.2], color=GREEN, lw=1.1, ls=':')
ax.text(x0 + 1.75, 106.1, 'your OPTION premium', fontsize=8.8, color=AMBER,
        ha='center', fontweight='bold')
ax.text(x0 + 1.75, 98.55, 'stop −50%', fontsize=8.0, color=RED, ha='center')
ax.text(x0 - 0.45, 102.2, '+100%:\narm the trail', fontsize=8.0, color=GREEN,
        ha='right', va='center', linespacing=1.25)
ax.plot(px[-1], py[-1], 'o', ms=6, color=GREEN, zorder=5)
ax.annotate('sell when it gives back\n30% from its high', (px[-1], py[-1]),
            xytext=(px[-1] - 1.2, 101.65), fontsize=8.0, color=INK, ha='center', va='top',
            linespacing=1.25,
            arrowprops=dict(arrowstyle='-', color=FAINT, lw=0.7,
                            shrinkA=2, shrinkB=4))

panel(SPLIT_A + GUT, DY, 1 - M - SPLIT_A - GUT, DH, 'EXIT STYLE MAKES THE DIFFERENCE')
axe = fig.add_axes([SPLIT_A + GUT + 0.033, DY + 0.036, 1 - M - SPLIT_A - GUT - 0.062,
                    DH - 0.082])
axe.set_facecolor(PANEL)
groups = ['single leg\n(break direction)', 'straddle\n(both legs)']
fixed, trail = [2.8, 0.5], [13.5, 12.0]
for i in range(2):
    for j, v, col in [(0, fixed[i], GRAY), (1, trail[i], GREEN)]:
        x = i + (j - 0.5) * 0.38
        axe.bar(x, v, width=0.34, color=col, zorder=3)
        bar_label(axe, x, v, dy=0.45, fs=9.2)
axe.axhline(0, color=BASELINE, lw=1.5)
axe.set_xticks([0, 1]); axe.set_xticklabels(groups, fontsize=8.8)
axe.set_ylim(0, 17.5); axe.set_yticks([])
for s in axe.spines.values():
    s.set_visible(False)
axe.set_title('avg P&L per trade, % of premium — all 2,345 boxes', fontsize=8.4,
              color=MUT, pad=6)
axe.text(-0.19, 4.6, 'FIXED\nBRACKET', ha='center', va='bottom', fontsize=7.4,
         color=MUT, fontweight='bold', linespacing=1.25)
axe.text(0.19, 6.7, 'ARM-\nTHEN-\nTRAIL', ha='center', va='center', fontsize=7.6,
         color='#0b0e14', fontweight='bold', linespacing=1.25)

# ------------------------------------------------------------------ row 3: vix chart | vix table
VYC, VHC = 0.253, DY - GUT - 0.253
panel(M, VYC, SPLIT_B - M, VHC, 'VIX AT ENTRY: WHICH VERSION WINS')
axv = fig.add_axes([M + 0.028, VYC + 0.040, SPLIT_B - M - 0.052, VHC - 0.098])
axv.set_facecolor(PANEL)
for i, b in enumerate(BUCKETS):
    for j, (key, col) in enumerate([('single', BLUE), ('straddle', AMBER)]):
        v = VS[b][key]['mean']
        x = i + (j - 0.5) * 0.40
        axv.bar(x, v, width=0.36, color=col, zorder=3)
        bar_label(axv, x, v, dy=0.55, fs=8.2)
axv.axhline(0, color=BASELINE, lw=1.5)
axv.set_xticks(range(len(BUCKETS)))
axv.set_xticklabels([f'VIX {b}' for b in BUCKETS], fontsize=8.8)
axv.tick_params(axis='x', pad=5)
axv.set_ylim(0, 25.5); axv.set_yticks([])
for s in axv.spines.values():
    s.set_visible(False)
handles = [plt.Rectangle((0, 0), 1, 1, fc=BLUE), plt.Rectangle((0, 0), 1, 1, fc=AMBER)]
axv.legend(handles, ['single leg (break direction)', 'straddle (both legs)'],
           loc='lower left', bbox_to_anchor=(0.0, 0.99), ncols=2, fontsize=8.2,
           frameon=False, labelcolor=MUT, handlelength=1.1, columnspacing=1.4)
fig.text(M + PAD, VYC + 0.011,
         'avg P&L per trade (% of premium). Single leg fades as VIX rises; straddle holds at both ends.',
         fontsize=8.4, color=MUT)

panel(SPLIT_B + GUT, VYC, 1 - M - SPLIT_B - GUT, VHC, 'VIX BUCKETS — FULL STATS')
axt = fig.add_axes([SPLIT_B + GUT + PAD, VYC + 0.028, 1 - M - SPLIT_B - GUT - 2 * PAD,
                    VHC - 0.072])
axt.axis('off')
cols = ['VIX', 'boxes', 'avg', 'win', 'PF', 'avg', 'win', 'PF']
cells, cellcol = [], []
for b in BUCKETS + ['ALL']:
    s, st = VS[b]['single'], VS[b]['straddle']
    cells.append([('ALL' if b == 'ALL' else b), f"{s['n']:,}",
                  f"{s['mean']:+.1f}%", f"{s['win']}%", f"{s['pf']:.2f}",
                  f"{st['mean']:+.1f}%", f"{st['win']}%", f"{st['pf']:.2f}"])
    sc = GREEN if s['t'] >= 2 else (FAINT if s['t'] < 1 else INK)
    stc = GREEN if st['t'] >= 2 else (FAINT if st['t'] < 1 else INK)
    cellcol.append([INK, MUT, sc, sc, sc, stc, stc, stc])
tbl = axt.table(cellText=cells, colLabels=cols, loc='center', cellLoc='center')
tbl.auto_set_font_size(False)
tbl.set_fontsize(9.4)
tbl.scale(1, 1.78)
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor(GRID)
    cell.set_facecolor(PANEL if r % 2 else '#121a2e')
    if r == 0:
        cell.set_text_props(color=MUT, fontweight='bold')
        cell.set_facecolor('#121a2e')
    else:
        cell.set_text_props(color=cellcol[r - 1][c])
        if r == 6:
            cell.set_text_props(fontweight='bold')
span, xL = 1 - M - SPLIT_B - GUT - 2 * PAD, SPLIT_B + GUT + PAD
fig.text(xL + span * 3.5 / 8, VYC + VHC - 0.0330, 'SINGLE LEG', fontsize=8.8,
         color=BLUE, fontweight='bold', ha='center')
fig.text(xL + span * 6.5 / 8, VYC + VHC - 0.0330, 'STRADDLE', fontsize=8.8,
         color=AMBER, fontweight='bold', ha='center')
fig.text(SPLIT_B + GUT + PAD, VYC + 0.011,
         'green = solid (t≥2) · gray = noise (t<1) · PF: dollars won per dollar lost.',
         fontsize=8.4, color=MUT)

# ------------------------------------------------------------------ row 4: tickers | honesty
TY = M
TH = VYC - GUT - TY
panel(M, TY, SPLIT_B - M, TH, 'WHERE IT WORKS — TOP TICKERS')
axk = fig.add_axes([M + PAD, TY + 0.040, SPLIT_B - M - 2 * PAD, TH - 0.092])
axk.axis('off')
kcols = ['ticker', 'boxes', 'single avg', 'straddle avg', 'win', 'PF']
kcells, krowcol = [], []
for tkr in TOP + AVOID:
    n = int(TS['n_straddle'][tkr])
    kcells.append([tkr, str(n), f"{TS['mean_single'][tkr]:+.1f}%",
                   f"{TS['mean_straddle'][tkr]:+.1f}%",
                   f"{TS['win_straddle'][tkr]:.0f}%", f"{TS['pf_straddle'][tkr]:.2f}"])
    krowcol.append(GREEN if tkr in TOP else RED_DIM)
ktbl = axk.table(cellText=kcells, colLabels=kcols, loc='center', cellLoc='center')
ktbl.auto_set_font_size(False)
ktbl.set_fontsize(8.8)
ktbl.scale(1, 0.98)   # 12 rows must fit INSIDE the axes box — >1 overflows the panel
for (r, c), cell in ktbl.get_celld().items():
    cell.set_edgecolor(GRID)
    cell.set_facecolor(PANEL if r % 2 else '#121a2e')
    if r == 0:
        cell.set_text_props(color=MUT, fontweight='bold')
        cell.set_facecolor('#121a2e')
    else:
        avoid_row = r > len(TOP)
        if c == 0:
            cell.set_text_props(color=krowcol[r - 1], fontweight='bold')
        else:
            cell.set_text_props(color=MUT if avoid_row else INK)
fig.text(M + PAD, TY + 0.021,
         'win & PF shown for the straddle version. Red rows = tested, negative — skip them.\n'
         'High beta is the fuel: the underlying must move.',
         fontsize=8.4, color=MUT, linespacing=1.45)

panel(SPLIT_B + GUT, TY, 1 - M - SPLIT_B - GUT, TH, 'NOTES')
notes = ('Averages are % of option premium per trade, from real minute trade '
         'prints — no bid/ask spread or commissions. Expect a 2–4 point '
         'haircut on liquid weeklies; doubled for straddles.\n'
         'Win rates are low by design: this strategy pays through rare big '
         'runners, not accuracy. Expect losing streaks of 5+ and deep '
         'drawdowns at full sizing — that is why rule 7 says 5% max.\n'
         'Backtest: Jul 2024 – Jul 2026, 20 tickers, 2,345 boxes. Index options '
         '(SPY/QQQ/SPX) tested and rejected — the edge needs single-name '
         'movement.\n'
         'Full study, live example charts and method notes:  '
         'milkmantrades.com/bilbo-box-options.html')
y = TY + TH - 0.032
for para in notes.split('\n'):
    wrapped = textwrap.fill(para, width=62)
    fig.text(SPLIT_B + GUT + PAD, y, wrapped, fontsize=9.0, color=MUT,
             va='top', linespacing=1.38)
    y -= LH(9.0, 1.38) * (wrapped.count('\n') + 1) + 0.0055

fig.savefig(OUT, facecolor=BG)
print('wrote', OUT)

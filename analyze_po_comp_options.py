#!/usr/bin/env python3
"""Summary tables for the PO-compression options study.

Reads trades.parquet; answers the 5 questions with event-clustered stats
(legs within an episode are correlated -> aggregate per episode first).
Writes analyst/po_comp_options/summary.json and prints tables.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path('/root/spy/analyst/po_comp_options')
tr = pd.read_parquet(STUDY / 'trades.parquet')

RULES = {
    'ema21d_slope3': 'ema21_d_slope3', 'ema21d_slope1': 'ema21_d_slope1',
    'po_slope3': 'po_slope3', 'po_slope1': 'po_slope1', 'expansion_dir': 'exp_dir',
}
LONG_EXITS = ['pnl_hold', 'pnl_tp25', 'pnl_tp50', 'pnl_tp80', 'pnl_tp100', 'pnl_tp200',
              'pnl_sc50_80', 'pnl_sc25_50', 'pnl_sc50_100', 'pnl_sc100_200',
              'pnl_stop50', 'pnl_tp100_stop50', 'pnl_inval', 'pnl_tp100_inval',
              'pnl_und50', 'pnl_und100']
SHORT_EXITS = ['pnl_hold', 'pnl_decay50', 'pnl_decay80', 'pnl_stop2x', 'pnl_stop2x_inval']


def cstats(df, col):
    """Event-clustered mean / t / n_events / win rate."""
    g = df.groupby('ep_id')[col].mean()
    n = len(g)
    if n < 3 or g.std(ddof=1) == 0:
        return {'mean': None, 't': None, 'n_ev': n, 'win': None}
    return {'mean': round(float(g.mean()), 4),
            't': round(float(g.mean() / (g.std(ddof=1) / np.sqrt(n))), 2),
            'n_ev': n, 'win': round(float((df[col] > 0).mean()), 3)}


def table(df, dim, col):
    return {str(k): cstats(g, col) for k, g in df.groupby(dim)}


out = {}
longs = tr[tr.vehicle == 'long']
shorts = tr[tr.vehicle == 'short']
uncens = longs[~longs.censored]

# ---- Q1 direction rules (long vehicle, canonical mid exits + hold) --------
q1 = {}
for rname, feat in RULES.items():
    sub = longs[np.sign(longs[feat]) == longs.direction]
    anti = longs[np.sign(longs[feat]) == -longs.direction]
    if rname == 'expansion_dir':
        sub = sub[sub.entry == 'expansion_confirm']
        anti = anti[anti.entry == 'expansion_confirm']
    q1[rname] = {ex: {'with_rule': cstats(sub, ex), 'against': cstats(anti, ex)}
                 for ex in ['pnl_hold', 'pnl_tp100_stop50', 'pnl_sc50_80']}
out['q1_direction_rules_long'] = q1

# ---- Q2 entry variant + ribbon proximity ----------------------------------
best_rule_feat = 'ema21_d_slope3'   # evaluated below regardless; both shown
q2 = {}
for ename, g in longs[np.sign(longs[best_rule_feat]) == longs.direction].groupby('entry'):
    q2[ename] = {ex: cstats(g, ex) for ex in ['pnl_hold', 'pnl_tp100_stop50', 'pnl_sc50_80']}
g = longs[np.sign(longs[best_rule_feat]) == longs.direction]
q2['near_ribbon_lt_0.35atr'] = {ex: cstats(g[g.dist_ribbon_atr.abs() < 0.35], ex)
                                for ex in ['pnl_hold', 'pnl_sc50_80']}
q2['far_ribbon_ge_0.35atr'] = {ex: cstats(g[g.dist_ribbon_atr.abs() >= 0.35], ex)
                               for ex in ['pnl_hold', 'pnl_sc50_80']}
out['q2_entry'] = q2

# ---- Q3 expiry bucket (exclude censored for hold-type exits) ---------------
sel = uncens[np.sign(uncens[best_rule_feat]) == uncens.direction]
out['q3_expiry'] = {ex: table(sel, 'bucket', ex)
                    for ex in ['pnl_hold', 'pnl_tp100_stop50', 'pnl_sc50_80']}
out['q3_m1_fill_caveat'] = 'M1 legs have ~45% missing fills (thin far-dated prints); results are the liquid subset'

# ---- Q4 strike offset -------------------------------------------------------
out['q4_offset'] = {ex: table(sel, 'offset', ex)
                    for ex in ['pnl_hold', 'pnl_tp100_stop50', 'pnl_sc50_80']}

# ---- Q5 exit rules, marginal over the rule-selected long set ---------------
out['q5_exits_long'] = {ex: cstats(sel, ex) for ex in LONG_EXITS}

# ---- shorts (credit side), same direction rule ------------------------------
ssel = shorts[np.sign(shorts[best_rule_feat]) == shorts.direction]
ssel_unc = ssel[~ssel.censored]
out['credit_side'] = {ex: cstats(ssel_unc, ex) for ex in SHORT_EXITS}

# ---- per-ticker consistency for the headline combo --------------------------
combo = sel[(sel.bucket == 'W2') & (sel.offset == 0.0)]
out['per_ticker_W2_ATM_long'] = {ex: table(combo, 'ticker', ex)
                                 for ex in ['pnl_hold', 'pnl_sc50_80', 'pnl_tp100_stop50']}

# ---- straddle: long ATM call + put, premium-weighted, per event/entry/bucket
strad_rows = []
atm = longs[longs.offset == 0.0]
for (ep, en, bu), g in atm.groupby(['ep_id', 'entry', 'bucket']):
    call = g[g.direction == 1]
    put = g[g.direction == -1]
    if len(call) != 1 or len(put) != 1 or g.censored.any():
        continue
    c, p = call.iloc[0], put.iloc[0]
    w = c.entry_px + p.entry_px
    row = {'ep_id': ep, 'entry': en, 'bucket': bu, 'ticker': c.ticker,
           'cost_pct_spot': w / c.spot * 100}
    for ex in ['pnl_hold', 'pnl_tp50', 'pnl_tp100', 'pnl_sc50_80', 'pnl_sc100_200']:
        row[ex] = (c[ex] * c.entry_px + p[ex] * p.entry_px) / w
    strad_rows.append(row)
st = pd.DataFrame(strad_rows)
st.to_parquet(STUDY / 'straddles.parquet')
out['straddle_long_atm'] = {
    f"{en}|{bu}": {ex: cstats(g, ex) for ex in ['pnl_hold', 'pnl_tp50', 'pnl_tp100',
                                                'pnl_sc50_80', 'pnl_sc100_200']}
    for (en, bu), g in st.groupby(['entry', 'bucket'])}
out['straddle_per_ticker_hold'] = table(st[st.bucket == 'W2'], 'ticker', 'pnl_hold')

# ---- baseline: both directions (no rule), to show rule value ----------------
out['baseline_no_rule_long'] = {ex: cstats(uncens, ex)
                                for ex in ['pnl_hold', 'pnl_sc50_80']}

(STUDY / 'summary.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

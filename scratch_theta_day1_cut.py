#!/usr/bin/env python3
"""Day-1 loss cut test on the validated deep-ITM options expression.

Question (Pedro): does cutting LOSING option trades at end of Day 1 improve
the validated hourly-bull deep-ITM result?

Baseline (canonical, reproduced exactly):
  trades  = theta_stock_directional_strict.parquet, pop=hourly, direction=1
            (strict stock walk: next-5m-close entries, RTH exits, next-bar
            exit fills; exits are the underlying-keyed runner rules)
  options = deepitm_legs in theta/quotes.sqlite (CALL, strike nearest
            spot - 2.0 x dATR, expiry nearest 7-16 DTE; windows pulled
            entry_date -> min(expiry, exit_date+1d))
  P&L     = buy at effective ask at first two-sided quote >= entry_s
            (300 s grace), sell at effective bid at first two-sided quote
            >= exit_s. Exec levels: full (ef=1.0) and half (ef=0.5).

Cut rules (both run, labeled):
  A: entry-session EOD  — cutoff 16:00 ET on the ENTRY date.
  B: next-RTH-session EOD — cutoff 16:00 ET on the first date AFTER the
     entry date on which the contract has two-sided quotes.
  A trade is cut-ELIGIBLE only if its baseline exit_s > cutoff (16:00).
  Mark at cutoff = last two-sided quote with 15:30 <= t <= 16:00 ET that day
  (30-minute staleness tolerance; no such quote -> 'no_mark', baseline kept).
  Decision: executable liquidation (mid - ef*(mid-bid)) vs entry buy price,
  PER execution level. Negative -> exit AT that mark. Never negative -> keep
  baseline. No lookahead: decision uses only the cutoff quote.

Outputs: theta/theta_day1_cut.parquet (row level, both exec levels),
         theta/day1_cut_summary.csv, printed table.
Invariants asserted in-script (see bottom).
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
GRACE_S = 300
STALE_S = 30 * 60          # cutoff mark: last two-sided quote within 30 min
ET = 'America/New_York'

con = sqlite3.connect(f"file:{OUTDIR/'quotes.sqlite'}?mode=ro", uri=True)
con.execute('PRAGMA busy_timeout=60000')
tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)].copy()
legs = pd.read_sql('SELECT * FROM deepitm_legs', con)
tr = tr.merge(legs, on=['ticker', 'entry_s'], how='inner')
print(f'baseline trades with deep-ITM contract: {len(tr)}', flush=True)

qcache = {}
def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 3000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        q = np.array(r, float) if r else np.zeros((0, 3))
        qcache[cid] = q[(q[:, 1] > 0) & (q[:, 2] > 0)] if len(q) else q
    return qcache[cid]


def eod_cutoff_s(date_et):
    """Epoch seconds of 16:00 ET on the given ET date."""
    return int(pd.Timestamp(f'{date_et} 16:00', tz=ET).timestamp())


def cutoff_mark(q, cut_s):
    """Index of last two-sided quote with cut_s-STALE <= t <= cut_s, or None."""
    i = np.searchsorted(q[:, 0], cut_s, side='right') - 1
    if i < 0 or q[i, 0] < cut_s - STALE_S:
        return None
    return i


rows = []
for r in tr.itertuples():
    q = quotes(r.contract)
    if not len(q):
        continue
    i = np.searchsorted(q[:, 0], r.entry_s)
    if i >= len(q) or q[i, 0] > r.entry_s + GRACE_S:
        continue
    k = min(np.searchsorted(q[:, 0], r.exit_s), len(q) - 1)
    ts = pd.Timestamp(r.entry_s, unit='s', tz='UTC').tz_convert(ET)
    entry_date = ts.date()
    cutA_s = eod_cutoff_s(entry_date)
    # next session with quotes for THIS contract after entry date
    qdates = pd.to_datetime(q[:, 0], unit='s', utc=True).tz_convert(ET).date
    later = sorted({d for d in qdates if d > entry_date})
    cutB_s = eod_cutoff_s(later[0]) if later else None

    rec = {'ticker': r.ticker, 'entry_s': int(r.entry_s), 'exit_s': int(r.exit_s),
           'date': str(entry_date), 'year': r.year, 'grey': int(r.grey),
           'entry_hour': ts.hour, 'contract': r.contract,
           'cutA_s': cutA_s, 'cutB_s': cutB_s if cutB_s else -1}
    for tag, ef in [('half', 0.5), ('full', 1.0)]:
        m0 = (q[i, 1] + q[i, 2]) / 2
        buy = m0 + ef * (q[i, 2] - m0)
        if buy <= 0.02:
            break
        mx = (q[k, 1] + q[k, 2]) / 2
        base = (mx - ef * (mx - q[k, 1])) / buy - 1
        rec[f'base|{tag}'] = base
        rec[f'base_exit_s'] = int(q[k, 0])
        for rule, cut_s in [('A', cutA_s), ('B', cutB_s)]:
            col = f'cut{rule}|{tag}'
            # eligibility: baseline exit strictly after the cutoff
            if cut_s is None or r.exit_s <= cut_s:
                rec[col] = base
                rec[f'flag{rule}|{tag}'] = 'ineligible'
                continue
            mi = cutoff_mark(q, cut_s)
            if mi is None:
                rec[col] = base
                rec[f'flag{rule}|{tag}'] = 'no_mark'
                continue
            mm = (q[mi, 1] + q[mi, 2]) / 2
            mark = mm - ef * (mm - q[mi, 1])
            if mark < buy:                      # negative at cutoff -> cut
                rec[col] = mark / buy - 1
                rec[f'flag{rule}|{tag}'] = 'cut'
                rec[f'cut{rule}_quote_s|{tag}'] = int(q[mi, 0])
            else:
                rec[col] = base
                rec[f'flag{rule}|{tag}'] = 'held_positive'
    else:
        rows.append(rec)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_day1_cut.parquet')
print(f'scored: {len(d)}')

# ---------- invariant checks ----------
for tag in ['half', 'full']:
    for rule in ['A', 'B']:
        f = d[f'flag{rule}|{tag}']
        cut = d[f == 'cut']
        # 1. cut decision quote never after cutoff
        qs = cut[f'cut{rule}_quote_s|{tag}']
        cs = cut['cutA_s'] if rule == 'A' else cut['cutB_s']
        assert (qs <= cs).all(), 'cut quote after cutoff!'
        # 2. cut only when eligible: baseline exit strictly after cutoff
        ex = cut['exit_s']
        assert (ex > cs).all(), 'cut on already-closed trade!'
        # 3. uncut rows keep baseline P&L exactly
        un = d[f != 'cut']
        assert np.allclose(un[f'cut{rule}|{tag}'], un[f'base|{tag}']), \
            'uncut P&L changed!'
        # 4. cut exits are losses at the mark
        assert (cut[f'cut{rule}|{tag}'] < 0).all(), 'cut executed at a gain!'
print('INVARIANTS OK')

# ---------- reporting ----------
def stat(v, dates=None, months=None):
    v = pd.Series(v).dropna()
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    out = dict(n=len(v), mean=round(100 * v.mean(), 2),
               med=round(100 * v.median(), 1),
               win=round(100 * (v > 0).mean()), t=round(t, 2))
    if dates is not None:
        by = pd.DataFrame({'v': v, 'd': dates.loc[v.index]}).groupby('d').v.mean()
        out['tclust'] = round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2)
    if months is not None:
        mo = pd.DataFrame({'v': v, 'm': months.loc[v.index]}).groupby('m').v.agg(['mean', 'size'])
        mo = mo[mo['size'] >= 3]['mean']
        out['pos_mo'] = round(100 * (mo > 0).mean())
    return out


d['month'] = d.date.str.slice(0, 7)
summary = []
COHORTS = [('all hourly-bull', d),
           ('grey5+ (primary)', d[d.grey >= 5]),
           ('grey5+ 2019-22', d[(d.grey >= 5) & (d.year <= 2022)]),
           ('grey5+ 2023-26', d[(d.grey >= 5) & (d.year >= 2023)]),
           ('A-diag: entry<=13h', d[d.entry_hour <= 13]),
           ('A-diag: entry>=14h', d[d.entry_hour >= 14])]
for cname, g in COHORTS:
    for tag in ['half', 'full']:
        b = stat(g[f'base|{tag}'], g.date, g.month)
        row = {'cohort': cname, 'exec': tag, 'rule': 'baseline', **b,
               'cut_share': 0.0, 'd_mean': 0.0}
        summary.append(row)
        for rule in ['A', 'B']:
            s = stat(g[f'cut{rule}|{tag}'], g.date, g.month)
            fl = g[f'flag{rule}|{tag}']
            summary.append({'cohort': cname, 'exec': tag, 'rule': f'cut{rule}', **s,
                            'cut_share': round(100 * (fl == 'cut').mean(), 1),
                            'd_mean': round(s['mean'] - b['mean'], 2)})
S = pd.DataFrame(summary)
S.to_csv(OUTDIR / 'day1_cut_summary.csv', index=False)
pd.set_option('display.width', 200)
print('\n' + S.to_string(index=False))

# recovery diagnostic (primary cohort, half exec)
print('\n---- recovery diagnostic: trades CUT (negative at cutoff), what would '
      'baseline have done? (grey5+, half) ----')
g = d[d.grey >= 5]
for rule in ['A', 'B']:
    cut = g[g[f'flag{rule}|half'] == 'cut']
    if not len(cut):
        continue
    b = cut['base|half']
    c = cut[f'cut{rule}|half']
    rec_w = (b > 0)
    print(f'  rule {rule}: cut n={len(cut)} | would-have-recovered to winners: '
          f'{rec_w.sum()} ({100*rec_w.mean():.0f}%) | right tail sacrificed '
          f'(sum of baseline pnl on recovered): {100*b[rec_w].sum():+.0f}%-units | '
          f'losses saved (sum base-cut on non-recovered): '
          f'{100*(c[~rec_w]-b[~rec_w]).sum():+.0f}%-units | net delta '
          f'{100*(c-b).sum():+.0f}%-units over {len(g)} trades')
print('\nDAY1 CUT COMPLETE')

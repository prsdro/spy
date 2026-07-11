#!/usr/bin/env python3
"""Volume skip-filters for the validated hourly-bull deep-ITM cohort.

Question (Pedro #2): can volume identify hourly Bilbo trades to SKIP?

Cohort (fixed): the 3,087 option-priced hourly-bull trades whose baseline
P&L lives in theta_day1_cut.parquet (base|half, base|full) — byte-verified
equal to theta_deepitm_trades.parquet (+3.84% half / +1.74% full). The trade
universe is NOT changed; features may be NaN (coverage reported).

PREDECLARED skip rules (written before any outcome was read):
  R1: skip if f_boxvol  < 1.0   (breakout bar didn't out-trade its own box)
  R2: skip if f_hourrel < 1.0   (below that ticker+clock-hour's norm)
  R3: skip if f_cumrel  < 1.0   (day running slower than prior day, same time)
  Secondary (labeled in-sample): skip bottom pooled quartile per feature.
Fixed pooled-quintile tables are shown for monotonicity; no threshold search.

Features — all computed ONLY from bars that close at/before the entry signal
(the hourly confirm close). Bars come from the same 5m store + topups and the
same ETH hourly resample as scratch_theta_episodes.py, so timestamps align
with the signal by construction. Session caveat: box bars can be
premarket/afterhours ETH hours whose volumes are structurally small vs the
RTH breakout bar, inflating f_boxvol — so f_boxvol_rth restricts the box
median to box bars fully inside RTH (start hour 10..15); bars 04..08,16..19
and the mixed 09:00 bar are excluded from that variant.
  f_boxvol     brk hourly vol / median vol of the locked box bars (<=5)
  f_boxvol_rth same, box median over RTH-only box bars (>=2 required)
  f_hourrel    brk hourly vol / median vol of same clock-hour bars, that
               ticker, prior 20 sessions (strictly before entry date)
  f_cumrel     RTH 5m cumulative volume on entry day through the signal /
               prior RTH session cumulative through the same clock time
  f_cumfull    day cum through signal / prior FULL RTH session volume
               (time-of-day dependent by construction — labeled, optional)

Outputs: theta/theta_volume_features.parquet, theta/volume_filters_summary.csv.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
import sys
sys.path.insert(0, '/root/spy')
from indicators import compute_phase_oscillator

STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
ET = 'America/New_York'

base = pd.read_parquet(OUTDIR / 'theta_day1_cut.parquet')
base = base[['ticker', 'entry_s', 'date', 'year', 'grey',
             'base|half', 'base|full']].copy()
ref = pd.read_parquet(OUTDIR / 'theta_deepitm_trades.parquet')
assert len(base) == len(ref) == 3087
assert abs(base['base|half'].mean() - ref['half'].mean()) < 1e-12, \
    'baseline mismatch vs theta_deepitm_trades'
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
base = base.merge(ent[['ticker', 'entry_s', 'grey_bars']],
                  on=['ticker', 'entry_s'], how='left')
assert base.grey_bars.notna().all()
print(f'cohort fixed: {len(base)} trades', flush=True)


def load_frames(tkr):
    fr = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            fr.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            fr.append(t[['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']])
    df = pd.concat(fr, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True).dt.tz_convert(ET)
    df = df.drop_duplicates(subset='ts').sort_values('ts').set_index('ts')
    x5 = df.between_time('04:00', '19:55')
    h = x5.resample('60min').agg(open=('open', 'first'), high=('high', 'max'),
                                 low=('low', 'min'), close=('close', 'last'),
                                 volume=('volume', 'sum')).dropna(subset=['close'])
    h = compute_phase_oscillator(h)
    r5 = df.between_time('09:30', '15:55')[['volume']].copy()
    return h, r5


results = []
recon_fail = 0
for tkr, g in base.groupby('ticker'):
    h, r5 = load_frames(tkr)
    hstart = h.index.map(lambda x: int(x.timestamp())).to_numpy()
    vol = h['volume'].to_numpy(float)
    comp = h['po_compression'].to_numpy(int)
    hhour = h.index.hour.to_numpy()
    hdate = np.array([d.date() for d in h.index])
    r5d = np.array([d.date() for d in r5.index])
    r5s = r5.index.map(lambda x: int(x.timestamp())).to_numpy()
    r5tod = (r5.index.hour * 60 + r5.index.minute).to_numpy()
    r5v = r5['volume'].to_numpy(float)
    rdates = np.array(sorted(set(r5d)))
    for r in g.itertuples():
        # confirm bar: hourly bar whose CLOSE == entry signal (start = entry-1h)
        bs = r.entry_s - 3600
        ci = np.searchsorted(hstart, bs)
        rec = {'ticker': tkr, 'entry_s': r.entry_s}
        if ci >= len(hstart) or hstart[ci] != bs:
            recon_fail += 1
            results.append(rec)
            continue
        gb = int(r.grey_bars)
        # reconstruct grey run and assert it matches the stored count
        k = 0
        while ci - 1 - k >= 0 and comp[ci - 1 - k] == 1:
            k += 1
        if k != gb:
            recon_fail += 1
            results.append(rec)
            continue
        box = slice(ci - gb, ci - gb + min(gb, 5))
        bvols = vol[box]
        brk = vol[ci]
        rec['feat_maxbar_s'] = int(hstart[ci] + 3600)   # latest bar close used
        if len(bvols) and np.median(bvols) > 0:
            rec['f_boxvol'] = brk / np.median(bvols)
        rth_mask = (hhour[box] >= 10) & (hhour[box] <= 15)
        if rth_mask.sum() >= 2 and np.median(bvols[rth_mask]) > 0:
            rec['f_boxvol_rth'] = brk / np.median(bvols[rth_mask])
        # same clock-hour, prior sessions (strictly earlier dates), last 20
        m = (hhour[:ci] == hhour[ci]) & (hdate[:ci] < hdate[ci])
        prior = vol[:ci][m][-20:]
        if len(prior) >= 5 and np.median(prior) > 0:
            rec['f_hourrel'] = brk / np.median(prior)
        # cumulative RTH volume through signal vs prior session same time
        ed = hdate[ci]
        tod_cut = pd.Timestamp(r.entry_s, unit='s', tz='UTC').tz_convert(ET)
        tod_min = tod_cut.hour * 60 + tod_cut.minute
        today = (r5d == ed) & (r5s < r.entry_s)
        cum_today = r5v[today].sum()
        pidx = np.searchsorted(rdates, ed) - 1
        if pidx >= 0:
            pd_ = rdates[pidx]
            prev_same = (r5d == pd_) & (r5tod < tod_min)
            prev_full = (r5d == pd_)
            c1 = r5v[prev_same].sum()
            c2 = r5v[prev_full].sum()
            if c1 > 0 and cum_today > 0:
                rec['f_cumrel'] = cum_today / c1
            if c2 > 0 and cum_today > 0:
                rec['f_cumfull'] = cum_today / c2
        results.append(rec)
    print(f'{tkr} done', flush=True)

F = pd.DataFrame(results)
d = base.merge(F, on=['ticker', 'entry_s'], how='left')
d.to_parquet(OUTDIR / 'theta_volume_features.parquet')
FEATS = ['f_boxvol', 'f_boxvol_rth', 'f_hourrel', 'f_cumrel', 'f_cumfull']
print(f'\nreconstruction failures: {recon_fail}')
print('feature coverage of 3,087:',
      {f: int(d[f].notna().sum()) for f in FEATS})
# no-lookahead assertion: every feature bar closes at/before the signal
ok = d.feat_maxbar_s.dropna() <= d.loc[d.feat_maxbar_s.notna(), 'entry_s']
assert ok.all(), 'feature uses bar closing after signal!'
print('NO-LOOKAHEAD ASSERTION OK')


def stat(g, col, dates=None, months=None):
    v = g[col].dropna()
    if len(v) < 30:
        return dict(n=len(v))
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    out = dict(n=len(v), mean=round(100 * v.mean(), 2),
               med=round(100 * v.median(), 1), win=round(100 * (v > 0).mean()))
    by = g.loc[v.index].groupby('date')[col].mean()
    out['tclust'] = round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2)
    mo = g.loc[v.index].assign(m=g.loc[v.index, 'date'].str.slice(0, 7)) \
        .groupby('m')[col].agg(['mean', 'size'])
    mo = mo[mo['size'] >= 3]['mean']
    if len(mo) > 6:
        out['pos_mo'] = round(100 * (mo > 0).mean())
    return out


rows = []
d['era'] = np.where(d.year <= 2022, '2019-22', '2023-26')
COHORTS = [('all', d), ('grey5+', d[d.grey >= 5])]
for cname, g in COHORTS:
    for f in FEATS:
        gg = g[g[f].notna()].copy()
        if len(gg) < 300:
            continue
        gg['q'] = pd.qcut(gg[f], 5, labels=False, duplicates='drop')
        for q, gq in gg.groupby('q'):
            s = stat(gq, 'base|half')
            rows.append({'cohort': cname, 'feature': f, 'bucket': f'Q{q+1}',
                         'f_range': f'{gq[f].min():.2f}-{gq[f].max():.2f}', **s})
        # era sign consistency: top-half minus bottom-half mean per era
        med = gg[f].median()
        for era, ge in gg.groupby('era'):
            hi = ge[ge[f] >= med]['base|half'].mean()
            lo = ge[ge[f] < med]['base|half'].mean()
            rows.append({'cohort': cname, 'feature': f, 'bucket': f'{era} hi-lo',
                         'f_range': '', 'n': len(ge),
                         'mean': round(100 * (hi - lo), 2)})
Q = pd.DataFrame(rows)

# predeclared skip rules on matched trades
rules = []
for cname, g in COHORTS:
    for tag in ['half', 'full']:
        b = stat(g, f'base|{tag}')
        rules.append({'cohort': cname, 'exec': tag, 'rule': 'baseline (matched)',
                      **b, 'share_kept': 100.0, 'sum_pnl': round(
                          100 * g[f'base|{tag}'].sum())})
        for f, lbl in [('f_boxvol', 'R1 skip f_boxvol<1'),
                       ('f_boxvol_rth', 'R1b skip f_boxvol_rth<1'),
                       ('f_hourrel', 'R2 skip f_hourrel<1'),
                       ('f_cumrel', 'R3 skip f_cumrel<1')]:
            m = g[f].notna()
            keep = g[m & (g[f] >= 1.0)]
            matched = g[m]
            bm = stat(matched, f'base|{tag}')
            s = stat(keep, f'base|{tag}')
            rules.append({'cohort': cname, 'exec': tag,
                          'rule': lbl + f' (match n={len(matched)}, '
                                  f'match mean={bm.get("mean")})',
                          **s, 'share_kept': round(100 * len(keep) / max(1, len(matched)), 1),
                          'sum_pnl': round(100 * keep[f'base|{tag}'].sum())})
        # secondary: bottom-quartile skip (in-sample threshold, labeled)
        for f in ['f_boxvol', 'f_hourrel']:
            m = g[f].notna()
            thr = g.loc[m, f].quantile(0.25)
            keep = g[m & (g[f] >= thr)]
            s = stat(keep, f'base|{tag}')
            rules.append({'cohort': cname, 'exec': tag,
                          'rule': f'Q1-skip {f} (thr={thr:.2f}, IN-SAMPLE)',
                          **s, 'share_kept': round(100 * len(keep) / m.sum(), 1),
                          'sum_pnl': round(100 * keep[f'base|{tag}'].sum())})
R = pd.DataFrame(rules)
S = pd.concat([Q.assign(section='quintiles'), R.assign(section='rules')],
              ignore_index=True)
S.to_csv(OUTDIR / 'volume_filters_summary.csv', index=False)
pd.set_option('display.width', 250)
print('\n===== QUINTILE TABLES (base|half) =====')
print(Q.to_string(index=False))
print('\n===== PREDECLARED SKIP RULES (matched baselines shown per rule) =====')
print(R.to_string(index=False))
print('\nVOLUME FILTERS COMPLETE')

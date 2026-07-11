#!/usr/bin/env python3
"""RTH breakout-bar vs compression-bar volume — focused follow-up (Pedro).

Cohort: the fixed 3,087 hourly-bull deep-ITM option trades; baseline P&L
base|half / base|full from theta_day1_cut.parquet (verified == published).

AUDIT of the prior f_boxvol_rth: its numerator is the FULL ETH hourly confirm
bar. Cohort signals close 10:00-15:00 ET, so confirm bars START 09:00-14:00.
The 09:00-start bar (10:00 signals) spans 09:00-09:30 premarket + 09:30-10:00
RTH -> MIXED numerator. All other confirm bars (start 10:00-14:00) are fully
RTH. The prior feature is therefore 'mixed-numerator / RTH-denominator'; the
share of mixed numerators is quantified below.

Features (predeclared rule for each: KEEP if ratio >= 1.0; fixed quintiles
shown; no threshold search). All inputs close at/before the signal.
  F1  prior f_boxvol_rth as-is (mixed numerator allowed), denom = median of
      fully-RTH locked box bars (start hour 10-15), >=2 required.
  F2  STRICT apples-to-apples: confirm bar must START in 10..14 (fully RTH
      numerator; a 15:00-start bar closes 16:00 and cannot be in this
      cohort), denom as F1. 10:00-signal trades are INELIGIBLE by
      construction — their baseline P&L is reported as the selection effect.
  F3  pure-RTH 5m rate construction: numerator = mean RTH 5m volume/bar in
      the confirm bucket (bars 09:30+ only, so the 09-bucket uses its 6 RTH
      bars); denom = median over box bars' same-normalized RTH rates (>=2 box
      bars overlapping RTH). Covers 10:00 signals, but the 09:30-10:00
      half-hour carries opening-auction seasonality that inflates its rate —
      LABELED limitation, not silently ignored.

Outputs: theta/theta_rth_boxvol_detail.parquet, theta/rth_boxvol_summary.csv.
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
assert len(base) == 3087 and abs(base['base|half'].mean() - 0.0384) < 1e-3
prior = pd.read_parquet(OUTDIR / 'theta_volume_features.parquet')
base = base.merge(prior[['ticker', 'entry_s', 'f_boxvol_rth', 'f_hourrel']],
                  on=['ticker', 'entry_s'], how='left')
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
base = base.merge(ent[['ticker', 'entry_s', 'grey_bars']],
                  on=['ticker', 'entry_s'], how='left')


def load_frames(tkr):
    fr = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            fr.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'close', 'volume']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            fr.append(t[['metric_ts_et', 'close', 'volume']])
    df = pd.concat(fr, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True).dt.tz_convert(ET)
    df = df.drop_duplicates(subset='ts').sort_values('ts').set_index('ts')
    x5 = df.between_time('04:00', '19:55')
    h = x5.resample('60min').agg(close=('close', 'last'),
                                 volume=('volume', 'sum')).dropna(subset=['close'])
    # PO needs OHLC; rebuild minimal frame for compression flags
    hh = x5.resample('60min').agg(open=('close', 'first'), high=('close', 'max'),
                                  low=('close', 'min'), close=('close', 'last')).dropna()
    # use the SAME construction as episodes for compression: full OHLC
    ho = x5['close']
    full = x5.resample('60min').agg(volume=('volume', 'sum'))
    r5 = df.between_time('09:30', '15:55')[['volume']].copy()
    return x5, r5


# NOTE: compression flags must match scratch_theta_episodes exactly (OHLC).
def hourly_with_po(tkr):
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
    r5 = x5.between_time('09:30', '15:55')[['volume']].copy()
    return h, r5


rows = []
for tkr, g in base.groupby('ticker'):
    h, r5 = hourly_with_po(tkr)
    hstart = h.index.map(lambda x: int(x.timestamp())).to_numpy()
    vol = h['volume'].to_numpy(float)
    comp = h['po_compression'].to_numpy(int)
    hhour = h.index.hour.to_numpy()
    r5s = r5.index.map(lambda x: int(x.timestamp())).to_numpy()
    r5v = r5['volume'].to_numpy(float)
    for r in g.itertuples():
        bs = r.entry_s - 3600
        ci = np.searchsorted(hstart, bs)
        rec = {'ticker': tkr, 'entry_s': r.entry_s}
        if ci >= len(hstart) or hstart[ci] != bs:
            rows.append(rec)
            continue
        gb = int(r.grey_bars)
        k = 0
        while ci - 1 - k >= 0 and comp[ci - 1 - k] == 1:
            k += 1
        if k != gb:
            rows.append(rec)
            continue
        box = np.arange(ci - gb, ci - gb + min(gb, 5))
        rec['confirm_start_hour'] = int(hhour[ci])
        rec['feat_maxbar_s'] = int(hstart[ci] + 3600)
        rth_box = box[(hhour[box] >= 10) & (hhour[box] <= 15)]
        # F2: strict — fully-RTH numerator AND >=2 fully-RTH box bars
        if hhour[ci] in (10, 11, 12, 13, 14) and len(rth_box) >= 2:
            med = np.median(vol[rth_box])
            if med > 0:
                rec['f2_strict'] = vol[ci] / med
        # F3: pure-RTH 5m rates (numerator bucket may be partial: 09 bucket)
        def rth_rate(bar_start_s):
            m = (r5s >= bar_start_s) & (r5s < bar_start_s + 3600)
            n = m.sum()
            return (r5v[m].sum() / n) if n >= 4 else np.nan
        num = rth_rate(hstart[ci])
        dens = [rth_rate(hstart[b]) for b in box]
        dens = [x for x in dens if np.isfinite(x) and x > 0]
        if np.isfinite(num) and num > 0 and len(dens) >= 2:
            rec['f3_rate'] = num / np.median(dens)
        rows.append(rec)
    print(f'{tkr} done', flush=True)

F = pd.DataFrame(rows)
d = base.merge(F, on=['ticker', 'entry_s'], how='left')
d.to_parquet(OUTDIR / 'theta_rth_boxvol_detail.parquet')
ok = d.feat_maxbar_s.dropna() <= d.loc[d.feat_maxbar_s.notna(), 'entry_s']
assert ok.all()
print('NO-LOOKAHEAD OK')
mixed = (d.confirm_start_hour == 9)
print(f'\nAUDIT: mixed-numerator (09:00-start confirm bar) share of cohort: '
      f'{mixed.sum()}/{len(d)} ({100*mixed.mean():.1f}%)')
print('coverage:', {f: int(d[f].notna().sum())
                    for f in ['f_boxvol_rth', 'f2_strict', 'f3_rate', 'f_hourrel']})
print('baseline of F2-INELIGIBLE 10:00-signal trades (selection effect): '
      f"n={mixed.sum()}, mean half {100*d.loc[mixed,'base|half'].mean():+.2f}%")


def stat(g, col):
    v = g[col].dropna()
    if len(v) < 30:
        return dict(n=len(v))
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


d['era'] = np.where(d.year <= 2022, '2019-22', '2023-26')
FEATS = ['f_boxvol_rth', 'f2_strict', 'f3_rate']
out_rows = []
for cname, g in [('all', d), ('grey5+', d[d.grey >= 5])]:
    for f in FEATS:
        gg = g[g[f].notna()].copy()
        if len(gg) < 200:
            continue
        gg['q'] = pd.qcut(gg[f], 5, labels=False, duplicates='drop')
        for q, gq in gg.groupby('q'):
            out_rows.append({'cohort': cname, 'feature': f, 'row': f'Q{q+1}',
                             'range': f'{gq[f].min():.2f}-{gq[f].max():.2f}',
                             **stat(gq, 'base|half')})
        for tag in ['half', 'full']:
            for era in ['ALL', '2019-22', '2023-26']:
                ge = gg if era == 'ALL' else gg[gg.era == era]
                keep = ge[ge[f] >= 1.0]
                out_rows.append({'cohort': cname, 'feature': f,
                                 'row': f'rule>=1 {era} {tag}',
                                 'range': f'matched n={len(ge)} '
                                          f'mean={stat(ge, f"base|{tag}").get("mean")}',
                                 **stat(keep, f'base|{tag}'),
                                 'share_kept': round(100 * len(keep) / max(1, len(ge)), 1),
                                 'sum_kept_pct': round(100 * keep[f'base|{tag}'].sum()
                                                       / max(1e-9, ge[f'base|{tag}'].sum()))
                                 if ge[f'base|{tag}'].sum() > 0 else np.nan})
S = pd.DataFrame(out_rows)
S.to_csv(OUTDIR / 'rth_boxvol_summary.csv', index=False)
pd.set_option('display.width', 250)
print('\n===== QUINTILES + RULES (base|half unless labeled) =====')
print(S.to_string(index=False))

# robustness: entry hour & ticker (F2, all cohort, half)
g = d[d.f2_strict.notna()]
print('\n-- F2 keep-minus-matched delta by entry clock hour (half) --')
for hr, gh in g.groupby(g.confirm_start_hour + 1):
    kp = gh[gh.f2_strict >= 1]['base|half']
    print(f'  {hr:02d}:00 signals: matched n={len(gh)} mean={100*gh["base|half"].mean():+.2f} '
          f'keep n={len(kp)} mean={100*kp.mean():+.2f} delta={100*(kp.mean()-gh["base|half"].mean()):+.2f}')
print('\n-- F2 by ticker: delta(keep - matched), half --')
imp = 0
for tkr, gt in g.groupby('ticker'):
    if len(gt) < 30:
        continue
    dlt = gt[gt.f2_strict >= 1]['base|half'].mean() - gt['base|half'].mean()
    imp += dlt > 0
    print(f'  {tkr:6s} n={len(gt):4d} delta={100*dlt:+.2f}')
print(f'  improved: {imp} tickers (of those with n>=30)')

# vs f_hourrel
both = d[d.f2_strict.notna() & d.f_hourrel.notna()].copy()
from scipy.stats import spearmanr
rho = spearmanr(both.f2_strict, both.f_hourrel).statistic
print(f'\n-- F2 vs f_hourrel: spearman rho={rho:.2f} (n={len(both)}) --')
both['A'] = both.f2_strict >= 1
both['B'] = both.f_hourrel >= 1
print('2x2 cells (n / mean half / tclust):')
for a in [True, False]:
    for b in [True, False]:
        c = both[(both.A == a) & (both.B == b)]
        s = stat(c, 'base|half')
        print(f'  box>=1={a!s:5s} hourrel>=1={b!s:5s}: n={s.get("n")} '
              f'mean={s.get("mean")} tclust={s.get("tclust")}')
for lbl, m in [('keep hourrel>=1 only', both.B),
               ('keep box>=1 only', both.A),
               ('keep BOTH>=1', both.A & both.B)]:
    k = both[m]
    s = stat(k, 'base|half')
    print(f'  {lbl:22s}: n={s["n"]} share={100*len(k)/len(both):.0f}% '
          f'mean={s["mean"]} tclust={s["tclust"]} '
          f'sumP&L={100*k["base|half"].sum():.0f} (matched total '
          f'{100*both["base|half"].sum():.0f})')
# incremental: within hourrel-keep, does box ratio add?
hk = both[both.B]
print('  within hourrel>=1: box>=1 ' + str(stat(hk[hk.A], 'base|half'))
      + ' | box<1 ' + str(stat(hk[~hk.A], 'base|half')))
print('\nRTH BOXVOL DETAIL COMPLETE')

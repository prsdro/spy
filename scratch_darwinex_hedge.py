#!/usr/bin/env python3
"""MES hedge overlay on the Bilbo stock-CFD strategy: does shorting index
notional against each long reduce variance while keeping the edge?

Hedge leg: ES continuous ratio-adjusted 1-min (ET timestamps, data ends
2026-01) — entry at the ES 1-min close at/before the stock fill time
(entry_s + 5min next-close fill), exit at the ES close at/before the stock
exit fill. Trades entering after the ES data end are EXCLUDED from every arm
(including h=0) so comparisons are like-for-like.

Costs: stock leg = base Darwinex CFD model; hedge leg = 0.5 bps/side of
hedge notional, zero carry (MES basis ~ financing-neutral; short US500 CFD
swap ~ 0, note in report). Hedge notional = h x stock notional at entry.

For each h in {0, 0.25, 0.5, 0.75, 1.0, 1.25}:
  per-trade: mean bps, per-trade std, date-clustered t, corr with ES leg
  portfolio: w matched to native monthly VaR95 ~ 6.5% -> DARWIN mret,
             qualification %, DarwinIA fees (same proxy/tranche model).
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import scratch_darwinex_cfd_analyze as H
from scratch_darwinex_account_compare import darwinia_m

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
ET = 'America/New_York'
ES_TXT = ('/srv/ftp/ossicones/futures-data/'
          'ES_full_1min_continuous_ratio_adjusted.txt')
ES_CACHE = OUTDIR / 'es_1min_2019plus.parquet'
HS = [0.0, 0.25, 0.50, 0.75, 1.00, 1.25]
HEDGE_BP_SIDE = 0.5
COMBOS = [('gated', H.STD), ('gated_grey5', H.UPG)]
ALLOC = [30_000, 375_000]

# ---------- ES data ----------
if ES_CACHE.exists():
    es = pd.read_parquet(ES_CACHE)
else:
    es = pd.read_csv(ES_TXT, header=None, usecols=[0, 4],
                     names=['ts', 'close'])
    es = es[es.ts >= '2018-12-01']
    es['t'] = (pd.DatetimeIndex(es.ts).tz_localize(
        ET, ambiguous='NaT', nonexistent='NaT').tz_convert('UTC'))
    es = es.dropna(subset=['t'])
    es['epoch'] = pd.DatetimeIndex(es.t).as_unit('ns').asi8 // 10 ** 9
    es[['epoch', 'close']].to_parquet(ES_CACHE)
    es = es[['epoch', 'close']]
ES_T = es.epoch.to_numpy()
ES_C = es.close.to_numpy(float)
ES_END = int(ES_T[-1])
et_dates = pd.to_datetime(ES_T, unit='s', utc=True).tz_convert(ET)
mark_ok = (et_dates.hour * 60 + et_dates.minute) <= 15 * 60 + 55
es_daily = pd.Series(ES_C[mark_ok],
                     index=et_dates[mark_ok].date.astype(str)) \
    .groupby(level=0).last()
print(f'ES 1min rows {len(ES_T)}, ends '
      f'{pd.Timestamp(ES_END, unit="s", tz="UTC").tz_convert(ET)}', flush=True)


def es_at(epochs):
    i = np.searchsorted(ES_T, epochs, side='right') - 1
    return ES_C[np.clip(i, 0, len(ES_C) - 1)]


def portfolio_hedged(df, cfg, w, h):
    comm, half, swapann = H.COSTS['base']
    per_night = swapann / 360
    hbp = HEDGE_BP_SIDE / 1e4
    tr = df[df[f'x_{cfg}'].notna()][
        ['ticker', 'entry_s', 'entry_px', f'g_{cfg}', f'x_{cfg}']].copy()
    tr.columns = ['ticker', 'entry_s', 'entry_px', 'gross', 'exit_s']
    tr['exit_px'] = tr.entry_px * (1 + tr.gross)
    tr['es_in'] = es_at(tr.entry_s.to_numpy() + 300)
    tr['es_out'] = es_at(tr.exit_s.to_numpy().astype('int64'))
    tr['d_in'] = pd.to_datetime(tr.entry_s, unit='s', utc=True) \
        .dt.tz_convert(ET).dt.date.astype(str)
    tr['d_out'] = pd.to_datetime(tr.exit_s, unit='s', utc=True) \
        .dt.tz_convert(ET).dt.date.astype(str)
    by_day_in = {d: t for d, t in tr.groupby('d_in')}
    days = H.ALLDAYS[(H.ALLDAYS >= tr.d_in.min()) & (H.ALLDAYS <= tr.d_out.max())]
    eq, open_pos, curve = 1.0, [], []
    for day in days:
        pnl = 0.0
        for pos in open_pos:
            closed = pos['d_out'] == day
            m1 = pos['exit_px'] if closed else H.px[pos['tkr']].get(day, pos['mark'])
            e1 = pos['es_out'] if closed else es_daily.get(day, pos['es_mark'])
            pnl += (m1 - pos['mark']) * pos['sh']
            pnl -= (e1 - pos['es_mark']) * pos['hu']          # short hedge
            if closed:
                pnl -= pos['sh'] * m1 * (comm + half) / 1e4
                pnl -= pos['hu'] * e1 * hbp
                pos['dead'] = True
            else:
                pos['mark'], pos['es_mark'] = m1, e1
                pnl -= pos['sh'] * m1 * per_night
        open_pos = [p for p in open_pos if not p.get('dead')]
        if day in by_day_in:
            for r in by_day_in[day].itertuples():
                sh = w * eq / r.entry_px
                hu = h * w * eq / r.es_in
                pnl -= sh * r.entry_px * (comm + half) / 1e4 + hu * r.es_in * hbp
                if r.d_out == day:
                    pnl += (r.exit_px - r.entry_px) * sh
                    pnl -= (r.es_out - r.es_in) * hu
                    pnl -= sh * r.exit_px * (comm + half) / 1e4
                    pnl -= hu * r.es_out * hbp
                else:
                    m1 = H.px[r.ticker].get(day, r.entry_px)
                    e1 = es_daily.get(day, r.es_in)
                    pnl += (m1 - r.entry_px) * sh - (e1 - r.es_in) * hu
                    pnl -= sh * m1 * per_night
                    open_pos.append({'tkr': r.ticker, 'sh': sh, 'hu': hu,
                                     'mark': m1, 'es_mark': e1,
                                     'exit_px': r.exit_px, 'es_out': r.es_out,
                                     'd_out': r.d_out})
        eq += pnl
        curve.append(eq)
    return pd.Series(curve, index=pd.to_datetime(days))


rows = []
for coh, cfg in COMBOS:
    df = H.g[H.COHORTS[coh]].copy()
    df = df[df[f'x_{cfg}'].notna()]
    df = df[df[f'x_{cfg}'] + 0 <= ES_END]           # ES coverage cutoff
    stock_net, _ = H.net_pnl(df, cfg, 'base')
    es_in = es_at(df.entry_s.to_numpy() + 300)
    es_out = es_at(df[f'x_{cfg}'].to_numpy().astype('int64'))
    es_ret = es_out / es_in - 1
    print(f'\n== {coh} / {cfg}: n={len(df)} (ES-covered) ==')
    print(f'corr(stock trade net, ES window ret) = '
          f'{np.corrcoef(stock_net, es_ret)[0, 1]:.3f}; '
          f'book beta (cov/var) = '
          f'{np.cov(stock_net, es_ret)[0, 1] / np.var(es_ret):.2f}')
    for h in HS:
        p = stock_net - h * es_ret - 2 * h * HEDGE_BP_SIDE / 1e4
        t = H.tclust(pd.Series(p.values, index=df.index),
                     df.loc[p.index, 'date'])
        # portfolio: match native VaR to 6.5%
        best = None
        for w in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.75]:
            eqc = portfolio_hedged(df, cfg, w, h)
            mt = H.metrics(eqc)
            key = abs(mt['var95'] - 0.065)
            if best is None or key < best[0]:
                best = (key, w, mt, eqc)
        _, w, mt, eqc = best
        m = eqc.resample('ME').last().pct_change().dropna()
        scale = min(0.065 / mt['var95'], 9.75)
        md = m * scale
        qual, _ = darwinia_m(md, 30_000)
        fees = {A: darwinia_m(md, A)[1] for A in ALLOC}
        yrs = range(md.index[0].year, md.index[-1].year + 1)
        f30 = fees[30_000].reindex(yrs, fill_value=0.0).mean()
        f375 = fees[375_000].reindex(yrs, fill_value=0.0).mean()
        rows.append({'cohort': coh, 'cfg': cfg, 'h': h, 'n': len(p),
                     'bps': 1e4 * p.mean(), 'trade_sd': 1e4 * p.std(),
                     'tclust': t, 'w': w, 'mret': m.mean(),
                     'mstd': m.std(), 'var95': mt['var95'],
                     'maxdd': mt['maxdd'], 'calmar': mt['calmar'],
                     'posm': mt['posm'], 'scale': scale,
                     'darwin_mret': md.mean(), 'qual': qual.mean(),
                     'fees30': f30, 'fees375': f375})
        r = rows[-1]
        print(f"h={h:4.2f}: {r['bps']:+6.1f}bps sd{r['trade_sd']:5.0f} "
              f"t{r['tclust']:+4.2f} | w={w} mret{100 * r['mret']:+5.2f}% "
              f"msd{100 * r['mstd']:4.2f} dd{100 * r['maxdd']:5.1f}% "
              f"calmar{r['calmar']:5.2f} posm{r['posm']:.2f} | "
              f"scale{scale:4.2f} Dmret{100 * r['darwin_mret']:+5.2f}% "
              f"qual{r['qual']:.0%} fees30 EUR{f30:,.0f} "
              f"fees375 EUR{f375:,.0f}", flush=True)
pd.DataFrame(rows).to_csv(OUTDIR / 'darwinex_hedge_sweep.csv', index=False)
print('\nDONE hedge')

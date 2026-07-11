import warnings; warnings.filterwarnings('ignore')
import sys, pandas as pd, numpy as np; sys.path.insert(0,'/root/spy')
import scratch_entry_search_undexit as U
SP='/tmp/claude-0/-root-spy/62277ae3-4f37-46b9-af6f-b11621720ea3/scratchpad'
TP='analyst/po_comp_options/underlying_5m_topup_fresh10.parquet'
EV='events_fresh10.csv'
ALL=['ORCL','QCOM','MRVL','CRM','WMT','XOM','GS','LLY','CAT','SHOP']

def breadth(dd):
    g=dd.groupby('ticker').strad.mean()
    pos=[t for t in ALL if t in g.index and g[t]>0]
    per=" ".join(f"{t}{100*g[t]:+.1f}" if t in g.index else f"{t}=NO-TRADES" for t in ALL)
    return len(pos), per

for tf,lbl in [('fresh10_confirm_trades.parquet','PRIMARY confirm'),
               ('fresh10_fullbox_trades.parquet','RUNNER-UP fullbox')]:
    d=U.run(tf,TP,EV)
    d['vix']=[U.vix_at(int(pd.Timestamp(x).timestamp()*1000)) for x in d.entry_ts]
    d.to_parquet(f'{SP}/es_fresh10_{"confirm" if "confirm" in tf else "fullbox"}.parquet')
    g=d[d.box_h_atr<0.6].reset_index(drop=True)
    print(f"===== {lbl} =====")
    print(" PRE-REGISTERED CELL (boxh<0.6):")
    print("   strad   ", U.fmt(U.stats(g,'strad')))
    print("   strad_sp", U.fmt(U.stats(g,'strad_sp')), " [sensitivity]")
    npos, per = breadth(g)
    print(f"   tickers positive: {npos}/10 :: {per}")
    s=U.stats(g,'strad')
    ok1=s['tc']>=2.0; ok2=s['mean']>=4.0; ok3=npos>=6
    print(f"   pass bar: tc>=2.0 {'PASS' if ok1 else 'FAIL'} ({s['tc']:+.2f}) | mean>=+4% {'PASS' if ok2 else 'FAIL'} ({s['mean']:+.1f}%) | >=6/10 tickers+ {'PASS' if ok3 else 'FAIL'} ({npos}/10)")
    print(f"   VERDICT: {'PASS' if (ok1 and ok2 and ok3) else 'FAIL'}")
    print(" exploratory (ungated):")
    print("   strad   ", U.fmt(U.stats(d,'strad')))
    npos,per=breadth(d); print(f"   tickers positive: {npos}/10 :: {per}")
    print(" exploratory (boxh>=0.6 complement):")
    c=d[d.box_h_atr>=0.6].reset_index(drop=True)
    print("   strad   ", U.fmt(U.stats(c,'strad')))
    print(" exploratory (boxh<0.6 & vix<18):")
    v=d[(d.box_h_atr<0.6)&(d.vix<18)].reset_index(drop=True)
    print("   strad   ", U.fmt(U.stats(v,'strad')))
print('FRESH10_VERDICT_DONE')

#!/usr/bin/env python3
"""Style-verification preview: ONE real trade (NVDA-043 retest down-break put)
rendered in the server.py /charts/ Saty style. Outputs site/po-comp-example-preview.html."""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, '/root/spy')
from fetch_po_comp_options import load_5m, hourly_and_daily
from indicators import compute_phase_oscillator, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
ev = pd.read_csv(STUDY / 'events.csv')
e = ev[ev.ep_id == 'NVDA-043'].iloc[0]
tr = pd.read_parquet(STUDY / 'bilbo_trades.parquet')
t = tr[(tr.ep_id == 'NVDA-043') & (tr.variant == 'retest') & (tr.bucket == 'W1') &
       (tr.offset == 0.0) & (tr.vehicle == 'long')].iloc[0]

df5 = load_5m('NVDA')
h, _ = hourly_and_daily(df5)
h = compute_phase_oscillator(h)
for p in [8, 13, 21, 48]:
    h[f'ema{p}'] = ema(h['close'], p)
win = h.loc['2026-03-06':'2026-03-27']

start = pd.Timestamp(e.start_ts_et)
i = h.index.get_loc(start)
box_bars = h.index[i:i + 5]
entry_ts = pd.Timestamp(t.entry_ts)

# option TP100 exit time + premium path from minute bars
con = sqlite3.connect(STUDY / 'option_bars.sqlite')
ob = pd.read_sql(f"SELECT t,h,c FROM bars WHERE ticker='{t.contract}' ORDER BY t", con)
con.close()
ob['ts'] = pd.to_datetime(ob.t, unit='ms', utc=True).dt.tz_convert('America/New_York')
entry_ms = int(entry_ts.timestamp() * 1000)
tp_px = round(t.entry_px * 2, 2)
hit = ob[(ob.t > entry_ms) & (ob.h >= tp_px)]
exit_ts = hit.ts.iloc[0] if len(hit) else None

def ts2u(x):
    return int(pd.Timestamp(x).timestamp())

data = {
    'candles': [[ts2u(ix), round(r.open, 2), round(r.high, 2), round(r.low, 2),
                 round(r.close, 2), int(r.po_compression)]
                for ix, r in win.iterrows()],
    'emas': {str(p): [[ts2u(ix), round(v, 2)] for ix, v in win[f'ema{p}'].items()]
             for p in [8, 13, 21, 48]},
    'po': [[ts2u(ix), round(r.phase_oscillator, 1), int(r.po_compression)]
           for ix, r in win.iterrows()],
    'box': {'hi': float(t.box_hi), 'lo': float(t.box_lo),
            'from': ts2u(box_bars[0]), 'to': ts2u(entry_ts)},
    'marks': {
        'box_lock': ts2u(box_bars[-1]),
        'entry': ts2u(entry_ts.floor('h') + pd.Timedelta(minutes=30) if entry_ts.minute < 30 else entry_ts),
        'exit': ts2u(exit_ts) if exit_ts is not None else None,
    },
    'trade': {'contract': t.contract, 'entry_px': float(t.entry_px), 'tp_px': tp_px,
              'entry_label': f"BUY {t.contract.split(':')[1]} @ {t.entry_px:.2f}",
              'exit_label': f"TP +100% @ {tp_px:.2f}" if exit_ts is not None else 'expiry'},
}

cloud_js = Path('/tmp/claude-0/-root-spy/9693d299-b8b3-4dbd-9193-0dff40236dd0/scratchpad/cloud_primitive.js').read_text()

html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>STYLE PREVIEW — PO Compression Options example trade</title>
<script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
 body{margin:0;background:#0b0e14;color:#e5edf7;font-family:ui-sans-serif,system-ui,sans-serif}
 .wrap{max-width:1200px;margin:0 auto;padding:14px}
 h1{font-size:18px;margin:0 0 2px} .sub{color:#93a4b8;font-size:13px;margin:0 0 10px}
 .banner{background:#7c2d12;border:1px solid #f97316;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:10px}
 #price{height:430px} #osc{height:170px}
 .legend{color:#93a4b8;font-size:12px;margin:8px 0}
 .k{display:inline-block;margin-right:14px}.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
</style></head><body><div class="wrap">
<div class="banner"><strong>STYLE PREVIEW</strong> — one real trade from the PO-compression options study, rendered in the /charts/ Saty style. Verify before the full study page is built.</div>
<h1>NVDA — hourly · mature-box retest · down-break put</h1>
<p class="sub">Box = first 5 compression bars (2026-03-16). Break down → retest of box low 2026-03-18 09:40 ET → bought Mar-20 182.5P @ 2.65 (2 DTE) → TP +100% same day. Hold-to-expiry would have made +258%.</p>
<div id="price"></div><div id="osc"></div>
<div class="legend">
 <span class="k"><span class="sw" style="background:#b0b0b0"></span>compression candle</span>
 <span class="k"><span class="sw" style="background:#22c55e"></span>up vs EMA48</span>
 <span class="k"><span class="sw" style="background:#ef4444"></span>down vs EMA48</span>
 <span class="k"><span class="sw" style="background:rgba(34,197,94,.5)"></span>fast cloud 8/21</span>
 <span class="k"><span class="sw" style="background:rgba(96,165,250,.5)"></span>slow cloud 13/48</span>
 <span class="k"><span class="sw" style="background:#e040fb"></span>PO compression</span>
 <span class="k"><span class="sw" style="background:#64748b"></span>Bilbo box</span>
</div>
</div>
<script>
__CLOUD__
const D = __DATA__;
const {createChart} = LightweightCharts;
const opts = {layout:{background:{color:'#0b0e14'},textColor:'#93a4b8'},grid:{vertLines:{color:'#151a24'},horzLines:{color:'#151a24'}},timeScale:{timeVisible:true,secondsVisible:false},rightPriceScale:{borderColor:'#1f2a44'}};
const pc = createChart(document.getElementById('price'), opts);
const oc = createChart(document.getElementById('osc'), opts);

const emaSeries = {};
const EMA_STYLE = {'8':['transparent',0],'13':['transparent',0],'21':['#ffffff',2],'48':['transparent',0]};
for (const p of ['8','13','21','48']) {
  emaSeries[p] = pc.addLineSeries({color:EMA_STYLE[p][0], lineWidth:EMA_STYLE[p][1]||1, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false});
  emaSeries[p].setData(D.emas[p].map(([t,v])=>({time:t,value:v})));
}
try {
  emaSeries['8'].attachPrimitive(new CloudFillPrimitive(emaSeries['8'], emaSeries['21'], 'rgba(34,197,94,0.35)','rgba(239,68,68,0.35)'));
  emaSeries['13'].attachPrimitive(new CloudFillPrimitive(emaSeries['13'], emaSeries['48'], 'rgba(96,165,250,0.25)','rgba(249,115,22,0.25)'));
} catch(err) { console.warn('cloud', err); }

const e48 = {}; D.emas['48'].forEach(([t,v])=>{e48[t]=v;});
const cs = pc.addCandlestickSeries();
cs.setData(D.candles.map(([t,o,h,l,c,comp])=>{
  const up = c>=o, above = c >= (e48[t] ?? c);
  let uC,dC;
  if (comp) {uC='#b0b0b0';dC='#808080';}
  else if (above) {uC='#22c55e';dC='#60a5fa';}
  else {uC='#f97316';dC='#ef4444';}
  const col = up?uC:dC;
  return {time:t,open:o,high:h,low:l,close:c,color:col,borderColor:col,wickColor:col+'aa'};
}));

// Bilbo box: top/bottom segments over the box->entry window
for (const lvl of [D.box.hi, D.box.lo]) {
  const s = pc.addLineSeries({color:'#64748b',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  s.setData(D.candles.filter(c=>c[0]>=D.box.from && c[0]<=D.box.to).map(c=>({time:c[0],value:lvl})));
}

const marks = [];
marks.push({time:D.marks.box_lock,position:'aboveBar',color:'#94a3b8',shape:'circle',text:'box locked'});
marks.push({time:D.marks.entry,position:'aboveBar',color:'#facc15',shape:'arrowDown',text:D.trade.entry_label});
if (D.marks.exit) marks.push({time:D.marks.exit,position:'belowBar',color:'#22c55e',shape:'arrowUp',text:D.trade.exit_label});
cs.setMarkers(marks.sort((a,b)=>a.time-b.time));

const po = oc.addLineSeries({lineWidth:2,priceLineVisible:false,lastValueVisible:false});
po.setData(D.po.map(([t,v,comp])=>({time:t,value:v,color: comp? '#e040fb' : (v>=0?'#69f0ae':'#ef4444')})));
for (const [p,c] of [[100,'#64748b88'],[61.8,'#64748b66'],[23.6,'#64748b44'],[-23.6,'#64748b44'],[-61.8,'#64748b66'],[-100,'#64748b88'],[0,'#64748b33']])
  po.createPriceLine({price:p,color:c,lineWidth:1,lineStyle:2,axisLabelVisible:false,title:''});

const sync = (a,b)=>{a.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r)b.timeScale().setVisibleLogicalRange(r);});};
sync(pc,oc); sync(oc,pc);
pc.timeScale().fitContent();
new ResizeObserver(()=>{pc.applyOptions({});oc.applyOptions({});}).observe(document.body);
</script></body></html>"""
html = html.replace('__CLOUD__', cloud_js).replace('__DATA__', json.dumps(data))
out = Path('/root/spy/site/po-comp-example-preview.html')
out.write_text(html)
print("wrote", out, "| entry", entry_ts, "| exit", exit_ts, "| box", t.box_hi, t.box_lo)

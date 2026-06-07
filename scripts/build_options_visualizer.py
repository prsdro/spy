#!/usr/bin/env python3
"""Build milkmantrades.com options visualizer with SPX 0DTE + 1DTE overlay."""
import json
import sqlite3
from pathlib import Path

DBS = {
    '0DTE': Path('/root/tradelab/data/massive_spxw_full_day_20260529_7560_7610_cp.sqlite'),
    '1DTE': Path('/root/tradelab/data/massive_spxw_1dte_full_day_20260529_exp20260601_7560_7610_cp.sqlite'),
}
EXPIRIES = {'0DTE': '2026-05-29', '1DTE': '2026-06-01'}
OUT_DATA = Path('/root/spy/site/data/options-visualizer/spxw-2026-05-29-0dte-1dte.json')
OUT_PAGE = Path('/root/spy/site/options-visualizer.html')
START_CT = '2026-05-29T08:30:00-05:00'
END_CT = '2026-05-29T15:00:00-05:00'
STRIKES = list(range(7560, 7611, 5))

HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Milkman Options Visualizer — SPXW 0DTE/1DTE</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root { color-scheme: dark; --bg:#05070d; --panel:#0b1020; --ink:#e5edf7; --muted:#93a4b8; --grid:#1d2940; --accent:#38bdf8; }
    * { box-sizing:border-box; }
    body { margin:0; background:linear-gradient(180deg,#05070d,#090d18); color:var(--ink); font-family:Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
    .wrap { max-width:1600px; margin:0 auto; padding:10px; }
    header { display:flex; gap:10px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; margin-bottom:8px; }
    h1 { margin:0; font-size:clamp(18px,3vw,32px); letter-spacing:-.03em; }
    .sub { color:var(--muted); margin-top:4px; font-size:13px; }
    .controls { display:flex; flex-wrap:wrap; align-items:center; gap:8px; background:rgba(11,16,32,.75); padding:8px 10px; border:1px solid #1f2a44; border-radius:14px; }
    button { cursor:pointer; color:#dbeafe; background:#111827; border:1px solid #334155; padding:7px 10px; border-radius:999px; font-weight:800; }
    button.active { background:#0e7490; border-color:#67e8f9; color:#fff; }
    input[type="time"] { color:#e5edf7; background:#111827; border:1px solid #334155; border-radius:10px; padding:7px 8px; font-weight:800; }
    .hint,.status { color:var(--muted); font-size:12px; }
    .grid { display:grid; grid-template-rows:minmax(410px,51vh) minmax(410px,43vh); gap:10px; }
    .card { background:rgba(11,16,32,.92); border:1px solid #1f2a44; border-radius:18px; padding:10px; box-shadow:0 20px 70px rgba(0,0,0,.35); min-height:0; }
    .card-title { display:flex; justify-content:space-between; gap:8px; align-items:baseline; margin:0 0 8px; color:#cbd5e1; font-size:14px; font-weight:800; }
    .chart { width:100%; height:calc(100% - 34px); min-height:280px; touch-action:none; overscroll-behavior:contain; position:relative; }
    #legend { color:#94a3b8; font-size:12px; font-weight:800; white-space:nowrap; }
    .line-label-layer { position:absolute; inset:0; pointer-events:none; z-index:5; overflow:hidden; }
    .line-label { position:absolute; right:7px; transform:translateY(-50%); max-width:82px; padding:2px 5px; border-radius:6px; background:rgba(5,7,13,.74); border:1px solid rgba(148,163,184,.28); font-size:10px; line-height:1.05; font-weight:900; white-space:nowrap; text-shadow:0 1px 2px #000; box-shadow:0 1px 6px rgba(0,0,0,.35); }
    #filterPanel { margin:0 0 8px; background:rgba(11,16,32,.88); border:1px solid #1f2a44; border-radius:14px; padding:8px 10px; touch-action:manipulation; }
    #filterPanel summary { cursor:pointer; color:#dbeafe; font-weight:900; list-style:none; display:flex; justify-content:space-between; gap:8px; }
    #filterPanel summary::-webkit-details-marker { display:none; }
    .filter-actions { display:flex; flex-wrap:wrap; gap:6px; margin:9px 0; }
    .filter-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(116px,1fr)); gap:6px; }
    .chip { display:inline-flex; align-items:center; justify-content:center; gap:5px; white-space:nowrap; color:#cbd5e1; padding:7px 6px; border:1px solid #24324f; border-radius:999px; background:#0f172a; cursor:pointer; user-select:none; font-size:12px; font-weight:800; }
    .chip input { margin:0; accent-color:#38bdf8; }
    .chip.off { opacity:.35; text-decoration:line-through; }
    .swatch { width:14px; height:3px; border-radius:3px; display:inline-block; }
    @media (max-width:700px) {
      .wrap { padding:6px; } header { gap:6px; margin-bottom:6px; } h1 { font-size:18px; } .sub { font-size:11px; }
      .controls { width:100%; gap:6px; padding:6px; } button { padding:6px 8px; font-size:12px; }
      .grid { grid-template-rows:calc((100vh - 184px) * .50) calc((100vh - 184px) * .50); gap:6px; min-height:770px; }
      .card { padding:7px; border-radius:12px; } .card-title { font-size:12px; margin-bottom:5px; flex-wrap:wrap; }
      .chart { height:calc(100% - 28px); min-height:285px; } #filterPanel { padding:7px; margin-bottom:6px; }
      #filterPanel summary { font-size:12px; } .filter-actions { gap:4px; margin:7px 0; } .filter-actions button { padding:6px 7px; }
      .filter-grid { grid-template-columns:repeat(3,minmax(0,1fr)); gap:5px; } .chip { padding:6px 4px; font-size:10px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div><h1>Milkman Options Visualizer</h1><div class="sub" id="subtitle">Loading…</div></div>
      <div class="controls">
        <span class="hint">DTE:</span><button id="bothDteBtn">Both</button><button id="zeroDteBtn">0DTE</button><button id="oneDteBtn">1DTE</button>
        <span class="hint">Option pane:</span><button id="rawBtn">Raw $</button><button id="indexedBtn">Indexed</button>
        <span class="hint">Show:</span><button id="bothSideBtn">Calls+Puts</button><button id="callsBtn">Calls</button><button id="putsBtn">Puts</button>
        <span class="hint">Index from:</span><input id="entryTime" type="time" min="08:30" max="15:00" step="60" value="08:30" /><button id="entryBtn">Apply</button>
        <span class="status" id="status"></span>
      </div>
    </header>
    <details id="filterPanel">
      <summary><span>Filters: <span id="filterSummary">loading…</span></span><span>tap to edit ▾</span></summary>
      <div class="filter-actions">
        <button id="defaultBtn">ATM/+10/+20</button><button id="showAllBtn">Show all</button><button id="hideAllBtn">Hide all</button>
        <button id="nearAtmBtn">Near ATM</button><button id="callsOnlyBtn">Calls only</button><button id="putsOnlyBtn">Puts only</button>
      </div>
      <div id="filterGrid" class="filter-grid"></div>
    </details>
    <div class="grid">
      <section class="card"><div class="card-title"><span>SPX cash-index candles — 1m full RTH</span><span>I:SPX · CT</span></div><div id="priceChart" class="chart"></div></section>
      <section class="card"><div class="card-title"><span id="lineTitle">SPXW options</span><div id="legend"></div></div><div id="optionChart" class="chart"></div></section>
    </div>
  </div>
<script>
const DATA_URL = '/data/options-visualizer/spxw-2026-05-29-0dte-1dte.json';
const qs = new URLSearchParams(location.search);
let dteMode = ['both','0DTE','1DTE'].includes(qs.get('dte')) ? qs.get('dte') : 'both';
let mode = qs.get('mode') === 'indexed' ? 'indexed' : 'raw';
let side = ['call','put','both'].includes(qs.get('side')) ? qs.get('side') : 'both';
let entryTime = /^\d{2}:\d{2}$/.test(qs.get('entry') || '') ? qs.get('entry') : '08:30';
let hidden = new Set((qs.get('hide') || '').split(',').filter(Boolean));
// Blank/no hide means the clean default view, not "show everything".
let hideParamProvided = qs.has('hide') && (qs.get('hide') || '').trim() !== '';
const strikeColors = {
  7560:'#e879f9', 7565:'#a78bfa', 7570:'#60a5fa', 7575:'#22d3ee', 7580:'#34d399', 7585:'#a3e635',
  7590:'#facc15', 7595:'#fb923c', 7600:'#f472b6', 7605:'#f87171', 7610:'#c084fc'
};
let fullPayload, priceChart, optionChart, candleSeries, optionSeries = [], optionLineMeta = [], optionLabelLayer;
window.__chartState = { ready:false, errors:[] };
window.addEventListener('error', e => window.__chartState.errors.push(String(e.message || e.error || e)));
function toUnixSeconds(iso){ return Math.floor(new Date(iso).getTime()/1000); }
function ctTimeLabel(time){ const sec = typeof time === 'number' ? time : (time.timestamp || 0); return new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(sec*1000)); }
function rowHHMM(row){ return ctTimeLabel(toUnixSeconds(row.timestamp_ct)); }
function datasets(){ return dteMode === 'both' ? ['0DTE','1DTE'] : [dteMode]; }
function dataset(){ return fullPayload.datasets['0DTE'] || fullPayload.datasets['1DTE']; }
function defaultStrikes(){ return fullPayload.default_strikes || [7580,7590,7600]; }
function combinedOptions(){ const out=[]; datasets().forEach(d => (fullPayload.datasets[d]?.options || []).forEach(o => out.push({...o, dte_label:d, uid:`${d}:${o.label}`, display_label:`${d} ${o.label}`}))); return out; }
function visibleOpts(){ return combinedOptions().filter(o => (side === 'both' || o.option_type === side) && !hidden.has(o.uid)); }
function colorFor(opt){
  const base = strikeColors[opt.strike] || '#94a3b8';
  // Same strike keeps the same hue; DTE/side are encoded by dash/width/opacity so nearby strikes are no longer all green.
  return base;
}
function lineStyleFor(opt){ return opt.dte_label === '1DTE' ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid; }
function getBaseRow(opt){ return opt.rows.find(r => rowHHMM(r) === entryTime) || opt.rows.find(r => rowHHMM(r) > entryTime) || opt.rows[0]; }
function updateUrl(){ const p = new URLSearchParams(); p.set('dte', dteMode); p.set('mode', mode); p.set('side', side); p.set('entry', entryTime); if (hidden.size) p.set('hide', Array.from(hidden).sort().join(',')); history.replaceState(null, '', '?' + p.toString()); }
function applyDefaultHidden(){ const keep = new Set(defaultStrikes()); hidden.clear(); combinedOptions().forEach(o => { if (!keep.has(o.strike)) hidden.add(o.uid); }); hideParamProvided = true; updateUrl(); }
function setActive(){
  bothDteBtn.classList.toggle('active', dteMode==='both'); zeroDteBtn.classList.toggle('active', dteMode==='0DTE'); oneDteBtn.classList.toggle('active', dteMode==='1DTE');
  rawBtn.classList.toggle('active', mode==='raw'); indexedBtn.classList.toggle('active', mode==='indexed');
  bothSideBtn.classList.toggle('active', side==='both'); callsBtn.classList.toggle('active', side==='call'); putsBtn.classList.toggle('active', side==='put'); entryTimeEl.value = entryTime;
  const visible = visibleOpts().length, total = combinedOptions().length;
  status.textContent = mode === 'indexed' ? `${dteMode} · ${visible}/${total} · 100 at ${entryTime} CT` : `${dteMode} · ${visible}/${total} · premiums in $`;
  lineTitle.textContent = mode === 'indexed' ? `SPXW ${dteMode} ${side} — indexed to ${entryTime} CT` : `SPXW ${dteMode} ${side} — raw option prices`;
}
function chartOpts(height, interactive=true){ return { height, layout:{background:{color:'#0b1020'},textColor:'#cbd5e1',fontSize:12}, grid:{vertLines:{color:'#1d2940'},horzLines:{color:'#1d2940'}}, rightPriceScale:{borderColor:'#334155',scaleMargins:{top:.06,bottom:.10}}, timeScale:{borderColor:'#334155',timeVisible:true,secondsVisible:false,rightOffset:2,barSpacing:5,tickMarkFormatter:t=>ctTimeLabel(t)}, localization:{timeFormatter:t=>ctTimeLabel(t)+' CT'}, crosshair:{mode:LightweightCharts.CrosshairMode.Normal}, handleScroll:{mouseWheel:false,pressedMouseMove:interactive,horzTouchDrag:interactive,vertTouchDrag:false}, handleScale:{axisPressedMouseMove:false,mouseWheel:false,pinch:true}, kineticScroll:{mouse:true,touch:true} }; }
function renderLegend(){ const visible=visibleOpts().length,total=combinedOptions().length; legend.textContent=`${visible}/${total} visible`; filterSummary.textContent = `${dteMode} · ${visible}/${total} · default ${defaultStrikes().join('/')}`; }
function refresh({preserveRange=true}={}){ updateUrl(); renderOptions({preserveRange}); renderLegend(); renderFilterPanel(); setActive(); }
function setHiddenByPredicate(predicate){ hidden.clear(); combinedOptions().forEach(o => { if (predicate(o)) hidden.add(o.uid); }); refresh(); }
function renderFilterPanel(){ filterGrid.innerHTML=''; combinedOptions().forEach(opt => { const label=document.createElement('label'); label.className='chip'+(hidden.has(opt.uid)?' off':''); label.innerHTML=`<input type="checkbox" ${hidden.has(opt.uid)?'':'checked'} data-label="${opt.uid}"><span class="swatch" style="background:${colorFor(opt)}"></span>${opt.display_label}`; label.querySelector('input').onchange=e=>{ if(e.target.checked) hidden.delete(opt.uid); else hidden.add(opt.uid); refresh(); }; filterGrid.appendChild(label); }); }
function labelText(opt){ return `${opt.dte_label.replace('DTE','')} ${opt.label}`; }
function updateOptionLabels(){
  if(!optionLabelLayer || !optionChart) return;
  const range = optionChart.timeScale().getVisibleRange();
  const h = optionLabelLayer.clientHeight || document.getElementById('optionChart').clientHeight;
  const minGap = 18, topPad = 10, botPad = 12;
  const labels = optionLineMeta.map(m => {
    const rows = range ? m.data.filter(p => p.value !== undefined && p.time >= range.from && p.time <= range.to) : m.data.filter(p => p.value !== undefined);
    const last = rows[rows.length - 1] || m.data.filter(p => p.value !== undefined).slice(-1)[0];
    if(!last) return null;
    const y = m.series.priceToCoordinate(last.value);
    if(y == null || !Number.isFinite(y) || y < -24 || y > h + 24) return null;
    return {y:Math.max(topPad, Math.min(h-botPad, y)), opt:m.opt, text:labelText(m.opt), color:colorFor(m.opt)};
  }).filter(Boolean).sort((a,b)=>a.y-b.y);
  for(let i=1;i<labels.length;i++) labels[i].y = Math.max(labels[i].y, labels[i-1].y + minGap);
  for(let i=labels.length-2;i>=0;i--) labels[i].y = Math.min(labels[i].y, labels[i+1].y - minGap);
  labels.forEach(l => { l.y = Math.max(topPad, Math.min(h-botPad, l.y)); });
  const visibleLabels=[];
  labels.forEach(l => { if(!visibleLabels.length || l.y - visibleLabels[visibleLabels.length-1].y >= minGap - .1) visibleLabels.push(l); });
  optionLabelLayer.innerHTML = visibleLabels.map(l => `<span class="line-label" style="top:${l.y}px;color:${l.color};border-color:${l.color}66">${l.text}</span>`).join('');
  if(window.__chartState) window.__chartState.optionLabels = visibleLabels.map(l => l.text);
}
function renderOptions({preserveRange=false}={}){
  const prev = preserveRange ? optionChart.timeScale().getVisibleRange() : null; optionSeries.forEach(s=>optionChart.removeSeries(s)); optionSeries=[]; optionLineMeta=[];
  visibleOpts().forEach(opt => { const s=optionChart.addLineSeries({ color:colorFor(opt), lineWidth: opt.dte_label==='1DTE'?2:3, lineStyle:lineStyleFor(opt), priceLineVisible:false, lastValueVisible:false, title:'' }); const baseRow=getBaseRow(opt), base=baseRow?baseRow.close:null; const data=opt.rows.map(r => { const time=toUnixSeconds(r.timestamp_ct); if(mode==='indexed' && rowHHMM(r)<entryTime) return {time}; const value = mode==='indexed' ? (r.close/base)*100 : r.close; return Number.isFinite(value)?{time,value}:{time}; }); s.setData(data); optionSeries.push(s); optionLineMeta.push({series:s,opt,data}); });
  optionChart.priceScale('right').applyOptions({autoScale:true,mode:LightweightCharts.PriceScaleMode.Normal}); if(prev) optionChart.timeScale().setVisibleRange(prev); if(window.__chartState) window.__chartState.visibleOptions=optionSeries.length; requestAnimationFrame(updateOptionLabels);
}
function setupBottomDrag(optEl){ let dragging=false,startX=0,baseRange=null,raf=null,moved=false; const applyBoth=r=>{ priceChart.timeScale().setVisibleRange(r); optionChart.timeScale().setVisibleRange(r); window.__chartState.lastCoupledRange=r; }; optEl.addEventListener('pointerdown',e=>{ if(e.pointerType==='mouse'&&e.button!==0)return; dragging=true;moved=false;startX=e.clientX;baseRange=priceChart.timeScale().getVisibleRange()||optionChart.timeScale().getVisibleRange();optEl.setPointerCapture?.(e.pointerId); },{passive:false}); optEl.addEventListener('pointermove',e=>{ if(!dragging||!baseRange)return; e.preventDefault(); moved=true; const span=baseRange.to-baseRange.from, secPerPx=span/Math.max(1,optEl.clientWidth), dx=e.clientX-startX, next={from:baseRange.from-dx*secPerPx,to:baseRange.to-dx*secPerPx}; cancelAnimationFrame(raf); raf=requestAnimationFrame(()=>applyBoth(next)); },{passive:false}); const stop=e=>{ if(!dragging)return; dragging=false; optEl.releasePointerCapture?.(e.pointerId); if(moved)e.preventDefault(); }; optEl.addEventListener('pointerup',stop,{passive:false}); optEl.addEventListener('pointercancel',stop,{passive:false}); }
function renderAll(){
  const priceEl=document.getElementById('priceChart'), optEl=document.getElementById('optionChart');
  optionLabelLayer=document.createElement('div'); optionLabelLayer.className='line-label-layer'; optEl.appendChild(optionLabelLayer);
  priceChart=LightweightCharts.createChart(priceEl, chartOpts(priceEl.clientHeight,true));
  optionChart=LightweightCharts.createChart(optEl, chartOpts(optEl.clientHeight,false));
  candleSeries=priceChart.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',wickUpColor:'#86efac',wickDownColor:'#fca5a5',borderVisible:false});
  candleSeries.setData(dataset().spx_1m.map(r=>({time:toUnixSeconds(r.timestamp_ct),open:r.open,high:r.high,low:r.low,close:r.close})));
  priceChart.timeScale().fitContent(); renderOptions(); optionChart.timeScale().fitContent(); renderLegend(); renderFilterPanel(); setupBottomDrag(optEl);
  subtitle.textContent = `${fullPayload.date} · overlay 0DTE + 1DTE · default strikes ATM/${defaultStrikes()[1]}/${defaultStrikes()[2]} · ${dataset().spx_1m.length} SPX 1m candles`;
  setActive();
  let syncing=false,pendingSync=null;
  function rangesEqual(a,b){return !!a&&!!b&&Math.abs(a.from-b.from)<.001&&Math.abs(a.to-b.to)<.001;}
  const sync=(source,target)=>source.timeScale().subscribeVisibleTimeRangeChange(r=>{
    if(!r||syncing)return;
    cancelAnimationFrame(pendingSync);
    pendingSync=requestAnimationFrame(()=>{
      const cur=target.timeScale().getVisibleRange(); if(rangesEqual(cur,r)){ updateOptionLabels(); return; }
      syncing=true; try{target.timeScale().setVisibleRange(r); updateOptionLabels();}finally{requestAnimationFrame(()=>{syncing=false;});}
    });
  });
  sync(priceChart,optionChart);
  optionChart.timeScale().subscribeVisibleTimeRangeChange(()=>requestAnimationFrame(updateOptionLabels));
  const resize=()=>{priceChart.applyOptions({width:priceEl.clientWidth,height:priceEl.clientHeight});optionChart.applyOptions({width:optEl.clientWidth,height:optEl.clientHeight});requestAnimationFrame(updateOptionLabels);};
  window.addEventListener('resize',resize); resize();
  window.__chartState={ready:true,dteMode,mode,side,rows:Object.fromEntries(Object.entries(fullPayload.datasets).map(([k,v])=>[k,v.minute_rows_total])),spxBars:dataset().spx_1m.length,combinedOptions:combinedOptions().length,visibleOptions:optionSeries.length,defaultStrikes:defaultStrikes(),errors:[]};
  requestAnimationFrame(updateOptionLabels);
}

const entryTimeEl=document.getElementById('entryTime'); entryTimeEl.value=entryTime;
bothDteBtn.onclick=()=>{dteMode='both'; if(!hideParamProvided) applyDefaultHidden(); else refresh();}; zeroDteBtn.onclick=()=>{dteMode='0DTE'; refresh();}; oneDteBtn.onclick=()=>{dteMode='1DTE'; refresh();};
rawBtn.onclick=()=>{mode='raw'; refresh();}; indexedBtn.onclick=()=>{mode='indexed'; entryTime=entryTimeEl.value||'08:30'; refresh();};
bothSideBtn.onclick=()=>{side='both'; refresh();}; callsBtn.onclick=()=>{side='call'; refresh();}; putsBtn.onclick=()=>{side='put'; refresh();};
defaultBtn.onclick=()=>applyDefaultHidden(); showAllBtn.onclick=()=>setHiddenByPredicate(()=>false); hideAllBtn.onclick=()=>setHiddenByPredicate(()=>true); nearAtmBtn.onclick=()=>{ const lo=defaultStrikes()[0]-10, hi=defaultStrikes()[0]+20; setHiddenByPredicate(o=>o.strike<lo||o.strike>hi); }; callsOnlyBtn.onclick=()=>{side='call'; refresh();}; putsOnlyBtn.onclick=()=>{side='put'; refresh();};
entryBtn.onclick=()=>{entryTime=entryTimeEl.value||'08:30'; mode='indexed'; refresh();}; entryTimeEl.onchange=()=>{entryTime=entryTimeEl.value||'08:30'; if(mode==='indexed') refresh();};
fetch(DATA_URL,{cache:'no-store'}).then(r=>r.json()).then(j=>{ fullPayload=j; if(!hideParamProvided) applyDefaultHidden(); renderAll(); }).catch(e=>{ document.body.insertAdjacentHTML('afterbegin', `<pre>${String(e)}</pre>`); throw e; });
</script>
</body>
</html>
'''


def row_to_bar(r):
    return {
        'timestamp_ct': r['timestamp_ct'], 'timestamp_utc': r['timestamp_utc'],
        'open': r['open'], 'high': r['high'], 'low': r['low'], 'close': r['close'],
        'volume': r['volume'], 'vwap': r['vwap'], 'transactions': r['transactions'],
    }


def build_dataset(label, db):
    if not db.exists():
        raise SystemExit(f'Missing DB: {db}')
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        """SELECT source_ticker, symbol, instrument_type, strike, option_type,
                  timestamp_ct, timestamp_utc, open, high, low, close, volume, vwap, transactions, epoch_ms
           FROM minute_bars
           WHERE timestamp_ct >= ? AND timestamp_ct <= ?
           ORDER BY source_ticker, epoch_ms""",
        (START_CT, END_CT),
    )]
    spx = [r for r in rows if r['source_ticker'] == 'I:SPX']
    expiry = EXPIRIES[label]
    yymmdd = expiry[2:4] + expiry[5:7] + expiry[8:10]
    options = []
    for option_type in ('call', 'put'):
        right = 'C' if option_type == 'call' else 'P'
        for strike in STRIKES:
            ticker = f'O:SPXW{yymmdd}{right}{strike * 1000:08d}'
            opt_rows = [r for r in rows if r['source_ticker'] == ticker]
            if not opt_rows:
                continue
            start = opt_rows[0]['close']
            end = opt_rows[-1]['close']
            options.append({
                'ticker': ticker, 'label': f'{strike}{right}', 'strike': strike,
                'option_type': option_type, 'rows_count': len(opt_rows),
                'raw_start': start, 'raw_end': end,
                'indexed_end': (end / start) * 100 if start else None,
                'rows': [row_to_bar(r) for r in opt_rows],
            })
    return {
        'title': f'SPX 1-minute candles + full-day SPXW {label} call/put strike lines',
        'date': '2026-05-29', 'expiry_date': expiry, 'dte_label': label,
        'window_ct': '08:30–15:00 America/Chicago', 'data_symbol': 'I:SPX',
        'source_note': 'True SPX cash-index candles from Massive I:SPX; SPXW option premiums from Massive 1-minute option aggregates.',
        'strikes': STRIKES, 'spx_1m': [row_to_bar(r) for r in spx], 'options': options,
        'call_count': sum(1 for o in options if o['option_type'] == 'call'),
        'put_count': sum(1 for o in options if o['option_type'] == 'put'),
        'minute_rows_total': len(rows),
        'min_option_rows': min((o['rows_count'] for o in options), default=0),
        'max_option_rows': max((o['rows_count'] for o in options), default=0),
    }


def default_strikes_from_spx(spx_rows):
    first = spx_rows[0]['open'] if spx_rows else 7580
    atm = min(STRIKES, key=lambda s: abs(s - first))
    return [s for s in (atm, atm + 10, atm + 20) if s in STRIKES]


def main():
    datasets = {k: build_dataset(k, v) for k, v in DBS.items()}
    payload = {
        'title': 'Milkman Options Visualizer',
        'date': '2026-05-29',
        'default_strikes': default_strikes_from_spx(datasets['0DTE']['spx_1m']),
        'datasets': datasets,
    }
    OUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    OUT_PAGE.parent.mkdir(parents=True, exist_ok=True)
    OUT_DATA.write_text(json.dumps(payload, separators=(',', ':'), ensure_ascii=False))
    OUT_PAGE.write_text(HTML)
    print(json.dumps({
        'page': str(OUT_PAGE), 'data': str(OUT_DATA),
        'default_strikes': payload['default_strikes'],
        'datasets': {k: {'spx_1m': len(v['spx_1m']), 'options': len(v['options']), 'rows_total': v['minute_rows_total'], 'min_option_rows': v['min_option_rows'], 'max_option_rows': v['max_option_rows']} for k, v in datasets.items()},
    }, indent=2))


if __name__ == '__main__':
    main()

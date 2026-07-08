#!/usr/bin/env python3
"""Build site/bilbo-box-options.html — PO-compression box-breakout options study.
Three example-trade charts in the /charts/ Saty style (approved via
site/po-comp-example-preview.html) + headline stats. Rerunnable."""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, '/root/spy')
from fetch_po_comp_options import load_5m, hourly_and_daily
from indicators import compute_phase_oscillator, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
OUT = Path('/root/spy/site/bilbo-box-options.html')
CLOUD = Path('/tmp/claude-0/-root-spy/9693d299-b8b3-4dbd-9193-0dff40236dd0/scratchpad/cloud_primitive.js').read_text()

EXAMPLES = [
    ('NVDA-286', 'win_up', "Up-break winner — NVDA, Apr 9 2026",
     "4-bar box formed on the afternoon of Apr 8-9. Price broke the box top at 3:55pm ET; "
     "immediate entry, Apr-17 185C @ 2.77. TP +100% hit the next session. Holding to expiry "
     "would have returned +502% — winners out of these boxes run."),
    ('GOOGL-101', 'win_dn', "Down-break winner — GOOGL, Feb 18 2025",
     "Box broke down mid-session; Feb-28 182.5P @ 2.61 at the break. TP +100% hit within two "
     "sessions. Hold-to-expiry: +368%. Down-breaks work as well as up-breaks (+9.5% vs +7.2% avg) — "
     "buy the direction of the break, either way."),
    ('NVDA-217', 'win_lose', "Stop-out — NVDA, Nov 24 2025",
     "The honest one: down-break, Nov-28 177.5P @ 3.75, no follow-through — premium bled to the "
     "−50% stop. Held to expiry this lost −86%. The bracket's job is exactly this: half the "
     "premium walks away."),
]

tr = pd.read_parquet(STUDY / 'v3_eth_trades.parquet')
ev = pd.read_csv(STUDY / 'events_v2_eth.csv')
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)

charts = []
hcache = {}
for ep, kind, title, caption in EXAMPLES:
    t = tr[(tr.ep_id == ep) & (tr.variant == 'immediate') & (tr.vehicle == 'long') &
           (tr.offset == 0.0) & (tr.bucket == 'W1')].iloc[0]
    e = ev[ev.ep_id == ep].iloc[0]
    tkr = t.ticker
    if tkr not in hcache:
        h, _ = hourly_and_daily(load_5m(tkr), session='ETH')
        h = compute_phase_oscillator(h)
        for p in [8, 13, 21, 48]:
            h[f'ema{p}'] = ema(h['close'], p)
        hcache[tkr] = h
    h = hcache[tkr]
    entry_ts = pd.Timestamp(t.entry_ts)
    start = pd.Timestamp(e.start_ts_et)

    ob = pd.read_sql(f"SELECT t,h,l FROM bars WHERE ticker='{t.contract}' ORDER BY t", con)
    entry_ms = int(entry_ts.timestamp() * 1000)
    if kind == 'win_lose':
        lvl = t.entry_px * 0.5
        hit = ob[(ob.t > entry_ms) & (ob.l <= lvl)]
        exit_label = f"STOP −50% @ {lvl:.2f}"
    else:
        lvl = t.entry_px * 2
        hit = ob[(ob.t > entry_ms) & (ob.h >= lvl)]
        exit_label = f"TP +100% @ {lvl:.2f}"
    exit_ts = pd.Timestamp(hit.t.iloc[0], unit='ms', tz='America/New_York') if len(hit) else None

    w0 = start - pd.Timedelta(days=4)
    w1_ = (exit_ts or entry_ts) + pd.Timedelta(days=4)
    win = h[(h.index >= w0) & (h.index <= w1_)]
    u = lambda x: int(pd.Timestamp(x).timestamp())
    charts.append({
        'id': ep.replace('-', ''), 'title': title, 'caption': caption,
        'candles': [[u(i), round(r.open, 2), round(r.high, 2), round(r.low, 2),
                     round(r.close, 2), int(r.po_compression)] for i, r in win.iterrows()],
        'emas': {str(p): [[u(i), round(v, 2)] for i, v in win[f'ema{p}'].items()]
                 for p in [8, 13, 21, 48]},
        'po': [[u(i), round(r.phase_oscillator, 1), int(r.po_compression)]
               for i, r in win.iterrows()],
        'box': {'hi': float(t.box_hi), 'lo': float(t.box_lo), 'from': u(start),
                'to': u(entry_ts)},
        'marks': [
            {'time': u(entry_ts.floor('h')), 'position': 'aboveBar', 'color': '#facc15',
             'shape': 'arrowDown',
             'text': f"BUY {t.contract.split(':')[1][-15:]} @ {t.entry_px:.2f}"},
        ] + ([{'time': u(exit_ts.floor('h')), 'position': 'belowBar',
               'color': '#22c55e' if kind != 'win_lose' else '#ef4444',
               'shape': 'arrowUp', 'text': exit_label}] if exit_ts is not None else []),
    })
con.close()

page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compression Box Breakouts → Options | Milkman Trades</title>
<meta name="description" content="Hourly Saty compression boxes on 8 mega-caps, 2 years, real option prices: intraday box breaks bought immediately with a +100%/−50% bracket returned +8.3% of premium per trade (t=3.78, 972 boxes).">
<script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="/nav.js" defer></script>
<style>
 body{margin:0;background:#0b0e14;color:#e5edf7;font-family:ui-sans-serif,system-ui,sans-serif;line-height:1.55}
 .wrap{max-width:1100px;margin:0 auto;padding:18px 14px 60px}
 h1{font-size:clamp(22px,4vw,34px);letter-spacing:-.02em;margin:.2em 0}
 h2{font-size:20px;margin:1.6em 0 .4em;color:#dbeafe}
 .lede{color:#b6c5d8;font-size:16px;max-width:70ch}
 .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:18px 0}
 .tile{background:#0f1524;border:1px solid #1f2a44;border-radius:12px;padding:12px}
 .tile .v{font-size:24px;font-weight:800}.tile .l{color:#93a4b8;font-size:12px;margin-top:2px}
 .good{color:#4ade80}.bad{color:#f87171}.neut{color:#e5edf7}
 .chart-block{margin:26px 0}.price{height:400px}.osc{height:150px}
 .cap{color:#93a4b8;font-size:13.5px;max-width:75ch;margin-top:8px}
 .ct{font-weight:700;margin:0 0 6px;font-size:15px}
 table{border-collapse:collapse;font-size:14px;margin:10px 0}
 td,th{padding:5px 12px;border-bottom:1px solid #1f2a44;text-align:right}
 td:first-child,th:first-child{text-align:left}
 ul{max-width:75ch} li{margin:6px 0}
 .foot{color:#7b8ba1;font-size:12.5px;border-top:1px solid #1f2a44;margin-top:36px;padding-top:14px;max-width:80ch}
 .legend{color:#93a4b8;font-size:12px;margin:6px 0 0}
 .sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 12px;vertical-align:-1px}
</style></head><body><div class="wrap">
<h1>When an hourly compression box breaks,<br>buy the break — with real option prices</h1>
<p class="lede">Saty Phase Oscillator compression on the hourly chart draws a box (the range of the first
five compression candles, extended-hours bars). Across <strong>8 mega-caps × 24 months × 2,449 boxes</strong>
priced with actual option trade prints: when the break happens <strong>during market hours</strong>, buying the
weekly ATM option in the break direction immediately — take-profit +100%, stop −50% — returned
<strong>+8.3% of premium per trade (t&nbsp;=&nbsp;3.78, n&nbsp;=&nbsp;972)</strong>. Overnight gap-breaks returned nothing:
skip them. That single filter is what two earlier rounds of this study were missing.</p>
<div class="tiles">
 <div class="tile"><div class="v good">+8.3%</div><div class="l">avg premium P&L / trade, intraday breaks, TP100/stop50 (t=3.78, n=972 boxes)</div></div>
 <div class="tile"><div class="v good">both ways</div><div class="l">up-breaks +7.2% (calls) · down-breaks +9.5% (puts)</div></div>
 <div class="tile"><div class="v neut">7 of 8</div><div class="l">tickers positive — NVDA +14.6%, TSLA +18.3%; AAPL the exception</div></div>
 <div class="tile"><div class="v bad">≈ 0%</div><div class="l">overnight / gap breaks (n=1,259) — the no-trade class</div></div>
</div>

<h2>How to read the numbers</h2>
<ul>
 <li><strong>+8.3% per trade</strong> means: on average, each trade returned 8.3% of the premium paid.
 Risk $1,000 on the option, walk away with $1,083 on average — some trades hit +100%, some stop out
 at −50%, this is the blend. It is a return on premium, not on your account.</li>
 <li><strong>n = 972</strong> is how many boxes that average rests on. More boxes = the average is
 less likely to be a fluke of a few lucky trades.</li>
 <li><strong>t = 3.78</strong> answers "could this average be luck?" It measures how far the average
 sits from zero, in units of its own noise. t near 1: could easily be luck — a rerun of history might
 flip the sign. t near 2: unlikely to be luck (~5% odds from a zero-edge process). t of 3.8: about
 1-in-10,000 odds of appearing by chance. Rule of thumb — the average tells you how big the edge is,
 t tells you how much to believe it exists, n tells you how much history that belief rests on.</li>
 <li>The same yardstick works in reverse: the "don'ts" below have <em>negative</em> averages with
 big t values — those are reliably losing trades, not bad luck.</li>
</ul>

<h2>The setup</h2>
<ul>
 <li><strong>Box</strong>: first 5 hourly compression candles (fewer if expansion comes early) on <strong>extended-hours</strong> bars — box top/bottom = that range. ETH bars matter: a level that held overnight is a proven level.</li>
 <li><strong>Entry</strong>: the moment price breaks either edge <em>during regular hours</em> — buy the weekly (nearest-Friday) ATM call on an up-break / put on a down-break. No waiting for retest: it faded at scale.</li>
 <li><strong>Exit (simple)</strong>: bracket order — sell at +100% of premium, stop at −50%. Scale-outs at +50/+80% erase the edge; the payoff needs the doubles.</li>
 <li><strong>Exit (better — arm-then-trail)</strong>: same −50% stop, but once the premium doubles, remove the target and trail instead: never give back more than 30% from the option's high-water mark. <strong>+14.7% per trade (t=4.84)</strong> vs +8.3% for the fixed bracket. Validated: better in <em>both years separately</em> (+14.3% / +15.2%), better on <em>all 8 tickers</em>, and insensitive to the exact settings (arming anywhere from +75% to +150%, trailing 25–35%, all land +13.7 to +14.8%). The +300–500% runners in the charts below are what pay for the ~62% of losers — this exit keeps them. One honesty note: trailing exits fire during fast moves, so real fills matter more — under worst-case fills (trigger-bar close) it's +8.1% vs the bracket's +4.8%; the advantage holds under every fill assumption, the absolute level depends on execution.</li>
 <li><strong>Skip</strong>: breaks that happen overnight/premarket (gap opens outside the box) — flat to negative as a class.</li>
</ul>

__CHARTS__

<h2>Per-ticker (intraday breaks, TP100/stop50)</h2>
<table><tr><th>Ticker</th><th>avg P&L/trade</th><th>t</th><th>win rate</th><th>profit factor</th><th>gain-to-pain</th><th>boxes</th></tr>
<tr><td>TSLA</td><td class="good">+18.3%</td><td>2.90</td><td>44%</td><td>1.56</td><td>2.14</td><td>127</td></tr>
<tr><td>NVDA</td><td class="good">+14.6%</td><td>2.37</td><td>43%</td><td>1.50</td><td>2.95</td><td>130</td></tr>
<tr><td>MSFT</td><td class="good">+11.0%</td><td>1.71</td><td>38%</td><td>1.21</td><td>0.52</td><td>115</td></tr>
<tr><td>AMD</td><td class="good">+9.1%</td><td>1.37</td><td>39%</td><td>1.26</td><td>1.08</td><td>104</td></tr>
<tr><td>AMZN</td><td class="good">+8.6%</td><td>1.46</td><td>37%</td><td>1.14</td><td>0.40</td><td>139</td></tr>
<tr><td>META</td><td class="good">+6.4%</td><td>0.99</td><td>38%</td><td>1.21</td><td>0.49</td><td>115</td></tr>
<tr><td>GOOGL</td><td class="good">+4.9%</td><td>0.87</td><td>35%</td><td>1.06</td><td>0.16</td><td>131</td></tr>
<tr><td>AAPL</td><td class="bad">−8.5%</td><td>−1.39</td><td>28%</td><td>0.78</td><td>−0.42</td><td>111</td></tr>
<tr style="border-top:2px solid #334155"><td><strong>All 8</strong></td><td class="good"><strong>+8.3%</strong></td><td><strong>3.78</strong></td><td><strong>38%</strong></td><td><strong>1.20</strong></td><td><strong>2.49</strong></td><td><strong>972</strong></td></tr></table>
<ul>
 <li><strong>Win rate</strong> — the share of trades that made any money. 38% sounds low, and that's the
 point: this is a payoff-driven strategy, not an accuracy-driven one. Winners pay +100% of premium,
 losers cost −50%, so 4 wins can carry 6 losses. Expect losing streaks — at 38%, five losers in a row
 happens routinely — and size so the streaks don't shake you out.</li>
 <li><strong>Profit factor</strong> — every dollar won divided by every dollar lost, per trade.
 1.00 is breakeven; 1.20 means the wins collected $1.20 for every $1.00 the losses gave back.
 Below 1.00 (AAPL's 0.78) means the losses outweigh the wins outright.</li>
 <li><strong>Gain-to-pain</strong> — the same idea measured on <em>monthly</em> P&L instead of per trade:
 total net profit divided by the sum of losing months. It punishes strategies that make their money in
 lumps and give it back in drawdowns. Above 1.0 is good, above 2.0 is strong. Note the "All 8" row:
 trading every name together scores 2.49 — better than most single names — because a bad month in one
 ticker tends to be covered by the others. The edge diversifies.</li>
</ul>

<h2>The don'ts (each tested, each lost)</h2>
<ul>
 <li><strong>Don't trade the gap.</strong> Overnight breaks bought at the open ≈ 0% across 1,259 boxes.</li>
 <li><strong>Don't scale out early.</strong> TP1 +50% / TP2 +80% turns +8.3% into −1%. The edge lives in the tail.</li>
 <li><strong>Don't fade strength in the box.</strong> Shorting the top third: −6.2%/trade, t=−3.87, n=1,421 — the most reliable losing trade in the study.</li>
 <li><strong>Don't overthink the oscillator.</strong> PO slope, position, and direction added nothing on top of the box: with-slope and against-slope entries performed the same. The compression flag is the signal; the box does the rest.</li>
</ul>

<div class="foot">
<strong>Method & honesty notes.</strong> Events: Saty Pine-spec po_compression on hourly bars (ETH 04:00–19:55 ET),
8 tickers (AMZN NVDA MSFT AAPL META GOOGL TSLA AMD), Jul 2024 – Jul 2026. Options: Massive/Polygon minute
trade prints, 21k contracts; fills = last print at signal (median lag ≈1 min); expiries anchored to entry date.
No bid/ask or commissions modeled — expect a 2–4pp haircut on liquid ATM weeklies; thin strikes worse.
Stats are episode-clustered; TP fills assume a resting limit at target; stops assume no gap-through.
This is round three of the study: round one (3 tickers, 12 months, RTH bars) found nothing;
a random-entry control reframed it; the 10× sample plus the ETH-session definition and the
intraday/overnight split produced the result above. Earlier candidate edges (retest entries, box-maturity
filters) faded out-of-sample and are reported dead. Charts show Saty-style hourly candles
(gray = compression), 8/21 + 13/48 EMA ribbons, phase oscillator (magenta = compression).
Built 2026-07-08 · data through 2026-07-06.</div>
</div>
<script>
__CLOUD__
const CHARTS = __DATA__;
const {createChart} = LightweightCharts;
const opts = {layout:{background:{color:'#0b0e14'},textColor:'#93a4b8'},grid:{vertLines:{color:'#151a24'},horzLines:{color:'#151a24'}},timeScale:{timeVisible:true,secondsVisible:false},rightPriceScale:{borderColor:'#1f2a44'}};
for (const D of CHARTS) {
  const pc = createChart(document.getElementById('p'+D.id), opts);
  const oc = createChart(document.getElementById('o'+D.id), opts);
  const emaSeries = {};
  const ST = {'8':['transparent',0],'13':['transparent',0],'21':['#ffffff',2],'48':['transparent',0]};
  for (const p of ['8','13','21','48']) {
    emaSeries[p] = pc.addLineSeries({color:ST[p][0],lineWidth:ST[p][1]||1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    emaSeries[p].setData(D.emas[p].map(([t,v])=>({time:t,value:v})));
  }
  try {
    emaSeries['8'].attachPrimitive(new CloudFillPrimitive(emaSeries['8'],emaSeries['21'],'rgba(34,197,94,0.35)','rgba(239,68,68,0.35)'));
    emaSeries['13'].attachPrimitive(new CloudFillPrimitive(emaSeries['13'],emaSeries['48'],'rgba(96,165,250,0.25)','rgba(249,115,22,0.25)'));
  } catch(e){}
  const e48={}; D.emas['48'].forEach(([t,v])=>{e48[t]=v;});
  const cs = pc.addCandlestickSeries();
  cs.setData(D.candles.map(([t,o,h,l,c,comp])=>{
    const up=c>=o, above=c>=(e48[t]??c);
    let uC,dC;
    if(comp){uC='#b0b0b0';dC='#808080';}else if(above){uC='#22c55e';dC='#60a5fa';}else{uC='#f97316';dC='#ef4444';}
    const col=up?uC:dC;
    return {time:t,open:o,high:h,low:l,close:c,color:col,borderColor:col,wickColor:col+'aa'};
  }));
  for (const lvl of [D.box.hi, D.box.lo]) {
    const s = pc.addLineSeries({color:'#94a3b8',lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    s.setData(D.candles.filter(c=>c[0]>=D.box.from&&c[0]<=D.box.to).map(c=>({time:c[0],value:lvl})));
  }
  cs.setMarkers(D.marks.sort((a,b)=>a.time-b.time));
  const po = oc.addLineSeries({lineWidth:2,priceLineVisible:false,lastValueVisible:false});
  po.setData(D.po.map(([t,v,comp])=>({time:t,value:v,color:comp?'#e040fb':(v>=0?'#69f0ae':'#ef4444')})));
  for (const [p,c] of [[100,'#64748b88'],[61.8,'#64748b66'],[23.6,'#64748b44'],[-23.6,'#64748b44'],[-61.8,'#64748b66'],[-100,'#64748b88'],[0,'#64748b33']])
    po.createPriceLine({price:p,color:c,lineWidth:1,lineStyle:2,axisLabelVisible:false,title:''});
  const sync=(a,b)=>{a.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r)b.timeScale().setVisibleLogicalRange(r);});};
  sync(pc,oc); sync(oc,pc);
  pc.timeScale().fitContent();
}
</script></body></html>"""

blocks = []
for c in charts:
    blocks.append(
        f'<div class="chart-block"><div class="ct">{c["title"]}</div>'
        f'<div id="p{c["id"]}" class="price"></div><div id="o{c["id"]}" class="osc"></div>'
        f'<div class="cap">{c["caption"]}</div></div>')
blocks.insert(0, '<h2>Three trades, start to finish</h2>'
              '<div class="legend">gray candles = compression'
              '<span class="sw" style="background:#e040fb"></span>PO compression'
              '<span class="sw" style="background:#94a3b8"></span>box'
              '<span class="sw" style="background:#facc15"></span>entry'
              '<span class="sw" style="background:#22c55e"></span>exit</div>')
page = page.replace('__CHARTS__', '\n'.join(blocks))
page = page.replace('__CLOUD__', CLOUD).replace('__DATA__', json.dumps(charts))
OUT.write_text(page)
print("wrote", OUT, len(page), "bytes,", len(charts), "charts")

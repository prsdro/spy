"""Assemble the combined-engines equity page (injects combo_data.json)."""
import json

data = json.load(open("combo_data.json"))

HTML = """<title>Three-Engine Combo — 2026 Forward</title>
<style>
:root{
  --surface:#fcfcfb; --panel:#f4f4f1; --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a887f;
  --line:#e4e3dd; --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s4:#008300;
  --neg:#e34948; --pos:#008300;
}
@media (prefers-color-scheme: dark){:root{
  --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a887f;
  --line:#33332f; --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#4caf50;
  --neg:#e66767; --pos:#4caf50;
}}
:root[data-theme="dark"]{
  --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink-2:#c3c2b7; --ink-3:#8a887f;
  --line:#33332f; --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#4caf50;
  --neg:#e66767; --pos:#4caf50;
}
:root[data-theme="light"]{
  --surface:#fcfcfb; --panel:#f4f4f1; --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a887f;
  --line:#e4e3dd; --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s4:#008300;
  --neg:#e34948; --pos:#008300;
}
*{box-sizing:border-box}
body{background:var(--surface);color:var(--ink);
  font:15px/1.55 "Seravek","Avenir Next",system-ui,sans-serif;margin:0;padding:0}
.wrap{max-width:1060px;margin:0 auto;padding:36px 24px 72px;display:flex;
  flex-direction:column;gap:28px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}
h1{font-size:30px;margin:4px 0 2px;letter-spacing:-.01em;text-wrap:balance}
.sub{color:var(--ink-2);max-width:70ch}
.num{font-variant-numeric:tabular-nums;font-family:ui-monospace,"SF Mono",Menlo,monospace}
.hero-num{font-size:44px;font-weight:650;letter-spacing:-.02em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;
  padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.tile .lab{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);
  display:flex;align-items:center;gap:7px}
.dot{width:9px;height:9px;border-radius:2px;display:inline-block}
.tile .v{font-size:22px;font-weight:640}
.tile .d{font-size:12.5px;color:var(--ink-2)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:18px}
.panel h2{font-size:15px;margin:0 0 4px}
.panel .note{font-size:12.5px;color:var(--ink-3);margin:0 0 10px}
.toggle{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:8px}
.toggle button{background:none;border:0;padding:6px 14px;font:inherit;font-size:13px;
  color:var(--ink-2);cursor:pointer}
.toggle button[aria-pressed="true"]{background:var(--s1);color:#fff}
.toggle button:focus-visible{outline:2px solid var(--s1);outline-offset:-2px}
svg text{font:11.5px ui-monospace,Menlo,monospace;fill:var(--ink-2)}
svg .lbl{font:12px "Seravek","Avenir Next",system-ui,sans-serif;font-weight:600}
.tooltip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);
  border-radius:5px;padding:7px 10px;font-size:12px;line-height:1.5;z-index:9;
  opacity:0;transition:opacity .08s;max-width:260px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  text-align:right;padding:6px 10px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
.caveats{font-size:13px;color:var(--ink-2);border-left:3px solid var(--s3);
  padding:4px 0 4px 14px}
.caveats b{color:var(--ink)}
.pos{color:var(--pos)}.neg{color:var(--neg)}
@media (prefers-reduced-motion: no-preference){
  .draw path.series{stroke-dasharray:var(--len);stroke-dashoffset:var(--len);
    animation:draw 1.1s ease-out forwards}
  @keyframes draw{to{stroke-dashoffset:0}}
}
</style>
<div class="wrap">
<header>
  <div class="eyebrow">Forward window · Jan 26 – Jul 10, 2026 · 120 trading days · all post-selection data</div>
  <h1>Three engines, one book</h1>
  <p class="sub">CompressionDrift (3m PO drift continuation, 1 ES + 1 NQ), RibbonRider
  (EMA-ribbon arm-entry longs, 1 ES-equivalent via SPY), and BeatTheMarket (noise-area
  intraday momentum, 1 NQ, skip-expansion filter) — frozen specs, summed daily P&L,
  no compounding.</p>
</header>

<div class="tiles">
  <div class="tile"><span class="lab"><span class="dot" style="background:var(--s1)"></span>Combined (1-lot stack)</span>
    <span class="v num pos">+$53,352</span><span class="d">$445/day · Sharpe 1.49 · maxDD −$14,413</span></div>
  <div class="tile"><span class="lab"><span class="dot" style="background:var(--s2)"></span>CompressionDrift</span>
    <span class="v num pos">+$22,551</span><span class="d">Sharpe 0.96 · maxDD −$17,068 · 106 active days</span></div>
  <div class="tile"><span class="lab"><span class="dot" style="background:var(--s3)"></span>RibbonRider</span>
    <span class="v num pos">+$12,152</span><span class="d">Sharpe 2.24 · maxDD −$5,364 · 57 active days</span></div>
  <div class="tile"><span class="lab"><span class="dot" style="background:var(--s4)"></span>BeatTheMarket</span>
    <span class="v num pos">+$18,649</span><span class="d">Sharpe 1.06 · maxDD −$9,246 · 61 active days</span></div>
</div>

<section class="panel">
  <h2>Equity curves</h2>
  <p class="note">Cumulative net P&L, $ per stated unit size. Costs: futures 1 tick/side + commissions; SPY mapped at $500/pt (ES-equivalent).</p>
  <div class="toggle" role="group" aria-label="weighting">
    <button id="bRaw" aria-pressed="true">1-lot stack</button>
    <button id="bEq" aria-pressed="false">Equal-risk ($1k/day σ each)</button>
  </div>
  <div id="chart"></div>
</section>

<section class="panel">
  <h2>Monthly P&L — combined</h2>
  <p class="note">Partial months at both ends (Jan from the 26th, Jul through the 10th).</p>
  <div id="monthly"></div>
</section>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:28px" class="two-col">
<section class="panel">
  <h2>Daily P&L correlation</h2>
  <p class="note">Low correlation is the point of combining.</p>
  <table>
    <tr><th></th><th>Drift</th><th>Ribbon</th><th>BTM</th></tr>
    <tr><td>CompressionDrift</td><td class="num">1.00</td><td class="num">−0.02</td><td class="num">0.45</td></tr>
    <tr><td>RibbonRider</td><td class="num">−0.02</td><td class="num">1.00</td><td class="num">0.05</td></tr>
    <tr><td>BeatTheMarket</td><td class="num">0.45</td><td class="num">0.05</td><td class="num">1.00</td></tr>
  </table>
</section>
<section class="panel">
  <h2>Equal-risk view</h2>
  <p class="note">Each engine scaled to $1,000/day realized σ (weights: Drift ×0.32, Ribbon ×1.40, BTM ×0.43 lots).</p>
  <table>
    <tr><th></th><th>Total</th><th>Sharpe</th><th>maxDD</th></tr>
    <tr><td>Combined, equal-risk</td><td class="num pos">+$32,201</td><td class="num">2.14</td><td class="num neg">−$6,684</td></tr>
    <tr><td>Combined, 1-lot stack</td><td class="num pos">+$53,352</td><td class="num">1.49</td><td class="num neg">−$14,413</td></tr>
  </table>
</section>
</div>

<section class="caveats">
  <b>Read this before believing it.</b> 5.5 months is one macro regime — 2026 has been
  a volatile, trend-rich tape that flatters all three engines; the diversification
  (correlations ≈ 0 for Ribbon) is the most durable part of the result. Specs were
  frozen before this window for all three engines, but the window is shared, not
  independent. Drift ↔ BTM correlation 0.45 means both can be short-vol-of-trend on
  the same NQ day; position netting in a single account is not modeled. Equal-risk
  weights use this window's own realized σ (mild look-ahead). Evidence tiers differ:
  CompressionDrift passed an NQ holdout (t=2.85), BeatTheMarket passed instrument-OOS
  (+$106/day NQ holdout), RibbonRider failed its NQ holdout and is
  promising-unconfirmed on this forward window only.
</section>
</div>
<div class="tooltip" id="tip"></div>
<script>
const D = __DATA__;
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt$ = v => (v<0?"−$":"+$") + Math.abs(v).toLocaleString();
const SERIES = [
  {k:"Combined", lab:"Combined", c:"--s1", w:2.5},
  {k:"CompressionDrift", lab:"Drift", c:"--s2", w:1.6},
  {k:"RibbonRider", lab:"Ribbon", c:"--s3", w:1.6},
  {k:"BeatTheMarket", lab:"BTM", c:"--s4", w:1.6},
];
let mode = "raw";
function drawChart(){
  const el = document.getElementById("chart");
  const W = Math.min(el.clientWidth||1000,1000), H = 380,
        m = {t:14,r:86,b:26,l:64};
  const ser = mode==="raw" ? SERIES
    : [{k:"Combined_eqrisk", lab:"Combined", c:"--s1", w:2.5}];
  const all = ser.flatMap(s=>D[s.k]);
  const ymin = Math.min(0,...all), ymax = Math.max(...all);
  const n = D.dates.length;
  const x = i => m.l + i*(W-m.l-m.r)/(n-1);
  const y = v => m.t + (ymax-v)*(H-m.t-m.b)/(ymax-ymin);
  let g = `<svg class="draw" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="equity curves">`;
  const step = Math.ceil((ymax-ymin)/5/5000)*5000 || 5000;
  for(let v=Math.ceil(ymin/step)*step; v<=ymax; v+=step){
    g += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${css('--line')}" stroke-width="1"/>`;
    g += `<text x="${m.l-8}" y="${y(v)+4}" text-anchor="end">${v===0?"0":(v/1000)+"k"}</text>`;
  }
  g += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(0)}" y2="${y(0)}" stroke="${css('--ink-3')}" stroke-width="1"/>`;
  const mticks = {}; D.dates.forEach((d,i)=>{const mo=d.slice(0,7); if(!(mo in mticks)) mticks[mo]=i;});
  for(const [mo,i] of Object.entries(mticks)){
    g += `<text x="${x(i)}" y="${H-8}">${new Date(mo+"-15").toLocaleString("en",{month:"short"})}</text>`;
  }
  for(const s of ser){
    const pts = D[s.k].map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    g += `<path class="series" style="--len:2200" d="M${pts.replaceAll(" "," L")}" fill="none" stroke="${css(s.c)}" stroke-width="${s.w}" stroke-linejoin="round"/>`;
    const last = D[s.k][n-1];
    g += `<circle cx="${x(n-1)}" cy="${y(last)}" r="3.5" fill="${css(s.c)}"/>`;
    g += `<text class="lbl" x="${x(n-1)+8}" y="${y(last)+4}" fill="${css(s.c)}">${s.lab}</text>`;
  }
  g += `<line id="xh" y1="${m.t}" y2="${H-m.b}" stroke="${css('--ink-3')}" stroke-width="1" opacity="0"/>`;
  g += `</svg>`;
  el.innerHTML = g;
  const svg = el.querySelector("svg"), tip = document.getElementById("tip"), xh = el.querySelector("#xh");
  svg.addEventListener("mousemove", e=>{
    const r = svg.getBoundingClientRect();
    const sx = (e.clientX-r.left)*W/r.width;
    let i = Math.round((sx-m.l)*(n-1)/(W-m.l-m.r)); i = Math.max(0,Math.min(n-1,i));
    xh.setAttribute("x1",x(i)); xh.setAttribute("x2",x(i)); xh.setAttribute("opacity",.6);
    tip.style.opacity = 1;
    tip.style.left = Math.min(e.clientX+14, innerWidth-280)+"px";
    tip.style.top = (e.clientY+14)+"px";
    tip.innerHTML = `<b>${D.dates[i]}</b><br>` + ser.map(s=>
      `${s.lab}: ${fmt$(D[s.k][i])} <span style="opacity:.7">(day ${fmt$(D[s.k+"_daily"][i])})</span>`).join("<br>");
  });
  svg.addEventListener("mouseleave", ()=>{tip.style.opacity=0; xh.setAttribute("opacity",0);});
}
function drawMonthly(){
  const el = document.getElementById("monthly");
  const mon = mode==="raw" ? D.monthly : D.monthly_eq;
  const keys = Object.keys(mon), W = Math.min(el.clientWidth||1000,1000), H=190,
        m={t:12,r:12,b:24,l:64};
  const vals = Object.values(mon);
  const ymin = Math.min(0,...vals), ymax = Math.max(0,...vals);
  const y = v => m.t + (ymax-v)*(H-m.t-m.b)/(ymax-ymin);
  const bw = (W-m.l-m.r)/keys.length;
  let g = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="monthly PnL">`;
  g += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(0)}" y2="${y(0)}" stroke="${css('--ink-3')}" stroke-width="1"/>`;
  keys.forEach((k,i)=>{
    const v = mon[k], up = v>=0;
    const bx = m.l+i*bw+bw*0.18, bwid = bw*0.64;
    g += `<rect data-k="${k}" data-v="${v}" x="${bx}" width="${bwid}" y="${y(Math.max(v,0))}"
      height="${Math.abs(y(v)-y(0))}" rx="3" fill="${up?css('--s1'):css('--neg')}"/>`;
    g += `<text x="${bx+bwid/2}" y="${H-6}" text-anchor="middle">${new Date(k+"-15").toLocaleString("en",{month:"short"})}</text>`;
    g += `<text x="${bx+bwid/2}" y="${up? y(v)-6 : y(v)+14}" text-anchor="middle">${(v/1000).toFixed(1)}k</text>`;
  });
  g += `</svg>`;
  el.innerHTML = g;
}
function setMode(mo){
  mode = mo;
  document.getElementById("bRaw").setAttribute("aria-pressed", mo==="raw");
  document.getElementById("bEq").setAttribute("aria-pressed", mo==="eq");
  drawChart(); drawMonthly();
}
document.getElementById("bRaw").onclick = ()=>setMode("raw");
document.getElementById("bEq").onclick = ()=>setMode("eq");
new MutationObserver(()=>{drawChart();drawMonthly();})
  .observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
addEventListener("resize", ()=>{drawChart();drawMonthly();});
setMode("raw");
</script>
"""

open("combo_equity.html", "w").write(HTML.replace("__DATA__", json.dumps(data)))
print("written", len(HTML))

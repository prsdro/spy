/**
 * Shared study-date drawer for all Milkman Trades study pages.
 *
 * Usage:
 *   1. Include this script: <script src="/study-drawer.js"></script>
 *   2. It auto-injects the drawer HTML + CSS on load.
 *   3. Make N cells clickable by adding these data attributes:
 *        class="n-clickable"
 *        data-study="golden-gate"        (study ID — matches JSON key)
 *        data-row="09:30"                (row key within the study)
 *        data-outcome="hit" | "miss"     (which outcome this N represents)
 *   4. Call StudyDrawer.loadData('/data/my-dates.json') to load date data.
 *      JSON format: { "rowKey": [ {d:"2024-01-15", h:1}, ... ], ... }
 *      h=1 means "yes" (outcome happened), h=0 means "no".
 *
 * Or use the programmatic API:
 *   StudyDrawer.open(dates, title, subtitle, filter)
 */
(function () {
  // ── Inject CSS ──
  const style = document.createElement('style');
  style.textContent = `
.n-clickable{cursor:pointer;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px;transition:color .15s}
.n-clickable:hover{color:#fbbf24 !important}
.n-yes{color:#1cd48a}.n-no{color:#6b7280}
.sd-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;opacity:0;pointer-events:none;transition:opacity .25s ease}
.sd-overlay.open{opacity:1;pointer-events:auto}
.sd-drawer{position:fixed;top:0;right:0;bottom:0;width:380px;max-width:90vw;background:#0c0e12;border-left:1px solid #1e2230;z-index:1001;transform:translateX(100%);transition:transform .3s cubic-bezier(.22,1,.36,1);display:flex;flex-direction:column}
.sd-drawer.open{transform:translateX(0)}
.sd-header{padding:1.25rem 1.25rem .75rem;border-bottom:1px solid #1e2230;display:flex;align-items:flex-start;justify-content:space-between;gap:.75rem;flex-shrink:0}
.sd-title{font-size:.95rem;font-weight:600;color:#e8eaed;line-height:1.3}
.sd-subtitle{font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#6b7280;margin-top:.2rem}
.sd-close{background:none;border:1px solid #1e2230;border-radius:4px;color:#6b7280;cursor:pointer;padding:.25rem .5rem;font-size:.75rem;line-height:1;transition:color .15s,border-color .15s;flex-shrink:0}
.sd-close:hover{color:#e8eaed;border-color:#6b7280}
.sd-filters{padding:.75rem 1.25rem;display:flex;gap:.4rem;border-bottom:1px solid #1e2230;flex-shrink:0}
.sd-filter{padding:.3rem .65rem;font-family:'JetBrains Mono',monospace;font-size:.68rem;border:1px solid #1e2230;border-radius:4px;background:none;color:#6b7280;cursor:pointer;transition:all .15s}
.sd-filter:hover{color:#e8eaed;border-color:#6b7280}
.sd-filter.active{color:#fbbf24;border-color:#fbbf24;background:#1a1800}
.sd-list{flex:1;overflow-y:auto;padding:.5rem 0}
.sd-list::-webkit-scrollbar{width:4px}
.sd-list::-webkit-scrollbar-thumb{background:#1e2230;border-radius:2px}
.sd-date-row{display:flex;align-items:center;padding:.4rem 1.25rem;gap:.75rem;cursor:pointer;transition:background .12s;text-decoration:none;color:#e8eaed}
.sd-date-row:hover{background:#13161c}
.sd-date-val{font-family:'JetBrains Mono',monospace;font-size:.78rem;font-weight:500;flex:1}
.sd-date-tag{font-family:'JetBrains Mono',monospace;font-size:.62rem;padding:.15rem .4rem;border-radius:3px;font-weight:500}
.sd-tag-yes{background:#0e3326;color:#22d3ee}
.sd-tag-no{background:#1f0c0c;color:#f87171}
.sd-chart-arrow{color:#6b7280;font-size:.7rem;transition:color .12s}
.sd-date-row:hover .sd-chart-arrow{color:#fbbf24}
.sd-count{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:#6b7280;padding:.5rem 1.25rem;border-top:1px solid #1e2230;flex-shrink:0}
`;
  document.head.appendChild(style);

  // ── Inject HTML ──
  const html = `
<div class="sd-overlay" id="sd-overlay"></div>
<div class="sd-drawer" id="sd-drawer">
  <div class="sd-header">
    <div>
      <div class="sd-title" id="sd-title">Dates</div>
      <div class="sd-subtitle" id="sd-subtitle"></div>
    </div>
    <button class="sd-close" id="sd-close">ESC</button>
  </div>
  <div class="sd-filters" id="sd-filters">
    <button class="sd-filter active" data-filter="all">All</button>
    <button class="sd-filter" data-filter="yes">Yes</button>
    <button class="sd-filter" data-filter="no">No</button>
  </div>
  <div class="sd-list" id="sd-list"></div>
  <div class="sd-count" id="sd-count"></div>
</div>`;
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html;
  while (wrapper.firstChild) document.body.appendChild(wrapper.firstChild);

  // ── State ──
  let drawerDates = [];
  let drawerFilter = 'all';
  let allData = {};  // loaded JSON keyed by row

  const overlay = document.getElementById('sd-overlay');
  const drawer = document.getElementById('sd-drawer');
  const titleEl = document.getElementById('sd-title');
  const subtitleEl = document.getElementById('sd-subtitle');
  const listEl = document.getElementById('sd-list');
  const countEl = document.getElementById('sd-count');

  // ── Render ──
  function render() {
    let filtered = drawerDates;
    if (drawerFilter === 'yes') filtered = drawerDates.filter(d => d.h);
    else if (drawerFilter === 'no') filtered = drawerDates.filter(d => !d.h);

    listEl.innerHTML = filtered.map(d => {
      const cls = d.h ? 'sd-tag-yes' : 'sd-tag-no';
      const label = d.h ? 'Yes' : 'No';
      return `<a class="sd-date-row" href="/charts/?mode=day&range=1&date=${encodeURIComponent(d.d)}" target="_blank" rel="noopener">
        <span class="sd-date-val">${d.d}</span>
        <span class="sd-date-tag ${cls}">${label}</span>
        <span class="sd-chart-arrow">chart \u2192</span>
      </a>`;
    }).join('');

    countEl.textContent = `Showing ${filtered.length} of ${drawerDates.length} dates`;
  }

  function open(dates, title, subtitle, autoFilter) {
    drawerDates = dates;
    drawerFilter = autoFilter || 'all';
    titleEl.textContent = title || 'Dates';
    subtitleEl.textContent = subtitle || '';

    document.querySelectorAll('.sd-filter').forEach(b => b.classList.remove('active'));
    const matchBtn = document.querySelector(`.sd-filter[data-filter="${drawerFilter}"]`);
    if (matchBtn) matchBtn.classList.add('active');

    render();
    drawer.classList.add('open');
    overlay.classList.add('open');
  }

  function close() {
    drawer.classList.remove('open');
    overlay.classList.remove('open');
  }

  // ── Events ──
  document.getElementById('sd-close').addEventListener('click', close);
  overlay.addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });

  document.getElementById('sd-filters').addEventListener('click', e => {
    const btn = e.target.closest('.sd-filter');
    if (!btn) return;
    drawerFilter = btn.dataset.filter;
    document.querySelectorAll('.sd-filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    render();
  });

  // ── Clickable N cells ──
  document.addEventListener('click', e => {
    const cell = e.target.closest('.n-clickable');
    if (!cell) return;

    const row = cell.dataset.row;
    const outcome = cell.dataset.outcome; // "hit" or "miss"

    if (!row) return;

    // Get dates for this row
    let dates = allData[row] || [];

    // Pre-filter by outcome if specified
    if (outcome === 'hit') dates = dates.filter(d => d.h);
    else if (outcome === 'miss') dates = dates.filter(d => !d.h);

    const title = cell.dataset.title || row;
    const outcomeLabel = outcome === 'hit' ? 'Yes' : outcome === 'miss' ? 'No' : 'All';
    const subtitle = `${outcomeLabel} \u00b7 ${dates.length} days`;

    open(dates, title, subtitle, 'all');
  });

  // ── Public API ──
  window.StudyDrawer = {
    open,
    close,
    loadData(url) {
      return fetch(url)
        .then(r => r.json())
        .then(data => { allData = data; })
        .catch(err => console.warn('StudyDrawer: could not load', url, err));
    },
    setData(data) { allData = data; },
  };
})();

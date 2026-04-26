// Shared navigation bar injected into all study pages
// Include with: <script src="/nav.js"></script>
(function(){
  const NAV = [
    {label:'Home', href:'/'},
    {label:'Subway Stats', href:'/golden-gate.html'},
    {label:'Bilbo GG', href:'/bilbo-golden-gate.html'},
    {label:'Continuation', href:'/bilbo-continuation.html'},
    {label:'10m vs 60m', href:'/bilbo-10m.html'},
    {label:'Pullbacks', href:'/gg-invalidation.html'},
    {label:'Entries', href:'/gg-entries.html'},
    {label:'Gap Fills', href:'/gap-fills.html'},
    {label:'4h PO × OpEx', href:'/4h-po-opex.html'},
    {label:'3m Close', href:'/call-trigger.html'},
    {label:'Call→Put', href:'/call-to-put-reversal.html'},
    {label:'Trigger Box', href:'/trigger-box.html'},
    {label:'Spreads', href:'/trigger-box-spreads.html'},
    {label:'Multi-Day', href:'/multiday-gg.html'},
    {label:'Swing', href:'/swing-gg.html'},
    {label:'Cheat Sheet', href:'/cheatsheet.html'},
    {label:'Data', href:'/data/'},
  ];
  const current = window.location.pathname;
  const bar = document.createElement('nav');
  bar.id = 'milknav';
  bar.innerHTML = '<div class="mn-inner">' + NAV.map(n => {
    const isActive = current === n.href || (n.href !== '/' && current.startsWith(n.href.replace('.html','')));
    const isHome = n.href === '/';
    const cls = 'mn-link' + (isActive ? ' mn-active' : '') + (isHome && !isActive ? ' mn-home' : '');
    const icon = isHome && !isActive ? '&larr; ' : '';
    return `<a href="${n.href}" class="${cls}">${icon}${n.label}</a>`;
  }).join('') + '</div>';

  const style = document.createElement('style');
  style.textContent = `
    #milknav{position:sticky;top:0;z-index:900;background:#0c0e12ee;backdrop-filter:blur(8px);border-bottom:1px solid #1e2230;padding:0;overflow:hidden}
    .mn-inner{display:flex;overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none;padding:.4rem .75rem;gap:.25rem}
    .mn-inner::-webkit-scrollbar{display:none}
    .mn-link{flex-shrink:0;padding:.35rem .6rem;font-family:'DM Sans',system-ui,sans-serif;font-size:.72rem;color:#9ca3af;text-decoration:none;border-radius:4px;white-space:nowrap;transition:color .12s,background .12s}
    .mn-link:hover{color:#eaebef;background:#181c24}
    .mn-link.mn-active{color:#fbbf24;background:#1a1800;font-weight:600}
    .mn-link.mn-home{color:#eaebef;font-weight:600;border-right:1px solid #252938;margin-right:.25rem;padding-right:.75rem}
    @media(max-width:640px){.mn-link{font-size:.68rem;padding:.3rem .5rem}}
    #mn-mobile-cta{display:none;position:fixed;bottom:1.2rem;right:1.2rem;z-index:950;padding:.65rem 1rem;background:#fbbf24;color:#000;border:none;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:.75rem;font-weight:700;text-decoration:none;box-shadow:0 4px 16px rgba(251,191,36,.35);letter-spacing:.02em;transition:transform .15s,box-shadow .15s}
    #mn-mobile-cta:active{transform:scale(.95)}
    @media(max-width:767px){#mn-mobile-cta{display:block}}
  `;
  document.head.appendChild(style);
  document.body.prepend(bar);

  // Floating "Cheat Sheet" CTA on mobile — hidden on cheatsheet pages
  const path = window.location.pathname;
  const isCheatsheet = path.indexOf('cheatsheet') !== -1;
  if (!isCheatsheet) {
    const fab = document.createElement('a');
    fab.id = 'mn-mobile-cta';
    fab.href = '/cheatsheet.html';
    fab.textContent = '\uD83D\uDCCB Cheat Sheet';
    document.body.appendChild(fab);
  }
})();

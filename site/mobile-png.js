// Mobile PNG renderer for cheat sheets
// Clones the poster, reformats to 600px single-column, renders via html2canvas
function saveMobilePNG() {
  const btn = document.querySelector('.save-mobile-btn');
  if (btn) btn.textContent = 'Rendering...';

  const poster = document.getElementById('poster');
  if (!poster) return;

  // Clone the poster
  const clone = poster.cloneNode(true);
  clone.id = 'poster-mobile';

  // Apply mobile styles
  const mobileCSS = document.createElement('style');
  mobileCSS.textContent = `
    #poster-mobile { width:600px !important; }
    #poster-mobile .grid { grid-template-columns:1fr !important; }
    #poster-mobile .grid2 { grid-template-columns:1fr !important; }
    #poster-mobile .sec { border-right:none !important; }
    #poster-mobile .sec.full { grid-column:1 !important; }
    #poster-mobile .hdr { flex-direction:column !important; gap:.75rem !important; align-items:flex-start !important; }
    #poster-mobile .hdr-right { text-align:left !important; }
    #poster-mobile .stats { flex-direction:column !important; }
    #poster-mobile .stat { min-width:auto !important; }
    #poster-mobile .chain { flex-wrap:wrap !important; justify-content:center !important; }
    #poster-mobile .pogrid { font-size:.8rem !important; }
    #poster-mobile .mtable { font-size:.75rem !important; }
    #poster-mobile .mtable td, #poster-mobile .mtable th { padding:.35rem .4rem !important; }
    #poster-mobile .ftr { flex-direction:column !important; gap:.3rem !important; text-align:center !important; }
    #poster-mobile .links { flex-direction:column !important; align-items:center !important; }
    #poster-mobile .sec-title { font-size:1rem !important; }
    #poster-mobile .take { font-size:.85rem !important; }
    #poster-mobile .blist { font-size:.82rem !important; }
    #poster-mobile div[style*="grid-template-columns: 1fr 1fr"] { grid-template-columns:1fr !important; }
    #poster-mobile div[style*="grid-template-columns:1fr 1fr"] { grid-template-columns:1fr !important; }
  `;
  document.head.appendChild(mobileCSS);

  // Position off-screen
  clone.style.position = 'absolute';
  clone.style.left = '-9999px';
  clone.style.top = '0';
  document.body.appendChild(clone);

  // Also fix inline grid styles
  clone.querySelectorAll('[style]').forEach(el => {
    const s = el.getAttribute('style');
    if (s && s.includes('grid-template-columns') && s.includes('1fr 1fr')) {
      el.style.gridTemplateColumns = '1fr';
    }
  });

  setTimeout(() => {
    html2canvas(clone, {
      scale: 2,
      backgroundColor: '#0c0e12',
      useCORS: true,
      width: 600,
    }).then(canvas => {
      const a = document.createElement('a');
      const title = document.title.split('|')[0].trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
      a.download = title + '-mobile.png';
      a.href = canvas.toDataURL('image/png');
      a.click();
      clone.remove();
      mobileCSS.remove();
      if (btn) {
        btn.textContent = '✓ Saved';
        setTimeout(() => btn.textContent = '📱 Mobile PNG', 2000);
      }
    });
  }, 100);
}

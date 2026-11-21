  /* ---------- input */
  document.addEventListener('click', (e) => {
    const t = e.target;
    const sc = t.closest && t.closest('.scb[data-sc]');
    if (sc) { useScenario(sc.getAttribute('data-sc')); return; }
    const row = t.closest && t.closest('.results tr[data-sc]');
    if (row) { useScenario(row.getAttribute('data-sc')).then(() => setTab('split')); return; }
    const chip = t.closest && t.closest('.chip[data-s]');
    if (chip) { choose(chip.getAttribute('data-s')); return; }
    if (t.closest && t.closest('[data-part]')) { setPart(true); return; }
    const blk = t.closest && t.closest('.blk[data-b]');
    if (blk) {
      const b = blk.getAttribute('data-b');
      if (blk.closest('#map')) readBlock(b); else if (blk.closest('#over')) gotoBlock(b);
      return;
    }
    const stg = t.closest && t.closest('.stg');
    if (stg) {
      const row = D.strip[+stg.getAttribute('data-st')];
      const m = moment();
      const hit = row[1].find((b) => m && m.lit.indexOf(b) >= 0) || row[1][0];
      readBlock(hit);
      return;
    }
    if (t.closest && t.closest('#now-gap')) {
      const m = moment();
      if (m && m.k.gap) { stopAll(); S.auto = false; updateBar(); S.read = null; S.view = S.view === 'gap' ? 'key' : 'gap'; clearRead(); settleMap(); showNow(); renderTerm(false); }
    }
  });
  $('t-all').addEventListener('click', () => {
    if (!moment()) return;
    stopAll();
    S.auto = false;
    updateBar();
    S.read = null;
    S.view = S.view === 'key' ? 'all' : 'key';
    clearRead();
    settleMap();
    showNow();
    renderTerm(false);
  });
  $('b-next').addEventListener('click', next);
  $('b-back').addEventListener('click', back);
  $('b-auto').addEventListener('click', () => {
    S.auto = !S.auto;
    updateBar();
    if (S.auto && S.m < 0) next();
    else if (S.auto && !S.busy) after(1500 / S.speed, () => next());
  });
  $('b-speed').addEventListener('click', () => {
    S.speed = SPEEDS[(SPEEDS.indexOf(S.speed) + 1) % SPEEDS.length];
    store.set('speed', String(S.speed));
    updateBar();
  });
  $('tab-split').addEventListener('click', () => setTab('split'));
  $('tab-whole').addEventListener('click', () => setTab('whole'));
  $('tab-long').addEventListener('click', () => setTab('long'));
  if ($('tab-res')) $('tab-res').addEventListener('click', () => setTab('res'));
  $('z-fit').addEventListener('click', () => setZoom(0));
  $('z-part').addEventListener('click', () => setPart(!S.part));
  $('z-in').addEventListener('click', () => setZoom(S.zi + 1));
  $('z-out').addEventListener('click', () => setZoom(S.zi - 1));
  const themes = ['system', 'light', 'dark'];
  function setTheme(v) {
    if (v === 'system') delete root.dataset.theme; else root.dataset.theme = v;
    if ($('long-f').dataset.on) syncLong();
    $('b-theme').textContent = 'Theme: ' + v;
    store.set('theme', v);
  }
  $('b-theme').addEventListener('click', () => {
    const cur = root.dataset.theme || 'system';
    setTheme(themes[(themes.indexOf(cur) + 1) % 3]);
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.closest && e.target.closest('input,textarea')) return;
    if (S.tab === 'long') return;
    if (e.key === 'ArrowRight') { e.preventDefault(); next(); } else if (e.key === 'ArrowLeft') { e.preventDefault(); back(); } else if (e.key === ' ' && e.target.tagName !== 'BUTTON') { e.preventDefault(); $('b-auto').click(); } else if (S.tab === 'whole' && (e.key === '+' || e.key === '=')) setZoom(S.zi + 1);
    else if (S.tab === 'whole' && e.key === '-') setZoom(S.zi - 1);
    else if (S.tab === 'whole' && e.key === '0') setZoom(0);
  });
  view.addEventListener('scroll', () => { paintMiniView(); pointer(S.ptr); }, { passive: true });
  $('over').addEventListener('scroll', () => pointer(S.ptr), { passive: true });
  view.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const z = zoomValue();
    const r = view.getBoundingClientRect();
    const wx = (view.scrollLeft + e.clientX - r.left) / z;
    const wy = (view.scrollTop + e.clientY - r.top) / z;
    const zi = clamp(S.zi + (e.deltaY < 0 ? 1 : -1), 1, ZOOMS.length - 1);
    if (zi !== S.zi) setZoom(zi, wx + (view.clientWidth / 2 - (e.clientX - r.left)) / ZOOMS[zi], wy + (view.clientHeight / 2 - (e.clientY - r.top)) / ZOOMS[zi]);
  }, { passive: false });
  let drag = null;
  view.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'mouse' || e.target.closest('.tb,.wa,.wi,button') || e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, l: view.scrollLeft, t: view.scrollTop };
    view.classList.add('drag');
  });
  window.addEventListener('pointermove', (e) => {
    if (!drag) return;
    view.scrollLeft = drag.l - (e.clientX - drag.x);
    view.scrollTop = drag.t - (e.clientY - drag.y);
  });
  window.addEventListener('pointerup', () => { drag = null; view.classList.remove('drag'); });
  $('mini').addEventListener('click', (e) => {
    const r = mini.getBoundingClientRect();
    const T = D.tree;
    const s = Math.min(r.width / T.W, r.height / T.H);
    const ox = (r.width - T.W * s) / 2;
    const oy = (r.height - T.H * s) / 2;
    const x = (e.clientX - r.left - ox) / s;
    const y = (e.clientY - r.top - oy) / s;
    const z = zoomValue();
    view.scrollLeft = x * z - view.clientWidth / 2;
    view.scrollTop = y * z - view.clientHeight / 2;
  });
  $('ptr').addEventListener('click', () => {
    if (!S.ptr) return;
    if (zoomValue()) { const z = zoomValue(); const r = V.world.R[S.ptr]; view.scrollLeft = r.x * z - 40; view.scrollTop = r.y * z - 40; } else { const el = V.over.blocks[S.ptr]; const o = $('over'); o.scrollTop += el.getBoundingClientRect().top - o.getBoundingClientRect().top - 20; }
  });
  /* the map is measured again when the room its branches have changes without the window telling: a view put beside it, a band above that wraps, a font arriving */
  if (window.ResizeObserver && !window.FG_NOFIT) {
    let rf = 0;
    fitWatch = new ResizeObserver(() => {
      cancelAnimationFrame(rf);
      rf = requestAnimationFrame(() => { if (S.tab !== 'split') return; const k = fitKeyOf(); if (!k || k === fitKey) return; measure(V.split); settleMap(); });
    });
    fitWatch.observe($('map'));
    fitEl = $('map').querySelector('.branches.lv');
    if (fitEl) fitWatch.observe(fitEl);
  }
  let rz = 0;
  window.addEventListener('resize', () => {
    clearTimeout(rz);
    rz = setTimeout(() => {
      reserveBar();
      if (S.tab === 'split') { measure(V.split); settleMap(); } else if (!zoomValue()) { measureOver(); const m = moment(); setEdges(V.over, m ? [m.p] : storyHops(), 'on'); }
    }, 120);
  });


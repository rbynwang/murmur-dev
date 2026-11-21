  /* ---------- nothing in a box is cut. The branches' boxes share the height their column has, so the map measures the boxes it has drawn and takes the
     first state in which every line stands whole inside its box (data-fit): 0 both lines as designed, 1 both lines and the branches' boxes closer,
     2 both lines and the whole map closer, 3 names only, 4 names only and the whole map closer, 5 names only and the map at its closest, 6 every box
     keeps its own height and the map scrolls. Sideways (data-fitw): 0 as designed, 1 narrower gutters, 2 the tags leave, 3 a name may take two lines.
     A band's box wraps a word that would be cut on the right (data-fitb). */
  function fitsBranches(brs) {
    for (const br of brs) {
      for (const blk of br.children) {
        if (!blk.classList.contains('blk')) continue;
        const cs = getComputedStyle(blk);
        const r = blk.getBoundingClientRect();
        const top = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop) - 0.05;
        const foot = r.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom) + 0.05;
        for (const ln of blk.children) {
          const c = getComputedStyle(ln);
          if (c.display === 'none' || c.position === 'absolute' || c.position === 'fixed') continue;
          const q = ln.getBoundingClientRect();
          if (q.top < top || q.bottom > foot) return false;                              /* a line stands outside the box's own padding, whatever pushed it there: the box is too low for what it holds */
          if (ln.classList.contains('sb') && ln.scrollWidth > ln.clientWidth + 1) return false;      /* a second line wider than its box would be cut sideways */
        }
      }
      if (br.scrollHeight > br.clientHeight + 1) return false;
    }
    return true;
  }
  function fitsWide(brs) {
    for (const br of brs) {
      for (const blk of br.children) {
        const bh = blk.classList.contains('blk') ? blk.querySelector('.bh') : null;
        if (bh && bh.scrollWidth > bh.clientWidth + 1) return false;
      }
    }
    return true;
  }
  /* a band's box (the aggregator's, the community agent's, NANDA Town, the return path) whose words run past its inner edge on the right */
  function bandsCut(host) {
    return qa('.band .blk', host).some((blk) => {
      const edge = blk.getBoundingClientRect().left + blk.clientLeft + blk.clientWidth + 0.5;
      return qa('.nm, .sb, .kd', blk).some((el) => { if (!el.offsetParent) return false; const g = document.createRange(); g.selectNodeContents(el); return g.getBoundingClientRect().right > edge; });
    });
  }
  /* the two counts above the branches stay inside the community's frame */
  function countsInside(host) {
    const pc = host.querySelector('.part.pcom');
    if (!pc) return true;
    const edge = pc.getBoundingClientRect().right - 5;
    return qa('.forks span', pc).every((sp) => { const g = document.createRange(); g.selectNodeContents(sp); return g.getBoundingClientRect().right <= edge; });
  }
  let fitKey = '';
  let fitEl = null;
  let fitWatch = null;
  function fitKeyOf() {
    const m = $('map');
    const b = m.querySelector('.branches.lv');
    if (!b || !b.offsetParent) return '';
    const r = b.getBoundingClientRect();
    return Math.round(r.width * 4) + 'x' + Math.round(r.height * 4) + ' in ' + m.clientWidth + 'x' + m.clientHeight;
  }
  function fitBranches(host) {
    if (window.FG_NOFIT || host !== $('map')) return;                    /* the tree at a glance scrolls, and its boxes keep their own height */
    const bx = host.querySelector('.branches.lv');
    const brs = bx ? qa('.br', bx) : [];
    if (!brs.length) return;
    host.setAttribute('data-fitb', '0');                                 /* the bands' boxes first: their height is the branches' room */
    if (bandsCut(host)) host.setAttribute('data-fitb', '1');
    let w = 0;
    for (; w < 3; w++) { host.setAttribute('data-fitw', String(w)); if (fitsWide(brs)) break; }
    host.setAttribute('data-fitw', String(w));
    if (w === 0 && !countsInside(host)) host.setAttribute('data-fitw', '1');
    const wide = host.getAttribute('data-fitw');
    let s = 0;
    for (; s < 6; s++) {
      host.setAttribute('data-fit', String(s));
      if (fitsBranches(brs)) break;
      if (s < 3 && wide === '0') {                                      /* both lines may fit once the gutters are narrower: a second line can be the widest thing in its box */
        host.setAttribute('data-fitw', '1');
        if (fitsBranches(brs)) break;
        host.setAttribute('data-fitw', wide);
      }
    }
    host.setAttribute('data-fit', String(s));
    if (fitWatch && fitEl !== bx) { if (fitEl) fitWatch.unobserve(fitEl); fitWatch.observe(bx); fitEl = bx; }
    fitKey = fitKeyOf();
  }
  /* a frame of the map that still cannot hold its boxes (a single site's, on a very low window) also ends the shrinking: the map scrolls */
  function fitScroll(host) {
    if (window.FG_NOFIT || host !== $('map') || host.getAttribute('data-fit') === '6') return;
    host.setAttribute('data-fit', '6');
    fitKey = fitKeyOf();
  }
  function measure(view) {
    if (!view.host.offsetParent && getComputedStyle(view.host).position !== 'fixed') return false;
    fitBranches(view.host);
    const box = view.host.getBoundingClientRect();
    const sx = view.host.scrollLeft;
    const sy = view.host.scrollTop;
    const p3 = view.host.querySelector('.parts3.t1');
    if (p3) {
      /* NANDA Town's band reaches across the single-site frames, and each site agent starts a short line below it */
      const tb = p3.querySelector('.band.town');
      const gaps = qa('.tsp', p3);
      const sites = qa('.part.psite', p3);
      tb.style.marginRight = '0px';
      gaps.forEach((el) => { el.style.height = '0px'; });
      sites.forEach((el) => { el.classList.remove('nonote', 'tight'); });
      if (getComputedStyle(p3).gridTemplateColumns.split(' ').length > 1) {
        tb.style.marginRight = (tb.getBoundingClientRect().right - p3.getBoundingClientRect().right) + 'px';
        const band = tb.getBoundingClientRect();
        /* a note that would run under the band is left out, and a frame too short for its boxes shows their names only */
        sites.forEach((el) => { const n = el.querySelector('.pn'); if (n && n.getBoundingClientRect().bottom > band.top - 3) el.classList.add('nonote'); });
        gaps.forEach((el) => { el.style.height = Math.max(0, band.bottom - el.getBoundingClientRect().top) + 'px'; });
        sites.forEach((el) => { if (el.scrollHeight > el.clientHeight + 1) el.classList.add('tight'); });
        if (sites.some((el) => el.scrollHeight > el.clientHeight + 1)) fitScroll(view.host);
      }
    }
    const R = {};
    Object.keys(view.blocks).forEach((b) => {
      const r = view.blocks[b].getBoundingClientRect();
      R[b] = { x: r.left - box.left + sx, y: r.top - box.top + sy, w: r.width, h: r.height };
    });
    const ret = view.host.querySelector('.band.ret').getBoundingClientRect();
    const hr = view.host.querySelector('.br.home').getBoundingClientRect();
    const br = view.host.querySelector('.br.bld').getBoundingClientRect();
    const tw = R.town;
    const buy = view.host.querySelector('.band.buy').getBoundingClientRect();
    const co = view.host.querySelector('.band.co').getBoundingClientRect();
    const lv = !!D.levels;
    view.R = R;
    view.G = { lv, coTop: co.top - box.top + sy, coL: co.left - box.left + sx, coR: co.right - box.left + sx, railY: view.extra || lv ? buy.bottom - box.top + sy + 7 : 0, railL: tw.x + 8, railR: tw.x + tw.w - 8, skipH: hr.right - box.left + sx + 10, skipB: br.left - box.left + sx - 10, sensH: hr.left - box.left + sx - 10, sensB: br.right - box.left + sx + 10, persH: hr.left - box.left + sx - 20, persB: br.right - box.left + sx + 20, retX: (hr.right + br.left) / 2 - box.left + sx, retY: ret.top - box.top + sy - 7, three: !!view.host.querySelector('.parts3'), t1: !!p3, townB: tw.y + tw.h, buyB: buy.bottom - box.top + sy, pt: Object.fromEntries(qa('.part.psite', view.host).map((el) => [el.querySelector('.blk').getAttribute('data-b') || '', el.getBoundingClientRect().top - box.top + sy])) };
    drawLinks(view);
    return true;
  }


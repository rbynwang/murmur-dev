/* What the walk check looks at inside a page. Each snippet is one function expression. */

// @moment
/* One moment of the replay, in the view on screen (the split view's map, or the whole picture's tree): a box outside its frame or
   outside the map, a single site's frame too short for its boxes, the message network's band not reaching the last frame, text cut
   by its own box, the bar's line cut, the whole picture's caption cut under its number, the panel running under the bar or a card
   wider than it, the page scrolling sideways. Returns the faults in words. */
() => {
  const bad = [];
  const vis = (e) => { if (!e) return false; const c = getComputedStyle(e); if (c.display === 'none' || c.visibility === 'hidden') return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const name = (e) => (e.id ? '#' + e.id : e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : '')) + ' "' + (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30) + '"';
  const whole = !document.getElementById('whole').hidden && vis(document.getElementById('whole'));
  const host = whole ? document.getElementById('over') : document.getElementById('map');
  if (host && vis(host)) {
    const hb = host.getBoundingClientRect();
    host.querySelectorAll('.part.psite').forEach((f) => {
      const fr = f.getBoundingClientRect(); let low = 0;
      f.querySelectorAll('.blk, .ins').forEach((b) => { if (vis(b)) low = Math.max(low, b.getBoundingClientRect().bottom); });
      if (low > fr.bottom + 1.5) bad.push('a site frame is too short for its boxes by ' + Math.round(low - fr.bottom) + ' px: ' + name(f.querySelector('.lg')));
      const n = f.querySelector('.pn'), t = host.querySelector('.band.town');
      if (n && vis(n) && t && n.getBoundingClientRect().bottom > t.getBoundingClientRect().top + 1) bad.push('a site note runs under the band');
    });
    const p3 = host.querySelector('.parts3.t1'), tb = host.querySelector('.parts3.t1 .band.town');
    if (p3 && tb && getComputedStyle(p3).gridTemplateColumns.split(' ').length > 1) {
      const gap = p3.getBoundingClientRect().right - tb.getBoundingClientRect().right;
      if (Math.abs(gap) > 3) bad.push("NANDA Town's band ends " + Math.round(gap) + ' px from the last frame');
      host.querySelectorAll('.part.psite .blk').forEach((b) => { const d = b.getBoundingClientRect().top - tb.getBoundingClientRect().bottom; if (d < 8) bad.push('a site agent sits ' + Math.round(d) + ' px under the band'); });
    }
    if (!whole) host.querySelectorAll('.blk, .band, .part').forEach((b) => {
      if (!vis(b)) return; const r = b.getBoundingClientRect();
      if (r.right > hb.right + 2 || r.bottom > hb.bottom + 2 || r.left < hb.left - 2) bad.push('outside the map: ' + name(b));
    });
    host.querySelectorAll('.blk .nm, .blk .sb, .ins, .lg, .fk, .pn').forEach((e) => {
      if (!vis(e)) return; const c = getComputedStyle(e);
      if (e.scrollWidth > e.clientWidth + 1 && c.overflowX !== 'visible') bad.push('cut sideways: ' + name(e));
    });
  }
  const tr = document.querySelector('#bar .truth, #bar p, #bar .bt');
  document.querySelectorAll('#bar *').forEach((e) => { if (e.children.length === 0 && vis(e) && e.scrollWidth > e.clientWidth + 1) bad.push('the bar cuts: ' + name(e)); });
  const cap = document.getElementById('w-cap'), wn = cap && cap.closest('.wnow');
  if (cap && vis(cap) && wn && cap.getBoundingClientRect().bottom > wn.getBoundingClientRect().bottom + 1) bad.push('the caption under the number is cut by ' + Math.round(cap.getBoundingClientRect().bottom - wn.getBoundingClientRect().bottom) + ' px');
  const h = document.getElementById('now-h');
  if (h && vis(h) && h.scrollWidth > h.clientWidth + 1) bad.push('the headline is cut: ' + name(h));
  if (!whole) {
    const lay = document.getElementById('layer');
    if (lay && vis(lay)) {
      const lr = lay.getBoundingClientRect();
      if (lr.bottom > innerHeight - 40) bad.push('the panel runs under the bar by ' + Math.round(lr.bottom - (innerHeight - 40)) + ' px');
      lay.querySelectorAll('.big, .lstat, .cards > *, .nowp').forEach((e) => { if (vis(e) && e.getBoundingClientRect().right > lr.right + 2) bad.push('wider than the panel: ' + name(e)); });
    }
  }
  if (document.documentElement.scrollWidth > innerWidth + 1) bad.push('the page scrolls sideways');
  return bad;
};

// @sections
/* The sections behind the whole picture's own buttons: every line inside its card, nothing squeezed or cut sideways, and a section
   that runs past the screen can be scrolled. Returns the faults in words. */
() => {
  const bad = [];
  document.querySelectorAll('section.engie').forEach((sec) => {
    const c = getComputedStyle(sec); if (sec.hidden || c.display === 'none') return;
    const sr = sec.getBoundingClientRect(); if (!sr.width) return;
    sec.querySelectorAll('li, td, th, dd, dt, p, h2, h3, h4, article').forEach((e) => {
      const r = e.getBoundingClientRect(); if (!r.width && !r.height) return;
      const art = e.closest('article') || sec, ar = art.getBoundingClientRect();
      const t = (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 34);
      if (e !== art && (r.left < ar.left - 2 || r.right > ar.right + 2 || r.top < ar.top - 2 || r.bottom > ar.bottom + 2)) bad.push('outside its card: ' + e.tagName.toLowerCase() + ' "' + t + '"');
      if (t.length > 12 && r.width < 40) bad.push('squeezed to ' + Math.round(r.width) + ' px: ' + e.tagName.toLowerCase() + ' "' + t + '"');
      if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible') bad.push('cut sideways: "' + t + '"');
    });
    if (sr.bottom > innerHeight + 1 && sec.scrollHeight <= sec.clientHeight + 1 && document.documentElement.scrollHeight <= innerHeight + 1) bad.push('the section runs ' + Math.round(sr.bottom - innerHeight) + ' px past the screen with no way to scroll');
  });
  if (document.documentElement.scrollWidth > innerWidth + 1) bad.push('the page scrolls sideways');
  return bad;
};

// @section_buttons
() => [...document.querySelectorAll('button.zb')].map(b => b.textContent.trim()).filter(x => x.length > 2 && x !== 'Overview');

// @data
/* The Data view as it stands: on, every part's squares shown inside their box and clear of its name, the data panel inside its
   side, nothing cut sideways, the page not scrolling sideways. Returns { bad, scroll (how far the panel scrolls), lit, dim, sel,
   title (the panel's heading) }. */
() => {
  const bad = [], map = document.getElementById('map'), dv = document.getElementById('dv'), body = document.getElementById('dvb');
  if (!document.getElementById('app').classList.contains('dv')) bad.push('the data view is not on');
  map.querySelectorAll('[data-dv]').forEach((n) => {
    const q = n.querySelector('.dq'); if (!q) { bad.push('no squares: ' + n.textContent.trim().slice(0, 24)); return; }
    const qr = q.getBoundingClientRect(), nr = n.getBoundingClientRect(), nm = n.querySelector('.nm, b');
    if (!qr.width) bad.push('squares not shown: ' + n.textContent.trim().slice(0, 24));
    if (!n.classList.contains('lg') && (qr.right > nr.right + 1 || qr.bottom > nr.bottom + 1 || qr.top < nr.top - 1)) bad.push('squares outside their box: ' + n.textContent.trim().slice(0, 24));
    if (nm && !n.classList.contains('lg')) { const r = document.createRange(); r.selectNodeContents(nm); const rs = [...r.getClientRects()]; if (rs.some((t) => t.right > qr.left + 0.5 && t.left < qr.right && t.bottom > qr.top + 0.5 && t.top < qr.bottom)) bad.push('squares over the name: ' + n.textContent.trim().slice(0, 24)); }
  });
  const pr = document.getElementById('panel').getBoundingClientRect(), dr = dv.getBoundingClientRect();
  if (dr.right > pr.right + 1 || dr.bottom > pr.bottom + 1) bad.push('the data panel runs past its side');
  const scroll = body.scrollHeight - body.clientHeight;
  dv.querySelectorAll('h2, h3, h4, p, li, td, b, span, button').forEach((e) => { if (e.children.length === 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible' && getComputedStyle(e).display !== 'inline') bad.push('cut sideways: ' + e.textContent.trim().slice(0, 30)); });
  if (document.documentElement.scrollWidth > innerWidth + 1) bad.push('the page scrolls sideways');
  return { bad, scroll, lit: map.querySelectorAll('.hit').length, dim: map.querySelectorAll('.dim').length, sel: map.querySelectorAll('.dsel').length, title: (dv.querySelector('.dvp h3') || {}).textContent || '' };
};

// @data_parts
() => JSON.parse(document.getElementById('fg-dv').textContent);

// @data_filter
(f) => { FG.dataView.state.sel = null; FG.dataView.filter(f); };

// @data_select
(k) => FG.dataView.select(k);

// @data_title
() => (document.querySelector('#dv .dvp h3') || {}).textContent || '';

// @back
/* The split view after the Data view: whether the data view is still on, the replay's panel and position, the squares, the tabs. */
() => ({ dv: document.getElementById('app').classList.contains('dv'), layer: getComputedStyle(document.getElementById('layer')).display, pos: document.getElementById('pos').textContent, sq: getComputedStyle(document.querySelector('#map .dq')).display, tabs: [...document.querySelectorAll('#bar .tab')].filter(t => getComputedStyle(t).display !== 'none').map(t => t.textContent) });

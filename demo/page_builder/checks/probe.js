/* The fit probe: is any word of the diagram cut, in the window as it stands? It looks only at what is on screen in `.map` (the
   replay's diagram) and `.over` (the whole picture):

     1. every box (`.blk`): its name (`.nm`) and its second line (`.sb`) stand inside the box, at least a pixel clear of its outer
        edge at the top and at the foot. A box that is too low for its lines cuts them there, because a box hides what runs past it;
     2. every piece of text in a box, measured as the ink of its own letters (the drawn size of that string in that font, so the
        tails of g, p and y count and a line of capitals is not blamed for tails it does not have): a pixel clear of the box's inner
        edge at the top and at the foot, and inside the box sideways;
     3. no box is cut by a frame around it, no two boxes overlap, and no letter stands under a mark of its own box (the Live view's
        dot, the Data view's bar);
     4. every other word of the diagram (frame labels, the two counts, notes): not cut by a frame around it, and not over a box.

   What a scrolling frame keeps below its edge is not a fault: it can be scrolled to. It is counted, so a check can say when a view
   scrolls. Returns { faults: [{ host, kind, box, what, by, text }], hosts: [what each host holds], vw, vh, plex }. */
() => {
  const TOL = 0.02, EDGE = 1, ROOM = 1;
  const found = new Map(), hosts = [];
  const shown = (e) => { const c = getComputedStyle(e); if (c.display === 'none' || c.visibility !== 'visible') return false; const r = e.getBoundingClientRect(); return r.width > 0.5 && r.height > 0.5; };
  const say = (e) => (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 34);
  const cls = (e) => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  const boxName = (b) => { const n = b.querySelector('.nm'); return (n ? say(n) : say(b)) || b.getAttribute('data-b') || 'box'; };
  const ownText = (e) => { const out = []; for (const n of e.childNodes) { if (n.nodeType === 3 && n.nodeValue.trim()) { const g = document.createRange(); g.selectNodeContents(n); for (const r of g.getClientRects()) if (r.width > 0.5 && r.height > 0.5) out.push(r); } } return out; };
  /* the ink of a run of text: from the rectangle its letters could fill (the font's own rise and fall around the baseline) to what this string really draws */
  const cv = document.createElement('canvas').getContext('2d');
  const ink = (e, r, node) => {
    const c = getComputedStyle(e); let t = node.nodeValue.replace(/\s+/g, ' ').trim();
    if (c.textTransform === 'uppercase') t = t.toUpperCase(); else if (c.textTransform === 'lowercase') t = t.toLowerCase();
    cv.font = c.font || (c.fontStyle + ' ' + c.fontWeight + ' ' + c.fontSize + ' ' + c.fontFamily);
    const m = cv.measureText(t); if (!(m.fontBoundingBoxAscent > 0)) return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
    const base = r.top + (r.height - (m.fontBoundingBoxAscent + m.fontBoundingBoxDescent)) / 2 + m.fontBoundingBoxAscent;
    return { top: base - m.actualBoundingBoxAscent, bottom: base + m.actualBoundingBoxDescent, left: r.left, right: r.right };
  };
  const ownInk = (e) => { const out = []; for (const n of e.childNodes) { if (n.nodeType === 3 && n.nodeValue.trim()) { const g = document.createRange(); g.selectNodeContents(n); const rs = [...g.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5); rs.forEach((r) => out.push(rs.length === 1 ? ink(e, r, n) : { top: r.top + r.height * 0.12, bottom: r.bottom - r.height * 0.04, left: r.left, right: r.right })); } } return out; };
  const inner = (x) => { const r = x.getBoundingClientRect(); return { top: r.top + x.clientTop, left: r.left + x.clientLeft, bottom: r.top + x.clientTop + x.clientHeight, right: r.left + x.clientLeft + x.clientWidth }; };
  /* the first frame, from this element outward, that cuts the rectangle; a frame that scrolls ends the search, since what is past its edge can be scrolled to */
  const cutBy = (from, r) => {
    for (let x = from; x && x.nodeType === 1; x = x.parentElement) {
      const c = getComputedStyle(x), oy = c.overflowY, ox = c.overflowX; if (oy === 'visible' && ox === 'visible') continue;
      const b = inner(x), dy = Math.max(b.top - r.top, r.bottom - b.bottom), dx = Math.max(b.left - r.left, r.right - b.right);
      if (dy > TOL && oy !== 'visible') return (oy === 'auto' || oy === 'scroll') ? { scroll: true } : { el: x, by: dy, side: b.top - r.top > r.bottom - b.bottom ? 'at the top' : 'at the foot' };
      if (dx > TOL && ox !== 'visible') return (ox === 'auto' || ox === 'scroll') ? { scroll: true } : { el: x, by: dx, side: 'sideways' };
    }
    return null;
  };
  const add = (host, kind, box, what, by, text) => { const k = host + '|' + kind + '|' + box + '|' + what; const o = found.get(k); if (!o || by > o.by) found.set(k, { host, kind, box, what, by: +by.toFixed(2), text }); };
  const over = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  document.querySelectorAll('.map, .over').forEach((host) => {
    if (!shown(host)) return;
    const hn = host.classList.contains('over') ? 'over' : 'map';
    const H = { host: hn, boxes: 0, names: 0, seconds: 0, texts: 0, scrolled: 0, scrollsBy: Math.max(0, host.scrollHeight - host.clientHeight), fit: host.getAttribute('data-fit'), lowest: null, branchSeconds: 0 };
    const blks = [...host.querySelectorAll('.blk')].filter(shown), rects = blks.map((b) => b.getBoundingClientRect());
    blks.forEach((blk, i) => {
      const b = rects[i], bn = boxName(blk), pb = inner(blk); H.boxes += 1;
      if (blk.closest('.br')) { H.lowest = H.lowest === null ? b.height : Math.min(H.lowest, b.height); }
      blk.querySelectorAll('.nm, .sb').forEach((t) => {
        if (!shown(t)) return; const r = t.getBoundingClientRect(), w = t.classList.contains('nm') ? 'its name' : 'its second line';
        if (t.classList.contains('nm')) H.names += 1; else { H.seconds += 1; if (blk.closest('.br')) H.branchSeconds += 1; }
        if (r.top < b.top + EDGE - TOL) add(hn, 'cut at the top', bn, w, b.top + EDGE - r.top, say(t));
        if (r.bottom > b.bottom - EDGE + TOL) add(hn, 'cut at the foot', bn, w, r.bottom - (b.bottom - EDGE), say(t));
      });
      const marks = [...blk.querySelectorAll('.lq, .dq')].filter((m) => shown(m) && getComputedStyle(m).position === 'absolute').map((m) => m.getBoundingClientRect());
      [blk, ...blk.querySelectorAll('*')].forEach((t) => {
        if (t !== blk && !shown(t)) return;
        ownInk(t).forEach((r) => {
          H.texts += 1; const w = t === blk ? 'its words' : cls(t);
          marks.forEach((m) => { const dx = Math.min(r.right, m.right) - Math.max(r.left, m.left), dy = Math.min(r.bottom, m.bottom) - Math.max(r.top, m.top); if (dx > 0.5 && dy > 0.5) add(hn, 'under a mark of its box (a dot or a bar)', bn, w, dx, say(t)); });
          if (r.top < pb.top + ROOM - TOL) add(hn, 'letters within ' + ROOM + ' px of the top edge, or past it', bn, w, pb.top + ROOM - r.top, say(t));
          if (r.bottom > pb.bottom - ROOM + TOL) add(hn, 'letters within ' + ROOM + ' px of the foot, or past it', bn, w, r.bottom - (pb.bottom - ROOM), say(t));
          if (r.left < pb.left - TOL || r.right > pb.right + TOL) add(hn, 'cut sideways', bn, w, Math.max(pb.left - r.left, r.right - pb.right), say(t));
        });
      });
      const c = cutBy(blk.parentElement, b);
      if (c && c.scroll) H.scrolled += 1; else if (c) add(hn, 'box cut ' + c.side + ' by ' + cls(c.el), bn, 'the box', c.by, '');
      for (let j = 0; j < i; j++) if (over(b, rects[j]) && !blk.contains(blks[j]) && !blks[j].contains(blk)) add(hn, 'two boxes overlap', bn, boxName(blks[j]), Math.min(b.bottom, rects[j].bottom) - Math.max(b.top, rects[j].top), '');
    });
    host.querySelectorAll('*').forEach((t) => {
      if (t.closest('.blk') || t.closest('svg') || !shown(t)) return;
      const rs = ownInk(t); if (!rs.length) return;
      rs.forEach((r) => {
        H.texts += 1; const c = cutBy(t, r);
        if (c && c.scroll) H.scrolled += 1; else if (c) add(hn, 'cut ' + c.side + ' by ' + cls(c.el), '(outside the boxes)', cls(t), c.by, say(t));
        rects.forEach((b, i) => { if (over(r, b)) add(hn, 'stands over a box', boxName(blks[i]), cls(t), Math.min(r.bottom, b.bottom) - Math.max(r.top, b.top), say(t)); });
      });
    });
    hosts.push(H);
  });
  return { faults: [...found.values()], hosts, vw: innerWidth, vh: innerHeight, plex: !!(document.fonts && document.fonts.check('600 15px "IBM Plex Sans"')) };
}

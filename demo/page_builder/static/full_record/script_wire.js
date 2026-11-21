  // ---- the wire: a bus down the sheet, taps at each layer, a path for the step, a packet along it
  function box(n) {
    const r = n.getBoundingClientRect(), s = sheet.getBoundingClientRect();
    return { x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height, layer: n.closest('.layer'), py: +n.dataset.py || 0 };
  }
  function busX() { return narrow.matches ? 7 : parseFloat(getComputedStyle(root).getPropertyValue('--bus')) || 22; }
  function seg(a, b) {
    const bx = busX();
    const ay = a.y + (a.py || Math.min(a.h / 2, 26)), by = b.y + (b.py || Math.min(b.h / 2, 26));
    if (a.layer === b.layer) {
      const ox0 = Math.max(a.x, b.x), ox1 = Math.min(a.x + a.w, b.x + b.w), oy0 = Math.max(a.y, b.y), oy1 = Math.min(a.y + a.h, b.y + b.h);
      if (ox1 - ox0 > 16) { const x = (ox0 + ox1) / 2; return a.y < b.y ? [[x, a.y + a.h], [x, b.y]] : [[x, a.y], [x, b.y + b.h]]; }
      if (oy1 - oy0 > 8) { const y = a.py ? ay : (oy0 + oy1) / 2; return a.x < b.x ? [[a.x, y], [b.x, y]] : [[a.x + a.w, y], [b.x + b.w, y]]; }
      const mid = a.y + a.h <= b.y ? (a.y + a.h + b.y) / 2 : (b.y + b.h + a.y) / 2;
      const ax = a.x + a.w / 2, cx = b.x + b.w / 2;
      return a.y < b.y ? [[ax, a.y + a.h], [ax, mid], [cx, mid], [cx, b.y]] : [[ax, a.y], [ax, mid], [cx, mid], [cx, b.y + b.h]];
    }
    return [[a.x, ay], [bx, ay], [bx, by], [b.x, by]];
  }
  function chainPoints(ids) {
    const ns = ids.map(el).filter(Boolean);
    if (ns.length < 2) return null;
    const rs = ns.map(box);
    let pts = [];
    for (let i = 0; i + 1 < rs.length; i++) {
      const s = seg(rs[i], rs[i + 1]);
      pts = pts.concat(i ? s : s);
    }
    return pts;
  }
  function sizeWire() {
    const r = sheet.getBoundingClientRect();
    wire.setAttribute('width', r.width);
    wire.setAttribute('height', sheet.scrollHeight);
    wire.setAttribute('viewBox', '0 0 ' + r.width + ' ' + sheet.scrollHeight);
    drawBus();
  }
  function drawBus() {
    const g = $('busg');
    g.replaceChildren();
    const ls = Array.from(document.querySelectorAll('.layer'));
    if (!ls.length) return;
    const x = busX(), first = box(ls[0]), last = box(ls[ls.length - 1]);
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', x); line.setAttribute('x2', x);
    line.setAttribute('y1', first.y + 18); line.setAttribute('y2', last.y + 18);
    line.setAttribute('class', 'busline');
    g.append(line);
    ls.forEach((l) => {
      const b = box(l), y = b.y + 18;
      const stub = document.createElementNS(NS, 'line');
      stub.setAttribute('x1', x); stub.setAttribute('x2', b.x); stub.setAttribute('y1', y); stub.setAttribute('y2', y);
      stub.setAttribute('class', 'busline');
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 5);
      c.setAttribute('class', 'tap'); c.dataset.l = l.dataset.l;
      c.style.setProperty('--tap', 'var(--' + TAPS[l.dataset.l] + ')');
      g.append(stub, c);
    });
  }
  function hueOf(st) { return getComputedStyle(root).getPropertyValue(HUE[(st && st.c) || (st && st.L && st.L[0]) || 3] || '--c3').trim(); }
  function clearPath() {
    cancelAnimationFrame(S.anim);
    $('paths').replaceChildren();
    document.querySelectorAll('.pkt').forEach((p) => { p.style.transform = 'translate(-9999px,0)'; });
  }
  function drawPath(st, animate, ms) {
    clearPath();
    if (!st || !st.p || !st.p.length) return;
    const g = $('paths'), color = hueOf(st);
    const paths = [];
    for (const ids of st.p) {
      const pts = chainPoints(ids);
      if (!pts) continue;
      const d = 'M' + pts.map((q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1)).join('L');
      const glow = document.createElementNS(NS, 'path');
      glow.setAttribute('d', d); glow.setAttribute('class', 'pathglow'); glow.setAttribute('stroke', color);
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('d', d); p.setAttribute('class', 'path'); p.setAttribute('stroke', color);
      g.append(glow, p);
      paths.push(p);
    }
    if (!paths.length) return;
    const packets = paths.slice(0, 3).map((p, i) => {
      let k = $('pkt' + i);
      if (!k) {
        k = document.createElement('div'); k.id = 'pkt' + i; k.className = 'pkt';
        k.innerHTML = '<i></i><span></span>';
        sheet.append(k);
      }
      k.style.setProperty('--pk', color);
      const lab = k.querySelector('span');
      lab.textContent = i === 0 ? (st.pk || '') : '';
      lab.hidden = !(i === 0 && st.pk);
      return { el: k, path: p, len: p.getTotalLength() };
    });
    const place = (t) => {
      for (const q of packets) {
        const pt = q.path.getPointAtLength(q.len * t);
        const room = sheet.clientWidth - 300;
        q.el.style.transform = 'translate(' + Math.min(pt.x, Math.max(0, room)).toFixed(1) + 'px,' + (pt.y - 10).toFixed(1) + 'px)';
      }
    };
    if (!animate || calm.matches) return;
    const t0 = performance.now();
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / ms);
      const e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      place(e);
      if (t < 1) S.anim = requestAnimationFrame(frame);
      else for (const q of packets) q.el.style.transform = 'translate(-9999px,0)';
    };
    S.anim = requestAnimationFrame(frame);
  }

  // ---- a long record runs past during its step, and the guard's checks light as its trace reaches them
  function sweepEnd() {
    cancelAnimationFrame(S.swp);
    if (S.swpEnd) { S.swpEnd(); S.swpEnd = null; }
  }
  function sweep(st, rows, animate, ms) {
    if (!animate || calm.matches || !st || !rows.length) return;
    const box2 = rows[0].closest('.tb');
    if (!box2 || box2.dataset.held === '1') return;
    const inBox = rows.filter((r) => r.closest('.tb') === box2);
    const last = inBox[inBox.length - 1];
    const from = Math.max(0, rows[0].offsetTop - box2.clientHeight * 0.2), to = Math.max(from, last.offsetTop + last.offsetHeight - box2.clientHeight + 6);
    const marks = (st.ck || []).slice();
    if (to <= from + 4 && !marks.length) return;
    if (marks.length) for (let i = 1; i <= 6; i++) { const c = el('ck-' + i); if (c) c.dataset.st = ''; }
    S.swpEnd = () => { if (st.k) for (const id in st.k) if (id.startsWith('ck-')) setK(id, st.k[id]); };
    const t0 = performance.now(), span = ms * 0.86;
    let on = null;
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / span);
      box2.scrollTop = from + (to - from) * t;
      while (marks.length && marks[0][0] <= t) {
        if (on) on.dataset.st = 'ok';
        on = el('ck-' + marks.shift()[1]);
        if (on) on.dataset.st = 'run';
      }
      if (t < 1) S.swp = requestAnimationFrame(frame);
      else sweepEnd();
    };
    S.swp = requestAnimationFrame(frame);
  }

  // ---- the camera: follows the step unless the reader has scrolled away
  function follow(st, ms) {
    if (!S.follow || !st) return;
    const term = st.f ? el(st.f) : null;
    const hotId = st.h && st.h[0];
    const anchor = hotId ? el(hotId) : null;
    const t = term ? term.getBoundingClientRect() : null, a = anchor ? anchor.getBoundingClientRect() : null;
    if (!t && !a) return;
    const vh = window.innerHeight - (parseFloat(getComputedStyle(root).getPropertyValue('--bar-h')) || 100);
    const lo = Math.min(t ? t.top : 1e9, a ? a.top : 1e9), hi = Math.max(t ? t.bottom : -1e9, a ? a.bottom : -1e9);
    let goal;
    if (hi - lo <= vh - 24) {
      if (lo >= 8 && hi <= vh - 8) return;
      goal = lo - Math.min(60, (vh - (hi - lo)) / 2);
    } else {
      const m = t || a;
      if (m.top >= 8 && m.bottom <= vh - 8) return;
      goal = m.top - Math.max(8, (vh - m.height) / 2);
    }
    glide(Math.max(0, window.scrollY + goal), ms);
  }
  function glide(to, ms) {
    cancelAnimationFrame(S.cam);
    if (calm.matches || !ms) { S.programmatic = performance.now() + 120; window.scrollTo(0, to); return; }
    const from = window.scrollY, t0 = performance.now(), span = Math.min(Math.max(ms, 240), 900);
    const frame = (now) => {
      const t = Math.min(1, (now - t0) / span);
      const e = 1 - Math.pow(1 - t, 3);
      S.programmatic = now + 120;
      window.scrollTo(0, from + (to - from) * e);
      if (t < 1) S.cam = requestAnimationFrame(frame);
    };
    S.cam = requestAnimationFrame(frame);
  }
  function setFollow(on) {
    S.follow = on;
    $('b-follow').setAttribute('aria-pressed', String(on));
    $('b-follow').textContent = on ? 'Follow' : 'Rejoin';
    if (on) {
      document.querySelectorAll('.tb, .chat').forEach((b) => { delete b.dataset.held; });
      const st = S.seq.steps[S.pos];
      if (st) follow(st, 500);
    }
  }
  function userMoved() { if (S.follow) setFollow(false); }
  window.addEventListener('wheel', (e) => { if (!e.target.closest || !e.target.closest('.tb, .chat, .trade, .rail, .ledw')) userMoved(); }, { passive: true });
  window.addEventListener('touchmove', (e) => { if (!e.target.closest || !e.target.closest('.tb, .chat, .trade, .rail, .ledw, .bar')) userMoved(); }, { passive: true });
  let lastY = window.scrollY;
  window.addEventListener('scroll', () => {
    const y = window.scrollY;
    if (Math.abs(y - lastY) > 30 && performance.now() > S.programmatic) userMoved();
    lastY = y;
  }, { passive: true });
  document.querySelectorAll('.tb, .chat').forEach((b) => {
    const hold = () => { b.dataset.held = '1'; };
    b.addEventListener('wheel', hold, { passive: true });
    b.addEventListener('touchmove', hold, { passive: true });
  });


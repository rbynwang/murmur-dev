  /* ---------- the whole picture */
  /* the day being played, in words, and an event's figure beside the day it stands against */
  function dayWords() { const c = SC.list.find((x) => x.id === S.sc); return c && c.date ? c.name + ', ' + c.date : 'This day'; }
  const beside = (r) => r[0] + ' ' + r[1] + ', ' + story().vs + ' ' + r[2];
  let worldFor = null;
  function renderWorld() {
    const st = story();
    if (worldFor === st.id) return;
    worldFor = st.id;
    const per = {};
    BI.forEach((id) => { per[id] = []; });
    st.moments.forEach((m, mi) => {
      const seen = {};
      m.s.forEach((si) => {
        const s = st.steps[si];
        const by = {};
        s.l.forEach((l) => lineBlocks(l).forEach((i) => { (by[BI[i]] = by[BI[i]] || []).push(l); }));
        Object.keys(by).forEach((id) => {
          if (!seen[id]) { seen[id] = 1; per[id].push('<li class="mh" data-m="' + mi + '">' + (mi + 1) + '. ' + esc(m.n) + '</li>'); }
          per[id].push(ttlHTML(s, mi));
          by[id].forEach((l) => per[id].push(liHTML(l, { m: mi, mark: true })));
        });
      });
    });
    BI.forEach((id) => {
      const el = $('T-' + id);
      if (!el) return;
      el.innerHTML = per[id].join('') || (id === 'input' ? '<li class="ln k-in"><i class="g">←</i><span class="m">' + esc(st.sent.full) + '</span></li>' : '<li class="miss">' + (absent(id) ? NOT_HERE + '.' : 'Nothing at this block in this story.') + '</li>');
      setHue(el, 'tb', id);
    });
    $('w-story').textContent = st.name;
    $('w-note').textContent = st.note + (st.ends ? ' ' + st.ends : '');
    const led = st.ledger || [];
    $('w-ledger').innerHTML = led.map((r, i) => '<tr>' + r.map((c) => (i ? '<td>' : '<th scope="col">') + esc(c) + (i ? '</td>' : '</th>')).join('') + '</tr>').join('');
    $('w-effect').textContent = st.effect.length ? st.effect.map(beside).join(' · ') : (st.own ? dayWords() + ', as it ran.' : 'The ordinary day, with no event.');
    qa('[data-kn]').forEach((el) => { el.textContent = st.nums[el.getAttribute('data-kn')] || ''; });
    qa('#over [data-fork]').forEach((el) => { el.textContent = el.getAttribute('data-all') + (!/^\d/.test(el.getAttribute('data-all')) ? '' : ', ' + st.followed[+el.getAttribute('data-fork')] + ' followed here'); });
  }
  function firstArrival(b, m) {
    const st = story();
    const bi = BI.indexOf(b);
    const list = m ? m.s : st.steps.map((_, i) => i);
    for (let k = 0; k < list.length; k++) {
      const s = st.steps[list[k]];
      if (s.b.indexOf(bi) >= 0) return s;
    }
    return null;
  }
  /* what a block's arrival line says at a moment, or at rest when m is null */
  function arrivalText(el, m) {
    const st = story();
    const b = el.getAttribute('data-in');
    const brief = !!el.closest('.over');
    if (b === 'input') return brief ? st.sent.plain : st.sent.who + ': ' + st.sent.full;
    if (b === 'trade') return st.effect.length ? beside(st.effect[0]) : (st.own ? dayWords() : 'The ordinary day');
    if (absent(b)) return brief ? NOT_HERE : NOT_HERE + '.';
    const s = (m && firstArrival(b, m)) || firstArrival(b, null);
    if (!s) return BN[b] && BN[b].lv && BN[b].s ? BN[b].s : brief ? 'Nothing arrives here' : 'Nothing arrives here in this story.';
    const who = s.f && s.f !== 'None' ? s.f + ': ' : '';
    return brief ? '← ' + s.n : s.t + '. ' + who + s.p;
  }
  function fillInputs() {
    const m = moment();
    qa('[data-in]').forEach((el) => { el.textContent = arrivalText(el, m); });
  }
  /* The tree at a glance holds still through a story, and cuts no word. Each arrival line is given the room its longest words need at this width,
     so a row keeps one height from the first moment to the last. Worked out once for a story and a width. */
  let reserved = '';
  function reserveOver() {
    const over = $('over');
    if (over.hidden || !over.offsetParent) return;
    const st = story();
    const key = S.sc + '|' + st.id + '|' + over.clientWidth;
    if (key === reserved) return;
    reserved = key;
    const els = qa('[data-in]', over);
    const need = els.map(() => 0);
    els.forEach((el) => { el.style.minHeight = ''; });
    [null].concat(st.moments).forEach((m) => {
      els.forEach((el) => { el.textContent = arrivalText(el, m); });
      els.forEach((el, i) => { need[i] = Math.max(need[i], el.getBoundingClientRect().height); });
    });
    /* layout works in 64ths of a pixel: the reserved height is kept to that exactly, so a row is the same height whichever words it holds */
    els.forEach((el, i) => { if (need[i]) el.style.minHeight = (Math.ceil(need[i] * 64 - 1e-6) / 64).toFixed(6) + 'px'; });
    fillInputs();
  }
  /* the lines of the tree at a glance, drawn on the rows as they stand now */
  function measureOver() { reserveOver(); return measure(V.over); }
  function fillTradeBlock() {
    const st = story();
    const fin = S.m < 0 || ended();
    const v = Object.assign({}, st.base);
    const fresh = {};
    st.moments.forEach((m, i) => { if (fin || i <= S.m) { Object.assign(v, m.tv); } if (i === S.m) Object.assign(fresh, m.tv); });
    qa('.tvr').forEach((r) => {
      const k = r.getAttribute('data-tv');
      r.hidden = !v[k];
      r.children[1].textContent = v[k] || '';
      r.classList.toggle('fresh', !!fresh[k]);
    });
  }
  let curRule = null;
  function markLines() {
    if (!curRule) { curRule = document.createElement('style'); curRule.id = 'fg-cur'; document.head.appendChild(curRule); }
    const m = moment();
    curRule.textContent = m ? '.wt li[data-m]{opacity:.62}.wt li[data-m="' + S.m + '"]{opacity:1}' : '';
  }
  function paintWhole(lit, now, hops) {
    paintBlocks(V.world, lit, now);
    paintBlocks(V.over, lit, now);
    setEdges(V.world, hops, 'on');
    setEdges(V.over, hops, 'on');
    paintMini(lit, now);
  }
  function applyWhole(play) {
    const began = performance.now();
    renderWorld();
    fillInputs();
    fillTradeBlock();
    markLines();
    /* each row's own words have just changed, and its height with them: the lines are drawn again on the rows as they now stand, so no arrowhead lands on a word */
    if (S.tab === 'whole' && !zoomValue() && !S.part) measureOver();
    const m = moment();
    if (!m) {
      const lit = {};
      story().touched.forEach((b) => { lit[b] = 1; });
      lit.trade = 1;
      paintWhole(ended() ? {} : lit, null, ended() ? [] : storyHops());
      pointer();
      S.busy = false;
      return;
    }
    const lit = litOf(m);
    if (play && m.p.length && !calm()) {
      const seen = {};
      hopByHop(m.p, seen, (b, i) => {
        seen[b] = 1;
        paintWhole(seen, b, [m.p.slice(0, i + 1)]);
        pointer(b);
      }, () => {
        paintWhole(lit, m.b, [m.p]);
        pointer(m.b);
        rest(began);
      });
    } else {
      paintWhole(lit, m.b, [m.p]);
      pointer(m.b);
      rest(began);
    }
  }

  /* zoom: the overview is the tree at a glance. Anything above it is the real tree, at scale */
  const view = $('wv');
  function zoomValue() { return ZOOMS[S.zi]; }
  function setZoomUI() {
    const z = zoomValue();
    const part = S.part;
    $('z-fit').setAttribute('aria-pressed', z || part ? 'false' : 'true');
    $('z-part').setAttribute('aria-pressed', part ? 'true' : 'false');
    $('z-now').textContent = z && !part ? Math.round(z * 100) + '%' : '';
    $('z-out').disabled = !z || part;
    $('z-in').disabled = S.zi >= ZOOMS.length - 1;
    $('engie').hidden = !part;
    $('whole').classList.toggle('part', part);
    $('over').hidden = !!z || part;
    view.hidden = !z || part;
    $('mini').hidden = !z || part;
  }
  function setPart(on) {
    if (S.part === !!on) return;
    if (on) { stopAll(); S.auto = false; S.busy = false; updateBar(); }
    S.part = !!on;
    setZoomUI();
    if (S.part) { pointer(); return; }
    if (S.tab === 'whole' && !zoomValue()) { measureOver(); const m = moment(); setEdges(V.over, m ? [m.p] : storyHops(), 'on'); }
    if (zoomValue()) paintMiniView();
    pointer(S.ptr);
  }
  function setZoom(zi, cx, cy) {
    const prev = zoomValue();
    S.part = false;
    S.zi = clamp(zi, 0, ZOOMS.length - 1);
    const z = zoomValue();
    if (z) { view.hidden = false; }
    let px = cx;
    let py = cy;
    if (prev && z && px === undefined) {
      px = (view.scrollLeft + view.clientWidth / 2) / prev;
      py = (view.scrollTop + view.clientHeight / 2) / prev;
    }
    setZoomUI();
    if (z) {
      const T = D.tree;
      $('wz').style.width = T.W * z + 'px';
      $('wz').style.height = T.H * z + 'px';
      $('ww').style.transform = 'scale(' + z + ')';
      $('ww').style.setProperty('--z', z);
      if (px === undefined) { px = T.W / 2; py = view.clientHeight / 2 / z; }
      view.scrollLeft = px * z - view.clientWidth / 2;
      view.scrollTop = py * z - view.clientHeight / 2;
      paintMiniView();
    } else {
      measureOver();
      const m = moment();
      setEdges(V.over, m ? [m.p] : storyHops(), 'on');
    }
    pointer();
  }
  function gotoBlock(b) {
    const r = V.world.R[b];
    if (!r) return;
    const z = 0.8;
    /* a hidden view measures zero, which would land the block mid-screen, so show it before measuring */
    $('over').hidden = true;
    view.hidden = false;
    const vw = view.clientWidth;
    const vh = view.clientHeight;
    const cx = r.w * z <= vw - 40 ? r.x + r.w / 2 : r.x + (vw / 2 - 20) / z;
    setZoom(ZOOMS.indexOf(z), cx, r.y + (vh / 2 - 24) / z);
  }
  /* the small map */
  const mini = $('mini-s');
  let miniV = null;
  function buildMini() {
    const T = D.tree;
    mini.setAttribute('viewBox', '0 0 ' + T.W + ' ' + T.H);
    let h = '';
    Object.keys(T.b).forEach((b) => {
      const g = T.b[b];
      h += '<rect class="mb ' + hueOf(b) + '" data-b="' + b + '" x="' + g[0] + '" y="' + g[1] + '" width="' + g[2] + '" height="' + g[3] + '" rx="60"/>';
    });
    mini.innerHTML = h + '<rect class="mv" id="mini-v" x="0" y="0" width="1" height="1"/>';
    miniV = $('mini-v');
  }
  function paintMini(lit, now) {
    qa('.mb', mini).forEach((r) => {
      const b = r.getAttribute('data-b');
      r.classList.toggle('on', !!lit[b]);
      r.classList.toggle('now', b === now);
    });
  }
  function paintMiniView() {
    const z = zoomValue();
    if (!z || !miniV) return;
    miniV.setAttribute('x', view.scrollLeft / z);
    miniV.setAttribute('y', view.scrollTop / z);
    miniV.setAttribute('width', view.clientWidth / z);
    miniV.setAttribute('height', view.clientHeight / z);
  }
  /* a small pointer says where the highlight went. The view stays where the viewer left it */
  function pointer(b) {
    const ptr = $('ptr');
    const m = moment();
    const target = b || (m && m.b);
    S.ptr = target || null;
    if (S.tab !== 'whole' || !target || S.part) { ptr.hidden = true; return; }
    const z = zoomValue();
    let dx = 0;
    let dy = 0;
    if (z) {
      const r = V.world.R[target];
      if (!r) { ptr.hidden = true; return; }
      const l = view.scrollLeft / z;
      const t = view.scrollTop / z;
      const w = view.clientWidth / z;
      const h = view.clientHeight / z;
      if (r.x + r.w < l) dx = -1; else if (r.x > l + w) dx = 1;
      if (r.y + r.h < t) dy = -1; else if (r.y > t + h) dy = 1;
    } else {
      const el = V.over.blocks[target];
      const box = $('over');
      if (!el) { ptr.hidden = true; return; }
      const r = el.getBoundingClientRect();
      const o = box.getBoundingClientRect();
      if (r.bottom < o.top) dy = -1; else if (r.top > o.bottom) dy = 1;
    }
    if (!dx && !dy) { ptr.hidden = true; return; }
    const where = [dy < 0 ? 'above' : dy > 0 ? 'below' : '', dx < 0 ? 'to the left' : dx > 0 ? 'to the right' : ''].filter(Boolean).join(', ');
    const arrowCh = (dy < 0 ? '↑' : dy > 0 ? '↓' : '') + (dx < 0 ? '←' : dx > 0 ? '→' : '');
    ptr.textContent = arrowCh + ' ' + BN[target].fn + ' is ' + where;
    ptr.hidden = false;
  }


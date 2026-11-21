  /* ---------- the moment, in fixed places */
  function hueOf(b) { return b && BN[b] ? BN[b].c : 'c3'; }
  function setHue(el, base, b) { el.className = base + ' ' + hueOf(b); }
  function fillNow(ids) {
    const st = story();
    const m = moment();
    let blockName = '';
    let when = '';
    let h = '';
    let big = '';
    let cap = '';
    let y = '';
    if (m) {
      blockName = m.bn + (m.w ? ', ' + (m.wn || m.w) : '');
      when = m.t;
      h = m.n;
      if (m.hero) { big = m.hero[0]; cap = m.hero[1]; }
      y = m.y;
    } else if (ended()) {
      h = 'That was the whole story';
      const last = st.moments[st.moments.length - 1];
      if (last.hero) { big = last.hero[0]; cap = last.hero[1]; }
      y = nextWords();
    } else {
      h = st.id === 'main' ? 'The evening cut, request to payment' : st.one;
      y = S.tab === 'whole' ? (st.own ? (oneStory() ? 'Press Next to step along the tree.' : 'Pick a story, or press Next to step along the tree.') : 'Pick an input, or press Next to step along the tree.') : (st.id === 'main' ? 'Press Next to start.' : 'Press Next to follow it.');
      const last = st.moments[st.moments.length - 1];
      if (S.tab === 'whole' && last.hero) { big = last.hero[0]; cap = last.hero[1]; }
    }
    $(ids.block).textContent = blockName;
    $(ids.when).textContent = when;
    $(ids.h).textContent = h;
    $(ids.big).textContent = big;
    $(ids.cap).textContent = cap;
    if (ids.y) $(ids.y).textContent = y;
    return m;
  }
  /* the card on the right: a layer of the Full record, for the block the moment is on. Every region keeps its place, and only its words change */
  const cardOf = () => { const st = story(); const m = moment(); return m ? m.k : ended() ? st.moments[st.moments.length - 1].k : st.k0; };
  const NONE = '<i class="dash">—</i>';
  function msgHTML(x, word) {
    if (!x || !x.length) return NONE;
    return esc(x[0]) + (x[2] ? '<span class="q2">, and ' + esc(x[2]) + ' more</span>' : '') + (x[1] && x[0].indexOf(x[1]) < 0 ? '<span class="q2"> ' + word + ' ' + esc(x[1]) + '</span>' : '');
  }
  function whoHTML(rows) {
    if (!rows.length) return NONE;
    return rows.map((r) => (r[1] ? '<span class="ak" data-k="' + esc(r[1]) + '">' + esc(r[1]) + '</span>' : '<b>' + esc(r[0]) + '</b>')).join('');
  }
  function flowHTML(k, did) {
    const rows = k.flow || [['Who', whoHTML(k.who)], ['Came in', msgHTML(k.in, 'from')], ['Did', did ? esc(did) : NONE], ['Rule', k.rule ? esc(k.rule) : NONE], ['Went out', msgHTML(k.out, 'to')]];
    /* a field the record doesn't hold is left out */
    return rows.filter((r) => r[1] && r[1] !== NONE).map((r) => '<dt>' + esc(r[0]) + '</dt><dd' + (r[0] === 'Did' ? ' class="say"' : '') + '>' + r[1] + '</dd>').join('');
  }
  function showNow() {
    const st = story();
    const m = moment();
    const k = cardOf();
    const fin = ended();
    const last = st.moments[st.moments.length - 1];
    const b = S.read && BN[S.read] ? S.read : k.cb;
    const big = k.big || [];
    const len = (big[0] || '').length;
    const size = big[0] && !/^[$\d]/.test(big[0]) ? (big[0].indexOf(' ') < 0 && len > 11 ? ' wd tk' : ' wd') : len > 10 ? ' sm' : len > 8 ? ' md' : '';
    let did = m ? k.did : '';
    const about = b ? BN[b].a1 : (st.id === 'main' ? (st.own ? (oneStory() ? 'One recorded day. Press Next to start.' : 'One recorded day. Press Next, or pick its other story.') : 'One recorded day. Press Next, or send an input.') : (st.own ? 'The same recorded day, from the event on. Press Next to follow it.' : 'A separate recorded run of the same day. Press Next to follow it.'));
    if (fin) { did = nextWords(); }
    $('layer').className = 'layer ' + hueOf(k.cb || null) + (k.kind === 'start' ? ' at-start' : '');
    $('c-n').textContent = k.l ? (k.l === 8 ? 'R' : k.l) : '';
    $('now-block').textContent = b ? BN[b].fn : 'Murmur';
    $('c-layer').textContent = k.l ? (D.layers[k.l] === BN[k.cb].fn ? '' : D.layers[k.l]) : st.name;
    $('now-when').textContent = m ? m.t : fin ? last.t : '';
    $('now-h').textContent = m ? m.n : fin ? 'That was the whole story' : (st.id === 'main' ? 'The evening cut, request to payment' : st.one);
    $('c-about').textContent = about;
    $('c-st').innerHTML = (k.l ? D.status[k.l] : []).map((x) => '<span class="st ' + esc(x[0]) + '">' + esc(x[1]) + '</span>').join('');
    $('c-big').className = 'big' + size;
    $('now-big').textContent = big[0] || '';
    $('now-cap').textContent = big[1] || '';
    $('c-flow').innerHTML = flowHTML(k, did);
    const tag = $('now-tag');
    tag.hidden = !(m && m.tag);
    if (m && m.tag) { tag.innerHTML = esc(m.tag[0]) + '<span class="tail">: ' + esc(m.tag[1]) + '</span>'; }
    fillNow({ block: 'w-block', when: 'w-when', h: 'w-h', big: 'w-big', cap: 'w-cap' });
    setHue(document.querySelector('.whead'), 'whead', m && m.b);
  }
  function showSent() {
    const st = story();
    $('sent').textContent = st.one;
    $('sent').title = st.sent.full;
  }
  /* the data cards, in the Full record's labels and values. The one card this moment is about is marked, and the values it set */
  const kvHTML = (rows) => '<dl class="kv">' + rows.map((r) => '<dt>' + esc(r[0]) + '</dt><dd' + (r[2] ? ' class="mk"' : '') + '>' + (r[1] ? esc(r[1]) : NONE) + '</dd>').join('') + '</dl>';
  const tblHTML = (rows) => '<table class="rt"><tbody>' + rows.map((r, i) => '<tr>' + r.map((c, j) => (i && j ? '<td>' : '<th scope="' + (i ? 'row' : 'col') + '">') + (c === null ? '' : c ? esc(c) : NONE) + (i && j ? '</td>' : '</th>')).join('') + '</tr>').join('') + '</tbody></table>';
  function cardHTML(c) {
    let h = '<section class="card' + (c.hot ? ' hot' : '') + '"><h4>' + esc(c.h) + '</h4>';
    if (c.q) h += '<p class="bub">' + esc(c.q) + '</p>';
    if (c.rows && c.rows.length) h += kvHTML(c.rows);
    if (c.six) h += '<ol class="ck">' + c.six.map((x) => '<li data-st="' + esc(x[2]) + '"><i>' + x[0] + '</i><span>' + esc(x[1]) + '</span></li>').join('') + '</ol>';
    if (c.nine) h += '<ol class="lad">' + c.nine.map((x) => '<li class="' + (x[3] ? 'on ' : '') + (x[4] ? 'mdl' : '') + '"><i>' + x[0] + '</i><b>' + esc(x[1]) + '</b><em>' + esc(x[2]) + '</em></li>').join('') + '</ol>';
    if (c.tbl) h += tblHTML(c.tbl);
    if (c.says) h += '<ul class="can">' + c.says.map((x) => '<li><code>' + esc(x[0]) + '</code> ' + esc(x[1]) + '</li>').join('') + '</ul>';
    return h + '</section>';
  }
  function showTrade() {
    const k = cardOf();
    const box = $('trade');
    box.className = 'cards' + (k.cd.length > 4 ? ' two' : '');
    box.style.setProperty('--cols', k.cols);
    box.innerHTML = k.cd.map(cardHTML).join('');
    $('notes').innerHTML = k.kind === 'start' ? '' : '';
  }
  function updateBar() {
    const n = story().moments.length;
    $('pos').textContent = Math.min(S.m + 1, n) + ' of ' + n;
    $('b-back').disabled = S.m < 0;
    $('b-next').disabled = ended();
    $('b-auto').setAttribute('aria-pressed', S.auto ? 'true' : 'false');
    $('b-speed').textContent = S.speed + '×';
    qa('.chip[data-s]').forEach((c) => {
      if (c.closest('.others')) return;
      const on = c.getAttribute('data-s') === S.story;
      c.setAttribute('aria-pressed', on ? 'true' : 'false');
      c.classList.toggle('offer', ended() && !on);
    });
  }

  function renderTerm(hide) {
    const tb = $('tb');
    const m = moment();
    const all = $('t-all');
    const k = cardOf();
    let html;
    let where = '';
    all.style.visibility = m ? 'visible' : 'hidden';
    setHue(tb, 'tb', k.cb || null);
    $('t-name').textContent = k.term[0];
    $('t-what').textContent = k.term[1];
    if (ended()) { html = endHTML(); } else if (!m) { html = briefHTML() + decidesHTML() + legendHTML(); } else if (S.view === 'gap') {
      html = gapHTML(k.gap);
      where = 'What the flow doesn\'t do';
    } else if (S.view === 'block') {
      const r = termRows(m, 'block', S.read);
      html = r.html || '<li class="miss">Nothing at this block in this moment.</li>';
      where = BN[S.read].fn + ', this moment';
    } else if (S.view === 'all') {
      const r = termRows(m, 'all');
      html = r.html;
      where = 'All ' + m.s.length + ' step' + (m.s.length === 1 ? '' : 's') + ' of this moment';
    } else {
      const r = termRows(m, 'key');
      html = r.html;
      where = r.n + ' of ' + m.s.length + ' step' + (m.s.length === 1 ? '' : 's') + ', key lines';
    }
    tb.innerHTML = html;
    tb.scrollTop = 0;
    $('t-where').textContent = where;
    all.textContent = S.view === 'key' ? 'Show all steps' : 'Back to the key lines';
    all.setAttribute('aria-pressed', S.view === 'key' ? 'false' : 'true');
    if (hide) qa('li', tb).forEach((li) => li.classList.add('hide'));
  }
  function reveal(done) {
    const lis = qa('li.hide', $('tb'));
    if (calm()) { lis.forEach((li) => li.classList.remove('hide')); done(); return; }
    const tok = S.token;
    let i = 0;
    const budget = 4200 / S.speed;
    const chars = lis.reduce((a, li) => a + Math.min(li.textContent.length, 200), 0) || 1;
    const step = () => {
      if (tok !== S.token) return;
      if (i >= lis.length) { done(); return; }
      lis[i].classList.remove('hide');
      const w = Math.min(lis[i].textContent.length, 200);
      i++;
      after(clamp(60 + budget * (w / chars), 60, 520), step);
    };
    step();
  }
  function rest(startedAt) {
    S.busy = false;
    if (!S.auto || ended()) return;
    const m = moment();
    const total = (m ? m.ms : 6000) / S.speed;
    const spent = performance.now() - startedAt;
    after(Math.max(1200 / S.speed, total - spent / FG.scale), () => next());
  }
  function pathOf(view, hops) {
    const pts = [];
    const cum = [];
    let len = 0;
    for (let i = 0; i + 1 < hops.length; i++) {
      const seg = view.pts[hops[i] + '>' + hops[i + 1]];
      if (!seg) return null;
      seg.forEach((p, j) => {
        if (pts.length) {
          const q = pts[pts.length - 1];
          const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
          if (!j && d > 1) { len += d; } else if (j) { len += d; }
        }
        pts.push(p);
      });
      cum.push(len);
    }
    return { pts, cum, len };
  }
  function pointAt(path, d) {
    let run = 0;
    for (let i = 1; i < path.pts.length; i++) {
      const a = path.pts[i - 1];
      const b = path.pts[i];
      const s = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (run + s >= d && s > 0) { const t = (d - run) / s; return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }
      run += s;
    }
    return path.pts[path.pts.length - 1];
  }
  const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const mapShown = () => getComputedStyle($('map')).display !== 'none';

  function hopByHop(hops, lit, cb, done) {
    const tok = S.token;
    let i = 0;
    const walk = () => {
      if (tok !== S.token) return;
      if (i >= hops.length) { done(); return; }
      cb(hops[i], i);
      i++;
      after(420, walk);
    };
    walk();
  }

  function travel(m, done) {
    const hops = m.p;
    if (!hops.length || calm()) { done(); return; }
    if (!mapShown()) {
      const lit = {};
      hopByHop(hops, lit, (b) => { lit[b] = 1; paintStrip(lit, b); }, done);
      return;
    }
    const view = V.split;
    const path = pathOf(view, hops);
    if (!path || !path.len) { done(); return; }
    const pill = $('pill');
    pill.textContent = m.c || 'message';
    pill.hidden = false;
    const pw = pill.offsetWidth;
    const ph = pill.offsetHeight;
    const box = view.host.getBoundingClientRect();
    const dur = clamp(1900 + path.len * 1.5, 2000, 3000) * FG.scale;
    const t0 = performance.now();
    const tok = S.token;
    const lit = {};
    lit[hops[0]] = 1;
    paintBlocks(view, lit, null);
    let reached = 0;
    const tick = (now) => {
      if (tok !== S.token) return;
      const t = Math.min(1, (now - t0) / dur);
      const d = ease(t) * path.len;
      const p = pointAt(path, d);
      pill.style.transform = 'translate(' + clamp(p[0] - pw / 2, 4, box.width - pw - 4).toFixed(1) + 'px,' + clamp(p[1] - ph / 2, 4, box.height - ph - 4).toFixed(1) + 'px)';
      while (reached < path.cum.length && d >= path.cum[reached] - 0.5) {
        lit[hops[reached + 1]] = 1;
        edgeEls(view, hops[reached], hops[reached + 1]).forEach((el) => el.classList.add('on'));
        paintBlocks(view, lit, null);
        reached++;
      }
      if (t < 1) raf = requestAnimationFrame(tick);
      else { pill.hidden = true; done(); }
    };
    raf = requestAnimationFrame(tick);
  }

  function settleMap() {
    const m = moment();
    const lit = litOf(m);
    paintBlocks(V.split, lit, m ? m.b : null);
    setEdges(V.split, m ? [m.p] : [], 'on');
    paintStrip(lit, m ? m.b : null);
    if (S.read) V.split.blocks[S.read] && V.split.blocks[S.read].classList.add('read');
  }
  function clearRead() { qa('.blk.read').forEach((b) => b.classList.remove('read')); qa('.stg.read').forEach((b) => b.classList.remove('read')); }

  function playSplit(play) {
    const m = moment();
    const began = performance.now();
    clearRead();
    if (!play || !m) {
      settleMap();
      renderTerm(false);
      rest(began);
      return;
    }
    setEdges(V.split, [], 'on');
    paintBlocks(V.split, {}, null);
    paintStrip({}, null);
    renderTerm(true);
    travel(m, () => {
      settleMap();
      reveal(() => rest(began));
    });
  }


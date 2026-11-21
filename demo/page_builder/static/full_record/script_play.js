  // ---- moving
  function stepMs(st) { return Math.max(350, BASE_MS * ((st && st.d) || 1) / SPEEDS[S.speed]); }
  function setPos(i, o) {
    o = o || {};
    const seq = S.seq, N = seq.steps.length;
    i = Math.max(-1, Math.min(N - 1, i));
    const from = S.pos;
    const forwardOne = i === from + 1;
    sweepEnd();
    markLines(seq, from, i);
    S.pos = i;
    if (forwardOne) {
      const st = seq.steps[i];
      if (st) {
        const nx = { x: Object.assign({}, S.cur.x, st.x || {}), w: Object.assign({}, S.cur.w, st.w || {}), k: Object.assign({}, S.cur.k, st.k || {}), g: st.g || S.cur.g };
        applyState(nx, !!o.animate);
      }
    } else {
      applyState(stateOf(seq, i), false);
    }
    const st = seq.steps[i] || null;
    hotSet(st, seq.steps[i + 1] || null);
    const rows = seq.lines[i] || [];
    const seenBox = new Set();
    for (const n of rows) {
      const b = n.closest('.tb, .chat');
      if (b && !seenBox.has(b)) { seenBox.add(b); scrollInside(n, !!o.animate); }
    }
    if (st && st.e && o.animate) sendEnvelope(st.e);
    countLines();
    paintBar(st);
    const ms = stepMs(st);
    sweep(st, rows, !!o.animate, ms);
    drawPath(st, !!o.animate, ms * 0.72);
    if (st) follow(st, o.animate ? ms * 0.6 : 0);
  }
  function paintBar(st) {
    const seq = S.seq, N = seq.steps.length;
    $('saying').innerHTML = st ? st.y : (seq === MAIN ? D.start : seq.intro);
    const s = $('scrub');
    s.max = N - 1;
    s.value = Math.max(0, S.pos);
    s.style.setProperty('--p', N > 1 ? (Math.max(0, S.pos) / (N - 1) * 100).toFixed(2) : 0);
    const lay = st && st.L ? LAYER_NAMES[st.L[0]] : '';
    const after = seq.steps[S.pos + 1];
    const nextLay = after && after.L && (!st || after.L[0] !== st.L[0]) ? '  ·  next: ' + LAYER_NAMES[after.L[0]] : '';
    $('meta').textContent = (lay ? lay + '  ·  ' : '') + (st ? st.t + '  ·  ' : '') + 'step ' + (S.pos + 1) + ' of ' + N + nextLay;
    const clock = $('tr-clock');
    if (clock.dataset.day === undefined) clock.dataset.day = clock.textContent;
    clock.textContent = st ? st.t : clock.dataset.day;
    const cg = $('chgnow');
    if (st && st.v) { cg.textContent = st.v[0] + ': ' + st.v[1]; cg.hidden = false; } else cg.hidden = true;
    const on = st ? st.s : -1;
    document.querySelectorAll('.mk').forEach((m, k) => { m.classList.toggle('on', k === on); m.classList.toggle('done', k < on); });
    $('b-play').textContent = S.playing ? 'Pause' : (S.pos >= N - 1 ? (seq === MAIN ? 'Replay' : 'Finish') : 'Play');
    $('b-play').classList.toggle('nudge', S.pos < 0 && !S.playing);
    $('b-play').setAttribute('aria-label', S.playing ? 'Pause' : 'Play');
    if (S.branch) {
      $('brnpos').textContent = (S.pos + 1) + ' of ' + N;
      const seen = new Set();
      for (let i = 0; i <= S.pos; i++) if (seq.steps[i].q !== undefined) seen.add(seq.steps[i].q);
      const now = st ? st.q : undefined;
      document.querySelectorAll('#brq li').forEach((li, k) => { li.classList.toggle('done', seen.has(k)); li.classList.toggle('on', k === now); });
    }
  }
  function stop() { S.playing = false; clearTimeout(S.timer); paintBar(S.seq.steps[S.pos] || null); $('saying').setAttribute('aria-live', 'polite'); }
  function tick() {
    if (!S.playing) return;
    const seq = S.seq;
    if (S.pos >= seq.steps.length - 1) {
      if (S.branch) { S.timer = setTimeout(() => leaveBranch(true), 1800 / SPEEDS[S.speed]); return; }
      stop(); return;
    }
    setPos(S.pos + 1, { animate: true });
    S.timer = setTimeout(tick, stepMs(seq.steps[S.pos]));
  }
  function play() {
    if (S.seq === MAIN && S.pos >= S.seq.steps.length - 1) setPos(-1);
    if (S.branch && S.pos >= S.seq.steps.length - 1) { leaveBranch(true); return; }
    S.playing = true;
    $('saying').setAttribute('aria-live', 'off');
    document.querySelectorAll('.tb, .chat').forEach((b) => { delete b.dataset.held; });
    if (!S.follow) setFollow(true);
    paintBar(S.seq.steps[S.pos] || null);
    tick();
  }
  function toggle() { if (S.playing) stop(); else play(); }
  function step(n) { stop(); setPos(S.pos + n, { animate: n > 0 }); }
  function stageBy(n) {
    stop();
    const seq = S.seq, st = seq.stages;
    if (!st || !st.length) { setPos(n > 0 ? seq.steps.length - 1 : -1); return; }
    const cur = S.pos < 0 ? -1 : seq.steps[S.pos].s;
    if (n > 0) { const k = cur + 1; setPos(k < st.length ? st[k].at : seq.steps.length - 1); }
    else {
      const here = S.pos >= 0 && S.pos > st[cur].at;
      const k = here ? cur : cur - 1;
      setPos(k >= 0 ? st[k].at : -1);
    }
  }
  function speed(k) {
    S.speed = Math.max(0, Math.min(SPEEDS.length - 1, k));
    $('b-speed').textContent = SPEEDS[S.speed] + '×';
    store.set('fg-speed', String(S.speed));
  }

  // ---- special events: the playback branches, then comes back
  function buildBranchDom(ev) {
    ev.lines = [];
    ev.blocks = {};
    ev.extra = [];
    const blockFor = (term) => {
      if (ev.blocks[term]) return ev.blocks[term];
      const t = $('T-' + term);
      if (!t) return null;
      const b = document.createElement('li');
      b.className = 'brl';
      const h = document.createElement('span'); h.className = 'bh'; h.textContent = ev.name + (ev.own ? ', followed from the event on' : ', a separate recorded run');
      const ol = document.createElement('ol');
      b.append(h, ol);
      const body = t.querySelector('.tb');
      const past = body.querySelectorAll(':scope > .ln.past, :scope > .ln.cur');
      const after = past[past.length - 1];
      if (after) after.after(b); else body.prepend(b);
      ev.blocks[term] = ol;
      return ol;
    };
    ev.steps.forEach((st, i) => {
      (st.l || []).forEach((row) => {
        const ol = blockFor(row[0]);
        if (!ol) return;
        const li = document.createElement('li');
        li.className = 'ln fut ' + (row[1] || '');
        li.innerHTML = row[2];
        ol.append(li);
        (ev.lines[i] = ev.lines[i] || []).push(li);
      });
      (st.b || []).forEach((row) => {
        const chat = $('chat-' + row[0]);
        if (!chat) return;
        const t = document.createElement('template');
        t.innerHTML = row[1];
        const n = t.content.firstElementChild;
        chat.append(n);
        ev.extra.push(n);
        (ev.lines[i] = ev.lines[i] || []).push(n);
      });
    });
  }
  function dropBranchDom(ev) {
    Object.values(ev.blocks || {}).forEach((ol) => ol.parentElement.remove());
    (ev.extra || []).forEach((n) => n.remove());
    ev.blocks = {}; ev.lines = []; ev.extra = [];
  }
  function showEffect(h) { const e = $('effect'); e.innerHTML = h; e.hidden = false; initial.x.effect = h; }
  function enterBranch(key) {
    const ev = D.events[key];
    if (!ev || ev.missing) return;
    if (S.branch) leaveBranch(false);
    const was = S.playing;
    stop();
    ev.id = key;
    S.seq = MAIN;
    setPos(ev.after);
    S.branch = { key, ev, back: ev.after, was };
    buildBranchDom(ev);
    S.seq = ev;
    S.pos = -1;
    applyState(stateOf(ev, -1), false);
    document.body.classList.add('branching');
    $('brn').hidden = false;
    fitPhone();
    $('brnname').textContent = ev.name;
    $('marks').hidden = true; $('ticks').hidden = true;
    clearTimeout(S.fx);
    showEffect('<b>' + ev.name + '</b><span>' + ev.intro + '</span><span>' + ev.note + '</span>');
    document.querySelectorAll('.ev').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.ev === key)));
    if (!S.follow) setFollow(true);
    paintBar(null);
    S.playing = true;
    $('saying').setAttribute('aria-live', 'off');
    S.timer = setTimeout(tick, 900 / SPEEDS[S.speed]);
  }
  function leaveBranch(resume) {
    const b = S.branch;
    if (!b) return;
    clearTimeout(S.timer);
    S.playing = false;
    dropBranchDom(b.ev);
    S.branch = null;
    S.seq = MAIN;
    S.pos = b.back - 1;
    document.body.classList.remove('branching');
    $('brn').hidden = true;
    $('marks').hidden = false; $('ticks').hidden = false;
    fitPhone();
    document.querySelectorAll('.ev').forEach((x) => x.setAttribute('aria-pressed', 'false'));
    applyState(stateOf(MAIN, S.pos), false);
    setPos(b.back);
    if (b.ev.effect) { $('effect').hidden = false; showEffect(b.ev.effect); S.fx = setTimeout(() => { $('effect').hidden = true; }, 16000); }
    if (resume && b.was) play();
  }

  // ---- marks on the scrubber
  function buildMarks() {
    const box2 = $('marks'), ticks = $('ticks');
    box2.replaceChildren(); ticks.replaceChildren();
    const N = D.steps.length;
    D.stages.forEach((s) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'mk'; b.textContent = s.n;
      b.title = 'Go to ' + s.n;
      b.addEventListener('click', () => { stop(); setPos(s.at); });
      box2.append(b);
      const t = document.createElement('i');
      t.style.left = (s.at / Math.max(1, N - 1) * 100).toFixed(2) + '%';
      ticks.append(t);
    });
  }

  // ---- controls
  $('b-play').addEventListener('click', toggle);
  $('b-back').addEventListener('click', () => step(-1));
  $('b-fwd').addEventListener('click', () => step(1));
  $('b-pstage').addEventListener('click', () => stageBy(-1));
  $('b-nstage').addEventListener('click', () => stageBy(1));
  $('b-speed').addEventListener('click', () => speed((S.speed + 1) % SPEEDS.length));
  $('b-follow').addEventListener('click', () => setFollow(!S.follow));
  $('b-keys').addEventListener('click', () => { const k = $('keys'); k.hidden = !k.hidden; $('b-keys').setAttribute('aria-expanded', String(!k.hidden)); });
  $('b-leave').addEventListener('click', () => leaveBranch(false));
  $('b-trade').addEventListener('click', () => {
    const t = $('trade'); t.hidden = !t.hidden;
    $('b-trade').setAttribute('aria-pressed', String(!t.hidden));
  });
  $('b-events').addEventListener('click', () => { setFollow(false); glide(0, 300); });
  $('scrub').addEventListener('input', (e) => { stop(); setPos(+e.target.value); });
  document.querySelectorAll('.ev').forEach((b) => b.addEventListener('click', () => { enterBranch(b.dataset.ev); b.blur(); }));
  document.querySelectorAll('.nav a').forEach((a) => a.addEventListener('click', () => { setFollow(false); }));
  $('b-theme').addEventListener('click', () => {
    const order = ['system', 'light', 'dark'];
    const now = root.dataset.theme || 'system';
    const next = order[(order.indexOf(now) + 1) % 3];
    if (next === 'system') delete root.dataset.theme; else root.dataset.theme = next;
    $('b-theme').textContent = 'Theme: ' + next;
    store.set('fg-theme', next);
    if (S.pos >= 0) drawPath(S.seq.steps[S.pos], false, 0);
  });
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target, tag = t && t.tagName;
    if (tag === 'TEXTAREA' || (tag === 'INPUT' && t.type !== 'range')) return;
    const k = e.key;
    if (k === ' ') { e.preventDefault(); if (!e.repeat) toggle(); return; }
    if (k === 'ArrowRight') { e.preventDefault(); step(1); return; }
    if (k === 'Enter' && !(t && t.closest && t.closest('button, a, input'))) { step(1); return; }
    if (k === 'ArrowLeft') { e.preventDefault(); step(-1); return; }
    if (k === ']') { stageBy(1); return; }
    if (k === '[') { stageBy(-1); return; }
    if (k === '=' || k === '+') { speed(S.speed + 1); return; }
    if (k === '-') { speed(S.speed - 1); return; }
    if (k === 'f' || k === 'F') { setFollow(!S.follow); return; }
    if (k === 'Escape') { if (S.branch) leaveBranch(false); $('keys').hidden = true; return; }
    if (k === '?') { const n = $('keys'); n.hidden = !n.hidden; return; }
    if (k >= '1' && k <= '8') {
      const l = document.querySelector('.layer[data-l="' + k + '"]');
      if (l) { setFollow(false); glide(window.scrollY + l.getBoundingClientRect().top - 10, 420); }
      return;
    }
    if (k === 'ArrowUp' || k === 'ArrowDown' || k === 'PageUp' || k === 'PageDown' || k === 'Home' || k === 'End') userMoved();
  });

  function fitPhone() {
    const t = $('trade');
    if (narrow.matches) { t.hidden = $('b-trade').getAttribute('aria-pressed') !== 'true'; } else { t.hidden = false; }
    const bh = $('bar').offsetHeight;
    if (bh) root.style.setProperty('--bar-h', bh + 'px');
  }
  function relayout() {
    fitPhone();
    sizeWire();
    if (S.pos >= 0) drawPath(S.seq.steps[S.pos], false, 0);
  }
  window.addEventListener('resize', relayout);
  if (narrow.addEventListener) narrow.addEventListener('change', relayout);
  if (window.ResizeObserver) {
    new ResizeObserver(() => sizeWire()).observe(sheet);
    new ResizeObserver(() => { const bh = $('bar').offsetHeight; if (bh) root.style.setProperty('--bar-h', bh + 'px'); }).observe($('bar'));
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);

  // ---- at rest the trade shows the day's end in grey, like the lines still to come
  function seedTrade() {
    const f = stateOf(MAIN, D.steps.length - 1);
    for (const id in f.x) {
      const n = el(id);
      if (n && n.closest('.trade')) { initial.x[id] = f.x[id]; n.innerHTML = f.x[id]; n.classList.add('todo'); seeded.add(id); }
    }
  }

  // ---- start
  const th = store.get('fg-theme');
  if (th === 'light' || th === 'dark') { root.dataset.theme = th; $('b-theme').textContent = 'Theme: ' + th; }
  const sp = store.get('fg-speed');
  speed(sp !== null && Number.isFinite(+sp) ? Math.round(+sp) : 1);
  seedTrade();
  buildMarks();
  relayout();
  paintBar(null);
  countLines();
  window.FG = { S, setPos, play, stop, toggle, enterBranch, leaveBranch, D, stageBy };
})();

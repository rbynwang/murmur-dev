
  /* ---- the timeline in the bottom bar: the evening's five parts with the window highlighted, where the clock stands, the quiet
     stretches it leapt, a pin for each named stop and each surprise, and a tick for every quarter-hour that holds a moment. A tick
     shows its first moment. A pin the clock has not reached is, on a console, a button that runs the clock to it. */
  const SHARE = { dayahead: 14, request: 18, before: 14, window: 36, settle: 18 };
  const LABELS = { dayahead: ['Day-ahead sale', 'Day-ahead'], request: ['Morning request', 'Request'], before: ['Pre-delivery', 'Before'],
    window: ['', 'Peak'], settle: ['Settlement', 'Settle'] };
  const PIN_WORDS = { sale: 'The day-ahead sale', request: "The aggregator's request", before: 'An hour before the window', delivery: 'The evening peak begins',
    end: 'The evening peak ends', readings: 'Readings and settlement' };
  let TL = null;
  function tlBuild() {
    TL = el('div', 'lv-tl');
    TL.id = 'lv-tl';
    TL.setAttribute('role', 'group');
    TL.setAttribute('aria-label', 'The evening, from the day-ahead sale to the settlement');
    TL.appendChild(el('div', 'lv-track'));
    $('bar').appendChild(TL);
  }
  /* how far along the track a quarter-hour is, in percent: linear inside its part */
  function along(t, q) {
    let left = 0;
    for (let i = 0; i < t.parts.length; i++) {
      const p = t.parts[i], w = SHARE[p.id] || 10;
      if (q < p.to || i === t.parts.length - 1) return left + w * Math.max(0, Math.min(1, (q - p.from) / (p.to - p.from)));
      left += w;
    }
    return left;
  }
  function nowTq(v) {
    const st = L.story, m = FG.moment();
    return st && m && FG.S.m < st.moments.length - 1 ? m.tq : v.clock.tq;
  }
  let drawn = '';
  /* the timeline is drawn again only when what it shows has changed, so a tick or a pin stays put under the pointer */
  function tlPaint() {
    const v = L.v2;
    if (!TL || !v) return;
    const t = v.timeline, track = TL.firstChild, m = FG.moment();
    const now = along(t, nowTq(v));
    const key = JSON.stringify([t.t0, t.n, t.parts, t.pins, v.clock.leaps.length, L.story ? L.story.moments.length : 0, m ? m.tq : -1, !!(L.console && L.console.ok)]);
    if (key === drawn) { const n = track.querySelector('.lv-now'); if (n) n.style.left = now + '%'; return; }
    drawn = key;
    track.textContent = '';
    let left = 0;
    t.parts.forEach((p) => {
      const w = SHARE[p.id] || 10, d = el('div', 'lv-part');
      d.dataset.p = p.id;
      d.style.left = left + '%';
      d.style.width = w + '%';
      const words = p.id === 'window' ? hhmm(t.t0, p.from) + ' to ' + hhmm(t.t0, p.to) + ' evening peak' : LABELS[p.id][0];
      const lab = el('span', 'lv-lab', words);
      lab.dataset.short = LABELS[p.id][1];
      lab.dataset.long = words;
      d.appendChild(lab);
      track.appendChild(d);
      left += w;
    });
    v.clock.leaps.forEach((x) => {
      const f = el('i', 'lv-fold'), a = along(t, x.from), b = along(t, x.to);
      f.style.left = a + '%';
      f.style.width = Math.max(0.4, b - a) + '%';
      f.title = 'Leapt ' + (x.to - x.from) + ' quiet quarter-hours in ' + x.ms + ' ms';
      track.appendChild(f);
    });
    const st = L.story, first = {};
    if (st) st.moments.forEach((m, i) => { if (!has(first, m.tq)) first[m.tq] = i; });
    Object.keys(first).forEach((q) => {
      const i = first[q], b = btn('lv-tick', '', stamp(t.t0, +q) + ': ' + st.moments[i].n);
      b.style.left = along(t, +q) + '%';
      b.classList.toggle('on', !!FG.moment() && FG.moment().tq === +q);
      b.addEventListener('click', () => FG.grow.show(i));
      track.appendChild(b);
    });
    t.pins.forEach((p) => {
      const word = p.kind === 'stop' ? PIN_WORDS[p.id] : 'Surprise: ' + (WORDS[p.id] || p.id);
      const run = p.jump && L.console && L.console.ok;
      const b = btn('lv-pin', '', stamp(t.t0, p.tq) + ': ' + word + (run ? '. Press to run the clock to it' : ''));
      b.dataset.k = p.kind;
      b.dataset.s = p.state;
      b.style.left = along(t, p.tq) + '%';
      if (run) b.addEventListener('click', () => L.send({ do: 'run_to', ts: tsOf(t.t0, p.tq) })); else b.tabIndex = -1;
      track.appendChild(b);
    });
    const mark = el('i', 'lv-now');
    mark.style.left = now + '%';
    track.appendChild(mark);
    fitLabels();
  }
  /* each part's label as long as it fits, else its short word, else none */
  function fitLabels() {
    TL.querySelectorAll('.lv-lab').forEach((lab) => {
      lab.textContent = lab.dataset.long;
      lab.hidden = false;
      if (lab.scrollWidth > lab.clientWidth) lab.textContent = lab.dataset.short;
      if (lab.scrollWidth > lab.clientWidth) lab.hidden = true;
    });
  }

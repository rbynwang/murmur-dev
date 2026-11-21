  const V = { split: domView($('map'), $('map').querySelector('.wires'), false), over: domView($('over'), $('over').querySelector('.wires'), true) };
  /* the tree of open blocks belongs to the scenario being played */
  function worldView() {
    const w = { host: $('ww'), svg: $('w-wires'), extra: true, arrow: 15, R: {}, G: D.tree.geo, blocks: {}, pts: {}, els: {} };
    qa('.wb[data-b]', $('ww')).forEach((el) => { w.blocks[el.getAttribute('data-b')] = el; });
    Object.keys(D.tree.b).forEach((b) => { const g = D.tree.b[b]; w.R[b] = { x: g[0], y: g[1], w: g[2], h: g[3] }; });
    return w;
  }
  V.world = worldView();
  const stageBtns = qa('.stg');

  function paintBlocks(view, lit, now) {
    const st = story();
    const touched = {};
    st.touched.forEach((b) => { touched[b] = 1; });
    touched.input = touched.trade = touched.status = 1;
    view.host.classList.toggle('live', !!moment());
    Object.keys(view.blocks).forEach((b) => {
      const c = view.blocks[b].classList;
      c.toggle('off', !touched[b]);
      c.toggle('on', !!lit[b]);
      c.toggle('now', b === now);
    });
  }
  function paintStrip(lit, now) {
    const st = story();
    D.strip.forEach((row, i) => {
      const c = stageBtns[i].classList;
      c.toggle('in', row[1].some((b) => st.touched.indexOf(b) >= 0));
      c.toggle('on', row[1].some((b) => lit[b]));
      c.toggle('now', row[1].indexOf(now) >= 0);
    });
  }
  const litOf = (m) => { const o = {}; if (m) { m.lit.forEach((b) => { o[b] = 1; }); if (Object.keys(m.tv).length) o.trade = 1; } return o; };
  const storyHops = () => story().moments.map((m) => m.p);

  /* ---------- lines */
  const liHTML = (l, opt) => {
    const cls = 'ln k-' + l[0] + (l[1] ? ' ' + l[1] : '') + (l[4] === 2 ? ' star' : '') + (opt.mark && (l[4] === 1 || l[4] === 3) ? ' key' : '');
    const html = opt.clip && l[5] ? l[5] : l[2];
    return '<li class="' + cls + '"' + (opt.m !== undefined ? ' data-m="' + opt.m + '"' : '') + '><i class="g">' + (GLYPH[l[0]] || '·') + '</i><span class="m">' + html + '</span></li>';
  };
  const ttlHTML = (s, m) => '<li class="ttl"' + (m !== undefined ? ' data-m="' + m + '"' : '') + '><time>' + esc(s.t) + '</time>' + (s.w ? '<span class="' + (s.sd === 'b' ? 'b' : 'h') + '">' + esc(s.wn || s.w) + '</span>' : '') + '<span>' + esc(s.n) + '</span></li>';

  /* the split view's terminal reads like the Full record's: a time down the left of each step, then its lines */
  const stepHTML = (s) => '<li class="ln tt"><time>' + esc(s.t) + '</time><i class="g">›</i><span class="m">' + (s.w ? '<span class="' + (s.sd === 'b' ? 'b' : 'h') + '">' + esc(s.wn || s.w) + '</span> ' : '') + '<span class="w">' + esc(s.n) + '</span></span></li>';
  const lineHTML = (l, clip) => {
    const html = clip && l[5] ? l[5] : l[2];
    return '<li class="ln k-' + l[0] + (l[1] ? ' ' + l[1] : '') + (l[4] === 2 ? ' star' : '') + '"><time></time><i class="g">' + (GLYPH[l[0]] || '·') + '</i><span class="m">' + html + '</span></li>';
  };
  function termRows(m, mode, block) {
    const st = story();
    const rows = [];
    let n = 0;
    m.s.forEach((si) => {
      const s = st.steps[si];
      const ls = mode === 'key' ? s.l.filter((l) => l[4] === 1 || l[4] === 2) : mode === 'block' ? s.l.filter((l) => hasBlock(l, BI.indexOf(block))) : s.l;
      /* an event opens on what was put into its run, in plain words */
      if (mode === 'key' && si === 0 && st.sent.who === 'Input') rows.push(stepHTML(s) + '<li class="ln k-note"><time></time><i class="g">·</i><span class="m">' + esc(st.sent.full) + '</span></li>');
      if (!ls.length && mode !== 'all') return;
      n++;
      rows.push(stepHTML(s));
      ls.forEach((l) => rows.push(lineHTML(l, mode === 'key')));
    });
    return { html: rows.join(''), n };
  }
  /* who decides what, before the first moment: the words are in who_decides.py, the same for all three views */
  function briefHTML() {
    const b = cardOf().brief;
    return b ? '<li class="pad brief"><h3>' + esc(b.t) + '</h3><dl>' + b.r.map((r) => '<dt class="' + esc(r[0]) + '">' + esc(r[1]) + '</dt><dd>' + esc(r[2]) + '</dd>').join('') + '</dl></li>' : '';
  }
  function decidesHTML() {
    const w = D.who;
    return '<li class="pad decides"><h3>' + esc(w.t) + '</h3><p>' + esc(w.s) + '</p><dl>' + w.r.map((r) => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') + '</dl></li>';
  }
  /* the one table of names: the record's own ids stay in the data files, and the page shows each home and building by a plain name */
  function namesHTML() {
    const n = D.names;
    if (!n || !(n.homes.length + n.buildings.length)) return '';
    const row = (lab, list) => (list.length ? '<dt>' + lab + '</dt><dd>' + esc(list.join(', ')) + '</dd>' : '');
    return '<li class="pad names"><h3>Names stand for the record\'s own ids</h3><dl>' + row('Homes', n.homes) + row('Buildings', n.buildings) + '</dl></li>';
  }
  function legendHTML() {
    const k = [['←', 'message in'], ['→', 'message out'], ['◆', 'model'], ['=', 'worked out'], ['#', 'signature or seal'], ['▸', 'tool call'], ['■', 'guard'], ['⇒', 'device write']];
    return '<li class="pad"><h3>The terminal is the evidence</h3>Each moment shows the real record of that moment. The line that matters is marked.<div class="legend">' + k.map((x) => '<span><i>' + x[0] + '</i>' + x[1] + '</span>').join('') + '</div></li>' + namesHTML();
  }
  /* what comes after a story. A day run over the message network holds its own event, the same run followed from the event on, and a day with no event has only its one story */
  const oneStory = () => D.order.length < 2;
  function nextWords() {
    if (!story().own) return 'Send another input to see the same day go differently.';
    if (oneStory()) return SC.list.length > 1 ? 'That was the whole day. Pick another day at the top.' : 'That was the whole day.';
    return 'The same recorded day, told the other way.';
  }
  function endHTML() {
    const others = D.order.filter((k) => k !== S.story).map((k) => '<button type="button" class="chip" data-s="' + k + '" title="' + esc(D.stories[k].one) + '">' + esc(D.stories[k].name) + '</button>').join('');
    if (story().own) return '<li class="pad"><h3>' + (oneStory() ? 'That was this day' : 'Its other story') + '</h3>' + nextWords() + (others ? '<div class="others">' + others + '</div>' : '') + '</li>';
    return '<li class="pad"><h3>Send another input</h3>Every story runs on the same day and the same map.<div class="others">' + others + '</div></li>';
  }
  function gapHTML(g) {
    return '<li class="pad gapbox"><h3>' + esc(g.t) + '</h3><p><b>You might expect:</b> ' + esc(g.e) + '</p><p><b>What happens:</b> ' + esc(g.a) + '</p></li>';
  }



  /* ---- "Try it on your phone": a card with a QR code of this page's own address (the one a viewer has in the address bar, never
     the live address behind it), three links and two lines of what is live now. The code is made here, in this file: nothing is
     fetched for it and no address stands in this file. On a console "How the network works" is the console's own /how; on a
     copy of the page published elsewhere it is the architecture page beside this one. Byte mode, error correction M, versions 1 to 6 (an address of up to 106 bytes); a longer address gets
     the card without a code. */
  const QR_SIZES = [null, [16, 10, 1], [28, 16, 1], [44, 26, 1], [32, 18, 2], [43, 24, 2], [27, 16, 4]];      /* by version: data words and check words of a block, blocks */
  const QR_ALIGN = [0, 0, 18, 22, 26, 30, 34];                                                               /* by version: the centre of its one alignment mark */
  const QR_MASKS = [(r, c) => (r + c) % 2 === 0, (r) => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0,
    (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
    (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0];
  /* the code words of a text: its bytes with their header, padded, cut into blocks, each block's check words after them, interleaved */
  function qrWords(bytes, v) {
    const dc = QR_SIZES[v][0], ec = QR_SIZES[v][1], nb = QR_SIZES[v][2], total = dc * nb, bits = [];
    const push = (x, n) => { for (let i = n - 1; i >= 0; i--) bits.push((x >> i) & 1); };
    push(4, 4);
    push(bytes.length, 8);
    bytes.forEach((b) => push(b, 8));
    push(0, Math.min(4, total * 8 - bits.length));
    while (bits.length % 8) bits.push(0);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => a * 2 + b, 0));
    for (let pad = 0xEC; data.length < total; pad ^= 0xEC ^ 0x11) data.push(pad);
    const exp = [], log = [];
    for (let i = 0, x = 1; i < 255; i++) { exp[i] = x; log[x] = i; x <<= 1; if (x & 256) x ^= 0x11D; }
    const mul = (a, b) => (a && b ? exp[(log[a] + log[b]) % 255] : 0);
    let gen = [1];
    for (let i = 0; i < ec; i++) {
      const next = new Array(gen.length + 1).fill(0);
      gen.forEach((g, j) => { next[j] ^= g; next[j + 1] ^= mul(g, exp[i]); });
      gen = next;
    }
    const check = (block) => {
      const r = block.concat(new Array(ec).fill(0));
      for (let i = 0; i < block.length; i++) { const f = r[i]; if (f) for (let j = 1; j < gen.length; j++) r[i + j] ^= mul(gen[j], f); }
      return r.slice(block.length);
    };
    const blocks = [], checks = [], words = [];
    for (let b = 0; b < nb; b++) { blocks.push(data.slice(b * dc, (b + 1) * dc)); checks.push(check(blocks[b])); }
    for (let i = 0; i < dc; i++) blocks.forEach((b) => words.push(b[i]));
    for (let i = 0; i < ec; i++) checks.forEach((c) => words.push(c[i]));
    return words;
  }
  function qrPenalty(m) {
    const n = m.length, lines = [];
    let p = 0, dark = 0;
    for (let i = 0; i < n; i++) { lines.push(m[i].join('')); lines.push(m.map((row) => row[i]).join('')); }
    lines.forEach((s) => {
      (s.match(/0{5,}|1{5,}/g) || []).forEach((run) => { p += run.length - 2; });
      for (let i = 0; i + 11 <= n; i++) { const w = s.slice(i, i + 11); if (w === '10111010000' || w === '00001011101') p += 40; }
    });
    for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) { const a = m[r][c]; if (a === m[r][c + 1] && a === m[r + 1][c] && a === m[r + 1][c + 1]) p += 3; }
    m.forEach((row) => row.forEach((x) => { dark += x; }));
    return p + 10 * Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n));
  }
  /* the modules of a text's code, rows of 0 and 1, or null when the text is longer than version 6 holds */
  function qrMatrix(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let v = 1;
    while (v <= 6 && bytes.length > QR_SIZES[v][0] * QR_SIZES[v][2] - 2) v++;
    if (v > 6) return null;
    const words = qrWords(bytes, v), n = 17 + 4 * v, M = [], fixed = [];
    for (let i = 0; i < n; i++) { M.push(new Array(n).fill(0)); fixed.push(new Array(n).fill(false)); }
    const set = (r, c, on) => { M[r][c] = on ? 1 : 0; fixed[r][c] = true; };
    [[0, 0], [0, n - 7], [n - 7, 0]].forEach((at) => {                                   /* the three finders, each with its light edge */
      for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) {
        const y = at[0] + r, x = at[1] + c, ring = Math.max(Math.abs(r - 3), Math.abs(c - 3));
        if (y >= 0 && x >= 0 && y < n && x < n) set(y, x, ring !== 2 && ring !== 4);
      }
    });
    for (let i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    if (v > 1) for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) set(QR_ALIGN[v] + r, QR_ALIGN[v] + c, Math.max(Math.abs(r), Math.abs(c)) !== 1);
    const format = (m, bits) => {                                                        /* fifteen bits, twice: beside the first finder, and split over the other two */
      const put = (r, c, i) => { m[r][c] = i < 0 ? 1 : (bits >> i) & 1; fixed[r][c] = true; };
      for (let i = 0; i <= 5; i++) put(i, 8, i);
      put(7, 8, 6);
      put(8, 8, 7);
      put(8, 7, 8);
      for (let i = 9; i < 15; i++) put(8, 14 - i, i);
      for (let i = 0; i < 8; i++) put(8, n - 1 - i, i);
      for (let i = 8; i < 15; i++) put(n - 15 + i, 8, i);
      put(n - 8, 8, -1);                                                                 /* the one module that is always dark */
    };
    format(M, 0);                                                                        /* their places are kept free of the words */
    let k = 0, up = true;
    for (let c = n - 1; c > 0; c -= 2) {                                                 /* the words, in pairs of columns from the right, up and down */
      if (c === 6) c = 5;
      for (let i = 0; i < n; i++) {
        const r = up ? n - 1 - i : i;
        for (let d = 0; d < 2; d++) {
          if (fixed[r][c - d]) continue;
          const w = words[k >> 3];
          M[r][c - d] = w === undefined ? 0 : (w >> (7 - (k & 7))) & 1;
          k++;
        }
      }
      up = !up;
    }
    let best = null, least = Infinity;
    QR_MASKS.forEach((mask, id) => {                                                     /* of the eight masks, the one that reads best */
      const m = M.map((row, r) => row.map((x, c) => (fixed[r][c] ? x : x ^ (mask(r, c) ? 1 : 0))));
      let rem = id;
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537);
      format(m, ((id << 10) | rem) ^ 0x5412);
      const p = qrPenalty(m);
      if (p < least) { least = p; best = m; }
    });
    return best;
  }
  const SVG_NS = 'http://www.w3.org/2000/svg', QR_INK = '#1B2A38', QR_PAPER = '#FFFFFF', QR_QUIET = 4;
  function qrSvg(text) {
    const m = qrMatrix(text);
    if (!m) return null;
    const n = m.length + 2 * QR_QUIET, svg = document.createElementNS(SVG_NS, 'svg'), paper = document.createElementNS(SVG_NS, 'rect'), ink = document.createElementNS(SVG_NS, 'path');
    svg.setAttribute('viewBox', '0 0 ' + n + ' ' + n);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'QR code of ' + text);
    svg.setAttribute('shape-rendering', 'crispEdges');
    paper.setAttribute('width', n);
    paper.setAttribute('height', n);
    paper.setAttribute('fill', QR_PAPER);
    const d = [];
    m.forEach((row, r) => row.forEach((x, c) => { if (x) d.push('M' + (c + QR_QUIET) + ' ' + (r + QR_QUIET) + 'h1v1h-1z'); }));
    ink.setAttribute('d', d.join(''));
    ink.setAttribute('fill', QR_INK);
    svg.appendChild(paper);
    svg.appendChild(ink);
    return svg;
  }

  const QC = { lines: [] }, HOW_PAGE = 'Murmur_NG_Architecture_and_Data.html';
  /* a link whose live address the page does not use has no card, and no button for one */
  function cardBuild() {
    B.qr.hidden = !base;
    if (!base) return;
    const home = web ? location.origin + location.pathname : base.origin + '/';
    const how = onConsole ? base.origin + '/how' : new URL(HOW_PAGE, location.href).href;
    const veil = el('div', 'lv-veil');
    veil.id = 'lv-card';
    veil.hidden = true;
    const card = el('div', 'lv-card');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.setAttribute('aria-labelledby', 'lv-card-h');
    const h = el('h2', '', 'Try it on your phone');
    h.id = 'lv-card-h';
    const close = btn('lv-x', '×', 'Close');
    const main = el('div', 'lv-card-main'), code = el('div', 'lv-qr'), side = el('div', 'lv-card-side'), links = el('ul', 'lv-links');
    const svg = qrSvg(home);
    if (svg) code.appendChild(svg); else code.hidden = true;
    [['Open the live demo', home, null], ['Data view', home + '#data', 'data'], ['How the network works', how, null]].forEach((x) => {
      const li = el('li'), a = el('a', '', x[0]);
      a.href = x[1];
      if (x[2] === 'data') a.addEventListener('click', (e) => { if (web && FG.dataView) { e.preventDefault(); cardToggle(false); setLive(false); FG.dataView.set(true); } });
      else if (x[1] === home) a.addEventListener('click', (e) => { if (web) { e.preventDefault(); cardToggle(false); } });
      else { a.target = '_blank'; a.rel = 'noopener'; }
      li.appendChild(a);
      links.appendChild(li);
    });
    side.appendChild(links);
    side.appendChild(el('p', 'lv-addr', home));
    main.appendChild(code);
    main.appendChild(side);
    const now = el('ul', 'lv-facts');
    QC.lines = [el('li'), el('li')];
    QC.lines.forEach((li) => now.appendChild(li));
    [close, h, main, el('h3', '', 'Live now'), now].forEach((x) => card.appendChild(x));
    veil.appendChild(card);
    $('app').appendChild(veil);
    QC.veil = veil;
    QC.close = close;
    close.addEventListener('click', () => cardToggle(false));
    veil.addEventListener('click', (e) => { if (e.target === veil) cardToggle(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !veil.hidden) cardToggle(false); });
    window.addEventListener('hashchange', () => { if (location.hash === '#qr') cardToggle(true); });
  }
  function cardToggle(on) {
    if (!QC.veil) return;
    const open = on === undefined ? QC.veil.hidden : on;
    QC.veil.hidden = !open;
    B.qr.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (location.hash === '#qr' && !open) history.replaceState(null, '', location.pathname + location.search);
    if (open) { cardPaint(); QC.close.focus(); } else B.qr.focus();
  }
  /* the two lines under "Live now", from the last answer: who answers and how often the page asks; what this evening has played */
  function cardPaint() {
    if (!QC.veil || QC.veil.hidden) return;
    const a = L.last && L.last.v1, v = L.v2, e = (a && a.event) || {};
    const parts = a && !a.withheld ? PART_KEYS.filter((k) => k !== 'homes' && k !== 'buildings' && a.parts[k] && a.parts[k].up).length : 0;
    const who = [[a && a.homes, 'home'], [a && a.buildings, 'building'], [parts, 'service']].filter((x) => x[0]).map((x) => x[0] + ' ' + x[1] + (x[0] === 1 ? '' : 's'));
    const every = v ? (v.every / 1000).toFixed(v.every % 1000 ? 1 : 0) + ' s' : '';
    QC.lines[0].textContent = who.length && L.kind === 'ok' ? who.join(', ') + ' answering now' + (every ? ', asked again every ' + every : '') : 'No answer from the network right now';
    const played = L.story ? L.story.moments.length : 0, day = v && v.loop ? dayWords(v.loop) : '';
    const sale = [e.asked != null ? fig(e.asked, ' kW asked') : '', e.offered != null ? fig(e.offered, ' kW offered') : ''].filter(Boolean).join(', ');
    QC.lines[1].textContent = [played + (played === 1 ? ' moment' : ' moments') + ' played this evening', sale, day].filter(Boolean).join(' · ');
  }

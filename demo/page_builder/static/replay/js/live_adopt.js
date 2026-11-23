
  /* ---- adopting what the feed sends as the split view's own steps and moments. Nothing becomes markup but the pieces of a line,
     each escaped, in a span only of a listed class. A box must be one of this page's; a path must run along the map's own lines.
     A step that fails becomes an empty step, so the indexes hold; a moment that fails is dropped. */
  const LINE_KINDS = ['in', 'out', 'think', 'calc', 'sign', 'tool', 'guard', 'write', 'note'];
  const LINE_CLS = ['', 'no', 'tbl'], PIECE_CLS = ['', 'n', 'd', 'w', 'q', 'h', 'b'];
  const CARD_KINDS = ['aggpart', 'buyers', 'market', 'node', 'model', 'chain', 'device', 'people', 'ret', 'desk'];
  const COLS = /^(repeat\([1-8],minmax\(0,1fr\)\)|\d(\.\d{1,2})?fr( \d(\.\d{1,2})?fr){0,7})$/;
  let IDX = null, EDGE = null;
  function maps() {
    if (IDX) return;
    IDX = {};
    FG.D.blocks.forEach((b, i) => { IDX[b.id] = i; });
    EDGE = {};
    (FG.D.edges || []).forEach((e) => { EDGE[e[0] + '>' + e[1]] = 1; EDGE[e[1] + '>' + e[0]] = 1; });
  }
  const known = (b) => typeof b === 'string' && has(IDX, b);
  const fail = () => { throw new Error('form'); };
  const txt = (x, n) => { const s = str(x, n); return s === null ? fail() : s; };
  function pieces(ps) {
    if (!arr(ps, 24)) fail();
    return ps.map((p) => {
      if (!Array.isArray(p) || PIECE_CLS.indexOf(p[0]) < 0 || typeof p[1] !== 'string') fail();
      const t = esc(p[1].slice(0, 600));
      return p[0] ? '<span class="' + p[0] + '">' + t + '</span>' : t;
    }).join('');
  }
  function line(l) {
    if (!Array.isArray(l) || LINE_KINDS.indexOf(l[0]) < 0 || LINE_CLS.indexOf(l[1]) < 0 || whole(l[4], 0, 3) === null) fail();
    const b = (arr(l[3], 64) || []).filter(known).map((x) => IDX[x]);
    const row = [l[0], l[1], pieces(l[2]), b.length === 1 ? b[0] : b, l[4]];
    if (l.length > 5 && l[5] != null) row.push(pieces(l[5]));
    return row;
  }
  function step(s, t0) {
    try {
      if (!obj(s)) fail();
      const ls = arr(s.l, 40) || fail();
      return { t: hhmm(t0, whole(s.tq, 0, 400)), n: txt(s.n, 90), w: str(s.w, 60) || '', wn: str(s.w, 60) || '', sd: s.sd === 'b' ? 'b' : 'h',
        b: (arr(s.b, 64) || []).filter(known).map((x) => IDX[x]), l: ls.map(line) };
    } catch (e) {
      return { t: '', n: '', w: '', wn: '', sd: 'h', b: [], l: [] };
    }
  }
  const pair = (x, n) => (x == null || (Array.isArray(x) && !x.length) ? null : arr(x, 2) && x.length === 2 ? [txt(x[0], n), txt(x[1], n)] : fail());
  function rows(rs, n) {
    return (arr(rs, n) || fail()).map((r) => {
      if (!Array.isArray(r) || r.length < 2 || r.length > 3) fail();
      return [txt(r[0], 60), r[1] == null ? '' : txt(r[1], 60), r[2] ? 1 : 0];
    });
  }
  function card(c) {
    if (!obj(c)) fail();
    const out = { h: txt(c.h, 90), hot: c.hot === true };
    if (c.q != null) out.q = txt(c.q, 220);
    if (c.rows != null) out.rows = rows(c.rows, 8);
    if (c.six != null) out.six = (arr(c.six, 8) || fail()).map((x) => [whole(x[0], 0, 99) ?? fail(), txt(x[1], 60), txt(x[2] || '', 10)]);
    if (c.nine != null) out.nine = (arr(c.nine, 12) || fail()).map((x) => [whole(x[0], 0, 99) ?? fail(), txt(x[1], 60), txt(x[2] || '', 60), x[3] ? 1 : 0, x[4] ? 1 : 0]);
    if (c.tbl != null) out.tbl = (arr(c.tbl, 6) || fail()).map((r) => (arr(r, 9) || fail()).map((x) => (x === null ? null : txt(String(x), 60))));
    if (c.says != null) out.says = (arr(c.says, 6) || fail()).map((x) => [txt(x[0], 60), txt(x[1], 120)]);
    return out;
  }
  function cardOfMoment(k) {
    if (!obj(k) || CARD_KINDS.indexOf(k.kind) < 0) fail();
    const l = whole(k.l, 0, 8);
    if (l === null || (l > 0 && !has(FG.D.layers, String(l)) && !FG.D.layers[l])) fail();
    const cb = k.cb === '' ? '' : known(k.cb) ? k.cb : fail();
    if (l > 0 && !cb) fail();
    const cols = typeof k.cols === 'string' && COLS.test(k.cols) ? k.cols : fail();
    const who = (arr(k.who, 4) || fail()).map((r) => (Array.isArray(r) ? [txt(r[0], 60), r[1] == null ? '' : txt(r[1], 40)] : fail()));
    const three = (x) => (x == null || (Array.isArray(x) && !x.length) ? [] : arr(x, 3) && x.length === 3 ? [txt(x[0], 220), txt(x[1] || '', 60), x[2] ? txt(String(x[2]), 20) : ''] : fail());
    return { kind: k.kind, cb, l, who, in: three(k.in), out: three(k.out), did: str(k.did, 400) || '', rule: str(k.rule, 220) || '', cd: (arr(k.cd, 8) || fail()).map(card),
      cols, term: pair(k.term, 90) || fail(), big: pair(k.big, 90) || [] };
  }
  function path(p) {
    const hops = arr(p, 9) || [];
    if (!hops.every(known)) return [];
    for (let i = 1; i < hops.length; i++) if (!EDGE[hops[i - 1] + '>' + hops[i]]) return [];
    return hops.slice();
  }
  /* a moment of the feed as the split view's own, or null; `count` is how many steps the story holds once this answer's are in */
  function moment(m, count, t0) {
    try {
      if (!obj(m)) fail();
      const s = arr(m.s, 24) || fail();
      if (!s.length || !s.every((i, j) => whole(i, 0, count - 1) !== null && (j === 0 || i > s[j - 1]))) fail();
      const b = known(m.b) ? m.b : fail();
      const k = cardOfMoment(m.k);
      const tq = whole(m.tq, 0, 400) ?? fail();
      return { id: txt(m.id, 40), n: txt(m.n, 90), b, bn: FG.D.blocks[IDX[b]].fn, w: str(m.w, 60) || '', wn: str(m.w, 60) || '', t: stamp(t0, tq), tq, y: '',
        hero: pair(m.hero, 120), nt: '', tag: pair(m.tag, 60), gap: null, p: path(m.p), c: str(m.c, 40) || '', lit: (arr(m.lit, 40) || []).filter(known),
        s: s.slice(), tr: [], tv: m.tv === 1 ? { x: 1 } : {}, ms: 8000, k, q: whole(m.q, 1, 1e6) };
    } catch (e) {
      return null;
    }
  }

(function () {
  'use strict';
  const D = JSON.parse(document.getElementById('fg-data').textContent);
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const sheet = $('sheet'), wire = $('wire');
  const NS = 'http://www.w3.org/2000/svg';
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = window.matchMedia('(max-width: 980px)');
  const SPEEDS = [0.5, 1, 2, 4];
  const BASE_MS = 1500;
  const LAYER_NAMES = D.layers;
  const TAPS = {1: 'c1', 2: 'c2', 3: 'c3', 4: 'c4h', 5: 'c5', 6: 'c6', 7: 'c7', 8: 'cr'};
  const HUE = {1: '--c1', 2: '--c2', 3: '--c3', 4: '--c4h', b: '--c4b', 5: '--c5', 6: '--c6', 7: '--c7', 8: '--cr', m: '--model', r: '--fail'};

  const store = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* the page works without it */ } }
  };

  // ---- the lines: every terminal line and ledger row is already in the page, marked with its step
  const MAIN = { id: 'main', steps: D.steps, stages: D.stages, lines: [] };
  document.querySelectorAll('[data-s]').forEach((n) => {
    const s = +n.dataset.s;
    (MAIN.lines[s] = MAIN.lines[s] || []).push(n);
  });
  const counters = {};
  document.querySelectorAll('.term').forEach((t) => {
    const at = Array.from(t.querySelectorAll('.ln[data-s]'), (n) => +n.dataset.s);
    counters[t.id] = { at, el: t.querySelector('figcaption em') };
  });

  const S = { seq: MAIN, pos: -1, playing: false, speed: 1, follow: true, branch: null, timer: 0, anim: 0, cam: 0, swp: 0, fx: 0, programmatic: 0, lastHot: [], lastNext: [], cur: { x: {}, w: {}, k: {}, g: null } };

  // ---- element state: text, numbers and flags that steps set, replayed so any position can be reached
  const initial = { x: {}, w: {}, k: {} };
  const seeded = new Set();
  const elCache = {};
  const el = (id) => elCache[id] || (elCache[id] = $(id));
  function stateOf(seq, pos) {
    const out = { x: {}, w: {}, k: {}, g: null };
    const merge = (st) => {
      if (st.x) Object.assign(out.x, st.x);
      if (st.w) Object.assign(out.w, st.w);
      if (st.k) Object.assign(out.k, st.k);
      if (st.g) out.g = st.g;
    };
    if (seq !== MAIN) {
      const m = D.steps;
      for (let i = 0; i <= seq.after; i++) merge(m[i]);
      if (seq.base) merge(seq.base);
    }
    for (let i = 0; i <= pos; i++) merge(seq.steps[i]);
    return out;
  }
  function setX(id, v, flash) {
    const n = el(id);
    if (!n) return;
    if (!(id in initial.x)) initial.x[id] = n.innerHTML;
    n.classList.remove('todo');
    if (n.innerHTML !== v) {
      n.innerHTML = v;
      if (flash && n.closest('.trade')) { n.classList.remove('flash'); void n.offsetWidth; n.classList.add('flash'); }
    }
  }
  function resetX(id) {
    const n = el(id);
    if (!n) return;
    if (id in initial.x) n.innerHTML = initial.x[id];
    if (seeded.has(id)) n.classList.add('todo');
  }
  function setW(id, v) {
    const n = el(id);
    if (n) n.style.setProperty('--v', v);
  }
  function setK(id, v) {
    const n = el(id);
    if (!n) return;
    if (!(id in initial.k)) initial.k[id] = n.dataset.st || '';
    n.dataset.st = v;
  }
  const cells = Array.from(document.querySelectorAll('.cell'));
  function setGrid(g) {
    if (g === S.cur.g) return;
    for (let i = 0; i < cells.length; i++) {
      const v = g ? g[i] : '0';
      if (cells[i].dataset.st !== v) cells[i].dataset.st = v;
    }
    S.cur.g = g;
  }
  function applyState(next, flash) {
    const c = S.cur;
    for (const id in c.x) if (!(id in next.x)) resetX(id);
    for (const id in next.x) if (c.x[id] !== next.x[id]) setX(id, next.x[id], flash);
    for (const id in c.w) if (!(id in next.w)) setW(id, 0);
    for (const id in next.w) if (c.w[id] !== next.w[id]) setW(id, next.w[id]);
    for (const id in c.k) if (!(id in next.k)) setK(id, initial.k[id] || '');
    for (const id in next.k) if (c.k[id] !== next.k[id]) setK(id, next.k[id]);
    setGrid(next.g);
    S.cur = { x: next.x, w: next.w, k: next.k, g: next.g };
  }

  // ---- lines: past, current, to come
  function markLines(seq, from, to) {
    const L = seq.lines;
    const lo = Math.min(from, to), hi = Math.max(from, to);
    for (let s = Math.max(0, lo); s <= hi; s++) {
      const rows = L[s];
      if (!rows) continue;
      const c = s > to ? 'fut' : s === to ? 'cur' : 'past';
      for (const n of rows) { n.classList.remove('fut', 'cur', 'past'); n.classList.add(c); }
    }
  }
  function countLines() {
    const top = S.seq === MAIN ? S.pos : S.seq.after;
    for (const id in counters) {
      const c = counters[id], a = c.at;
      let lo = 0, hi = a.length;
      while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= top) lo = m + 1; else hi = m; }
      if (c.el) c.el.textContent = lo + ' of ' + a.length;
    }
  }
  function scrollInside(n, smooth) {
    const box = n.closest('.tb, .chat');
    if (!box || box.dataset.held === '1') return;
    const top = n.offsetTop - box.clientHeight * 0.2;
    box.scrollTo({ top: Math.max(0, top), behavior: smooth && !calm.matches ? 'smooth' : 'auto' });
  }
  function sendEnvelope(text) {
    const e = $('env');
    if (!e) return;
    e.textContent = text;
    e.classList.remove('go');
    void e.offsetWidth;
    e.classList.add('go');
  }

  // ---- highlights
  function hotClear() {
    for (const n of S.lastHot) n.classList.remove('hot');
    for (const n of S.lastNext) n.classList.remove('nxt');
    S.lastHot = []; S.lastNext = [];
  }
  function hotSet(st, nx) {
    hotClear();
    const ids = new Set(st ? st.h || [] : []);
    if (st && st.p) st.p.forEach((c) => ids.add(c[c.length - 1]));
    ids.forEach((id) => { const n = el(id); if (n) { n.classList.add('hot'); S.lastHot.push(n); } });
    if (nx) {
      const first = (nx.h && nx.h[0]) || (nx.p && nx.p[0] && nx.p[0][nx.p[0].length - 1]);
      const n = first && el(first);
      if (n && !ids.has(first)) { n.classList.add('nxt'); S.lastNext.push(n); }
    }
    const on = new Set(st ? st.L || [] : []);
    document.querySelectorAll('.layer').forEach((l) => l.classList.toggle('on', on.has(+l.dataset.l)));
    document.querySelectorAll('.nav a').forEach((a) => a.classList.toggle('on', on.has(+a.dataset.l)));
    document.querySelectorAll('#busg .tap').forEach((c) => c.classList.toggle('on', on.has(+c.dataset.l)));
  }


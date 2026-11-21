
/* ---- optional live mode. It runs only when the page's own address carries ?live=<base address>.
   Without that, the first lines below stop and the page is the recorded replay.
   The base address is never written here: it comes from the link, and the page asks <base address>/live/state.json.
   Whatever comes back is treated as untrusted: every field is checked and shown as plain text, never as markup. */
(function () {
  'use strict';
  var given = null;
  try { given = new URLSearchParams(window.location.search).get('live'); } catch (e) { given = null; }
  if (!given) return;

  var SCHEMA = 'murmur.live.v1', STATE_PATH = '/live/state.json', MAX_CHARS = 65536;
  var base = null, url = null, refused = '';
  try { base = new URL(given); } catch (e) { base = null; }
  if (!base || (base.protocol !== 'http:' && base.protocol !== 'https:')) { refused = 'The live address in this link is not a web address.'; base = null; }
  else if (base.username || base.password) { refused = 'The live address in this link carries a sign-in, so the page does not use it.'; base = null; }
  else { url = base.origin + base.pathname.replace(/\/+$/, '') + STATE_PATH; }

  var CSS = [
    ':root{--lu:#0B7285;--lo:#8A6100;--ld:#B5472A}',
    '@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--lu:#56C8DC;--lo:#E5BE5A;--ld:#F2A07B}}',
    ':root[data-theme="dark"]{--lu:#56C8DC;--lo:#E5BE5A;--ld:#F2A07B}',
    '#lv{display:none}',
    '#app.lv .panel > :not(#lv),#app.lv #pill{display:none!important}',
    '#app.lv .panel{display:flex;flex-direction:column}',
    '#app.lv #lv{display:flex;flex-direction:column;gap:10px;flex:1 1 auto;min-height:0;min-width:0;overflow:auto;overscroll-behavior:contain}',
    '#app.lv .bar .ctl{visibility:hidden}',
    '#app.lv .wires{opacity:.3}',
    '#app.lv .map .blk{cursor:default}',
    '#app.lv .map .blk.on,#app.lv .map .blk.now{background:var(--sheet);border-color:var(--hair);box-shadow:none}',
    '#app.lv .map .blk::before{opacity:0}',
    /* a part outside the live network is dimmed with lvdim, not lvd: lvd is the page's own class for the line "People and devices", and a box
       that took it would take that line's spacing and rule and push its words past its edge. The line itself is dimmed too (span.lvd). */
    '#app.lv .map .lvdim,#app.lv .map .lvn,#app.lv .map span.lvd{opacity:.28;filter:grayscale(1)}',
    '#app.lv .map .lvg{opacity:.3}',
    '#app.lv .map .blk.lvu{border-color:var(--lu);background:color-mix(in srgb,var(--lu) 12%,var(--sheet))}',
    '#app.lv .map .blk.lvo{border-color:var(--lo);background:color-mix(in srgb,var(--lo) 12%,var(--sheet))}',
    '#app.lv .map .blk.lvx{border-color:var(--ld);background:color-mix(in srgb,var(--ld) 10%,var(--sheet))}',
    '.lq{display:none}',
    '#app.lv .lq{display:block;position:absolute;right:6px;top:6px;width:9px;height:9px;border-radius:50%;background:var(--rule);z-index:2;pointer-events:none}',
    /* the dot stands in the box's top right corner, so the first line of a box that has one ends before it: a name or its tag is never under the dot */
    '#app.lv .map .blk:has(> .lq) > .bh{padding-right:11px}',
    '#app.lv .lvu > .lq{background:var(--lu)}',
    '#app.lv .lvo > .lq{background:var(--lo)}',
    '#app.lv .lvx > .lq{background:var(--ld)}',
    '#app.lv .lg > .lq{position:static;display:inline-block;margin-left:7px;vertical-align:middle}',
    '.lvh{display:flex;flex-direction:column;gap:6px;padding:0 0 9px;border-bottom:1px solid var(--rule)}',
    '.lvt{display:flex;align-items:center;gap:12px;flex-wrap:wrap}',
    '.lvt h2{font:600 24px/1.1 var(--disp);margin:0}',
    '.lvs{font:500 11.5px/1 var(--mono);letter-spacing:.04em;padding:5px 9px;border-radius:999px;border:1px solid var(--rule);color:var(--muted)}',
    '.lvs.u{border-color:var(--lu);color:var(--lu)}',
    '.lvs.x{border-color:var(--ld);color:var(--ld)}',
    '.lvn2{font-size:13.5px;line-height:1.42;color:var(--muted);margin:0}',
    '.lvv{font:600 14px/1.35 var(--body);margin:0}',
    '.lvr{background:var(--sheet);border:1px solid var(--hair);border-left:4px solid var(--ink);border-radius:0 6px 6px 0;padding:9px 12px 10px;display:flex;flex-direction:column;gap:4px}',
    '.lvk{font:500 10.5px/1 var(--mono);letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}',
    '.lvr b{font:600 21px/1.12 var(--disp)}',
    '.lvr p{font-size:13.5px;line-height:1.4;margin:0;color:var(--muted)}',
    '.lvq{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 16px;margin:4px 0 0}',
    '.lvq div{min-width:0}',
    '.lvq dt{font:500 10.5px/1.2 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}',
    '.lvq dd{margin:2px 0 0;font:600 16px/1.2 var(--disp)}',
    '.lvc{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}',
    '.lc{position:relative;background:var(--sheet);border:1px solid var(--hair);border-radius:6px;padding:8px 10px 9px 28px;display:flex;flex-direction:column;gap:2px;min-width:0}',
    '.lc i{position:absolute;left:10px;top:11px;width:10px;height:10px;border-radius:50%;background:var(--rule)}',
    '.lc.u i{background:var(--lu)}',
    '.lc.o i{background:var(--lo)}',
    '.lc.x i{background:var(--ld)}',
    '.lc .ln{font:500 10.5px/1.25 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}',
    '.lc b{font:600 17px/1.15 var(--disp)}',
    '.lc .lx{font-size:12.5px;line-height:1.35;color:var(--muted)}',
    '.lvf{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:12.5px;line-height:1.4;color:var(--muted);border-top:1px solid var(--hair);padding-top:8px}',
    '@media (max-width:1180px){.lvc{grid-template-columns:repeat(2,minmax(0,1fr))}}'
  ].join('\n');

  /* what the live network's parts are called on this page, and which boxes of the diagram stand for them */
  var PARTS = [
    { key: 'aggregator', name: 'Request agent', boxes: ['mkt'], sub: 'the aggregator\u2019s: sends each request, signed' },
    { key: 'town', name: 'NANDA Town', boxes: ['town'], sub: 'the channel every message crosses' },
    { key: 'community', name: 'Community agent', legend: 'Community agent', inner: ['co-fc', 'co-cover', 'co-agent', 'co-market', 'co-desk', 'co-report'], sub: '' },
    { key: 'homes', name: 'Home agents', boxes: ['h-agent'], inner: ['h-tools', 'h-guard', 'h-seal', 'h-driver', 'h-dev', 'h-person'], sub: '' },
    { key: 'buildings', name: 'Building agents', boxes: ['b-agent'], inner: ['b-tools', 'b-guard', 'b-seal', 'b-driver', 'b-dev', 'b-person'], sub: '' },
    { key: 'datacenter', name: 'Data center', boxes: ['site-dc'], frame: true, sub: 'a single site with its own agent' },
    { key: 'buyer_utility', name: 'Buyer: utility', boxes: ['buy-u'], sub: 'a stand-in buyer' },
    { key: 'buyer_grid', name: 'Buyer: grid operator', boxes: ['buy-g'], sub: 'a stand-in buyer' },
    { key: 'model', name: 'Small model', boxes: ['h-model', 'b-model'], sub: 'reads what people write' }
  ];
  var PHASE = { offers: 'Collecting offers', cleared: 'Cleared', confirming: 'Confirming the contracts', settling: 'Settling on the meters', settled: 'Settled',
    no_offers: 'No offers came in', failed: 'Not completed', other: 'In progress' };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  /* ---- reading what came back: only these fields, only these kinds of value */
  function whole(x, hi) { return typeof x === 'number' && isFinite(x) && x >= 0 && x <= (hi || 1e7) ? Math.floor(x) : null; }
  function number(x, hi) { return typeof x === 'number' && isFinite(x) && x >= 0 && x <= (hi || 1e9) ? x : null; }
  function clock(x) { return typeof x === 'string' && /^\d{4}-\d\d-\d\d \d\d:\d\d$/.test(x) ? x : null; }
  function obj(x) { return x && typeof x === 'object' && !Array.isArray(x) ? x : null; }
  function read(j) {
    if (!obj(j) || j.schema !== SCHEMA) return null;
    if (j.withheld === true) return { withheld: true, every: 5, parts: {}, event: null, clock: null };
    var p = obj(j.parts) || {}, parts = {}, e = obj(j.event), ev = null;
    PARTS.forEach(function (d) {
      var r = obj(p[d.key]);
      parts[d.key] = r ? { up: r.up === true, seen: whole(r.seen_s, 1e9), current: r.current === true ? true : r.current === false ? false : null, ready: r.ready === true,
        nodes: whole(r.nodes), count: whole(r.count), contracts: whole(r.contracts), waiting: whole(r.waiting) } : null;
    });
    if (e) {
      var w = Array.isArray(e.window) && e.window.length === 2 ? [clock(e.window[0]), clock(e.window[1])] : [null, null];
      ev = { phase: Object.prototype.hasOwnProperty.call(PHASE, e.phase) ? e.phase : 'other', from: w[0], to: w[1], asked: number(e.asked_kw), halfHours: whole(e.half_hours, 96),
        offers: whole(e.offers), accepted: whole(e.accepted), declined: whole(e.declined), offered: number(e.offered_kw), readings: whole(e.readings), expected: whole(e.readings_expected),
        buyers: whole(e.buyers, 50), paid: whole(e.paid_nodes), income: number(e.income_usd), askedAll: e.asked_all === true };
    }
    return { withheld: false, every: Math.min(60, Math.max(3, whole(j.every_s, 3600) || 5)), parts: parts, event: ev, clock: clock(j.clock) };
  }

  /* ---- words */
  function fig(n, places) { return n.toLocaleString('en-US', { maximumFractionDigits: places == null ? 1 : places, minimumFractionDigits: places === 2 ? 2 : 0 }); }
  function count(n, one, many) { return fig(n, 0) + ' ' + (n === 1 ? one : many); }
  function ago(s) { return s < 2 ? 'just now' : s < 90 ? Math.round(s) + ' s ago' : Math.round(s / 60) + ' min ago'; }
  /* Between the contracts and the settlement the network's own word for its stage stays the same. The clock and the window say where the evening is. */
  function stage(e, now) {
    if (e.phase === 'confirming' && now && e.from && e.to && e.offers != null && e.accepted != null && e.accepted + (e.declined || 0) >= e.offers) {
      return now < e.from ? 'Contracts signed, delivery to come' : now < e.to ? 'Delivering' : 'Delivered, readings coming in';
    }
    return PHASE[e.phase];
  }
  function day(c) { var m = /^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)$/.exec(c); return m ? { d: (+m[3]) + ' ' + MONTHS[(+m[2]) - 1] + ' ' + m[1], t: m[4] + ':' + m[5] } : null; }
  function stateOf(r) { return !r ? 'none' : !r.up ? 'down' : r.current === false ? 'old' : 'up'; }
  function partWords(d, r) {
    if (!r) return ['Not set up', 'no source is set for it'];
    if (!r.up) return ['No answer', r.seen != null ? 'last answer ' + ago(r.seen) : 'not reached yet'];
    var main = 'Answering', sub = d.sub;
    if (d.key === 'community') { main = r.nodes != null ? count(r.nodes, 'node on its roster', 'nodes on its roster') : main; sub = r.ready ? 'ready for a request' : 'starting up'; }
    else if (d.key === 'homes') { main = r.count != null ? count(r.count, 'home', 'homes') : main; sub = r.ready ? 'reporting' : 'starting up'; }
    else if (d.key === 'buildings') { main = r.count != null ? count(r.count, 'building', 'buildings') : main; sub = r.ready ? 'reporting' : 'starting up'; }
    else if (d.key === 'model') { main = r.waiting != null ? count(r.waiting, 'request waiting', 'requests waiting') : main; }
    else if (d.key === 'buyer_utility' || d.key === 'buyer_grid') { main = r.contracts != null ? count(r.contracts, 'contract', 'contracts') : main; }
    if (r.current === false) sub = (sub ? sub + ' \u00b7 ' : '') + 'old code';
    return [main, sub];
  }
  function codeWords(st) {
    var tot = 0, cur = 0;
    PARTS.forEach(function (d) { var r = st.parts[d.key]; if (r && r.up && r.current !== null) { tot += 1; if (r.current) cur += 1; } });
    if (!tot) return 'Code: no part that answers says which code it runs.';
    if (cur === tot) return 'Code: all ' + tot + ' parts that report it run the current code.';
    return 'Code: ' + cur + ' of ' + tot + ' parts that report it run the current code. The others run old code.';
  }

  (function wait() {
    if (!(window.FG && window.FG.ready)) { setTimeout(wait, 40); return; }
    var FG = window.FG, app = document.getElementById('app'), map = document.getElementById('map'), panel = document.getElementById('panel'), truth = document.getElementById('truth');
    var tabs = document.querySelector('#bar .tabs'), ts = document.getElementById('tab-split'), td = document.getElementById('tab-data');
    if (!app || !map || !panel || !tabs || !ts) return;
    function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

    var style = el('style'); style.id = 'lv-css'; style.textContent = CSS; document.head.appendChild(style);

    /* the diagram: a dot on each part the live network can have; everything else goes grey while the live view is on */
    var marks = {}, frames = {}, inner = {}, lit = [], kept = [];
    PARTS.forEach(function (d) {
      var nodes = [];
      (d.boxes || []).forEach(function (id) { var b = map.querySelector('.blk[data-b="' + id + '"]'); if (b) nodes.push(b); });
      if (d.legend) [].forEach.call(map.querySelectorAll('.lg'), function (g) { if (g.textContent.replace(/\s+/g, ' ').trim() === d.legend) nodes.push(g); });
      nodes.forEach(function (n) { var q = el('i', 'lq'); q.setAttribute('aria-hidden', 'true'); n.appendChild(q); lit.push(n); });
      marks[d.key] = nodes; frames[d.key] = d.frame && nodes[0] ? nodes[0].closest('.part.psite') : null;
      inner[d.key] = (d.inner || []).map(function (id) { return map.querySelector('.blk[data-b="' + id + '"]'); }).filter(Boolean); kept = kept.concat(inner[d.key]);
    });
    [].forEach.call(map.querySelectorAll('.blk[data-b]'), function (b) { if (lit.indexOf(b) < 0 && kept.indexOf(b) < 0 && !b.closest('.part.psite')) b.classList.add('lvdim'); });
    [].forEach.call(map.querySelectorAll('.part.psite'), function (f) { f.classList.add('lvg'); });
    /* the diagram's two counts are the replay's; in the live view they show the live network's, and go back afterwards */
    var forkH = map.querySelector('.forks .c4h'), forkB = map.querySelector('.forks .c4b'), forkWas = [forkH ? forkH.textContent : '', forkB ? forkB.textContent : ''];
    function forks(st) {
      var h = st ? st.parts.homes : null, b = st ? st.parts.buildings : null;
      if (forkH) forkH.textContent = !on ? forkWas[0] : h && h.up && h.count != null ? count(h.count, 'home agent', 'home agents') : 'home agents';
      if (forkB) forkB.textContent = !on ? forkWas[1] : b && b.up && b.count != null ? count(b.count, 'building agent', 'building agents') : 'building agents';
    }

    /* the right side */
    var lv = el('article'); lv.id = 'lv';
    var head = el('header', 'lvh'), top = el('div', 'lvt'), status = el('span', 'lvs', 'asking'), codeLine = el('p', 'lvv', ''); status.setAttribute('role', 'status');
    top.appendChild(el('h2', '', 'Live network')); top.appendChild(status); head.appendChild(top);
    head.appendChild(el('p', 'lvn2', 'What is running now on our own hardware, by the network\u2019s own clock. Lit boxes are answering. Ochre means answering, but on old code. Grey means not in the live network.'));
    head.appendChild(codeLine); lv.appendChild(head);
    var req = el('section', 'lvr'), reqH = el('b', '', 'Asking the live address'), reqP = el('p', '', ''), reqQ = el('dl', 'lvq');
    req.appendChild(el('span', 'lvk', 'Request')); req.appendChild(reqH); req.appendChild(reqP); req.appendChild(reqQ); lv.appendChild(req);
    var grid = el('div', 'lvc'), cards = {};
    PARTS.forEach(function (d) {
      var c = el('div', 'lc'), i = el('i'), b = el('b', '', 'Asking'), x = el('span', 'lx', '');
      i.setAttribute('aria-hidden', 'true'); c.appendChild(i); c.appendChild(el('span', 'ln', d.name)); c.appendChild(b); c.appendChild(x); grid.appendChild(c); cards[d.key] = { c: c, b: b, x: x };
    });
    lv.appendChild(grid);
    var foot = el('footer', 'lvf'), fClock = el('span', '', ''), fSrc = el('span', '', '');
    foot.appendChild(fClock); foot.appendChild(fSrc); lv.appendChild(foot);
    panel.appendChild(lv);

    var on = false, last = null, lastAt = 0, misses = 0, kind = refused ? 'refused' : 'asking', timer = null, asking = false, truthWas = truth ? truth.textContent : '';

    function row(dl, k, v) { var d = el('div'); d.appendChild(el('dt', '', k)); d.appendChild(el('dd', '', v)); dl.appendChild(d); }
    function paintStatus() {
      var s = (Date.now() - lastAt) / 1000, cls = '', t;
      if (kind === 'refused') { t = 'not asked'; cls = 'x'; }
      else if (kind === 'withheld') { t = 'the feed withheld its state'; cls = 'x'; }
      else if (!last) { t = misses ? 'no answer yet' : 'asking'; cls = misses ? 'x' : ''; }
      else if (misses >= 2) { t = 'no answer for ' + Math.round(s) + ' s'; cls = 'x'; }
      else { t = 'updated ' + ago(s); cls = 'u'; }
      status.textContent = t; status.className = 'lvs' + (cls ? ' ' + cls : '');
    }
    function paint() {
      var st = last && misses < 2 && kind !== 'withheld' ? last : null;
      PARTS.forEach(function (d) {
        var r = st ? st.parts[d.key] : null, s = st ? stateOf(r) : 'none', c = cards[d.key];
        var w = st ? partWords(d, r) : ['No answer', kind === 'refused' ? 'the page did not ask' : last ? 'the live address stopped answering' : 'not reached yet'];
        if (!st && kind === 'asking' && !misses) w = ['Asking', ''];
        c.b.textContent = w[0]; c.x.textContent = w[1]; c.c.className = 'lc' + (s === 'up' ? ' u' : s === 'old' ? ' o' : s === 'down' ? ' x' : '');
        marks[d.key].forEach(function (n) { n.classList.toggle('lvu', s === 'up'); n.classList.toggle('lvo', s === 'old'); n.classList.toggle('lvx', s === 'down'); n.classList.toggle('lvn', s === 'none'); });
        if (frames[d.key]) frames[d.key].classList.toggle('lvg', s === 'none');
        inner[d.key].forEach(function (n) { n.classList.toggle('lvdim', s === 'none' || s === 'down'); });
      });
      codeLine.textContent = st ? codeWords(st) : '';
      while (reqQ.firstChild) reqQ.removeChild(reqQ.firstChild);
      var e = st ? st.event : null;
      if (kind === 'refused') { reqH.textContent = 'No live address to ask'; reqP.textContent = refused; }
      else if (kind === 'shape') { reqH.textContent = 'Not a live state'; reqP.textContent = 'The address answered, but not with a state this page reads. Nothing from it is shown.'; }
      else if (kind === 'withheld') { reqH.textContent = 'State withheld'; reqP.textContent = 'The feed answered, and held its state back after its own check.'; }
      else if (!st) { reqH.textContent = last || misses ? 'No answer from the live address' : 'Asking the live address'; reqP.textContent = last || misses ? 'The page keeps asking. If the browser asked for permission to reach this address, it needs a yes.' : ''; }
      else if (!e) { reqH.textContent = 'No request is open right now'; reqP.textContent = 'When a request is open, its numbers show here as the network works through it.'; }
      else {
        var a = e.from ? day(e.from) : null, b = e.to ? day(e.to) : null;
        reqH.textContent = stage(e, st.clock);
        reqP.textContent = a && b ? 'For ' + a.t + ' to ' + b.t + ' on ' + a.d + ', by the network\u2019s own clock.' : '';
        /* one figure a network gives is its first buyer's order, and which buyer came first changes from evening to evening; a source that knows every order says so, and gives their sum */
        if (e.asked != null) row(reqQ, e.askedAll ? 'Ordered by ' + count(e.buyers || 1, 'buyer', 'buyers') : e.buyers > 1 ? 'First order' : 'Asked', fig(e.asked) + ' kW' + (e.halfHours ? ' for ' + count(e.halfHours, 'half hour', 'half hours') : ''));
        if (e.offers != null) row(reqQ, 'Offers', fig(e.offers, 0) + ' in' + (e.accepted != null ? ', ' + fig(e.accepted, 0) + ' accepted' : '') + (e.declined ? ', ' + fig(e.declined, 0) + ' declined' : ''));
        if (e.offered != null) row(reqQ, 'On offer, on average', fig(e.offered) + ' kW');
        if (e.expected) row(reqQ, 'Meter readings', fig(e.readings || 0, 0) + ' of ' + fig(e.expected, 0) + ' in');
        if (e.buyers != null) row(reqQ, 'Buyers', fig(e.buyers, 0));
        if (e.paid != null) row(reqQ, 'Paid', count(e.paid, 'node', 'nodes'));
        if (e.income != null) row(reqQ, 'Flexibility income', '$' + fig(e.income, 2));
      }
      var c = st && st.clock ? day(st.clock) : null;
      fClock.textContent = c ? 'Network clock: ' + c.d + ', ' + c.t + ' (its own simulated time)' : 'Network clock: not known';
      fSrc.textContent = base ? 'Source: ' + base.host + ', asked every ' + (st ? st.every : 5) + ' s. Figures only.' : 'Source: none';
      forks(st); paintStatus();
    }

    function again(s) { if (timer) clearTimeout(timer); timer = on ? setTimeout(ask, s * 1000) : null; }
    function ask() {
      if (!on || !url || asking) return;
      if (document.visibilityState === 'hidden') { again(2); return; }
      asking = true;
      var ctl = window.AbortController ? new AbortController() : null, stop = ctl ? setTimeout(function () { ctl.abort(); }, 4000) : null, opts = { method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer' };
      if (ctl) opts.signal = ctl.signal;
      fetch(url, opts).then(function (r) {
        if (!r.ok) throw new Error('none');
        var n = +r.headers.get('content-length'); if (n && n > MAX_CHARS) throw new Error('shape');
        return r.text();
      }).then(function (t) {
        if (t.length > MAX_CHARS) throw new Error('shape');
        var j; try { j = JSON.parse(t); } catch (e) { throw new Error('shape'); }
        var s = read(j); if (!s) throw new Error('shape');
        last = s; lastAt = Date.now(); misses = 0; kind = s.withheld ? 'withheld' : 'ok';
      }).catch(function (e) {
        misses += 1; if (e && e.message === 'shape') { kind = 'shape'; last = null; } else if (kind !== 'ok' && kind !== 'withheld') kind = 'asking';
      }).then(function () {
        if (stop) clearTimeout(stop); asking = false; paint();
        again(misses ? Math.min(30, 5 * Math.pow(2, Math.min(3, misses - 1))) : (last ? last.every : 5));
      });
    }

    /* a third tab, only in this mode */
    var tl = el('button', 'tab', 'Live'); tl.type = 'button'; tl.id = 'tab-live'; tl.setAttribute('role', 'tab'); tl.setAttribute('aria-selected', 'false');
    tabs.insertBefore(tl, document.getElementById('tab-whole') || null);
    function setLive(v) {
      if (v) { if (FG.dataView) FG.dataView.set(false); if (FG.setTab) FG.setTab('split'); }
      on = v; app.classList.toggle('lv', v); tl.setAttribute('aria-selected', v ? 'true' : 'false');
      if (v) { ts.setAttribute('aria-selected', 'false'); if (td) td.setAttribute('aria-selected', 'false'); }
      if (truth) truth.textContent = v ? 'Live: what runs now on our own hardware, by its own clock' : truthWas;
      if (FG.measure && FG.V) { try { FG.measure(FG.V.split); } catch (err) {} }
      paint();
      if (v) ask(); else if (timer) { clearTimeout(timer); timer = null; }
    }
    tl.addEventListener('click', function () { setLive(true); });
    ts.addEventListener('click', function () { if (on) setLive(false); ts.setAttribute('aria-selected', 'true'); });
    if (td) td.addEventListener('click', function () { if (on) setLive(false); });
    map.addEventListener('click', function (e) { if (on) { e.stopPropagation(); e.preventDefault(); } }, true);
    document.addEventListener('keydown', function (e) {
      if (on && ['ArrowLeft', 'ArrowRight', ' ', 'Enter'].indexOf(e.key) >= 0 && !e.target.closest('.tabs')) { e.stopImmediatePropagation(); e.preventDefault(); }
    }, true);
    document.addEventListener('visibilitychange', function () { if (on && document.visibilityState === 'visible') ask(); });
    setInterval(function () { if (on) paintStatus(); }, 1000);
    FG.live = { set: setLive, state: function () { return { on: on, kind: kind, misses: misses, last: last }; } };
    setLive(true);
  })();
})();

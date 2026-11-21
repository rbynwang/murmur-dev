
/* ---- the Data view: the same diagram, coloured by where each part's data comes from */
(function wait() {
  /* the page unpacks its day first, and only then is its own script ready */
  var el = document.getElementById('fg-dv'); if (!el) return;
  if (!(window.FG && window.FG.ready)) { setTimeout(wait, 40); return; }
  var FG = window.FG, D = JSON.parse(el.textContent), app = document.getElementById('app'), map = document.getElementById('map'), panel = document.getElementById('panel');
  var ORDER = ['e', 's', 'm', 'o'], cur = { f: 'all', sel: null }, on = false;
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function h(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function squares(k) { return '<i class="dq" aria-hidden="true">' + ORDER.map(function (x) { return '<b class="k' + x + (k.indexOf(x) >= 0 ? ' on' : '') + '"></b>'; }).join('') + '</i>'; }
  function said(k) { return k ? ORDER.filter(function (x) { return k.indexOf(x) >= 0; }).map(function (x) { return D.kinds[x].name; }).join(', ') : 'no data of its own'; }

  /* the parts of the map: its boxes, the lines inside a single site's frame, and the community's own frame */
  var parts = [];
  function mark(node, id) { var b = D.box[id]; if (!b) return; node.setAttribute('data-dv', id); node.insertAdjacentHTML('beforeend', squares(b.k)); node.setAttribute('title', said(b.k)); parts.push(node); }
  [].forEach.call(map.querySelectorAll('.blk[data-b]'), function (b) { mark(b, b.getAttribute('data-b')); });
  [].forEach.call(map.querySelectorAll('.part.psite'), function (f) {
    var blk = f.querySelector('.blk[data-b]'); if (!blk) return; var site = blk.getAttribute('data-b');
    [].forEach.call(f.querySelectorAll('.ins'), function (x, i) { mark(x, site + '-' + (i + 1)); });
  });
  var lg = map.querySelector('.part.pcom > .lg') || map.querySelector('.pcom .lg');
  if (lg) { lg.classList.add('dvl'); mark(lg, 'host'); }

  /* the right side */
  var dv = h('article', '', ''); dv.id = 'dv';
  dv.innerHTML = '<header class="dvh"><h2>Where each part\'s data comes from</h2>' +
    '<div class="dvf" role="group" aria-label="Show">' +
    '<button type="button" data-f="all">All</button>' +
    '<button type="button" data-f="e" class="ke"><i></i>' + esc(D.kinds.e.name) + '</button>' +
    '<button type="button" data-f="built" class="kb"><i></i><i></i><i></i>Built by us</button>' +
    '<span class="gl">of which</span>' +
    ['s', 'm', 'o'].map(function (k) { return '<button type="button" data-f="' + k + '" class="sm k' + k + '"><i></i>' + esc(D.kinds[k].tag) + '</button>'; }).join('') +
    '</div><p class="dvk">The bar on every box, from top to bottom: ENGIE, survey, measured, ours. A coloured piece means the part reads that kind of source.</p></header><div class="dvb" id="dvb"></div>';
  panel.appendChild(dv);
  var body = dv.querySelector('#dvb');

  function match(k, f) { return f === 'all' ? true : f === 'built' ? /[smo]/.test(k) : k.indexOf(f) >= 0; }
  function paint() {
    var fk = cur.f === 'all' ? '' : cur.f === 'built' ? 'var(--ink)' : 'var(--k' + cur.f + ')';
    parts.forEach(function (n) {
      var b = D.box[n.getAttribute('data-dv')], m = match(b.k, cur.f);
      n.classList.toggle('dim', on && cur.f !== 'all' && !m); n.classList.toggle('hit', on && cur.f !== 'all' && m);
      n.classList.toggle('dsel', on && cur.sel != null && b.p === cur.sel);
      if (fk) n.style.setProperty('--fk', fk); else n.style.removeProperty('--fk');
    });
    [].forEach.call(dv.querySelectorAll('.dvf button'), function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-f') === cur.f ? 'true' : 'false'); });
  }

  /* pictures */
  var VZ = {
    note: function (v) { return '<p class="none">' + esc(v.t) + '</p>'; },
    stats: function (v) { return '<div class="stats">' + v.rows.map(function (r) { return '<div class="k' + r[2] + '"><b>' + esc(r[0]) + '</b><span>' + esc(r[1]) + '</span></div>'; }).join('') + '</div>'; },
    bars: function (v) { return '<ul class="bars">' + v.rows.map(function (r) { return '<li class="k' + r[2] + '"><span>' + esc(r[0]) + '</span><span class="tr"><i style="width:' + (100 * r[1] / v.max).toFixed(1) + '%"></i></span><b>' + esc(r[1]) + '</b></li>'; }).join('') + '</ul>'; },
    units: function (v) {
      return '<div class="un' + (v.cols === 3 ? ' three' : v.cols === 2 ? ' two' : '') + '">' + v.groups.map(function (g) {
        return '<div class="ug"><span class="gl">' + esc(g[0]) + '</span>' + g[1].map(function (r) { return '<div class="ur"><span>' + esc(r[0]) + '</span><span class="usq ' + r[2] + '">' + new Array(r[1] + 1).join('<i></i>') + '</span><b>' + r[1] + '</b></div>'; }).join('') + '</div>';
      }).join('') + '</div><p class="ukey"><span><span class="usq c"><i></i></span>the agent commands it</span><span><span class="usq v"><i></i></span>through another device or system</span><span><span class="usq w"><i></i></span>watched only</span></p>';
    },
    stack: function (v) {
      var max = 0, i; for (i = 0; i < 24; i++) max = Math.max(max, v.homes[i] + v.bld[i] + v.other[i]);
      var cols = '', xs = '';
      for (i = 0; i < 24; i++) {
        var p = function (x) { return (100 * x / max).toFixed(2) + '%'; };
        cols += '<div class="cl' + (i >= v.win[0] && i < v.win[1] ? ' w' : '') + '" title="' + i + ':00  homes ' + v.homes[i] + ' kW, office and shops ' + v.bld[i] + ' kW, other use ' + v.other[i] + ' kW"><i class="h" style="height:' + p(v.homes[i]) + '"></i><i class="b" style="height:' + p(v.bld[i]) + '"></i><i class="x" style="height:' + p(v.other[i]) + '"></i></div>';
        xs += '<span>' + (i % 6 === 0 ? i : '') + '</span>';
      }
      return '<div class="stk">' + cols + '</div><div class="stx">' + xs + '</div><p class="skey"><span><i style="background:var(--ink)"></i>our 200 homes</span><span><i style="background:color-mix(in srgb,var(--ink) 48%,var(--paper))"></i>our office and shops</span><span><i style="background:color-mix(in srgb,var(--ke) 55%,var(--panel))"></i>other use, the rest of ENGIE\'s record</span><span>shaded: the sale window, 18 to 21</span></p>';
    },
    layers: function (v) { return '<ul class="lay">' + v.rows.map(function (r) { return '<li class="k' + r[0] + '"><span class="kt">' + esc(D.kinds[r[0]].tag) + '</span><b>' + esc(r[1]) + '</b><span>' + esc(r[2]) + '</span></li>'; }).join('') + '</ul>'; },
    range: function (v) {
      var x = function (n) { return (100 * n / v.max).toFixed(2) + '%'; }, t = '';
      [0, 1, 2, 3].forEach(function (n) { t += '<span class="tk" style="left:' + x(n) + '">$' + n + '</span>'; });
      return '<div class="rng"><div class="ax"></div><div class="bd" style="left:' + x(v.band[0]) + ';width:' + x(v.band[1] - v.band[0]) + '"></div>' + v.marks.map(function (m) { return '<div class="mk k' + m[2] + '" style="left:' + x(m[0]) + '"></div>'; }).join('') + t + '</div>' +
        '<p class="rkey">' + v.marks.map(function (m) { return esc(m[1]); }).join('. ') + '. Shaded: $' + v.band[0] + ' to $' + v.band[1] + ', ' + esc(v.band[2]) + '.</p>';
    },
    split: function (v) { return '<div class="spl">' + v.rows.map(function (r, i) { return '<i class="k' + r[2] + '" style="width:' + r[0] + '%;--n:' + i + '"></i>'; }).join('') + '</div><ul class="spk">' + v.rows.map(function (r) { return '<li><b>' + r[0] + '%</b>' + esc(r[1]) + '</li>'; }).join('') + '</ul>'; },
    fields: function (v) { return '<div class="fld">' + v.rows.map(function (r) { return '<span class="k' + r[1] + '">' + esc(r[0]) + '</span>'; }).join('') + '</div>'; },
    rows: function (v) { return '<table class="rws k' + (v.k || 's') + '">' + v.rows.map(function (r) { return '<tr><td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td></tr>'; }).join('') + '</table>'; }
  };
  function vizHTML(p) { return (p.viz || []).map(function (v) { return '<div class="vz">' + (v.h ? '<h4>' + esc(v.h) + '</h4>' : '') + VZ[v.y](v) + '</div>'; }).join(''); }

  function partHTML(key) {
    var p = D.panels[key], src = '';
    ORDER.forEach(function (k) {
      var its = p.src.filter(function (s) { return s[0] === k; }); if (!its.length) return;
      src += '<div class="src k' + k + '"><span class="kt">' + esc(D.kinds[k].name) + '</span><ul>' + its.map(function (s) { return '<li>' + esc(s[1]) + '</li>'; }).join('') + '</ul></div>';
    });
    var viz = vizHTML(p), solo = !src || !viz, wide = !!p.wide;
    return '<div class="dvp"><header><span class="fr">' + esc(p.f) + '</span><h3>' + esc(p.t) + (p.r ? '<i>' + esc(p.r) + '</i>' : '') + '</h3><p>' + esc(p.d) + '</p></header>' +
      '<div class="dvg' + (solo ? ' solo' : '') + (wide ? ' wide' : '') + '">' + (src ? '<section><h4>Built from</h4><div class="srcs">' + src + '</div></section>' : '') + (viz ? '<section><h4>' + (src ? 'What it looks like' : 'Its data') + '</h4>' + viz + '</section>' : '') + '</div></div>';
  }
  function overviewHTML() {
    var ks = cur.f === 'all' ? ORDER : cur.f === 'built' ? ['s', 'm', 'o'] : [cur.f];
    var cards = ks.map(function (k) {
      var ps = D.order.filter(function (key) { return D.panels[key].k.indexOf(k) >= 0; });
      return '<div class="kcard k' + k + '"><span class="kt">' + esc(D.kinds[k].tag) + '</span><b>' + esc(D.kinds[k].name) + '</b><p>' + esc(D.kinds[k].head) + '</p>' +
        '<div class="pl">' + ps.map(function (key) { return '<button type="button" data-p="' + key + '">' + esc(D.panels[key].t) + '</button>'; }).join('') + '</div></div>';
    }).join('');
    return '<p class="dvhint">Choose a kind above to light its parts and grey the rest. Click a part of the diagram to see how its data was built.</p><div class="dvc' + (ks.length === 1 ? ' one' : '') + '">' + cards + '</div>';
  }
  function render() { body.innerHTML = cur.sel ? partHTML(cur.sel) : overviewHTML(); body.scrollTop = 0; paint(); }
  function select(key) { cur.sel = key === cur.sel ? null : key; render(); }

  dv.addEventListener('click', function (e) {
    var f = e.target.closest('[data-f]'), p = e.target.closest('[data-p]');
    if (f) { cur.f = f.getAttribute('data-f'); if (cur.sel && !match(D.panels[cur.sel].k, cur.f)) cur.sel = null; render(); }
    else if (p) { cur.sel = p.getAttribute('data-p'); render(); }
  });
  map.addEventListener('click', function (e) {
    if (!on) return; var n = e.target.closest('[data-dv]'); e.stopPropagation(); e.preventDefault();
    if (n) select(D.box[n.getAttribute('data-dv')].p);
  }, true);
  document.addEventListener('keydown', function (e) {
    if (!on) return;
    if (e.key === 'Escape') { cur.sel = null; render(); }
    if (['ArrowLeft', 'ArrowRight', ' ', 'Enter'].indexOf(e.key) >= 0 && !e.target.closest('#dv, .tabs')) { e.stopImmediatePropagation(); e.preventDefault(); }
  }, true);

  /* two tabs: Split view and Data view */
  var tabs = document.querySelector('#bar .tabs'), ts = document.getElementById('tab-split'), td = h('button', 'tab', 'Data view');
  td.type = 'button'; td.id = 'tab-data'; td.setAttribute('role', 'tab'); td.setAttribute('aria-selected', 'false'); tabs.insertBefore(td, document.getElementById('tab-whole'));
  function setData(v) {
    if (v && FG.setTab) FG.setTab('split');
    on = v; app.classList.toggle('dv', v); td.setAttribute('aria-selected', v ? 'true' : 'false'); ts.setAttribute('aria-selected', v ? 'false' : 'true');
    if (v) render(); else paint();
    if (FG.measure && FG.V) { try { FG.measure(FG.V.split); } catch (err) {} }
    if (history.replaceState) history.replaceState(null, '', v ? '#data' : '#split');
  }
  td.addEventListener('click', function () { setData(true); });
  ts.addEventListener('click', function () { setData(false); });
  FG.dataView = { set: setData, select: function (k) { cur.sel = k; render(); }, filter: function (f) { cur.f = f; render(); }, state: cur };
  if (location.hash === '#data') setData(true);
  window.addEventListener('hashchange', function () { if (location.hash === '#data' && !on) setData(true); });
})();

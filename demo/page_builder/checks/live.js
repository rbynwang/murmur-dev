/* What the live check reads inside the two-view page. Each snippet is one function expression. */

// @snap
/* The Live view and the replay as they stand: which parts of the live mode exist, the tabs (the selected one marked *), the live
   panel's words (status, code, request, rows, a card per part, foot), the bar, the replay's controls, how each box of the diagram is
   lit, the diagram's two counts, whether anything a feed sent became markup or ran (window.__x), and whether the panel fits. */
() => { const q = (s) => document.querySelector(s), t = (s) => (q(s) || {}).textContent || '', lv = q('#lv'), panel = q('#panel');
  const vis = (e) => { if (!e) return false; const c = getComputedStyle(e), r = e.getBoundingClientRect(); return c.display !== 'none' && c.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const pr = panel.getBoundingClientRect(); let wide = 0, cut = [];
  if (lv && vis(lv)) lv.querySelectorAll('*').forEach((e) => { const r = e.getBoundingClientRect(); if (r.width && r.right > pr.right + 1) wide += 1; if (e.children.length === 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline') cut.push(e.textContent.slice(0, 30)); });
  return { tabLive: !!q('#tab-live'), lv: !!lv, css: !!q('#lv-css'), live: !!(window.FG && FG.live), on: !!(q('#app') && q('#app').classList.contains('lv')), shown: vis(lv),
    tabs: [...document.querySelectorAll('#bar .tab')].filter(vis).map((e) => e.textContent + (e.getAttribute('aria-selected') === 'true' ? '*' : '')),
    status: t('#lv .lvs'), code: t('#lv .lvv'), reqH: t('#lv .lvr b'), reqP: t('#lv .lvr p'), rows: [...document.querySelectorAll('#lv .lvq div')].map((e) => e.children[0].textContent + ': ' + e.children[1].textContent),
    cards: [...document.querySelectorAll('#lv .lc')].map((c) => c.querySelector('.ln').textContent + ' | ' + c.querySelector('b').textContent + ' | ' + c.querySelector('.lx').textContent + ' | ' + (c.className.split(' ')[1] || '-')),
    foot: t('#lv .lvf'), truth: t('#truth'), pos: t('#pos'), ctl: q('#bar .ctl') ? getComputedStyle(q('#bar .ctl')).visibility : '', layer: q('#layer') ? getComputedStyle(q('#layer')).display : '',
    boxes: Object.fromEntries(['mkt', 'town', 'h-agent', 'b-agent', 'site-dc', 'buy-u', 'buy-g', 'h-model', 'co-market', 'h-guard', 'agg-ref', 'r-pay'].map((id) => { const b = q('#map .blk[data-b="' + id + '"]'); return [id, b ? ['lvu', 'lvo', 'lvx', 'lvn', 'lvdim'].filter((c) => b.classList.contains(c)).join('+') || '-' : 'missing']; })),
    forks: [(q('#map .forks .c4h') || {}).textContent || '', (q('#map .forks .c4b') || {}).textContent || ''],
    dcFrameGrey: (() => { const b = q('#map .blk[data-b="site-dc"]'); const f = b && b.closest('.part.psite'); return f ? f.classList.contains('lvg') : null; })(),
    markup: lv ? lv.querySelectorAll('img, script, iframe, a, svg, object').length : 0, x: window.__x || 0, html: lv ? /[<>]/.test(lv.textContent) : false,
    wide: wide, cut: cut, scroll: lv && vis(lv) ? lv.scrollHeight - lv.clientHeight : 0, sideways: document.documentElement.scrollWidth > innerWidth + 1 }; };

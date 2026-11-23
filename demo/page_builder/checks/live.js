/* What the live check reads inside the two-view page. Each snippet is one function expression. */

// @state
/* Live as it stands: whether it exists and is on, its bar and timeline, the split view's moment (headline, cards, terminal lines,
   position), the state word and the bar's message, the timeline's pins and ticks, whether the page follows the newest moment,
   anything a feed sent that became an element or ran (window.__x), leaves of the bar and the timeline that are cut (the message may
   be), the bar over the layer, and a page that scrolls sideways. */
() => { const q = (s) => document.querySelector(s), t = (s) => ((q(s) || {}).textContent || '').trim();
  const vis = (e) => { if (!e) return false; const c = getComputedStyle(e), r = e.getBoundingClientRect(); return c.display !== 'none' && c.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const leaves = (root) => (root ? [...root.querySelectorAll('*')].filter((e) => !e.children.length && vis(e) && e.textContent.trim()) : []);
  const cut = leaves(q('#lv-bar')).concat(leaves(q('#lv-tl'))).filter((e) => !e.classList.contains('lv-msg') && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 2)).map((e) => e.className + ': ' + e.textContent.trim().slice(0, 30));
  const bar = q('#lv-bar'), layer = q('#layer'), pos = /(\d+) of (\d+)/.exec(t('#pos')) || [0, 0, 0];
  const markup = ['#layer', '#lv-bar', '#lv-tl', '#lv-drawer'].reduce((n, s) => n + (q(s) ? q(s).querySelectorAll('img, script, iframe, a, svg, object, embed, form').length : 0), 0);
  const k = window.FG && FG.moment && FG.moment() ? FG.moment().k.kind : 'start';
  return { tab: !!q('#tab-live'), on: !!q('#app.lv'), bar: vis(bar), tl: q('#lv-tl') && vis(q('#lv-tl')) ? Math.round(q('#lv-tl').getBoundingClientRect().width) : 0,
    now_h: t('#now-h'), cards: document.querySelectorAll('#trade .card').length, lines: document.querySelectorAll('#tb li.ln').length, k,
    pos_m: +pos[1], pos_n: +pos[2], state: t('.lv-state'), msg: t('.lv-msg'), pins: document.querySelectorAll('.lv-pin').length,
    ticks: document.querySelectorAll('.lv-tick').length, auto: !!(window.FG && FG.S && FG.S.auto), back: !!(q('.lv-back') && !q('.lv-back').hidden),
    markup, x: window.__x || 0, cut, over: !!(bar && layer && vis(bar) && bar.getBoundingClientRect().bottom > layer.getBoundingClientRect().top + 1),
    sideways: document.documentElement.scrollWidth > innerWidth + 1 }; };

// @tick
/* a press on the first tick of the timeline: the split view shows that quarter-hour's first moment */
() => { const b = document.querySelector('.lv-tick'); if (b) b.click(); return !!b; };

  /* ---------- scenarios: one page plays any of the days. Picking one swaps the story, the map, the tree and the Full record */
  function chipsHTML() { return D.order.map((k) => '<button type="button" class="chip" data-s="' + k + '" title="' + esc(D.stories[k].one) + '" aria-pressed="false">' + esc(D.stories[k].name) + '</button>').join(''); }
  function showChips() { $('inputs').innerHTML = chipsHTML(); $('w-inputs').innerHTML = chipsHTML(); }
  /* The top bar keeps one height whichever day is playing: its line gets the room the longest day's words need at this width, so changing the day moves nothing below it */
  function reserveBar() {
    const line = $('sc-line');
    if (!line || !line.offsetParent) return;
    const keep = line.innerHTML;
    let need = 0;
    line.style.minHeight = '';
    SC.list.forEach((d) => { line.innerHTML = '<b>' + esc(d.date) + '</b>' + esc(d.line); need = Math.max(need, line.getBoundingClientRect().height); });
    line.innerHTML = keep;
    if (need) line.style.minHeight = (Math.ceil(need * 64 - 1e-6) / 64).toFixed(6) + 'px';
  }
  function markScen() {
    $('app').setAttribute('data-rec', D.kind || '');     /* which recording this day is: the lines of the map are drawn by it */
    const line = $('sc-line');
    if (!line) return;
    const cur = SC.list.find((x) => x.id === S.sc);
    line.innerHTML = '<b>' + esc(cur.date) + '</b>' + esc(cur.line);
    line.title = cur.about || cur.line;
    qa('.scb').forEach((b) => b.setAttribute('aria-pressed', b.getAttribute('data-sc') === S.sc ? 'true' : 'false'));
    document.title = 'Murmur Three Levels: ' + cur.name;
  }
  async function useScenario(id) {
    if (!SC.list.some((x) => x.id === id)) return;
    stopAll();
    S.scTok = (S.scTok || 0) + 1;
    const tok = S.scTok;
    const pack = await packOf(id);
    if (tok !== S.scTok) return;                         /* a later pick won */
    B = pack;
    D = B.d;
    FG.D = D;
    S.sc = id;
    S.story = 'main';
    S.m = -1;
    S.view = 'key';
    S.read = null;
    S.auto = false;
    $('wz').innerHTML = B.world;
    V.world = worldView();
    drawLinks(V.world);
    buildMini();
    worldFor = null;
    markScen();
    showChips();
    showSent();
    showNow();
    showTrade();
    updateBar();
    if (zoomValue()) setZoom(S.zi); else setZoomUI();
    if (S.tab === 'whole') { if (!zoomValue()) measureOver(); applyWhole(false); } else if (S.tab === 'split') { measure(V.split); playSplit(false); } else if (S.tab === 'long') { openLong(); }
  }

  /* ---------- start */
  const sp = parseFloat(store.get('speed') || '1');
  S.speed = SPEEDS.indexOf(sp) >= 0 ? sp : 1;
  setTheme(store.get('theme') || 'system');
  drawLinks(V.world);
  buildMini();
  markScen();
  reserveBar();
  showChips();
  showSent();
  showNow();
  showTrade();
  updateBar();
  setZoomUI();
  measure(V.split);
  settleMap();
  renderTerm(false);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { reserveBar(); if (S.tab === 'split') { measure(V.split); settleMap(); } else if (S.tab === 'whole' && !zoomValue() && !S.part) { reserved = ''; measureOver(); const m = moment(); setEdges(V.over, m ? [m.p] : storyHops(), 'on'); } });
  /* a link can open any view: the page's address with #split, #whole or #full */
  function tabFromHash() { if (location.hash === '#whole') setTab('whole'); else if (location.hash === '#split') setTab('split'); else if (location.hash === '#full') setTab('long'); else if (location.hash === '#results' && $('results')) setTab('res'); else if (location.hash === '#coordinator') { setTab('whole'); setPart(true); } }
  window.addEventListener('hashchange', tabFromHash);
  tabFromHash();
  Object.assign(FG, { go, next, back, choose, setTab, setZoom, setPart, gotoBlock, measure, V, story, moment, ended, ZOOMS, useScenario, packOf, SC });
  FG.ready = true;
})();

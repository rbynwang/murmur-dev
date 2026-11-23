  /* ---------- moving through a story */
  function go(mi, play) {
    stopAll();
    S.m = mi;
    S.wait = false;
    S.view = 'key';
    S.read = null;
    S.busy = true;
    showNow();
    showTrade();
    updateBar();
    if (S.part && play) setPart(false);                  /* a step is shown on the tree */
    if (S.tab === 'split') playSplit(play); else applyWhole(play);
    FG.lastGo = performance.now();
  }
  function next() {
    const st = story();
    if (st.live && S.m >= st.moments.length - 1) { S.wait = true; updateBar(); return; }   /* a live story waits for its next moment */
    const n = st.moments.length;
    if (S.m < n) go(S.m + 1, true);
    if (ended()) { S.auto = false; updateBar(); }
  }
  function back() { if (S.m >= 0) { S.auto = false; go(S.m - 1, false); } }
  function choose(id) {
    if (!D.stories[id]) return;
    S.story = id;
    S.auto = false;
    showSent();
    if (S.tab === 'split') go(0, true); else go(-1, false);
  }
  function setTab(t) {
    if (t === S.tab) return;
    if (t !== 'split' && story().live) growLeave();
    stopAll();
    S.tab = t;
    $('app').setAttribute('data-tab', t);
    $('split').hidden = t !== 'split';
    $('whole').hidden = t !== 'whole';
    $('long').hidden = t !== 'long';
    if ($('results')) $('results').hidden = t !== 'res';
    $('tab-split').setAttribute('aria-selected', t === 'split' ? 'true' : 'false');
    $('tab-whole').setAttribute('aria-selected', t === 'whole' ? 'true' : 'false');
    $('tab-long').setAttribute('aria-selected', t === 'long' ? 'true' : 'false');
    if ($('tab-res')) $('tab-res').setAttribute('aria-selected', t === 'res' ? 'true' : 'false');
    showNow();
    updateBar();
    if (t === 'whole') {
      renderWorld();
      setZoomUI();
      if (!zoomValue()) measureOver(); else paintMiniView();
      applyWhole(false);
    } else if (t === 'split') {
      measure(V.split);
      playSplit(false);
    } else if (t === 'long') {
      openLong();
    }
  }
  /* the full record is a whole page of its own, so it keeps its own controls and styles. It loads when first opened */
  function openLong() {
    const f = $('long-f');
    if (f.dataset.on === S.sc) return;
    if (!f.dataset.on) f.addEventListener('load', syncLong);
    f.dataset.on = S.sc;
    f.srcdoc = B.long;
  }
  function syncLong() {
    let d = null;
    try { d = $('long-f').contentDocument; } catch (e) { return; }
    if (!d || !d.documentElement) return;
    if (root.dataset.theme) d.documentElement.dataset.theme = root.dataset.theme; else delete d.documentElement.dataset.theme;
  }
  function readBlock(b) {
    const m = moment();
    stopAll();
    S.auto = false;
    updateBar();
    S.read = S.read === b ? null : b;
    S.view = S.read ? 'block' : 'key';
    clearRead();
    settleMap();
    showNow();
    renderTerm(false);
    if (!m && S.read) $('tb').innerHTML = '<li class="pad"><h3>' + esc(BN[b].fn) + '</h3>' + esc(BN[b].ab) + '</li>';
  }


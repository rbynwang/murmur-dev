
  /* ---- asking: the state address with the cursor of the last moment held, every every_ms, at once again while more waits (at most
     80 times in a row). The Live tab; leaving it (the Split view or Data view tab, or the whole picture) stops the asking. */
  let timer = null, asking = false, burst = 0, filled = false;
  function ask() {
    if (!url || asking || !L.on) return;
    asking = true;
    const ctl = new AbortController(), stop = setTimeout(() => ctl.abort(), 8000);
    fetch(url + '?since=' + L.since, { cache: 'no-store', credentials: 'omit', redirect: 'error', signal: ctl.signal })
      .then((r) => { if (!r.ok) throw new Error('status'); return r.text(); })
      .then((t) => { const a = readAnswer(t); if (a) take(a); else { L.kind = 'shape'; L.misses += 1; } })
      .catch(() => { L.misses += 1; L.kind = L.kind === 'shape' ? 'shape' : 'down'; })
      .then(() => { clearTimeout(stop); asking = false; paint(); schedule(); });
  }
  function take(a) {
    L.misses = 0;
    L.last = a;
    L.kind = a.v1.withheld ? 'withheld' : 'ok';
    dots(a.v1);
    const v = a.v2;
    if (!v) {                                         /* no live log here: the start card alone, its figures renewed */
      L.v2 = null;
      if (L.story) { L.story.k0 = startCard(a.v1); if (FG.S.m < 0) FG.go(-1, false); }
      return;
    }
    if (L.run !== null && v.run !== L.run) {          /* a new run: the story starts again, and the log is asked from its start */
      L.run = v.run;
      L.since = 0;
      burst = 1;
      filled = false;
      FG.grow.reset();
      L.story.k0 = startCard(a.v1);
      return;
    }
    L.run = v.run;
    const leaps = L.v2 ? L.v2.clock.leaps.length : 0;
    L.v2 = v;
    if (v.clock.leaps.length > leaps) L.leapAt = Date.now();
    FG.scale = Math.max(0.02, v.clock.dwell / 8000);
    if (v.since === L.since) {
      grow(v);
      if (v.next > L.since) L.since = v.next;
    }
    burst = v.more && v.next > v.since ? burst + 1 : 0;
    follow(v);
  }
  /* the follower jumps to the newest moment after a first fill, when over 12 behind, and at speed max when over 2 behind */
  function follow(v) {
    const st = L.story;
    if (!st || !FG.S.auto || !st.moments.length) return;
    const behind = st.moments.length - 1 - FG.S.m;
    if ((!filled && !v.more && behind > 1) || behind > 12 || (v.clock.fast && behind > 2)) FG.grow.follow();
    if (!v.more) filled = true;
  }
  function schedule() {
    clearTimeout(timer);
    if (!L.on) return;
    const wait = burst > 0 && burst <= 80 ? 0 : L.misses ? Math.min(30000, 2000 * Math.pow(2, Math.min(4, L.misses - 1))) : L.v2 ? L.v2.every : 2000;
    timer = setTimeout(ask, wait);
  }
  function paint() {
    if (!L.on) return;
    barPaint();
    crowdPaint();
    cardPaint();
    tlPaint();
  }

  /* ---- the Live tab */
  function setLive(on) {
    const app = $('app'), tl = $('tab-live');
    if (on === L.on) return;
    if (on) {
      if (FG.dataView) FG.dataView.set(false);
      L.on = true;
      app.classList.add('lv');
      tl.setAttribute('aria-selected', 'true');
      ['tab-split', 'tab-data', 'tab-whole'].forEach((id) => { if ($(id)) $(id).setAttribute('aria-selected', 'false'); });
      L.story = makeStory((L.v2 && L.v2.net) || { boxes: [] });
      L.run = null;
      L.since = 0;
      filled = false;
      FG.grow.enter(L.story);
      barPlace();
      if (L.key && !L.console) hello(); else if (L.console) consoleRead();
      ask();
    } else {
      left();
      FG.grow.leave();
    }
  }
  function left() {
    if (!L.on) return;
    L.on = false;
    clearTimeout(timer);
    drawerToggle(false);
    cardToggle(false);
    CR.flash.hidden = true;
    $('app').classList.remove('lv', 'lv-aud');
    $('tab-live').setAttribute('aria-selected', 'false');
    clearDots();
    L.story = null;
  }
  function boot() {
    if (!(window.FG && window.FG.ready && window.FG.grow)) { setTimeout(boot, 40); return; }
    FG = window.FG;
    maps();
    L.key = keyFromLink();
    const tabs = document.querySelector('#bar .tabs');
    const tl = btn('tab', 'Live');
    tl.id = 'tab-live';
    tl.setAttribute('role', 'tab');
    tl.setAttribute('aria-selected', 'false');
    tabs.insertBefore(tl, $('tab-whole') || null);
    tl.addEventListener('click', () => setLive(true));
    ['tab-split', 'tab-data'].forEach((id) => { if ($(id)) $(id).addEventListener('click', () => { if (L.on) setLive(false); }); });
    barBuild();
    drawerBuild();
    cardBuild();
    tlBuild();
    FG.live = { set: setLive, left, state: () => ({ on: L.on, kind: L.kind, run: L.run, since: L.since, console: !!(L.console && L.console.ok), key: !!L.key }) };
    document.addEventListener('visibilitychange', () => { if (L.on && document.visibilityState === 'visible') { ask(); if (L.story && FG.S.auto) FG.grow.follow(); } });
    window.addEventListener('resize', () => { barPlace(); if (L.on && TL) requestAnimationFrame(fitLabels); });
    setInterval(() => { if (L.on) { barPaint(); crowdPaint(); } }, 500);
    /* a page that found its console by itself keeps a view its address names; any other opens Live */
    if (!(discover && /^#(data|split|whole|full|results|coordinator)$/.test(location.hash))) setLive(true);
    if (location.hash === '#qr') cardToggle(true);
  }
  /* with no live address in the link, the page looks for one: at its own server when it stands at that server's "/" (a console
     answers there, and is then asked for nothing it does not have), else in live.json beside the page. Each address found is
     asked once, and only a live state there opens Live. Whatever fails on the way (no file, no answer, an answer that is no live
     state), nothing is said and the page stays the recorded replay. */
  const get = (address) => {
    const ctl = new AbortController(), stop = setTimeout(() => ctl.abort(), 8000);
    return fetch(address, { cache: 'no-store', credentials: 'omit', redirect: 'error', signal: ctl.signal })
      .then((r) => (r.ok ? r.text() : '')).catch(() => '').then((t) => { clearTimeout(stop); return t; });
  };
  const answers = (address) => (aim(address) ? get(url + '?since=0').then((t) => !!readAnswer(t)) : Promise.resolve(false));
  function begin() {
    if (!discover) { boot(); return; }
    const own = location.pathname === '/' || location.pathname === '/index.html';
    const named = () => get(new URL('live.json', location.href).href).then((t) => {
      let j = null;
      try { j = t.length <= 2048 ? JSON.parse(t) : null; } catch (e) { j = null; }
      return obj(j) && typeof j.live === 'string' && j.live.length <= 400 ? answers(j.live) : false;
    });
    (own ? answers(location.origin) : Promise.resolve(false)).then((found) => found || named()).then((found) => { if (found) boot(); });
  }
  begin();
})();

  /* ---------- a live story: Live is the split view itself, playing the running network's moments as they come.
     The live script (live_*.js) makes the story and hands it its steps and moments, already checked; here they are only added and
     played by the split view's own code. A live story never ends: at its newest moment it waits for the next. */
  let kept = null;
  function growEnter(st) {
    if (!kept) kept = { story: S.story, m: S.m, speed: S.speed, scale: FG.scale };
    stopAll();
    D.stories.live = st;
    S.story = 'live';
    S.auto = true;
    S.speed = 1;
    showSent();
    if (S.tab !== 'split') setTab('split');
    go(-1, false);
    S.wait = true;
  }
  function growAdd(steps, moments) {
    const st = D.stories.live;
    if (!st || S.story !== 'live') return;
    steps.forEach((s) => st.steps.push(s));
    moments.forEach((m) => {
      st.moments.push(m);
      m.lit.forEach((b) => { if (st.touched.indexOf(b) < 0) st.touched.push(b); });
    });
    updateBar();
    if (S.auto && S.wait && moments.length) go(S.m + 1, true);
  }
  function growShow(i) {
    const st = D.stories.live;
    if (!st || i < 0 || i >= st.moments.length) return;
    S.auto = false;
    go(i, false);
  }
  function growFollow() {
    const st = D.stories.live;
    if (!st) return;
    S.auto = true;
    if (st.moments.length) go(st.moments.length - 1, true); else { go(-1, false); S.wait = true; }
  }
  function growReset() {
    const st = D.stories.live;
    if (!st) return;
    stopAll();
    st.steps.length = 0;
    st.moments.length = 0;
    st.touched.length = 0;
    S.auto = true;
    go(-1, false);
    S.wait = true;
  }
  function growLeave() {
    if (!kept) return;
    stopAll();
    delete D.stories.live;
    const was = kept;
    kept = null;
    S.story = D.stories[was.story] ? was.story : 'main';
    S.speed = was.speed;
    FG.scale = was.scale;
    S.auto = false;
    showSent();
    go(Math.min(was.m, story().moments.length - 1), false);
    if (FG.live && FG.live.left) FG.live.left();
  }
  FG.grow = { enter: growEnter, add: growAdd, show: growShow, follow: growFollow, reset: growReset, leave: growLeave };

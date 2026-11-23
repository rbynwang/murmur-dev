
  /* ---- the bar over the panel's top rows: a LIVE mark, a looping console's day, where the clock is and what it is doing, what the
     page says, back to live, and the card for a phone. A presenter's page has a row of controls above it: Start, Hold or Continue,
     Step, the speeds, the surprises, the other network. No other viewer is shown that row; a viewer of a console that takes the
     audience's taps has the strip of six events there (live_crowd). */
  const SPEED_WORDS = [['0.5', '½×'], ['1', '1×'], ['2', '2×'], ['4', '4×'], ['max', 'Max']];
  const B = {};
  function barBuild() {
    const bar = el('div', 'lv-bar');
    bar.id = 'lv-bar';
    const ctl = el('div', 'lv-row lv-ctl');
    ctl.setAttribute('role', 'toolbar');
    ctl.setAttribute('aria-label', "The presenter's controls");
    B.start = btn('lv-b', 'Start', 'Start the evening from the day before the sale');
    B.hold = btn('lv-b', 'Hold', 'Hold the clock once the step in hand is finished');
    B.step = btn('lv-b', 'Step', 'Show the next moment; at the newest, play one move of the clock');
    B.speeds = el('span', 'lv-speeds');
    B.speeds.setAttribute('role', 'group');
    B.speeds.setAttribute('aria-label', 'How long each moment stays on screen');
    SPEED_WORDS.forEach((x) => {
      const b = btn('lv-s', x[1], x[0] === 'max' ? 'As fast as the network' : 'Each moment ' + SPEEDS[x[0]] / 1000 + ' s on screen');
      b.dataset.speed = x[0];
      b.addEventListener('click', () => L.send({ do: 'pace', speed: x[0] }));
      B.speeds.appendChild(b);
    });
    B.sur = btn('lv-b lv-sur', 'Surprise', 'Trigger a surprise: a note, a car, the weather, a building, an emergency, a battery');
    B.sur.setAttribute('aria-expanded', 'false');
    B.net = btn('lv-b lv-net', 'Other network', 'Switch to the other network');
    [B.start, B.hold, B.step, B.speeds, B.sur, B.net].forEach((x) => ctl.appendChild(x));
    const row = el('div', 'lv-row lv-stat');
    B.live = el('span', 'lv-live', 'LIVE');
    B.day = el('span', 'lv-day');
    B.day.hidden = true;
    B.clock = el('b', 'lv-clock');
    B.state = el('span', 'lv-state');
    B.msg = el('span', 'lv-msg');
    B.back = btn('lv-back', '', 'Follow the running network again');
    B.qr = btn('lv-b lv-qrb', 'Phone', 'Try it on your phone: a QR code of this page, and what is live now');
    B.qr.setAttribute('aria-expanded', 'false');
    [B.live, B.day, B.clock, B.state, B.msg, B.back, B.qr].forEach((x) => row.appendChild(x));
    bar.appendChild(ctl);
    bar.appendChild(row);
    $('panel').appendChild(bar);
    B.bar = bar;
    crowdBuild(bar, row);
    B.qr.addEventListener('click', () => cardToggle());
    B.start.addEventListener('click', startPressed);
    B.hold.addEventListener('click', () => {
      const held = L.console && L.console.state && L.console.state.hold;
      if (held) { L.send({ do: 'go' }); FG.S.auto = true; if (FG.S.wait || !FG.S.busy) FG.next(); } else { L.send({ do: 'hold' }); FG.S.auto = false; }
    });
    B.step.addEventListener('click', () => {
      const st = L.story;
      if (st && FG.S.m < st.moments.length - 1) FG.grow.show(FG.S.m + 1); else L.send({ do: 'step' });
    });
    B.sur.addEventListener('click', () => drawerToggle());
    B.net.addEventListener('click', switchNet);
    B.back.addEventListener('click', () => FG.grow.follow());
    if (window.ResizeObserver) new ResizeObserver(barPlace).observe($('panel'));
    barPlace();
  }
  /* the bar covers the panel's intro and its row of stories, which keep their boxes: the layer below stays where it was */
  function barPlace() {
    if (!B.bar) return;
    const a = $('intro'), b = $('inputs');
    B.bar.style.top = a.offsetTop + 'px';
    B.bar.style.height = Math.max(0, b.offsetTop + b.offsetHeight - a.offsetTop) + 'px';
  }
  let armed = 0;
  function startPressed() {
    const play = L.console && L.console.state ? L.console.state.play : 'idle';
    if ((play === 'running' || play === 'held') && Date.now() - armed > 5000) {
      armed = Date.now();
      B.start.textContent = 'Press again to start anew';
      setTimeout(() => { armed = 0; barPaint(); }, 5000);
      return;
    }
    armed = 0;
    L.send({ do: 'start' });
  }
  function switchNet() {
    const peer = L.console && L.console.state && L.console.state.peer;
    let to = null;
    try { to = peer && peer.url ? new URL(peer.url) : null; } catch (e) { to = null; }
    if (!to || to.protocol !== location.protocol || to.hostname !== location.hostname) return;
    const go = () => { location.href = to.pathname && to.pathname !== '/' ? to.href : to.origin + '/?live=' + encodeURIComponent(to.origin) + '#k=' + encodeURIComponent(L.key); };
    const other = L.console.state.other || {};
    if (other.play === 'settled' && (!to.pathname || to.pathname === '/')) fetch(to.origin + '/console/do', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Murmur-Console': L.key },
      body: JSON.stringify({ do: 'start', run_to: L.console.state.ready && L.console.state.ready.ts }), credentials: 'omit', redirect: 'error' }).finally(go);
    else go();
  }
  /* the state word: what the clock does, as the screen shows it */
  function stateWord(v) {
    const st = L.story, behind = st && FG.S.m < st.moments.length - 1;
    if (L.kind === 'down') return 'No answer';
    if (!v) return L.kind === 'ok' ? 'Not started' : 'Waiting';
    const c = v.clock;
    if (c.state === 'settled') return behind ? 'Live event' : 'Settled';
    if (c.state === 'failed') return 'Stopped';
    if (c.state === 'idle') return 'Not started';
    if (c.state === 'starting') return 'Starting';
    if (c.state === 'held') return behind && FG.S.auto ? 'Live event' : 'Held';
    if (c.state === 'leaping' || Date.now() - L.leapAt < 700) return behind ? 'Live event' : 'Leaping to next event';
    if (!behind && c.waiting > 0 && Date.now() - L.newAt > 3 * Math.max(1000, c.dwell)) return 'Waiting for the network';
    return 'Live event';
  }
  function message() {
    if (L.refused) return L.refused;
    if (L.kind === 'shape') return 'Not a live state';
    if (L.kind === 'withheld') return 'State withheld';
    const pres = !!(L.console && L.console.ok);      /* only a presenter is told the live address's host: no other viewer's screen names it */
    if (L.kind === 'down') return 'No answer from ' + (pres ? L.base.host : 'the network');
    const s = L.console && L.console.state;
    if (s && (s.error || s.warn || s.busy || s.said)) return s.said || s.error || s.warn || s.busy;
    const loop = L.v2 && L.v2.loop;
    if (loop && loop.next !== null && !(CR.box && !CR.box.hidden)) return 'Next day starting in ' + loop.next + 's…';      /* the audience's strip says it, once */
    return pres ? 'Live from ' + L.base.host : '';
  }
  function barPaint() {
    if (!B.bar) return;
    const v = L.v2, st = L.story, c = L.console;
    const ok = !!(c && c.ok), s = ok ? c.state || {} : {};
    B.bar.classList.toggle('lv-pres', ok);
    B.live.dataset.on = L.kind === 'ok' && v && ['starting', 'leaping', 'live', 'held'].indexOf(v.clock.state) >= 0 ? '1' : '0';
    B.day.hidden = !(v && v.loop);
    if (v && v.loop) B.day.title = B.day.textContent = dayWords(v.loop);
    B.clock.textContent = v ? stamp(v.timeline.t0, nowTq(v)) : '';
    const word = stateWord(v);
    B.state.textContent = word;
    B.state.dataset.w = word.split(' ')[0].toLowerCase();
    const msg = message();
    B.msg.textContent = msg;
    B.msg.title = msg;
    const behind = st ? Math.max(0, st.moments.length - 1 - FG.S.m) : 0;
    B.back.hidden = !st || (FG.S.auto && behind === 0);
    B.back.textContent = behind ? 'Back to live, ' + behind + ' new' : 'Back to live';
    if (!ok) return;
    if (!armed) B.start.textContent = s.play === 'running' || s.play === 'held' || s.play === 'settled' ? 'Start anew' : 'Start';
    B.hold.textContent = s.hold ? 'Continue' : 'Hold';
    B.hold.setAttribute('aria-pressed', s.hold ? 'true' : 'false');
    B.speeds.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.speed === s.speed ? 'true' : 'false'));
    const mx = B.speeds.querySelector('[data-speed="max"]');
    if (mx && v) mx.title = 'As fast as the network: about ' + (Math.max(500, v.clock.floor) / 1000).toFixed(1) + ' s a quarter-hour';
    const peer = s.peer && s.peer.url;
    B.net.hidden = !peer;
    if (peer) B.net.dataset.up = s.other && s.other.up ? '1' : '0';
  }

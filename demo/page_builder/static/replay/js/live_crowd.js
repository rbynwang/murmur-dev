
  /* ---- the audience's side: where the live state says its console takes viewers' taps (the feed's crowd), every viewer without a
     presenter's key has a strip of six events in the bar, on the console's own page and on a copy of the page published
     elsewhere alike. A tap posts its event's one word to the live address's door and nothing else: no text, no number and no
     name is ever sent. The first tap fires; while the network settles the taps are votes, and the strip shows the
     seconds left, each event's votes and how many events the evening still has. A banner says so when a viewer's event fires. */
  const EVENTS = ['battery_low', 'car_now', 'weather', 'building_need', 'emergency', 'battery_fault'];
  /* an event: its word on the strip, its words in the banner, and what it does */
  const EVENT_WORDS = { battery_low: ['Battery 10%', 'Battery at 10%', 'A home battery drops to 10% charge'],
    car_now: ['Car now', 'Car needed now', 'An owner needs the car now'],
    weather: ['Solar −80%', 'Solar drop (−80%)', 'Clouds cut the sun to a fifth for three hours'],
    building_need: ['Building need', 'Building needs power', 'A building takes a quarter of its flexible load back'],
    emergency: ['Grid 20 kW', 'Grid emergency (20 kW)', 'The grid operator calls for 20 kW for an hour'],
    battery_fault: ['Battery fault', 'Battery fault', 'A home battery fails'] };
  const TAP_SAID = { fire: 'Sent. The agents are recalculating.', vote: 'Your vote is in for the next event.', again: 'You have voted in this round.',
    done: "All of tonight's events are used.", closed: 'Events open while an evening is running.' };
  const TAP_PATH = '/live/surprise', VIEWER_HEAD = 'X-Murmur-Viewer', VIEWER_STORE = 'murmur-viewer';
  const CR = { id: null, voted: null, left: null, said: null, saidAt: 0, busy: false, pills: {} };
  /* this tab's own token, made here: it tells one viewer's vote from the next one's, and is sent to the live address only */
  function viewer() {
    if (CR.id) return CR.id;
    try { CR.id = sessionStorage.getItem(VIEWER_STORE); } catch (e) { CR.id = null; }
    if (!CR.id || !/^[A-Za-z0-9_-]{16,64}$/.test(CR.id)) {
      const a = new Uint8Array(16);
      crypto.getRandomValues(a);
      CR.id = Array.from(a, (x) => x.toString(16).padStart(2, '0')).join('');
      try { sessionStorage.setItem(VIEWER_STORE, CR.id); } catch (e) { /* the token then lasts this page only */ }
    }
    return CR.id;
  }
  function crowdBuild(bar, before) {
    const box = el('div', 'lv-crowd');
    box.id = 'lv-crowd';
    box.hidden = true;
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Trigger a live grid event');
    const head = el('p', 'lv-crowd-h');
    head.appendChild(el('b', '', 'Trigger a live grid event'));
    CR.status = el('span', 'lv-crowd-s');
    CR.status.setAttribute('aria-live', 'polite');
    CR.count = el('span', 'lv-crowd-n');
    head.appendChild(CR.status);
    head.appendChild(CR.count);
    const evs = el('div', 'lv-evs');
    EVENTS.forEach((k) => {
      const b = btn('lv-ev', '', EVENT_WORDS[k][2]);
      b.dataset.kind = k;
      b.appendChild(el('span', 'lv-ev-n', EVENT_WORDS[k][0]));
      b.appendChild(el('i', 'lv-ev-v'));
      b.addEventListener('click', () => crowdTap(k));
      evs.appendChild(b);
      CR.pills[k] = b;
    });
    box.appendChild(head);
    box.appendChild(evs);
    bar.insertBefore(box, before);
    CR.box = box;
    CR.flash = el('p', 'lv-flash');
    CR.flash.hidden = true;
    CR.flash.setAttribute('role', 'status');
    $('split').appendChild(CR.flash);
  }
  function crowdTap(kind) {
    if (CR.busy || !base) return;
    CR.busy = true;
    fetch(base.origin + TAP_PATH, { method: 'POST', headers: { 'Content-Type': 'application/json', [VIEWER_HEAD]: viewer() }, body: JSON.stringify({ kind }),
      credentials: 'omit', redirect: 'error', cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const did = obj(j) && typeof j.did === 'string' && has(TAP_SAID, j.did) ? j.did : null;
        if (did === 'vote' || did === 'again') CR.voted = CR.voted || kind;
        crowdSay(did ? TAP_SAID[did] : 'The network did not take that.');
      })
      .catch(() => crowdSay('No answer from the network.'))
      .then(() => { CR.busy = false; ask(); });
  }
  function crowdSay(words) {
    CR.said = words;
    CR.saidAt = Date.now();
    paint();
  }
  /* what the strip says of the round: the next day's countdown, the cooldown, or the invitation */
  function crowdWords(c, loop) {
    if (CR.said && Date.now() - CR.saidAt < 4000) return CR.said;
    if (!c.open && loop && loop.next !== null) return 'Next day starting in ' + loop.next + 's…';
    if (!c.open) return c.left === 0 ? "All of tonight's events are used" : 'Opens while an evening is running';
    const votes = EVENTS.reduce((n, k) => n + c.votes[k], 0);
    if (c.cooldown > 0) return (votes ? 'Top vote fires in ' : 'Vote for the next event: ') + c.cooldown + 's';
    return votes ? 'Top vote fires now' : 'Tap one: the agents answer live';
  }
  function crowdPaint() {
    if (!CR.box) return;
    const v = L.v2, c = v && v.crowd;
    const show = !!c && !(L.console && L.console.ok);
    CR.box.hidden = !show;
    if ($('app').classList.contains('lv-aud') !== show) { $('app').classList.toggle('lv-aud', show); barPlace(); }      /* the strip has its own height in the bar */
    flashPaint(c);
    if (!show) return;
    const strip = $('strip'), stage = strip && strip.querySelector('.stg.now');          /* a phone's row of stages keeps the one in hand in sight */
    if (stage && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = stage.offsetLeft - strip.offsetLeft - (strip.clientWidth - stage.offsetWidth) / 2;
    if (c.left !== CR.left || (c.cooldown === 0 && EVENTS.every((k) => !c.votes[k]))) { CR.left = c.left; CR.voted = null; }      /* a new round */
    CR.status.textContent = crowdWords(c, v.loop);
    CR.count.textContent = c.left + '/' + c.most + ' left tonight';
    EVENTS.forEach((k) => {
      const b = CR.pills[k], n = c.votes[k];
      b.disabled = !c.open || c.presets.indexOf(k) < 0 || CR.busy || !!CR.voted;
      b.setAttribute('aria-pressed', CR.voted === k ? 'true' : 'false');
      b.lastChild.textContent = n ? String(n) : '';
      b.lastChild.hidden = !n;
    });
  }
  /* the banner: for twelve seconds after an event of the audience's has fired */
  function flashPaint(c) {
    const last = c && c.last, on = !!last && last.ago !== null && last.ago < 12;
    CR.flash.hidden = !on;
    if (on) CR.flash.textContent = '⚡ ' + (last.by === 'vote' ? 'Live viewers voted: ' : 'Live viewer triggered: ') + EVENT_WORDS[last.kind][1] + ' — agents recalculating…';
  }
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  /* a looping console's day as the bar says it: "Day 1 of 3 · Jan 28 Winter peak" */
  function dayWords(loop) {
    const m = /^\d{4}-(\d\d)-(\d\d)$/.exec(loop.date), date = m && MONTHS[+m[1] - 1] ? MONTHS[+m[1] - 1] + ' ' + +m[2] : '';
    return [loop.days > 1 ? 'Day ' + loop.day + ' of ' + loop.days : '', [date, loop.label].filter(Boolean).join(' ')].filter(Boolean).join(' · ');
  }

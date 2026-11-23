
  /* ---- reading an answer: of v1 only what the dots and the start card show; v2 against the feed's fixed lists and caps */
  const STATES = ['idle', 'starting', 'leaping', 'live', 'held', 'settled', 'failed'];
  const SPEEDS = { '0.5': 16000, '1': 8000, '2': 4000, '4': 2000, max: 0 };      /* ms a moment stays on screen: at 1, the replay's own 8 seconds */
  const PART_IDS = ['dayahead', 'request', 'before', 'window', 'settle'];
  const STOP_IDS = ['sale', 'request', 'before', 'delivery', 'end', 'readings'];
  const KINDS = ['note', 'car_now', 'weather', 'building_closed', 'building_need', 'emergency', 'battery_fault', 'battery_low'];
  const PART_KEYS = ['town', 'aggregator', 'community', 'homes', 'buildings', 'datacenter', 'buyer_utility', 'buyer_grid', 'model'];
  function readV1(j) {
    if (!obj(j) || j.schema !== V1) return null;
    if (j.withheld === true) return { withheld: true, parts: {}, event: null };
    const p = obj(j.parts) || {}, parts = {};
    PART_KEYS.forEach((k) => { const r = obj(p[k]); parts[k] = r ? { up: r.up === true, current: r.current === true ? true : r.current === false ? false : null } : null; });
    const e = obj(j.event);
    const ev = e ? { asked: num(e.asked_kw, 0, 1e7), offers: whole(e.offers, 0, 1e6), accepted: whole(e.accepted, 0, 1e6), offered: num(e.offered_kw, 0, 1e7),
      readings: whole(e.readings, 0, 1e7), expected: whole(e.readings_expected, 0, 1e7),
      window: arr(e.window, 2) && e.window.every((x) => TIME.test(x)) ? e.window.map((x) => x.slice(11)) : null } : null;
    return { withheld: false, parts, event: ev, homes: whole((obj(p.homes) || {}).count, 0, 1e5), buildings: whole((obj(p.buildings) || {}).count, 0, 1e5) };
  }
  function readClock(c) {
    c = obj(c) || {};
    const speed = typeof c.speed === 'string' && has(SPEEDS, c.speed) ? c.speed : '1';
    const leaps = (arr(c.leaps, 24) || []).map((x) => (obj(x) ? { from: whole(x.from, 0, 400), to: whole(x.to, 0, 400), ms: whole(x.ms, 0, 3600000) } : null))
      .filter((x) => x && x.from !== null && x.to !== null && x.from < x.to);
    const dwell = whole(c.dwell_ms, 0, 20000);
    return { state: STATES.indexOf(c.state) >= 0 ? c.state : 'idle', tq: whole(c.tq, 0, 400) || 0, speed, dwell: dwell === null ? SPEEDS[speed] : dwell,
      fast: c.fast === true, waiting: whole(c.waiting, 0, 999) || 0, floor: whole(c.floor_ms, 0, 120000) || 0, leaps };
  }
  function readTimeline(t) {
    t = obj(t) || {};
    const n = whole(t.n, 1, 400);
    if (!TIME.test(t.t0 || '') || n === null) return null;
    const parts = (arr(t.parts, 8) || []).map((p) => (obj(p) && PART_IDS.indexOf(p.id) >= 0 ? { id: p.id, from: whole(p.from, 0, 400), to: whole(p.to, 0, 400) } : null))
      .filter((p) => p && p.from !== null && p.to !== null && p.from < p.to);
    const pins = (arr(t.pins, 48) || []).map((p) => {
      if (!obj(p) || whole(p.tq, 0, 400) === null) return null;
      const ok = (p.kind === 'stop' && STOP_IDS.indexOf(p.id) >= 0) || (p.kind === 'surprise' && KINDS.indexOf(p.id) >= 0);
      return ok && ['past', 'next', 'ahead'].indexOf(p.state) >= 0 ? { tq: p.tq, kind: p.kind, id: p.id, state: p.state, jump: p.jump === true } : null;
    }).filter(Boolean);
    return parts.length ? { t0: t.t0, n, parts, pins } : null;
  }
  /* the audience's door and a looping console's day: only on a console that sends them, and only these fields */
  const PRESETS = ['battery_low', 'car_now', 'weather', 'building_need', 'emergency', 'battery_fault'];
  function readCrowd(c) {
    if (!obj(c)) return null;
    const votes = {}, sent = obj(c.votes) || {}, last = obj(c.last);
    PRESETS.forEach((k) => { votes[k] = has(sent, k) ? whole(sent[k], 0, 1e6) || 0 : 0; });
    const most = whole(c.most, 1, 99) || 5;
    return { open: c.open === true, presets: (arr(c.presets, 6) || []).filter((k) => PRESETS.indexOf(k) >= 0), cooldown: whole(c.cooldown_s, 0, 600) || 0, votes,
      left: Math.min(most, whole(c.left, 0, 99) || 0), most,
      last: last && PRESETS.indexOf(last.kind) >= 0 ? { kind: last.kind, by: last.by === 'vote' ? 'vote' : 'viewer', ago: whole(last.ago_s, 0, 1e7) } : null };
  }
  function readLoop(l) {
    if (!obj(l)) return null;
    const day = whole(l.day, 1, 99), days = whole(l.days, 1, 99);
    if (day === null || days === null || day > days) return null;
    return { day, days, date: /^\d{4}-\d\d-\d\d$/.test(l.date || '') ? l.date : '', label: (str(l.label, 40) || '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim(),
      next: whole(l.next_s, 0, 3600) };
  }
  function readV2(v) {
    if (!obj(v) || v.schema !== V2) return null;
    const run = whole(v.run, 0, 1e9), since = whole(v.since, 0, 1e6), next = whole(v.next, 0, 1e6);
    const timeline = readTimeline(v.timeline);
    if (run === null || since === null || next === null || !timeline) return null;
    const net = obj(v.net) || {};
    return { run, since, next, more: v.more === true, every: Math.min(5000, Math.max(250, whole(v.every_ms, 0, 1e6) || 2000)), clock: readClock(v.clock), timeline,
      net: { key: str(net.key, 20) || '', boxes: (arr(net.boxes, 64) || []).filter(known) },
      crowd: readCrowd(v.crowd), loop: readLoop(v.loop), steps: arr(v.steps, 6 * 24) || [], moments: arr(v.moments, 6) || [] };
  }
  /* an answer as text: refused over its cap, or when it is no JSON, or no live state */
  function readAnswer(text) {
    if (text.length > MAX_CHARS) return null;
    let j = null;
    try { j = JSON.parse(text); } catch (e) { return null; }
    const v1 = readV1(j);
    return v1 ? { v1, v2: obj(j) && j.v2 !== undefined ? readV2(j.v2) : null } : null;
  }

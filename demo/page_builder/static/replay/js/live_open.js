
/* ---- Live: the split view, playing what the running network sends. It runs when the page's own address carries
   ?live=<base address>, and the page then asks <base address>/live/state.json. With no such address a page on the web looks
   for one itself (live_ask's begin): first in the file live.json beside the page, {"live": "<base address>"}, which whoever
   publishes the page puts there; then, for a page at its server's own "/", at that server (a console). Where a live state
   answers, Live opens by itself. Where none does (no such file, a network that is switched off), and always with ?replay=1,
   nothing of Live is made and the page is the recorded replay.
   The base address comes from the link, from that file or from the page's own origin, never from this file.
   Everything that comes back is untrusted: every field is checked, and every text becomes text, never markup.
   The files live_open to live_ask are one function: this one opens it, live_ask ends it. */
(function () {
  'use strict';
  let given = null, replay = false;
  try { const q = new URLSearchParams(window.location.search); given = q.get('live'); replay = q.get('replay') === '1'; } catch (e) { given = null; }
  const web = location.protocol === 'http:' || location.protocol === 'https:';
  const discover = !given && !replay && web;         /* no address in the link: the page looks for one */
  if (!given && !discover) return;

  const STATE_PATH = '/live/state.json', MAX_CHARS = 262144, V1 = 'murmur.live.v1', V2 = 'murmur.live.v2';
  let base = null, url = null, refused = '', onConsole = false;
  /* takes a live address: the state's address, or why the page does not use it. The page is on a console when the live address
     is the page's own origin: only then are a presenter's key and the console's two keyed doors used */
  function aim(address) {
    base = null; url = null; refused = '';
    try { base = new URL(address); } catch (e) { base = null; }
    if (!base || (base.protocol !== 'http:' && base.protocol !== 'https:')) { refused = 'The live address in this link is not a web address.'; base = null; }
    else if (base.username || base.password) { refused = 'The live address in this link carries a sign-in, so the page does not use it.'; base = null; }
    else { url = base.origin + base.pathname.replace(/\/+$/, '') + STATE_PATH; }
    onConsole = !!base && web && base.origin === location.origin;
    return !!base;
  }
  if (given) aim(given);

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const btn = (cls, text, title) => { const b = el('button', cls, text); b.type = 'button'; if (title) b.title = title; return b; };
  const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const obj = (x) => (x && typeof x === 'object' && !Array.isArray(x) ? x : null);
  const arr = (x, n) => (Array.isArray(x) && x.length <= n ? x : null);
  const str = (x, n) => (typeof x === 'string' ? x.slice(0, n || 600) : null);
  const whole = (x, lo, hi) => (typeof x === 'number' && isFinite(x) && Math.floor(x) === x && x >= lo && x <= hi ? x : null);
  const num = (x, lo, hi) => (typeof x === 'number' && isFinite(x) && x >= lo && x <= hi ? x : null);
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const TIME = /^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d)$/;
  /* a quarter-hour of the evening as the bar says it, "Tue 18:30", counted from the timeline's first quarter-hour */
  function stamp(t0, tq) {
    const m = TIME.exec(t0 || '');
    if (!m || tq == null) return '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) + tq * 900000);
    return DAYS[d.getUTCDay()] + ' ' + String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0');
  }
  function hhmm(t0, tq) { const s = stamp(t0, tq); return s ? s.slice(4) : ''; }
  /* the dataset time of a quarter-hour, as a console takes it: "2025-01-28 18:30" */
  function tsOf(t0, tq) {
    const m = TIME.exec(t0 || '');
    if (!m) return '';
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) + tq * 900000);
    const p = (x) => String(x).padStart(2, '0');
    return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate()) + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
  }
  let FG = null;                         /* the split view's own: set once its page is ready (live_ask) */
  /* what every file of this function shares: the address, the last answer, the story, and the console */
  const L = { get base() { return base; }, get refused() { return refused; }, last: null, v2: null, run: null, since: 0, story: null, key: null, console: null, on: false,
    kind: 'asking', misses: 0, newAt: 0, leapAt: 0, held: false };

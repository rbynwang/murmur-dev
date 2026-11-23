
  /* ---- the console: a presenter's key and the console's two doors, used only on the console's own origin. The key comes after
     "#k=" in the link: it is read once into this tab's own store and taken out of the address before anything else asks. On any
     other origin the fragment is taken out unread, no stored key is used, and nothing asks the console's doors. */
  const DOOR = '/console/do', STATE = '/console/state', STORE = 'murmur-console-key', HEAD = 'X-Murmur-Console';
  function keyFromLink() {
    const h = location.hash || '';
    const m = /(?:^#|&)k=([A-Za-z0-9_-]{16,})(?:&|$)/.exec(h);
    if (/(?:^#|&)k=/.test(h)) history.replaceState(null, '', location.pathname + location.search);
    if (!onConsole) return null;
    if (m) { try { sessionStorage.setItem(STORE, m[1]); } catch (e) { /* the key then lasts this page only */ } return m[1]; }
    try { return sessionStorage.getItem(STORE); } catch (e) { return null; }
  }
  function forget() {
    L.key = null;
    L.console = null;
    try { sessionStorage.removeItem(STORE); } catch (e) { /* nothing kept */ }
    paint();
  }
  const door = (path, body) => fetch(path, { method: body ? 'POST' : 'GET', headers: Object.assign({ [HEAD]: L.key }, body ? { 'Content-Type': 'application/json' } : {}),
    body: body ? JSON.stringify(body) : undefined, credentials: 'omit', redirect: 'error', cache: 'no-store' });
  function hello() {
    if (!L.key) return;
    door(DOOR, { do: 'hello' }).then((r) => {
      if (r.status === 202) { L.console = { ok: true, state: null }; consoleRead(); } else if (r.status === 403) forget();
    }).catch(() => { setTimeout(hello, 3000); });
  }
  /* what the console says of itself, checked: only these fields, only these kinds of value */
  function consoleState(j) {
    if (!obj(j) || j.schema !== 'murmur.console.v1') return null;
    const r = obj(j.roster) || {};
    const homes = (arr(r.homes, 400) || []).filter((h) => obj(h) && str(h.id, 40)).map((h) => ({ id: h.id, name: str(h.name, 60) || h.id, battery: h.battery === true }));
    const builds = (arr(r.buildings, 100) || []).filter((b) => obj(b) && str(b.id, 40)).map((b) => ({ id: b.id, name: str(b.name, 60) || b.id }));
    const peer = obj(j.peer), other = obj(j.other) || {}, ready = obj(j.ready) || {};
    return { play: str(j.play, 20) || 'idle', speed: has(SPEEDS, j.speed) ? j.speed : '1', hold: j.hold === true, busy: str(j.busy, 200), error: str(j.error, 200),
      warn: str(j.warn, 200), roster: { homes, buildings: builds, buyers: (arr(r.buyers, 10) || []).filter((b) => str(b, 40)) },
      peer: peer && str(peer.url, 200) ? { url: peer.url } : null, other: { up: other.up === true, play: str(other.play, 20) },
      ready: { ts: TIME.test(ready.ts || '') ? ready.ts : null }, said: L.console && L.console.state ? L.console.state.said : null };
  }
  function consoleRead() {
    if (!L.console || !L.on) return;
    door(STATE).then((r) => {
      if (r.status === 403) { forget(); return null; }
      return r.ok ? r.json() : null;
    }).then((j) => {
      const s = j ? consoleState(j) : null;
      if (s && L.console) { L.console.state = s; paint(); }
    }).catch(() => {}).then(() => { if (L.console) setTimeout(consoleRead, 1000); });
  }
  /* one command; a refusal's words stand in the bar for a few seconds */
  L.send = function (body) {
    if (!L.console || !L.key) return;
    door(DOOR, body).then((r) => {
      if (r.status === 403) { forget(); return; }
      if (r.status === 400) return r.json().then((j) => say(str(obj(j) && j.error, 200) || 'The console refused that.'));
      say(null);
    }).catch(() => say('No answer from the console.'));
  };
  function say(words) {
    if (!L.console || !L.console.state) return;
    L.console.state.said = words;
    paint();
    if (words) setTimeout(() => { if (L.console && L.console.state && L.console.state.said === words) { L.console.state.said = null; paint(); } }, 4000);
  }

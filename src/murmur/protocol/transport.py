"""The client of the message bus: one session per participant name, over the bus's HTTP contract (version 0.2.0).

  POST /runs/{run}/join          a session, with the run's grant for this name (or its join token)
  POST /runs/{run}/messages      send: one message id, one message; a retry of the same body is a replay, another body a refusal
  GET  /runs/{run}/inbox/notify  a wake-up hint (never a held long-poll)
  POST /runs/{run}/inbox/claim   the oldest message, leased
  POST /runs/{run}/inbox/ack     done, with its fence

Every call is safe to repeat. A session that loses its name to another process again and again pauses instead of fighting for it.
The bus's address comes from configuration only (town_url).
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from typing import Any

import httpx

from murmur.protocol import envelope as beckn

VOLATILE = {"timestamp", "sentWall", "messageId"}         # what a body made again differs in, however alike


def grants() -> dict[str, Any]:
    """The run grants held in this participant's configuration folder, by name ({} when there are none)."""
    from murmur import config
    path = config.CONFIG_DIR / "secrets" / "town_grants.json"
    return json.loads(path.read_text()) if path.exists() else {}


def join_proof(private_hex: str, run_id: str, name: str) -> str:
    """The session's proof for a grant join: its Ed25519 signature over {"purpose": "join", "run_id", "name"} as canonical JSON."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    text = json.dumps({"purpose": "join", "run_id": run_id, "name": name}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).sign(text.encode()).hex()


class TownIdentityConflict(RuntimeError):
    """Another process keeps taking this participant's Town session (each join ends the other's session)."""


class TownWatch:
    """Is the bus answering, and are this process's sends getting through? What /health tells. A host's sessions share one.

    Every session polls its inbox every few seconds, so this needs no probe of its own. An answer from the bus counts as reached; a 5xx (a proxy in
    front of it) or no answer doesn't. A send that raised counts as failed, and so does one the bus refused (409: that message went nowhere, see send)."""

    def __init__(self, window: float = 60.0):
        self.window, self.started = window, time.time()
        self.ok_at = 0.0                                   # when Town last answered: 0 until it has, so a process that never reached it says so
        self.sends: deque = deque(maxlen=4000)             # (wall, went through)

    def reached(self, ok: bool) -> None:
        if ok:
            self.ok_at = time.time()

    def sent(self, ok: bool) -> None:
        self.sends.append((time.time(), ok))

    def state(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        lately = [ok for t, ok in list(self.sends) if now - t <= self.window]
        return {"town_seen": self.ok_at > 0, "town_ok_s": round(now - (self.ok_at or self.started), 1), "sends": len(lately), "failed": lately.count(False)}


def meaning(body: Any) -> Any:
    """What a body says: all of it but the time it was made and the signature over that, here or in a reading inside a batch."""
    if isinstance(body, list):
        return [meaning(x) for x in body]
    if not isinstance(body, dict):
        return body
    return {k: ({a: b for a, b in v.items() if a not in VOLATILE} if k == "context" and isinstance(v, dict) else meaning(v)) for k, v in body.items() if k != "sig"}


class Sent:
    """What this participant has sent, by id, for as long as the process runs. It's how the same id goes only with the same body (ids.py): a body made again carries a new
    time and signature, so a retry takes the body that went first, and Town answers replay. After a restart a body made again goes: Town takes it if the first never reached
    it, and refuses it if it did, which is loud and loses nothing, because a 409 means Town holds this message already."""

    def __init__(self, size: int = 512):
        self.size = size
        self.held: OrderedDict[str, tuple[str, str, dict[str, Any]]] = OrderedDict()
        self.lock = threading.Lock()

    def body_for(self, mid: str, to: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        """The body to send under this id. The first time, this one. A retry, the first one, unless nobody would read it any more: past its ttl a body made again goes instead.
        Town takes it if the first never reached it, and refuses it if it did, and then the first is what counts. Something that says otherwise goes as it is, to be refused."""
        with self.lock:
            first = self.held.get(mid)
            again = first is not None and first[:2] == (to, kind) and meaning(first[2]) == meaning(body)
            if again and beckn.expired(first[2]) is None:
                return first[2]
            if first is None or again:
                self.held[mid] = (to, kind, body)
                while len(self.held) > self.size:
                    self.held.popitem(last=False)
            return body


class TownSession:
    # a participant that has to join again this many times within CONFLICT_WINDOW s is sharing its name with another
    # process (a join ends the other session, which joins again, ...): stop for CONFLICT_PAUSE s instead of fighting
    CONFLICT_REJOINS, CONFLICT_WINDOW, CONFLICT_PAUSE = 3, 120.0, 60.0

    def __init__(self, base_url: str, run_id: str, name: str, token: str, http: httpx.Client | None = None):
        self.base_url, self.run_id, self.name, self.token = base_url.rstrip("/"), run_id, name, token
        # http: a client to share. Each client holds its own TLS context, about 0.75 MB: 200 sessions on one client save about 150 MB
        self.http = http or httpx.Client(base_url=self.base_url, timeout=40.0)
        self.session: str | None = None
        self.lock = threading.Lock()
        self.retried = 0                   # calls this session had to try again (a dropped connection, a 502/503/504)
        self.dropped = 0                   # messages Town refused: their id already held another message
        self.replays = 0                   # sends Town had already taken: a retry after an answer that never came
        self.sent = Sent()                 # the bodies this session sent, by message id: a retry sends the same body
        self.rejoins: deque = deque(maxlen=10)       # when this session had to join again after a 401
        self.conflict_until = 0.0
        self.conflicts = 0                 # times another process was found using this name
        self.times: deque = deque(maxlen=3000)      # (wall, op, seconds) of each Town call: timing()
        self.watch = TownWatch()           # a host gives all its sessions one

    def timing(self, window: float = 120.0) -> dict[str, dict[str, float]]:
        """How long this session's calls took in the last `window` s, by kind: {op: {n, p50_ms, p95_ms}}. A slow bus shows here first."""
        now, by = time.time(), {}
        for t, op, d in list(self.times):
            if now - t <= window:
                by.setdefault(op, []).append(d)
        out = {}
        for op, ds in by.items():
            ds.sort()
            out[op] = {"n": len(ds), "p50_ms": round(1000 * ds[len(ds) // 2]), "p95_ms": round(1000 * ds[int(0.95 * (len(ds) - 1))])}
        return out

    @staticmethod
    def _op(path: str) -> str:
        for key, op in (("/inbox/notify", "notify"), ("/inbox/claim", "claim"), ("/inbox/ack", "ack"),
                        ("/messages", "send"), ("/participants", "participants")):
            if path.endswith(key):
                return op
        return "other"

    def _h(self) -> dict[str, str]:
        return {"X-Town-Session": self.session or ""}

    def join(self) -> dict[str, Any]:
        with self.lock:
            return self._join()

    def join_until_up(self, then: Any = None, log: Any = None, every: float = 15.0) -> threading.Thread:
        """Join in the background, again every `every` s while the bus cannot be reached (a 5xx, a refused connection), then call
        `then()`: the service's own doors stay up meanwhile, so /health can say what is wrong instead of a process that exited."""
        def run() -> None:
            tries = 0
            while True:
                try:
                    self.join()
                    break
                except Exception as exc:               # noqa: BLE001  any failure: wait and try again
                    tries += 1
                    if log and (tries == 1 or tries % 20 == 0):
                        log(f"the bus is not reachable ({str(exc)[:120]}); trying again every {every:g} s")
                    time.sleep(every)
            if log and tries:
                log(f"joined the bus after {tries} failed tries")
            if then:
                then()
        t = threading.Thread(target=run, daemon=True, name=f"town-join-{self.name}")
        t.start()
        return t

    def _join(self) -> dict[str, Any]:
        """Join the run: with the run's grant for this name (secrets/town_grants.json: grant, grant_signature, session_private), signed as
        a proof of the session's own key, or else with the join token."""
        held = grants().get(self.name)
        if held is None:
            r = self.http.post(f"/runs/{self.run_id}/join", json={"name": self.name, "token": self.token})
        else:
            r = self.http.post(f"/runs/{self.run_id}/join", json={"name": self.name, "grant": held["grant"], "grant_signature": held["grant_signature"],
                                                                 "session_proof": join_proof(held["session_private"], self.run_id, self.name)})
        r.raise_for_status()
        data = r.json()
        self.session = data["session"]
        return data

    def _rejoin(self, stale: str | None) -> None:
        """Join again only if nobody has done it since `stale` was read: a join ends the previous session, so threads
        that all saw the same 401 must not each join (they would end each other's new session). A name that keeps
        losing its session is held by another process too: pause instead of taking it back again and again."""
        with self.lock:
            if self.session == stale or not self.session:
                now = time.time()
                if stale is not None:
                    self.rejoins.append(now)
                    recent = [t for t in self.rejoins if now - t <= self.CONFLICT_WINDOW]
                    if len(recent) >= self.CONFLICT_REJOINS:
                        self.rejoins.clear()
                        self.conflicts += 1
                        self.conflict_until = now + self.CONFLICT_PAUSE
                        raise TownIdentityConflict(
                            f"{self.name}: another process keeps taking this Town session; pausing "
                            f"{self.CONFLICT_PAUSE:.0f} s (run only one process per participant name)")
                self._join()

    def _request(self, method: str, path: str, session: str | None, **kw) -> httpx.Response:
        """One HTTP call, tried once more if the connection drops on the way (a kept-alive connection the server had
        already closed). Every call is safe to repeat: a send carries its
        message id (Town takes it once), a claim whose answer was lost comes back after its lease, an ack repeated
        gets a stale-fence answer."""
        try:
            return self.http.request(method, path, headers={"X-Town-Session": session or ""}, **kw)
        except httpx.TransportError:
            self.retried += 1
            time.sleep(0.3)
            return self.http.request(method, path, headers={"X-Town-Session": session or ""}, **kw)

    def _call(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self._tried(method, path, **kw)
        except httpx.HTTPError:
            self.watch.reached(False)
            raise
        self.watch.reached(r.status_code < 500)
        return r

    def _tried(self, method: str, path: str, **kw) -> httpx.Response:
        if time.time() < self.conflict_until:
            raise TownIdentityConflict(f"{self.name}: paused, another process holds this Town session")
        if not self.session:
            self._rejoin(None)
        used = self.session
        t0 = time.time()
        r = self._request(method, path, used, **kw)
        if r.status_code == 401:                           # another join ended the session, or it expired: join again once
            self._rejoin(used)
            r = self._request(method, path, self.session, **kw)
        if r.status_code in (502, 503, 504):               # the bus's "lost ack" fault (503), or a proxy in front of it
            self.retried += 1                              # (502/504): retry once
            time.sleep(0.5)
            r = self._request(method, path, self.session, **kw)
        self.times.append((t0, self._op(path), time.time() - t0))
        return r

    def send(self, to: str, kind: str, body: dict[str, Any], message_id: str) -> dict[str, Any]:
        body = self.sent.body_for(message_id, to, kind, body)
        try:
            r = self._call("POST", f"/runs/{self.run_id}/messages",
                           json={"message_id": message_id, "to": to, "kind": kind, "body": body})
            if r.status_code == 409:
                # Town answers a retry of the same envelope as it did the first time, with "replay": true. A 409 means this id already holds a different
                # message, and this one went nowhere (nandatown db.accept_message). The caller records it: otherwise a day's readings could vanish without a word
                self.dropped += 1
                self.watch.sent(False)
                return {"message_id": message_id, "duplicate": True}
            r.raise_for_status()
        except Exception:
            self.watch.sent(False)
            raise
        self.watch.sent(True)
        out = r.json()
        self.replays += 1 if out.get("replay") else 0
        return out

    def notify(self, wait: float = 0.0) -> bool:
        """Pop one wake-up hint. Keep `wait` at 0 (see the module docstring: a held long-poll costs Town ~20 scans a
        second); InboxPoller does the waiting on this side."""
        r = self._call("GET", f"/runs/{self.run_id}/inbox/notify", params={"wait": wait})
        r.raise_for_status()
        return bool(r.json().get("hint"))

    def claim(self) -> dict[str, Any] | None:
        r = self._call("POST", f"/runs/{self.run_id}/inbox/claim")
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def ack(self, message_id: str, fence: str, status: str, note: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._call("POST", f"/runs/{self.run_id}/inbox/ack",
                       json={"message_id": message_id, "fence": fence, "status": status, "note": note or {}})
        if r.status_code == 409:
            return {"stale_fence": True}
        r.raise_for_status()
        return r.json()

    def participants(self) -> list[dict[str, Any]]:
        r = self._call("GET", f"/runs/{self.run_id}/participants")
        r.raise_for_status()
        return r.json()

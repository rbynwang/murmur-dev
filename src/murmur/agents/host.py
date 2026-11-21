"""A node host: many members run as real agents in one process, each with its own replay, simulated devices, Ed25519 key and bus session.

  NodeLock   the tick, the inbox and the agent take turns on a node; the agent lets go while it waits for the model
  Thinker    a node agent's own thread: its mail first, then the newest step
  NodeHost   the members, their inboxes, their sends and their ticks; HomeNodes (agents/home.py) makes homes, BuildingHost buildings

A message is acted on once: a copy of one still being worked on is left alone, one already finished is only acknowledged, and the bus
hears a message was done only when it was. If the model is away, every point it would word falls back to code by itself.

  python -m murmur.agents.host_doors run [--buildings]
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import httpx

from murmur import config
from murmur.protocol import signing
from murmur.node.home import MemberNode
from murmur.node.home_days import TRAINED
from murmur.node import record
from murmur.node.llm_client import SharedModel
from murmur.protocol import envelope as beckn
from murmur.protocol.transport import TownSession
from murmur.agents.host_common import log
from murmur.agents.host_people import HostPeople
from murmur.agents.home import HomeNodes

KEEP_DECISIONS = 300           # what the status API keeps of a thinking node's decisions (all of them go to the file)
KEEP_SEEN = 512                # message ids a node remembers, so a repeat from Town changes nothing
RETRY_S = (5.0, 15.0, 45.0, 120.0, 300.0)   # a batch of readings goes once, after the window: these waits outlast a dropped connection


class NodeLock:
    """Whoever holds it may touch this node's state. A plain lock, plus let_go for the time spent waiting on the model."""

    def __init__(self) -> None:
        self._l = threading.Lock()
        self._who: int | None = None

    def __enter__(self) -> "NodeLock":
        self._l.acquire()
        self._who = threading.get_ident()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.leave()

    def leave(self) -> None:
        self._who = None
        self._l.release()

    def try_enter(self) -> bool:
        ok = self._l.acquire(blocking=False)
        if ok:
            self._who = threading.get_ident()
        return ok

    @contextlib.contextmanager
    def let_go(self):
        mine = self._who == threading.get_ident()
        if mine:
            self._who = None
            self._l.release()
        try:
            yield
        finally:
            if mine:
                self._l.acquire()
                self._who = threading.get_ident()


class Thinker(threading.Thread):
    """A thinking node's own thread. It takes its mail first, then the newest step: a step it missed while busy isn't owed."""

    def __init__(self, host: "NodeHost", name: str):
        super().__init__(daemon=True, name=f"think-{name}")
        self.host, self.node = host, name
        self.mail: deque = deque()
        self.want: str | None = None
        self.done: str | None = None
        self.wake = threading.Event()
        self.skipped = 0
        self.running = False                  # taking its mail or stepping: the clock waits for it (cfg clock_waits)

    def post(self, msg: dict[str, Any]) -> None:
        self.mail.append(msg)
        self.wake.set()

    def offer(self, ts: str | None) -> None:
        if ts and ts != self.want and ts != self.done:
            if self.want and self.want != self.done:
                self.skipped += 1
            self.want = ts
            self.wake.set()

    def run(self) -> None:
        while True:
            self.wake.wait()
            self.wake.clear()
            self.running = True
            try:
                while self.mail:
                    self.host.take(self.node, self.mail.popleft())
                ts = self.want
                if ts and ts != self.done:
                    self.done = ts
                    self.host.agent_step(self.node, ts)
            finally:
                self.running = False

    def busy(self) -> bool:
        """Still at work on what it was given: mail, or a step it hasn't finished."""
        return self.running or bool(self.mail) or bool(self.want and self.want != self.done)


class NodeHost(HostPeople, HomeNodes):
    sending, sent_wall, send_lock = 0, 0.0, threading.Lock()      # messages still leaving, and when the last one left: what the conductor waits for (cfg clock_waits)

    kind = "homes"
    port_key = "host_port"
    alarm_unsaved: dict[str, dict[str, Any]] = {}         # node -> what's waiting for the disk beside its alarm. Its own dict in __init__

    def __init__(self, limit: int | None = None):
        self.cfg = c = config.load()
        roster = self.roster()[:limit]
        tokens = json.loads((config.CONFIG_DIR / "secrets" / "host_tokens.json").read_text())
        self.community_pub = signing.public_hex(signing.load_or_create(config.CONFIG_DIR / "secrets" / "signing.key")) \
            if c.get("role") == "community" else None
        self.events = deque(maxlen=500)
        self.town_in: deque = deque(maxlen=4000)        # s from the sender making a message to a home here claiming it
        self.checks = self.claims = 0                     # Town notify checks and claims made (polling load on Town)
        self.seen: dict[str, dict[str, str]] = {}         # node -> the message ids it has finished, oldest first, and the status each came to. In memory: a new process starts with none
        self.taking: dict[str, dict[str, str]] = {}       # node -> the message ids it's still working on, and the fence of the last hand-out. Never saved: a process that dies drops them, so Town hands them out again and they run
        self.mail_lock = threading.Lock()                 # the poll thread and a thinker both move ids between those two
        self.repeats = 0                                  # messages Town handed out again and nobody acted on
        self.dropped = 0                                  # messages Town refused because their id held another message: /health shows it
        self.alarm_unsaved = {}
        self.kept = set(c.get("kept_days") or ())         # days a node doesn't step on: cfg kept_days, the benchmark's
        self.kept_passes = 0
        self.started = time.time()
        self.ready = False                                # the first pass over the nodes is over. Until then a reset waits on each node in turn, and at full size the first pass takes
                                                          # minutes, far past /demo/start's 20 s call to this host. /health says it, and whatever starts an evening waits for it
        self.pool = ThreadPoolExecutor(max_workers=int(c.get("send_workers", 8)))
        self.homes: dict[str, MemberNode] = {}
        self.towns: dict[str, TownSession] = {}
        self.locks: dict[str, NodeLock] = {}
        self.entries: dict[str, dict[str, Any]] = {}
        self.tick_s: deque = deque(maxlen=120)           # how long each pass over the nodes took, s
        self.tick_worst = 0.0                             # a sale's steps solve every home's plan: this must stay under a step
        self.busy_passes = 0                              # a node skipped in a pass because it was busy: it catches up next pass
        self.ticked: str | None = None                    # the step every node ticked at in the last whole pass: what the conductor waits for (cfg clock_waits)
        self.keydir = config.CONFIG_DIR / "fleet" / "keys"
        self.keydir.mkdir(parents=True, exist_ok=True)
        # one client for every session: each client holds a TLS context of its own
        self.http = httpx.Client(base_url=c["town_url"].rstrip("/"), timeout=40.0, limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))
        for h in roster:
            name = h["name"]
            town = TownSession(c["town_url"], c["town_run_id"], name, tokens[name], http=self.http)
            self.towns[name] = town
            self.locks[name] = NodeLock()
            self.entries[name] = h
            self.homes[name] = self.make_node(h, lambda to, k, body, mid, t=town: self._send(t, to, k, body, mid))
        # thinking nodes
        self.mind: SharedModel | None = None
        self.agents: dict[str, Any] = {}
        self.channels: dict[str, Any] = {}                # a person's channel to each node, made on first use
        self.thinkers: dict[str, Thinker] = {}
        self.decisions: dict[str, deque] = {}
        self.logs: dict[str, Any] = {}
        think = self.thinking() if c.get("llm_enabled") else []
        if think:
            self.mind = SharedModel(c)
            self.version = record.model_version(self.mind.client.model, self.mind.client.url)
            for name in think:
                try:
                    self.decisions[name] = deque(maxlen=KEEP_DECISIONS)
                    self.logs[name] = record.Log(name, config.state_dir() / "decisions" / f"{name}.jsonl")
                    self.attach_agent(name)
                    self.thinkers[name] = Thinker(self, name)
                except Exception:                         # noqa: BLE001  one node's damaged record must not stop the other 199. It runs on code, as a node with no agent does, and the log says why
                    log.exception("%s agent", name)
                    self.homes[name].agent = self.homes[name].brain = None
                    for held in (self.decisions, self.logs, self.agents):
                        held.pop(name, None)
            log.info("%d thinking nodes on %s: %s", len(self.thinkers), self.mind.client.url, sorted(self.thinkers))


    def agent_step(self, name: str, ts: str) -> None:
        agent = self.agents.get(name)
        if agent is None:
            return
        with self.locks[name]:
            try:
                agent.step(ts)
            except Exception as exc:                      # the controller carries on without the agent
                log.exception("%s agent step", name)
                self.events.append({"at": time.time(), "home": name, "kind": "agent_error", "ts": ts, "error": str(exc)[:200]})

    def _send(self, town: TownSession, to: str, kind: str, body: dict[str, Any], mid: str) -> Future:
        """Sends go through a small pool so 200 homes reporting the same slot do not queue behind each other. The
        future tells the home whether the send went through: a meter reading is marked reported only then, and is
        sent again on the next tick if it failed (node/home_delivery.py _mark_reported). With two buyers each owns a copy of the meter, so
        a reading goes to both, the same signed body. Nobody sends anything else again by itself, and a live bus fails a few sends in bursts,
        so it retries here, under the same id: Town answers the same envelope as a replay."""
        buyers = self.cfg.get("buyers") or []
        m = body.get("message") or {}

        def run(dest: str, message_id: str, tries: int = 0):
            try:
                return go(dest, message_id, tries)
            finally:
                self._went(-1)

        def go(dest: str, message_id: str, tries: int = 0):
            try:
                out = town.send(dest, kind, body, message_id)
            except Exception as exc:
                self.events.append({"at": time.time(), "home": town.name, "kind": "send_error", "to": dest,
                                    "message_kind": kind, "error": str(exc)[:200]})
                log.warning("%s: %s to %s failed, try %d: %s", town.name, kind, dest, tries + 1, str(exc)[:160])
                if ("performance" not in m or dest != to) and tries < len(RETRY_S):
                    self._went(1)
                    t = threading.Timer(RETRY_S[tries], lambda: self.pool.submit(run, dest, message_id, tries + 1))
                    t.daemon = True
                    t.start()
                raise
            if isinstance(out, dict) and out.get("duplicate"):     # a retry here is the same envelope, which Town answers as a replay: this one went nowhere
                self.dropped += 1
                self.events.append({"at": time.time(), "home": town.name, "kind": "send_dropped", "to": dest, "message_kind": kind, "message_id": message_id})
                log.error("Town refused %s from %s to %s: id %s holds another message", kind, town.name, dest, message_id)
            return out
        if to in buyers and ("performance" in m or "batch" in m):
            for b in buyers:
                if b != to:
                    self._went(1)
                    self.pool.submit(run, b, f"{mid}:{b}")
        if "batch" in m:              # report_rule.Outbox gives its one envelope the same id for every receiver, and Town takes an id once
            mid = f"{mid}:{to}"
        self._went(1)
        return self.pool.submit(run, to, mid)

    def _went(self, n: int) -> None:
        with self.send_lock:
            self.sending += n
            self.sent_wall = time.time()

    def trusted(self) -> list[str]:
        keys = list(config.load().get("community_pubkeys") or [])
        return keys + ([self.community_pub] if self.community_pub else [])

    def _logger(self, name: str):
        shown = name == self.cfg.get("log_node")        # this node's steps go to the service's log too

        def f(kind: str, **d):
            self.events.append({"at": time.time(), "home": name, "kind": kind, **d})
            if shown:
                log.info("%s %s %s", name, kind, json.dumps(d, default=str)[:400])
        return f

    def configure_clock(self, only: str | None = None, **kw) -> dict[str, Any]:
        out = None
        for name, h in self.homes.items():
            if only and name != only:
                continue
            r = h.replay
            r.configure(kw.get("start", r.start), float(kw.get("step_seconds", r.step_seconds)),
                        int(kw.get("loop_days", r.loop_days)), kw.get("at"), kw.get("at_wall"), hold=bool(kw.get("hold")))
            if not kw.get("keep"):        # a new run starts each home afresh; a change of speed (keep) goes on with it
                h.adapter.idx = None
            out = r.clock()
        return out or {}

    def reset(self, only: str | None = None) -> None:
        for name, h in self.homes.items():
            if only and name != only:
                continue
            with self.locks[name]:
                h.reset()                                 # its play too: nothing it sends in the new run names a message of the last one
                self.channels.pop(name, None)
                if hasattr(h, "outbox"):                              # QuietNode: last run's readings don't go out in this one
                    h.outbox.held.clear()
                    h.outbox.first = None
                if name in self.thinkers:
                    self.attach_agent(name)
                    self.thinkers[name].want = self.thinkers[name].done = None
                    ctx = getattr(self.agents[name], "ctx", None)
                    if ctx is not None:                       # the same days again: its log must not answer "done already"
                        ctx.new_run(keep_alarm=True)          # this door is unsigned, so an alarm stays on through it


    def tick_loop(self) -> None:
        while True:
            t0 = time.time()
            if self.held():
                self.kept_passes += 1
                self.ready = True                         # no node steps on a kept day, so there's no pass to wait for
                time.sleep(1.0)
                continue
            whole = True
            for name, h in list(self.homes.items()):
                lock = self.locks[name]
                if not lock.try_enter():
                    self.busy_passes += 1
                    whole = False
                    continue
                try:
                    h.tick()
                except Exception as exc:
                    self.events.append({"at": time.time(), "home": name, "kind": "tick_error", "error": str(exc)[:200]})
                finally:
                    lock.leave()
                th = self.thinkers.get(name)
                if th is not None:
                    th.offer((h.adapter.tel or {}).get("ts"))
            for name in list(self.alarm_unsaved):
                self.alarm_kept(name)
            seen = {(h.adapter.tel or {}).get("ts") for h in self.homes.values()}
            self.ticked = next(iter(seen)) if whole and len(seen) == 1 else None
            self.ready = True
            d = round(time.time() - t0, 3)
            self.tick_s.append(d)
            self.tick_worst = max(self.tick_worst, d)
            time.sleep(max(0.2, 1.0 - (time.time() - t0)))

    def take(self, name: str, msg: dict[str, Any]) -> None:
        """One claimed message: handled under the node's lock, then acknowledged."""
        town, h = self.towns[name], self.homes[name]
        with self.locks[name]:
            try:
                note = h.handle(msg.get("kind", ""), msg.get("from"), msg.get("body") or {})
            except Exception as exc:
                note = beckn.Refused(f"error: {exc}")
                log.exception("%s handle", name)
            status, said = beckn.ack_of(note)
            fence = self._done(name, msg, status)         # a repeat of it says the same: _repeat
        try:
            town.ack(msg["message_id"], fence, status, said)
        except Exception as exc:                          # Town hands it out again after its lease; the answer is kept
            self.events.append({"at": time.time(), "home": name, "kind": "town_error", "error": f"ack: {str(exc)[:160]}"})

    def _done(self, name: str, msg: dict[str, Any], status: str) -> str:
        """This message is finished: it's seen now, and not before. Returns the fence of its last hand-out, the one Town will take an ack on."""
        mid = msg["message_id"]
        with self.mail_lock:
            seen = self.seen.setdefault(name, {})
            seen[mid] = status
            if len(seen) > KEEP_SEEN:
                seen.pop(next(iter(seen)))
            return self.taking.setdefault(name, {}).pop(mid, None) or msg.get("fence")

    def _repeat(self, name: str, msg: dict[str, Any]) -> bool:
        """True for a message that is not to be acted on now. Town delivers at least once, and hands a message out again when its lease runs out. A thinking node finishes a message
        only after the model answers, so that is usual here: with a real model a commitment can be answered twice, and an rt_dispatch handled twice would add its kW twice.
        Finished, the copy is acknowledged with its new fence, so Town stops. It says what the first one came to, so a message refused and handed out again is on Town's record as refused.
        Still in the mail, it's left alone. Town keeps it until the work is done, because a kill here would lose the mail, and only this new fence can acknowledge it then."""
        mid = msg.get("message_id")
        with self.mail_lock:
            seen, taking = self.seen.setdefault(name, {}), self.taking.setdefault(name, {})
            done, working, said = mid in seen, mid in taking, seen.get(mid)
            if not done:
                taking[mid] = msg.get("fence")
            if not done and not working:
                return False
            self.repeats += 1
        if done:
            try:
                self.towns[name].ack(mid, msg["fence"], said or "processed", {"note": "a repeat: already taken"})
            except Exception as exc:                      # it comes back once more, and is acknowledged then
                self.events.append({"at": time.time(), "home": name, "kind": "town_error", "error": f"ack: {str(exc)[:160]}"})
        return True

    def _drain(self, name: str) -> int:
        """Claims until the inbox is empty; returns the messages handled. A thinking home takes its mail on its own thread,
        because an offer may wait on the model and this thread serves other homes too."""
        town, th = self.towns[name], self.thinkers.get(name)
        n = 0
        while True:
            msg = town.claim()
            self.claims += 1
            if not msg:
                return n
            n += 1
            if self._repeat(name, msg):
                continue
            sent = ((msg.get("body") or {}).get("context") or {}).get("sentWall")
            if isinstance(sent, (int, float)):
                self.town_in.append(max(0.0, time.time() - sent))
            if th is not None:
                th.post(msg)
            else:
                self.take(name, msg)
                if msg["message_id"] in self.taking.get(name, ()):      # a take that left it unfinished: back here, it's finished
                    self._done(name, msg, "processed")

    def poll_loop(self, names: list[str]) -> None:
        """One worker polls a share of the homes' inboxes in turn (a quick, non-blocking check each), instead of 200
        long-polls held open at once: a bus server may re-check each open long-poll every few milliseconds inside a write
        transaction (a scan of its whole notifications table), and record every request, so polling load is the bus's
        load. A home is checked every `host_poll_seconds` (5 s) for a minute after it last got mail, every
        `host_poll_idle_seconds` (15 s) otherwise: a call for offers waits at most 15 s (1.25 steps at 12 s a step;
        offers are due 6 replay hours later), and 200 idle homes cost Town 13 checks a second."""
        every = float(self.cfg.get("host_poll_seconds", 5.0))
        idle = float(self.cfg.get("host_poll_idle_seconds", 15.0))
        sweep = float(self.cfg.get("host_sweep_seconds", 60.0))   # a hint is only a wake-up call: a claim pass this often anyway, as InboxPoller's sweep
        last_mail = dict.fromkeys(names, 0.0)
        swept = dict.fromkeys(names, 0.0)                          # 0: a first pass at once, for what came while this process was away
        due = {n: time.time() + k * idle / max(1, len(names)) for k, n in enumerate(names)}   # spread the checks
        while True:
            t0 = time.time()
            for name in names:
                if t0 < due[name]:
                    continue
                try:
                    self.checks += 1
                    # Town keeps a message until it's acknowledged, but it wakes a receiver once. Waiting for a hint alone would leave a message whose hint was lost, or
                    # one handed out again after a claim that was never acknowledged (a node that died), in the inbox until the next message came
                    if self.towns[name].notify(wait=0) or t0 - swept[name] >= sweep:
                        swept[name] = t0
                        if self._drain(name):
                            last_mail[name] = time.time()
                except Exception as exc:
                    swept[name] = 0.0                              # the check may have used up a hint: a pass on the next round
                    self.events.append({"at": time.time(), "home": name, "kind": "town_error", "error": str(exc)[:200]})
                due[name] = time.time() + (every if time.time() - last_mail[name] < 60.0 else idle)
            time.sleep(max(0.2, min(due.values()) - time.time()))

    def join_all(self) -> None:
        """Joined one after another, in the background: the status API stays up while Town is away, and a session that
        didn't join here joins at its first call."""
        for name, t in self.towns.items():
            try:
                t.join()
            except Exception as exc:
                self.events.append({"at": time.time(), "home": name, "kind": "town_error", "error": f"join: {str(exc)[:160]}"})
            time.sleep(0.02)

    def warm(self) -> None:
        """Makes each home's trained forecaster now, not at the first call for offers, so the host's real memory shows at the start and
        200 homes aren't all building one while offers are due. It reads no more than the first offer would, and changes no result.
        It holds no node's lock: a reset waiting behind this would take over 20 s at full size, past what /demo/start waits for this host.
        A step that gets there first builds its own, and one of the two stays."""
        if self.kind != "homes" or self.cfg.get("forecast") not in TRAINED:
            return
        for name, h in self.homes.items():
            try:
                h._models()
            except Exception as exc:                          # the home's own forecast path reports it and falls back
                self.events.append({"at": time.time(), "home": name, "kind": "forecast_error", "error": str(exc)[:200]})

    def start(self) -> None:
        threading.Thread(target=self.warm, daemon=True, name="warm").start()
        threading.Thread(target=self.join_all, daemon=True, name="town-join").start()
        threading.Thread(target=self.tick_loop, daemon=True, name="tick").start()
        for th in self.thinkers.values():
            th.start()
        names = list(self.homes)
        workers = min(len(names), max(1, int(self.cfg.get("host_poll_workers", 8))))
        for k in range(workers):
            threading.Thread(target=self.poll_loop, args=(names[k::workers],), daemon=True, name=f"poll-{k}").start()
        log.info("%d %s running", len(self.homes), self.kind)

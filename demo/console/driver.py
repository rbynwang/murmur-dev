"""The console's driver: it plays an evening on a running stack and keeps the live log, one pass every quarter of a second.

A pass reads the conductor (through the runner's Evening.look, which also answers the configuration's gates and holds the clock
once the money is final), takes one queued command, posts a waiting surprise once the clock stands, reads what the network said
(the bus, the sale, the followed nodes' rows, the meter, its own posts) into the story, and tells the log the clock and the pins.

The clock runs as fast as the network finishes a step (pace 0, leaping over empty quarter-hours). The screen sets the pace: each
moment the story gives out is owed its dwell on screen at the presenter's speed, and while more is owed than one dwell ahead the
clock is held once its step is finished, so the network runs no further ahead of the screen than that. At speed max, and while a
run to a chosen time is under way, nothing is owed. A presenter's Hold holds the clock as well, and Step plays one move.

A console started for an audience also takes the viewers' taps (crowd.py): the first is posted as the presenter's surprise of that
kind would be, with every field at its default, and the votes of a cooldown choose the next.

A looping console (`days`, see days.py) plays one evening after the other with nobody at it: a settled evening's summary stands
12 seconds, then the next evening starts at the speed the last one had, on the same network or on the next day's. An evening that did not start or
did not settle is followed by the next after 30 seconds, and so is one whose clock stood unmoved for 15 minutes.
"""
from __future__ import annotations

import math
import queue
import statistics
import threading
import time
from types import SimpleNamespace
from typing import Any

from . import commands, settings, surprises
from . import crowd as C
from . import timeline as T
from .intake import Intake
from .parts import Clean, Played

PASS_S = 0.25
OWED = 1.1                       # a moment is owed this many dwells of screen time
REST_S, RETRY_S = 12.0, 30.0     # a looping console: how long a settled evening stands before the next, and one that failed
STALL_S = 900.0                  # and how long a running evening's clock may stand unmoved before the next is started
LOOP_SPEED = "4"                 # the speed a console plays at until it is given another, evening after evening: 2 seconds a moment,
                                 # which shows a whole evening to a room in about two minutes (speed 1 is the replay's own reading pace)


class Driver:
    def __init__(self, s: Any, k: Any, log: Any, net: dict[str, Any], say: Any = print, follow: list[str] | None = None):
        self.log, self.net, self.say, self.named = log, net, say, follow
        self.day(s, k)
        self.todo: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.play, self.busy, self.error, self.warn, self.link = "idle", None, None, None, None
        self.speed, self.presenter, self.fast, self.target = LOOP_SPEED, False, False, None
        self.run, self.e, self.parts, self.intake = 0, None, None, None
        self.view: dict[str, Any] = {}
        self.posted_hold: bool | None = None
        self.owed, self.waiting, self.pins_more, self.stops_more = 0.0, None, [], set()
        self.later: list[dict[str, Any]] = []            # surprises that came while one was waiting, in their order
        self.other: dict[str, Any] = {}
        self.crowd = C.Crowd()                           # the audience's door: shut unless the console is started for one (crowd.on)
        self.days: Any = None                            # a looping console's days (days.Days, or whatever has its now() and turn())
        self.rest: float | None = None                   # the wall time the next evening starts at, while one that ended stands
        self.mark, self.moved = None, time.time()

    def day(self, s: Any, k: Any) -> None:
        """The evening this console plays and the stack it plays it on: at its making, and at each turn of a looping console."""
        self.s, self.k = s, k
        self.timeline = T.build(s.evening, s.events, s.sites)
        self.follow, self.alias = settings.follow_of(s, self.named), settings.alias_of(s)
        self.facts_live = settings.facts_of(s, self.follow)
        self.roster: dict[str, Any] = {"homes": [], "buildings": [], "buyers": list(s.buyers)}

    # ------------------------------------------------------------------ what the door asks (server.py)
    def facts(self) -> dict[str, Any]:
        return {"play": self.play, "now": self.view.get("now"), "span": [self.timeline.first, self.timeline.last], "roster": self.roster,
                "follow": {"home": next((x for x in self.follow if x.startswith("home-")), None),
                           "building": next((x for x in self.follow if x.startswith("building-")), None)}}

    def do(self, c: dict[str, Any]) -> str | None:
        """Queues a checked command for the next pass; nothing a command asks is refused here."""
        self.todo.put(c)
        return None

    def state(self) -> dict[str, Any]:
        v = self.view
        return {"schema": "murmur.console.v1", "play": self.play, "busy": self.busy, "error": self.error, "warn": self.warn, "link": self.link,
                "run": self.run, "clock": v.get("now"), "at_gate": v.get("at_gate"), "target": self.target,
                "phase": self.intake.phase if self.intake else None, "speed": self.speed, "hold": self.presenter,
                "net": {"key": self.net["key"], "label": settings.NETS.get(self.net["key"], ""), "where": self.net.get("where", "")},
                "other": self.other, "peer": self.net.get("peer"), "ready": {"ts": self.ready(), "holds": self.play == "held"},
                "roster": self.roster, "surprises": list(commands.KINDS)}

    def tap(self, kind: str, viewer: str, address: str) -> str:
        """A viewer's tap on a preset (the door's POST /live/surprise): one of crowd's five words."""
        did = self.crowd.tap(kind, viewer, address)
        if did == C.FIRE and not self.fire(kind):
            self.crowd.unfire()
            return C.CLOSED
        return did

    def fire(self, kind: str) -> bool:
        """Queues the audience's surprise of a kind, every field at its default. False when this network does not take it now."""
        c, _ = commands.check({"do": "surprise", "kind": kind}, self.facts())
        if c is not None:
            self.todo.put(c)
        return c is not None

    def ready(self) -> str:
        """Where a presenter's network waits, ready: an hour before the window."""
        return next(self.timeline.ts(p["tq"]) for p in self.timeline.pins if p["id"] == "before")

    # ------------------------------------------------------------------ the loop
    def loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            t = time.time()
            try:
                self.once()
            except Exception as exc:                       # a part that stopped answering: the console says which, and goes on asking
                self.error = commands.say("no_answer", "community")
                self.say(f"pass failed: {type(exc).__name__}: {str(exc)[:200]}")
            stop.wait(max(0.0, PASS_S - (time.time() - t)))

    def once(self) -> None:
        try:
            c = self.todo.get_nowait()
        except queue.Empty:
            c = None
        if c is not None and c["do"] == "start":
            return self.start(c.get("run_to"))
        if self.e is None:
            self.show()
            return self.log.set({"state": "idle", "speed": self.speed}, None) if self.log.run is not None else None
        if self.again():
            return
        ended = self.e.look()
        self.view = v = self.e.clock
        if c is not None:
            self.command(c)
        if ended and self.play != "settled":
            self.play = "settled" if ended.startswith("settled") else "failed"
            self.warn = None if self.play == "settled" else commands.say("not_settled")
            self.presenter = True
        voted = self.crowd.due()
        if voted and not self.fire(voted):
            self.crowd.unfire()
        self.surprise()
        self.read(v)
        self.hold(v)
        self.tell(v)
        self.stall(v)
        self.show()

    def start(self, run_to: str | None) -> None:
        self.play, self.busy, self.error, self.warn = "starting", commands.say("starting"), None, None
        if self.e is not None:
            self.e.halt.set()
        self.e = e = Played(self.k, say=self.say)
        e.more_stops = sorted(set(self.timeline.stops) | self.stops_more)
        self.parts = Clean(e, self.follow)
        self.run += 1
        self.intake = Intake(self.facts_live, self.follow, self.alias, self.log)
        self.log.reset(self.run, self.net, self.timeline)
        self.presenter, self.fast, self.target, self.posted_hold, self.owed, self.pins_more = False, False, None, None, 0.0, []
        self.rest, self.mark, self.moved, self.crowd.open = None, None, time.time(), False
        try:
            self.roster = settings.roster_of(self.s, self.alias, e.get("homes", "/telemetry"))
            ready = {**self.facts(), "play": "running"}
            self.crowd.reset([p for p in C.PRESETS if commands.check({"do": "surprise", "kind": p}, ready)[0]])
            if self.k is not None and "bus" in getattr(self.k, "url", {}):
                try:
                    e.http.post(self.k.url["bus"] + f"/runs/{self.s.run}/reset", json={})
                except Exception:
                    pass
            e.start()
        except Exception as exc:
            self.play, self.busy, self.error = "failed", None, commands.say("no_start")
            self.say(f"start failed: {type(exc).__name__}: {str(exc)[:200]}")
            return
        if run_to:
            self.parts.conduct(run_to=run_to)
            self.fast, self.target = True, run_to
        self.play, self.busy = "running", None

    def command(self, c: dict[str, Any]) -> None:
        do = c["do"]
        if do == "hold":
            self.presenter = True
        elif do == "go":
            self.presenter, self.play = False, "running" if self.play == "held" else self.play
        elif do == "step":
            self.parts.conduct(step=1)
            self.posted_hold = None                        # the clock holds again by itself after its move
        elif do == "run_to":
            self.parts.conduct(run_to=c["ts"])
            self.presenter, self.fast, self.target, self.posted_hold = False, True, c["ts"], False
        elif do == "pace":
            self.speed = c["speed"]
        elif do == "surprise" and self.waiting is not None:
            self.later.append(c)
        elif do == "surprise":
            self.waiting = c
            self.busy = commands.say("surprise_waits", word=c["kind"])

    # ------------------------------------------------------------------ a looping console
    def again(self) -> bool:
        """True in the pass the next evening is started in: the one that ended has stood its time."""
        if self.days is None or self.play not in ("settled", "failed"):
            self.rest = None
            return False
        if self.rest is None:
            self.rest = time.time() + (REST_S if self.play == "settled" else RETRY_S)
        if time.time() < self.rest:
            return False
        self.turn()
        return True

    def turn(self) -> None:
        """The next evening: on the next day's stack when the days give one, else on this one again."""
        self.rest, self.play, self.busy, self.crowd.open = None, "starting", commands.say("next_day"), False
        self.log.set({"state": "starting", "speed": self.speed}, None)
        self.show()
        try:
            new = self.days.turn()
        except Exception as exc:
            self.play, self.busy, self.error = "failed", None, commands.say("no_start")
            self.say(f"the next day did not start: {type(exc).__name__}: {str(exc)[:200]}")
            return
        if new is not None:
            if self.e is not None:
                self.e.halt.set()
            self.day(*new)
        self.waiting, self.later, self.stops_more = None, [], set()      # the speed stays as the console was given it
        self.start(None)

    def stall(self, v: dict[str, Any]) -> None:
        """A looping console has nobody to see a clock that stands: after 15 minutes unmoved the evening counts as failed."""
        mark = (v.get("now"), v.get("mode"))
        if mark != self.mark:
            self.mark, self.moved = mark, time.time()
        if self.days is not None and self.play == "running" and time.time() - self.moved > STALL_S:
            self.play, self.warn = "failed", commands.say("stalled")

    def show(self) -> None:
        """Once a pass, what a viewer's page is told beside the clock: the audience's door, and a looping console's day."""
        self.crowd.open = self.play in ("running", "held")
        loop = None
        if self.days is not None:
            loop = {**self.days.now(), "next_s": None if self.rest is None else max(0, math.ceil(self.rest - time.time()))}
        self.log.show(self.crowd.state(), loop)

    # ------------------------------------------------------------------ inside a pass
    def surprise(self) -> None:
        """A waiting surprise is posted once the clock stands, a quarter-hour ahead, with its stops and its pin."""
        c, v = self.waiting, self.view
        if c is None or v.get("mode") not in ("held", "at_gate", "ended"):
            return
        at = T.shift(v["now"], 15)
        hosts = ["homes"] + (["buildings"] if self.s.buildings else [])
        self.waiting = self.later.pop(0) if self.later else None
        self.busy = commands.say("surprise_waits", word=self.waiting["kind"]) if self.waiting else None
        try:
            for part, path, body in surprises.doors(c, at, hosts):
                self.parts.post(part, path, body)
                self.e.posts[-1].update(kind=c["kind"], who=c.get("who"), at=at, what="surprise")
        except Exception:
            self.warn = commands.say("not_posted", commands.ROLES["homes" if c["kind"] != "emergency" else "buyer"], commands.WORDS[c["kind"]])
            return
        self.stops_more |= set(surprises.stops(c, at))
        self.parts.conduct(stops=sorted((set(self.timeline.stops) | self.stops_more) & self.span()))
        self.pins_more.append({"tq": self.timeline.tq(at), "kind": "surprise", "id": c["kind"]})

    def span(self) -> set[str]:
        out, at = set(), self.timeline.first
        while at <= self.timeline.last:
            out.add(at)
            at = T.shift(at, 15)
        return out

    def read(self, v: dict[str, Any]) -> None:
        p, it = self.parts, self.intake
        bus, summary = p.bus(), p.summary()
        due, sale = it.triggers(bus, summary), it.sale_id(summary)
        snaps = [{"trigger": due, "event": p.snapshot(sale)}] if due and sale else []
        rows = {n: p.rows(n) for n in self.follow}
        q = it.take(SimpleNamespace(t=time.time(), conductor=v, bus=bus, reports={}, rows=rows, summary=summary, snapshots=snaps,
                                    meter=p.meter(), posts=p.posts()))
        dwell = commands.SPEEDS[self.speed] / 1000
        for _ in q:
            self.owed = max(self.owed, time.time()) + OWED * dwell
        if self.log.full:
            self.warn = commands.say("log_full")

    def floor_ms(self, v: dict[str, Any]) -> int:
        played = [int(x.get("wall_ms") or 0) for x in (v.get("played") or [])[-12:]]
        return int(statistics.median(played)) if played else 0

    def hold(self, v: dict[str, Any]) -> None:
        """Holds the clock while the screen is behind, a presenter holds, or a surprise waits; lets it go otherwise."""
        if self.target and v.get("now") == self.target and v.get("mode") in ("held", "at_gate"):
            self.fast, self.target, self.presenter = False, None, True
        if self.e.holding:                                  # the money is final: the clock stays held
            return
        dwell = commands.SPEEDS[self.speed] / 1000
        lead = max(dwell, self.floor_ms(v) / 1000)
        behind = not self.fast and self.speed != "max" and self.owed - time.time() > lead
        want = bool(self.presenter or self.waiting is not None or behind)
        if want != self.posted_hold and not (self.fast and not want and self.posted_hold is False):
            self.parts.conduct(hold=want)
            self.posted_hold = want
        if self.presenter and v.get("mode") in ("held", "at_gate"):
            self.play = "held" if self.play == "running" else self.play

    def tell(self, v: dict[str, Any]) -> None:
        mode = str(v.get("mode") or "idle")
        state = {"idle": "starting", "leaping": "leaping", "playing": "live", "waiting": "live", "ended": "settled"}.get(mode)
        if state is None:                                    # held or at a gate: the presenter's own hold, or the screen's pace
            state = "held" if self.presenter else "live"
        if self.play in ("settled", "failed"):
            state = self.play
        self.log.set({"state": state, "tq": self.timeline.tq(v["now"]) if v.get("now") else 0, "speed": self.speed,
                      "fast": self.fast or self.speed == "max", "waiting": len(v.get("waiting_on") or ()), "floor_ms": self.floor_ms(v),
                      "leaps": v.get("leaps") or [], "played": v.get("played") or []}, self.timeline.pins + self.pins_more)

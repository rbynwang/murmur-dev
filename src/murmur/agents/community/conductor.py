"""The community agent's waiting clock.

The waiting clock (cfg clock_waits): every participant's clock holds at a step until every one of them has caught up with it, no agent is still
deciding, nothing is still on its way over the bus, and nothing the market waits on is still to come (offers, a contract, commitments, a call's
answers, readings, settlement). Then all of them move together. Waits that don't change for clock_wait_idle_s let the clock go on, and that is
on the record. A runner may set gates: steps the clock stops before until it opens them.

A step that is played lasts its pace at least. With leaping on, the clock plays only the steps something is scheduled at (conductor_stops.py)
and moves over the empty quarter hours between them in one move, waiting there only until every participant has caught up; a run of leaps takes
as long as the participants need, and no longer. A clock that runs fast, leaping or at a pace under the participants' own step_seconds, also
gives every step it plays the time an inbox takes to be looked at, counted from the moment every participant had caught up: its pace no longer
covers that by itself. With leaping off and the pace the participants' own, every step is played, one after another, as it always was.

Three questions are kept apart, each a method of its own: is the step every clock holds finished (Conductor.finished), may the clocks move and
where to (Conductor.next_step, with ConductorStops.landing for a leap), and what a step waits on (conductor_waits.py). Conductor.step asks them
in that order and moves the clocks. What a driver asks, and what the clock says of itself, is conductor_asked.py.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Callable

import httpx

from murmur import config
from murmur.protocol import doors
from murmur.agents.community.conductor_asked import ConductorAsked
from murmur.agents.community.conductor_stops import ConductorStops
from murmur.agents.community.conductor_waits import WIRE_LOGS, ConductorWaits, once_more
from murmur.agents.community.service import CommunityAgent

log = logging.getLogger("murmur.community")
POLL_S = 0.05                  # between two looks at a step in hand (cfg clock_poll_s): how soon a finished step is seen
REST_S = 0.5                   # between two looks while nothing can move: before a start, at a gate, held, at the end of the data. A driver's word ends it at once


class Conductor(ConductorWaits, ConductorStops, ConductorAsked):
    """The waiting clock of one community agent. `c` is that agent: its cfg, its clock, its market, the participants its clock moves (targets)
    and its event log. The rest is what a test puts in place of the world: the wire logs to read, the HTTP calls (an httpx client's get and post),
    the wall clock, and the wait between two passes of the loop that sends the line again."""

    def __init__(self, c: CommunityAgent, wire_files: list[Path] | None = None, http: Any = None, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.c, self.wall, self.sleep = c, wall, sleep
        self.reach = http                                # None: one client of its own for every call, made at the first one
        self.wire_files = [config.log_dir() / f for f in WIRE_LOGS] if wire_files is None else wire_files
        self.cond: dict[str, Any] = {"since": 0.0, "waits": None, "changed": 0.0, "went_on": deque(maxlen=200), "steps": 0, "held_s": 0.0, "posting": False,
                                     "gates": set(), "at_gate": None, "unreached": set(),
                                     "started": False,           # an evening was started through this clock
                                     "stops": set(),             # steps the driver wants played
                                     "opened": set(),            # the step of each gate that was opened, and the step after it
                                     "unread": None,             # why the market's schedule could not be read, once that was told
                                     "pace": None, "leap": None,                  # what the driver set; None: the participants' step_seconds, cfg clock_leap
                                     "hold": False, "budget": None, "run_to": None,     # the driver holds the clock; moves left before it holds; the step it holds at
                                     "empty": False,             # the step in hand was reached by a leap and nothing is scheduled at it: no pace
                                     "came": None,               # the step the clocks moved from to the one in hand
                                     "heard": set(),             # participants not asked again in this step: caught up, or unable to say
                                     "seen": [],                 # what the step in hand has waited on so far: the first eight things
                                     "done": None,               # the wall time the step in hand was first found finished
                                     "caught": None,             # the wall time every participant was first found to have caught up with the step in hand
                                     "leaping": None,            # the leap whose landing has still to catch up
                                     "leaps": deque(maxlen=50), "played": deque(maxlen=50)}
        self.lock = threading.Lock()                     # one thing moves the clocks at a time: a start, a step, or sending the line again
        self.woken = threading.Event()                   # a driver's word, or the meter fed: the loop looks at once
        self.looping = False

    @property
    def http(self) -> Any:
        """What reaches the participants. One client for every call: a client made for each call builds a TLS context of its own each time, which
        costs more than the call, and the loop looks many times a second."""
        if self.reach is None:
            self.reach = httpx.Client()
        return self.reach

    def wake(self) -> None:
        """The loop's wait ends now."""
        self.woken.set()

    # ------------------------------------------------------------------ moving every clock
    def hold_all(self, j: int) -> None:
        """Every clock to step j, held there."""
        r, cond = self.c.clock, self.cond
        at = r.ts(j)
        body = {"start": at, "at": at, "at_wall": self.wall(), "step_seconds": float(r.step_seconds), "loop_days": 0, "keep": True, "hold": True}
        res: dict[str, Any] = {}

        def post(name: str, base: str) -> None:
            try:
                once_more(self.http.post, base + "/demo/clock", json=body, timeout=5, headers=doors.headers()).raise_for_status()
            except Exception as exc:                      # noqa: BLE001  it gets the line again from clock_again
                res[name] = f"not reached: {str(exc)[:80]}"
        cond["posting"] = True
        try:
            ths = [threading.Thread(target=post, args=kv, daemon=True) for kv in self.c.targets.items()]
            for t in ths:
                t.start()
            r.configure(at, float(r.step_seconds), 0, at, body["at_wall"], hold=True)
            for t in ths:
                t.join(6)
        finally:
            cond["posting"] = False
        if set(res) != cond["unreached"]:                 # once when it changes, not at every step
            self.c.event("clock_not_reached", sim=at, agents=res)
        cond["unreached"] = set(res)

    def clock_again(self) -> None:
        """A participant that restarted runs on its own configured clock again. Any participant on another line gets this one again."""
        r = self.c.clock
        wall0, step, i0, loop, held = r._line
        if r.at_wall is None or loop or self.cond.get("posting") or not self.lock.acquire(blocking=False):
            return
        try:
            at = r.ts(i0)
            for name, base in self.c.targets.items():
                try:
                    got = self.http.get(base + "/demo/clock", timeout=3).json()
                    if abs(float(got["at_wall"] or 0.0) - wall0) > 0.5 or abs(float(got["step_seconds"]) - step) > 1e-6 or bool(got.get("held")) != (held is not None) \
                            or (held is not None and got.get("now") != at):
                        self.http.post(base + "/demo/clock", timeout=3, headers=doors.headers(), json={"start": at, "at": at, "at_wall": wall0, "step_seconds": step, "loop_days": 0, "keep": True,
                                                                                                       **({"hold": True} if held is not None else {})}).raise_for_status()
                        self.c.event("clock_sent_again", agent=name, was=got.get("now"), now=r.ts(r.current()))
                except (httpx.HTTPError, KeyError, TypeError, ValueError):
                    continue
        finally:
            self.lock.release()

    # ------------------------------------------------------------------ one step
    def tick(self) -> bool:
        """One pass of the clock's loop: True when the clocks moved. Nothing while the clock doesn't wait (cfg clock_waits), or while a start is
        moving every clock."""
        if not self.c.cfg.get("clock_waits") or not self.lock.acquire(blocking=False):
            return False
        try:
            return self.step()
        finally:
            self.lock.release()

    def step(self) -> bool:
        """Looks at the step every clock holds: once it is finished, and the clocks may move, all of them move together, in one move: to the next
        step, or, leaping, over the empty quarter hours to where the leap lands. True when they moved."""
        r, cond = self.c.clock, self.cond
        if r.at_wall is None or r.loop_days or not r.held or self.wall() < cond["since"]:
            return False
        i = r.current()
        if i >= len(r.rows) - 1:                          # the last step of the data: none follows. A leap that landed on it is seen to its landing, for the record
            if cond["leaping"] is not None:
                self.finished(i)
            return False
        t = self.finished(i)
        if t is None:
            return False
        j = self.next_step(i)
        if j is None:
            return False
        empty = self.leap and self.why_stop(j) is None    # where the clocks land: a step to play, or one more of the empty stretch
        cond["held_s"] += max(0.0, t - cond["since"] - (0.0 if cond["empty"] else self.pace()))
        cond["steps"] += j - i
        left, to = cond["budget"], cond["run_to"]         # read once: a driver's word may change them while this look runs
        if left is not None:                              # the driver asked for a number of steps: this move is one of them, however far it goes
            cond["budget"] = left - 1 if left > 1 else None
            cond["hold"] = cond["hold"] or left <= 1      # the step the clocks now move to is the last: it is played, and the clock holds there
        if to and r.ts(j) >= to:
            cond["hold"], cond["run_to"] = True, None      # arrived
        leap = {"from": r.ts(i), "to": r.ts(j), "steps": j - i, "wall": self.wall()} if empty or j > i + 1 else None
        self.hold_all(j)
        cond.update(since=self.wall(), waits=None, changed=0.0, empty=empty, came=i, heard=set(), seen=[], done=None, caught=None, leaping=leap,
                    opened={x for x in set(cond["opened"]) if x >= r.ts(j)})
        return True

    def finished(self, i: int) -> float | None:
        """Is step i finished? The wall time at which it was found finished, or None while it is not. A step that is played is finished once its
        pace has passed and nothing is waited on: no participant that has still to catch up, no node service, no message on its way, nothing
        the market needs. An empty step a leap landed on waits for the same, and for no pace. Waits that stand unchanged for clock_wait_idle_s
        finish it too, and that goes on the record (went_on, and the event clock_went_on). A clock that runs fast (ConductorAsked.quick) asks the
        participants how far they are from a step's first look on: the moment every one had caught up is when a leap has landed, and when the
        time an inbox needs begins to count (ConductorWaits.bus_waits)."""
        r, cond = self.c.clock, self.cond
        now_ts = r.ts(i)
        if cond["empty"]:
            with self.c.market.lock:                      # something came up at a step the clock leaped to, or the driver told it to leap no more: the step is played like any other
                cond["empty"] = self.leap and self.why_stop(i) is None
        early = not cond["empty"] and self.wall() < cond["since"] + self.pace()      # the pace: a played step lasts at least this long
        if early and (cond["caught"] is not None or not self.quick()):
            return None                                   # and nobody is asked before it has passed, unless the clock runs fast: then it must know when everyone had caught up
        nodes, caught_up = self.node_waits(now_ts)
        loops = self.loop_waits(i)
        if caught_up and not loops and cond["caught"] is None:
            cond["caught"] = self.wall()
            self.landed()
        if early:
            return None
        nodes += self.bus_waits(played=not cond["empty"])
        if not nodes:
            self.c.market.rt.settled = now_ts             # every node has done this step and what it sent is in: the desk can read the step's reports together
        waits = nodes + loops + self.market_waits(now_ts)
        t = self.wall()
        if tuple(waits) != (cond["waits"] or ()):
            cond["waits"], cond["changed"] = tuple(waits) or None, t
        if waits:
            cond["seen"] = (cond["seen"] + [w for w in waits if w not in cond["seen"]])[:8]
            if t - cond["changed"] < float(self.c.cfg.get("clock_wait_idle_s", 180)):
                return None
            cond["went_on"].append({"sim": now_ts, "wall": round(t, 1), "without": list(waits)[:8]})
            self.c.event("clock_went_on", sim=now_ts, waited_s=round(t - cond["since"], 1), without=list(waits)[:8])
        self.landed()
        if cond["done"] is None:
            cond["done"] = t
            if not cond["empty"]:
                cond["played"].append({"sim": now_ts, "wall_ms": round((t - cond["since"]) * 1000), "waited_on": list(cond["seen"])})
        return t

    def landed(self) -> None:
        """The leap the clocks last made has landed: every participant has caught up with the step it moved them to (or the clock went on without
        one). It goes on the record once (leaps, and the event clock_leap), with the wall time it took."""
        leap, self.cond["leaping"] = self.cond["leaping"], None
        if leap is not None:
            rec = {**{k: leap[k] for k in ("from", "to", "steps")}, "wall_ms": round((self.wall() - leap["wall"]) * 1000)}
            self.cond["leaps"].append(rec)
            self.c.event("clock_leap", **rec)

    def next_step(self, i: int) -> int | None:
        """Which step the clocks move to from step i. None while they may not move: the driver holds the clock, or the step after i is a gate (a
        runner posts what happens there before any node sees it, then opens the gate). Else the step after i; or, leaping, with that step empty,
        where a leap over the empty quarter hours lands (ConductorStops.landing)."""
        cond, nxt = self.cond, self.c.clock.ts(i + 1)
        if cond["hold"]:
            return None
        if nxt in cond["gates"]:
            cond["at_gate"] = nxt
            return None
        if not self.leap:
            return i + 1
        j = self.landing(i)                               # the step after i itself, when that one must be played
        return j if j > i else None

    # ------------------------------------------------------------------ the two loops
    def again_loop(self) -> None:
        """Every 20 s, for as long as the service runs: any participant that lost the line gets it again."""
        while True:
            self.sleep(20.0)
            self.clock_again()

    def nap(self) -> float:
        """How long the loop waits for its next look when nothing wakes it: to the end of a played step's pace; a short poll (cfg clock_poll_s)
        while a step in hand waits on the participants; longer while nothing can move."""
        r, cond = self.c.clock, self.cond
        if not self.c.cfg.get("clock_waits") or r.at_wall is None or not r.held or cond["done"] is not None \
                or (r.current() >= len(r.rows) - 1 and cond["leaping"] is None):
            return REST_S
        left = cond["since"] + (0.0 if cond["empty"] else self.pace()) - self.wall()
        if left > 0 and (cond["caught"] is not None or not self.quick()):      # a clock that runs fast asks at once how far the participants are, pace or no pace
            return min(REST_S, left)
        return max(0.01, min(1.0, float(self.c.cfg.get("clock_poll_s", POLL_S))))

    def pause(self, seconds: float) -> None:
        """The loop's wait between two looks: this long, or until it is woken."""
        self.woken.wait(seconds)

    def step_loop(self) -> None:
        """For as long as the service runs: one look at the step every clock holds, then a short wait that a driver's word ends at once. After a
        move there is no wait at all: the next look comes at once, so a run of leaps takes only as long as the participants need to catch up.
        A look that fails costs that look."""
        while True:
            self.woken.clear()                            # before the look: a word that comes while it runs ends the wait after it
            try:
                moved = self.tick()
            except Exception:
                log.debug("clock loop: %s", traceback.format_exc())
                moved = False
            if not moved:
                self.pause(self.nap())

    def start_loops(self) -> None:
        """Starts the two loops, each on a thread of its own, the first time it is called."""
        if self.looping:
            return
        self.looping = True
        threading.Thread(target=self.again_loop, daemon=True, name="clock-again").start()
        threading.Thread(target=self.step_loop, daemon=True, name="clock").start()

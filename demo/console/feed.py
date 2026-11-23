"""The console's log of one run, and what GET /live/state.json answers from it.

Without a valid ?since=N the answer is the runner's own state (murmur.live.v1), exactly as the read-only feed gives it. With one it
is the same keys and `v2`:

  {schema: "murmur.live.v2", run, since, next, more, every_ms, net: {key, boxes},
   clock: {state, tq, speed, dwell_ms, fast, waiting, floor_ms, leaps: [{from, to, ms}]},
   timeline: {t0, n, parts: [{id, from, to}], pins: [{tq, kind, id, state, jump}]},
   steps: [{i, tq, n, w, sd, b, l}], moments: [{q, tq, id, n, b, w, hero, tag, p, c, lit, s, tv, k}]}

and, only on a console that has them (show()):

   crowd: {open, presets: [ids], cooldown_s, votes: {id: n}, left, most, last: {kind, by, ago_s} | null}     the audience's door (crowd.py)
   loop: {day, days, date, label, next_s: n | null}     a looping console: which evening of how many, and the seconds to the next

The moments are those after N, in order, at most six and at most 200,000 characters of answer, but always the next one due; the
steps are exactly theirs. `next` is the cursor to ask with next, and `more` says that moments wait beyond it. A page that asks in
any split of cursors is given the same log. `run` rises with every reset: a page holding another run starts again from 0.

The driver fills the log: reset() at a start, add() for each moment the story closes with its steps (in the wire forms of
page_builder/live/wire.py: the log numbers them, a step's `i` from 0, a moment's `q` from 1 and its `s`), set() once a pass with
the clock and the pins, show() once a pass with the audience's door and the loop. Nothing taken ever changes. No call here raises on what a running network sent: what cannot be taken is
left out and counted in `faults` (form: not the wire's form; over: a moment over its cap; full: the run's log is full; set: a
clock or a pin outside the fixed lists). Only reset() refuses, with ValueError, a network or a timeline it cannot send.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from . import timeline as T
from .commands import KINDS, SPEEDS

SCHEMA = "murmur.live.v2"
STATES = ("idle", "starting", "leaping", "live", "held", "settled", "failed")
RUNNING = ("leaping", "live", "held")               # the states in which the clock can be run to a stop
NETS = ("one", "first", "standin", "standby", "rehearsal")
PIN_IDS = {"stop": T.STOPS, "surprise": KINDS}
ANSWER_MOMENTS, ANSWER_CHARS = 6, 200_000           # what one answer holds at most; the page refuses one over 262,144
MOMENT_CHARS, MOMENT_STEPS = 60_000, 24             # a moment with its steps, as the wire cuts it
RUN_MOMENTS, RUN_STEPS = 400, 3_000                 # what one run keeps
PARTS, PINS, LEAPS, BOXES = 8, 48, 24, 64
DWELL_MS, FLOOR_MS, LEAP_MS, WAITING = 20_000, 120_000, 3_600_000, 999
ROOM = 16                                           # characters an answer's own numbers may still grow by


def wire(x: Any) -> str:
    """A step or a moment as it travels: its JSON with no spaces, which is how the wire forms measure it. ValueError for a
    figure that is no number."""
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def text(answer: Any) -> str:
    """An answer as the door sends it: as the read-only feed writes it while it holds no v2, else with no spaces."""
    return json.dumps(answer, ensure_ascii=False, separators=(",", ":")) if isinstance(answer, dict) and "v2" in answer else json.dumps(answer)


def raw(sent: str) -> bytes:
    """The bytes of a text on its way out. Half of a character pair, which no UTF-8 holds, leaves as a question mark."""
    return sent.encode("utf-8", "replace")


def cursor(since: Any) -> int | None:
    """The N of ?since=N: a whole number from 0, in at most nine digits. None for anything else."""
    if isinstance(since, int) and not isinstance(since, bool):
        return since if 0 <= since < 10 ** 9 else None
    return int(since) if isinstance(since, str) and since.isascii() and since.isdigit() and len(since) <= 9 else None


def whole(x: Any, top: int) -> int | None:
    """A number as a whole one from 0 to top; None for anything that is no number."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")):
        return None
    return max(0, min(top, int(x)))


def rows(x: Any) -> Any:
    return x if isinstance(x, (list, tuple)) else ()


class Log:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.run: int | None = None                  # None before the first reset: the answer is v1 alone
        self.full = False                            # the run's log holds all it keeps: the console's `warn` says so
        self.faults = {"form": 0, "over": 0, "full": 0, "set": 0}
        self.more: dict[str, Any] = {}               # crowd and loop, as show() was last given them
        self.clock: dict[str, Any] = {"state": "idle", "tq": 0, "speed": "1", "dwell_ms": SPEEDS["1"], "fast": False, "waiting": 0,
                                      "floor_ms": 0, "leaps": []}

    # ------------------------------------------------------------------ a new run
    def reset(self, run: int, net: dict[str, Any], timeline: Any) -> None:
        """A new run: its number, the network ({key, boxes}: which one, and every map box of a part it runs) and the evening's
        timeline (timeline.build's, or the same as a dict). The log is emptied; the clock keeps its state, speed and floor."""
        try:
            t = timeline if isinstance(timeline, dict) else vars(timeline)
            parts = [{"id": p["id"], "from": whole(p["from"], T.TOP), "to": whole(p["to"], T.TOP)} for p in t["parts"]]
            line = {"t0": T.when(t["t0"]).strftime(T.FMT), "n": whole(t["n"], T.TOP), "parts": parts}
            boxes = list(net.get("boxes") or ())
            good = net["key"] in NETS and all(isinstance(b, str) for b in boxes) and len(parts) <= PARTS and line["n"] is not None \
                and all(p["id"] in T.PARTS and p["from"] is not None and p["to"] is not None for p in parts)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"no network or timeline to send: {type(exc).__name__}") from exc
        if not good:
            raise ValueError(f"the network is one of {NETS} with its boxes' ids, the timeline at most {PARTS} parts of {T.PARTS}")
        with self.lock:
            self.run, self.full, self.began = int(run), False, True
            self.net, self.line = {"key": net["key"], "boxes": boxes[:BOXES]}, line
            self.steps: list[dict[str, Any]] = []
            self.moments: list[dict[str, Any]] = []
            self.sizes: list[int] = []               # each moment with its steps, in bytes of an answer
            self.at: set[int] = set()                # the quarter-hours that hold a moment
            self.leaps: dict[tuple[int, int], int] = {}
            self.played: set[int] = set()
            self.clock = {**self.clock, "tq": 0, "waiting": 0, "leaps": []}
            self.marks = self.known(t.get("pins"))
            self.pins = T.marked(self.marks, 0, False)

    # ------------------------------------------------------------------ what the driver gives
    def add(self, steps: list[dict[str, Any]], moment: dict[str, Any]) -> int | None:
        """Takes one closed moment with its steps and numbers them. Its `q`, or None when it is not taken."""
        with self.lock:
            at = whole(moment.get("tq"), T.TOP) if isinstance(moment, dict) else None
            if self.run is None or at is None or at != moment["tq"] or not isinstance(steps, list) or not 1 <= len(steps) <= MOMENT_STEPS \
                    or not all(isinstance(s, dict) for s in steps):
                return self.fault("form")
            if self.full or len(self.moments) >= RUN_MOMENTS or len(self.steps) + len(steps) > RUN_STEPS:
                self.full = True                      # and nothing more is taken in this run
                return self.fault("full")
            i, q = len(self.steps), len(self.moments) + 1
            own = [{"i": i + k, **{a: b for a, b in s.items() if a != "i"}} for k, s in enumerate(steps)]
            own.append({"q": q, **{a: b for a, b in moment.items() if a not in ("q", "s")}, "s": list(range(i, i + len(steps)))})
            try:
                texts = [wire(x) for x in own]
                taken = [json.loads(t) for t in texts]   # the log's own copy: what was given may change, what was taken may not
            except (TypeError, ValueError, RecursionError):
                return self.fault("form")
            if sum(len(t) + 1 for t in texts) > MOMENT_CHARS:
                return self.fault("over")
            self.steps += taken[:-1]
            self.moments.append(taken[-1])
            self.sizes.append(sum(len(raw(t)) + 1 for t in texts))
            self.at.add(at)
            return q

    def set(self, clock: dict[str, Any], pins: list[dict[str, Any]] | None) -> None:
        """Once a pass: the clock and the pins. clock: {state, tq, speed, fast, waiting, floor_ms} and the conductor's `leaps` and
        `played` as it gives them (a time as a dataset time or in quarter-hours; a leap's wall time as `ms` or `wall_ms`); a
        `dwell_ms` only where it is not the speed's own. pins: [{tq, kind, id}], or None for those in hand. A value outside the
        fixed lists leaves the last good one standing.

        The pass a run begins in read the conductor before the start, so the first call after a reset still tells of the run
        before: of its clock only the state, the speed and the floor are taken, and the clock stands at 0 until the next call."""
        with self.lock:
            if self.run is None or not isinstance(clock, dict):
                return self.fault("set")
            old, state, speed = self.clock, clock.get("state"), clock.get("speed")
            if not isinstance(state, str) or state not in STATES:
                state = self.fault("set") or old["state"]
            if not isinstance(speed, str) or speed not in SPEEDS:
                speed = self.fault("set") or old["speed"]
            began, self.began = self.began, False
            now, waits = None if began else self.q(clock.get("tq")), 0 if began else clock.get("waiting")
            dwell, floor = whole(clock.get("dwell_ms"), DWELL_MS), whole(clock.get("floor_ms"), FLOOR_MS)
            for p in () if began else rows(clock.get("played")):
                at = self.q(p.get("sim") if isinstance(p, dict) else p)
                self.played |= set() if at is None else {at}
            for leap in () if began else rows(clock.get("leaps")):
                a, b = (self.q(leap.get(k)) for k in ("from", "to")) if isinstance(leap, dict) else (None, None)
                if a is not None and b is not None and a < b:
                    self.leaps[(a, b)] = whole(leap.get("ms", leap.get("wall_ms")), LEAP_MS) or 0
            self.clock = {"state": state, "tq": old["tq"] if now is None else now, "speed": speed,
                          "dwell_ms": SPEEDS[speed] if dwell is None else dwell, "fast": clock.get("fast") is True,
                          "waiting": whole(len(waits) if isinstance(waits, (list, tuple, set)) else waits, WAITING) or 0,
                          "floor_ms": old["floor_ms"] if floor is None else floor, "leaps": self.folds()}
            if pins is not None:
                self.marks = self.known(pins)
            self.pins = T.marked(self.marks, self.clock["tq"], state in RUNNING)

    def show(self, crowd: dict[str, Any] | None, loop: dict[str, Any] | None) -> None:
        """Once a pass: the audience's door (crowd.Crowd.state) and the loop (the driver's own), each None where the console has
        none. Both are the console's own words and counts, and leave as they are given."""
        with self.lock:
            self.more = {k: v for k, v in (("crowd", crowd), ("loop", loop)) if isinstance(v, dict)}

    # ------------------------------------------------------------------ inside
    def fault(self, kind: str) -> None:
        self.faults[kind] += 1

    def q(self, at: Any) -> int | None:
        """A time of the clock in quarter-hours, from a dataset time or from a count of them. None when it is neither."""
        try:
            return max(0, min(T.TOP, T.tq(at, self.line["t0"]))) if isinstance(at, str) else whole(at, T.TOP)
        except ValueError:
            return None

    def known(self, pins: Any) -> list[dict[str, Any]]:
        """The pins that may leave: a stop or a surprise of a known id at a quarter-hour of the timeline, each once, at most 48:
        the stops, and the newest surprises."""
        seen: dict[tuple[Any, ...], dict[str, Any]] = {}
        for p in rows(pins):
            kind, name = (p.get("kind"), p.get("id")) if isinstance(p, dict) else (None, None)
            at = whole(p.get("tq"), T.TOP) if isinstance(p, dict) else None
            if at is None or not isinstance(kind, str) or not isinstance(name, str) or name not in PIN_IDS.get(kind, ()):
                self.fault("set")
                continue
            seen[(at, kind, name)] = {"tq": at, "kind": kind, "id": name}
        stops = [p for p in seen.values() if p["kind"] == "stop"][:PINS]
        rest = [p for p in seen.values() if p["kind"] == "surprise"]
        return stops + rest[max(0, len(rest) - (PINS - len(stops))):]

    def folds(self) -> list[dict[str, int]]:
        """The run's leaps as the timeline folds them: two with no played quarter-hour and no moment between them are one, and
        beyond 24 the oldest are joined with their neighbours."""
        out: list[dict[str, int]] = []
        for (a, b), ms in sorted(self.leaps.items()):
            if out and out[-1]["to"] >= a and a not in self.played and a not in self.at:
                out[-1].update(to=max(b, out[-1]["to"]), ms=min(LEAP_MS, out[-1]["ms"] + ms))
            else:
                out.append({"from": a, "to": b, "ms": ms})
        while len(out) > LEAPS:
            gone = out.pop(1)
            out[0].update(to=max(gone["to"], out[0]["to"]), ms=min(LEAP_MS, out[0]["ms"] + gone["ms"]))
        return out

    def every(self) -> int:
        """How soon the page asks again, in ms: slowly before a start, fast when the moments are short."""
        return 2_000 if self.clock["state"] == "idle" else 250 if self.clock["dwell_ms"] <= 500 else 400

    # ------------------------------------------------------------------ what the door answers
    def answer(self, v1: Any, since: Any) -> Any:
        """The feed's answer: v1 itself without a valid `since` (the query's own text, or a number), else v1's keys and `v2`
        with the moments after it."""
        n = cursor(since)
        with self.lock:
            if n is None or self.run is None or not isinstance(v1, dict):
                return v1
            head = len(self.moments)
            v2 = {"schema": SCHEMA, "run": self.run, "since": n, "next": min(n, head), "more": False, "every_ms": self.every(),
                  "net": self.net, "clock": self.clock, "timeline": {**self.line, "pins": self.pins}, **self.more, "steps": [], "moments": []}
            room = ANSWER_CHARS - len(raw(text({**v1, "v2": v2}))) - ROOM
            k = n
            while k < head and k - n < ANSWER_MOMENTS and (k == n or self.sizes[k] <= room):
                room -= self.sizes[k]
                k += 1
            if k > n:
                due = self.moments[n:k]
                v2.update(next=k, more=k < head, moments=due, steps=self.steps[due[0]["s"][0]:due[-1]["s"][-1] + 1])
            return {**v1, "v2": v2}

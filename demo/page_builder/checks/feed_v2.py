"""Made-up answers in the feed's second form (murmur.live.v2), for the checks of the Live view: an evening that arrives moment
by moment, and a hostile one that breaks the form in every way hostile.json lists.

The evening is live_evening.json: twelve moments of the recorded evening in the feed's wire forms, with a timeline, six stops,
two leaps and a surprise. An answer is the first-form state plus "v2": the moments after the cursor asked (`since`), at most
six and 200,000 characters, with exactly their steps. A check decides how many moments have happened so far (`out`), lets more
arrive, starts a new run, or sets words of the clock. feed.py builds these and serves them.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
SCHEMA = "murmur.live.v2"
DWELL_MS = {"0.5": 16000, "1": 8000, "2": 4000, "4": 2000, "max": 0}      # a speed's dwell on each moment
RUNNING = ("leaping", "live", "held")  # the clock's states in which a console can run to a stop
MOST, ROOM = 6, 200_000                # an answer holds at most this many moments and characters
SPARE = 200                            # kept free in an answer for the commas between its moments and steps
FLOOR_MS = 1600                        # what the made-up network needs for a played quarter-hour
Entry = tuple[int, Any, list[Any]]     # one moment of the log: its quarter-hour, the moment, its steps


def wire(x: Any) -> str:
    """A value as it travels: its JSON with no spaces."""
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class Evening:
    """A made-up evening, answered by cursor.

    out: how many of its moments have happened; `arrive` lets more happen, one or a burst. run: rises with `new_run`, as at
    each Start; while it is 0 no run has begun, and every answer is the first form alone, as a console's is before its first
    Start. speed: one of DWELL_MS. clock: words a check sets over the clock this evening gives, such as
    {"state": "leaping"} or {"waiting": 3}. pins: surprise pins a check or the made-up console adds, [{tq, kind, id}].
    at: a quarter-hour the clock stands at beyond its last moment. asked: every cursor asked so far with its time,
    (since, seconds), since None for an ask without a valid cursor."""

    always_more = False

    def __init__(self, v1: Callable[[], dict], data: dict[str, Any], entries: list[Entry], out: int | None = None,
                 speed: str = "1", per: int = MOST):
        self.v1, self.data, self.entries, self.per = v1, data, entries, per
        self.out = len(entries) if out is None else max(0, min(out, len(entries)))
        self.run, self.speed, self.at = 1, speed, 0
        self.clock: dict[str, Any] = {}
        self.pins: list[dict[str, Any]] = []
        self.asked: list[tuple[int | None, float]] = []
        self.lock = threading.RLock()
        self.t0 = dt.datetime.fromisoformat(data["timeline"]["t0"])

    def arrive(self, n: int = 1) -> int:
        """Lets n more moments happen; gives how many have happened now."""
        with self.lock:
            self.out = max(0, min(self.out + n, len(self.entries)))
            return self.out

    def new_run(self, out: int = 0) -> int:
        """A new run, as a Start gives: `run` rises, and `out` moments of it have happened."""
        with self.lock:
            self.run, self.at, self.pins = self.run + 1, 0, []
            self.out = max(0, min(out, len(self.entries)))
            return self.run

    def tq(self) -> int:
        """The clock's quarter-hour: that of the last moment that has happened, or where the clock stands beyond it."""
        return max(self.entries[self.out - 1][0] if self.out else 0, self.at)

    def when(self, tq: int) -> str:
        """A quarter-hour as a dataset time, "2025-01-28 18:00"."""
        return (self.t0 + dt.timedelta(minutes=15 * tq)).strftime("%Y-%m-%d %H:%M")

    def clock_now(self) -> dict[str, Any]:
        tq = self.tq()
        state = "settled" if self.out == len(self.entries) else "live"
        return {"state": state, "tq": tq, "speed": self.speed, "dwell_ms": DWELL_MS[self.speed], "fast": self.speed == "max",
                "waiting": 0, "floor_ms": FLOOR_MS, "leaps": [x for x in self.data["leaps"] if x["to"] <= tq], **self.clock}

    def timeline(self, clock: dict[str, Any]) -> dict[str, Any]:
        """The timeline, each pin with its state by the clock: one the clock has reached is past, the first one after it is
        next, the others are ahead, and a stop ahead of a running clock may be run to. The evening's own surprise has its pin
        once its moment has happened."""
        tq, running, own = clock["tq"], clock["state"] in RUNNING, self.data.get("surprise")
        pins: list[dict[str, Any]] = []
        for p in sorted(self.data["timeline"]["pins"] + ([own["pin"]] if own and own["q"] <= self.out else []) + self.pins,
                        key=lambda p: p["tq"]):
            ahead = p["tq"] > tq
            state = "past" if not ahead else "ahead" if any(x["state"] != "past" for x in pins) else "next"
            pins.append({**p, "state": state, "jump": ahead and running and p["kind"] == "stop"})
        return {**self.data["timeline"], "pins": pins}

    def picked(self, since: int, room: int) -> list[int]:
        """Which moments an answer to `since` holds, by number: those after it that have happened, at most `per` and what
        `room` characters hold, and always the next one due."""
        qs: list[int] = []
        for q in range(since + 1, self.out + 1):
            room -= len(wire(self.entries[q - 1][1])) + len(wire(self.entries[q - 1][2]))
            if qs and (len(qs) >= self.per or room < 0):
                break
            qs.append(q)
        return qs

    def v2(self, since: int, room: int) -> dict[str, Any]:
        clock = self.clock_now()
        every = 2000 if clock["state"] == "idle" else 250 if clock["dwell_ms"] <= 500 else 400
        head = {"schema": SCHEMA, "run": self.run, "since": since, "next": min(since, self.out), "more": self.always_more,
                "every_ms": every, "net": self.data["net"], "clock": clock, "timeline": self.timeline(clock)}
        qs = self.picked(since, room - len(wire(head)) - SPARE)
        if qs:
            head.update(next=qs[-1], more=self.always_more or qs[-1] < self.out)
        return {**head, "steps": [s for q in qs for s in self.entries[q - 1][2]], "moments": [self.entries[q - 1][1] for q in qs]}

    def answer(self, since: int | None) -> dict[str, Any]:
        """One answer: the first-form state, its clock the evening's, and with a cursor the second form under "v2"."""
        with self.lock:
            self.asked.append((since, time.monotonic()))
            state = {**self.v1(), "clock": self.when(self.tq())}
            return state if since is None or not self.run else {**state, "v2": self.v2(since, ROOM - len(wire(state)))}

    def text(self, query: str = "") -> str:
        """The answer to an address's query, as text. A cursor is `since=N`, once, N a whole number from 0 in at most nine
        digits; anything else is none, and is answered in the first form alone, written as the first-form feeds write it."""
        asked = parse_qs(query, keep_blank_values=True).get("since") or []
        good = len(asked) == 1 and asked[0].isascii() and asked[0].isdigit() and len(asked[0]) <= 9
        a = self.answer(int(asked[0]) if good else None)
        return wire(a) if "v2" in a else json.dumps(a)


def evening(v1: Callable[[], dict], out: int | None = None, speed: str = "1") -> Evening:
    """The made-up evening of live_evening.json."""
    data = load("live_evening.json")
    return Evening(v1, data, [(m["tq"], m, [data["steps"][i] for i in m["s"]]) for m in data["moments"]], out, speed)


def put(root: Any, path: str, value: Any) -> Any:
    """`root` with `value` set at a dotted path ("k.cd.0.rows.*.1"); `*` is every item, and a part of the tree that an item
    under a `*` lacks is passed over. A path that names nothing else is a fault of the case, and raises."""
    def walk(node: Any, keys: list[str], loose: bool) -> Any:
        if not keys:
            return copy.deepcopy(value)
        k, rest = keys[0], keys[1:]
        if k == "*" and isinstance(node, (list, dict)):
            for at in (range(len(node)) if isinstance(node, list) else list(node)):
                node[at] = walk(node[at], rest, True)
            return node
        at: Any = int(k) if isinstance(node, list) and k.lstrip("-").isdigit() else k
        there = (isinstance(node, list) and isinstance(at, int) and -len(node) <= at < len(node)) or (isinstance(node, dict) and at in node)
        if there or (isinstance(node, dict) and not rest):
            node[at] = walk(node[at] if there else None, rest, loose)
        elif not loose:
            raise KeyError(f"{path}: nothing at {k!r}")
        return node
    return walk(root, path.split("."), False)


class Hostile(Evening):
    """The cases of hostile.json as one log: a good moment, then each case's moment (a copy of the good one with the case's
    values set) and a good one after it, all of them out from the start, at the speed "max". Every answer says there is
    more. A case's `answer` values are set once, in the first answer that holds its moment: asked again, the feed gives
    that answer clean.

    cases: each case as written, with "q", its moment's number, and "after", the number of the good moment behind it. Moments
    are called "case-NAME" and "after-NAME" by their ids, the first one "good-first"."""

    always_more = True

    def __init__(self, v1: Callable[[], dict], per: int = 1, only: str = ""):
        book, data = load("hostile.json"), load("live_evening.json")
        self.markup = book["markup"]
        self.good = next(m for m in data["moments"] if m["id"] == book["v2"]["from"])
        self.steps0 = [data["steps"][i] for i in self.good["s"]]
        self.cases: list[dict[str, Any]] = []
        self.once: dict[int, dict[str, Any]] = {}
        entries: list[Entry] = []
        self.add(entries, "good-first", self.good["n"], {})
        for case in book["v2"]["cases"]:
            if only in ("", case["name"]):
                q = self.add(entries, "case-" + case["name"], "Case: " + case["name"], case.get("set") or {})
                self.once[q] = case.get("answer") or {}
                self.cases.append({**case, "q": q, "after": self.add(entries, "after-" + case["name"], self.good["n"], {})})
        super().__init__(v1, {**data, "surprise": None}, entries, None, "max", per)
        self.clock["state"] = "live"                 # a hostile evening is never over

    def add(self, entries: list[Entry], mid: str, title: str, sets: dict[str, Any]) -> int:
        """One more moment of the log, with its own steps; gives its number."""
        i0 = sum(len(e[2]) for e in entries)
        made = {"steps": [{**copy.deepcopy(s), "i": i0 + k} for k, s in enumerate(self.steps0)],
                "moment": {**copy.deepcopy(self.good), "q": len(entries) + 1, "id": mid, "n": title,
                           "s": list(range(i0, i0 + len(self.steps0)))}}
        for path, value in sets.items():
            made = put(made, path, self.value(value, i0))
        entries.append((self.good["tq"], made["moment"], made["steps"]))
        return len(entries)

    def value(self, v: Any, i0: int) -> Any:
        """A case's value: "$markup" is the hostile markup, {"$text": n} a text of n characters, {"$times": [x, n]} a list of
        n x, {"$i0": [a, b]} step numbers counted from the case's own first step."""
        if v == "$markup":
            return self.markup
        if isinstance(v, dict) and len(v) == 1 and next(iter(v)) in ("$text", "$times", "$i0"):
            (word, arg), = v.items()
            if word == "$text":
                return ("long text " * (arg // 10 + 1))[:arg]
            return [self.value(arg[0], i0) for _ in range(arg[1])] if word == "$times" else [i0 + a for a in arg]
        if isinstance(v, dict):
            return {k: self.value(x, i0) for k, x in v.items()}
        return [self.value(x, i0) for x in v] if isinstance(v, list) else v

    def v2(self, since: int, room: int) -> dict[str, Any]:
        out = super().v2(since, room)
        sets = [x for q in range(since + 1, out["next"] + 1) for x in self.once.pop(q, {}).items()]
        if sets:
            out = copy.deepcopy(out)                 # the answer alone is changed, never the log behind it
        for path, value in sets:
            out = put(out, path, self.value(value, 0))
        return out

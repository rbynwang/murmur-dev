"""The audience's surprises: six presets, one at a time, and a vote while the network settles (POST /live/surprise).

A viewer sends one of six words and nothing else: no text, no number and no node of a viewer's is ever taken. Each preset is one
of the presenter's surprises with every field at its default (commands.check fills them in): battery_low at 10%, car_now, weather
with the sun at a fifth, building_need, emergency of 20 kW, battery_fault.

  the first tap while nothing cools down   is posted at once, and starts a cooldown of 10 seconds
  a tap during the cooldown                is a vote for its preset: one a viewer in each round
  when the cooldown ends                   the preset with the most votes is posted, and the next cooldown starts; with no vote
                                           the door is open again
  twenty surprises an evening              and no more: the count starts again with the next evening (reset)

A viewer is the token its page sends, or its address when the page sends none; one address has at most 200 votes in a round, so a
hall behind one address can all vote and one machine cannot fill a round.
The numbers are for a room that watches an evening of about two minutes: a round every ten seconds, and no evening runs out. tap() and due() are called from different threads.

The door is shut until a console is started for an audience (`on`), and while no evening plays (`open`). Of the six presets an
evening takes those its network can play (reset): a network with no building has no building's need.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

PRESETS = ("battery_low", "car_now", "weather", "building_need", "emergency", "battery_fault")      # each a kind of commands.KINDS
COOLDOWN_S = 10.0
MOST = 20                         # surprises of the audience in one evening
ADDRESS_VOTES = 200               # votes one address has in one round
VIEWERS = 5_000                   # viewers one round remembers: beyond that no vote is taken until the next round
FIRE, VOTE, AGAIN, DONE, CLOSED = "fire", "vote", "again", "done", "closed"


class Crowd:
    def __init__(self, wall: Callable[[], float] = time.time, on: bool = False):
        self.wall, self.lock, self.on = wall, threading.Lock(), on
        self.open = False                              # the driver opens the door while an evening plays
        self.reset()

    def reset(self, presets: Any = PRESETS) -> None:
        """A new evening, with the presets its network can play: its twenty surprises are all still to come, and nothing cools down."""
        with self.lock:
            self.presets = tuple(k for k in PRESETS if k in presets)
            self.fired, self.until, self.last = 0, 0.0, None
            self.votes: dict[str, list[float]] = {}      # preset -> [votes, the time of its first]
            self.seen: set[str] = set()
            self.per_address: dict[str, int] = {}

    def tap(self, kind: str, viewer: str, address: str) -> str:
        """One viewer's tap on a preset: FIRE (post it now), VOTE (counted), AGAIN (this viewer, or this address, has had its
        votes in this round), DONE (the evening has had its twenty) or CLOSED (no evening plays, or the word is no preset)."""
        now = self.wall()
        with self.lock:
            if not (self.on and self.open) or kind not in self.presets:
                return CLOSED
            if self.fired >= MOST:
                return DONE
            if now >= self.until and not self.votes:
                self.fire(kind, "viewer", now)
                return FIRE
            if viewer in self.seen or self.per_address.get(address, 0) >= ADDRESS_VOTES or len(self.seen) >= VIEWERS:
                return AGAIN
            self.seen.add(viewer)
            self.per_address[address] = self.per_address.get(address, 0) + 1
            row = self.votes.setdefault(kind, [0, now])
            row[0] += 1
            return VOTE

    def due(self) -> str | None:
        """Once a cooldown is over: the preset the round voted for, which is posted now and starts the next cooldown. None while
        one runs, when nobody voted, or when the evening has had its twenty."""
        now = self.wall()
        with self.lock:
            if now < self.until or not self.votes:
                return None
            kind = min(self.votes, key=lambda k: (-self.votes[k][0], self.votes[k][1]))       # the most votes; of equals, the first voted for
            if not (self.on and self.open) or self.fired >= MOST:
                self.votes, self.seen, self.per_address = {}, set(), {}
                return None
            self.fire(kind, "vote", now)
            return kind

    def fire(self, kind: str, by: str, now: float) -> None:
        self.fired, self.until, self.last = self.fired + 1, now + COOLDOWN_S, {"kind": kind, "by": by, "at": now}
        self.votes, self.seen, self.per_address = {}, set(), {}

    def unfire(self) -> None:
        """The surprise just fired could not be posted: the evening gets it back."""
        with self.lock:
            self.fired, self.until, self.last = max(0, self.fired - 1), 0.0, None

    def state(self) -> dict[str, Any] | None:
        """What every viewer's page is told (the feed's v2.crowd): only counts, the six words and whole seconds. None on a console
        that was not started for an audience."""
        now = self.wall()
        if not self.on:
            return None
        with self.lock:
            last = self.last and {"kind": self.last["kind"], "by": self.last["by"], "ago_s": max(0, int(now - self.last["at"]))}
            return {"open": bool(self.open and self.fired < MOST), "presets": list(self.presets), "cooldown_s": max(0, math.ceil(self.until - now)),
                    "votes": {k: int(v[0]) for k, v in self.votes.items()}, "left": MOST - self.fired, "most": MOST, "last": last}

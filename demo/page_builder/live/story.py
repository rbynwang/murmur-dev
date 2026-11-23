"""A live evening's story, told while the network runs: shaped steps come in, gather into moments, and each moment is built
by the replay's own builder when it is over.

A moment in the making is an instance of a beat: its steps of one quarter-hour, and of one node or one half hour where the
beat says so. A key step opens its instance and the beat's other steps join it. The driver gives each pass's steps to take()
and ends the pass with close(), which gives out the instances that are over as (wire steps, wire moment), in the order
quarter-hour, rank, opening. Nothing given out ever changes. Steps that come in the beats' own order give the same moments
fed one a pass or many a pass: a higher beat closes a lower one only a pass after it opened, and inside a running step of
the network nothing closes by time.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .. import names as N
from ..replay import cards as K
from ..replay import moments as M
from ..replay import panels as P
from ..replay.story import Step, Story
from . import wire
from .beats import WORDS, Beat, beats, figures

Given = tuple[list[dict[str, Any]], dict[str, Any]]
STANDS = ("held", "at_gate", "ended")       # the conductor's modes in which the clock stands: nothing more comes for its step
RUNS = ("playing", "waiting")               # its modes inside a running step, where nothing closes by time
SIDE_BY_SIDE = ("desk", "call-desk")        # these run to the end of the network's step, whatever opens beside them
PASSES = 8                                  # how many passes an instance may stay without a step, and a step ahead of the clock


@dataclass
class Instance:
    """One moment in the making."""
    beat: Beat
    key: tuple[Any, ...]
    tq: int
    opened: int
    steps: list[Step] = field(default_factory=list)
    fed: bool = True          # it took a step in this pass
    idle: int = 0             # passes in a row with no step for it, in none of which the clock ran a step


class LiveStory(Story):
    """The story of an evening that is still running. It keeps the builder's own state (what the story has seen so far), so a
    moment's figures are those the network had reached when the moment was given out."""

    def __init__(self, ev: Any):
        self.ev = ev
        self.seen: dict[str, Any] = {}
        self.tv_prev: dict[str, str] = {}
        self.beats = {b.id: b for b in beats(ev.sites)}
        self.open: dict[tuple[Any, ...], Instance] = {}
        self.began: list[Instance] = []         # the instances that were open when this pass began
        self.shut: list[Instance] = []          # over, and given out at the end of this pass
        self.ahead: list[list[Any]] = []        # [step, passes waited]: steps of a quarter-hour the clock has not reached
        self.loose: list[Step] = []             # steps that open nothing, waiting for their beat's instance
        self.windows: list[Step] = []           # every delivery step given out so far
        self.opened = 0
        self.faults = {"orphans": 0, "cards": 0, "ahead": 0}

    def take(self, steps: list[Step], now_tq: int) -> None:
        """Takes shaped steps in the order they came. A step of a quarter-hour the clock has not reached waits for it."""
        self.ahead += [[s, 0] for s in steps]
        due = [p[0] for p in self.ahead if p[0]["tq"] <= now_tq]
        self.ahead = [p for p in self.ahead if p[0]["tq"] > now_tq]
        for s in due:
            self._join(s)

    def _key(self, s: Step) -> tuple[Any, ...]:
        per = getattr(self.beats.get(str(s.get("beat"))), "per", "tq")
        return (str(s.get("beat")), s["tq"]) + ((s.get("node"),) if per == "node" else (s.get("sim_time"),) if per == "half" else ())

    def _join(self, s: Step) -> None:
        """A key step opens its instance, and the steps that waited for it join behind it. Another step joins its beat's open
        instance, or waits for one. At 24 steps an instance is over at once, and its beat may open again."""
        key = self._key(s)
        x = self.open.get(key)
        if x is None and not s.get("key"):
            self.loose.append(s)
            return
        if x is None:
            beat = self.beats.get(key[0]) or Beat(key[0], len(self.beats), None, "tq")     # a beat nobody knows ranks last
            x = self.open[key] = Instance(beat, key, s["tq"], self.opened)
            self.opened += 1
        x.steps.append(s)
        x.fed = True
        if len(x.steps) == wire.STEPS:
            self.shut.append(self.open.pop(key))
        if len(x.steps) == 1:
            waited = [w for w in self.loose if self._key(w) == key]
            self.loose = [w for w in self.loose if self._key(w) != key]
            for w in waited:
                self._join(w)

    def close(self, now_tq: int, mode: str) -> list[Given]:
        """The end of a pass, with the conductor's reading from the pass's start. An instance is over when (1) the clock has
        left its quarter-hour; (2) the clock stands at or after it; (3) an instance of its quarter-hour and a higher rank was
        open when the pass began; (4) it took no step in eight passes, in none of which the clock ran a step. A step that
        waited for an instance until its quarter-hour closed is an orphan: counted, and shown nowhere."""
        self.take([], now_tq)
        for p in self.ahead:
            p[1] += 1
            self.faults["ahead"] += p[1] == PASSES + 1
        past = now_tq + (mode in STANDS)                          # quarter-hours before this one are closed
        for key, x in list(self.open.items()):
            x.idle = 0 if x.fed or mode in RUNS else x.idle + 1
            x.fed = False
            outranked = x.beat.id not in SIDE_BY_SIDE and any(y.tq == x.tq and y.beat.rank > x.beat.rank for y in self.began)
            if x.tq < past or outranked or x.idle >= PASSES:
                self.shut.append(self.open.pop(key))
        kept = [s for s in self.loose if s["tq"] >= past]
        self.faults["orphans"] += len(self.loose) - len(kept)
        self.loose, self.began = kept, list(self.open.values())
        over, self.shut = sorted(self.shut, key=lambda x: (x.tq, x.beat.rank, x.opened)), []
        return [self._give(x) for x in over]

    def _give(self, x: Instance) -> Given:
        """An instance that is over, as the feed sends it. One the builder cannot make is given out all the same, as "other"."""
        recs = self._recs(x.steps)
        try:
            moment = wire.moment(self._build(x, recs), x.tq)
        except Exception:                           # whatever the builder lacks, the steps are shown, and the fault counted
            self.faults["cards"] += 1
            moment = wire.moment(self._other(x.steps[0], recs), x.tq)
        steps = [wire.step(r, x.tq, self.ev.map.ids) for r in recs]
        wire.fit(steps, moment)
        return steps, moment

    def _recs(self, ms: list[Step]) -> list[dict[str, Any]]:
        """The steps' records as Story.compile makes them (replay/story.py:96-102), with the fields a live step is sent with.
        A box this evening's map does not draw is left out."""
        bidx = self.ev.map.index
        recs = []
        for s in ms:
            ls = self.lines(s)
            for x in ls:
                x["b"] = [b for b in x["b"] if b in bidx]
            own = sorted({b for x in ls for b in x["b"]}, key=bidx.get) or [b for b in M.block_of(s) if b in bidx]
            recs.append({"n": str(s.get("title") or ""), "m": 0, "wn": N.fixed_name(s.get("node")), "sd": M.side(s),
                         "b": [bidx[b] for b in own], "_l": ls})
        return recs

    def _build(self, x: Instance, recs: list[dict[str, Any]]) -> dict[str, Any]:
        """The builder's own moment (Story.moment) from a copy of the beat's words: its key steps are the instance's key steps,
        by their titles, and the step that explains it is its `say` step, else its first key step."""
        ms, mo = x.steps, copy.copy(x.beat.mo)
        keys = [s for s in ms if s.get("key")]
        titles = lambda steps: "|".join(re.escape(str(s.get("title") or "")) for s in steps)  # noqa: E731
        mo.key, mo.say = f"^(?:{titles(keys)})$", f"^(?:{titles([next((s for s in ms if s.get('say')), keys[0])])})$"
        buyer = "buy-g" if any(str(s.get(k) or "").startswith("grid") for s in ms for k in ("from", "to")) else "buy-u"
        mo.block, mo.path = mo.block.replace("{buyer}", buyer), tuple(buyer if b == "{buyer}" else b for b in mo.path)
        m = self.moment(0, mo, ms, recs, {id(s): i for i, s in enumerate(ms)})
        k = m["k"]
        if x.beat.id == "window":                   # the half hours' card shows the evening so far, not this half hour alone
            self.windows += ms
            k["cd"], k["cols"] = P.CARDS["device"](self.ev, {"ms": self.windows, "v": self.tv_prev})
        k["cd"] = [c for c in K.some_cards(k["cd"]) if "tbl" not in c or len(c["tbl"]) > 1]      # the wire fits the columns to them
        if x.beat.id in WORDS:
            m["tag"] = ["Surprise", WORDS[x.beat.id]]
        return m

    def hero(self, mo: M.Mo, allv: dict[str, str], ms: list[Step]) -> list[str] | None:
        """The builder's big figure and caption, with the figures only a live moment has. A beat that names none shows none."""
        return super().hero(mo, {**allv, **figures(ms, self.seen)}, ms) if mo.big else None

    def _other(self, s: Step, recs: list[dict[str, Any]]) -> dict[str, Any]:
        """A moment the builder could not make: its first step's title and box, no path, and that step's sentence on a bare
        card. Its first lines are marked, so the terminal shows them."""
        box = M.receiver(s) if s.get("layer") == "town" else M.block_of(s)[0]
        box = box if box in self.ev.map.index else "town"
        node = str(s.get("node") or "")
        for x in recs[0]["_l"][:6]:
            x.setdefault("key", 1)
        return {"id": "other", "n": recs[0]["n"], "b": box, "wn": N.fixed_name(node), "hero": None, "tag": None, "p": [], "c": "",
                "lit": self.lit({box} | {b for r in recs for x in r["_l"] for b in x["b"]}), "tv": {},
                "k": {"kind": "aggpart", "cb": box, "l": K.ROLE[box], "who": [], "in": [], "out": [], "did": str(s.get("plain") or "")[:124],
                      "rule": "", "cd": [], "cols": "1fr", "term": K.term_cap("aggpart", node), "big": None}}

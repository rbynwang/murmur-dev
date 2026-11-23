"""What the live shapers stand on: the fixed words of one kind of step (Row), and what one run's shaping keeps between items
(Shaping), which makes every step: the recorder's keys and, with them, its beat, its quarter-hour, key, say and its item's wall time.

Every step leaves through Shaping.step, where each live id becomes its page id and every text is scrubbed. No shaper raises: each
item (a message the bus accepted, a row of a node's record, a snapshot of the sale, a post of the console's own) is shaped inside
Shaping.shaped, which shows an item it cannot shape as it came, and counts it.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from .. import names as N
from ..replay import moments as M
from .fmt import J, T, scrub

Step = dict[str, Any]
FMT, QUARTER = "%Y-%m-%d %H:%M", timedelta(minutes=15)     # a dataset time, and one step of the clock
COMMUNITY, COORDINATOR = "community", "coordinator"        # the community agent's page id, and the name the builder knows it by
AGENT, WHY = "agent", 20         # a Row's layer for a node's own agent (home_agent or building_agent); how many faults keep their reason


@dataclass(frozen=True)
class Row:
    """The fixed words of one kind of step (ROWS of words_bus and words_node). beat: the beat its steps belong to, by its id.
    stage, layer: the recorder's, which the builder's boxes and cards read; the layer "agent" stands for the node's own agent,
    home_agent or building_agent by the step's node. title, plain: the step's title and its sentence, a {name} taking the field
    of that name given to Shaping.step. key: a key step opens its beat's moment. say: the step whose sentence the moment says.
    box: the map box its steps land in (see boxes), with {side} for h or b where homes and buildings share the row."""
    beat: str
    stage: str
    layer: str
    title: str
    plain: str
    key: bool
    say: bool
    box: str


def when(ts: Any) -> datetime:
    """A dataset time, read. ValueError when the text is none."""
    return datetime.strptime(str(ts)[:16].replace("T", " "), FMT)


def boxes(step: Step) -> list[str]:
    """The map boxes the builder gives a step: those of its lines, or the step's own when it has none (replay/story.py)."""
    own = {b for x in step.get("terminal") or [] for b in M.line_blocks(step, x.get("kind") or "note", str(x.get("text") or ""))}
    return sorted(own) or M.block_of(step)


class Shaping:
    """One run's shaping: who is followed, how a live id is named on the page, the clock's zero, and what is kept between items.
    ev      the LiveEvening the story is built on: the shapers give it the orders, the totals and the followed nodes' facts
    follow  the followed nodes by live id, a set; the driver adds a surprise's node to it
    alias   live id -> page id (home-NN, building-NN, community); an id it does not hold is its own page id
    t0      the dataset time of tq 0: 09:45 on the day before the sale's
    snap    the sale's last snapshot, {} before the first: whoever shapes a snapshot leaves it here for the next item
    count   what is counted and not shaped: count["community.report"] += 1
    faults  {"shape": n}, the items shaped() could not shape as their Row says; why: the first 20 reasons, never for the page"""

    def __init__(self, ev: Any, follow: Iterable[str], alias: dict[str, str] | None, t0: str):
        self.ev, self.follow, self.t0, self.snap = ev, set(follow or ()), t0, {}
        self.alias = {str(k): str(v) for k, v in (alias or {}).items() if str(k) != str(v)}
        self.count, self.faults, self.why, self._zero, self._marks = Counter(), {"shape": 0}, [], when(t0), set()
        self.held: dict[str, Any] = {}           # a message shown only with a later one: an aggregator's request, with its answer
        self.calls: dict[str, Any] = {}          # a buyer's calls at short notice, by id: the desk's exchanges for them are the call's
        self.asked: Counter = Counter()          # (gap or call id, tq): how many members the desk asked
        self.meter: dict[str, dict[str, Any]] = {}   # the meter's fed quarter-hours, by dataset time
        self.nodes: dict[str, dict[str, Any]] = {}   # each followed node's rows read so far that no step has shown yet
        ids = "|".join(re.escape(k) for k in sorted(self.alias, key=len, reverse=True))
        self._ids = re.compile(rf"(?<!\w)(?:{ids})(?!\w)") if ids else None

    @property
    def window(self) -> tuple[str, str]:
        """The window as two dataset times, from the evening's day and its half hours."""
        day, halves = str(self.ev.meta.get("day") or ""), [h["start"] for h in self.ev.ledger.get("half_hours") or []]
        if not day or not halves:
            return ("", "")
        end = (when(f"{day} {halves[-1]}") + 2 * QUARTER).strftime(FMT)
        return f"{day} {halves[0]}", end

    def tq(self, ts: Any) -> int:
        """The quarter-hours from t0 to a dataset time: 1 at 10:00 on the day before the sale's, 129 at 18:00 on its day. A time
        inside a quarter-hour counts with its start. ValueError when ts is no dataset time."""
        return (when(ts) - self._zero) // QUARTER

    def ts(self, tq: int) -> str:
        """The dataset time of a quarter-hour: what tq() counts back from."""
        return (self._zero + tq * QUARTER).strftime(FMT)

    def name(self, who: Any) -> str:
        """A live id as the builder names the participant: its page id, coordinator for the community agent. Not for a text given to step()."""
        page = self.alias.get(str(who or ""), str(who or ""))
        return COORDINATOR if page == COMMUNITY else page

    def clean(self, x: Any) -> Any:
        """A text, or every text inside a list or a dict, as it may leave: each live id as its page id, then scrubbed."""
        if isinstance(x, str):
            return scrub(self._ids.sub(lambda m: self.alias[m.group(0)], x) if self._ids else x)
        if isinstance(x, dict):
            return {k: self.clean(v) for k, v in x.items()}
        return [self.clean(v) for v in x] if isinstance(x, (list, tuple)) else x

    def once(self, *mark: Any) -> bool:
        """True the first time a mark is asked for and False ever after, for what a sale shows once: once(sale, "confirm")."""
        return not (mark in self._marks or self._marks.add(mark))

    def step(self, row: Row, tq: int, wall: float, **fields: Any) -> Step:
        """One step of a Row at quarter-hour tq, from an item with wall time `wall` (seconds). fields: frm, to and node (who sent
        it, who it is for, the node it is about); lines (its terminal, a list of fmt.T); values (the figures the builder reads);
        sim_time (when the step's own time is not tq's: a delivery step's half hour); key and say (in place of the Row's); and each
        word the Row's title and plain name, frm, to and node among them. Every id given here, in a field or inside a text, is the
        live one: only here does it become its page id, so no text comes through name() or clean() first. A word the Row names
        that is not given is a KeyError: shaped() makes it the item's fault step."""
        who = {k: self.name(fields.get(k)) for k in ("frm", "to", "node")}
        layer = row.layer if row.layer != AGENT else "building_agent" if N.is_building(who["node"]) else "home_agent"
        return {"sim_time": str(fields.get("sim_time") or self.ts(tq)), "stage": row.stage, "layer": layer, "from": who["frm"],
                "to": who["to"], "node": who["node"], "title": self.clean(row.title.format(**fields)),
                "plain": self.clean(row.plain.format(**fields)),
                "terminal": [T(x["kind"], self.clean(x["text"])) for x in fields.get("lines") or ()],
                "values": self.clean(dict(fields.get("values") or {})), "beat": row.beat, "tq": tq,
                "key": bool(fields.get("key", row.key)), "say": bool(fields.get("say", row.say)), "wall": wall}

    def shaped(self, row: Row, item: Any, tq: int, wall: float, shape: Callable[..., Any], *args: Any, kind: str | None = None,
               node: Any = None) -> list[Step]:
        """The steps shape(*args) makes of one item, and never an exception: every item is shaped inside this call. shape gives
        a list of steps, one step, or None for an item that shows nothing. When it raises (the item lacks a field its Row reads,
        a figure is no number), the item still gives one step: in the Row's beat, stage and layer, key and say as the Row's,
        titled by the item's kind, its JSON cut at 600 characters as its one line, from, to and node as the item names them;
        faults["shape"] counts it. row is the Row the item's kind is shaped by; tq and wall are values already in hand, read
        before this call. kind names an item that carries none (a snapshot, a post); node, the node a message's step is about."""
        try:
            made = shape(*args)
            return [made] if isinstance(made, dict) else list(made or ())
        except Exception as exc:                    # whatever an item lacks, it is shown as it came and counted
            got = item.get if isinstance(item, dict) else lambda k: None
            kind = str(kind or got("kind") or row.beat)
            self.faults["shape"] += 1
            self.why += [f"{kind}: {type(exc).__name__}: {exc}"][:WHY - len(self.why)]
            return [self.step(replace(row, title="{kind}", plain=""), tq, wall, frm=got("from"), to=got("to"), node=node or got("node"),
                              kind=kind, lines=[T("note", J(item, 600))])]

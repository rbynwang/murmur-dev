"""One pass of the console's reading, turned into moments: the dataset time of each item, the shapers, the story and the log.

A pass is what the driver read in one look at the network (the fixtures' Pass has the same fields): t, the wall time it began; the
conductor's view; the bus record's new events; the community.report rows not kept, counted by sender; each followed node's new
rows; the sale's summary and the snapshots read at its triggers; the meter's new fed quarter-hours; the console's own posts.

Dataset time (the specification's 1.3). A row carries its own. A bus message carries only its wall time, so every pass that finds
the conductor's clock moved leaves a mark, (the wall time of the last pass that saw the old clock, the new clock), and a message
takes the clock of the last mark at or before its own wall time: it was sent after the clock moved there. A snapshot, a post and a
half hour of the window take the clock of the pass that read them.
"""
from __future__ import annotations

from typing import Any

from demo.page_builder.live import shape_bus, shape_market, shape_node
from demo.page_builder.live.evening import LiveEvening
from demo.page_builder.live.shape import Shaping
from demo.page_builder.live.story import LiveStory
from . import timeline as T

WAIT_PASSES = 40                 # a row with no time waits this many passes for the node's next row, then takes the clock's
TRIGGERS = ("select", "telemetry_done", "settlement", "done")


class Intake:
    def __init__(self, facts: dict[str, Any], follow: list[str], alias: dict[str, str] | None, log: Any):
        self.ev = LiveEvening(facts)
        self.t0 = T.shift(f"{facts['day']} 09:45", -1440)
        self.sh = Shaping(self.ev, follow, alias, self.t0)
        self.story = LiveStory(self.ev)
        self.log = log
        self.marks: list[tuple[float, str]] = []
        self.last: tuple[float, str] | None = None
        self.waited: dict[str, int] = {}
        self.taken: set[str] = set()                   # the triggers already read: each snapshot is read once
        self.phase: str | None = None

    # ------------------------------------------------------------------ what the driver should read in this pass
    def triggers(self, events: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
        """The triggers this pass holds that were not read yet: the first select; an update with telemetry_done; a buyer's on_status
        with a settlement; the sale's phase done. The driver reads /v2/events/{id} once for them, before take()."""
        found = []
        for e in events:
            k, m = shape_bus.kind(e), shape_bus.message(e)
            if k == "select":
                found.append("select")
            elif k == "update" and "telemetry_done" in m:
                found.append("telemetry_done")
            elif k == "on_status" and "settlement" in m and str(e.get("from")) in shape_bus.BUYERS:
                found.append("settlement")
        if self.sale_phase(summary) == "done":
            found.append("done")
        return [t for t in dict.fromkeys(found) if t not in self.taken]

    @staticmethod
    def sale_phase(summary: dict[str, Any]) -> str | None:
        events = (summary or {}).get("events") or {}
        rows = list(events.values()) if isinstance(events, dict) else list(events)
        return str(rows[0].get("phase")) if rows and isinstance(rows[0], dict) else None

    @staticmethod
    def sale_id(summary: dict[str, Any]) -> str | None:
        events = (summary or {}).get("events") or {}
        return next(iter(events), None) if isinstance(events, dict) else None

    # ------------------------------------------------------------------ one pass
    def when(self, at: Any) -> str:
        """The clock a bus message was sent at, by its wall time."""
        try:
            wall = float(at)
        except (TypeError, ValueError):
            return self.marks[-1][1]
        return next((now for w, now in reversed(self.marks) if w <= wall), self.marks[0][1])

    def take(self, p: Any) -> list[int]:
        """Shapes everything a pass read, closes what is over and gives it to the log. The q of each moment logged."""
        view = p.conductor or {}
        now, mode = str(view.get("now") or self.t0), str(view.get("mode") or "idle")
        if self.last is None:
            self.marks.append((float("-inf"), now))
        elif self.last[1] != now:
            self.marks.append((self.last[0], now))
        self.last = (p.t, now)
        sh, q = self.sh, self.sh.tq(now)
        for who, n in (p.reports or {}).items():
            sh.count["community.report"] += n
        steps: list[dict[str, Any]] = []
        for e in p.bus or []:
            steps += shape_bus.steps(sh, e, sh.tq(self.when(e.get("at"))), float(e.get("at") or p.t))
        for snap in p.snapshots or []:
            marks = snap.get("trigger") or []
            self.taken |= set([marks] if isinstance(marks, str) else marks)
            steps += shape_market.snapshot(sh, marks, snap.get("event") or {}, q, p.t)
        for node, rows in (p.rows or {}).items():
            steps += shape_node.steps(sh, node, rows, p.t)
        for node, st in sh.nodes.items():
            self.waited[node] = self.waited.get(node, 0) + 1 if st["waiting"] else 0
            if self.waited[node] > WAIT_PASSES:
                steps += shape_node.flush(sh, node, now, p.t)
        steps += shape_market.delivery(sh, p.meter or [], now, q, p.t)
        for post in p.posts or []:                      # an order is placed before the evening's first quarter-hour
            steps += shape_market.posted(sh, post, 0 if str(post.get("path") or "").endswith("/needs") else q, p.t)
        self.phase = self.sale_phase(p.summary) or self.phase
        self.story.take(steps, q)
        return [x for x in (self.log.add(s, m) for s, m in self.story.close(q, mode)) if x is not None]

    def faults(self) -> dict[str, int]:
        return {**self.sh.faults, **self.story.faults}

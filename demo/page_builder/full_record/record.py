"""The facts the Full record reads from one recorded evening: its steps in page order, the nodes it follows, the
community's cells, the scale of the trade's bars and how often the small model was asked for each kind of answer."""
from __future__ import annotations

import json
import re
from typing import Any

from .anchors import device_anchor, queue_kind
from .figures import first, num
from .naming import is_building, is_home, number_of

READER = re.compile(r"qwen(\d+(?:\.\d+)?)[:-](\d+)b")


def reader_name(meta: dict[str, Any]) -> str:
    """The small model that read the notes, in a few words: qwen3.5:4b-q4_K_M is Qwen 3.5 4B."""
    m = READER.match(str(meta.get("note_reader") or meta.get("model") or "").lower())
    return f"Qwen {m.group(1)} {m.group(2)}B"


def tidy(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The record's steps in page order: the same record shaped twice shows once, where it comes last."""
    def key(s: dict[str, Any]) -> tuple[Any, ...]:
        return s.get("layer"), tuple(s["raw"]), json.dumps(s.get("terminal"))
    last = {key(s): i for i, s in enumerate(steps) if s.get("raw")}
    return [s for i, s in enumerate(steps) if not s.get("raw") or last[key(s)] == i]


class Record:
    """One recorded evening, as the Full record reads it."""

    def __init__(self, recording: dict[str, Any]) -> None:
        self.meta = recording.get("meta") or {}
        self.cast = recording.get("cast") or {}
        self.follow = self.cast.get("follow") or {}
        self.ledger = recording.get("ledger") or {}
        self.steps = tidy(recording.get("steps") or [])
        self.gaps = list(recording.get("gaps") or [])
        self.changes = {c["id"]: c for c in recording.get("changes") or []}
        self.home = (self.follow.get("thinking_home") or {}).get("node")       # the home whose steps the ladder follows
        self.uni = (self.follow.get("university") or {}).get("node")           # the building the Building column follows
        self.other = (self.follow.get("mall_or_office") or {}).get("node")     # the building that runs the same steps beside it
        self.community = self.meta.get("community") or {}
        self.counts = {"homes": self.community.get("homes"), "buildings": self.community.get("buildings"),
                       "nodes": int(self.community.get("homes") or 0) + int(self.community.get("buildings") or 0)}
        self.reader = reader_name(self.meta)
        self.half_hours = self.ledger.get("half_hours") or []
        self.scale = self._scale()
        self.nodes = self._nodes()
        self.queue_max: dict[str, int] = {}
        for s in self.steps:
            if s.get("layer") == "model":
                kind = queue_kind(s)
                self.queue_max[kind] = self.queue_max.get(kind, 0) + 1

    def _scale(self) -> float:
        """The largest kW of the evening: the trade's bars are drawn against it."""
        xs = [num(h.get(k)) or 0.0 for h in self.half_hours for k in ("offered_kw", "asked_of_nodes_kw", "asked_kw", "delivered_kw", "true_kw")]
        for s in self.steps:
            for k in ("offered_kw", "asked_kw", "asked_of_nodes_kw"):
                x = first((s.get("values") or {}).get(k))
                if x:
                    xs.append(x)
        return max(xs or [1.0])

    def _nodes(self) -> list[dict[str, Any]]:
        """The community's cells: its buildings, the followed ones first, then one cell for each of the homes numbered
        1 to its number of homes, with the figures of the home that has that number, where the community has one."""
        homes, blds = int(self.community.get("homes") or 0), int(self.community.get("buildings") or 0)
        th = set(self.cast.get("thinkers") or [])
        known = list(th) + list(self.ledger.get("nodes") or {})
        named = [n for n in known if is_building(n)]
        firsts = [x for x in (self.uni, self.other) if x]
        out = [{"node": n, "number": None, "big": True, "think": n in th} for n in (firsts + sorted(set(named) - set(firsts)))[:blds]]
        by_number = {number_of(n): n for n in known if is_home(n)}
        for i in range(1, homes + 1):
            node = by_number.get(i)
            out.append({"node": node, "number": i, "big": False, "think": node in th})
        return out

    def card_nodes(self) -> dict[str, str]:
        """Which followed node's readings each appliance card carries."""
        return {"battery": self.home or "", "cooling": self.home or "", "car": self.home or "", "campus": self.uni or "", "plant": self.uni or "", "lights": self.uni or ""}

    def device_rows(self) -> dict[str, str]:
        """The node each row of the appliance table belongs to ("" for a row of no one node)."""
        return {**self.card_nodes(), "plugs": self.uni or "", "water": self.home or ""}

    def devices_called(self) -> set[str]:
        """The rows of the appliance table that have a call on this evening: a write on the row's own node."""
        rows = self.device_rows()
        out: set[str] = set()
        for s in self.steps:
            a = device_anchor(str(s.get("to"))) if s.get("layer") == "device" and s.get("to") else None
            if a and (not rows.get(a[5:]) or rows[a[5:]] == str(s.get("node") or "")):
                out.add(a[5:])
        return out

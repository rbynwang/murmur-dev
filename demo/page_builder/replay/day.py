"""One evening's packed day: its data "d" (the story, the map, the figures' names and the opening card) and its whole-picture
markup "world", as the page unpacks them when the evening is chosen."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .. import names as N
from . import words as W
from .evening import Evening
from .story import Story
from .tree import layout
from .world import world


def opening_card(ev: Evening, two_view: bool) -> dict[str, Any]:
    """Who does what, as the opening card says it."""
    scope, rows = W.CARD_SITES if ev.sites else W.CARD_YEAR
    rows = [list(r) for r in rows]
    if ev.sites and ev.engie.get("site_notes"):
        d = dt.date.fromisoformat(str(ev.meta.get("day")))
        rows[-1][1] = W.REPLAY_WITH_NOTES.format(date=f"{d.day} {d.strftime('%B %Y')}")
    return {"t": W.CARD_TITLE, "s": W.PREMISE if two_view else scope, "r": rows}


def data(ev: Evening, two_view: bool = False, min_w: int = 0) -> dict[str, Any]:
    """The day's data. min_w: the tree's least width (see tree.layout)."""
    d = {"stories": {"main": Story(ev).compile()}, "order": ["main"], "blocks": ev.map.page_blocks(), "edges": ev.map.page_edges(),
         "kind": "code", "levels": True, "absent": [], "strip": [[n, list(bs)] for n, bs in ev.map.strip],
         "tv": [[k, lab] for k, lab in ev.tv], "layers": ev.map.layers, "status": {k: [] for k in ev.map.layers},
         "who": opening_card(ev, two_view)}
    d["names"] = N.cast_names(ev.tr)
    d["tree"] = layout(ev, d, min_w)
    return d


def pack(tr: dict[str, Any], two_view: bool = False, min_w: int = 0) -> dict[str, Any]:
    """The packed day without its Full record: {"d": data, "world": the whole picture's markup}."""
    ev = Evening(tr)
    d = data(ev, two_view, min_w)
    return {"d": d, "world": str(world(ev, d))}

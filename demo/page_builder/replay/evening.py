"""One recorded evening, read for the replay: its steps in the order the page tells them, the nodes it follows, the buyers'
orders, its gaps, and what each figure on the page is called.

Every recording the pages play ran on code-made plans with every home and building its own agent, over the message network;
an evening with single sites (meta.engie.single_sites) shows them on the map beside the community.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from .. import names as N
from . import words as W
from .blocks import Map
from .text import in_scope, kw, num

Step = dict[str, Any]


def tidy(steps: list[Step]) -> list[Step]:
    """The record's steps in the page's order: a record shaped twice shows once, where it comes last."""
    def key(s: Step) -> tuple[Any, ...]:
        return s.get("layer"), tuple(s["raw"]), json.dumps(s.get("terminal"))
    last = {key(s): i for i, s in enumerate(steps) if s.get("raw")}
    return [s for i, s in enumerate(steps) if not s.get("raw") or last[key(s)] == i]


def lines(s: Step) -> list[str]:
    return [str(x.get("text") or "") for x in s.get("terminal") or []]


def orders(steps: list[Step]) -> dict[str, dict[str, str]]:
    """Each buyer's order, from its place_order line: demand, window, price, value and deposit."""
    out: dict[str, dict[str, str]] = {}
    for s in steps:
        if s.get("layer") != "buyer" or s.get("stage") != "order":
            continue
        ls = lines(s)
        m = next((m for t in ls for m in [re.match(r"place_order\((.*)\)$", t)] if m), None)
        o = json.loads(m.group(1)) if m else {}
        worth = next((g.group(1) for t in ls for g in [re.search(r"worth if delivered.*= (\$[\d,.]+)", t)] if g), "")
        out[str(s.get("from"))] = {"kw": f"{kw(o.get('kw'))} kW" if num(o.get("kw")) is not None else "",
                                   "win": f'{o.get("start")} to {o.get("end")}' if o else "",
                                   "price": f'${o["price_usd_per_kwh"]:.2f} per kWh' if num(o.get("price_usd_per_kwh")) else "",
                                   "worth": worth, "dep": f'${o["deposit_usd"]:,.2f}' if num(o.get("deposit_usd")) else ""}
    return out


def model_name(meta: dict[str, Any]) -> str:
    """The small model that read the notes and worded the reports, in a few words: qwen3.5:4b-q4_K_M is Qwen 3.5 4B."""
    raw = str(meta.get("note_reader") or meta.get("model") or "")
    m = re.match(r"qwen(\d+(?:\.\d+)?)[:-](\d+)b", raw.lower())
    return f"Qwen {m.group(1)} {m.group(2)}B" if m else raw


def gap_words(g: dict[str, Any]) -> dict[str, str]:
    """A gap as the page says it: the record's own words, without its sentences about data centers."""
    return {"id": str(g.get("id") or ""), "title": in_scope(str(g.get("title") or "")), "expect": in_scope(str(g.get("expect") or "")),
            "actual": in_scope(str(g.get("actual") or ""))}


class Evening:
    """A recording, with what the story, the cards and the whole picture read from it."""

    def __init__(self, tr: dict[str, Any]):
        self.tr = tr
        self.meta = tr.get("meta") or {}
        self.engie = self.meta.get("engie") or {}
        self.sites = bool(self.engie.get("single_sites"))
        self.map = Map(self.sites)
        cast = tr.get("cast") or {}
        follow = cast.get("follow") or {}
        self.cast, self.ledger = cast, tr.get("ledger") or {}
        self.steps = tidy(tr.get("steps") or [])
        self.gaps = {g["id"]: g for g in (gap_words(x) for x in tr.get("gaps") or []) if g["id"] not in W.SOLVED}
        for g in W.DESIGN_GAPS:
            self.gaps.setdefault(g["id"], gap_words(g))
        node = lambda key: (follow.get(key) or {}).get("node")  # noqa: E731
        self.home, self.code_home, self.second = node("thinking_home"), node("code_home"), node("second_home")
        self.uni, self.other = node("university"), node("mall_or_office")
        self.other_place = N.PLACE.get(str(self.other), "the office")
        self.ctx = {"home": self.home, "code": self.code_home, "second": self.second, "day": self.meta.get("day")}
        com = self.meta.get("community") or {}
        self.total = int(com.get("homes") or 0) + int(com.get("buildings") or 0)
        self.followed = {str(f.get("node")): f for f in follow.values() if f.get("node")}
        self.model_short = model_name(self.meta)
        self.orders = orders(self.steps)
        hs = self.ledger.get("half_hours") or []
        self.window = ""
        if hs:
            h, m = str(hs[-1].get("start")).split(":")
            end = dt.datetime(2026, 1, 1, int(h), int(m)) + dt.timedelta(minutes=30)
            self.window = f'{hs[0].get("start")} to {end.strftime("%H:%M")}'
        self.tv = W.tv_labels(self.sites)
        self.labels = dict(self.tv + W.TV_SIDE + W.place_labels(self.other_place.split(" ", 1)[1].capitalize()))

    @property
    def sentence(self) -> str:
        """The recording in one sentence, as the story's note says it."""
        com = self.meta.get("community") or {}
        return (f"In this recording code makes every plan for all {self.total} nodes, {com.get('homes')} homes and {com.get('buildings')} "
                "buildings, and a small model reads what people write and words the reports.")

    def gap(self, gid: str) -> dict[str, str] | None:
        g = self.gaps.get(gid) if gid else None
        return {"t": g["title"], "e": g["expect"], "a": g["actual"]} if g else None

    def tv_label(self, k: str) -> str:
        """What a figure is called on the page; a half hour's figure is called by its start."""
        if re.fullmatch(r"hh\d", k):
            hs = self.ledger.get("half_hours") or []
            i = int(k[2:])
            return str(hs[i].get("start")) if i < len(hs) else k
        return self.labels.get(k, k)

"""A recorded evening, step by step, as the page's data: what each step lights, its path along the sheet, how long it
plays, its stage, and what it sets in the panel, the tables and the cards. Every step's rows go to their terminal, and
what reaches a person goes to the chats."""
from __future__ import annotations

import re
from typing import Any

from ..templating import Markup, esc, render
from .anchors import RETURN_STAGES, anchor_of, layer_anchor, layer_of_anchor, step_nos, term_for
from .cards import card_state, chain_state, device_state, guard_state, queue_state, texts, town_state
from .figures import kw, stamp
from .naming import data, is_building
from .panel import grid_state, values_to_state
from .record import Record
from .terminals import TERMS, bubbles, step_rows
from .words import CHANGE_NAME, CHANGE_TAG

LAYER_OF = {"buyer": 1, "coordinator": 2, "market": 2, "town": 3, "home_agent": 4, "building_agent": 4, "model": 4, "guard": 5, "driver": 5, "device": 6, "person": 7}
STAGE_NAME = {"order": "Order", "offers": "Offers", "clearing": "Clearing", "contract": "Contracts", "prepare": "Prepare", "delivery": "Delivery", "readings": "Readings",
              "settlement": "Settlement", "report": "Report"}
RETURN_HERE = {"buyer": "a-rp-settle", "coordinator": "a-rp-checks", "person": "a-rp-pay"}
HUE = {1: 1, 2: 2, 3: 3, 5: 5, 6: 6, 7: 7, 8: 8}
OUT = re.compile(r", out (.*)")
PREPARE_LAYERS = ("guard", "driver", "device", "home_agent", "building_agent")


def returning(s: dict[str, Any], lay: str, stage: str) -> str:
    """The block a step of the return path lights."""
    if "pay" in str(s.get("title") or "").lower() and lay != "buyer":
        return "a-rp-pay"
    if lay == "market":
        return "a-rp-settle" if stage == "settlement" else "a-rp-read"
    return RETURN_HERE.get(lay, "a-rp-read")


def step_path(s: dict[str, Any], lay: str, stage: str, here: str, prev: dict[str, Any] | None) -> list[list[str]]:
    """The way a step's packet runs along the sheet, block to block."""
    agent = "a-bld" if is_building(s.get("node")) else "a-home"
    frm, to = anchor_of(s.get("from"), s), anchor_of(s.get("to"), s)
    if lay == "town" and frm and to and frm != to:
        return [[frm, "a-town", to]]
    if lay == "guard":
        return [[agent, "a-menu", "a-policy", "a-guard"]]
    if lay == "driver":
        return [["a-guard", "a-seal", "a-driver"]]
    if lay == "device" and s.get("from") == "driver":
        return [["a-driver", here]]
    if lay == "buyer" and stage == "order":
        return []                                     # the order waits with the buyer until the coordinator asks
    if frm and (to or here) != frm and layer_of_anchor(frm) != layer_of_anchor(to or here):
        return [[frm, to or here]]
    if prev is not None and prev.get("_here") and layer_of_anchor(prev["_here"]) != layer_of_anchor(here):
        return [[prev["_here"], here]]
    return []


def play_length(s: dict[str, Any], lay: str, stage: str, seen: dict[str, Any]) -> float:
    """How long a step plays, in seconds, from how much it says. The first two calls on a node in the morning's
    preparation play at full length, and the rest of the same walk go quicker."""
    lines = s.get("terminal") or []
    d = 1.0 + min(2.0, sum(len(str(t.get("text") or "")) for t in lines) / 900)
    if lay == "town":
        d = .8
    if len(lines) > 24 or lay == "model":
        d = max(d, 3.0)
    if stage == "prepare" and lay in PREPARE_LAYERS:
        node = str(s.get("node") or "")
        done = seen.setdefault("_calls", {})
        if lay == "guard":
            done[node] = done.get(node, 0) + 1
        if done.get(node, 0) > 2:
            d *= .6
    return round(d, 2)


def ladder(rec: Record, s: dict[str, Any], lay: str, hot: list[str], k: dict[str, str], x: dict[str, Any]) -> None:
    """A step of the followed nodes lights the rungs of their nine steps it belongs to, with what came out of each."""
    node = str(s.get("node") or "")
    if node in (rec.home, rec.uni) and lay in ("home_agent", "building_agent", "model"):
        side = "b" if is_building(node) or lay == "building_agent" else "h"
        for n in step_nos(s):
            hot.append(f"lad-{side}-{n}")
            k[f"lad-{side}-{n}"] = "done"
            own = next((t for t in texts(s) if re.match(rf"{n} [a-z ]+: ", t)), "")
            m = OUT.search(own)
            x[f"ladr-{side}-{n}"] = esc(data(stamp(s.get("sim_time")) + ": " + (m.group(1)[:150] if m else str(s.get("plain") or s.get("title") or ""))))
    if lay in ("building_agent", "model") and node == rec.other:
        x["also-b"] = esc(data(stamp(s.get("sim_time")) + ": " + str(s.get("plain") or "")))


def compile_step(rec: Record, s: dict[str, Any], prev: dict[str, Any] | None, seen: dict[str, Any]) -> dict[str, Any]:
    """One step as the page's data."""
    lay = s.get("layer") or "market"
    stage = s.get("stage") or ""
    ret = stage in RETURN_STAGES and lay != "town"
    here = returning(s, lay, stage) if ret else layer_anchor(s)
    layers = [8] if ret else [LAYER_OF.get(lay, 2)]
    path = step_path(s, lay, stage, here, prev)
    hot = [here]
    k: dict[str, str] = {}
    x: dict[str, Any] = {}
    st: dict[str, Any] = {"x": x}
    ladder(rec, s, lay, hot, k, x)
    out: dict[str, Any] = {"t": stamp(s.get("sim_time")), "y": esc(data(s.get("plain") or s.get("title") or "")), "L": layers, "_here": here}
    if lay == "model":
        queue_state(rec, s, x, st, seen)
    if lay == "guard":
        out["ck"] = guard_state(s, k, x)
    if lay in ("guard", "driver"):
        chain_state(s, lay, x)
    device_state(rec, s, x)
    card_state(s, x)
    if path:
        out["p"] = path
    out["h"] = hot
    out["pk"] = data(str(s.get("title") or "")[:40])
    out["c"] = "b" if lay == "building_agent" else "m" if lay == "model" else HUE.get(layers[0], 4)
    out["d"] = play_length(s, lay, stage, seen)
    out["f"] = "T-" + term_for(s)
    ids = [c for c in (s.get("change_ids") or []) if c in rec.changes]
    if ids:
        out["v"] = [CHANGE_TAG.get(ids[0], "changed"), CHANGE_NAME]
    values_to_state(rec, s, s.get("values") or {}, st, seen)
    grid_state(rec, s.get("values") or {}, st, seen)
    if lay == "town":
        town_state(s, st, seen)
        out["e"] = data(f'{s.get("from")} → {s.get("to")}')
    if st.get("x"):
        out["x"] = st["x"]
    if st.get("w"):
        out["w"] = {a: max(0.0, min(100.0, b)) for a, b in st["w"].items()}
    if k:
        out["k"] = k
    if st.get("g"):
        out["g"] = st["g"]
    return out


def compile_day(rec: Record) -> tuple[dict[str, Any], dict[str, list[Markup]], dict[str, list[Markup]], dict[str, int]]:
    """The whole evening: the steps and stages for the page's data, each terminal's rows, the two chats, and the first
    step that sets each recorded value (so a row of the clearing lights when the run reaches it)."""
    stages: list[dict[str, Any]] = []
    for j, s in enumerate(rec.steps):
        key = s.get("stage")
        if key in STAGE_NAME and not any(g["key"] == key for g in stages):
            stages.append({"n": STAGE_NAME[key], "at": j, "key": key})
    terms: dict[str, list[Markup]] = {t: [] for t in TERMS}
    chats: dict[str, list[Markup]] = {"owner": [], "manager": []}
    tagged: set[tuple[str, str]] = set()
    first_set: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    seen: dict[str, Any] = {}
    prev = None
    for i, s in enumerate(rec.steps):
        term = term_for(s)
        rows = step_rows(rec, s, term, tagged)
        for n, (cls, inner) in enumerate(rows):
            terms[term].append(render("full_record/line.html#li", cls=cls + (" end" if n == len(rows) - 1 else ""), step=str(i), inner=inner))
        if s.get("layer") == "person":
            for who, bubble in bubbles(s, i):
                chats[who].append(bubble)
        c = compile_step(rec, s, prev, seen)
        c["s"] = max((k for k, g in enumerate(stages) if g["at"] <= i), default=0)
        for key in s.get("values") or {}:
            first_set.setdefault(key, i)
        prev = c
        out.append(c)
    for c in out:
        c.pop("_here", None)
    last = out[-1].setdefault("x", {})            # the simulator's own truth closes the column: the half-hour steps carry the monitor's estimate
    for k, h in enumerate(rec.half_hours[:6]):
        last[f"rt-true-{k}"] = kw(h["true_kw"], 1)
    return {"steps": out, "stages": stages}, terms, chats, first_set

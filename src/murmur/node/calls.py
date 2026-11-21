"""A device call as code checks it before it runs: its arguments cleaned against the tool's card, the node's plans by the day, and the desk a node answers."""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
import numpy as np
from murmur.node import drivers as D
from murmur.node import policy as P
from murmur.node import record as R
from murmur.node import tools as T
from murmur.node.guard import blocked


HERE = Path(__file__).parent


MAX_SIMULATE = 4                 # device calls a parameter of kind "calls" may list


TEXT_MAX = 200                   # a model's free text, in characters


SANE = {"kW": (0.0, 1e5), "kWh": (0.0, 1e6), "A": (0.0, 1000.0), "percent": (0.0, 100.0), "C": (-10.0, 10.0)}     # by the unit a card gives


ACT_STEPS = ("6 prepare", "7 watch", "8 exception")


# What a node may say about a shortfall, as the desk reads it. These words are in the gap desk's KNOWN_REASONS (agents/community/gaps.py): anything else reaches the pool as "not given"
SHORT_WORDS = {"device_out": "a device is out", "schedule_changed": "the schedule changed", "owner_need": "an owner's need came first", "forecast_changed": "the forecast changed", "other": "another cause"}


HELD_BY_CONTROLLER = {"set_water_heater": ("hpwh",), "set_pool_pump": ("pool",), "delay_appliance": ("dish", "dryer")}     # devices a home's controller holds by itself


# --------------------------------------------------------------------------------------------------- the arguments
def clean_args(params: list[dict[str, Any]], args: Any) -> tuple[dict[str, Any], str]:
    """(clean values, why not). Stops what the guard shouldn't have to see: bad types, NaN, unknown names, text where a number goes.
    start and end are dropped: code fills them. A number outside its unit's sane range stops here too, and the guard's range check
    for the installed product still follows."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {}, "Arguments must be named values."
    known = {p["name"]: p for p in params if p["name"] not in ("start", "end")}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in ("start", "end") or v is None:
            continue
        p = known.get(k)
        if p is None:
            return {}, f"{str(k)[:40]} isn't a parameter of this tool."
        kind = p["type"]
        if kind == "number":
            x = _number(v)
            lo, hi = SANE.get(p.get("unit", ""), (-1e6, 1e6))
            if x is None or not lo <= x <= hi:
                return {}, f"{k} must be a number from {lo:g} to {hi:g}."
            out[k] = x
        elif kind == "enum" and k != "target":
            allowed = [x.strip() for x in str(p.get("allowed", "")).split("|")]
            if p["name"] == "tool" and allowed == ["this node's tools"]:
                if not isinstance(v, str) or not re.fullmatch(r"[a-z_]{1,40}", v):
                    return {}, "That isn't a tool's name."
            elif v not in allowed:
                return {}, f"{k} must be one of: {', '.join(allowed)}."
            out[k] = v
        elif kind == "time":
            if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                return {}, f"{k} must be a time like 18:30."
            out[k] = v
        elif kind == "calls":
            if not isinstance(v, list) or not 1 <= len(v) <= MAX_SIMULATE or not all(isinstance(c, dict) for c in v):
                return {}, f"{k} must list 1 to {MAX_SIMULATE} device calls."
            out[k] = v
        elif kind == "ids":
            ids = [v] if isinstance(v, str) else v
            if not isinstance(ids, list) or len(ids) > 16 or not all(isinstance(c, str) and re.fullmatch(r"[A-Z][0-9]{0,2}|none", c) for c in ids):
                return {}, f"{k} must list ids like A or R1."
            out[k] = ids
        else:
            if not isinstance(v, str) or len(v) > (64 if k == "target" else TEXT_MAX) or any(ord(c) < 32 for c in v):
                return {}, f"{k} must be plain text, {64 if k == 'target' else TEXT_MAX} characters at most."
            out[k] = v
    return out, ""


def _number(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        x = float(v)
    except (ValueError, OverflowError):           # text, or an integer too long to be a number here
        return None
    return x if math.isfinite(x) else None


def device_params(side: str, tool: str) -> list[dict[str, Any]]:
    b = T.bundle()
    return (b.get(side, {}).get(tool) or b["common"].get(tool) or {"model_view": {"parameters": []}})["model_view"]["parameters"]


def run_call(tool: str, args: Any, start: str, end: str, f: dict[str, Any], side: str, step: str | None, who: P.Who, policy: P.Policy, gate: D.Gate) -> dict[str, Any]:
    """One device call, from the step's menu to the driver. The live path and the replay both run exactly this."""
    target = str(args.get("target", ""))[:64] if isinstance(args, dict) else ""
    out: dict[str, Any] = {"clean": None, "policy": None, "answer": None, "command": None, "driver": None}
    if step not in ACT_STEPS:
        out["answer"] = blocked(target, "This step can't change a device.")
        return out
    if tool not in f["shelf"]:
        out["answer"] = blocked(target, f"This node has no {str(tool)[:40]}.")
        return out
    clean, why = clean_args(device_params(side, tool), args)
    if why:
        out["answer"] = blocked(target, why)
        return out
    out["clean"] = clean
    v = policy.check(who, "call", P.group_of(tool))
    out["policy"] = v
    if not v["allow"]:
        out["answer"] = blocked(target, v["why"])
        return out
    out["answer"] = gate.run({"tool": tool, "args": clean, "start": start, "end": end}, f)
    out["command"], out["driver"] = gate.last.get("command"), gate.last.get("driver")
    out["seal"], out["guard_lines"] = gate.last.get("seal"), gate.last.get("guard_lines")       # recording only: replay compares only record.COMPARE
    return out


def listed(tools: list[dict[str, Any]]) -> dict[str, list[str] | None]:
    """What a turn's tools allow: each tool and the targets it lists, or None for a tool with no target list."""
    return {t["function"]["name"]: (t["function"]["parameters"]["properties"].get("target") or {}).get("enum") for t in tools}


def guard_state(guard: Any) -> dict[str, Any]:
    """What the guard remembers, so a replay can start it from the same place."""
    return R.clean({k: v for k, v in vars(guard).items() if k != "setup" and isinstance(v, (dict, list, set))})


STATES = ("empty", "occupied", "asleep", "home", "away", "open", "closed", "busy", "event")


SOURCES = ("calendar", "timetable", "sensor", "history")


def clean_block(b: dict[str, Any], spaces: set[str]) -> dict[str, Any] | None:
    """The one shape every node gives, and nothing else: titles, names and notes never get past this. A value that isn't on a fixed
    list is replaced, so text can't ride in on a field either."""
    if not isinstance(b, dict):
        return None
    t = re.compile(r"([01]\d|2[0-3]):[0-5]\d|24:00")
    start, end = str(b.get("start", "")), str(b.get("end", ""))
    if not t.fullmatch(start) or not t.fullmatch(end):
        return None
    c = _number(b.get("confidence"))
    return {"space": b.get("space") if b.get("space") in spaces else "a space", "start": start, "end": end, "state": b.get("state") if b.get("state") in STATES else "busy",
            "confidence": round(min(1.0, max(0.0, c or 0.0)), 2), "source": b.get("source") if b.get("source") in SOURCES else "calendar"}


@lru_cache(maxsize=1)
def _home_plans() -> dict[str, Any]:
    z = np.load(HERE / "home_plans_past.npz")
    return {"row": {k: i for i, k in enumerate(z["keys"].tolist())}, "day": {d: i for i, d in enumerate(z["days"].tolist())},
            "state": z["state"], "conf": z["conf"], "leave": z["leave"]}


def _hm(q: int) -> str:
    return f"{q // 4:02d}:{(q % 4) * 15:02d}" if q < 96 else "24:00"


def home_plan(node: str, day: str) -> tuple[list[dict[str, Any]], set[str]]:
    """The day-before plan only: home_plans_past.npz holds no true day."""
    z = _home_plans()
    h, d = z["row"].get(T.home_id(node)), z["day"].get(day)
    spaces = {"whole house", "car"}
    if h is None or d is None:
        return [], spaces
    a, c = z["state"][h, d], z["conf"][h, d]
    cut = [0, *(np.flatnonzero(np.diff(a)) + 1).tolist(), 96]
    names = {0: "empty", 1: "occupied", 2: "asleep"}
    rows = [{"space": "whole house", "start": _hm(s), "end": _hm(e), "state": names[int(a[s])], "confidence": float(c[s:e].mean()) / 100, "source": "calendar"} for s, e in zip(cut, cut[1:])]
    leave = float(z["leave"][h, d])
    if math.isfinite(leave):
        rows.append({"space": "car", "start": "00:00", "end": _hm(int(round(leave * 4))), "state": "home", "confidence": .9, "source": "calendar"})
    return rows, spaces


EVENING_RIGHT = {"shopping_center": .99, "office": .9}       # by building map: the confidence each block of its day-before plan carries


EMPTY_BELOW, BUSY_FROM = .1, .5                                                 # share of a space in use


def building_plan(node: str, day: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Each space by the hour, from the plan made the day before. Below a tenth in use reads as empty."""
    from murmur.node import buildings
    z = buildings.load(node)
    rows: list[dict[str, Any]] = []
    spaces = {s["names"] for s in z.spaces.values()}
    for k, s in z.spaces.items():
        share = [z.plan(k, f"{day} {h:02d}:00") for h in range(24)]
        names = ["closed" if s.get("closed") else "empty" if x < EMPTY_BELOW else "busy" if x >= BUSY_FROM else "occupied" for x in share]
        h0 = 0
        for h in range(1, 25):
            if h == 24 or names[h] != names[h0]:
                rows.append({"space": s["names"], "start": f"{h0:02d}:00", "end": f"{h:02d}:00" if h < 24 else "24:00", "state": names[h0],
                             "confidence": EVENING_RIGHT.get(z.key, .9), "source": "timetable"})
                h0 = h
    return rows, spaces


class Schedule:
    """Calendars stop here: the model gets busy and free blocks, which protects privacy and blocks injection in one step."""

    def __init__(self, side: str, source: Callable[[str, str], tuple[list[dict[str, Any]], set[str]]] | None = None):
        self.source = source or (building_plan if side == "building" else home_plan)

    def blocks(self, node: str, day: str) -> list[dict[str, Any]]:
        rows, spaces = self.source(node, day)
        return [b for b in (clean_block(r, spaces) for r in rows) if b]


# --------------------------------------------------------------------------------------------------- the market side
class Desk:
    """The node's market side, for homes and buildings alike: the member node (node/home.py) serves both. Offers and commitments go through
    MemberNode.handle and the offer rule (node/offer_rule.py); the desk sends step 9's report."""

    def report(self, labelled: dict[str, Any]) -> dict[str, Any]:
        """Step 9's labelled answer goes up to the community agent, signed. It keeps it beside the sale, and no model reads it there."""
        from murmur.protocol import envelope as beckn
        v2 = self.v2
        body = v2.say("on_status", v2.community, f"report-{v2.name}", {"node_report": labelled})
        return {"sent": v2.send(v2.community, beckn.kind("on_status"), body, v2.mid(v2.community, "on_status", "report", labelled.get("sale"), labelled.get("ts")))}

    def __init__(self, v2: Any):
        self.v2 = v2


def offer_request(need: dict[str, Any], safe: dict[str, Any], txn: str | None = None) -> dict[str, Any]:
    """Step 5's request: what the buyer asks and what the planner found safe."""
    sl = need.get("slots") or []
    return {"kind": "offer", "id": need.get("event_id"), "window": (need["window_start"], need["window_end"]), "price": float(sl[0].get("price") or 0.0) if sl else 0.0,
            "asked_kw": [s.get("kw_requested") for s in sl], "reply_by": need.get("commit_by"), "safe": safe, "txn": txn}


def commitment_request(c: dict[str, Any], verdict: dict[str, Any], txn: str | None = None) -> dict[str, Any]:
    """Step 6's request: the commitment and code's own verdict on it."""
    return {"kind": "commitment", "id": c.get("id"), "window": (c.get("window_start"), c.get("window_end")), "contract": c, "verdict": verdict, "txn": txn,
            "kw": [s.get("kw") for s in c.get("commitments", [])], "reply_by": c.get("opt_out_by")}


# --------------------------------------------------------------------------------------------------- the server
def device_write(node: Any) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]:
    """What a call changes on this simulated node. A building's needs the device and the facts too."""
    if getattr(node, "zm", None) is None:
        return lambda call, ans, f: node.apply(call, ans)
    from murmur.node.building_levers import apply_call

    def write(call: dict[str, Any], ans: dict[str, Any], f: dict[str, Any]) -> None:
        d = next((x for x in f["devices"].values() if x["tool"] == call["tool"] and x["target"] == ans["target"]), None)
        apply_call(node.sim, node.zm, call, ans, d, f)
    return write

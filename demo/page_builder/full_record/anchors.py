"""Where a recorded step stands on the sheet: its terminal, the block it lights (its anchor), the layer an anchor sits in,
and which of the nine steps of a node it belongs to."""
from __future__ import annotations

import re
from typing import Any

from .naming import is_building, is_home

RETURN_STAGES = ("readings", "settlement")
TERMINAL_OF = {"buyer": "buy", "coordinator": "coord", "market": "coord", "model": "queue", "guard": "tools", "driver": "tools", "device": "dev", "person": "people"}

# Words in a coordinator step's title, and the block they light; otherwise its stage says
CO_WORDS = [(("second round",), "a-co-round2"), (("picks the reserve", "reserve is set"), "a-co-margin"), (("homes against",), "a-co-hb"), (("what the nodes are asked", "deposits still hold"), "a-co-reserve"),
            (("working starts", "joins the same sale", "own forecast"), "a-co-book"), (("offers by kind", "the book", "move the peak"), "a-co-clear"), (("all offers are in", "call for offers"), "a-co-offers"),
            (("frozen", "each node gets"), "a-co-contract")]
CO_STAGE = {"order": "a-co-book", "offers": "a-co-offers", "clearing": "a-co-clear", "contract": "a-co-contract", "prepare": "a-co-desk", "delivery": "a-co-desk", "exception": "a-co-desk",
            "readings": "a-rp-checks", "settlement": "a-rp-settle", "report": "a-co-desk"}

# Words in a device's name, and the row of the appliance table it lights
DEVICE_WORDS = [("campus", r"campus-battery"), ("plant", r"plant|chiller|zones?\b|air-handler|standby"), ("lights", r"light"), ("plugs", r"plug|outlet"),
                ("battery", r"battery|powerwall"), ("car", r"\bcar\b|car-|charger|ev-"), ("cooling", r"thermostat|room-ac|heat-pump"), ("water", r"water|dish|dryer|pool")]

# An actor's name, and the block it stands for
ACTORS = {"utility": "a-util", "buyers": "a-util", "grid-operator": "a-grid", "grid_operator": "a-grid", "model": "a-queue", "qwen": "a-queue", "brain": "a-queue", "queue": "a-queue",
          "guard": "a-guard", "safety_guard": "a-guard", "driver": "a-driver", "owner": "a-owner", "home_owner": "a-owner", "people": "a-owner", "owners and managers": "a-owner",
          "manager": "a-manager", "facility_manager": "a-manager", "building_manager": "a-manager", "all": "a-cells", "nodes": "a-cells", "homes": "a-cells", "community": "a-cells",
          "all nodes": "a-cells", "all members": "a-cells", "members": "a-cells"}
MEMBERS = re.compile(r"\d+ members?")
LAYER_ANCHOR = {"town": "a-town", "home_agent": "a-home", "building_agent": "a-bld", "model": "a-queue", "guard": "a-guard", "driver": "a-driver"}

# Which layer an anchor sits in, by the start of its name, so a path is drawn only between layers
ANCHOR_LAYER = (("a-util", 1), ("a-grid", 1), ("a-co-", 2), ("a-town", 3), ("a-home", 4), ("a-bld", 4), ("a-queue", 4), ("a-cells", 4), ("a-menu", 5), ("a-policy", 5),
                ("a-guard", 5), ("a-seal", 5), ("a-driver", 5), ("a-dv", 6), ("a-owner", 7), ("a-manager", 7), ("a-rp", 8))
STEP_NUMBERS = re.compile(r"\b[Ss]teps?\s+([1-9])(?:\s+to\s+([1-9]))?")

# The small model's answers, by words in the step's title
QUEUE_KINDS = [("offer", ("offer",)), ("accept", ("accept", "commitment")), ("plan", ("plan",)), ("note", ("note",)), ("report", ("report",)), ("margin", ("margin", "reserve"))]


def term_for(s: dict[str, Any]) -> str:
    """The terminal a step's lines go to."""
    lay = s.get("layer")
    if lay == "town":
        return "town"
    if s.get("stage") in RETURN_STAGES:
        return "ret"
    if lay == "home_agent":
        return "home"
    if lay == "building_agent":
        return "bld"
    return TERMINAL_OF.get(lay, "coord")


def co_anchor(stage: str, title: str) -> str:
    t = title.lower()
    for words, a in CO_WORDS:
        if any(w in t for w in words):
            return a
    return CO_STAGE.get(stage, "a-co-book")


def device_anchor(name: str) -> str | None:
    n = name.lower()
    for key, pat in DEVICE_WORDS:
        if re.search(pat, n):
            return f"a-dv-{key}"
    return None


def anchor_of(actor: Any, s: dict[str, Any]) -> str | None:
    """The block a step's sender or receiver stands for."""
    a = str(actor or "")
    if a == "coordinator":
        return co_anchor(s.get("stage") or "", str(s.get("title") or ""))
    if is_home(a):
        return "a-home"
    if is_building(a):
        return "a-bld"
    if a in ACTORS:
        return ACTORS[a]
    if MEMBERS.fullmatch(a):
        return "a-cells"
    return device_anchor(a)


def layer_anchor(s: dict[str, Any]) -> str:
    """The block a step lights, by its layer."""
    lay = s.get("layer")
    if lay == "buyer":
        return "a-grid" if str(s.get("from") or "").startswith("grid") or str(s.get("to") or "").startswith("grid") else "a-util"
    if lay in ("coordinator", "market"):
        return co_anchor(s.get("stage") or "", str(s.get("title") or ""))
    if lay == "device":
        return device_anchor(str(s.get("to") or "")) or "a-devs"
    if lay == "person":
        return "a-manager" if is_building(s.get("node")) or "manager" in str(s.get("to") or s.get("from")) else "a-owner"
    return LAYER_ANCHOR[lay]


def layer_of_anchor(a: str) -> int:
    for pre, n in ANCHOR_LAYER:
        if a.startswith(pre):
            return n
    return 0


def step_nos(s: dict[str, Any]) -> list[int]:
    """Which of the nine steps a recorded step belongs to, from its title."""
    m = STEP_NUMBERS.search(str(s.get("title") or ""))
    if m:
        a = int(m.group(1))
        return list(range(a, int(m.group(2) or a) + 1))
    return []


def queue_kind(s: dict[str, Any]) -> str:
    """Which kind of answer the small model gave at a model step."""
    low = str(s.get("title") or "").lower()
    return next((k for k, words in QUEUE_KINDS if any(w in low for w in words)), "other")

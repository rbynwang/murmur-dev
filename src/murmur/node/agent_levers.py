"""The levers a node's agent works through: the comfort slot the plan reads, the devices a call opens, and what a fact bears on."""
from __future__ import annotations

import os
from typing import Any
from murmur.node.control import inside, person_limit
from murmur.node.see import MACHINE_TARGET
from murmur.node import note_reader


LEAD_MIN = int(os.environ.get("MURMUR_LEAD_MIN", "30"))     # the agent plans the sale this long before it opens. A run on a fast clock needs more: planning every node takes wall time


MAX_OPTIONS = 8        # lines in a plan's list of what can open, and of what runs


MACHINE_KEY = {v: k for k, v in MACHINE_TARGET.items()}


OPENS = "The sale opens."   # what changed, when every node is an agent and the opening is a plan of its own (node/modes.py)


NO_REASON = "no reason given"           # a receipt's word for an answer that said nothing of why, even when asked again


CAME_UP_SHORT = "The equipment gave less than the plan expected."       # the person hears this when the calls, not the agent's choice, left kW uncovered: a plan's own reason is written before its calls run, so it can't say how they came out


# --------------------------------------------------------------------------------------------------- the controller's side
def write_comfort(sim: Any, value: dict[str, float] | None = None) -> None:
    """The agent's door to the slot the plan reads. It never passes what a person said, which is in comfort_limit and isn't the agent's to write. None hands the slot back to the person."""
    said = sim.overrides.get("comfort_limit")
    if value is not None:
        sim.overrides["comfort"] = inside(value, said)
    elif said:
        sim.overrides["comfort"] = dict(said)
    else:
        sim.overrides.pop("comfort", None)


def open_levers(sim: Any) -> None:
    """From now on the controller uses only what the agent's calls open."""
    # the car's own lever is its kW, so it stays in "devices" and gives nothing until a call sets that
    sim.levers = {"battery_kw": 0.0, "ev": False, "ev_kw": None, "v2h_kw": 0.0, "v2h_kwh": None, "devices": {"v2h"}}
    write_comfort(sim, held_comfort(sim))


def held_comfort(sim: Any) -> dict[str, float]:
    """No easing, and no pre-cooling below where the house is: extra cooling before a sale nobody opened is load nobody pays for."""
    return {"max_rise_c": 0.0, "max_rise_away_c": 0.0, "precool_c": max(0.0, -sim.x)}


def close_levers(sim: Any) -> None:
    """Every write ends by itself, and the device goes back to its own day."""
    sim.levers = None
    write_comfort(sim)


def apply_call(sim: Any, call: dict[str, Any], ans: dict[str, Any]) -> None:
    tool, v = call["tool"], ans["applied"]
    lev = sim.levers
    if tool == "set_battery":
        lev["battery_kw"] = float(v.get("kw", 0.0)) if v.get("action") == "discharge" else 0.0
    elif tool == "limit_ev_charging":
        lev["ev"] = True
        amps = float(v.get("amps", 0.0))
        lev["ev_kw"] = amps * 240 / 1000 if amps > 0 else None
    elif tool == "discharge_car":
        lev["v2h_kw"] = float(v.get("kw", 0.0))
        lev["v2h_kwh"] = float(v["max_kwh"]) if v.get("max_kwh") else None
        lev["ev"] = True        # one charger can't draw and give at once, so a car that gives holds its charger, as the controller does on rules
    elif tool in ("set_thermostat", "set_room_ac"):
        c = float(v.get("less_comfort_c", 0.0))
        # each keeps its own limit: the call is sized for who is home now, and a home that fills up in the sale goes back to the tighter one
        write_comfort(sim, {**held_comfort(sim), "max_rise_c": min(c, person_limit(sim, "max_rise_c")), "max_rise_away_c": min(c, person_limit(sim, "max_rise_away_c"))})
    elif tool == "set_water_heater" and v.get("action") == "hold":
        lev["devices"].add("hpwh")
    elif tool == "set_pool_pump":
        lev["devices"].add("pool")
    elif tool == "delay_appliance":
        lev["devices"].add(MACHINE_KEY[ans["target"]])


def fact(says: str, key: str, about: tuple[str, ...] = (), spaces: list[str] | None = None) -> dict[str, Any]:
    """What a plan may cite. about: the parts of the node it bears on. spaces: for a fact about certain rooms, those rooms, and nothing else. key: which fact this is, however its figures move."""
    return {"says": says, "key": key, "about": list(about), **({"spaces": list(spaces)} if spaces else {})}


def bears_on(x: dict[str, Any], tool: str, spaces: Any = None, closed: bool = False) -> bool:
    """Does this fact bear on this call? A fact bears only on the parts of the node it names: a reading of one floor says nothing about a battery. About certain rooms, a fact can end
    a call that presses on them. To keep something closed (closed=True) all of it must lie in those rooms, so one room's reading can't keep every zone of a campus shut."""
    rooms = set(x.get("spaces") or ())
    if rooms:
        have = set(spaces or ())
        return bool(have) and (have <= rooms if closed else bool(have & rooms))
    return note_reader.PART_OF.get(tool) in x["about"]

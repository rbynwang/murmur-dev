"""A building's levers as its agent works them: comfort per zone, the plant, plug loads, and the morning's pre-cool times."""
from __future__ import annotations

import re
from typing import Any
from murmur.node.agent import write_comfort
from murmur.node.see_building import comfort_c


PRE_COOL = {"shopping_center": ("08:00", "11:00"), "office": ("07:00", "13:00")}   # the playbook's pre-cool hours, by building map


PRE_RAMP_MIN = 120     # how long the pull-down takes: well inside the card's limit, 0.25 C a step


# what the card tests' sentences say that a plan doesn't need: orders the letters carry out by themselves, and constants that read as sensors
re_order = re.compile(r" ?(Its zones aren't eased yet(: call set_zone_standby first)?\.|The plant can't cap until these zones are eased\.|Its zones are eased\.|Zones are set to coast\.|Call set_zone_standby with mode off\.|Live lab load reads normal\.)| and every room has a working sensor")


# --------------------------------------------------------------------------------------------------- the controller's side
def comfort(sim: Any, rise: float) -> dict[str, float]:
    """The plan may let the building rise this far, and may not cool it below where it is: extra cooling is a call of its own, not a closed lever."""
    cap = getattr(sim, "person_rise", None)     # a person's tighter limit holds through every step's rewrite
    rise = rise if cap is None else min(rise, cap)
    return {"max_rise_c": rise, "max_rise_away_c": rise, "precool_c": max(0.0, -sim.x)}


def sync_comfort(sim: Any, zm: Any, free: dict[str, float]) -> float:
    """The rise the building may reach now: from its zones' offsets, or a stopped plant's limits, and who is in the rooms."""
    lev = sim.levers
    zones = dict(lev["zones"])
    if any(p.get("stop") for p in lev["plants"].values()):
        zones = {s: 3.0 for s in zm.spaces}
    c = comfort_c(zm, zones, free)
    write_comfort(sim, comfort(sim, c))
    return c


def sync_plant(sim: Any, f: dict[str, Any]) -> None:
    """Caps and stops force cooling down from their start to their end: the share of the building's own cooling they hold off."""
    live = [p for p in sim.levers["plants"].values() if not p.get("released")]
    sim.house.cut_span = (min((p["from"] for p in live), default=""), max((p["to"] for p in live), default="9"))
    if any(p.get("stop") for p in live):
        sim.house.cut = 1.0
        return
    sim.house.cut = min(1.0, sum(p["kw"] for p in live) / max(1e-6, f["cool_kw"]))


def _add(sim: Any, device: str, kw: float, total: float) -> None:
    dev = sim.levers["dev"]
    dev[device] = min(1.0, dev.get(device, 0.0) + kw / max(1e-6, total))


def _take(sim: Any, device: str, kw: float, total: float) -> None:
    dev = sim.levers["dev"]
    dev[device] = max(0.0, dev.get(device, 0.0) - kw / max(1e-6, total))


def apply_call(sim: Any, zm: Any, call: dict[str, Any], ans: dict[str, Any], d: dict[str, Any], f: dict[str, Any]) -> None:
    tool, v, lev, kw = call["tool"], ans["applied"], sim.levers, float(ans["expected_kw"])
    t = ans["target"]
    if lev is None:
        return                                      # the morning's pre-cool: BuildingAgent._pre_cool plays it
    if tool == "set_battery":
        lev["battery_kw"] = float(v.get("kw", 0.0)) if v.get("action") == "discharge" else 0.0
    elif tool == "limit_ev_charging":
        lev["dev"]["ev"] = 1.0 if not v.get("amps") else min(1.0, kw / max(1e-6, d["kw_now"]))
    elif tool == "set_plant_demand_limit":
        lev["plants"][t] = {"kw": kw, "from": call["start"], "to": call["end"]}
        sync_plant(sim, f)
    elif tool == "stop_plant_early":
        lev["plants"][t] = {"kw": kw, "stop": True, "from": call["start"], "to": call["end"]}
        sync_plant(sim, f)
        sync_comfort(sim, zm, f["free"])
    elif tool == "set_zone_cooling":
        c = float(v.get("offset_c", 0.0))
        if c > 0:
            lev["zones"].update({s: c for s in d["spaces"]})
            _until(lev, "zones", d["spaces"], call["end"], f)
            sync_comfort(sim, zm, f["free"])
            if d.get("tenant_fan_kw"):
                _add(sim, "fans", d["tenant_fan_kw"] * min(1.0, c / 1.5), f["fans_kw"])
    elif tool == "set_zone_standby":
        lev["standby"] = (lev["standby"] | set(d["spaces"])) if v.get("mode") == "on" else (lev["standby"] - set(d["spaces"]))
        if v.get("mode") == "on":
            _until(lev, "standby", d["spaces"], call["end"], f)
    elif tool == "limit_air_handler":
        lev["fans"][t] = kw
        _add(sim, "fans", kw, f["fans_kw"])
    elif tool == "dim_lights":
        lev["lights"].update({s: float(v.get("cut_percent", 0.0)) for s in d["spaces"]})
        lev["light_share"] = min(1.0, lev["light_share"] + kw / max(1e-6, sum(sim.house.light_kw(x) for x in f["steps"]) / max(1, len(f["steps"]))))
    elif tool == "switch_plugs":
        if v.get("state") == "off":
            lev["plugs"][t] = kw
            _add(sim, "plugs", kw, _plugs_kw(sim, f))
        else:
            _add(sim, "plugs", -lev["plugs"].pop(t, 0.0), _plugs_kw(sim, f))


def _until(lev: dict[str, Any], kind: str, spaces: list[str], end: str, f: dict[str, Any]) -> None:
    """A write ends by itself. Most end with the sale, when the levers close. A booking can end a zone's sooner, and that end is kept here."""
    if end < f["sale"]["end"]:
        lev["until"].update({(kind, s): end for s in spaces})


def _plugs_kw(sim: Any, f: dict[str, Any]) -> float:
    from murmur.node.see import window_mean
    sale = f["sale"]
    return window_mean(sim, "plugs", sale["start"], sale["end"])

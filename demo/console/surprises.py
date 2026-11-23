"""A presenter's surprise, posted to the door that makes it happen (the specification's 5.3).

Each surprise is posted once, at a quarter-hour the clock has not yet played (`at`, a dataset time), through the parts adapter, so
its answer is kept with it for the story. The stops it sets make the clock play what follows instead of leaping over it.
"""
from __future__ import annotations

from typing import Any

from .timeline import shift

AFTER = (15, 30, 45, 60)          # minutes after `at` the clock plays, so the network's answer to a surprise is seen


def doors(c: dict[str, Any], at: str, hosts: list[str]) -> list[tuple[str, str, dict[str, Any]]]:
    """(part, path, body) for each post a checked surprise command makes."""
    k, who = c["kind"], c.get("who")
    if k == "note":
        return [("homes", "/demo/scenario", {"override": {"home": who, "kind": "note", "value": c["text"], "source": "owner's phone"}})]
    if k == "car_now":
        return [("homes", "/demo/scenario", {"override": {"home": who, "kind": "ev_now", "value": True, "source": "owner's phone"}})]
    if k == "weather":
        body = {"weather": {"pv": c["pv"], "load": c["load"], "dT": c["dT"], "from": at, "hours": c["hours"]}}
        return [(h, "/demo/scenario", body) for h in hosts]
    if k == "building_closed":
        return [("buildings", f"/b/{who}/demo/scenario", {"closed": {"at": at}})]
    if k == "building_need":
        return [("buildings", f"/b/{who}/demo/scenario", {"zone_event": {"at": at, "share": c["share"], "hours": c["hours"]}})]
    if k == "emergency":
        return [(c["buyer"], "/alert", {"kw": c["kw"], "minutes": c["minutes"], "why": "grid emergency", "at": at})]
    if k == "battery_fault":
        return [("homes", "/demo/scenario", {"battery_fault": {"homes": [who], "on": c["on"]}})]
    return [("homes", "/demo/scenario", {"battery_soc": {"homes": [who], "pct": c["pct"]}})]


def stops(c: dict[str, Any], at: str) -> list[str]:
    """The quarter-hours the clock plays after a surprise: the next hour, and for an emergency to its end and 45 minutes more."""
    out = [shift(at, m) for m in (0, *AFTER)]
    if c["kind"] == "emergency":
        out += [shift(at, m) for m in range(0, int(c["minutes"]) + 60, 15)]
    return sorted(set(out))

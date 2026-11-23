"""What the console derives from the runner's settings before an evening: the nodes its story follows, the page's names for them,
what a live evening is made from, the roster a presenter picks a surprise's node from, and the network's label.
"""
from __future__ import annotations

import json
from typing import Any

from demo.page_builder import names as N

NETS = {"one": "One computer", "first": "Three machines", "standin": "Three machines, with stand-ins", "standby": "Stand-by",
        "rehearsal": "Rehearsal"}
OFFICE, SHOP = "building-02", "building-01"          # the page's ids for an office and for a shopping center (page_builder/names.py)


def follow_of(s: Any, named: list[str] | None = None) -> list[str]:
    """The nodes the story follows: those named, else the home a configured note is for (else the first), the next home, and the
    first building."""
    if named:
        return list(named)
    homes = s.homes
    noted = next((h for e in s.events if e.get("kind") == "note" for h in e.get("homes") or [] if h in homes), homes[0] if homes else None)
    rest = [h for h in homes if h != noted]
    return [x for x in [noted, rest[0] if rest else None, (s.buildings or [None])[0]] if x]


def alias_of(s: Any) -> dict[str, str]:
    """Each building by the page's name for its kind: an office is the page's office, any other building its shopping center."""
    try:
        data = json.loads((s.data_dir / "buildings.json").read_text())
    except (OSError, ValueError):
        return {}
    rows = data.items() if isinstance(data, dict) else ((str(x.get("id")), x) for x in data if isinstance(x, dict))
    out = {}
    for bid, row in rows:
        if bid in s.buildings:
            out[bid] = OFFICE if "office" in json.dumps(row).lower() else SHOP
    return {k: v for k, v in out.items() if k != v and list(out.values()).count(v) == 1}


def half_hours(window: list[str]) -> list[str]:
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in window)
    b += 1440 if b <= a else 0
    return [f"{(m // 60) % 24:02d}:{m % 60:02d}" for m in range(a, b, 30)]


def facts_of(s: Any, follow: list[str]) -> dict[str, Any]:
    """What a LiveEvening is made from (page_builder/live/evening.py)."""
    homes = [x for x in follow if x.startswith("home-")]
    builds = [x for x in follow if x.startswith("building-")]
    model = "stand-in" if (s.model or {}).get("stand_in") else str((s.model or {}).get("name") or "")
    return {"day": s.evening["date"], "homes": s.homes, "buildings": s.buildings, "sites": list(s.sites), "window": s.evening["window"],
            "follow": {"thinking_home": homes[0] if homes else None, "second_home": homes[1] if len(homes) > 1 else None,
                       "mall_or_office": builds[0] if builds else None},
            "half_hours": half_hours(s.evening["window"]), "model": model}


def roster_of(s: Any, alias: dict[str, str], telemetry: dict[str, Any] | None) -> dict[str, Any]:
    """Who a presenter may name in a surprise: each home with whether it has a battery (its telemetry's E above 0), each building,
    each buyer. Names are the page's."""
    keys, rows = (telemetry or {}).get("keys") or [], (telemetry or {}).get("homes") or {}
    e = keys.index("E") if "E" in keys else None

    def battery(h: str) -> bool:
        row = rows.get(h)
        return bool(row and e is not None and e < len(row) and isinstance(row[e], (int, float)) and row[e] > 0)
    return {"homes": [{"id": h, "name": N.name_of(alias.get(h, h), start=True), "battery": battery(h)} for h in s.homes],
            "buildings": [{"id": b, "name": N.name_of(alias.get(b, b), start=True)} for b in s.buildings],
            "buyers": list(s.buyers)}

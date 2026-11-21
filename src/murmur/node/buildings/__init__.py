"""The zone maps: each building's tool targets, its kW share of each end use, and which zones are occupied when."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).parent
EVENT = .15        # sensors reading this far above the plan: an added event or a late meeting, not noise
BUSY = .10         # at or above this share in use a space counts as booked
MAPS = {"mall": "shopping_center", "office": "office"}      # a building's map, by the stem of its dataset profile (buildings/mall -> mall)


def _read(path: Path) -> dict[str, Any]:
    z = np.load(path)
    return {"row": {k: i for i, k in enumerate(z["keys"].tolist())}, "day": {d: i for i, d in enumerate(z["days"].tolist())},
            "plan": z["plan"], "true": z["true"]}


@lru_cache(maxsize=1)
def _schedules() -> dict[str, Any]:
    return _read(HERE / "schedules.npz")


@lru_cache(maxsize=1)
def _dataset_schedules() -> dict[str, Any] | None:
    """A dataset on other dates than the year these maps were written for brings its own days: buildings/schedules.npz, in the same layout.
    None where the dataset has none. The year's own days are always read from the year's own file."""
    try:
        from murmur.config import DATA_DIR
        f = DATA_DIR / "buildings" / "schedules.npz"
        return _read(f) if f.exists() else None
    except (OSError, ValueError, KeyError):
        return None


class ZoneMap:
    def __init__(self, key: str):
        self.key = key
        self.m = json.loads((HERE / f"{key}.json").read_text())
        self.spaces: dict[str, dict[str, Any]] = self.m["spaces"]
        self.plants: dict[str, dict[str, Any]] = self.m["plants"]
        self.targets: dict[str, list[dict[str, Any]]] = self.m["targets"]
        self.limits: dict[str, Any] = self.m.get("limits") or {}
        self.surprises: list[dict[str, Any]] = []        # what node/surprises.py puts on the true day: {from, to, space (None: all), share}

    def _at(self, kind: str, space: str, ts: str) -> float:
        for s in (_schedules(), _dataset_schedules()):
            if s is None:
                continue
            r = s["row"].get(f'{self.m["schedule"]}/{self.spaces[space]["schedule"]}')
            d = s["day"].get(ts[:10])
            if r is not None and d is not None:
                return float(s[kind][r, d, int(ts[11:13])])
        return 1.0                                                                        # no record reads as in use: the guard's "unknown counts as occupied"

    def plan(self, space: str, ts: str) -> float:
        """The share of this space in use at this hour, by the plan made the day before."""
        return self._at("plan", space, ts)

    def true(self, space: str, ts: str) -> float:
        """The share in use now, as the sensors read it. Never call this for a time still to come."""
        for e in self.surprises:
            if e["from"] <= ts < e["to"] and e.get("space") in (None, space):
                return float(e["share"])
        return self._at("true", space, ts)

    def use(self, space: str, now: str, steps: list[str]) -> float:
        """The share in use over these steps: the plan, or what the sensors read now if that is more. A clear miss reads as an event, which may last."""
        if not steps:
            return self.plan(space, now)
        read = self.true(space, now)
        event = read - self.plan(space, now) >= EVENT
        return sum(max(self.plan(space, t), read if event or t[:13] == now[:13] else 0.0) for t in steps) / len(steps)

    def state(self, space: str, ts: str) -> str:
        """free or booked at this hour, by the plan. A shopping center is open or closed."""
        use = self.plan(space, ts)
        if not self.m.get("sale_free"):
            return "open" if use > 0 else "closed"
        return "booked" if use >= BUSY else "free"

    def avoid(self, space: str, ts: str) -> str | None:
        """Why this space is off limits today: exams at the campus, Black Friday to Christmas at the mall."""
        return next((a["why"] for a in self.m.get("avoid", []) if a["from"] <= ts[:10] <= a["to"] and space in a["spaces"]), None)


@lru_cache(maxsize=None)
def _load(key: str) -> ZoneMap:
    return ZoneMap(key)


@lru_cache(maxsize=1)
def _profiles() -> dict[str, str]:
    from murmur import config
    try:
        return {b["name"]: Path(str(b.get("profile") or "")).name for b in json.loads(config.data_path("buildings.json").read_text())["buildings"]}
    except (OSError, ValueError, KeyError):
        return {}


def map_key(name: str) -> str | None:
    """The map a building node uses: its own name when that is a map, else the map of its dataset profile, else None."""
    if (HERE / f"{name}.json").exists():
        return name
    return MAPS.get(_profiles().get(name, ""))


def known(name: str) -> bool:
    return map_key(name) is not None


def load(name: str) -> ZoneMap:
    """A building's map, by its map name or its node name."""
    key = map_key(name)
    if key is None:
        raise KeyError(f"no zone map for {name}")
    return _load(key)

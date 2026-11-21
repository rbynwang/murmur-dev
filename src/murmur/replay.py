"""The dataset's replay clock: wall-clock time mapped onto the dataset's 15-minute steps.

A profile is a dataset file stem (homes/HH001 -> homes/HH001.csv.gz and homes/HH001_ev.csv); the dataset's profile_alias may name one.
All participants agree on the step at the same wall moment (an absolute line set by the community agent), and a held clock stays on its
step until it is set again.
"""
from __future__ import annotations

import csv
import gzip
import threading
import time
from datetime import datetime
from typing import Any

from murmur.config import data_path, dataset_meta

FMT = "%Y-%m-%d %H:%M"
_CACHE: dict[str, tuple[list, dict, list]] = {}
_LOCK = threading.Lock()

# What-if weather (POST /demo/scenario on each node host, as the demo runner's evening sends it): from dataset time
# `from` on, every home's solar is scaled by `pv` and its household load by `load`. It changes the physical truth of
# this process's homes only (actual and no-event twin alike: the same homes in the same weather); forecasts made
# earlier do not know it, as with a real surprise. Off (None) by default and after every demo reset.
WEATHER: dict[str, Any] = {"from": None, "pv": 1.0, "load": 1.0, "dT": 0.0, "to": None}



def set_weather(pv: float | None = None, load: float | None = None, frm: str | None = None, to: str | None = None,
                dT: float | None = None) -> dict[str, Any]:
    """Change the what-if weather from dataset time `frm` on (until `to`, if given); pv = load = 1 and dT = 0 switch
    it off. dT: degrees C warmer (cooler if negative) than measured."""
    pv = WEATHER["pv"] if pv is None else max(0.0, min(1.5, float(pv)))
    load = WEATHER["load"] if load is None else max(0.5, min(2.0, float(load)))
    dT = WEATHER.get("dT", 0.0) if dT is None else max(-15.0, min(15.0, float(dT)))
    on = abs(pv - 1.0) > 1e-6 or abs(load - 1.0) > 1e-6 or abs(dT) > 1e-6
    WEATHER.update({"pv": pv, "load": load, "dT": dT, "from": (frm or WEATHER["from"]) if on else None,
                    "to": (to if to is not None else WEATHER.get("to")) if on else None})
    return dict(WEATHER)


def _load(profile: str):
    with _LOCK:
        if profile in _CACHE:
            return _CACHE[profile]
        name = dataset_meta().get("profile_alias", {}).get(profile, profile)   # the dataset's own name for a profile
        stem, ev_name = (name, f"{name}_ev.csv") if "/" in name else (f"home_{name}", f"ev_{name}.csv")
        with gzip.open(data_path(f"{stem}.csv.gz"), "rt") as f:
            rows = [dict(r) for r in csv.DictReader(f)]
        for r in rows:
            blank = tuple(k for k in r if k != "ts_local" and r.get(k) in (None, ""))
            for k in list(r):
                if k != "ts_local":                     # every other column is a number (fc_* = forecast as issued)
                    r[k] = float(r[k]) if r.get(k) not in (None, "") else 0.0
            if blank:                                   # a blank cell is no reading, never 0 kW: the number above is only there for code that needs one, and a forecast reads this instead (node/forecast.py)
                r["_missing"] = blank
        index: dict[str, int] = {}
        for i, r in enumerate(rows):
            index.setdefault(r["ts_local"], i)        # the repeated hour when clocks fall back keeps its first copy
        sessions = []
        with open(data_path(ev_name)) as f:
            for r in csv.DictReader(f):
                sessions.append({"arrival": r["arrival_local"], "deadline": r["deadline_local"],
                                 "kwh": float(r["kwh"]), "max_kw": float(r["max_kw"]), "plug_in": r.get("plug_in_local") or None})
        _CACHE[profile] = (rows, index, sessions)
        return _CACHE[profile]


class Replay:
    def __init__(self, profile: str, start: str, step_seconds: float, loop_days: int = 1):
        self.profile = profile
        self.rows, self.index, self.sessions = _load(profile)
        self.arrivals = {s["arrival"]: s for s in self.sessions}          # a session starts charging: at the plug-in or at a timer
        self.plugins = {s["plug_in"]: s for s in self.sessions if s.get("plug_in")}   # empty on a dataset without plug-in times
        self.at_wall: float | None = None
        # this clock's own what-if weather, for this node alone (node/surprises.py: a building closed for the day
        # runs on a share of its load); None: the process's WEATHER
        self.weather: dict[str, Any] | None = None
        self.configure(start, step_seconds, loop_days)

    def configure(self, start: str, step_seconds: float, loop_days: int = 1, at: str | None = None,
                  at_wall: float | None = None, hold: bool = False) -> None:
        """`at`: jump so that the current step shows that dataset time. With `at_wall` (unix seconds) and
        loop_days = 0 the jump is absolute, so agents configured at different moments still agree; without it the
        jump counts from now. hold: stay on that step until the clock is set again."""
        if start not in self.index:
            raise ValueError(f"replay start {start!r} not in dataset")
        step, loop = float(step_seconds), int(loop_days)
        i0, aw = self.index[start], None
        held = i0
        if at:
            if at not in self.index:
                raise ValueError(f"replay time {at!r} not in dataset")
            held = self.index[at]
            if loop == 0:
                i0, aw = held, (float(at_wall) if at_wall is not None else None)
            else:                                    # a looping clock runs on the wall clock: the step the wall is at now shows `at`
                i0 = held - int(time.time() // step) % (loop * 96)
            start = self.ts(max(0, i0))
        # Looping replays are anchored to the wall clock (not to process start), so every machine with
        # an NTP-synced clock and the same settings plays the same dataset step at the same moment.
        wall0 = aw if aw is not None else (0.0 if loop > 0 else time.time())
        # one assignment, so a thread reading the clock while it changes (a change of speed mid-run) sees the old
        # line or the new one, never half of each
        self._line = (wall0, step, i0, loop, held if hold else None)
        self.start, self.step_seconds, self.loop_days, self.i0, self.at_wall, self.wall0 = start, step, loop, i0, aw, wall0

    @property
    def held(self) -> bool:
        return self._line[4] is not None

    def current(self) -> int:
        wall0, step, i0, loop, held = self._line
        if held is not None:
            return max(0, min(held, len(self.rows) - 1))
        k = int((time.time() - wall0) // step)
        if loop > 0:
            k %= loop * 96
        return max(0, min(i0 + k, len(self.rows) - 1))


    def clock(self) -> dict[str, Any]:
        return {"start": self.start, "step_seconds": self.step_seconds, "loop_days": self.loop_days,
                "at_wall": self.at_wall, "now": self.ts(self.current()), "held": self.held}

    def row(self, i: int) -> dict[str, Any]:
        r = self.rows[max(0, min(i, len(self.rows) - 1))]
        w = self.weather if self.weather is not None else WEATHER
        ts = r["ts_local"]
        if w.get("from") and ts >= w["from"] and (not w.get("to") or ts < w["to"]):
            r = {**r, "pv_kw": r["pv_kw"] * w.get("pv", 1.0), "base_kw": r["base_kw"] * w.get("load", 1.0)}
            if w.get("dT"):
                r["temp_c"] = r.get("temp_c", 0.0) + w["dT"]
        return r

    def ts(self, i: int) -> str:
        return self.row(i)["ts_local"]

    def idx_of(self, ts: str) -> int | None:
        return self.index.get(ts)

    def session_starting(self, i: int) -> dict[str, Any] | None:
        return self.arrivals.get(self.ts(i))

    def session_plugging(self, i: int) -> dict[str, Any] | None:
        """The session whose car is plugged in at this step. A timer home's car waits here until its session starts."""
        return self.plugins.get(self.ts(i))

    def columns(self, names: tuple[str, ...]) -> dict[str, Any]:
        """The record as numpy columns, for the agents' forecasts. A what-if (self.weather, WEATHER) is left out: it starts after any
        day-ahead forecast is made."""
        import numpy as np
        return {k: np.fromiter((r[k] for r in self.rows), dtype=float, count=len(self.rows)) if k in self.rows[0] else np.full(len(self.rows), np.nan) for k in names}

    @staticmethod
    def minutes_between(a: str, b: str) -> float:
        return (datetime.strptime(b, FMT) - datetime.strptime(a, FMT)).total_seconds() / 60.0

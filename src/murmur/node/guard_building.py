"""The guard for a building's device calls: plain code, the same checks as a home's for a building's tools.

A zone that is closed, has an event or is occupied keeps its own comfort; the fans and the fresh air are never touched; the plant may
only stop early once its zones can coast; a battery keeps its reserve.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from murmur.node.guard import STOPPED, Guard, blocked, off_list
from murmur.node.guard_building_rules import RECOVER_MIN, clock, day_of, good, mins, span, with_times
from murmur.node.guard_building_tools import BuildingGuardTools
from murmur.node import note_words
from murmur.node import note_reader

POINT = {"set_zone_cooling": "zone", "set_zone_standby": "mode", "limit_air_handler": "fan", "set_plant_demand_limit": "plant", "stop_plant_early": "plant",
         "dim_lights": "light", "switch_plugs": "plug", "set_battery": "battery", "limit_ev_charging": "ev"}   # a cap and a stop on one plant are one writer
CONFIRM_MIN = {"set_zone_cooling": 30, "set_zone_standby": 5, "limit_air_handler": 10, "set_plant_demand_limit": 10, "stop_plant_early": 10,
               "dim_lights": 35, "switch_plugs": 5, "set_battery": 5, "limit_ev_charging": 5}
MAX_WRITE_MIN = 1440             # every write ends by itself, and applied only says HH:MM, so a call can't reach past a day
CLIMATE = {"set_zone_cooling", "set_zone_standby", "limit_air_handler", "set_plant_demand_limit", "stop_plant_early"}   # what "leave the house as it is" means here


class BuildingGuard(BuildingGuardTools, Guard):
    """One per node. writers holds each point's running calls, day_stops the day's one plant stop."""

    def __init__(self, setup: dict[str, Any] | None = None):
        super().__init__(setup)
        self.writers: dict[str, list[dict[str, Any]]] = {}
        self.day_stops: dict[str, str] = {}
        self.mode_writes: dict[str, int] = {}
        self.mode_day: str | None = None                  # the day mode_writes counts. A box's stored writes are by the day, so a new sale or a restart mustn't start them again

    def clear(self) -> None:
        self.writers.clear()

    def kept(self) -> set[str]:
        """The tools a manager's wish stops. note_reader.BLOCKS names a home's tools, so keep_house_as_is reaches the climate tools here."""
        out = note_reader.blocked_tools(self.wishes)
        return out | CLIMATE if any(w["wish"] == "keep_house_as_is" for w in self.wishes) else out

    def check(self, call: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
        tool, a = call["tool"], call.get("args")
        a = dict(a) if isinstance(a, dict) else {}
        target = str(a.get("target", ""))
        if f.get("alarm"):                                                      # step 1
            return blocked(target, "An alarm is on, so nothing is sent and every agent limit releases.")
        if f.get("stopped"):
            return blocked(target, STOPPED)
        if tool not in f["shelf"]:                                              # step 2
            return blocked(target, f"This node has no {tool}.")
        d = next((x for x in f["devices"].values() if x["tool"] == tool and x["target"] == target), None)
        if d is None:
            return self._no_target(tool, target, a, f, call)
        sale = f.get("sale") or {}
        if any(call.get(k) and not good(call[k]) for k in ("start", "end")):
            return blocked(target, "start and end must be local HH:MM.")
        if not call.get("start") or not call.get("end"):                        # step 3: every write ends by itself
            fill = {"start": clock(mins(call.get("start") or sale["start"])), "end": clock(mins(sale["end"]))} if sale else {}
            return blocked(target, "Every write needs a start and an end.", {"tool": tool, **a, **fill})
        s, e = span(call)
        if e <= s:
            return blocked(target, "end must come after start.")
        if e - s > MAX_WRITE_MIN:
            return blocked(target, "A write ends by itself within a day.")
        keeps = tool == "set_battery" and a.get("action") in ("hold", "charge")
        if tool in self.kept() and not keeps:                                   # step 5: the owner first
            return blocked(target, note_words.why(tool, self.wishes))
        hidden = off_list(f, tool, target)                                      # step 2: a writer giving back its own call needs no list
        if hidden and not (tool == "set_zone_standby" and a.get("mode") == "off") and not (tool == "switch_plugs" and a.get("state") == "auto"):
            return blocked(target, hidden)
        try:
            ans = getattr(self, "_" + tool)(a, d, f, call)                      # steps 3 to 5
        except (KeyError, TypeError, ValueError, AttributeError) as exc:        # no reading, no write
            return blocked(target, f"A reading this call needs is missing ({exc}), so nothing was sent.")
        if ans.pop("released", False):                                          # a writer ending its own call
            ans["confirm_by"] = clock(s + CONFIRM_MIN[tool])
            return ans
        if ans["status"] in ("done", "adjusted"):                               # step 6
            clash = self._clash(tool, d, s, e)
            if clash:
                later = {"tool": tool, **a, "start": clock(clash["end"]), "end": clock(e)} if clash["end"] < e else None
                return blocked(target, f'{clash["says"]} runs until {clock(clash["end"])}, and the later call wins only after it ends.', later)
            give = float(ans["applied"].get("kw", 0.0)) if ans["applied"].get("action") == "discharge" else 0.0
            for p in self._points(tool, d):
                self.writers.setdefault(p, []).append({"start": s, "end": e, "tool": tool, "target": target, "says": self._says(tool), "kw": give})
            ans["confirm_by"] = clock(s + (5 if tool == "dim_lights" and ans["applied"].get("cut_percent") == 100 else CONFIRM_MIN[tool]))
            if tool == "stop_plant_early":
                self.day_stops[target] = day_of(call, f)
            if tool == "set_zone_standby" and d.get("write_limit"):             # only a write that goes out counts against the box
                self.mode_writes[target] = self.mode_writes.get(target, 0) + 2
        return ans

    # ------------------------------------------------------------------ steps 2 and 6
    def _no_target(self, tool, target, a, f, call):
        alt = (f.get("instead") or {}).get(target)
        if alt:
            return blocked(target, alt["why"], with_times({"tool": alt.get("tool", tool), **{**a, **alt.get("args", {})}, "target": alt["target"]}, call))
        if any(w in target for w in f.get("never", ())):
            return blocked(target, f"{target} is on the never-touched list.")
        names = [x["target"] for x in f["devices"].values() if x["tool"] == tool]
        return blocked(target, f"{target or 'That target'} can't take this call now.", {"tool": tool, "target": names[0]} if names else None)

    @staticmethod
    def _points(tool: str, d: dict[str, Any]) -> list[str]:
        return [f"{POINT[tool]}:{p}" for p in (d.get("points") or [d["target"]])]

    @staticmethod
    def _says(tool: str) -> str:
        return {"plant": "A call on this plant"}.get(POINT[tool], "An earlier call here")

    def _clash(self, tool, d, s, e):
        for p in self._points(tool, d):
            for w in self.writers.get(p, []):
                if w["start"] < e and s < w["end"]:
                    return w
        return None

    def _end(self, tool: str, d: dict[str, Any], at: int) -> list[dict[str, Any]]:
        """A writer ends its own running call at this minute."""
        out = []
        for p in self._points(tool, d):
            for w in self.writers.get(p, []):
                if w["start"] <= at < w["end"]:
                    w["end"] = at
                    out.append(w)
        return out

    # ------------------------------------------------------------------ what stops any zone tool
    @staticmethod
    def _back_by(d: dict[str, Any], call: dict[str, Any]) -> int | None:
        """The minute this zone must be back at temperature, on the call's own clock. A booking earlier than the start is tomorrow's."""
        nb = d.get("next_booking")
        if not nb:
            return None
        m = mins(nb)
        return (m + 1440 if m < span(call)[0] else m) - RECOVER_MIN

    @staticmethod
    def _zone_stop(d: dict[str, Any]) -> str | None:
        if d.get("exam"):
            return "A room in this group is in an exam, so it is never touched."
        if d.get("avoid"):
            return f'This is a time to avoid: {d["avoid"]}.'
        if not d["smoke_ok"]:
            return "Rule out a smoke role before any write to this unit."
        if d["closet"]:
            return "A unit in this group also cools a closet, and the driver can't separate them."
        if d["override"]:
            return "An occupant override is running, and it beats the agent."
        if d["humid"]:
            return "Humidity ends the event: dew point is past 15 C or RH is past 65%."
        return None


    def _promised(self, d: dict[str, Any], f: dict[str, Any]) -> float:
        """kWh that calls already running or queued will still take from this battery. Each call alone can pass and the sum still reach under the reserve."""
        now = mins(f["now"]) if f.get("now") else 0
        return sum(w["kw"] * max(0, w["end"] - max(w["start"], now)) / 60.0 for p in self._points("set_battery", d) for w in self.writers.get(p, []))


    @staticmethod
    def _car_ok(x, amps, s, e, volts, day=None):
        """Does the car still get what it needs by the time it leaves? A clock time before the call is tomorrow morning."""
        left = str(x.get("leaves") or "23:59")
        leaves = mins(left)
        if len(left) > 5 and day:
            leaves += 1440 * (date.fromisoformat(left[:10]) - date.fromisoformat(day)).days
        elif leaves < s:
            leaves += 1440
        need = float(x.get("need_kwh", 0.0))
        if need <= 0:
            return True
        rate = volts * x["amps"] / 1000
        got = volts * amps / 1000 * max(0, min(e, leaves) - s) / 60 + rate * max(0, leaves - e) / 60
        return got >= need - 1e-6

    # ------------------------------------------------------------------ the reading that proves it
    def confirm(self, tool: str, call: dict[str, Any], ans: dict[str, Any], reading: dict[str, Any]) -> dict[str, Any]:
        """At confirm_by: `failed` when the device didn't do what was sent. Sent values stay in `applied`, so the record shows both."""
        t = ans["target"]
        late = reading.get("failed")
        if not late:
            return ans
        return {**ans, "status": "failed", "expected_kw": round(float(reading.get("kw", 0.0)), 2), "why": reading.get("why", f"{late} did not respond.")}

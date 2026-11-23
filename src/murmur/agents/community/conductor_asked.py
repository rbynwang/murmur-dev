"""What a driver asks of the waiting clock through the agent's doors (doors.py), and what the clock says of itself.

A driver is whoever plays the evening: the demo runner, a presenter's console. It starts an evening, sets the gates and the stops, the pace of a
played step and whether the clock leaps over empty time, holds the clock, lets it go on, plays a number of steps, or runs it to a step.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from murmur.agents.community.community_rules import number

LEAP_MAX = 12                  # quarter hours one leap covers at most (cfg clock_leap_max_steps): the meter rows an older node host gives back after one move of its clock. A host of this code gives back 192 (agents/host_doors.py)


class ConductorAsked:
    """The clock's settings and its door: what a driver sets, and the view a driver reads."""

    # ------------------------------------------------------------------ the settings
    @property
    def leap(self) -> bool:
        """Does the clock leap over empty quarter hours? Only when asked: at the door, at a start, or by cfg clock_leap."""
        return bool(self.c.cfg.get("clock_leap") if self.cond["leap"] is None else self.cond["leap"])

    def leap_max(self) -> int:
        """How far one leap goes at most, in quarter hours: cfg clock_leap_max_steps, from 1 to 192, which is as many as a home steps one by one
        when its clock has moved on (node/simulator.py)."""
        return max(1, min(96 * 2, int(self.c.cfg.get("clock_leap_max_steps", LEAP_MAX))))

    def pace(self) -> float:
        """The least wall time a played step lasts: what the driver set (0: as fast as the network finishes the step), else the participants' own
        step_seconds; never under cfg clock_min_step_s, the floor of a deployment whose participants cannot all say how far they are."""
        own = self.c.clock.step_seconds if self.cond["pace"] is None else self.cond["pace"]
        return max(float(own), float(self.c.cfg.get("clock_min_step_s", 0.0)))

    def quick(self) -> bool:
        """Does the clock run faster than it always did: leaping, or playing a step in less than the participants' own step_seconds? Then a
        step's pace no longer covers the time an inbox takes to be looked at, and a played step waits that time out by itself
        (ConductorWaits.bus_waits)."""
        return self.leap or self.pace() < float(self.c.clock.step_seconds)

    # ------------------------------------------------------------------ what the doors ask (doors.py)
    def started(self, at_wall: float, pace_s: float | None = None, leap: bool | None = None) -> None:
        """An evening starts at this wall time, every clock just set (POST /demo/start, under self.lock): the count of steps and the record begin
        again, nothing holds the clock, and it plays at this pace (None: the participants' step_seconds), leaping if asked (None: as it was).
        Gates and stops stay: a runner sets them first."""
        self.cond.update(since=at_wall, waits=None, changed=0.0, went_on=deque(maxlen=200), steps=0, held_s=0.0, at_gate=None, unreached=set(),
                         started=True, pace=pace_s, hold=False, budget=None, run_to=None, opened=set(), empty=False, came=None, heard=set(), seen=[],
                         done=None, caught=None, leaping=None, leaps=deque(maxlen=50), played=deque(maxlen=50))
        if leap is not None:
            self.cond["leap"] = leap
        self.wake()

    def set_gates(self, steps: list[Any]) -> None:
        """The steps the clock stops before, held one step earlier with everything else done, until each is opened. A new list takes the old one's
        place. A gate the clock stands at that the new list leaves out counts as opened: what was posted there is still played."""
        was, self.cond["gates"], self.cond["at_gate"] = self.cond["at_gate"], {str(x) for x in steps}, None
        if was and was not in self.cond["gates"]:
            self.gate_opened(was)

    def open_gate(self, ts: Any) -> None:
        """Opens one gate: the clock moves on to that step at its next pass."""
        self.cond["gates"].discard(str(ts))
        if self.cond["at_gate"] == str(ts):
            self.cond["at_gate"] = None
        self.gate_opened(str(ts))

    def asked(self, body: dict[str, Any]) -> None:
        """A driver's word at the clock's door (POST /demo/conductor), any of these together:

          {"gates": [step, ...]}   the steps the clock stops before, until each is opened with {"open": step}
          {"stops": [step, ...]}   steps that must be played: a leap lands on each. They do not hold the clock. A new list takes the old one's place
          {"leap": true}           leap over empty quarter hours; false: play every step
          {"pace_s": 1.5}          the least wall time a played step lasts, 0 to 120; 0: as fast as the network finishes it
          {"hold": true}           stop once the step in hand is finished; false: go on
          {"step": 3}              play that many steps, a leap counting as one, then hold
          {"run_to": step}         go on, leaping where the clock leaps, and hold on arrival at that step

        A word that can't be read is refused whole (ValueError), and nothing of it is done."""
        cond, r = self.cond, self.c.clock
        stops, pace, n, to = body.get("stops"), body.get("pace_s"), body.get("step"), body.get("run_to")
        if stops is not None and not (isinstance(stops, list) and all(isinstance(x, str) and r.idx_of(x) is not None for x in stops)):
            raise ValueError("stops is a list of steps of the data, each YYYY-MM-DD HH:MM")
        if pace is not None and not (number(pace) and 0 <= pace <= 120):
            raise ValueError("pace_s is 0 to 120 seconds")
        if any(body.get(k) is not None and not isinstance(body[k], bool) for k in ("leap", "hold")):
            raise ValueError("leap and hold are true or false")
        if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 1000):
            raise ValueError("step is how many steps to play, 1 to 1000")
        if to is not None and not (isinstance(to, str) and r.idx_of(to) is not None and r.idx_of(to) > r.current()):
            raise ValueError("run_to is a step of the data after the one the clock holds")
        if isinstance(body.get("gates"), list):
            self.set_gates(body["gates"])
        if body.get("open"):
            self.open_gate(body["open"])
        if stops is not None:
            cond["stops"] = set(stops)
        if body.get("leap") is not None:
            cond["leap"] = body["leap"]
        if pace is not None:
            cond["pace"] = float(pace)
        if body.get("hold") is not None:
            cond["hold"], cond["budget"] = body["hold"], None
        if n is not None:
            cond["hold"], cond["budget"] = False, n
        if to is not None:
            cond["hold"], cond["budget"], cond["run_to"] = False, None, to
        self.wake()

    # ------------------------------------------------------------------ what the clock says
    def mode(self) -> str:
        """What the clock is doing: "idle" before a start; "ended" on the last step of the data; "at_gate" or "held" once the step in hand is
        finished and a gate or the driver keeps the clock there; "leaping" on an empty step, while every participant catches up; else "playing",
        and "waiting" once a played step has lasted its pace and something is still waited on."""
        r, cond = self.c.clock, self.cond
        if not cond["started"] or not self.c.cfg.get("clock_waits") or r.at_wall is None or not r.held:
            return "idle"
        if r.current() >= len(r.rows) - 1:
            return "ended"
        if cond["done"] is not None and (cond["at_gate"] or cond["hold"]):
            return "at_gate" if cond["at_gate"] else "held"
        if cond["empty"]:
            return "leaping"
        return "waiting" if cond["waits"] and self.wall() >= cond["since"] + self.pace() else "playing"

    def view(self) -> dict[str, Any]:
        """The waiting clock: steps moved, seconds held beyond the pace, every time it went on without something; its mode, its pace, whether it
        leaps and how far, whether the driver holds it, the driver's stops and the next step that must be played, and its last leaps and played steps."""
        c, cond = self.c, self.cond
        i = c.clock.current()
        stop = self.next_stop(i)
        return {"on": bool(c.cfg.get("clock_waits")), "now": c.clock.ts(i), "held": c.clock.held, "steps": cond["steps"],
                "held_s": round(cond["held_s"], 1), "waiting_on": list(cond["waits"] or ()), "went_on": list(cond["went_on"]),
                "gates": sorted(cond["gates"]), "at_gate": cond["at_gate"], "mode": self.mode(), "pace_s": self.pace(), "leap": self.leap,
                "leap_max_steps": self.leap_max(), "hold": cond["hold"], "stops": sorted(cond["stops"]),
                "next_stop": None if stop is None else c.clock.ts(stop), "leaps": list(cond["leaps"]), "played": list(cond["played"])}

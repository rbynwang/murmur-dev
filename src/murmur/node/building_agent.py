"""A building's agent: the member agent with a building's tools, words, guard and levers.

A building's devices are its zones' cooling, its air handlers, its plant, its lights, its plug loads and its car ports; a zone's own day
(open, closed, an event) and the manager's comfort limit bound every call.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from murmur.node import buildings
from murmur.node import tools as T
from murmur.node.agent import CUSHION, LEAD_MIN, NodeAgent, write_comfort
from murmur.node.guard_building_rules import RAMP_MIN
from murmur.node.guard_building import CLIMATE, BuildingGuard
from murmur.node.see_building import can_act, free_shares, see_building, steps_of
from murmur.node.building_levers import PRE_COOL, comfort, sync_comfort
from murmur.node.building_plan import BuildingPlan
from murmur.node import note_reader

STANDBY_LEAD_MIN = 15
PRE_LEAD_MIN = 10
HELD_DEVICES = {"cooling": "fans", "car": "ev", "devices": "plugs"}      # the building's own devices each part takes with it


def open_levers(sim: Any) -> None:
    """From now on the controller uses only what the agent's calls open."""
    sim.levers = {"battery_kw": 0.0, "ev": False, "ev_kw": None, "v2h_kw": 0.0, "light_share": 0.0, "dev": {}, "zones": {}, "standby": set(), "plants": {}, "lights": {},
                  "fans": {}, "plugs": {}, "released": None, "until": {}}
    write_comfort(sim, comfort(sim, 0.0))
    sim.house.cut = 0.0
    sim.hold_cold = False


def close_levers(sim: Any) -> None:
    """Every write ends by itself, and the building goes back to its own day."""
    sim.levers = None
    write_comfort(sim)
    sim.house.cut = 0.0


# --------------------------------------------------------------------------------------------------- the agent
class BuildingAgent(BuildingPlan, NodeAgent):
    word = "building"

    def __init__(self, home: Any, brain: Any, record: Callable[[dict[str, Any]], None] | None = None, log: Any = None):
        self.zm = buildings.load(home.name)
        self.retry: dict[tuple[str, str], tuple[str, str]] = {}
        self.noticed: set[str] = set()
        self.seen_release: str | None = None
        self.prepared: str | None = None
        self.pre: dict[str, Any] | None = None
        self.held_devices: set[str] = set()         # what hold_out took out of the sale, so it can give back that and no more
        super().__init__(home, 0, brain, record, log)

    # ------------------------------------------------------------------ what differs by node
    def tools(self) -> list[str]:
        return T.building_shelf(self.zm.key)

    def make_guard(self) -> BuildingGuard:
        return BuildingGuard({"zones": self.zm.key})

    def view(self, ts: str, sale: dict[str, Any], owed: float | None = None) -> dict[str, Any]:
        f = see_building(self.sim, ts, sale, self.shelf, self.zm, self.owed_now(sale) if owed is None else owed)
        f["steps"] = steps_of(self.sim, max(ts, sale["start"]), sale["end"])
        self.view_plan(f)
        return f


    def limits_now(self) -> dict[str, float]:
        return {**super().limits_now(), "lights": self.sim.light_limit()}

    def shrink(self, f: dict[str, Any]) -> None:
        """The lights share one limit, so each call keeps its part of it. The rest give what their device can now give."""
        lev = self.sim.levers
        share, limit = float(lev.get("light_share", 0.0)), self.sim.light_limit()
        k = min(1.0, limit / share) if share > 0 else 1.0
        lev["light_share"] = min(share, limit)
        for c in self.calls:
            d = next((x for x in f["devices"].values() if x["tool"] == c["tool"] and x["target"] == c["target"]), None)
            if c["tool"] == "dim_lights":
                self.cap_call(c, c["expected_kw"] * k)
            elif d is not None and c["tool"] in ("set_zone_cooling", "limit_air_handler", "switch_plugs"):
                self.cap_call(c, float(d.get("gives_kw", d.get("can_give_kw", 0.0))))

    def gives(self, target: str, kw: float) -> str:
        return f"{target} gives {kw:,.0f} kW."

    def open(self) -> None:
        open_levers(self.sim)
        self.guard.clear()                          # an alarm or a lost model ends a sale without the usual close
        self.noticed.clear()
        self.retry.clear()
        self.seen_release = None

    def close(self) -> None:
        self.hold_out(set())
        close_levers(self.sim)

    def hold_out(self, keep: set[str]) -> None:
        """What a wish keeps out, with no levers open: the building is the controller's, and these limits hold there. Without them a note at a building with no levers
        open would be read and recorded, and change nothing the controller does. keep: the tools kept out, or nothing to hand the building back."""
        sim = self.sim
        parts = {note_reader.PART_OF.get(t) for t in keep}
        off = {d for p, d in HELD_DEVICES.items() if p in parts} & set(getattr(sim, "app", None) or ())
        sim.dev_off = (set(sim.dev_off) - self.held_devices) | off
        self.held_devices = off
        sim.held_out = parts
        if self.sim.levers is None:
            write_comfort(sim, comfort(sim, 0.0) if "cooling" in parts else None)

    def all_open(self, keep: set[str]) -> None:
        """For could_give: with no levers the plan may use every device. A wish or a closed group can't open all but a few, so then the sum stays with what's open."""
        if not keep:
            self.sim.levers = None

    def replan(self) -> None:
        """A building has more points than a home, and a stop or a cap can't be run twice: what's running stays, and the plan picks from the rest."""


    def reopen(self, blocked: set[str]) -> None:
        """Take back what a manager's wish stops, at once. note_reader.BLOCKS names a home's tools: a building's levers sit elsewhere."""
        super().reopen(blocked)
        lev = self.sim.levers
        if "dim_lights" in blocked:                 # keep_lights_on: every dim ends at once
            lev["lights"].clear()
            lev["light_share"] = 0.0
        if "limit_ev_charging" in blocked:
            lev["dev"].pop("ev", None)
        if "switch_plugs" in blocked:               # keep_machines_on
            lev["plugs"].clear()
            lev["dev"].pop("plugs", None)
        if blocked & {"set_thermostat", "set_room_ac"}:         # keep_house_as_is: the climate tools leave the sale
            lev["zones"].clear()
            lev["standby"].clear()
            lev["plants"].clear()
            lev["until"].clear()
            self.sim.house.cut = 0.0
            taken = sum(lev["fans"].values())
            lev["fans"].clear()
            if taken:
                lev["dev"]["fans"] = 0.0
            self.calls = [c for c in self.calls if c["tool"] not in CLIMATE]
            write_comfort(self.sim, comfort(self.sim, 0.0))

    def amount(self, tool: str, args: Any, f: dict[str, Any], owed: float) -> Any:
        """The list gives one ready number, which can be far more than is left to sell: a light cut or a battery's discharge can be worth many times what is owed, and the
        building would give kW the sale doesn't pay for. Code only lowers it here: the device stays as chosen, and what it gives is arithmetic."""
        d = next((x for x in f["devices"].values() if x["tool"] == tool and x["target"] == args.get("target")), None)
        want = owed * CUSHION
        if d is None or want <= 0:
            return args
        if tool == "set_battery" and args.get("action") == "discharge" and isinstance(args.get("kw"), (int, float)):
            return {**args, "kw": round(min(float(args["kw"]), want), 1)}
        if tool == "dim_lights" and isinstance(args.get("cut_percent"), (int, float)) and args["cut_percent"] != 100:
            full = float(d.get("running_kw", 0.0)) * float(d.get("scale", 1.0))
            return {**args, "cut_percent": max(1, min(float(args["cut_percent"]), math.ceil(100 * want / max(1e-6, full))))} if full > 0 else args
        return args

    def expire(self, ts: str) -> None:
        """A call that ends before the sale does ends here. The next step played is the one after ts."""
        from murmur.protocol.envelope import add_minutes
        lev, nxt = self.sim.levers, add_minutes(ts, 15)
        gone = [k for k, e in lev["until"].items() if e <= nxt]
        for kind, s in gone:
            del lev["until"][(kind, s)]
            if kind == "zones":
                lev["zones"].pop(s, None)
            else:
                lev["standby"].discard(s)
        if gone:
            self.calls = [c for c in self.calls if c["tool"] not in ("set_zone_cooling", "set_zone_standby") or not any(s in c.get("spaces", ()) for _, s in gone)]

    # ------------------------------------------------------------------ times, from the cards
    def times(self, tool: str, a: dict[str, Any], d: dict[str, Any] | None, sale: dict[str, Any], ts: str) -> tuple[str, str]:
        """In a sale step code fills start and end. Where people may be in, the ramp starts 30 minutes early, so it ends as the window opens."""
        from murmur.protocol.envelope import add_minutes
        k = (tool, str(a.get("target", "")))
        if k in self.retry:
            return self.retry.pop(k)
        s, e = sale["start"], sale["end"]
        t0 = max(ts, s)
        lead = max(ts, add_minutes(s, -RAMP_MIN))
        if tool == "dim_lights":
            return (ts if a.get("cut_percent") == 100 else lead), e
        if tool == "set_zone_cooling" and (d or {}).get("state") != "free":
            return lead, e
        if tool == "set_zone_standby":
            return max(ts, add_minutes(s, -STANDBY_LEAD_MIN)), e
        return t0, e


    # ------------------------------------------------------------------ when to wake
    def watch(self, ts: str, sale: dict[str, Any]) -> str | None:
        """The schedule watch: sensors far above the plan mean an event, so the rise falls now, and the agent hears why."""
        out = None
        for s, sp in self.zm.spaces.items():
            if s not in self.noticed and self.zm.true(s, ts) - self.zm.plan(s, ts) >= buildings.EVENT:
                self.noticed.add(s)
                self.sim.levers.setdefault("events", set()).add(s)
                out = f'{sp["names"]} read {self.zm.true(s, ts) * 100:.0f}% in use, and the plan said {self.zm.plan(s, ts) * 100:.0f}%.'
        return out

    def step(self, ts: str) -> None:
        alarm = self.sim.overrides.get("alarm") or self.sim.overrides.get("alarm_hold") or self.ctx.stopped
        if alarm:
            self.ctx.alarm(alarm, ts)               # nothing is sent and every agent limit releases
            self.calls = []
            self.guard.clear()
            self.pre = None                         # the morning's pre-cool is an agent limit too
            self.sim.hold_cold = False
            write_comfort(self.sim)
            return
        from murmur.protocol.envelope import add_minutes
        sale = self.sale(ts)
        self._pre_cool(ts)
        if sale and self.prepared != sale["start"] and ts < add_minutes(sale["start"], -LEAD_MIN):
            at = add_minutes(f'{ts[:10]} {PRE_COOL[self.zm.key][0]}', -PRE_LEAD_MIN)
            if at <= ts < f'{ts[:10]} {PRE_COOL[self.zm.key][1]}':
                self.prepared = sale["start"]
                self.steps.append(("6 prepare", ts))
                self.ctx.enter("6 prepare", ts, sale)
                self.prepare(ts, sale)
                self.ctx.leave()
        running = self.sim.levers is not None
        super().step(ts)
        sale = self.sale(ts)
        if not running or self.sim.levers is None or not sale or ts >= sale["end"] or ts < sale["start"]:
            self.wake_zones(ts)
            return
        why = self.watch(ts, sale)
        free = free_shares(self.zm, ts, steps_of(self.sim, ts, sale["end"]))
        had = bool(self.sim.levers["zones"])
        self.expire(ts)
        if had or any(p.get("stop") for p in self.sim.levers["plants"].values()):
            sync_comfort(self.sim, self.zm, free)
        released = self.sim.levers.get("released")
        if released and released != self.seen_release:
            self.seen_release = released
            for t, p in self.sim.levers["plants"].items():
                p["released"] = True                # called and used up: it doesn't come back in this sale
                self.log_calls.append({"target": t, "status": "released", "expected_kw": 0.0, "why": f"Zones reached their limit at {ts[11:16]}, so the plant came back."})
            self.calls = [c for c in self.calls if c["tool"] not in ("set_plant_demand_limit", "stop_plant_early")]
            why = "The plant was released: zones reached their limit."
        if why:
            self.last_wake = ts
            self.steps.append(("8 exception", ts))
            self.ctx.enter("8 exception", ts, sale)
            self.decide(ts, sale, why)
            self.ctx.leave()
        self.wake_zones(ts)

    def wake_zones(self, ts: str) -> None:
        """Standby stops a zone's outdoor air, so whatever the agent decides, it ends once the zone's sensors read people: a zone the plan calls free can still fill."""
        lev = self.sim.levers
        if lev is not None and lev.get("standby"):
            lev["standby"] = {x for x in lev["standby"] if self.zm.true(x, ts) < buildings.BUSY}

    # ------------------------------------------------------------------ what a call needs, and what it costs
    def can(self, f: dict[str, Any], d: dict[str, Any]) -> bool:
        return can_act(f, d)

    def may_decide(self) -> bool:
        return self.sim.levers is not None and not self.sim.overrides.get("stop")     # an alarm, a stop or a lost model took the node out of this sale

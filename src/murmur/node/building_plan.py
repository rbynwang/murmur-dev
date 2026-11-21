"""A building's plan steps: the morning's pre-cool, what each zone and plant call gives and waits on, and a call let go."""
from __future__ import annotations

from typing import Any
from murmur.node import buildings
from murmur.node import policy as P
from murmur.node import tools as T
from murmur.node.agent_levers import fact, write_comfort
from murmur.node.see_building import see_building
from murmur.node import modes as arm
from murmur.node.guard_building_rules import EMPTY_C, OPEN_C
from murmur.node.see_building import line
from murmur.node.building_levers import PRE_COOL, PRE_RAMP_MIN, _plugs_kw, _take, re_order, sync_comfort, sync_plant


class BuildingPlan:
    """A building's plan steps: the morning's pre-cool, what each zone and plant call gives and waits on, and a call let go."""

    # ------------------------------------------------------------------ the morning of a sale
    def prepare(self, ts: str, sale: dict[str, Any]) -> None:
        """Before a cooling sale: pre-cool, so the stored cold is there when the sale opens. Code's one call, through the same guard."""
        if self.sim.overrides.get("stop"):
            return                                  # a closed building or a person's stop: no sale to cool for
        self.prepare_by_code(ts, sale)

    @staticmethod
    def precool_facts(target: str, depth: float, t0: str, t1: str, sale: dict[str, Any]) -> list[dict[str, str]]:
        """What a pre-cool rests on: what the playbook allows, and the sale it is for."""
        return [{"id": "playbook", "says": f"The playbook lets {target} go {depth:g} C below its setpoint from {t0[11:16]} to {t1[11:16]}."},
                {"id": "sale", "says": f'A sale runs {sale["start"][11:16]} to {sale["end"][11:16]} today, and cooling will be running then.'}]

    def _pre_cool(self, ts: str) -> None:
        """The controller's side of a pre-cool: the setpoint comes down slowly, or the pull-down is a new morning peak. At its end the write ends
        by itself, and the stored cold stays in the mass."""
        p = self.pre
        if not p or ts < p["from"]:
            return
        if self.sim.overrides.get("stop"):          # a person took the node out: this write ends now
            self.pre = None
            self.sim.hold_cold = False
            write_comfort(self.sim)
            return
        if self.sim.levers is not None:             # the sale's levers are open: its offsets decide now
            self.pre = None
            return
        from murmur.protocol.envelope import add_minutes
        if add_minutes(ts, 15) >= p["until"]:       # the next step played is the one after ts
            self.pre = None
            write_comfort(self.sim)
            return
        c = p["c"] * min(1.0, (self.sim.replay.minutes_between(p["from"], ts) + 15) / PRE_RAMP_MIN)
        write_comfort(self.sim, {"max_rise_c": c, "max_rise_away_c": c})

    # ------------------------------------------------------------------ one step
    def prepare_by_code(self, ts: str, sale: dict[str, Any]) -> None:
        """The morning's pre-cool: the playbook's one number, through the same call, guard and record, with its receipt."""
        if self.sim.overrides.get("stop"):
            return
        day = ts[:10]
        t0, t1 = (f"{day} {x}" for x in PRE_COOL[self.zm.key])
        f = see_building(self.sim, ts, sale, self.shelf, self.zm, 0.0)
        whole = next((x for x in self.zm.targets["set_zone_cooling"] if x.get("whole")), None)
        d = f["devices"].get(f'set_zone_cooling:{whole["target"]}') if whole else None
        if not d or not d["running"] or d.get("exam") or d.get("avoid") or d.get("smoke_ok") is False:
            return
        args = {"target": d["target"], "offset_c": -float(d["precool_c"])}
        if hasattr(self.ctx, "show"):
            self.ctx.show([T.spec("building", "set_zone_cooling", [d["target"]])])
        rec = {**self.blank(ts, "pre-cool", 0.0, text=f'Code: pre-cool {t0[11:16]} to {t1[11:16]}, {d["target"]} to {args["offset_c"]:g} C.'), "tier": 0, "answer": [{"name": "set_zone_cooling", "args": args}]}
        ans = self.ctx.act("set_zone_cooling", args, start=t0, end=t1, facts={**f, "sale": None}, who=P.CODE)
        rec["verdicts"].append({"call": {"tool": "set_zone_cooling", "args": args, "start": t0, "end": t1}, "answer": ans})
        v = float(ans["applied"].get("offset_c", 0.0))
        if ans["status"] in ("done", "adjusted") and v < 0:
            self.sim.hold_cold = True
            self.pre = {"c": v, "from": t0, "until": t1}
        self.receipt("pre-cool", ts, asked={"sale": [sale["start"], sale["end"]], "may_go_c": args["offset_c"]}, rule={"offset_c": args["offset_c"], "from": t0, "until": t1},
                         chose={"offset_c": v}, reason=arm.BY_CODE_SAYS, facts=self.precool_facts(d["target"], float(d["precool_c"]), t0, t1, sale), flags=[],
                         by=f"rule: {arm.BY_CODE}", less=False)
        self.record(rec)
        self.guard.clear()

    def ready(self, d: dict[str, Any], f: dict[str, Any], owed: float) -> dict[str, Any]:
        tool, t = d["tool"], d["target"]
        if tool == "set_battery":
            return {"target": t, "action": "discharge", "kw": d["can_give_kw"]}
        if tool == "set_plant_demand_limit":
            return {"target": t, "limit_percent": d["cap_percent"]}
        if tool == "set_zone_cooling":
            return {"target": t, "offset_c": EMPTY_C if d["state"] in ("free", "part") else OPEN_C}
        if tool == "limit_air_handler":
            return {"target": t, "speed_percent": d["floor_percent"]}
        if tool == "set_zone_standby":
            return {"target": t, "mode": "off" if d.get("event") else "on"}
        if tool == "dim_lights":
            return {"target": t, "cut_percent": d["limit_pct"]}
        if tool == "switch_plugs":
            return {"target": t, "state": "off"}
        if tool == "limit_ev_charging":
            return {"target": t, "amps": 0}
        return {"target": t}

    def took(self, tool: str, ans: dict[str, Any], d: dict[str, Any] | None) -> None:
        says = f'{ans["target"]} gives {ans["expected_kw"]:,.0f} kW.' if ans["expected_kw"] > 0 else f'{ans["target"]} is set.'
        if ans["applied"].get("state") == "auto":       # plugs handed back: their kW no longer count against what is owed
            self.calls = [x for x in self.calls if (x["tool"], x["target"]) != (tool, ans["target"])]
        self.calls.append({"tool": tool, "target": ans["target"], "expected_kw": ans["expected_kw"], "says": says, "spaces": (d or {}).get("spaces", [])})

    def refused(self, ans: dict[str, Any], ts: str) -> None:
        ti = dict(ans.get("try_instead") or {})
        if ti.get("start") and ti.get("end") and ti.get("tool"):
            self.retry[(ti["tool"], str(ti.get("target", "")))] = (f'{ts[:10]} {ti["start"]}', f'{ts[:10]} {ti["end"]}')

    def prerequisite(self, d: dict[str, Any] | None, f: dict[str, Any]) -> dict[str, Any] | None:
        e = d.get("ease_with") if d and d["tool"] == "limit_air_handler" and not d.get("eased") else None
        return f["devices"].get(f'{e["tool"]}:{e["target"]}') if e else None

    def after_test(self, f: dict[str, Any], d: dict[str, Any] | None, args: dict[str, Any]) -> dict[str, Any]:
        """Zones eased in a test ease the air handlers on their spaces for the calls after it, as the view reads them once the call has run (see_building: eased)."""
        if not d or not ((d["tool"] == "set_zone_cooling" and float(args.get("offset_c") or 0.0) > 0) or (d["tool"] == "set_zone_standby" and args.get("mode") == "on")):
            return f
        sp = set(d.get("spaces") or ())
        return {**f, "devices": {k: {**x, "eased": True} if x["tool"] == "limit_air_handler" and sp & set(x.get("spaces") or ()) else x for k, x in f["devices"].items()}}

    def would_refuse(self, d: dict[str, Any], f: dict[str, Any], owed: float, ts: str, sale: dict[str, Any]) -> str:
        """A device that waits for its zones is asked as it will be when a plan opens it: code sets what it waits for first (first_needs), so that is asked first, and this one
        as the view reads it once that went through. If the guard would refuse what it waits for, it can't open either. Asked alone, an air handler that waits for its zones reads as blocked."""
        held = dict(self.retry)                     # times() takes a try_instead's times once: a test must not use them up
        try:
            pre = self.prerequisite(d, f)
            if pre is None:
                return super().would_refuse(d, f, owed, ts, sale)
            why = super().would_refuse(pre, f, owed, ts, sale)
            if why:
                return f'It needs {pre["target"]} first, and the guard would refuse that: {why}'
            return super().would_refuse(d, self.after_test(f, pre, self.ready(pre, f, owed)), owed, ts, sale)
        finally:
            self.retry = held

    def first_needs(self, d: dict[str, Any], f: dict[str, Any], done: set[str]) -> dict[str, Any] | None:
        x = self.prerequisite(d, f)
        if x is None or self.key(x) in done:
            return None
        done.add(self.key(x))
        return {"tool": x["tool"], **self.ready(x, f, self.owed_now(f["sale"]))}

    def walk_unlocked(self, ts: str, sale: dict[str, Any], done: set[str], why: str) -> None:
        """Zones eased in a plan open the plant behind them, and that follows by itself: the letter already counted its kW."""
        kept = self.kept_now()
        for _ in range(4):
            f = self.view(ts, sale)
            owed = self.owed_now(sale)
            d = next((x for x in self.live(f, done, kept) if x["tool"] == "set_plant_demand_limit" and x.get("can_give_kw", 0.0) > 0), None)
            if owed <= 0.05 or d is None:
                return
            self.code_call(d, f, owed, ts, sale, why, "Code opened the plant the plan's zones unlocked.")
            done.add(self.key(d))

    def view_plan(self, f: dict[str, Any]) -> None:
        """Zones that wait on nothing but open a plant carry the plant's kW on their letter."""
        behind = sum(float(d.get("can_give_kw", 0.0)) for d in f["devices"].values() if d["tool"] == "set_plant_demand_limit" and not d.get("show"))
        for d in f["devices"].values():
            if d["tool"] == "set_zone_cooling" and d.get("unlocks"):
                d["behind_kw"] = behind
                behind = 0.0

    def cost_of(self, d: dict[str, Any], f: dict[str, Any]) -> str:
        tool = d["tool"]
        if tool == "set_battery":
            return "stored energy runs down toward the reserve"
        if tool == "dim_lights":
            return "people in these rooms see dimmer lights"
        if tool == "set_zone_cooling":
            return f'rooms warm up to +{EMPTY_C if d["state"] in ("free", "part") else OPEN_C:g} C, and booked rooms stay at +{OPEN_C:g} C at most'
        if tool == "limit_air_handler":
            return "fans slow, and booked rooms keep their air"
        if tool == "set_zone_standby":
            return "free rooms stop getting air until people come"
        if tool == "switch_plugs":
            return f'{d.get("holds") or "these outlets"} go off'
        if tool == "limit_ev_charging":
            return "drivers charge later"
        if tool == "set_plant_demand_limit":
            return "zones coast warmer"
        if tool == "stop_plant_early":
            return "no cooling from this plant until the sale ends"
        return "none known"

    def weighs(self, d: dict[str, Any]) -> bool:
        return d["tool"] in ("set_zone_cooling", "set_plant_demand_limit", "stop_plant_early", "dim_lights", "switch_plugs", "limit_air_handler")

    def option_line(self, d: dict[str, Any], f: dict[str, Any]) -> str:
        """The card tests' sentence, without its orders: a plan's letters carry those. What opens more behind it says so."""
        s = re_order.sub("", line(d, f)).strip()
        return s + (f' It also opens about {d["behind_kw"]:,.0f} kW at the plant.' if d.get("behind_kw") else "")

    def still_full(self) -> list[str]:
        """The spaces the schedule watch caught that still read far above the plan. One that has emptied again is no fact, however it read an hour ago."""
        now = self.ctx.ts
        return [s for s in sorted((self.sim.levers or {}).get("events") or ()) if self.zm.true(s, now) - self.zm.plan(s, now) >= buildings.EVENT]

    def touched(self, c: dict[str, Any], f: dict[str, Any]) -> bool:
        """People are in a zone this call holds: the lights, the air, the warmth."""
        return bool(set(self.still_full()) & set(c.get("spaces") or ()))

    def facts_at_hand(self, f: dict[str, Any], why: str) -> list[dict[str, Any]]:
        out = super().facts_at_hand(f, why)
        now = self.ctx.ts
        for s in self.still_full():                 # about these rooms and no others
            out.append(fact(f'{self.zm.spaces[s]["names"]} read {self.zm.true(s, now) * 100:.0f}% in use, and the plan said {self.zm.plan(s, now) * 100:.0f}%.', f"space:{s}", spaces=[s]))
        if float(self.sim.x) >= 0.8 * OPEN_C:
            out.append(fact(f'The building already runs {float(self.sim.x):.2f} C above its own day, and open rooms stop at +{OPEN_C:g} C.', "warm", ("cooling",)))
        return out

    def let_go(self, target: str) -> None:
        """One call ends, and only what that call opened closes. The controller's side of apply_call, backwards."""
        lev, sim = self.sim.levers, self.sim
        gone = [c for c in self.calls if c["target"] == target]
        self.calls = [c for c in self.calls if c["target"] != target]
        for points in self.guard.writers.values():
            points[:] = [w for w in points if w.get("target") != target]
        if lev is None or not gone:
            return
        f = self.ctx.facts() if self.ctx.ts else {"free": {s: 0.0 for s in self.zm.spaces}, "fans_kw": 0.0, "steps": [], "cool_kw": 0.0}     # a person's word can come with no step running
        for c in gone:
            tool, spaces = c["tool"], c.get("spaces") or []
            if tool == "set_battery":
                lev["battery_kw"] = 0.0
            elif tool == "limit_ev_charging":
                lev["dev"].pop("ev", None)
            elif tool in ("set_plant_demand_limit", "stop_plant_early"):
                lev["plants"].pop(target, None)
                sync_plant(sim, f)
                sync_comfort(sim, self.zm, f["free"])
            elif tool == "set_zone_cooling":
                for s in spaces:
                    lev["zones"].pop(s, None)
                    lev["until"].pop(("zones", s), None)
                sync_comfort(sim, self.zm, f["free"])
            elif tool == "set_zone_standby":
                lev["standby"] -= set(spaces)
                for s in spaces:
                    lev["until"].pop(("standby", s), None)
            elif tool == "limit_air_handler":
                _take(sim, "fans", lev["fans"].pop(target, 0.0), f["fans_kw"])
            elif tool == "dim_lights":
                for s in spaces:
                    lev["lights"].pop(s, None)
                still = any(x["tool"] == "dim_lights" for x in self.calls)
                on = sum(sim.house.light_kw(x) for x in f["steps"]) / max(1, len(f["steps"]))
                lev["light_share"] = max(0.0, lev["light_share"] - float(c["expected_kw"]) / max(1e-6, on)) if still else 0.0
            elif tool == "switch_plugs":
                _take(sim, "plugs", lev["plugs"].pop(target, 0.0), _plugs_kw(sim, f))

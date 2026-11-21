"""Code's plan at the opening of a sale and at each exception: what can open, what each call gives, and the calls carried out through menu, policy, guard, seal and driver."""
from __future__ import annotations

from typing import Any, Callable
from murmur.node import context
from murmur.node import record as R
from murmur.node import policy as P
from murmur.node import tools as T
from murmur.node.see import can_act
from murmur.node import modes as arm
from murmur.node.agent_levers import CAME_UP_SHORT, MAX_OPTIONS, OPENS, bears_on, fact
from murmur.node import note_words
from murmur.node import note_reader


class AgentPlan:
    """Code's plan at the opening of a sale and at each exception: what can open, what each call gives, and the calls carried out through menu, policy, guard, seal and driver."""

    # ------------------------------------------------------------------ one device call, whoever chose it
    def key(self, d: dict[str, Any]) -> str:
        return f'{d["tool"]}:{d["target"]}'

    def can(self, f: dict[str, Any], d: dict[str, Any]) -> bool:
        return can_act(f, d) and (d["tool"] != "discharge_car" or d.get("status") == "idle")     # a car that isn't idle can't give, and the guard would only block it

    def kept_now(self) -> set[str]:
        return self.ctx._kept()

    def used_now(self) -> set[str]:
        return {f'{c["tool"]}:{c["target"]}' for c in self.calls} | self.let_gone      # what a plan let go stays closed for this sale: the next plan can't flip it back

    def may_decide(self) -> bool:
        return self.sim.levers is not None and not self.ctx.handed_back and not self.sim.overrides.get("stop")     # else the model went, or a person took the node out of this sale

    def live(self, f: dict[str, Any], used: set[str], kept: set[str]) -> list[dict[str, Any]]:
        """What can still be opened, largest first."""
        return sorted((d for d in f["devices"].values() if self.key(d) not in used and d["tool"] not in kept and self.can(f, d)), key=lambda d: -d.get("can_give_kw", 0.0))

    def ready(self, d: dict[str, Any], f: dict[str, Any], owed: float) -> dict[str, Any]:
        """The call with the numbers the list gives. amount() sizes it after this."""
        tool, t = d["tool"], d["target"]
        if tool == "set_battery":
            return {"target": t, "action": "discharge", "kw": d["can_give_kw"]}
        if tool == "limit_ev_charging":
            return {"target": t, "amps": 0}
        if tool == "discharge_car":
            return {"target": t, "kw": d["can_give_kw"], "max_kwh": d["max_kwh"]}
        if tool in ("set_thermostat", "set_room_ac"):
            return {"target": t, "less_comfort_c": d["limit_c"]}
        if tool == "set_water_heater":
            return {"target": t, "action": "hold"}
        if tool == "delay_appliance":
            return {"target": t, "finish_by": d["done_by"]}
        if tool == "set_pool_pump":
            return {"target": t, "speed_percent": d["floor"]}
        return {"target": t}

    def times(self, tool: str, a: dict[str, Any], d: dict[str, Any] | None, sale: dict[str, Any], ts: str) -> tuple[str, str]:
        return max(ts, sale["start"]), sale["end"]

    def took(self, tool: str, ans: dict[str, Any], d: dict[str, Any] | None) -> None:
        self.calls.append({"tool": tool, "target": ans["target"], "expected_kw": ans["expected_kw"], "says": f'{ans["target"]} gives {ans["expected_kw"]:.2f} kW.'})

    def refused(self, ans: dict[str, Any], ts: str) -> None:
        """A building keeps the times of a guard's try_instead here."""

    def one_call(self, tool: str, args: dict[str, Any], ts: str, sale: dict[str, Any], rec: dict[str, Any], who: P.Who = P.CODE) -> dict[str, Any]:
        """One device call: code sizes it, and it goes through the step's menu, policy, guard, seal and driver, as every device call does. who: whose choice it was, for the record."""
        f = self.view(ts, sale)                     # the controller ran on: the guard judges the node as it is now
        d = next((x for x in f["devices"].values() if x["tool"] == tool and x["target"] == args.get("target")), None)
        args = self.amount(tool, args, f, self.owed_now(sale))
        t0, t1 = self.times(tool, args, d, sale, ts)
        if hasattr(self.ctx, "show"):               # the guard holds a call to the turn's list (off_list): code's own turn lists this one call
            self.ctx.show([T.spec(self.ctx.side, tool, [str(args.get("target"))])])
        ans = self.ctx.act(tool, args, start=t0, end=t1, facts=f, who=who)
        rec["verdicts"].append({"call": {"tool": tool, "args": args, "start": t0, "end": t1}, "answer": ans})
        self.log_calls.append({"target": ans["target"], "status": ans["status"], "expected_kw": ans["expected_kw"], "why": ans["why"]})
        if ans["status"] in context.SENT:
            self.took(tool, ans, d)
        else:
            self.refused(ans, ts)
        return ans

    def blank(self, ts: str, why: str | None, owed: float, by: str = "code", text: str = "") -> dict[str, Any]:
        return {"node": self.name, "tier": self.tier, "ts": ts, "why": why, "text": text, "shortlist": [], "answer": [], "said": "", "ms": 0, "model": "code" if by == "code" else self.brain.model,
                "prompt": T.PROMPT_VERSION, "owed_kw": round(owed, 2), "verdicts": [], "by": by}

    def code_call(self, d: dict[str, Any], f: dict[str, Any], owed: float, ts: str, sale: dict[str, Any], why: str | None, note: str) -> dict[str, Any]:
        """One call code chose, with its own line in the decision record. A guard's try_instead gets one go."""
        args = self.ready(d, f, owed)
        rec = self.blank(ts, why, owed, text=note)
        rec["answer"] = [{"name": d["tool"], "args": args}]
        ans = self.one_call(d["tool"], args, ts, sale, rec)
        ti = ans.get("try_instead") or {}
        if ans["status"] not in context.SENT and ti.get("tool") and ti["tool"] in self.shelf:
            more = {k: v for k, v in ti.items() if k not in ("tool", "start", "end")}
            rec["answer"].append({"name": ti["tool"], "args": more})
            ans = self.one_call(ti["tool"], more, ts, sale, rec)
        self.record(rec)
        return ans

    def by_step(self, ts: str, sale: dict[str, Any], why: str | None = None) -> None:
        """Code plans the opening (step 7) and every exception (step 8). A new sale starts with nothing let go and no fact spent."""
        if why:
            return self.plan(ts, sale, why)
        self.let_gone, self.spent = set(), set()    # a new sale
        return self.plan(ts, sale, OPENS)

    # ------------------------------------------------------------------ steps 7 and 8: code's whole plan
    def price_now(self, sale: dict[str, Any]) -> float:
        """$ per kWh in the contract behind this sale."""
        for c in self.home.contracts.values():
            if c.get("status") == "ACCEPTED" and c.get("window_start") == sale["start"]:
                return float(c.get("price_usd_per_kwh") or 0.0)
        return 0.0

    def cost_of(self, d: dict[str, Any], f: dict[str, Any]) -> str:
        """What opening this costs, in plain words."""
        tool = d["tool"]
        if tool == "set_battery":
            return "the battery ends lower and refills after the sale"
        if tool == "limit_ev_charging":
            return f'the car waits, and must be ready by {d.get("leaves")}'
        if tool == "discharge_car":
            return f'the car gives up to {d.get("max_kwh", 0.0):.1f} kWh and refills before {d.get("leaves")}'
        if tool in ("set_thermostat", "set_room_ac"):
            return f'the house may warm by up to {d.get("limit_c", 0.0):.2f} C'
        if tool == "set_water_heater":
            return "the tank cools a little"
        if tool == "delay_appliance":
            return f'it starts after the sale and ends by {d.get("done_by")}'
        if tool == "set_pool_pump":
            return "the filter runs slower"
        return "none known"

    def weighs(self, d: dict[str, Any]) -> bool:
        """People feel this one: choosing it over nothing is a real trade-off."""
        return d["tool"] in ("set_thermostat", "set_room_ac", "limit_ev_charging", "discharge_car", "delay_appliance")

    def option_line(self, d: dict[str, Any], f: dict[str, Any]) -> str:
        return f'{d["target"]} gives {d.get("can_give_kw", 0.0):.2f} kW.'

    def touched(self, c: dict[str, Any], f: dict[str, Any]) -> bool:
        """This running call now presses on something that changed, so letting it go is a live question. A building's zones say so here."""
        return False

    def facts_at_hand(self, f: dict[str, Any], why: str) -> list[dict[str, Any]]:
        """What a plan may cite to leave kW uncovered or let a call go, each with what it bears on: a wish its own part, a limit a person lowered its own device, a limit close by its own device.
        Each is read here, not assumed, and each is true now. A note that set no wish isn't here: the model read it, and it asks for nothing of the devices. A tripped battery isn't here either:
        it explains a shortfall, and it is no reason to warm the house less."""
        sim = self.sim
        out = [fact(note_words.SAYS[w["wish"]], f'wish:{w["wish"]}', (note_reader.PART[w["wish"]],)) for w in self.guard.wishes]
        out += [fact(str(v), f"lowered:{t}", (note_reader.PART_OF.get(t, ""),)) for t, v in (f.get("lowered") or {}).items()]       # a limit a person lowered during the sale
        for d in f["devices"].values():
            if d["tool"] in ("set_thermostat", "set_room_ac") and d.get("limit_c") and float(sim.x) >= 0.8 * float(d["limit_c"]):
                out.append(fact(f'The house already runs {float(sim.x):.2f} C above normal, and its limit is {d["limit_c"]:.2f} C.', "warm", ("cooling",)))
            if d["tool"] == "limit_ev_charging" and d.get("leaves") and float(d.get("wait_h", 99.0)) < 2.0:
                out.append(fact(f'The car leaves at {d["leaves"]} with {max(0.0, float(d["wait_h"])):.1f} hours to spare.', "car", ("car",)))
        return out

    def situation(self, ts: str, sale: dict[str, Any], why: str, used: set[str], kept: set[str]) -> dict[str, Any]:
        """Everything a plan needs, with code's own plan beside it: what is owed, what runs, what can open, what each is worth, what may be cited."""
        f = self.view(ts, sale)
        owed = self.owed_now(sale)
        hours = max(0.25, self.sim.replay.minutes_between(max(ts, sale["start"]), sale["end"]) / 60.0)
        price = self.price_now(sale)
        opts: list[dict[str, Any]] = []
        refused: list[str] = []
        for d in self.live(f, used, kept):
            why_not = self.would_refuse(d, f, owed, ts, sale)
            if why_not:
                refused.append(f'{d["target"]}: {why_not}')
            elif len(opts) < MAX_OPTIONS:
                opts.append({"id": chr(65 + len(opts)), "d": d, "kw": float(d.get("can_give_kw", 0.0)) + float(d.get("behind_kw", 0.0)), "line": self.option_line(d, f), "cost": self.cost_of(d, f), "costs": self.weighs(d)})
        for o in opts:                              # what a device waits for, on its line: the guard blocks it alone, and code sets that first when a plan opens it (first_needs)
            pre = self.prerequisite(o["d"], f)      # a line that hides what its device waits for reads as if the device could simply open
            if pre is None:
                continue
            by = next((p for p in opts if self.key(p["d"]) == self.key(pre)), None)
            if by is not None:
                by.setdefault("unlocks", []).append(o["id"])
            first = by["id"] if by else pre["target"]
            o["line"] = f'{o["line"]} It needs {first} first, which eases its zones: if the plan opens {o["id"]}, code sets {first} first.'
        run = sorted((c for c in self.calls if c["expected_kw"] > 0 or self.touched(c, f)), key=lambda c: (not self.touched(c, f), -c["expected_kw"]))[:MAX_OPTIONS]
        on = {self.key(d): d for d in f["devices"].values()}
        run = [{"id": f"R{i + 1}", "c": c, "kw": float(c["expected_kw"]), "touched": self.touched(c, f), "cost": self.cost_of(on[self.key(c)], f) if self.key(c) in on else "",
                "costs": self.weighs(c)} for i, c in enumerate(run)]
        tol = max(0.05, 0.02 * float(sale["owed_kw"]))
        left, plan = owed, []
        for o in opts:
            if left <= tol:
                break
            plan.append(o["id"])
            left -= o["kw"]
        touches = [(o["d"]["tool"], o["d"].get("spaces"), True) for o in opts] + [(r["c"]["tool"], r["c"].get("spaces")) for r in run]
        facts = [{"id": f"F{i + 1}", **x} for i, x in enumerate(y for y in self.facts_at_hand(f, why) if y["key"] not in self.spent and any(bears_on(y, *t) for t in touches))]
        return {"f": f, "owed": owed, "covered": sum(c["expected_kw"] for c in self.calls), "hours": hours, "price": price, "options": opts, "running": run, "tol": tol, "default": plan,
                "left": max(0.0, left), "facts": facts, "why": why, "refused": refused[:4]}

    def would_refuse(self, d: dict[str, Any], f: dict[str, Any], owed: float, ts: str, sale: dict[str, Any]) -> str:
        """The guard's word on this device, asked of a copy: a call it would block isn't on the plan's list, and the plan is told why."""
        args = self.amount(d["tool"], self.ready(d, f, owed), f, max(owed, float(d.get("can_give_kw", 0.0))))
        t0, t1 = self.times(d["tool"], args, d, sale, ts)
        a = self.ctx.dry(d["tool"], args, t0, t1, f)
        return "" if a["status"] in context.SENT else str(a["why"])

    def plan(self, ts: str, sale: dict[str, Any], why: str) -> None:
        """Something changed in a sale: code's own plan stands (what opens, what is let go, what the desk hears), and the record says so."""
        if not self.may_decide():
            return
        st = self.situation(ts, sale, why, self.used_now(), self.kept_now())
        return self.carry_out(st, ts, sale, arm.BY_CODE)

    def carry_out(self, st: dict[str, Any], ts: str, sale: dict[str, Any], no_ask: str, rec: dict[str, Any] | None = None) -> None:
        """Code's own plan, in the order that holds: what the list opens, until what is owed is covered, then what that unlocks."""
        why = st["why"]
        rec = rec or {**self.blank(ts, why, st["owed"], "code", f"Code's plan: {no_ask}."), "default": {"open": st["default"], "left_kw": round(st["left"], 2)}}
        by_id = {o["id"]: o for o in st["options"]}
        pick = list(st["default"])
        check: dict[str, Any] = {"cites": None, "grounded": False, "facts": [x["says"] for x in st["facts"]], "numbers_not_in_prompt": []}
        rec["plan"] = {"open": pick, "release": [], "report": "none", "reason": "", "check": check}
        done: set[str] = self.used_now()
        opened: list[str] = []
        for i in pick:
            if self.owed_now(sale) <= 0.05:
                break                               # covered: the rest would only be sized down to nothing
            opened.append(i)
            f = self.view(ts, sale)
            d = next((x for x in f["devices"].values() if self.key(x) == self.key(by_id[i]["d"])), by_id[i]["d"])
            if self.key(d) in done:
                continue                            # set already, as what an earlier call waited for: a second write would only spend the device's writes
            first = self.first_needs(d, f, done)
            if first is not None:
                self.one_call(first["tool"], {k: v for k, v in first.items() if k != "tool"}, ts, sale, rec)
            self.one_call(d["tool"], self.ready(d, f, self.owed_now(sale)), ts, sale, rec, P.CODE)
            done.add(self.key(d))
        rec["plan"]["opened"] = opened
        rec["changed"] = False
        self.walk_unlocked(ts, sale, done, why)
        self.ctx.log.add("tool", step=self.ctx.step, ts=ts, tool="set_plan", args=rec["plan"], who="code", result={"status": "done", "changed": False})
        rec["receipt"] = self.plan_receipt(st, ts, sale, rec, pick, no_ask)
        self.record(rec)

    def plan_receipt(self, st: dict[str, Any], ts: str, sale: dict[str, Any], rec: dict[str, Any], pick: list[str], no_ask: str) -> dict[str, Any]:
        """The receipt of a plan: what changed, code's plan and what it covered. When the calls gave less than the plan expected, the person hears it."""
        fmt = (lambda x: f"{x:,.0f}") if self.word == "building" else (lambda x: f"{x:.1f}")
        left = max(0.0, self.owed_now(sale))
        less = left > st["left"] + st["tol"]
        told = None
        if less:                                    # nobody chose less: the equipment gave less than the plan expected
            told = " ".join(([f'I left {fmt(left)} kW of the {fmt(float(sale["owed_kw"]))} kW owed uncovered.'] if left > st["tol"] else []) + [CAME_UP_SHORT])
            self.tell(told, "opening" if st["why"] == OPENS else "exception", ts)
        letters = {o["id"]: f'{o["d"]["tool"]} {o["d"].get("target") or ""}'.strip() for o in st["options"]}      # so the receipt reads by itself
        letters.update({r["id"]: f'{r["c"]["tool"]} {r["c"].get("target") or ""}'.strip() for r in st["running"]})
        return self.receipt("opening" if st["why"] == OPENS else "exception", ts, asked={"what_changed": st["why"], "owed_kw": round(st["owed"], 2), "question": R.sha(rec.get("text") or ""),
                                                                                          "letters": letters},
                            rule={"open": st["default"], "left_kw": round(st["left"], 2)}, chose={"open": pick, "release": [], "left_kw": round(left, 2), "report": None},
                            reason=CAME_UP_SHORT if less else arm.BY_CODE_SAYS if no_ask == arm.BY_CODE and not rec.get("fallback") else (rec.get("fallback") or no_ask or ""),
                            facts=self.plan_facts(st, sale, fmt), flags=[], by=f'rule: {rec.get("fallback") or no_ask or "code"}', less=less, told=told)

    def plan_facts(self, st: dict[str, Any], sale: dict[str, Any], fmt: Callable[[float], str]) -> list[dict[str, str]]:
        """What a plan rests on: what changed, what was owed and covered, and what code's own plan does."""
        return [{"id": "changed", "says": st["why"]},
                {"id": "owed", "says": f'{fmt(float(sale["owed_kw"]))} kW were owed and calls running covered {fmt(st["covered"])} kW.'},
                {"id": "rule", "says": f'Code\'s own plan opens {", ".join(st["default"]) or "nothing"} and leaves {fmt(st["left"])} kW uncovered.'}]

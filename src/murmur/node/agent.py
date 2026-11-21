"""A member's agent: code owns the steps and their deadlines, and every amount.

  steps 1-4  read the schedule, forecast, check the devices, estimate what can be sold (code)
  steps 5-6  the offer and the answer to a commitment (node/offer_rule.py)
  step 7     the sale's opening: code's plan of device calls, through menu, policy, guard, seal and driver
  step 8     an exception (a limit fell, a note, the car plugged in, the battery tripped, a call, a shortfall): code's plan again
  step 9     the report, worded by the model from code's facts (node/report.py)

A person's notes are read by the note reader (node/agent_notes.py). Each decision leaves a receipt in the node's decision record.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable


from murmur.node.control import person_limit
from murmur.node import context
from murmur.node import report
from murmur.node import tools as T
from murmur.node.guard import Guard
from murmur.node.see import see_home
from murmur.node.agent_levers import LEAD_MIN, NO_REASON, apply_call, close_levers, open_levers, write_comfort
from murmur.node.agent_notes import AgentNotes
from murmur.node.agent_plan import AgentPlan

CUSHION = 1.1          # a call is sized this far over what is owed: a call's expected kW run high, so one sized at what is owed delivers less than that
SHORT_SHARE = 0.15     # the plan may fall this share short before the agent is woken
SHORT_KW = 0.1
QUIET_MIN = 30         # at least this long between wake-ups for a shortfall
CODE_STEPS = ("1 read schedule", "2 forecast", "3 check devices", "4 estimate sellable")


# --------------------------------------------------------------------------------------------------- the agent
class NodeAgent(AgentNotes, AgentPlan):
    """A home's agent. A building's agent subclasses this and changes the small methods under `what differs by node`."""
    word = "home"

    def __init__(self, home: Any, tier: int, brain: Any, record: Callable[[dict[str, Any]], None] | None = None, log: Any = None):
        self.home, self.sim, self.tier, self.brain = home, home.adapter, tier, brain
        self.name = home.name
        self.shelf = self.tools()
        self.guard = self.make_guard()
        self.ctx = context.ContextServer(self, log=log)
        home.agent = self
        self.record = record or (lambda r: None)
        self.done_for: str | None = None        # the sale already planned
        self.calls: list[dict[str, Any]] = []    # the calls running now
        self.last_wake: str | None = None
        self.noted: str | None = self.ctx.noted         # the door's note already read: after a restart it isn't read again, and its wish isn't held twice
        self.tripped = False
        self.plugged = False
        self.waiting: Any = None
        self.short_reason: str | None = None        # what this agent told the desk about a shortfall: rt_report repeats it until the sale ends
        self.filed = self.ctx.notes_read            # the notes on file already read
        self.market_seen: dict[Any, set[str]] = {}  # the market steps each call for offers has run
        self.let_gone: set[str] = set()             # calls a plan let go in this sale
        self.spent: set[str] = set()                # facts that have carried a decision in this sale
        self.decide = self.by_step                  # code's plan at the opening and at every exception
        self.fallbacks: Counter = Counter()         # points code decided because the model failed, by why, as the host's status reports them (agents/host_doors.py)
        self.flags: Counter = Counter()             # receipts flagged: no reason given, or a reason that cites no fact
        self.receipts: list[dict[str, Any]] = []    # one per decision, with every node an agent: also in the node's decision log
        self.note_waits: dict[str, dict[str, Any]] = {}      # notes whose reader gave no reason, by their words: how often, and the sale they last tried in (note_reader.read_note_carefully)
        self.told: list[dict[str, Any]] = []        # what the owner or manager was told when the node gave less than the rule's amount
        self.wish_notes: dict[str, str] = {}        # each wish's note, in the person's words: an offer under the wish cites it
        self.call_kw = 0.0                          # kW dispatched on top of the sale since the last step
        self.log_calls: list[dict[str, Any]] = []   # every call this sale, for step 9
        self.reported: str | None = None
        self.reports: list[dict[str, Any]] = []
        self.steps: list[tuple[str, str]] = []      # (step, when): the workflow's record
        self.seen_limits: dict[str, float] | None = None     # the limits in force at the last look, while a sale runs

    @property
    def car_first(self) -> bool:
        """A wish put the car first, and no person has said anything of it since. It lives on the node, so a restart keeps it, and a person's own word ends it."""
        return bool(getattr(self.sim, "car_first", False))

    # ------------------------------------------------------------------ what differs by node
    def tools(self) -> list[str]:
        return T.shelf(self.name, self.tier)

    def make_guard(self) -> Guard:
        return Guard(T.home_setup().get(T.home_id(self.name)))

    def view(self, ts: str, sale: dict[str, Any]) -> dict[str, Any]:
        return see_home(self.sim, ts, sale, self.shelf)


    def amount(self, tool: str, args: Any, f: dict[str, Any], owed: float) -> Any:
        """For a thermostat, a room unit, a battery's discharge or a car, the call's size is code's arithmetic, whatever figure its arguments came with: CUSHION over
        what is owed, in degrees as the guard counts them up to the home's limit, or in kW up to what the device can give. Other calls pass as they are."""
        d = next((x for x in f["devices"].values() if x["tool"] == tool), None)
        if not isinstance(args, dict) or d is None:
            return args
        if tool in ("set_thermostat", "set_room_ac"):           # the degrees that give what is owed, as the guard counts them, up to the home's limit
            return {**args, "less_comfort_c": round(min(d["limit_c"], owed * CUSHION * d["cop"] * d["hours"] / max(1e-6, d["cap"])), 2)}
        if tool == "discharge_car" or (tool == "set_battery" and args.get("action") == "discharge"):
            out = {**args, "kw": round(min(owed * CUSHION, d["can_give_kw"]), 2)}
            return {**out, "max_kwh": d["max_kwh"]} if tool == "discharge_car" else out
        return args

    def open(self) -> None:
        open_levers(self.sim)

    def close(self) -> None:
        close_levers(self.sim)

    def apply(self, call: dict[str, Any], ans: dict[str, Any]) -> None:
        apply_call(self.sim, call, ans)

    def limits_now(self) -> dict[str, float]:
        return {k: person_limit(self.sim, k) for k in ("max_rise_c", "max_rise_away_c")}

    def shrink(self, f: dict[str, Any]) -> None:
        """A limit fell: a running call can't count for more than its device can now give."""
        for c in self.calls:
            if c["tool"] in ("set_thermostat", "set_room_ac"):
                self.cap_call(c, next((float(d["can_give_kw"]) for d in f["devices"].values() if d["tool"] == c["tool"]), c["expected_kw"]))

    def cap_call(self, c: dict[str, Any], kw: float) -> None:
        if kw < c["expected_kw"]:
            c.update(expected_kw=round(kw, 2), says=self.gives(c["target"], kw))

    def gives(self, target: str, kw: float) -> str:
        return f"{target} gives {kw:.2f} kW."

    # ------------------------------------------------------------------ the same for every node
    def sale(self, ts: str) -> dict[str, Any] | None:
        """Today's sale from the contract the node holds: its window and the most it owes."""
        day = ts[:10]
        owed = {t: float(a["deliver_kw"]) + float(self.sim.rt_extra.get(t, 0.0)) for t, a in self.sim.plan.items()
                if t[:10] == day and "deliver_kw" in a and float(a["deliver_kw"]) > 0}
        if not owed:
            return None
        from murmur.protocol.envelope import add_minutes
        groups: list[list[str]] = []
        for t in sorted(owed):
            if groups and t == add_minutes(groups[-1][-1], 15):
                groups[-1].append(t)
            else:
                groups.append([t])
        # the first that isn't over. One that has ended stays until step() has closed it, so its levers can't stay shut through the gap
        g = next((g for g in groups if ts < add_minutes(g[-1], 15) or (self.done_for == g[0] and self.reported != g[0])), groups[-1])
        by = {t: owed[t] for t in g}
        return {"start": g[0], "end": add_minutes(g[-1], 15), "owed_kw": max(by.values()), "by_ts": by}

    def market(self, step: str, ts: str, need: dict[str, Any] | None = None, fc: dict[str, Any] | None = None, offer: dict[str, Any] | None = None) -> None:
        """Steps 1 to 6 run on the market's side, as a call for offers comes in: code reads the schedule, forecasts, checks the devices and works out what is sellable, and
        the offer rule (node/offer_rule.py) makes the offer and answers the commitment. Each enters the record when it really happens, with what went in and what came out.
        ctx.step stays as it is: this comes on the market's thread, and a sale step may be waiting on the model at this moment."""
        seen = self.market_seen.setdefault((need or {}).get("event_id"), set()) if need else set()
        for s in (*CODE_STEPS, step) if step == "5 offer" else (step,):
            if s in seen:
                continue                            # it ran when it really happened, before the offer
            seen.add(s)
            self.steps.append((s, ts))
            self.ctx.steps.enter(s, ts)
            io = self.step_record(s, need, fc, offer)
            if io:
                self.ctx.log.add("step_io", step=s, ts=ts, **io)
                self.record({"node": self.name, "tier": self.tier, "ts": ts, "why": s, "by": "code", "model": "code", "text": "", "shortlist": [], "answer": [], "said": "", "ms": 0, "owed_kw": 0.0,
                             "prompt": T.PROMPT_VERSION, "verdicts": [], **io})
            self.ctx.steps.leave(s, ts, "done")

    def step_record(self, step: str, need: dict[str, Any] | None, fc: dict[str, Any] | None, offer: dict[str, Any] | None) -> dict[str, Any] | None:
        """What went into a code step and what came out of it."""
        if need is None:
            return None
        window = {"start": need["window_start"], "end": need["window_end"]}
        if step == "1 read schedule":
            from murmur.node.grounds import schedule_in
            rows = schedule_in(self.home, need)
            return {"inputs": {"day": need["window_start"][:10], **window}, "outputs": {"blocks_in_window": len(rows), "blocks": rows}}
        if step == "2 forecast" and fc is not None:
            st = fc.get("steps") or []
            mean = lambda k: round(sum(float(x.get(k) or 0.0) for x in st) / max(1, len(st)), 3)      # noqa: E731
            return {"inputs": {"method": str(fc.get("method", ""))[:60], **window}, "outputs": {"load_kw": mean("load_p50"), "solar_kw": mean("pv_p50"), "car_kw": mean("ev_kw"), "steps": len(st)}}
        if step == "3 check devices" and offer is not None:
            s0 = (offer.get("slots") or [{}])[0]
            parts = {k: s0.get(k) for k in ("battery_kw", "ev_pause_kw", "ac_kw", "app_kw", "light_kw") if s0.get(k)}
            return {"inputs": {"shelf": list(self.shelf), "sensors": offer.get("health")}, "outputs": {"by_part_kw": parts, "by_device_kw": (offer.get("appliances") or {}).get("by_device") or {}}}
        if step == "4 estimate sellable" and offer is not None:
            from murmur.agents.community.market_rules import firm_part
            kw = [s.get("kw_offered", 0.0) for s in offer.get("slots") or []]
            return {"inputs": {"battery": offer.get("battery"), "forecast": str(offer.get("forecast_method", ""))[:60]},        # the firm part as the market will read it: a building's is set after this step
                    "outputs": {"safe_kw_per_half_hour": kw, "firm_kw": [round(firm_part(offer, s), 3) for s in offer.get("slots") or []], "energy_kwh": offer.get("energy_kwh")}}
        return None

    def delivered(self, sale: dict[str, Any]) -> str:
        """What the meter says of the sale, for the report: the kWh missed step by step, so a good first hour can't hide a short last one."""
        rows = [t for t in self.sim.recent.values() if sale["start"] <= t["ts"] < sale["end"]]
        gave = [t["grid_kw"] - t["grid_cf_kw"] for t in rows]
        short = sum(max(0.0, t["owed_kw"] - g) for t, g in zip(rows, gave)) * .25
        n = 0 if self.word == "building" else 1
        return f"The meter shows {sum(gave) / max(1, len(gave)):,.{n}f} kW delivered on average, and {short:,.{n}f} kWh missed in the steps that fell short."

    def could_give(self, start: str, end: str) -> dict[str, Any]:
        """A call asks how much more this node could give. The levers show only what calls have opened, so for this sum they stand open, less what a wish
        or a person keeps out. If the call comes, the agent wakes and opens it, and if the model has gone the controller does."""
        sim = self.sim
        lev, comfort = sim.levers, sim.overrides.get("comfort")
        if lev is None:
            return sim.rt_capacity(start, end)
        keep = self.ctx._kept()
        try:
            write_comfort(sim)                      # the agent's hold goes out of this sum, and a person's word stays in it
            self.all_open(keep)
            return sim.rt_capacity(start, end)
        finally:
            sim.levers = lev
            write_comfort(sim, comfort)

    def all_open(self, keep: set[str]) -> None:
        self.sim.levers = {"battery_kw": 1e9, "ev": True, "ev_kw": None, "v2h_kw": 1e9, "v2h_kwh": None, "devices": set(getattr(self.sim, "app", None) or ())}
        self.reopen(keep)

    def called(self, steps: dict[str, float]) -> None:
        """The community agent dispatched more. The next step wakes the agent."""
        kw = max(steps.values(), default=0.0)
        if kw > SHORT_KW and self.sim.levers is not None:
            self.call_kw = max(self.call_kw, kw)

    def replan(self) -> None:
        """The sale's amount changed, so this step plans it afresh: each call below takes over from what runs, and what the plan leaves stays open."""
        self.calls = []
        self.guard.clear()

    def owed_now(self, sale: dict[str, Any]) -> float:
        return max(0.0, sale["owed_kw"] - sum(c["expected_kw"] for c in self.calls))

    def limit_fell(self, ts: str, sale: dict[str, Any]) -> str | None:
        """A person lowered a limit while the sale runs. The controller holds it from its next part. Here what's owed comes out right, and the agent hears why. Without this
        the running calls would still count their old kW, and the agent would read 0 kW owed and do nothing."""
        now, seen = self.limits_now(), self.seen_limits
        self.seen_limits = now
        if seen is None or all(v >= seen.get(k, v) - 1e-9 for k, v in now.items()):
            return None
        self.shrink(self.view(ts, sale))
        return "A limit was lowered."


    def step(self, ts: str) -> None:
        """Called every 15 minutes. Most steps do nothing: the controller is running the node. A wish ends after the step, so the sale's report still has it."""
        try:
            self.turn(ts)
        finally:
            self.lapse(ts)

    def turn(self, ts: str) -> None:
        from murmur.protocol.envelope import add_minutes
        alarm = self.sim.overrides.get("alarm") or self.sim.overrides.get("alarm_hold") or self.ctx.stopped
        if alarm:
            self.ctx.alarm(alarm, ts)
            self.calls = []
            return
        note_why = self.read_note(ts)
        sale = self.sale(ts)
        if not sale:
            return
        if ts >= sale["end"]:
            if self.sim.levers is not None:
                self.close()
                self.guard.clear()
                self.calls = []
                self.short_reason = None
            if self.done_for == sale["start"] and self.reported != sale["start"]:
                self.reported = sale["start"]
                self.steps.append(("9 report", ts))
                self.ctx.enter("9 report", ts, sale)
                report.fell_short(self, sale, ts)
                self.reports.append(report.send(self, report.write(self, sale, ts), sale))
                self.ctx.leave()
            return
        lead = add_minutes(sale["start"], -LEAD_MIN)
        if self.done_for != sale["start"] and ts >= lead:
            self.done_for = sale["start"]
            self.last_wake = ts
            self.steps.append(("7 watch", ts))
            self.ctx.enter("7 watch", ts, sale)
            self.log_calls = []
            self.open()
            self.seen_limits = self.limits_now()
            self.decide(ts, sale)
            self.ctx.leave()          # a step ends with its work: no tools stay open until the next one
            return
        if self.done_for != sale["start"]:
            return
        why = self.limit_fell(ts, sale) or note_why
        plugged = bool(self.sim.has_ev and self.sim.ev_deadline and self.sim.ev_left > 0.01)
        if plugged and not self.plugged and "limit_ev_charging" not in {c["tool"] for c in self.calls} and why is None:
            why = "the car plugged in."
        self.plugged = plugged
        waiting = "delay_appliance" in self.shelf and ts >= sale["start"] and next((d["name"] for d in self.view(ts, sale)["devices"].values() if d["tool"] == "delay_appliance"), None)
        if waiting and waiting != self.waiting and "delay_appliance" not in {c["tool"] for c in self.calls} and why is None:
            why = f"The {waiting.lower()} is waiting to start."
        self.waiting = waiting
        trip = bool(self.sim.E > 0 and self.sim.P <= 0)
        if trip and not self.tripped:
            self.tripped = True
            self.calls = [c for c in self.calls if c["tool"] != "set_battery"]
            why = "The battery shut off."
        if self.call_kw and why is None:
            why = f"The grid called for {self.call_kw:.1f} kW more."
            self.call_kw = 0.0
            self.replan()
        if why is None and ts >= sale["start"]:
            last = self.sim.ctl.last or {}
            short = max((v for t, v in (last.get("short_by_ts") or {}).items() if t >= ts), default=0.0)
            quiet = self.last_wake and ts < add_minutes(self.last_wake, QUIET_MIN)
            if short > max(SHORT_KW, SHORT_SHARE * sale["owed_kw"]) and not quiet:
                why = f"The plan falls {short:.1f} kW short."
                sale = {**sale, "owed_kw": short + sum(c["expected_kw"] for c in self.calls)}
        if why:
            self.last_wake = ts
            self.steps.append(("8 exception", ts))
            self.ctx.enter("8 exception", ts, sale)
            self.decide(ts, sale, why)
            self.ctx.leave()


    def receipt(self, point: str, ts: str, *, asked: Any, rule: Any, chose: Any, reason: str, facts: list[dict[str, Any]], flags: list[str], by: str, less: bool,
                told: str | None = None) -> dict[str, Any]:
        """Every node an agent: one decision's receipt, in the node's own decision log (node/record.py): what was asked, the rule's plan, what the agent chose,
        its reason and the facts that reason rests on. A flag says a reason was missing or cited no fact, and each flag is counted. No receipt has a blank reason."""
        if not str(reason or "").strip():
            reason, flags = NO_REASON, [*flags, NO_REASON] if NO_REASON not in flags else flags
        for x in flags:
            self.flags[x] += 1
        r = {"node": self.name, "point": point, "ts": ts, "asked": asked, "rule": rule, "chose": chose, "less_than_rule": bool(less), "by": by,
             "reason": reason, "facts": facts, "flags": list(flags), **({"told": told} if told else {})}
        self.receipts.append(r)
        self.ctx.log.add("receipt", **{k: v for k, v in r.items() if k != "node"})
        return r

    def tell(self, text: str, point: str, ts: str) -> None:
        """Every node an agent: the owner, or a building's manager, hears in plain words whenever the node gives less than asked. It goes on the person's
        channel, here the node's own list and log, and into the node's own report. None of it goes on the market's wire."""
        m = {"ts": ts, "point": point, "to": "manager" if self.word == "building" else "owner", "text": str(text)[:400]}
        self.told.append(m)
        self.ctx.log.add("told", **m)


    def let_go(self, target: str) -> None:
        """One running call ends: its device leaves the sale at once, and its point is free again."""
        tools = {c["tool"] for c in self.calls if c["target"] == target}
        self.calls = [c for c in self.calls if c["target"] != target]
        self.guard.writers.pop(target, None)
        if self.sim.levers is not None and tools:
            self.reopen(tools)

    def first_needs(self, d: dict[str, Any], f: dict[str, Any], done: set[str]) -> dict[str, Any] | None:
        """The call this one needs in place before it. A building's fans wait for their zones."""
        return None

    def prerequisite(self, d: dict[str, Any] | None, f: dict[str, Any]) -> dict[str, Any] | None:
        """The device this one waits for, which code sets first when a plan opens it (first_needs). A home's devices wait for nothing."""
        return None

    def walk_unlocked(self, ts: str, sale: dict[str, Any], done: set[str], why: str) -> None:
        """What a plan's calls opened up. A building's plant waits for its zones to coast."""

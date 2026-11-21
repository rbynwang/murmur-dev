"""A node's context server: the only way its agent reaches anything.

Every device call goes through it: the step's menu, the policy (who may change what), the guard (the node's limits), the seal and the
driver. It also holds the alarm: while one holds the node, nothing runs and every limit is released. Reads answer from the node's own
view; writes go to the simulated devices on the dataset's replay.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import date, timedelta
from typing import Any, Callable


from murmur.node import drivers as D
from murmur.node import policy as P
from murmur.node import record as R
from murmur.node.guard import answer, blocked
from murmur.node.calls import ACT_STEPS, Desk, Schedule, clean_args, device_params, device_write, guard_state, listed, run_call
from murmur.node.context_sim import ContextSim
from murmur.node import note_reader

EVENING = ("18:00", "21:00")     # the window a forecast reads when no request or sale names one
STEPS = ("1 read schedule", "2 forecast", "3 check devices", "4 estimate sellable", "5 offer", "6 commitment", "6 prepare", "7 watch", "8 exception", "9 report")     # a node's workflow: enter() takes no other step
SENT = ("done", "adjusted")


class ContextServer(ContextSim):
    def __init__(self, node: Any, *, side: str | None = None, policy: P.Policy | None = None, log: R.Log | None = None, driver: D.Driver | None = None,
                 schedule: Schedule | None = None, desk: Any = None, mode: str | None = None):
        self.node = node
        self.v2 = getattr(node, "home", None)
        self.side = side or getattr(node, "side", None) or ("building" if getattr(self.v2, "is_building", False) else "home")
        self.policy = policy or P.Policy(self.side)
        self.log = log or R.Log(node.name)
        self.steps = R.Steps(self.log)
        self.schedule = schedule or Schedule(self.side)
        self.desk = desk or (Desk(self.v2) if self.v2 is not None else None)
        self._write = device_write(node)
        self.driver = driver or D.make(self.side, mode or os.environ.get("MURMUR_DRIVERS", "simulated"), P.group_of, write=self._sim_write, release=self._sim_release,
                                       read=self._sim_read, limit=self._sim_limit)
        self.gate = D.Gate(node.name, node.guard, self.driver)
        self._lock = threading.RLock()            # the sale's steps and a person's channel may ask at once
        self._f: dict[str, Any] = {}
        self.step: str | None = None
        self.ts = ""
        self.sale: dict[str, Any] | None = None
        self.request: dict[str, Any] | None = None
        self.stopped: str | None = None           # an alarm's stop: nothing is sent until a person clears it, whatever the signal does
        self.acted: set[str] = set()              # calls this process has already answered, so a repeat isn't counted twice
        self.handed_back = False                  # the model went, so the controller is running this sale alone
        self.shown: dict[str, list[str] | None] | None = None     # the list this step last showed: the guard refuses a device call outside it
        self._restore()

    def _restore(self) -> None:
        """What a restart must not forget, from the record: what people said, a stop after an alarm, the request still waiting. It comes back here, not when
        a channel opens, because a node can start with no channel. A new run starts clean, and what people said through the channel still stands.

        The guard's other memory stays behind on purpose: a restart resets the levers too, so a point it remembered would only block the node's own new call."""
        stop, wishes = None, []
        self.notes_read: set[str] = set()         # the notes on file this node has read: a date in one means what it meant the first time
        self.noted: str | None = None             # the last door note it read, so a restart doesn't read it twice
        for r in list(self.log.rows):
            k = r["kind"]
            if k == "new_run":
                self.request, stop, wishes = None, None, []
                self.notes_read.clear()
                self.noted = None
            elif k == "alarm":
                stop = r.get("why") or "alarm"
            elif k == "request":
                self.request = r.get("request")
            elif k == "decision" and r.get("why") == "owner's note" and r.get("node", self.node.name) == self.node.name:     # a row another node wrote on this log is that node's wish, not this one's
                wishes += [w for w in r.get("answer") or [] if isinstance(w, dict) and w.get("wish") in note_reader.BLOCKS]
                self.notes_read.add(str(r.get("text")))
                self.noted = r.get("note_key") or self.noted
            elif k == "wish_ended":
                wishes = [w for w in wishes if (w.get("wish"), w.get("from", "")) != (r.get("wish"), r.get("since"))]
            elif k == "owner_channel" and (r.get("result") or {}).get("status") == "done":
                if r["verb"] in ("close_group", "need_now"):
                    self.policy.closed[r["group"]] = r["role"]
                elif r["verb"] == "open_group":
                    self.policy.closed.pop(r["group"], None)
                elif r["verb"] == "clear_alarm":
                    stop = None
                try:
                    if r["verb"] != "clear_alarm":
                        self._person(r["verb"], r["group"], r.get("name") or "", r.get("value"))
                except Exception as exc:          # a word that can't be put back mustn't stop the node coming back
                    self.log.add("restore_failed", verb=r["verb"], group=r["group"], why=type(exc).__name__)
        if wishes:
            self.node.guard.wishes = wishes
        if stop:
            self.stopped = stop
            self.gate.release_all()
            self._controller("hold", stop)

    # ------------------------------------------------------------------ the workflow
    def enter(self, step: str, ts: str, sale: dict[str, Any] | None = None, request: dict[str, Any] | None = None) -> None:
        """Code moves the node to a step. The step decides whether a device call may run now (ACT_STEPS). The step before ends here."""
        if step not in STEPS:
            raise ValueError(f"no step {step!r}")
        self.leave()
        self.step, self.ts, self.sale = step, ts, sale
        self.shown = None
        self.handed_back = self.handed_back and step != "7 watch"      # a new sale opens its own levers
        if request is not None:
            self.request = request
        self.steps.enter(step, ts, sale=(sale or {}).get("start"), request=(self.request or {}).get("id"))

    def leave(self, outcome: str = "done") -> None:
        if self.step:
            self.steps.leave(self.step, self.ts, outcome)
        self.step = None

    def new_run(self, keep_alarm: bool = False) -> None:
        """A run over the same days again on the same log, as a node host's reset does (agents/host.py). Without this a repeat would answer done and send nothing.
        keep_alarm: the host's reset door has no signature, so an alarm stays on through it, and on the record for a restart."""
        held = self.stopped if keep_alarm else None
        self.leave("new run")
        self.steps.new_run()
        if self.stopped and not held:
            self._controller("clear_stop")        # the restore's stop was the last run's
        self.request, self.acted, self.stopped = None, set(), held
        if held:
            self.log.add("alarm", ts=self.ts, why=held, release={"status": "kept through a reset"})
        self.node.guard.wishes = []
        self.node.guard.clear()
        self.notes_read.clear()
        self.noted = None
        if hasattr(self.node, "noted"):
            self.node.noted = None

    def facts(self) -> dict[str, Any]:
        """What the node reads now. With no sale running, the window ahead stands in, with nothing owed."""
        if self.sale:
            return self._held(self.node.view(self.ts, self.sale))
        start, end = self._window()
        return self._held(self.node.view(self.ts, {"start": start, "end": end, "owed_kw": 0.0, "by_ts": {}}))

    def _held(self, f: dict[str, Any]) -> dict[str, Any]:
        """A stop after an alarm reads as the alarm, so the guard's first step answers it and a replay sees the same."""
        return {**f, "alarm": f.get("alarm") or self.stopped} if self.stopped else f


    def show(self, tools: list[dict[str, Any]]) -> None:
        """A turn that builds its own list says so here: before each call it makes, code shows that one call."""
        self.shown = listed(tools)

    def on_list(self, f: dict[str, Any]) -> dict[str, list[str] | None]:
        """What a device call may name now: the list this step showed, or with none shown, the node's own menu."""
        return self.shown if self.shown is not None else listed(self.node.menu(f, set(), True))

    def after_call(self) -> dict[str, Any] | None:
        """Recording only: each device's state and what is owed, read just after a call. A fault here never reaches the call."""
        if self.step not in ACT_STEPS:
            return None
        try:
            f = self.facts()
            return {"owed_kw": f.get("owed_kw"), "devices": f.get("devices")}
        except Exception:
            return None

    # ------------------------------------------------------------------ calling a tool
    def act(self, tool: str, args: Any, *, start: str, end: str, facts: dict[str, Any] | None = None, who: P.Who = P.AGENT) -> dict[str, Any]:
        """One device call. Repeating it in the same step at the same moment sends nothing. Here the repeat comes back blocked, as the guard's one writer
        per point would say, so the agent doesn't count its kW twice. After a restart the first answer comes back: that memory is gone, and the call is running."""
        f = self._held(facts) if facts is not None else self.facts() if self.step in ACT_STEPS else {}
        target = str(args.get("target", ""))[:64] if isinstance(args, dict) else ""
        if self.step in ACT_STEPS:
            f = {**f, "menu": self.on_list(f)}

        def first() -> dict[str, Any]:
            before = guard_state(self.node.guard)
            self._f = f
            out = run_call(tool, args, start, end, f, self.side, self.step, who, self.policy, self.gate)
            self.log.add("act", step=self.step, ts=self.ts, side=self.side, tool=tool, args=args, start=start, end=end, who={"role": who.role, "via": who.via, "proven": who.proven},
                         inputs=f, guard_before=before, policy_version=self.policy.rules.get("version"), policy_closed=self.policy.closed, after=self.after_call(), **out)
            return out["answer"]
        with self._lock:
            key = ("act", self.step, self.ts, tool, args, start, end)
            k = R.sha(key)
            a = self.steps.once(key, first, lambda x: x["status"] in SENT)
            if a["status"] == "unknown":          # cut off by a crash: it may have reached the device, and it isn't sent again
                return answer("failed", target, why=a["why"])
            if k in self.acted:
                return blocked(a["target"], f'{a["target"]} already took this call in this step, so nothing more was sent.')
            if a["status"] in SENT:
                self.acted.add(k)
            return a

    def _day(self, day: str) -> str:
        return self.ts[:10] if day == "today" else str(date.fromisoformat(self.ts[:10]) + timedelta(days=1))

    # ------------------------------------------------------------------ predict
    def _window(self, day: str = "today") -> tuple[str, str]:
        """The window being traded in steps 5 and 6, then the sale running, then a request still waiting, then the evening."""
        w = (self.request or {}).get("window") or ()
        ask = (w[0], w[1]) if len(w) == 2 and w[0] else None
        if ask and self.step in ("5 offer", "6 commitment"):
            return ask
        if self.sale:
            return self.sale["start"], self.sale["end"]
        if ask:
            return ask
        d = self._day(day)
        return f"{d} {EVENING[0]}", f"{d} {EVENING[1]}"


    def _test_guard(self) -> Any:
        g = copy.copy(self.node.guard)
        for k, v in vars(g).items():
            if isinstance(v, (dict, list, set)) and k != "setup":
                setattr(g, k, copy.deepcopy(v))
        return g

    def dry(self, tool: str, args: dict[str, Any], start: str, end: str, f: dict[str, Any]) -> dict[str, Any]:
        """What the real call would hear now, with no point taken and nothing sent: a plan offers only what would go through, and says why the rest can't."""
        target = str(args.get("target", ""))[:64]
        clean, why = clean_args(device_params(self.side, tool), args)
        v = self.policy.check(P.AGENT, "call", P.group_of(tool))
        why = why or ("" if v["allow"] else v["why"])
        if why:
            return blocked(target, why)
        try:
            return self._test_guard().check({"tool": tool, "args": clean, "start": start, "end": end}, f)
        except Exception as exc:                  # a guard that breaks has said no
            return blocked(target, f"The guard couldn't check this ({type(exc).__name__}).")


    # ------------------------------------------------------------------ the alarm and a person's word
    def alarm(self, why: str, ts: str | None = None) -> None:
        """Life safety: nothing more is sent, and every agent limit releases. It holds when the signal ends and across a restart, until a person clears it
        through the signed channel. The first call does that. Each step calls this again, and that only says the stop again to the controller: the guard reads
        self.stopped and the controller reads its own overrides, and whatever takes one away, they must not come to disagree. ts: when, since the last step
        entered can be hours back."""
        with self._lock:
            if not self.stopped:
                self.stopped = str(why)[:80]
                out = self.gate.release_all()
                self.log.add("alarm", ts=ts or self.ts, why=self.stopped, release=out)
            self._controller("hold", self.stopped)

    def closed_tools(self) -> set[str]:
        """This node's tools in a group a person has closed."""
        return {t for t in self.node.shelf if P.group_of(t) in self.policy.closed}

    def hand_back(self) -> None:
        """The model is gone, so the controller may use every device, except what the owner's wish or a person's closed group keeps out. With no levers at all
        the controller would take those too, and the guard would never be asked."""
        self.handed_back = True
        keep = self._kept()
        if keep and getattr(self.node, "zm", None) is not None:
            if self.node.sim.levers is None:      # no agent call opened anything here: the controller runs it all, so the wish has to hold there
                self.node.hold_out(keep)
            return                                # a building's levers can't open all but a few: what the agent opened stays and the rest stays closed
        self.node.close()
        if keep:
            self._controller("hand_back", keep)

    def _kept(self) -> set[str]:
        g = self.node.guard
        return (g.kept() if hasattr(g, "kept") else note_reader.blocked_tools(g.wishes)) | self.closed_tools()

    def _controller(self, what: str, *args: Any) -> None:
        """The simulated controller's side of what people say. The real controller isn't built, so on real drivers nothing moves here."""
        if isinstance(self.driver, D.SimulatedDriver):
            getattr(self, "_sim_" + what)(*args)

    def owner_channel(self, keys: dict[str, str], seq: dict[str, int] | None = None, save: Callable[[dict[str, int]], Any] | None = None) -> P.OwnerChannel:
        """A person's channel. What people said is back already (_restore): this takes no old message again, including one the node refused, which used its number all the same.
        The log's owner_seq row is written before the word does anything, and a finished word's owner_channel row counts as well, so a log that has only those rows keeps its
        numbers too. seq, save: the node's own file of a person's words (node/person.py)."""
        def person(*a: Any) -> dict[str, Any]:
            with self._lock:
                return self._person(*a)

        def kept(numbers: dict[str, int]) -> None:
            self.log.add("owner_seq", seq=numbers)
            if save:
                save(numbers)
        ch = P.OwnerChannel(self.node.name, self.policy, keys, person, self.log.add, seq, kept)
        for r in self.log.all("owner_seq"):
            for k, n in r["seq"].items():
                ch.seq[k] = max(ch.seq.get(k, 0), n)
        for r in self.log.all("owner_channel"):
            k = keys.get(r["role"]) if isinstance(r.get("role"), str) else None
            if k and (r.get("result") or {}).get("status") == "done":
                ch.seq[k] = max(ch.seq.get(k, 0), r["seq"])
        return ch

    def _person(self, verb: str, group: str, name: str, value: float | None) -> dict[str, Any]:
        if verb == "set_limit":
            return self.driver.set_limit(group, name, float(value))
        if verb == "clear_alarm":
            ov = getattr(getattr(self.node, "sim", None), "overrides", {})
            if ov.get("alarm"):
                return {"status": "blocked", "why": "The alarm is still on."}
            if not self.stopped and "alarm_hold" not in ov:   # a signal over before the next step holds the controller and never reached self.stopped
                return {"status": "blocked", "why": "No alarm is holding this node."}
            self.stopped = None
            self.log.add("alarm_cleared", ts=self.ts)
            self._controller("clear_stop")
            if self._kept():
                self.hand_back()                  # the alarm closed the levers, and with none the controller has every device: a wish or a closed group would stop being kept
            return {"status": "done"}
        if verb == "need_now":
            for c in [c for c in getattr(self.node, "calls", []) if P.group_of(c["tool"]) == group]:
                self.driver.release(c["target"])
        if verb in ("need_now", "close_group", "open_group"):
            self._controller("keep_out", group, verb != "open_group")
        if verb in ("need_now", "close_group") and self.handed_back:
            self._controller("hand_back", self._kept())     # no agent is running the sale, so its levers won't do this
        return {"status": "done"}

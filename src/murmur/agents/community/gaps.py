"""The real-time desk: a buyer's calls during the day and the gaps in members' delivery, filled by the members with room, at a premium.

Messages ride the same signed envelopes as the day-ahead ones (actions added to the demand-flex set): rt_call (buyer to community),
rt_ask / rt_answer (community to members and back), rt_dispatch / rt_confirm, rt_capacity (a member's room) and rt_end (a buyer
ending its call early). A gap is found in a member's readings, not sent: the desk logs each one it takes up (rt_gap).
"""
from __future__ import annotations

import time
from typing import Any

from murmur.protocol import envelope as beckn
from murmur.protocol import ids
from murmur.agents.community.gaps_rules import real
from murmur.agents.community.gaps_calls import GapCalls
from murmur.agents.community.gaps_settle import GapSettle

ANSWER_WAIT_MIN = 5          # dataset minutes the desk waits for answers before it allocates
ANSWER_WAIT_S = 25.0         # live, also this many real seconds (the bus brings the answers in 2-20 s; the node
                             # host checks an idle home's inbox every 15 s); cfg rt_answer_wait_s
NO_ROOM_MIN = 30             # the quiet path doesn't ask a member with nothing to add again for this long
CHASE_EVERY_MIN = 30         # a call settled short: nodes are asked again after this long, and each gap doubles
CHASE_FOR_MIN = 1440         # for this long after the call
# what a node may say about a shortfall on the pool. Free text here would reach the buyers and the community agent's model, so anything else reads "not given"
KNOWN_REASONS = {"the forecast changed", "the owner left the event", "the owner needs the car now", "its battery tripped", "the owner changed the comfort limit",
                 "the building closed for the day", "an event was added in a sold zone", "an alarm is on",
                 "a device is out", "the schedule changed", "an owner's need came first", "another cause"}     # what a node's agent may say (node/calls.py SHORT_WORDS)


class GapDesk(GapCalls, GapSettle):
    def __init__(self, market):
        self.m = market
        self.calls: dict[str, dict[str, Any]] = {}      # call or gap id -> record
        self.reports: dict[str, dict[str, float]] = {}  # home -> {ts: kW short} as last reported
        self.report_wall: dict[str, float] = {}         # home -> when that report was made: a retry can come after the next one
        self.reasons: dict[str, str] = {}
        self.dirty = False                              # a report came since the last check
        self.settled: str | None = None                 # with the clock waiting: the step every node has finished, with all it sent read (set by the waiting clock, conductor.py)
        self.checked_at: str | None = None
        self.absorbed: dict[str, float] = {}            # ts -> kW of shortfall the margin covered (the record)
        self.no_room: dict[str, str] = {}               # member -> when it may be asked again (the quiet path)
        self.warned: dict[str, float] = {}              # first step short -> kW the buyers were last warned of
        self.abnormal: dict[str, str] = {}              # member -> when it said its meter stopped measuring a cut (a building closed)

    # ------------------------------------------------------------------ helpers
    def play(self) -> str:
        return getattr(self.m, "play", "")

    def _mid(self, to: str, action: str, txn: str, *key: Any) -> str:
        return ids.sealed(getattr(self.m, "key", None), self.play(), self.m.name, to, action, txn, *key)

    def _send(self, to: str, action: str, txn: str, message: dict[str, Any]) -> None:
        body = self.m._msg(action, to, txn, message)
        self.m._send(to, action, body, self._mid(to, action, txn, ids.digest(message)))

    def _item(self, to: str, action: str, txn: str, message: dict[str, Any], *key: Any) -> tuple:
        """One message for Market._broadcast: sent in the background (live), so the market lock is not held through
        a Town round trip per home while the homes' answers wait to be handled. key: what it is, or by default what it says: a buyer's confirm goes again when it changes, and
        the same words again are a retry."""
        return (to, action, self.m._msg(action, to, txn, message), self._mid(to, action, txn, *(key or (ids.digest(message),))))

    def _buyers(self) -> list[str]:
        return list(getattr(self.m, "buyers", None) or [self.m.utility])

    def _quiet(self) -> bool:
        return bool(getattr(self.m, "quiet", False))


    # ------------------------------------------------------------------ inbox
    def handle(self, act: str, sender: str, body: dict[str, Any]) -> str | None:
        m = body.get("message") or {}
        if act == "rt_call" and sender in self._buyers():
            c = m["call"]
            if c["id"] in self.calls:
                return f"call {c['id']} already known"
            why = self._call_problem(c) if getattr(self.m, "pooled", False) else None
            if why:
                self.m.log("rt_call_refused", call_id=c["id"], why=why)
                self.m._broadcast([self._item(sender, "rt_confirm", str(c["id"]), {"confirm": {
                    "id": c["id"], "kw": 0.0, "short_kw": real(c.get("kw")) or 0.0, "homes": [], "refused": why}})])
                return beckn.Refused(f"call {c['id']} refused: {why}")
            rec = {"id": c["id"], "kind": c.get("kind", "short_notice"), "start": c["start"], "end": c["end"],
                   "kw": float(c["kw"]), "price": float(c["price_usd_per_kwh"]), "why": c.get("why", ""),
                   "from": sender, "answers": {}, "alloc": {}, "round": 0, "phase": "asking",
                   "received_at": self.m.now(), "readings": {}}
            self.calls[c["id"]] = rec
            self.m.log("rt_call", call_id=c["id"], call_kind=rec["kind"], kw=rec["kw"], start=rec["start"], end=rec["end"],
                       price=rec["price"], why=rec["why"])
            if rec["end"] <= rec["received_at"]:        # it reached the desk after its window (a backlog on the way):
                rec.update({"phase": "dispatched", "confirmed_kw": 0.0, "short_kw": rec["kw"], "homes": 0,   # say so
                            "allocated_at": rec["received_at"], "too_late": True})          # at once; ask nobody
                self.m.log("rt_call_too_late", call_id=c["id"], end=rec["end"], received_at=rec["received_at"])
                self.m._broadcast([self._item(sender, "rt_confirm", c["id"], {"confirm": {
                    "id": c["id"], "kw": 0.0, "short_kw": rec["kw"], "homes": [], "too_late": True}})])
                return beckn.Refused(f"call {c['id']} arrived after its window ({rec['end']}): confirmed 0 kW")
            self._ask(rec, list(self.m.roster))
            return f"call {c['id']}: asked {len(rec.get('asked', []))} homes"
        if act == "rt_answer":
            a = m["answer"]
            rec = self.calls.get(a["id"])
            if not rec or sender not in rec.get("asked", []):
                return beckn.Refused("answer ignored")
            kw = max(0.0, real(a.get("kw", 0.0)) or 0.0)
            rec["answers"][sender] = {"kw": min(kw, getattr(self.m, "rated", {}).get(sender, kw)), "why": a.get("why")}      # no more than its nameplate
            if rec["answers"][sender]["kw"] < 0.05 and not a.get("below_min_price") and "price" not in str(a.get("why") or ""):     # below_min_price: with every node an agent, a reason doesn't come (node/amount.py)
                self.no_room[sender] = beckn.add_minutes(self.m.now(), NO_ROOM_MIN)
            if rec["phase"] == "asking" and (len(rec["answers"]) >= len(rec["asked"]) or self._covered_by_answers(rec)):
                self.allocate(rec)
            return f"{sender} can add {a.get('kw')} kW"
        if act == "rt_capacity":
            pooled = getattr(self.m, "pooled", False)
            if pooled and sender not in self.m.roster:
                self.m.log("rt_report_refused", sender=sender)
                return beckn.Refused("report ignored: not a member")
            made = float((body.get("context") or {}).get("sentWall") or 0.0)
            if made < self.report_wall.get(sender, 0.0):
                return beckn.Refused("report ignored: a newer one is in")
            self.report_wall[sender] = made
            short = self._checked_short(sender, m.get("short")) if pooled \
                else {ts: float(kw) for ts, kw in (m.get("short") or {}).items() if float(kw) > 0.0}
            self.reports[sender] = short
            if m.get("abnormal") and self.abnormal.get(sender, "")[:10] != self.m.now()[:10]:
                self.abnormal[sender] = self.m.now()
            why = "the forecast changed" if m.get("drift") else m.get("reason", "")     # drift: with every node an agent, the one thing check() needs from a reason, which doesn't come (node/amount.py)
            self.reasons[sender] = why if not pooled or (isinstance(why, str) and why in KNOWN_REASONS) else "not given"
            self.dirty = True
            if not short:
                return f"{sender}: no shortfall any more"
            return f"{sender} short {round(max(short.values()), 2)} kW from {min(short)}: checked at the next 5 minutes"
        if act == "rt_end" and sender in self._buyers():
            rec = self.calls.get((m.get("end") or {}).get("id"))
            if not rec or rec.get("from") != sender:
                return beckn.Refused("end for an unknown call")
            if rec.get("end_early"):                        # at-least-once delivery: a second release would take the node below its booking
                return f"call {rec['id']} already ended"
            at = (m.get("end") or {}).get("at") or self.m.now()
            rec["end_early"] = at
            items = []
            for h, slots in rec["alloc"].items():
                rest = {t: -kw for t, kw in slots.items() if t >= at}
                if rest:
                    items.append(self._item(h, "rt_dispatch", rec["id"], {"dispatch": {"id": rec["id"], "steps": rest,
                                                                                       "release": True}}, "release"))
            if items:
                self.m._broadcast(items)
            self.m.log("rt_end", call_id=rec["id"], at=at)
            return f"call {rec['id']} ended at {at}"
        if act == "on_status" and sender in self._buyers() and (m.get("settlement") or {}).get("call_id") in self.calls:
            return self.settlement_in(sender, m["settlement"])
        if act == "on_status" and "performance" in m and m["performance"].get("event_id") in self.calls:
            r = m["performance"]
            self.calls[r["event_id"]]["readings"].setdefault(sender, {}).setdefault(r["slot_id"], r)
            return f"call reading {sender} slot {r['slot_id']}"
        return None

    def _parent(self, ts: str, sender: str) -> tuple[dict[str, Any] | None, list[str]]:
        """What the home owes at `ts` and who can cover it where it is paid for: the booked event (its accepted homes,
        whose readings in the window count in its settlement) or a call (any home: readings go under the call)."""
        for eid, ev in self.m.events.items():
            n = ev["need"]
            if n["window_start"] <= ts < n["window_end"]:
                acc = ev.get("final_meters") or [h for h, c in ev["commitments"].items() if c["status"] == "ACCEPTED"]
                return {"kind": "event", "id": eid}, [h for h in acc if h != sender]
        for rec in self.calls.values():
            if rec["kind"] != "gap" and rec["start"] <= ts < rec["end"]:
                return {"kind": "call", "id": rec["id"]}, [h for h in self.m.roster if h != sender]
        return None, [h for h in self.m.roster if h != sender]


    def chase(self, now: str) -> None:
        """Asks the nodes a call settled without to send its readings again. What comes in is paid as a top-up (the buyer's settle_again, as in demo/runner/buyers/grid_watch.py)."""
        wall, floor = time.time(), 0.0 if self.m.cfg.get("sync_broadcast") else float(self.m.cfg.get("readings_chase_wall_seconds", 120))
        for rec in self.calls.values():
            if not rec.get("lacking") or now >= beckn.add_minutes(rec["end"], CHASE_FOR_MIN):
                continue
            n = rec.get("chases", 0)
            if rec.get("chased_at") and (now < beckn.add_minutes(rec["chased_at"], CHASE_EVERY_MIN * 2 ** n) or wall < rec["chased_wall"] + floor):
                continue
            rec["chased_at"], rec["chased_wall"], rec["chases"] = now, wall, n + 1
            self.m._broadcast([self._item(h, "status", rec["id"], {"readings_wanted": {"event_id": rec["id"], "contract_id": None, "slots": []}}, "chase", n + 1) for h in sorted(rec["lacking"])])
            self.m.log("rt_readings_chased", call_id=rec["id"], round=n + 1, nodes=len(rec["lacking"]))

    def abnormal_slots(self, ev: dict[str, Any]) -> dict[str, list[int]]:
        """Half hours a member's meter can't be paid on: load that fell because a building closed isn't a cut it made."""
        return {h: [s["id"] for s in ev["need"]["slots"] if beckn.add_minutes(s["start"], beckn.SLOT_MINUTES) > t and s["start"][:10] == t[:10]]
                for h, t in self.abnormal.items()}          # closed for that day: the next day's sale pays as usual

    def called_slots(self, ev: dict[str, Any]) -> list[int]:
        """The sale's half hours that a buyer's call covers, whoever placed it."""
        calls = [c for c in self.calls.values() if c["kind"] != "gap"]
        return [s["id"] for s in ev["need"]["slots"]
                if any(c["start"] < beckn.add_minutes(s["start"], beckn.SLOT_MINUTES) and s["start"] < c["end"] for c in calls)]


    def due(self) -> bool:
        """A report has come and the desk hasn't looked since, and it looks at most every 5 minutes."""
        return self.dirty and (self.checked_at is None or self.m.now() >= beckn.add_minutes(self.checked_at, 5))

    def tick(self) -> None:
        now = self.m.now()
        live = not self.m.cfg.get("sync_broadcast")
        wait_s = float(self.m.cfg.get("rt_answer_wait_s", ANSWER_WAIT_S))
        if live:                                        # the bus behind: the answers take that much longer too
            try:
                wait_s += min(float(self.m.cfg.get("rt_answer_wait_max_extra_s", 90.0)), float(self.m.town_lag()))
            except Exception:                           # noqa: BLE001  no lag known: the plain wait
                pass
        for rec in list(self.calls.values()):
            if rec["phase"] == "asking" and now >= beckn.add_minutes(rec["asked_at"], ANSWER_WAIT_MIN) \
                    and (not live or time.time() - rec.get("asked_wall", 0.0) >= wait_s):
                self.allocate(rec)                      # some homes did not answer in time: go with what came
        busy = any(r["kind"] == "gap" and r["phase"] == "asking" for r in self.calls.values())
        if self.due() and not busy and (not self.m.cfg.get("clock_waits") or self.settled == now):      # a held step: not before the step's reports are all in, so every run of a play builds its first gap from the same reports
            self.check()
        if self._quiet():
            self.chase(now)

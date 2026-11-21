"""The community's day-ahead market: one contract per sale with its buyers, delivered by the members that accept a share.

  need received        discover (call for offers) to every member of the roster
  offers in            clear (all offers in, or the clearing's deadline) -> select / init / confirm with each buyer
  buyer ACTIVE         confirm (commitment) to each allocated member; a decline is topped up from spare offers
  window - 2 h         update (event notice) to committed members; the buyers send baselines
  each half hour       members send signed meter readings (on_status) to the community and to the buyers
  window end + 15 min  readings are in -> buyers (update); each answers with actuals and its settlement
  settlement           split and pay by measured delivery, once

The class is assembled from mixins, one module per step: market_above, market_orders, market_clearing, market_delivery, market_settle.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from murmur.protocol import envelope as beckn
from murmur import config
from murmur.protocol import ids
from murmur.settlement import meter_check as mc
from murmur.protocol import wire
from murmur.agents.community.market_rules import READINGS_CHASES, READINGS_EXTRA_MIN, offer_problem
from murmur.agents.community.market_above import MarketAbove
from murmur.agents.community.market_orders import MarketOrders
from murmur.agents.community.market_clearing import MarketClearing
from murmur.agents.community.market_delivery import MarketDelivery
from murmur.agents.community.market_settle import MarketSettle
from murmur.settlement import market_checks

BROADCAST_AGAIN_S = (15, 45)        # what a broadcast's three quick tries couldn't send goes again this much later: past a dropped connection


class Market(MarketAbove, MarketOrders, MarketClearing, MarketDelivery, MarketSettle):
    def __init__(self, name: str, key, send: Callable, clock, roster: list[str], pins: dict[str, str],
                 save_pins: Callable, log: Callable[..., None], cfg: dict[str, Any]):
        self.name, self.key, self.send, self.clock = name, key, send, clock
        self.roster, self.pins, self.save_pins, self.log, self.cfg = roster, pins, save_pins, log, cfg
        self.utility = cfg.get("utility_name", "utility")
        self.buyers = list(cfg.get("buyers") or [self.utility])
        self.pooled = bool(cfg.get("buyers"))              # cfg buyers: fixed orders on a window fill from one pool
        self.rated: dict[str, float] = {}                # each node's nameplate kW, from its enrolment: an offer can't claim more
        self.run_wall = 0.0                              # when this run started: a reading sent before it belongs to the run before
        self.quiet = cfg.get("report_rule") == "exception"   # nodes speak only outside expected limits (report_rule.py)
        self.margin = float(cfg.get("clear_margin", 0.10))
        self.fill = self.pooled and bool(cfg.get("fill_to_ask", True))     # the pool sells to the order, at face value
        self.round2 = self.fill and bool(cfg.get("second_round", True))
        self.fee = float(cfg.get("coordinator_fee_share", 0.0))
        self.events: dict[str, dict[str, Any]] = {}
        self.reputation: dict[str, float] = {}
        self.last_discover_day: str | None = None        # the last day whose discover the utility has answered
        self.other_discover: dict[str, str] = {}         # the same for any other buyer
        self.discover_asked: dict[str, str] = {}         # day -> sim time the discover was last sent (retries)
        self.discover_asked_wall: dict[str, float] = {}  # day -> wall time of that send (retry floor)
        self.discover_rounds: dict[str, int] = {}        # day -> how many times the discover went: asked again, it's a new message
        self.play = ids.new_play()                       # this play of the day, in every id it sends (ids.py): new at each start and at each reset
        self.too_late: set[str] = set()                  # needs that arrived after their deadline (logged once)
        self.orders_refused: dict[str, dict[str, Any]] = {}   # orders the door kept out, by id, with the end of their window (v2_order_refused says each)
        self.failing: dict[str, dict[str, Any]] = {}     # the parts of the tick that are failing now, and how many times in a row. Not kept: a restart finds out again in seconds
        self.lock = threading.RLock()
        self._up_wait = 0.0                                # no row is sent upward before this wall time: set when a send to the level above fails
        self._up_busy = False                              # rows are on their way upward: the next lot waits for them
        self.pool = ThreadPoolExecutor(max_workers=int(cfg.get("send_workers", 8)))
        self.bg = ThreadPoolExecutor(max_workers=1)        # broadcasts run here, one after another
        self.on_clear: Callable | None = None           # the clearing, run off the tick's thread (service.CommunityAgent.c3)
        self.on_settle: Callable | None = None          # the settlement, run off the tick's thread (service.CommunityAgent.c4)
        self.town_lag: Callable[[], float] = lambda: 0.0   # seconds the bus is behind (service.CommunityAgent sets it)
        self.outlook_pool = ThreadPoolExecutor(max_workers=1)   # the community forecast, off the market lock (market_clearing.call_homes)
        from murmur.agents.community.gaps import GapDesk  # the real-time desk: calls, gaps, dispatch (gaps.py)
        self.rt = GapDesk(self)
        self.community = None                            # the community this agent stands for (community.py), set only when its switch is on: the member record's word on an offer, the utility's limit after the clearing, and the report upward

    def reset(self) -> None:
        """Forget all events, reputations and the desk's records (demo: replay the same day again): a new run starts clean."""
        with self.lock:
            self.events.clear()
            self.reputation.clear()
            self.last_discover_day = None
            self.other_discover.clear()
            self.discover_asked.clear()
            self.discover_asked_wall.clear()
            self.discover_rounds.clear()
            self.play = ids.new_play()
            if getattr(self, "community", None) is not None:      # rows of the play that ended aren't sent in the next one
                self.community.outbox.clear()
            self._up_wait = 0.0
            self.too_late.clear()
            self.orders_refused.clear()
            self.failing.clear()
            self.run_wall = time.time()
            self.rt = type(self.rt)(self)                 # its calls, gaps and closed buildings would count against the same day played again

    # ------------------------------------------------------------------ helpers
    def now(self) -> str:
        return self.clock.ts(self.clock.current())

    def _msg(self, action: str, to: str, txn: str, message: dict[str, Any], role: str = "bap",
             ttl_s: float | None = None) -> dict[str, Any]:
        return beckn.make(action, sender=self.name, receiver=to, transaction_id=txn, message=message, key=self.key,
                          sender_role=role, ttl_s=ttl_s)

    def mid(self, to: str, action: str, *key: Any) -> str:
        return ids.sealed(self.key, self.play, self.name, to, action, *key)

    def _send(self, to: str, action: str, body: dict[str, Any], mid: str) -> bool:
        try:
            self.send(to, beckn.kind(action), body, mid)
            wire.note("send", self.name, to, action, body, sim=self.now())
            return True
        except Exception as exc:                                  # one failed send must not stop a broadcast
            self.log("v2_send_error", to=to, action=action, error=str(exc)[:160])
            return False

    # ------------------------------------------------------------------ the level above the community: its aggregator (community.py: asked, outbox)
    def _send_up(self, to: str, kind: str, body: dict[str, Any], mid: str) -> bool:
        """One signed message to the level above, of a kind that isn't a contract step (community.answer, community.report)."""
        try:
            self.send(to, kind, body, mid)
            act = str((body.get("context") or {}).get("action"))
            wire.note("send", self.name, to, act, body, sim=self.now())
            return True
        except Exception as exc:                                  # the level above not being there must not stop the tick
            self.log("v2_send_error", to=to, action=kind, error=str(exc)[:160])
            return False


    def _broadcast(self, items: list[tuple[str, str, dict[str, Any], str]]) -> None:
        """Send to many homes in parallel, in the background: the inbox handler that triggered it must ack its
        Town message within the lease (30 s), or Town hands the message out again. Tests set sync_broadcast."""
        if self.cfg.get("sync_broadcast"):
            self._broadcast_now(items)
        else:
            self.bg.submit(self._broadcast_now, items)

    def _broadcast_now(self, items: list[tuple[str, str, dict[str, Any], str]], again: int = 0) -> None:
        """Sends that failed (a Town timeout) are tried twice more, then again later, off this thread, since nobody sends a payment notice a second time. With
        sync_broadcast (the offline simulation) the sends go out one after another, in roster order, so a run repeats exactly."""
        for attempt in range(3):
            if self.cfg.get("sync_broadcast"):
                ok = [self._send(*it) for it in items]
            else:
                ok = list(self.pool.map(lambda it: self._send(*it), items))
            items = [it for it, good in zip(items, ok) if not good]
            if not items:
                return
            self.log("v2_send_retry", attempt=attempt + 1, failed=len(items))
            time.sleep(2)
        if again < len(BROADCAST_AGAIN_S):
            t = threading.Timer(BROADCAST_AGAIN_S[again], lambda: self.bg.submit(self._broadcast_now, items, again + 1))
            t.daemon = True
            t.start()
        else:
            self.log("v2_send_gave_up", failed=len(items), first=[(it[0], it[1]) for it in items[:8]])

    def _verify(self, sender: str, body: dict[str, Any]) -> bool:
        signer = body.get("signer", "")
        with self.lock:
            if sender not in self.pins and signer:
                self.pins[sender] = signer                         # first contact pins the key
                self.save_pins()
        return beckn.check(body, self.pins.get(sender, ""))

    def _report(self, ev: dict[str, Any]) -> None:
        """For people to read. It comes after the money, so nothing here may undo a sale that was paid."""
        try:
            d = config.state_dir() / "events"
            d.mkdir(exist_ok=True)
            (d / f"{ev['need']['event_id']}.json").write_text(json.dumps(ev, indent=1, default=str))
        except (OSError, TypeError, ValueError) as exc:
            self.log("v2_report_not_written", event_id=ev["need"]["event_id"], error=str(exc)[:160])


    def tick(self) -> None:
        with self.lock:
            self._tick()

    def failed(self, part: str, exc: Exception) -> None:
        """A part of the tick didn't finish. Told once (v2_tick_failed), not every second, and again when the reason changes. `failing` holds it until the part runs."""
        why = f"{type(exc).__name__}: {exc}"[:160]
        was = self.failing.get(part)
        self.failing[part] = {"why": why, "times": (was or {}).get("times", 0) + 1}
        if not was or was["why"] != why:
            self.log("v2_tick_failed", part=part, why=why)

    def _part(self, part: str, f: Callable, *a: Any) -> None:
        """One part of the tick, on its own: a sale that can't be read costs that sale, not every other part of the tick."""
        try:
            f(*a)
            self.failing.pop(part, None)
        except Exception as exc:                            # noqa: BLE001
            self.failed(part, exc)

    def _tick(self) -> None:
        now = self.now()
        day, hm = now[:10], now[11:16]
        if hm >= "10:00":
            for b in self.buyers:
                self._part(f"the discover to {b}", self._ask_buyer, b, day, now)
        self._part("the desk", self.rt.tick)
        self._part("the call for offers", self._call_held, True)
        for eid, ev in list(self.events.items()):
            self._part(f"the sale {eid}", self._tick_sale, ev, now)
        if self.community is not None:                  # one row of the report upward for each quarter hour (community.py)
            self._part("the community's report", self.community.step, self, now)
            self._part("the community's report upward", self.report_up)

    def _tick_sale(self, ev: dict[str, Any], now: str) -> None:
        n = ev["need"]
        ph = ev["phase"]
        if ph == "offers" and "call_held" not in ev:
            self.ask_silent(ev, now)
        lead = -float(self.cfg.get("clear_lead_minutes", 180))      # cleared this long before commit_by: time left for the buyers' contract and the members' commitments
        if ph == "offers" and self.round2 and not self._second_round_over(ev, now, lead):
            return
        if ph == "offers" and (len(ev["offers"]) >= len(self.roster) or now >= beckn.add_minutes(n["commit_by"], lead)):
            (self.on_clear or self.clear_and_commit)(n["event_id"])
        if ph == "cleared" and now >= beckn.add_minutes(ev.get("cleared_at", now), 30):
            self.log("v2_commit_retry", event_id=n["event_id"])    # cleared (C3) but never contracted
            self.commit_to_utility(n["event_id"])
        if ph == "utility":
            tries = ev.get("utility_tries", 1)
            due = self._utility_retry_due(ev, now)
            if now >= n["commit_by"] or (due and tries >= int(self.cfg.get("utility_retries", 5))):
                ev["phase"] = "failed"                         # the utility's deadline passed, or it never answered in utility_retries tries
                self.log("v2_utility_gave_up", event_id=n["event_id"], tries=tries, deadline=n["commit_by"])
            elif due:                                          # select/init/confirm lost on the way: again
                self.log("v2_utility_retry", event_id=n["event_id"], attempt=tries + 1)
                self.commit_to_utility(n["event_id"])
        if ph == "homes" and not ev.get("finalized"):
            self.resend_commitments(ev, now)
        if ph in ("homes", "active") and not ev.get("final_sent") and (ev.get("finalized") or now >= n["commit_by"]
                                                                        or all(c["status"] != "SENT" for c in ev["commitments"].values())):
            self.finalize(ev)                                      # sent again on every tick until Town takes it
        if ev.get("finalized") and not ev.get("notice_sent") and now >= beckn.add_minutes(n["window_start"], -120):
            self.notify_homes(ev)
        if ev.get("final_sent") and not ev.get("telemetry_sent") and now >= beckn.add_minutes(n["window_end"], 15):
            missing = self.missing_readings(ev)
            if not missing:
                self.send_telemetry(ev)
            else:
                self.chase_readings(ev, now, missing)
                wait = float(self.cfg.get("readings_wait_minutes", 120))
                if now >= beckn.add_minutes(n["window_end"], wait + READINGS_EXTRA_MIN) \
                        or (now >= beckn.add_minutes(n["window_end"], wait) and ev.get("chases", 0) >= READINGS_CHASES and self._readings_quiet(ev)):
                    ev["readings_missing"] = missing      # the alarm: the buyers settle on less than was sold, and everyone can see it
                    self.log("v2_readings_missing", event_id=n["event_id"], nodes=len(missing), readings=sum(len(v) for v in missing.values()),
                             chases=ev.get("chases", 0), first=sorted(missing)[:8])
                    self.send_telemetry(ev)
        if ev.get("telemetry_sent") and ev.get("readings_missing"):   # short, here or at a buyer: go on asking for a day. What comes in after the settlement is paid as a top-up
            ev["readings_missing"] = self.missing_readings(ev)
            if ev["readings_missing"] and now < beckn.add_minutes(n["window_end"], 1440):
                self.chase_readings(ev, now, ev["readings_missing"])
        if ev.get("telemetry_sent") and ev["phase"] != "done" and now < beckn.add_minutes(n["window_end"], 1440):
            self.ask_settlement(ev, now)


    # ------------------------------------------------------------------ inbox
    def handle(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        with self.lock:
            try:
                return self._handle(kind, sender, body)
            except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
                if not self.pooled:
                    raise
                self.log("v2_bad_message", sender=sender, message_kind=kind, error=f"{type(exc).__name__}: {exc}"[:160])
                return beckn.Refused("rejected: that message can't be read")     # one sender's junk must not stop the desk for everyone

    def _handle(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        if not self._verify(sender, body):
            self.log("v2_bad_signature", sender=sender, message_kind=kind)
            wire.note("recv", sender, self.name, beckn.action_of(kind), body, ok=False, sim=self.now())
            return beckn.Refused("rejected: bad signature")
        act = beckn.action_of(kind)
        wire.note("recv", sender, self.name, act, body, sim=self.now())
        m = body.get("message", {})
        if act == "on_status" and "batch" in m:             # one envelope of a node's signed readings: each counts as if sent alone
            return beckn.of_batch([self._one_of_batch(kind, sender, b) for b in m["batch"]])
        if act == "on_status" and "performance" in m and sender not in self.buyers:
            why = market_checks.market_refuses(self, sender, m["performance"], body)
            if why:
                return why
        rt = self.rt.handle(act, sender, body)
        if rt is not None:
            return rt
        if sender in self.buyers:
            return self.from_utility(act, body, sender)
        if act == "on_discover" and "offer" in m:
            o = mc.own_kind(m["offer"], sender)
            ev = self.events.get(o["event_id"])
            if not ev or ev["phase"] != "offers" or o.get("home") != sender:
                return beckn.Refused("offer ignored")
            if self.pooled:
                why = "not a member" if sender not in self.roster else "no nameplate on file" if self.rated and sender not in self.rated \
                    else offer_problem(o, {s["id"] for s in ev["need"]["slots"]}, self.rated.get(sender))
                if why:
                    self.log("v2_offer_refused", event_id=o["event_id"], home=sender, why=why)
                    return beckn.Refused(f"offer refused: {why}")
            if self.community is not None:              # the community's member record: who agreed to this kind of sale, and who opted out of this one
                why = self.community.refuses(sender, ev["need"])
                if why:
                    self.log("v2_offer_refused", event_id=o["event_id"], home=sender, why=why)
                    return beckn.Refused(f"offer refused: {why}")
            ev["offers"][sender] = o
            if ev.get("round2") and sender in ev["round2"]["asked"]:
                ev["round2"]["answered"].append(sender)
            return f"offer from {sender}: {o['energy_kwh']} kWh"
        if act == "on_confirm":
            c = m["contract"]
            ev = self.events.get(c["event_id"])
            if not ev or sender not in ev["commitments"]:
                return beckn.Refused("answer ignored")
            cm = ev["commitments"][sender]
            if cm["status"] != "SENT":          # an answer is final: a repeat (Town redelivery, or the home answering
                return f"{sender} answer already recorded ({cm['status']})"   # a re-sent confirm) changes nothing
            if ev.get("finalized") and c["status"] == "ACCEPTED":
                # its yes came after the contract with the buyer was frozen without it (a bad network can hold a yes that long): it is
                # not in the deal, so it is told (signed) to stand down instead of delivering for nothing
                cm["status"], cm["reason"] = "LATE", "accepted after the contract with the buyer was final"
                cid = (cm.get("contract") or {}).get("id") or c.get("id")
                body = self._msg("cancel", sender, ev["ctxn"], {"contract": {"id": cid, "event_id": c["event_id"],
                                                                              "reason": "accepted_after_final"}})
                self._send(sender, "cancel", body, self.mid(sender, "cancel", cid))
                self.log("v2_late_answer_cancelled", event_id=c["event_id"], home=sender, contract_id=cid)
                return f"{sender} accepted after the contract was final: cancelled"
            cm["status"] = c["status"]
            cm["reason"] = c.get("reason")
            if c["status"] == "DECLINED":
                self.top_up(ev, sender)
            return f"{sender} {c['status']} ({c.get('reason')})"
        if act == "on_status" and "performance" in m:
            r = m["performance"]
            ev = self.events.get(r["event_id"])
            if not ev:
                return beckn.Refused("reading ignored")
            if ev.get("finalized") and sender not in (ev.get("final_meters") or []):
                return beckn.Refused("reading ignored: not in the final contract")
            ev["readings"].setdefault(sender, {}).setdefault(r["slot_id"], {**mc.no_bad_truth(r), "signer": body.get("signer"), "sig": body.get("sig"), "signed_body": body})    # the first of a slot stands
            ev["last_reading_wall"] = time.time()
            return f"reading {sender} slot {r['slot_id']}: {r['usage_kw']} kW"
        if act == "on_status" and "node_report" in m:       # step 9's labelled answer: kept for people, and no model here reads it
            r = m["node_report"]
            ev = next((e for e in self.events.values() if e["need"]["window_start"] == r.get("sale")), None)
            if ev is None:
                return beckn.Refused("report ignored: no such sale")
            ev.setdefault("node_reports", {})[sender] = {k: r[k] for k in ("owed_kw", "sold_kwh", "delivered_kwh", "short_kwh") if k in r} if "summary" not in r else \
                {"by": str(r.get("by"))[:8], "summary": str(r.get("summary"))[:400], "facts": r.get("facts")}     # with every node an agent a report is numbers only (node/amount.py)
            self.log("v2_node_report", node=sender, sale=r.get("sale"), by=r.get("by"), facts=len(r.get("facts") or []))
            return f"report from {sender}"
        return beckn.Refused(f"ignored {kind}")

    def _one_of_batch(self, kind: str, sender: str, b: Any) -> str:
        """One reading that can't be read costs that reading: the others in its envelope still count."""
        try:
            if isinstance(b, dict) and "batch" in (b.get("message") or {}):
                raise ValueError("a batch inside a batch")
            out = self._handle(kind, sender, b)
            return out if isinstance(out, str) else str(out)
        except Exception as exc:                            # noqa: BLE001
            self.log("v2_bad_message", sender=sender, message_kind=kind, error=f"{type(exc).__name__}: {exc}"[:160])
            return beckn.Refused("rejected: that reading can't be read")


    MARGINS_SHOWN = (0.05, 0.10, 0.15, 0.20, 0.30)


    def summary(self) -> dict[str, Any]:
        out = {}
        for eid, ev in self.events.items():
            cs = ev["commitments"].values()
            sl = ev["need"].get("slots") or []
            out[eid] = {"phase": ev["phase"], "window": [ev["need"]["window_start"], ev["need"]["window_end"]],
                        "commit_by": ev["need"].get("commit_by"), "final_sent": bool(ev.get("final_sent")),
                        "kw_requested": [s.get("kw_requested") for s in sl], "price": sl[0].get("price") if sl else None,
                        "margin": ev.get("margin"), "margin_thinking": bool(ev.get("margin_asked")) and "margin" not in ev,
                        "offers": len(ev["offers"]), "committed": len(ev["commitments"]),
                        "accepted": sum(1 for c in cs if c["status"] == "ACCEPTED"),
                        "declined": sum(1 for c in cs if c["status"] == "DECLINED"),
                        "capacity_offered_kw": ev.get("capacity_offered_final") or ev.get("capacity_offered"),
                        "readings": sum(len(v) for v in ev["readings"].values()),
                        "readings_expected": sum(len(c["contract"]["commitments"]) for c in cs if c["status"] == "ACCEPTED"),
                        "chases": ev.get("chases", 0), "readings_missing": ev.get("readings_missing") or {}, "readings_refused": ev.get("readings_refused", 0),
                        "baselines": len(ev["baselines"]), "result": ev.get("result"),
                        **({"outlook": ev.get("outlook"), "buyers": sorted(ev.get("orders") or [])} if self.pooled else {})}
        return out

"""A stand-in buyer, built from public data only: it publishes tomorrow's need, places orders, contracts with the community agent, enrols
the members' meters, sends baselines and settles on their signed readings.

  python -m demo.runner.buyers NAME --port PORT
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from typing import Any

from murmur.protocol import envelope as beckn
from murmur import config
from murmur.protocol import ids
from murmur.settlement import rules as st
from murmur.protocol import signing
from murmur.replay import Replay
from murmur.protocol.transport import TownSession
from murmur.protocol.inbox import InboxPoller
from murmur.protocol.inbox import LagMeter
from demo.runner.buyers.utility_orders import UtilityOrders
from demo.runner.buyers.utility_settle import UtilitySettle
from murmur.settlement import market_checks

log = logging.getLogger("murmur-utility")
TICK_S = 2.0                   # the loop's cadence: its next pass starts this long after the last, or at once when its clock is set


class Utility(UtilityOrders, UtilitySettle):
    def __init__(self, key_file: str = "utility.key"):
        """key_file: each buyer loads its own key and no other's, so two buyers starting together share no file."""
        self.cfg = config.load()
        self.name = self.cfg.get("utility_name", "utility")
        self.key = signing.load_or_create(config.CONFIG_DIR / "secrets" / key_file)
        self.pub = signing.public_hex(self.key)
        tok = config.secret("utility_town_token") or config.secret("town_token")
        self.town = TownSession(self.cfg["town_url"], self.cfg["town_run_id"], self.name, tok)
        self.catalog = st.catalog_terms(json.loads(config.events_file().read_text())["message"]["catalogs"][0])
        self.fleet = {h["name"]: h for h in json.loads(config.data_path("fleet_v2.json").read_text())["homes"]}
        from murmur.node import simulator_building as building  # the building nodes this config enables: their meters' history too
        self.fleet.update({b["name"]: building.meter_entry(b) for b in building.enabled(self.cfg)})
        c = self.cfg
        self.clock = Replay(c["clock_profile"], c["replay_start"], c["replay_step_seconds"],
                            c["replay_loop_days"])
        self.pins: dict[str, str] = {}
        self.orders: dict[str, dict[str, Any]] = {}          # event_id -> the buyer agent's order, signed by us
        self.contracts: dict[str, dict[str, Any]] = {}       # transactionId -> contract state
        self.events = deque(maxlen=300)
        self.unsent: deque = deque()                         # replies Town didn't take: sent again on each tick, under the same id
        self.event_days = {beckn.need_from_catalog(r, o)["window_start"][:10]
                           for r, o in self._pairs()}
        self.lock = threading.RLock()
        self.traffic_homes: Counter = Counter()
        self.lag = LagMeter(window=float(c.get("town_lag_window_s", 20.0)))   # how far behind the inbox is
        # Town names allowed to discover and contract with this buyer (the aggregators it has enrolled). Homes only
        # send meter readings, and a reading counts only for the ACTIVE contract its meter is enrolled in.
        self.aggregators = set(c.get("utility_aggregators") or ["community"])
        self.run_wall = 0.0                                  # when this run started (POST /demo/reset): a message sent
                                                             # earlier, still in the inbox, belongs to an earlier run
        self.play = ids.new_play()                           # this play of the day, in the id of every message it sends unasked (ids.sealed): new at each start and each reset
        from demo.runner.buyers.grid_watch import GridWatch  # calls during the day, and their settlement
        self.watch = GridWatch(self)

    def _pairs(self):
        """The DEG needs this buyer publishes: the catalog's, with a buyer agent's order in place of that day's."""
        offers = {o["resourceIds"][0]: o for o in self.catalog["offers"]}
        pairs = {r["id"]: (r, offers[r["id"]]) for r in self.catalog["resources"] if r["id"] in offers}
        for eid, o in self.orders.items():
            pairs[eid] = (o["resource"], o["offer"])
        return list(pairs.values())

    # ------------------------------------------------------------------ the buyer agent's orders (POST /needs)
    # An order (place_order): one day of the dataset, a window on the half hour of at most ORDER_MAX_H hours, at most ORDER_MAX_KW kW
    # per slot at a price of at most ORDER_MAX_PRICE $/kWh, one per day, taken until the day's call for offers goes out (notice_of).
    ORDER_MAX_KW, ORDER_MAX_PRICE, ORDER_MAX_H = 20000.0, 5.0, 4.0
    ORDER_PREFIX = "flex-need-"                         # the event id of a day's order (the catalog's ids)
    PARTICIPANT = "utility-or-engie-mock"               # the buyer's participant id in each order's offer (a wire value)
    CLASS_RATES = False                                 # a call at each class's rate. On the one-buyer path a call pays its nodes all of it, pro rata, so there it stays at the call's price

    @staticmethod
    def notice_of(date: str) -> str:
        """When the community agent can discover a day's needs: from 10:00 the day before."""
        return f"{beckn.add_minutes(f'{date} 00:00', -1440)[:10]} 10:00"


    def contract_of_event(self, event_id: str) -> dict[str, Any] | None:
        """The latest contract for an event (a settled one first)."""
        cs = [c for c in self.contracts.values() if c.get("need", {}).get("event_id") == event_id]
        return next((c for c in reversed(cs) if c.get("status") == "COMPLETE"), cs[-1] if cs else None)

    def evidence(self, event_id: str) -> dict[str, Any]:
        """What this buyer holds about one event (GET /evidence/{event_id}), so its settlement can be checked from the buyer's own record."""
        ct = self.contract_of_event(event_id)
        if not ct:
            raise KeyError(event_id)
        bases = self.settlement_baselines(ct) if ct.get("baselines") else {}
        return {"event_id": event_id, "need": ct["need"], "order": self.orders.get(event_id), "utility_pubkey": self.pub,
                "contract_id": ct.get("contract", {}).get("id"), "status": ct.get("status"),
                "meters": ct.get("meters", []), "pins": {m: self.pins[m] for m in ct.get("meters", []) if m in self.pins},
                "offered": {str(k): v for k, v in (ct.get("offered") or {}).items()},
                "baselines": {m: {s: v for s, v in d.items() if s != "_days"} for m, d in bases.items()},
                "pre_baselines": ct.get("pre_baselines") or {},
                "meter_readings": {m: {str(s): v for s, v in d.items()} for m, d in ct.get("meter_readings", {}).items()},
                "rejected_readings": ct.get("rejected_readings", 0), "settlement": ct.get("settlement"), "owed": ct.get("owed"), "solar": ct.get("solar"), "meter_pre": ct.get("meter_pre") or {},
                "buyer_review": ct.get("buyer_review"),
                **({"share": {str(k): v for k, v in ct["share"].items()}} if ct.get("share") else {}),
                **({"capped": {str(k): v for k, v in ct["capped"].items()}} if ct.get("capped") else {}),
                **({"abnormal": ct["abnormal"]} if ct.get("abnormal") else {})}


    def event(self, kind: str, **d) -> None:
        self.events.append({"at": time.time(), "sim": self.now(), "kind": kind, **d})
        log.info("%s %s", kind, json.dumps(d, default=str)[:300])

    def now(self) -> str:
        return self.clock.ts(self.clock.current())

    def reply(self, to: str, action: str, txn: str, message: dict[str, Any], *key: Any, asked: str | None = None) -> None:
        """A signed message to an aggregator (the community agent). `asked`: what this answers (ids.asked). `key`: what it is, or by default what it says, as with a call's settlement, where each top-up says
        something new. A settlement names its round: a second one in a round that says otherwise would be a fault, and Town refuses it, loudly."""
        # a status (baselines, actuals, the settlement) is a statement of fact: valid for a day (beckn.TTL_EVIDENCE_S)
        body = beckn.make(action, sender=self.name, receiver=to, transaction_id=txn, message=message, key=self.key,
                          sender_role="bpp", ttl_s=beckn.TTL_EVIDENCE_S if action == "on_status" else None)
        item = (to, beckn.kind(action), body, ids.sealed(None if asked else self.key, asked or self.play, self.name, to, action, txn, *(key or (ids.digest(message),))))
        if not self._post(*item):
            self.unsent.append(item)

    def _post(self, to: str, kind: str, body: dict[str, Any], mid: str) -> bool:
        """One send to Town. False if it failed: the caller keeps it and it's sent again on a later tick, so one failed send never loses a settlement."""
        try:
            out = self.town.send(to, kind, body, mid)
        except Exception as exc:                            # noqa: BLE001  the bus away for a moment
            self.event("send_failed", to=to, message_kind=kind, error=str(exc)[:160])
            return False
        if isinstance(out, dict) and out.get("duplicate"):    # Town refused it: see TownSession.send
            self.event("send_dropped", to=to, message_kind=kind, message_id=mid)
        return True


    def _repeat(self, ct: dict[str, Any], sender: str, txn: str, action: str, asked: str | None = None) -> str:
        """A select / init / confirm / update for a contract that has moved past it: the bus delivered it again, or
        the aggregator is retrying because a reply was lost. Nothing changes; an open contract is answered as it
        stands (so a retrying aggregator can carry on), a settled or superseded one gets no answer."""
        status = ct.get("status")
        if status in ("DRAFT", "ACTIVE") and action != "on_status":
            self.reply(sender, action, txn, {"contract": ct["contract"]}, "contract", asked=asked)
            return f"{action} {status} (repeat, nothing changed)"
        if status == "COMPLETE":
            return "already settled"
        return beckn.Refused(f"contract {str(status).lower()}: nothing to do")

    def handle(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        late = beckn.expired(body, default_ttl=float(self.cfg.get("max_message_age_s", 900)))
        if late:                                            # waited in the inbox past its validity: drop it
            self.event("expired_skipped", sender=sender, message_kind=kind, late_s=round(late))
            return beckn.Refused("expired: not acted on")
        sent = ((body or {}).get("context") or {}).get("sentWall") if isinstance(body, dict) else None
        if isinstance(sent, (int, float)) and sent < self.run_wall:
            # sent in an earlier run (a demo reset came after it): its question about another day must not be answered
            # into this run's record
            self.event("stale_skipped", sender=sender, message_kind=kind)
            return beckn.Refused("sent before this run started: not acted on")
        if beckn.action_of(kind) == "on_status" and "batch" in (body.get("message") or {}):
            return beckn.of_batch([self._one_of_batch(kind, sender, b) for b in body["message"]["batch"]])
        if beckn.action_of(kind) == "on_status" and "performance" in (body.get("message") or {}):
            return self.meter_reading(sender, body)
        if sender not in self.aggregators:                # only enrolled aggregators discover and contract
            self.event("sender_refused", sender=sender, message_kind=kind)
            return beckn.Refused("rejected: not an enrolled aggregator")
        signer = body.get("signer", "")
        self.pins.setdefault(sender, signer)
        if not beckn.check(body, self.pins[sender]):
            return beckn.Refused("rejected: bad signature")
        act = beckn.action_of(kind)
        txn = body["context"]["transactionId"]
        m = body["message"]
        asked = ids.asked(body)
        rt = self.watch.handle(act, sender, body)
        if rt is not None:
            return rt
        if act == "discover":
            date = m["intent"]["date"]
            res, offs = [], []
            for r, o in self._pairs():
                n = beckn.need_from_catalog(r, o)
                notice = beckn.add_minutes(f"{beckn.add_minutes(n['window_start'], -1440)[:10]} 10:00", 0)
                if n["window_start"][:10] == date and self.now() >= notice:
                    res.append(r); offs.append(o)
            cat = {**{k: v for k, v in self.catalog.items() if k not in ("resources", "offers")},
                   "resources": res, "offers": offs}
            self.reply(sender, "on_discover", txn, {"catalogs": [cat] if res else []}, "catalogs", asked=asked)
            self.event("on_discover", date=date, needs=[r["id"] for r in res])
            return f"{len(res)} needs for {date}"
        if act == "select":
            prev = self.contracts.get(txn)
            if prev and prev.get("seller", sender) != sender:
                return beckn.Refused("rejected: this transaction belongs to another aggregator")
            if prev and prev.get("status") in ("DRAFT", "ACTIVE", "COMPLETE", "SUPERSEDED"):
                return self._repeat(prev, sender, txn, "on_select", asked)    # delivered again: the contract stays as it is
            ct = self.contracts.setdefault(txn, {"seller": sender, "status": "NEW"})
            rid = m["contract"]["commitments"][0]["resources"][0]["id"]
            r, o = next((r, o) for r, o in self._pairs() if r["id"] == rid)
            for t, other in self.contracts.items():       # one open contract per aggregator and event: a new
                if t != txn and other.get("seller") == sender and other.get("status") in ("DRAFT", "ACTIVE") \
                        and other.get("need", {}).get("event_id") == rid:   # transaction supersedes the open one
                    other["status"] = "SUPERSEDED"
                    self.event("contract_superseded", event_id=rid, transaction=t)
            ct.update({"need": beckn.need_from_catalog(r, o), "resource": r, "offer": o, "status": "DRAFT"})
            contract = {"id": f"contract-{rid}", "status": "DRAFT", "event_id": rid,
                        "contractAttributes": {**o["offerAttributes"]["contractAttributes"],
                                               "roles": [{"role": "buyer", "participantId": "utility-or-engie-mock"},
                                                         {"role": "seller", "participantId": None}]}}
            ct["contract"] = contract
            self.reply(sender, "on_select", txn, {"contract": contract}, "contract", asked=asked)
            return "on_select DRAFT"
        ct = self.contracts.get(txn)
        if not ct or "need" not in ct:
            return beckn.Refused("unknown transaction")
        if ct.get("seller") != sender:                # follow-ups only from the aggregator that selected
            self.event("sender_refused", sender=sender, message_kind=kind, transaction=txn)
            return beckn.Refused("rejected: not this contract's aggregator")
        if ct.get("status") == "SUPERSEDED":
            return beckn.Refused("contract superseded by a newer transaction")
        if act == "init":
            if ct.get("status") != "DRAFT":               # init again after confirm (redelivery or the aggregator's
                return self._repeat(ct, sender, txn, "on_init", asked)    # retry): the confirmed meters and capacity stay
            c = m["contract"]
            ct["contract"]["contractAttributes"]["roles"][1]["participantId"] = c.get("seller")
            ct.update({"meters": self._enroll(ct, c.get("participatingMeters", [])),
                       "offered": {int(k): float(v) for k, v in c.get("capacityOffered", {}).items()}})
            self._pool_terms(ct, c)
            self.reply(sender, "on_init", txn, {"contract": ct["contract"]}, "contract", asked=asked)
            return "on_init"
        if act == "confirm":
            if ct.get("status") == "COMPLETE":
                return self._repeat(ct, sender, txn, "on_confirm", asked)  # a settled contract is never reopened
            ct["contract"]["status"] = ct["status"] = "ACTIVE"
            self.reply(sender, "on_confirm", txn, {"contract": ct["contract"]}, "contract", asked=asked)
            self.event("contract_active", event_id=ct["need"]["event_id"], meters=len(ct.get("meters", [])),
                       offered=ct.get("offered"))
            return "on_confirm ACTIVE"
        if act == "update" and "telemetry_done" in m:
            if ct.get("status") == "COMPLETE":
                if ct.get("settled_msg"):                 # the community agent is still waiting for it, or this is a repeat, which it ignores
                    self.reply(sender, "on_status", txn, ct["settled_msg"], "settled", ct.get("top_ups", 0), asked=asked)
                return "already settled"
            ct["settle_to"] = (sender, txn)
            ct["called_slots"] = m["telemetry_done"].get("called_slots") or []
            ct["abnormal"] = {h: [int(x) for x in v] for h, v in (m["telemetry_done"].get("abnormal") or {}).items()}
            ct["owed"] = market_checks.owed_of(m["telemetry_done"].get("owed"))
            if self._readings_complete(ct):
                return self.settle(ct)
            if not ct.get("settle_requested"):
                ct["settle_requested"] = True             # settle anyway once the wait is over (replay clock, see tick)
                ct["settle_by"] = beckn.add_minutes(self.now(), float(self.cfg.get("utility_settle_wait_minutes", 30)))
                ct["settle_requested_wall"] = time.time()
                self.reply(sender, "on_status", txn, {"readings_lacking": self._lacking(ct)}, "lacking", asked=asked)   # only this buyer knows what reached it
            return "waiting for the last meter readings"
        if act == "update":
            if ct.get("status") == "COMPLETE":
                return self._repeat(ct, sender, txn, "on_status", asked)
            c = m["contract"]
            ct["meters"] = self._enroll(ct, c.get("participatingMeters", ct.get("meters", [])))
            ct["offered"] = {int(k): float(v) for k, v in c.get("capacityOffered", {}).items()} or ct.get("offered", {})
            self._pool_terms(ct, c)
            if c.get("meterSlots"):                       # the slots each meter committed to (it reports only those)
                ct["meter_slots"] = {h: [int(x) for x in v] for h, v in c["meterSlots"].items()}
            ct["baselines"] = self.baselines(ct, ct["meters"])
            self.reply(sender, "on_status", txn, {"contract": {"id": ct["contract"]["id"]},
                                                  "performance": {"kind": "baselines", **({"rule": ct["baseline_rule"]} if ct.get("baseline_rule") else {}), "methodology": st.baseline_rule(),
                                                                  "models": None,
                                                                  "meters": {k: {s: v for s, v in d.items() if s != "_days"}
                                                                             for k, d in ct["baselines"].items()}}}, "baselines", asked=asked)
            self.event("baselines_sent", event_id=ct["need"]["event_id"], meters=len(ct["baselines"]))
            return f"baselines for {len(ct['baselines'])} meters"
        return beckn.Refused(f"ignored {kind}")

    # ------------------------------------------------------------------ meter data and settlement
    def _one_of_batch(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        """A reading can set off the settlement. Whatever goes wrong there, the readings behind it in the envelope still count."""
        try:
            out = self.handle(kind, sender, body)
            return out if isinstance(out, str) else str(out)
        except Exception as exc:                            # noqa: BLE001
            self.event("reading_error", home=sender, error=str(exc)[:200])
            log.exception("a reading from %s", sender)
            return beckn.Refused(f"error: {str(exc)[:80]}")


    def tick(self) -> None:
        """Settle a contract whose readings are still incomplete once its wait (replay minutes) is over and no reading
        has come for `utility_settle_quiet_s` real seconds: readings still on their way through a busy Town, or waiting
        in the inbox of a machine that was asleep, are counted before the money is split, however fast the replay clock
        runs or however far it jumped. The demo stack sets the quiet time at the run's pace, the process (__main__)
        takes 30 s when the configuration has none, and without either it is 0."""
        with self.lock:
            while self.unsent and self._post(*self.unsent[0]):
                self.unsent.popleft()
            try:
                self.watch.tick()
            except Exception as exc:                      # noqa: BLE001  the sale's settlement below doesn't wait on the calls
                self.event("tick_error", error=str(exc)[:200])
            now = self.now()
            quiet = float(self.cfg.get("utility_settle_quiet_s", 0.0))
            for ct in self.contracts.values():
                last = max(ct.get("last_reading_wall", 0.0), ct.get("settle_requested_wall", 0.0))
                try:                                      # one contract that can't be settled doesn't hold up the next
                    if ct.get("settle_requested") and ct.get("status") == "ACTIVE" and now >= ct.get("settle_by", now) \
                            and time.time() - last >= quiet:
                        self.event("settle_late", event_id=ct["need"]["event_id"],
                                   readings=sum(len(v) for v in ct.get("meter_readings", {}).values()))
                        self.settle(ct)
                    if ct.get("status") == "COMPLETE" and ct.get("late_readings") and time.time() - ct.get("late_wall", 0.0) >= quiet:
                        self.settle(ct, top_up=True)      # readings came after the settlement: the sellers are owed for them
                except Exception as exc:                  # noqa: BLE001
                    self.event("settle_error", event_id=(ct.get("need") or {}).get("event_id"), error=str(exc)[:200])
                    log.exception("settling a contract")

    def tick_loop(self) -> None:
        f = self.clock.follower
        while True:
            seen, now = f.moves, self.now()
            try:
                self.tick()
                if not self.unsent:                           # a reply the bus didn't take goes again on the next pass: this one wasn't whole
                    f.passed(seen, now)
            except Exception as exc:
                self.event("tick_error", error=str(exc)[:200])
            f.wait(seen, TICK_S)


    def inbox_loop(self) -> None:
        """The Town inbox, watched with short checks (inbox.InboxPoller: no held long-poll, which costs Town many database
        scans a second): every `town_poll_seconds` (1 s by default) while messages flow, every `town_poll_idle_seconds`
        (3 s by default) after a quiet minute. A pass that finds a message brings in `utility_inbox_workers` claimers
        (12 by default): each claim and each ack is a round trip to Town, so one claimer alone falls far behind the
        hundreds of meter readings an event brings."""
        self.poller = InboxPoller(self.town, self._handle_claimed, every=float(self.cfg.get("town_poll_seconds", 1.0)),
                                  idle_every=float(self.cfg.get("town_poll_idle_seconds", 3.0)),
                                  claimers=max(1, int(self.cfg.get("utility_inbox_workers", 12))),
                                  on_error=lambda where, exc: self.event("town_error", error=f"{where}: {str(exc)[:200]}"))
        self.poller.run()

    def _handle_claimed(self, msg: dict[str, Any]) -> None:
        self.lag.seen(msg)                                # how far behind this inbox is (GET /traffic, /health)
        with self.lock:
            try:
                note = self.handle(msg.get("kind", ""), msg.get("from"), msg.get("body") or {})
            except Exception as exc:
                note = beckn.Refused(f"error: {exc}")
                log.exception("handle")
        self.town.ack(msg["message_id"], msg["fence"], *beckn.ack_of(note, 300))

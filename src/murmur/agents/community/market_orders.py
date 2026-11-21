"""The buyers' side of a sale: orders taken at the door, the pool they share, and the contract steps (select, init, confirm, update) with each buyer."""
from __future__ import annotations

import time
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.protocol import ids
from murmur.agents.community.market_rules import CALL_HOLD_S, need_problem
from murmur.settlement import market_checks


class MarketOrders:
    """The buyers' side of a sale: orders taken at the door, the pool they share, and the contract steps (select, init, confirm, update) with each buyer."""

    # ------------------------------------------------------------------ utility side (C3 grid interface)
    def from_utility(self, act: str, body: dict[str, Any], sender: str | None = None) -> str:
        m = body["message"]
        sender = sender or self.utility
        if act == "on_discover":
            txn = body.get("context", {}).get("transactionId", "")
            if txn.startswith("discover-"):                       # the buyer answered that day's discover
                if sender == self.utility:
                    self.last_discover_day = max(self.last_discover_day or "", txn[len("discover-"):])
                else:
                    self.other_discover[sender] = max(self.other_discover.get(sender, ""), txn[len("discover-"):])
            new = []
            for cat in m.get("catalogs", []):
                offers = {o["resourceIds"][0]: o for o in cat.get("offers", [])}
                for res in cat.get("resources", []):
                    if res["id"] in self.events or res["id"] not in offers:
                        continue
                    need = self._order_at_door(res, offers[res["id"]], sender)
                    if need is None:
                        continue
                    last = beckn.add_minutes(need["commit_by"], -float(self.cfg.get("clear_lead_minutes", 180)))
                    if self.now() >= last:                        # no time left to collect offers (e.g. an answer
                        if need["event_id"] not in self.too_late:  # that waited in a backlog): do not start it
                            self.too_late.add(need["event_id"])
                            self.log("v2_need_too_late", event_id=need["event_id"], commit_by=need["commit_by"],
                                     now=self.now())
                        continue
                    od = self._new_order(need, sender, offers[res["id"]])
                    if self.pooled and self._join(need, od):
                        continue
                    self.events[need["event_id"]] = {"need": need, "phase": "offers", "offers": {}, "commitments": {},
                                                     "readings": {}, "baselines": {}, "utxn": od["utxn"],
                                                     "ctxn": f"community-{need['event_id']}", "log": [], "orders": {sender: od}}
                    new.append(need["event_id"])
                    self.events[need["event_id"]]["call_held"] = time.time()
            self._call_held()
            return f"needs received: {new or 'none new'}"
        ev = self._event_by_utxn(body["context"]["transactionId"])
        if not ev:
            return beckn.Refused("unknown transaction")
        od = self._order_of(ev, body["context"]["transactionId"])
        first = od["utxn"] == ev["utxn"]
        c = m.get("contract", {})
        if act in ("on_select", "on_init", "on_confirm") and ev["phase"] != "utility":
            return f"duplicate {act} ignored"              # the bus delivers at least once: be idempotent
        if act in ("on_select", "on_init", "on_confirm"):
            od["contract"] = c
            if first:
                ev["utility_contract"] = c
        if act == "on_select":
            self._to_order(ev, od, "init", {"contract": {**c, "seller": "murmur-community",
                                                         "participatingMeters": sorted(ev["alloc"]),
                                                         "capacityOffered": {str(k): v for k, v in
                                                                             self._tranche(ev, od, ev["capacity_offered"]).items()},
                                                         **self._terms(ev, od, ev["capacity_offered"])}})
            return "on_select -> init"
        if act == "on_init":
            self._to_order(ev, od, "confirm", {"contract": c})
            return "on_init -> confirm"
        if act == "on_confirm":
            od["active"] = c.get("status") == "ACTIVE"
            if all(o.get("active") for o in self._orders(ev)):    # every buyer is signed: now the nodes get their contracts
                ev["phase"] = "homes"
                self.commit_homes(ev, sorted(ev["alloc"]))
            return f"utility contract {c.get('status')}"
        if act == "on_status":
            if "readings_lacking" in m:                   # the community agent may have them all and this buyer not: the nodes are asked for it too
                why = market_checks.lacking_problem(m["readings_lacking"])
                if why:
                    self.log("v2_bad_message", sender=od["buyer"], why=why)
                    return beckn.Refused(f"rejected: {why}")
                if not od.get("settlement"):              # its settlement says the same, and later: this one may be a repeat
                    od["lacking"] = m["readings_lacking"]
                    ev["readings_missing"] = self.missing_readings(ev)
                return f"{od['buyer']} lacks readings from {len(m['readings_lacking'])} meters"
            perf = m.get("performance", {})
            if perf.get("kind") == "baselines":
                why = market_checks.baselines_problem(perf.get("meters"))
                if why:
                    self.log("v2_bad_message", sender=od["buyer"], why=why)
                    return beckn.Refused(f"rejected: {why}")
                if first or not ev.get("baselines"):
                    ev["baselines"] = perf["meters"]
                    if perf.get("rule"):                # the buyer's baseline is a stand-in: which rule, and on how many days it rests, on the record (v2_baseline_flagged)
                        ev["baseline_rule"] = perf["rule"]
                        self.log("v2_baseline_flagged", event_id=ev["need"]["event_id"], buyer=sender, **{k: perf["rule"].get(k) for k in ("rule", "days")})
                return f"baselines for {len(perf['meters'])} meters"
            if perf.get("kind") == "actuals":
                if not ev.get("result") and first and isinstance(perf.get("meters"), dict):
                    ev["actuals"] = perf["meters"]
                    if ev.get("settle_waiting"):
                        self.settle(ev["need"]["event_id"])       # a settlement without actuals was waiting for them
                return "actuals received"
            if "settlement" in m:
                s = m["settlement"]
                why = market_checks.settlement_problem(s)
                if why:                                           # the split would stop on it, and every seller with it. It's asked for again (ask_settlement)
                    od["refused"] = why                           # the alarm says so, until a settlement that can be read comes
                    self.log("v2_settlement_refused", event_id=ev["need"]["event_id"], buyer=od["buyer"], why=why)
                    return beckn.Refused(f"settlement refused: {why}")
                od.pop("refused", None)
                if od.get("settlement") and int(s.get("top_up") or 0) <= int(od["settlement"].get("top_up") or 0):
                    return "duplicate settlement ignored"        # the bus delivers at least once, in any order: a buyer's latest stands
                if s.get("top_up") and (ev.get("result") or ev["phase"] == "settling"):
                    return self.top_up_settlement(ev, od, first, s)
                if ev.get("result") or ev["phase"] in ("settling", "done"):
                    return "duplicate settlement ignored"        # the bus delivers at least once: settle once
                od["settlement"], od["lacking"] = s, s.get("lacking") or {}
                if first:
                    if isinstance(s.get("actuals"), dict):        # the actuals travel inside the settlement
                        ev["actuals"] = s["actuals"]
                    ev["settlement"] = s
                if all(o.get("settlement") for o in self._orders(ev)):
                    (self.on_settle or self.settle)(ev["need"]["event_id"])
                return "settlement received"
        return beckn.Refused(f"ignored utility {act}")

    def _order_at_door(self, res: dict[str, Any], offer: dict[str, Any], buyer: str) -> dict[str, Any] | None:
        """This order's need, or None if it stays out. One buyer's junk costs that order and no other. The refusal is on the record (v2_order_refused, and orders_refused until its
        window is over): the buyer thinks it has placed an order, and nobody else would tell it, or anyone, that it hasn't."""
        if not self.pooled:
            return beckn.need_from_catalog(res, offer)
        eid = str(res.get("id"))[:120]
        try:
            need = beckn.need_from_catalog(res, offer)
            why = need_problem(need, ((offer.get("offerAttributes") or {}).get("deposit") or {}).get("usd"))
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
            need, why = None, f"it can't be read: {type(exc).__name__}"
        if why is None:
            self.orders_refused.pop(eid, None)
            return need
        self.orders_refused[eid] = {"buyer": buyer, "why": why, "until": beckn.add_minutes(self.now(), 2880) if need is None else need.get("window_end")}
        self.log("v2_order_refused", event_id=eid, buyer=buyer, why=why)
        return None

    def _orders(self, ev: dict[str, Any]) -> list[dict[str, Any]]:
        """The orders this sale fills. An event that carries no orders has the utility's alone."""
        if not ev.get("orders"):
            ev["orders"] = {self.utility: {"buyer": self.utility, "need": ev["need"], "utxn": ev["utxn"], "deposit_usd": 0.0}}
        return list(ev["orders"].values())

    def _new_order(self, need: dict[str, Any], buyer: str, offer: dict[str, Any]) -> dict[str, Any]:
        """One buyer's fixed order. A deposit travels in its signed offer (as the demo's stand-in buyer places it, demo/runner/buyers/utility_orders.py)."""
        dep = (offer.get("offerAttributes") or {}).get("deposit") or {}
        return {"buyer": buyer, "need": need, "utxn": f"order-{need['event_id']}-{ids.digest(self.play, buyer)}", "deposit_usd": max(0.0, float(dep.get("usd") or 0.0))}

    def _call_held(self, late: bool = False) -> None:
        """A sale's call for offers goes out once every buyer asked today has answered, so a node reads the whole pool and not one buyer's line (2,726 kW of a 4,362 kW order).
        Offline they answer in the same step. Live a buyer that stays silent holds the call back for CALL_HOLD_S at most, and then it goes with what is in."""
        day = self.now()[:10]
        waiting = [b for b in self.buyers if (self.last_discover_day if b == self.utility else self.other_discover.get(b)) != day and (day if b == self.utility else f"{b}:{day}") in self.discover_asked]
        for ev in self.events.values():
            held = ev.get("call_held")
            if held is not None and (not waiting or not self.pooled or (late and (self.cfg.get("sync_broadcast") or time.time() >= held + CALL_HOLD_S))):
                del ev["call_held"]
                self.call_homes(ev)

    def _pool_need(self, ev: dict[str, Any]) -> dict[str, Any]:
        """The call as a node reads it: what all the orders on this sale ask."""
        n = ev["need"]
        if not self.pooled:
            return n
        return {**n, "pool": {"orders": len(self._orders(ev)), "members": len(self.roster), "kw": {str(s["id"]): round(self._asked(ev, s), 2) for s in n["slots"]}}}

    def _join(self, need: dict[str, Any], od: dict[str, Any]) -> bool:
        """True if this order is dealt with here: it joins the open sale on its window, or it's refused for overlapping one on another
        window, since a node can owe only one thing at a time."""
        for ev in self.events.values():
            n = ev["need"]
            if need["window_start"] >= n["window_end"] or need["window_end"] <= n["window_start"]:
                continue
            same = (need["window_start"], need["window_end"]) == (n["window_start"], n["window_end"])
            if same and od["buyer"] in ev.get("orders", {}):
                return True                                       # the same buyer's order, heard again
            if same and ev["phase"] == "offers":
                ev["orders"][od["buyer"]] = od
                self.log("v2_order_joined", event_id=n["event_id"], buyer=od["buyer"], order=need["event_id"],
                         kw=need["slots"][0]["kw_requested"])
                return True
            self.orders_refused[need["event_id"]] = {"buyer": od["buyer"], "why": f"its window overlaps the sale {n['event_id']} in phase {ev['phase']}",
                                                     "until": need["window_end"]}          # kept out like an order the door refused, and on the same record
            self.log("v2_order_refused", event_id=need["event_id"], buyer=od["buyer"], overlaps=n["event_id"], phase=ev["phase"])
            return True
        return False

    def _event_by_utxn(self, txn: str) -> dict[str, Any] | None:
        return next((e for e in self.events.values() if e["utxn"] == txn or any(o["utxn"] == txn for o in self._orders(e))), None)

    def _order_of(self, ev: dict[str, Any], txn: str) -> dict[str, Any]:
        return next(o for o in self._orders(ev) if o["utxn"] == txn)

    def _to_order(self, ev: dict[str, Any], od: dict[str, Any], action: str, message: dict[str, Any],
                  ttl_s: float | None = None, key: tuple = ()) -> bool:
        """key: what this message is. The default is a contract step of this round of select, init, confirm. All of a round's steps are retries of each other: a step answered
        twice goes once. A later round (a lost answer, after `utility_retry_minutes`) goes again, all the way."""
        body = self._msg(action, od["buyer"], od["utxn"], message, ttl_s=ttl_s)
        ok = self._send(od["buyer"], action, body, self.mid(od["buyer"], action, od["utxn"], *(key or ("try", ev.get("utility_tries", 1)))))
        self.log(f"v2_utility_{action}", event_id=ev["need"]["event_id"], sent=ok, **({"buyer": od["buyer"]} if self.pooled else {}))
        return ok

    def _to_utility(self, ev: dict[str, Any], action: str, message: Any, ttl_s: float | None = None, key: tuple = ()) -> bool:
        """To every buyer of this sale. message: the same for each, or a function of the order."""
        ok = True
        for od in self._orders(ev):
            ok = self._to_order(ev, od, action, message(od) if callable(message) else message, ttl_s, key) and ok
        return ok

    def _tranche(self, ev: dict[str, Any], od: dict[str, Any], cap: dict[int, float]) -> dict[int, float]:
        """This buyer's part of the capacity sold."""
        if not self.pooled:
            return cap
        share = od.get("share") or {}
        return {k: round(float(v) * share.get(k, 0.0), 2) for k, v in cap.items()}

    def _terms(self, ev: dict[str, Any], od: dict[str, Any], cap: dict[int, float]) -> dict[str, Any]:
        """What a buyer needs to settle its share of the pool. Nothing on the one-buyer path."""
        if not self.pooled:
            return {}
        return {"community_event": ev["need"]["event_id"], "poolCapacity": {str(k): v for k, v in cap.items()},
                "share": {str(k): round(v, 6) for k, v in (od.get("share") or {}).items()},
                "firm": {str(k): round(v, 2) for k, v in (od.get("firm") or {}).items()},
                "reserved": {str(k): round(v, 2) for k, v in (od.get("reserved") or {}).items()},
                "deposit_held_usd": round(float(od.get("deposit_held_usd") or 0.0), 4), "pooled_offer": ev.get("pooled_offer")}

    def commit_to_utility(self, event_id: str) -> dict[str, Any]:
        ev = self.events[event_id]
        if ev["phase"] not in ("cleared", "utility"):     # not cleared yet, or contracted already
            return {"sent": None, "event_id": event_id, "phase": ev["phase"]}
        if not any(float(v) > 0 for v in (ev.get("capacity_offered") or {}).values()):
            ev["phase"] = "no_offer"                      # nothing to sell: no contract, no retries
            self.log("v2_no_capacity", event_id=event_id, offers=len(ev["offers"]))
            return {"sent": None, "event_id": event_id, "phase": "no_offer"}
        ev["phase"] = "utility"
        ev["utility_asked_at"] = self.now()
        ev["utility_asked_wall"] = time.time()
        ev["utility_tries"] = ev.get("utility_tries", 0) + 1
        for od in self._orders(ev):
            if not od.get("active"):
                self._to_order(ev, od, "select", {"contract": {"commitments": [{"resources": [{"id": od["need"]["event_id"]}],
                                                                                "offer": {"id": od["need"]["offer_id"]}}]}})
        return {"sent": "select", "event_id": event_id}

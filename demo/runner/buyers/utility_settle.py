"""The stand-in buyer's meter readings and settlement: each signed reading checked, and the sale settled once the readings are in."""
from __future__ import annotations

import time
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.settlement import rules as st
from murmur.protocol import wire
from murmur.settlement import meter_check as mc


class UtilitySettle:
    """The stand-in buyer's meter readings and settlement: each signed reading checked, and the sale settled once the readings are in."""

    def meter_reading(self, sender: str, body: dict[str, Any]) -> str:
        """A home's own signed reading for one slot (the utility's meter data). Checked against the key the utility
        pinned for that meter on first contact; a reading changed on the way is counted and thrown out."""
        r = body["message"]["performance"]
        self.traffic_homes["on_status"] += 1                 # GET /traffic: a reading is the one message a home sends this buyer
        if not isinstance(r, dict) or not isinstance(r.get("event_id"), str):
            self.event("reading_unmatched", home=sender, event_id=None)
            return beckn.Refused("reading ignored: it names no event")
        with self.lock:
            if r.get("event_id") in self.watch.calls:        # a half hour of a call the home was dispatched for
                ok = self.watch.reading(sender, body)
                wire.note("recv", sender, self.name, "on_status", body, ok=not isinstance(ok, beckn.Refused), sim=self.now())
                return ok
            ct = self._contract_of_meter(sender, r.get("event_id"))   # the ACTIVE contract this meter is enrolled in
            if not ct:
                self.event("reading_unmatched", home=sender, event_id=r.get("event_id"))
                return beckn.Refused("reading ignored: this meter is in no active contract for that event")
            pin = self.pins.setdefault(sender, body.get("signer", ""))
            ok = beckn.check(body, pin) and r.get("home") == sender
            wire.note("recv", sender, self.name, "on_status", body, ok=ok, sim=self.now())
            if not ok:
                ct["rejected_readings"] = ct.get("rejected_readings", 0) + 1
                self.event("reading_rejected", home=sender, event_id=r.get("event_id"))
                return beckn.Refused("rejected: bad signature")
            why = mc.buyer_refuses(ct, sender, r, self.event)   # what can't be true never reaches the money, and it's counted
            if why:
                return why
            pre = mc.pre_kw(ct, sender, r, self.event)
            if ct.get("status") == "COMPLETE" and int(r["slot_id"]) not in ct.get("meter_readings", {}).get(sender, {}):
                ct["late_readings"], ct["late_wall"] = ct.get("late_readings", 0) + 1, time.time()
            ct.setdefault("meter_readings", {}).setdefault(sender, {}).setdefault(int(r["slot_id"]), float(r["usage_kw"]))     # the first of a slot stands: small repeats can't walk it anywhere
            ct.setdefault("meter_committed", {}).setdefault(sender, {})[int(r["slot_id"])] = float(r.get("committed_kw") or 0.0)
            ct.setdefault("meter_batt", {}).setdefault(sender, {}).setdefault(int(r["slot_id"]), float(r.get("battery_kw") or 0.0))
            if pre is not None:
                ct.setdefault("meter_pre", {})[sender] = pre
            ct["last_reading_wall"] = time.time()
            if ct.get("settle_requested") and ct.get("status") != "COMPLETE" and self._readings_complete(ct):
                return self.settle(ct)
            return f"reading {sender} slot {r['slot_id']}"

    def _lacking(self, ct: dict[str, Any]) -> dict[str, list[int]]:
        """The slots each participating meter committed to that this buyer has no reading for (a home with no commitment in a
        slot sends no reading for it). Without the community agent's per-meter slots: every slot of the window."""
        got = ct.get("meter_readings", {})
        every = [int(s["id"]) for s in ct["need"]["slots"]]
        slots = ct.get("meter_slots") or {}
        out = {m: sorted(set(slots.get(m, every)) - set(got.get(m, {})) - set((ct.get("rejected_slots") or {}).get(m, {}))) for m in ct.get("meters", [])}   # a reading refused came: nobody waits for another
        return {m: v for m, v in out.items() if v}

    def _readings_complete(self, ct: dict[str, Any]) -> bool:
        return not self._lacking(ct)

    def settle(self, ct: dict[str, Any], top_up: bool = False) -> str:
        """DEG demand-flex settlement on the participating meters' own readings against their baselines. `top_up`: settled again on readings
        that came in after the first settlement. The whole result goes again, and the community agent pays what it adds."""
        sender, txn = ct["settle_to"]
        prior = float((ct.get("settlement") or {}).get("total") or 0.0)
        need = ct["need"]
        bases = self.settlement_baselines(ct)
        meters, notes = mc.counted(ct, bases)
        rule = ct.get("baseline_rule")
        without = sorted(m for m in ct.get("meters", []) if (ct.get("meter_readings") or {}).get(m) and not any(k != "_days" for k in bases.get(m, {}))) if rule else []
        if without and not meters:                        # no meter has a baseline: nothing can be measured, so nothing is settled. The contract is HELD, with why, and the event log says so: never a zero
            if not ct.get("held"):
                ct["held"] = {"why": f"no baseline could be built ({rule['rule']}), so the payment is held as not yet settled", "meters": without, "at": self.now()}
                self.event("settlement_held", event_id=need["event_id"], meters=len(without), why=ct["held"]["why"])
            ct["status"] = "HELD"
            return f"held: {ct['held']['why']}"
        # a building node's meter counts at most 1.2x its commitment in each half hour (its reading's word, inside what the
        # community agent says it owed): its baseline can rest on days without its own routine evening cut (rules.building_counted_kwh)
        caps = {m: {int(k): st.BUILDING_CAP_X * mc.committed(ct, m, k) for k in ct.get("meter_committed", {}).get(m, {})}
                for m in meters if (self.fleet.get(m) or {}).get("kind") == "building"}
        ct["capped"] = self._called_slots(ct)
        result = st.deg_settle(need["slots"], ct.get("offered", {}), meters, hours=beckn.SLOT_MINUTES / 60,
                               currency=need["currency"], caps=caps or None, share=ct.get("share"), capped=ct["capped"])
        if ct["capped"]:
            result["capped_kw"] = {str(k): v for k, v in ct["capped"].items()}
        if rule:                                          # a flagged baseline (see baselines): the settlement names its rule and how many days it rests on
            result["baseline"] = {"rule": rule["rule"], "days": rule["days"], **({"held_meters": without, "held": "no baseline could be built for these meters: not yet settled"} if without else {})}
        if ct.get("deposit_held_usd"):
            result["deposit"] = st.deposit_statement(result["total"], ct["deposit_held_usd"])
        if caps:
            result["caps_kw"] = {m: {str(k): round(v, 6) for k, v in c.items()} for m, c in caps.items()}   # the split reads these
            result["cap_rule"] = f"a building's meter counts at most {st.BUILDING_CAP_X:g} x its commitment per half hour"
        refused = {h: {str(k): v for k, v in d.items()} for h, d in (ct.get("rejected_slots") or {}).items() if d}
        checks = {**notes, **({"refused": refused} if refused else {}), **({"pre_refused": ct["pre_refused"]} if ct.get("pre_refused") else {})}
        if checks:                                        # never silent: on the settlement, on the record and in the log
            result["meter_checks"] = checks
            self.event("readings_checked", event_id=need["event_id"], **{k: (len(v) if hasattr(v, "__len__") else v) for k, v in checks.items()})
        ct["settlement"] = result
        ct["status"] = "COMPLETE"
        ct["late_readings"] = 0
        ct["top_ups"] = ct.get("top_ups", 0) + (1 if top_up else 0)
        bad = ct.get("rejected_readings", 0)
        actuals = {h: {str(k): v for k, v in d.items()} for h, d in meters.items()}
        self.reply(sender, "on_status", txn, {"contract": {"id": ct["contract"]["id"]},
                                              "performance": {"kind": "actuals", "meters": actuals}}, "actuals", ct["top_ups"])
        # the actuals travel inside the settlement too, so the split never depends on which message arrives first
        ct["settled_msg"] = {"contract": {"id": ct["contract"]["id"], "status": "COMPLETE"},
                             "settlement": {**result, "currency": need["currency"], "rejected_readings": bad, "actuals": actuals, "lacking": self._lacking(ct),
                                            **({"top_up": ct["top_ups"], "prior_total": prior} if top_up else {})}}
        self.reply(sender, "on_status", txn, ct["settled_msg"], "settled", ct["top_ups"])
        self.event("settle_top_up" if top_up else "settled", event_id=need["event_id"], seller_usd=result["total"], prior_usd=prior, meters=len(meters), bad=bad)
        self.watch.settle_again_for(ct)                   # a call settled first was measured against fewer of these readings
        return f"settled {result['total']} {need['currency']}"

    def _called_slots(self, ct: dict[str, Any]) -> dict[int, float]:
        """Half hours a call covers, with the capacity sold in them: the booking stops there and the call pays the rest, so nothing is
        paid twice. A call from this buyer is known here. Another buyer's comes from the community agent (update, telemetry_done)."""
        sold = ct.get("pool_offered") or ct.get("offered") or {}
        out = {int(k): float(sold.get(int(k), 0.0)) for k in ct.get("called_slots") or []}
        for s in ct["need"]["slots"]:
            end = beckn.add_minutes(s["start"], beckn.SLOT_MINUTES)
            if any(c["start"] < end and s["start"] < c["end"] and c.get("status") != "REFUSED" and c.get("confirmed_kw") is not None for c in self.watch.calls.values()):   # a call the desk never heard of cuts nothing
                out[int(s["id"])] = float(sold.get(int(s["id"]), 0.0))
        return out

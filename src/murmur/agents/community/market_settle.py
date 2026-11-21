"""Settlement: each buyer's payment checked against the market's own sums from the meters, split among the members by measured delivery, and paid once."""
from __future__ import annotations

from typing import Any, Callable
from murmur.protocol import envelope as beckn
from murmur.settlement import meter_check as mc
from murmur.settlement import rules as st
from murmur.agents.community.market_rules import CENT, SLOT_H
from murmur.settlement import market_checks


class MarketSettle:
    """Settlement: each buyer's payment checked against the market's own sums from the meters, split among the members by measured delivery, and paid once."""

    # ------------------------------------------------------------------ settlement
    def top_up_settlement(self, ev: dict[str, Any], od: dict[str, Any], first: bool, s: dict[str, Any]) -> str:
        """A buyer settled again on readings that came in after its settlement. Either buyer can come first or alone: the split reads every buyer's meters,
        so each top-up shares out what it adds. A split still on its way (CommunityAgent.c4) reads this one itself."""
        od["settlement"], od["lacking"] = s, s.get("lacking") or {}
        if first:
            if isinstance(s.get("actuals"), dict):
                ev["actuals"] = s["actuals"]
            ev["settlement"] = s
        if ev.get("result"):
            self.settle(ev["need"]["event_id"], again=True)
        return "top-up received"

    def settle(self, event_id: str, again: bool = False) -> dict[str, Any]:
        """Split the buyers' payment and update reputations, once per event: a repeated settlement message or a re-run
        of CommunityAgent.c4 returns the stored result and pays nobody again. `again`: the buyers settled again on late
        readings, so each node gets what its new share adds to what it was paid, and nothing is taken back.
        A split that can't finish changes nothing and pays nobody. It's on the sale as split_failed, with a v2_split_failed log, and it isn't taken for one that worked:
        a restart makes it again."""
        ev = self.events[event_id]
        if ev.get("result") and not again:
            return ev["result"]
        kept = ("paid_usd", "rep_after", "result")
        was, rep, phase = {k: ev[k] for k in kept if k in ev}, dict(self.reputation), ev["phase"]
        was.update({k: dict(was[k]) for k in ("paid_usd", "rep_after") if k in was})
        try:
            items, paid = self._split(ev, event_id, again)
        except Exception as exc:                            # noqa: BLE001  whatever it was, a sale is paid whole or not yet, and somebody hears
            why = f"{type(exc).__name__}: {exc}"[:160]
            for k in kept:
                ev.pop(k, None)
            ev.update(was)
            self.reputation.clear()
            self.reputation.update(rep)
            ev["split_failed"], ev["phase"] = why, phase if again else "settling"
            self.log("v2_split_failed", event_id=event_id, why=why, top_up=again)
            return {"failed": why, "event_id": event_id}
        ev.pop("split_failed", None)
        self._broadcast(items)                              # last: everything above is worked out first, so a sale is paid whole or not yet
        return paid()

    def _split(self, ev: dict[str, Any], event_id: str, again: bool) -> tuple[list[tuple], Callable[[], dict[str, Any]]]:
        """The sale worked out and marked as paid: the notices to send, and what to say once they're on their way."""
        s = ev["settlement"]
        meters = ev.get("actuals")
        if meters is None:
            meters = s.get("actuals")
        if meters is None:                                  # a buyer whose settlement doesn't carry its actuals: wait for its separate actuals message
            ev["phase"] = "settling"
            ev["settle_waiting"] = True
            self.log("v2_settle_waiting", event_id=event_id, reason="no actuals yet")
            return [], lambda: {"waiting_for": "actuals", "event_id": event_id}
        meters = market_checks.clean_actuals(meters, self.log, event_id)   # a row the split can't read costs that node, and nobody else
        for od in self._orders(ev):                         # a reading that reached one buyer: the node delivered, whichever copy shows it, and a split on one copy gives
            for h, m in market_checks.clean_actuals((od.get("settlement") or {}).get("actuals"), self.log, event_id).items():      # the other buyer's money for its kWh to everyone else (no top-up takes that back)
                for k, v in m.items():
                    market_checks.keep_lower(meters, h, k, v)
        paid = lambda x: next(f["value"] for f in x["revenue_flows"] if f["role"] == "seller")  # noqa: E731
        # on the pool the full price is worked out here, from the meters and the price: a node's rate reads it, so it can't be a buyer's word
        fulls = {od["buyer"]: self._checked_full(ev, od, meters, paid(od["settlement"])) for od in self._orders(ev)} if self.pooled else {}
        seller = sum(paid(od["settlement"]) for od in self._orders(ev)) if self.pooled else paid(s)
        at_full = sum(fulls.values()) if self.pooled else s.get("full_price_usd", paid(s))     # what the kWh come to at the order's price. A settlement that doesn't say was billed at it
        committed_kwh = lambda h: (sum(x["kw"] for x in ev["commitments"][h]["contract"]["commitments"]) * SLOT_H  # noqa: E731
                                   if h in ev["commitments"] else 0.0)
        per_slot = lambda h: {str(x["id"]): x["kw"] for x in ((ev["commitments"].get(h) or {}).get("contract") or {})  # noqa: E731
                              .get("commitments", [])}
        # a building node (its enrolment says so: meter_check.own_kind): counted per half hour at most 1.2x its commitment, as the buyer
        # counts it (rules.building_counted_kwh); the homes as measured
        caps = {h: st.building_counted_kwh(meters[h], per_slot(h), SLOT_H) for h in meters
                if (ev["offers"].get(h) or {}).get("node") == "building"}
        # each node's share follows what its delivery is worth. The buyer's caps come first: its readings carry a gap a building took on, which this contract copy doesn't
        kwcap = {h: {str(k): float(v) for k, v in ((s.get("caps_kw") or {}).get(h) or
                                                   {k: st.BUILDING_CAP_X * float(v) for k, v in per_slot(h).items()}).items()}
                 for h in caps}
        val = {h: st.meter_kwh(m, SLOT_H, kwcap.get(h), h in kwcap, h) for h, m in meters.items()}
        st.trim_called(val, self._capped(ev) if self.pooled else s.get("capped_kw") or {}, SLOT_H)
        delivered = {h: sum(v[0].values()) for h, v in val.items()}
        sp = st.share_out(seller, at_full, val)
        if caps:
            sp["caps_kwh"] = {h: round(v, 3) for h, v in caps.items()}
        self.rt.premiums(ev, sp, delivered, committed_kwh)
        by_buyer = {od["buyer"]: {                          # all that reads a buyer's word comes first: below this line the sale changes, and nothing may stop it half way
            "order": od["need"]["event_id"], "paid_usd": paid(od["settlement"]), "full_price_usd": fulls[od["buyer"]], **({"differs": od["differs"]} if od.get("differs") else {}),
            "sold_kwh": round(sum(self._tranche(ev, od, ev.get("capacity_offered_final") or {}).values()) * SLOT_H, 3),
            "delivered_kwh": round(sum(float(r.get("delivered", 0.0)) for r in od["settlement"].get("components") or []) * SLOT_H, 3),
            "deposit": od["settlement"].get("deposit")} for od in self._orders(ev)} if self.pooled else None
        checks = {od["buyer"]: od["settlement"]["meter_checks"] for od in self._orders(ev) if (od.get("settlement") or {}).get("meter_checks")}
        split = market_checks.buyers_disagree(self._orders(ev))
        items = []
        rep0, rep1 = ev.setdefault("rep_before", dict(self.reputation)), ev.setdefault("rep_after", {})   # a second split starts from the same place as the first

        def rated(h: str, value: float) -> None:
            """This sale's mark. Made again, it moves the reputation by the difference, so a sale settled since keeps its own."""
            self.reputation[h] = round(self.reputation.get(h, 1.0) + value - rep1[h], 3) if h in rep1 else value
            rep1[h] = value
        paid0, round_no = ev.setdefault("paid_usd", {}), ev.get("top_ups", 0) + 1
        added = 0.0
        for h, usd in sp["per_home"].items():
            committed = committed_kwh(h)
            ratio = delivered[h] / committed if committed > 0 else 0.0
            rated(h, round(0.7 * rep0.get(h, 1.0) + 0.3 * min(1.2, ratio), 3))
            pay = round(usd - paid0.get(h, 0.0), 4) if again else usd
            if again and pay < 0.005:
                continue
            added += pay
            paid0[h] = round(paid0.get(h, 0.0) + pay, 4)
            msg = {"settlement": {"event_id": event_id, "payment": pay, "currency": s.get("currency", "USD"),
                                  "delivered_kwh": round(delivered[h], 3), "committed_kwh": round(committed, 3),
                                  "reputation": self.reputation[h], "rule": sp["rule"], **({"top_up": round_no} if again else {})}}
            items.append((h, "on_status", self._msg("on_status", h, ev["ctxn"], msg, ttl_s=beckn.TTL_EVIDENCE_S),
                          self.mid(h, "on_status", event_id, "pay", round_no if again else 0)))
        # participating homes the buyers have no readings from delivered nothing they can see: reputation x 0.7
        participants = ev.get("final_meters") or [h for h, c in ev["commitments"].items() if c["status"] == "ACCEPTED"]
        counted_none = sorted(h for h in participants if h not in delivered)
        silent = [h for h in counted_none if not ev["readings"].get(h)]
        left = self.rt.abnormal_slots(ev)
        for h in counted_none:
            rated(h, round(0.7 * rep0.get(h, 1.0), 3))
            if again:
                continue
            note = "no meter readings" if h in silent else "its readings came in and don't count: it left the sale" if h in left else "its readings came in and none counted"     # a closed building that sent every reading is told so, not that it sent none
            msg = {"settlement": {"event_id": event_id, "payment": 0.0, "currency": s.get("currency", "USD"),
                                  "delivered_kwh": 0.0, "committed_kwh": round(committed_kwh(h), 3),
                                  "reputation": self.reputation[h], "rule": sp["rule"], "note": note}}
            items.append((h, "on_status", self._msg("on_status", h, ev["ctxn"], msg, ttl_s=beckn.TTL_EVIDENCE_S),
                          self.mid(h, "on_status", event_id, "pay", 0)))
        truth = sum(mc.true_kw(r) * SLOT_H for rs in ev["readings"].values() for r in rs.values())      # for the record: no money reads it
        ev["result"] = {"seller_usd": seller, "full_price_usd": at_full, "paid_homes": len(sp["per_home"]), "split": sp,
                        "delivered_kwh_measured": round(sum(delivered.values()), 3),
                        "delivered_kwh_true": round(truth, 3), "silent_homes": silent, "not_counted_homes": [h for h in counted_none if h not in silent],
                        "components": s.get("components"), "net_zero_ok": s.get("net_zero_ok")}
        if self.community is not None:                  # the community's record of the sale: what it delivered of what it offered sets its next cover (community.py)
            gaps = {h: {"contract_kwh": committed_kwh(h), "delivered_kwh": v, "gap_kwh": v - committed_kwh(h)} for h, v in delivered.items()}      # each member's own gap, for the record only
            self.community.sale_delivered(event_id, sum(delivered.values()) / max(len(ev["need"]["slots"]) * SLOT_H, 1e-9), self.now(), members=gaps)
        if self.pooled:
            ev["result"]["by_buyer"] = by_buyer
        if checks or split or ev.get("readings_refused"):  # none of this stops a payment, and none of it stays quiet
            ev["result"]["meter_checks"] = {"by_buyer": checks, "buyers_disagree": split, "refused_here": ev.get("rejected_slots") or {}}
            self.log("v2_readings_refused", event_id=event_id, refused=ev.get("readings_refused", 0), by_buyer=checks, buyers_disagree=split)
        ev["phase"] = "done"
        ev["readings_missing"] = self.missing_readings(ev)

        def paid_out() -> dict[str, Any]:
            if again:
                ev["top_ups"] = round_no
                ev["result"]["top_ups"] = round_no
                ev["result"]["top_up_usd"] = round(float(ev.get("top_up_usd", 0.0)) + added, 4)
                ev["top_up_usd"] = ev["result"]["top_up_usd"]
                self.log("v2_settled_again", event_id=event_id, round=round_no, seller_usd=seller, usd=round(added, 4), nodes=len(items))
                self._report(ev)
                return ev["result"]
            if ev["readings_missing"]:                      # a buyer settled short, with the community agent's own readings complete: the same alarm
                self.log("v2_readings_missing", event_id=event_id, nodes=len(ev["readings_missing"]), first=sorted(ev["readings_missing"])[:8], when="at the settlement")
            self._report(ev)
            self.log("v2_settled", event_id=event_id, seller_usd=seller, nodes_usd=sp["pool"], homes_paid=len(sp["per_home"]),
                     silent_homes=len(silent), measured_kwh=ev["result"]["delivered_kwh_measured"],
                     true_kwh=ev["result"]["delivered_kwh_true"])
            return ev["result"]
        return items, paid_out

    def _capped(self, ev: dict[str, Any]) -> dict[int, float]:
        """The half hours a call covers, at the capacity sold: where a booking stops (rules.trim_called). This desk knows its calls, and it's what it told the buyers."""
        sold = ev.get("capacity_offered_final") or ev.get("capacity_offered") or {}
        return {sid: float(sold.get(sid, 0.0)) for sid in self.rt.called_slots(ev)}

    def own_sums(self, ev: dict[str, Any], od: dict[str, Any], meters: dict[str, Any]) -> dict[str, Any]:
        """This order's settlement as this desk works it out: st.deg_settle, as the buyer runs it, on the buyer's own copy of the meters, at its own order's prices, its share and the desk's calls.
        Each buyer's own copy, so a reading that reached one of them counts as it did at that buyer, whichever readings reached this desk."""
        s = od["settlement"]
        rows = market_checks.clean_actuals(s["actuals"], lambda *a, **k: None, "") if s.get("actuals") is not None else meters
        said = s.get("caps_kw") or {}

        def cap(h: str) -> dict[Any, float]:               # a building counts at most 1.2 x what it owed, and the buyer's own number comes first, as in the split: it knows a gap the contract doesn't
            owed = {x["id"]: x["kw"] for x in ((ev["commitments"].get(h) or {}).get("contract") or {}).get("commitments", [])}
            return said.get(h) or {k: st.BUILDING_CAP_X * float(v) for k, v in owed.items()}
        caps = {h: cap(h) for h in rows if (ev["offers"].get(h) or {}).get("node") == "building"}
        return st.deg_settle(od["need"]["slots"], {}, rows, hours=SLOT_H, caps=caps or None, share={k: round(float(v), 6) for k, v in (od.get("share") or {}).items()}, capped=self._capped(ev))

    def _checked_full(self, ev: dict[str, Any], od: dict[str, Any], meters: dict[str, Any], bill: float) -> float:
        """What this order adds to the full price. A buyer's word stands when it's what its meters and its price come to, and that's every honest day. When it isn't, or it's left out, this desk's
        own sum stands and the order says so (its differs, with a v2_buyer_word_differs log): a buyer that doesn't know the field, or has it wrong, can't move a seller's pay. A wrong bill is
        said the same way. A split still pays out no more than the bills brought in (rules.within), and a top-up from the buyer mends it."""
        s = od["settlement"]
        word = s.get("full_price_usd")
        try:
            own = self.own_sums(ev, od, meters)
            top, at = float(own["total"]), float(own["full_price_usd"])
        except Exception as exc:                            # noqa: BLE001  whatever it is, it mustn't stop the split: its word stands, and somebody hears
            self._differs(ev, od, f"its sums can't be worked out here: {type(exc).__name__}: {exc}"[:160])
            return word if word is not None else bill
        wrong = [] if word is not None else [f"it gave no full price, and its meters come to ${at:,.2f}"]
        if word is not None and abs(word - at) > CENT:
            wrong.append(f"its full price is ${word:,.2f}, and its meters come to ${at:,.2f}")
        if abs(bill - top) > CENT:
            wrong.append(f"its bill is ${bill:,.2f}, and its meters come to ${top:,.2f}")
        self._differs(ev, od, "; ".join(wrong))
        return at if word is None or abs(word - at) > CENT else word

    def _differs(self, ev: dict[str, Any], od: dict[str, Any], why: str) -> None:
        if why and od.get("differs") != why:
            self.log("v2_buyer_word_differs", event_id=ev["need"]["event_id"], buyer=od["buyer"], why=why)
        if why:
            od["differs"] = why
        else:
            od.pop("differs", None)

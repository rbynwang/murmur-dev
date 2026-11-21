"""Steps 5 and 6 on a member's side: the safe offer from its forecasts, the commitment checked against it, and the plan installed for the window."""
from __future__ import annotations

from typing import Any
from murmur.protocol import envelope as beckn
from murmur.node import grounds
from murmur.node.home_days import BACKUP, REBOUND_FRACTIONS, SLOT


class HomeOffer:
    """Steps 5 and 6 on a member's side: the safe offer from its forecasts, the commitment checked against it, and the plan installed for the window."""

    def build_offer(self, need: dict[str, Any], fc: dict[str, Any]) -> dict[str, Any]:
        """Everything is read off the same forecast runs the community agent will rely on:
        no event (EV on, battery default)  vs  EV paused  vs  EV paused + battery discharging extra.
        EV part of the offer = what pausing the EV really saves at the meter, step by step. At a step it can pass the
        car's own draw: a car paused earlier leaves battery energy that covers the house later (that stored part is
        tentative, report_rule.PoolNode.tag_offer). Battery part = what the extra discharge saves on top."""
        if self.agent is not None:                                   # what a person wrote comes first: the offer follows what the model reads in it
            self.agent.read_note(self.now_ts())
        lim = self.adapter.limits()
        P, E, R, SM, eta = lim["battery_kw"], lim["battery_kwh"], lim["reserve_pct"] / 100, lim["soc_max_pct"] / 100, lim["eta"]
        usable = (SM - R) * E * eta                                   # kWh between reserve and full, AC side
        win, both, n_w = fc["steps"], fc["steps"] + fc["post"], len(fc["steps"])
        # battery energy when the window opens: no event = run the battery's default job forward from now;
        # with the event = that plus the 2 h pre-charge, at most full
        soc = fc.get("soc_now_pct")
        e_now = usable if soc is None else max(0.0, min(usable, (soc / 100 - R) * E * eta))
        _, e_cf = self._battery_run(fc.get("lead", []), e_now, usable, P, eta, ev_on=True)
        e_ev = min(usable, e_cf + P * 2.0 * eta * eta)
        # most the battery can add on top of its default job, per window step (power and export limits)
        incr, need_def = [], 0.0
        for st in win:
            b0 = 0.0 if BACKUP else min(P, max(0.0, st["load_p50"] - st["pv_p50"]))
            incr.append(max(0.0, min(P, lim["export_limit_kw"] - st["pv_p50"] + st["load_p50"]) - b0))
            need_def += b0 * 0.25
        need_inc = sum(incr) * 0.25
        scale = 1.0 if need_inc <= 1e-9 else max(0.0, min(1.0, (e_ev - need_def) / need_inc))
        x = [scale * v for v in incr]
        cf, _ = self._battery_run(both, e_cf, usable, P, eta, ev_on=True)
        noev, _ = self._battery_run(both, e_ev, usable, P, eta, ev_on=False)
        per_slot: dict[int, dict[str, float]] = {}
        runs = {}
        for f in REBOUND_FRACTIONS:                              # the rebound is not linear in the delivery
            runs[f], _ = self._battery_run(both, e_ev, usable, P, eta, ev_on=False, extra=[f * v for v in x])
        full = runs[1.0]
        for k, st in enumerate(win):
            d = per_slot.setdefault(st["slot_id"], {"ev": 0.0, "batt": 0.0, "n": 0})
            d["ev"] += max(0.0, cf[k] - noev[k]); d["batt"] += max(0.0, noev[k] - full[k]); d["n"] += 1
        slots = []
        for sid, d in sorted(per_slot.items()):
            ev_kw, batt = d["ev"] / d["n"], d["batt"] / d["n"]
            slots.append({"id": sid, "kw_offered": round(batt + ev_kw, 2), "battery_kw": round(batt, 2),
                          "ev_pause_kw": round(ev_kw, 2)})
        ac = None
        ctl = getattr(self.adapter, "ctl", None)
        if ctl is not None and getattr(self.adapter, "house", None) is not None:   # the real-time design: + the AC
            try:
                saved, self._fc_now = self._fc_now, self.now_idx()
                ac = ctl.ac_offer(need["window_start"], need["window_end"])
            except Exception as exc:
                self.log("v2_ac_offer_error", error=str(exc)[:200])
            finally:
                self._fc_now = saved
            if ac and ac.get("kw", 0.0) > 0.01:
                slots = [{**x, "ac_kw": ac["kw"], "kw_offered": round(x["kw_offered"] + ac["kw"], 2)} for x in slots]
        app = None
        if ctl is not None and getattr(self.adapter, "app", None):   # benchmark: the node's other smart systems
            app = ctl.app_offer(need["window_start"], need["window_end"])
            if app and app.get("kw", 0.0) > 0.01:
                slots = [{**x, "app_kw": app["kw"], "kw_offered": round(x["kw_offered"] + app["kw"], 2)} for x in slots]
        light = None
        if ctl is not None and hasattr(ctl, "light_offer"):        # a building: its lighting too (simulator_building.py)
            try:
                light = ctl.light_offer(need["window_start"], need["window_end"])
            except Exception as exc:
                self.log("v2_light_offer_error", error=str(exc)[:200])
            if light and light.get("kw", 0.0) > 0.01:
                slots = [{**x, "light_kw": light["kw"], "kw_offered": round(x["kw_offered"] + light["kw"], 2)} for x in slots]
        h = self.health()
        base_conf = 0.9 if lim.get("control", "auto") == "auto" else 0.6
        conf = round(base_conf * h.get("confidence_factor", 1.0) * self.reputation, 3)
        if h.get("status") in ("frozen", "jump"):
            slots = [{**s, "kw_offered": 0.0, "battery_kw": 0.0, "ev_pause_kw": 0.0} for s in slots]
        rebound = {str(f): [round(r - z, 2) for r, z in zip(runs[f][n_w:], noev[n_w:])] for f in REBOUND_FRACTIONS}
        ev = fc.get("ev")
        ev_kwh = sum(st["ev_kw"] for st in both) * 0.25 if ev else 0.0
        evening = {"start": need["window_end"], "step_min": 15,
                   "import_cf_kw": [round(v, 2) for v in cf[n_w:]],
                   "import_noev_kw": [round(v, 2) for v in noev[n_w:]],
                   "rebound_kw": rebound}
        ev_flex = None
        if ev and ev.get("in_sale") is False:                        # a car the sale won't touch charges as it always does: the evening holds it as it is
            evening["import_noev_kw"] = [round(v + st["ev_kw"], 2) for v, st in zip(evening["import_noev_kw"], fc["post"])]
        elif ev and ev_kwh > 0.05:                                   # charging expected in the window or evening
            ev_flex = {"kwh": round(ev_kwh, 2), "max_kw": round(ev["max_kw"], 2), "latest_finish": ev["deadline"],
                       "arrival": ev["arrival"]}
        if app and app.get("kw", 0.0) > 0.01:                        # their catch-up goes in the evening it declares
            left = sum(v for k, v in (app.get("by_device") or {}).items()
                       if self.adapter.app[k]["kind"] == "shift") * n_w * 0.25
            k = int(ctl.app_delay_min() // 15)
            row = evening["import_noev_kw"]
            while left > 1e-6 and k < len(row):
                kw = min(3.0, left / 0.25)
                row[k] = round(row[k] + kw, 2)
                left -= kw * 0.25
                k += 1
        if self.is_building:
            # the community's evening check is about the homes' batteries and cars refilling at once; a building's
            # lights leave nothing to catch up and its cooling cools back at most RECOVER_C_PER_H, so its evening
            # (a 1 MW building on a 300 kW community) is not added to it
            evening, ev_flex = None, None
        offer = {"event_id": need["event_id"], "home": self.name, "slots": slots,
                 "energy_kwh": round(sum(s["kw_offered"] for s in slots) * SLOT / 60, 2),
                 "confidence": conf, "health": h.get("status"), "price_floor": 0.0,
                 "battery": {"kw": P, "kwh": E, "usable_kwh": round(usable, 2), "energy_scale": round(scale, 3),
                             "window_start_kwh": {"no_event": round(e_cf, 2), "event": round(e_ev, 2)}},
                 "evening": evening, "ev_flex": ev_flex, "forecast_method": fc.get("method"),
                 **({"air_conditioning": ac} if ac else {}), **({"lighting": light} if light else {}),
                 **({"appliances": app} if app and app.get("kw", 0.0) > 0.01 else {}),
                 **({"node": "building"} if self.is_building else {}),
                 "valid_until": need["commit_by"], "made_at": self.now_ts()}
        w = self._weather()
        if w:                                # the what-if weather this home lives in (the demo runner's scenario),
            offer["weather"] = w             # declared so that the independent check's replay runs under it too
        if P <= 0 and E > 0:                 # a battery out of service (its inverter tripped): declared the same way
            offer["battery"]["out_of_service"] = True
        if self.agent is not None:                                   # what a person's note keeps out leaves the offer here
            kept = grounds.keep_out(offer, self.agent.guard.wishes, need)
            if kept is not offer:
                self.before_note[need["event_id"]] = offer           # the offer without the note: what a rule would make, since it can't read one (HomeRule.offer_receipt)
            offer = kept
            self.agent.market("5 offer", self.now_ts(), need=need, offer=offer)
        if self.brain is not None:                                   # code's rule under the person's limits decides how much of it
            try:                                                     # to offer (offer_rule.py); should it raise, the plan's offer
                offer = self.brain.decide_offer(need, fc, offer)     # goes out
            except Exception as exc:
                self.log("agent_error", where="offer", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        self.offers[need["event_id"]] = offer
        return offer

    def answer_more(self, txn: str, need: dict[str, Any], more: dict[str, Any], asked: str | None = None) -> str:
        """The second round of a sale: this node held part of its safe offer back and the pool is short (more: what the pool still lacks).
        Code's rule (offer_rule.py) made the offer under the person's limits and has nothing new to propose, so the same offer goes again.
        The answer goes either way, so the clearing doesn't wait for it."""
        eid = need["event_id"]
        offer = self.offers.get(eid)
        if offer is None:
            return beckn.Refused(f"no offer for {eid}")
        return self.send_offer(txn, offer, asked)["summary"]

    def send_offer(self, txn: str, offer: dict[str, Any], asked: str | None = None) -> dict[str, Any]:
        body = self.say("on_discover", self.community, txn, {"offer": offer})
        out = self.send(self.community, beckn.kind("on_discover"), body, self.mid(self.community, "on_discover", offer["event_id"], asked=asked))
        self.log("v2_offer_sent", event_id=offer["event_id"], kw=[s["kw_offered"] for s in offer["slots"]],
                 confidence=offer["confidence"])
        return {"sent": out, "summary": f"Offer for {offer['event_id']}: {[s['kw_offered'] for s in offer['slots']]} kW "
                                        f"per slot, {offer['energy_kwh']} kWh, confidence {offer['confidence']}."}

    # ------------------------------------------------------------------ H4 Accept
    def verify_contract(self, sender: str, body: dict[str, Any]) -> dict[str, Any]:
        c = (body.get("message") or {}).get("contract") or {}
        def no(reason):
            return {"decision": "DECLINED", "reason": reason, "contract_id": c.get("id")}
        if body.get("signer") not in self.trusted() or not beckn.check(body, body.get("signer", "")):
            return no("bad_signature")
        if c.get("home") != self.name or body["context"].get("bppId") != self.name:
            return no("wrong_recipient")
        offer = self.offers.get(c.get("event_id"))
        if not offer:
            return no("no_offer_for_event")
        if self.now_ts() >= c.get("opt_out_by", "9999"):
            return no("past_opt_out_deadline")
        mine = {s["id"]: s["kw_offered"] for s in offer["slots"]}
        for s in c.get("commitments", []):
            if s["kw"] > mine.get(s["id"], 0.0) + 0.01:
                return no(f"slot_{s['id']}_above_offer")
        h = self.health().get("status")
        if h in ("frozen", "jump"):
            return no("telemetry_unverified")
        if c.get("event_id") in (self.cfg.get("opt_out_events") or []) or \
                c.get("window_start", "")[:10] in (self.cfg.get("opt_out_days") or []):
            return no("homeowner_opted_out")
        if self.cfg.get("control", "auto") == "advisory":
            return no("homeowner_approval_needed")
        verdict = {"decision": "ACCEPTED", "reason": "within_offer", "contract_id": c.get("id")}
        if self.agent is not None:
            self.agent.market("6 commitment", self.now_ts())
        if self.brain is not None:                    # the guard said yes: code's rule may still say no (never yes to a no)
            prev = self.contracts.get(c.get("id"))
            if not (prev and prev.get("status") in ("ACCEPTED", "DECLINED")):
                try:
                    out = self.brain.decide_accept(c, verdict)
                    if out.get("decision") in ("ACCEPTED", "DECLINED"):
                        verdict = out if out["decision"] == "DECLINED" else verdict
                except Exception as exc:
                    self.log("agent_error", where="accept", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return verdict

    def install_plan(self, c: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
        prev = self.contracts.get(c.get("id"))
        if prev and prev.get("status") in ("ACCEPTED", "DECLINED"):      # answered before: nothing changes
            return {"installed": prev["status"] == "ACCEPTED", "repeat": True}
        if verdict["decision"] != "ACCEPTED":
            return {"installed": False}
        cid = c["id"]
        actions: dict[str, dict[str, Any]] = {}
        for s in c["commitments"]:
            for k in (0, 1):
                actions[beckn.add_minutes(s["start"], 15 * k)] = {"deliver_kw": float(s["kw"]), "contract_id": cid}
        w0 = c["window_start"]
        by_idx = self.replay.idx_of(w0)
        for k in range(8, 0, -1):                                    # pre-charge over the 2 h before the window
            actions.setdefault(beckn.add_minutes(w0, -15 * k),
                               {"precharge_to": self.adapter.SM, "by_idx": by_idx, "contract_id": cid})
        hold = (w0, c["ev_resume_after"]) if (self.adapter.has_ev and c.get("ev_resume_after")) else None
        self.adapter.set_plan(actions, hold)
        self.contracts[cid] = {**c, "status": "ACCEPTED", "reported": [], "accepted_at": self.now_ts()}
        return {"installed": True, "steps": len(actions), "ev_hold": hold}

    def answer(self, txn: str, c: dict[str, Any], verdict: dict[str, Any], asked: str | None = None) -> dict[str, Any]:
        prev = self.contracts.get(c.get("id")) if c.get("id") else None
        if prev and prev.get("status") in ("ACCEPTED", "DECLINED"):
            # an answer is final: a contract this home accepted (its plan is installed) is never turned into DECLINED,
            # and a repeat of the same commitment gets the same answer again
            verdict = {"decision": prev["status"], "reason": prev.get("reason", "within_offer"), "contract_id": c.get("id")}
        elif verdict["decision"] != "ACCEPTED" and c.get("id"):
            self.contracts[c["id"]] = {**c, "status": "DECLINED", "reason": verdict["reason"], "reported": []}
        body = self.say("on_confirm", self.community, txn, {"contract": {"id": c.get("id"), "event_id": c.get("event_id"), "home": self.name,
                                                                          "status": verdict["decision"], "reason": verdict["reason"]}})
        out = self.send(self.community, beckn.kind("on_confirm"), body, self.mid(self.community, "on_confirm", c.get("id"), asked=asked))
        self.log("v2_contract_" + verdict["decision"].lower(), contract_id=c.get("id"), reason=verdict["reason"])
        return {"sent": out, "summary": f"Contract {c.get('id')}: {verdict['decision']} ({verdict['reason']})."}

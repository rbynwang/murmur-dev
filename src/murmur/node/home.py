"""A member node's part of the protocol: offer, accept or decline, deliver, report. Homes and buildings run the same code.

The class is assembled from mixins: home_forecast (its forecasts), home_offer (steps 5 and 6), home_delivery (readings and the desk).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from murmur.protocol import envelope as beckn
from murmur.protocol import ids
from murmur.protocol import signing
from murmur.node import telemetry as tcheck
from murmur.node.forecast import HomeForecaster
from murmur.node import amount


from murmur.node.home_forecast import HomeForecasting
from murmur.node.home_offer import HomeOffer
from murmur.node.home_delivery import HomeDelivery


class MemberNode(HomeForecasting, HomeOffer, HomeDelivery):
    def __init__(self, name: str, cfg: dict[str, Any], adapter, replay, key, send: Callable,
                 trusted: Callable[[], list[str]], log: Callable[..., None], community: str = "community"):
        self.name, self.cfg, self.adapter, self.replay, self.key = name, cfg, adapter, replay, key
        self.pub = signing.public_hex(key)
        self.send, self.trusted, self.log, self.community = send, trusted, log, community
        self.is_building = getattr(adapter, "name", None) == "building"
        if self.is_building:                  # the homes' trained models are for homes: a building forecasts its load
            self.cfg = {**cfg, "forecast": "temp_regression", "building_forecast": cfg.get("forecast")}   # on its own record (hour-of-day line, weather), or with same_kind_day from its last day of that kind
        self.offers: dict[str, dict[str, Any]] = {}          # event_id -> offer we made
        self.before_note: dict[str, dict[str, Any]] = {}     # event_id -> the safe offer before a person's note kept part of it out
        self.contracts: dict[str, dict[str, Any]] = {}       # contract_id -> contract + our status
        self.payments: list[dict[str, Any]] = []             # one per event_id (a repeated payment notice is ignored)
        self.reputation = float(cfg.get("reputation", 1.0))
        self.play = ids.new_play()                           # this play of the day, in every id it sends (ids.py): new at each reset, kept through a restart
        self.history: deque = deque(maxlen=8)
        self._fits: dict[tuple, tuple[float, float] | None] = {}
        self._fc_now: int | None = None
        self._forecaster: HomeForecaster | None = None       # forecast = "trained" (node/forecast.py)
        self._tf: dict[str, Any] | None = None               # the trained forecast being used, by step
        self._lock = threading.Lock()                        # readings marked by send callbacks (the node host's send threads)
        self.brain = None                    # steps 5 and 6: code's rule under the person's limits (node/offer_rule.py), set by the host
        self.agent = None                    # a thinking node's workflow, for its record of steps 1 to 6
        self._rt_fc: dict[str, Any] = {"hour": None, "vals": {}}
        if getattr(adapter, "ctl", None) is not None:            # the real-time design: its forecasts come from here
            adapter.ctl.forecast_fn = self.rt_forecast


    def reset(self) -> None:
        """Forget offers, contracts and plans (demo: replay the same day again)."""
        self.offers.clear(); self.contracts.clear(); self.payments.clear(); self.before_note.clear()
        self.play = ids.new_play()
        self.reputation = float(self.cfg.get("reputation", 1.0))   # a run's marks are that run's: messages one run lost must not shrink the next run's sale
        if hasattr(self.adapter, "recent"):
            self.adapter.recent.clear()                     # last run's meter rows: a run must read only its own
        if self.brain is not None:
            self.brain.reset()
        if hasattr(self.adapter, "plan"):
            self.adapter.plan.clear()
            self.adapter.ev_holds.clear()
        if hasattr(self.adapter, "rt_reset"):
            self.adapter.rt_reset()
        self.history.clear()                                # the sensors' check compares readings: last run's mustn't read as a jump in this one
        self._rt_reported, self._rt_at, self._rt_why = {}, None, None
        self._rt_fc, self._fc_now = {"hour": None, "vals": {}}, None

    # ------------------------------------------------------------------ helpers
    def now_idx(self) -> int:
        return self.replay.current()

    def now_ts(self) -> str:
        return self.replay.ts(self.now_idx())

    def observe(self) -> dict[str, Any]:
        tel = self.adapter.telemetry()
        if not self.history or self.history[-1].get("idx") != tel.get("idx"):
            self.history.append(tel)
        return tel

    def health(self) -> dict[str, Any]:
        return tcheck.check(list(self.history), self.adapter.limits())


    def mid(self, to: str, kind: str, *key: Any, asked: str | None = None) -> str:
        """The id of one of this node's messages. `asked`: what it answers (ids.asked), which takes the place of the play tag. A message of its own goes under its play."""
        return ids.sealed(None if asked else self.key, asked or self.play, self.name, to, kind, *key)


    def say(self, action: str, to: str, txn: str, message: dict[str, Any], **kw: Any) -> dict[str, Any]:
        """Every message this node makes for the market, signed. What it may carry is decided in one place (node/amount.py): the amount and what the
        market needs to run, and nothing else leaves the node."""
        return beckn.make(action, sender=self.name, receiver=to, transaction_id=txn, message=amount.only(action, message, self.log), key=self.key, sender_role="bpp", **kw)


    # ------------------------------------------------------------------ the agent's tools, logged with input and output
    def _tool(self, name: str, inp: str, out: str, t0: float) -> None:
        self.log("tool", tool=name, input=inp, output=out, ms=round((time.perf_counter() - t0) * 1000, 1))


    # ------------------------------------------------------------------ in-process path (and the node host)
    def gate(self, kind: str, sender: str, body: dict[str, Any]) -> str | None:
        """None if the message comes from the community agent this member trusts (the bus's sender, a trusted key, a valid signature
        over the whole body); else why not. Every message is checked here first."""
        if sender != self.community or body.get("signer") not in self.trusted() or \
                not beckn.check(body, body.get("signer", "")):
            self.log("v2_rejected_message", message_kind=kind, sender=sender)
            return beckn.Refused("rejected: not from a trusted coordinator")
        return None

    def repeat_answer(self, body: dict[str, Any]) -> str | None:
        """A commitment this home has answered already (Town redelivery, or the community agent sending it again because
        the answer was lost): the same answer again, without checking or installing anything. None if it is new."""
        txn = body.get("context", {}).get("transactionId", "")
        c = {**((body.get("message") or {}).get("contract") or {}), "transaction_id": txn}
        prev = self.contracts.get(c.get("id"))
        if prev and prev.get("status") in ("ACCEPTED", "DECLINED"):
            v = {"decision": prev["status"], "reason": prev.get("reason", "within_offer"), "contract_id": c.get("id")}
            return self.answer(txn, c, v, ids.asked(body))["summary"]
        return None

    def handle(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        act = beckn.action_of(kind)
        txn = body.get("context", {}).get("transactionId", "")
        asked = ids.asked(body)
        late = beckn.expired(body, default_ttl=float(self.cfg.get("max_message_age_s", 900)))
        if late:                                            # e.g. a call for offers that waited while this home was
            return beckn.Refused(f"expired {round(late)} s ago: not acted on")   # off: the community agent has moved on
        rejected = self.gate(kind, sender, body)
        if rejected:
            return rejected
        if act == "discover" and "more" in body["message"]["intent"]:
            return self.answer_more(txn, body["message"]["intent"]["need"], body["message"]["intent"]["more"], asked)
        if act == "discover":
            need = body["message"]["intent"]["need"]
            if need.get("event_id") in self.offers:         # asked again: its offer didn't arrive. The same offer goes, and its agent isn't asked twice
                return self.send_offer(txn, self.offers[need["event_id"]], asked)["summary"]
            sl = need.get("slots") or []
            self.log("recv", what="call for offers", sender=sender, event=need.get("event_id"),
                     window=f"{need['window_start'][5:]}-{need['window_end'][11:]}", half_hours=len(sl),
                     kw_wanted=sl[0].get("kw_requested") if sl else None, price=sl[0].get("price") if sl else None)
            t0 = time.perf_counter()
            if self.agent is not None:
                self.agent.market("1 read schedule", self.now_ts(), need=need)
            fc = self.forecast_window(need)
            if self.agent is not None:
                self.agent.market("2 forecast", self.now_ts(), need=need, fc=fc)
            self._tool("forecast_window", f"event {need['window_start'][5:]}-{need['window_end'][11:]} ({len(sl)} half hours), "
                       f"as of {self.now_ts()[5:]}", self._fc_words(fc), t0)
            t0 = time.perf_counter()
            offer = self.build_offer(need, fc)
            lim = self.adapter.limits()
            soc = fc.get("soc_now_pct")
            self._tool("plan_offer", f"battery {lim['battery_kwh']:g} kWh" + (f" at {soc:.0f} %" if soc is not None else "")
                       + f", reserve {lim['reserve_pct']:.0f} %" + (f"; EV charger {lim['ev_max_kw']:g} kW" if lim.get("ev_max_kw") else ""),
                       " · ".join(f"{x['kw_offered']:g}" for x in offer["slots"]) + f" kW per half hour = {offer['energy_kwh']} kWh, "
                       f"confidence {offer['confidence']}", t0)
            return self.send_offer(txn, offer, asked)["summary"]
        if act == "confirm":
            again = self.repeat_answer(body)
            if again is not None:
                return again
            c = {**body["message"]["contract"], "transaction_id": txn}
            t0 = time.perf_counter()
            v = self.verify_contract(sender, body)
            self._tool("check_commitment", "share " + " · ".join(f"{x['kw']:g}" for x in c.get("commitments", [])) + " kW, "
                       f"opt out by {str(c.get('opt_out_by', ''))[5:]}", f"{v['decision']} ({v['reason']})", t0)
            self.install_plan(c, v)
            return self.answer(txn, c, v, asked)["summary"]
        if act == "cancel":                                 # the community agent froze the deal without this home's late yes
            cid = (body["message"].get("contract") or {}).get("id")
            c = self.contracts.get(cid)
            if not c:
                return "cancel for a contract this home does not hold: nothing to undo"
            if c.get("status") == "ACCEPTED":
                if hasattr(self.adapter, "clear_plan"):
                    self.adapter.clear_plan(cid)
                if hasattr(self.adapter, "ev_holds"):
                    self.adapter.ev_holds = [x for x in self.adapter.ev_holds
                                             if tuple(x) != (c.get("window_start"), c.get("ev_resume_after"))]
                c["status"], c["reason"] = "CANCELLED", (body["message"].get("contract") or {}).get("reason")
                self.log("v2_contract_cancelled", contract_id=cid, reason=c["reason"])
            return f"contract {cid} cancelled"
        if act == "update":
            self.log("v2_event_notice", **{k: v for k, v in body["message"].items() if k != "contract"})
            return "event notice noted"
        if act == "rt_ask":                                 # the community agent asks, during the day: how much more?
            return self.rt_answer(txn, body["message"]["ask"], asked)
        if act == "rt_dispatch":                            # what this home owes on top of its booking
            return self.rt_take(txn, body["message"]["dispatch"])
        if act == "on_status" and "settlement" in body["message"]:
            st = body["message"]["settlement"]
            if any(p.get("event_id") == st.get("event_id") and p.get("top_up") == st.get("top_up") for p in self.payments):
                return f"payment for {st.get('event_id')} already noted"      # at-least-once delivery: count it once
            self.payments.append(st)
            self.reputation = float(st.get("reputation", self.reputation))
            self.log("v2_paid", event_id=st.get("event_id"), usd=st.get("payment"), delivered_kwh=st.get("delivered_kwh"))
            return f"payment noted: {st.get('payment')}"
        return beckn.Refused(f"ignored {kind}")


    REPORT_MIN_KW = 0.5            # a shortfall below this (or 10 % of what is owed) is the plan's noise, not news
    REPORT_AHEAD_STEPS = 12        # report what the next 3 hours look like
    REPORT_EVERY_MIN = 30          # forecast drift is reported at most every 30 dataset minutes; an owner's wish, a
                                   # battery trip or leaving the event at once


    def tick(self) -> list[str]:
        self.observe()
        for c in getattr(self.adapter, "clips", ()):        # the controller's writes pass no guard, so a limit that stopped one is on the record here
            self.log("write_clipped", **c)
        if getattr(self.adapter, "clips", None):
            self.adapter.clips = []
        self.rt_report()
        out = []
        for cid, sid in self.due_readings():
            txn = self.contracts[cid].get("transaction_id", "")
            out.append(self.send_reading(txn, self.build_reading(cid, sid))["summary"])
        return out

    def status(self) -> dict[str, Any]:
        tel = self.adapter.tel or {}
        return {"home": self.name, "now": self.now_ts(), "soc_pct": tel.get("soc_pct"), "grid_kw": tel.get("grid_kw"),
                "mode": tel.get("mode"), "offers": len(self.offers),
                "contracts": {k: v.get("status") for k, v in self.contracts.items()},
                "paid_usd": round(sum(float(p.get("payment") or 0) for p in self.payments), 4),
                "reputation": self.reputation, "time": time.time()}

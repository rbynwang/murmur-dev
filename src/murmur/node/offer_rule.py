"""Code's decisions at steps 5 and 6: how much of the planner's safe offer goes out, and the answer to a commitment the guard found safe.

The model is never asked here. The owner's wishes (a home) or the manager's policy (a building) apply to every offer and every commitment.
Each decision leaves a receipt in the node's decision record (NodeAgent.receipt); the market hears only the amount.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

from murmur.protocol import envelope as beckn
from murmur.node import grounds
from murmur.node.modes import BY_CODE, BY_CODE_SAYS
from murmur.node.offer_shape import Decisions, Wishes, drop_devices, held_back, kw_of, mean_kw, scale_building_offer, scale_offer
from murmur.node import note_words


class HomeRule:
    ROLE, WHO, WORD, DECIDES = "home", "owner", "the owner's", "the owner's wish decides"

    def __init__(self, v2: Any, wishes: Wishes, *, label: str = "", log: Callable[..., None] | None = None):
        self.v2, self.wishes, self.label = v2, wishes, label
        self.log = log or (lambda *a, **k: None)
        self.decisions = Decisions()
        self.needs: dict[str, dict[str, Any]] = {}
        self.forecasts: dict[str, dict[str, Any]] = {}
        self._done: dict[Any, Any] = {}               # (step, id) -> the decision already made: a redelivered message gets the same answer
        self._lock = threading.Lock()
        self.safe: dict[str, dict[str, Any]] = {}     # event id -> the planner's safe offer
        self.fallbacks: Counter = Counter()          # decisions with nothing to decide on: a day off, or nothing safe to offer

    def reset(self) -> None:
        """A new run: forget the decisions (the person's wishes stay)."""
        with self._lock:
            self._done.clear()
            self.needs.clear()
            self.forecasts.clear()
            self.decisions = Decisions()

    # ---- receipts
    def receipt(self, point: str, **r: Any) -> None:
        ag = getattr(self.v2, "agent", None)
        if ag is not None and hasattr(ag, "receipt"):
            ag.receipt(point, self.v2.now_ts(), **r)

    def tell(self, text: str, point: str) -> str:
        ag = getattr(self.v2, "agent", None)
        if ag is not None and hasattr(ag, "tell"):
            ag.tell(text, point, self.v2.now_ts())
        return text

    @staticmethod
    def offer_facts(need: dict[str, Any], rule: dict[str, Any], fmt: Callable[[float], str]) -> list[dict[str, str]]:
        """What an offer rests on: what the planner found safe, and what the sale is."""
        sl = need.get("slots") or []
        price = float(sl[0].get("price") or 0.0) if sl else 0.0
        return [{"id": "safe", "says": f"The planner found {fmt(mean_kw(rule))} kW per half hour safe to offer, within the person's own limits."},
                {"id": "sale", "says": f"The sale runs {str(need.get('window_start'))[11:16]} to {str(need.get('window_end'))[11:16]} on {str(need.get('window_start'))[:10]}, "
                                       f"and pays up to ${price:.2f} per kWh delivered."}]

    def before_note(self, eid: str, scale: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any] | None:
        """The rule's offer without a person's note: the safe offer before the note kept part of it out (HomeOffer.build_offer)."""
        before = (getattr(self.v2, "before_note", None) or {}).get(eid)
        return scale(before) if before else None

    def offer_receipt(self, need: dict[str, Any], rule: dict[str, Any], final: dict[str, Any], fmt: Callable[[float], str],
                      without: dict[str, Any] | None, by_code: bool) -> None:
        """An offer's receipt: the request, the rule's kW and what went out. When a person's note kept part of the offer out, the receipt measures
        against the offer without the note (a rule can't read one), the note is its fact, and the person hears it was heard."""
        noted = without is not None and sum(kw_of(without)) > sum(kw_of(rule)) + 0.01
        base = without if noted else rule
        less = sum(kw_of(final)) < sum(kw_of(base)) - 0.01
        told, flags = None, []
        why = BY_CODE_SAYS if by_code else (final.get("agent") or {}).get("reason") or "the model did not answer: the rule's offer"
        facts = self.offer_facts(need, rule, fmt)
        if noted:
            ag = getattr(self.v2, "agent", None)
            live = [w for w in getattr(getattr(ag, "guard", None), "wishes", None) or [] if grounds.in_force(w, need["window_start"])]
            words = dict.fromkeys((getattr(ag, "wish_notes", None) or {}).get(w["wish"]) for w in live)
            facts = [{"id": "note", "says": f'The {self.WHO} wrote: "{x}"'} for x in words if x] + facts
            told = self.tell(note_words.got_it(live, mean_kw(final), mean_kw(without), note_words.when_of(need["window_start"], self.v2.now_ts()), fmt), "offer")
            why = " ".join(x for x in (note_words.says(live, self.WHO), why) if x)
            flags = [note_words.FOR_NOTE]
        sl = need.get("slots") or []
        self.receipt("offer", asked={"event_id": need.get("event_id"), "window": [need.get("window_start"), need.get("window_end")],
                                     "kw_asked_per_half_hour": [x.get("kw_requested") for x in sl], "price_usd_per_kwh": float(sl[0].get("price") or 0.0) if sl else None},
                     rule={"kw_per_half_hour": kw_of(base), "what": "the planner's safe offer at the person's own limits" + (", without the note: a rule can't read one" if noted else ""),
                           **({"with_the_note": kw_of(rule)} if noted else {})}, chose={"kw_per_half_hour": kw_of(final)},
                     reason=why, facts=facts, flags=flags, by=f"rule: {BY_CODE}" if by_code else "rule: fallback", less=less, told=told)

    def accept_receipt(self, c: dict[str, Any], kw: list[float], out: dict[str, Any], changed: list[dict[str, Any]], reason: str, by_code: bool) -> None:
        declined = out.get("decision") == "DECLINED"
        mean = f"{sum(kw) / max(1, len(kw)):,.1f}"
        rests_on = [{"id": "commitment", "says": f"The commitment is {mean} kW per half hour on average, and code found it inside the offer."},
                    {"id": "changed", "says": "Nothing changed since the offer went out." if not changed else "; ".join(x["says"] for x in changed)}]
        self.receipt("commitment", asked={"contract_id": c.get("id"), "event_id": c.get("event_id"), "kw_per_half_hour": kw, "changed_since_the_offer": [x["says"] for x in changed]},
                     rule={"answer": "accept", "what": "inside the offer and safe"}, chose={"answer": "decline" if declined else "accept"},
                     reason=BY_CODE_SAYS if by_code else reason, facts=rests_on, flags=[],
                     by=f"rule: {BY_CODE}" if by_code else "rule: fallback", less=declined, told=None)

    # ---- step 5: the offer
    def shares(self, w: dict[str, Any]) -> dict[str, Any]:
        return {"battery_share": float(w["battery_max_share"]), "pause_ev": bool(not w["no_ev_pause"])}

    def scaled(self, offer: dict[str, Any], off: list[str], sh: dict[str, Any], take: bool) -> dict[str, Any]:
        has_ev = any(s.get("ev_pause_kw", 0) > 0 for s in offer["slots"])
        return scale_offer(drop_devices(offer, off), sh["battery_share"], sh["pause_ev"] and has_ev, take)

    def logged(self, offer: dict[str, Any], final: dict[str, Any], sh: dict[str, Any], take: bool) -> dict[str, Any]:
        has_ev = any(s.get("ev_pause_kw", 0) > 0 for s in offer["slots"])
        return {"battery_share": round(sh["battery_share"] if take else 0.0, 2), "pause_ev": bool(sh["pause_ev"] and has_ev and take)}

    def agent_shares(self, offer: dict[str, Any], sh: dict[str, Any]) -> dict[str, Any]:
        has_ev = any(s.get("ev_pause_kw", 0) > 0 for s in offer["slots"])
        return {"battery_share": float(sh["battery_share"]), "pause_ev": bool(sh["pause_ev"] and has_ev)}

    @staticmethod
    def fmt(x: float) -> str:
        return f"{x:.1f}"

    def decide_offer(self, need: dict[str, Any], fc: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
        eid = need["event_id"]
        with self._lock:
            if ("offer", eid) in self._done:
                return self._done[("offer", eid)]
        self.needs[eid], self.forecasts[eid] = need, fc
        sl = need.get("slots") or []
        price = float(sl[0].get("price") or 0.0) if sl else 0.0
        w = self.wishes.get()
        skip = self.wishes.skips(need["window_start"][:10]) or (f"the price ${price:.2f}/kWh is below {self.WORD} minimum "
                                                                 f"${w['min_price_usd_per_kwh']:.2f}" if price < w["min_price_usd_per_kwh"] else None)
        safe_kwh = offer["energy_kwh"]
        t0 = time.perf_counter()
        code = not skip and safe_kwh > 0.01             # code decides: nothing to weigh is no failure
        error = None if code else self.DECIDES if skip else "nothing safe to offer (the planner offered 0 kW)"
        if not code:
            self.fallbacks["offer"] += 1
        take = bool(code)
        sh = self.shares(w)
        reason = skip or ("rules: the planner's safe offer" + (f" ({BY_CODE})" if code else f" ({error})"))
        have = set((getattr(self.v2.adapter, "app", None) or {}))
        off = sorted(have & set(w.get("devices_off") or []))
        if have:
            self.v2.adapter.dev_off = set(off)
        final = self.scaled(offer, off, sh, take)
        self.safe[eid] = offer
        rule = self.scaled(offer, off, sh, not skip)
        final["held_back_kw"] = held_back(rule, final)
        d = self.decisions.add(kind="offer", event_id=eid, sim=self.v2.now_ts(), take_part=take, **self.logged(offer, final, sh, take),
                               safe_kw=[s["kw_offered"] for s in offer["slots"]], kw=[s["kw_offered"] for s in final["slots"]],
                               price=price, if_delivered_usd=round(final["energy_kwh"] * price, 2), reason=reason, reason_log=reason, guard=[],
                               fallback=not code, routine=code, **({"by_code": True} if code else {}), check={}, devices_off=off,
                               llm={"model": None, "ms": None, "error": error, "runtime": None})
        final["agent"] = {"decided_by": "rules", "reason": reason[:300], "decision": d["n"], "take_part": take, **self.agent_shares(offer, sh), "devices_off": off}
        self.log("agent_decision", what="offer", event_id=eid, take_part=take, kw=d["kw"], fallback=not code, reason=reason[:200],
                 ms=round((time.perf_counter() - t0) * 1000, 1))
        final["agent"]["wishes"], final["agent"]["seen"] = grounds.stamp(w), grounds.seen(self.v2, w)
        final["agent"]["flags"] = []
        without = self.before_note(eid, lambda o: self.scaled(o, off, sh, not skip))
        self.offer_receipt(need, rule, final, self.fmt, without, code)
        with self._lock:
            self._done[("offer", eid)] = final
        return final

    # ---- step 6: the commitment
    OPTED_OUT = "homeowner_opted_out"

    def decide_accept(self, c: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
        cid = c.get("id")
        if verdict.get("decision") != "ACCEPTED" or not cid:
            return verdict                                   # the guard said no
        with self._lock:
            if ("accept", cid) in self._done:
                return self._done[("accept", cid)]
        skip = self.wishes.skips(str(c.get("window_start", ""))[:10])
        offer = self.v2.offers.get(c.get("event_id")) or {}
        sl = (self.needs.get(c.get("event_id")) or {}).get("slots") or []
        price = float(sl[0].get("price") or 0.0) if sl else float(c.get("price_usd_per_kwh") or 0.0)
        kw = [float(x.get("kw", 0)) for x in c.get("commitments", [])]
        usd = round(sum(kw) * beckn.SLOT_MINUTES / 60 * price, 2)
        if getattr(self.v2, "agent", None) is not None:           # a note that came in since: what it asks is what changed
            self.v2.agent.read_note(self.v2.now_ts())
        changed = grounds.since_offer(self.v2, offer, self.wishes.get(), str(c.get("window_start", "")), price)
        code = not skip
        if skip:
            self.fallbacks["accept"] += 1
            out, reason = {"decision": "DECLINED", "reason": self.OPTED_OUT, "contract_id": cid}, skip
        else:
            out, reason = verdict, f"code: within the offer and safe ({BY_CODE})"
        self.decisions.add(kind="accept", event_id=c.get("event_id"), contract_id=cid, sim=self.v2.now_ts(), accept=out["decision"] == "ACCEPTED",
                           decision=out["decision"], kw=kw, price=price, if_delivered_usd=usd, reason=reason, fallback=not code, routine=code,
                           **({"by_code": True} if code else {}), check={}, **({"node": "building"} if self.ROLE == "building" else {}),
                           llm={"model": None, "ms": None, "error": None if code else self.DECIDES, "runtime": None})
        self.log("agent_decision", what="accept", contract_id=cid, decision=out["decision"], fallback=not code, reason=reason[:200])
        self.accept_receipt(c, kw, out, changed, reason, code)
        with self._lock:
            self._done[("accept", cid)] = out
        return out


class BuildingRule(HomeRule):
    """A building's steps 5 and 6: the same rule over its own levers, the share of its cooling and of its lighting, under the manager's policy."""
    ROLE, WHO, WORD, DECIDES = "building", "manager", "the facility manager's", "the facility manager's policy decides"
    OPTED_OUT = "facility_manager_opted_out"

    def shares(self, w: dict[str, Any]) -> dict[str, Any]:
        return {"cooling_share": float(w["cooling_max_share"]), "lighting_share": float(w["lighting_max_share"])}

    def scaled(self, offer: dict[str, Any], off: list[str], sh: dict[str, Any], take: bool) -> dict[str, Any]:
        return scale_building_offer(drop_devices(offer, off), sh["cooling_share"], sh["lighting_share"], take)

    def logged(self, offer: dict[str, Any], final: dict[str, Any], sh: dict[str, Any], take: bool) -> dict[str, Any]:
        return {"node": "building", "cooling_share": round(sh["cooling_share"] if take else 0.0, 2), "lighting_share": round(sh["lighting_share"] if take else 0.0, 2),
                "cooling_kw": [s.get("ac_kw", 0.0) for s in final["slots"]], "lighting_kw": [s.get("light_kw", 0.0) for s in final["slots"]]}

    def agent_shares(self, offer: dict[str, Any], sh: dict[str, Any]) -> dict[str, Any]:
        return {"cooling_share": float(sh["cooling_share"]), "lighting_share": float(sh["lighting_share"])}

    @staticmethod
    def fmt(x: float) -> str:
        return f"{x:,.0f}"


"""The stand-in buyer's orders and baselines: an order checked and placed, the meters it enrols, and each meter's baseline from its own history."""
from __future__ import annotations

import json
from typing import Any
from murmur.protocol import envelope as beckn
from murmur import config
from murmur.settlement import rules as st
from murmur.protocol import signing
from murmur.node.simulator import SimulatedHome
from murmur.replay import Replay
from murmur.settlement import meter_check as mc
from demo.runner.buyers.utility_meters import _meter_cfg


class UtilityOrders:
    """The stand-in buyer's orders and baselines: an order checked and placed, the meters it enrols, and each meter's baseline from its own history."""

    def place_order(self, o: dict[str, Any]) -> dict[str, Any]:
        """A buyer agent's order for one day's window becomes that day's DEG need (DemandFlexNeed + BuyOffer), signed by
        the utility. Raises ValueError("400: ...") for a malformed order and ValueError("409: ...") for one that comes
        too late (the call for offers has gone out) or twice."""
        def bad(msg: str):
            raise ValueError(f"400: {msg}")
        date, start, end = str(o.get("date", "")), str(o.get("start", "")), str(o.get("end", ""))
        try:
            beckn.add_minutes(f"{date} 00:00", 0)                 # raises on a date that isn't YYYY-MM-DD
        except ValueError:
            bad("date must be YYYY-MM-DD")
        meta = config.dataset_meta()                          # an order's day lies in the dataset, from its first full day after the warm-up
        lo, hi = meta.get("baseline_from", meta["range"][0]), meta["range"][1]
        if not lo <= date <= hi:
            bad(f"{date} is outside the data this buyer runs on ({lo} to {hi})")
        def minutes(hhmm: str) -> int:
            try:
                h, m = (int(x) for x in hhmm.split(":"))
            except ValueError:
                bad("start and end are local times HH:MM")
            if not (0 <= h < 24 and m in (0, 30)):
                bad("start and end must be on the half hour (HH:00 or HH:30)")
            return h * 60 + m
        m0, m1 = minutes(start), minutes(end)
        if m1 <= m0:
            bad("the window must end after it starts")
        if m1 - m0 > self.ORDER_MAX_H * 60:
            bad(f"the window may be at most {self.ORDER_MAX_H:g} h")
        try:
            kw, price = float(o.get("kw")), float(o.get("price_usd_per_kwh"))
        except (TypeError, ValueError):
            bad("kw and price_usd_per_kwh must be numbers")
        if not 0 < kw <= self.ORDER_MAX_KW:
            bad(f"kw must be more than 0 and at most {self.ORDER_MAX_KW:g} per slot")
        if not 0 < price <= self.ORDER_MAX_PRICE:
            bad(f"price_usd_per_kwh must be more than 0 and at most {self.ORDER_MAX_PRICE:g}")
        # now: the buyer's own clock, never a time taken from the order itself, so an order cannot be backdated past its notice time
        eid, notice, now = f"{self.ORDER_PREFIX}{date}", self.notice_of(date), self.now()
        if eid in self.orders:
            raise ValueError(f"409: an order for {date} was already placed by {self.orders[eid]['buyer']}")
        if now >= notice:
            raise ValueError(f"409: too late for {date}: the call for offers went out at {notice} (now {now})")
        if any(c.get("need", {}).get("event_id") == eid for c in self.contracts.values()):
            raise ValueError(f"409: {date} is already contracted")
        # the DEG resource + offer, in the catalog's own shape: a copy of its first resource and that resource's offer
        tr = self.catalog["resources"][0]
        to = next(x for x in self.catalog["offers"] if x["resourceIds"][0] == tr["id"])
        n_slots = (m1 - m0) // beckn.SLOT_MINUTES
        ws = f"{date} {start}"
        utc = beckn.utc_from_local                       # the dataset's local time, as the catalog
        tzl = config.dataset_meta().get("tz_label", "CDT")
        resource = json.loads(json.dumps(tr))
        resource.update({"id": eid, "descriptor": {"name": f"Buyer order {date}",
                                                    "shortDesc": f"{kw:g} kW, {start}-{end} {tzl}"},
                         "quantity": {**tr.get("quantity", {}), "unitQuantity": kw}})
        ra = resource["resourceAttributes"]
        ra["intervalPeriod"] = {**ra["intervalPeriod"], "start": utc(ws)}
        ra["intervals"] = [{"id": k, "payloads": [{"type": "CAPACITY_REQUESTED", "values": [kw]},
                                                  {"type": "PRICE", "values": [price]},
                                                  {"type": "SHORTFALL_PENALTY", "values": [0.0]}]}
                           for k in range(n_slots)]
        offer = json.loads(json.dumps(to))
        offer.update({"id": f"offer-{date}", "resourceIds": [eid],
                      "descriptor": {"name": f"Buyer order {date}", "shortDesc": f"{st.up_to()}${price:g}/kWh reduced, measured against baseline"},
                      "validity": {"endDate": utc(f"{beckn.add_minutes(f'{date} 00:00', -1440)[:10]} 16:00")}})
        for x in offer["offerAttributes"].get("inputs") or []:
            if x.get("role") == "buyer":
                x["participantId"] = self.PARTICIPANT
        deposit = max(0.0, float(o.get("deposit_usd") or 0.0))
        if deposit > 0:                                  # it holds tentative power: the community agent reads it from the signed offer
            offer["offerAttributes"]["deposit"] = {"usd": deposit}
        need = beckn.need_from_catalog(resource, offer)
        rec = signing.sign({"event_id": eid, "buyer": str(o.get("buyer") or "buyer agent")[:80], "placed_at": now,
                            "order": {"date": date, "start": start, "end": end, "kw": kw, "price_usd_per_kwh": price,
                                      "note": str(o.get("note") or "")[:200], **({"deposit_usd": deposit} if deposit > 0 else {})},
                            "notice": notice, "commit_by": need["commit_by"], "resource": resource, "offer": offer},
                           self.key)
        self.orders[eid] = rec
        self.event_days.add(need["window_start"][:10])     # an event day never counts in a later baseline
        self.event("need_posted", event_id=eid, buyer=rec["buyer"], kw=kw, window=[need["window_start"], need["window_end"]],
                   price_usd_per_kwh=price)
        return rec

    # ------------------------------------------------------------------ baselines
    def baselines(self, ct: dict[str, Any], meters: list[str]) -> dict[str, dict[str, dict[str, float]]]:
        """Each meter's baseline per slot from its own history (the utility's meter data, before the event).
        Always the baseline in force (rules.baseline_rule): the last 10 days of the same kind, flagged when there aren't 10 clean ones."""
        need = ct["need"]
        day = need["window_start"][:10]
        ev_days = {st.day_of(x) for x in self.event_days}
        pick = st.baseline_days(st.day_of(day), ev_days)       # the days, and the rule that chose them: flagged when it isn't 10 clean days of the same kind
        days = pick["days"]
        first = min(days).isoformat() if days else beckn.add_minutes(f"{day} 00:00", -14 * 1440)[:10]
        out = {}
        thin: list[int] = []                              # how many days each meter's baseline rests on
        for m in meters:
            h = self.fleet.get(m)
            if not h:
                continue
            rp = Replay(h["profile"], need["window_start"], 60, 0)
            ev_max = rp.sessions[0]["max_kw"] if rp.sessions else 0.0
            sim = SimulatedHome(_meter_cfg(h, ev_max), rp)
            i_from = rp.idx_of(beckn.add_minutes(f"{first} 00:00", -1440))   # one day of warm-up before the first
            if i_from is None:                                # data that starts on the first baseline day: the warm-up is what there is
                i_from = rp.idx_of(f"{first} 00:00") or 0
            i_to = rp.idx_of(f"{day} 00:00")
            series = dict(sim.run_default(i_from, i_to))
            def window(d: str) -> list[float] | None:
                vals = []
                for s in need["slots"]:
                    t0 = d + s["start"][10:]
                    t1 = beckn.add_minutes(t0, 15)
                    if t0 in series and t1 in series:
                        vals.append(-(series[t0] + series[t1]) / 2)
                return vals if len(vals) == len(need["slots"]) else None
            usage_by_day = {}
            for dd in days:
                v = window(dd.isoformat())
                if v:
                    usage_by_day[dd] = v
            if pick["add_back"]:               # a sale day's use is what was left after the cut: what was recorded as delivered that day goes back on
                for dd in list(usage_by_day):
                    gave = self._delivered_on(m, dd.isoformat())
                    usage_by_day[dd] = [v + gave.get(s["start"][11:16], 0.0) for v, s in zip(usage_by_day[dd], need["slots"])]
            if pick["flag"]:
                b = st.mean_of_days(usage_by_day, days)
            else:
                b = st.ten_of_ten(usage_by_day, st.day_of(day), ev_days)
            if not b["per_slot"]:              # no day to measure against: no number at all, never 0 kW, which would count nothing as delivered and pay nobody, in silence
                out[m] = {}
                thin.append(0)
            else:
                out[m] = {str(s["id"]): {"BASELINE": b["per_slot"][j]}
                          for j, s in enumerate(need["slots"])}
                thin.append(len(b["days"]))
            p0 = beckn.add_minutes(need["window_start"], -120)[10:]      # the same-day adjustment's hour: 2 hours before the event
            pre = []
            for dd in days:
                xs = [series.get(beckn.add_minutes(dd.isoformat() + p0, 15 * q)) for q in range(4)]
                if all(x is not None for x in xs):
                    pre.append(-sum(xs) / 4)
            ct.setdefault("pre_baselines", {})[m] = round(sum(pre) / len(pre), 3) if pre else None
            ct.setdefault("solar", {})[m] = mc.recent_solar(rp, days, need["slots"])
            out[m]["_days"] = b["days"]
        if thin and (pick["flag"] or min(thin) < st.BASELINE_THIN):      # not 10 clean days of the same kind, or under 5 for a meter: said on the contract and the settlement, and an alarm in the event log
            ct["baseline_rule"] = {"rule": pick["rule"], "days": min(thin), "meters_without_a_baseline": sorted(m for m in out if not any(k != "_days" for k in out[m]))}
            self.event("baseline_flagged", event_id=need["event_id"], rule=pick["rule"], days=min(thin), meters_without=len(ct["baseline_rule"]["meters_without_a_baseline"]))
        return out

    def _delivered_on(self, meter: str, day: str) -> dict[str, float]:
        """What this buyer's own settlements record as delivered by one meter on one day, by the half hour's clock time: {"18:00": kW}. Nothing on record: nothing."""
        out: dict[str, float] = {}
        for c in self.contracts.values():
            n = c.get("need") or {}
            if str(n.get("window_start") or "")[:10] != day:
                continue
            got = (((c.get("settled_msg") or {}).get("settlement") or {}).get("actuals") or {}).get(meter) or {}
            for s in n.get("slots") or []:
                v = got.get(str(s["id"]))
                if v:
                    out[s["start"][11:16]] = max(out.get(s["start"][11:16], 0.0), st.clamp0(float(v["BASELINE"]) - float(v["USAGE"])))
        return out

    def settlement_baselines(self, ct: dict[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
        """The baselines the settlement uses: those sent with the contract."""
        return ct.get("baselines", {})

    # ------------------------------------------------------------------ inbox
    def _enroll(self, ct: dict[str, Any], requested: list[str]) -> list[str]:
        """The meters this contract may count: a meter is enrolled in at most one open contract per event."""
        eid = ct["need"]["event_id"]
        held = {m for c in self.contracts.values() if c is not ct and c.get("status") in ("DRAFT", "ACTIVE")
                and c.get("need", {}).get("event_id") == eid for m in c.get("meters", [])}
        refused = sorted(set(requested) & held)
        if refused:
            self.event("meters_refused", event_id=eid, aggregator=ct.get("seller"), meters=refused,
                       reason="enrolled in another contract for this event")
        ct["refused_meters"] = refused
        return [m for m in requested if m not in held]

    def _contract_of_meter(self, meter: str, event_id: str | None) -> dict[str, Any] | None:
        """The ACTIVE contract for this event that the meter is enrolled in (at most one, see _enroll). Else the settled one, since a reading
        that comes after the settlement is still owed for."""
        cs = [c for c in self.contracts.values() if c.get("status") in ("ACTIVE", "COMPLETE")
              and event_id in (c.get("need", {}).get("event_id"), c.get("community_event"))
              and meter in c.get("meters", [])]
        return next((c for c in cs if c["status"] == "ACTIVE"), cs[-1] if cs else None)

    @staticmethod
    def _pool_terms(ct: dict[str, Any], c: dict[str, Any]) -> None:
        """The community agent's terms when two buyers fill from one pool: this buyer's share of each half hour on the same meters, the
        pool's capacity (a call pays only for what goes beyond all of it), the sale's id on the readings, and the deposit it holds."""
        if "share" not in c:
            return
        ct["share"] = {int(k): float(v) for k, v in c["share"].items()}
        ct["pool_offered"] = {int(k): float(v) for k, v in (c.get("poolCapacity") or {}).items()}
        ct["community_event"] = c.get("community_event")
        ct["deposit_held_usd"] = float(c.get("deposit_held_usd") or 0.0)

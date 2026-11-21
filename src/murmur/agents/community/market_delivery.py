"""After the clearing: each member's commitment, a declined share topped up from spare offers, the notices, and the meter readings the sale is owed."""
from __future__ import annotations

import time
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.protocol import ids
from murmur.settlement import rules as st
from murmur.agents.community.market_rules import READINGS_CHASES, READINGS_CHASE_AFTER_MIN, READINGS_CHASE_EVERY_MIN, READINGS_DUE_MIN, READINGS_EXTRA_MIN
from murmur.settlement import market_checks


class MarketDelivery:
    """After the clearing: each member's commitment, a declined share topped up from spare offers, the notices, and the meter readings the sale is owed."""

    def _contract_for(self, ev: dict[str, Any], home: str, slots: dict[int, float], k_ev: int) -> dict[str, Any]:
        n = ev["need"]
        sold = (ev.get("sold_offers") or {}).get(home) or {}

        def part(sid: int, kw: float) -> dict[str, float]:         # the pool only: how much of this commitment is firm
            x = self._slot_of(sold, sid) if sold else {}
            return {"firm_kw": round(min(kw, float(x.get("firm_kw", 0.0))), 3)} if x else {}
        return {"id": f"{n['event_id']}:{home}", "event_id": n["event_id"], "home": home,
                "window_start": n["window_start"], "window_end": n["window_end"],
                "commitments": [{"id": sid, "start": next(s["start"] for s in n["slots"] if s["id"] == sid), "kw": kw, **part(sid, kw)}
                                for sid, kw in sorted(slots.items())],
                "price_usd_per_kwh": n["slots"][0]["price"], "opt_out_by": n["commit_by"],
                "ev_resume_after": ev.get("ev_restart", {}).get(home) or n["window_end"],
                "precharge_minutes": 120, "settlement_rule": st.pay_rule()}

    def commit_homes(self, ev: dict[str, Any], homes: list[str], resend: bool = False) -> None:
        """Send each home its commitment. resend: the same contract again to homes that have not answered (the
        confirm or the answer was lost on the way); a home that did answer simply repeats its answer."""
        items, now, wall = [], self.now(), time.time()
        for k, h in enumerate(homes):
            cm = ev["commitments"].get(h) if resend else None
            if cm:
                c = cm["contract"]
                cm["tries"] = cm.get("tries", 1) + 1
                cm["sent_at"], cm["sent_wall"] = now, wall
            else:
                c = self._contract_for(ev, h, ev["alloc"][h], k)
                ev["commitments"][h] = {"status": "SENT", "contract": c, "sent_at": now, "sent_wall": wall, "tries": 1}
            items.append((h, "confirm", self._msg("confirm", h, ev["ctxn"], {"contract": c}),
                          self.mid(h, "confirm", c["id"], ev["commitments"][h]["tries"])))    # sent again, it's the next try: a home that lost it, or whose answer was lost, hears it
        self._broadcast(items)
        self.log("v2_commitments_resent" if resend else "v2_commitments_sent", event_id=ev["need"]["event_id"],
                 homes=len(items))

    def resend_commitments(self, ev: dict[str, Any], now: str) -> None:
        """Homes still SENT after `confirm_retry_minutes` get their commitment again, at most `confirm_retries`
        times (bounded: a home that never answers is simply left out at finalize). A live demo replays a day in
        minutes (12 s per 15-minute step, so 30 replay minutes are 24 s), so a re-send also waits
        `confirm_retry_wall_seconds` of real time (120): a slow link is not a lost message. The
        offline simulation (sync_broadcast) has no real time to wait for."""
        wait = float(self.cfg.get("confirm_retry_minutes", 30))
        tries = int(self.cfg.get("confirm_retries", 3))
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("confirm_retry_wall_seconds", 120))
        t = time.time()
        again = [h for h, c in ev["commitments"].items() if c["status"] == "SENT" and c.get("tries", 1) <= tries
                 and now >= beckn.add_minutes(c.get("sent_at", now), wait)
                 and (floor <= 0 or t - c.get("sent_wall", 0.0) >= floor)]
        if again:
            self.commit_homes(ev, again, resend=True)

    def top_up(self, ev: dict[str, Any], decliner: str) -> None:
        """Replace a declined share with spare offers from homes not yet asked (in roster order), once per decliner,
        and only with what the rebound guard lets each of those homes deliver (its EV pause plus the cleared share
        of its battery offer): a replacement must not empty a battery the guard did not plan for."""
        if ev.get("finalized") or decliner in ev.setdefault("topped_up", []):
            return
        ev["topped_up"].append(decliner)
        missing = dict(ev["alloc"].get(decliner, {}))
        share = ev.get("battery_share") or {}
        new = []
        for h, o in sorted((ev.get("sold_offers") or ev["offers"]).items()):
            if not missing or h in ev["commitments"]:
                continue
            take = {}
            for sid, kw in list(missing.items()):
                x = next((x for x in o["slots"] if x["id"] == sid), {})
                allowed = x.get("ev_pause_kw", 0.0) + share.get(sid, 0.0) * x.get("battery_kw", 0.0)
                avail = min(x.get("kw_offered", 0.0), allowed)
                t = round(min(avail, kw), 3)
                if t >= 0.05:
                    take[sid] = t
                    missing[sid] = round(kw - t, 3)
                    if missing[sid] < 0.05:
                        missing.pop(sid)
            if take:
                ev["alloc"][h] = take
                new.append(h)
        if new:
            self.commit_homes(ev, new)
        self.log("v2_top_up", event_id=ev["need"]["event_id"], decliner=decliner, replacements=new,
                 still_missing_kw=missing)

    def finalize(self, ev: dict[str, Any]) -> None:
        """Freeze who takes part and the capacity sold (once), then tell the utility. The update is sent again on
        every tick until Town takes it: the utility computes its baselines from it, so it must not be lost."""
        if not ev.get("finalized"):
            acc = {h: c for h, c in ev["commitments"].items() if c["status"] == "ACCEPTED"}
            cap = {}
            for s in ev["need"]["slots"]:
                got = sum(next((x["kw"] for x in c["contract"]["commitments"] if x["id"] == s["id"]), 0.0) for c in acc.values())
                cap[s["id"]] = round(min(ev["capacity_offered"][s["id"]], got / (1.0 if self.fill else 1 + self.margin_of(ev))), 2)
            ev["capacity_offered_final"] = cap
            ev["final_meters"] = sorted(acc)
            ev["final_slots"] = {h: sorted(x["id"] for x in c["contract"]["commitments"]) for h, c in acc.items()}
            ev["finalized"] = True
            self.log("v2_final", event_id=ev["need"]["event_id"], accepted=len(acc),
                     declined=sum(1 for c in ev["commitments"].values() if c["status"] == "DECLINED"),
                     capacity_offered_kw=cap)
        cap = ev["capacity_offered_final"]
        msg = lambda od: {"contract": {"participatingMeters": ev["final_meters"],  # noqa: E731
                                       "capacityOffered": {str(k): v for k, v in self._tranche(ev, od, cap).items()},
                                       "meterSlots": ev["final_slots"], **self._terms(ev, od, cap)}}
        if self._to_utility(ev, "update", msg, key=("final",)):
            ev["final_sent"] = True

    def notify_homes(self, ev: dict[str, Any]) -> None:
        ev["notice_sent"] = True
        if self.quiet:                                    # the contract already carries the pre-charge time
            return
        n = ev["need"]
        items = [(h, "update", self._msg("update", h, ev["ctxn"], {"notice": "event_tomorrow_precharge_now",
                                                                    "event_id": n["event_id"], "window_start": n["window_start"]}),
                  self.mid(h, "update", n["event_id"], "notice"))
                 for h, c in ev["commitments"].items() if c["status"] == "ACCEPTED"]
        self._broadcast(items)
        self.log("v2_event_notice", event_id=n["event_id"], homes=len(items))

    def send_telemetry(self, ev: dict[str, Any]) -> None:
        """Tell the utility the community's readings are in. Each home already sent its own signed readings to the
        utility; the community agent does not relay them (it could not alter them, and 100 x 4 signed bodies are ~600 kB,
        too big for one message over a slow link). Retried on the next tick if the send fails."""
        got = sum(len(v) for v in ev["readings"].values())
        for od in self._orders(ev):                       # however long Town is away, each buyer until it took this: without it a buyer never settles
            if not od.get("readings_told"):
                msg = self._readings_in(ev)               # the state of the moment: the same words again are a retry, and new ones are the news
                od["readings_told"] = self._to_order(ev, od, "update", msg, ttl_s=beckn.TTL_EVIDENCE_S, key=("readings_in", ids.digest(msg)))
        ok = all(od["readings_told"] for od in self._orders(ev))
        if ok:
            ev["telemetry_sent"], ev["telemetry_at"], ev["telemetry_wall"] = True, self.now(), time.time()
        self.log("v2_telemetry_to_utility", event_id=ev["need"]["event_id"], meters=len(ev["readings"]), readings=got,
                 sent=ok)

    def _readings_in(self, ev: dict[str, Any]) -> dict[str, Any]:
        return {"telemetry_done": {"meters": len(ev["readings"]), "readings": sum(len(v) for v in ev["readings"].values()),
                                   "missing": sum(len(v) for v in (ev.get("readings_missing") or {}).values()),
                                   "called_slots": self.rt.called_slots(ev), "abnormal": self.rt.abnormal_slots(ev), "owed": market_checks.owed_kw(self, ev)}}

    def ask_silent(self, ev: dict[str, Any], now: str) -> None:
        """Members with no offer in hear the call again while the sale is open. A node whose offer went missing can't sell, and nobody else would ask it."""
        n, wall = ev["need"], time.time()
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("offers_retry_wall_seconds", 120))
        if now < beckn.add_minutes(ev.setdefault("called_at", now), float(self.cfg.get("offers_retry_minutes", 30))) or wall < ev.setdefault("called_wall", wall) + floor:
            return
        silent = [h for h in self.roster if h not in ev["offers"]]
        ev["called_at"], ev["called_wall"] = now, wall
        if silent:
            ev["calls_again"] = ev.get("calls_again", 0) + 1      # its own round: the first call may have reached Town, and a retry there would deliver nothing
            self._broadcast([(h, "discover", self._msg("discover", h, ev["ctxn"], {"intent": {"need": self._pool_need(ev)}}), self.mid(h, "discover", n["event_id"], "call", ev["calls_again"])) for h in silent])
            self.log("v2_call_again", event_id=n["event_id"], homes=len(silent), offers=len(ev["offers"]), first=silent[:8])

    def ask_settlement(self, ev: dict[str, Any], now: str) -> None:
        """A buyer that has told nothing since "readings are in" hears it again. One that settled sends its settlement again (as the demo's stand-in buyer does,
        demo/runner/buyers/utility.py), and one that never heard it starts now. Every seller waits on this: a lost settlement holds back the whole sale's pay,
        and v2_settlement_missing says so."""
        owing = [od for od in self._orders(ev) if not od.get("settlement")]
        wall = time.time()
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("readings_chase_wall_seconds", 120))
        if not owing or now < beckn.add_minutes(ev.get("telemetry_at", now), 2 * READINGS_CHASE_EVERY_MIN) or wall < ev.get("telemetry_wall", wall) + floor:
            return
        ev["telemetry_at"], ev["telemetry_wall"] = now, wall
        self.log("v2_settlement_missing", event_id=ev["need"]["event_id"], buyers=[od["buyer"] for od in owing])
        for od in owing:
            msg = self._readings_in(ev)
            self._to_order(ev, od, "update", msg, ttl_s=beckn.TTL_EVIDENCE_S, key=("readings_in", ids.digest(msg), now))    # asked again, even in the same words

    def readings_due(self) -> int:
        """Readings the open sales are still owed, from the nodes' batches going out to the market's last deadline: what the live clock waits for.
        Arrivals can't say: they stop too when the link is down."""
        last = float(self.cfg.get("readings_wait_minutes", 120)) + READINGS_EXTRA_MIN
        with self.lock:
            now = self.now()
            return sum(sum(len(v) for v in self.missing_readings(ev).values()) for ev in self.events.values() if ev.get("final_sent") and ev["phase"] != "done"
                       and beckn.add_minutes(ev["need"]["window_end"], READINGS_DUE_MIN) <= now < beckn.add_minutes(ev["need"]["window_end"], last))

    # ------------------------------------------------------------------ readings still missing
    def missing_readings(self, ev: dict[str, Any]) -> dict[str, list[int]]:
        """What each node with an accepted contract still owes in readings: the half hours it committed to that aren't in here, or that a buyer
        said it lacks. Each buyer pays on its own copy, and only it knows what reached it."""
        out = {}
        for h, c in ev["commitments"].items():
            if c["status"] == "ACCEPTED":
                got = {**(ev["readings"].get(h) or {}), **(ev.get("rejected_slots") or {}).get(h, {})}    # a reading refused came: asking again brings the same one
                miss = [x["id"] for x in c["contract"]["commitments"] if x["id"] not in got]
                if miss:
                    out[h] = miss
        for od in self._orders(ev):
            for h, slots in (od.get("lacking") or {}).items():
                if h in ev["commitments"]:
                    out[h] = sorted(set(out.get(h, [])) | set(slots))
        return out

    def _readings_quiet(self, ev: dict[str, Any]) -> bool:
        return time.time() - float(ev.get("last_reading_wall") or 0.0) >= float(self.cfg.get("readings_quiet_s", 0.0))

    def chase_readings(self, ev: dict[str, Any], now: str, missing: dict[str, list[int]]) -> bool:
        """Asks the nodes that owe readings to send them again. The market pays on readings, and Town can lose a batch without an error, so settling
        on what happens to be in underpays sellers who delivered. It waits for the batches after the window and for a quiet inbox, so a reading still
        on its way isn't asked for twice."""
        n, wall = ev["need"], time.time()
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("readings_chase_wall_seconds", 120))
        if wall < ev.setdefault("chased_wall", wall) + floor:       # as confirm_retry_wall_seconds: a slow Town is not a lost message, and each round puts 3 sends per node on it
            return False
        if now < beckn.add_minutes(n["window_end"], READINGS_CHASE_AFTER_MIN) or not self._readings_quiet(ev):
            return False
        every = READINGS_CHASE_EVERY_MIN * 2 ** max(0, ev.get("chases", 0) - READINGS_CHASES)
        if ev.get("chased_at") and now < beckn.add_minutes(ev["chased_at"], every):
            return False
        ev["chased_at"], ev["chased_wall"], ev["chases"] = now, wall, ev.get("chases", 0) + 1
        eid = n["event_id"]
        self._broadcast([(h, "status", self._msg("status", h, ev["ctxn"], {"readings_wanted": {
            "event_id": eid, "contract_id": ev["commitments"][h]["contract"]["id"], "slots": slots}}, ttl_s=beckn.TTL_EVIDENCE_S),
            self.mid(h, "status", eid, "chase", ev["chases"])) for h, slots in sorted(missing.items())])
        self.log("v2_readings_chased", event_id=eid, round=ev["chases"], nodes=len(missing), readings=sum(len(v) for v in missing.values()))
        return True

"""Delivery on a member's side: signed meter readings for each half hour owed, and the real-time desk's calls and gaps."""
from __future__ import annotations

from concurrent.futures import Future
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.protocol import ids


class HomeDelivery:
    """Delivery on a member's side: signed meter readings for each half hour owed, and the real-time desk's calls and gaps."""

    # ------------------------------------------------------------------ H5 Report
    def due_readings(self) -> list[tuple[str, int]]:
        cur = self.now_idx()
        due = []
        for cid, c in self.contracts.items():
            if c.get("status") != "ACCEPTED":
                continue
            busy = c.get("in_flight") or []
            for s in c["commitments"]:
                i0 = self.replay.idx_of(s["start"])
                if i0 is not None and cur > i0 + 1 and s["id"] not in c["reported"] and s["id"] not in busy \
                        and i0 in self.adapter.recent and i0 + 1 in self.adapter.recent:
                    due.append((cid, s["id"]))
        return due

    def _pre_kw(self, c: dict[str, Any]) -> float | None:
        """benchmark: the meter's mean import in the hour starting 2 hours before the event (the same-day adjustment)."""
        w0 = c.get("window_start") or min((x["start"] for x in c.get("commitments") or []), default=None)
        if w0 is None:
            return None
        j = self.replay.idx_of(beckn.add_minutes(w0, -120))
        rec = getattr(self.adapter, "recent", {}) or {}
        vals = [rec[k]["grid_kw"] for k in range(j, j + 4) if k in rec] if j is not None else []
        return round(-sum(vals) / len(vals), 3) if len(vals) == 4 else None

    def build_reading(self, cid: str, slot_id: int) -> dict[str, Any]:
        c = self.contracts[cid]
        s = [x for x in c["commitments"] if x["id"] == slot_id][0]
        i0 = self.replay.idx_of(s["start"])
        t0, t1 = self.adapter.recent[i0], self.adapter.recent[i0 + 1]
        usage = -(t0["grid_kw"] + t1["grid_kw"]) / 2
        usage_cf = -(t0["grid_cf_kw"] + t1["grid_cf_kw"]) / 2
        self.log("tool", tool="meter_reading", input=f"slot {slot_id} ({s['start'][11:]}), committed {s['kw']:g} kW less",
                 output=f"grid use {usage:.2f} kW, battery {t1['soc_pct']:.0f} %" + (", EV paused" if t0["ev_held"] or t1["ev_held"] else ""), ms=0.0)
        return {"contract_id": cid, "event_id": c["event_id"], "home": self.name, "slot_id": slot_id,
                "start": s["start"], "committed_kw": s["kw"], "usage_kw": round(usage, 3),
                "soc_end_pct": t1["soc_pct"], "modes": [t0["mode"], t1["mode"]], "ev_held": t0["ev_held"] or t1["ev_held"],
                "battery_kw": round((t0.get("batt_kw", 0.0) + t1.get("batt_kw", 0.0) + t0.get("v2h_kw", 0.0) + t1.get("v2h_kw", 0.0)) / 2, 3), "pre_kw": self._pre_kw(c),
                "truth": {"usage_without_event_kw": round(usage_cf, 3),
                          "delivered_true_kw": round(usage_cf - usage, 3)}}

    def send_reading(self, txn: str, reading: dict[str, Any]) -> dict[str, Any]:
        body = self.say("on_status", self.community, txn, {"performance": reading}, ttl_s=beckn.TTL_EVIDENCE_S)
        out = self.send(self.community, beckn.kind("on_status"), body, self.mid(self.community, "on_status", reading["contract_id"], reading["slot_id"]))
        util = self.cfg.get("utility_name", "utility")
        uout = None
        if util:                     # the meter owner gets the reading straight from the home, signed by the home
            meter = {k: v for k, v in reading.items() if k != "truth"}
            ubody = self.say("on_status", util, txn, {"performance": meter}, ttl_s=beckn.TTL_EVIDENCE_S)
            uout = self.send(util, beckn.kind("on_status"), ubody, self.mid(util, "on_status", reading["contract_id"], reading["slot_id"]))
        self._mark_reported(reading["contract_id"], reading["slot_id"], [out, uout])
        return {"sent": out, "summary": f"Slot {reading['slot_id']} of {reading['event_id']}: committed "
                                        f"{reading['committed_kw']} kW, meter {reading['usage_kw']} kW used."}

    def _mark_reported(self, cid: str, sid: int, results: list[Any]) -> None:
        """A slot counts as reported only once both sends went through. A send that raised never gets here (the
        reading is due again on the next tick); the node host sends in the background and hands back futures: the slot
        stays in flight until they finish, and goes back to due if one of them failed."""
        c = self.contracts[cid]
        futs = [r for r in results if isinstance(r, Future)]
        if not futs:
            with self._lock:
                if sid not in c["reported"]:
                    c["reported"].append(sid)
            return
        with self._lock:
            c.setdefault("in_flight", []).append(sid)

        def done(_f: Future) -> None:
            if not all(f.done() for f in futs):
                return
            ok = all(f.exception() is None and f.result() is not False for f in futs)
            with self._lock:
                if sid in c.get("in_flight", []):
                    c["in_flight"].remove(sid)
                    if ok and sid not in c["reported"]:
                        c["reported"].append(sid)
                    elif not ok:
                        self.log("v2_reading_send_failed", contract_id=cid, slot_id=sid)
        for f in futs:
            f.add_done_callback(done)

    # ------------------------------------------------------------------ the real-time design (the gap desk, agents/community/gaps*.py)
    def rt_answer(self, txn: str, ask: dict[str, Any], asked: str | None = None) -> str:
        if getattr(self.adapter, "mode", "fixed") == "rolling":
            cap = self.agent.could_give(ask["start"], ask["end"]) if self.agent is not None else self.adapter.rt_capacity(ask["start"], ask["end"])
        else:
            cap = {"kw": 0.0, "why": "fixed plan: this home cannot change its plan during the day"}
        kw = float(cap.get("kw", 0.0))
        if ask.get("price_usd_per_kwh", 0.0) < float(self.cfg.get("rt_min_price", 0.0)):
            kw, cap["why"] = 0.0, "below the owner's minimum price"
        body = self.say("rt_answer", self.community, txn, {"answer": {"id": ask["id"], "kw": round(kw, 3), "why": cap.get("why")}})
        self.send(self.community, beckn.kind("rt_answer"), body, self.mid(self.community, "rt_answer", ask["id"], asked=asked))
        self.log("rt_answer", call_id=ask["id"], kw=round(kw, 3), why=cap.get("why"))
        return f"can add {kw:.2f} kW for {ask['id']}"

    def rt_take(self, txn: str, d: dict[str, Any]) -> str:
        """Owe the dispatched kW on top of the booking (a release: less). Covering another home's gap in the booked
        event, the kW is owed under the event (its readings count in the event's settlement); for a call, readings for
        its half hours go out under the call's id, so the buyer can pay for them."""
        applied = getattr(self.adapter, "mode", "fixed") == "rolling"
        if applied:
            self.adapter.rt_dispatch({t: float(v) for t, v in d["steps"].items()})
            if self.agent is not None:
                self.agent.called({t: float(v) for t, v in d["steps"].items()})
        halves: dict[str, float] = {}
        for t, v in d["steps"].items():                       # half hours, as the meter readings go
            h = t[:14] + ("00" if t[14:16] < "30" else "30")
            halves[h] = halves.get(h, 0.0) + float(v) / 2.0
        ev_c = next((c for c in self.contracts.values() if d.get("event_id") and c.get("event_id") == d["event_id"]
                     and c.get("status") == "ACCEPTED" and not c.get("rt")), None)
        if ev_c is not None:
            for h, v in halves.items():
                sid = int(self.replay.minutes_between(ev_c["window_start"], h) // 30)
                cm = next((x for x in ev_c["commitments"] if x["id"] == sid), None)
                if sid in ev_c.get("reported", []):
                    continue                                   # its reading went out already
                if cm is None:
                    ev_c["commitments"].append({"id": sid, "start": h, "kw": round(v, 3), "gap": True})
                else:
                    cm["kw"] = round(cm["kw"] + v, 3)
            ev_c["commitments"].sort(key=lambda x: x["id"])
            where = ev_c["id"]
        else:
            cid = f"{d['id']}:{self.name}"
            c = self.contracts.setdefault(cid, {"id": cid, "event_id": d["id"], "home": self.name, "status": "ACCEPTED",
                                                "commitments": [], "reported": [], "rt": True, "transaction_id": txn,
                                                "price_usd_per_kwh": d.get("price_usd_per_kwh"), "steps": {}})
            for t, v in d["steps"].items():
                c["steps"][t] = round(c["steps"].get(t, 0.0) + float(v), 4)
            per: dict[str, float] = {}
            for t, v in c["steps"].items():
                h = t[:14] + ("00" if t[14:16] < "30" else "30")
                per[h] = per.get(h, 0.0) + v / 2.0
            done = {x["start"]: x for x in c["commitments"] if x["id"] in c["reported"]}
            c["commitments"] = [done.get(h) or {"id": k, "start": h, "kw": round(v, 3)}
                                for k, (h, v) in enumerate(sorted(per.items())) if v > 1e-3 or h in done]
            where = cid
        self.log("rt_dispatch", call_id=d["id"], call_kind=d.get("kind"), steps=len(d["steps"]),
                 kw=round(max(d["steps"].values(), default=0.0), 3), release=bool(d.get("release")), applied=applied,
                 owed_under=where)
        return f"dispatch {d['id']}: {len(d['steps'])} steps"

    def rt_report(self) -> None:
        """Tell the community agent when this home's plan says it will fall short of what it owes (an owner's wish, a storm,
        a battery trip), and only when that changes materially: one message, not one every 5 minutes."""
        ctl = getattr(self.adapter, "ctl", None)
        if ctl is None:
            return
        now = self.now_ts()
        i = self.now_idx()
        horizon = self.replay.ts(i + self.REPORT_AHEAD_STEPS)
        if self.adapter.overrides.get("stop"):              # the owner left the event: everything still owed is short
            short = {}
            for k in range(1, self.REPORT_AHEAD_STEPS + 1):
                t = self.replay.ts(i + k)
                if ctl.target_at(t) > 0.1:
                    short[t] = round(ctl.target_at(t), 3)
        elif not ctl.last or not ctl.last.get("ok"):
            return
        else:
            short = {t: v for t, v in (ctl.last.get("short_by_ts") or {}).items()
                     if now < t <= horizon and v >= max(self.REPORT_MIN_KW, 0.1 * ctl.target_at(t))}
        prev = getattr(self, "_rt_reported", {})
        grew = any(v - prev.get(t, 0.0) >= max(self.REPORT_MIN_KW, 0.25 * prev.get(t, 0.0)) for t, v in short.items())
        healed = bool(prev) and not short and any(t > now for t in prev)
        if not grew and not healed:
            return
        why = self._rt_reason()
        urgent = why != "the forecast changed" and why != getattr(self, "_rt_why", None)
        last = getattr(self, "_rt_at", None)
        if not urgent and last and self.replay.minutes_between(last, now) < self.REPORT_EVERY_MIN:
            return
        msg = {"short": {t: round(v, 3) for t, v in short.items()}, "reason": why}
        body = self.say("rt_capacity", self.community, f"cap-{self.name}", msg)
        self.send(self.community, beckn.kind("rt_capacity"), body, self.mid(self.community, "rt_capacity", now, ids.digest(msg)))
        self._rt_reported, self._rt_at, self._rt_why = short, now, why
        self.log("rt_capacity", short_kw=round(max(short.values(), default=0.0), 3), steps=len(short), reason=why)

    def _rt_reason(self) -> str:
        ov = self.adapter.overrides or {}
        if ov.get("stop"):
            return "the owner left the event"
        if ov.get("ev_now"):
            return "the owner needs the car now"
        if self.adapter.P <= 0 < self.adapter.E:
            return "its battery tripped"
        said = getattr(getattr(self, "agent", None), "short_reason", None)    # what its agent reported stands until the sale ends
        if said:
            return said
        if ov.get("comfort_limit") and getattr(self.adapter, "levers", None) is None:     # a person's word lives here. "comfort" is the slot the plan reads, and the agent writes it too, with levers open and in a building's pre-cool with them closed: read from there, a gap would blame an owner who changed nothing
            return "the owner changed the comfort limit"
        return "the forecast changed"

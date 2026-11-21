"""A call's settlement and the desk's check of each step: the buyer's payment against the meters, the premiums, and the gaps the step's reports show."""
from __future__ import annotations

from typing import Any
from murmur.protocol import envelope as beckn
from murmur.protocol import ids
from murmur.settlement import rules as st
from murmur.agents.community.gaps_rules import MIN_GAP_SHARE, QUIET_CUSHION, real, steps_between
from murmur.settlement import market_checks


class GapSettle:
    """A call's settlement and the desk's check of each step: the buyer's payment against the meters, the premiums, and the gaps the step's reports show."""

    def settlement_in(self, sender: str, s: dict[str, Any]) -> str:
        """A buyer's settlement of a call, at its door. What can't be paid on is refused, the call keeps why (settlement_refused) and nothing else about it changes: a settlement that
        can be read is taken when it comes."""
        rec = self.calls[s["call_id"]]
        if not getattr(self.m, "pooled", False):
            return self.settle(s)
        why = market_checks.call_settlement_problem(s, rec, sender, float(rec["kw"]) * 0.25 * len(steps_between(rec["start"], rec["end"])))
        try:
            out = None if why else self.settle(s)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
            out, why = None, f"{type(exc).__name__}: {exc}"[:160]
        if why:
            rec["settlement_refused"] = why
            self.m.log("rt_settlement_refused", call_id=rec["id"], buyer=sender, why=why)
            return beckn.Refused(f"settlement refused: {why}")
        rec.pop("settlement_refused", None)
        return out

    def _checked_full(self, rec: dict[str, Any], s: dict[str, Any], word: float | None, bill: float, buildings: set[str]) -> float:
        """A call's full price, as MarketSettle._checked_full has a sale's: its kWh at the call's price, worked out here. The buyer's word stands when it says the same. Its delivered_kwh has 3 places."""
        price = real(rec.get("price"))
        if price is None:
            return bill if word is None else word
        own = round(float(s.get("delivered_kwh") or 0.0) * price, 4)
        room = 0.01 + 0.0006 * price
        right = word is not None and abs(word - own) <= room
        wrong = [] if right or (word is None and own <= room) else [f"its full price is ${word:,.2f}, and its kWh come to ${own:,.2f}" if word is not None else f"it gave no full price, and its kWh come to ${own:,.2f}"]
        full = word if right else own
        top = st.call_bill(full, s.get("by_home_kwh") or {}, s.get("by_home_batt_kwh") or {}, buildings)
        if abs(bill - top) > room:
            wrong.append(f"its bill is ${bill:,.2f}, and its kWh come to ${top:,.2f}")
        rec.pop("differs", None)
        if wrong:
            rec["differs"] = "; ".join(wrong)
            self.m.log("rt_buyer_word_differs", call_id=rec["id"], why=rec["differs"])
        return full

    def settle(self, s: dict[str, Any]) -> str:
        """Pay each node the call's price on the extra it measured: on the pool times its class's share, with what's left of the bill kept (rules.call_bill sets it to the
        book's part); with one buyer pro rata to the kWh (rules.split)."""
        rec = self.calls[s["call_id"]]
        again = bool(rec.get("settled")) and bool(s.get("top_up"))
        if rec.get("settled") and (not again or int(s["top_up"]) <= int(rec["settled"].get("top_up") or 0)):
            return f"call {rec['id']} already paid"       # delivered again, or an older top-up after a newer one
        if getattr(self.m, "pooled", False):              # the price book's shares, as in the booking
            bill = real(s.get("paid_usd", 0.0))
            word = real(s.get("full_price_usd", bill))
            if bill is None or word is None or bill < 0 or word < 0:
                raise ValueError("a call's settlement with no real sum")      # as junk kWh: it isn't taken for one that was paid
            buildings = {h for ev in self.m.events.values() for h, o in ev["offers"].items() if o.get("node") == "building"}
            full = self._checked_full(rec, s, word if "full_price_usd" in s else None, bill, buildings)
            sp = st.call_shares(full, s.get("by_home_kwh") or {}, s.get("by_home_batt_kwh") or {}, buildings, bill)
        else:
            sp = st.split(float(s.get("paid_usd", 0.0)), {h: float(v) for h, v in (s.get("by_home_kwh") or {}).items()}, self.m.fee)
        missing = self.lacking(rec, s.get("read"))
        rec["settled"] = s                                  # only now: a settlement that can't be read isn't taken for one that was paid
        items = []
        paid0, round_no = rec.setdefault("paid_by_home", {}), rec.get("top_ups", 0) + 1
        for h, usd in sp["per_home"].items():
            if h not in rec["alloc"]:                        # the buyer's list came unchecked (its confirm was lost): the desk pays only those it dispatched
                self.m.log("rt_pay_refused", call_id=rec["id"], home=h, usd=usd)
                continue
            pay = round(usd - paid0.get(h, 0.0), 4) if again else usd
            if again and pay < 0.005:                        # a top-up adds what the new share is owed, and takes nothing back
                continue
            paid0[h] = round(paid0.get(h, 0.0) + pay, 4)
            msg = {"settlement": {"event_id": rec["id"], "payment": pay, "currency": s.get("currency", "USD"),
                                  "delivered_kwh": round(float(s["by_home_kwh"].get(h, 0.0)), 3), "kind": rec["kind"],
                                  "rule": sp["rule"], **({"top_up": round_no} if again else {})}}
            items.append((h, "on_status", self.m._msg("on_status", h, rec["id"], msg, ttl_s=beckn.TTL_EVIDENCE_S),
                          self._mid(h, "on_status", rec["id"], "pay", round_no if again else 0)))
        kept = round(float(s.get("paid_usd") or 0.0) - sum(paid0.values()), 4)    # what is left of the bill once the dispatched nodes are paid
        rec["result"] = {"paid_usd": s.get("paid_usd"), "delivered_kwh": s.get("delivered_kwh"), "homes_paid": len(paid0), "fee_usd": kept}
        self.m.log("rt_paid", call_id=rec["id"], usd=s.get("paid_usd"), delivered_kwh=s.get("delivered_kwh"), homes=len(items), top_up=again)
        rec["lacking"] = missing
        self.m._broadcast(items)                            # last, as in the sale: worked out first, then paid
        if rec["lacking"] and not again:
            self.m.log("rt_readings_missing", call_id=rec["id"], nodes=len(rec["lacking"]), first=sorted(rec["lacking"])[:8])
        if again:
            rec["top_ups"] = round_no
            return f"call {rec['id']}: top-up to {len(items)} homes"
        return f"call {rec['id']}: {s.get('paid_usd')} USD to {len(items)} homes"

    def lacking(self, rec: dict[str, Any], read: dict[str, list[str]] | None) -> dict[str, list[str]]:
        """The half hours a dispatched node owed this call that its buyer has no reading for. A call pays on readings too, and a node with nothing
        missing from the sale, or none in it, is never asked by the sale's own chase."""
        if read is None or rec["kind"] == "gap":
            return {}
        end, out = rec.get("end_early") or rec["end"], {}
        for h, steps in rec["alloc"].items():
            halves: dict[str, float] = {}
            for t, kw in steps.items():
                if t < end:
                    k = t[:14] + ("00" if t[14:16] < "30" else "30")
                    halves[k] = halves.get(k, 0.0) + kw / 2.0
            miss = sorted(k for k, v in halves.items() if v > 1e-3 and k not in (read.get(h) or ()))
            if miss:
                out[h] = miss
        return out

    def premiums(self, ev: dict[str, Any], sp: dict[str, Any], delivered: dict[str, float], committed_kwh) -> None:
        """A gap's helper was asked at a rising price, so it's paid it. The event pays the slot's price. The step up on the kWh it delivered
        beyond its booking comes out of the kept part of the bill, and never takes more than that part. The buyer's bill doesn't move, so a day with a premium keeps that much less
        than the book's part of the bill. On the pool only."""
        if not getattr(self.m, "pooled", False):
            return
        book, add, left = st.price_book()["x"], {}, {}
        for g in self.calls.values():
            if g["kind"] != "gap" or (g.get("parent") or {}).get("id") != ev["need"]["event_id"]:
                continue
            base = float(g.get("base_price") or 0.0)
            for h, steps in g["alloc"].items():
                beyond = left.setdefault(h, st.clamp0(delivered.get(h, 0.0) - committed_kwh(h)))
                kwh = min(sum(steps.values()) * 0.25, beyond)
                left[h] = beyond - kwh                      # a kWh beyond the booking earns the step up once, in the order the gaps came
                up = float((g.get("asked_price") or {}).get(h, base)) / base - 1.0 if base > 0 else 0.0
                if kwh > 0 and up > 0:
                    x = float(book[st.node_class(h, (ev["offers"].get(h) or {}).get("node") == "building")])
                    add[h] = add.get(h, 0.0) + kwh * float(sp.get("usd_per_kwh") or 0.0) * x * up
        if not add:
            return
        k = min(1.0, float(sp.get("fee") or 0.0) / sum(add.values()))
        sp["premium_usd"] = {h: round(v * k, 4) for h, v in add.items()}
        for h, v in sp["premium_usd"].items():
            sp["per_home"][h] = round(sp["per_home"].get(h, 0.0) + v, 4)
        sp["fee"] = round(float(sp["fee"]) - sum(sp["premium_usd"].values()), 4)
        sp["pool"] = round(float(sp["pool"]) + sum(sp["premium_usd"].values()), 4)
        self.m.log("rt_gap_premiums", event_id=ev["need"]["event_id"], homes=len(add), usd=round(sum(sp["premium_usd"].values()), 2))

    # ------------------------------------------------------------------ the community's total, every 5 minutes
    def _cushion(self, ts: str) -> tuple[float, dict[str, Any] | None]:
        """kW the booked event's homes committed beyond what was sold at ts (the margin), and that event."""
        for ev in self.m.events.values():
            n = ev["need"]
            if not (n["window_start"] <= ts < n["window_end"]) or not ev.get("finalized"):
                continue
            half = ts[:14] + ("00" if ts[14:16] < "30" else "30")
            sid = next((s["id"] for s in n["slots"] if s["start"] == half), None)
            if sid is None:
                return 0.0, ev
            committed = sum(next((x["kw"] for x in c["contract"]["commitments"] if x["id"] == sid), 0.0)
                            for c in ev["commitments"].values() if c["status"] == "ACCEPTED")
            sold = float((ev.get("capacity_offered_final") or {}).get(sid, 0.0))
            return max(0.0, committed - sold) + self._surplus(ev, sid), ev
        return 0.0, None

    @staticmethod
    def _measured(ev: dict[str, Any], before: int) -> tuple[float, float] | None:
        """(measured, sold) kW in the latest half hour before slot `before` that the meters have read (80 % of the
        event's homes), in the buyer's own measure (baseline minus use); None before the first one is read."""
        bases, reads = ev.get("baselines") or {}, ev.get("readings") or {}
        meters = ev.get("final_meters") or []
        for s in sorted((x for x in ev["need"]["slots"] if x["id"] < before), key=lambda x: -x["id"]):
            sid = s["id"]
            got = [h for h in meters if sid in (reads.get(h) or {}) or str(sid) in (reads.get(h) or {})]
            if not meters or len(got) < 0.8 * len(meters):
                continue
            measured = 0.0
            for h in got:
                r = reads[h].get(sid) or reads[h].get(str(sid)) or {}
                b = ((bases.get(h) or {}).get(str(sid)) or {}).get("BASELINE")
                if b is not None and r.get("usage_kw") is not None:
                    measured += max(0.0, float(b) - float(r["usage_kw"]))
            return measured, float((ev.get("capacity_offered_final") or {}).get(sid, 0.0))
        return None

    @staticmethod
    def _surplus(ev: dict[str, Any], before: int) -> float:
        """Half of what the meters showed beyond what was sold in the latest half hour already read (the buyer's own
        measure: baseline minus use, as it pays): when the community is running over its booking, a home's forecast
        of a shortfall is not worth moving power for."""
        bases, reads = ev.get("baselines") or {}, ev.get("readings") or {}
        meters = ev.get("final_meters") or []
        for s in sorted((x for x in ev["need"]["slots"] if x["id"] < before), key=lambda x: -x["id"]):
            sid = s["id"]
            got = [h for h in meters if sid in (reads.get(h) or {}) or str(sid) in (reads.get(h) or {})]
            if not meters or len(got) < 0.8 * len(meters):
                continue                                  # not read yet (readings come after each half hour)
            measured = 0.0
            for h in got:
                r = reads[h].get(sid) or reads[h].get(str(sid)) or {}
                b = ((bases.get(h) or {}).get(str(sid)) or {}).get("BASELINE")
                if b is not None and r.get("usage_kw") is not None:
                    measured += max(0.0, float(b) - float(r["usage_kw"]))
            sold = float((ev.get("capacity_offered_final") or {}).get(sid, 0.0))
            return max(0.0, measured - sold) * 0.5
        return 0.0

    def _sold(self, ts: str) -> float:
        """kW sold at this step."""
        for ev in self.m.events.values():
            n = ev["need"]
            if n["window_start"] <= ts < n["window_end"]:
                half = ts[:14] + ("00" if ts[14:16] < "30" else "30")
                sid = next((s["id"] for s in n["slots"] if s["start"] == half), None)
                return float((ev.get("capacity_offered_final") or {}).get(sid, 0.0))
        return 0.0

    def _covered(self, ts: str) -> float:
        return sum(v.get(ts, 0.0) for g in self.calls.values() if g["kind"] == "gap" for v in g["alloc"].values())

    def check(self) -> dict[str, float]:
        """The community's shortfall beyond its margin: the homes' reported shortfalls, less what the margin already
        covers (homes were asked for more than was sold) and less what other homes were dispatched to cover. Only
        that is moved, in one round for the whole community."""
        now = self.m.now()
        self.dirty, self.checked_at = False, now
        steps = sorted({t for r in self.reports.values() for t in r if t > now})
        need: dict[str, float] = {}
        drift = {h for h, why in self.reasons.items() if why == "the forecast changed"}
        for t in steps:
            _, ev0 = self._cushion(t)
            m = None
            if ev0 is not None:
                half = t[:14] + ("00" if t[14:16] < "30" else "30")
                sid = next((x["id"] for x in ev0["need"]["slots"] if x["start"] == half), None)
                m = self._measured(ev0, sid) if sid is not None else None
            tight = m is not None and m[0] < 1.1 * m[1]       # the meters say the community is near what it sold
            if self._quiet() and m is None:
                tight = True                                  # no meters on the desk in the window: a report beyond limits counts
            total = sum(r.get(t, 0.0) for h, r in self.reports.items() if h not in drift or tight)
            cushion, ev = self._cushion(t)
            if self._quiet():
                cushion *= QUIET_CUSHION                      # shortfalls under each node's limit don't reach the desk, and they use the margin too
            if ev is None and not any(c["kind"] != "gap" and c["start"] <= t < c["end"] for c in self.calls.values()):
                continue                                # owed nowhere the desk sells (a home's own plan)
            left = total - cushion - self._covered(t)
            floor = max(0.5, MIN_GAP_SHARE * self._sold(t)) if self._quiet() else 0.5
            if left > floor:
                need[t] = round(left, 3)
            elif total > 0:
                self.absorbed[t] = round(min(total, cushion), 3)
        if not need:
            if steps:
                self.m.log("rt_gap_absorbed", homes=sum(1 for r in self.reports.values() if any(t > now for t in r)),
                           short_kw=round(max(sum(r.get(t, 0.0) for r in self.reports.values()) for t in steps), 2),
                           why="within the margin and what other homes already cover")
            return {}
        who = sorted((h for h, r in self.reports.items() if any(t in need for t in r)),
                     key=lambda h: -max(self.reports[h].values(), default=0.0))
        ts = sorted(need)
        gid = f"gap-{ts[0].replace(' ', 'T')}-{ids.digest(self.play(), len(self.calls))[:6]}"      # the play and the desk's own count: a restart that finds the same gap names it the same
        reporters = {h for h, r in self.reports.items() if any(t > now for t in r)}
        parent, helpers = self._parent(ts[0], who[0] if who else "")
        helpers = [h for h in helpers if h not in reporters]
        rec = {"id": gid, "kind": "gap", "start": ts[0], "end": beckn.add_minutes(ts[-1], 15), "kw": max(need.values()),
               "price": self._gap_price(ts[0]), "base_price": self._gap_price(ts[0]),
               "why": "; ".join(sorted({self.reasons.get(h, "") for h in who if self.reasons.get(h)}))[:160],
               "from": who[0] if who else "", "homes_short": who, "answers": {}, "alloc": {}, "round": 0,
               "phase": "asking", "received_at": now, "readings": {}, "short_by_ts": need, "parent": parent}
        self.calls[gid] = rec
        self.m.log("rt_gap", gap_id=gid, home=rec["from"], homes=len(who), kw=round(rec["kw"], 2), start=rec["start"],
                   end=rec["end"], reason=rec["why"], parent=(parent or {}).get("id"))
        if not helpers:
            rec.update({"phase": "dispatched", "confirmed_kw": 0.0, "short_kw": round(rec["kw"], 3), "homes": 0})
            self._warn(rec)
        else:
            self._ask(rec, helpers)
        return need

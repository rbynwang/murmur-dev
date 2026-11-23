"""Gap filling: a buyer's call or a member's reported gap, sized, offered to the members with room, allocated on their answers and dispatched."""
from __future__ import annotations

import time
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.agents.community.gaps_rules import ASK_COVER, ASK_WAVE, MARGIN, PRICE_LADDER, WARN_AGAIN_SHARE, real, steps_between


class GapCalls:
    """Gap filling: a buyer's call or a member's reported gap, sized, offered to the members with room, allocated on their answers and dispatched."""

    def _room(self, h: str, rec: dict[str, Any]) -> float | None:
        """kW this member has free through the request, from its offer and what it owes: known without a message. None: a step
        outside any sale, where nothing is on file."""
        steps = sorted(rec["short_by_ts"]) if rec["kind"] == "gap" else steps_between(rec["start"], rec["end"])
        room = None
        for t in steps:
            half = t[:14] + ("00" if t[14:16] < "30" else "30")
            ev = next((e for e in self.m.events.values() if e["need"]["window_start"] <= t < e["need"]["window_end"]), None)
            sid = next((s["id"] for s in ev["need"]["slots"] if s["start"] == half), None) if ev else None
            if sid is None:
                return None
            x = next((x for x in (ev["offers"].get(h) or {}).get("slots", []) if x["id"] == sid), {})
            cm = ev["commitments"].get(h) or {}
            owed = next((c["kw"] for c in (cm.get("contract") or {}).get("commitments", []) if c["id"] == sid), 0.0) \
                if cm.get("status") == "ACCEPTED" else 0.0
            owed += sum(g["alloc"].get(h, {}).get(t, 0.0) for g in self.calls.values() if g is not rec)
            free = max(0.0, min(float(x.get("kw_offered") or 0.0), getattr(self.m, "rated", {}).get(h, float("inf"))) - owed)
            room = free if room is None else min(room, free)
        return room or 0.0

    def _owed(self, h: str, t: str) -> float:
        """kW this member owes at a step: its booking and what the desk dispatched on top."""
        half = t[:14] + ("00" if t[14:16] < "30" else "30")
        kw = sum(g["alloc"].get(h, {}).get(t, 0.0) for g in self.calls.values())
        for ev in self.m.events.values():
            cm = ev["commitments"].get(h) or {}
            if ev["need"]["window_start"] <= t < ev["need"]["window_end"] and cm.get("status") == "ACCEPTED":
                sid = next((s["id"] for s in ev["need"]["slots"] if s["start"] == half), None)
                kw += next((c["kw"] for c in cm["contract"]["commitments"] if c["id"] == sid), 0.0)
        return kw

    def _checked_short(self, h: str, short: Any) -> dict[str, float]:
        """A report counts for what this member owes and no more: a bigger claim would move power that nobody is short of."""
        out = {}
        for ts, kw in (short.items() if isinstance(short, dict) else ()):
            v, owed = real(kw), self._owed(h, str(ts))
            if v is not None and v > 0.0 and owed > 0.0:
                out[ts] = min(v, owed)
        return out

    def _call_problem(self, c: dict[str, Any]) -> str | None:
        """Why the desk can't take this call, or None."""
        kw, price = real(c.get("kw")), real(c.get("price_usd_per_kwh"))
        if kw is None or kw <= 0 or price is None or price <= 0:
            return "its kW and price must be real numbers above zero"
        if c.get("kind") == "gap":
            return "a buyer can't open a gap"
        try:
            if beckn.add_minutes(c["start"], 0) >= beckn.add_minutes(c["end"], 0):
                return "it ends before it starts"
        except (KeyError, TypeError, ValueError):
            return "its times can't be read"
        over = next((r for r in self.calls.values() if r["kind"] != "gap" and c["start"] < (r.get("end_early") or r["end"]) and r["start"] < c["end"]), None)
        if over:                                        # both would be told the same room is free, and each would pay on the same meters
            return f"it overlaps call {over['id']}"
        return None

    def _short_list(self, rec: dict[str, Any], homes: list[str]) -> list[str]:
        """Who to ask. Everyone, except on the quiet path: there a buyer's call goes by size, a wave at a time, and a gap goes to the members with room on file."""
        if not self._quiet():
            return homes
        if rec["kind"] != "gap":
            return self._wave(rec, self._ranked(homes))
        now = self.m.now()
        homes = [h for h in homes if self.no_room.get(h, "") <= now]
        rooms = {h: self._room(h, rec) for h in homes}
        if any(v is None for v in rooms.values()):
            return homes                                # no offers on file for these steps: nothing to choose by
        want = float(rec["kw"]) * ASK_COVER
        out, got = [], 0.0
        for h in sorted(rooms, key=lambda x: (-rooms[x], x)):
            if rooms[h] < 0.05 or got >= want:
                break
            out.append(h)
            got += rooms[h]
        if got < want and getattr(self.m, "fill", False):  # room on file is the offer. A sale that fills to the order leaves little of it, and what a node can do now only its answer says
            out += self._wave(rec, self._ranked([h for h in rooms if h not in out]))
        return out

    def _size(self, h: str) -> float:
        """What this member's offers on file say it holds, whatever it chose to sell: its biggest offer, or its battery, cooling and lighting before anyone's share. A node that
        cut its offer or sat the sale out is as big as it was. It only says who to ask first: a few buildings give most of what the answers offer, and among homes no figure on file does much better."""
        out = 0.0
        for e in self.m.events.values():
            o = e["offers"].get(h) or {}
            held = sum(real(o[k].get(f)) or 0.0 for k, f in (("battery", "kw"), ("air_conditioning", "raw_kw"), ("lighting", "raw_kw")) if isinstance(o.get(k), dict))
            out = max([out, held] + [float(x.get("kw_offered") or 0.0) for x in o.get("slots", [])])
        return out

    def _ranked(self, homes: list[str]) -> list[str]:
        """Who to ask first, known without a message: the biggest first. A member short of its own booking, or that said it had nothing in the last half hour, counts for a tenth:
        a shorter window can change its answer, so it isn't left out, and a building stays above the homes."""
        now = self.m.now()
        short = {h for h, r in self.reports.items() if any(t > now for t in r)}
        return sorted(homes, key=lambda h: (-self._size(h) * (0.1 if h in short or self.no_room.get(h, "") > now else 1.0), h))

    def _wave(self, rec: dict[str, Any], homes: list[str]) -> list[str]:
        """The next part of the list. The rest waits in the record until the answers in hand fall short."""
        n = ASK_WAVE * 2 ** rec.get("waves", 0)
        rec["waves"], rec["queue"] = rec.get("waves", 0) + 1, homes[n:]
        return homes[:n]

    def _ask(self, rec: dict[str, Any], homes: list[str]) -> None:
        homes = self._short_list(rec, homes)
        if not homes and self._quiet():                 # nobody has room: no point in asking
            self.allocate(rec)
            return
        msg = {"ask": {"id": rec["id"], "start": rec["start"], "end": rec["end"], "price_usd_per_kwh": rec["price"],
                       "kind": rec["kind"]}}
        items = [self._item(h, "rt_ask", rec["id"], msg, rec.get("round", 0), rec.get("waves", 0)) for h in homes]      # a second round or wave may ask a member again
        self.m._broadcast(items)
        rec["asked"] = sorted(set(rec.get("asked", [])) | set(homes))     # whose answers this round waits for: a call's next wave adds to them, a gap's next round begins its own (_raise)
        rec["asked_at"] = self.m.now()
        rec["asked_wall"] = time.time()

    def _gap_price(self, ts: str) -> float:
        """A gap is paid what the slot earns: the booked event's price there, or an open call's."""
        for ev in self.m.events.values():
            n = ev["need"]
            if n["window_start"] <= ts < n["window_end"]:
                return float(n["slots"][0]["price"])
        for rec in self.calls.values():
            if rec["kind"] != "gap" and rec["start"] <= ts < rec["end"]:
                return rec["price"]
        return 0.0

    # ------------------------------------------------------------------ allocation
    def _covered_by_answers(self, rec: dict[str, Any]) -> bool:
        """Live: the answers in hand already cover the call and its margin (or the gap), so the desk dispatches now
        instead of waiting for the last homes (over the bus the last of 100 answers can come 30 s after the first, three
        15-minute steps at the demo's pace). The offline simulation delivers every answer at once and
        keeps waiting for all of them, so its results do not change. With the clock waiting for the agents (cfg
        clock_waits) the desk waits for every answer too, as offline: a held step costs no sim time, and otherwise the
        answer that happened to come first through Town would decide who covers a gap."""
        if self.m.cfg.get("sync_broadcast") or self.m.cfg.get("clock_waits"):
            return False
        want = rec["kw"] * (1.0 + (MARGIN if rec["kind"] != "gap" else 0.0))
        return sum(a["kw"] for a in rec["answers"].values() if a["kw"] >= 0.05) >= want - 1e-9

    def allocate(self, rec: dict[str, Any]) -> None:
        """Fill the call (plus the margin) from the biggest answers first, evenly over its steps; tell each home what
        it owes on top, tell the buyer what is confirmed. A gap: the same, for the steps it was short. A call still short
        goes on to its next wave, and what that wave brings is dispatched on top of this."""
        call = rec["kind"] != "gap"
        over = 1.0 + (MARGIN if call else 0.0)
        steps = steps_between(rec["start"], rec.get("end_early") or rec["end"])
        if not call:                                    # only the steps the home said it would miss, at its size
            steps = sorted(rec["short_by_ts"])
        elif self._quiet():                             # a later wave comes when the call may be running: nobody owes a step that's gone
            steps = [t for t in steps if t >= self.m.now()]
        left, alloc = rec["kw"] * over - rec.get("dispatched_kw", 0.0), {}
        for h, a in sorted(rec["answers"].items(), key=lambda x: (-x[1]["kw"], x[0])):
            if left <= 1e-3 or not steps:
                break
            kw = min(a["kw"], left)
            if kw >= 0.05 and not (call and h in rec["alloc"]):     # a wave's answers only: Town can bring an answer twice, and a node dispatched twice would owe it twice
                alloc[h] = round(kw, 3)
                left -= kw
        parent = rec.get("parent") or {}
        items = []
        for h, kw in alloc.items():
            per = {t: (kw if call else kw * min(1.0, rec["short_by_ts"][t] / rec["kw"])) for t in steps}
            rec["alloc"][h] = {t: round(v, 3) for t, v in per.items() if v > 1e-3}
            rec.setdefault("asked_price", {})[h] = rec["price"]
            did = parent["id"] if parent.get("kind") == "call" else rec["id"]     # covering a call: owed under the call
            if parent.get("kind") == "call":
                self.calls[did]["alloc"].setdefault(h, {})
                for t, v in rec["alloc"][h].items():
                    self.calls[did]["alloc"][h][t] = round(self.calls[did]["alloc"][h].get(t, 0.0) + v, 3)
            items.append(self._item(h, "rt_dispatch", did, {"dispatch": {"id": did, "steps": rec["alloc"][h],
                                                                         "price_usd_per_kwh": rec["price"], "kind": rec["kind"],
                                                                         "start": rec["start"], "end": rec["end"],
                                                                         **({"event_id": parent["id"]} if parent.get("kind") == "event" else {})}},
                                    rec["id"], rec.get("round", 0), rec.get("waves", 0)))     # never by what it says: a node adds up what it's dispatched, and two gaps can ask the same
        rec["dispatched_kw"] = rec.get("dispatched_kw", 0.0) + sum(alloc.values())
        first = "confirmed_kw" not in rec
        confirmed = round(min(rec["kw"], rec["dispatched_kw"] / over), 3)
        rec.update({"phase": "dispatched", "confirmed_kw": confirmed, "short_kw": round(max(0.0, rec["kw"] - confirmed), 3),
                    "allocated_at": self.m.now(), "homes": len(rec["alloc"]) if call else len(alloc)})
        self.m.log("rt_dispatched", call_id=rec["id"], call_kind=rec["kind"], homes=len(alloc), confirmed_kw=confirmed,
                   short_kw=rec["short_kw"], answers=len(rec["answers"]))
        if call and (first or alloc):                   # the buyer hears at once, and again when it changes
            items.append(self._item(rec.get("from") or self.m.utility, "rt_confirm", rec["id"],
                                    {"confirm": {"id": rec["id"], "kw": confirmed, "short_kw": rec["short_kw"], "homes": sorted(rec["alloc"])}}))
        if items:                                       # the dispatches (and the buyer's confirm) in the background
            items += self._who_owes(rec)
            self.m._broadcast(items)
        if not call and rec["short_kw"] > 0.05:
            if rec["round"] + 1 < len(PRICE_LADDER):
                self._raise(rec)                       # the first round did not cover it: once more, at a higher price
            else:
                self._warn(rec)
        elif call and rec["short_kw"] > 0.05 and rec.get("queue") and steps and not rec.get("end_early"):
            rec["phase"] = "asking"
            self._ask(rec, rec["queue"])

    def _who_owes(self, rec: dict[str, Any]) -> list[tuple]:
        """The call's list of who owes what, for its buyer: it pays only those the desk dispatched, and a gap's helper owes under the call too."""
        parent = rec.get("parent") or {}
        call = rec if rec["kind"] != "gap" else self.calls.get(parent.get("id")) if parent.get("kind") == "call" else None
        return [self._item(call.get("from") or self.m.utility, "rt_confirm", call["id"], {"dispatched": {"id": call["id"], "alloc": call["alloc"]}})] if call else []

    def _raise(self, rec: dict[str, Any]) -> None:
        """Offer what is left once more, at the next price on the ladder, to the homes that could cover it and have not
        been dispatched for it yet (a home below its owner's minimum price may now say yes). Nobody left: warn.
        The new round counts its own answers, from the homes it asks: a home asked before and not again owes none, so the round
        is filled when the last of its own has answered, and an answer that comes again from a home already dispatched is not taken twice."""
        rec["round"] += 1
        rec["price"] = round(rec["price"] * PRICE_LADDER[rec["round"]] / PRICE_LADDER[rec["round"] - 1], 4)
        rec["kw"], rec["dispatched_kw"] = rec["short_kw"], 0.0
        rec["short_by_ts"] = {t: v * rec["short_kw"] / max(1e-6, max(rec["short_by_ts"].values())) for t, v in rec["short_by_ts"].items()}
        rec["answers"], rec["asked"], rec["phase"] = {}, [], "asking"
        short_now = {h for h, r in self.reports.items() if any(t > self.m.now() for t in r)}
        others = [h for h in self._parent(rec["start"], rec["from"])[1] if h not in rec["alloc"] and h not in short_now]
        self.m.log("rt_price_up", gap_id=rec["id"], price=rec["price"], kw=round(rec["kw"], 3), asked=len(others))
        if not others:
            rec["phase"] = "dispatched"
            self._warn(rec)
            return
        self._ask(rec, others)

    def _warn(self, rec: dict[str, Any]) -> None:
        """What the community will be short of: the buyer hears it now, not from the meters tomorrow."""
        if self._quiet():                               # a buyer hears a change, not every five minutes
            last = self.warned.get(rec["start"][:13])
            if last is not None and abs(rec["short_kw"] - last) < WARN_AGAIN_SHARE * max(last, 1e-6):
                return
            self.warned[rec["start"][:13]] = rec["short_kw"]
        self.m.log("rt_early_warning", gap_id=rec["id"], short_kw=rec["short_kw"], start=rec["start"], end=rec["end"])
        for b in self._buyers():
            self._send(b, "rt_confirm", rec["id"], {"warning": {"id": rec["id"], "short_kw": rec["short_kw"], "start": rec["start"],
                                                                "end": rec["end"], "why": rec["why"]}})

"""A person's notes at a node: each read once by the note reader, kept as wishes the guard holds until they end, with what they cost a sale already made."""
from __future__ import annotations

from typing import Any
from murmur.node import calls
from murmur.node import tools as T
from murmur.node.grounds import quoted
from murmur.node import modes as arm
from murmur.node.agent_levers import LEAD_MIN, MACHINE_KEY, NO_REASON, held_comfort, write_comfort
from murmur.node import note_words
from murmur.node import note_reader


class AgentNotes:
    """A person's notes at a node: each read once by the note reader, kept as wishes the guard holds until they end, with what they cost a sale already made."""

    def read_note(self, ts: str) -> str | None:
        """New notes: the model says what the owner needs, and code keeps it from here on, until the wish ends (lapse). A note on file goes the same way, once, the first time this node sees it."""
        ov = self.sim.overrides
        said = None
        for n in list(ov.get("note_before") or ()):     # notes a newer one pushed aside before anyone read them, oldest first
            got, read = self.take_note(n.get("note"), n.get("at") or ts, ts)
            if not read and self.note_waiting(quoted(n.get("note"), note_reader.NOTE_MAX), ts):
                continue                            # this one waits for want of a reason. The model is there, so the newer notes are still read
            if not read:
                self.noted = None                   # the model is away: these and the newest wait for the next step
                return said
            q = ov.get("note_before") or []
            if n in q:
                q.remove(n)
            said = said or got
        if ov.get("note") and note_reader.note_key(ov) != self.noted:
            self.noted, read = note_reader.note_key(ov), False      # first: the model's wait lets go of the node, and a market message may look for notes meanwhile
            try:
                said, read = self.take_note(ov["note"], ov.get("note_at") or ts, ts, self.noted)
                if read:
                    self.sim.note_seen = self.noted
            finally:
                if not read:
                    self.noted = None               # the model never read it, so it's read again at the next step, not lost
        for n in self.on_file():
            if quoted(n, note_reader.NOTE_MAX) not in self.filed:
                self.filed.add(quoted(n, note_reader.NOTE_MAX))
                got, read = self.take_note(n, ts, ts)
                said = said or got
                if not read:
                    self.filed.discard(quoted(n, note_reader.NOTE_MAX))
        return said

    def on_file(self) -> list[str]:
        """The owner's or manager's own words on file with the node's offer rule, the last two as an offer's facts read them."""
        wishes = getattr(getattr(self.home, "brain", None), "wishes", None)
        return list(wishes.get().get("notes") or [])[-2:] if wishes is not None else []

    def take_note(self, note: str, at: str, ts: str, key: str | None = None) -> tuple[str | None, bool]:
        """One note, through its own short step. (What changed for a plan to hear, did the model read it.) A note that sets no wish bears on nothing, so it changes nothing.
        key: the door's note, by note_reader.note_key, so a restart knows it was read."""
        if arm.careful_notes() and self.note_waiting(quoted(note, note_reader.NOTE_MAX), ts, key):
            return None, False                      # its record says it waits: nobody is asked at this step
        waiting = [w for w in self.guard.wishes if w.get("why") == note_reader.NO_READING] if arm.careful_notes() else []      # kept while a note couldn't be read
        live = [w for w in self.guard.wishes if (not w.get("until") or w["until"] > ts) and w not in waiting]
        if arm.careful_notes():                     # a small reader on the site: its question carries examples, and no usable reading keeps everything
            r = note_reader.read_note_carefully(self.brain, note, at, "manager" if self.word == "building" else "owner", live)
            self.note_tried(quoted(note, note_reader.NOTE_MAX), r, ts, key)
            if waiting and not r.get("error"):
                self.end(waiting, ts)               # the note is read now, so what was kept in its place goes back
            elif waiting:
                r["wishes"], r["tell"] = [], None   # still no reading: everything is kept already and the person has heard so. The note waits for the next step
        else:
            r = note_reader.read_note(self.brain, note, at, "manager" if self.word == "building" else "owner", live)
        read_as = [w["wish"] for w in r["wishes"]]
        if r.get("no_reason"):     # every node an agent: it wouldn't say why, so the rule's answer stands, and a rule can't read a note
            r = {**r, "wishes": [], "ended": []}
        car = quoted(note, note_reader.NOTE_MAX) == note_reader.CAR_NOW and not r.get("error")      # a person's "car now" isn't free text: its wish holds whatever the model read in it
        if car and note_reader.CAR_WISH not in [w["wish"] for w in r["wishes"]]:
            r = {**r, "wishes": [*r["wishes"], {"wish": note_reader.CAR_WISH, "by": "", "from": at, "until": ""}]}
        self.record({"node": self.name, "tier": self.tier, "ts": ts, "why": "owner's note", "text": quoted(note, note_reader.NOTE_MAX), "shortlist": ["set_owner_wish", "end_owner_wish", "no_wish"] if live else ["set_owner_wish", "no_wish"],
                     "answer": r["wishes"], "said": r["said"], "ms": r["ms"], "model": self.brain.model, "prompt": T.PROMPT_VERSION, "owed_kw": 0.0, "verdicts": [],
                     **({"how": r["how"], "readings": r["readings"]} if r.get("how") else {}), **({"waits": r["waits"]} if r.get("waits") else {}),
                     **({"note_key": key} if key and not r.get("error") else {}), **({"ended": r["ended"]} if r["ended"] else {})})
        new = [w for w in r["wishes"] if not w["until"] or w["until"] > ts]
        for w in new:
            self.wish_notes[w["wish"]] = quoted(note, note_reader.NOTE_MAX)     # the words behind each wish, which a later offer cites
        # the note's receipt. Rules can't read text, so the rule's answer is that nothing changes
        who = "manager" if self.word == "building" else "owner"
        cost = None if r.get("error") else self.note_cost(ts, new)      # a sale already made: what the note takes out of it, against the amount without it
        told = note_words.got_it(new, cost["gives"], cost["would"], note_words.when_of(cost["start"], ts), self.kw_text) if cost else note_words.heard(new) if car else note_words.not_kept(note) if r.get("no_reason") and read_as else None
        told = told or (r.get("tell") if new else None)      # the careful step kept everything because the note couldn't be read: the person hears that, not silence
        if told:
            self.tell(told, "note", ts)
        deferred = "the model did not answer, so the note is read again at the next step"
        if str(r.get("how") or "").startswith(note_reader.KEPT):
            held = "until tonight is over" if new or waiting else "for the night it was written, which is over"
            deferred = f'{r["how"]} {held}' + (f'. {r["waits"]}' if r.get("waits") else ", and the note is read again at the next step")
        self.receipt("note", ts, asked={"note": quoted(note, note_reader.NOTE_MAX), "from": who},
                     rule={"needs": [], "what": "rules can't read a note", **({"kw_per_half_hour": cost["without"]} if cost else {})},
                     chose={"needs": [w["wish"] for w in r["wishes"]], "ended": r["ended"], **({"kw_per_half_hour": cost["with"]} if cost else {}), **({"read_as": read_as} if r.get("no_reason") else {})},
                     reason=NO_REASON if r.get("no_reason") else deferred if r.get("error") else r.get("reason") or "",
                     facts=[{"id": "note", "says": f'The {who} wrote: "{quoted(note, note_reader.NOTE_MAX)}"'}],
                     flags=([NO_REASON] if r.get("no_reason") else []) + ([note_words.FOR_NOTE] if cost else []),
                     by=f"rule: {NO_REASON}" if r.get("no_reason") else "agent" if not r.get("error") else f"deferred: {deferred}", less=bool(cost), told=told)
        gone = [w for w in self.guard.wishes if "all" in r["ended"] or w["wish"] in r["ended"]]
        if gone:
            self.end(gone, ts)                      # first: "use the battery after all, but keep the car" ends one and sets the other
        wishes = [w for w in r["wishes"] if not w["until"] or w["until"] > ts]       # a date already gone is a fact about the past
        if not wishes:
            return (note_words.TAKEN_BACK if gone else None), not r.get("error")
        wishes = self.put_in_force(wishes, ts)
        if not wishes:
            return None, True
        return note_words.SAYS[wishes[0]["wish"]], not r.get("error")      # kept everything for want of a reading: the note itself is read again at the next step

    def note_waiting(self, text: str, ts: str, key: str | None = None) -> bool:
        """A note whose reader answered and gave no reason, on its first reading and on the one after: it waits. It is read again when the next sale opens,
        once for that sale, and not at every step. key: the door's own name for the note. The same words under a new one are a new note, with its own readings."""
        w = self.note_waits.get(text)
        if w and key and w.get("key") and key != w["key"]:
            del self.note_waits[text]
            return False
        if not w or w["tries"] < 2:
            return False
        from murmur.protocol.envelope import add_minutes
        sale = self.sale(ts)
        return not (sale and sale["start"] != w["sale"] and add_minutes(sale["start"], -LEAD_MIN) <= ts < sale["end"])

    def note_tried(self, text: str, r: dict[str, Any], ts: str, key: str | None = None) -> None:
        """Counts the readings that gave no reason. From the second in a row the note waits (note_waiting), and r says so for the record."""
        if r.get("error") != note_reader.NO_REASON:
            self.note_waits.pop(text, None)         # read, or the reader was away: a reader that is away is asked again at every step
            return
        from murmur.protocol.envelope import add_minutes
        w = self.note_waits.setdefault(text, {"tries": 0, "sale": None, "key": key})
        w["tries"] += 1
        if w["tries"] >= 2:
            sale = self.sale(ts)
            w["sale"] = sale["start"] if sale and add_minutes(sale["start"], -LEAD_MIN) <= ts < sale["end"] else None      # the sale whose opening is behind us, if any
            r["waits"] = note_reader.WAITS
            self.ctx.log.add("note_waits", ts=ts, readings=w["tries"], until="the next sale opens")

    def put_in_force(self, wishes: list[dict[str, Any]], ts: str) -> list[dict[str, Any]]:
        """These needs hold from now: the guard has them, what they keep out leaves the sale, and the car goes first if one of them is the car. Those still standing."""
        self.guard.wishes += wishes
        self.lapse(ts)                              # one with no end of its own takes its sale's, and read again after a restart that sale may be over
        wishes = [w for w in wishes if w in self.guard.wishes]
        if not wishes:
            return []
        self.short_reason = calls.SHORT_WORDS["owner_need"]
        blocked = note_reader.blocked_tools(wishes)
        if any(w["wish"] == "keep_car_ready" for w in wishes) and not self.sim.overrides.get("ev_now") and self.word != "building":
            self.sim.overrides["ev_now"] = True                   # the owner's car first. Not by rt_override: that is a person's door, and with every node an agent it would be one more note
            self.sim.car_first = True
        self.calls = [c for c in self.calls if c["tool"] not in blocked]
        if self.sim.levers is not None:
            self.reopen(blocked)
        elif self.ctx.handed_back:                  # the controller runs this sale alone: handed back again, it keeps out what the new wish keeps
            self.ctx.hand_back()
        return wishes

    def kw_text(self, x: float) -> str:
        return f"{x:,.0f}" if self.word == "building" else f"{x:.1f}"

    def note_cost(self, ts: str, wishes: list[dict[str, Any]]) -> dict[str, Any] | None:
        """What a note takes out of a sale this node already committed to, half hour by half hour from now: the committed kW, which is what it gives without the note and what
        a rule would give, since a rule can't read one; and what is left with the note, by the same keep_out that sizes an offer under a wish. None: no such sale, or nothing taken."""
        from murmur.protocol.envelope import add_minutes
        from murmur.node.grounds import keep_out
        rows: list[tuple[str, float, float]] = []
        for c in (getattr(self.home, "contracts", None) or {}).values() if wishes else ():
            offer = (getattr(self.home, "offers", None) or {}).get(c.get("event_id"))
            if c.get("status") != "ACCEPTED" or not offer or str(c.get("window_end") or "") <= ts:
                continue
            kept = {s.get("id"): s for s in keep_out(offer, wishes, c).get("slots") or []}
            had = {s.get("id"): s for s in offer.get("slots") or []}
            for s in c.get("commitments") or []:
                if add_minutes(s["start"], 30) <= ts or s.get("id") not in had or s.get("id") not in kept:
                    continue                        # a half hour already over
                y = float(s["kw"])
                out = max(0.0, float(had[s["id"]].get("kw_offered") or 0.0) - float(kept[s["id"]].get("kw_offered") or 0.0))
                rows.append((s["start"], y, max(0.0, y - out)))
        if not rows or sum(y - x for _, y, x in rows) <= 0.01:
            return None
        n = len(rows)
        return {"start": min(r[0] for r in rows), "without": [round(y, 2) for _, y, _ in rows], "with": [round(x, 2) for _, _, x in rows],
                "would": sum(y for _, y, _ in rows) / n, "gives": sum(x for _, _, x in rows) / n}

    def lapse(self, ts: str) -> list[dict[str, Any]]:
        """Wishes end here and nowhere else. One with its own end keeps it, whatever sales pass. One with none holds through the next sale, and failing a sale by the day after it was read
        it ends then. So "going away tonight" doesn't hold into later commitments, and "until Friday" doesn't end with the first sale."""
        if not self.guard.wishes:
            return []
        kept, ended = [], []
        for w in self.guard.wishes:
            since = w["from"] = w.get("from") or ts                # a wish that carries no date dates from now
            if not w.get("until"):
                w["until"] = self.sale_end_after(since) or (ts if ts[:10] > note_reader.next_day(since) else "")
            (ended if w.get("until") and ts >= w["until"] else kept).append(w)
        if ended:
            self.end(ended, ts)
        return ended

    def end(self, ended: list[dict[str, Any]], ts: str) -> None:
        """These wishes end now, by their date or because a note took them back. What they kept out is the sale's again."""
        self.guard.wishes = kept = [w for w in self.guard.wishes if w not in ended]
        for w in ended:
            self.ctx.log.add("wish_ended", ts=ts, wish=w["wish"], since=w.get("from") or "")
        if self.car_first and not any(w["wish"] == "keep_car_ready" for w in kept):
            self.sim.rt_override("ev_now", False)             # and car_first with it
        if self.ctx.handed_back:
            self.ctx.hand_back()                # what the wish kept out is the controller's again

    def sale_end_after(self, since: str) -> str | None:
        """The end of the first sale still running or to come at this moment, from the contract. Read again after a restart, an old note finds the sale it was for, which has gone."""
        from murmur.protocol.envelope import add_minutes
        owed = sorted(t for t, a in self.sim.plan.items() if t >= since and float(a.get("deliver_kw") or 0.0) > 0)
        if not owed:
            return None
        end = owed[0]
        for t in owed[1:]:
            if t != add_minutes(end, 15):
                break
            end = t
        return add_minutes(end, 15)

    def reopen(self, blocked: set[str]) -> None:
        """Take back what the owner's wish stops: the device leaves the sale at once."""
        lev = self.sim.levers
        if "set_battery" in blocked:
            lev["battery_kw"] = 0.0
        if "limit_ev_charging" in blocked:
            lev["ev"], lev["ev_kw"] = False, None
        if "discharge_car" in blocked:
            lev["v2h_kw"] = 0.0
            if not any(c["tool"] == "limit_ev_charging" for c in self.calls):
                lev["ev"], lev["ev_kw"] = False, None      # the charger it held goes back, unless a pause of its own still runs
        if blocked & {"set_thermostat", "set_room_ac"}:
            write_comfort(self.sim, held_comfort(self.sim))
        held = lev.get("devices", set())            # a building's levers have none of these
        if "set_water_heater" in blocked:
            held.discard("hpwh")
        if "set_pool_pump" in blocked:
            held.discard("pool")
        if "delay_appliance" in blocked:
            held -= set(MACHINE_KEY.values())

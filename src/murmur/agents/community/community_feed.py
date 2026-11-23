"""The community's meter, quarter hour by quarter hour: what it is fed, the report row it sends up for each step, and the members' batteries where it runs them."""
from __future__ import annotations

from collections import Counter
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.agents.community.community_rules import FEED, NO_METER, QUIET, RUNS, STEP_MIN, TIME, line, number, row

MOVE_MAX = 96 * 2              # quarter hours of one move of the clock that each get a row: as many as a home steps one by one (node/simulator.py). A move further on, or back, begins again


def quarters(after: str, until: str) -> list[str]:
    """Every quarter hour after one time up to another, in order."""
    out, t = [], beckn.add_minutes(after, STEP_MIN)
    while t <= until:
        out.append(t)
        t = beckn.add_minutes(t, STEP_MIN)
    return out


class CommunityFeed:
    """The community's meter, quarter hour by quarter hour: what it is fed, the report row it sends up for each step, and the members' batteries where it runs them."""

    # ---- the feed: what its meter, its members' batteries and the market tell it while it runs
    def feed(self, rows: Any, from_above: bool = False) -> dict[str, Any]:
        """Quarter hour by quarter hour. Each row is a time and any of: "meter_kw" (its meter, taking from the grid negative), "expect_kw" (what the meter would read with
        neither the battery's giving nor a sale, which is what the utility's limit is checked on), "battery_kw" (what the members' batteries are to give, as the level above
        asked), "soc_pct" (its state of charge) and "price_usd_kwh". Numbers and nothing else: a row with any other field, a time that isn't one or a number out of
        range is refused, and the whole feed with it, so half a feed is never taken. A meter reading for a quarter hour already reported is put beside that row: what
        was reported stays as it was sent."""
        if not isinstance(rows, list) or not rows:
            raise ValueError("a feed is a list of rows, one for each quarter hour")
        took: list[tuple[str, dict[str, float]]] = []
        for r in rows:
            if not isinstance(r, dict) or set(r) - FEED or len(r) < 2 or not (isinstance(r.get("ts"), str) and TIME.match(r["ts"])):
                raise ValueError("a feed row is a time and any of " + ", ".join(sorted(FEED - {"ts"})) + ", and nothing else")
            vals = {k: v for k, v in r.items() if k != "ts"}
            if not all(number(v) for v in vals.values()):
                raise ValueError("a feed row holds numbers")
            if not 0 <= vals.get("soc_pct", 0) <= 100 or vals.get("price_usd_kwh", 0) < 0:
                raise ValueError("a state of charge is 0 to 100, and a price is not below zero")
            if "battery_kw" in vals and (self.battery is None or abs(vals["battery_kw"]) > self.battery.rating_kw * 1.001):
                raise ValueError("the members' batteries can't be asked for more than their rating, and a community without any can't be asked at all")
            if "battery_kw" in vals and self.aggregator and not from_above:
                raise ValueError("what the members' batteries are asked comes from the community's aggregator, signed, and not through this door")
            if set(vals) & RUNS and not (self.battery is not None and self.battery.run_by_agent):
                raise ValueError("only a community that holds its members' batteries itself is fed what its meter reads with the batteries idle")
            if "store_kwh" in vals and not 0 <= vals["store_kwh"] <= self.battery.energy_kwh * 1.001:
                raise ValueError("the battery's charge is between nothing and what it holds")
            took.append((r["ts"][:16].replace("T", " "), {k: float(v) for k, v in vals.items()}))
        seen: Counter = Counter()
        for ts, vals in took:
            seen.update(vals.keys())
            if "meter_kw" in vals:
                self.meter.add(ts, vals["meter_kw"])
                for sent in self.report:
                    if sent["timestamp"] == ts:
                        sent["meter_p_net_kw"] = round(vals["meter_kw"], 3)
            if "expect_kw" in vals:
                self.meter.expect(ts, vals["expect_kw"])
            if "battery_kw" in vals:
                self.battery_kw[ts] = vals["battery_kw"]
            if "soc_pct" in vals:
                self.soc[ts] = vals["soc_pct"]
            if "price_usd_kwh" in vals:
                self.prices[ts] = vals["price_usd_kwh"]
            if "idle_kw" in vals:
                self.idle[ts] = {k: vals[k] for k in RUNS if k in vals}
        self.log("community_feed", rows=len(took), fields=dict(seen), first=took[0][0], last=took[-1][0])
        return {"rows": len(took), "fields": dict(seen), "first": took[0][0], "last": took[-1][0]}

    def step(self, market: Any, now: str) -> dict[str, Any] | None:
        """The tick (6): one report row for each quarter hour, once, in order. A clock that has moved over several quarter hours in one move leaves none out: each of them
        gets its row. On a real clock the rows of the quarter hours it passed over are written as their meter readings come in, oldest first, and when the clock next
        moves at the latest. The last row written now, or None."""
        q = now[:14] + f"{int(now[14:16]) // STEP_MIN * STEP_MIN:02d}"
        wrote = None
        if q != self.last_step:
            was, play, self.last_step, self.play = self.last_step, self.play, q, getattr(market, "play", None)
            new, due, self.rows_due = [q], self.rows_due, []
            if was is not None and play == self.play and was < q <= beckn.add_minutes(was, STEP_MIN * MOVE_MAX):
                new = quarters(was, q)                       # one move on, in the same play: every quarter hour of it, and what was still due from the move before
                for t in due:                                # those can wait no longer: with their reading or without
                    wrote = self.write_row(market, t)
            if self.report_ended:                            # on a real clock the meter's reading of a quarter hour, and the charge at its end, exist once it has ended:
                new = [] if was is None else [beckn.add_minutes(t, -STEP_MIN) for t in new]      # its row is written then, as ENGIE's participants send theirs
                new, self.rows_due = new[:1], new[1:]        # the step the clock held at was read while it held there. The ones it passed over are only now being read: their rows wait
            for t in new:
                wrote = self.write_row(market, t)
        while self.rows_due and self.read_at(self.rows_due[0]):
            wrote = self.write_row(market, self.rows_due.pop(0))
        return wrote

    def read_at(self, q: str) -> bool:
        """Does the meter have its reading of this quarter hour? Where the agent holds the members' batteries, the reading is its own, once the battery has run."""
        self.run_battery(q)
        return self.meter.at(q) is not None

    def write_row(self, market: Any, q: str) -> dict[str, Any]:
        """One quarter hour's report row. The net power is the meter's, the line says what the community promised for that step, and no member is in it."""
        text = QUIET
        for ev in list(getattr(market, "events", {}).values()):
            n, cap = ev.get("need") or {}, ev.get("capacity_offered")
            if not cap or not str(n.get("window_start") or "") <= q < str(n.get("window_end") or ""):
                continue
            sid = next((s["id"] for s in n.get("slots") or [] if TIME.match(str(s.get("start") or "")[:16]) and str(s["start"])[:16] <= q < beckn.add_minutes(str(s["start"])[:16], 2 * STEP_MIN)), None)
            asked = [a[sid] for a in (ev.get("alloc") or {}).values() if sid in a]
            text = line(len(asked), float(cap.get(sid) or 0.0), max(0.0, sum(asked) - float(cap.get(sid) or 0.0)), self.battery_kw.get(q, 0.0), str(n.get("window_end")))
        if text == QUIET and self.battery_kw.get(q, 0.0) > 0:      # outside a sale the members' batteries may still be asked to give: the line says so
            text = f"{QUIET}; battery gives {self.battery_kw[q]:,.0f} kW"
        self.run_battery(q)
        read = self.meter.at(q)
        soc = self.soc.get(q, self.soc_pct)                                                    # the feed's word for this quarter hour, else what was last read
        price = self.prices[q] if q in self.prices else self.price(q) if self.price else None
        r = row(self.id, q, read, soc, price, text if read is not None or text != QUIET else NO_METER, meter_kw=read, members=list(self.members.rows))
        self.report = (self.report + [r])[-self.keep_rows:]
        if self.aggregator:                                   # and it goes upward once, signed (market.report_up)
            self.outbox = (self.outbox + [r])[-self.keep_out:]
        return r

    def run_battery(self, until: str) -> None:
        """Where the community agent holds the members' batteries itself: every quarter hour up to this one that it was fed and hasn't run yet, in order, none skipped. The
        battery follows what the aggregator asked for that quarter hour (the request it took, cut where the utility's limit needed it), never past its rating, never
        below 10% or above 90% of its charge, and never so that the community sends out more than its connection allows; outside a request it runs its own schedule
        inside the same limits. The arithmetic is a single site's (site.Site), which is the sharing-out's own. What the meter then reads, and the charge, are the
        agent's own: they go into the report row as the meter's reading and the battery's state of charge."""
        b = self.battery
        if b is None or not b.run_by_agent:
            return
        from murmur.agents.site import Site  # here and not at the top: site.py reads this module for the row every participant sends
        for q in sorted(t for t in self.idle if t <= until[:16] and (not self.battery_ran or t > self.battery_ran[-1]["ts"])):
            x = self.idle[q]
            if self.engine is None:
                start = x.get("store_kwh", (self.soc_pct if self.soc_pct is not None else 50.0) / 100 * b.energy_kwh)
                self.engine = Site(self.id, "shared_battery", b.rating_kw, b.energy_kwh, b.out_factor, self.limit_out_kw, store_kwh=start)
            asked = self.battery_kw.get(q, 0.0)
            self.engine.asked_kw[int(q[11:13])] = asked
            r = self.engine.step(q, x["idle_kw"], x.get("recorded_kw", x["idle_kw"]), x.get("own_kwh", 0.0))
            self.meter.add(q, r["sent_out_kw"])
            self.soc[q] = self.soc_pct = 100 * r["store_kwh"] / b.energy_kwh
            self.battery_ran = (self.battery_ran + [{"ts": q, "asked_kw": round(asked, 3), "gave_kw": round(r["battery_kw"], 3), "idle_kw": round(x["idle_kw"], 3), "meter_kw": round(r["sent_out_kw"], 3), "soc_pct": round(self.soc[q], 3)}])[-self.keep_rows:]
        for t in [t for t in self.idle if self.battery_ran and t <= self.battery_ran[-1]["ts"]]:
            del self.idle[t]

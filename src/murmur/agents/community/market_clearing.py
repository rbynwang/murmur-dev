"""The day-ahead clearing: the call for offers, a second round when the pool is short, the book per half hour, and the promise upward that the members' offers can keep."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.replay import Replay
from murmur.agents.community.market_rules import DEPOSIT_SHARE, MAX_CONFIDENCE, PARTS, POOL_HEADROOM, ROUND2_BEFORE_MIN, ROUND2_MIN_SHARE, SLOT_H, _rebound_at, firm_part


class MarketClearing:
    """The day-ahead clearing: the call for offers, a second round when the pool is short, the book per half hour, and the promise upward that the members' offers can keep."""

    # ------------------------------------------------------------------ community side
    def call_homes(self, ev: dict[str, Any]) -> None:
        n, called = ev["need"], self._pool_need(ev)
        items = [(h, "discover", self._msg("discover", h, ev["ctxn"], {"intent": {"need": called}}),
                  self.mid(h, "discover", n["event_id"], "call", 0)) for h in self.roster]
        self._broadcast(items)
        self.log("v2_call_for_offers", event_id=n["event_id"], homes=len(items))
        if self.cfg.get("community_forecast", self.pooled):
            if self.cfg.get("sync_broadcast"):
                self.outlook(ev)
            else:                                         # seconds of work: not under the market lock on a live community agent
                self.outlook_pool.submit(self.outlook, ev)

    def _second_round_over(self, ev: dict[str, Any], now: str, lead: float) -> bool:
        """True when the clearing may look at the offers. It waits for the second round, if one is needed, and never past its own deadline. On a live clock the round can open with offers
        still coming (little more than half of them in), and thinking nodes answer last, because they wait for the model. So while the deadline holds, whoever comes in after is asked too."""
        last = beckn.add_minutes(ev["need"]["commit_by"], lead)
        r2 = ev.get("round2")
        if r2 is None:
            if len(ev["offers"]) < len(self.roster) and now < beckn.add_minutes(last, -ROUND2_BEFORE_MIN):
                return False                               # offers are still coming
            r2 = self.ask_more(ev, now)
        elif now < last:
            r2 = self.ask_more(ev, now)
        return len(set(r2["answered"])) >= len(r2["asked"]) or now >= last

    def _pool_short(self, ev: dict[str, Any]) -> dict[int, float]:
        """kW per half hour by which the offers fall short of the order, its margin and the headroom."""
        out = {}
        for s in ev["need"]["slots"]:
            sid = s["id"]
            pool = sum(min(float(self._slot_of(o, sid).get("kw_offered") or 0.0), self.rated.get(h, float("inf"))) for h, o in ev["offers"].items())
            out[sid] = round(max(0.0, self._asked(ev, s) * (1 + self.margin_of(ev)) / POOL_HEADROOM - pool), 2)
        return out

    def ask_more(self, ev: dict[str, Any], now: str) -> dict[str, Any]:
        """The second round. If the pool is short, a member that held back part of what its code calls safe hears how much is missing and may raise its offer. Each member is asked
        once per sale, whenever its offer came in. A member with no offer in is ask_silent's."""
        n = ev["need"]
        short = self._pool_short(ev)
        first = "round2" not in ev
        r2 = ev.setdefault("round2", {"at": now, "short_kw": short, "asked": [], "answered": []})
        asked = []
        if max(short.values(), default=0.0) >= ROUND2_MIN_SHARE * max(self._asked(ev, s) for s in n["slots"]):
            asked = sorted(h for h, o in ev["offers"].items() if h not in r2["asked"] and max((float(v) for v in (o.get("held_back_kw") or {}).values()), default=0.0) >= 0.05)
        r2["short_kw"] = short
        r2["asked"] = r2["asked"] + asked
        if asked:
            more = {"short_kw": {str(k): v for k, v in short.items()}, "ordered_kw": {str(s["id"]): self._asked(ev, s) for s in n["slots"]}, "margin": self.margin_of(ev)}
            self._broadcast([(h, "discover", self._msg("discover", h, ev["ctxn"], {"intent": {"need": n, "more": more}}), self.mid(h, "discover", n["event_id"], "more")) for h in asked])
        if first or asked:
            self.log("v2_second_round", event_id=n["event_id"], asked=len(asked), short_kw=max(short.values(), default=0.0))
        return r2

    # ------------------------------------------------------------------ the book: firm first, then what deposits reserved
    @staticmethod
    def _slot_of(o: dict[str, Any], sid: int) -> dict[str, Any]:
        return next((x for x in o["slots"] if x["id"] == sid), {})

    @staticmethod
    def _order_kw(od: dict[str, Any], sid: int) -> float:
        return float(next((s["kw_requested"] for s in od["need"]["slots"] if s["id"] == sid), 0.0))

    @staticmethod
    def deposit_rate(need: dict[str, Any]) -> float:
        """USD a deposit pays to hold one kW through the window."""
        s = need["slots"]
        return DEPOSIT_SHARE * float(s[0]["price"]) * len(s) * SLOT_H

    def _worth(self, h: str, o: dict[str, Any]) -> float:
        """What one kW of this offer counts for in the book. Filling to the order: its face value, less what its sensors or an advisory control take off. Not the 0.9 every offer
        carries, and not its reputation: lost readings can cut that to 0.7 and take a thousand kW off a sale the nodes then deliver. Reputation stays in the
        node's record and its agent's facts."""
        c = self._confidence(o)
        return min(1.0, c / (0.9 * max(self.reputation.get(h, 1.0), 1e-6))) if self.fill else c

    def _book(self, ev: dict[str, Any]) -> dict[int, dict[str, Any]]:
        """Per half hour: the pool, as the clearing counts it, and what each order takes of it. Firm goes to the orders in proportion to their size. The rest of each order takes
        tentative power, as far as its deposit reserved it. `tentative_asked` adds the margin on top of what's sold: spare firm first, then what's left of the tentative power. That
        part isn't sold, so no deposit holds it, but an order with no deposit touches no tentative power at all."""
        orders = self._orders(ev)
        rows = {}
        for s in ev["need"]["slots"]:
            sid = s["id"]
            firm = tent = 0.0
            for h, o in ev["offers"].items():
                x, c = self._slot_of(o, sid), self._worth(h, o)
                kw = min(float(x.get("kw_offered") or 0.0), self.rated.get(h, float("inf")))   # no more than its nameplate
                f = min(firm_part(o, x), kw)
                firm += f * c
                tent += (kw - f) * c
            want = {od["buyer"]: self._order_kw(od, sid) for od in orders}
            total = sum(want.values())
            k = min(1.0, firm / total) if total > 0 else 0.0
            firm_to = {b: w * k for b, w in want.items()}
            hold = {od["buyer"]: min(want[od["buyer"]] - firm_to[od["buyer"]],
                                     od["deposit_usd"] / max(self.deposit_rate(od["need"]), 1e-9)) for od in orders}
            r = min(1.0, tent / sum(hold.values())) if sum(hold.values()) > 0 else 0.0
            tent_kw = r * sum(hold.values())
            extra = max(0.0, self.margin_of(ev) * (sum(firm_to.values()) + tent_kw) - max(0.0, firm - sum(firm_to.values())))
            rows[sid] = {"firm_pool_kw": firm, "tentative_pool_kw": tent, "firm": firm_to, "reserved": {b: v * r for b, v in hold.items()},
                         "tentative_sold": min(1.0, tent_kw / tent) if tent > 0 else 0.0,
                         "tentative_asked": min(1.0, (tent_kw + (extra if any(od["deposit_usd"] > 0 for od in orders) else 0.0)) / tent) if tent > 0 else 0.0}
        return rows

    def _sellable(self, ev: dict[str, Any], asked: bool = False) -> dict[str, dict[str, Any]]:
        """The offers as they may be sold. One buyer, not pooled: all of each offer. In the pool: each node's firm part and the
        same share of its tentative part, the share the deposits reserved. asked: with the margin on top, as the clearing asks the nodes for it."""
        if not self.pooled:
            return ev["offers"]
        book = self._book(ev)
        part = "tentative_asked" if asked else "tentative_sold"
        out = {}
        for h, o in ev["offers"].items():
            slots = []
            for x in o["slots"]:
                kw, f = float(x.get("kw_offered") or 0.0), firm_part(o, x)
                sold = min(f + (kw - f) * book[x["id"]][part], self.rated.get(h, kw))
                k = sold / kw if kw > 0 else 0.0
                parts = k * sum(float(x.get(p) or 0.0) for p in PARTS)
                if parts > 1.01 * sold + 0.05:                     # the clearing allocates on the parts: a claim there can't get past the total
                    k *= sold / parts
                slots.append({**x, "kw_offered": round(sold, 3), "firm_kw": round(f, 3),
                              **{p: round(float(x.get(p) or 0.0) * k, 3) for p in PARTS if p in x}})
            out[h] = {**o, "slots": slots}
        return out

    def _fill_orders(self, ev: dict[str, Any]) -> None:
        """After the clearing: each buyer's share of each half hour, and what its deposit holds."""
        book = self._book(ev)
        for od in self._orders(ev):
            b = od["buyer"]
            od["firm"] = {sid: r["firm"][b] for sid, r in book.items()}
            od["reserved"] = {sid: r["reserved"][b] for sid, r in book.items()}
            od["share"] = {sid: (r["firm"][b] + r["reserved"][b]) / max(sum(r["firm"].values()) + sum(r["reserved"].values()), 1e-9)
                           for sid, r in book.items()}
            held = max(od["reserved"].values(), default=0.0) * self.deposit_rate(od["need"])
            od["deposit_held_usd"] = min(od["deposit_usd"], held)
            od["deposit_back_usd"] = round(od["deposit_usd"] - od["deposit_held_usd"], 4)   # what the pool couldn't hold goes back now
        ev["pooled_offer"] = {"firm_kw": {sid: round(r["firm_pool_kw"], 1) for sid, r in book.items()},
                              "tentative_kw": {sid: round(r["tentative_pool_kw"], 1) for sid, r in book.items()}}

    # ------------------------------------------------------------------ C1 clearing
    @staticmethod
    def _place_evs(base: list[float], evs: list[tuple[str, dict[str, Any]]], t0: str) -> tuple[list[float], dict[str, str]]:
        """Valley filling: each paused EV (largest first) restarts at the 15-minute step that keeps the running
        community total lowest while it charges, not before the car arrives, and still finishes before its
        departure."""
        total, starts = list(base), {}
        n = len(total)
        for h, f in sorted(evs, key=lambda x: (-x[1]["kwh"], x[0])):      # cars that need the same energy: by name, so arrival order never counts
            prof, left = [], f["kwh"]
            while left > 1e-6:
                kw = min(f["max_kw"], left / 0.25)
                prof.append(kw)
                left -= kw * 0.25
            first = max(0, math.ceil(Replay.minutes_between(t0, f["arrival"]) / 15)) if f.get("arrival") else 0
            last = min(n, int(Replay.minutes_between(t0, f["latest_finish"]) // 15)) - len(prof)
            if first >= n:                                 # arrives after the evening the guard looks at
                starts[h] = beckn.add_minutes(t0, 15 * first)
                continue
            best = None
            for k in range(first, max(first, last) + 1):
                peak = max(total[k + j] + prof[j] for j in range(len(prof)) if k + j < n) if prof else 0.0
                if best is None or peak < best[0] - 1e-9:
                    best = (peak, k)
            k = best[1] if best else 0
            for j, kw in enumerate(prof):
                if k + j < n:
                    total[k + j] += kw
            starts[h] = beckn.add_minutes(t0, 15 * k)
        return total, starts

    @staticmethod
    def _confidence(o: dict[str, Any]) -> float:
        """The home's own confidence (0.9 x sensor health x its reputation), kept within what that formula allows."""
        try:
            c = float(o.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(MAX_CONFIDENCE, c)) if math.isfinite(c) else 0.0     # NaN would pass min() and count as the most confident

    # ------------------------------------------------------------------ the margin
    def margin_of(self, ev: dict[str, Any]) -> float:
        """This event's margin: its own where the event carries one ("margin"), else clear_margin."""
        return float(ev.get("margin", self.margin))

    def _asked(self, ev: dict[str, Any], s: dict[str, Any]) -> float:
        """kW wanted in this half hour: every order on the sale."""
        return sum(self._order_kw(od, s["id"]) for od in self._orders(ev)) if self.pooled else s["kw_requested"]

    def clear(self, event_id: str) -> dict[str, Any]:
        ev = self.events[event_id]
        if ev["phase"] not in ("offers", "clearing"):     # cleared already (e.g. C3 run again): nothing changes
            return ev.get("clear_summary") or {}
        n = ev["need"]
        offers = self._sellable(ev, asked=self.fill)
        margin = self.margin_of(ev)
        sids = [s["id"] for s in n["slots"]]
        get = lambda o, sid, k: next((x.get(k, 0.0) for x in o["slots"] if x["id"] == sid), 0.0)  # noqa: E731
        cap, evk, bat, share = {}, {}, {}, {}
        book = self._book(ev) if self.fill else {}
        for s in n["slots"]:
            sid = s["id"]
            # reputation enters once, through the home's confidence, not again here
            weighted = sum(get(o, sid, "kw_offered") * self._confidence(o) for o in offers.values())
            if self.fill:
                weighted = sum(book[sid]["firm"].values()) + sum(book[sid]["reserved"].values())
            cap[sid] = round(min(self._asked(ev, s), weighted), 2)
            evk[sid] = sum(get(o, sid, "ev_pause_kw") for o in offers.values())
            bat[sid] = sum(get(o, sid, "battery_kw") + get(o, sid, "ac_kw") + get(o, sid, "light_kw") + get(o, sid, "app_kw") for o in offers.values())
            share[sid] = 0.0 if bat[sid] <= 0 else max(0.0, min(1.0, (cap[sid] * (1 + margin) - evk[sid]) / bat[sid]))
        # rebound guard
        homes = [h for h, o in offers.items() if o.get("evening")]
        lengths = Counter(len(offers[h]["evening"]["import_cf_kw"]) for h in homes)
        steps = lengths.most_common(1)[0][0] if lengths else 0     # every honest node gives the same evening. One that doesn't is left out of the guard: it can't shorten what the guard sees for all
        homes = [h for h in homes if len(offers[h]["evening"]["import_cf_kw"]) == steps]
        no_event = [sum(offers[h]["evening"]["import_cf_kw"][k] for h in homes) for k in range(steps)]
        limit = max(no_event) * (1 + float(self.cfg.get("rebound_tolerance", 0.0))) if steps else None
        evs = [(h, offers[h]["ev_flex"]) for h in homes if offers[h].get("ev_flex")]
        t0 = n["window_end"]

        def evening(g: float):
            base = [0.0] * steps
            for h in homes:
                o = offers[h]
                bsum = sum(get(o, sid, "battery_kw") for sid in sids)
                frac = 0.0 if bsum <= 0 else sum(share[sid] * g * get(o, sid, "battery_kw") for sid in sids) / bsum
                e = o["evening"]
                reb = _rebound_at(e["rebound_kw"], frac)
                for k in range(steps):
                    base[k] += e["import_noev_kw"][k] + reb[k]
            return self._place_evs(base, evs, t0)

        g, guard = 1.0, {"applied": False}
        if steps:
            total, starts = evening(1.0)
            limit = max(limit, max(evening(0.0)[0]))      # no event at all is the least the guard can ask for: rounding must not cancel the event
            guard = {"limit_kw": round(limit, 1), "no_event_peak_kw": round(max(no_event), 1),
                     "peak_without_guard_kw": round(max(total), 1), "applied": False}
            while max(total) > limit + 1e-6 and g > 0:
                g = round(max(0.0, g - 0.05), 2)
                total, starts = evening(g)
                guard["applied"] = True
            guard.update({"battery_factor": g, "peak_forecast_kw": round(max(total), 1),
                          "met": max(total) <= limit + 1e-6, "ev_restarts": starts,
                          "no_event_kw": [round(x, 1) for x in no_event], "with_event_kw": [round(x, 1) for x in total]})
        else:
            starts = {}
        alloc: dict[str, dict[int, float]] = {}
        for h, o in offers.items():
            for sid in sids:
                kw = get(o, sid, "ev_pause_kw") + share[sid] * g * (get(o, sid, "battery_kw") + get(o, sid, "ac_kw")
                                                                    + get(o, sid, "light_kw") + get(o, sid, "app_kw"))
                if kw >= 0.05:
                    alloc.setdefault(h, {})[sid] = round(kw, 3)
        for sid in sids:                                   # promise no more than the homes are asked for, less margin. Filling to the order, the margin gives way before the sale does
            cap[sid] = round(min(cap[sid], sum(a.get(sid, 0.0) for a in alloc.values()) / (1.0 if self.fill else 1 + margin)), 2)
        cover = limit = None
        if self.community is not None:                  # the community's own rules for what it promises upward (community.py)
            offered = {sid: sum(get(o, sid, "kw_offered") for o in offers.values()) for sid in sids}
            cover = self.community.promise_sale(n, cap, offered, margin, self.now())       # its cover comes from its record of delivering what it offered, never more generous than the margin
            limit = self.community.fit_sale(n, cap, alloc)                    # and the utility's limit at its connection has the last word: a sale that would break it is cut to fit
            self.community.record_sale(n["event_id"], n["window_start"], sum(offered.values()) / max(1, len(sids)), sum(cap.values()) / max(1, len(sids)))
        ev.update({"alloc": alloc, "capacity_offered": cap, "phase": "cleared", "cleared_at": self.now(),
                   "ev_restart": starts, "guard": guard, "battery_share": {sid: share[sid] * g for sid in sids}})
        if limit is not None:
            ev["connection_limit"], ev["cover"] = limit, cover
        if self.pooled:
            ev["sold_offers"] = offers
            self._fill_orders(ev)
        summary = {"homes": len(alloc), "capacity_offered_kw": cap,
                   "requested_kw": {s["id"]: self._asked(ev, s) for s in n["slots"]},
                   "offered_kw_raw": {sid: round(sum(get(o, sid, "kw_offered") for o in offers.values()), 2) for sid in sids},
                   "ev_pause_kw": {sid: round(evk[sid], 2) for sid in sids},
                   "battery_share": {sid: round(share[sid] * g, 3) for sid in sids},
                   "rebound_guard": {k: v for k, v in guard.items() if k not in ("ev_restarts", "no_event_kw", "with_event_kw")},
                   "offers": len(offers), "margin": margin}
        if limit is not None:
            summary["connection_limit"], summary["cover"] = limit, cover
        if self.pooled:
            summary["pooled_offer"] = ev["pooled_offer"]
            summary["orders"] = {od["buyer"]: {"share": {k: round(v, 4) for k, v in od["share"].items()},
                                               "firm_kw": {k: round(v, 1) for k, v in od["firm"].items()},
                                               "reserved_kw": {k: round(v, 1) for k, v in od["reserved"].items()},
                                               "deposit_held_usd": round(od["deposit_held_usd"], 2),
                                               "deposit_back_usd": od["deposit_back_usd"]} for od in self._orders(ev)}
        if ev.get("round2"):
            r2 = ev["round2"]
            summary["second_round"] = {"short_kw": r2["short_kw"], "asked": len(r2["asked"]), "answered": len(set(r2["answered"]))}
        ev["clear_summary"] = summary
        self.log("v2_cleared", event_id=event_id, **{k: v for k, v in summary.items() if k != "offered_kw_raw"})
        return summary

    def clear_and_commit(self, event_id: str) -> dict[str, Any]:
        s = self.clear(event_id)
        self.commit_to_utility(event_id)
        return s

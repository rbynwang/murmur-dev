"""The levels around the community's market: its aggregator above it (signed requests in, report rows up), and each buyer's discovery of tomorrow's sale."""
from __future__ import annotations

import time
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.protocol import wire
from murmur.agents.community.market_rules import UP_ANSWER, UP_REPORT, UP_REQUEST, community_id


class MarketAbove:
    """The levels around the community's market: its aggregator above it (signed requests in, report rows up), and each buyer's discovery of tomorrow's sale."""

    def from_above(self, kind: str, sender: str, body: dict[str, Any]) -> str:
        """A signed message from the level above the community, over the message bus: its aggregator's request (kind community.request) for what the members' batteries are to
        give, and at what price. Checked here: this community has an aggregator on record and the sender is it; the signature holds against the key its enrolment
        gave, or the key its first message pinned; and the message was made for this community. Then the community answers for itself (community.asked): taken, or
        refused with the reason. Its answer goes back signed (community.answer). A request is never an order: one that is refused changes nothing."""
        with self.lock:
            c = self.community
            if c is None or not c.aggregator:
                return beckn.Refused("rejected: no aggregator on record")
            if sender != c.aggregator:
                c.refusals["request"] += 1
                self.log("community_request_refused", sender=sender, why="not this community's aggregator")
                return beckn.Refused("rejected: not this community's aggregator")
            ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
            act = str(ctx.get("action"))
            if not (beckn.check(body, c.aggregator_key) if c.aggregator_key else self._verify(sender, body)):
                c.refusals["request"] += 1
                self.log("v2_bad_signature", sender=sender, message_kind=kind)
                wire.note("recv", sender, self.name, act, body, ok=False, sim=self.now())
                return beckn.Refused("rejected: bad signature")
            wire.note("recv", sender, self.name, act, body, sim=self.now())
            if kind != UP_REQUEST or act != "request":
                return beckn.Refused("rejected: unknown kind")
            if ctx.get("bapId") != sender or ctx.get("bppId") != self.name:
                c.refusals["request"] += 1
                return beckn.Refused("rejected: not made for this community")
            req = (body.get("message") or {}).get("request") if isinstance(body.get("message"), dict) else None
            now = self.now()
            try:
                ans = c.asked(sender, req, now)
                text: str = f"request taken: {ans['rows']} quarter hours"
            except ValueError as exc:                            # community.Refused: its words name the rule, never what was in the request
                rid = req.get("id") if isinstance(req, dict) and isinstance(req.get("id"), str) and community_id(req["id"]) else None       # an id only: never a sentence handed back
                ans = {"request": rid, "community": c.id, "taken": False, "why": str(exc), "at": now}
                text = beckn.Refused(f"request refused: {exc}")
            out = self._msg("on_request", sender, str(ctx.get("transactionId") or "request"), {"answer": ans}, role="bpp", ttl_s=beckn.TTL_EVIDENCE_S)
            item = (sender, UP_ANSWER, out, self.mid(sender, "on_request", str(ctx.get("messageId"))))
        if self.cfg.get("sync_broadcast"):                   # off the inbox's thread: it must acknowledge its Town message within the lease
            self._send_up(*item)
        else:
            self.bg.submit(self._send_up, *item)
        return text

    def report_up(self) -> None:
        """Each row of the community's report goes to its aggregator once, signed, oldest first (kind community.report). The report is the community's own record: it
        is written whether or not anyone hears it, and a row that can't be sent now waits and is tried again later, not every tick. The rows are signed here, under
        the market's lock, and sent off it: a slow link upward must not hold up the market."""
        c = self.community
        if c is None or not c.aggregator or not c.outbox or self._up_busy or time.time() < self._up_wait:
            return
        items = [(r, c.aggregator, UP_REPORT, self._msg("report", c.aggregator, f"report:{c.id}:{str(r['timestamp'])[:10]}", {"report": r}, role="bpp", ttl_s=beckn.TTL_EVIDENCE_S),
                  self.mid(c.aggregator, "report", c.id, str(r["timestamp"]))) for r in c.outbox]
        self._up_busy = True
        if self.cfg.get("sync_broadcast"):
            self._report_up_now(items, self.play)
        else:
            self.bg.submit(self._report_up_now, items, self.play)

    def _report_up_now(self, items: list[tuple[dict[str, Any], str, str, dict[str, Any], str]], play: str) -> None:
        try:
            for row, to, kind, body, mid in items:
                if self.play != play:                             # a new play began: the last one's rows are not sent in it
                    return
                if not self._send_up(to, kind, body, mid):
                    self._up_wait = time.time() + float(self.cfg.get("report_up_retry_s", 30.0))
                    return
                with self.lock:
                    c = self.community
                    if c is not None and c.outbox and c.outbox[0] is row:
                        c.outbox.pop(0)
                        c.sent_up += 1
        finally:
            self._up_busy = False

    def _utility_retry_due(self, ev: dict[str, Any], now: str) -> bool:
        """Retry select/init/confirm with backoff: 30, 60, 120 ... replay minutes AND 60, 120, 240 ... wall seconds
        (a fast demo clock must not resend before the utility's answer can be back: each resend starts the exchange
        again, and the community agent would never get past it)."""
        tries = ev.get("utility_tries", 1)
        wait = float(self.cfg.get("utility_retry_minutes", 30)) * 2 ** (tries - 1)
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("utility_retry_wall_seconds", 60)) * 2 ** (tries - 1)
        return (now >= beckn.add_minutes(ev.get("utility_asked_at", now), wait)
                and time.time() >= ev.get("utility_asked_wall", 0.0) + floor)

    # ------------------------------------------------------------------ the clock drives the timeline
    def _ask_buyer(self, buyer: str, day: str, now: str) -> None:
        """Tomorrow's needs, asked until this buyer answers (on_discover)."""
        first = buyer == self.utility
        if (self.last_discover_day if first else self.other_discover.get(buyer)) == day:
            return
        key = day if first else f"{buyer}:{day}"
        asked = self.discover_asked.get(key)
        floor = 0.0 if self.cfg.get("sync_broadcast") else float(self.cfg.get("discover_retry_wall_seconds", 30))
        if asked is None or (now >= beckn.add_minutes(asked, float(self.cfg.get("discover_retry_minutes", 30)))
                             and time.time() >= self.discover_asked_wall.get(key, 0.0) + floor):
            tomorrow = beckn.add_minutes(f"{day} 00:00", 1440)[:10]
            body = self._msg("discover", buyer, f"discover-{day}", {"intent": {"date": tomorrow}})
            n = self.discover_rounds.get(key, 0)                  # a failed send is a retry, under this id. Asked again after it went, it's the next round
            if self._send(buyer, "discover", body, self.mid(buyer, "discover", day, n)):
                self.discover_rounds[key] = n + 1
                self.discover_asked[key] = now                    # a failed send is tried again on the next tick
                self.discover_asked_wall[key] = time.time()
                self.log("v2_discover", date=tomorrow, repeat=asked is not None, **({} if first else {"buyer": buyer}))

    def outlook(self, ev: dict[str, Any]) -> dict[str, Any]:
        """The community forecast, called by the community agent itself when the sale opens: the homes' demand at the sale hours with its
        range, and whether the window sits on the forecast peak. It goes on the sale's record (ev["outlook"]), which a pooled market's summary
        shows. No model or no data for the day never stops a sale."""
        from murmur.agents.community import forecast
        n = ev["need"]
        try:
            f = forecast.forecast(n["window_start"][:10], issued_at=self.now(), members=list(self.roster))
        except (ValueError, OSError, KeyError, IndexError) as exc:
            ev["outlook"] = {"error": str(exc)[:160]}
            self.log("v2_outlook_failed", event_id=n["event_id"], error=ev["outlook"]["error"])
            return ev["outlook"]
        h0, h1 = int(n["window_start"][11:13]), int(n["window_end"][11:13]) + (1 if n["window_end"][14:16] != "00" else 0)
        rows = [x for x in f.get("hours") or [] if h0 <= x["hour"] < h1] or list(f.get("hours") or [])
        if not rows or not f.get("peak_window"):          # no hours in the forecast: the first two weeks of a year have no history to fit, and a division by zero here would stop the sale
            ev["outlook"] = {"error": "the community forecast has no hours for this day, so the sale goes on without the outlook"}
            self.log("v2_outlook_failed", event_id=n["event_id"], error=ev["outlook"]["error"])
            return ev["outlook"]
        mean = lambda k: sum(x[k] for x in rows) / len(rows)  # noqa: E731
        p50 = mean("p50_kw")
        pk = f["peak_window"]
        ev["outlook"] = {"issued_at": f["issued_at"], "homes": f["homes"], "window_p10_kw": round(mean("p10_kw"), 1),
                         "window_p50_kw": round(p50, 1), "window_p90_kw": round(mean("p90_kw"), 1),
                         "range_pct_of_p50": round(100 * (mean("p90_kw") - mean("p10_kw")) / max(p50, 1e-6), 1),
                         "peak_window": [pk["start"], pk["end"]],
                         "window_on_peak": n["window_start"][11:16] < pk["end"] and n["window_end"][11:16] > pk["start"],
                         "days_read": int(f.get("days_read") or 0)}     # 0: the community's own fit didn't run, and community_load's range stands in (forecast.py)
        if f.get("stand_in") or f.get("inputs_missing_share"):      # the forecast worked from incomplete data: it is used, and the record says which answer it was
            ev["outlook"].update(how=str(f.get("how") or "")[:120], stand_in=bool(f.get("stand_in")), inputs_missing_share=float(f.get("inputs_missing_share") or 0.0))
            self.log("v2_outlook_stand_in", event_id=n["event_id"], how=ev["outlook"]["how"], stand_in=ev["outlook"]["stand_in"], inputs_missing_share=ev["outlook"]["inputs_missing_share"])
        self.log("v2_outlook", event_id=n["event_id"], **ev["outlook"])
        if not ev["outlook"]["days_read"]:                 # never in silence: community_load's range holds the truth on 14 % of evenings
            self.log("v2_outlook_fell_back", event_id=n["event_id"], why="the community's own fit read no days: under 21 days of history, or no list of kept days "
                     "(models/forecast_2026/fleet_errors.json), so community_load's range stood in", model=str(f.get("model") or "")[:120])
        return ev["outlook"]

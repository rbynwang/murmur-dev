"""What the level above asks of the community: a signed request checked, answered and kept, so a restart knows what it already took."""
from __future__ import annotations

import json
from typing import Any
from murmur.protocol import envelope as beckn
from murmur.agents.community.community_rules import ASKED, ID, REQUEST, REQUEST_ROWS, STEP_MIN, TIME, _digest, number

from murmur.agents.community.members import Refused

class CommunityAsked:
    """What the level above asks of the community: a signed request checked, answered and kept, so a restart knows what it already took."""

    # ---- the level above: its aggregator asks, the community answers
    def asked(self, sender: str, req: Any, now: str = "") -> dict[str, Any]:
        """A request from the level above, after its signature was checked (market.from_above). It asks and doesn't order: the community takes the request or refuses
        it, and says why. Only this community's aggregator may ask, only for this community, and only for what the members' batteries are to give and the price it offers,
        by the quarter hour: numbers and nothing else. A request for more than the battery's rating is refused whole. A quarter hour that has ended can't be asked for
        any more: those rows are left out and the answer counts them, and a request with nothing left is refused. The same request arriving again gets the same
        answer and changes nothing, and its id can't be used for a different one. The record keeps the answer, never the request's content."""
        def no(why: str, rid: str | None = None) -> Refused:
            self.refusals["request"] += 1
            self.requests = (self.requests + [{"id": rid, "at": now, "from": sender if sender == self.aggregator else None, "taken": False, "why": why}])[-200:]
            self.log("community_request_refused", request=rid, why=why)
            return Refused(why)
        if not self.aggregator:
            raise no("this community has no aggregator on record")
        if sender != self.aggregator:
            raise no("only this community's aggregator may ask")
        if not isinstance(req, dict) or set(req) - REQUEST or not (isinstance(req.get("id"), str) and ID.match(req["id"])):
            raise no("a request is an id, the community it is for, when it was made and its rows, and nothing else")
        rid, rows = req["id"], req.get("rows")
        if req.get("community") != self.id:
            raise no("the request is for another community", rid)
        if req.get("made_at") is not None and not (isinstance(req["made_at"], str) and TIME.match(req["made_at"])):
            raise no("made_at is a time", rid)
        if not isinstance(rows, list) or not rows or len(rows) > REQUEST_ROWS:
            raise no("a request holds rows, one for each quarter hour, and two days of them at most", rid)
        if any(not isinstance(r, dict) or set(r) - ASKED or len(r) < 2 or not (isinstance(r.get("ts"), str) and TIME.match(r["ts"])) for r in rows):
            raise no("a request row is a time and any of " + ", ".join(sorted(ASKED - {"ts"})) + ", and nothing else", rid)
        mark = _digest(rows)
        for old in self.requests:
            if old.get("id") == rid and old.get("taken"):
                if old.get("digest") != mark:
                    raise no("that id was used for another request", rid)
                return {**{k: v for k, v in old.items() if k not in ("digest", "from", "id")}, "request": rid, "community": self.id, "again": True}
        ended = beckn.add_minutes(now[:16], -STEP_MIN) if now and TIME.match(now[:16]) else ""                # a row dated at or before this has ended
        live = [r for r in rows if not ended or r["ts"][:16].replace("T", " ") > ended]
        if not live:
            raise no("every quarter hour asked for has ended", rid)
        try:
            took = self.feed(live, from_above=True)
        except ValueError as exc:
            raise no(str(exc), rid) from None
        ans = {"id": rid, "at": now, "taken": True, "rows": took["rows"], "first": took["first"], "last": took["last"], "too_late": len(rows) - len(live)}
        self.requests = (self.requests + [{**ans, "from": sender, "digest": mark}])[-200:]
        for r in live:                                         # what it said it took, it still holds after a restart
            self.asked_rows.setdefault(r["ts"][:16].replace("T", " "), {}).update({k: float(v) for k, v in r.items() if k != "ts"})
        self._save_asked(now)
        self.log("community_request_taken", request=rid, rows=took["rows"], first=took["first"], last=took["last"], too_late=ans["too_late"])
        return {**{k: v for k, v in ans.items() if k != "id"}, "request": rid, "community": self.id}

    def _save_asked(self, now: str = "") -> None:
        """What was taken from above, on disk: the answers given and the rows taken, for the last two days. A refusal is not written: it changed nothing."""
        if not self.asked_path:
            return
        old = beckn.add_minutes(now[:16], -2 * 24 * 60) if now and TIME.match(now[:16]) else ""
        self.asked_rows = {ts: v for ts, v in sorted(self.asked_rows.items()) if ts >= old}
        self.asked_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.asked_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"community": self.id, "aggregator": self.aggregator, "requests": [r for r in self.requests if r.get("taken")], "rows": self.asked_rows}, indent=1))
        tmp.replace(self.asked_path)

    def _load_asked(self) -> None:
        """After a restart: the requests it took and their rows, if they were taken from the aggregator it has on record now. A file that can't be read, or that
        another aggregator's requests wrote, is left alone and said: nothing is guessed from it."""
        if not (self.asked_path and self.asked_path.exists() and self.aggregator):
            return
        try:
            kept = json.loads(self.asked_path.read_text())
            if kept.get("community") != self.id or kept.get("aggregator") != self.aggregator:
                raise ValueError("it was written for another community or another aggregator")
            rows = {str(ts): {k: float(v) for k, v in vals.items()} for ts, vals in (kept.get("rows") or {}).items()}
            if any(not TIME.match(ts) or set(vals) - (ASKED - {"ts"}) or not all(number(v) for v in vals.values()) for ts, vals in rows.items()):
                raise ValueError("it holds something a request can't ask")
            if any("battery_kw" in v and (self.battery is None or abs(v["battery_kw"]) > self.battery.rating_kw * 1.001) for v in rows.values()):
                raise ValueError("it asks the members' batteries for more than their rating")
            reqs = [r for r in (kept.get("requests") or []) if isinstance(r, dict) and r.get("taken") is True and isinstance(r.get("id"), str) and ID.match(r["id"])]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.log("community_requests_not_read", why=f"{type(exc).__name__}: {str(exc)[:120]}")
            return
        self.requests, self.asked_rows = reqs[-200:], rows
        for ts, vals in rows.items():
            if "battery_kw" in vals:
                self.battery_kw[ts] = vals["battery_kw"]
            if "price_usd_kwh" in vals:
                self.prices[ts] = vals["price_usd_kwh"]
        self.log("community_requests_read", requests=len(reqs), quarter_hours=len(rows))

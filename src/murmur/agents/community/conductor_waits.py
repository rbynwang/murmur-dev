"""What a step of the waiting clock waits on: every participant has caught up with it, no agent is still deciding, nothing is still on its way over
the bus, and nothing the market waits on is still to come. Each wait is a short line a person can read (GET /demo/conductor, `waiting_on`).
"""
from __future__ import annotations

import re
from typing import Any, Callable

import httpx

from murmur.protocol import envelope as beckn
from murmur.agents.community.market_schedule import opens_brake

WIRE_LOGS = ("town_wire.jsonl", "town_wire_utility.jsonl")    # the community agent's wire log and the first buyer's, every signed message either sent or received: what "a message is on its way" reads
T_RE = re.compile(r'^\{"t":([0-9.]+)')                         # a wire log line begins with the wall time it was written at
ROW_UP_RE = re.compile(r'^\{"t":[0-9.]+,"dir":"send","from":"[^"]*","to":"[^"]*","action":"report",')      # a report row the community sent upward: nothing answers it
TAIL = 48_000                  # bytes of a wire log read from its end at first: about 80 report rows, or 30 contract messages


def once_more(call: Callable[..., Any], *a: Any, **k: Any) -> Any:
    """A call to a participant, tried once more at once when the connection drops: the clock keeps its connections open between calls, and a
    participant may have closed one. Not after a timeout: that call has waited long enough."""
    try:
        return call(*a, **k)
    except httpx.TransportError as exc:
        if isinstance(exc, httpx.TimeoutException):
            raise
        return call(*a, **k)


class ConductorWaits:
    """What a step waits on. `c` is the community agent, `cond` the clock's own record, `http` and `wall` what reaches the participants and tells the time (conductor.Conductor)."""

    def wire_recent(self, quiet: float, reports: bool = True) -> bool:
        """A message on either wire log in the last `quiet` seconds. Meter readings do not count: they wait for the window's end. reports=False: nor
        does a report row the community sent upward, which nothing answers. A log is read from its end; where the rows of a long leap fill all
        that was read, it is read further back, so a message that came just before them still counts."""
        now = self.wall()
        for p in self.wire_files:
            span = TAIL
            while span:
                try:
                    if now - p.stat().st_mtime > quiet:
                        break
                    with open(p, "rb") as f:
                        f.seek(0, 2)
                        start = max(0, f.tell() - span)
                        f.seek(start)
                        lines = f.read().decode("utf-8", "replace").splitlines()
                    if start > 0:
                        lines = lines[1:]
                except OSError:
                    break
                span = 0 if reports or start == 0 else span * 4      # nothing older than the quiet time among these lines: four times as much the next time round
                for ln in reversed(lines):
                    m = T_RE.match(ln)
                    if not m:
                        continue
                    if now - float(m.group(1)) > quiet:
                        span = 0
                        break
                    if '"usage_kw"' in ln or (not reports and ROW_UP_RE.match(ln)):
                        continue
                    return True
        return False

    def bus_waits(self, played: bool) -> list[str]:
        """What may still be on its way over the bus. A message on either wire log in the quiet time. And, where the clock runs fast
        (ConductorAsked.quick), at a step that is played: the quiet time itself, counted from the moment every participant had caught up. A
        participant sends what the clock brings due while it catches up, a receiver's inbox takes about that long to be looked at, and only a
        node service says when a message has left it. The old clock's steps lasted longer than an inbox takes by themselves."""
        quiet, caught = self.quiet_s(), self.cond["caught"]
        out = ["messages on their way over the bus"] if self.wire_recent(quiet, reports=not self.leap) else []
        if played and caught is not None and self.quick() and self.wall() - caught < quiet:
            out.append("an inbox may still hold what was sent at this step")
        return out

    def agent_services(self) -> list[str]:
        """The node services' base URLs, where /agents says who is still deciding: cfg clock_wait_urls, or the homes' host and the buildings'."""
        c = self.c
        urls = list(c.cfg.get("clock_wait_urls") or [])
        if not urls:
            if c.targets.get("fleet"):
                urls.append(c.targets["fleet"])
            for b in c.buildings:
                base = str(c.targets.get(b["name"]) or "").split("/b/")[0]
                if base and base not in urls:
                    urls.append(base)
        return urls

    def market_waits(self, now_ts: str) -> list[str]:
        """What the market waits on now that only an answer can bring: dataset time doesn't pass while the clock holds."""
        out, market = [], self.c.market
        with market.lock:
            members = len(market.roster)
            for e in market.events.values():
                n, ph = e["need"], e.get("phase")
                eid = n["event_id"]
                if ph == "offers" and len(e.get("offers") or {}) < members:
                    out.append(f"{eid}: {members - len(e.get('offers') or {})} offers to come")
                elif ph in ("clearing", "cleared", "utility"):
                    out.append(f"{eid}: the buyers' contract")
                elif ph == "homes" and not e.get("final_sent"):
                    left = sum(1 for x in (e.get("commitments") or {}).values() if x.get("status") == "SENT")
                    if left:
                        out.append(f"{eid}: {left} commitments to answer")
                if e.get("telemetry_sent") and ph not in ("done", "failed") and now_ts < beckn.add_minutes(n["window_end"], 1440):
                    out.append(f"{eid}: the buyers' settlement")
            for r in market.rt.calls.values():
                if r.get("phase") == "asking":
                    out.append(f'call {r.get("id")}: answers to come')
        due = market.readings_due()
        if due:
            out.append(f"{due} readings to come")
        if market.rt.due():
            out.append("the desk has reports to read")
        if opens_brake(market.last_discover_day, now_ts, now_ts):
            out.append("the buyer's request for tomorrow")
        return out

    def node_waits(self, now_ts: str) -> tuple[list[str], bool]:
        """What each node service still has to do with this step: tick it, let its agents decide, and send what they say. And whether every one of
        them has ticked it: its nodes have caught up, however many quarter hours the clock moved."""
        out, caught_up = [], True
        for base in self.agent_services():
            try:
                cl = (once_more(self.http.get, base + "/agents", timeout=3).json() or {}).get("clock") or {}
            except (httpx.HTTPError, ValueError):
                out.append(f"{base}: no answer")
                caught_up = False
                continue
            if cl.get("ticked") != now_ts:
                out.append(f'{base}: its nodes at {cl.get("ticked")}')
                caught_up = False
            if cl.get("busy"):
                out.append(f'{base}: {len(cl["busy"])} deciding ({", ".join(cl["busy"][:4])})')
            if cl.get("sending"):
                out.append(f'{base}: {cl["sending"]} messages leaving')
            elif cl.get("sent_s") is not None and cl["sent_s"] < self.quiet_s():
                out.append(f"{base}: a message just left")
        return out, caught_up

    def loop_waits(self, i: int) -> list[str]:
        """Who else has still to catch up with step i. Each other participant that says how far its own loop is (GET /demo/clock, `ticked`): a buyer,
        the aggregator, a single site. One that cannot say, or does not answer, is not waited for (cfg clock_min_step_s gives such a deployment
        its time), and one that has caught up is not asked again in this step. The market's own loop, in this process (clock.ticked). And, where
        the clock waits for it (cfg clock_wait_meter), the community's meter: a reading for every quarter hour since the step the clocks moved from."""
        c, r, cond = self.c, self.c.clock, self.cond
        now_ts, out, nodes = r.ts(i), [], self.agent_services()
        for name, base in c.targets.items():
            if name in cond["heard"] or str(base).split("/b/")[0] in nodes:
                continue
            try:
                ticked = once_more(self.http.get, base + "/demo/clock", timeout=3).json()["ticked"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                cond["heard"].add(name)
                continue
            if ticked == now_ts:
                cond["heard"].add(name)
            else:
                out.append(f"{name}: its loop at {ticked}")
        if r.ticked != now_ts:
            out.append(f"the market: its loop at {r.ticked}")
        community = c.market.community if c.cfg.get("clock_wait_meter") else None
        if community is not None:
            unread = next((r.ts(k) for k in range(i if cond["came"] is None else cond["came"] + 1, i + 1) if community.meter.at(r.ts(k)) is None), None)
            if unread:
                out.append(f"the community's meter: no reading for {unread}")
        return out

    def quiet_s(self) -> float:
        """How long after the last message a step can be called finished: longer than an inbox takes to be looked at."""
        return float(self.c.cfg.get("clock_wait_quiet_s", 4.0))

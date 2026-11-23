"""The community agent's HTTP doors: its health, the community's own record and its report upward, the sales as the market holds them, the start
of an evening, and the waiting clock's own door: its gates and stops, its pace, its leaps, and a driver's hold. The waiting clock itself is conductor.py.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import httpx

from murmur import config
from murmur.protocol import doors
from murmur import files
from murmur.agents.community.community_rules import number
from murmur.agents.community.conductor import Conductor
from murmur.agents.community.service import CommunityAgent


def build_app(c: CommunityAgent, conductor: Conductor | None = None):
    """The agent's doors. `conductor` is its waiting clock: made here when none is given."""
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="murmur-community", version="0.3.0", dependencies=[doors.door()])
    started_at, code_at_start = time.time(), files.code_stamp()
    conductor = conductor or Conductor(c)

    @app.get("/health")
    def health():
        p = getattr(c, "poller", None)
        return {"ok": True, "ready": c.inbox_ready, "agent": c.name, "role": "community", "pubkey": c.pub,
                "started_at": round(started_at, 1), "code": code_at_start, "town_calls": p.stats() if p else None,
                "town_lag_s": round(c.town_lag(), 1), "inbox_lag_s": round(c.lag.value(), 1),
                "town_ms": c.town.timing() if c.town is not None and hasattr(c.town, "timing") else None,
                "town": bool(c.town), "doors": doors.state(), "expired_skipped": c.expired_skipped, "pinned_homes": sorted(c.pins)}

    if c.market.community is not None:                   # the community's own record and its report upward, one row per quarter hour
        @app.get("/v2/community")
        def v2_community():
            return c.market.community.view()

        @app.get("/v2/community/report")
        def v2_community_report(n: int = 96):
            return {"rows": c.market.community.report[-max(1, min(int(n), 2000)):]}

        @app.post("/v2/community/feed")
        def v2_community_feed(body: dict = Body(...)):
            """What the community's meter tells it, by the quarter hour (community.Community.feed). Numbers only; anything else is refused whole."""
            try:
                with c.market.lock:
                    took = c.market.community.feed(body.get("rows"))
            except ValueError as e:
                raise HTTPException(400, str(e))
            conductor.wake()                             # a step may be waiting for these readings (cfg clock_wait_meter)
            return took

    @app.get("/v2/summary")
    def v2_summary():
        return {"now": c.market.now(), "roster": len(c.market.roster), "events": c.market.summary(), "reputation": c.market.reputation}

    @app.get("/v2/events/{event_id}")
    def v2_event(event_id: str, signed: bool = False):
        """One sale as the market holds it. signed=true: with every member's signed meter reading as it arrived and the keys pinned on first contact."""
        ev = c.market.events.get(event_id)
        if not ev:
            raise HTTPException(404, "unknown event")
        if signed:
            with c.market.lock:
                import json
                return json.loads(json.dumps({**ev, "pins": dict(c.market.pins)}, default=str))
        return {k: v for k, v in ev.items() if k != "readings"} | {
            "readings": {h: {s: {k: v for k, v in r.items() if k != "signed_body"} for s, r in rs.items()} for h, rs in ev["readings"].items()}}

    @app.post("/demo/start")
    def demo_start(body: dict = Body(default={})):
        """Start an evening: every participant's clock jumps to 09:45 the day before the sale at the same wall-clock moment, held at each step
        while the clock waits. `step_seconds` (2 to 120) is the participants' own clock setting. `pace_s` (0 to 120; when not given,
        `step_seconds`) is the least wall time a played step lasts, and `leap` says whether the clock leaps over the quarter hours nothing is
        scheduled at (when not given: as the clock was last told, or cfg clock_leap)."""
        if not c.inbox_ready and not body.get("force"):
            raise HTTPException(503, "the community agent is still clearing old messages from its inbox; the evening starts once it has caught up")
        day = body.get("event", config.dataset_meta().get("default_event"))
        step = float(body.get("step_seconds", 10))
        pace, leap = body.get("pace_s", step), body.get("leap")
        try:
            datetime.strptime(str(day), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "event must be YYYY-MM-DD")
        if not 2 <= step <= 120:
            raise HTTPException(400, "step_seconds must be 2-120")
        if not (number(pace) and 0 <= pace <= 120):
            raise HTTPException(400, "pace_s must be 0-120")
        if leap is not None and not isinstance(leap, bool):
            raise HTTPException(400, "leap must be true or false")
        at = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d") + " 09:45"
        lead = max(1.0, min(60.0, float(body.get("lead_s") or 15)))     # every participant starts together, this much later
        clock = {"start": at, "at": at, "at_wall": time.time() + lead, "step_seconds": step, "loop_days": 0, **({"hold": True} if c.cfg.get("clock_waits") else {})}
        with conductor.lock:                             # no step of the waiting clock lands while every clock is moved
            out = {}
            with httpx.Client(timeout=20, headers=doors.headers()) as http:
                for name, base in c.targets.items():
                    try:
                        http.post(base + "/demo/reset", json={}).raise_for_status()
                        j = http.post(base + "/demo/clock", json=clock).json()
                        out[name] = j.get("now", "ok")
                    except Exception as exc:
                        out[name] = f"not reached: {str(exc)[:80]}"
            c.market.reset()
            r = c.clock
            r.configure(clock["start"], step, 0, clock["at"], clock["at_wall"], hold=bool(clock.get("hold")))
            conductor.started(clock["at_wall"], float(pace), leap)      # gates and stops stay: a runner sets them first
        out["community"] = r.ts(r.current())
        c.event("demo_start", event=day, step_seconds=step, pace_s=float(pace), leap=conductor.leap, starts_at=at, targets=out)
        conductor.start_loops()
        return {"event": day, "starts_at": at, "step_seconds": step, "wall_start": clock["at_wall"],
                "minutes_total": round((96 + 57) * float(pace) / 60, 1), "agents": out, "pace_s": float(pace), "leap": conductor.leap}

    @app.get("/demo/conductor")
    def conductor_get():
        """The waiting clock: steps moved, seconds held beyond the pace, every time it went on without something, and its mode, pace, stops and
        last leaps (conductor_asked.ConductorAsked.view)."""
        return conductor.view()

    @app.post("/demo/conductor")
    def conductor_post(body: dict = Body(default={})):
        """A driver's word to the waiting clock. Gates, for a runner: {"gates": [ts, ...]} are the steps the clock stops before, held one step
        earlier with everything else done, until {"open": ts}. And {"stops": [ts, ...]}, {"leap": bool}, {"pace_s": 0 to 120}, {"hold": bool},
        {"step": n}, {"run_to": ts} (conductor_asked.ConductorAsked.asked). A word that can't be read is refused whole."""
        try:
            conductor.asked(body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return conductor.view()

    return app

"""The community agent's HTTP doors and its waiting clock.

The waiting clock (cfg clock_waits): every participant's clock holds at a step until every node service has ticked it, no agent there is still
deciding, nothing is still on its way over the bus, and nothing the market waits on is still to come (offers, a contract, commitments, a call's
answers, readings, settlement). Then all of them move one step together. Waits that don't change for clock_wait_idle_s let the clock go on,
and that is on the record. A runner may set gates: steps the clock stops before until it opens them.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta
from typing import Any

import httpx

from murmur.protocol import envelope as beckn
from murmur import config
from murmur.protocol import doors
from murmur import files
from murmur.agents.community.service import CommunityAgent, opens_brake

log = logging.getLogger("murmur.community")


def build_app(c: CommunityAgent):
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="murmur-community", version="0.3.0", dependencies=[doors.door()])
    started_at, code_at_start = time.time(), files.code_stamp()

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
                    return c.market.community.feed(body.get("rows"))
            except ValueError as e:
                raise HTTPException(400, str(e))

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
        """Start an evening: every participant's clock jumps to 09:45 the day before the sale at the same wall-clock moment, then plays one
        15-minute step every `step_seconds` (held at each step while the clock waits)."""
        if not c.inbox_ready and not body.get("force"):
            raise HTTPException(503, "the community agent is still clearing old messages from its inbox; the evening starts once it has caught up")
        day = body.get("event", config.dataset_meta().get("default_event"))
        step = float(body.get("step_seconds", 10))
        try:
            datetime.strptime(str(day), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "event must be YYYY-MM-DD")
        if not 2 <= step <= 120:
            raise HTTPException(400, "step_seconds must be 2-120")
        at = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d") + " 09:45"
        lead = max(1.0, min(60.0, float(body.get("lead_s") or 15)))     # every participant starts together, this much later
        clock = {"start": at, "at": at, "at_wall": time.time() + lead, "step_seconds": step, "loop_days": 0, **({"hold": True} if c.cfg.get("clock_waits") else {})}
        with cond_lock:                                  # no step of the waiting clock lands while every clock is moved
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
            cond.update(since=clock["at_wall"], waits=None, changed=0.0, went_on=deque(maxlen=200), steps=0, held_s=0.0, at_gate=None, unreached=set())   # gates stay: a runner sets them first
        out["community"] = r.ts(r.current())
        c.event("demo_start", event=day, step_seconds=step, starts_at=at, targets=out)
        start_loops()
        return {"event": day, "starts_at": at, "step_seconds": step, "wall_start": clock["at_wall"],
                "minutes_total": round((96 + 57) * step / 60, 1), "agents": out}

    # ---- every signed message this machine's services sent or received (the wire logs): what "a message is on its way" reads
    wire_files = [config.log_dir() / f for f in ("town_wire.jsonl", "town_wire_utility.jsonl")]
    t_re = re.compile(r'^\{"t":([0-9.]+)')

    def wire_recent(ids: list[str] | None, quiet: float) -> bool:
        """A message about one of these sales (any message while there is none) on either wire log in the last `quiet` seconds. Meter
        readings do not count: they wait for the window's end."""
        now = time.time()
        for p in wire_files:
            try:
                if now - p.stat().st_mtime > quiet:
                    continue
                with open(p, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    start = max(0, size - 48_000)
                    f.seek(start)
                    lines = f.read().decode("utf-8", "replace").splitlines()
                if start > 0:
                    lines = lines[1:]
            except OSError:
                continue
            for ln in reversed(lines):
                m = t_re.match(ln)
                if not m:
                    continue
                if now - float(m.group(1)) > quiet:
                    break
                if '"usage_kw"' in ln:
                    continue
                if not ids or any(x in ln for x in ids):
                    return True
        return False

    cond: dict[str, Any] = {"since": 0.0, "waits": None, "changed": 0.0, "went_on": deque(maxlen=200), "steps": 0, "held_s": 0.0, "posting": False,
                            "gates": set(), "at_gate": None, "unreached": set()}
    cond_lock = threading.Lock()                         # one thing moves the clocks at a time: a start, a step, or sending the line again
    loops = {"on": False}

    def clock_again() -> None:
        """A participant that restarted runs on its own configured clock again. Any participant on another line gets this one again."""
        r = c.clock
        wall0, step, i0, loop, held = r._line
        if r.at_wall is None or loop or cond.get("posting") or not cond_lock.acquire(blocking=False):
            return
        try:
            at = r.ts(i0)
            for name, base in c.targets.items():
                try:
                    got = httpx.get(base + "/demo/clock", timeout=3).json()
                    if abs(float(got["at_wall"] or 0.0) - wall0) > 0.5 or abs(float(got["step_seconds"]) - step) > 1e-6 or bool(got.get("held")) != (held is not None) \
                            or (held is not None and got.get("now") != at):
                        httpx.post(base + "/demo/clock", timeout=3, headers=doors.headers(), json={"start": at, "at": at, "at_wall": wall0, "step_seconds": step, "loop_days": 0, "keep": True,
                                                                                                  **({"hold": True} if held is not None else {})}).raise_for_status()
                        c.event("clock_sent_again", agent=name, was=got.get("now"), now=r.ts(r.current()))
                except (httpx.HTTPError, KeyError, TypeError, ValueError):
                    continue
        finally:
            cond_lock.release()

    def agent_services() -> list[str]:
        """The node services' base URLs, where /agents says who is still deciding: cfg clock_wait_urls, or the homes' host and the buildings'."""
        urls = list(c.cfg.get("clock_wait_urls") or [])
        if not urls:
            if c.targets.get("fleet"):
                urls.append(c.targets["fleet"])
            for b in c.buildings:
                base = str(c.targets.get(b["name"]) or "").split("/b/")[0]
                if base and base not in urls:
                    urls.append(base)
        return urls

    def market_waits(now_ts: str) -> list[str]:
        """What the market waits on now that only an answer can bring: dataset time doesn't pass while the clock holds."""
        out = []
        with c.market.lock:
            members = len(c.market.roster)
            for e in c.market.events.values():
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
            for r in c.market.rt.calls.values():
                if r.get("phase") == "asking":
                    out.append(f'call {r.get("id")}: answers to come')
        due = c.market.readings_due()
        if due:
            out.append(f"{due} readings to come")
        if c.market.rt.due():
            out.append("the desk has reports to read")
        if opens_brake(c.market.last_discover_day, now_ts, now_ts):
            out.append("the buyer's request for tomorrow")
        return out

    def node_waits(now_ts: str) -> list[str]:
        out = []
        for base in agent_services():
            try:
                cl = (httpx.get(base + "/agents", timeout=3).json() or {}).get("clock") or {}
            except (httpx.HTTPError, ValueError):
                out.append(f"{base}: no answer")
                continue
            if cl.get("ticked") != now_ts:
                out.append(f'{base}: its nodes at {cl.get("ticked")}')
            if cl.get("busy"):
                out.append(f'{base}: {len(cl["busy"])} deciding ({", ".join(cl["busy"][:4])})')
            if cl.get("sending"):
                out.append(f'{base}: {cl["sending"]} messages leaving')
            elif cl.get("sent_s") is not None and cl["sent_s"] < quiet_s():
                out.append(f"{base}: a message just left")
        return out

    def quiet_s() -> float:
        """How long after the last message a step can be called finished: longer than an inbox takes to be looked at."""
        return float(c.cfg.get("clock_wait_quiet_s", 4.0))

    def hold_all(j: int) -> None:
        """Every clock to step j, held there."""
        r = c.clock
        at = r.ts(j)
        body = {"start": at, "at": at, "at_wall": time.time(), "step_seconds": float(r.step_seconds), "loop_days": 0, "keep": True, "hold": True}
        res: dict[str, Any] = {}

        def post(name: str, base: str) -> None:
            try:
                httpx.post(base + "/demo/clock", json=body, timeout=5, headers=doors.headers()).raise_for_status()
            except Exception as exc:                      # noqa: BLE001  it gets the line again from clock_again
                res[name] = f"not reached: {str(exc)[:80]}"
        cond["posting"] = True
        try:
            ths = [threading.Thread(target=post, args=kv, daemon=True) for kv in c.targets.items()]
            for t in ths:
                t.start()
            r.configure(at, float(r.step_seconds), 0, at, body["at_wall"], hold=True)
            for t in ths:
                t.join(6)
        finally:
            cond["posting"] = False
        if set(res) != cond["unreached"]:                 # once when it changes, not at every step
            c.event("clock_not_reached", sim=at, agents=res)
        cond["unreached"] = set(res)

    def conductor_tick() -> None:
        if not c.cfg.get("clock_waits") or not cond_lock.acquire(blocking=False):      # a start is moving every clock
            return
        try:
            conductor_step()
        finally:
            cond_lock.release()

    def conductor_step() -> None:
        r = c.clock
        if r.at_wall is None or r.loop_days or not r.held or time.time() < cond["since"]:
            return
        if time.time() < cond["since"] + float(r.step_seconds):      # the run's pace: a step lasts at least this long
            return
        i = r.current()
        if i >= len(r.rows) - 1:
            return
        now_ts = r.ts(i)
        nodes = node_waits(now_ts) + (["messages on their way over the bus"] if wire_recent(None, quiet_s()) else [])
        if not nodes:
            c.market.rt.settled = now_ts                  # every node has done this step and what it sent is in: the desk can read the step's reports together
        waits = nodes + market_waits(now_ts)
        t = time.time()
        if waits:
            sig = tuple(waits)
            if sig != cond["waits"]:
                cond["waits"], cond["changed"] = sig, t
            if t - cond["changed"] < float(c.cfg.get("clock_wait_idle_s", 180)):
                return
            cond["went_on"].append({"sim": now_ts, "wall": round(t, 1), "without": list(waits)[:8]})
            c.event("clock_went_on", sim=now_ts, waited_s=round(t - cond["since"], 1), without=list(waits)[:8])
        nxt = r.ts(i + 1)
        if nxt in cond["gates"]:                          # a runner posts what happens at nxt before any node sees it, then opens the gate
            cond["at_gate"] = nxt
            return
        cond["held_s"] += max(0.0, t - cond["since"] - float(r.step_seconds))
        cond["steps"] += 1
        hold_all(i + 1)
        cond.update(since=time.time(), waits=None, changed=0.0)

    @app.get("/demo/conductor")
    def conductor_get():
        """The waiting clock: steps moved, seconds held beyond the pace, and every time it went on without something."""
        return {"on": bool(c.cfg.get("clock_waits")), "now": c.clock.ts(c.clock.current()), "held": c.clock.held, "steps": cond["steps"],
                "held_s": round(cond["held_s"], 1), "waiting_on": list(cond["waits"] or ()), "went_on": list(cond["went_on"]),
                "gates": sorted(cond["gates"]), "at_gate": cond["at_gate"]}

    @app.post("/demo/conductor")
    def conductor_post(body: dict = Body(default={})):
        """Gates, for a runner: {"gates": [ts, ...]} are the steps the clock stops before, held one step earlier with everything else done,
        until {"open": ts}."""
        if isinstance(body.get("gates"), list):
            cond["gates"] = {str(x) for x in body["gates"]}
            cond["at_gate"] = None
        if body.get("open"):
            cond["gates"].discard(str(body["open"]))
            if cond["at_gate"] == str(body["open"]):
                cond["at_gate"] = None
        return conductor_get()

    def start_loops() -> None:
        if loops["on"]:
            return
        loops["on"] = True

        def again() -> None:
            while True:
                time.sleep(20.0)
                clock_again()
        threading.Thread(target=again, daemon=True, name="clock-again").start()

        def loop() -> None:
            while True:
                time.sleep(0.4)
                try:
                    conductor_tick()
                except Exception:
                    log.debug("clock loop: %s", traceback.format_exc())
        threading.Thread(target=loop, daemon=True, name="clock").start()

    return app

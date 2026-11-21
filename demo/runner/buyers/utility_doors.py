"""The stand-in buyer's HTTP doors (the process itself is demo.runner.buyers: python -m demo.runner.buyers NAME --port PORT)."""
from __future__ import annotations

import time

from murmur.protocol import doors
from murmur.protocol import ids
from demo.runner.buyers.utility import Utility


def build_app(u: Utility):
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="murmur-utility", version="0.2.0", dependencies=[doors.door()])

    @app.get("/health")
    def health():
        p = getattr(u, "poller", None)
        lag = getattr(u, "lag", None)
        return {"ok": True, "agent": u.name, "pubkey": u.pub, "now": u.now(), "contracts": len(u.contracts),
                "label": "Utility or ENGIE (mock, public data)", "town_calls": p.stats() if p else None,
                "inbox_lag_s": round(lag.value(), 1) if lag else 0.0, "doors": doors.state(),
                "town_ms": u.town.timing() if getattr(u, "town", None) is not None and hasattr(u.town, "timing") else None}

    @app.get("/contracts")
    def contracts():
        return {t: {**{k: v for k, v in c.items() if k in ("status", "meters", "offered", "settlement", "buyer_review", "rejected_readings", "rejected_slots", "pre_refused")},
                    "event_id": c.get("need", {}).get("event_id")}
                for t, c in u.contracts.items()}

    def _fail(exc: ValueError):
        code, _, msg = str(exc).partition(": ")
        raise HTTPException(int(code) if code in ("400", "404", "409") else 400, msg or str(exc))


    @app.post("/needs")
    def post_need(body: dict = Body(...)):
        with u.lock:
            try:
                return u.place_order(body)
            except ValueError as exc:
                _fail(exc)


    @app.get("/evidence/{event_id}")
    def evidence(event_id: str):
        with u.lock:
            try:
                return u.evidence(event_id)
            except KeyError:
                raise HTTPException(404, f"no contract for {event_id}")


    @app.get("/events")
    def events(n: int = 50):
        return list(u.events)[-n:]

    @app.get("/traffic")
    def traffic():
        lag = getattr(u, "lag", None)                  # how far behind this buyer's inbox is (inbox.LagMeter)
        return {"received_from_homes": dict(u.traffic_homes), "inbox_lag_s": round(lag.value(), 1) if lag else 0.0}

    @app.get("/calls")
    def calls():
        """Short-notice and emergency calls during the day (grid_watch.GridWatch): what was asked, confirmed, measured, paid."""
        with u.lock:
            return {"now": u.now(), "calls": u.watch.summary(), "alerts": u.watch.alerts}

    @app.post("/alert")
    def alert(body: dict = Body(...)):
        """The grid operator tells the buyer of an emergency (in a demo run, the runner's "emergency" event): {"kw": extra kW
        wanted, or "pct": a percentage of the program's kW, "minutes": how long, "why": ..., "at": the step it is told at}.
        The buyer calls the community agent at once, or at that step when it is still to come."""
        try:
            if body.get("kw") is None and body.get("pct") is not None:      # "10-100 % more than the program"
                body = {**body, "kw": u.watch.program(u.now()[:10])[0] * float(body["pct"]) / 100.0}
            kw, minutes = float(body.get("kw")), float(body.get("minutes", 60))
        except (TypeError, ValueError):
            raise HTTPException(400, "kw (or pct) and minutes must be numbers")
        if not (0 < kw <= 2000 and 15 <= minutes <= 240):
            raise HTTPException(400, "kw must be in (0, 2000] and minutes in [15, 240]")
        with u.lock:                                     # "at": a step a test runner names, for an alert told at that step
            a = u.watch.alert(kw, minutes, str(body.get("why") or "grid emergency")[:120], at=body.get("at") or None)
            if a["at"] <= u.now():
                u.watch.tick()
            return a


    @app.post("/demo/reset")
    def demo_reset(body: dict = Body(default={})):
        """A new run. The demo runner's orders (buyer "demo runner (NAME)") go and another buyer agent's order stays, unless
        clear_orders, which drops every order: the runner sends it, then orders again for the same day."""
        with u.lock:
            u.contracts.clear()
            u.unsent.clear()
            u.traffic_homes.clear()
            u.run_wall = time.time()
            u.play = ids.new_play()
            from demo.runner.buyers.grid_watch import GridWatch
            u.watch, u.watch.price_rule = GridWatch(u), u.watch.price_rule   # a stand-in buyer stays one that calls only on an alert
            u.orders = {} if (body or {}).get("clear_orders") else \
                {k: v for k, v in u.orders.items() if not str(v.get("buyer", "")).startswith("demo runner")}
        return {"ok": True}

    @app.get("/demo/clock")
    def demo_clock_get():
        return u.clock.clock()

    @app.post("/demo/clock")
    def demo_clock(body: dict = Body(default={})):
        u.clock.configure(body.get("start", u.clock.start), float(body.get("step_seconds", u.clock.step_seconds)),
                          int(body.get("loop_days", u.clock.loop_days)), body.get("at"), body.get("at_wall"), hold=bool(body.get("hold")))
        return u.clock.clock()

    return app

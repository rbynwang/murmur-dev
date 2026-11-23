"""A node host's HTTP doors (each building also under /b/<name>) and its process."""
from __future__ import annotations

import argparse
import logging
import math
import time
from typing import Any
import httpx
from murmur.protocol import doors
from murmur import replay as replay_mod
from murmur.node.home import MemberNode
from murmur.node.simulator import CATCH_UP
from murmur.protocol import envelope as beckn
from murmur.agents.host_common import TEL_KEYS, held, log, memory_mb
from murmur.agents.building import BuildingHost
from murmur.agents.host_people import comfort_ok, override_ok, raises_a_limit
from murmur.agents.host import NodeHost
from murmur.agents import host_reads


def rows_after(adapter: Any, since: str, keep: int = CATCH_UP) -> list[list[Any]]:
    """A node's kept meter rows after dataset time `since`, oldest first, as /telemetry's lists of values: the newest `keep` of them, which is as
    many quarter hours as a node steps in one move of its clock."""
    kept = sorted((i, x) for i, x in list((getattr(adapter, "recent", None) or {}).items()) if (x.get("ts") or "") > since)
    return [[x.get(k) for k in TEL_KEYS] + [adapter.E] for _, x in kept[-keep:]]


def build_app(f: NodeHost):
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="murmur-host", version="0.3.0", dependencies=[doors.door()])

    @app.get("/health")
    def health():
        any_home = next(iter(f.homes.values()), None)
        v = sorted(f.town_in)
        q = (lambda p: round(v[min(len(v) - 1, int(round(p * (len(v) - 1))))], 2)) if v else None   # noqa: E731
        ticks = sorted(f.tick_s)
        out = {"ok": True, "ready": f.ready, "kind": f.kind, "homes": len(f.homes), "clock": any_home.replay.clock() if any_home else None,
               "town_delivery_s": {"n": len(v), "p50": q(0.5), "p95": q(0.95), "max": round(v[-1], 2)} if v else {"n": 0},
               "town_calls": {"notify": f.checks, "claim": f.claims,
                              "uptime_s": round(time.time() - f.started)},
               "memory": memory_mb(), "tick_s": {"p50": ticks[len(ticks) // 2], "max": ticks[-1], "worst": f.tick_worst} if ticks else None, "busy_passes": f.busy_passes,
               "repeats": f.repeats, "dropped": f.dropped, "kept_passes": f.kept_passes, "thinking": sorted(f.thinkers), "model": f.mind.status() if f.mind else None, "doors": doors.state()}
        if f.kind == "buildings":
            out["agent"] = "ready" if BuildingHost.agent_class() else "missing: murmur/node/building_agent.py, so the buildings run on code"
        out["held"] = held(f)                             # who waits for a person's word
        out["person_keys"] = sorted(f.cfg.get("person_keys") or ())       # whose word can end it
        if f.alarm_unsaved:
            out = {**out, "ok": False, "alarms": [{"what": "alarm_not_saved", "why": f"{len(f.alarm_unsaved)} nodes' alarms aren't on disk, so a restart would lose them"}]}
        return out


    @app.get("/telemetry")
    def telemetry(since: str | None = None):
        """Every home's latest telemetry in one small answer, for the runner's meter feed (simulation truth).
        With `since` (a dataset time), also each home's readings of the steps after it: the steps a poll every few
        seconds would miss while the live clock runs fast, and every step of a clock that moved many at once (192
        at most, about 150 bytes a row: 120 kB for 8 homes after a move of 96 steps)."""
        keys = list(TEL_KEYS) + ["E"]                   # compact: one list of values per home (~8 kB for 98 homes)
        out: dict[str, Any] = {}
        recent: dict[str, Any] = {}
        for n, h in f.homes.items():
            t = h.adapter.tel or {}
            out[n] = [t.get(k) for k in TEL_KEYS] + [h.adapter.E]
            if since:
                got = rows_after(h.adapter, since)
                if len(got) > 1:                        # one row after it is the latest, which `homes` says already
                    recent[n] = got
        any_home = next(iter(f.homes.values()), None)
        res = {"now": any_home.now_ts() if any_home else None, "keys": keys, "homes": out}
        if since:
            res["recent"] = recent
        return res

    @app.get("/homes/{name}")
    def home(name: str):
        h = f.homes.get(name)
        if not h:
            raise HTTPException(404, "unknown home")
        return {**h.status(), "offers": h.offers, "contracts": h.contracts, "payments": h.payments,
                "telemetry": h.adapter.tel}

    @app.get("/agents")
    def agents():
        """The thinking nodes at a glance: what each is running now, and its workflow so far."""
        out = {}
        for n, a in f.agents.items():
            th = f.thinkers.get(n)
            out[n] = {"steps": [list(s) for s in a.steps[-12:]], "calls_running": len(a.calls), "levers": a.sim.levers, "decisions": len(f.decisions.get(n) or ()),
                      "reports": len(a.reports), "steps_skipped": th.skipped if th else 0,
                      "fallbacks": dict(getattr(a, "fallbacks", {})) | dict(getattr(f.homes[n].brain, "fallbacks", None) or {}),
                      "flags": dict(getattr(a, "flags", {})), "receipts": len(getattr(a, "receipts", ())), "told": len(getattr(a, "told", ()))}
        any_home = next(iter(f.homes.values()), None)
        busy = sorted(n for n, th in f.thinkers.items() if th.busy()) + sorted(n for n, ids in f.taking.items() if ids and n not in f.thinkers)
        return {"model": f.mind.status() if f.mind else None, "nodes": out,
                "clock": {"now": any_home.replay.ts(any_home.replay.current()) if any_home else None, "held": bool(any_home and any_home.replay.held),
                          "ticked": f.ticked, "busy": busy, "sending": f.sending, "sent_s": round(time.time() - f.sent_wall, 2) if f.sent_wall else None}}

    @app.get("/agents/{name}/receipts")
    def agent_receipts(name: str):
        """Every node an agent: each decision's receipt, and what the owner or manager was told (node/agent.py)."""
        a = f.agents.get(name)
        if a is None:
            raise HTTPException(404, "this node has no agent")
        return {"receipts": list(getattr(a, "receipts", ())), "told": list(getattr(a, "told", ())), "reports": list(getattr(a, "reports", ())), "flags": dict(getattr(a, "flags", {})),
                "fallbacks": dict(getattr(a, "fallbacks", {})) | dict(getattr(f.homes[name].brain, "fallbacks", None) or {})}

    host_reads.mount(app, f)                              # the record door: each node's own log, read from a place on

    @app.post("/demo/reset")
    def demo_reset():
        f.reset()
        scenario_reset()
        return {"ok": True, "homes": len(f.homes)}

    def scenario_reset() -> None:
        replay_mod.set_weather(1.0, 1.0, dT=0.0)
        for h in f.homes.values():
            h.adapter.set_battery_fault(False)
            if hasattr(h.adapter, "overrides"):
                h.adapter.rt_override("clear")          # an alarm stays: this door has no signature

    def with_battery(n: int) -> list[str]:
        """n nodes with a battery, picked the same way every time: spread evenly over those that have one."""
        have = [x for x, h in f.homes.items() if h.adapter.E > 0]
        return have[::max(1, len(have) // max(1, n))][:n]

    def charge_asked(bs: Any) -> tuple[list[str], float]:
        """Whose battery a battery_soc names, and the charge in percent. Anything else answers 400, before the scenario changes a thing."""
        def number(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        if not isinstance(bs, dict) or not number(bs.get("pct")) or not 5 <= bs["pct"] <= 100:
            raise HTTPException(400, 'battery_soc: {"homes": [names] or "n": N, "pct": a number from 5 to 100}')
        names, n = bs.get("homes"), bs.get("n")
        if names:
            if not isinstance(names, list) or not all(isinstance(x, str) and x in f.homes for x in names):
                raise HTTPException(400, "battery_soc: homes is a list of nodes here")
            flat = next((x for x in names if f.homes[x].adapter.E <= 0), None)
            if flat:
                raise HTTPException(400, f"battery_soc: {flat} has no battery")
            return list(dict.fromkeys(names)), float(bs["pct"])
        if not number(n) or n != int(n) or n < 1:
            raise HTTPException(400, "battery_soc: homes names nodes here, or n is how many with a battery, 1 or more")
        if not with_battery(int(n)):
            raise HTTPException(400, "battery_soc: no node here has a battery")
        return with_battery(int(n)), float(bs["pct"])

    @app.post("/person/{name}")
    def person_word(name: str, body: dict = Body(default={})):
        """A person's signed word for one node (policy.signed): the end of an alarm, a limit, and on a node with an agent a group closed or opened. HostPeople.person_word takes it."""
        if name not in f.homes:
            raise HTTPException(404, "no such node here")
        return f.person_word(name, body)

    @app.post("/demo/scenario")
    def demo_scenario(body: dict = Body(default={})):
        """What if, for the homes here (the demo runner's evening posts these): {"weather": {"pv": 0.3, "load": 1.2}} from now on,
        {"battery_fault": {"n": 10, "on": true}} (n homes with a battery, picked the same way every time) or
        {"battery_fault": {"homes": [...], "on": false}}, {"battery_soc": {"homes": [...] or "n": 2, "pct": 5 to 100}} (those
        batteries hold that charge now, each inside its own band: the answer says what each was set to), {"reset": true}.
        Physical truth only: each home's agent reacts with its own code."""
        out: dict[str, Any] = {"homes": len(f.homes)}
        charge = charge_asked(body["battery_soc"]) if body.get("battery_soc") is not None else None
        any_home = next(iter(f.homes.values()), None)
        now = any_home.replay.ts(any_home.replay.current()) if any_home else None
        if body.get("reset"):
            scenario_reset()
            out["reset"] = True
        w = body.get("weather")
        if isinstance(w, dict):                           # from now on, or from a step a test runner names ("from")
            frm = str(w.get("from") or now)
            to = beckn.add_minutes(frm, 60 * float(w["hours"])) if w.get("hours") else None
            out["weather"] = replay_mod.set_weather(w.get("pv"), w.get("load"), frm, to=to, dT=w.get("dT"))
        ov = body.get("override")
        if isinstance(ov, dict):                          # an owner's wish, with where it came from ("source")
            name, k = ov.get("home"), ov.get("kind")
            kinds = ("comfort", "lights", "stop", "clear", "alarm") if f.kind == "buildings" else ("ev_now", "comfort", "stop", "depart_at", "clear", "note", "alarm")
            if not isinstance(name, str) or name not in f.homes or k not in kinds:
                raise HTTPException(400, f"override: a node here and kind {'|'.join(kinds)}")
            value = ov.get("value", "alarm" if k == "alarm" else True)
            if k == "comfort" and not comfort_ok(value):
                raise HTTPException(400, "override: comfort takes max_rise_c, max_rise_away_c or precool_c, inside policy.py's range")
            if not override_ok(k, value):
                raise HTTPException(400, f"override: {k} doesn't take that value. A switch is true, plain text, false or null")
            a = f.homes[name].adapter
            if not hasattr(a, "rt_override"):
                raise HTTPException(409, f"{name} has no real-time control")
            if raises_a_limit(a, k, value):
                raise HTTPException(403, f"override: a limit goes up only by a person's signed word, through POST /person/{name}")
            # an alarm's input: {"kind": "alarm", "value": "smoke"}, and value false when the signal ends. Neither frees the node: only the signed door does that
            a.rt_override(k, value)
            if k == "alarm":
                f.alarm_kept(name)
            f.homes[name].log("owner_override", override=k, value=value, source=ov.get("source", "control room"))
            out["override"] = {"home": name, "kind": k, "overrides": dict(a.overrides), "mode": getattr(a, "mode", "fixed")}
            if "alarm_hold" in a.overrides:
                out["held"] = f"an alarm holds {name} until a person clears it through POST /person/{name}"
        for k in ("closed", "zone_event"):                # a building closes for the day, or holds an event in a zone it sold (node/surprises.py)
            sp = body.get(k)
            if isinstance(sp, dict):
                name = sp.get("home")
                if f.kind != "buildings" or name not in f.homes:
                    raise HTTPException(400, f"{k}: a building here")
                from murmur.node import surprises
                h = f.homes[name]
                t = str(sp.get("at") or now)              # now, or the step a test runner names: it posts while every clock waits one step before
                with f.locks[name]:
                    out.update(surprises.close_building(h, t, sp.get("share")) if k == "closed" else
                               surprises.zone_event(h, t, float(sp.get("share", 0.25)), float(sp.get("hours", 3.5)), sp.get("space")))
                h.log("what_if", what=k, **{x: v for x, v in sp.items() if x != "home"})
        bf = body.get("battery_fault")
        if isinstance(bf, dict):
            on = bool(bf.get("on", True))
            names = [n for n in (bf.get("homes") or []) if n in f.homes]
            if not names and bf.get("n"):
                names = with_battery(int(bf["n"]))
            for n in names:
                f.homes[n].adapter.set_battery_fault(on)
            out["battery_fault"] = {"on": on, "homes": names}
            f.events.append({"t": time.time(), "kind": "what_if_battery_fault", "on": on, "homes": len(names)})
        if charge:
            names, pct = charge
            done = {}
            for n in names:
                with f.locks[n]:                          # between two steps of the node, never inside one
                    done[n] = f.homes[n].adapter.set_soc(pct)
                f.homes[n].log("what_if", what="battery_soc", **done[n])
            out["battery_soc"] = {"pct": pct, "homes": names, "set": done}
            f.events.append({"t": time.time(), "kind": "what_if_battery_soc", "pct": pct, "homes": len(names)})
        out["faulted"] = [n for n, h in f.homes.items() if h.adapter.E > 0 and h.adapter.P == 0]
        out["now"] = now
        return out

    @app.get("/demo/clock")
    def demo_clock_get():
        any_home = next(iter(f.homes.values()), None)
        return any_home.replay.clock() if any_home else {}

    @app.post("/demo/clock")
    def demo_clock(body: dict = Body(default={})):
        return f.configure_clock(**body)

    # ---- one base URL per building, http://.../b/<name>: cfg building_urls names it for the community agent (simulator_building.service_url)
    if f.kind == "buildings":
        def node(name: str) -> MemberNode:
            if name not in f.homes:
                raise HTTPException(404, "no such building here")
            return f.homes[name]

        @app.get("/b/{name}/health")
        def b_health(name: str):
            h = node(name)
            return {"ok": True, "ready": f.ready, "agent": name, "adapter": "building", "town": True, "replay": {"now": h.replay.ts(h.replay.current())}, "memory": memory_mb()}

        @app.get("/b/{name}/telemetry")
        def b_telemetry(name: str):
            h = node(name)
            return {"telemetry": h.adapter.tel, "history": list(h.history)[-8:], "limits": h.adapter.limits()}

        @app.get("/b/{name}/v2/status")
        def b_status(name: str):
            h = node(name)
            return {**h.status(), "offers": h.offers, "contracts": h.contracts, "payments": h.payments}

        @app.post("/b/{name}/demo/reset")
        def b_reset(name: str):
            node(name)
            f.reset(only=name)
            replay_mod.set_weather(1.0, 1.0, dT=0.0)      # a what-if here is the process's: this is the only reset a run's start sends the buildings
            return {"ok": True, "home": name}

        @app.get("/b/{name}/demo/clock")
        def b_clock_get(name: str):
            return node(name).replay.clock()

        @app.post("/b/{name}/demo/clock")
        def b_clock(name: str, body: dict = Body(default={})):
            node(name)
            return f.configure_clock(only=name, **body)

        @app.post("/b/{name}/demo/scenario")
        def b_scenario(name: str, body: dict = Body(default={})):
            node(name)
            ov = body.get("override")
            if isinstance(ov, dict):
                body = {**body, "override": {**ov, "home": name}}
            for k in ("closed", "zone_event"):
                if isinstance(body.get(k), dict):
                    body = {**body, k: {**body[k], "home": name}}
            return demo_scenario(body)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(prog="murmur-host")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--buildings", action="store_true", help="run the building nodes instead of the homes")
    a = ap.parse_args()
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    f = (BuildingHost if a.buildings else NodeHost)(a.limit)
    if not f.cfg.get("person_keys"):
        log.warning("no person's key is on file here, so nobody can end an alarm on these nodes: python -m murmur.node.person says how")
    f.person_back()                                       # an alarm or a person's limit on file holds from the start
    f.start()
    uvicorn.run(build_app(f), host=f.cfg["bind_host"], port=int(f.cfg[f.port_key]), log_level="warning")


if __name__ == "__main__":
    main()

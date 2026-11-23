"""One evening on a running stack: the clock told its gates and stops and started, the buyers' orders, the community's meter fed
every quarter hour, the surprises posted at their steps, and the run followed until the money is final.

The community agent's clock plays the evening (its /demo/start and /demo/conductor doors). The runner tells it what it cannot know
by itself: the gates, steps it stops before until the runner has posted what happens there (the buyers' orders before the step
they are asked at, each configured event at its own, and the evening's last step); and the stops, the steps the aggregator's
requests go at, which a clock that leaps must play. It starts the clock at the configuration's pace and holds it once the money
is final.

The community's meter is the evening's base load (its feed) plus what the homes and the buildings draw, read from their hosts'
telemetry: a quarter hour is fed once every member has reported it, and after a clock that moved many at once every one it moved
over. A step waits for its reading (the community's clock_wait_meter), so the hosts are read as often as the pace needs.

The run's summary is written to summary.json in the run folder, and every message the bus accepted to record.json.gz beside it
(compare.py reads both).
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx

from .stack import AGGREGATOR, COMMUNITY, IDLE_S, Stack

PRICE_USD_KWH, DEPOSIT_SHARE = 2.04, 0.10
TS = "%Y-%m-%d %H:%M"
STEP_MIN = 15
LEAD_S = 1.0                   # the clock's first step is looked at this long after the start: the least the community takes. The orders' gate holds it, not this
FAST_S, SLOW_S = 0.05, 0.25    # between two looks at the hosts' telemetry, and at the clock: an eighth of the pace, never outside these
STALL_S = IDLE_S + 300.0       # a run in which nothing new is said for a step's pace and this long is given up: the clock itself goes on after IDLE_S of the same waits
RECORD = "record.json.gz"      # every message the bus accepted and every ack, as the bus gave them at the end of the run
SAID = ("now", "mode", "pace_s", "leap", "leap_max_steps", "steps", "held_s", "went_on")      # what the summary keeps of the clock's last answer, beside its leaps and played steps


def day_after(date: str) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def add_minutes(ts: str, minutes: int) -> str:
    return (datetime.strptime(ts[:16], TS) + timedelta(minutes=minutes)).strftime(TS)


def clock_starts(date: str) -> str:
    """Where the community agent starts an evening's clock: 09:45 the day before (its /demo/start)."""
    return add_minutes(f"{date} 09:45", -1440)


def ends(evening: dict[str, Any]) -> str:
    """The evening's last step: 03:00 the morning after, or the quarter hour after its feed's last row when that comes first. A step past
    the feed would wait for a meter reading nobody has."""
    last = f"{day_after(evening['date'])} 03:00"
    return min(last, add_minutes(max(evening["feed"]), STEP_MIN)) if evening.get("feed") else last


def stops(evening: dict[str, Any], sites: dict[str, Any]) -> list[str]:
    """The steps the clock must play that only the runner knows of: the step each request of the aggregator goes at (the evening's
    battery request and each site's: the first quarter hour at or after its made_at) and the quarter hour after it, when its answer
    is acted on. A clock that leaps lands on each. Only steps of this evening's clock: after its start, before its end."""
    asked = ([evening["battery_request"]] if evening.get("battery_request") else []) + [r for sp in sites.values() for r in sp.get("requests") or []]
    out: set[str] = set()
    for r in asked:
        made = datetime.strptime(str(r["made_at"])[:16], TS)
        at = (made + timedelta(minutes=-made.minute % STEP_MIN)).strftime(TS)
        out |= {at, add_minutes(at, STEP_MIN)}
    return sorted(t for t in out if clock_starts(evening["date"]) < t < ends(evening))


class Evening:
    """One evening on the stack's parts. `http` is what reaches them (an httpx client's get and post) and `wall` the wall clock: a test
    puts its own in their place."""

    def __init__(self, stack: Stack, say: Callable[..., None] = print, http: Any = None, wall: Callable[[], float] = time.time):
        self.k, self.s, self.say, self.wall = stack, stack.s, say, wall
        self.http = httpx.Client(timeout=20) if http is None else http
        self.pending = self.gates()
        self.more_stops: list[str] = []                  # steps a driver of its own (the presenter's console) wants played too
        self.asked_at = add_minutes(clock_starts(self.s.evening["date"]), STEP_MIN)       # the step the buyers are asked for their orders: the clock's first move
        self.end = ends(self.s.evening)
        self.every = max(FAST_S, min(SLOW_S, self.s.pace_s / 8))
        self.hosts = ["homes"] + (["buildings"] if self.s.buildings else [])
        self.members = self.s.homes + self.s.buildings
        self.seen: dict[str, dict[str, float]] = {m: {} for m in self.members}           # member -> quarter hour -> what it draws beyond its no-sale twin, kW
        self.since = add_minutes(clock_starts(self.s.evening["date"]), -STEP_MIN)         # the hosts are asked for every row after this: the last quarter hour fed
        self.fed: dict[str, dict[str, float]] = {}
        self.halt = threading.Event()
        self.errors: list[str] = []
        self.t0: float | None = None                     # the wall time the evening was started
        self.holding = False                             # the clock was told to hold: the money is final
        self.line: tuple | None = None                   # the sale's phase and counts as last said
        self.last: tuple | None = None                   # what the clock and the sale last said, and since when: a run that says nothing new is given up
        self.changed = 0.0
        self.leaps: dict[tuple[str, str], dict[str, Any]] = {}       # every leap and every played step the clock told of. It keeps its last 50 of each
        self.played: dict[str, dict[str, Any]] = {}
        self.clock: dict[str, Any] = {}                  # the clock's last answer

    def post(self, part: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.http.post(self.k.url[part] + path, json=body)
        r.raise_for_status()
        return r.json()

    def get(self, part: str, path: str) -> Any:
        r = self.http.get(self.k.url[part] + path)
        r.raise_for_status()
        return r.json()

    def orders(self) -> list[dict[str, Any]]:
        """Each buyer's order for the evening's window, at the evening's price, with a deposit of a tenth of what it could pay."""
        e = self.s.evening
        start, end = e["window"]
        hours = (int(end[:2]) * 60 + int(end[3:]) - int(start[:2]) * 60 - int(start[3:])) / 60
        price = float(e.get("price_usd_per_kwh", PRICE_USD_KWH))
        return [{"to": buyer, "date": e["date"], "start": start, "end": end, "kw": kw, "price_usd_per_kwh": price, "note": "demo run",
                 "buyer": f"demo runner ({buyer})", "deposit_usd": round(DEPOSIT_SHARE * price * kw * hours, 2)} for buyer, kw in e["order_kw"].items()]

    def gates(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for e in self.s.events:
            out.setdefault(e["at"], []).append(e)
        return out

    # ------------------------------------------------------------------ the start
    def start(self) -> dict[str, Any]:
        """Starts the evening's clock. Its gates and stops are named first, and stay through the start: the clock cannot reach the step the
        buyers are asked at before their orders are placed, however fast it runs."""
        self.t0 = self.wall()
        for b in self.s.buyers:
            self.post(b, "/demo/reset", {"clear_orders": True})
        self.post(COMMUNITY, "/demo/conductor", {"gates": sorted({self.asked_at, self.end, *self.pending}),
                                                 "stops": sorted(set(stops(self.s.evening, self.s.sites)) | set(self.more_stops))})
        st = self.post(COMMUNITY, "/demo/start", {"event": self.s.evening["date"], "step_seconds": self.s.step_seconds, "pace_s": self.s.pace_s, "force": True, "lead_s": LEAD_S})
        lost = {k: v for k, v in st["agents"].items() if str(v).startswith("not reached") and not k.startswith("home-")}
        if lost:
            raise RuntimeError(f"not every part took the clock: {lost}")
        for order in self.orders():
            self.post(order["to"], "/needs", order)
        if self.asked_at not in self.pending:             # an event configured at that step opens it when the clock stands there (look)
            self.post(COMMUNITY, "/demo/conductor", {"open": self.asked_at})
        threading.Thread(target=self.meter, daemon=True, name="meter").start()
        return st

    # ------------------------------------------------------------------ the community's meter
    def meter(self) -> None:
        """Until the run is halted: the hosts are read and what is ready is fed, an eighth of the pace apart."""
        while not self.halt.wait(self.every):
            try:
                self.meter_pass()
            except Exception as exc:                       # the next pass tries again; the summary keeps the first faults
                if len(self.errors) < 40:
                    self.errors.append(f"{time.strftime('%H:%M:%S')} {type(exc).__name__}: {str(exc)[:160]}")

    def meter_pass(self) -> int:
        """One reading of the hosts' telemetry. Every quarter hour of the feed that every member has reported by now, and that is not fed
        yet, is fed, oldest first: after a clock that moved many quarter hours at once that is each of them, since the hosts give back
        every row after the last one fed. A row dated after its host's own clock is not this evening's (a clock that ran before the start
        left it) and is not taken. How many quarter hours it fed."""
        feed = self.s.evening["feed"]
        for host in self.hosts:
            t = self.get(host, f"/telemetry?since={self.since}")
            keys = t["keys"]
            ig, ic, its = keys.index("grid_kw"), keys.index("grid_cf_kw"), keys.index("ts")
            now = str(t.get("now") or "")[:16]
            for m in self.members:
                for v in [t["homes"].get(m)] + list((t.get("recent") or {}).get(m) or []):
                    if v and v[its] and str(v[its])[:16] <= now and v[ig] is not None and v[ic] is not None:
                        self.seen[m][str(v[its])[:16]] = float(v[ig]) - float(v[ic])
        ready = sorted(q for q in feed if q not in self.fed and all(q in self.seen[m] for m in self.members))
        if not ready:
            return 0
        rows, fed = [], {}
        for q in ready:
            homes = round(sum(self.seen[m][q] for m in self.s.homes), 3)
            buildings = round(sum(self.seen[m][q] for m in self.s.buildings), 3)
            fed[q] = {"homes_kw": homes, "buildings_kw": buildings}
            rows.append({"ts": q, "meter_kw": round(feed[q]["base_kw"] + homes + buildings, 3), "soc_pct": feed[q]["soc_pct"],
                         "price_usd_kwh": feed[q]["price_usd_kwh"]})
        self.post(COMMUNITY, "/v2/community/feed", {"rows": rows})
        self.fed.update(fed)
        self.since = ready[-1]
        return len(ready)

    # ------------------------------------------------------------------ surprises
    def post_events(self, at: str, events: list[dict[str, Any]]) -> None:
        for e in events:
            kind, who = e["kind"], e.get("homes") or []
            if kind == "cloud":
                for host in self.hosts:
                    self.post(host, "/demo/scenario", {"weather": {"pv": e["pv"], "from": at, "hours": e["hours"]}})
            elif kind == "building_closed":
                for b in who:
                    self.post("buildings", f"/b/{b}/demo/scenario", {"closed": {"at": at}})
            elif kind == "zone_event":
                for b in who:
                    self.post("buildings", f"/b/{b}/demo/scenario", {"zone_event": {"at": at, "share": e["share"], "hours": e["hours"]}})
            elif kind in ("note", "car_now"):
                for h in who:
                    value = e["text"] if kind == "note" else True
                    self.post("homes", "/demo/scenario", {"override": {"home": h, "kind": "note" if kind == "note" else "ev_now", "value": value,
                                                                       "source": "owner's phone"}})
            else:
                self.post(e["buyer"], "/alert", {"kw": e["kw"], "minutes": e["minutes"], "why": e.get("why", "grid emergency"), "at": at})
            self.say(f"{at} {kind} {who or ''}")

    # ------------------------------------------------------------------ until the money is final
    def follow(self) -> str:
        """Looks at the run until it has ended, and says how: as often as the meter is read, so a gate costs a fast clock no more than a
        twentieth of a second."""
        while True:
            ended = self.look()
            if ended:
                return ended
            time.sleep(self.every)

    def look(self) -> str | None:
        """One look at the clock and the sale: how the evening ended, or None while it goes on.

        A gate the clock stands at is answered at once: what was configured for that step is posted, and the gate opened. The evening
        ends `settled` once the sale is done with no reading missing and the clock, told to hold there, has finished the step in hand:
        every part has caught up with it and nothing is on its way, by the clock's own word. It ends at once on a sale that failed or
        found no offer; where the clock stands before the evening's last step, or on the last step of the data (`settled, with an alarm
        standing` when the sale is done, else `not settled`); and `timed out` when neither the clock nor the sale has said anything new
        for a step's pace and STALL_S more."""
        if self.k.stopped():
            raise RuntimeError(f"stopped: {self.k.stopped()}")
        c = self.clock = self.get(COMMUNITY, "/demo/conductor")
        self.leaps.update({(x["from"], x["to"]): x for x in c.get("leaps") or []})
        self.played.update({x["sim"]: x for x in c.get("played") or []})
        gate, stands = c.get("at_gate"), c.get("mode") in ("held", "at_gate", "ended")
        if gate and gate in self.pending:
            self.post_events(gate, self.pending.pop(gate))
            self.post(COMMUNITY, "/demo/conductor", {"open": gate})
        s = self.get(COMMUNITY, "/v2/summary")
        ev = next(iter((s.get("events") or {}).values()), None) or {}
        line = (ev.get("phase"), ev.get("offers"), ev.get("accepted"), ev.get("readings"))
        if line != self.line:
            self.say(f"{s.get('now') or ''} phase {line[0]} offers {line[1]} accepted {line[2]} readings {line[3]}")
            self.line = line
        if ev.get("phase") in ("failed", "no_offer"):
            return ev["phase"]
        done = ev.get("phase") == "done"
        if done and not ev.get("readings_missing"):
            if self.holding and stands:
                return "settled"
            if not self.holding:                          # the money is final: the clock stops once the step in hand is finished
                self.post(COMMUNITY, "/demo/conductor", {"hold": True})
                self.holding = True
        elif gate == self.end or c.get("mode") == "ended":
            return "settled, with an alarm standing" if done else "not settled"
        said, t = (c.get("now"), c.get("mode"), c.get("steps"), tuple(c.get("waiting_on") or ()), line), self.wall()
        if said != self.last:
            self.last, self.changed = said, t
        elif t - self.changed > self.s.pace_s + STALL_S:
            return "timed out"
        return None

    def read(self, part: str, path: str) -> Any:
        """A part's answer for the summary, or the fault that kept it away."""
        try:
            return self.get(part, path)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}

    def summary(self, ended: str) -> dict[str, Any]:
        """Ends the meter, and writes what the evening came to: summary.json (how it ended, the sale as the community holds it, the
        aggregator's view, the bus's counts, and the clock: the steps it moved, its leaps and played steps, the seconds it held beyond
        the pace, and the wall seconds from the start to now) and beside it the bus record whole, record.json.gz."""
        self.halt.set()
        wall_s = None if self.t0 is None else round(self.wall() - self.t0, 1)
        clock = self.read(COMMUNITY, "/demo/conductor")
        if "error" not in clock:
            self.clock = clock
            self.leaps.update({(x["from"], x["to"]): x for x in clock.get("leaps") or []})
            self.played.update({x["sim"]: x for x in clock.get("played") or []})
        out: dict[str, Any] = {"run": self.s.run, "date": self.s.evening["date"], "window": self.s.evening["window"], "ended": ended,
                               "ports": self.k.port, "meter_rows_fed": len(self.fed), "meter_errors": self.errors,
                               "clock": {**{k: self.clock.get(k) for k in SAID}, "leaps": list(self.leaps.values()), "played": list(self.played.values()), "wall_s": wall_s},
                               "community": self.read(COMMUNITY, "/v2/summary"), "aggregator": self.read(AGGREGATOR, "/aggregator")}
        record = self.read("bus", f"/runs/{self.s.run}/record")
        events = record.get("events") or []
        if "error" not in record:
            with gzip.open(self.s.folder / RECORD, "wt", encoding="utf-8") as f:
                json.dump(record, f, separators=(",", ":"))
        kinds: dict[str, int] = {}
        for e in events:
            if e.get("event") == "accepted":
                kinds[str(e.get("kind"))] = kinds.get(str(e.get("kind")), 0) + 1
        out["bus"] = {"messages": sum(kinds.values()), "by_kind": kinds, "acks": sum(1 for e in events if e.get("event") == "ack"), **{k: v for k, v in record.items() if k == "error"}}
        (self.s.folder / "summary.json").write_text(json.dumps(out, indent=1, default=str))
        return out

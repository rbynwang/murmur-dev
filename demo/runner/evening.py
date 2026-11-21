"""One evening on a running stack: the clock started and held at each step until the network has finished it, the buyers' orders,
the community's meter fed every quarter hour, the surprises posted at their steps, and the run followed until the money is final.

The community's meter is the evening's base load (its feed) plus what the homes and the buildings draw, read from their hosts'
telemetry: a quarter hour is fed once every member has reported it. The summary of the run is written to summary.json in the
run folder.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from .stack import AGGREGATOR, COMMUNITY, Stack

PRICE_USD_KWH, DEPOSIT_SHARE = 2.04, 0.10


def day_after(date: str) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


class Evening:
    def __init__(self, stack: Stack, say=print):
        self.k, self.s, self.say = stack, stack.s, say
        self.http = httpx.Client(timeout=20)
        self.pending = self.gates()
        self.fed: dict[str, dict[str, float]] = {}
        self.halt = threading.Event()
        self.errors: list[str] = []

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
        for b in self.s.buyers:
            self.post(b, "/demo/reset", {"clear_orders": True})
        self.post(COMMUNITY, "/demo/conductor", {"gates": sorted(self.pending)})
        st = self.post(COMMUNITY, "/demo/start", {"event": self.s.evening["date"], "step_seconds": self.s.step_seconds, "force": True, "lead_s": 6})
        lost = {k: v for k, v in st["agents"].items() if str(v).startswith("not reached") and not k.startswith("home-")}
        if lost:
            raise RuntimeError(f"not every part took the clock: {lost}")
        for order in self.orders():
            self.post(order["to"], "/needs", order)
        threading.Thread(target=self.meter, daemon=True, name="meter").start()
        return st

    # ------------------------------------------------------------------ the community's meter
    def meter(self) -> None:
        feed, members = self.s.evening["feed"], self.s.homes + self.s.buildings
        seen: dict[str, dict[str, float]] = {m: {} for m in members}
        since = ""
        hosts = ["homes"] + (["buildings"] if self.s.buildings else [])
        while not self.halt.is_set():
            time.sleep(0.25)
            try:
                now = ""
                for host in hosts:
                    t = self.get(host, "/telemetry" + (f"?since={since}" if since else ""))
                    keys = t["keys"]
                    ig, ic, its = keys.index("grid_kw"), keys.index("grid_cf_kw"), keys.index("ts")
                    stamp = str(t.get("now") or "")[:16]
                    now = min(now, stamp) if now else stamp
                    for m in members:
                        for v in [t["homes"].get(m)] + list((t.get("recent") or {}).get(m) or []):
                            if v and v[its] and v[ig] is not None and v[ic] is not None:
                                seen[m][str(v[its])[:16]] = float(v[ig]) - float(v[ic])
                ready = sorted(q for q in feed if q <= now and q not in self.fed and all(q in seen[m] for m in members))
                if not ready:
                    continue
                rows = []
                for q in ready:
                    homes = round(sum(seen[m][q] for m in self.s.homes), 3)
                    buildings = round(sum(seen[m][q] for m in self.s.buildings), 3)
                    self.fed[q] = {"homes_kw": homes, "buildings_kw": buildings}
                    rows.append({"ts": q, "meter_kw": round(feed[q]["base_kw"] + homes + buildings, 3), "soc_pct": feed[q]["soc_pct"],
                                 "price_usd_kwh": feed[q]["price_usd_kwh"]})
                self.post(COMMUNITY, "/v2/community/feed", {"rows": rows})
                since = ready[-1]
            except Exception as exc:                       # the next pass tries again; the summary keeps the first faults
                if len(self.errors) < 40:
                    self.errors.append(f"{time.strftime('%H:%M:%S')} {type(exc).__name__}: {str(exc)[:160]}")

    # ------------------------------------------------------------------ surprises
    def post_events(self, at: str, events: list[dict[str, Any]]) -> None:
        for e in events:
            kind, who = e["kind"], e.get("homes") or []
            if kind == "cloud":
                for host in ["homes"] + (["buildings"] if self.s.buildings else []):
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
    def follow(self, wall_limit_s: float | None = None) -> str:
        limit = time.time() + (wall_limit_s or 170 * self.s.step_seconds + 900)
        end = f"{day_after(self.s.evening['date'])} 03:00"
        seen, settled_at = None, None
        while time.time() < limit:
            time.sleep(0.5)
            if self.k.stopped():
                raise RuntimeError(f"stopped: {self.k.stopped()}")
            gate = self.get(COMMUNITY, "/demo/conductor").get("at_gate")
            if gate and gate in self.pending:
                self.post_events(gate, self.pending.pop(gate))
                self.post(COMMUNITY, "/demo/conductor", {"open": gate})
            s = self.get(COMMUNITY, "/v2/summary")
            now = s.get("now") or ""
            ev = next(iter((s.get("events") or {}).values()), None) or {}
            line = (ev.get("phase"), ev.get("offers"), ev.get("accepted"), ev.get("readings"))
            if line != seen:
                self.say(f"{now} phase {line[0]} offers {line[1]} accepted {line[2]} readings {line[3]}")
                seen = line
            if ev.get("phase") in ("failed", "no_offer"):
                return ev["phase"]
            if ev.get("phase") == "done":
                settled_at = settled_at or time.time()
                if time.time() - settled_at >= 8 * self.s.step_seconds and not ev.get("readings_missing"):
                    return "settled"
            if now >= end:
                return "settled, with an alarm standing" if ev.get("phase") == "done" else "not settled"
        return "timed out"

    def summary(self, ended: str) -> dict[str, Any]:
        self.halt.set()
        out: dict[str, Any] = {"run": self.s.run, "date": self.s.evening["date"], "window": self.s.evening["window"], "ended": ended,
                               "ports": self.k.port, "meter_rows_fed": len(self.fed), "meter_errors": self.errors}
        for key, part, path in (("community", COMMUNITY, "/v2/summary"), ("aggregator", AGGREGATOR, "/aggregator"), ("bus", "bus", f"/runs/{self.s.run}/record")):
            try:
                out[key] = self.get(part, path)
            except Exception as exc:
                out[key] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        record = out.get("bus") or {}
        events = record.get("events") or []
        kinds: dict[str, int] = {}
        for e in events:
            if e.get("event") == "accepted":
                kinds[str(e.get("kind"))] = kinds.get(str(e.get("kind")), 0) + 1
        out["bus"] = {"messages": sum(kinds.values()), "by_kind": kinds, "acks": sum(1 for e in events if e.get("event") == "ack")}
        (self.s.folder / "summary.json").write_text(json.dumps(out, indent=1, default=str))
        return out

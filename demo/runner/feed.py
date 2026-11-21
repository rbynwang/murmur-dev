"""The read-only state feed of a running demo: GET /live/state.json, the network's state in the schema the two-view page's Live
view reads (murmur.live.v1), served with CORS open so that a page opened from a file may read it.

It only reads: each part's /health, the community's /v2/summary and the buyers' /contracts, every few seconds. It sends nothing
to any part and changes nothing.

  python -m demo.runner feed --run FOLDER [--host H] [--port 0]   prints "listening on PORT"; then open the page with ?live=http://H:PORT
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import httpx

from murmur import files

SCHEMA = "murmur.live.v1"
EVERY_S = 5
PATH = "/live/state.json"


def part(answer: dict[str, Any] | None, seen: float, now: float, current: bool | None, **more: Any) -> dict[str, Any]:
    return {"up": answer is not None, "seen_s": round(now - seen) if seen else None, "current": current, **more}


def most(x: Any) -> float | None:
    """The largest half hour of a by-slot figure ({slot: kW} or a list), or the figure itself."""
    vals = list(x.values()) if isinstance(x, dict) else list(x) if isinstance(x, list) else [x]
    vals = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(max(vals), 1) if vals else None


def event_of(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    ev = next(iter(((summary or {}).get("events") or {}).values()), None)
    if not ev:
        return None
    return {"phase": ev.get("phase"), "window": ev.get("window"), "asked_kw": most(ev.get("kw_requested") or []),
            "half_hours": len(ev.get("kw_requested") or []), "offers": ev.get("offers"), "accepted": ev.get("accepted"),
            "declined": ev.get("declined"), "offered_kw": most(ev.get("capacity_offered_kw")), "readings": ev.get("readings"),
            "readings_expected": ev.get("readings_expected"), "buyers": len(ev.get("buyers") or []) or None,
            "paid_nodes": None, "income_usd": None}


def state(answers: dict[str, Any], seen: dict[str, float], code: str, now: float) -> dict[str, Any]:
    """The feed's state from the parts' last answers (None for a part that did not answer)."""
    def current(name: str) -> bool | None:
        h = answers.get(name)
        return None if not h or not h.get("code") else h.get("code") == code

    def first(prefix: str) -> str | None:
        return next((n for n in answers if n.startswith(prefix)), None)
    summary = answers.get("summary")
    dc = first("site-dc-")
    parts = {"town": part(answers.get("bus"), seen.get("bus", 0), now, None),
             "aggregator": part(answers.get("aggregator"), seen.get("aggregator", 0), now, current("aggregator")),
             "community": part(answers.get("community"), seen.get("community", 0), now, current("community"),
                               ready=bool((answers.get("community") or {}).get("ready")), nodes=(summary or {}).get("roster")),
             "homes": part(answers.get("homes"), seen.get("homes", 0), now, current("homes"), ready=answers.get("homes") is not None,
                           count=len(answers.get("homes_names") or [])),
             "buildings": part(answers.get("buildings"), seen.get("buildings", 0), now, current("buildings"), ready=answers.get("buildings") is not None,
                               count=len(answers.get("buildings_names") or [])),
             "datacenter": part(answers.get(dc) if dc else None, seen.get(dc or "", 0), now, current(dc) if dc else None),
             "buyer_utility": part(answers.get("utility"), seen.get("utility", 0), now, current("utility"), contracts=answers.get("utility_contracts")),
             "buyer_grid": part(answers.get("grid-operator"), seen.get("grid-operator", 0), now, current("grid-operator"),
                                contracts=answers.get("grid-operator_contracts")),
             "model": part(answers.get("model"), seen.get("model", 0), now, None)}
    ev = event_of(summary)
    return {"schema": SCHEMA, "at": int(now), "every_s": EVERY_S, "clock": (summary or {}).get("now"), "parts": parts, "event": ev,
            "events": len((summary or {}).get("events") or {})}


class Watcher:
    """Reads the parts of the run in `folder` (its summary of ports in run.json) every EVERY_S seconds."""

    def __init__(self, folder: Path, get: Callable[[str], Any] | None = None):
        run = json.loads((Path(folder) / "run.json").read_text())
        self.url, self.homes, self.buildings = run["urls"], run["homes"], run["buildings"]
        self.http = httpx.Client(timeout=3)
        self.get = get or (lambda url: self.http.get(url).json())
        self.code = files.code_stamp()
        self.answers: dict[str, Any] = {}
        self.seen: dict[str, float] = {}
        self.lock = threading.Lock()

    def read(self) -> None:
        got: dict[str, Any] = {"homes_names": self.homes, "buildings_names": self.buildings}
        paths = {name: "/health" for name in self.url if name not in ("feed", "model")} | {"model": "/"}
        for name, path in paths.items():
            try:
                got[name] = self.get(self.url[name] + path)
                self.seen[name] = time.time()
            except Exception:
                got[name] = None
        try:
            got["summary"] = self.get(self.url["community"] + "/v2/summary")
        except Exception:
            got["summary"] = None
        for buyer in ("utility", "grid-operator"):
            if buyer in self.url:
                try:
                    got[f"{buyer}_contracts"] = len(self.get(self.url[buyer] + "/contracts").get("contracts") or [])
                except Exception:
                    got[f"{buyer}_contracts"] = None
        with self.lock:
            self.answers = got

    def text(self) -> str:
        with self.lock:
            return json.dumps(state(self.answers, self.seen, self.code, time.time()))

    def loop(self) -> None:
        while True:
            self.read()
            time.sleep(EVERY_S)


class _Answer(BaseHTTPRequestHandler):
    server: Any

    def do_GET(self) -> None:
        found = self.path.split("?")[0] == PATH
        body = self.server.watcher.text().encode() if found else b""
        self.send_response(200 if found else 404)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return


def serve(folder: Path, port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Starts the feed for the run in `folder` on `host` (port 0: a free one) and returns its server, already serving."""
    srv = ThreadingHTTPServer((host, port), _Answer)
    srv.daemon_threads = True
    srv.watcher = Watcher(folder)
    srv.watcher.read()
    threading.Thread(target=srv.watcher.loop, daemon=True, name="feed-read").start()
    threading.Thread(target=srv.serve_forever, daemon=True, name="feed-serve").start()
    return srv

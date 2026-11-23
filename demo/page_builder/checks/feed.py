"""Made-up live feeds, served on a free port of this computer while a check runs, and an address where nothing answers.

The two-view page's live mode asks `<base>/live/state.json` for the network's state. A served feed answers that address for
each base path it knows, with CORS open so a page opened from a file may read it; every other address answers 404. The states
are made up. In the first form (schema murmur.live.v1) they name every part of a network the Live view can light. Asked with
`?since=N`, an evening (feed_v2.py) adds the second form: the moments after N with their steps, the clock and the timeline.
A made-up console serves the page itself, an evening's feed and the two console addresses, behind the real console's door
rules, and keeps every command it is given.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import re
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs

from .. import names as N
from . import feed_v2

STATE = "/live/state.json"
KEY_HEADER = "X-Murmur-Console"
LIMIT = 4096                    # the longest command a console takes, in bytes
ALWAYS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
ROUTES = {"/": "GET", STATE: "GET", "/console/state": "GET", "/console/do": "POST"}
Feeds = dict[str, Any]          # base path to a function giving the state's text, or to a feed_v2 evening, asked by cursor


def part(up: bool = True, current: bool | None = True, **more: object) -> dict:
    """One part of the network as the feed reports it: answering, seen a second ago, on current code."""
    return {"up": up, "seen_s": 1, "current": current, **more}


def network(asked_kw: float = 136.0, offered_kw: float = 110.0, **event: object) -> dict:
    """A whole network answering, every part on current code, with a request open whose window holds the network's clock."""
    return {"schema": "murmur.live.v1", "at": int(time.time()), "every_s": 5, "clock": "2025-01-28 18:20",
            "parts": {"town": part(current=None), "aggregator": part(current=None), "community": part(ready=True, nodes=10),
                      "homes": part(ready=True, count=8), "buildings": part(ready=True, count=2),
                      "datacenter": part(current=None), "buyer_utility": part(contracts=1), "buyer_grid": part(contracts=1),
                      "model": part(current=None, waiting=1)},
            "event": {"phase": "confirming", "window": ["2025-01-28 18:00", "2025-01-28 21:00"], "asked_kw": asked_kw,
                      "half_hours": 6, "offers": 10, "accepted": 10, "declined": 0, "offered_kw": offered_kw, "readings": 12,
                      "readings_expected": 60, "buyers": 2, "paid_nodes": None, "income_usd": None, **event},
            "events": 1}


def every_box_lit() -> str:
    """The state the fit check shows: every box the Live view can light is lit, and the request names every buyer's order."""
    return json.dumps(network(asked_kw=135.5, offered_kw=107.8, asked_all=True))


def evening_v2(out: int | None = None, speed: str = "1") -> feed_v2.Evening:
    """The made-up evening (live_evening.json), answered by cursor: asked with ?since=N it adds the second form, asked without
    it gives the first-form state as before. out: how many of its twelve moments have happened (all of them when None)."""
    return feed_v2.evening(network, out, speed)


def hostile_v2(per: int = 1, only: str = "") -> feed_v2.Hostile:
    """The hostile evening: every case of hostile.json, each between two good moments, `per` moments an answer, every answer
    saying there is more. only: one case by name."""
    return feed_v2.Hostile(network, per, only)


def text_of(make: Any, query: str) -> str:
    """A feed's answer: an evening is asked with the address's query, a plain feed is called."""
    return make.text(query) if isinstance(make, feed_v2.Evening) else make()


class _Answer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        make = self.server.feeds.get(path.removesuffix(STATE)) if path.endswith(STATE) else None
        body = text_of(make, query).encode() if make else b""
        self.send_response(200 if make else 404)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@contextmanager
def serve(feeds: Feeds) -> Iterator[str]:
    """Serve `feeds` (base path, such as "/ok", to a function giving the state's text or to an evening) on 127.0.0.1 at a port
    the system picks, for as long as the block runs. Yields the server's address, "http://127.0.0.1:PORT"."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    srv.feeds = feeds
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def silent() -> str:
    """An address on this computer where nothing listens: a port the system hands out and takes back at once, so a page that
    asks it is refused straight away (as a feed that is down refuses), not left waiting."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


TAKES = {"hello": (), "start": ("run_to",), "hold": (), "go": (), "step": (), "run_to": ("ts",), "pace": ("speed",), "surprise": ("kind",)}
WHO = {"note": "home", "car_now": "home", "building_closed": "building", "building_need": "building", "battery_fault": "battery",
       "battery_low": "battery"}
NUMBERS = {"weather": {"pv": (0, 1), "load": (0.5, 2), "dT": (-10, 10), "hours": (0.5, 24)},        # a field's least and most
           "building_need": {"share": (0.05, 1), "hours": (0.5, 6)}, "emergency": {"kw": (1, 2000), "minutes": (15, 240)},
           "battery_low": {"pct": (5, 100)}}
OTHER = {"note": ("text",), "emergency": ("buyer",), "battery_fault": ("on",)}
KINDS = ("note", "car_now", "weather", "building_closed", "building_need", "emergency", "battery_fault", "battery_low")
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:(00|15|30|45)")
NO_BATTERY = ("home-03", "home-08")


class Console:
    """A made-up console's state (murmur.console.v1) over an evening of its own, not yet started: its feed answers in the
    first form alone until a start. It follows the commands it takes: start (a new run, none of its moments out; with
    run_to as that command too), hold, go, step (the next quarter-hour's moments arrive), run_to (the moments before that
    time arrive, and the clock stands one step before it, held), pace, surprise (a pin at the clock's time). Moments arrive
    by a command or by the check's own `evening.arrive`.

    commands: every command taken, in order. refused: every command refused, with the words. seen: every request that came
    to the door, (method, path, whether it carried a key, the answer's code). words: the sentences of busy, error, warn and
    link, for a check to set. play: for a check to set too ("starting", "failed")."""

    def __init__(self, v1: Callable[[], dict], net: str, label: str):
        self.evening = feed_v2.evening(v1, 0)
        self.net, self.label, self.url, self.key, self.link = net, label, "", "", ""
        self.peer: Console | None = None
        self.play, self.at_gate, self.target = "idle", None, None
        self.words = {"busy": "", "error": "", "warn": "", "link": "The other network answers."}
        self.commands: list[dict[str, Any]] = []
        self.refused: list[tuple[Any, str]] = []
        self.seen: list[tuple[str, str, bool, int]] = []
        homes = [f"home-{i:02d}" for i in range(1, 9)]
        self.roster = {"homes": [{"id": h, "name": N.fixed_name(h), "battery": h not in NO_BATTERY} for h in homes],
                       "buildings": [{"id": b, "name": N.fixed_name(b)} for b in ("building-01", "building-02")],
                       "buyers": ["utility", "grid-operator"]}
        self.ready = self.evening.when(next(p["tq"] for p in self.evening.data["timeline"]["pins"] if p["id"] == "before"))
        self.evening.run = 0

    def over(self) -> bool:
        return self.play in ("running", "held") and self.evening.out == len(self.evening.entries)

    def brief(self) -> dict[str, Any]:
        """This console as its peer shows it."""
        return {"up": True, "key": self.net, "label": self.label, "play": "settled" if self.over() else self.play,
                "clock": self.evening.when(self.evening.tq()), "ready": self.play == "held" and self.at_gate == self.ready, "trouble": ""}

    def state(self) -> dict[str, Any]:
        ev, me = self.evening, self.brief()
        return {"schema": "murmur.console.v1", "play": me["play"], **self.words, "run": ev.run, "clock": me["clock"], "at_gate": self.at_gate,
                "target": self.target, "phase": None if self.play == "idle" else "done" if self.over() else "homes", "messages": 40 * ev.out,
                "rows_up": 25 * ev.out, "speed": ev.speed, "hold": self.play == "held" or self.over(),
                "net": {"key": self.net, "label": self.label, "where": "this computer"}, "other": self.peer.brief() if self.peer else None,
                "peer": {"url": self.peer.url} if self.peer else None, "ready": {"ts": self.ready, "holds": me["ready"]},
                "roster": self.roster, "surprises": list(KINDS)}

    def check(self, said: Any) -> str:
        """Why a command is refused, or nothing: every field checked."""
        do = said.get("do") if isinstance(said, dict) else None
        if not isinstance(do, str) or do not in TAKES:
            return "The console does not know that command."
        kind = said.get("kind")
        if do == "surprise" and not (isinstance(kind, str) and kind in KINDS):
            return "The console does not know that surprise."
        own = (*(("who",) if kind in WHO else ()), *OTHER.get(kind, ()), *NUMBERS.get(kind, ())) if do == "surprise" else ()
        if any(k not in ("do", *TAKES[do], *own) for k in said):
            return "The command carries a field the console does not take."
        ev, play = self.evening, "settled" if self.over() else self.play
        if do == "hello":
            return ""
        if do == "start":
            if play == "starting":
                return "The network is already starting."
            return "" if said.get("run_to") is None else self.time(said["run_to"], ev.when(1))
        if do == "pace":
            good = isinstance(said.get("speed"), str) and said["speed"] in feed_v2.DWELL_MS
            return "" if good else "The speed is one of 0.5, 1, 2, 4 and max."
        if do == "step" and play != "held":
            return "Step works only while the clock is held."
        if play not in ("running", "held") and not (play == "starting" and do in ("hold", "go")):
            return "No evening is running."
        if do == "run_to":
            return self.time(said.get("ts"), ev.when(ev.tq()))
        return self.surprise(kind, said) if do == "surprise" else ""

    def time(self, ts: Any, after: str) -> str:
        """A quarter-hour of the evening later than `after`: nothing, or why not."""
        good = isinstance(ts, str) and TIME.fullmatch(ts) and after < ts <= self.evening.when(self.evening.data["timeline"]["n"])
        try:
            good = good and dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")
        except ValueError:
            good = False
        return "" if good else "The time must be a quarter-hour of this evening, after the clock's."

    def surprise(self, kind: str, said: dict[str, Any]) -> str:
        who, text, on = said.get("who"), said.get("text"), said.get("on")
        if kind in WHO and who is not None:
            side = "buildings" if WHO[kind] == "building" else "homes"
            row = next((r for r in self.roster[side] if r["id"] == who), None) if isinstance(who, str) else None
            if not row or (WHO[kind] == "battery" and not row["battery"]):
                return "That home has no battery." if row else "That home or building is not in this network."
        if text is not None and not (isinstance(text, str) and 1 <= len(text.strip()) <= 200 and text.strip().isprintable()):
            return "The note is one printable line of 1 to 200 characters."
        if said.get("buyer") is not None and said["buyer"] not in self.roster["buyers"]:
            return "That buyer is not in this network."
        if on is not None and not isinstance(on, bool):
            return "On must be true or false."
        for field, (least, most) in NUMBERS.get(kind, {}).items():
            x = said.get(field)
            if x is not None and (isinstance(x, bool) or not isinstance(x, (int, float)) or not least <= x <= most):
                return f"{field} must be a number from {least} to {most}."
        return ""

    def run_to(self, ts: str) -> None:
        ev = self.evening
        stand = (dt.datetime.strptime(ts, "%Y-%m-%d %H:%M") - ev.t0) // dt.timedelta(minutes=15) - 1
        ev.out = max(ev.out, sum(1 for e in ev.entries if e[0] <= stand))
        ev.at, self.play, self.at_gate, self.target = stand, "held", ts, ts

    def do(self, said: Any) -> str:
        """Takes one command and follows it; gives nothing, or the words it is refused with."""
        with self.evening.lock:
            why = self.check(said)
            if why:
                self.refused.append((said, why))
                return why
            self.commands.append(said)
            ev, do = self.evening, said["do"]
            if do == "start":
                ev.new_run(0)
            if do in ("start", "go"):
                self.play, self.at_gate, self.target = "running", None, None
            if do == "hold":
                self.play = "held"
            if do == "step" and ev.out < len(ev.entries):
                ev.arrive(sum(1 for e in ev.entries[ev.out:] if e[0] == ev.entries[ev.out][0]))
            if do == "run_to" or said.get("run_to") is not None:
                self.run_to(said["ts"] if do == "run_to" else said["run_to"])
            if do == "pace":
                ev.speed = said["speed"]
            if do == "surprise":
                ev.pins.append({"tq": ev.tq(), "kind": "surprise", "id": said["kind"]})
            ev.clock.pop("state", None)
            if self.play == "held":
                ev.clock["state"] = "held"
            return ""


class _Door(BaseHTTPRequestHandler):
    """The made-up console's door, by the real console's rules. Every route answers 403 unless Host is one of the door's own
    two names, and so does OPTIONS; another path is 404, another method 405. The two console routes want the key, and a
    command an Origin that is absent or the door's own and a JSON body of at most 4,096 bytes: 202, or 400 with the words."""

    def reply(self, code: int, body: bytes = b"", kind: str = "application/json", more: dict[str, str] | None = None) -> None:
        self.server.console.seen.append((self.command, self.path.partition("?")[0], KEY_HEADER in self.headers, code))
        self.send_response(code)
        for name, value in {**ALWAYS, **(more or {}), **({"Content-Type": kind} if body else {}), "Content-Length": str(len(body))}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def one(self, header: str) -> str | None:
        """A header's value, lower case, when the request carries it once; "" when it carries none, None when several."""
        got = self.headers.get_all(header) or [""]
        return got[0].strip().lower() if len(got) == 1 else None

    def route(self) -> None:
        c: Console = self.server.console
        names = [f"{host}:{self.server.server_address[1]}" for host in ("127.0.0.1", "localhost")]
        size = self.headers.get("Content-Length") or "0"
        body = self.rfile.read(min(int(size), 1 << 20)) if size.isdigit() else b""
        path, _, query = self.path.partition("?")
        if self.one("Host") not in names or self.command == "OPTIONS":
            return self.reply(403)
        if path not in ROUTES:
            return self.reply(404)
        if self.command != ROUTES[path]:
            return self.reply(405, more={"Allow": ROUTES[path]})
        if path == "/" and not parse_qs(query).get("live"):
            return self.reply(302, more={"Location": f"/?live=http://{self.one('Host')}"})
        if path == "/":
            return self.reply(200, self.server.page, "text/html; charset=utf-8")
        if path == STATE:
            return self.reply(200, c.evening.text(query).encode(), more={"Access-Control-Allow-Origin": "*"})
        if not hmac.compare_digest((self.headers.get(KEY_HEADER) or "").encode("utf-8", "replace"), c.key.encode()):
            return self.reply(403)
        if path == "/console/state":
            return self.reply(200, json.dumps(c.state()).encode())
        if self.one("Origin") not in ("", *("http://" + n for n in names)):
            return self.reply(403)
        try:
            why = "The command is longer than 4,096 bytes." if len(body) > LIMIT else c.do(json.loads(body.decode("utf-8")))
        except (ValueError, RecursionError):
            why = "The command is not a JSON object the console can read."
        if why:
            return self.reply(400, json.dumps({"error": why}).encode())
        self.reply(202, json.dumps({"ok": True}).encode())

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = route

    def log_message(self, *args: object) -> None:
        return


@contextmanager
def console(page: Path | str | bytes, key: str) -> Iterator[Console]:
    """A made-up console and its peer, each on a port of 127.0.0.1 the system picks, for as long as the block runs: the page's
    bytes at /, a made-up evening's feed, and /console/state and /console/do behind the key. page: the page file, or its
    bytes. Yields the first console (network "one"); its peer is the second ("standby"). Each has `url`, `link` (the address
    a presenter opens: the page with ?live= and the key after #), `key`, its own `evening`, and the `commands` it took."""
    body = page if isinstance(page, bytes) else Path(page).read_bytes()
    pair = [Console(network, "one", "One computer"), Console(network, "standby", "Stand-by")]
    doors = []
    for c in pair:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Door)
        srv.console, srv.page = c, body
        c.url, c.key = f"http://127.0.0.1:{srv.server_address[1]}", key
        c.link = f"{c.url}/?live={c.url}#k={key}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        doors.append(srv)
    pair[0].peer, pair[1].peer = pair[1], pair[0]
    try:
        yield pair[0]
    finally:
        for srv in doors:
            srv.shutdown()
            srv.server_close()

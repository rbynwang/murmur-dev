"""Made-up live feeds, served on a free port of this computer while a check runs, and an address where nothing answers.

The two-view page's live mode asks `<base>/live/state.json` for the network's state (schema murmur.live.v1). A served feed
answers that address for each base path it knows, with CORS open so a page opened from a file may read it; every other
address answers 404. The states are made up: they name every part of a network the Live view can light.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterator

STATE = "/live/state.json"
Feeds = dict[str, Callable[[], str]]


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


class _Answer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        make = self.server.feeds.get(path.removesuffix(STATE)) if path.endswith(STATE) else None
        body = make().encode() if make else b""
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
    """Serve `feeds` (base path, such as "/ok", to a function giving the state's text) on 127.0.0.1 at a port the system
    picks, for as long as the block runs. Yields the server's address, "http://127.0.0.1:PORT"."""
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

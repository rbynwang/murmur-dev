"""python -m demo.console --config FILE [--page PAGE] [--port N] [--network one] [--peer URL] [--key-file F] [--speed 4] [--follow a,b,c] [--ready]
                         [--loop-days [FILE ...]] [--audience]

Starts the runner's stack of the configuration (every part on this computer), and serves on 127.0.0.1 the page, the live state and
the presenter's door (server.py). The clock runs as fast as the network finishes a step and leaps over empty quarter-hours; the
page sets the pace. The presenter's link, with its key after "#", is printed and written beside the key file. Stops on Ctrl-C, and
stops only what it started.

--loop-days makes it a looping console: the evening starts at once and, 12 seconds after it has settled, the next one starts at
the same speed, for as long as the console runs. At --speed 1 a moment stays on screen 8 seconds, as in the recorded
replay at its 1x; 2 and 4 halve that and halve it again, 0.5 doubles it. The usual speed is 4: a whole evening in about two minutes. With no file it is the same evening again; each file is one more day's configuration,
played after --config's and before the loop begins again (days.py). --audience opens POST /live/surprise, where any viewer of the
page may trigger one of six preset events (crowd.py).
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from . import server
from .commands import SPEEDS
from .days import Days
from .driver import LOOP_SPEED, Driver
from .feed import Log
from .settings import NETS

PAGE = Path(__file__).resolve().parents[1] / "pages" / "index.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo.console", description="the presenter's console: a live evening, its page and its controls")
    ap.add_argument("--config", required=True)
    ap.add_argument("--page", default=str(PAGE))
    ap.add_argument("--port", type=int, default=None, help="where the console listens; else the configuration's feed_port (0: a free one)")
    ap.add_argument("--network", default="one", choices=sorted(NETS))
    ap.add_argument("--peer", default=None, help="the other console of a pair, http://127.0.0.1:PORT/")
    ap.add_argument("--key-file", default=None, help="the presenter's key, made when absent (mode 600); else beside the run folder")
    ap.add_argument("--speed", default=LOOP_SPEED, choices=sorted(SPEEDS))
    ap.add_argument("--follow", default=None, help="the nodes the story follows, by id, comma separated")
    ap.add_argument("--ready", action="store_true", help="start at once and wait an hour before the window, held")
    ap.add_argument("--loop-days", nargs="*", default=None, metavar="FILE",
                    help="play evening after evening, unattended: with no file the same one, else each file's day after --config's")
    ap.add_argument("--audience", action="store_true", help="let any viewer of the page trigger one of six preset events")
    a = ap.parse_args(argv)
    say = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)      # noqa: E731
    days = Days([a.config, *(a.loop_days or [])], say)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):           # a pass is let finish, then every part this console started is stopped
        signal.signal(sig, lambda *_: stop.set())
    try:
        s, k = days.open()
        threading.Thread(target=days.watch, daemon=True, name="feed-read").start()
        log = Log()
        peer = {"url": a.peer} if a.peer else None
        d = Driver(s, k, log, {"key": a.network, "peer": peer}, say, a.follow.split(",") if a.follow else None)
        d.speed, d.crowd.on = a.speed, a.audience
        d.days = days if a.loop_days is not None else None
        key_file = Path(a.key_file) if a.key_file else s.folder.parent / "console.key"
        key = server.read_key(key_file)
        srv = server.serve(s.host, s.feed_port if a.port is None else a.port, a.page, log, d, key, days.v1)
        port = srv.server_address[1]
        link = server.write_link(key_file, port, key)
        say(f"console on http://127.0.0.1:{port}/ ; the presenter's link is in {key_file}.link")
        if a.ready or d.days is not None:
            d.todo.put({"do": "start", "run_to": d.ready() if a.ready else None})
        print(link if sys.stdout.isatty() else "", end="\n" if sys.stdout.isatty() else "", flush=True)
        d.loop(stop)
    finally:
        days.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

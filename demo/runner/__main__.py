"""The demo runner's commands, run from the repository root:

  python -m demo.runner example [--out FOLDER]           writes the synthetic example evening that config.example.json names
  python -m demo.runner evening --config FILE           starts every part, plays the evening to its settlement, writes summary.json
  python -m demo.runner feed --run FOLDER [--port 0]    the read-only state feed of a run that is going on
  python -m demo.runner bus --port PORT --runs FILE     the local message bus on its own (the evening command starts one)

The stand-in model and the stand-in buyers run as their own modules: python -m demo.runner.model, python -m demo.runner.buyers.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def evening(config: str, feed_port: int | None) -> int:
    from . import feed as live
    from .evening import Evening
    from .settings import load
    from .stack import Stack
    s = load(config)
    s.folder.mkdir(parents=True)
    say = lambda *x: print(time.strftime("%H:%M:%S"), *x, flush=True)
    k = Stack(s)
    try:
        k.write()
        k.start()
        srv = live.serve(s.folder, s.feed_port if feed_port is None else feed_port, s.host)
        say(f"parts up; state feed at http://{s.host}:{srv.server_address[1]}{live.PATH}")
        e = Evening(k, say)
        st = e.start()
        say(f"evening {st['event']} from {st['starts_at']}, {st['step_seconds']} s a step")
        ended = e.follow()
        out = e.summary(ended)
        say(f"ended: {ended}; {out['bus']['messages']} messages on the bus; summary in {s.folder / 'summary.json'}")
        return 0 if ended.startswith("settled") else 1
    finally:
        k.stop()


def bus(host: str, port: int, runs: str) -> None:
    import uvicorn
    from .bus import make_bus, runs_from
    uvicorn.run(make_bus(runs_from(json.loads(Path(runs).read_text()))), host=host, port=port, log_level="warning")


def feed(run: str, host: str, port: int) -> None:
    from . import feed as live
    srv = live.serve(Path(run), port, host)
    print(f"listening on {srv.server_address[1]}", flush=True)
    while True:
        time.sleep(3600)


def main() -> int:
    ap = argparse.ArgumentParser(prog="demo.runner", description="a Murmur evening on this computer, every part its own process")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("example", help="write the synthetic example evening")
    ex.add_argument("--out", default="out/example")
    ev = sub.add_parser("evening", help="play one evening to its settlement")
    ev.add_argument("--config", required=True)
    ev.add_argument("--feed-port", type=int, default=None)
    fd = sub.add_parser("feed", help="the read-only state feed of a run")
    fd.add_argument("--run", required=True)
    fd.add_argument("--host", default="127.0.0.1")
    fd.add_argument("--port", type=int, default=0)
    bs = sub.add_parser("bus", help="the local message bus")
    bs.add_argument("--host", default="127.0.0.1")
    bs.add_argument("--port", type=int, required=True)
    bs.add_argument("--runs", required=True)
    a = ap.parse_args()
    if a.cmd == "example":
        from .example import write
        print(write(Path(a.out)))
        return 0
    if a.cmd == "evening":
        return evening(a.config, a.feed_port)
    if a.cmd == "feed":
        feed(a.run, a.host, a.port)
    else:
        bus(a.host, a.port, a.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

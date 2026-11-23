"""Checks Live in the two-view page in a browser, against made-up feeds this check serves itself.

  python -m demo.page_builder.checks.live FOLDER_OR_PAGE [--shots DIR]

A folder: its index.html, the two-view page. The feeds (feed.py: the made-up evening of live_evening.json and the hostile one of
hostile.json) are served on 127.0.0.1 at a port the system picks, for as long as the check runs; nothing else is asked. Checked:

  no_live      without ?live= nothing of Live exists and nothing is asked
  plays        with ?live= of the made-up evening the split view plays its moments: the headline, the cards, the terminal's
               lines, the position, a state word, the timeline with its pins and ticks; a tick shows its moment and Back to live
               follows again; at the seven standard window sizes, 1280x720, 1100x800 and 390x844 nothing in the bar or the
               timeline is cut (but the bar's message, which may be), the bar is not over the layer, and nothing scrolls sideways
  run          a new run of the feed starts the story again
  hostile      a feed that breaks every rule makes no element and runs nothing, and its good moments still play
  says         an address with no answer, one that answers no live state, and one that is no web address each say so in the bar
  asked        the page asks only the state address, and no console door, when it is not on a console

The presenter's controls, the drawer and a real evening are checked against a running console by live_run.py. Exit code 1 when a
check fails.
"""
from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from . import feed
from .browser import WEB, chrome, js, new_window

SIZES = [(1440, 900), (1512, 850), (1512, 920), (1600, 900), (1728, 960), (1920, 950), (1920, 1080), (1280, 720), (1100, 800), (390, 844)]


class Live:
    def __init__(self, browser: Any, page: str, base: str, nothing: str, shots: Path | None):
        self.browser, self.page, self.base, self.nothing, self.shots = browser, page, base, nothing, shots
        self.count, self.fails = 0, []

    def check(self, ok: bool, what: str, seen: Any = "") -> None:
        self.count += 1
        if not ok:
            self.fails.append(what)
            print(f"FAULT {what}: {str(seen)[:300]}")

    def open(self, query: str, size: tuple[int, int] = (1440, 900), wait: int = 3000) -> tuple[Any, Any, list[str], list[str]]:
        errors: list[str] = []
        asked: list[str] = []
        ctx, pg = new_window(self.browser, size, errors, web_feed=self.page.startswith(WEB) and "?live=" in query)
        pg.on("request", lambda r: asked.append(r.url) if r.url.startswith((self.base, self.nothing)) or "/console/" in r.url else None)
        pg.goto(self.page + query)
        pg.wait_for_timeout(wait)
        return ctx, pg, errors, asked

    def no_live(self) -> None:
        ctx, pg, errors, asked = self.open("", wait=1500)
        s = pg.evaluate(js("live.js#state"))
        self.check(not s["tab"] and not s["bar"] and not s["on"], "no_live: nothing of Live without ?live=", s)
        self.check(not asked and not errors, "no_live: nothing asked, no script error", asked + errors)
        ctx.close()

    def plays(self) -> None:
        for size in SIZES:
            ctx, pg, errors, asked = self.open("?live=" + self.base + "/ev", size, wait=6000)
            s = pg.evaluate(js("live.js#state"))
            where = f"plays {size[0]}x{size[1]}"
            self.check(s["on"] and s["tab"] and s["bar"] and s["tl"] > 50, f"{where}: Live is on, with its bar and timeline", s)
            self.check(bool(s["now_h"]) and s["lines"] > 0 and s["pos_n"] > 0, f"{where}: a moment plays in the split view", s)
            self.check(s["pins"] >= 6 and s["ticks"] >= 1 and bool(s["state"]), f"{where}: the timeline's pins and ticks, a state word", s)
            self.check(not s["cut"] and not s["over"] and not s["sideways"], f"{where}: nothing cut, the layer clear, nothing sideways", s)
            self.check(not errors, f"{where}: no script error", errors)
            if size == (1440, 900):
                self.check(s["cards"] > 0 or s["k"] in ("start",), f"{where}: the moment's cards", s)
                pg.evaluate(js("live.js#tick"))
                pg.wait_for_timeout(600)
                t = pg.evaluate(js("live.js#state"))
                self.check(not t["auto"] and t["back"], "plays: a tick shows its moment and stops following", t)
                pg.click(".lv-back")
                pg.wait_for_timeout(600)
                b = pg.evaluate(js("live.js#state"))
                self.check(b["auto"] and b["pos_m"] == b["pos_n"], "plays: Back to live follows the newest moment again", b)
            if self.shots and size in ((1440, 900), (1100, 800), (390, 844)):
                pg.screenshot(path=str(self.shots / f"live_{size[0]}x{size[1]}.png"))
            ctx.close()

    def run_change(self) -> None:
        ev = feed.evening_v2()
        with feed.serve({"/ev": ev}) as base:
            ctx, pg, errors, asked = self.open("?live=" + base + "/ev", wait=4000)
            before = pg.evaluate(js("live.js#state"))
            ev.new_run(out=2)
            pg.wait_for_timeout(5000)
            after = pg.evaluate(js("live.js#state"))
            self.check(after["pos_n"] <= 2 < before["pos_n"] and not errors, "run: a new run starts the story again", [before["pos_n"], after["pos_n"], errors])
            ctx.close()

    def hostile(self) -> None:
        ctx, pg, errors, asked = self.open("?live=" + self.base + "/hostile", wait=9000)
        s = pg.evaluate(js("live.js#state"))
        self.check(s["markup"] == 0 and not s["x"], "hostile: no element made from the feed, nothing run", s)
        self.check(s["pos_n"] > 0, "hostile: its good moments still play", s)
        self.check(not [e for e in errors if "__x" in e or "pageerror" in e.lower()], "hostile: no script error from the feed", errors)
        ctx.close()

    def says(self) -> None:
        for query, words in (("?live=" + self.nothing, "No answer from"), ("?live=" + self.base + "/no", "Not a live state"),
                             ("?live=javascript:alert(1)", "not a web address")):
            ctx, pg, errors, asked = self.open(query, wait=3500)
            s = pg.evaluate(js("live.js#state"))
            self.check(words in s["msg"], f"says: {words}", s["msg"])
            ctx.close()

    def asked(self) -> None:
        ctx, pg, errors, asked = self.open("?live=" + self.base + "/ev#k=" + "x" * 32, wait=4000)
        state = self.base + "/ev/live/state.json"
        others = [u for u in asked if not u.startswith(state)]
        self.check(not others, "asked: only the state address, no console door", others)
        self.check("#k=" not in pg.url, "asked: a key in the link is taken out of the address", pg.url)
        ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.live", description="Live in the two-view page.")
    ap.add_argument("where", help="a folder (its index.html), a two-view page, or a page's web address")
    ap.add_argument("--shots", type=Path, help="save pictures of Live here")
    opts = ap.parse_args(argv)
    where = Path(opts.where)
    page = opts.where if opts.where.startswith(WEB) else (where / "index.html" if where.is_dir() else where).resolve().as_uri()
    if opts.shots:
        opts.shots.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        base = stack.enter_context(feed.serve({"/ev": feed.evening_v2(), "/hostile": feed.hostile_v2(), "/no": lambda: '{"schema": "something else"}'}))
        live = Live(stack.enter_context(chrome()), page, base, feed.silent(), opts.shots)
        live.no_live()
        live.plays()
        live.run_change()
        live.hostile()
        live.says()
        live.asked()
    print(f"{live.count} checks. faults: {len(live.fails)}")
    return 1 if live.fails else 0


if __name__ == "__main__":
    sys.exit(main())

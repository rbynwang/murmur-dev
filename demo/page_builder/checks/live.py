"""Checks the optional live mode of the two-view page in a browser, against made-up feeds this check serves itself.

  python -m demo.page_builder.checks.live FOLDER_OR_PAGE [--shots DIR]

A folder: its index.html, the front page, which opens on the split view. The feeds (feed.py, and the states below) are served
on 127.0.0.1 at a port the system picks, for as long as the check runs; nothing else is asked. Checked: without ?live= nothing
of the live mode exists and nothing is asked; with it, the Live view shows the feed's state as plain text, tells old code from
current, says so when the address is bad, silent, withheld or not a live state, never turns what a feed sends into markup,
fits its panel, and leaves the replay as it was. At nine window sizes (the seven standard ones among them) the diagram beside
the Live view is measured too (probe.js): no name or second line of a box cut, no box cut or over another. Exit code 1 when a
check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from . import feed
from .browser import HERE, WEB, chrome, fault_line, js, measure, new_window

EVIL = json.loads((HERE / "hostile.json").read_text(encoding="utf-8"))["markup"]
SIZES = [(1440, 900), (1680, 1000), (1280, 720), (1512, 850), (1512, 920), (1600, 900), (1728, 960), (1920, 950), (1920, 1080)]
DIAGRAM_BOXES = ["8 home agents", "2 building agents"]


def at(clock: str) -> dict:
    s = feed.network()
    s["clock"] = clock
    return s


def settled() -> dict:
    s = feed.network()
    s["event"].update({"phase": "settled", "readings": 60, "paid_nodes": 10, "income_usd": 497.07})
    s["parts"]["town"]["up"] = False
    return s


def hostile() -> dict:
    s = at(EVIL)
    s["extra"] = EVIL
    s["parts"]["homes"] = {"up": True, "seen_s": EVIL, "current": EVIL, "ready": EVIL, "count": EVIL, "name": EVIL}
    s["parts"]["community"]["nodes"] = 1e99
    s["parts"][EVIL] = feed.part()
    s["event"] = {"phase": EVIL, "window": [EVIL, EVIL], "asked_kw": EVIL, "offers": -3, "buyers": 1e9, "income_usd": "1e9",
                  "note": EVIL}
    return s


FEEDS = {"": lambda: json.dumps(feed.network()), "/ok": lambda: json.dumps(feed.network()),
         "/all": lambda: json.dumps(feed.network(asked_kw=135.5, asked_all=True)),
         "/before": lambda: json.dumps(at("2025-01-28 17:00")), "/after": lambda: json.dumps(at("2025-01-28 21:15")),
         "/settled": lambda: json.dumps(settled()), "/hostile": lambda: json.dumps(hostile()),
         "/wrong": lambda: json.dumps({"schema": "something.else", "parts": {}}),
         "/withheld": lambda: json.dumps({"schema": "murmur.live.v1", "withheld": True}),
         "/text": lambda: EVIL, "/big": lambda: json.dumps({"schema": "murmur.live.v1", "pad": "x" * 200000})}


class Live:
    """The checks, each one line: ok or FAIL, and what it holds."""

    def __init__(self, browser: Any, page: str, base: str, nothing: str, shots: Path | None) -> None:
        self.browser, self.page, self.base, self.nothing, self.shots = browser, page, base, nothing, shots
        self.network = base                # a whole network's feed answers at the root of its address, as a real one does
        self.fails: list[str] = []
        self.count = 0

    def want(self, ok: bool, what: str) -> None:
        self.count += 1
        print(("   ok   " if ok else "   FAIL ") + what)
        if not ok:
            self.fails.append(what)

    def open(self, query: str, size: tuple[int, int] = (1440, 900), wait: int = 2600) -> tuple[Any, list[str], list[str]]:
        """The page with `query` after its address. Returns the page, its script errors and what it asked of a feed."""
        errors: list[str] = []
        asked: list[str] = []
        ctx, pg = new_window(self.browser, size, errors, web_feed=self.page.startswith(WEB) and "?live=" in query)
        pg.on("request", lambda r: asked.append(r.url) if r.url.startswith((self.base, self.nothing, "http://user")) else None)
        pg.goto(self.page + query)
        pg.wait_for_timeout(wait)
        return pg, errors, asked

    def snap(self, pg: Any) -> dict:
        return pg.evaluate(js("live.js#snap"))

    def pos(self, pg: Any) -> str:
        return pg.evaluate(js("steps.js#pos"))

    def picture(self, pg: Any, name: str) -> None:
        if self.shots:
            pg.screenshot(path=str(self.shots / name))

    def no_live(self) -> int:
        print("1 no ?live= : the page is the replay, and nothing of the live mode exists")
        pg, errs, asked = self.open("", wait=1800)
        s, n = self.snap(pg), pg.evaluate(js("steps.js#moment_count"))
        self.want(not s["tabLive"] and not s["lv"] and not s["css"] and not s["live"] and not s["on"],
                  "no Live tab, no live panel, no live styles, no live object")
        self.want(s["tabs"] == ["Split view*", "Data view"] and s["pos"] == f"0 of {n}" and s["truth"].startswith("A recorded run"),
                  f"tabs and bar as before: {s['tabs']}, {s['pos']}")
        self.want(not asked and not errs, f"nothing asked of any feed, no script errors ({len(asked)} asked, {len(errs)} errors)")
        pg.get_by_role("button", name="Next").click()
        pg.wait_for_timeout(250)
        self.want(self.pos(pg) == f"1 of {n}", "the replay steps")
        pg.context.close()
        return n

    def whole_network(self, n: int) -> None:
        print(f"2 ?live= a made-up whole network on port {self.base.rsplit(':', 1)[-1]}")
        parts = feed.network()["parts"]
        for size in SIZES:
            pg, errs, asked = self.open("?live=" + self.network, size)
            s = self.snap(pg)
            if size == (1440, 900):
                self.tabs_and_back(pg, s, parts, asked, n)
            self.want(not errs, f"{size[0]}x{size[1]}: no script errors" + (f" ({errs[:2]})" if errs else ""))
            self.want(s["wide"] == 0 and not s["cut"] and not s["sideways"],
                      f"{size[0]}x{size[1]}: nothing wider than the panel, nothing cut ({s['wide']}, {s['cut'][:2]})")
            d = measure(pg)
            state = [h["fit"] for h in d["hosts"] if h["host"] == "map"]
            self.want(not d["faults"], f"{size[0]}x{size[1]}: nothing cut in the diagram beside it (state {state})"
                      + ("" if not d["faults"] else " | " + "; ".join(fault_line(f) for f in d["faults"][:3])))
            print(f"      {size[0]}x{size[1]}: the live panel scrolls by {s['scroll']} px")
            if size == (1280, 720):
                self.picture(pg, "live_network_1280.png")
            pg.context.close()

    def tabs_and_back(self, pg: Any, s: dict, parts: dict, asked: list[str], n: int) -> None:
        """At 1440x900: what the Live view says, and the way to the replay and the Data view and back."""
        print("      status:", s["status"], "|", s["code"])
        print("      request:", s["reqH"], "|", s["reqP"])
        for c in s["cards"]:
            print("      card:", c)
        print("      foot:", s["foot"])
        print("      bar:", s["truth"], "| tabs:", s["tabs"])
        print("      boxes:", s["boxes"], "| data center frame grey:", s["dcFrameGrey"])
        b = s["boxes"]
        self.want(s["on"] and s["shown"] and s["tabs"] == ["Split view", "Data view", "Live*"], "the Live tab is there and selected")
        self.want(s["status"].startswith("updated") and len(s["cards"]) == 9, "the state arrived and nine parts are listed")
        self.want(self.network.split("//", 1)[-1] in s["foot"] and "Network clock: " in s["foot"], "the source and the network clock are named")
        self.want(b["co-market"] == "-" and b["h-guard"] == "-" and b["agg-ref"] == "lvdim"
                  and b["mkt"] == ("lvn" if parts["aggregator"] is None else "lvu"),
                  "boxes inside an answering agent are left as they are; parts outside the live network are grey")
        self.want(s["forks"] == [f"{parts['homes']['count']} home agents", f"{parts['buildings']['count']} building agents"],
                  f"the diagram's two counts show the live network's: {s['forks']}")
        self.want(s["ctl"] == "hidden" and s["layer"] == "none" and s["truth"].startswith("Live:"),
                  "the replay's controls and panel are put away, and the bar says Live")
        self.want(all(u.startswith(self.network + feed.STATE) for u in asked) and len(asked) >= 1,
                  f"only the state address was asked ({len(asked)} times)")
        self.picture(pg, "live_network_1440.png")
        pos0 = s["pos"]
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(200)
        self.want(self.pos(pg) == pos0, "an arrow key does not move the hidden replay")
        pg.click("#tab-split")
        pg.wait_for_timeout(350)
        s2 = self.snap(pg)
        self.want(not s2["on"] and s2["tabs"] == ["Split view*", "Data view", "Live"] and s2["ctl"] == "visible"
                  and s2["layer"] != "none" and s2["truth"].startswith("A recorded run"), f"Split view brings the replay back: {s2['tabs']}")
        self.want(s2["forks"] == DIAGRAM_BOXES, f"and the diagram's counts are the replay's again: {s2['forks']}")
        pg.get_by_role("button", name="Next").click()
        pg.wait_for_timeout(250)
        self.want(self.pos(pg) == f"1 of {n}", "and it steps")
        pg.click("#tab-data")
        pg.wait_for_timeout(350)
        s3 = self.snap(pg)
        self.want(not s3["on"] and s3["tabs"] == ["Split view", "Data view*", "Live"], f"Data view opens as before: {s3['tabs']}")
        if not s3["tabLive"]:
            self.want(False, "Live comes back and asks again: there is no Live tab")
            return
        pg.click("#tab-live")
        pg.wait_for_timeout(900)
        s4 = self.snap(pg)
        self.want(s4["on"] and s4["tabs"] == ["Split view", "Data view", "Live*"] and s4["status"].startswith("updated"),
                  "Live comes back and asks again")

    def headline(self, path: str) -> tuple[str, list[str]]:
        pg, _, _ = self.open("?live=" + self.base + path)
        s = self.snap(pg)
        pg.context.close()
        return s["reqH"], s["rows"]

    def made_up(self) -> None:
        print("3 a made-up feed with every part on current code and a request open")
        pg, errs, asked = self.open("?live=" + self.base + "/ok")
        s = self.snap(pg)
        print("      status:", s["status"], "|", s["code"])
        print("      request:", s["reqH"], "|", s["reqP"], "|", s["rows"])
        print("      boxes:", s["boxes"], "| data center frame grey:", s["dcFrameGrey"])
        rows, b = s["rows"], s["boxes"]
        self.want(s["reqH"] == "Delivering" and any(r.startswith("First order: 136 kW for 6 half hours") for r in rows)
                  and any("12 of 60" in r for r in rows),
                  "the request's numbers show, and its headline follows the clock: inside the window it reads Delivering")
        heads = [self.headline(p)[0] for p in ("/before", "/after")]
        self.want(heads == ["Contracts signed, delivery to come", "Delivered, readings coming in"],
                  f"before the window and after it the headline says so: {heads}")
        every = self.headline("/all")[1]
        self.want(any(r.startswith("Ordered by 2 buyers: 135.5 kW for 6 half hours") for r in every)
                  and not any(r.startswith("First order") for r in every),
                  f"a source that knows every buyer's order shows their sum, and says so: {every[:1]}")
        self.want(s["code"].startswith("Code: all 5 parts"), "the code line says all five reporting parts are current")
        self.want(b["mkt"] == "lvu" and b["site-dc"] == "lvu" and s["dcFrameGrey"] is False and b["agg-ref"] == "lvdim",
                  "the request agent and the data center are lit; parts outside the live network stay grey")
        self.want(not errs and s["wide"] == 0 and not s["cut"], "no script errors, nothing cut")
        d = measure(pg)
        self.want(not d["faults"], "nothing cut in the diagram with every part lit"
                  + ("" if not d["faults"] else " | " + "; ".join(fault_line(f) for f in d["faults"][:3])))
        self.picture(pg, "live_ok_1440.png")
        pg.context.close()
        pg, errs, asked = self.open("?live=" + self.base + "/settled")
        s = self.snap(pg)
        self.want(s["reqH"] == "Settled" and any(r == "Flexibility income: $497.07" for r in s["rows"])
                  and any(r == "Paid: 10 nodes" for r in s["rows"]) and s["boxes"]["town"] == "lvx",
                  f"a settled request shows pay, and a silent part shows as not answering: {s['rows'][-2:]}")
        pg.context.close()

    def hostile_feed(self) -> None:
        print("4 a hostile feed: markup in every field")
        pg, errs, asked = self.open("?live=" + self.base + "/hostile")
        s = self.snap(pg)
        print("      request:", s["reqH"], "|", s["rows"], "| homes card:", [c for c in s["cards"] if c.startswith("Home agents")])
        self.want(s["markup"] == 0 and s["x"] == 0 and not s["html"],
                  "nothing a feed sent became markup or ran, and no angle bracket reached the screen")
        self.want(s["reqH"] == "In progress" and not errs, "unknown words fall back to a fixed one; no script errors")
        pg.context.close()

    def not_a_state(self) -> None:
        print("5 addresses that are not a live state")
        for path, head, why in (("/wrong", "Not a live state", "another schema"), ("/text", "Not a live state", "not JSON"),
                                ("/big", "Not a live state", "too large"), ("/withheld", "State withheld", "withheld by the feed")):
            pg, errs, asked = self.open("?live=" + self.base + path)
            s = self.snap(pg)
            self.want(s["reqH"] == head and s["markup"] == 0 and s["x"] == 0 and not errs, f"{why}: '{s['reqH']}'")
            pg.context.close()
        pg, errs, asked = self.open("?live=" + self.nothing, wait=3200)
        s = self.snap(pg)
        self.want(s["reqH"] == "No answer from the live address" and s["status"] == "no answer yet"
                  and all(c.split(" | ")[1] == "No answer" for c in s["cards"]) and s["boxes"]["co-market"] == "lvdim",
                  f"nothing listening: '{s['reqH']}', status '{s['status']}'")
        pg.context.close()
        signed_in = "http://user:pw@" + self.base.split("//", 1)[-1]
        for query, why in (("?live=javascript:alert(1)", "not a web address"), ("?live=nonsense", "not a web address"),
                           ("?live=" + signed_in, "carries a sign-in"), ("?live=file:///etc/hosts", "not a web address")):
            pg, errs, asked = self.open(query, wait=1500)
            s = self.snap(pg)
            self.want(why in s["reqP"] and not asked and s["x"] == 0, f"{query[6:30]}: refused ('{s['reqP'][:60]}'), nothing asked")
            pg.context.close()
        pg, errs, asked = self.open("?live=", wait=1200)
        s = self.snap(pg)
        self.want(not s["tabLive"] and not s["lv"], "an empty ?live= counts as none")
        pg.context.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.live", description="The optional Live view.")
    ap.add_argument("where", help="a folder (its index.html), a two-view page, or a page's web address")
    ap.add_argument("--shots", type=Path, help="save pictures of the Live view here")
    opts = ap.parse_args(argv)
    where = Path(opts.where)
    page = opts.where if opts.where.startswith(WEB) else (where / "index.html" if where.is_dir() else where).resolve().as_uri()
    if opts.shots:
        opts.shots.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        base = stack.enter_context(feed.serve(FEEDS))
        live = Live(stack.enter_context(chrome()), page, base, feed.silent(), opts.shots)
        n = live.no_live()
        live.whole_network(n)
        live.made_up()
        live.hostile_feed()
        live.not_a_state()
    print(f"{live.count} checks. faults: {len(live.fails)}")
    return 1 if live.fails else 0


if __name__ == "__main__":
    sys.exit(main())

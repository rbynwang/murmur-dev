"""Walks a page through every moment of its replay, and its Data view through every filter and part, and lists what is cut
off, overflowing or broken.

  python -m demo.page_builder.checks.walk FOLDER_OR_PAGE [--sizes 1440x900,1680x1000] [--evenings N] [--only PART-OF-NAME]
                                          [--shots DIR]

Moments (every page with the diagram), at each size, in the split view and in the whole picture (opened by its address #whole),
stepped with the page's own Next button: script errors; a box of the map outside its frame or outside the map; a single site's
frame whose boxes run past its foot; the message network's band not reaching the last frame; text cut by its own box (the bar's
line, a box's name); the whole picture's caption cut under its number; the opening card or a moment's card running past the
panel. In the whole picture the sections behind its own buttons are read too. A year's page holds several evenings: the first
N (default 3) are walked, every moment of each. A page that opens on its Data view is walked from its split view's tab.

Data view (every page that has it), at 1440x900, 1680x1000 and 1280x720: each of the six filters and every part (squares shown
inside their box and clear of its name, the panel inside its side, nothing cut sideways); a click on the Home agent box opens
its panel and the replay does not move meanwhile; back in the split view the replay's panel returns and still steps.
--shots saves pictures of the filters and of most parts at 1440x900. Exit code 1 on any fault.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .browser import chrome, js, label, open_page, parse_sizes, source, targets

SIZES = [(1440, 900), (1680, 1000)]
DATA_SIZES = [(1440, 900), (1680, 1000), (1280, 720)]
FILTERS = ("all", "e", "built", "s", "m", "o")
PICTURED = ("clean", "share", "buy", "host", "homes", "hdev", "people", "blds", "bguard", "bdev", "pv", "dc", "ret", "req")


def note(found: dict[str, list[str]], faults: list[str], where: str) -> None:
    for f in faults:
        found.setdefault(f, []).append(where)


def every_moment(pg: Any, where: str, found: dict[str, list[str]]) -> int:
    """The opening card and every moment after it, one Next at a time. Returns the number of moments."""
    n = pg.evaluate(js("steps.js#moment_count"))
    for i in range(n + 1):
        note(found, pg.evaluate(js("walk.js#moment")), f"{where} m{i}")
        if i < n:
            pg.get_by_role("button", name="Next").click()
            pg.wait_for_timeout(140)
    return n


def sections(pg: Any, size: str, found: dict[str, list[str]]) -> None:
    """The sections behind the whole picture's own buttons."""
    for name in pg.evaluate(js("walk.js#section_buttons")):
        pg.get_by_role("button", name=name, exact=True).click()
        pg.wait_for_timeout(500)
        note(found, pg.evaluate(js("walk.js#sections")), f"{size} section {name}")


def moments(browser: Any, name: str, url: str, sizes: list[tuple[int, int]], evenings: int) -> int:
    """Every moment of the first evenings, in both views, at every size. Prints one line; returns the number of faults."""
    found: dict[str, list[str]] = {}
    errors: list[str] = []
    seen = 0
    for sz in sizes:
        for view in ("split", "whole"):
            ctx, pg = open_page(browser, url + ("#whole" if view == "whole" else ""), sz, errors, wait=1100)
            if pg.evaluate(js("steps.js#data_on")):        # the replay's Next button is behind the split view's tab
                pg.click("#tab-split")
                pg.wait_for_timeout(300)
            ids = pg.evaluate(js("steps.js#evenings"))
            for k, sid in enumerate(ids[:evenings] if len(ids) > 1 else [None]):
                if sid is not None and k:
                    pg.evaluate(js("steps.js#choose_evening"), sid)
                    pg.wait_for_timeout(900)
                tag = f" evening{k + 1}" if sid is not None else ""
                seen += every_moment(pg, f"{label(sz)} {view}{tag}", found)
            if view == "whole":
                sections(pg, label(sz), found)
            ctx.close()
    errs = sorted(set(errors))
    print(f"{name}: {seen} moments walked over {len(sizes)} sizes and 2 views, {len(found)} kinds of fault,"
          f" {len(errs)} script errors")
    for kind, where in sorted(found.items(), key=lambda kv: -len(kv[1]))[:18]:
        print(f"   [{len(where)}] {kind[:150]}   e.g. {where[0]}")
    for e in errs[:4]:
        print("   ! ", e)
    return len(found) + len(errs)


class DataWalk:
    """The Data view of one page in one window: what each look found, and which panels scroll."""

    def __init__(self, pg: Any, shots: Path | None) -> None:
        self.pg, self.shots = pg, shots
        self.found: dict[str, list[str]] = {}
        self.scrolls: dict[str, int] = {}

    def look(self, where: str, picture: str = "") -> dict:
        r = self.pg.evaluate(js("walk.js#data"))
        note(self.found, r["bad"], where)
        if r["scroll"] > 1:
            self.scrolls[where] = r["scroll"]
        if self.shots and picture:
            self.pg.screenshot(path=str(self.shots / picture))
        return r

    def filters(self) -> dict[str, tuple[int, int]]:
        """Each filter in turn: how many parts it lights and greys."""
        counts = {}
        for f in FILTERS:
            self.pg.evaluate(js("walk.js#data_filter"), f)
            self.pg.wait_for_timeout(120)
            r = self.look(f"filter {f}", f"dv_filter_{f}.png")
            counts[f] = (r["lit"], r["dim"])
        self.pg.evaluate(js("walk.js#data_filter"), "all")
        return counts

    def parts(self, order: list[str]) -> None:
        """Each part in turn: it shows a panel and its box is the selected one."""
        for key in order:
            self.pg.evaluate(js("walk.js#data_select"), key)
            self.pg.wait_for_timeout(120)
            r = self.look(f"part {key}", f"dv_part_{key}.png" if key in PICTURED else "")
            if not r["title"] or r["sel"] < 1:
                note(self.found, ["a part shows no panel or no selected box"], key)

    def click_and_back(self) -> str:
        """A click on the diagram opens that part and the replay does not move; back in the split view it still steps."""
        pg = self.pg
        pos0 = pg.evaluate(js("steps.js#pos"))
        pg.evaluate(js("walk.js#data_select"), None)
        pg.click('#map [data-dv="h-agent"]')
        pg.wait_for_timeout(150)
        title = pg.evaluate(js("walk.js#data_title"))
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(150)
        pos1 = pg.evaluate(js("steps.js#pos"))
        if "200 households" not in title:
            note(self.found, ["a click on the Home agent box did not open its panel: " + title], "click")
        if pos0 != pos1:
            note(self.found, ["the replay moved under the data view"], f"{pos0} -> {pos1}")
        pg.click("#tab-split")
        pg.wait_for_timeout(250)
        pg.get_by_role("button", name="Next").click()
        pg.wait_for_timeout(250)
        back = pg.evaluate(js("walk.js#back"))
        if back["dv"] or back["layer"] == "none" or back["sq"] != "none" or back["tabs"] != ["Split view", "Data view"]:
            note(self.found, ["the split view did not come back as it was: " + json.dumps(back)], "back")
        if self.shots:
            pg.screenshot(path=str(self.shots / "dv_back_to_split.png"))
        return back["pos"]


def data_view(browser: Any, name: str, url: str, shots: Path | None) -> int:
    """The Data view at its three sizes. Prints a line per size; returns the number of faults."""
    print(f"{name}: the Data view")
    total = 0
    for sz in DATA_SIZES:
        errors: list[str] = []
        ctx, pg = open_page(browser, url + "#data", sz, errors, wait=1300)
        walk = DataWalk(pg, shots if sz == (1440, 900) else None)
        order = pg.evaluate(js("walk.js#data_parts"))["order"]
        counts = walk.filters()
        walk.parts(order)
        pos = walk.click_and_back()
        errs = sorted(set(errors))
        total += len(walk.found) + len(errs)
        print(f"   {label(sz)}: {len(order)} parts and {len(FILTERS)} filters walked | lit/grey by filter {counts} |"
              f" {len(walk.found)} kinds of fault, {len(errs)} script errors | panels that scroll:"
              f" {walk.scrolls or 'none'} | split view after: {pos}")
        for kind, where in list(walk.found.items())[:14]:
            print(f"      [{len(where)}] {kind[:150]}   e.g. {where[0]}")
        for e in errs[:3]:
            print("      ! ", e)
        ctx.close()
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.walk", description="Every moment, every part.")
    ap.add_argument("where", help="a folder of pages, one page, or a page's web address")
    ap.add_argument("--sizes", type=parse_sizes, default=SIZES, help="window sizes of the moments walk (default 1440x900,1680x1000)")
    ap.add_argument("--evenings", type=int, default=3, help="a year's page: the first N evenings")
    ap.add_argument("--only", default="", help="only the pages whose name holds this")
    ap.add_argument("--shots", type=Path, help="save pictures of the Data view here, a folder per page")
    opts = ap.parse_args(argv)
    pages = targets(opts.where, 'id="map"', only=opts.only)
    if not pages:
        print(f"no page with the diagram in {opts.where}")
        return 2
    total, walked = 0, 0
    with chrome() as browser:
        for name, url in pages:
            total += moments(browser, name, url, opts.sizes, opts.evenings)
            if 'id="fg-dv"' in source(url, browser):
                shots = opts.shots / Path(name).stem[-34:] if opts.shots else None
                if shots:
                    shots.mkdir(parents=True, exist_ok=True)
                total += data_view(browser, name, url, shots)
                walked += 1
    print(f"{len(pages)} pages walked, {walked} with the Data view. faults: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

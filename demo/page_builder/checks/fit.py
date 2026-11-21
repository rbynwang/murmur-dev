"""Checks that no word of the diagram is cut, at many window sizes, in every view of a page.

  python -m demo.page_builder.checks.fit FOLDER_OR_PAGE [--url BASE] [--more | --sizes 1440x900,1512x850] [--moments all]
                                         [--evenings N] [--only PART-OF-NAME] [--no-live] [--shots DIR] [--quiet]

A folder: every page in it that holds the diagram (--url BASE opens the same names at a web address). For each size the page
is opened afresh and measured by the fit probe (probe.js: each box's name and second line inside the box, a pixel clear of its
edge at top and foot; the ink of every piece of text inside its frame; no box cut or over another; no label over a box), in
each view the page has:

  split    the replay's map, at the opening card and at moments through the evening (--moments all: every moment)
  whole    the whole picture, where the page has that tab, at moments through the evening
  data     the Data view, where the page has it: as opened, with one kind chosen, with one part chosen
  live     the Live view, where the page carries the live mode: with a made-up feed answering (served by this check on a
           free port of this computer, every box the Live view can light lit) and with an address where nothing answers

Then one window that is never reloaded is resized through every size and back, and the map must end in the state a fresh page
of that size has (the measured fit follows the window both ways). Last, the seven standard sizes are opened with the page's
measuring switched off, so the size rules alone are shown to cut nothing. A year's page holds several evenings: the first N
(default 2) and the last are measured. The seven standard sizes run from 1440x900 to 1920x1080; --more adds smaller laptops and
projectors, a tall narrow window and a large screen. Exit code 1 when anything is cut.
"""
from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from . import feed
from .browser import MORE, SEVEN, Size, chrome, fault_line, js, label, measure, open_page, parse_sizes, source, targets

STATES = {"0": "both lines", "1": "both lines, boxes closer", "2": "both lines, map closer", "3": "names only",
          "4": "names only, map closer", "5": "names only, map closest", "6": "names only, the map scrolls"}


def benign(message: Any) -> bool:
    """A feed that does not answer, or that the browser was not allowed to ask, is not a script error; nor is a missing icon."""
    t = message.text
    return "favicon" in t or t.startswith("Failed to load resource") or "Permission was denied" in t


class Run:
    """What one page's check found: each kind of fault with where it was seen, the script errors, and the fit state each size
    opened in (the resize walk must end in the same one)."""

    def __init__(self) -> None:
        self.found: dict[str, list[str]] = {}
        self.errors: list[str] = []
        self.states: dict[str, list] = {}
        self.probes = 0

    def open(self, browser: Any, url: str, size: Size, **window: Any) -> tuple[Any, Any]:
        return open_page(browser, url, size, self.errors, ignore=benign, **window)

    def probe(self, pg: Any, where: str) -> dict:
        s = measure(pg)
        self.probes += 1
        for f in s["faults"]:
            self.found.setdefault(fault_line(f).split(" by ")[0], []).append(f"{where} ({f['by']} px)")
        return s

    def fault(self, kind: str, where: str) -> None:
        self.found.setdefault(kind, []).append(where)


def moments_of(pg: Any, every: bool) -> list[int]:
    """The moments measured: every one, or nine spread through the evening."""
    n = pg.evaluate(js("steps.js#moment_count"))
    if every or n <= 9:
        return list(range(n))
    return sorted({0, 1, n // 6, n // 3, n // 2, (2 * n) // 3, (5 * n) // 6, n - 2, n - 1})


def replay_views(pg: Any, run: Run, size: str, tabs: list[str], every: bool, evenings: int) -> dict:
    """The split view, and the whole picture where the page has it, for each evening measured. Returns the first probe."""
    ids = pg.evaluate(js("steps.js#evenings"))
    picks = [None] if len(ids) < 2 else list(dict.fromkeys(ids[:evenings] + ids[-1:]))
    first = None
    for k, sid in enumerate(picks):
        eve = "" if sid is None else f" evening {ids.index(sid) + 1}"
        if sid is not None and k:
            pg.evaluate(js("steps.js#choose_evening"), sid)
            pg.wait_for_timeout(900)
        s = run.probe(pg, f"{size} split{eve} opening")
        first = first or s
        ms = moments_of(pg, every)
        for i in ms:
            pg.evaluate(js("steps.js#go"), i)
            pg.wait_for_timeout(60)
            run.probe(pg, f"{size} split{eve} moment {i + 1}")
        if "tab-whole" in tabs:
            pg.evaluate(js("steps.js#set_tab"), "whole")
            pg.wait_for_timeout(450)
            run.probe(pg, f"{size} whole{eve}")
            for i in ms[:: max(1, len(ms) // 4)]:
                pg.evaluate(js("steps.js#go"), i)
                pg.wait_for_timeout(80)
                run.probe(pg, f"{size} whole{eve} moment {i + 1}")
            pg.evaluate(js("steps.js#set_tab"), "split")
            pg.wait_for_timeout(300)
            run.probe(pg, f"{size} split{eve} again after the whole picture")
    return first


def data_view(pg: Any, run: Run, size: str, shots: Path | None) -> None:
    """The Data view as opened, with one kind of data chosen, and with the Home agent's part chosen."""
    pg.click("#tab-data")
    pg.wait_for_timeout(450)
    run.probe(pg, f"{size} data")
    chips = pg.locator("#dv button, .dvchips button, [data-dvk]")
    if chips.count() > 1:
        chips.nth(1).click()
        pg.wait_for_timeout(200)
        run.probe(pg, f"{size} data, one kind chosen")
    box = pg.locator("#map .blk[data-b='h-agent']")
    if box.count():
        box.first.click()
        pg.wait_for_timeout(250)
        run.probe(pg, f"{size} data, one part chosen")
    if shots:
        pg.screenshot(path=str(shots / f"{size}_data.png"))


def live_views(browser: Any, url: str, sz: Size, run: Run, live: tuple[str, str], shots: Path | None) -> None:
    """The Live view with the made-up feed answering and with nothing answering, and the split view after each."""
    size = label(sz)
    for address, what in ((live[0] + "/ok", "live, the feed answering"), (live[1], "live, no answer")):
        ctx, pg = run.open(browser, url + "?live=" + address, sz, wait=2300)
        if not pg.evaluate(js("steps.js#live_on")):
            run.fault("the Live view did not open", f"{size} {what}")
        run.probe(pg, f"{size} {what}")
        if shots and what.endswith("answering"):
            pg.screenshot(path=str(shots / f"{size}_live.png"))
        pg.click("#tab-split")
        pg.wait_for_timeout(350)
        run.probe(pg, f"{size} split again after {what}")
        ctx.close()


def one_size(browser: Any, url: str, sz: Size, run: Run, opts: argparse.Namespace, live: tuple[str, str] | None,
             shots: Path | None) -> str:
    """Every view of the page in a fresh window of one size. Returns the line that says the state the diagram took."""
    size = label(sz)
    ctx, pg = run.open(browser, url, sz)
    tabs = pg.evaluate(js("steps.js#tabs"))
    first = replay_views(pg, run, size, tabs, opts.moments == "all", opts.evenings)
    if shots:
        pg.screenshot(path=str(shots / f"{size}_split.png"))
    if "tab-data" in tabs:
        data_view(pg, run, size, shots)
    m = [h for h in first["hosts"] if h["host"] == "map"]
    st = pg.evaluate(js("steps.js#fit_state"))
    line = f"state {st[0]} ({STATES.get(st[0] or '', 'no map shown')})"
    line += f", sideways {st[1]}" if st[1] not in (None, "0") else ""
    line += f", scrolls {m[0]['scrollsBy']} px" if m and m[0]["scrollsBy"] else ""
    run.states[size] = st
    ctx.close()
    if live:
        live_views(browser, url, sz, run, live, shots)
        line += " | live"
    return line


def resize_walk(browser: Any, url: str, sizes: list[Size], run: Run) -> list[str]:
    """One window, never reloaded, taken through every size and back: the map must end in the state a fresh page has."""
    ctx, pg = run.open(browser, url, sizes[-1])
    off = []
    for w, h in sizes + sizes[::-1]:
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(420)
        run.probe(pg, f"resized to {w}x{h}")
        st, fresh = pg.evaluate(js("steps.js#fit_state")), run.states.get(f"{w}x{h}")
        if fresh is not None and st != fresh:
            off.append(f"{w}x{h}: {st} after resizing, {fresh} when opened at that size")
    ctx.close()
    return off


def check(browser: Any, name: str, url: str, sizes: list[Size], opts: argparse.Namespace, live: tuple[str, str] | None,
          shots: Path | None) -> int:
    """Every size, the resize walk and the pass with the measuring off, for one page. Returns the number of faults."""
    run = Run()
    print(name)
    live = live if live and "lv-js" in source(url, browser) else None
    for sz in sizes:
        line = one_size(browser, url, sz, run, opts, live, shots)
        if not opts.quiet:
            print(f"   {sz[0]}x{sz[1]:<5} {line}")
    off = resize_walk(browser, url, sizes, run)
    for sz in SEVEN:
        ctx, pg = run.open(browser, url, sz, nofit=True)
        run.probe(pg, f"{label(sz)} with the measuring switched off")
        ctx.close()
    errors = sorted(set(run.errors))
    print(f"   {run.probes} measurements over {len(sizes)} sizes: {len(run.found)} kinds of fault, {len(off)} sizes where a"
          f" resized window differs from a fresh one, {len(errors)} script errors")
    for kind, where in sorted(run.found.items(), key=lambda kv: -len(kv[1]))[:24]:
        print(f"      [{len(where)}] {kind[:150]}   e.g. {where[0]}")
    for o in off[:8]:
        print("      resize:", o)
    for e in errors[:4]:
        print("      ! ", e)
    return len(run.found) + len(off) + len(errors)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.fit", description="No word of the diagram cut.")
    ap.add_argument("where", help="a folder of pages, one page, or a page's web address")
    ap.add_argument("--url", help="open the folder's pages at this web address instead of their files")
    ap.add_argument("--more", action="store_true", help="the seven standard sizes and fifteen more")
    ap.add_argument("--sizes", type=parse_sizes, help="these window sizes, such as 1440x900,1512x850")
    ap.add_argument("--moments", choices=("spread", "all"), default="spread", help="nine moments of each evening, or all")
    ap.add_argument("--evenings", type=int, default=2, help="a year's page: the first N evenings and the last")
    ap.add_argument("--only", default="", help="only the pages whose name holds this")
    ap.add_argument("--no-live", action="store_true", help="leave the Live view out")
    ap.add_argument("--shots", type=Path, help="save a picture of each size's views here, a folder per page")
    ap.add_argument("--quiet", action="store_true", help="no line per size")
    opts = ap.parse_args(argv)
    sizes = opts.sizes or (SEVEN + MORE if opts.more else list(SEVEN))
    pages = targets(opts.where, 'id="map"', opts.url, opts.only)
    if not pages:
        print(f"no page with the diagram in {opts.where}")
        return 2
    total = 0
    with ExitStack() as stack:
        live = None if opts.no_live else (stack.enter_context(feed.serve({"/ok": feed.every_box_lit})), feed.silent())
        browser = stack.enter_context(chrome())
        for name, url in pages:
            shots = opts.shots / Path(name).stem[-34:] if opts.shots else None
            if shots:
                shots.mkdir(parents=True, exist_ok=True)
            total += check(browser, name, url, sizes, opts, live, shots)
    print(f"{len(pages)} pages with the diagram, {len(sizes)} sizes each. faults: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

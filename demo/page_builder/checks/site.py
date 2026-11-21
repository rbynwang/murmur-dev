"""Opens every page of a folder in a browser and lists what a visitor could meet that should not be there.

  python -m demo.page_builder.checks.site FOLDER_OR_PAGE [--url BASE] [--shots DIR]

Without --url the folder's files are opened; with it, the same names at that web address (index.html as the address itself).
One page may be given instead of a folder: its links are then checked against the pages beside it. For each page:

  errors     script errors and console errors (a browser's own request for a site icon is not the page's doing)
  asks       every outside address the page asks for: only the font servers may be asked, and with --url the site itself
  links      every link: one inside the set must name a page of the folder, and no link may leave the set
  on screen  the words on screen, as opened, in every tab, in every section behind the whole picture's own buttons, at the
             first six moments of the replay and in the message network's panel, read by the repository's own trace
             scanner (scripts/verify_clean_repo.py, which holds the names it looks for only as salted hashes)
  chips      the status chips of the message network's panel, read by the same scanner

and, for a page with the replay, how many moments it holds and which tabs it shows. Exit code 1 on any fault.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Callable

from .browser import chrome, js, new_window, targets

FONT_HOSTS = frozenset({"fonts.googleapis.com", "fonts.gstatic.com"})
SCANNER = Path(__file__).resolve().parents[3] / "scripts" / "verify_clean_repo.py"
HOST = re.compile(r"https?://([^/]+)/")
WEB_LINK = re.compile(r"https?:")
NOT_A_PAGE = re.compile(r"https?:|#|mailto:|javascript:")
Scan = Callable[[str], list]


def trace_scanner() -> Scan:
    """`scan(text)` of the repository's trace check: a list of (offset, kind, excerpt), the excerpt leaving the name out.
    Loaded from its file without writing a compiled copy beside it."""
    spec = importlib.util.spec_from_file_location("verify_clean_repo", SCANNER)
    module = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module.scan


def icon_request(message: Any) -> bool:
    return str((message.location or {}).get("url") or "").endswith("/favicon.ico")


class Visit:
    """One page opened as a visitor would open it, with everything it asked for and every trace seen on its screen."""

    def __init__(self, browser: Any, url: str, scan: Scan) -> None:
        self.errors: list[str] = []
        self.hosts: dict[str, int] = {}
        self.failed: list[str] = []
        self.seen: dict[str, list[str]] = {}
        self.scan = scan
        self.ctx, self.pg = new_window(browser, (1440, 900), self.errors, ignore=icon_request)
        self.pg.on("request", self.asked)
        self.pg.on("requestfailed", lambda r: self.failed.append(r.url[:110]))
        got = self.pg.goto(url)
        self.status = got.status if got is not None else None
        self.pg.wait_for_timeout(1600)

    def asked(self, request: Any) -> None:
        m = HOST.match(request.url)
        if m:
            self.hosts[m.group(1)] = self.hosts.get(m.group(1), 0) + 1

    def look(self, where: str) -> None:
        for _, kind, _ in self.scan(self.pg.evaluate(js("site.js#text"))):
            self.seen.setdefault(kind, []).append(where)

    def tabs(self) -> list[str]:
        """Every tab the bar shows, and in each every section behind the whole picture's own buttons."""
        tabs = self.pg.evaluate(js("steps.js#tabs"))
        for t in tabs:
            self.pg.click("#" + t)
            self.pg.wait_for_timeout(350)
            self.look("tab " + t)
            for name in self.pg.evaluate(js("site.js#section_buttons")):
                try:
                    self.pg.get_by_role("button", name=name, exact=True).click(timeout=1500)
                except Exception:          # a section button another view covers is not on offer there
                    continue
                self.pg.wait_for_timeout(350)
                self.look(f"tab {t}, section {name}")
        return tabs

    def replay(self, tabs: list[str], moments: int, shots: Path | None) -> list[str]:
        """The first six moments, then the message network's panel. Returns the panel's status chips."""
        pg = self.pg
        if tabs:
            pg.click("#" + tabs[0])
            pg.wait_for_timeout(300)
        for i in range(min(moments, 6)):
            pg.get_by_role("button", name="Next").click()
            pg.wait_for_timeout(160)
            self.look(f"moment {i + 1}")
        chips = pg.evaluate(js("site.js#town_chips"))
        try:
            pg.click("#map .band.town", timeout=1500)
            pg.wait_for_timeout(400)
            self.look("Town panel")
            if shots:
                pg.screenshot(path=str(shots / "town_panel.png"))
        except Exception as e:             # the panel is a fault to report, not a reason to stop the check
            self.errors.append("could not open the Town panel: " + str(e)[:80])
        return chips


def check(browser: Any, name: str, url: str, names: set[str], base: str | None, scan: Scan, shots: Path | None) -> int:
    """One page: prints its line and returns the number of faults."""
    v = Visit(browser, url, scan)
    v.look("as opened")
    has_replay = v.pg.evaluate(js("site.js#has_replay"))
    moments = v.pg.evaluate(js("steps.js#moment_count")) if has_replay else 0
    tabs = v.tabs()
    front = shots if shots and name == "index.html" else None
    chips = v.replay(tabs, moments, front) if has_replay else None
    links = v.pg.evaluate(js("site.js#links"))
    outside = sorted({h for h in links if WEB_LINK.match(h)})
    local = sorted({h.split("#")[0] for h in links if not NOT_A_PAGE.match(h) and h.split("#")[0]})
    missing = [h for h in local if h not in names]
    own = HOST.match(base).group(1) if base else None
    other = {h: n for h, n in v.hosts.items() if h not in FONT_HOSTS and h != own}
    if front:
        v.pg.goto(url)
        v.pg.wait_for_timeout(1600)
        v.pg.screenshot(path=str(front / "index_opening.png"))
    status = v.status if base else "file"
    errors = sorted(set(v.errors))
    faults = (len(errors) + len(v.seen) + len(missing) + len(outside) + len(other) + (1 if base and status != 200 else 0)
              + (1 if chips and any(scan(c) for c in chips) else 0))
    seen = {kind: len(where) for kind, where in v.seen.items()}
    replay = f" | {moments} moments, tabs {tabs}, Town chips {chips}" if has_replay else ""
    print(f"{name[:50]:50} {status} | errors {len(errors)} | asks {dict(sorted(v.hosts.items())) or 'nothing outside'} |"
          f" links: {len(local)} in the set, missing {missing or 'none'}, outside {outside or 'none'} |"
          f" traces on screen {seen or 'none'}{replay}")
    for kind, where in v.seen.items():
        print(f"     trace: {kind} x{len(where)}, e.g. {where[0]}")
    for e in errors[:3]:
        print("     ! ", e)
    for f in v.failed[:3]:
        print("     failed request:", f)
    v.ctx.close()
    return faults


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.site", description="What a visitor could meet.")
    ap.add_argument("where", type=Path, help="a folder of pages, or one page of it")
    ap.add_argument("--url", help="open the pages at this web address instead of their files")
    ap.add_argument("--shots", type=Path, help="save pictures of the front page and its message network's panel here")
    opts = ap.parse_args(argv)
    folder = opts.where if opts.where.is_dir() else opts.where.parent
    names = {f.name for f in folder.glob("*.html")}
    pages = targets(str(opts.where), base=opts.url)
    if not pages:
        print(f"no page in {opts.where}")
        return 2
    if opts.shots:
        opts.shots.mkdir(parents=True, exist_ok=True)
    scan, total = trace_scanner(), 0
    with chrome() as browser:
        for name, url in pages:
            total += check(browser, name, url, names, opts.url, scan, opts.shots)
    print(f"{len(pages)} pages opened. faults in all: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

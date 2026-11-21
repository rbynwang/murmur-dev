"""What the page checks share: the pages to check, the window sizes, a browser, a window opened with its script errors caught,
the fit probe, and the scripts a check runs inside a page.

Those scripts are the .js files beside this module. A file is one script, or holds several snippets, each starting at a line
`// @name` and running to the next such line: `js("probe.js")` is a whole file, `js("steps.js#go")` one snippet. Every script
is one function expression, which Playwright calls in the page with the argument a check passes.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
SEVEN = [(1440, 900), (1512, 850), (1512, 920), (1600, 900), (1728, 960), (1920, 950), (1920, 1080)]
MORE = [(1180, 700), (1200, 800), (1280, 720), (1280, 800), (1366, 660), (1366, 768), (1440, 760), (1440, 1100),
        (1470, 956), (1512, 982), (1536, 730), (1536, 864), (1680, 1050), (1920, 700), (2560, 1300)]
WEB = ("http://", "https://")
MARK = re.compile(r"^// @([a-z][a-z0-9_]*)\n", re.M)
Size = tuple[int, int]


@lru_cache(maxsize=None)
def _scripts(file: str) -> dict[str, str]:
    """The snippets of one script file by name; a file without markers is one script, named ""."""
    text = (HERE / file).read_text(encoding="utf-8")
    marks = list(MARK.finditer(text))
    if not marks:
        return {"": text}
    ends = [m.start() for m in marks[1:]] + [len(text)]
    return {m.group(1): text[m.end():end] for m, end in zip(marks, ends)}


def js(ref: str) -> str:
    """One script to run in a page: "file.js" (the whole file) or "file.js#name" (one snippet of it)."""
    file, _, name = ref.partition("#")
    found = _scripts(file)
    if name not in found:
        raise KeyError(f"{ref}: no such script (the file has {', '.join(sorted(found)) or 'one script'})")
    return found[name]


def parse_sizes(text: str) -> list[Size]:
    """Window sizes written "1440x900,1512x850"."""
    return [(int(w), int(h)) for w, h in (s.split("x") for s in text.split(",") if s)]


def label(size: Size) -> str:
    return f"{size[0]}x{size[1]}"


def targets(where: str, holding: str = "", base: str | None = None, only: str = "") -> list[tuple[str, str]]:
    """(name, address) of each page to check. `where` is a folder (its .html pages by name, those whose text holds `holding`
    and whose name holds `only`), one page, or a page's web address. With `base` the folder's pages are opened at that web
    address instead, index.html as the address itself."""
    if where.startswith(WEB):
        return [(where.rstrip("/").rsplit("/", 1)[-1] or where, where)]
    path = Path(where)
    files = sorted(path.glob("*.html")) if path.is_dir() else [path]
    files = [f for f in files if only in f.name and holding in f.read_text("utf-8", "replace")]
    if not base:
        return [(f.name, f.resolve().as_uri()) for f in files]
    root = base.rstrip("/") + "/"
    return [(f.name, root + ("" if f.name == "index.html" else f.name)) for f in files]


def source(url: str, browser: Any) -> str:
    """The text of the page at an address: read from its file, or fetched by the browser."""
    if url.startswith("file:"):
        return Path(unquote(urlparse(url).path)).read_text("utf-8", "replace")
    pg = browser.new_page()
    try:
        got = pg.goto(url)
        return got.text() if got else ""
    finally:
        pg.close()


@contextmanager
def chrome() -> Iterator[Any]:
    """The installed Chrome, driven by Playwright, for as long as the block runs."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        try:
            yield browser
        finally:
            browser.close()


def new_window(browser: Any, size: Size, errors: list[str], *, ignore: Callable[[Any], bool] | None = None,
               nofit: bool = False, web_feed: bool = False) -> tuple[Any, Any]:
    """A fresh window (context and page) of `size`, not yet opened at any address. Script errors, and console errors that
    `ignore` does not excuse, go to `errors`. `nofit` switches the page's own measuring off before its scripts run. `web_feed`:
    a page on the web will ask a feed on this computer, which the browser allows only with a leave a check grants."""
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
    if nofit:
        ctx.add_init_script(path=str(HERE / "nofit.js"))
    if web_feed:
        try:
            ctx.grant_permissions(["local-network-access"])
        except Exception:                # a browser that does not know the leave asks for none
            pass
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" and not (ignore and ignore(m)) else None)
    return ctx, pg


def open_page(browser: Any, url: str, size: Size, errors: list[str], *, wait: int = 1200, **window: Any) -> tuple[Any, Any]:
    """A fresh window of `size` at `url`, `wait` ms after the page opened (see new_window for the rest)."""
    ctx, pg = new_window(browser, size, errors, web_feed="?live=" in url and url.startswith(WEB), **window)
    pg.goto(url)
    pg.wait_for_timeout(wait)
    return ctx, pg


def measure(pg: Any) -> dict:
    """The fit probe (probe.js), run once the page's fonts are in (a fallback font has other heights)."""
    pg.evaluate(js("steps.js#fonts"))
    return pg.evaluate(js("probe.js"))


def fault_line(f: dict) -> str:
    """One fault the probe found, in words."""
    text = f" (\"{f['text']}\")" if f.get("text") else ""
    return f"{f['host']}: {f['box']}: {f['what']} {f['kind']} by {f['by']} px{text}"

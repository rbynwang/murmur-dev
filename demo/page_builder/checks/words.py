"""Reads built pages, with their packed days opened, and checks the words of the evening-cut scope.

  python -m demo.page_builder.checks.words FOLDER_OR_PAGE [--show PHRASE ...]

The pages show only the evening peak cut: no shared battery of the community, no trading, no market or retail price, no second
business beside the aggregator. For each page (a folder: every page in it), every phrase of GONE that is still there, counted
over every piece of text the page can show: the page itself without its style sheets, and every string of each packed day.
A full record's own lines (the packed day's "l" and "long") keep the words they were recorded with, so they are counted apart
and only reported. --show prints each distinct line holding a phrase, numbers written #. Exit code 1 when a phrase is left.
Reads files only: no browser.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

GONE = ("shared batter", "Shared batter", "Two businesses", "two businesses", "4.31M", "market price", "AI request agent",
        "aggregator's AI agent", "Desk: ", "day of trading", "retailer", "Answers for itself", "community's battery",
        "request the battery can't", "within the battery's rating", "Gives when asked", "best-priced",
        "real-time price the rule is worth", "second business", "Battery and solar")
RECORD_KEYS = ("l", "long")
STYLE = re.compile(r"<style[\s\S]*?</style>")
PACK = re.compile(r'<script type="text/plain" id="fg-sc-[^"]+">([^<]+)</script>')
NUMBER = re.compile(r"\d[\d,.]*")


def strings(value: Any, shown: list[str], record: list[str]) -> None:
    """Every string inside a packed day, into `shown`; a full record's lines, as JSON text, into `record`."""
    if isinstance(value, str):
        shown.append(value)
    elif isinstance(value, dict):
        for key, v in value.items():
            if key in RECORD_KEYS:
                record.append(json.dumps(v))
            else:
                strings(v, shown, record)
    elif isinstance(value, list):
        for v in value:
            strings(v, shown, record)


def texts(page: Path) -> tuple[list[str], list[str]]:
    """The pieces of text a page can show, unescaped, and apart from them its full records' own lines."""
    source = page.read_text()
    shown, record = [" ".join(STYLE.split(source))], []
    for m in PACK.finditer(source):
        strings(json.loads(gzip.decompress(base64.b64decode(m.group(1)))), shown, record)
    return [html.unescape(t) for t in shown], record


def lines_with(pieces: list[str], phrase: str) -> dict[str, int]:
    """Each distinct stretch of text around `phrase` (spaces folded, numbers written #) and how often it stands."""
    near = re.compile(r"[^<>{}\n\"]{0,110}" + re.escape(phrase) + r"[^<>{}\n\"]{0,110}")
    found: dict[str, int] = {}
    for t in pieces:
        for m in near.finditer(t):
            key = "#".join(NUMBER.split(" ".join(m.group(0).split())))
            found[key] = found.get(key, 0) + 1
    return found


def check(page: Path, show: list[str]) -> int:
    """One page's line. Returns the number of phrases still there."""
    pieces, record = texts(page)
    left = {p: n for p in GONE if (n := sum(t.count(p) for t in pieces))}
    battery = sum(r.count("shared batter") for r in record)
    best = sum(r.count("price is best") + r.count("best-priced") for r in record)
    verdict = "nothing left that should be gone" if not left else "STILL THERE: " + json.dumps(left)
    print(f"{page.name}: {len(pieces)} pieces of text, {verdict} | the record's own lines still say shared battery {battery}"
          f" times, and name the best price {best} times")
    for phrase in show:
        for line, n in sorted(lines_with(pieces, phrase).items(), key=lambda kv: -kv[1])[:30]:
            print(f"   [{n}] {line[:240]}")
    return len(left)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.words", description="The evening-cut words.")
    ap.add_argument("where", type=Path, help="a folder of pages or one page")
    ap.add_argument("--show", action="append", default=[], metavar="PHRASE", help="print the lines that hold this phrase")
    opts = ap.parse_args(argv)
    pages = sorted(opts.where.glob("*.html")) if opts.where.is_dir() else [opts.where]
    if not pages:
        print(f"no page in {opts.where}")
        return 2
    left = sum(check(p, opts.show) for p in pages)
    print(f"{len(pages)} pages read. phrases left: {left}")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())

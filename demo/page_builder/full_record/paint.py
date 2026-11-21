"""One recorded terminal line as page text.

The words are escaped as a terminal shows them: only &, < and > are escaped, so quotes stand as recorded. Numbers with a
unit and sums of money are marked, a home or a building is named in its own colour, and a guard line marks its file and
line, the step it checked and its verdict. No word changes.
"""
from __future__ import annotations

import html
import re

from ..templating import Markup, join, render
from .naming import NODE, is_home, shown

UNIT = re.compile(r"(?<![\w.])(\$?\d[\d,]*(?:\.\d+)?(?: ?(?:kWh|kW|%|°C| C\b|s\b|ms\b)))")
MONEY = re.compile(r"(?<![\w.$])\$\d[\d,]*(?:\.\d+)?")
GUARD = re.compile(r"(\w+\.py:\d+)(\s+)(.*)", re.S)
CHECKED = re.compile(r"(#\s*steps?\s.*?)(\s+-> (?:yes|no))?$")
VERDICT = re.compile(r"-> (yes|no)$")


def term_text(plain: str) -> Markup:
    """Text as a terminal shows it."""
    return Markup(html.escape(plain, quote=False))


class Ink:
    """A terminal line being written, piece by piece, and the last page character that is not a space."""

    def __init__(self) -> None:
        self.parts: list[Markup] = []
        self.last = ">"                       # a line's text follows its element's opening tag

    def text(self, plain: str) -> None:
        if plain:
            page = term_text(plain)
            self.parts.append(page)
            self.last = page.rstrip(" ")[-1:] or self.last

    def mark(self, cls: str, page: Markup) -> None:
        self.parts.append(render("full_record/line.html#mark", cls=cls, text=page))
        self.last = ">"

    def names(self, plain: str) -> None:
        """Words with every home and building in them named and marked."""
        at = 0
        for m in NODE.finditer(plain):
            self.text(plain[at:m.start()])
            node = m.group(1)
            self.mark("h" if is_home(node) else "b", term_text(shown(node, self.last)))
            at = m.end()
        self.text(plain[at:])

    def words(self, plain: str) -> None:
        """Words with every sum of money marked."""
        at = 0
        for m in MONEY.finditer(plain):
            self.names(plain[at:m.start()])
            self.mark("n", term_text(m.group(0)))
            at = m.end()
        self.names(plain[at:])

    def page(self) -> Markup:
        return join(self.parts)


def guard_line(m: re.Match[str]) -> Markup:
    """A guard's own trace line: its file and line, the step it checked, and its verdict."""
    where, gap, body = m.groups()
    ink = Ink()
    ink.mark("d", term_text(where))
    ink.text(gap)
    step = CHECKED.search(body)
    rest = body
    if step:
        ink.text(body[:step.start()])
        ink.mark("w", term_text(step.group(1)))
        rest = body[step.end(1):]
    verdict = VERDICT.search(rest)
    if verdict:
        ink.text(rest[:verdict.start()])
        ink.mark("n" if verdict.group(1) == "yes" else "d", term_text(verdict.group(0)))
        rest = rest[verdict.end():]
    ink.text(rest)
    return ink.page()


def paint(text: str, kind: str) -> Markup:
    """A recorded line of the given kind, ready for its terminal."""
    if kind == "guard":
        m = GUARD.match(text)
        if m:
            return guard_line(m)
    if kind in ("think", "tool") and text.startswith("answer:"):
        return render("full_record/line.html#mark", cls="q", text=term_text(text))
    ink = Ink()
    at = 0
    for m in UNIT.finditer(text):
        ink.words(text[at:m.start()])
        ink.mark("n", term_text(m.group(1)))
        at = m.end()
    ink.words(text[at:])
    return ink.page()

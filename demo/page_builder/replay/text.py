"""Small helpers for the words and numbers a replay page shows: figures, times, sentences, and the painting of a terminal line
(numbers, names and a guard's verdict picked out by the highlight snippets of `templates/replay/paint.html`)."""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any

from .. import templating as T
from ..names import MARK_A, MARK_Z, named

CLIP = 300              # a long key line is cut to this many characters in the default view; Show all steps has it whole
SENTENCE = re.compile(r"(?<=[.!?])\s+")
FIGURE = re.compile(r"(?<![\w.])(\$?\d[\d,]*(?:\.\d+)?(?: ?(?:kWh|kW|%|°C| C\b|s\b|ms\b)))")
DOLLARS = re.compile(r"(?<![\w.$])(\$\d[\d,]*(?:\.\d+)?)")
GUARD_LINE = re.compile(r"(\w+\.py:\d+)(\s+)(.*)", re.S)
GUARD_STEP = re.compile(r"(#\s*steps?\s.*?)(\s+-> (?:yes|no))?$")
MARKED = re.compile(f"{MARK_A}([hb])(.*?){MARK_Z}")


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    return float(v) if isinstance(v, (int, float)) else None


def first(v: Any) -> float | None:
    if isinstance(v, (list, tuple)):
        return num(v[0]) if v else None
    return num(v)


def kw(v: Any, d: int = 0) -> str:
    x = num(v)
    return "" if x is None else f"{x:,.{d}f}"


def usd(v: Any) -> str:
    x = num(v)
    return "" if x is None else f"${x:,.2f}"


def stamp(ts: str) -> str:
    """A recorded time as the page shows it: "Tue 18:30"."""
    return f'{dt.date.fromisoformat(ts[:10]).strftime("%a")} {ts[11:16]}'


def in_scope(text: str) -> str:
    """The text without its sentences about data centers: the replay leaves them to the single sites' own lines."""
    if "data cent" not in text.lower():
        return text
    return " ".join(x for x in SENTENCE.split(text) if "data cent" not in x.lower())


def sentences(text: str) -> list[str]:
    return SENTENCE.split(text.strip())


def first_sentence(text: str) -> str:
    return sentences(text)[0]


def wrapped(text: str, cpl: int) -> int:
    """How many rows a text takes at cpl characters a row, wrapped at spaces as a browser does."""
    rows = 0
    for seg in text.split("\n"):
        n, used = 1, 0
        for w in re.split(r"(?<= )", seg):
            lw = len(w)
            if used + len(w.rstrip()) <= cpl:
                used += lw
                continue
            if lw <= cpl:
                n, used = n + 1, lw
                continue
            lw -= cpl - used
            n += lw // cpl + 1
            used = lw % cpl
        rows += n
    return rows


def trim(text: Any, n: int = 128) -> str:
    """A text cut to n characters at a clause's end where one is near, else at a word, with an ellipsis."""
    t = " ".join(str(text).split())
    if len(t) <= n:
        return t
    cut = t[:n]
    end = max(cut.rfind(". "), cut.rfind("; "))
    if end > n * .5:
        return cut[:end + 1].rstrip(";")
    for mark in (", ", ": "):
        end = cut.rfind(mark)
        if end > n * .5:
            return cut[:end]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + " …"


def text_html(text: str) -> T.Markup:
    """Plain terminal text as HTML: & < > escaped, quotes as written, each marked name in its span."""
    out, at = [], 0
    for m in MARKED.finditer(text):
        out += [html.escape(text[at:m.start()], quote=False), T.render("replay/paint.html#" + m.group(1), text=m.group(2))]
        at = m.end()
    out.append(html.escape(text[at:], quote=False))
    return T.Markup("".join(out))


def span(kind: str, text: str) -> T.Markup:
    return T.render("replay/paint.html#" + kind, text=text_html(text))


def picked(text: str, pat: re.Pattern[str], inner: Any) -> list[str]:
    """The text in pieces: each match of pat as a figure's span, the rest given to inner."""
    out, at = [], 0
    for m in pat.finditer(text):
        out += [inner(text[at:m.start()]), span("n", m.group(1))]
        at = m.end()
    out.append(inner(text[at:]))
    return out


def figures(text: str) -> T.Markup:
    return T.join(picked(text, FIGURE, lambda seg: T.join(picked(seg, DOLLARS, text_html))))


def paint(text: str, kind: str = "") -> T.Markup:
    """A terminal line as HTML. A guard's line shows its source line, the steps it reached and its verdict; a model's answer
    stands out whole; any other line has its figures and its names picked out. No word is changed."""
    if kind == "guard":
        m = GUARD_LINE.match(text)
        if m:
            return T.join([span("d", m.group(1)), text_html(m.group(2)), guard_body(m.group(3))])
    if kind in ("think", "tool") and text.startswith("answer:"):
        return span("q", text)
    return figures(text)


def guard_body(body: str) -> T.Markup:
    """The rest of a guard's line: the steps it names, and its yes or no at the end."""
    m = GUARD_STEP.search(body)
    if m:
        head, verdict = body[:m.start()], m.group(2) or ""
        return T.join([text_html(head), span("w", m.group(1)), verdict_html(verdict)])
    return verdict_html(body)


def verdict_html(text: str) -> T.Markup:
    for word, kind in (("-> yes", "n"), ("-> no", "d")):
        if text.endswith(word):
            return T.join([text_html(text[:-len(word)]), span(kind, word)])
    return text_html(text)


def paint_row(text: str, kind: str, more: int = 0) -> T.Markup:
    """A terminal line of the record as the page shows it: its node ids named, then painted. more: how many characters a cut
    line leaves out, said after it."""
    line = paint(named(text, mark=True), kind)
    return T.render("replay/paint.html#more", line=line, count=f"{more:,}") if more else line

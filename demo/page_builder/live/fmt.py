"""The live shapers' small formatters: a terminal line, a message as one line of JSON, times, figures, money, plurals, a table of
right-aligned columns, and the scrub every text goes through before it leaves.

The builder's cards parse a step's lines (replay/panels.py), so each format here is the recorded evenings' own: the comma of
thousands, the two spaces between a table's columns, the ", " and ": " of JSON. A figure that is no number raises, and so does a
line of a kind the page does not draw: the shaper's fault path then shows the item as it came (shape.Shaping.shaped).
"""
from __future__ import annotations

import json
import re
from typing import Any

KINDS = ("in", "out", "think", "calc", "sign", "tool", "guard", "write", "note")      # the kinds of line the page draws
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HEX = re.compile(r"[0-9a-f]{48,}", re.I)            # a signature, a key, a seal or a digest written whole
FOLDER = re.compile(r"(?<![\w.])(?:~|/(?:Users|home|private|tmp|var|Volumes|root|mnt|opt))/[^\s\"',;)\]}]+")
ADDRESS = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\d.])")


def T(kind: str, text: Any) -> dict[str, str]:
    """One terminal line of a step. Its kind is one of KINDS."""
    if kind not in KINDS:
        raise ValueError(f"no such kind of line: {kind!r}")
    return {"kind": kind, "text": str(text)}


def J(x: Any, n: int | None = None) -> str:
    """A value as one line of JSON, the way a line shows a message. Past n characters it is cut, and says how long it was."""
    s = json.dumps(x, separators=(", ", ": "), ensure_ascii=False, default=str)
    return s if n is None or len(s) <= n else f"{s[:n]} … ({len(s):,} characters in all)"


def cut(s: Any, n: int = 16) -> str:
    """A long id, key or seal by its first n characters."""
    s = str(s or "")
    return s[:n] + "…" if len(s) > n else s


def hm(ts: str | None) -> str:
    """The clock of a dataset time: "18:30"."""
    return (ts or "")[11:16]


def dt(ts: str | None) -> str:
    """A dataset time with its day, as a line says it: "28 Jan 18:30"."""
    return f"{int(ts[8:10])} {MONTHS[int(ts[5:7]) - 1]} {ts[11:16]}" if ts else ""


def n0(x: Any) -> str:
    return f"{float(x):,.0f}"


def n1(x: Any) -> str:
    return f"{float(x):,.1f}"


def n2(x: Any) -> str:
    return f"{float(x):,.2f}"


def usd(x: Any) -> str:
    return f"${float(x):,.2f}"


def pl(n: Any, word: str, many: str | None = None) -> str:
    """A count with its noun: "1 member", "3 members", and "2 batteries" when the plural is given."""
    return f"{n} {word if n == 1 else many or word + 's'}"


def table(head: list[Any], rows: list[list[Any]]) -> list[str]:
    """A table as lines, the head first: every column as wide as its widest cell, cells set to the right, two spaces between."""
    full = [head] + rows
    wide = [max(len(str(r[i])) for r in full) for i in range(len(head))]
    return ["  ".join(str(c).rjust(wide[i]) for i, c in enumerate(r)) for r in full]


def scrub(x: Any) -> Any:
    """A text, or every text inside a list or a dict, with nothing private left in it: a run of 48 or more hex characters is cut
    to its first 16, and a folder of the computer it ran on and a network address are named only as what they are."""
    if isinstance(x, str):
        x = HEX.sub(lambda m: m.group(0)[:16] + "…", x)
        return ADDRESS.sub("<network address>", FOLDER.sub("<local path>", x))
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [scrub(v) for v in x]
    return x

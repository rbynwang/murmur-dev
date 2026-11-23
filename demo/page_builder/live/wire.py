"""The wire forms of a live step and a live moment, as the feed sends them, with their caps and cuts.

Nothing a feed sends may become markup in the page, so a terminal line travels as pieces of [class, text]: the builder's own
painting of the line, read back as each run's text and the class of the innermost span around it. A step is {tq, n, w, sd, b, l}
and a moment {tq, id, n, b, w, hero, tag, p, c, lit, tv, k}; the feed's log gives a step its `i` and a moment its `q` and `s`.
A box travels as its id. The page refuses what is over a cap, so everything is cut here.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from ..replay.cards import fit_cols
from ..replay.text import CLIP, paint_row, trim

Piece, Line = list[str], list[Any]
KINDS = ("in", "out", "think", "calc", "sign", "tool", "guard", "write", "note")
LINE_CLASSES, PIECE_CLASSES = ("", "no", "tbl"), ("", "n", "d", "w", "q", "h", "b")
CARD_KEYS = ("h", "hot", "q", "rows", "six", "nine", "tbl", "says")
LINE_CHARS, PIECES, LINES, MOMENT_CHARS, STEPS, HOPS, LIT = 600, 24, 40, 60_000, 24, 8, 40
CARDS, ROWS, TBL_ROWS, TBL_COLS, CELL, BUBBLE, DID, TITLE = 8, 8, 6, 9, 60, 220, 400, 90
MORE_ROOM = 40          # kept free in a cut line for the words that say how much it leaves out
LOG_ROOM = 600          # kept free in a moment for what the log adds: each step's i, the moment's q and s
MORE_LINES = re.compile(r"… ([\d,]+) more lines?")


class _Runs(HTMLParser):
    """A painted line's text, run by run, each with the class of the innermost span around it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: list[str] = []
        self.runs: list[Piece] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.open.append(dict(attrs).get("class") or "")

    def handle_endtag(self, tag: str) -> None:
        if self.open:
            self.open.pop()

    def handle_data(self, data: str) -> None:
        self.runs.append([self.open[-1] if self.open and self.open[-1] in PIECE_CLASSES else "", data])


def pieces(text: str, kind: str, more: int = 0) -> list[Piece]:
    """A terminal line as [class, text] pieces: paint_row's own picking of figures, names and a guard's verdict, with no markup
    left in it. more: how many characters a cut line leaves out, said after it as paint_row says it."""
    p = _Runs()
    p.feed(str(paint_row(text, kind, more)))
    p.close()
    return p.runs


def chars(ps: list[Piece]) -> int:
    return sum(len(t) for _, t in ps)


def _few(ps: list[Piece]) -> list[Piece]:
    """At most 24 pieces: the first 23 as they are, the rest joined as one plain piece."""
    return ps if len(ps) <= PIECES else ps[:PIECES - 1] + [["", "".join(t for _, t in ps[PIECES - 1:])]]


def _whole(text: str, kind: str) -> list[Piece]:
    """A line's pieces within 600 characters. A longer text is cut before it is painted, at a space so that no name is cut in
    two, and says how many characters it leaves out. A name longer than its id can push a line over, so it is measured again."""
    n = LINE_CHARS - MORE_ROOM
    ps = pieces(text, kind) if len(text) <= LINE_CHARS else None
    while ps is None or chars(ps) > LINE_CHARS:
        cut = text[:max(n, 0)].rsplit(" ", 1)[0]
        ps = pieces(cut, kind, more=len(text) - len(cut))
        n = len(cut) - max(1, chars(ps) - LINE_CHARS)
    return _few(ps)


def line(x: dict[str, Any]) -> Line:
    """[kind, class, pieces, box ids, key mark], and for a key line over CLIP its cut pieces as a sixth item: the builder's
    line_row, in pieces. x is a line as Story.lines gives it, with the key mark Story.mark set."""
    text, kind, key = x["text"], x["k"], int(x.get("key", 0))
    row: Line = [kind if kind in KINDS else "note", x["cl"] if x["cl"] in LINE_CLASSES else "", _whole(text, kind), list(x["b"]), key]
    if key and len(text) > CLIP:
        cut = text[:CLIP].rsplit(" ", 1)[0]
        row.append(_few(pieces(cut, "", more=len(text) - len(cut))))
    return row


def _left_out(ls: list[Line]) -> tuple[int, int]:
    """The note line by which a step says how many lines it leaves out: (that count, the line's index), or (0, -1)."""
    for i, l in enumerate(ls):
        m = MORE_LINES.fullmatch(l[2][0][1]) if l[0] == "note" and len(l[2]) == 1 and l[2][0][0] == "d" else None
        if m:
            return int(m.group(1).replace(",", "")), i
    return 0, -1


def _without(ls: list[Line], gone: list[int], boxes: list[str]) -> list[Line]:
    """A step's lines without those at `gone`: one note line, where the first of them stood, says how many are left out. A
    step holds one such line, so an earlier one is counted into it."""
    if not gone:
        return ls
    was, old = _left_out(ls)
    out = (set(gone) | {old}) - {-1}
    n = was + len(out - {old})
    note: Line = ["note", "", [["d", f"… {n:,} more line{'' if n == 1 else 's'}"]], list(boxes), 0]
    return ls[:min(out)] + [note] + [l for i, l in enumerate(ls) if i > min(out) and i not in out]


def _forty(ls: list[Line], boxes: list[str]) -> list[Line]:
    """A step's lines within 40: its key lines (marks 1 and 2) and its last line, a guard's verdict, stay, and the others go
    from the middle. Only a step with more key lines than it can hold loses the last of those too."""
    need, last = len(ls) - LINES + 1, len(ls) - 1           # one more goes than is over: the note line takes a place
    if need <= 1:
        return ls
    spare = [i for i in range(last) if ls[i][4] not in (1, 2)]
    a = max(0, (len(spare) - need) // 2)
    gone = spare[a:a + need]
    kept = [i for i in range(last) if i not in gone]
    return _without(ls, sorted(gone + kept[len(kept) - (need - len(gone)):]), boxes)


def cap(text: Any, n: int) -> str:
    """A text within n characters: a longer one is trimmed at a clause's end or at a word, as the builder trims."""
    t = str(text)
    return t if len(t) <= n else trim(t, n - 2)


def step(rec: dict[str, Any], tq: int, ids: list[str]) -> dict[str, Any]:
    """A step as the feed sends it. rec is the builder's step record while its lines are still under "_l" (Story.compile's
    form before line_row), with their key marks; ids, the map's box ids in the page's order."""
    boxes = [ids[b] for b in rec["b"] if b < len(ids)]
    return {"tq": tq, "n": cap(rec["n"], TITLE), "w": cap(rec["wn"], TITLE), "sd": rec["sd"], "b": boxes,
            "l": _forty([line(x) for x in rec["_l"]], boxes)}


def _pair(x: Any, n: int) -> list[str] | None:
    return [cap(x[0], n), cap(x[1], n)] if x else None


def _table(rows: list[list[Any]]) -> list[list[Any]]:
    """A card's table within 6 rows of 9 cells: the labels and the newest columns stay."""
    return [[None if x is None else cap(x, CELL) for x in r[:1] + r[1:][1 - TBL_COLS:]] for r in rows[:TBL_ROWS]]


def _data_card(c: dict[str, Any]) -> dict[str, Any]:
    """One data card, key by key as the builder made it, every list and cell inside its cap."""
    cut = {"h": lambda v: cap(v, CELL), "hot": lambda v: 1, "q": lambda v: cap(v, BUBBLE),
           "rows": lambda v: [[cap(r[0], CELL), cap(r[1], CELL), 1 if r[2] else 0] for r in v[:ROWS]],
           "six": lambda v: [[int(r[0]), cap(r[1], CELL), cap(r[2], CELL)] for r in v[:6]],
           "nine": lambda v: [[int(r[0]), cap(r[1], CELL), cap(r[2], CELL), 1 if r[3] else 0, 1 if r[4] else 0] for r in v[:9]],
           "tbl": _table, "says": lambda v: [[cap(r[0], CELL), cap(r[1], CELL)] for r in v[:ROWS]]}
    return {key: cut[key](v) for key, v in c.items() if key in CARD_KEYS}


def moment(m: dict[str, Any], tq: int) -> dict[str, Any]:
    """A moment as the feed sends it, from the builder's own (Story.moment): its card without `rev` and `gap`, `tv` as 0 or 1,
    `big` always a list, and every list and string inside its cap."""
    k = m["k"]
    cards = [_data_card(c) for c in k["cd"][:CARDS]]
    card = {"kind": k["kind"], "cb": k["cb"], "l": int(k["l"]), "who": [[cap(a, TITLE), cap(b, TITLE)] for a, b in k["who"][:4]],
            "in": [cap(x, TITLE) for x in k["in"][:3]], "out": [cap(x, TITLE) for x in k["out"][:3]], "did": cap(k["did"], DID),
            "rule": cap(k["rule"], DID), "cd": cards, "cols": fit_cols(k["cols"], len(cards)), "term": _pair(k["term"], TITLE),
            "big": _pair(k["big"], BUBBLE) or []}
    return {"tq": tq, "id": m["id"], "n": cap(m["n"], TITLE), "b": m["b"], "w": cap(m["wn"], TITLE), "hero": _pair(m["hero"], BUBBLE),
            "tag": _pair(m["tag"], BUBBLE), "p": list(m["p"][:HOPS]), "c": cap(m["c"], CELL), "lit": list(m["lit"][:LIT]),
            "tv": 1 if m["tv"] else 0, "k": card}


def size(x: Any) -> int:
    """How many characters a value takes on the wire: its JSON with no spaces, as a browser writes it."""
    return len(json.dumps(x, ensure_ascii=False, separators=(",", ":")))


def fit(steps: list[dict[str, Any]], m: dict[str, Any]) -> None:
    """Keeps a moment with its steps within 60,000 characters: lines of key 0 go first, the longest step's before the others',
    then of key 3, then of key 1, each step saying so in its one note line. The lines that matter (key 2) and the card stay."""
    room = MOMENT_CHARS - LOG_ROOM - size(m)
    for key in (0, 3, 1):
        for s in sorted(steps, key=size, reverse=True):
            if size(steps) <= room:
                return
            old = _left_out(s["l"])[1]
            s["l"] = _without(s["l"], [i for i, l in enumerate(s["l"]) if l[4] == key and i != old], s["b"])

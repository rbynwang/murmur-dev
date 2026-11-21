"""Where it stands: the whole picture's first block. Who decides what, then three columns of headed lists: what is built,
live and recorded and what is not built; what this run simulated; what was real in it and what the recording is. The
recording's own lines (meta.simulated, meta.real, meta.engie.chain.lines) fill the second and third columns."""
from __future__ import annotations

import math
from typing import Any

from . import words as W
from .text import in_scope

Column = list[tuple[str, list[str]]]


def lines_of(text: str, cpl: float) -> int:
    return max(1, math.ceil(len(text) / max(cpl, 1)))


def col_h(col: Column, cpl: float) -> int:
    """How tall a column of headed lists runs at the world's sizes: a 22 px heading, and 19 px lines at 1.42 with 6 px under
    each item."""
    return sum(35 + 14 * bool(i) + sum(lines_of(x, cpl) * 27 + 6 for x in items) for i, (_, items) in enumerate(col))


def columns(ev: Any) -> list[Column]:
    """The three columns. The evening's lines in short go under whichever of the last two runs shorter."""
    m, com = ev.meta, ev.meta.get("community") or {}
    sim = [in_scope(str(x)) for x in (m.get("simulated") or []) if in_scope(str(x))]
    real = [in_scope(str(x)) for x in (m.get("real") or []) if in_scope(str(x))]
    run = [f"This recording: code makes every plan for all {ev.total} nodes",
           f'{m.get("day")}, {m.get("case")}' + (f", tier {m.get('tier')}" if m.get("tier") else ""),
           f'{com.get("homes")} homes, {com.get("buildings")} buildings, {ev.model_short}, {m.get("model_calls")} answers',
           f'Recorded {m.get("made_at")}. Every line and number comes from that trace']
    when = ev.engie.get("evening_words") or "One evening"
    one: Column = [("Built", list(W.BUILT)), ("Live", list(W.LIVE)),
                   (W.RECORD_HEAD, [W.RECORD_FIRST, W.RECORD_CHECK.format(when=when), W.RECORD_LAST]), ("Not built", list(W.NOT_BUILT))]
    two: Column = [("Simulated in this run", sim)]
    three: Column = [("Real in this run", real), ("This run", run)]
    (two if col_h(two, 96) <= col_h(three, 96) else three).append((W.IN_SHORT, list((ev.engie.get("chain") or {}).get("lines") or [])))
    return [one, two, three]


def height(ev: Any, w: int) -> int:
    """How tall the block must be to show every word at this width. Characters are counted at 10 px each, a little wide, so
    the estimate runs tall and never short."""
    wide = (w - 396) / 10                                           # the statement's text column: the block less its padding and labels
    who = 33 + lines_of(W.WHO_SCOPE, (w - 68) / 10) * 27 + 10 + sum(max(lines_of(a, 30), lines_of(b, wide)) * 27 + 6 for a, b in W.WHO_ROWS) + 22
    cpl = ((w - 136) / 3 - 24) / 10                                 # one of three columns, less a bullet's indent
    return int((104 + who + max(col_h(c, cpl) for c in columns(ev)) + 30) * 1.04)

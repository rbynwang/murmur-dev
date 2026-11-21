"""The notes a box carries on the whole picture: what changed in that part, and what it does not do yet (the recording's own
gaps first, then the design's)."""
from __future__ import annotations

from typing import Any

from . import words as W
from .text import first_sentence


def notes_for(ev: Any, b: str) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
    """(title, tag, was, now) for each change in box b, and (title, first sentence) for each of its gaps."""
    revs = [(t, tag, was, now) for tag, t, was, now, boxes in W.REVS if b in boxes]
    gaps = [(g["title"], first_sentence(g["actual"])) for gid, g in ev.gaps.items() if b in W.GAP_BLOCKS.get(gid, ())]
    return revs, gaps

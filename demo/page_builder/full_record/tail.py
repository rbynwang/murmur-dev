"""The sheet's last section: what changed since the last version, where it stands, where this record comes from, what
it doesn't hold, and what the flow doesn't do."""
from __future__ import annotations

from typing import Any

from ..templating import Markup, join, render
from .layers import gap_rows
from .naming import TAG, named
from .record import Record
from .words import BRANCH_ONLY, LAYER_NAMES, ON_AGENTIC, OUT_OF_TABLE, REV


def where(rec: Record, cid: str) -> str:
    """Where a change lives: on a branch, or the commit the recording names, or merged."""
    if cid in BRANCH_ONLY:
        return "on a branch"
    if cid == ON_AGENTIC:
        return "branch agentic"
    return str(rec.changes.get(cid, {}).get("commit") or "merged")


def column(col: list[tuple[str, list[str]]]) -> Markup:
    sections = [render("full_record/tail.html#column_section", title=title, items=join(render("full_record/tail.html#item", text=named(x, TAG)) for x in items)) for title, items in col]
    return render("full_record/tail.html#column", sections=join(sections))


def status_columns(rec: Record) -> Markup:
    """What is simulated in this run, with this evening in short under it; what is real, and the run itself."""
    m, c = rec.meta, rec.counts
    run = [f"This recording: code makes every plan for all {c['nodes']} nodes", f'{m.get("day")}, {m.get("case")}',
           f"{c['homes']} homes, {c['buildings']} buildings, {rec.reader}, {m.get('model_calls')} answers", f'Recorded {m.get("made_at")}. Every line and number comes from that trace']
    two = [("Simulated in this run", [str(x) for x in m["simulated"]]), ("This evening, in short", [str(x) for x in m["engie"]["chain"]["lines"]])]
    three = [("Real in this run", [str(x) for x in m["real"]]), ("This run", run)]
    return join((column(two), column(three)))


def lacks(rec: Record) -> Markup:
    """What the record doesn't hold, in its own words."""
    return render("full_record/tail.html#lacks", items=join(render("full_record/tail.html#item", text=named(x, TAG)) for x in map(str, rec.meta["not_recorded"])))


def tail(rec: Record) -> Markup:
    m: dict[str, Any] = rec.meta
    changes = [render("full_record/tail.html#change_row", title=title, tag=tag, now=now, layer=str(layer), layer_name=LAYER_NAMES[layer], where=where(rec, cid))
               for tag, title, _, now, cid, layer in REV]
    gaps = [render("full_record/tail.html#gap_row", title=title, expect=expect, actual=actual) for gid, title, expect, actual in gap_rows(rec) if gid != OUT_OF_TABLE]
    return render("full_record/tail.html#tail", changes=join(changes), when=named(m["engie"]["evening_words"], TAG), columns=status_columns(rec),
                  commit=str(m.get("code_commit") or "")[:7], made_at=str(m.get("made_at") or ""), made_by=named(m.get("made_by") or "", "."), lacks=lacks(rec), gaps=join(gaps))

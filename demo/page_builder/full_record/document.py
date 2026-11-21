"""The Full record of one recorded evening: the whole document a replay page carries in each packed day, with its own
style sheet, script and data. It shows the evening layer by layer, every terminal line as recorded, and plays it back.

The small script right after <head> keeps a link to a part of the record inside the record when the document is shown
from text in a frame. Its file has no newline at its end, as it stands on one line inside its element.
"""
from __future__ import annotations

from typing import Any

from ..templating import Markup, esc, join, render as fill, script_json, static
from .layers import sheet_layers
from .naming import TAG, named
from .record import Record
from .steps import compile_day
from .tail import tail
from .words import LAYER_HUES, LAYER_NAMES, START

CSS = ("full_record/style_sheet.css", "full_record/style_layers.css", "full_record/style_panels.css")
JS = ("full_record/script_lines.js", "full_record/script_wire.js", "full_record/script_play.js")


def run_block(rec: Record) -> Markup:
    """The block beside the sheet's title: the run, its code, the small model, the nodes and when it was recorded."""
    m, c = rec.meta, rec.counts
    rows = [("Run", f'{m.get("day")}, {m.get("case")}'), ("Code", str(m.get("code_commit") or "")[:7]), ("Small model", f'{rec.reader}, {m.get("model_calls")} answers'),
            ("Nodes", f"{c['homes']} homes, {c['buildings']} buildings"), ("Recorded", str(m.get("made_at") or ""))]
    return join(fill("full_record/frame.html#block_row", name=name, value=named(value, TAG)) for name, value in rows)


def trade(rec: Record) -> Markup:
    """The trade panel, with one column a half hour, marked where the sale stands against the evening's largest kW."""
    hs = rec.half_hours[:6]
    columns = [fill("full_record/frame.html#trade_column", k=str(k), start=str(h.get("start")), mark=f'{min(100, (h.get("sold_kw") or 0) / (rec.scale or 1) * 100):.2f}')
               for k, h in enumerate(hs)]
    labels = [fill("full_record/frame.html#trade_label", k=str(k), start=str(h.get("start"))) for k, h in enumerate(hs)]
    return fill("full_record/frame.html#trade", day=str(rec.meta.get("day") or ""), columns=join(columns), labels=join(labels))


def render(recording: dict[str, Any], name: str) -> str:
    """The Full record document of one recorded evening (a recording from demo/recordings, with neutral ids). `name`
    labels the evening in an error."""
    if not isinstance(recording.get("steps"), list) or not recording["steps"]:
        raise ValueError(f"{name}: the recording holds no steps, so it has no Full record")
    rec = Record(recording)
    day, terms, chats, first_set = compile_day(rec)
    data = {**day, "events": {}, "layers": {str(k): v for k, v in LAYER_NAMES.items()}, "start": esc(START)}
    nav = join(fill("full_record/frame.html#nav_link", n=str(n), hue=LAYER_HUES[n], name=title) for n, title in LAYER_NAMES.items())
    app = fill("full_record/frame.html#app", nav=nav, block=run_block(rec), total=str(rec.counts["nodes"]), layers=sheet_layers(rec, terms, chats, first_set),
               tail=tail(rec), trade=trade(rec))
    return str(fill("full_record/frame.html#page", keep_links=static("full_record/keep_links.js"), css=static(*CSS), app=app,
                    data=script_json(data, separators=(",", ":")), js=static(*JS)))

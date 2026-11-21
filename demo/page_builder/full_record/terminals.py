"""The record's terminals: every recorded step as rows of its layer's terminal (a title row, then the record's own lines),
and what reaches a person as a bubble in the owner's or the manager's chat."""
from __future__ import annotations

import re
from typing import Any

from ..templating import Markup, join, render
from .figures import stamp
from .naming import QUOTE, TAG, is_building, named, shown
from .paint import paint
from .record import Record
from .words import CHANGE_TAG

TERMS = ("buy", "coord", "town", "home", "bld", "queue", "tools", "dev", "people", "ret")
WHO_SHOWN = ("home", "bld", "queue", "tools", "dev", "people", "ret")       # terminals of many nodes: a step's row names its node
KIND = {"in": ("←", ""), "out": ("→", ""), "think": ("◆", "mdl"), "calc": ("=", ""), "sign": ("#", ""), "tool": ("▸", ""), "guard": ("■", ""), "write": ("⇒", ""), "note": ("·", "nt")}
NO = re.compile(r"\b(guard says blocked|refused|failed|overruled)\b")
COLUMNS = re.compile(r"\S {2,}\S")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
LABEL = re.compile(r"^(reason kept|report by model): ")
NOTE = re.compile(r'^note = "(.*)"$')
OUT_OF_SCOPE = "data cent"
RAW_ROWS = 'title="raw rows '


def in_scope(text: str) -> str:
    """The data center market is outside the Full record's scope: a sentence that names it stays out."""
    if OUT_OF_SCOPE not in text.lower():
        return text
    return " ".join(x for x in SENTENCE.split(text) if OUT_OF_SCOPE not in x.lower())


def change_tag(rec: Record, cid: str) -> Markup:
    return render("full_record/line.html#change", title=rec.changes.get(cid, {}).get("title") or cid, tag=CHANGE_TAG[cid])


def step_rows(rec: Record, s: dict[str, Any], term: str, tagged: set[tuple[str, str]]) -> list[tuple[str, Markup]]:
    """(class, inner page text) for each row of a step: its title, then the record's own lines. A change is tagged on the
    first row of each terminal that carries it."""
    raw = s.get("raw") or []
    tip = render("full_record/line.html#tip", rows=named(", ".join(map(str, raw)), RAW_ROWS)) if raw else ""
    tag: Markup | str = ""
    for c in s.get("change_ids") or []:
        if (term, c) not in tagged and c in CHANGE_TAG:
            tagged.add((term, c))
            tag = change_tag(rec, c)
            break
    node = s.get("node")
    head = {"tip": tip, "time": stamp(s.get("sim_time")), "title": named(s.get("title") or "", TAG), "tag": tag}
    if node and term in WHO_SHOWN:
        title = render("full_record/line.html#title_node", cls="b" if is_building(node) else "h", name=shown(node, TAG), **head)
    else:
        title = render("full_record/line.html#title", **head)
    rows = [("ttl", title)]
    for x in s.get("terminal") or []:
        k = x.get("kind") or "note"
        g, cl = KIND.get(k, ("·", ""))
        text = in_scope(str(x.get("text") or ""))
        if not text:
            continue
        if k in ("guard", "out") and NO.search(text):
            cl += " no"
        if k == "calc" and "\n" not in text and len(COLUMNS.findall(text)) >= 2:
            cl += " tbl"
        rows.append((f"k-{k} {cl}".strip(), render("full_record/line.html#row", glyph=g, text=paint(text, k))))
    return rows


def said(s: dict[str, Any]) -> str:
    """What a person reads at a person step: its first line, without the record's label."""
    text = next((str(t.get("text") or "") for t in s.get("terminal") or []), str(s.get("plain") or ""))
    return NOTE.sub(r"\1", LABEL.sub("", text))


def bubbles(s: dict[str, Any], step: int) -> list[tuple[str, Markup]]:
    """A person step as a bubble, in the owner's chat, the manager's, or both. What a person wrote sits on the right."""
    to = str(s.get("to") or "")
    groups = ["manager"] if to == "manager" or is_building(s.get("node")) else ["owner"]
    if to in ("people", "owners and managers"):
        groups = ["owner", "manager"]
    bubble = render("full_record/parts.html#bubble", me=" me" if str(s.get("from") or "") == "person" else "", step=str(step), time=stamp(s.get("sim_time")),
                    title=named(s.get("title") or "", "·"), text=named(said(s), TAG))
    return [(who, bubble) for who in groups]


def terminal(id_: str, name: str, what: str, lines: list[Markup], cls: str = "", size: str = "") -> Markup:
    """One layer's terminal: its caption, and every row the record put there."""
    return render("full_record/parts.html#terminal", cls=cls, id=id_, name=shown(name, TAG), what=what, size=size, label=shown(name, QUOTE), body=join(lines))

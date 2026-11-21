"""The four built sections of the architecture-and-data page, each filled from its template under `templates/overview/`:
the architecture map with its rules, the sources (the key, the map marked by source, the table of every part), the product
survey, and the recorded evening stepped through pictures of its replay.
"""
from __future__ import annotations

import base64
from typing import Iterable

from ..templating import Markup, join, render
from . import words
from .figures import Equipment, Figures, Side

REACH_CLASS = {"commanded": "cmd", "through": "via", "watched": "watch"}  # how an agent reaches a kind -> its squares' class
NOTHING = Markup("")


def _role(role: str) -> Markup:
    return render("overview/parts.html#role", role=role) if role else NOTHING


def _line(line: str) -> Markup:
    return render("overview/parts.html#line", line=line) if line else NOTHING


def _items(texts: Iterable[str]) -> Markup:
    return join(render("overview/parts.html#item", item=t) for t in texts)


# ---------------------------------------------------------------- 1. the architecture
def _box(box: words.Box, size: str) -> Markup:
    return render("overview/architecture.html#box", size=size, part=box.part, name=box.name, role=_role(box.role),
                  line=_line(box.line))


def _boxes(boxes: Iterable[words.Box], size: str) -> Markup:
    return join(_box(b, size) for b in boxes)


def _chain(boxes: Iterable[words.Box]) -> Markup:
    """Boxes one under another, an arrow between each two: a command's road from the agent down to the person."""
    return join((_box(b, "sm") for b in boxes), sep=render("overview/architecture.html#arrow"))


def architecture() -> Markup:
    return render("overview/architecture.html#section", aggregator=_boxes(words.AGGREGATOR, ""),
                  buyers=_boxes(words.BUYERS, "lite"), community=_boxes(words.COMMUNITY, "sm"), homes=_chain(words.HOME),
                  buildings=_chain(words.BUILDING), plant=_boxes(words.PLANT, "sm"), data_center=_boxes(words.DATA_CENTER, "sm"),
                  return_path=_boxes(words.RETURN_PATH, "lite"), rules=_items(words.RULES))


# ---------------------------------------------------------------- 2. where each part's data comes from
def _marks(part: str) -> Markup:
    """Four squares, one per kind of source in the order e s m o, filled where the part reads that kind."""
    reads = words.READS[part]
    said = ", ".join(words.SOURCES[k].name for k in reads) if reads else "no data of its own"
    squares = join(render("overview/sources.html#square", cls=f"{k} on" if k in reads else k) for k in words.SOURCES)
    return render("overview/sources.html#marks", said=said, squares=squares)


def _marked(boxes: Iterable[words.Box]) -> Markup:
    return join(render("overview/sources.html#marked_box", name=words.SHORT.get(b.part, b.name), marks=_marks(b.part))
                for b in boxes)


def _row(row: words.Row) -> Markup:
    part = render("overview/sources.html#part", name=row.part, role=_role(row.role),
                  line=_line(row.does) if row.reads else NOTHING)
    if not row.reads:
        return render("overview/sources.html#row_without_data", part=part, does=row.does)
    cells = []
    for kind, source in words.SOURCES.items():
        read = [text for k, text in row.reads if k == kind]
        inner = render("overview/sources.html#cell_items", name=source.name, items=_items(read)) if read else NOTHING
        cells.append(render("overview/sources.html#cell", kind=kind, items=inner))
    return render("overview/sources.html#row", part=part, cells=join(cells))


def sources(f: Figures) -> Markup:
    lines = words.key_lines(f)
    key = join(render("overview/sources.html#kind", kind=k, tag=s.tag, name=s.name, what=s.what, line=lines[k])
               for k, s in words.SOURCES.items())
    heads = join(render("overview/sources.html#head", kind=k, name=s.name) for k, s in words.SOURCES.items())
    groups = join(render("overview/sources.html#group", group=g.key, name=g.name, rows=join(_row(r) for r in g.rows))
                  for g in words.data_groups(f))
    return render("overview/sources.html#section", key=key, aggregator=_marked(words.AGGREGATOR + words.BUYERS),
                  town=_marks("town"), community_marks=_marks("co"), community=_marked(words.COMMUNITY),
                  homes=_marked(words.HOME), buildings=_marked(words.BUILDING), plant=_marked(words.PLANT),
                  data_center=_marked(words.DATA_CENTER), return_path=_marked(words.RETURN_PATH), heads=heads, groups=groups)


# ---------------------------------------------------------------- 3. the product survey
def _equipment(kind: Equipment) -> Markup:
    """One kind of equipment: one square per product, drawn by how an agent reaches it."""
    squares = join(render("overview/survey.html#product") for _ in range(kind.products))
    return render("overview/survey.html#kind", kind=kind.name, reach=REACH_CLASS[kind.reach], squares=squares,
                  products=kind.products)


def _side(side: Side, title: str, wide: bool) -> Markup:
    groups = join(render("overview/survey.html#group", group=g.name, kinds=join(_equipment(k) for k in g.kinds))
                  for g in side.groups)
    return render("overview/survey.html#side", cls="sv wide" if wide else "sv", title=title, products=side.products,
                  brands=side.brands, kinds=side.kinds, groups=groups)


def survey(f: Figures) -> Markup:
    """The survey's totals, then a home's equipment beside a building's (the building's in two columns)."""
    return render("overview/survey.html#section", products=f.products, brands=f.brands, kinds=f.kinds,
                  home_recent=f.home.dated_2025_or_later, home_products=f.home.products,
                  building_recent=f.building.dated_2025_or_later, building_products=f.building.products,
                  home=_side(f.home, words.SURVEY_TITLES["home"], wide=False),
                  building=_side(f.building, words.SURVEY_TITLES["building"], wide=True))


# ---------------------------------------------------------------- 4. the recorded evening
def evening(f: Figures, pictures: dict[int, bytes]) -> Markup:
    """The steps, and for each the picture of its replay moment: every step has its picture, and every picture its step."""
    steps = words.steps(f)
    numbers = [f.moments[s.moment].number for s in steps]
    stray, missing = sorted(set(pictures) - set(numbers)), sorted(set(numbers) - set(pictures))
    if stray or missing:
        raise ValueError(f"overview pictures: of moments no step shows {stray}, missing for the steps at moments {missing}")
    shots, cards = [], []
    for i, (step, number) in enumerate(zip(steps, numbers)):
        on = "on" if i == 0 else ""
        shots.append(render("overview/evening.html#picture", on=on, i=i, moment=number, moments=f.moments_in_the_replay,
                            title=step.title, data=base64.b64encode(pictures[number]).decode("ascii")))
        cards.append(render("overview/evening.html#card", on=on, i=i, moment=number, moments=f.moments_in_the_replay,
                            headline=f.moments[step.moment].headline, title=step.title, caption=step.caption))
    first = steps[0]
    figures = join(render("overview/evening.html#figure", figure=figure, what=what) for figure, what in words.evening_figures(f))
    return render("overview/evening.html#section", moment=numbers[0], moments=f.moments_in_the_replay,
                  headline=f.moments[first.moment].headline, title=first.title, caption=first.caption, steps=len(steps),
                  pictures=join(shots), cards=join(cards), figures=figures, year_messages=f"{f.year_set_messages:,}")

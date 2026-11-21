"""The method note: how Murmur simulates a community, its homes and its devices.

The words and layout are `templates/explainer/page.html`; the style sheet and the day chart's pointer script are in
`static/explainer/`. Two figures are computed here, from the data files beside this module:

  data/weekday_by_hour_kw.json  the host community on an average 2025 weekday: mean kW in each hour for the community
                                and for its four parts, our 200 homes, our office, our shops and other use (the rest of
                                ENGIE's record)
  data/households.json          six facts of each of the 200 simulated households (type, people at home, dwelling, age,
                                heating, cooling), one list per fact, every list in the same home order

The page's words speak of 200 homes, and the chart stacks the parts into the community's total, so the build stops
when the data say otherwise. `page.html` ends with a blank line because a template loses one trailing newline and the
document ends with one.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..templating import Markup, join, render, static

DATA = Path(__file__).resolve().parent / "data"
CHART = "explainer/day_chart.html"
HOUSEHOLDS = "explainer/households.html"

HOMES = 200
SERIES = ("community", "homes", "office", "shops", "other")  # the community first, then the parts that add up to it
PARTS_ROUNDING_KW = 2  # each series is rounded to whole kW, so the parts may miss the total by this much
TOP_KW = 3500.0  # the day chart's scale runs from 0 to this
TICKS_KW = (0, 1000, 2000, 3000)  # the scale's labels and grid lines
LABEL_EVERY_H = 3  # hours between the labels of the time axis
READ_OUT_HOUR = 19  # the hour the caption under the chart reads out
GROUPS = (  # heading, field, then each value with its label, in the order the page lists them
    ("Household type", "archetype", (("retiree", "Retired"), ("commuter", "Commuter"), ("hybrid", "Hybrid worker"),
                                     ("wfh", "Works from home"), ("family", "Family"),
                                     ("evening_shift", "Evening shift"))),
    ("People at home", "people", ((1, "One"), (2, "Two"), (3, "Three"), (4, "Four"), (5, "Five"))),
    ("Dwelling", "dwelling", (("detached", "Detached"), ("two-family", "Two-family"), ("attached", "Attached"))),
    ("Built", "vintage", (("pre_1950", "Before 1950"), ("1950_1990", "1950 to 1990"), ("post_1990", "After 1990"))),
    ("Heating", "heating", (("gas_furnace", "Furnace, gas or oil"), ("heat_pump", "Heat pump"))),
    ("Cooling", "cooling", (("central_ac", "Central air"), ("window_ac", "Window units"), ("heat_pump", "Heat pump"))),
)


def page() -> str:
    """The whole method note document."""
    day = _weekday()
    return str(render(
        "explainer/page.html",
        css=static("explainer/method_note.css"),
        script=static("explainer/day_chart.js"),
        y_labels=join(render(CHART + "#y_label", bottom=_height(kw), kw=f"{kw:,}") for kw in TICKS_KW),
        gridlines=join(render(CHART + ("#baseline" if kw == 0 else "#gridline"), bottom=_height(kw))
                       for kw in TICKS_KW),
        columns=join(_column(day, h) for h in range(24)),
        x_labels=join(render(CHART + "#x_label", column=h + 1, hour=f"{h:02d}") for h in range(0, 24, LABEL_EVERY_H)),
        callout=render(CHART + "#callout", hour=f"{READ_OUT_HOUR:02d}", **_kw_words(day, READ_OUT_HOUR)),
        household_groups=_household_groups(),
    ))


def _load(name: str) -> dict:
    """One data file of this page."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _weekday() -> dict[str, list[int]]:
    """The average weekday, checked: 24 hours of every series, and the parts adding up to the community each hour."""
    day = _load("weekday_by_hour_kw.json")
    if set(day) != set(SERIES) or any(len(day[s]) != 24 for s in SERIES):
        raise ValueError(f"weekday_by_hour_kw.json: expected 24 hourly values for each of {', '.join(SERIES)}")
    for h in range(24):
        parts, total = sum(day[s][h] for s in SERIES[1:]), day["community"][h]
        if abs(parts - total) > PARTS_ROUNDING_KW:
            raise ValueError(f"weekday_by_hour_kw.json: at hour {h} the parts make {parts} kW, the community {total}")
    return day


def _height(kw: float) -> str:
    """A level on the day chart, as a percentage of its height."""
    return f"{kw / TOP_KW * 100:.2f}"


def _kw_words(day: dict[str, list[int]], h: int) -> dict[str, str]:
    """Each series at hour `h`, written for reading (thousands separated)."""
    return {s: f"{day[s][h]:,}" for s in SERIES}


def _column(day: dict[str, list[int]], h: int) -> Markup:
    """One hour of the chart: other use at the bottom, then the office and shops together, then the homes."""
    kw = {s: day[s][h] for s in SERIES}
    label = render(CHART + "#column_label", hour=f"{h:02d}", **_kw_words(day, h))
    return render(CHART + "#column", label=label, hour=h, **kw, other_height=_height(kw["other"]),
                  buildings_height=_height(kw["office"] + kw["shops"]), homes_height=_height(kw["homes"]))


def _household_groups() -> Markup:
    """The six bar groups: for each listed value, how many of the 200 homes have it, on one scale of 0 to 200."""
    homes = _load("households.json")
    fields = [field for _, field, _ in GROUPS]
    if set(homes) != set(fields):
        raise ValueError(f"households.json: expected the fields {', '.join(fields)}")
    groups = []
    for title, field, values in GROUPS:
        counts = Counter(homes[field])
        if len(homes[field]) != HOMES or set(counts) != {value for value, _ in values}:
            raise ValueError(f"households.json: {field} must hold one of the listed values for each of {HOMES} homes")
        rows = join(render(HOUSEHOLDS + "#row", label=label, width=f"{100 * counts[value] / HOMES:.1f}",
                           count=counts[value]) for value, label in values)
        groups.append(render(HOUSEHOLDS + "#group", title=title, rows=rows))
    return join(groups)

"""The live fixtures' one loader: two evenings of the example configuration, each as a console would have read it in passes of 0.25 s.

tests/fixtures/live/ holds them, and its README.md says what each file holds and how it was cut. The capture "evening" is the whole example
evening from the start to settled; "surprises" is the quarter-hours around seven surprises of a second evening. A capture has one file for each
source: the conductor's view, the bus record, the sale's two doors, the nodes' record rows, the meter's fed rows and the driver's own posts.

  facts()                  what a live evening is made from (day, homes, buildings, sites, follow, half_hours, model), the window, the orders,
                           the configuration's events, and what each capture was
  load(capture)            every source's items in the order they were read, each with `t`: its pass's wall time in seconds from the capture's start
  passes(capture)          the same items pass by pass: what a console would have read in each pass
  burst(capture)           the same items in the same order as one pass that reads everything at once
  report_counts(capture)   the community.report rows that were not kept, counted by quarter-hour and sender

Every value keeps its source's own form: a bus event as the bus record gives it, a row as the hosts' record door serves it, an answer as its door
gave it. What was changed is in the README (addresses, wall-clock stamps, long hex runs). Each call builds its values anew, so a test may change them.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, NamedTuple

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "live"
CAPTURES = ("evening", "surprises")
SOURCES = ("conductor", "bus", "sale", "rows", "meter", "posts")          # one file a source: <capture>_<source>.json


class Pass(NamedTuple):
    """What one pass of a console read, the conductor first (the specification's 5.4)."""
    t: float                                 # wall seconds from the capture's start, taken as the pass began
    part: int                                # the stretch of the capture the pass lies in: 0, and 1 for the later stretch of "surprises"
    conductor: dict[str, Any]                # GET {community}/demo/conductor
    bus: list[dict[str, Any]]                # the bus record's new `accepted` events, oldest first: {event, message_id, from, to, kind, body, at}
    reports: dict[str, int]                  # the community.report rows read in this pass that were not kept: how many, by sender
    rows: dict[str, list[dict[str, Any]]]    # each node's new record rows, as the record door serves them
    summary: dict[str, Any]                  # GET {community}/v2/summary, as this pass read it
    snapshots: list[dict[str, Any]]          # {trigger, id, event}: GET {community}/v2/events/{id}, read when a trigger fell in this pass
    meter: list[dict[str, Any]]              # the meter's new fed rows: {ts, homes_kw, buildings_kw}
    posts: list[dict[str, Any]]              # the driver's own posts: {part, path, body, status, answer, what}, a surprise's also {kind, who, at, from}


@lru_cache(maxsize=None)
def _text(name: str) -> str:
    return (FOLDER / name).read_text()


def _plain(v: Any, shapes: list[list[str]], shared: list[Any]) -> Any:
    """A packed value as it was read: [0, ...] is a list, [k, ...] a dict with the keys of shape k, [-k] the k-th shared value."""
    if not isinstance(v, list):
        return v
    if v[0] < 0:
        return _plain(shared[-v[0] - 1], shapes, shared)
    if v[0] == 0:
        return [_plain(x, shapes, shared) for x in v[1:]]
    return {k: _plain(x, shapes, shared) for k, x in zip(shapes[v[0] - 1], v[1:])}


def _items(capture: str, source: str) -> list[dict[str, Any]]:
    f = json.loads(_text(f"{capture}_{source}.json"))
    return [_plain(v, f["shapes"], f["shared"]) for v in f["items"]]


def _less(x: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in x.items() if k not in keys}


def facts() -> dict[str, Any]:
    """facts.json: day, homes, buildings, sites, follow, half_hours and model, as a LiveEvening takes them; window, buyers, orders (the bodies
    posted to the buyers), events (the configuration's), requests (the aggregator's, each with its made_at); and under "captures" what each
    capture was: its gates and stops, its leaps, its sale's totals, its surprises, its bus messages by kind."""
    return json.loads(_text("facts.json"))


def load(capture: str) -> dict[str, list[dict[str, Any]]]:
    """Every item of a capture by source, in the order it was read:

      conductor   {t, part, view}                       one a pass
      bus         {t, event}                            an `accepted` event of the bus record; its `at` is in the capture's seconds too
      reports     {t, now, count: {sender: n}}          the community.report rows of a pass that were not kept
      sale        {t, summary}                          /v2/summary when it differed from the pass before
                  {t, trigger, id, event}               /v2/events/{id} at a trigger: select, telemetry_done, settlement, done
      rows        {t, node, row}                        a row of a node's record
      meter       {t, ts, homes_kw, buildings_kw}       a quarter-hour the meter fed
      posts       {t, part, path, body, status, answer, what}    an order or a surprise; a surprise also has kind, who, at, from"""
    if capture not in CAPTURES:
        raise ValueError(f"a capture is one of {CAPTURES}")
    got = {source: _items(capture, source) for source in SOURCES}
    got["reports"] = [x for x in got["bus"] if "count" in x]
    got["bus"] = [x for x in got["bus"] if "event" in x]
    return got


def passes(capture: str) -> Iterator[Pass]:
    """The capture pass by pass, in order: what a console would have read in each pass of 0.25 s. A pass that read nothing new still comes, with
    its conductor's view and the summary as it stood. Between two stretches of "surprises" the passes that were not kept are simply absent."""
    got = load(capture)
    at: dict[str, dict[float, list[dict[str, Any]]]] = {source: {} for source in got}
    for source, items in got.items():
        for x in items:
            at[source].setdefault(x["t"], []).append(x)
    summary: dict[str, Any] = {}
    for c in got["conductor"]:
        t = c["t"]
        sale = at["sale"].get(t, [])
        summary = next((x["summary"] for x in sale if "summary" in x), summary)
        rows: dict[str, list[dict[str, Any]]] = {}
        for x in at["rows"].get(t, []):
            rows.setdefault(x["node"], []).append(x["row"])
        reports = {who: n for x in at["reports"].get(t, []) for who, n in x["count"].items()}
        yield Pass(t, c["part"], c["view"], [x["event"] for x in at["bus"].get(t, [])], reports, rows, copy.deepcopy(summary),
                   [_less(x, "t") for x in sale if "event" in x], [_less(x, "t") for x in at["meter"].get(t, [])], [_less(x, "t") for x in at["posts"].get(t, [])])


def burst(capture: str) -> Pass:
    """The capture as one pass: what a console would have read had it come once, at the end. Its bus events, rows, snapshots, meter rows and posts
    are those of passes(capture) in the same order; its conductor's view and its summary are the last ones, its report counts the sums."""
    got = load(capture)
    rows: dict[str, list[dict[str, Any]]] = {}
    for x in got["rows"]:
        rows.setdefault(x["node"], []).append(x["row"])
    reports: dict[str, int] = {}
    for x in got["reports"]:
        for who, n in x["count"].items():
            reports[who] = reports.get(who, 0) + n
    last, sale = got["conductor"][-1], got["sale"]
    return Pass(last["t"], last["part"], last["view"], [x["event"] for x in got["bus"]], reports, rows, [x["summary"] for x in sale if "summary" in x][-1],
                [_less(x, "t") for x in sale if "event" in x], [_less(x, "t") for x in got["meter"]], [_less(x, "t") for x in got["posts"]])


def report_counts(capture: str) -> dict[str, dict[str, int]]:
    """The community.report rows that were not kept, {quarter-hour: {sender: n}}: the quarter-hour is the one the conductor's clock held in the
    pass that read them."""
    out: dict[str, dict[str, int]] = {}
    for x in load(capture)["reports"]:
        day = out.setdefault(x["now"], {})
        for who, n in x["count"].items():
            day[who] = day.get(who, 0) + n
    return out

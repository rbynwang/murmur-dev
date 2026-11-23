"""The live fixtures (tests/fixtures/live/) and their one loader (live_fixture.py): fed pass by pass or as one burst they give the same items
in the same order, every file parses and unpacks, and the files stay under the sizes and inside the scrub rules they were cut to."""
from __future__ import annotations

import json
import re

import pytest

from tests.page_builder import live_fixture as F

EVENING_MAX, FOLDER_MAX = 200_000, 320_000          # bytes: the first capture's six files; the whole folder, both captures in it
LISTS = ("bus", "snapshots", "meter", "posts")
FACTS = {"day", "window", "homes", "buildings", "sites", "follow", "half_hours", "model", "orders", "events", "captures"}
PRIVATE = (re.compile(r"127\.0\.0\.1|localhost|http://"),           # an address of the run (what a message cites is https)
           re.compile(r"[0-9a-fA-F]{48,}"),                          # a hash, a key or a signature left whole
           re.compile(r"(?<=[\[,: ])1[6-9]\d{8}(?:\.\d+)?(?=[,\]}\n])"))   # a number that is a wall-clock stamp in seconds since 1970


def files() -> list:
    """The folder's own files: not what a file browser leaves beside them."""
    return sorted(f for f in F.FOLDER.iterdir() if not f.name.startswith("."))


@pytest.mark.parametrize("capture", F.CAPTURES)
def test_passes_and_one_burst_give_the_same_items_in_the_same_order(capture):
    every, one = list(F.passes(capture)), F.burst(capture)
    for name in LISTS:
        assert [x for p in every for x in getattr(p, name)] == getattr(one, name), name
    assert list(one.rows) == list(dict.fromkeys(node for p in every for node in p.rows))
    for node, rows in one.rows.items():
        assert [r for p in every for r in p.rows.get(node, [])] == rows, node
    assert one.reports == {who: sum(p.reports.get(who, 0) for p in every) for who in one.reports}
    assert set(one.reports) == {who for p in every for who in p.reports}
    assert (one.t, one.part, one.conductor, one.summary) == (every[-1].t, every[-1].part, every[-1].conductor, every[-1].summary)


@pytest.mark.parametrize("capture", F.CAPTURES)
def test_every_item_is_read_in_one_pass_and_in_order(capture):
    got, every = F.load(capture), list(F.passes(capture))
    times = [p.t for p in every]
    assert times == sorted(set(times)) and len(got["conductor"]) == len(every)
    for source, items in got.items():
        assert [x["t"] for x in items] == sorted(x["t"] for x in items), source
        assert {x["t"] for x in items} <= set(times), source
    assert [e for p in every for e in p.bus] == [x["event"] for x in got["bus"]]
    assert [x["event"]["at"] for x in got["bus"]] == sorted(x["event"]["at"] for x in got["bus"])        # as the bus accepted them
    for node in {x["node"] for x in got["rows"]}:
        ns = [x["row"]["n"] for x in got["rows"] if x["node"] == node]
        assert ns == sorted(set(ns)), node                                                              # a node's rows in its record's order
    assert [r for p in every for rows in p.rows.values() for r in rows] == [x["row"] for x in got["rows"]]
    assert [m["ts"] for p in every for m in p.meter] == [x["ts"] for x in got["meter"]]
    assert [q["body"] for p in every for q in p.posts] == [x["body"] for x in got["posts"]]
    assert sum(len(p.snapshots) for p in every) == sum(1 for x in got["sale"] if "event" in x)
    assert all(p.summary.get("now") for p in every)                 # every pass has the summary it read, changed or not
    assert F.report_counts(capture) and sum(n for by in F.report_counts(capture).values() for n in by.values()) == sum(sum(p.reports.values()) for p in every)
    again = next(F.passes(capture))
    again.conductor.clear()
    assert next(F.passes(capture)).conductor == every[0].conductor  # each call builds its values anew


@pytest.mark.parametrize("capture", F.CAPTURES)
def test_a_capture_holds_what_its_facts_say(capture):
    got, one, said = F.load(capture), F.burst(capture), F.facts()["captures"][capture]
    kinds: dict[str, int] = {}
    for e in one.bus:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    assert kinds == said["bus"]["whole"] and sum(one.reports.values()) == said["bus"]["reports_counted"]
    assert {node: len(rows) for node, rows in one.rows.items()} == said["rows"]
    assert (len(got["conductor"]), len(one.meter), [s["trigger"] for s in one.snapshots]) == (said["passes"], said["meter_rows"], said["snapshots"])
    assert sum(1 for x in got["sale"] if "summary" in x) == said["summaries"]
    assert [(q["kind"], q["at"]) for q in one.posts if q["what"] == "surprise"] == [(s["kind"], s["at"]) for s in said["surprises"] if s["in_capture"] for _ in s["to"]]


def test_the_whole_evening_is_whole():
    one, facts = F.burst("evening"), F.facts()
    assert set(one.rows) == set(facts["homes"]) | set(facts["buildings"])
    for node, rows in one.rows.items():
        assert [r["n"] for r in rows] == list(range(1, len(rows) + 1)), node       # a node's record from its first row, none left out
    sale = one.summary["events"][facts["captures"]["evening"]["sale"]]
    assert sale["phase"] == "done" and [s["trigger"] for s in one.snapshots] == [["select"], ["telemetry_done"], ["settlement", "done"]]
    result, totals = sale["result"], facts["captures"]["evening"]["totals"]
    assert (result["seller_usd"], result["split"]["pool"], result["delivered_kwh_measured"]) == (totals["seller_usd"], totals["pool_usd"], totals["delivered_kwh"])


def test_every_file_parses_and_unpacks():
    assert [f.name for f in files()] == sorted(["README.md", "facts.json"] + [f"{c}_{s}.json" for c in F.CAPTURES for s in F.SOURCES])
    for capture in F.CAPTURES:
        for source in F.SOURCES:
            f = json.loads((F.FOLDER / f"{capture}_{source}.json").read_text())
            assert list(f) == ["about", "shapes", "shared", "items"] and f["items"], (capture, source)
            assert all(isinstance(k, str) for shape in f["shapes"] for k in shape)
        got = F.load(capture)
        assert all(isinstance(x, dict) and isinstance(x["t"], float) for items in got.values() for x in items)
    facts = F.facts()
    assert FACTS <= set(facts) and set(facts["captures"]) == set(F.CAPTURES)
    assert all(set(c["files"]) == set(F.SOURCES) for c in facts["captures"].values())


def test_the_files_stay_under_their_sizes():
    evening = sum((F.FOLDER / f"evening_{source}.json").stat().st_size for source in F.SOURCES)
    folder = sum(f.stat().st_size for f in files())
    assert evening < EVENING_MAX and folder < FOLDER_MAX, (evening, folder)


def test_nothing_private_is_in_a_file():
    for f in files():
        text = f.read_text()
        for pattern in PRIVATE:
            assert not pattern.search(text), (f.name, pattern.pattern)
    for capture in F.CAPTURES:
        for p in F.passes(capture):
            assert all(e["at"] < 3600 for e in p.bus) and p.t < 3600       # wall time is counted from the capture's start

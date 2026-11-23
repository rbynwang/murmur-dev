"""The live shapers, the story, the wire and the console's log together, on the two captured evenings (tests/fixtures/live).

What a page is sent for the example evening must be the evening that ran: its moments in clock order, every card kind the replay
draws, the sale's figures where they belong, and every answer within the feed's fixed lists and caps.
"""
from __future__ import annotations

import json
import re

import pytest

from demo.console import timeline as TL
from demo.console.feed import Log
from demo.console.intake import Intake
from demo.page_builder.live import shape_bus, wire
from demo.page_builder.live.shape import Shaping
from tests.page_builder import live_fixture as F

FACTS = F.facts()
FOLLOW = list(FACTS["follow"].values())
CARD_KINDS = {"aggpart", "buyers", "market", "node", "model", "chain", "device", "people", "ret", "desk"}


def timeline() -> TL.Timeline:
    return TL.build({"date": FACTS["day"], "window": FACTS["window"]}, FACTS.get("events"))


def run(capture: str) -> tuple[Intake, Log]:
    log = Log()
    log.reset(1, {"key": "one", "boxes": []}, timeline())
    it = Intake(FACTS, FOLLOW, {}, log)
    for p in F.passes(capture):
        it.take(p._replace(rows={n: r for n, r in p.rows.items() if n in FOLLOW}))
    return it, log


@pytest.fixture(scope="module")
def evening() -> tuple[Intake, Log]:
    return run("evening")


@pytest.fixture(scope="module")
def surprises() -> tuple[Intake, Log]:
    return run("surprises")


def by_id(log: Log, mid: str) -> list[dict]:
    return [m for m in log.moments if m["id"] == mid]


def test_the_shapers_and_the_timeline_count_quarter_hours_alike():
    tl = timeline()
    sh = Shaping(None, (), None, tl.t0)
    for q in range(tl.n + 1):
        assert sh.tq(tl.ts(q)) == tl.tq(tl.ts(q)) == q


def test_the_whole_evening_shapes_without_a_fault_and_shows_every_card_kind(evening):
    it, log = evening
    f = it.faults()
    assert f["shape"] == 0 and f["cards"] == 0 and f["ahead"] == 0
    assert f["orphans"] <= 1                    # a member's "no longer short" in a quarter-hour where the desk did nothing else
    assert log.faults == {"form": 0, "over": 0, "full": 0, "set": 0}
    assert {m["k"]["kind"] for m in log.moments} == CARD_KINDS
    assert 30 <= len(log.moments) <= 60


def test_moments_come_in_clock_order_and_tell_the_evening_in_its_order(evening):
    _, log = evening
    tqs = [m["tq"] for m in log.moments]
    assert tqs == sorted(tqs)
    first = {}
    for m in log.moments:
        first.setdefault(m["id"], m["q"])
    order = ["orders", "ask", "call", "home-model", "offers-in", "book", "buyer-contract", "node-contract", "frozen", "tomorrow",
             "battery-ask", "note-read", "watch-home", "desk", "window", "report", "readings", "settle", "pay"]
    assert [first[i] for i in order] == sorted(first[i] for i in order)


def test_the_sale_s_figures_are_the_evening_s_own(evening):
    _, log = evening
    assert by_id(log, "settle")[0]["hero"][0] == "$20.79"
    assert by_id(log, "pay")[0]["hero"][0] == "$14.57"
    assert "26 kWh" in by_id(log, "settle")[0]["hero"][1]
    assert by_id(log, "orders")[0]["hero"][0] == "14 kW"
    assert by_id(log, "node-contract")[0]["hero"][0] == "3"
    assert len(by_id(log, "window")) == 6                         # each half hour of the window, once


def test_the_note_is_read_by_the_small_model_and_its_person_is_told(evening):
    _, log = evening
    read = by_id(log, "note-read")[0]
    assert read["k"]["kind"] == "model" and read["hero"][0] == "Keep the battery full"
    lines = [t for i in read["s"] for x in log.steps[i]["l"] for _, t in x[2]]
    assert any(t.startswith("system: You read a note") for t in lines)
    assert by_id(log, "told") and by_id(log, "told")[0]["k"]["kind"] == "people"


def test_a_device_call_is_shown_through_the_guard_and_the_driver(evening):
    _, log = evening
    chain = by_id(log, "watch-home")[0]
    assert chain["k"]["kind"] == "chain"
    text = " ".join(t for i in chain["s"] for x in log.steps[i]["l"] for _, t in x[2])
    assert re.search(r"guard says done", text) and "seals the command" in text and "driver answers done" in text


def test_each_surprise_kind_gives_its_own_moment_and_what_followed(surprises):
    it, log = surprises
    f = it.faults()
    assert f["shape"] == 0 and f["cards"] == 0
    kinds = {m["id"] for m in log.moments}
    for k in ("emergency", "battery_fault", "battery_low", "weather", "car_now", "building_need", "building_closed"):
        assert f"s-{k}" in kinds
    assert {"call-in", "call-desk", "exc-code", "note-read"} <= kinds
    call = by_id(log, "call-desk")[0]
    assert call["hero"][1] == "confirmed of 20 kW called"


def test_a_bus_message_of_no_known_kind_is_counted_not_shown():
    sh = Shaping(None, ["home-02"], None, timeline().t0)
    assert shape_bus.steps(sh, {"kind": "beckn.something_new", "body": {}}, 1, 0.0) == []
    assert sh.count["something_new"] == 1 and sh.faults["shape"] == 0


def test_every_answer_cursor_by_cursor_keeps_the_feed_s_lists_and_caps(evening):
    _, log = evening
    since, seen = 0, []
    for _ in range(200):
        a = log.answer({"schema": "murmur.live.v1"}, str(since))
        v = a["v2"]
        text = json.dumps(a)
        assert len(text) <= 262_144
        assert not re.search(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}:\d+|/Users/|/private/", text)
        for s in v["steps"]:
            assert len(s["l"]) <= wire.LINES
            for line in s["l"]:
                assert line[0] in wire.KINDS and line[1] in wire.LINE_CLASSES and 0 <= line[4] <= 3
                assert all(c in wire.PIECE_CLASSES and isinstance(t, str) for c, t in line[2])
        for m in v["moments"]:
            assert m["k"]["kind"] in CARD_KINDS and 1 <= len(m["s"]) <= wire.STEPS
            assert all(isinstance(b, str) for b in m["lit"]) and len(m["p"]) <= wire.HOPS + 1
        seen += [m["q"] for m in v["moments"]]
        if not v["more"] and v["next"] == since:
            break
        since = v["next"]
    assert seen == list(range(1, len(log.moments) + 1))

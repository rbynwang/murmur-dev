"""The console's timeline: the count of quarter-hours, an evening's parts, pins and stops, and how the pins are marked by the clock."""
from __future__ import annotations

import pytest

from demo.console import timeline as T

DAY, T0 = "2025-01-28", "2025-01-27 09:45"


def evening(**over) -> dict:
    """The example evening as the runner holds it: its window, its rows from the day before at 10:00, the aggregator's request."""
    return {"date": DAY, "window": ["18:00", "21:00"], "feed": {"2025-01-27 10:00": {}, "2025-01-28 12:00": {}, "2025-01-29 02:45": {}},
            "battery_request": {"made_at": "2025-01-28 14:00", "rows": []}} | over


NOTE = {"at": "2025-01-28 17:00", "kind": "note", "homes": ["home-02"], "text": "Please keep the battery full tonight."}


def test_quarter_hours_count_from_a_quarter_to_ten_on_the_day_before_the_sale():
    tl = T.build(evening(), [])
    assert tl.t0 == T0
    assert (tl.tq(T0), tl.tq("2025-01-27 10:00"), tl.tq("2025-01-28 18:00"), tl.tq("2025-01-29 02:45")) == (0, 1, 129, 164)
    assert T.tq("2025-01-28 18:00", T0) == 129                                    # the same count without a timeline in hand
    assert [tl.ts(q) for q in (0, 1, 129)] == [T0, "2025-01-27 10:00", "2025-01-28 18:00"]
    assert all(tl.tq(tl.ts(q)) == q for q in range(0, 401, 7))


@pytest.mark.parametrize("ts, q", [("2025-01-28 18:14", 129), ("2025-01-28 18:15", 130), ("2025-01-28T18:29:59", 130), ("2025-01-28 18:00:00.25", 129),
                                   ("2025-01-27 09:44", -1), ("2025-01-27 09:30", -1)])
def test_a_time_inside_a_quarter_hour_counts_with_its_start(ts, q):
    assert T.tq(ts, T0) == q


@pytest.mark.parametrize("ts", ["", "18:00", "2025-01-28", None, 129, "2025-13-01 10:00", "yesterday at six"])
def test_a_text_that_is_no_dataset_time_is_a_value_error(ts):
    with pytest.raises(ValueError):
        T.tq(ts, T0)


def test_the_five_parts_run_from_the_day_before_to_ninety_minutes_after_the_window():
    tl = T.build(evening(), [NOTE])
    assert [p["id"] for p in tl.parts] == list(T.PARTS) == ["dayahead", "request", "before", "window", "settle"]
    assert [(p["from"], p["to"]) for p in tl.parts] == [(0, 57), (57, 125), (125, 129), (129, 141), (141, 147)]
    assert tl.n == 147 == tl.parts[-1]["to"] and (tl.first, tl.last) == ("2025-01-27 10:00", "2025-01-29 02:45")
    assert all(a["to"] == b["from"] and a["from"] < a["to"] for a, b in zip(tl.parts, tl.parts[1:]))


def test_the_stops_are_the_sale_ten_oclock_each_request_each_event_the_hour_before_every_quarter_hour_of_delivery_and_the_readings():
    tl = T.build(evening(), [NOTE])
    window = [f"2025-01-28 {h}:{m}" for h in ("18", "19", "20") for m in ("00", "15", "30", "45")]
    assert tl.stops == ["2025-01-27 10:00", "2025-01-28 10:00", "2025-01-28 14:00", "2025-01-28 17:00", "2025-01-28 17:30", "2025-01-28 17:45",
                        *window, "2025-01-28 21:00", "2025-01-28 21:15", "2025-01-28 21:30", "2025-01-28 21:45"]
    assert len(tl.stops) == 22 and tl.stops == sorted(set(tl.stops))
    more = T.build(evening(), [NOTE, {"at": "2025-01-28 12:20", "kind": "cloud"}, {"at": "2025-01-28 19:00", "kind": "emergency"}])
    assert set(more.stops) - set(tl.stops) == {"2025-01-28 12:15"}             # an event inside a quarter-hour stops the clock at its start


def test_the_six_named_stops_are_the_pins():
    tl = T.build(evening(), [NOTE])
    assert tl.pins == [{"tq": 1, "kind": "stop", "id": "sale"}, {"tq": 113, "kind": "stop", "id": "request"},
                       {"tq": 125, "kind": "stop", "id": "before"}, {"tq": 129, "kind": "stop", "id": "delivery"},
                       {"tq": 141, "kind": "stop", "id": "end"}, {"tq": 144, "kind": "stop", "id": "readings"}]
    assert [p["id"] for p in tl.pins] == list(T.STOPS) and all(tl.ts(p["tq"]) in tl.stops for p in tl.pins)


def test_the_request_pin_is_the_earliest_request_and_an_evening_without_one_has_five_pins():
    sites = {"site-dc-01": {"requests": [{"made_at": "2025-01-28 09:00", "rows": []}, {"made_at": "2025-01-28 15:30", "rows": []}]},
             "site-pv-01": {"requests": []}}
    tl = T.build(evening(), [], sites)
    assert next(p for p in tl.pins if p["id"] == "request")["tq"] == tl.tq("2025-01-28 09:00") == 93
    assert {"2025-01-28 09:00", "2025-01-28 14:00", "2025-01-28 15:30"} <= set(tl.stops)
    bare = T.build(evening(battery_request=None), [])
    assert [p["id"] for p in bare.pins] == ["sale", "before", "delivery", "end", "readings"] and "2025-01-28 14:00" not in bare.stops


def test_nothing_outside_the_evenings_rows_is_a_stop_or_a_pin():
    short = T.build(evening(feed={"2025-01-27 10:00": {}, "2025-01-28 21:45": {}}), [{"at": "2025-01-30 08:00", "kind": "note"}, {"at": "2025-01-26 08:00", "kind": "note"}])
    assert short.stops[0] == "2025-01-27 10:00" and short.stops[-1] == "2025-01-28 21:45" == short.last
    assert [p["id"] for p in short.pins] == ["sale", "request", "before", "delivery", "end", "readings"]
    cut = T.build(evening(feed={"2025-01-27 10:00": {}, "2025-01-28 21:30": {}}), [])
    assert [p["id"] for p in cut.pins][-1] == "end" and cut.stops[-1] == "2025-01-28 21:30"
    assert T.build(evening(feed={}), []).last == "2025-01-29 02:45"               # without rows: to a quarter to three, the night after


def test_a_window_that_ends_after_midnight_ends_on_the_next_day():
    tl = T.build(evening(window=["22:00", "01:00"]), [])
    assert {p["id"]: p["tq"] for p in tl.pins}["end"] == tl.tq("2025-01-29 01:00") == 157
    assert [(p["from"], p["to"]) for p in tl.parts][-2:] == [(145, 157), (157, 163)] and "2025-01-29 00:45" in tl.stops


@pytest.mark.parametrize("bad", [{}, {"date": DAY}, {"date": DAY, "window": ["18:00"]}, {"date": "tomorrow", "window": ["18:00", "21:00"]},
                                 {"date": DAY, "window": ["six", "nine"]}, {"date": DAY, "window": None}])
def test_an_evening_without_a_day_or_a_window_is_refused(bad):
    with pytest.raises(ValueError):
        T.build(bad, [])


@pytest.mark.parametrize("window", [["00:00", "00:15"], ["00:30", "00:15"], ["23:45", "23:30"], ["12:00", "12:00"]])
def test_every_window_of_a_day_gives_five_parts_in_order_inside_what_the_page_takes(window):
    tl = T.build(evening(window=window), [])
    edges = [tl.parts[0]["from"], *(p["to"] for p in tl.parts)]
    assert len(tl.parts) == 5 and edges == sorted(set(edges)) and edges[0] == 0 and tl.n == edges[-1] <= T.TOP == 400


@pytest.mark.parametrize("now, states", [(0, ["next", "ahead", "ahead", "ahead", "ahead", "ahead"]), (1, ["past", "next", "ahead", "ahead", "ahead", "ahead"]),
                                         (128, ["past", "past", "past", "next", "ahead", "ahead"]), (129, ["past", "past", "past", "past", "next", "ahead"]),
                                         (141, ["past", "past", "past", "past", "past", "next"]), (400, ["past"] * 6)])
def test_a_pin_is_past_once_the_clock_has_reached_it_the_first_after_it_is_next(now, states):
    pins = T.build(evening(), []).pins
    out = T.marked(pins, now, True)
    assert [p["state"] for p in out] == states
    assert [p["jump"] for p in out] == [s != "past" for s in states]                 # a stop ahead of a running clock may be run to
    assert not any(p["jump"] for p in T.marked(pins, now, False))                   # and none while no clock runs
    assert all(set(p) == {"tq", "kind", "id", "state", "jump"} for p in out)


def test_pins_leave_in_clock_order_and_a_surprise_is_never_run_to():
    pins = [{"tq": 129, "kind": "stop", "id": "delivery"}, {"tq": 131, "kind": "surprise", "id": "weather"}, {"tq": 1, "kind": "stop", "id": "sale"},
            {"tq": 126, "kind": "surprise", "id": "note", "more": "left out"}]
    out = T.marked(pins, 125, True)
    assert [(p["tq"], p["id"], p["state"], p["jump"]) for p in out] == [(1, "sale", "past", False), (126, "note", "next", False),
                                                                        (129, "delivery", "ahead", True), (131, "weather", "ahead", False)]
    assert pins[0] == {"tq": 129, "kind": "stop", "id": "delivery"}                   # what was given is left as it was

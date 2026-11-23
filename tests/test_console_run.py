"""The running console's own decisions, without a network: who its story follows and by what name, the roster a presenter picks
from, each surprise's doors and the quarter-hours it makes the clock play, and the driver's state word and pacing hold."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from demo.console import settings, surprises
from demo.console.driver import Driver


def runner(tmp_path, events=None, buildings=("building-01",)):
    (tmp_path / "buildings.json").write_text(json.dumps({"building-01": {"short": "office", "name": "An office"}}))
    return SimpleNamespace(evening={"date": "2025-01-28", "window": ["18:00", "21:00"], "feed": {}}, events=events or [], sites={},
                           homes=["home-01", "home-02", "home-03"], buildings=list(buildings), buyers=["grid-operator", "utility"],
                           data_dir=tmp_path, model={"stand_in": True})


def test_the_story_follows_the_noted_home_the_next_home_and_the_first_building(tmp_path):
    s = runner(tmp_path, events=[{"kind": "note", "homes": ["home-02"], "at": "2025-01-28 17:00"}])
    assert settings.follow_of(s) == ["home-02", "home-01", "building-01"]
    assert settings.follow_of(runner(tmp_path)) == ["home-01", "home-02", "building-01"]
    assert settings.follow_of(s, ["home-03"]) == ["home-03"]


def test_an_office_takes_the_page_s_name_for_an_office(tmp_path):
    s = runner(tmp_path)
    assert settings.alias_of(s) == {"building-01": "building-02"}
    (tmp_path / "buildings.json").write_text(json.dumps({"building-01": {"short": "mall"}}))
    assert settings.alias_of(s) == {}


def test_the_window_s_half_hours_also_across_midnight():
    assert settings.half_hours(["18:00", "21:00"]) == ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30"]
    assert settings.half_hours(["23:00", "00:30"]) == ["23:00", "23:30", "00:00"]


def test_the_roster_says_which_homes_hold_a_battery_and_names_them_as_the_page_does(tmp_path):
    tel = {"keys": ["ts", "grid_kw", "E"], "homes": {"home-01": ["x", 1.0, 13.5], "home-02": ["x", 1.0, 0.0]}}
    r = settings.roster_of(runner(tmp_path), {"building-01": "building-02"}, tel)
    assert [(h["id"], h["battery"]) for h in r["homes"]] == [("home-01", True), ("home-02", False), ("home-03", False)]
    assert r["homes"][0]["name"] == "Home 1" and r["buildings"] == [{"id": "building-01", "name": "The office"}]
    assert r["buyers"] == ["grid-operator", "utility"]


@pytest.mark.parametrize("c, doors", [
    ({"kind": "note", "who": "home-02", "text": "Keep it warm."}, [("homes", "/demo/scenario", {"override": {"home": "home-02", "kind": "note", "value": "Keep it warm.", "source": "owner's phone"}})]),
    ({"kind": "car_now", "who": "home-03"}, [("homes", "/demo/scenario", {"override": {"home": "home-03", "kind": "ev_now", "value": True, "source": "owner's phone"}})]),
    ({"kind": "building_closed", "who": "building-01"}, [("buildings", "/b/building-01/demo/scenario", {"closed": {"at": "2025-01-28 18:15"}})]),
    ({"kind": "building_need", "who": "building-01", "share": 0.25, "hours": 3.5},
     [("buildings", "/b/building-01/demo/scenario", {"zone_event": {"at": "2025-01-28 18:15", "share": 0.25, "hours": 3.5}})]),
    ({"kind": "emergency", "buyer": "grid-operator", "kw": 20, "minutes": 60},
     [("grid-operator", "/alert", {"kw": 20, "minutes": 60, "why": "grid emergency", "at": "2025-01-28 18:15"})]),
    ({"kind": "battery_fault", "who": "home-01", "on": True}, [("homes", "/demo/scenario", {"battery_fault": {"homes": ["home-01"], "on": True}})]),
    ({"kind": "battery_low", "who": "home-01", "pct": 10}, [("homes", "/demo/scenario", {"battery_soc": {"homes": ["home-01"], "pct": 10}})]),
])
def test_each_surprise_goes_to_the_door_that_makes_it_happen(c, doors):
    assert surprises.doors(c, "2025-01-28 18:15", ["homes", "buildings"]) == doors


def test_a_weather_change_goes_to_both_hosts():
    c = {"kind": "weather", "pv": 0.2, "load": 1.3, "dT": 6, "hours": 3}
    got = surprises.doors(c, "2025-01-28 18:15", ["homes", "buildings"])
    assert [g[0] for g in got] == ["homes", "buildings"] and got[0][2]["weather"]["from"] == "2025-01-28 18:15"


def test_a_surprise_makes_the_clock_play_the_hour_after_it_and_an_emergency_to_its_end_and_beyond():
    assert surprises.stops({"kind": "note"}, "2025-01-28 18:15") == ["2025-01-28 18:15", "2025-01-28 18:30", "2025-01-28 18:45",
                                                                     "2025-01-28 19:00", "2025-01-28 19:15"]
    long = surprises.stops({"kind": "emergency", "minutes": 120}, "2025-01-28 18:15")
    assert long[0] == "2025-01-28 18:15" and long[-1] == "2025-01-28 21:00"


class Told:
    def __init__(self):
        self.run, self.full, self.sets = 1, False, []

    def set(self, clock, pins):
        self.sets.append(clock)


class Asked:
    def __init__(self):
        self.said = []

    def conduct(self, **body):
        self.said.append(body)


def driver(tmp_path):
    d = Driver(runner(tmp_path), None, Told(), {"key": "one"}, say=lambda *_: None)
    d.parts, d.e = Asked(), SimpleNamespace(holding=False)
    return d


@pytest.mark.parametrize("mode, presenter, word", [("leaping", False, "leaping"), ("playing", False, "live"), ("waiting", False, "live"),
                                                   ("held", True, "held"), ("held", False, "live"), ("at_gate", False, "live")])
def test_the_clock_s_state_word_is_the_presenter_s_hold_or_what_the_clock_does(tmp_path, mode, presenter, word):
    d = driver(tmp_path)
    d.presenter = presenter
    d.tell({"mode": mode, "now": "2025-01-28 18:00", "played": [{"wall_ms": 1500}, {"wall_ms": 1700}]})
    told = d.log.sets[-1]
    assert told["state"] == word and told["tq"] == 129 and told["floor_ms"] == 1600


def test_the_clock_is_held_while_the_screen_is_behind_and_let_go_once_it_has_caught_up(tmp_path):
    d = driver(tmp_path)
    d.owed = time.time() + 10
    d.hold({"mode": "playing", "now": "2025-01-28 18:00", "played": []})
    d.owed = time.time() - 1
    d.hold({"mode": "held", "now": "2025-01-28 18:00", "played": []})
    assert d.parts.said == [{"hold": True}, {"hold": False}]


def test_at_speed_max_and_on_a_run_to_a_time_the_screen_holds_nothing(tmp_path):
    d = driver(tmp_path)
    d.owed, d.speed = time.time() + 10, "max"
    d.hold({"mode": "playing", "now": "2025-01-28 18:00", "played": []})
    assert d.parts.said == [{"hold": False}]


def test_a_run_to_a_time_ends_held_by_the_presenter_on_arrival(tmp_path):
    d = driver(tmp_path)
    d.fast, d.target, d.posted_hold = True, "2025-01-28 17:00", False
    d.hold({"mode": "held", "now": "2025-01-28 17:00", "played": []})
    assert (d.fast, d.target, d.presenter) == (False, None, True) and d.parts.said == [{"hold": True}]

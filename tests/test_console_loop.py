"""A looping console without a network: the turn from an evening that ended to the next, the days it turns through and their
stacks, the audience's taps on their way to the clock, and what the page is told of both."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from demo.console import commands as C
from demo.console import crowd as K
from demo.console import driver as D
from demo.console.days import Days
from demo.runner import settings as S


def runner(tmp_path, date="2025-01-28", buyers=("grid-operator", "utility")):
    (tmp_path / "buildings.json").write_text(json.dumps({"building-01": {"short": "office", "name": "An office"}}))
    return SimpleNamespace(evening={"date": date, "window": ["18:00", "21:00"], "feed": {}}, events=[], sites={},
                           homes=["home-01", "home-02", "home-03"], buildings=["building-01"], buyers=list(buyers), data_dir=tmp_path,
                           model={"stand_in": True})


class Told:
    def __init__(self):
        self.run, self.full, self.sets, self.shown = 1, False, [], []

    def set(self, clock, pins):
        self.sets.append(clock)

    def show(self, crowd, loop):
        self.shown.append((crowd, loop))


class Turns:
    """What stands in for the days: it gives what it is told to, or raises it."""

    def __init__(self, gives=None):
        self.gives, self.turned = gives, 0

    def now(self):
        return {"day": 2, "days": 3, "date": "2025-01-28", "label": "Winter peak"}

    def turn(self):
        self.turned += 1
        if isinstance(self.gives, Exception):
            raise self.gives
        return self.gives


def driver(tmp_path, days=None):
    d = D.Driver(runner(tmp_path), "the first stack", Told(), {"key": "one"}, say=lambda *_: None)
    d.started = []
    d.start = lambda run_to: d.started.append(run_to)
    d.days, d.e = days, SimpleNamespace(holding=False, halt=SimpleNamespace(set=lambda: None), posts=[])
    return d


# ---------------------------------------------------------------------- the turn
def test_a_console_that_does_not_loop_leaves_a_settled_evening_standing(tmp_path):
    d = driver(tmp_path)
    d.play, d.rest = "settled", 1.0
    assert d.again() is False and d.rest is None and d.started == []


def test_a_settled_evening_stands_twelve_seconds_and_one_that_failed_thirty(tmp_path):
    for play, rest in (("settled", 12.0), ("failed", 30.0)):
        d = driver(tmp_path, Turns())
        d.play = play
        assert d.again() is False and rest - 0.5 < d.rest - time.time() <= rest and d.started == []
        assert d.again() is False                                   # the time is counted once, from the pass that saw the end
    d.play = "running"
    assert d.again() is False and d.rest is None


def test_after_its_rest_the_same_network_plays_the_next_evening_at_the_speed_it_was_given(tmp_path):
    d = driver(tmp_path, Turns(None))
    d.play, d.rest, d.speed, d.waiting, d.later, d.stops_more = "settled", time.time() - 0.1, "0.5", {"kind": "weather"}, [{"kind": "car_now"}], {"x"}
    assert d.again() is True and d.days.turned == 1 and d.started == [None]
    assert (d.speed, d.waiting, d.later, d.stops_more, d.rest, d.k) == ("0.5", None, [], set(), None, "the first stack")
    assert D.LOOP_SPEED == "4" and driver(tmp_path).speed == "4" and C.SPEEDS[D.LOOP_SPEED] == 2000      # given no speed: 2 seconds a moment
    assert d.log.sets[-1]["state"] == "starting" and d.busy == C.say("next_day")


def test_the_next_day_s_evening_plays_on_the_next_day_s_stack_with_its_own_timeline(tmp_path):
    other = runner(tmp_path, date="2025-07-23", buyers=("utility",))
    d = driver(tmp_path, Turns((other, "the next stack")))
    d.play, d.rest = "settled", time.time() - 0.1
    first = d.timeline.first
    assert d.again() is True and (d.s, d.k) == (other, "the next stack") and d.started == [None]
    assert d.timeline.first.startswith("2025-07-22") and first.startswith("2025-01-27") and d.roster["buyers"] == ["utility"]
    assert d.facts_live["day"] == "2025-07-23"


def test_a_day_that_does_not_start_is_tried_again_after_thirty_seconds(tmp_path):
    d = driver(tmp_path, Turns(RuntimeError("homes did not answer at http://127.0.0.1:51999")))
    d.play, d.rest = "settled", time.time() - 0.1
    assert d.again() is True and (d.play, d.error, d.started) == ("failed", C.say("no_start"), [])
    assert d.again() is False and 29.5 < d.rest - time.time() <= 30.0


def test_a_looping_console_gives_up_an_evening_whose_clock_stood_fifteen_minutes(tmp_path):
    v = {"now": "2025-01-28 18:00", "mode": "waiting"}
    for days, play in ((Turns(), "failed"), (None, "running")):
        d = driver(tmp_path, days)
        d.play = "running"
        d.stall(v)
        d.moved -= D.STALL_S - 5
        d.stall(v)
        assert d.play == "running"
        d.moved -= 10
        d.stall(v)
        assert d.play == play and (d.warn == C.say("stalled")) == (play == "failed")
    d = driver(tmp_path, Turns())
    d.play = "running"
    d.stall(v)
    d.moved -= D.STALL_S + 5
    d.stall({**v, "now": "2025-01-28 18:15"})                      # the clock moved: the time is counted anew
    assert d.play == "running"


# ---------------------------------------------------------------------- what the page is told
def test_the_page_is_told_the_day_and_the_seconds_to_the_next_and_nothing_of_a_door_that_is_shut(tmp_path):
    d = driver(tmp_path, Turns())
    d.play = "running"
    d.show()
    assert d.log.shown[-1] == (None, {"day": 2, "days": 3, "date": "2025-01-28", "label": "Winter peak", "next_s": None})
    d.play, d.rest = "settled", time.time() + 7.4
    d.crowd.on = True
    d.show()
    crowd, loop = d.log.shown[-1]
    assert loop["next_s"] == 8 and crowd["open"] is False and crowd["left"] == 20
    d = driver(tmp_path)
    d.show()
    assert d.log.shown[-1] == (None, None)


# ---------------------------------------------------------------------- the audience's taps
def audience(tmp_path, buyers=("utility",)):
    d = driver(tmp_path)
    d.s.buyers = list(buyers)
    d.roster = {"homes": [{"id": "home-01", "name": "Home 1", "battery": True}], "buildings": [{"id": "building-01", "name": "An office"}], "buyers": list(buyers)}
    d.play, d.crowd.on, d.crowd.open = "running", True, True
    return d


def test_the_first_tap_queues_the_presenter_s_surprise_of_that_kind_at_its_defaults(tmp_path):
    d = audience(tmp_path)
    assert d.tap("weather", "viewer-1", "a") == K.FIRE and d.tap("emergency", "viewer-2", "b") == K.VOTE
    assert d.todo.get_nowait() == {"do": "surprise", "kind": "weather", "pv": 0.2, "load": 1.3, "dT": 6, "hours": 3} and d.todo.empty()
    assert d.crowd.state()["left"] == 19


def test_a_preset_this_network_cannot_play_now_is_not_counted_against_the_evening(tmp_path):
    d = audience(tmp_path, buyers=())
    assert d.tap("emergency", "viewer-1", "a") == K.CLOSED and d.todo.empty() and d.crowd.state()["left"] == 20
    assert d.crowd.state()["cooldown_s"] == 0


def test_no_tap_is_taken_while_no_evening_plays(tmp_path):
    d = audience(tmp_path)
    d.play = "settled"
    d.show()
    assert d.tap("weather", "viewer-1", "a") == K.CLOSED and d.todo.empty()


def test_a_surprise_that_comes_while_one_waits_is_posted_after_it(tmp_path):
    d = audience(tmp_path)
    posted = []
    d.parts = SimpleNamespace(post=lambda part, path, body: (posted.append(path), d.e.posts.append({})), conduct=lambda **body: None)
    d.command({"do": "surprise", "kind": "car_now", "who": "home-01"})
    d.command({"do": "surprise", "kind": "battery_low", "who": "home-01", "pct": 10})
    assert d.waiting["kind"] == "car_now" and [c["kind"] for c in d.later] == ["battery_low"]
    d.view = {"mode": "held", "now": "2025-01-28 18:00"}
    d.surprise()
    assert (len(posted), d.waiting["kind"], d.later, d.busy) == (1, "battery_low", [], C.say("surprise_waits", word="battery_low"))
    d.surprise()
    assert (len(posted), d.waiting, d.busy) == (2, None, None) and [p["id"] for p in d.pins_more] == ["car_now", "battery_low"]


# ---------------------------------------------------------------------- the days and their stacks
class Stack:
    made: list["Stack"] = []

    def __init__(self, s):
        self.s, self.did, self.dead = s, [], []
        Stack.made.append(self)

    def write(self):
        (self.s.folder / "run.json").write_text(json.dumps({"run": self.s.run, "urls": {}, "homes": self.s.homes, "buildings": self.s.buildings}))
        self.did.append("write")

    def start(self):
        self.did.append("start")

    def stop(self):
        self.did.append("stop")

    def stopped(self):
        return self.dead


@pytest.fixture
def configs(tmp_path, monkeypatch):
    """Three days' configurations, each with a fresh run folder for every start, and a clock that gives each start its own second."""
    class Later(datetime):
        at = datetime(2026, 1, 1)

        @classmethod
        def now(cls, tz=None):
            cls.at += timedelta(seconds=1)
            return cls.at
    monkeypatch.setattr(S, "datetime", Later)
    Stack.made = []
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "dataset.json").write_text("{}")
    out = []
    for date, label in (("2025-01-28", "Winter peak"), ("2025-07-23", "High solar"), ("2025-02-14", "")):
        evening = {"date": date, "window": ["18:00", "21:00"], "homes": ["home-01"], "order_kw": {"utility": 5.0}, "community_definition": {}, "feed": {}}
        (tmp_path / f"evening_{date}.json").write_text(json.dumps(evening))
        cfg = {"run": "loop-test", "folder": f"runs/{date}-{{time}}", "data_dir": "data", "evening": f"evening_{date}.json", "ports": 51000, "label": label}
        (tmp_path / f"{date}.json").write_text(json.dumps(cfg))
        out.append(tmp_path / f"{date}.json")
    return out


def test_a_loop_of_several_days_turns_through_them_each_on_a_fresh_stack_and_begins_again(configs):
    days = Days(configs, say=lambda *_: None, stack=Stack)
    s, k = days.open()
    assert days.now() == {"day": 1, "days": 3, "date": "2025-01-28", "label": "Winter peak"} and k.did == ["write", "start"]
    assert (s.pace_s, s.leap) == (0.0, True) and days.v1()["schema"] == "murmur.live.v1"
    seen = [days.now()["date"]]
    for _ in range(4):
        before = days.k
        s, k = days.turn()
        assert before.did[-1] == "stop" and k is not before and k.did == ["write", "start"] and s.folder.is_dir()
        seen.append(days.now()["date"])
    assert seen == ["2025-01-28", "2025-07-23", "2025-02-14", "2025-01-28", "2025-07-23"] and days.now()["day"] == 2
    assert len({m.s.folder for m in Stack.made}) == 5
    days.close()
    assert days.k.did[-1] == "stop" and [m.did.count("stop") for m in Stack.made] == [1, 1, 1, 1, 1]


def test_one_day_plays_again_on_the_same_stack_while_every_part_of_it_runs(configs):
    days = Days(configs[:1], say=lambda *_: None, stack=Stack)
    s, k = days.open()
    assert days.turn() is None and k.did == ["write", "start"] and days.now()["days"] == 1
    k.dead = ["homes"]
    s2, k2 = days.turn()
    assert k.did[-1] == "stop" and k2 is not k and s2.folder != s.folder and days.now()["day"] == 1


def test_a_loop_of_several_days_wants_a_fresh_folder_for_each_start(configs, tmp_path):
    fixed = tmp_path / "fixed.json"
    fixed.write_text(json.dumps({**json.loads(configs[0].read_text()), "folder": "runs/always-the-same"}))
    with pytest.raises(ValueError, match="fresh run folder"):
        Days([configs[0], fixed], stack=Stack)
    Days([fixed], stack=Stack)                                    # one day alone starts once: its folder may be a fixed one
    with pytest.raises(ValueError):
        Days([], stack=Stack)


@pytest.mark.parametrize("label, good", [("Winter peak", True), ("", True), ("x" * 40, True), ("x" * 41, False), ("two\nlines", False)])
def test_a_day_s_label_is_one_printable_line_of_at_most_40_characters(configs, label, good):
    configs[0].write_text(json.dumps({**json.loads(configs[0].read_text()), "label": label}))
    if good:
        assert S.load(configs[0]).label == label
    else:
        with pytest.raises(ValueError, match="label"):
            S.load(configs[0])

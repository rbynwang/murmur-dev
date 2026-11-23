"""The waiting clock's leaps (conductor.py, conductor_stops.py), in the world of test_conductor.py: an evening from 17:00 whose data ends at 23:45.

Asked to leap, the clock plays only the steps something is scheduled at: a gate and, once it is opened, that step and the one after it; a step
the driver named; a quarter hour the market has something at; the last step of the data. Over the empty quarter hours between them every clock
moves in one move, to the next stop or as far as one leap goes. A step the clock lands on is played at its pace when it is a stop; an empty one
lasts only until every participant has caught up: the node services, each other participant that says how far its loop is, the market's own
loop, and the community's meter where the clock waits for it. A clock that runs fast also gives a step it plays the time an inbox takes to be
looked at, from the moment everyone had caught up, and does not wait after a report row the community sent upward. A leap never passes a stop,
stops one step before a gate, and a driver's hold keeps the clock where the leap in hand lands. With leaping off nothing of this happens: every
step is played.
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from murmur.agents.community.community import Meter
from murmur.protocol import wire
from tests.test_conductor import BUILDINGS, BUYER, DAY, HOMES, IDLE, LAST, OFFICE, PACE, QUIET, T0, done, held, look, parts, world  # noqa: F401  parts and world are this file's fixtures too

Q = [f"{DAY} {17 + k // 4:02d}:{15 * (k % 4):02d}" for k in range(28)]         # every step of the evening: Q[0] is 17:00, where the clock starts, Q[27] is 23:45, the last of the data
INBOX = "an inbox may still hold what was sent at this step"


def went(w) -> list[str]:
    """The steps every clock was moved to, in order, as the homes' host was told them."""
    return [body["at"] for base, body in w.parts.posts if base == HOMES]


def leaping(w, most: int | None = None, quiet: float = 0.0, **word) -> None:
    """The driver asks the clock to leap, as far as `most` steps in one move. `quiet` is the time an inbox takes to be looked at, which a clock that
    runs fast gives every step it plays: none here, unless a test is about it."""
    if most is not None:
        w.c.cfg["clock_leap_max_steps"] = most
    w.c.cfg["clock_wait_quiet_s"] = quiet
    w.k.asked({"leap": True, **word})


def test_leaping_moves_every_clock_over_the_empty_quarter_hours_in_one_move_and_plays_the_step_it_lands_on_at_its_pace(world):
    w = world
    leaping(w, stops=[Q[5]])
    assert look(w, 1.5)["now"] == T0                                   # the step in hand is played: its pace first
    v = look(w, 0.5, nodes_done=False)
    assert (v["now"], v["steps"], v["mode"], v["next_stop"], v["leaps"]) == (Q[5], 5, "playing", LAST, [])
    assert len(w.parts.posts) == 3 and dict(w.parts.posts) == dict.fromkeys((BUYER, HOMES, OFFICE), held(Q[5], w.wall.t))     # one move: each participant is told once, the step it lands on
    assert look(w, 0.25, nodes_done=False)["leaps"] == [] and w.events == []     # the node services are asked at once, pace or no pace: they have not caught up
    leap = {"from": T0, "to": Q[5], "steps": 5, "wall_ms": 500}
    assert look(w, 0.25)["leaps"] == [leap] and w.events == [("clock_leap", leap)]      # caught up half a second after the move: on the record, once
    assert look(w, 1.25)["now"] == Q[5]                                # a stop is played: 1.75 s of its 2 s
    v = look(w, 0.25)
    assert (v["now"], v["mode"], v["held_s"]) == (Q[17], "leaping", 0.0)         # then on, as far as one leap goes: nothing is scheduled before the end of the data
    assert v["played"] == [{"sim": T0, "wall_ms": 2000, "waited_on": []}, {"sim": Q[5], "wall_ms": 2000, "waited_on": []}]
    assert w.events == [("clock_leap", leap)]


def test_a_clock_that_runs_fast_gives_a_step_it_plays_the_time_an_inbox_takes_from_the_moment_everyone_had_caught_up_and_an_empty_step_none(world):
    w = world
    leaping(w, most=4, quiet=QUIET, stops=[Q[8]])
    assert look(w, 0.5)["mode"] == "playing" and len(w.parts.asked) == 3          # asked at once, pace or no pace: every participant has caught up half a second in
    v = look(w, 1.5)
    assert (v["now"], v["mode"], v["waiting_on"], w.c.market.rt.settled) == (T0, "waiting", [INBOX], None)       # its pace has passed, the inbox's time has not
    assert look(w, 2.0)["now"] == T0 and len(w.parts.asked) == 7                  # 4 s in: half a second short of it
    v = look(w, 0.5)
    assert (v["now"], w.c.market.rt.settled) == (Q[4], T0) and v["played"] == [{"sim": T0, "wall_ms": 4500, "waited_on": [INBOX]}]
    assert look(w, 0.0)["now"] == Q[8]                                 # nothing was scheduled at the step it leaped to: nothing was sent by the clock there
    w.k.asked({"pace_s": 10})
    assert look(w, 0.5)["now"] == Q[8] and look(w, 9.0)["now"] == Q[8] and look(w, 0.5)["now"] == Q[12]             # a pace longer than that covers it
    assert w.k.view()["played"][1] == {"sim": Q[8], "wall_ms": 10000, "waited_on": []}
    w.k.asked({"leap": False, "pace_s": 1})                            # playing every step, in less than the participants' own step_seconds: the same
    assert look(w, 1.0)["waiting_on"] == [INBOX] and look(w, QUIET)["now"] == Q[13]
    w.k.asked({"pace_s": PACE})                                        # and at the participants' own pace the clock is as it always was
    assert look(w, PACE - 0.5)["now"] == Q[13] and look(w, 0.5)["now"] == Q[14]


def test_a_run_of_leaps_lasts_no_pace_at_all_and_ends_on_the_last_step_of_the_data(world):
    w = world
    leaping(w, most=4)
    assert look(w)["now"] == Q[4]
    for k in (8, 12, 16, 20, 24):
        v = look(w, 0.0)                                               # not a moment passes: an empty step has no pace
        assert (v["now"], v["mode"], v["next_stop"]) == (Q[k], "leaping", LAST)
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["next_stop"], v["steps"], v["held_s"]) == (LAST, "ended", None, 27, 0.0)
    v = look(w, 0.0)                                                   # the last leap has landed too, three steps: the end of the data is a stop
    assert [(x["to"], x["steps"], x["wall_ms"]) for x in v["leaps"]] == [(Q[k], 4, 0) for k in (4, 8, 12, 16, 20, 24)] + [(LAST, 3, 0)]
    assert went(w) == [x["to"] for x in v["leaps"]] and len(w.parts.posts) == 3 * 7 and [x["sim"] for x in v["played"]] == [T0]
    asked = len(w.parts.asked)
    assert look(w, 60.0)["now"] == LAST and len(w.parts.asked) == asked           # at the end nobody is asked any more


def test_the_longest_leap_is_what_the_configuration_names_from_1_to_192_steps(world):
    w = world
    assert (w.k.view()["leap"], w.k.view()["leap_max_steps"]) == (False, 12)
    for named, most in ((0, 1), (1, 1), (500, 192), (96, 96)):
        w.c.cfg["clock_leap_max_steps"] = named
        assert w.k.leap_max() == most
    w.c.cfg.update(clock_leap=True, clock_leap_max_steps=1, clock_wait_quiet_s=0.0)       # asked in the configuration, one step at a time: every empty step still lasts no pace
    assert w.k.view()["leap"] is True and look(w)["now"] == Q[1] and look(w, 0.0)["now"] == Q[2] and went(w) == Q[1:3]
    w.k.asked({"leap": False})                                         # a driver's word stands over the configuration
    assert w.k.view()["leap"] is False and look(w, 0.0)["now"] == Q[2] and look(w)["now"] == Q[3]


def test_an_empty_step_waits_until_every_participant_has_caught_up_and_for_nothing_else(world):
    w = world
    w.c.cfg["clock_wait_meter"] = True
    meter = w.c.market.community = SimpleNamespace(meter=Meter())
    meter.meter.add(T0, -1.0)                                          # the meter is read for the step the evening starts on
    leaping(w, most=4)
    w.parts.line[BUYER] = {"ticked": T0}                               # the buyer says how far its own loop is
    assert look(w)["now"] == Q[4]
    behind = [f"{HOMES}: its nodes at {T0}", f"{BUILDINGS}: its nodes at {T0}", f"utility: its loop at {T0}", "the market: its loop at None",
              f"the community's meter: no reading for {Q[1]}"]
    w.parts.at = {HOMES: done(T0), BUILDINGS: done(T0)}
    v = look(w, 0.0, nodes_done=False, market_done=False)
    assert (v["now"], v["mode"], v["waiting_on"]) == (Q[4], "leaping", behind)
    assert look(w, 0.2, market_done=False)["waiting_on"] == behind[2:]           # the hosts' nodes have stepped every quarter hour of the move
    w.parts.line[BUYER] = {"ticked": Q[4]}
    assert look(w, 0.2, market_done=False)["waiting_on"] == behind[3:]
    asked = [x for x in w.parts.asked if x == ("GET", f"{BUYER}/demo/clock")]
    assert look(w, 0.2)["waiting_on"] == behind[4:] and [x for x in w.parts.asked if x == ("GET", f"{BUYER}/demo/clock")] == asked      # a participant that caught up is not asked again
    for q in Q[1:4]:
        meter.meter.add(q, -1.0)
    assert look(w, 0.2)["waiting_on"] == [f"the community's meter: no reading for {Q[4]}"] and w.k.view()["leaps"] == []     # every quarter hour of the move, in order
    meter.meter.add(Q[4], -1.0)
    v = look(w, 0.2)
    assert v["now"] == Q[8] and v["leaps"] == [{"from": T0, "to": Q[4], "steps": 4, "wall_ms": 1000}] and v["held_s"] == 1.0     # one second, all of it catching up


def test_a_participant_that_cannot_say_how_far_it_is_or_does_not_answer_is_not_waited_for_and_is_asked_once_a_step(world):
    w = world
    leaping(w, most=4)
    w.c.targets["site-01"] = "http://site.test"
    w.parts.down = {"http://site.test"}                                # the site does not answer; the buyer's clock door has no `ticked`
    assert look(w)["now"] == Q[4] and look(w, 0.0, nodes_done=False)["waiting_on"] == [f"{HOMES}: its nodes at {T0}", f"{BUILDINGS}: its nodes at {T0}"]
    assert look(w, 0.0)["now"] == Q[8]
    asked = {base: sum(1 for x in w.parts.asked if x == ("GET", f"{base}/demo/clock")) for base in (BUYER, "http://site.test")}
    assert asked == {BUYER: 2, "http://site.test": 4}                  # each once at 17:00 and once at 18:00, in three looks; a call that found no connection is tried once more at once


def test_waits_that_never_end_let_a_leap_go_on_after_the_idle_limit_and_both_go_on_the_record(world):
    w = world
    leaping(w, most=4)
    look(w)
    stuck = [f"{HOMES}: its nodes at {T0}"]
    w.parts.at = {HOMES: done(T0), BUILDINGS: done(Q[4])}
    assert look(w, 0.0, nodes_done=False)["waiting_on"] == stuck and look(w, IDLE - 0.5, nodes_done=False)["now"] == Q[4]
    v = look(w, 0.5, nodes_done=False)
    leap = {"from": T0, "to": Q[4], "steps": 4, "wall_ms": 180000}
    assert (v["now"], v["leaps"], v["went_on"]) == (Q[8], [leap], [{"sim": Q[4], "wall": w.wall.t, "without": stuck}])
    assert w.events == [("clock_went_on", {"sim": Q[4], "waited_s": 180.0, "without": stuck}), ("clock_leap", leap)]


def test_a_stop_is_a_gate_the_step_after_an_opened_gate_a_step_the_driver_named_what_the_market_has_scheduled_and_the_last_step(world):
    w = world
    w.plan[Q[9]] = "sale-1: its window"
    w.k.asked({"gates": [Q[3]], "stops": [Q[6], Q[7]]})
    i = w.c.clock.current()
    whys = {k: w.k.why_stop(i + k) for k in range(28)}
    assert {k: v for k, v in whys.items() if v} == {3: "a gate", 6: "a stop the driver set", 7: "a stop the driver set", 9: "sale-1: its window", 27: "the last step of the data"}
    assert (w.k.next_stop(i), w.k.next_stop(i, 2), w.k.next_stop(i + 9), w.k.next_stop(i + 27)) == (i + 3, None, i + 27, None)
    w.k.asked({"open": Q[3]})
    assert w.k.why_stop(i + 3) == w.k.why_stop(i + 4) == "a gate was opened" and w.k.view()["gates"] == []
    w.k.asked({"stops": [Q[12]], "run_to": Q[20]})                     # a new list takes the old one's place
    assert [k for k in range(28) if w.k.why_stop(i + k)] == [3, 4, 9, 12, 20, 27] and w.k.why_stop(i + 20) == "where the driver runs to"
    assert (w.k.view()["stops"], w.k.view()["next_stop"]) == ([Q[12]], Q[3])


def test_a_schedule_that_cannot_be_read_is_no_ground_for_a_leap_every_step_is_played(world):
    w = world
    leaping(w)
    w.c.market.scheduled = lambda ts: {}["a sale that can't be read"]
    assert look(w)["now"] == Q[1] and look(w, PACE - 0.5)["now"] == Q[1] and look(w, 0.5)["now"] == Q[2]
    assert w.k.view()["leaps"] == [] and w.k.why_stop(w.c.clock.current() + 1) == "the market's schedule can't be read: KeyError"
    assert w.events == [("clock_schedule_unread", {"error": "KeyError: \"a sale that can't be read\""})]              # told once, however often the clock looks


@pytest.mark.parametrize("seed", range(16))
def test_a_leap_never_passes_a_stop_and_every_stop_is_landed_on_whatever_the_stops_and_however_far_a_leap_may_go(world, seed):
    w, rng = world, random.Random(seed)
    gates, stops, plan = (set(rng.sample(Q[1:27], rng.randint(0, 4))) for _ in range(3))
    w.plan.update(dict.fromkeys(plan, "the market's own"))
    leaping(w, most=rng.choice((1, 2, 3, 5, 12, 192)), gates=sorted(gates), stops=sorted(stops))
    opened = set()
    for _ in range(120):
        v = look(w)
        if v["at_gate"]:
            k = Q.index(v["at_gate"])
            assert v["now"] == Q[k - 1] and v["mode"] == "at_gate"     # held one step before it, as a gate holds any step
            opened |= {Q[k], Q[min(k + 1, 27)]}
            w.k.asked({"open": Q[k]})
    path, must = [T0] + went(w), gates | stops | plan | opened | {LAST}
    assert path[-1] == LAST and path == sorted(set(path))
    assert [(a, b) for a, b in zip(path, path[1:]) if must & set(Q[Q.index(a) + 1:Q.index(b)])] == []       # nothing that must be played lies between two landings
    assert must <= set(path) and all(x["steps"] <= w.k.leap_max() for x in w.k.view()["leaps"])            # every stop was landed on, and no leap went further than it may
    assert must - {LAST} <= {x["sim"] for x in w.k.view()["played"]} <= must | {T0}                        # and those were the steps that lasted their pace: no other


def test_a_gate_inside_an_empty_stretch_stops_the_leap_one_step_before_it_and_the_gates_step_and_the_one_after_are_played(world):
    w = world
    leaping(w, gates=[Q[6]])
    v = look(w)
    assert (v["now"], v["mode"], v["at_gate"]) == (Q[5], "leaping", None) and went(w) == [Q[5]]      # one step short of the gate
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["at_gate"]) == (Q[5], "at_gate", Q[6])                             # with everything else done, as gates always held the clock
    assert look(w, 30.0)["now"] == Q[5] and went(w) == [Q[5]]
    w.k.asked({"open": Q[6]})
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["at_gate"], v["next_stop"]) == (Q[6], "playing", None, Q[7])        # what a runner posted at the gate happens here
    assert look(w, PACE - 0.5)["now"] == Q[6] and look(w, 0.5)["now"] == Q[7]                         # played at the pace, and the step after it too:
    assert look(w, PACE - 0.5)["now"] == Q[7] and look(w, 0.5)["now"] == Q[19]                        # there the nodes act on it. Then the clock leaps again
    assert [x["sim"] for x in w.k.view()["played"]] == [T0, Q[6], Q[7]] and [(x["from"], x["to"]) for x in w.k.view()["leaps"]] == [(T0, Q[5])]
    w.k.asked({"gates": [Q[22]]})
    assert look(w, 0.0)["now"] == Q[21] and look(w, 0.0)["at_gate"] == Q[22]
    w.k.asked({"gates": []})                                           # a new list without the gate the clock stands at: that gate counts as opened
    assert (w.k.why_stop(w.c.clock.current() + 1), look(w, 0.0)["now"], look(w)["now"]) == ("a gate was opened", Q[22], Q[23])


def test_a_hold_during_a_run_of_leaps_keeps_the_clock_where_the_leap_in_hand_lands(world):
    w = world
    leaping(w, most=4)
    look(w)
    assert look(w, 0.0, nodes_done=False)["now"] == Q[4]               # the leap is in hand: the nodes have not caught up
    w.k.asked({"hold": True})
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["hold"], went(w)) == (Q[4], "held", True, [Q[4]])
    assert look(w, 60.0)["now"] == Q[4] and [x["to"] for x in w.k.view()["leaps"]] == [Q[4]]
    w.k.asked({"hold": False})
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["hold"]) == (Q[8], "leaping", False)


def test_something_that_comes_up_at_an_empty_step_makes_it_a_step_to_play_at_its_pace(world):
    w = world
    leaping(w, most=4)
    look(w)
    w.plan[Q[4]] = "call call-1: answers to come"                       # a buyer's call came in while the clock stood on the step it leaped to
    v = look(w, 0.0)
    assert (v["now"], v["mode"]) == (Q[4], "playing")
    assert look(w, PACE - 0.5)["now"] == Q[4] and look(w, 0.5)["now"] == Q[8]            # it lasts its pace like any step that is played; then the clock leaps on
    assert [x["sim"] for x in w.k.view()["played"]] == [T0, Q[4]]


def test_with_leaping_off_stops_and_what_the_market_has_scheduled_change_nothing_every_step_is_played_one_after_another(world):
    w = world
    w.plan[Q[6]] = "sale-1: its window"
    w.k.asked({"stops": [Q[3]]})
    for k in range(1, 6):
        assert look(w, PACE - 0.5)["now"] == Q[k - 1] and look(w, 0.5)["now"] == Q[k]           # each lasts the pace, stop or not, and the clocks move one step
    v = w.k.view()
    assert went(w) == Q[1:6] and [body for _, body in w.parts.posts[-3:]] == [held(Q[5], w.wall.t)] * 3
    assert (v["leap"], v["mode"], v["leaps"], v["stops"], v["next_stop"], v["steps"], v["held_s"]) == (False, "playing", [], [Q[3]], Q[6], 5, 0.0)
    assert [x["sim"] for x in v["played"]] == Q[:5] and w.events == []


def test_a_report_row_the_community_sent_upward_holds_no_step_of_a_clock_that_leaps_and_holds_a_step_as_before_when_it_does_not(world, monkeypatch):
    w = world
    monkeypatch.setattr(wire, "_path", str(w.wire))
    monkeypatch.setattr(wire, "time", SimpleNamespace(time=w.wall))
    row = {"context": {"action": "report"}, "message": {"report": {"timestamp": T0, "reported_p_net_kw": -3.0}}}
    w.wall.t += PACE
    wire.note("send", "community", "aggregator", "report", row)
    assert w.k.wire_recent(QUIET) is True and w.k.wire_recent(QUIET, reports=False) is False
    assert look(w, 1.0)["waiting_on"] == ["messages on their way over the bus"] and w.k.view()["now"] == T0      # leaping off: as it always was
    leaping(w, most=4, quiet=QUIET)
    assert look(w, 0.0)["waiting_on"] == [INBOX]                       # nothing answers a report row: a clock that leaps does not wait after one,
    assert look(w, QUIET)["now"] == Q[4]                               # only for what an inbox may still hold at a step that is played
    wire.note("recv", "aggregator", "community", "request", {"message": {"request": {"id": "req-1"}}})
    assert look(w, 0.0)["waiting_on"] == ["messages on their way over the bus"]          # any other message is waited after, on an empty step too
    assert look(w, QUIET + 0.5)["now"] == Q[8]
    wire.note("recv", "home-03", "community", "rt_capacity", {"message": {"short": {}}})
    for _ in range(120):                                               # then the rows of a long leap, 70 kB of them: more than the clock reads of a log at first
        wire.note("send", "community", "aggregator", "report", {"message": {"report": {"timestamp": T0, "text": "x" * 500}}})
    assert w.wire.stat().st_size > 60_000 and w.k.wire_recent(QUIET, reports=False) is True      # the message that came just before them still counts
    w.wall.t += QUIET + 0.5
    assert w.k.wire_recent(QUIET, reports=False) is False

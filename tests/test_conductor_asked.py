"""What a driver asks of the waiting clock and what the clock says of itself (conductor_asked.py, and the agent's doors), in the world of
test_conductor.py.

The pace is the least time a played step lasts: the participants' own step_seconds until the driver names one, 0 for as fast as the network
finishes the step, never under the configuration's floor; a change is taken at once, because a driver's word ends the loop's wait. A hold stops
the clock once the step in hand is finished and lets it go on again; a number of steps is played and then held, a leap counting as one; a run to
a step holds on arrival. The door refuses whole a word it can't read. A start sets the pace and the leaping, takes away a hold, and keeps the
gates and the stops. The clock says its mode: idle, playing, waiting, leaping, held, at a gate, ended.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from murmur.agents.community import doors
from murmur.agents.community.conductor import POLL_S, REST_S, Conductor
from murmur.agents.community.service import CommunityAgent
from tests.test_community_market import DEF
from tests.test_conductor import BUILDINGS, DAY, HOMES, LAST, PACE, T0, T1, T2, T3, Stop, Wall, done, look, parts, world  # noqa: F401  parts and world are this file's fixtures too
from tests.test_conductor_leap import Q, leaping, went

BEGIN, FIRST = "2025-01-27 09:45", "2025-01-27 10:00"        # where an evening for the fixture's second day starts, and its next step


def test_the_pace_is_the_participants_step_seconds_until_the_driver_names_one_and_zero_is_as_fast_as_the_network_finishes_the_step(world):
    w = world
    w.c.cfg["clock_wait_quiet_s"] = 0.0                                # no inbox's time on top of a step: test_conductor_leap.py has that
    assert w.k.view()["pace_s"] == PACE and look(w, PACE - 0.5)["now"] == T0
    w.k.asked({"pace_s": 0.5})                                         # shorter, while the step is in hand: it has lasted its new pace already
    v = look(w, 0.0)
    assert (v["now"], v["pace_s"]) == (T1, 0.5) and look(w, 0.25)["now"] == T1 and look(w, 0.25)["now"] == T2
    w.k.asked({"pace_s": 0})
    assert look(w, 0.0)["now"] == T3                                   # every participant is done with it: it lasts no longer
    v = look(w, 0.0, nodes_done=False)
    assert (v["now"], v["mode"], v["waiting_on"]) == (T3, "waiting", [f"{HOMES}: its nodes at {T2}", f"{BUILDINGS}: its nodes at {T2}"])
    assert look(w, 0.0)["now"] == Q[4] and [x["wall_ms"] for x in w.k.view()["played"]] == [1500, 500, 0, 0]
    assert {body["step_seconds"] for _, body in w.parts.posts} == {PACE}                  # the participants' own clock setting stays what it was
    w.c.cfg["clock_min_step_s"] = 1.0                                  # a deployment's floor under any pace
    assert w.k.view()["pace_s"] == 1.0 and look(w, 0.5)["now"] == Q[4] and look(w, 0.5)["now"] == Q[5]
    w.k.asked({"pace_s": 120})
    assert w.k.view()["pace_s"] == 120.0 and look(w, 119.0)["now"] == Q[5] and look(w, 1.0)["now"] == Q[6]


def test_a_hold_stops_the_clock_once_the_step_in_hand_is_finished_and_lets_it_go_on_again(world):
    w = world
    w.k.asked({"hold": True})
    v = look(w, 1.0)
    assert (v["now"], v["mode"], v["hold"]) == (T0, "playing", True)   # the step in hand is played to its end first
    v = look(w, 1.0)
    assert (v["now"], v["mode"], v["hold"], w.parts.posts) == (T0, "held", True, [])
    assert look(w, 300.0)["now"] == T0
    w.k.asked({"hold": False})
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["hold"], v["held_s"]) == (T1, "playing", False, 300.0)      # the time it was held counts as held beyond the pace


def test_a_number_of_steps_is_played_and_then_the_clock_holds_and_a_leap_counts_as_one(world):
    w = world
    w.k.asked({"hold": True})
    look(w)
    w.k.asked({"step": 2})
    assert (look(w, 0.0)["now"], look(w)["now"]) == (T1, T2)
    v = look(w)
    assert (v["now"], v["mode"], v["hold"], went(w)) == (T2, "held", True, [T1, T2])           # the second is played, and held
    leaping(w, most=4, step=2)
    v = look(w, 0.0)
    assert (v["now"], v["mode"]) == (Q[6], "leaping") and look(w, 0.0)["now"] == Q[10]
    v = look(w, 0.0)
    assert (v["now"], v["mode"], v["hold"], went(w)[2:]) == (Q[10], "held", True, [Q[6], Q[10]])
    w.k.asked({"step": 5})
    look(w, 0.0)
    w.k.asked({"hold": True})                                          # a hold ends a count in hand
    assert look(w, 0.0)["now"] == Q[14] and look(w, 0.0)["mode"] == "held"
    w.k.asked({"hold": False})
    assert [look(w, 0.0)["now"] for _ in range(4)] == [Q[18], Q[22], Q[26], LAST]              # and the clock goes on with no count left


@pytest.mark.parametrize("leap, path", [(True, [Q[4], Q[8], Q[10]]), (False, Q[1:11])])
def test_a_run_to_a_step_goes_on_leaping_where_the_clock_leaps_and_holds_on_arrival(world, leap, path):
    w = world
    w.c.cfg["clock_leap_max_steps"] = 4
    w.k.asked({"leap": leap, "hold": True})
    look(w)
    w.k.asked({"run_to": Q[10]})
    v = w.k.view()
    assert (v["hold"], v["next_stop"]) == (False, Q[10])               # the step it runs to must be played: no leap passes it
    for _ in range(12):
        v = look(w)
    assert (v["now"], v["mode"], v["hold"], went(w)) == (Q[10], "held", True, path) and w.k.cond["run_to"] is None
    w.k.asked({"hold": False})
    assert look(w, 0.0)["now"] == (Q[14] if leap else Q[11])


def test_a_drivers_word_ends_the_loops_wait_at_once_and_a_look_follows(world):
    w, stop, naps = world, threading.Event(), []
    w.c.cfg["clock_wait_quiet_s"] = 0.0
    w.k.wall = time.time                                               # a real wall clock and the loop on a thread of its own
    w.c.clock.configure(T0, PACE, 0, T0, time.time(), hold=True)
    w.k.started(time.time(), pace_s=60.0)
    w.parts.at = {HOMES: done(T0), BUILDINGS: done(T0)}
    w.c.clock.follower.passed(w.c.clock.follower.moves, T0)
    pause = w.k.pause

    def wait(seconds: float) -> None:
        naps.append(seconds)
        if not stop.is_set():
            pause(seconds)
        if stop.is_set():
            raise Stop

    def run() -> None:
        try:
            w.k.step_loop()
        except Stop:
            pass
    w.k.pause = wait
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        end = time.time() + 5.0
        while not naps and time.time() < end:
            time.sleep(0.002)
        assert naps and naps[0] == REST_S                              # in a played step's pace the loop rests: nothing can move for a minute
        t0 = time.time()
        w.k.asked({"pace_s": 0})
        while w.k.view()["now"] != T1 and time.time() < t0 + 5.0:
            time.sleep(0.002)
        took = time.time() - t0
    finally:
        stop.set()
        w.k.wake()
        thread.join(5.0)
    assert not thread.is_alive() and w.k.view()["now"] == T1 and took < 0.25      # at once: not after the half second the loop would have rested


def test_the_loop_waits_to_the_end_of_a_pace_polls_a_step_in_hand_and_rests_while_nothing_can_move(world):
    w = world
    assert w.k.nap() == REST_S                                         # 2 s of pace left: no look is needed for a while
    w.wall.t += PACE - 0.2
    assert w.k.nap() == pytest.approx(0.2)
    w.wall.t += 0.2
    assert w.k.nap() == POLL_S == 0.05                                 # the pace has passed: how soon a finished step is seen
    w.c.cfg["clock_poll_s"] = 0.2
    assert w.k.nap() == 0.2
    w.k.asked({"hold": True})
    assert look(w, 0.0)["mode"] == "held" and w.k.nap() == REST_S      # finished and held: only a driver's word can change anything
    leaping(w, most=4, hold=False, stops=[Q[4]])
    look(w, 0.0)
    assert w.k.view()["mode"] == "playing" and w.k.nap() == 0.2        # a clock that runs fast asks at once how far everyone is, in a played step's pace too,
    look(w, 0.5)
    assert w.k.view()["now"] == Q[4] and w.k.nap() == REST_S           # and rests once they have caught up: 1.5 s of pace are left
    look(w, 1.5)
    assert w.k.view()["mode"] == "leaping" and w.k.nap() == 0.2        # an empty step is asked about at once, and again soon
    w.c.cfg["clock_waits"] = False
    assert w.k.nap() == REST_S and w.k.view()["mode"] == "idle"
    k = Conductor(w.c, wire_files=[])
    k.wake()
    t0 = time.time()
    k.pause(30.0)                                                      # a wait that was woken before it began ends at once
    assert time.time() - t0 < 5.0


@pytest.fixture
def agent(agent_config, tmp_path, parts):  # noqa: F811
    """A community agent with its doors and a waiting clock on a wall clock moved by hand, its loops not running: (the agent, its clock, the door, the wall)."""
    agent_config(agent_name="community", buyers=["utility"], sync_broadcast=True, replay_start=T0, replay_loop_days=0, clock_waits=True, clock_wait_urls=[HOMES],
                 clock_wait_quiet_s=0.0, community=DEF)
    c, wall = CommunityAgent(), Wall()
    k = Conductor(c, wire_files=[tmp_path / "town_wire.jsonl"], http=parts.http, wall=wall)
    k.step_loop = k.again_loop = lambda: None
    return c, k, TestClient(doors.build_app(c, k)), wall


@pytest.mark.parametrize("word, why", [
    ({"pace_s": -0.1}, "pace_s is 0 to 120 seconds"), ({"pace_s": 120.5}, "pace_s is 0 to 120 seconds"), ({"pace_s": "fast"}, "pace_s is 0 to 120 seconds"),
    ({"pace_s": True}, "pace_s is 0 to 120 seconds"), ({"leap": "yes"}, "leap and hold are true or false"), ({"hold": 1}, "leap and hold are true or false"),
    ({"step": 0}, "step is how many steps to play, 1 to 1000"), ({"step": 1.5}, "step is how many steps to play, 1 to 1000"),
    ({"step": True}, "step is how many steps to play, 1 to 1000"), ({"step": 1001}, "step is how many steps to play, 1 to 1000"),
    ({"stops": FIRST}, "stops is a list of steps of the data, each YYYY-MM-DD HH:MM"), ({"stops": [FIRST, "tomorrow"]}, "stops is a list of steps of the data, each YYYY-MM-DD HH:MM"),
    ({"stops": ["2025-02-01 10:00"]}, "stops is a list of steps of the data, each YYYY-MM-DD HH:MM"), ({"stops": [7]}, "stops is a list of steps of the data, each YYYY-MM-DD HH:MM"),
    ({"run_to": T0}, "run_to is a step of the data after the one the clock holds"), ({"run_to": "2025-01-28 16:45"}, "run_to is a step of the data after the one the clock holds"),
    ({"run_to": "the window"}, "run_to is a step of the data after the one the clock holds"), ({"run_to": 18}, "run_to is a step of the data after the one the clock holds")])
def test_the_clocks_door_refuses_whole_a_word_it_cannot_read(agent, word, why):
    c, k, door, _ = agent
    before = door.get("/demo/conductor").json()
    r = door.post("/demo/conductor", json={"gates": [T1], "stops": [T2], "hold": True, "leap": True, **word})
    assert (r.status_code, r.json()["detail"]) == (400, why)
    assert door.get("/demo/conductor").json() == before and not k.woken.is_set()       # nothing of it was done: not the gate, not the hold


def test_the_clocks_door_takes_a_drivers_words_together_and_shows_them(agent):
    c, k, door, _ = agent
    v = door.get("/demo/conductor").json()
    assert {x: v[x] for x in ("mode", "pace_s", "leap", "leap_max_steps", "hold", "stops", "next_stop", "leaps", "played")} == {
        "mode": "idle", "pace_s": 60.0, "leap": False, "leap_max_steps": 12, "hold": False, "stops": [], "next_stop": LAST, "leaps": [], "played": []}
    v = door.post("/demo/conductor", json={"gates": [T2], "stops": [T3, T1], "leap": True, "pace_s": 1.5, "hold": True, "run_to": Q[9]}).json()
    assert (v["gates"], v["stops"], v["leap"], v["pace_s"], v["hold"], v["next_stop"], v["mode"]) == ([T2], [T1, T3], True, 1.5, False, T1, "idle")
    assert k.woken.is_set() and k.cond["run_to"] == Q[9]               # the run to a step lets the clock go on: it came last in the word
    assert door.post("/demo/conductor", json={"stops": [], "leap": False, "hold": True}).json()["stops"] == [] and k.cond["hold"] is True
    assert door.post("/demo/conductor", json={}).status_code == 200


def test_a_start_sets_the_pace_and_the_leaping_takes_away_a_hold_and_keeps_the_gates_and_the_stops(agent, parts):  # noqa: F811
    c, k, door, wall = agent
    go = {"event": DAY, "step_seconds": 2, "lead_s": 1, "force": True}
    for bad, why in (({"pace_s": 121}, "pace_s must be 0-120"), ({"pace_s": "slow"}, "pace_s must be 0-120"), ({"leap": "on"}, "leap must be true or false")):
        r = door.post("/demo/start", json={**go, **bad})
        assert (r.status_code, r.json()["detail"]) == (400, why) and door.get("/demo/conductor").json()["mode"] == "idle"
    door.post("/demo/conductor", json={"gates": ["2025-01-27 12:00"], "stops": ["2025-01-27 11:00"], "step": 3, "run_to": "2025-01-28 20:00"})
    st = door.post("/demo/start", json={**go, "pace_s": 0.5, "leap": True}).json()
    assert (st["step_seconds"], st["pace_s"], st["leap"], st["minutes_total"]) == (2.0, 0.5, True, 1.3)
    v = door.get("/demo/conductor").json()
    assert (v["now"], v["mode"], v["pace_s"], v["leap"], v["hold"], v["gates"], v["stops"]) == (BEGIN, "playing", 0.5, True, False, ["2025-01-27 12:00"], ["2025-01-27 11:00"])
    assert (k.cond["budget"], k.cond["run_to"], v["next_stop"]) == (None, None, FIRST)          # 10:00: the day's question to the buyer
    assert [e for e in c.events if e["kind"] == "demo_start"][0] | {"at": 0, "targets": 0} == {
        "at": 0, "sim": BEGIN, "kind": "demo_start", "event": DAY, "step_seconds": 2.0, "pace_s": 0.5, "leap": True, "starts_at": BEGIN, "targets": 0}
    parts.at, wall.t = {HOMES: done(BEGIN)}, st["wall_start"] + 0.5
    c.clock.follower.passed(c.clock.follower.moves, BEGIN)
    k.tick()
    assert door.get("/demo/conductor").json()["now"] == FIRST          # the question is a stop: the clock does not leap over it
    st = door.post("/demo/start", json=go).json()                      # again, saying nothing of pace or leaping
    assert (st["pace_s"], st["leap"], st["minutes_total"]) == (2.0, True, 5.1)                # the pace is the step's again; the leaping stays as it was last told


def test_a_feed_of_the_communitys_meter_wakes_the_clock_and_a_feed_that_is_refused_does_not(agent):
    c, k, door, _ = agent
    assert door.post("/v2/community/feed", json={"rows": [{"ts": T0, "meter_kw": "low"}]}).status_code == 400 and not k.woken.is_set()
    assert door.post("/v2/community/feed", json={"rows": [{"ts": T0, "meter_kw": -1.5}]}).json()["rows"] == 1 and k.woken.is_set()
    assert c.market.community.meter.at(T0) == -1.5

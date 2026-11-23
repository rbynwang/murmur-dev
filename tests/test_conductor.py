"""The community agent's waiting clock (conductor.py) with leaping off, as it always was: on a wall clock the test moves by hand, with participants
that answer from a table and a market that says only what it waits on and what it has scheduled.

A step lasts the run's pace at least, then every clock moves one step together. Before that the step waits for each node service to tick it, to
decide and to send, for the wire logs to fall quiet (meter readings don't count), and for what only an answer can bring the market. Waits that
stand unchanged for the idle limit let the clock go on, and that goes on the record. The clock stops before a gate with the step before it
finished, and goes on when the gate is opened: whether a step is finished and which step comes next are asked apart. A participant that does not
take the clock is told of once, one on another line is sent this one again, and the two loops start once. The agent's doors show the clock, set
and open its gates, and start an evening with the count at zero and the gates kept. Every step here is played, though the market has nothing
scheduled at any of them: a clock that was not asked to leap moves one step at a time. Leaps, stops, the pace and a driver's words are
test_conductor_leap.py and test_conductor_asked.py, which use this file's world.
"""
from __future__ import annotations

import json
import os
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from murmur.agents.community import doors
from murmur.agents.community.conductor import Conductor
from murmur.agents.community.conductor_waits import once_more
from murmur.agents.community.service import CommunityAgent
from murmur.protocol import wire
from murmur.replay import Replay

DAY = "2025-01-28"
T0, T1, T2, T3, LAST = (f"{DAY} {hm}" for hm in ("17:00", "17:15", "17:30", "17:45", "23:45"))     # the fixture's last evening: past 16:00, so the 10:00 question holds no clock
HOMES, BUILDINGS, BUYER = "http://homes.test", "http://buildings.test", "http://buyer.test"
OFFICE = f"{BUILDINGS}/b/building-01"
PACE, QUIET, IDLE = 2.0, 4.0, 180.0
KEPT = ("on", "now", "held", "steps", "held_s", "waiting_on", "went_on", "gates", "at_gate")       # what the clock's door has always said


class Stop(BaseException):
    """Ends a loop from inside its wait."""


class Wall:
    """The wall clock, moved by hand."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Parts:
    """The participants as the clock reaches them over HTTP, by base address: a node service says how far its nodes are at GET /agents (`at`), each
    takes the clock at POST /demo/clock (`posts` keeps them) and says its own line at GET /demo/clock (`line`). One in `down` cannot be reached.
    `http` is the client that reaches them, and no network."""

    def __init__(self):
        self.at, self.line, self.posts, self.down, self.asked = {}, {}, [], set(), []
        self.http = httpx.Client(transport=httpx.MockTransport(self))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        base = url.removesuffix("/agents").removesuffix("/demo/clock")
        self.asked.append((request.method, url))
        if base in self.down:
            raise httpx.ConnectError("down", request=request)
        if request.method == "POST":
            self.posts.append((base, json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"clock": self.at[base]} if url.endswith("/agents") else self.line.get(base, {}))


def done(ts: str) -> dict:
    """What a node service says of its clock once its nodes have ticked `ts`, nobody is deciding and nothing is leaving."""
    return {"ticked": ts, "busy": [], "sending": 0, "sent_s": None}


def held(ts: str, wall: float) -> dict:
    """What the waiting clock posts to hold a participant at one step."""
    return {"start": ts, "at": ts, "at_wall": wall, "step_seconds": PACE, "loop_days": 0, "keep": True, "hold": True}


def kept(view: dict) -> dict:
    """Out of all the clock's door says, the fields it has always had."""
    return {k: view[k] for k in KEPT}


def look(w, seconds: float = PACE, nodes_done: bool = True, market_done: bool = True) -> dict:
    """`seconds` pass, with every node service and the market's own loop done with the step the clock holds (unless told not), and the clock's
    loop takes one look: the clock as its door shows it."""
    now = w.k.view()["now"]
    if nodes_done:
        w.parts.at = {HOMES: done(now), BUILDINGS: done(now)}
    if market_done:
        w.c.clock.follower.passed(w.c.clock.follower.moves, now)
    w.wall.t += seconds
    w.k.tick()
    return w.k.view()


@pytest.fixture
def parts():
    p = Parts()
    yield p
    p.http.close()


@pytest.fixture
def world(tmp_path, parts):
    """A community agent as its waiting clock sees it, an evening just started at 17:00: a buyer, the homes' host and one building to move, the two
    hosts to ask, a market that waits on nothing and has scheduled only what `plan` names (step: why), and an empty wire log."""
    wall, events, plan = Wall(), [], {}
    market = SimpleNamespace(lock=threading.RLock(), roster=["home-01", "home-02", "home-03"], events={}, last_discover_day=None, readings_due=lambda: 0,
                             rt=SimpleNamespace(calls={}, settled=None, due=lambda: False), scheduled=plan.get, community=None)
    c = SimpleNamespace(cfg={"clock_waits": True, "clock_wait_quiet_s": QUIET, "clock_wait_idle_s": IDLE}, clock=Replay("homes/HH001", T0, PACE, 0), market=market,
                        targets={"utility": BUYER, "fleet": HOMES, "building-01": OFFICE}, buildings=[{"name": "building-01"}],
                        event=lambda kind, **detail: events.append((kind, detail)))
    k = Conductor(c, wire_files=[tmp_path / "town_wire.jsonl"], http=parts.http, wall=wall)
    c.clock.configure(T0, PACE, 0, T0, wall.t, hold=True)
    k.started(wall.t)
    return SimpleNamespace(k=k, c=c, wall=wall, parts=parts, events=events, plan=plan, wire=tmp_path / "town_wire.jsonl")


def test_a_step_lasts_the_runs_pace_at_least_then_every_clock_moves_one_step_together_and_the_desk_may_read_the_steps_reports(world):
    w = world
    assert look(w, 1.5)["now"] == T0 and w.parts.asked == []          # the pace has not passed: no node service is asked yet
    assert kept(look(w, 0.5)) == {"on": True, "now": T1, "held": True, "steps": 1, "held_s": 0.0, "waiting_on": [], "went_on": [], "gates": [], "at_gate": None}
    assert len(w.parts.posts) == 3 and dict(w.parts.posts) == dict.fromkeys((BUYER, HOMES, OFFICE), held(T1, w.wall.t))
    assert w.c.clock.clock()["at_wall"] == w.wall.t and w.c.market.rt.settled == T0 and w.events == []
    assert look(w, 2.5)["now"] == T2 and look(w)["now"] == T3 and w.k.view()["steps"] == 3 and w.k.view()["held_s"] == 0.5     # half a second beyond the pace, once


def test_a_step_waits_for_each_node_service_to_tick_it_to_decide_and_to_send_what_its_nodes_say(world):
    w = world
    for says, waits in (({"ticked": f"{DAY} 16:45"}, [f"{HOMES}: its nodes at {DAY} 16:45"]),
                        ({"ticked": T0, "busy": ["home-01", "home-02"]}, [f"{HOMES}: 2 deciding (home-01, home-02)"]),
                        ({"ticked": T0, "sending": 3, "sent_s": 0.0}, [f"{HOMES}: 3 messages leaving"]),
                        ({"ticked": T0, "sending": 0, "sent_s": 3.9}, [f"{HOMES}: a message just left"]),
                        (None, [f"{HOMES}: no answer"])):
        w.parts.at, w.parts.down = {HOMES: says, BUILDINGS: done(T0)}, {HOMES} if says is None else set()
        assert look(w, nodes_done=False)["waiting_on"] == waits and w.k.view()["now"] == T0
    assert w.parts.posts == [] and w.c.market.rt.settled is None         # the step's reports aren't all in: the desk doesn't read them yet
    w.parts.down = set()
    w.parts.at[HOMES] = {"ticked": T0, "busy": [], "sending": 0, "sent_s": QUIET}
    assert look(w, nodes_done=False)["now"] == T1 and w.c.market.rt.settled == T0


def test_a_step_waits_while_a_message_went_over_the_bus_in_the_quiet_time_and_a_meter_reading_does_not_count(world, monkeypatch):
    w = world
    monkeypatch.setattr(wire, "_path", str(w.wire))                    # the service's own writer, on this test's wire log and wall clock
    monkeypatch.setattr(wire, "time", SimpleNamespace(time=w.wall))
    wire.note("recv", "home-03", "community", "rt_capacity", {"message": {"short": {}}})
    assert look(w)["waiting_on"] == ["messages on their way over the bus"] and w.k.view()["now"] == T0 and w.c.market.rt.settled is None      # 2 s after it
    w.wall.t += 1.0
    wire.note("recv", "home-03", "community", "on_status", {"message": {"performance": {"usage_kw": 1.2}}})    # a reading, 3 s after the message
    assert look(w, 1.0)["waiting_on"] == ["messages on their way over the bus"]      # the message is 4 s old: the quiet time, and not a moment more
    assert look(w, 0.5)["now"] == T1 and w.c.market.rt.settled == T0   # 4.5 s: only the reading is in the quiet time, and a reading is no reason to wait
    wire.note("send", "community", "home-03", "rt_ask", {"message": {"ask": {}}})
    w.wire.write_text(json.dumps({"t": 1.0, "message": "x" * 100}, separators=(",", ":")) * 600 + "\n" + w.wire.read_text())
    assert w.k.wire_recent(QUIET) is True                              # behind 70 kB of an old line: a log is read from its end
    os.utime(w.wire, (w.wall.t - QUIET - 1.0,) * 2)
    assert w.k.wire_recent(QUIET) is False                             # a log nothing was written to in the quiet time isn't opened
    w.k.wire_files = [w.wire.parent / "no_such_log.jsonl"]
    assert w.k.wire_recent(QUIET) is False                             # and a log that isn't there is quiet


def test_the_market_holds_the_clock_for_what_only_an_answer_can_bring(world):
    w = world
    m, waits = w.c.market, w.k.market_waits
    sale = m.events["sale-1"] = {"need": {"event_id": "sale-1", "window_end": f"{DAY} 21:00"}, "phase": "offers", "offers": {"home-01": {}}}
    assert waits(T0) == ["sale-1: 2 offers to come"]
    sale["phase"] = "utility"
    assert waits(T0) == ["sale-1: the buyers' contract"]
    sale.update(phase="homes", commitments={"home-01": {"status": "SENT"}, "home-02": {"status": "ACCEPTED"}})
    assert waits(T0) == ["sale-1: 1 commitments to answer"]
    sale.update(final_sent=True, telemetry_sent=True)
    assert waits(f"{DAY} 21:45") == ["sale-1: the buyers' settlement"] and waits("2025-01-29 21:00") == []      # a day after the window nothing waits for it
    sale["phase"] = "done"
    m.readings_due, m.rt.due = (lambda: 4), (lambda: True)
    assert waits(T0) == ["4 readings to come", "the desk has reports to read"]
    m.readings_due, m.rt.due = (lambda: 0), (lambda: False)
    assert waits(f"{DAY} 09:45") == [] and waits(f"{DAY} 10:00") == ["the buyer's request for tomorrow"] == waits(f"{DAY} 15:45") and waits(f"{DAY} 16:00") == []
    m.last_discover_day = DAY
    assert waits(f"{DAY} 10:00") == []
    m.rt.calls["gap-1"] = {"id": "gap-1", "phase": "asking"}           # the desk has asked and not every answer is in
    assert look(w)["waiting_on"] == ["call gap-1: answers to come"] and w.k.view()["now"] == T0 and m.rt.settled == T0
    m.rt.calls["gap-1"]["phase"] = "dispatched"
    assert look(w)["now"] == T1


def test_waits_that_stand_unchanged_for_the_idle_limit_let_the_clock_go_on_and_that_goes_on_the_record(world):
    w = world
    w.c.market.rt.calls["gap-1"] = {"id": "gap-1", "phase": "asking"}
    assert look(w)["waiting_on"] == ["call gap-1: answers to come"]    # first seen 2 s into the step
    assert look(w, IDLE - 0.5)["now"] == T0 and w.events == []
    w.parts.at = {HOMES: {"ticked": T0, "busy": ["home-02"]}, BUILDINGS: done(T0)}
    without = [f"{HOMES}: 1 deciding (home-02)", "call gap-1: answers to come"]
    assert look(w, 0.5, nodes_done=False)["waiting_on"] == without      # the waits changed: the idle limit counts from here
    assert look(w, IDLE - 0.5, nodes_done=False)["now"] == T0 and w.events == []
    view = look(w, 0.5, nodes_done=False)
    assert w.events == [("clock_went_on", {"sim": T0, "waited_s": 362.0, "without": without})]
    assert kept(view) == {"on": True, "now": T1, "held": True, "steps": 1, "held_s": 360.0, "waiting_on": [], "went_on": [{"sim": T0, "wall": 1362.0, "without": without}],
                          "gates": [], "at_gate": None}


def test_the_clock_stops_before_a_gate_with_the_step_before_it_finished_and_goes_on_when_the_gate_is_opened(world):
    w = world
    w.k.set_gates([T1, T3])
    view = look(w)
    assert (view["now"], view["at_gate"], view["gates"], view["steps"]) == (T0, T1, [T1, T3], 0) and w.parts.posts == []
    i = w.c.clock.current()
    assert w.k.finished(i) == w.wall.t and w.k.next_step(i) is None    # two questions: the step is finished, and no step comes next while the gate is shut
    w.k.open_gate(T1)
    assert w.k.view()["at_gate"] is None and w.k.view()["gates"] == [T3] and w.k.next_step(i) == i + 1
    assert look(w, 3.0)["now"] == T1 and w.k.view()["held_s"] == 3.0   # the seconds at the gate count as held beyond the pace
    assert look(w)["now"] == T2 and look(w)["at_gate"] == T3 and w.k.view()["now"] == T2
    w.k.set_gates([])                                                  # a new list takes the old one's place
    assert w.k.view()["at_gate"] is None and look(w, 0.0)["now"] == T3


def test_a_participant_that_does_not_take_the_clock_is_told_of_once_and_again_when_that_changes(world):
    w = world
    w.parts.down = {BUYER}
    assert look(w)["now"] == T1 and look(w)["now"] == T2
    assert w.events == [("clock_not_reached", {"sim": T1, "agents": {"utility": "not reached: down"}})]      # at the first step it missed, not at the second
    w.parts.down = set()
    assert look(w)["now"] == T3 and w.events[1:] == [("clock_not_reached", {"sim": T3, "agents": {}})]
    assert sorted(base for base, body in w.parts.posts if body["at"] == T3) == sorted((BUYER, HOMES, OFFICE))


def test_a_participant_on_another_line_is_sent_this_one_again_unless_the_clocks_are_being_moved(world):
    w = world
    line = {"at_wall": w.wall.t, "step_seconds": PACE, "held": True, "now": T0}
    w.parts.line, w.parts.down = {BUYER: line, HOMES: {**line, "at_wall": None, "held": False, "now": f"{DAY} 00:00"}}, {OFFICE}
    w.k.clock_again()                                                  # the homes' host started again on its own clock; the building can't be asked
    assert w.parts.posts == [(HOMES, held(T0, w.wall.t))] and w.events == [("clock_sent_again", {"agent": "fleet", "was": f"{DAY} 00:00", "now": T0})]
    w.parts.line.update({HOMES: line, BUYER: {**line, "now": T1}})     # the host took it; now the buyer is a step off
    w.k.cond["posting"] = True
    w.k.clock_again()                                                  # a step is posting the next line: not now
    w.k.cond["posting"] = False
    with w.k.lock:
        w.k.clock_again()                                              # a start is moving every clock: not now
    assert len(w.parts.posts) == 1
    w.k.clock_again()
    assert w.parts.posts[1:] == [(BUYER, held(T0, w.wall.t))]


def test_the_clock_stays_while_it_does_not_wait_while_a_start_moves_every_clock_before_the_start_running_free_and_at_the_end_of_the_data(world):
    w = world
    w.c.cfg["clock_waits"] = False
    assert look(w)["now"] == T0
    w.c.cfg["clock_waits"] = True
    with w.k.lock:
        assert look(w)["now"] == T0                                    # a start holds the lock
    w.k.started(w.wall.t + 5.0)
    assert look(w)["now"] == T0                                        # the start lies ahead: every clock begins together, a little later
    w.c.clock.configure(LAST, PACE, 0, LAST, w.wall.t, hold=True)
    w.k.started(w.wall.t)
    assert look(w)["now"] == LAST and w.k.view()["steps"] == 0         # the last step of the data
    w.c.clock.configure(T0, PACE, 0, T0, time.time())                  # on 17:00 again, running free on the real wall clock
    w.k.started(w.wall.t)
    assert look(w)["held"] is False                                    # a clock that runs free is nobody's to hold
    assert w.parts.asked == [] and w.parts.posts == []


def test_the_node_services_asked_are_the_homes_host_and_each_buildings_host_once_or_the_ones_the_configuration_names(world):
    w = world
    w.c.targets["building-02"] = f"{BUILDINGS}/b/building-02"
    w.c.buildings.append({"name": "building-02"})
    assert w.k.agent_services() == [HOMES, BUILDINGS]
    w.c.cfg["clock_wait_urls"] = [BUYER]
    assert w.k.agent_services() == [BUYER] and w.k.quiet_s() == QUIET
    del w.c.cfg["clock_wait_quiet_s"]
    assert w.k.quiet_s() == 4.0


def test_a_call_whose_kept_connection_had_dropped_is_tried_once_more_at_once_and_one_that_timed_out_is_not():
    tries = []

    def call(url: str, faults: list) -> str:
        tries.append(url)
        if faults:
            raise faults.pop(0)
        return "answer"
    assert once_more(call, "a", [httpx.RemoteProtocolError("the participant had closed it")]) == "answer"
    pytest.raises(httpx.ConnectError, once_more, call, "b", [httpx.ConnectError("down"), httpx.ConnectError("down")])
    pytest.raises(httpx.ReadTimeout, once_more, call, "c", [httpx.ReadTimeout("no answer in time")])
    assert tries == ["a", "a", "b", "b", "c"]


def test_the_two_loops_start_once_one_looks_again_at_once_after_a_move_and_outlives_a_look_that_fails_the_other_sends_the_line_again_every_20_s(world):
    w, waits, did = world, [], []
    looks = [True, True, False, RuntimeError("a look that fails"), False, False]       # the clocks moved twice, then not; a look failed; then nothing moved

    def wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) > 3:
            raise Stop

    def tick() -> bool:
        did.append("woken" if w.k.woken.is_set() else "look")
        if isinstance(looks[0], Exception):
            raise looks.pop(0)
        return looks.pop(0)
    w.k.pause, w.k.sleep, w.k.tick, w.k.clock_again = wait, wait, tick, lambda: did.append("again")
    w.k.wake()
    with pytest.raises(Stop):
        w.k.step_loop()
    assert did == ["look"] * 6 and waits == [w.k.nap()] * 4            # no wait after a move, one after every other look; a word that woke the loop is taken with the look
    del waits[:], did[:]
    with pytest.raises(Stop):
        w.k.again_loop()
    assert waits == [20.0] * 4 and did == ["again"] * 3
    before, release = set(threading.enumerate()), threading.Event()
    w.k.step_loop = w.k.again_loop = release.wait                      # each loop's thread waits here until the test lets it end
    w.k.start_loops()
    w.k.start_loops()
    mine = [t for t in threading.enumerate() if t not in before]
    release.set()
    for t in mine:
        t.join(5.0)
    assert sorted(t.name for t in mine) == ["clock", "clock-again"] and all(t.daemon and not t.is_alive() for t in mine)


def test_the_agents_doors_show_the_clock_set_and_open_its_gates_and_start_an_evening_with_the_count_at_zero_and_the_gates_kept(agent_config, tmp_path, parts):
    agent_config(agent_name="community", buyers=["utility"], sync_broadcast=True, replay_start=T0, replay_loop_days=0, clock_waits=True, clock_wait_urls=[HOMES])
    c, wall, loops = CommunityAgent(), Wall(), []
    k = Conductor(c, wire_files=[tmp_path / "town_wire.jsonl"], http=parts.http, wall=wall)
    k.step_loop, k.again_loop = (lambda: loops.append("clock")), (lambda: loops.append("clock-again"))      # the loops' threads end at once: the test looks by hand
    door = TestClient(doors.build_app(c, k))
    begin, first, second = "2025-01-27 09:45", "2025-01-27 10:00", "2025-01-27 10:15"

    def shown(**other) -> dict:
        """What GET /demo/conductor says just after a start with both gates set, but for `other`."""
        return {"on": True, "now": begin, "held": True, "steps": 0, "held_s": 0.0, "waiting_on": [], "went_on": [], "gates": [first, second], "at_gate": None} | other
    assert kept(door.get("/demo/conductor").json()) == shown(now=T0, held=False, gates=[])
    assert kept(door.post("/demo/conductor", json={"gates": [second, first]}).json()) == shown(now=T0, held=False)
    assert door.post("/demo/start", json={"event": DAY}).status_code == 503       # its inbox has not been empty yet: only a forced start
    st = door.post("/demo/start", json={"event": DAY, "step_seconds": 2, "lead_s": 1, "force": True}).json()
    assert st == {"event": DAY, "starts_at": begin, "step_seconds": 2.0, "wall_start": k.cond["since"], "minutes_total": 5.1, "agents": {"community": begin},
                  "pace_s": 2.0, "leap": False}
    assert kept(door.get("/demo/conductor").json()) == shown()
    parts.at, wall.t = {HOMES: done(begin)}, st["wall_start"] + 2.0   # the pace has passed and the homes' host is done with 09:45
    c.clock.follower.passed(c.clock.follower.moves, begin)            # and so is the market's own loop, which no thread runs here
    k.tick()
    assert kept(door.get("/demo/conductor").json()) == shown(at_gate=first)
    assert kept(door.post("/demo/conductor", json={"open": first}).json()) == shown(gates=[second])
    k.tick()
    assert kept(door.get("/demo/conductor").json()) == shown(now=first, steps=1, gates=[second]) and c.market.now() == first
    assert door.post("/demo/start", json={"event": DAY, "step_seconds": 2, "lead_s": 1, "force": True}).status_code == 200
    assert kept(door.get("/demo/conductor").json()) == shown(gates=[second])              # the count at zero again, the gate still set
    assert [e["kind"] for e in c.events if e["kind"].startswith(("demo", "clock"))] == ["demo_start", "demo_start"]
    for t in [t for t in threading.enumerate() if t.name in ("clock", "clock-again")]:
        t.join(5.0)
    assert sorted(loops) == ["clock", "clock-again"] and k.looping                 # started at the first start, not again at the second

"""Loops that work by the clock, and two doors of a node host: a clock that is set starts the next pass of its loop at once, the loop says the dataset
time of its last whole pass and the clock door answers it, a host gives back every reading it kept after a time however far its clock moved, and the
scenario door sets a battery's charge."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from demo.runner.bus import Run, make_bus
from demo.runner.buyers import utility, utility_doors
from demo.runner.buyers.stand_in import StandInBuyer
from murmur import config, replay
from murmur.agents import aggregator, host, host_doors, site_service
from murmur.agents.building import BuildingHost
from murmur.agents.community import service
from murmur.agents.host_common import TEL_KEYS
from murmur.node.simulator import CATCH_UP
from tests.test_sites_aggregator import REQ, RUN, TOKENS, aggregator_node, on_bus, site_node

HOMES = ["home-01", "home-02", "home-03"]
FIRST, NOON, NEXT_NOON, LAST = "2025-01-27 00:00", "2025-01-27 12:00", "2025-01-28 12:00", "2025-01-28 23:45"     # the fixture's two days; the noons are 96 quarter hours apart
FAR, SOON = 60.0, 1.0          # each loop's own cadence is stretched to FAR s, so only a clock that is set can start its next pass within SOON s


class Stop(BaseException):
    """Ends a loop's thread from inside its wait."""


def until(cond, seconds: float = 5.0) -> bool:
    """Waits for cond() to hold, `seconds` at most."""
    end = time.time() + seconds
    while not cond() and time.time() < end:
        time.sleep(0.002)
    return bool(cond())


@contextmanager
def running(loop, follower):
    """A service's loop on a thread of its own, for one test: gives its waits, each [began, ended] in wall seconds (ended None while it lasts)."""
    real, waits, stop = follower.wait, [], threading.Event()

    def wait(seen: int, seconds: float) -> None:
        waits.append([time.time(), None])
        if not stop.is_set():
            real(seen, seconds)
        waits[-1][1] = time.time()
        if stop.is_set():
            raise Stop

    def run() -> None:
        try:
            loop()
        except Stop:
            pass
    follower.wait = wait
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield waits
    finally:
        stop.set()
        follower.moved()
        thread.join(10.0)
        del follower.wait
    assert not thread.is_alive()


def set_while_it_waits(waits: list, set_clock) -> float:
    """Sets the clock while the loop is in a wait, and gives the seconds until that wait ended: there the loop's next pass begins."""
    assert until(lambda: bool(waits) and waits[-1][1] is None)
    last, t0 = waits[-1], time.time()
    set_clock()
    assert until(lambda: last[1] is not None)
    return last[1] - t0


def held(ts: str, **more) -> dict:
    """What the community's waiting clock posts to hold a participant at one step."""
    return {"start": ts, "at": ts, "at_wall": time.time(), "step_seconds": 2.0, "loop_days": 0, "keep": True, "hold": True, **more}


def ticked(door: TestClient, path: str = "/demo/clock") -> str | None:
    return door.get(path).json()["ticked"]


@pytest.fixture
def bus():
    run = Run(RUN, tokens=dict(TOKENS), lease_s=0.1)
    client = TestClient(make_bus({RUN: run}))
    yield run, client
    client.close()


@pytest.fixture
def nodes(agent_config):
    """Makes a node host over the fixture dataset, set up as the demo runner sets one up, with no bus: what a node sends lands in host.sent."""
    tokens, made = config.CONFIG_DIR / "secrets" / "host_tokens.json", []
    tokens.parent.mkdir(parents=True, exist_ok=True)

    def make(kind: str = "homes"):
        names = HOMES if kind == "homes" else ["building-01"]
        tokens.write_text(json.dumps(dict.fromkeys(names, "t")))
        agent_config(agent_name=kind, homes=HOMES, buildings=["building-01"], town_url="http://testserver", town_run_id=RUN, replay_start=FIRST, replay_loop_days=0,
                     control_mode="rolling", buyers=["utility"], report_rule="exception")
        f = (host.NodeHost if kind == "homes" else BuildingHost)()
        f.sent = []
        f._send = lambda town, to, kind_, body, mid: f.sent.append((town.name, to, kind_))
        made.append(f)
        return f, TestClient(host_doors.build_app(f))
    yield make
    for f in made:
        f.pool.shutdown(wait=False)
        f.http.close()
    tokens.unlink(missing_ok=True)


def one_pass(f) -> None:
    for h in f.homes.values():
        h.tick()


# ---------------------------------------------------------------------------------------------------------------- the clock and its follower
def test_a_clock_that_is_set_ends_its_loops_wait_at_once_and_a_wait_nothing_ends_runs_its_whole_time():
    rp = replay.Replay("homes/HH001", FIRST, 60, 0)
    f, t0 = rp.follower, time.time()
    seen = f.moves
    threading.Timer(0.05, rp.configure, (NOON, 60, 0)).start()
    f.wait(seen, FAR)                                             # ended by the set, not by its 60 s
    assert time.time() - t0 < SOON and f.moves == seen + 1
    t0 = time.time()
    f.wait(seen, FAR)                                             # the clock was set since `seen` was read: no move is slept through
    assert time.time() - t0 < SOON
    t0 = time.time()
    f.wait(f.moves, 0.05)                                         # nothing set: the wait is the loop's cadence
    assert 0.04 <= time.time() - t0 < SOON
    with pytest.raises(ValueError, match="not in dataset"):
        rp.configure("2025-02-01 00:00", 60, 0)
    assert f.moves == seen + 1                                    # a set that was refused moved nothing


def test_a_loop_says_the_time_of_its_last_whole_pass_and_a_pass_the_clock_was_set_under_says_nothing():
    rp = replay.Replay("homes/HH001", FIRST, 60, 0)
    rp.configure(NOON, 60, 0, hold=True)
    f = rp.follower
    seen = f.moves
    assert rp.ticked is None and rp.clock() == {"start": NOON, "step_seconds": 60.0, "loop_days": 0, "at_wall": None, "now": NOON, "held": True, "ticked": None}
    f.passed(seen, NOON)
    assert rp.ticked == rp.clock()["ticked"] == NOON
    rp.configure(NEXT_NOON, 60, 0, hold=True)                     # set again: the pass at the new time is still to come
    assert rp.ticked is None
    f.passed(seen, NOON)                                          # a pass that began before the set
    assert rp.ticked is None
    f.passed(f.moves, NEXT_NOON)
    assert rp.ticked == NEXT_NOON


def test_each_loop_keeps_its_cadence_while_no_clock_is_set():
    assert (aggregator.TICK_S, site_service.TICK_S, service.TICK_S, utility.TICK_S, host.PASS_S) == (0.25, 0.25, 1.0, 2.0, 1.0)


# ---------------------------------------------------------------------------------------------------------------- the five loops
def test_a_set_clock_starts_the_aggregators_next_pass_at_once_and_its_request_goes_with_it(bus, agent_config, sites, monkeypatch):
    run, client = bus
    agg = on_bus(aggregator_node(agent_config, sites), client)
    door = TestClient(aggregator.build_app(agg))
    monkeypatch.setattr(aggregator, "TICK_S", FAR)
    with running(agg.tick_loop, agg.clock.follower) as waits:
        assert until(lambda: bool(waits)) and ticked(door) is None and not agg.started          # before its play starts a pass does nothing, and says nothing
        took = set_while_it_waits(waits, lambda: door.post("/demo/clock", json=held("2025-01-28 14:00")))
        assert took < SOON and until(lambda: ticked(door) == "2025-01-28 14:00")
        assert list(agg.sent) == [REQ] and len(run.inbox["site-pv-01"]) == 1                    # the request made at 14:00 went with that pass


def test_a_set_clock_starts_the_sites_next_pass_at_once_and_every_quarter_hour_due_goes_up(bus, agent_config, sites, monkeypatch):
    run, client = bus
    site = on_bus(site_node(agent_config, sites), client)
    door = TestClient(site_service.build_app(site))
    monkeypatch.setattr(site_service, "TICK_S", FAR)
    with running(site.tick_loop, site.clock.follower) as waits:
        took = [set_while_it_waits(waits, lambda t=t: door.post("/demo/clock", json=held(t))) for t in ("2025-01-28 17:45", "2025-01-28 18:45")]
        assert max(took) < SOON and until(lambda: ticked(door) == "2025-01-28 18:45")
        assert (len(site.done), site.sent_up, len(run.inbox["aggregator"])) == (5, 5, 5)        # 17:45, then the four quarter hours the clock moved over


def test_a_pass_that_leaves_work_for_the_next_one_is_not_a_whole_pass(bus, agent_config, sites):
    run, client = bus
    site = site_node(agent_config, sites)
    door = TestClient(site_service.build_app(site))
    assert site.tick() is False                                   # its play has not started
    site.town = SimpleNamespace(send=lambda *a: (_ for _ in ()).throw(OSError("the bus is away")))
    door.post("/demo/clock", json=held("2025-01-28 17:45"))
    assert site.tick() is False and len(site.outbox) == 1         # the row is made and still to go
    assert on_bus(site, client).tick() is True and not site.outbox
    agg = aggregator_node(agent_config, sites)
    agg_door = TestClient(aggregator.build_app(agg))
    assert agg.tick() is False                                    # not started
    agg.town = SimpleNamespace(send=lambda *a: (_ for _ in ()).throw(OSError("the bus is away")))
    agg_door.post("/demo/clock", json=held("2025-01-28 14:00"))
    assert agg.tick() is False and not agg.sent                   # its request is due and did not go
    assert on_bus(agg, client).tick() is True and list(agg.sent) == [REQ]


def test_a_set_clock_starts_the_buyers_next_pass_at_once_and_a_call_told_for_that_step_goes_with_it(agent_config, monkeypatch):
    agent_config(town_url="http://testserver", town_run_id=RUN, replay_start=FIRST, replay_loop_days=0)
    u, sent = StandInBuyer("utility"), []
    u.town = SimpleNamespace(send=lambda to, kind, body, mid: sent.append((to, kind)) or {})
    door = TestClient(utility_doors.build_app(u))
    door.post("/demo/clock", json=held("2025-01-28 17:45"))
    assert door.post("/alert", json={"kw": 5.0, "minutes": 60, "at": "2025-01-28 18:00"}).json()["at"] == "2025-01-28 18:00"
    monkeypatch.setattr(utility, "TICK_S", FAR)
    with running(u.tick_loop, u.clock.follower) as waits:
        assert until(lambda: ticked(door) == "2025-01-28 17:45") and not sent
        took = set_while_it_waits(waits, lambda: door.post("/demo/clock", json=held("2025-01-28 18:00")))
        assert took < SOON and until(lambda: ticked(door) == "2025-01-28 18:00")
        assert sent == [("community", "beckn.rt_call")]


def test_a_set_clock_starts_the_markets_next_pass_at_once_and_the_market_says_the_pass_in_its_own_process(agent_config, monkeypatch):
    agent_config(agent_name="community", buyers=["utility"], sync_broadcast=True, replay_start="2025-01-27 09:45", replay_loop_days=0)
    c, sent = service.CommunityAgent(), []
    c.town = SimpleNamespace(send=lambda to, kind, body, mid: sent.append((to, kind)) or {})
    c.clock.configure("2025-01-27 09:45", 2.0, 0, hold=True)
    monkeypatch.setattr(service, "TICK_S", FAR)
    with running(c.market_loop, c.clock.follower) as waits:
        assert until(lambda: c.clock.ticked == "2025-01-27 09:45") and not sent
        took = set_while_it_waits(waits, lambda: c.clock.configure("2025-01-27 10:00", 2.0, 0, "2025-01-27 10:00", time.time(), hold=True))   # as its waiting clock sets it
        assert took < SOON and until(lambda: c.clock.ticked == "2025-01-27 10:00")
        assert sent == [("utility", "beckn.discover")]            # the 10:00 question to the buyer went with that pass


@pytest.mark.parametrize("kind, clock_door", [("homes", "/demo/clock"), ("buildings", "/b/building-01/demo/clock")])
def test_a_set_clock_starts_a_hosts_next_pass_over_its_nodes_at_once(nodes, monkeypatch, kind, clock_door):
    f, door = nodes(kind)
    assert all(h.replay.follower is f.follower for h in f.homes.values())                       # one loop for every node's clock
    monkeypatch.setattr(host, "PASS_S", FAR)
    with running(f.tick_loop, f.follower) as waits:
        took = set_while_it_waits(waits, lambda: door.post(clock_door, json=held(NOON, keep=False)))
        assert took < SOON and until(lambda: ticked(door, clock_door) == NOON)
        took = set_while_it_waits(waits, lambda: door.post(clock_door, json=held(NEXT_NOON)))     # 96 steps on: every one of them is stepped in the pass it starts
        assert took < SOON and until(lambda: ticked(door, clock_door) == NEXT_NOON)
        clock = door.get("/agents").json()["clock"]
        assert (clock["now"], clock["held"], clock["ticked"]) == (NEXT_NOON, True, NEXT_NOON)   # as the waiting clock has always read it
        assert all(set(range(48, 145)) <= set(h.adapter.recent) and h.adapter.tel["ts"] == NEXT_NOON for h in f.homes.values()) and not f.sent


def test_a_new_runs_clock_and_its_fresh_start_reach_a_node_together_so_the_pass_the_clock_starts_steps_it_once(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held(NOON, keep=False))
    one_pass(f)
    h, lock, stepped = f.homes["home-01"], f.locks["home-01"], []
    step, configure = h.adapter._step, h.replay.configure

    def set_and_tick(*line) -> None:                              # the tick comes the moment the clock is set, as its loop now does
        configure(*line)
        if lock.try_enter():
            try:
                h.tick()
            finally:
                lock.leave()
    h.adapter._step = lambda i: (stepped.append(h.replay.ts(i)), step(i))[1]
    h.replay.configure = set_and_tick
    door.post("/demo/clock", json=held("2025-01-27 09:45", keep=False))     # a new run, from an earlier step
    one_pass(f)
    assert stepped == ["2025-01-27 09:45"] and h.adapter.tel["ts"] == "2025-01-27 09:45"


# ---------------------------------------------------------------------------------------------------------------- readings across a leap
def rows_of(f, ts_from: str, ts_to: str) -> dict:
    """What /telemetry gives back as `recent`: each node's kept rows after ts_from up to ts_to, oldest first."""
    return {n: [[x.get(k) for k in TEL_KEYS] + [h.adapter.E] for i, x in sorted(h.adapter.recent.items()) if ts_from < x["ts"] <= ts_to] for n, h in f.homes.items()}


def test_every_reading_kept_after_a_time_comes_back_however_far_the_clock_moved(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held(NOON, keep=False))
    one_pass(f)
    door.post("/demo/clock", json=held(NEXT_NOON))                # 96 quarter hours in one move
    one_pass(f)
    got = door.get("/telemetry", params={"since": NOON}).json()
    its = got["keys"].index("ts")
    quarters = [f.homes["home-01"].replay.ts(i) for i in range(48 + 1, 48 + 97)]
    assert sorted(got["recent"]) == HOMES and all([r[its] for r in got["recent"][n]] == quarters for n in HOMES)
    assert got["recent"] == rows_of(f, NOON, NEXT_NOON) and all(got["recent"][n][-1] == got["homes"][n] for n in HOMES)
    assert len(door.get("/telemetry", params={"since": NOON}).content) < 96 * len(HOMES) * 400      # under 400 bytes a row


def test_a_host_keeps_and_gives_back_as_many_quarter_hours_as_its_nodes_catch_up(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held(FIRST, keep=False))
    one_pass(f)
    door.post("/demo/clock", json=held(LAST))                     # the fixture's whole two days less one step: 191 quarter hours
    one_pass(f)
    got = door.get("/telemetry", params={"since": FIRST}).json()["recent"]
    assert CATCH_UP == 192 and all(len(got[n]) == 191 for n in HOMES) and got == rows_of(f, FIRST, LAST)
    assert host_doors.rows_after(f.homes["home-01"].adapter, FIRST, keep=12) == rows_of(f, "2025-01-28 20:45", LAST)["home-01"]     # the newest ones, when more are kept than are given


def test_the_readings_door_answers_as_before_without_a_time_and_for_a_time_one_or_two_steps_back(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held(NOON, keep=False))
    one_pass(f)
    for ts in ("2025-01-27 12:15", "2025-01-27 12:30"):
        door.post("/demo/clock", json=held(ts))
        one_pass(f)
    latest = {n: [h.adapter.tel.get(k) for k in TEL_KEYS] + [h.adapter.E] for n, h in f.homes.items()}
    plain = {"now": "2025-01-27 12:30", "keys": list(TEL_KEYS) + ["E"], "homes": latest}
    assert door.get("/telemetry").json() == plain
    assert door.get("/telemetry", params={"since": "2025-01-27 12:15"}).json() == {**plain, "recent": {}}     # one row after it: the latest row says it already
    assert door.get("/telemetry", params={"since": NOON}).json() == {**plain, "recent": rows_of(f, NOON, "2025-01-27 12:30")}
    assert door.get("/telemetry", params={"since": "2025-01-27 12:30"}).json() == {**plain, "recent": {}}


# ---------------------------------------------------------------------------------------------------------------- a battery's charge
def test_the_scenario_door_sets_a_batterys_charge_and_its_no_event_twin_holds_the_same(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held("2025-01-28 17:45", keep=False))
    one_pass(f)
    a = f.homes["home-01"].adapter
    was = round(a.soc * 100, 2)
    out = door.post("/demo/scenario", json={"battery_soc": {"homes": ["home-01"], "pct": 85}}).json()
    assert out["battery_soc"] == {"pct": 85.0, "homes": ["home-01"], "set": {"home-01": {"soc_pct": 85.0, "was_pct": was}}} and out["now"] == "2025-01-28 17:45"
    assert (a.soc, a.cf["soc"]) == (0.85, 0.85) and (a.P, a.levers, a.plan, a.overrides) == (5.0, None, {}, {})      # the charge alone: the rest of the node is its own
    events = list(f.events)
    assert {"home": "home-01", "kind": "what_if", "what": "battery_soc", "soc_pct": 85.0, "was_pct": was}.items() <= events[-2].items()
    assert {"kind": "what_if_battery_soc", "pct": 85.0, "homes": 1}.items() <= events[-1].items()
    door.post("/demo/clock", json=held("2025-01-28 18:00"))
    one_pass(f)                                                   # the next quarter hour starts from that charge, in the home and in its twin alike
    t = a.tel
    assert t["soc_pct"] == t["soc_cf_pct"] < 85.0 and t["batt_kw"] > 0 and t["grid_kw"] == t["grid_cf_kw"]


def test_a_charge_below_a_batterys_reserve_is_held_at_the_reserve_and_n_picks_homes_with_a_battery(nodes):
    f, door = nodes()
    door.post("/demo/clock", json=held("2025-01-28 17:45", keep=False))
    one_pass(f)
    out = door.post("/demo/scenario", json={"battery_soc": {"n": 2, "pct": 5}}).json()["battery_soc"]
    assert out["homes"] == ["home-01", "home-02"] and [out["set"][n]["soc_pct"] for n in out["homes"]] == [20.0, 20.0]     # each one's reserve: the answer says what it set
    door.post("/demo/clock", json=held("2025-01-28 18:00"))
    one_pass(f)
    for n in out["homes"]:
        t = f.homes[n].adapter.tel
        assert (t["soc_pct"], t["soc_cf_pct"], t["batt_kw"]) == (20.0, 20.0, 0.0) and t["grid_kw"] == t["grid_cf_kw"]      # nothing to give, and no charge from nowhere
    assert f.homes["home-03"].adapter.tel["soc_pct"] > 20.0


@pytest.mark.parametrize("bad", [{"pct": 50}, {"homes": ["home-01"]}, {"homes": ["home-01"], "pct": 4.9}, {"homes": ["home-01"], "pct": 100.1},
                                 {"homes": ["home-01"], "pct": "50"}, {"homes": ["home-01"], "pct": True}, {"homes": ["home-01"], "pct": float("nan")},
                                 {"homes": ["home-09"], "pct": 50}, {"homes": "home-01", "pct": 50}, {"homes": [], "pct": 50}, {"n": 0, "pct": 50},
                                 {"n": 1.5, "pct": 50}, {"n": True, "pct": 50}, {"n": "2", "pct": 50}, ["home-01", 50], "low"])
def test_the_scenario_door_refuses_a_charge_it_cannot_set_and_changes_nothing(nodes, bad):
    f, door = nodes()
    before = {n: (h.adapter.soc, dict(h.adapter.cf)) for n, h in f.homes.items()}
    r = door.post("/demo/scenario", content=json.dumps({"battery_soc": bad}), headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"].startswith("battery_soc: ")
    assert {n: (h.adapter.soc, dict(h.adapter.cf)) for n, h in f.homes.items()} == before and not f.events


def test_a_node_without_a_battery_takes_no_charge(nodes):
    f, door = nodes("buildings")
    r = door.post("/demo/scenario", json={"battery_soc": {"homes": ["building-01"], "pct": 50}})
    assert (r.status_code, r.json()["detail"]) == (400, "battery_soc: building-01 has no battery")
    assert door.post("/demo/scenario", json={"battery_soc": {"n": 1, "pct": 50}}).status_code == 400

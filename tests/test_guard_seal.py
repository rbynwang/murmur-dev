"""The safety guard and the seal, refusals first.

A home's guard (node/guard.py) answers a device call in a fixed order: an alarm, a person's stop, the shelf, the target, the owner's
wishes, the step's list, each tool's own rules, then one writer per target. A building's guard (node/guard_building.py) adds the
never-touched list, the times of every write, a writer giving back its own call, missing readings and points that targets share. The
gate (node/drivers.py) seals what a guard passed, as it applied it, and a refused call reaches no driver: only Gate.run makes a ticket, a
driver takes only a fresh, untouched ticket from its own gate, a guard or a driver that breaks sends nothing and gives the guard its memory
back, the real drivers refuse every write, and release_all ends every limit. The facts: the fixture dataset at 17:30, 30 minutes before SALE."""
from __future__ import annotations

import dataclasses

import pytest

from murmur.agents.host_common import node_class
from murmur.node import drivers as D
from murmur.node import policy as P
from murmur.node import simulator_building as building
from murmur.node.building_agent import BuildingAgent
from murmur.node.guard import STOPPED, Guard, answer
from murmur.node.guard_building import CLIMATE
from murmur.protocol import signing
from murmur.replay import Replay
from tests import world

DAY = "2025-01-28"
SALE = {"start": f"{DAY} 18:00", "end": f"{DAY} 21:00", "owed_kw": 4.0, "by_ts": {}}
NO_SEAL = {"status": "blocked", "why": "Nothing was sent: this command has no guard's seal."}
DONE = {"status": "done", "why": ""}
HOLD = {"tool": "set_battery", "target": "home-battery", "action": "hold", "kw": 0}


def call(tool: str, start: str = "18:00", end: str = "21:00", **args) -> dict:
    return {"tool": tool, "args": args, "start": f"{DAY} {start}", "end": f"{DAY} {end}"}


def facts(node, agent) -> dict:
    """What the agent reads at 17:30, before the sale."""
    node.replay.configure("2025-01-27 00:00", 60, 0, f"{DAY} 17:30", 1e12, hold=True)
    return agent.view(node.now_ts(), dict(SALE))


def home(name: str, tmp) -> tuple:
    """(the node, its agent, the agent's facts) for a fixture home."""
    node, _ = world.home(name, tmp)
    agent = world.agent(node)
    return node, agent, facts(node, agent)


def brief(out: dict) -> tuple:
    return out["status"], out["applied"], out["expected_kw"], out["why"]


def broken(*_):
    raise RuntimeError("no answer")


@pytest.fixture
def h1(tmp_path):
    return home("home-01", tmp_path)


@pytest.fixture
def office(tmp_path):
    """The office building's guard and facts, with its agent built as the buildings host builds it."""
    b, c = next(x for x in building.enabled({"buildings": "all"}) if x["name"] == "building-01"), world.EVENING
    rp = Replay(b["profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
    acfg = {"agent_name": b["name"], "name": b["name"], "building": b["name"], "control": "auto", "forecast": c["forecast"], "control_mode": "rolling",
            "opt_out_days": [], "owner_limits": {}}
    node = node_class(c)(b["name"], acfg, building.SimulatedBuilding(acfg, rp), rp, signing.load_or_create(tmp_path / "building-01.key"),
                         send=lambda *m: None, trusted=lambda: [], log=lambda *a, **k: None)
    agent = BuildingAgent(node, world.Model(), lambda rec: None)
    return agent.guard, facts(node, agent)


def gate(guard: Guard | None = None, hold: bool = False, **hooks) -> tuple:
    """A gate on a simulated driver that writes nothing and keeps, in tickets, everything it is handed. hold: it sends none, so each nonce stays fresh."""
    drv = D.SimulatedDriver(**{"write": lambda c, a: None, **hooks})
    drv.tickets, send = [], drv.send
    drv.send = lambda t: drv.tickets.append(t) or (DONE if hold else send(t))
    return D.Gate("home-01", guard or Guard(), drv), drv


class Passes(Guard):
    """A guard that takes every call's point and passes the call as asked, so each one reaches the driver."""
    def check(self, call, f):
        self.writers[call["args"]["target"]] = call
        return answer("done", call["args"]["target"], {"asked": True}, 1.0)


def test_an_alarm_then_a_persons_stop_block_every_call_before_the_shelf_is_read(h1):
    node, a, _ = h1
    pump = call("set_pool_pump", target="pool-pump", speed_percent=40)
    node.adapter.rt_override("stop", True)
    f = facts(node, a)
    assert (f["alarm"], f["stopped"], a.guard.check(pump, f)["why"]) == (None, True, STOPPED)
    node.adapter.rt_override("alarm", "smoke detector")
    f, alarm = facts(node, a), "An alarm is on, so nothing is sent and every agent limit releases."
    assert (f["alarm"], a.guard.check(pump, f)["why"], a.guard.check(call("set_battery", target="home-battery", action="hold"), f)["why"]) == ("smoke detector", alarm, alarm)


def test_a_tool_off_the_shelf_is_refused_first_and_an_unknown_target_is_offered_the_tools_own(h1):
    g, f = h1[1].guard, h1[2]
    assert g.check(call("set_thermostat", target="all-room-acs", less_comfort_c=1), f)["why"] == "This node has no set_thermostat."     # its room ACs are set_room_ac's
    out = g.check(call("set_battery", target="garage-battery", action="hold"), f)
    assert (out["status"], out["why"], out["try_instead"]) == ("blocked", "garage-battery can't take this call now.", {"tool": "set_battery", "target": "home-battery"})
    assert g.check(call("set_battery", action="hold"), f)["why"] == "That target can't take this call now."
    out = g.check(call("discharge_car", target="car", kw=2), f)                  # on the shelf, and this home's car gives no power
    assert (out["why"], out["try_instead"]) == ("car can't take this call now.", {})


def test_an_owners_wish_then_the_steps_list_refuse_a_call_but_a_full_battery_may_still_hold_or_charge(h1):
    g, f = h1[1].guard, h1[2]
    g.wishes = [{"wish": "keep_battery_full"}, {"wish": "keep_hot_water"}]
    assert g.check(call("set_battery", target="home-battery", action="discharge", kw=1), f)["why"] == "The owner needs the battery kept full."
    assert g.check(call("set_battery", "16:00", "17:00", target="home-battery", action="charge", kw=2), f)["status"] == "done"
    assert g.check(call("set_battery", target="home-battery", action="hold"), f)["status"] == "done"
    listed = {**f, "menu": {"set_battery": ["home-battery"], "set_room_ac": []}}
    assert g.check(call("set_water_heater", target="water-heater", action="hold"), listed)["why"] == "The owner needs hot water."
    g.wishes = []
    assert g.check(call("set_water_heater", target="water-heater", action="hold"), listed)["why"] == \
        "set_water_heater on water-heater isn't on this step's list, so nothing was sent."
    assert g.check(call("set_room_ac", target="all-room-acs", less_comfort_c=1), listed)["why"] == "It isn't running, so there is nothing to ease."   # [] lists every target


def test_a_target_takes_one_call_at_a_time_until_that_call_ends(h1):
    g, f = h1[1].guard, h1[2]
    out = g.check(call("set_battery", target="home-battery", action="discharge", kw=1.5), f)
    assert (out["status"], out["expected_kw"], out["confirm_by"]) == ("done", 1.5, "18:00")
    assert g.check(call("set_battery", "20:00", "21:00", target="home-battery", action="hold"), f)["why"] == "home-battery already runs a call until 21:00."
    assert brief(g.check(call("set_battery", "21:00", "22:00", target="home-battery", action="hold"), f)) == ("done", {"action": "hold", "kw": 0}, 0.0, "")


def test_set_battery_takes_charge_discharge_or_hold_over_0_kw_and_a_charge_stays_out_of_the_sale_and_under_its_limit(h1):
    g, f = h1[1].guard, h1[2]
    assert g.check(call("set_battery", target="home-battery", action="drain", kw=1), f)["why"] == "action must be charge, discharge or hold."
    for kw in (None, 0, -1, float("nan"), True, "lots"):
        out = g.check(call("set_battery", target="home-battery", action="discharge", kw=kw), f)
        assert (out["status"], out["why"], out["try_instead"]) == ("blocked", "A charge or discharge needs more than 0 kW.", HOLD)
    out = g.check(call("set_battery", "17:30", "18:15", target="home-battery", action="charge", kw=2), f)
    assert (out["why"], out["try_instead"]) == ("A charge can't run into the sale window.", HOLD)
    out = g.check(call("set_battery", "16:00", "17:00", target="home-battery", action="charge", kw=7), f)
    assert brief(out) == ("adjusted", {"action": "charge", "kw": 5.0}, -5.0, "Lowered to the charge limit, 5.00 kW.")
    assert brief(g.check(call("set_battery", "17:00", "18:00", target="home-battery", action="charge", kw=3), f)) == ("done", {"action": "charge", "kw": 3.0}, -3.0, "")


def test_a_discharge_keeps_the_owners_reserve_and_a_tripped_battery_takes_no_call(h1):
    node, a, f = h1
    assert f["devices"]["battery"]["can_give_kw"] == 1.71           # (60% - 20% reserve) x 13.5 kWh x 0.95 over the 3 h sale
    out = a.guard.check(call("set_battery", target="home-battery", action="discharge", kw=3), f)
    assert brief(out) == ("adjusted", {"action": "discharge", "kw": 1.71}, 1.71, "Lowered to 1.71 kW, which keeps the owner's reserve.")
    node.adapter.soc = node.adapter.R
    f = facts(node, a)
    assert (f["devices"]["battery"]["can_give_kw"], f["devices"]["battery"]["at_reserve"]) == (0.0, True)
    assert a.guard.check(call("set_battery", target="home-battery", action="discharge", kw=1), f)["why"] == "A discharge would pass the owner's reserve."
    node.adapter.set_battery_fault(True)
    assert a.guard.check(call("set_battery", target="home-battery", action="hold"), facts(node, a))["why"] == "The battery shut off under 10 minutes ago."


def test_the_water_heater_holds_in_the_sale_and_starts_no_load_up_in_it(h1):
    g, f = h1[1].guard, h1[2]
    out = g.check(call("set_water_heater", target="water-heater", action="hold"), f)
    assert brief(out) + (out["confirm_by"],) == ("done", {"action": "hold"}, 1.7, "", "18:00")
    out = g.check(call("set_water_heater", "18:30", "19:00", target="water-heater", action="load_up"), f)
    assert (out["why"], out["try_instead"]) == ("load_up can't run during a sale.", {"tool": "set_water_heater", "target": "water-heater", "action": "hold"})
    assert g.check(call("set_water_heater", "16:00", "17:00", target="water-heater", action="load_up"), f)["why"] == "The tank is already at normal."
    assert g.check(call("set_water_heater", "17:00", "19:00", target="water-heater", action="load_up"), f)["why"] == "load_up can't run during a sale."   # into the sale
    assert g.check(call("set_water_heater", "17:00", "18:00", target="water-heater", action="load_up"), f)["why"] == "The tank is already at normal."  # ends as it starts


def test_room_acs_ease_only_while_running_and_no_further_than_the_homes_limit(h1):
    g, f = h1[1].guard, h1[2]
    ac = call("set_room_ac", target="all-room-acs", less_comfort_c=2.5)
    assert g.check(call("set_room_ac", target="all-room-acs", less_comfort_c="warm"), f)["why"] == "less_comfort_c must be a number."
    assert (f["devices"]["cool"]["mode"], g.check(ac, f)["why"]) == ("heating", "It isn't running, so there is nothing to ease.")
    f["devices"]["cool"].update(running=True, run_kw=2.0)          # 1.5 C x 8 kWh/C held, against 2 kW x COP 2.1 x 3 h: 12 / 12.6 of the 2 kW
    assert brief(g.check(ac, f)) == ("adjusted", {"less_comfort_c": 1.5}, 1.9, "Lowered to this home's limit, 1.50 C.")


def test_a_car_charger_is_limited_only_while_it_charges_and_never_paused_past_what_the_car_can_wait(h1):
    g, f = h1[1].guard, h1[2]
    charger, pause = f["devices"]["charger"], call("limit_ev_charging", target="car-charger", amps=0)
    assert (charger["status"], g.check(pause, f)["why"]) == ("away", "The car reads away, so there is nothing to limit.")
    charger.update(status="charging", charge_kw=7.2, wait_h=2.0, leaves="23:30")              # it can wait 2 h and still be ready: less than the 3 h sale
    assert g.check(pause, f)["why"] == "The car must be ready by 23:30, so it can't wait that long."
    assert g.check(call("limit_ev_charging", target="car-charger", amps=-1), f)["why"] == "amps must be 0, or 6 and up."
    charger["wait_h"] = 3.0                                                                   # it can wait the whole sale
    assert brief(g.check(call("limit_ev_charging", target="car-charger", amps=3), f)) == ("done", {"amps": 6.0}, 5.76, "")      # 3 A rises to 6 A: 7.2 kW - 240 V x 6 A


def test_a_held_machine_still_finishes_by_the_owners_done_by_time(tmp_path):
    _, a, f = home("home-02", tmp_path)
    dryer, g = f["devices"]["dryer"], a.guard
    assert (dryer["status"], dryer["done_by"], dryer["cycle_min"]) == ("waiting", "22:45", 75)
    assert g.check(call("delay_appliance", "18:00", "21:45", target="dryer"), f)["why"] == "It would miss the done-by time, 22:45."     # 21:45 + 75 min
    assert brief(g.check(call("delay_appliance", "18:00", "21:30", target="dryer"), f)) == ("done", {"finish_by": "22:45"}, dryer["can_give_kw"], "")   # 21:30 + 75 min: on time
    for asked, kept in (("23:00", "22:45"), ("00:15", "22:45"), ("9pm", "22:45"), ("22:30", "22:30"), ("21:30", "22:15")):   # 00:15 is after 22:45; 21:30 is before the cycle can end
        g.clear()
        assert g.check(call("delay_appliance", "18:00", "21:00", target="dryer", finish_by=asked), f)["applied"] == {"finish_by": kept}     # 21:00 + 75 min is 22:15


def test_only_an_idle_car_gives_power_and_only_what_keeps_it_ready(tmp_path):
    _, a, f = home("home-02", tmp_path)
    car, g = f["devices"]["car"], a.guard
    assert g.check(call("discharge_car", target="car", kw=3), f)["why"] == "The car reads away."
    car["status"] = "charging"
    out = g.check(call("discharge_car", target="car", kw=3), f)
    assert (out["why"], out["try_instead"]) == ("The car is charging. Pause the charger first.", {"tool": "limit_ev_charging", "target": "car-charger", "amps": 0})
    car.update(status="idle", can_give_kw=2.5, max_kwh=6.0)
    out = g.check(call("discharge_car", target="car", kw=3, max_kwh=10), f)
    assert brief(out) == ("adjusted", {"kw": 2.5, "max_kwh": 6.0}, 2.5, "Lowered to what the car can give and still be ready.")


def test_the_building_guard_refuses_a_missing_tool_a_never_touched_or_unknown_target_and_bad_times(office):
    g, f = office
    lights = {"target": "office-lights", "cut_percent": 30}
    assert g.check(call("set_battery", target="site-battery", action="hold"), f)["why"] == "This node has no set_battery."
    assert g.check(call("dim_lights", target="stair-lights", cut_percent=30), f)["why"] == "stair-lights is on the never-touched list."
    out = g.check(call("dim_lights", target="lobby-lights", cut_percent=30), f)
    assert (out["why"], out["try_instead"]) == ("lobby-lights can't take this call now.", {"tool": "dim_lights", "target": "office-lights"})
    assert g.check({**call("dim_lights", **lights), "start": "6pm"}, f)["why"] == "start and end must be local HH:MM."
    out = g.check({**call("dim_lights", **lights), "end": ""}, f)
    assert (out["why"], out["try_instead"]) == ("Every write needs a start and an end.", {"tool": "dim_lights", **lights, "start": "18:00", "end": "21:00"})
    assert g.check(call("dim_lights", "20:00", "19:00", **lights), f)["why"] == "end must come after start."
    assert g.check({**call("dim_lights", **lights), "end": "2025-01-29 18:15"}, f)["why"] == "A write ends by itself within a day."


def test_a_managers_wish_and_the_steps_list_stop_building_calls_but_a_writer_may_give_its_call_back(office):
    g, f = office
    g.wishes = [{"wish": "keep_house_as_is"}, {"wish": "keep_lights_on"}]
    assert g.kept() == {"set_thermostat", "set_room_ac", "dim_lights"} | CLIMATE
    assert g.check(call("dim_lights", target="office-lights", cut_percent=30), f)["why"] == "The manager needs the lights kept up."
    assert g.check(call("limit_air_handler", target="office-air-handlers", speed_percent=80), f)["why"] == "The owner asked for this to stay as it is."
    g.wishes, plugs = [], {"target": "free-floors-plugs"}
    assert brief(g.check(call("switch_plugs", state="off", **plugs), f))[:2] == ("done", {"state": "off", "start": "18:00", "end": "21:00"})
    listed = {**f, "menu": {"dim_lights": ["office-lights"]}}
    assert g.check(call("switch_plugs", "19:00", "21:00", state="off", **plugs), listed)["why"] == \
        "switch_plugs on free-floors-plugs isn't on this step's list, so nothing was sent."
    out = g.check(call("switch_plugs", "19:00", "21:00", state="auto", **plugs), listed)
    assert (out["status"], out["applied"], out["confirm_by"]) == ("done", {"state": "auto", "start": "19:00", "end": "21:00"}, "19:05")


def test_a_building_call_waits_for_an_earlier_call_on_a_shared_point_and_needs_every_reading(office):
    g, f = office
    out = g.check(call("dim_lights", "18:00", "20:00", target="office-lights", cut_percent=30), f)
    assert (out["status"], out["expected_kw"], out["confirm_by"]) == ("done", 1.71, "18:35")     # 6.33 kW of lights x 0.90 free-room scale x 30%
    out = g.check(call("dim_lights", "19:00", "21:00", target="low-floors-lights", cut_percent=30), f)
    assert out["why"] == "An earlier call here runs until 20:00, and the later call wins only after it ends."
    assert out["try_instead"] == {"tool": "dim_lights", "target": "low-floors-lights", "cut_percent": 30, "start": "20:00", "end": "21:00"}
    del f["devices"]["dim_lights:high-floors-lights"]["running"]
    assert g.check(call("dim_lights", "20:00", "21:00", target="high-floors-lights", cut_percent=30), f)["why"] == \
        "A reading this call needs is missing ('running'), so nothing was sent."


def test_only_gate_run_makes_a_ticket_and_a_driver_takes_only_a_fresh_ticket_from_its_own_gate(h1):
    f, c = h1[2], call("set_battery", target="home-battery", action="discharge", kw=1.5)
    assert sorted(n for n in dir(D.Gate) if not n.startswith("_")) == ["release_all", "run"]
    (g, drv), (other, theirs) = gate(), gate()
    cmd = D.Command("home-01", "set_battery", "charge_discharge", "home-battery", {"action": "discharge", "kw": 1.5}, c["start"], c["end"])
    made = D.Ticket(cmd, c, answer("done", "home-battery", {"action": "discharge", "kw": 1.5}, 1.5), "00" * 8, "0" * 64)
    assert drv.send(made) == drv.send(cmd) == D.SimulatedDriver(write=broken).send(made) == NO_SEAL
    with pytest.raises(RuntimeError, match="this driver already has a gate"):
        D.Gate("home-01", Guard(), drv)
    assert other.run(c, f)["status"] == g.run(c, f)["status"] == "done"
    t = drv.tickets[-1]
    assert g.last["seal"] == {"nonce": t.nonce, "seal": t.seal[:16]} and {x["file"] for x in g.last["guard_lines"]} == {"guard.py"}
    for bad in (t, theirs.tickets[0], dataclasses.replace(t, nonce="ab" * 8), dataclasses.replace(t, seal="0" * 64)):
        assert drv.send(bad) == NO_SEAL
    assert drv.sent == theirs.sent == [cmd]


def test_the_seal_covers_what_the_guard_applied_and_a_refused_call_reaches_no_driver(h1):
    (g, drv), f = gate(hold=True), h1[2]
    assert g.run(call("set_battery", target="home-battery", action="drain"), f)["why"] == "action must be charge, discharge or hold." and drv.tickets == []
    assert g.run(call("set_battery", target="home-battery", action="discharge", kw=3), f)["status"] == "adjusted"
    t, send = drv.tickets[0], lambda x: D.SimulatedDriver.send(drv, x)        # the gate's own ticket, unsent: its nonce is still fresh
    assert t.command.values == {"action": "discharge", "kw": 1.71}             # what the guard applied, not the 3 kW asked
    for bad in (dataclasses.replace(t, command=dataclasses.replace(t.command, values={"action": "discharge", "kw": 3})),
                dataclasses.replace(t, call={**t.call, "end": f"{DAY} 23:00"}), dataclasses.replace(t, answer={**t.answer, "expected_kw": 3.0})):
        assert send(bad) == NO_SEAL                                            # one thing changed, and the seal no longer fits
    assert (send(t), send(t), drv.sent) == (DONE, NO_SEAL, [t.command])


def test_a_guard_that_raises_sends_nothing_and_forgets_the_point_it_took(h1):
    f, guard = h1[2], Guard()
    bad = {**call("set_battery", target="home-battery", action="discharge", kw=1.5), "start": 1080}      # the guard takes the point, then can't read the start
    g, drv = gate(guard)
    out = g.run(bad, f)
    assert (out["status"], out["target"], out["why"]) == ("blocked", "home-battery", "The guard couldn't check this (TypeError), so nothing was sent.")
    assert (drv.tickets, drv.sent, guard.writers) == ([], [], {})
    with pytest.raises(TypeError):
        guard.check(bad, f)
    assert list(guard.writers) == ["home-battery"]


def test_a_driver_that_fails_answers_failed_and_the_guard_gets_its_point_back(h1):
    class Unplugged(D.Driver):
        _write = broken
    f, c = h1[2], call("set_battery", target="home-battery", action="discharge", kw=3)
    for driver in (D.SimulatedDriver(write=broken), Unplugged()):
        guard = Guard()
        out = D.Gate("home-01", guard, driver).run(c, f)
        assert brief(out) + (out["confirm_by"], out["try_instead"]) == ("failed", {}, 0.0, "The device didn't take it: RuntimeError.", "", {})
        assert guard.writers == {} and guard.check(c, f)["status"] == "adjusted"


def test_a_building_gate_keeps_its_guards_lines_and_a_standby_write_the_device_refused_does_not_use_up_the_days_writes(office):
    g, f = office
    f["devices"]["set_zone_standby:office-free-floors-zones"]["write_limit"] = 2           # a box that stores each write: one on and off a day
    standby, ok = call("set_zone_standby", target="office-free-floors-zones", mode="on"), D.Gate("building-01", g, D.SimulatedDriver(write=lambda c, a: None))
    assert ok.run({**standby, "start": "2025-01-27 18:00", "end": "2025-01-27 21:00"}, f)["status"] == "done"
    assert {(x["file"], x["fn"]) for x in ok.last["guard_lines"]} >= {("guard_building.py", "check"), ("guard_building_tools.py", "_set_zone_standby")}
    g.clear()                                                                                # the next day's sale opens
    assert D.Gate("building-01", g, D.SimulatedDriver(write=broken)).run(standby, f)["status"] == "failed"
    assert ok.run(standby, f)["status"] == "done"


def test_the_real_drivers_refuse_every_write_and_the_guard_forgets_each_one():
    for side, protocols in {"home": ("Home Assistant", "OCPP", "Matter"), "building": ("Modbus", "OCPP", "BACnet")}.items():
        guard = Passes()
        g = D.Gate(side, guard, D.make(side, "real", P.group_of))
        outs = [g.run(call(tool, target="x"), {}) for tool in D.KIND]
        assert {o["status"] for o in outs} == {"blocked"} and guard.writers == {}
        assert {o["why"] for o in outs} == {f"{p} driver isn't connected, so nothing was sent to x." for p in protocols} | {"No driver is set up for x."}
    drv = D.make("home", "real", P.group_of)
    assert drv.read("home-battery") == {"status": "blocked", "why": "No real driver is connected, so home-battery can't be read."}
    assert drv.set_limit("energy_storage", "reserve_pct", 30.0) == {"status": "blocked", "why": "Home Assistant driver isn't connected, so nothing was sent to energy_storage."}
    with pytest.raises(ValueError, match="no driver mode 'remote'"):
        D.make("home", "remote", P.group_of)


def test_release_all_ends_every_limit_and_frees_every_point_even_when_the_release_breaks(h1):
    f, c, released = h1[2], call("set_water_heater", target="water-heater", action="hold"), []
    g, _ = gate(release=released.append)
    assert g.run(c, f)["status"] == "done" and list(g.guard.writers) == ["water-heater"]
    assert (g.release_all(), released, g.guard.writers) == (DONE, [None], {})
    g, _ = gate(release=broken)
    assert g.run(c, f)["status"] == "done"
    assert (g.release_all(), g.guard.writers) == ({"status": "failed", "why": "The release didn't go through: RuntimeError."}, {})


def test_release_all_on_a_homes_own_gate_closes_its_levers_and_takes_the_node_out_of_the_sale(h1):
    node, a, f = h1
    g = a.ctx.gate
    assert g.guard is a.guard and type(g.driver) is D.SimulatedDriver
    a.open()
    assert g.run(call("set_battery", target="home-battery", action="discharge", kw=1.5), f)["status"] == "done"
    assert (node.adapter.levers["battery_kw"], list(a.guard.writers)) == (1.5, ["home-battery"])
    assert g.release_all() == DONE and (node.adapter.levers, a.guard.writers) == (None, {})
    f = facts(node, a)
    assert f["stopped"] and a.guard.check(call("set_water_heater", target="water-heater", action="hold"), f)["why"] == STOPPED

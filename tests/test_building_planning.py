"""Building planning by code on the office fixture: the member the host builds, its zone map and schedules, its view of zones and plant at a
winter sale, its evening offer and what the facility manager's policy, a manager's wish and a zone event take out of it, the comfort its zone
calls let the plan reach, and the thermal mass behind them."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from murmur import config
from murmur.agents.building import BuildingHost
from murmur.node import buildings, control, surprises
from murmur.node import tools as T
from murmur.node.building_agent import BuildingAgent, open_levers
from murmur.node.building_levers import apply_call, sync_comfort
from murmur.node.offer_rule import BuildingRule
from murmur.node.report_rule import QuietNode
from murmur.node.see_building import comfort_c, rise_allowed, see_building
from murmur.node.simulator_building import SimulatedBuilding
from murmur.protocol import envelope as beckn
from tests.world import EVENING, building_rule

DAY = "2025-01-28"
AFTER_HOURS = (f"{DAY} 19:00", f"{DAY} 21:00")          # every floor free
LAST_HOURS = (f"{DAY} 17:00", f"{DAY} 19:00")           # three floors 80 % booked, the vacant floors closed
BOOKED_FREE = {"low": 0.2, "mid": 0.2, "high": 0.2, "vacant": 1.0}
SHELF = T.building_shelf("office")


@pytest.fixture(autouse=True)
def zone_map(monkeypatch):
    """The office's zone map with a surprise list of the test's own: none comes in from another test, and none goes out to one."""
    zm = buildings.load("building-01")
    monkeypatch.setattr(zm, "surprises", [])
    return zm


def stand_in_host(folder):
    """What BuildingHost's own make_node and make_mind read off their host, with the keys in this test's folder."""
    folder.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(cfg=dict(EVENING), keydir=folder, trusted=lambda: [], _logger=lambda name: (lambda *a, **k: None), homes={})


def building(folder, at):
    """The fixture's building member, made by BuildingHost.make_node, its clock held at `at`."""
    host = stand_in_host(folder)
    node = BuildingHost.make_node(host, BuildingHost.roster(host)[0], lambda *a: None)
    node.replay.configure(at, 60, 0, hold=True)
    return node


def member(folder, at=f"{DAY} 12:00", policy=None):
    """The building member with the facility manager's rule over a policy file in its own folder."""
    node = building(folder, at)
    if policy is not None:
        (folder / "policy.json").write_text(json.dumps(policy))
    node.brain = building_rule(node, folder)
    return node


def offer(node, window):
    """The member's offer to a call for offers over this window at $0.40 per kWh, one slot per half hour."""
    start, end = window
    slots = [{"id": k, "start": beckn.add_minutes(start, 30 * k), "kw_requested": 50.0, "price": 0.4, "penalty": 0.0}
             for k in range(int(node.replay.minutes_between(start, end) // 30))]
    need = {"event_id": "sale-1", "window_start": start, "window_end": end, "slots": slots, "commit_by": f"{DAY} 14:00"}
    return node.build_offer(need, node.forecast_window(need))


def sale(window):
    """A sale running over this window with 2 kW owed, as the agent's view reads it."""
    return {"start": window[0], "end": window[1], "owed_kw": 2.0}


# ------------------------------------------------------------------------------------------------ the member and its map
def test_the_host_builds_the_office_from_its_file_as_a_quiet_member_with_the_managers_rule_and_an_agent(tmp_path):
    host = stand_in_host(tmp_path)
    assert [b["name"] for b in BuildingHost.roster(host)] == ["building-01"]
    node = BuildingHost.make_node(host, BuildingHost.roster(host)[0], lambda *a: None)
    sim = node.adapter
    assert isinstance(node, QuietNode) and isinstance(sim, SimulatedBuilding) and node.is_building
    assert (sim.E, sim.P, sim.has_ev, sim.light_default, sim.sell) == (0.0, 0.0, False, 0.5, {"fans": 0.5, "plugs": 0.2})
    assert (sim.ctl.limits.max_rise_c, sim.ctl.limits.max_rise_away_c, sim.ctl.limits.precool_c) == (1.5, 2.775, 1.0)
    assert sorted(sim.app) == ["fans", "plugs"]
    host.homes[node.name] = node
    rule = BuildingHost.make_mind(host, node.name)
    assert isinstance(rule, BuildingRule) and rule.v2 is node and rule.wishes.path == config.state_dir() / "building-01_policy.json"
    agent = BuildingHost.agent_class()(node, rule)
    assert isinstance(agent, BuildingAgent) and node.agent is agent and agent.zm is buildings.load("office") and agent.shelf == SHELF
    assert agent.limits_now() == {"max_rise_c": 1.5, "max_rise_away_c": 2.775, "lights": 0.5}


def test_a_building_node_finds_its_zone_map_by_its_own_name_or_its_dataset_profile():
    assert buildings.map_key("building-01") == "office"                  # its profile in buildings.json is buildings/office
    assert buildings.map_key("office") == "office" and buildings.map_key("shopping_center") == "shopping_center"
    assert buildings.map_key("home-01") is None and not buildings.known("home-01") and buildings.known("building-01")
    assert buildings.load("building-01") is buildings.load("office")
    with pytest.raises(KeyError):
        buildings.load("home-01")


def test_zone_schedules_read_the_datasets_own_days_and_an_hour_with_no_record_counts_as_in_use(zone_map):
    assert [zone_map.plan(s, f"{DAY} 18:45") for s in ("low", "mid", "high", "vacant")] == pytest.approx([0.8, 0.8, 0.8, 0.0])
    assert [zone_map.state(s, t) for s, t in (("low", f"{DAY} 07:00"), ("low", f"{DAY} 19:00"), ("vacant", f"{DAY} 12:00"))] == ["booked", "free", "free"]
    assert zone_map.plan("low", "2024-06-01 12:00") == 1.0 and zone_map.state("low", "2024-06-01 12:00") == "booked"


def test_sensors_far_above_the_plan_read_as_an_event_that_lasts_and_a_small_miss_counts_only_this_hour(zone_map):
    now, steps = AFTER_HOURS[0], [beckn.add_minutes(AFTER_HOURS[0], 15 * k) for k in range(8)]
    zone_map.surprises.append({"from": now, "to": AFTER_HOURS[1], "space": "low", "share": 0.1})
    assert (zone_map.true("low", now), zone_map.true("mid", now)) == (0.1, 0.0)
    assert zone_map.use("low", now, steps) == pytest.approx(0.1 * 4 / 8)          # 0.1 is noise: the four 19:xx steps read it, 20:xx the plan
    zone_map.surprises[0]["share"] = 0.5
    assert zone_map.use("low", now, steps) == pytest.approx(0.5)


# ------------------------------------------------------------------------------------------------ what the building sees
def test_the_view_lists_every_zone_and_the_plant_with_the_numbers_of_a_winter_office_afternoon(tmp_path, zone_map):
    f = see_building(building(tmp_path, f"{DAY} 16:00").adapter, f"{DAY} 16:00", sale(LAST_HOURS), SHELF, zone_map, 2.0)
    dev = f["devices"]
    zones = {d["target"]: d for d in dev.values() if d["tool"] == "set_zone_cooling"}
    assert {d["tool"] for d in dev.values()} == set(SHELF) and len(zones) == 5
    assert f["free"] == pytest.approx(BOOKED_FREE)
    assert [zones[t]["state"] for t in ("office-zones", "low-floors-zones", "vacant-floors-zones")] == ["part", "part", "free"]
    assert zones["office-zones"]["free_share"] == 0.296 and zones["low-floors-zones"]["cap"] == pytest.approx(31.3 * 0.32)
    assert f["cool_kw"] == 0.0 and not any(d["show"] or d["can_give_kw"] for d in zones.values())      # heat leads: no cooling to ease
    plant = dev["set_plant_demand_limit:office-plant"]
    assert (plant["percent_now"], plant["floor_percent"], plant["can_give_kw"], plant["show"]) == (0.0, 70, 0.0, False)
    assert dev["stop_plant_early:office-plant"]["normal_off"] == "21:00" and not dev["stop_plant_early:office-plant"]["show"]
    scale = 0.296 / 0.85                                              # the sale counts free rooms against the 85 % it assumed
    lights = dev["dim_lights:office-lights"]
    assert (lights["running_kw"], lights["limit_pct"]) == (8.4, 50.0) and lights["scale"] == pytest.approx(scale)
    assert lights["can_give_kw"] == 1.46                               # 8.4 kW x 0.348 x 50 %, down to the cent
    assert dev["limit_air_handler:office-air-handlers"]["can_give_kw"] == 1.04       # 6 kW of fans x 0.348 x (1 - (73/92)^3)
    assert dev["switch_plugs:free-floors-plugs"]["can_give_kw"] == 0.2                # 3 kW of plugs x the 0.2 sold x 0.348


# ------------------------------------------------------------------------------------------------ the offer
def test_the_after_hours_offer_is_the_dimmable_lighting_and_is_the_same_on_two_builds(tmp_path):
    a, b = (offer(member(tmp_path / k), AFTER_HOURS) for k in "ab")
    assert a == b
    assert (a["lighting"]["raw_kw"], a["lighting"]["kw"]) == (2.65, 2.517)          # 5.3 kW on x the half that may dim, x 0.95
    assert [s["kw_offered"] for s in a["slots"]] == [2.52] * 4 and a["energy_kwh"] == 5.04
    assert a["air_conditioning"]["kw"] == 0.0 and a["evening"] is None and a["node"] == "building"
    assert [(s["firm_kw"], s["tentative_kw"]) for s in a["slots"]] == [(1.346, 1.174)] * 4       # a building's firm share, 0.534


def test_in_office_hours_only_free_rooms_and_the_closed_floors_dim_so_a_longer_window_offers_less(tmp_path):
    node = member(tmp_path)
    assert node.adapter.free_scale(f"{DAY} 18:45") == pytest.approx(0.296 / 0.85)      # 0.88 of the lights 20 % free, 0.12 closed
    assert node.adapter.free_scale(f"{DAY} 19:00") == 1.0
    o = offer(node, (LAST_HOURS[0], AFTER_HOURS[1]))
    assert o["lighting"]["raw_kw"] == round(8.4 * 0.5 * 0.296 / 0.85, 3)            # the window's lowest step sets one even offer
    assert [s["kw_offered"] for s in o["slots"]] == [1.39] * 8


def test_the_managers_policy_shares_cut_the_lighting_offer_by_the_kw_the_lights_lose(tmp_path):
    node = member(tmp_path, policy={"lighting_max_share": 0.5, "cooling_max_share": 0.3, "devices_off": ["plugs"]})
    o = offer(node, AFTER_HOURS)
    assert [s["kw_offered"] for s in node.brain.safe["sale-1"]["slots"]] == [2.52] * 4
    assert [(s["light_kw"], s["kw_offered"]) for s in o["slots"]] == [(1.26, 1.26)] * 4      # 2.517 x 0.5; 2.52 - (2.517 - 1.26)
    assert o["energy_kwh"] == 2.52 and (o["lighting"]["agent_share"], o["air_conditioning"]["agent_share"]) == (0.5, 0.3)
    d = node.brain.decisions.list()[-1]
    assert (d["node"], d["lighting_kw"], d["cooling_kw"], d["if_delivered_usd"]) == ("building", [1.26] * 4, [0.0] * 4, 1.01)
    assert d["devices_off"] == ["plugs"] and node.adapter.dev_off == {"plugs"}


@pytest.mark.parametrize("policy, why", [({"skip_days": [DAY]}, f"the facility manager asked to skip {DAY}"),
                                         ({"min_price_usd_per_kwh": 0.5}, "the price $0.40/kWh is below the facility manager's minimum $0.50")])
def test_a_policy_day_off_or_a_price_floor_above_the_sale_offers_nothing_and_says_why(tmp_path, policy, why):
    o = offer(member(tmp_path, policy=policy), AFTER_HOURS)
    assert [s["kw_offered"] for s in o["slots"]] == [0.0] * 4 and o["energy_kwh"] == 0.0
    assert (o["agent"]["take_part"], o["agent"]["reason"]) == (False, why)


def test_a_managers_wish_to_keep_the_lights_on_takes_the_lighting_out_of_the_offer(tmp_path):
    node = member(tmp_path)
    BuildingAgent(node, node.brain).guard.wishes = [{"wish": "keep_lights_on", "from": f"{DAY} 11:00"}]
    o = offer(node, AFTER_HOURS)
    assert [(s["light_kw"], s["kw_offered"]) for s in o["slots"]] == [(0.0, 0.0)] * 4
    assert o["kept_out"]["parts"] == ["lighting"] and [s["kw_offered"] for s in node.before_note["sale-1"]["slots"]] == [2.52] * 4


def test_a_managers_lower_lights_limit_holds_at_once_and_a_clear_goes_back_to_it(tmp_path):
    node = member(tmp_path)
    node.adapter.rt_override("lights", 0.5)                                            # what the door left
    control.write_limit(node.adapter, "lighting_and_shading", "light_dim_max", 0.3)    # the manager's own limit, lower
    assert node.adapter.light_limit() == 0.3
    node.adapter.rt_override("clear")
    assert node.adapter.light_limit() == 0.3 and [s["kw_offered"] for s in offer(node, AFTER_HOURS)["slots"]] == [1.51] * 4      # 5.3 kW x 0.3 x 0.95


# ------------------------------------------------------------------------------------------------ comfort
def test_rooms_with_no_booking_take_the_offset_and_booked_rooms_at_most_1_5_c():
    assert (rise_allowed(1.0, 3.0), rise_allowed(0.0, 3.0), rise_allowed(1.0, 5.0), rise_allowed(0.5, 1.0)) == (3.0, 1.5, 3.0, 1.0)
    assert rise_allowed(0.2, 3.0) == pytest.approx(0.2 * 3.0 + 0.8 * 1.5)


def test_the_building_may_rise_by_its_eased_zones_each_weighted_by_its_cooling_share(zone_map):
    assert comfort_c(zone_map, {"low": 3.0, "vacant": 3.0}, BOOKED_FREE) == pytest.approx(0.32 * 1.8 + 0.12 * 3.0)
    assert comfort_c(zone_map, {"low": 3.0, "mid": 0.0}, BOOKED_FREE) == pytest.approx(0.32 * 1.8)         # a zone at +0 C isn't eased
    assert comfort_c(zone_map, {}, BOOKED_FREE) == 0.0


def test_zone_calls_let_the_plan_rise_only_as_far_as_their_rooms_allow_and_never_past_a_persons_limit(tmp_path, zone_map):
    sim = building(tmp_path, f"{DAY} 16:00").adapter
    sim.x = -0.4                                                      # pre-cooled: the plan may hold that, and cool no further
    open_levers(sim)
    assert sim.overrides["comfort"] == {"max_rise_c": 0.0, "max_rise_away_c": 0.0, "precool_c": 0.4}
    f = see_building(sim, f"{DAY} 16:00", sale(LAST_HOURS), SHELF, zone_map, 2.0)

    def call(target):
        apply_call(sim, zone_map, {"tool": "set_zone_cooling", "start": f"{DAY} 16:30", "end": LAST_HOURS[1]},
                   {"applied": {"offset_c": 3.0}, "expected_kw": 0.0, "target": target}, f["devices"][f"set_zone_cooling:{target}"], f)
        return sim.overrides["comfort"]

    assert call("low-floors-zones") == pytest.approx({"max_rise_c": 0.32 * 1.8, "max_rise_away_c": 0.32 * 1.8, "precool_c": 0.4})
    rise = 0.88 * 1.8 + 0.12 * 3.0                                    # three floors 20 % free, the closed floors wholly free
    assert call("office-zones")["max_rise_c"] == pytest.approx(rise) and sim.levers["zones"] == dict.fromkeys(zone_map.spaces, 3.0)
    sim.rt_override("comfort", {"max_rise_c": 1.0})
    sync_comfort(sim, zone_map, f["free"])
    assert sim.overrides["comfort"] == pytest.approx({"max_rise_c": 1.0, "max_rise_away_c": rise, "precool_c": 0.4})


def test_a_stopped_plant_lets_every_zone_coast_as_far_as_its_rooms_allow(tmp_path, zone_map):
    sim = building(tmp_path, f"{DAY} 16:00").adapter
    open_levers(sim)
    sim.levers["zones"]["low"] = 1.0
    assert sync_comfort(sim, zone_map, BOOKED_FREE) == pytest.approx(0.32 * 1.0)
    sim.levers["plants"]["office-plant"] = {"kw": 0.0, "stop": True}
    assert sync_comfort(sim, zone_map, BOOKED_FREE) == pytest.approx(0.88 * 1.8 + 0.12 * 3.0)


# ------------------------------------------------------------------------------------------------ a zone event
def test_a_zone_event_fills_the_largest_zone_and_its_share_of_lights_fans_plugs_and_comfort_leaves_the_sale(tmp_path, zone_map):
    node = member(tmp_path, at=f"{DAY} 18:00")
    sim = node.adapter
    out = surprises.zone_event(node, f"{DAY} 18:00", share=0.25, hours=3.5)
    assert out["zone_event"] == {"from": f"{DAY} 18:00", "to": f"{DAY} 21:30", "share": 0.25, "space": "low"}     # low and mid tie: the first
    assert zone_map.surprises == [{"from": f"{DAY} 18:00", "to": f"{DAY} 21:30", "space": "low", "share": 1.0}]
    assert sim.light_limit() == 0.375 and sim.sell == pytest.approx({"fans": 0.375, "plugs": 0.15})
    assert sim.overrides["comfort_limit"] == pytest.approx({"max_rise_c": 1.5 * 0.75, "max_rise_away_c": 2.775 * 0.75})
    assert [s["kw_offered"] for s in offer(node, AFTER_HOURS)["slots"]] == [1.89] * 4          # 5.3 kW x 0.375 x 0.95, not 2.52
    node.replay.configure(AFTER_HOURS[0], 60, 0, hold=True)
    f = see_building(sim, AFTER_HOURS[0], sale(AFTER_HOURS), SHELF, zone_map, 2.0)
    assert f["free"] == {"low": 0.0, "mid": 1.0, "high": 1.0, "vacant": 1.0}
    assert f["devices"]["set_zone_cooling:low-floors-zones"]["state"] == "booked" and f["devices"]["dim_lights:low-floors-lights"]["can_give_kw"] == 0.0
    lights = f["devices"]["dim_lights:office-lights"]
    assert (lights["limit_pct"], lights["can_give_kw"]) == (37.5, 1.59)                 # 5.3 kW x 37.5 % x 0.8: 0.68 of the lights free, over the 0.85 assumed
    assert f["lowered_why"] == "An event was added in a sold zone."


# ------------------------------------------------------------------------------------------------ the thermal mass
def test_the_buildings_mass_runs_on_its_file_constants_and_keeps_its_stored_cold(tmp_path):
    h = building(tmp_path, f"{DAY} 12:00").adapter.house
    assert (h.ua, h.cap, h.qmax, h.sign(f"{DAY} 18:00")) == (3.3, 31.3, 117.7, -1)       # the fixture's winter: heat leads
    a = math.exp(-0.25 / (31.3 / 3.3))
    assert h.step(1.0, 0.0, 0.25) == pytest.approx(a)                                     # left alone, it drifts back to its own day
    h.at = lambda ts: (10.0, 3.0, 22.8, 1)        # a day it cools, 30 kW of heat away: a home's thermostat would cut that to spend a pre-cool's cold
    assert h.thermostat(-0.5, f"{DAY} 18:00", 0.25) == 0.0                                # the building's keeps it
    assert h.thermostat(0.5, f"{DAY} 18:00", 0.25) == pytest.approx(3.3 * a * 0.5 / (1 - a))
    assert (h.light_kw(f"{DAY} 18:45"), h.light_kw(f"{DAY} 19:00")) == (8.4, 5.3)
    h.cut, h.cut_span = 0.5, LAST_HOURS
    assert h.cutting(f"{DAY} 18:45") and not h.cutting(f"{DAY} 19:00")                 # a plant cap holds only the steps it was called for

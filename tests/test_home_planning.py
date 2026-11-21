"""Home planning by code on the fixture homes: the safe offer for an evening sale and what bounds it (the battery's reserve and power, the car,
the owner's comfort limits, battery share, car pause, days off and device wishes), the arithmetic that shapes an offer, the controller's plan inside
its limits, and the commitment, delivery and readings that follow what the buyer took."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from murmur import config
from murmur.agents.home import HomeNodes
from murmur.node import control, grounds
from murmur.node.calls import commitment_request, offer_request
from murmur.node.control import RECOVER_C_PER_H, Limits, Problem, capacity, solve
from murmur.node.offer_shape import DEFAULT_WISHES, Decisions, Wishes, drop_devices, held_back, kw_of, mean_kw, scale_offer
from murmur.protocol import envelope as beckn
from murmur.protocol import signing
from tests import world

DAY, NOW, W0, W1 = "2025-01-28", "2025-01-28 10:00", "2025-01-28 18:00", "2025-01-28 21:00"
SAFE = {"event_id": "ev-1", "energy_kwh": 3.5,
        "slots": [{"id": 0, "kw_offered": 4.0, "battery_kw": 2.0, "ev_pause_kw": 1.0, "app_kw": 1.0},
                  {"id": 1, "kw_offered": 3.0, "battery_kw": 2.0, "ev_pause_kw": 0.0, "app_kw": 1.0}],
        "appliances": {"kw": 1.0, "mean_kw": 1.2, "by_device": {"hpwh": 0.75, "dryer": 0.25}},
        "evening": {"import_cf_kw": [1.0], "import_noev_kw": [0.5], "rebound_kw": {"0.25": [0.4], "0.5": [1.0], "0.75": [1.6], "1.0": [2.0]}},
        "ev_flex": {"kwh": 5.0, "max_kw": 7.2, "latest_finish": "2025-01-29 07:00", "arrival": "2025-01-28 18:30"}}


def need(n: int = 6, price: float = 0.5) -> dict:
    """The buyer's sale: n half hours from 18:00 at 3 kW each, offers due by noon."""
    slots = [{"id": k, "start": beckn.add_minutes(W0, 30 * k), "kw_requested": 3.0, "price": price, "penalty": 0.0} for k in range(n)]
    return {"event_id": "ev-1", "window_start": W0, "window_end": beckn.add_minutes(W0, 30 * n), "slots": slots, "commit_by": f"{DAY} 12:00"}


def built(folder, name: str = "home-01", wishes: dict | None = None):
    """(node, what it sent) for a fixture home with the owner's wishes on file and its clock held at 10:00 on the day of the sale."""
    folder.mkdir(parents=True, exist_ok=True)
    if wishes is not None:
        (folder / f"{name}_wishes.json").write_text(json.dumps(wishes))
    node, sent = world.home(name, folder, replay_start=NOW)
    node.replay.configure(NOW, 60, 0, hold=True)
    return node, sent


def offered(node) -> tuple[dict, dict]:
    """(the forecast, the offer) of a home for the sale."""
    nd = need()
    fc = node.forecast_window(nd)
    return fc, node.build_offer(nd, fc)


def tick_at(node, ts: str) -> None:
    node.replay.configure(ts, 60, 0, hold=True)
    node.tick()


def contract(nd: dict, kw: list[float], cid: str = "ev-1:home-01") -> dict:
    """The community's commitment for the sale, in the shape the clearing writes it."""
    return {"id": cid, "event_id": nd["event_id"], "home": "home-01", "window_start": nd["window_start"], "window_end": nd["window_end"],
            "commitments": [{"id": s["id"], "start": s["start"], "kw": k} for s, k in zip(nd["slots"], kw)], "price_usd_per_kwh": 0.5,
            "opt_out_by": nd["commit_by"], "ev_resume_after": nd["window_end"], "precharge_minutes": 120}


def owner_limits(**said: float) -> Limits:
    """home-01's comfort limits on file (owners.json), with what a person said on top."""
    o = json.loads(config.data_path("owners.json").read_text())["homes"]["home-01"]
    return Limits(**{**{k: o[k] for k in ("max_rise_c", "max_rise_away_c", "precool_c")}, **said})


def problem(P: float = 3.0, E: float = 10.0, cool: float = 0.0, limits: Limits | None = None, owed: float = 1.0) -> Problem:
    """Three hours of a home drawing 2 kW with someone in, `owed` kW owed in its second hour, its battery half full. cool: kW of cooling
    inside the load (COP 3), in a house of 0.45 kW/C and 8 kWh/C."""
    K = 12
    target = [owed if 4 <= k < 8 else 0.0 for k in range(K)]
    return Problem(ts=[beckn.add_minutes("2025-07-01 17:00", 15 * k) for k in range(K)], dt=[0.25] * K, pv=[0.0] * K, load=[2.0] * K,
                   cool=[cool] * K, cop=[3.0] * K, occ=[1] * K, ref=[2.0] * K, target=target, watch=[t == 0 for t in target], soc=0.5,
                   E=E, P=P, R=0.2, SM=1.0, eta=0.95, ua=0.45 if cool else 0.0, cap=8.0, qmax=8.0 if cool else 0.0, limits=limits or owner_limits())


# ---------------------------------------------------------------------------------------------------- the safe offer of a fixture home
def test_two_identical_builds_make_the_same_offer_and_send_the_same_amounts(tmp_path):
    homes = [built(tmp_path / x) for x in ("a", "b")]
    offers = [offered(node)[1] for node, _ in homes]
    assert signing.canonical(offers[0]) == signing.canonical(offers[1])
    assert [s["id"] for s in offers[0]["slots"]] == [0, 1, 2, 3, 4, 5]
    assert offers[0]["energy_kwh"] == round(sum(kw_of(offers[0])) * 0.5, 2) > 0
    for (node, _), offer in zip(homes, offers):
        node.send_offer("txn-1", offer)
    assert signing.canonical(homes[0][1][-1][2]["message"]) == signing.canonical(homes[1][1][-1][2]["message"])


@pytest.mark.parametrize("reserve_pct, usable_kwh", [(None, 10.26), (50.0, 6.41)])
def test_the_battery_part_spends_exactly_the_energy_above_the_owners_reserve(tmp_path, reserve_pct, usable_kwh):
    node, _ = built(tmp_path)
    if reserve_pct is not None:                               # the owner's new reserve reaches the home's battery
        control.write_limit(node.adapter, "energy_storage", "reserve_pct", reserve_pct)
    fc, offer = offered(node)
    own_job = sum(min(5.0, max(0.0, s["load_p50"] - s["pv_p50"])) * 0.25 for s in fc["steps"])     # the battery covers the house first
    assert offer["battery"]["usable_kwh"] == usable_kwh       # (100 % - reserve) x 13.5 kWh x 0.95
    assert sum(s["battery_kw"] for s in offer["slots"]) * 0.5 + own_job == pytest.approx(usable_kwh, abs=0.02)


def test_each_slot_is_its_parts_and_never_more_than_the_battery_and_the_car_can_give(tmp_path):
    node, _ = built(tmp_path)
    fc, offer = offered(node)
    car = {s["id"]: 0.0 for s in offer["slots"]}
    for st in fc["steps"]:
        car[st["slot_id"]] += st["ev_kw"] / 2                 # the car's forecast charging, per half hour
    assert fc["ev"]["arrival"] == "2025-01-28 18:30" and offer["slots"][0]["ev_pause_kw"] == 0.0      # no car to pause before it comes
    for s in offer["slots"]:
        assert s["kw_offered"] == pytest.approx(s["battery_kw"] + s["ev_pause_kw"], abs=0.011)
        assert s["kw_offered"] <= 5.0 + car[s["id"]] + 0.01   # the battery's 5 kW and what the car would draw, no more
        assert (s["firm_kw"], s["tentative_kw"]) == (s["battery_kw"], round(s["kw_offered"] - s["battery_kw"], 3))     # stored energy is firm
    assert offer["air_conditioning"]["kw"] == 0.0 and all("ac_kw" not in s for s in offer["slots"])    # a January house: no cooling to ease


@pytest.mark.parametrize("wishes, why, answer", [
    ({"skip_days": [DAY]}, "the owner asked to skip 2025-01-28", ("DECLINED", "homeowner_opted_out")),
    ({"skip_until": "2025-01-30"}, "the owner asked to skip events until 2025-01-30", ("DECLINED", "homeowner_opted_out")),
    ({"min_price_usd_per_kwh": 0.75}, "the price $0.50/kWh is below the owner's minimum $0.75", ("ACCEPTED", "within_offer"))])
def test_a_day_off_or_a_price_under_the_owners_minimum_offers_nothing(tmp_path, wishes, why, answer):
    node, _ = built(tmp_path, wishes=wishes)
    _, offer = offered(node)
    assert kw_of(offer) == [0.0] * 6 and offer["energy_kwh"] == 0.0 and set(offer["held_back_kw"].values()) == {0.0}
    assert (offer["agent"]["take_part"], offer["agent"]["reason"]) == (False, why)
    assert offer["ev_flex"] is None and set(offer["evening"]["rebound_kw"]["1.0"]) == {0.0}          # no car to restart, no rebound
    assert sum(kw_of(node.brain.safe["ev-1"])) > 0 and node.brain.fallbacks["offer"] == 1           # the planner had kW to give
    c = {"id": "c-1", "event_id": "ev-1", "window_start": W0, "commitments": []}
    out = node.brain.decide_accept(c, {"decision": "ACCEPTED", "reason": "within_offer", "contract_id": "c-1"})
    assert (out["decision"], out["reason"]) == answer        # a day off declines its commitment too; a price floor shapes the offer only


def test_the_owners_battery_share_and_no_car_pause_take_only_what_they_allow_from_the_planner(tmp_path):
    node, _ = built(tmp_path, wishes={"battery_max_share": 0.5, "no_ev_pause": True})
    _, offer = offered(node)
    safe = node.brain.safe["ev-1"]
    half = [round(s["battery_kw"] / 2, 2) for s in safe["slots"]]
    assert [s["battery_kw"] for s in offer["slots"]] == half and sum(s["ev_pause_kw"] for s in safe["slots"]) > 10     # the planner had a car to pause
    assert kw_of(offer) == pytest.approx(half, abs=0.011) and offer["ev_flex"] is None and set(offer["held_back_kw"].values()) == {0.0}     # nothing held back
    assert (offer["agent"]["battery_share"], offer["agent"]["pause_ev"], offer["agent"]["take_part"]) == (0.5, False, True)


def test_the_owners_device_wish_takes_that_devices_share_out_of_the_offer_and_the_plan(tmp_path):
    node, _ = built(tmp_path, "home-02", wishes={"devices_off": ["hpwh"]})
    assert "hpwh" in node.adapter.dev_now(W0)
    out = node.brain.decide_offer(need(2), {}, json.loads(json.dumps(SAFE)))
    assert kw_of(out) == [3.25, 2.25] and out["energy_kwh"] == 2.75       # the water heater gave 0.75 of each slot's 1 kW of devices
    assert out["appliances"]["by_device"] == {"dryer": 0.25} and out["agent"]["devices_off"] == ["hpwh"]
    assert node.adapter.dev_off == {"hpwh"} and "hpwh" not in node.adapter.dev_now(W0)


def test_a_note_wish_that_blocks_the_water_heater_takes_its_share_out_of_the_offer():
    ended = {"wish": "keep_hot_water", "from": "2025-01-27 09:00", "until": "2025-01-28 12:00"}
    assert grounds.keep_out(SAFE, [ended], need(2)) is SAFE      # a wish that ended before the sale keeps nothing out
    kept = grounds.keep_out(SAFE, [{"wish": "keep_hot_water", "from": "2025-01-28 09:00"}], need(2))
    assert kw_of(kept) == [3.25, 2.25] and kept["energy_kwh"] == 2.75 and kept["appliances"]["by_device"] == {"dryer": 0.25}
    assert kept["kept_out"]["parts"] == ["devices"] and kw_of(SAFE) == [4.0, 3.0]


def test_a_node_an_alarm_holds_offers_nothing_and_holds_nothing_back(tmp_path):
    node, sent = built(tmp_path)
    _, offer = offered(node)
    node.adapter.rt_override("alarm", True)
    node.send_offer("txn-1", offer)
    wire = sent[-1][2]["message"]["offer"]
    assert kw_of(wire) == [0.0] * 6 and wire["energy_kwh"] == 0.0 and "held_back_kw" not in wire
    assert all(v == 0.0 for s in node.offers["ev-1"]["slots"] for k, v in s.items() if k != "id")


def test_the_comfort_limits_in_force_are_the_owners_on_file_until_a_person_lowers_one(tmp_path):
    host = type("Host", (HomeNodes,), {})()                         # home-01 as a host builds it: HomeNodes.owner_setup reads owners.json
    host.cfg, host.keydir, host.trusted, host._logger = dict(world.EVENING), tmp_path, lambda: [], lambda name: (lambda *a, **k: None)
    sim = host.make_node(host.roster()[0], lambda *a: None).adapter
    assert [control.person_limit(sim, k) for k in ("max_rise_c", "max_rise_away_c", "precool_c")] == [1.5, 2.5, 0.5]     # not the plan's 2.0, 4.0, 1.5
    sim.rt_override("comfort", {"max_rise_c": 1.0})
    said = sim.ctl.said_limits()
    assert control.person_limit(sim, "max_rise_c") == said.max_rise_c == 1.0 and said.precool_c == 0.5
    assert control.inside({"max_rise_c": 2.0, "precool_c": 0.3}, {"max_rise_c": 1.0}) == {"max_rise_c": 1.0, "precool_c": 0.3}
    assert control.inside({"max_rise_c": 0.5}, {"max_rise_c": 1.0}) == {"max_rise_c": 0.5}     # the agent's hold never passes the person's word


# ---------------------------------------------------------------------------------------------------- the shapes of an offer
def test_dropping_a_device_takes_out_its_share_of_the_devices_kw_in_proportion():
    out = drop_devices(SAFE, ["hpwh"])
    assert [(s["app_kw"], s["kw_offered"]) for s in out["slots"]] == [(0.25, 3.25), (0.25, 2.25)]
    assert out["energy_kwh"] == 2.75 and out["appliances"] == {"kw": 0.25, "mean_kw": 0.3, "by_device": {"dryer": 0.25}}
    assert drop_devices(SAFE, ["pool"]) is SAFE and drop_devices(SAFE, []) is SAFE and kw_of(SAFE) == [4.0, 3.0]


def test_a_battery_share_or_no_car_pause_never_offers_more_than_the_planner():
    half = scale_offer(SAFE, 0.5, True, True)
    assert [(s["battery_kw"], s["kw_offered"]) for s in half["slots"]] == [(1.0, 3.0), (1.0, 2.0)] and half["energy_kwh"] == 2.5
    assert half["evening"]["rebound_kw"] == {"0.25": [0.2], "0.5": [0.4], "0.75": [0.7], "1.0": [1.0]}    # the planner's at f x 0.5
    no_car = scale_offer(SAFE, 1.0, False, True)
    assert kw_of(no_car) == [3.0, 3.0] and no_car["energy_kwh"] == 3.0 and no_car["ev_flex"] is None
    assert no_car["evening"]["import_noev_kw"] == [1.0]      # without the pause the evening is the no-event one
    same = scale_offer(SAFE, 2.0, True, True)
    assert same["slots"] == SAFE["slots"] and same["energy_kwh"] == 3.5    # a share above 1 counts as 1: the planner's offer to the decimal
    assert kw_of(scale_offer(SAFE, 1.0, True, False)) == [0.0, 0.0]


def test_held_back_is_the_kw_between_what_the_rule_allows_and_what_went_out():
    final = scale_offer(SAFE, 0.5, True, True)
    assert held_back(SAFE, final) == {"0": 1.0, "1": 1.0} and held_back(final, SAFE) == {"0": 0.0, "1": 0.0}
    assert mean_kw(final) == 2.5 and kw_of({}) == [] and mean_kw({}) == 0.0


def test_the_decision_log_numbers_each_decision_in_plain_values_and_keeps_the_last_n():
    log = Decisions(n=2)
    first = log.add(kind="offer", kw=[np.float64(1.25)], share=np.float32(0.5))
    assert (first["n"], first["kw"], first["share"], type(first["share"])) == (1, [1.25], 0.5, float)
    log.add(kind="accept")
    log.add(kind="offer")
    assert [d["n"] for d in log.list()] == [2, 3] and [d["kind"] for d in log.list(1)] == ["offer"]


def test_the_owners_wishes_keep_only_known_keys_and_name_each_day_off(tmp_path):
    path = tmp_path / "wishes.json"
    path.write_text(json.dumps({"skip_days": [DAY], "skip_until": "2025-01-20", "battery_max_share": 0.4, "unknown": 1}))
    w = Wishes(path)
    assert set(w.get()) == set(DEFAULT_WISHES) and w.get()["battery_max_share"] == 0.4
    assert w.skips("2025-01-20") == "the owner asked to skip events until 2025-01-20"
    assert w.skips(DAY) == "the owner asked to skip 2025-01-28" and w.skips("2025-01-29") is None
    path.write_text("{not json")
    assert Wishes(path).get() == DEFAULT_WISHES == Wishes(tmp_path / "none.json").get()


# ---------------------------------------------------------------------------------------------------- the controller's plan
@pytest.mark.parametrize("P, short_kw", [(3.0, 0.0), (0.5, 0.5)])
def test_the_plan_delivers_from_the_battery_inside_its_power_and_counts_what_it_cannot(P, short_kw):
    r = solve(problem(P=P))
    given = min(P, 1.0)
    assert r["ok"] and all(abs(b) <= P + 1e-6 for b in r["b"]) and all(2.0 - 1e-6 <= s <= 10.0 + 1e-6 for s in r["S"])
    assert r["b"][4:8] == pytest.approx([given] * 4, abs=1e-6) and r["short"][4:8] == pytest.approx([short_kw] * 4, abs=1e-6)
    assert r["short_kwh"] == pytest.approx(4 * short_kw * 0.25, abs=1e-6)
    assert r["S"][-1] == pytest.approx(5.0 - 4 * given * 0.25 / 0.95, abs=1e-6)     # half of 10 kWh, less the hour's draw through the inverter


def test_the_plan_keeps_the_owners_comfort_and_falls_short_rather_than_break_it():
    eased = solve(problem(E=0.0, cool=1.0))                       # owners.json: 1.5 C warmer at most, 0.5 C cooler
    assert eased["short_kwh"] == pytest.approx(0.0, abs=1e-6) and eased["cool_kw"][4:8] == pytest.approx([-1.0] * 4, abs=1e-6)
    assert min(eased["x"]) >= -0.5 - 1e-6 and max(eased["x"]) <= 1.5 + 1e-6
    tight = solve(problem(E=0.0, cool=1.0, limits=owner_limits(max_rise_c=0.2, precool_c=0.0)))
    x, given = tight["x"], [2.0 - tight["g"][k] for k in range(4, 8)]
    a = math.exp(-0.25 * 0.45 / 8.0)                              # a step of the house: each kW given (3 kW less heat removed) warms it 3 (1 - a) / 0.45 C
    assert max(x) == pytest.approx(0.2, abs=1e-6) and min(x) >= -1e-6
    assert 0.2 * 0.45 / 3 / (1 - a) - 1e-6 <= sum(given) <= 0.2 * 0.45 / 3 / (1 - a) / a ** 3 + 1e-6      # as much as 0.2 C allows, and no more
    assert [g + s for g, s in zip(given, tight["short"][4:8])] == pytest.approx([1.0] * 4, abs=1e-6) and tight["short_kwh"] > 0.4     # the rest is short
    assert all(-1e-6 <= x[k - 1] - x[k] <= RECOVER_C_PER_H * 0.25 + 1e-6 for k in range(8, 12))     # after the sale: never warmer, back slowly


def test_a_call_gets_the_battery_energy_above_the_reserve_or_its_full_power_with_time_to_charge():
    p = problem(owed=0.0)
    assert capacity(p, [k < 4 for k in range(12)]) == pytest.approx((0.5 - 0.2) * 10.0 * 0.95 / 1.0, abs=1e-5)
    assert capacity(p, [4 <= k < 8 for k in range(12)]) == pytest.approx(3.0, abs=1e-5)


# ---------------------------------------------------------------------------------------------------- the commitment and delivery
def test_the_plan_and_the_readings_follow_what_the_buyer_took_not_what_was_offered(tmp_path):
    node, sent = built(tmp_path)
    key = signing.load_or_create(tmp_path / "community.key")
    node.trusted = lambda: [signing.public_hex(key)]

    def confirm(c: dict) -> str:
        return node.handle("beckn.confirm", "community", beckn.make("confirm", sender="community", receiver="home-01", transaction_id="txn-1",
                                                                     message={"contract": c}, key=key))
    nd, (_, offer) = need(), offered(node)
    took = [round(kw / 2, 2) for kw in kw_of(offer)]          # the buyer takes half of every slot
    assert confirm(contract(nd, [kw + 0.05 for kw in kw_of(offer)], "c-2")) == "Contract c-2: DECLINED (slot_0_above_offer)."
    assert node.adapter.plan == {}
    assert confirm(contract(nd, took)) == "Contract ev-1:home-01: ACCEPTED (within_offer)."
    assert [b["message"]["contract"]["status"] for _, kind, b, _ in sent if kind == "beckn.on_confirm"] == ["DECLINED", "ACCEPTED"]
    assert {node.adapter.plan[beckn.add_minutes(W0, -15 * k)]["precharge_to"] for k in range(1, 9)} == {1.0}     # full by 18:00
    assert node.adapter.ev_holds == [(W0, W1)]
    tick_at(node, W0)
    assert node.adapter.ctl.last["owed_kw"] == {beckn.add_minutes(s["start"], m): kw for s, kw in zip(nd["slots"], took) for m in (0, 15)}
    assert node.adapter.ctl.last["short_by_ts"] == {}         # the plan expects to give all of it
    node.rt_take("txn-1", {"id": "rel-1", "event_id": "ev-1", "steps": {"2025-01-28 19:00": -1.0, "2025-01-28 19:15": -1.0}})     # 1 kW let go
    took[2] = round(took[2] - 1.0, 2)
    assert node.adapter.ctl.target_at("2025-01-28 19:15") == pytest.approx(took[2])
    tick_at(node, "2025-01-28 21:30")
    tick_at(node, "2025-01-28 22:30")                         # an hour after the last reading: the batch goes
    batch = {to: b["message"]["batch"] for to, _, b, _ in sent if "batch" in b["message"]}
    assert [r["message"]["performance"]["committed_kw"] for r in batch["community"]] == took
    assert len(batch["utility"]) == 6 and "truth" not in batch["utility"][0]["message"]["performance"]


def test_the_requests_for_steps_5_and_6_carry_the_amounts_code_decides_on():
    nd, verdict = need(), {"decision": "ACCEPTED", "reason": "within_offer", "contract_id": "ev-1:home-01"}
    ask = offer_request(nd, SAFE, "txn-1")
    assert (ask["kind"], ask["window"], ask["price"], ask["asked_kw"], ask["reply_by"], ask["safe"]) == \
        ("offer", (W0, W1), 0.5, [3.0] * 6, "2025-01-28 12:00", SAFE)
    got = commitment_request(contract(nd, [1.0, 2.0, 0.0, 0.0, 0.0, 0.5]), verdict)
    assert (got["kind"], got["id"], got["kw"], got["verdict"], got["reply_by"], got["txn"]) == \
        ("commitment", "ev-1:home-01", [1.0, 2.0, 0.0, 0.0, 0.0, 0.5], verdict, "2025-01-28 12:00", None)

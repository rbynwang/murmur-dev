"""Meter verification and settlement math, on the fixture dataset and its price book: a home battery's kWh earns 0.7 of the order's price, a building's
0.5075, a home's other kWh 0.18375, and 0.3 of each bill is kept.

A baseline is the mean of the last ten clean days of the same kind, with a flagged fall-back and the same-day adjustment. A meter delivers its baseline
less its use over the event, never below zero. A bill prices each class's kWh at its own rate, each node is paid its class's share of the order's price,
and the shares and the kept part add up to the bill. A reading, an owed amount or a settlement that can't be true is refused with its reason, and
settling the same readings twice gives the same money.
"""
from __future__ import annotations

import copy
from datetime import date
from types import SimpleNamespace

import pytest

from murmur import config
from murmur.protocol import envelope
from murmur.settlement import market_checks as mk
from murmur.settlement import meter_check as mc
from murmur.settlement import rules as st

NAN, INF = float("nan"), float("inf")
SLOTS = [{"id": 0, "price": 0.8}, {"id": 1, "price": 0.8}]          # one order, one price: $0.8 a kWh
CT = {"meters": ["home-01", "home-02"], "meter_readings": {"home-01": {0: 1.0, 1: 2.0}, "home-02": {0: 1.0, 1: 2.0}}, "meter_batt": {"home-01": {0: 2.0}},
      "meter_pre": {"home-01": 2.0}, "pre_baselines": {"home-01": 1.25}}
BASES = {"home-01": {"0": {"BASELINE": 3.25}, "1": {"BASELINE": 3.25}}, "home-02": {"0": {"BASELINE": 3.0}, "1": {"BASELINE": 3.0}}}
METERS = {"home-01": {0: {"BASELINE": 4.0, "USAGE": 1.0, "BATT": 2.0}, 1: {"BASELINE": 4.0, "USAGE": 2.0, "BATT": 0.0}},
          "home-02": {0: {"BASELINE": 3.0, "USAGE": 1.0, "BATT": 0.0}, 1: {"BASELINE": 3.0, "USAGE": 2.0, "BATT": 0.0}}}
TEN = [date(2025, 2, d) for d in (14, 13, 11, 10, 7, 6, 5, 4, 3)] + [date(2025, 1, 31)]


def val_of(meters: dict) -> dict:
    """Each meter's (kWh delivered, kWh at its class's share) per half hour."""
    return {h: st.meter_kwh(m, 0.5, name=h) for h, m in meters.items()}


def sold(v: float, **more) -> dict:
    """A settlement that pays the sellers v, with the fields given."""
    return {"revenue_flows": [{"role": "buyer", "value": -v}, {"role": "seller", "value": v}], **more}


# ------------------------------------------------------------------ baselines
def test_a_baseline_is_the_mean_of_the_last_ten_clean_weekdays_skipping_holidays_and_sale_days(monkeypatch):
    monkeypatch.setitem(config.dataset_meta(), "holidays", ["2025-02-17"])
    tue, sale = date(2025, 2, 18), {date(2025, 2, 12)}
    usage = {d: [1.0 + i, 3.0] for i, d in enumerate(TEN)} | {date(2025, 2, d): [50.0, 50.0] for d in (12, 15, 16, 17)}
    assert st.similar_days(tue, sale) == TEN
    assert st.ten_of_ten(usage, tue, sale) == {"per_slot": [5.5, 3.0], "days": [d.isoformat() for d in TEN], "candidates": 10}     # (1 + ... + 10) / 10
    assert st.baseline_days(tue, sale) == {"days": TEN, "rule": st.TEN_CLEAN, "flag": False, "add_back": False}


@pytest.mark.parametrize("day, sales, rule, days", [
    (date(2025, 2, 22), set(), st.SAME_KIND, [date(2025, 2, d) for d in (16, 15, 9, 8, 2, 1)]),
    (date(2025, 2, 8), {date(2025, 2, 1), date(2025, 2, 2)}, st.ANY_KIND, [date(2025, 2, d) for d in (7, 6, 5, 4, 3)] + [date(2025, 1, d) for d in (31, 30, 29, 28, 27)]),
    (date(2025, 1, 28), {date(2025, 1, 27)}, st.SALE_DAYS, [date(2025, 1, 27)]),
    (date(2025, 1, 27), set(), st.NO_BASELINE, []),
], ids=["same-kind", "any-kind", "sale-days", "none"])
def test_short_of_ten_clean_days_a_baseline_falls_back_in_order_from_the_dataset_s_first_day_and_says_so(day, sales, rule, days):
    assert st.baseline_days(day, sales) == {"days": days, "rule": rule, "flag": True, "add_back": rule == st.SALE_DAYS}


def test_a_fall_back_baseline_is_the_mean_of_the_chosen_days_that_have_a_reading():
    usage = {date(2025, 2, 16): [2.0, 1.0], date(2025, 2, 15): [4.0, 1.5]}
    assert st.mean_of_days(usage, [date(2025, 2, 16), date(2025, 2, 15), date(2025, 2, 9)]) == {"per_slot": [3.0, 1.25], "days": ["2025-02-16", "2025-02-15"], "candidates": 2}
    assert st.mean_of_days(usage, []) == {"per_slot": [], "days": []}


def test_the_same_day_adjustment_adds_the_pre_event_load_above_its_baseline_and_never_lowers_it():
    assert (st.adjusted(5.5, 2.0, 1.25), st.adjusted(5.5, 1.0, 1.25), st.adjusted(5.5, None, 1.25)) == (6.25, 5.5, 5.5)
    assert mc.counted(CT, BASES) == (METERS, {})                    # home-01: 3.25 + (2.0 - 1.25) kW; home-02 sent no pre-event load
    ct = {"need": {"event_id": "ev-1"}, "pre_baselines": {"home-01": 1.0}}
    assert mc.pre_kw(ct, "home-01", {"slot_id": 0, "pre_kw": 2.5}, lambda *a, **k: None) == 2.5
    assert mc.pre_kw(ct, "home-01", {"slot_id": 0, "pre_kw": 19.0}, lambda *a, **k: None) is None and ct["pre_refused"] == 1    # past 1.0 + the 17.9 kW it can add


def test_a_half_hour_marked_abnormal_or_never_owed_is_left_out_of_the_count():
    ct = {**CT, "abnormal": {"home-02": [1]}, "owed": {"home-01": {0: (1.0, 1.0)}, "home-02": {0: (2.0, 2.0), 1: (1.0, 1.0)}}}
    meters, notes = mc.counted(ct, BASES)
    assert {h: sorted(m) for h, m in meters.items()} == {"home-01": [0], "home-02": [0]} and notes == {"not_owed": {"home-01": [1]}}


# ------------------------------------------------------------------ delivery and pay
def test_a_meter_delivers_its_baseline_less_its_use_with_the_battery_at_its_own_share():
    assert val_of(METERS)["home-01"] == ({"0": 1.5, "1": 1.0}, {"0": 0.791875, "1": 0.18375})     # 0.5 h x (2 kW x 0.7 + 1 kW x 0.18375); 0.5 h x 2 kW x 0.18375
    assert st.meter_kwh({0: {"BASELINE": 3.0, "USAGE": 1.0, "BATT": -1.0}}, 0.5, name="home-01")[0] == {"0": 1.0}      # a charging battery adds nothing
    bld = st.meter_kwh({0: {"BASELINE": 50.0, "USAGE": 20.0}}, 0.5, cap={0: 12.0}, building=True, name="building-01")
    assert bld == ({"0": 6.0}, {"0": 3.045})                        # a 30 kW cut counted at its 12 kW cap, at the building's 0.5075


def test_a_meter_s_half_hours_net_over_the_event_and_an_event_below_its_baseline_pays_nothing():
    above = {0: {"BASELINE": 2.0, "USAGE": 3.0}, 1: {"BASELINE": 2.0, "USAGE": 1.5}}              # -1 kW, then +0.5 kW
    assert st.meter_kwh(above, 0.5, name="home-01") == ({"0": 0.0, "1": 0.0}, {"0": 0.0, "1": 0.0})
    mixed = {0: {"BASELINE": 2.0, "USAGE": 2.5}, 1: {"BASELINE": 2.0, "USAGE": 1.0}}              # -0.5 kW, then +1 kW
    assert st.meter_kwh(mixed, 0.5, name="home-01")[0] == {"0": -0.25, "1": 0.5}
    assert st.split(1.0, {"home-01": 2.0, "home-02": -1.0})["per_home"] == {"home-01": 1.0, "home-02": 0.0}


def test_a_bill_prices_each_class_s_kwh_at_its_own_rate_with_no_cap_at_the_offer_and_no_penalty():
    s = st.deg_settle(SLOTS, {0: 6.0, 1: 1.0}, METERS)
    # a battery kWh is billed at the order's $0.8, a home's other kWh at 0.18375 / 0.7 = 0.2625 of it ($0.21)
    # slot 0: 2 kW battery + 3 kW other for half an hour = 1 x 0.8 + 1.5 x 0.21; slot 1: 3 kW other = 1.5 x 0.21
    assert [(r["offered"], r["delivered"], r["pay"], r["penalty"]) for r in s["components"]] == [(6.0, 5.0, 1.115, 0.0), (1.0, 3.0, 0.315, 0.0)]
    assert (s["total"], s["full_price_usd"], s["net_zero_ok"]) == (1.43, 3.2, True)                # 8 kW for half an hour at $0.8
    assert s["revenue_flows"] == [{"role": "buyer", "value": -1.43, "currency": "USD"}, {"role": "seller", "value": 1.43, "currency": "USD"}]
    assert "0.2625 for any other home device" in st.bill_rule() and "0.1 by the community's operator and 0.2 by the aggregator" in st.bill_rule()


def test_each_node_is_paid_its_class_s_share_of_the_order_s_price_and_the_kept_part_is_0_3_of_the_bill():
    s = st.deg_settle(SLOTS, {}, METERS)
    sp = st.share_out(s["total"], s["full_price_usd"], val_of(METERS))
    # home-01: (2 x 0.7 + 3 x 0.18375) kW x 0.5 h x $0.8 = 0.7805; home-02: 3 x 0.18375 x 0.5 x 0.8 = 0.2205
    assert (sp["per_home"], sp["pool"], sp["fee"], sp["usd_per_kwh"]) == ({"home-01": 0.7805, "home-02": 0.2205}, 1.001, 0.429, 0.8)
    assert sum(sp["per_home"].values()) + sp["fee"] == pytest.approx(1.43, abs=1e-12) and sp["fee"] == pytest.approx(0.3 * 1.43)
    short = st.share_out(0.4004, s["full_price_usd"], val_of(METERS))       # a bill short of the shares: each is cut by 0.4004 / 1.001
    assert (short["per_home"], short["fee"]) == ({"home-01": 0.3122, "home-02": 0.0882}, 0.0)


def test_share_out_never_pays_out_more_than_a_short_bill_after_rounding():
    val = {h: st.meter_kwh({0: {"BASELINE": kw, "USAGE": 0.0, "BATT": kw}}, 0.5, name=h) for h, kw in (("home-01", 1.0), ("home-02", 1.0), ("home-03", 4.0))}
    sp = st.share_out(1.0, 2.4, val)                                # shares of 1/6, 1/6 and 2/3 of a $1.00 bill: rounded one by one they come to $1.0001
    assert (sp["pool"], sp["fee"], round(sum(sp["per_home"].values()), 4)) == (1.0, 0.0, 1.0)
    assert all(abs(sp["per_home"][h] - x) <= 1e-4 for h, x in (("home-01", 1 / 6), ("home-02", 1 / 6), ("home-03", 2 / 3)))


def test_in_a_half_hour_a_call_covers_the_booking_stops_at_the_capacity_sold_and_every_class_shrinks_alike():
    s = st.deg_settle(SLOTS, {}, METERS, capped={0: 4.0})          # slot 0 delivered 5 kW of the 4 sold: every class x 4 / 5
    assert [r["delivered"] for r in s["components"]] == [4.0, 3.0] and (s["total"], s["full_price_usd"]) == (1.207, 2.8)     # 0.8 x 1.115 + 0.315
    val = val_of(METERS)
    st.trim_called(val, {0: 4.0}, 0.5)
    kwh, paid = val["home-02"]
    assert kwh == pytest.approx({"0": 0.8, "1": 0.5}) and paid == pytest.approx({"0": 0.147, "1": 0.091875})
    sp = st.share_out(s["total"], s["full_price_usd"], val)
    assert sp["per_home"] == {"home-01": 0.6538, "home-02": 0.1911} and sp["fee"] == pytest.approx(0.3 * 1.207)


def test_two_buyers_filled_from_one_pool_each_pay_their_share_of_the_same_meters_so_no_kwh_is_paid_twice():
    parts = [st.deg_settle(SLOTS, {}, METERS, share={0: k, 1: k}) for k in (0.25, 0.75)]       # a quarter and three quarters of the 5 kW, then 3 kW, the pool delivered
    assert [(p["total"], p["full_price_usd"], [r["delivered"] for r in p["components"]]) for p in parts] == [(0.3575, 0.8, [1.25, 0.75]), (1.0725, 2.4, [3.75, 2.25])]
    assert sum(p["total"] for p in parts) == pytest.approx(1.43) and sum(p["full_price_usd"] for p in parts) == pytest.approx(3.2)       # one buyer's bill on these meters


def test_a_call_bill_is_its_nodes_shares_over_what_they_are_left_of_it():
    kwh, batt, bld = {"home-01": 1.0, "building-01": 2.0}, {"home-01": 0.5}, {"building-01"}
    bill = st.call_bill(2.4, kwh, batt, bld)                        # 3 kWh at $0.8: (0.5 x 0.7 + 0.5 x 0.18375) x 0.8 + 2 x 0.5075 x 0.8 = 1.1655
    assert bill == 1.665                                            # 1.1655 / 0.7
    sp = st.call_shares(2.4, kwh, batt, bld, bill)
    assert (sp["per_home"], sp["pool"], sp["fee"]) == ({"home-01": 0.3535, "building-01": 0.812}, 1.1655, 0.4995)


def test_split_shares_by_measured_delivery_with_a_building_counted_at_most_1_2_times_its_commitment():
    caps = st.building_counted_kwh({0: {"BASELINE": 50.0, "USAGE": 20.0}, 1: {"BASELINE": 50.0, "USAGE": 45.0}}, {"0": 10.0, "1": 10.0})
    assert caps == 8.5                                              # (min(30, 1.2 x 10) + min(5, 12)) kW x 0.5 h
    sp = st.split(10.0, {"home-01": 2.0, "building-01": 15.0}, 0.1, {"building-01": caps})
    assert (sp["pool"], sp["fee"], sp["per_home"], sp["caps_kwh"]) == (9.0, 1.0, {"home-01": 1.7143, "building-01": 7.2857}, {"building-01": 8.5})   # 9 x 2 / 10.5


def test_three_equal_shares_that_do_not_divide_add_up_to_their_pool_with_the_ten_thousandth_left_over_to_the_first_by_name():
    homes = {"home-01": 1.0, "home-02": 1.0, "home-03": 1.0}
    calls, pro_rata = st.call_shares(1.0, homes, homes, set()), st.split(1.0, homes)      # three battery kWh at $1/3: 0.7 / 3 each and $0.30 kept; $1 pro rata
    assert (calls["per_home"], calls["pool"], calls["fee"]) == ({"home-01": 0.2334, "home-02": 0.2333, "home-03": 0.2333}, 0.7, 0.3)
    assert (pro_rata["per_home"], pro_rata["pool"], pro_rata["fee"]) == ({"home-01": 0.3334, "home-02": 0.3333, "home-03": 0.3333}, 1.0, 0.0)


def test_a_deposit_is_credited_up_to_the_bill_and_the_rest_refunded():
    assert st.deposit_statement(1.43, 2.0) == {"held_usd": 2.0, "credited_usd": 1.43, "refund_usd": 0.57, "still_due_usd": 0.0}
    assert st.deposit_statement(1.43, 1.0) == {"held_usd": 1.0, "credited_usd": 1.0, "refund_usd": 0.0, "still_due_usd": 0.43}


def test_settling_the_same_readings_twice_gives_the_same_money_and_leaves_the_readings_as_they_were():
    before = copy.deepcopy((CT, BASES))

    def settle():
        meters, _ = mc.counted(CT, BASES)
        s = st.deg_settle(SLOTS, {}, meters, capped={0: 4.0})
        val = val_of(meters)
        st.trim_called(val, {0: 4.0}, 0.5)
        return s, st.share_out(s["total"], s["full_price_usd"], val)
    first = settle()
    assert settle() == first and first[1]["per_home"] == {"home-01": 0.6538, "home-02": 0.1911}
    assert (CT, BASES) == before


# ------------------------------------------------------------------ readings
def test_a_home_s_enrolment_bounds_its_readings_and_good_readings_are_kept():
    f = mc.facts("home-01")         # 5 kW battery + 7.2 kW car charger + 8 / 2 kW cooling + 1.7 kW water heater; 13.5 kWh x 0.8 above reserve x 0.95
    assert f == pytest.approx({"kind": "home", "rated_kw": 17.9, "intake_kw": 17.9, "export_kw": 5.0, "battery_kw": 5.0, "stored_kwh": 10.26}) and mc.facts("site-pv-01") is None
    for usage, battery in ((1.2, 2.0), (-5.0, 0.0), (19.9, -5.0)):
        assert mc.reading_problem({"slot_id": 1, "usage_kw": usage, "battery_kw": battery, "committed_kw": 1.5}, {0, 1}, f, 2.0) is None
    assert mc.reading_problem({"slot_id": 1, "usage_kw": 35.8}, {0, 1}, f, None) is None            # no baseline: its nameplate and what it can add
    assert [mc.real(v) for v in (1, 2.5, True, "1", NAN, INF, 10 ** 400)] == [True, True, False, False, False, False, False]
    assert [mc.sane(v) for v in (1e9, -1e9, 1.1e9)] == [True, True, False]


@pytest.mark.parametrize("reading, why", [
    ({"slot_id": 1, "usage_kw": -5.1}, "5.1 kW going out is past its meter's 5 kW"),
    ({"slot_id": 1, "usage_kw": 1.2, "battery_kw": -5.1}, "5.1 kW into a battery that takes 5"),
    ({"slot_id": 1, "usage_kw": 1.2, "committed_kw": -0.5}, "it committed less than nothing"),
    ({"slot_id": 1, "usage_kw": 19.95}, "19.95 kW coming in is past its baseline and the 17.9 kW it can add"),
    ({"slot_id": 1, "usage_kw": NAN}, "its usage isn't a real number"),
    ({"slot_id": 1, "usage_kw": "1.2"}, "its usage isn't a real number"),
    ({"slot_id": 1, "usage_kw": 1.2, "battery_kw": INF}, "its battery_kw isn't a real number"),
    ({"slot_id": "1", "usage_kw": 1.2}, "it names no real slot"),
    ({"slot_id": True, "usage_kw": 1.2}, "it names no real slot"),
    ({"slot_id": 7, "usage_kw": 1.2}, "this sale has no slot 7"),
    ([1, 1.2], "it isn't a reading"),
])
def test_an_impossible_reading_is_refused_with_its_reason(reading, why):
    assert mc.reading_problem(reading, {0, 1}, mc.facts("home-01"), 2.0) == why


def test_a_buyer_keeps_a_repeat_that_says_the_same_and_refuses_one_that_changes_it():
    ct = {"need": {"event_id": "ev-1", "slots": [{"id": 0}, {"id": 1}]}, "baselines": {"home-01": {"0": {"BASELINE": 2.0}, "1": {"BASELINE": 2.0}}},
          "meter_readings": {"home-01": {0: 1.0}}, "meter_batt": {"home-01": {0: 0.0}}}
    seen = []
    refuse = lambda r: mc.buyer_refuses(ct, "home-01", r, lambda kind, **k: seen.append((kind, k["slot"], k["why"])))     # noqa: E731
    assert refuse({"slot_id": 0, "usage_kw": 1.003}) is None                                        # within 0.004 kW of the reading in
    out = refuse({"slot_id": 0, "usage_kw": 1.5})
    assert isinstance(out, envelope.Refused) and out == "rejected: it changes a reading already in"
    assert refuse({"slot_id": 1, "usage_kw": NAN}) == "rejected: its usage isn't a real number"
    assert ct["rejected_readings"] == 2 and ct["rejected_slots"] == {"home-01": {1: "its usage isn't a real number"}}
    assert refuse({"slot_id": 1, "usage_kw": 0.8}) is None and ct["rejected_slots"] == {"home-01": {}}
    assert seen == [("reading_refused", "0", "it changes a reading already in"), ("reading_refused", "1", "its usage isn't a real number")]


def test_a_home_s_claim_is_cut_once_to_its_nameplate_its_battery_s_rate_and_what_its_meter_delivered():
    rows = {"home-01": {0: {"BASELINE": 20.0, "USAGE": 1.0, "BATT": 6.0}, 1: {"BASELINE": 3.0, "USAGE": 1.0, "BATT": 4.0}}, "building-01": {0: {"BASELINE": 500.0, "USAGE": 1.0}}}
    assert mc.limit(rows) == {"home-01": {"battery_kw": {"0": 6.0}, "nameplate_kw": {"0": 19.0}}}
    assert rows["home-01"][0] == pytest.approx({"BASELINE": 20.0, "USAGE": 2.1, "BATT": 5.0})        # 20 - 17.9 kW, and its 5 kW battery
    assert rows["home-01"][1] == {"BASELINE": 3.0, "USAGE": 1.0, "BATT": 2.0} and rows["building-01"][0] == {"BASELINE": 500.0, "USAGE": 1.0}
    assert mc.limit(rows) == {}


def test_a_building_s_battery_claim_past_its_enrolled_battery_never_reaches_the_money():
    ct = {"need": {"event_id": "ev-1", "slots": [{"id": 0}]}, "baselines": {"building-01": {"0": {"BASELINE": 40.0}}}, "meters": ["building-01"]}
    reading = {"slot_id": 0, "usage_kw": 40.0, "battery_kw": 12.0}                 # building-01 enrolled no battery, and its meter shows no cut
    assert mc.buyer_refuses(ct, "building-01", reading, lambda *a, **k: None) is None      # the door checks a battery that charges, not one that gives
    ct.update(meter_readings={"building-01": {0: 40.0}}, meter_batt={"building-01": {0: 12.0}})
    meters, notes = mc.counted(ct, ct["baselines"])
    assert meters == {"building-01": {0: {"BASELINE": 40.0, "USAGE": 40.0, "BATT": 0.0}}} and notes == {"capped": {"building-01": {"battery_kw": {"0": 12.0}}}}
    assert st.deg_settle([{"id": 0, "price": 0.8}], {}, meters, caps={"building-01": {0: 12.0}})["total"] == 0.0     # its cap: 1.2 x 10 kW owed


# ------------------------------------------------------------------ owed amounts and settlements
def test_a_node_owes_its_accepted_contract_plus_the_gaps_it_was_dispatched_for_and_a_reading_cannot_say_more():
    ev = {"need": {"event_id": "ev-1", "slots": [{"id": 0, "start": "2025-01-28 18:00"}, {"id": 1, "start": "2025-01-28 18:30"}]}, "readings": {},
          "commitments": {"home-01": {"status": "ACCEPTED", "contract": {"commitments": [{"id": 0, "kw": 1.5}]}}, "home-02": {"status": "DECLINED"}}}
    market = SimpleNamespace(run_wall=0.0, pooled=True, events={"ev-1": ev}, rt=SimpleNamespace(calls={}), log=lambda *a, **k: None)
    reading = {"event_id": "ev-1", "home": "home-01", "slot_id": 1, "usage_kw": 1.0}
    assert mk.market_refuses(market, "home-01", reading, {}) == "reading refused: it owes nothing in slot 1"
    assert mk.market_refuses(market, "home-02", reading, {}) == "reading refused: it's another node's reading"
    market.rt.calls["gap-1"] = {"kind": "gap", "parent": {"id": "ev-1"}, "alloc": {"home-01": {"2025-01-28 18:30": 1.0, "2025-01-28 18:45": 0.6}}}
    assert mk.owed_kw(market, ev) == {"home-01": {"0": [1.5, 1.5], "1": [0.0, 0.8]}}               # the gap's two quarter hours: (1.0 + 0.6) / 2 kW
    assert mk.market_refuses(market, "home-01", reading, {}) is None and ev["rejected_slots"]["home-01"] == {}
    owed = mk.owed_of(mk.owed_kw(market, ev))
    assert [mc.committed({"meter_committed": {"home-01": {1: kw}}, "owed": owed}, "home-01", 1) for kw in (2.0, 0.5)] == [0.8, 0.5]


def test_a_call_reading_is_held_to_the_kw_the_desk_dispatched_and_to_the_node_s_battery():
    rec = {"id": "call-1", "start": "2025-01-28 18:00", "end": "2025-01-28 19:00", "alloc": {"home-01": {"2025-01-28 18:00": 2.0, "2025-01-28 18:15": 1.0}}}
    assert mk.allowed_kw(rec, "home-01", "2025-01-28 18:00") == 1.5
    row = mk.call_row(rec, "home-01", {"start": "2025-01-28 18:00", "usage_kw": 0.5, "committed_kw": 3.0, "battery_kw": 6.0})
    assert row == {"usage_kw": 0.5, "dispatched_kw": 1.5, "battery_kw": 5.0, "said_battery_kw": 6.0}
    refuse = lambda home, start: mk.call_refuses(rec, home, {"start": start, "usage_kw": 0.5}, lambda *a, **k: None)     # noqa: E731
    assert refuse("home-01", "2025-01-28 18:00") is None and refuse("home-01", "2025-01-29 00:30") is None
    assert refuse("home-02", "2025-01-28 18:00") == "rejected: the desk didn't dispatch this node for this call"
    assert refuse("home-01", "2025-01-28 18:15") == "rejected: its half hour can't be read"
    assert refuse("home-01", "2025-01-29 01:00") == "rejected: 2025-01-29 01:00 is no half hour of this call"     # six hours past the call's end


@pytest.mark.parametrize("s, why", [
    ([1.43], "it isn't a settlement"),
    ({"total": 1.43}, "no real sum for the sellers"),
    (sold(NAN), "no real sum for the sellers"),
    (sold(2e9), "no real sum for the sellers"),
    (sold(-1.0), "less than nothing for the sellers"),
    (sold(1.0, full_price_usd=-1.0), "a full price that can't be read"),
    (sold(1.0, components=[{"delivered": "5"}]), "components that can't be read"),
    (sold(1.0, capped_kw={"0": NAN}), "caps that can't be read"),
    (sold(1.0, top_up=True), "a top-up round that can't be read"),
    (sold(1.0, currency=840), "a currency that can't be read"),
    (sold(1.0, actuals=[]), "actuals that can't be read"),
    (sold(1.0, actuals={"home-01": {"0": {"BASELINE": 1.0, "USAGE": 2.0}}}), "a sum for the sellers and no meter that shows them delivering"),
    (sold(1.0, note=NAN), "a number that isn't real"),
    (sold(1.0, lacking={"home-01": ["0"]}), "a list of what it lacks that can't be read"),
])
def test_a_settlement_the_split_cannot_read_is_refused_at_the_door(s, why):
    assert mk.settlement_problem(s) == why


def test_a_settlement_worked_out_by_the_rules_passes_the_door():
    s = {**st.deg_settle(SLOTS, {}, METERS), "currency": "USD", "actuals": {h: {str(k): v for k, v in m.items()} for h, m in METERS.items()}}
    assert mk.settlement_problem(s) is None
    assert mk.settlement_problem(sold(0.0, actuals={"home-01": {"0": {"BASELINE": 1.0, "USAGE": 2.0}}}, lacking={"home-02": [0, 1]})) is None


def test_a_call_settlement_is_refused_when_its_kwh_pass_what_the_call_or_its_nodes_could_bring_in():
    s = {"paid_usd": 1.0, "full_price_usd": 1.2, "delivered_kwh": 2.0, "by_home_kwh": {"home-01": 1.5, "home-02": 0.5}, "by_home_batt_kwh": {"home-01": 1.0}}
    rec = {"from": "utility"}
    assert mk.call_settlement_problem(s, rec, "utility", 2.0) is None
    assert mk.call_settlement_problem(s, rec, "buyer-02", 2.0) == "it isn't this buyer's call"
    assert mk.call_settlement_problem({**s, "paid_usd": -0.1}, rec, "utility", 2.0) == "no real sum"
    assert mk.call_settlement_problem({**s, "delivered_kwh": 2.02}, rec, "utility", 2.0) == "a delivery the call can't have brought in"
    assert mk.call_settlement_problem({**s, "by_home_kwh": {"home-01": 1.5, "home-02": 0.52}}, rec, "utility", 2.0) == "more kWh for its nodes than it says the call brought in"
    assert mk.call_settlement_problem({**s, "by_home_kwh": {"home-01": -0.5}}, rec, "utility", 2.0) == "kWh that can't be read"


def test_baselines_that_cannot_be_read_are_refused():
    assert mk.baselines_problem({"home-01": {"0": {"BASELINE": 2.0}, "1": {"BASELINE": None}}}) is None
    for bad in ({"home-01": {"0": {"BASELINE": NAN}}}, {"home-01": {"0": 2.0}}, {"home-01": []}, []):
        assert mk.baselines_problem(bad) == "baselines that can't be read"


def test_buyers_disagree_where_two_copies_of_a_half_hour_differ_by_more_than_the_meter_s_tolerance():
    one = {"settlement": {"actuals": {"home-01": {"0": {"USAGE": 1.0}, "1": {"USAGE": 2.0}}, "home-02": {"0": {"USAGE": 3.0}}}}}
    two = {"settlement": {"actuals": {"home-01": {"0": {"USAGE": 1.003}, "1": {"USAGE": 2.5}}, "home-02": {"0": {"USAGE": 3.0}}}}}
    assert mk.buyers_disagree([one, two]) == {"home-01": ["1"]}
    assert mk.buyers_disagree([one, copy.deepcopy(one), {"settlement": None}]) == {}


def test_a_row_that_cannot_be_read_costs_its_node_alone_and_a_node_is_counted_on_the_copy_that_pays_it_less():
    seen = []
    meters = {"home-01": {"0": {"BASELINE": 2.0, "USAGE": 1.0}, "1": {"BASELINE": "2", "USAGE": 1.0}}, "home-02": {"0": {"BASELINE": 2.0, "USAGE": NAN}},
              "home-03": {"0": {"BASELINE": 2.0, "USAGE": 1.0, "BATT": INF}}}
    assert mk.clean_actuals(meters, lambda kind, **k: seen.append((kind, k["homes"])), "ev-1") == {"home-01": {"0": {"BASELINE": 2.0, "USAGE": 1.0}}}
    assert seen == [("v2_bad_actuals", ["home-01", "home-02", "home-03"])]
    kept: dict = {}
    for usage in (1.0, 1.5, 1.2):
        mk.keep_lower(kept, "home-01", "0", {"BASELINE": 3.0, "USAGE": usage})
    assert kept == {"home-01": {"0": {"BASELINE": 3.0, "USAGE": 1.5}}}

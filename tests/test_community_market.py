"""The community's market from its door to its clearing: what an offer or an order may say, an offer's firm part, what a member may hand its community, how the
clearing shares the buyers' orders out over the members' offers, the community's cover, connection limit and report rows, and the community forecast's own fit."""
from __future__ import annotations

import itertools
import json
import math
from types import SimpleNamespace

import pytest

from murmur.agents.community import community as cm, community_rules as cr, forecast as cf, market_rules as mr
from murmur.agents.community.market import Market
from murmur.agents.community.members import Members
from murmur.protocol import envelope as beckn, signing
from murmur.replay import Replay

NAN = float("nan")
HOMES = ("home-01", "home-02", "home-03")
NOW, SALE = "2025-01-27 12:00", "2025-01-28 17:00"            # the market's clock, and the start of tomorrow evening's sale
DEF = {"id": "community-1", "point": "feeder-1", "limit_out_kw": 8.0, "members": [{"member": h, "devices": [{"kind": "battery", "kw": 5.0, "kwh": 13.5}]} for h in HOMES]}


def stored(*kws: float) -> list[dict]:
    """An offer's half hours from 0, all of it from the battery, so all of it firm."""
    return [{"id": i, "kw_offered": kw, "battery_kw": kw} for i, kw in enumerate(kws)]


OFFERS = {"home-01": stored(6.0, 4.0), "home-02": stored(4.0, 8.0), "home-03": stored(2.0, 2.0)}       # a pool of 12 kW in the first half hour, 14 kW in the second


def order(eid: str, kws: list[float], commit_by: str = "2025-01-27 16:00", deposit: float | None = None) -> dict:
    """A buyer's on_discover holding one order from SALE at $0.50 a kWh, in a catalog's shape."""
    pay = lambda kw: [{"type": t, "values": [v]} for t, v in (("CAPACITY_REQUESTED", kw), ("PRICE", 0.5), ("SHORTFALL_PENALTY", 0.0))]  # noqa: E731
    res = {"id": eid, "descriptor": {"name": "order"},
           "resourceAttributes": {"intervalPeriod": {"start": beckn.utc_from_local(SALE)}, "intervals": [{"id": k, "payloads": pay(kw)} for k, kw in enumerate(kws)]}}
    off = {"id": f"offer-{eid}", "resourceIds": [eid], "validity": {"endDate": beckn.utc_from_local(commit_by)}, "offerAttributes": {
        "inputs": [{"role": "buyer", "participantId": "utility", "inputs": {"currency": "USD"}}], "contractAttributes": {"policy": {}}, **({"deposit": {"usd": deposit}} if deposit else {})}}
    return {"context": {"transactionId": "discover-2025-01-27"}, "message": {"catalogs": [{"resources": [res], "offers": [off]}]}}


def sale(tmp, kws=(10.0, 10.0), deposit=None, rated=None, community=None, **cfg) -> Market:
    """A pooled market on a held clock whose buyer has ordered sale-1. No bus: what it sends lands in market.sent."""
    clock = Replay("homes/HH001", NOW, 60, 0)
    clock.configure(NOW, 60, 0, hold=True)
    m = Market("community", signing.load_or_create(tmp / "community.key"), lambda *a: m.sent.append(a), clock, list(HOMES), {}, lambda: None, lambda *a, **k: None,
               {"buyers": ["utility"], "sync_broadcast": True, "community_forecast": False, **cfg})
    m.sent, m.rated, m.community = [], rated or {}, community
    m.from_utility("on_discover", order("sale-1", list(kws), deposit=deposit), "utility")
    return m


def offer(m: Market, tmp, h: str, slots: list[dict], **more) -> str:
    """A member's signed offer for sale-1, through the market's door."""
    o = {"event_id": "sale-1", "home": h, "slots": slots, "confidence": 0.9, "energy_kwh": 0.5 * sum(x["kw_offered"] for x in slots), **more}
    body = beckn.make("on_discover", sender=h, receiver="community", transaction_id="community-sale-1", message={"offer": o}, key=signing.load_or_create(tmp / f"{h}.key"))
    return m.handle("beckn.on_discover", h, body)


def cleared(m: Market, tmp, offers: dict[str, list[dict]]) -> dict:
    """sale-1 cleared over these offers, arriving in this order."""
    for h, slots in offers.items():
        offer(m, tmp, h, slots)
    m.clear("sale-1")
    return m.events["sale-1"]


def cars(tmp, max_kw: dict[str, float], noev: list[float]) -> dict:
    """sale-1, one half hour of 1 kW, cleared over members that each pause a car needing 2 kWh by 20:00, offers arriving in this order; each one's evening from 17:30 reads noev."""
    m = sale(tmp, kws=(1.0,))
    for h, kw in max_kw.items():
        offer(m, tmp, h, [{"id": 0, "kw_offered": 3.0, "battery_kw": 1.0, "ev_pause_kw": 2.0}], ev_flex={"kwh": 2.0, "max_kw": kw, "latest_finish": "2025-01-28 20:00"},
              evening={"import_cf_kw": noev, "import_noev_kw": noev, "rebound_kw": {"1.0": [0.0] * len(noev)}})
    m.clear("sale-1")
    return m.events["sale-1"]


GOOD = {"slots": [{"id": 0, "kw_offered": 3.0, "battery_kw": 2.0, "ev_pause_kw": 1.0}], "confidence": 0.9, "energy_kwh": 1.5, "held_back_kw": {"0": 0.5},
        "evening": {"import_cf_kw": [4.0, 3.0], "import_noev_kw": [3.0, 3.0], "rebound_kw": {"0.5": [0.5, 0.2], "1.0": [1.0, 0.4]}},
        "ev_flex": {"kwh": 6.0, "max_kw": 7.2, "latest_finish": "2025-01-29 06:00", "arrival": "2025-01-28 18:00"}}
EVENING, CAR = "an evening the rebound guard can't read", "a car the evening's restart can't place"
but = lambda part, **kw: {**GOOD, part: [{**GOOD[part][0], **kw}] if part == "slots" else {**GOOD[part], **kw}}       # noqa: E731  GOOD with one part changed


def test_a_whole_number_is_an_int_a_number_is_finite_neither_is_a_bool_and_an_amount_is_a_number_not_below_zero():
    assert [mr.whole(v) for v in (0, 7, True, 7.0, "7", None)] == [True, True, False, False, False, False]
    assert [cr.number(v) for v in (0, -2.5, True, NAN, math.inf, "1")] == [True, True, False, False, False, False]
    assert [cr.amount(v) for v in (0, 2.5, -0.1, NAN)] == [True, True, False, False]


@pytest.mark.parametrize("o, x, firm", [({}, {"kw_offered": 5.0, "firm_kw": 7.0}, 5.0), ({}, {"kw_offered": 5.0, "firm_kw": -1.0}, 0.0), ({}, {"kw_offered": 5.0, "battery_kw": 9.0}, 5.0),
                                        ({"node": "building"}, {"kw_offered": 5.0, "firm_kw": 1.0}, 1.0), ({}, {"kw_offered": 5.0, "battery_kw": 2.0, "ac_kw": 3.0}, 2.0),
                                        ({"node": "building"}, {"kw_offered": 5.0, "battery_kw": 2.0}, 2.0 + 3.0 * 0.534)])
def test_the_firm_part_is_the_nodes_own_estimate_else_what_is_stored_plus_a_buildings_signed_off_share(o, x, firm):
    assert mr.firm_part(o, x) == pytest.approx(firm)


@pytest.mark.parametrize("o, rated, why", [
    (GOOD, 10.0, None), (but("evening", import_cf_kw=[4.0, 11.0]), None, None), (but("evening", import_cf_kw=[4.0, 2e9]), None, EVENING),
    (but("evening", import_cf_kw=[4.0, 11.0]), 10.0, EVENING), (but("ev_flex", max_kw=12.0), 10.0, CAR), ({**GOOD, "slots": []}, 10.0, "no slots"),
    (but("slots", id=True), 10.0, "a slot without a real id and kW"), (but("slots", kw_offered=-1.0), 10.0, "a slot without a real id and kW"),
    (but("slots", kw_offered=NAN), 10.0, "a slot without a real id and kW"), (but("slots", id=4), 10.0, "a slot this sale doesn't have: 4"),
    (but("slots", battery_kw=NAN), 10.0, "a slot with a part that isn't a real kW"), ({**GOOD, "slots": GOOD["slots"] * 2}, 10.0, "the same slot twice"),
    ({**GOOD, "confidence": NAN}, 10.0, "no real confidence or energy"), ({**GOOD, "energy_kwh": -1.0}, 10.0, "no real confidence or energy"),
    ({**GOOD, "held_back_kw": {"0": -0.5}}, 10.0, "a held-back figure that isn't a real kW"), (but("evening", import_noev_kw=[3.0]), 10.0, EVENING),
    (but("evening", rebound_kw={"1.5": [1.0, 0.4]}), 10.0, EVENING), (but("ev_flex", max_kw=0.0), 10.0, CAR), (but("ev_flex", kwh=400.0), 10.0, CAR),
    (but("ev_flex", latest_finish="tomorrow"), 10.0, CAR)])
def test_a_good_offer_is_taken_and_numbers_that_would_spread_through_the_book_or_pass_the_nameplate_on_file_are_refused(o, rated, why):
    assert mr.offer_problem(o, {0, 1}, rated) == why


NEED = {"event_id": "sale-1", "offer_id": "offer-sale-1", "name": "order", "currency": "USD", "slots": [{"id": k, "kw_requested": 10.0, "price": 0.5, "penalty": 0.0} for k in range(2)]}
every = lambda **kw: {**NEED, "slots": [{**s, **kw} for s in NEED["slots"]]}      # noqa: E731  NEED with each of its half hours changed


@pytest.mark.parametrize("n, deposit, why", [
    (NEED, None, None), (NEED, 25.0, None), ({**NEED, "event_id": ""}, None, "no id that can be read"),
    ({**NEED, "slots": NEED["slots"][::-1]}, None, "half hours that aren't numbered from 0"), ({**NEED, "slots": []}, None, "half hours that aren't numbered from 0"),
    (every(kw_requested=NAN), None, "a kW that isn't real"), (every(kw_requested=-1.0), None, "a kW that isn't real"), (every(price=0.0), None, "a price that isn't real"),
    (every(penalty=-0.1), None, "a penalty that isn't real"), ({**NEED, "currency": None}, None, "a name or a currency that can't be read"),
    (NEED, NAN, "a deposit that isn't real"), (NEED, -1.0, "a deposit that isn't real")])
def test_a_good_order_is_taken_and_one_with_reversed_half_hours_or_a_number_that_would_stop_the_market_is_refused(n, deposit, why):
    assert mr.need_problem(n, deposit) == why


def test_an_order_too_late_to_collect_offers_with_a_number_that_is_not_real_or_over_an_open_sale_opens_no_sale(tmp_path):
    m = sale(tmp_path)                       # late-1's clearing would have had to start 180 minutes before 14:00, before the clock's 12:00
    for eid, kws, by in (("late-1", [5.0], "2025-01-27 14:00"), ("bad-1", [-5.0], "2025-01-27 16:00"), ("wide-1", [5.0] * 3, "2025-01-27 16:00")):
        m.from_utility("on_discover", order(eid, kws, by), "utility")
    assert sorted(m.events) == ["sale-1"] and m.too_late == {"late-1"}
    assert m.orders_refused == {"bad-1": {"buyer": "utility", "why": "a kW that isn't real", "until": "2025-01-28 17:30"},
                                "wide-1": {"buyer": "utility", "why": "its window overlaps the sale sale-1 in phase offers", "until": "2025-01-28 18:30"}}


@pytest.mark.parametrize("member, more", [("a home", {}), ("home-01", {"connects_at": "feeder-2"}), ("home-01", {"devices": [{"kind": "battery", "kw": 5.0, "make": "x"}]}),
                                          ("home-01", {"devices": [{"kind": "sauna", "kw": 5.0}]}), ("home-01", {"devices": [{"kind": "battery", "kw": -5.0}]}),
                                          ("home-01", {"sales": ["day_trading"]}), ("home-01", {"pay_share": 1.5})])
def test_enrol_takes_only_an_id_with_kinds_and_sizes_of_device_behind_this_communitys_connection(member, more):
    with pytest.raises(ValueError):
        Members("feeder-1").enrol(member, **{"connects_at": "feeder-1", "devices": [], **more})


@pytest.mark.parametrize("opt_out, why", [({"sale": "sale-1"}, "opted out of this sale"), ({"day": "2025-01-28"}, "opted out for this day"),
                                          ({"until": "2025-01-28 18:00"}, "opted out until a later time"), ({"until": SALE}, None), ({}, "opted out")])
def test_an_opt_out_on_the_member_record_kept_between_runs_keeps_that_members_offer_out(tmp_path, opt_out, why):
    path = tmp_path / "members.json"
    Members("feeder-1", path).enrol("home-01", connects_at="feeder-1", devices=[])
    kept = json.loads(path.read_text())
    kept["members"]["home-01"]["opt_outs"] = [opt_out]
    path.write_text(json.dumps(kept))
    assert Members("feeder-1", path).refuses("home-01", {"id": "sale-1", "kind": "evening_sale", "day": "2025-01-28", "start": SALE}) == why


def test_define_builds_the_community_its_battery_its_meter_and_its_member_record():
    c = cm.define({**DEF, "limit_in_kw": 12.0, "battery": {"rating_kw": 20.0, "energy_kwh": 80.0, "out_factor": 0.894}, "meter": {"2025-01-28T17:00": -3.5}})
    assert (c.limit_out_kw, c.limit_in_kw, c.battery, c.meter.at(SALE)) == (8.0, 12.0, cm.Battery(20.0, 80.0, 0.894), -3.5)
    assert c.members.view() == {"members": 3, "agreed": {"evening_sale": 3}, "opted_out": 0, "devices": {"battery": 3}, "kw_on_record": 15.0, "changes": 3}


@pytest.mark.parametrize("change", [{"id": "a community"}, {"point": None}, {"limit_out_kw": 0}, {"limit_in_kw": NAN}, {"solar_kw": -1.0}, {"report_when_ended": "yes"},
                                    {"battery": {"rating_kw": 20.0, "energy_kwh": 80.0, "out_factor": 1.2}}, {"members": [{"member": "home-01", "connects_at": "feeder-2"}]},
                                    {"battery": {"rating_kw": 20.0, "energy_kwh": 80.0, "in_factor": 0.9, "run_by_agent": True}}, {"aggregator": {"id": "aggregator-1", "public_key": "x"}}])
def test_define_refuses_a_definition_that_does_not_hold(change):
    with pytest.raises(ValueError):
        cm.define({**DEF, **change})


def test_for_agent_stands_for_the_configured_community_and_keeps_its_record_between_runs(tmp_path):
    said: list = []
    log = lambda kind, **k: said.append(kind)  # noqa: E731
    assert cm.for_agent({}, tmp_path, log) is None and said == ["community_not_defined"]
    cm.for_agent({"community": DEF}, tmp_path, log).record_sale("sale-1", SALE, 13.0, 8.9)
    again = cm.for_agent({"community": {**DEF, "members": []}}, tmp_path, log)
    assert sorted(again.members.rows) == list(HOMES) and again.sales == [{"sale": "sale-1", "start": SALE, "delivered_kw": None, "offered_kw": 13.0, "promised_kw": 8.9}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["community_members.json", "community_sales.json"]


def history(c: cm.Community, *shares: float) -> None:
    """Sales on 10, 11, 12 ... January, each 10 kW offered and 9 kW promised, that delivered these shares of the offer, each result in at 19:00."""
    for i, s in enumerate(shares):
        day = beckn.add_minutes("2025-01-10 00:00", 1440 * i)[:10]
        c.record_sale(f"old-{i}", f"{day} 17:00", 10.0, 9.0)
        c.sale_delivered(f"old-{i}", 10.0 * s, at=f"{day} 19:00")


def test_the_cover_is_the_fixed_margin_until_three_sales_are_on_record_then_never_more_generous_than_the_last_ten():
    c, longer = cm.define(DEF), cm.define(DEF)
    history(c, 0.8, 0.95, 0.7)
    history(longer, 0.5, *[0.95] * 10)
    assert c.cover(0.10) == {"share": 0.7, "by": "the record", "lowest_delivered_share": 0.7, "sales_on_record": 3}
    assert c.cover(0.50) == {"share": pytest.approx(1 / 1.5), "by": "the fixed margin", "lowest_delivered_share": 0.7, "sales_on_record": 3}
    assert c.cover(0.10, before="2025-01-12 17:00") == {"share": pytest.approx(1 / 1.1), "by": "the fixed margin", "sales_on_record": 2}
    assert c.cover(0.10, known_by="2025-01-12 18:00")["sales_on_record"] == 2          # the third result was not in when this clearing ran
    assert longer.cover(0.0)["share"] == 0.95                                           # its first sale, at 50 %, is the eleventh back
    assert c.gaps[-1] == {"sale": "old-2", "start": "2025-01-12 17:00", "promised_kw": 9.0, "delivered_kw": 7.0, "gap_kw": -2.0}


@pytest.mark.parametrize("args, out", [
    ((1.0, 2.0, 3.0, 6.0), {"battery_kw": 2.0, "sale_kw": 3.0, "net_kw": 6.0, "cut": None}),
    ((2.0, 3.0, 4.0, 6.0), {"battery_kw": 0.0, "sale_kw": 4.0, "net_kw": 6.0, "cut": {"battery_kw": 3.0}}),
    ((5.0, 2.0, 4.0, 6.0), {"battery_kw": 0.0, "sale_kw": 1.0, "net_kw": 6.0, "cut": {"battery_kw": 2.0, "sale_kw": 3.0}}),
    ((8.0, 0.0, 1.0, 6.0), {"battery_kw": 0.0, "sale_kw": 0.0, "net_kw": 8.0, "cut": {"sale_kw": 1.0, "still_over_kw": 2.0}}),
    ((-10.0, -4.0, 0.0, 6.0, 12.0), {"battery_kw": -2.0, "sale_kw": 0.0, "net_kw": -12.0, "cut": {"charging_kw": 2.0}})])
def test_at_the_connection_the_battery_gives_way_before_the_sale_and_charges_less_to_keep_under_the_draw_limit(args, out):
    assert cm.fit(*args) == out


def test_a_report_row_is_rounded_quotes_by_the_sign_of_its_net_power_and_names_no_member_and_its_line_says_the_promise_and_the_cover():
    r = cr.row("community-1", SALE, -3.14159, 55.5551, 0.1234567, "a line", meter_kw=-3.14159, members=HOMES)
    assert r == {"entity_id": "community-1", "timestamp": SALE, "reported_p_net_kw": -3.142, "reported_soc_percent": 55.56, "quote_side": "buy",
                 "quote_price_usd_kwh": 0.123457, "text": "a line", "meter_p_net_kw": -3.142}
    assert [cr.row("community-1", SALE, kw, None, None, "home-010 sold", members=["home-01"])["quote_side"] for kw in (2.0, None)] == ["sell", None]
    pytest.raises(ValueError, cr.row, "community-1", SALE, 2.0, None, None, "home-01 gave most", members=HOMES)
    assert cr.line(3, 1234.4, 56.6, 7.0, "2025-01-28 18:00") == "community coordinator: 3 members promise 1,234 kW until 18:00, 57 kW held as cover; battery gives 7 kW"


def test_the_door_refuses_strangers_members_without_a_nameplate_or_the_records_word_and_a_slot_the_sale_does_not_have(tmp_path):
    c = cm.define({**DEF, "members": [{"member": "home-01"}, {"member": "home-02", "sales": ["grid_call"]}]})
    m = sale(tmp_path, rated={"home-01": 20.0, "home-02": 20.0}, community=c)
    said = [offer(m, tmp_path, h, stored(*kw)) for h, kw in (("home-09", [2.0]), ("home-03", [2.0]), ("home-02", [2.0]), ("home-01", [2.0] * 3), ("home-01", [6.0, 4.0]))]
    assert said == ["offer refused: not a member", "offer refused: no nameplate on file", "offer refused: has not agreed to this kind of sale",
                    "offer refused: a slot this sale doesn't have: 2", "offer from home-01: 5.0 kWh"]
    assert list(m.events["sale-1"]["offers"]) == ["home-01"]


@pytest.mark.parametrize("kw, alloc, cap", [
    (10.0, {"home-01": {0: 5.5, 1: 3.143}, "home-02": {0: 3.667, 1: 6.286}, "home-03": {0: 1.833, 1: 1.571}}, {0: 10.0, 1: 10.0}),     # 11/12, then 11/14 of each offer
    (20.0, {h: {x["id"]: x["kw_offered"] for x in s} for h, s in OFFERS.items()}, {0: 12.0, 1: 14.0})])                              # a short pool: all of each offer
def test_the_clearing_asks_each_member_its_offer_times_the_order_and_margin_over_the_pool_and_never_more_than_it_offered(tmp_path, kw, alloc, cap):
    ev = cleared(sale(tmp_path, kws=(kw, kw)), tmp_path, OFFERS)
    assert (ev["alloc"], ev["capacity_offered"]) == (alloc, cap)


def test_an_offer_above_the_members_nameplate_counts_only_up_to_it(tmp_path):
    ev = cleared(sale(tmp_path, kws=(10.0,), rated={"home-01": 3.0, "home-02": 30.0, "home-03": 30.0}), tmp_path, {h: s[:1] for h, s in OFFERS.items()})
    assert ev["alloc"] == {"home-01": {0: 3.0}, "home-02": {0: 4.0}, "home-03": {0: 2.0}} and ev["capacity_offered"] == {0: 9.0}


@pytest.mark.parametrize("deposit, alloc, cap, back", [(None, {"home-01": {0: 6.0}}, 6.0, 0.0), (0.05, {"home-01": {0: 6.0}, "home-02": {0: 2.8}}, 8.0, 0.0),
                                                       (1.0, {"home-01": {0: 6.0}, "home-02": {0: 5.0}}, 10.0, 0.9)])
def test_tentative_power_is_sold_only_as_far_as_the_buyers_deposit_holds_it_and_what_it_cannot_hold_goes_back(tmp_path, deposit, alloc, cap, back):
    # a kW held takes $0.025 (10 % of $0.50 a kWh, half an hour): $0.05 holds 2 of the 4 kW the firm 6 leave, $1 all 4 and $0.90 back; 10 % margin on top
    ev = cleared(sale(tmp_path, kws=(10.0,), deposit=deposit), tmp_path, {"home-01": stored(6.0), "home-02": [{"id": 0, "kw_offered": 8.0, "ac_kw": 8.0}]})
    assert (ev["alloc"], ev["capacity_offered"], ev["orders"]["utility"]["deposit_back_usd"]) == (alloc, {0: cap}, back)


def test_a_second_buyers_order_on_the_same_window_joins_the_sale_and_the_firm_pool_goes_to_the_orders_in_proportion_to_their_size(tmp_path):
    m = sale(tmp_path, buyers=["utility", "grid-op"])
    m.from_utility("on_discover", order("sale-2", [5.0, 5.0]), "grid-op")         # 15 kW asked of a firm pool of 12, then 14 kW: all of it sold, 10 / 15 to the bigger order
    firm = {b: {k: round(v, 2) for k, v in od["firm"].items()} for b, od in cleared(m, tmp_path, OFFERS)["orders"].items()}
    assert (sorted(m.events), m.events["sale-1"]["capacity_offered"], firm) == (["sale-1"], {0: 12.0, 1: 14.0}, {"utility": {0: 8.0, 1: 9.33}, "grid-op": {0: 4.0, 1: 4.67}})


def test_whichever_offer_arrives_first_the_clearing_is_the_same_equal_offers_are_asked_alike_and_the_contracts_go_out_in_name_order(tmp_path):
    offers = {**OFFERS, "home-03": OFFERS["home-02"]}
    runs = [cleared(sale(tmp_path), tmp_path, {h: offers[h] for h in arrival}) for arrival in itertools.permutations(offers)]
    assert all((ev["alloc"], ev["capacity_offered"]) == (runs[0]["alloc"], runs[0]["capacity_offered"]) for ev in runs)
    assert runs[0]["alloc"]["home-02"] == runs[0]["alloc"]["home-03"] == {0: 3.143, 1: 4.4}
    m = sale(tmp_path)
    ev = cleared(m, tmp_path, dict(reversed(OFFERS.items())))
    m.commit_to_utility("sale-1")
    for act, status in (("on_select", None), ("on_init", None), ("on_confirm", "ACTIVE")):
        m.from_utility(act, {"context": {"transactionId": ev["utxn"]}, "message": {"contract": {"status": status}}}, "utility")
    assert ev["phase"] == "homes" and [to for to, kind, *_ in m.sent if kind == "beckn.confirm" and to != "utility"] == list(HOMES)


def test_a_paused_car_restarts_in_the_first_valley_that_keeps_the_evenings_peak_lowest_and_cars_that_need_the_same_energy_go_by_name(tmp_path):
    ev = cars(tmp_path, {"home-01": 4.0}, [3.0, 3.0] + [1.0] * 6)       # 2 kWh at 4 kW is two quarter hours: 7 kW at 17:30 or 17:45, 5 kW from 18:00
    assert ev["ev_restart"] == {"home-01": "2025-01-28 18:00"} and ev["guard"]["peak_forecast_kw"] == 5.0
    kw, flat = {"home-01": 4.0, "home-02": 8.0}, [1.0] * 8              # 2 kWh each: home-01 first, then home-02's 8 kW in the first quarter hour still at 2 kW
    assert cars(tmp_path, kw, flat)["ev_restart"] == cars(tmp_path, dict(reversed(kw.items())), flat)["ev_restart"] == {"home-01": "2025-01-28 17:30", "home-02": "2025-01-28 18:00"}


def test_the_community_promises_no_more_than_its_cover_and_connection_allow_and_each_quarter_hours_row_says_so(tmp_path):
    c = cm.define({**DEF, "meter": {SALE: 0.0, "2025-01-28 17:15": -1.0}})        # 8 kW out at most, its meter read at 17:00 and 17:15 and not in the second half hour
    history(c, 0.8, 0.95, 0.7)
    m = sale(tmp_path, community=c)
    ev = cleared(m, tmp_path, OFFERS)
    assert ev["cover"]["cut"] == {0: {"from_kw": 10.0, "to_kw": 8.4}, 1: {"from_kw": 10.0, "to_kw": 9.8}}            # 70 % of 12 and of 14 kW
    assert ev["connection_limit"]["cut"] == {0: {"from_kw": 8.4, "to_kw": 8.0, "why": "the utility's limit at the connection"}} and ev["connection_limit"]["not_checked"] == [1]
    assert ev["capacity_offered"] == {0: 8.0, 1: 9.8} and ev["alloc"] == {"home-01": {0: 5.238, 1: 3.143}, "home-02": {0: 3.492, 1: 6.286}, "home-03": {0: 1.746, 1: 1.571}}
    assert c.sales[-1] == {"sale": "sale-1", "start": SALE, "delivered_kw": None, "offered_kw": 13.0, "promised_kw": 8.9}
    rows = [c.step(m, t) for t in ("2025-01-28 17:05", "2025-01-28 17:10", "2025-01-28 17:15", "2025-01-28 18:00")]
    promise = "community coordinator: 3 members promise 8 kW until 18:00, 2 kW held as cover; battery gives 0 kW"    # 10.476 kW asked against 8 kW promised
    assert rows[1] is None and [(r["timestamp"], r["text"], r["quote_side"]) for r in rows if r] == [
        (SALE, promise, "sell"), ("2025-01-28 17:15", promise, "buy"), ("2025-01-28 18:00", cr.NO_METER, None)]


def test_a_community_forecast_that_cannot_be_made_leaves_the_sale_open_and_says_why(tmp_path):
    m = sale(tmp_path, community_forecast=True)              # the test dataset has no trained models
    assert m.events["sale-1"]["phase"] == "offers" and list(m.events["sale-1"]["outlook"]) == ["error"] and [s[0] for s in m.sent] == list(HOMES)


def town(n: int, gaps=(), zero=()) -> cf._Community:
    """n synthetic days of a community from 1 February 2025, its load rising with the issued forecast's heating degrees. gaps: (day, hour) not in the file; zero: read as 0 kW."""
    comm, temp = cf._Community.__new__(cf._Community), lambda i, h: (i * 7) % 11 - 6.0 - abs(h - 14) / 2
    comm.sessions, comm.rows = [], [{"ts_local": f"{d} {q // 4:02d}:{15 * (q % 4):02d}", "fc_temp_c": temp(i, q // 4), "pv_kw": 0.0,
                                     "base_kw": 0.0 if (d, q // 4) in zero else (20.0 + 1.5 * max(10.0 - temp(i, q // 4), 0.0)) * (1 + 0.03 * (i % 4))}
                                    for i, d in enumerate(beckn.add_minutes("2025-02-01 00:00", 1440 * k)[:10] for k in range(n)) for q in range(96) if (d, q // 4) not in gaps]
    comm.index = {r["ts_local"]: k for k, r in enumerate(comm.rows)}
    return comm


def test_fit_days_are_the_last_whole_days_before_the_issue_newest_first_and_never_a_kept_one():
    days = cf.fit_days(town(40, gaps={("2025-03-01", 7)}), "2025-03-10 10:00", {"2025-03-05"})
    assert days[:5] == ["2025-03-09", "2025-03-08", "2025-03-07", "2025-03-06", "2025-03-04"] and days[-1] == "2025-02-01"
    assert len(days) == 35 and "2025-03-01" not in days                  # 37 days were over: one kept, one missing an hour
    assert len(cf.fit_days(town(70), "2025-04-01 10:00", set())) == cf.FIT_DAYS


def test_the_communitys_own_fit_gives_a_finite_non_negative_range_and_leaves_out_what_it_cannot_read():
    comm = town(40, gaps={("2025-03-10", 18)}, zero={("2025-03-04", 19)})
    days = cf.fit_days(comm, "2025-03-10 10:00", set())
    fit = cf.own_fit(comm, set(), "2025-03-10", days)
    assert fit[18] is None and fit[19]["dropped"] == 1 and all("dropped" not in x for h, x in enumerate(fit) if h not in (18, 19))
    assert all(0 < x["p10_kw"] <= x["p50_kw"] <= x["p90_kw"] < math.inf for x in fit if x)
    assert cf.own_fit(comm, set(), "2025-03-10", days[:cf.FIT_MIN - 1]) == [None] * 24


@pytest.mark.parametrize("n, day, days_read, how, peak", [(40, "2025-03-10", 35, "the community's own fit on its last days", "18:00"), (15, "2025-02-10", 0, "model", "15:00")])
def test_the_forecast_is_its_own_fit_once_21_days_are_left_after_the_kept_ones_else_the_models_with_the_earliest_of_equal_peaks(monkeypatch, n, day, days_read, how, peak):
    comm, trees = town(n), SimpleNamespace(holidays=set(), last={"how": "model"}, forecast=lambda now, ts: {t: {"load": [1.0, 2.0, 3.0]} for t in ts})     # no trained models here
    monkeypatch.setattr(cf, "_setup", lambda members=(): (comm, trees, 3))
    monkeypatch.setattr(cf, "_kept_out", lambda: {"2025-03-05"})
    f = cf.forecast(day)
    assert (f["days_read"], f["how"], f["stand_in"], f["peak_window"]["start"]) == (days_read, how, False, peak)
    assert all(math.isfinite(x[k]) and x[k] >= 0 for x in f["hours"] for k in ("p10_kw", "p50_kw", "p90_kw")) and len(f["hours"]) == 24

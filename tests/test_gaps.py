"""Gap filling at the community's real-time desk, driven through the community market the way its service drives it: signed messages in, the tick.

A buyer's call is asked of every member and filled from the biggest answers up to the call and its margin, each answer held to the member's nameplate.
A member that will fall short reports it; the report counts for what the member owes and no more, the other members are asked, and the gap is filled
up to what they say they can give, spread over the short steps and owed under the call it covers. What nobody can give is offered up the price ladder,
then stays open and the buyer is warned. A gap offered again at a higher price asks only the members not yet dispatched for it and is filled once each
of them has answered, on the step the clock holds; an answer that comes again from a member already dispatched is refused, not dispatched twice.
A shortfall within the sale's margin, or past it by under half a kW, moves no power. A call's settlement pays
each node the desk dispatched, on its measured kWh at the call's price times its class's share, and a top-up only what a node's new share adds; a gap
filled at a raised price under a booked sale earns its helper the step up on what it delivered beyond its booking, out of the coordinator's keep. A
repeated call, answer, end or settlement changes nothing. Answers for a gap that does not exist, from a member not asked, under another key or past
their time, reports older than the one in, and calls that overlap another or come after their window are refused.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from murmur.agents.community.conductor import Conductor
from murmur.agents.community.gaps_rules import real, steps_between
from murmur.agents.community.market import Market
from murmur.protocol import envelope as beckn
from murmur.protocol import signing

DAY = "2025-01-28"
Q = [f"{DAY} 17:{m}" for m in ("00", "15", "30", "45")]          # the call's four quarter hours
END = f"{DAY} 18:00"
CALL = {"id": "call-1", "kind": "short_notice", "start": Q[0], "end": END, "kw": 10.0, "price_usd_per_kwh": 0.8, "why": "peak"}
MEMBERS = ("home-01", "home-02", "home-03")


class Clock:
    """The market's dataset clock, held on one step that a test moves by hand."""

    def __init__(self, at: str):
        self.at = at

    def current(self) -> int:
        return 0

    def ts(self, i: int) -> str:
        return self.at


class Desk:
    """A pooled community market on the fixture's three homes, with the nameplates on file as its service sets them: each member and the buyer
    sign with a key of their own, and every message the market sends is kept as (to, action, message)."""

    def __init__(self, folder, **cfg):
        self.keys = {n: signing.load_or_create(folder / f"{n}.key") for n in (*MEMBERS, "home-04", "utility", "community")}
        self.clock, self.sent = Clock(f"{DAY} 16:00"), []
        self.m = Market("community", self.keys["community"], lambda to, kind, body, mid: self.sent.append((to, beckn.action_of(kind), body["message"])),
                        self.clock, list(MEMBERS), {}, lambda: None, lambda *a, **k: None, {"sync_broadcast": True, "buyers": ["utility"], **cfg})
        self.m.rated = {"home-01": 6.0, "home-02": 8.0, "home-03": 4.0}

    def say(self, sender, action, message, key=None, wall=None):
        """A signed message from sender to the community, as the inbox hands it to the market; the market's answer."""
        body = beckn.make(action, sender=sender, receiver="community", transaction_id="t", message=message, key=key or self.keys[sender], wall=wall)
        return self.m.handle(beckn.kind(action), sender, body)

    def out(self, action, part):
        """(to, message[part]) for each message of this action the market sent that carries part."""
        return [(to, msg[part]) for to, a, msg in self.sent if a == action and part in msg]


@pytest.fixture
def desk(tmp_path):
    return Desk(tmp_path)


def called(d, *answers):
    """The buyer's 10 kW call for 17:00-18:00 at $0.80/kWh, then each member's answer in turn: by default home-02 9 kW (its nameplate is 8),
    home-01 6 kW and home-03 nothing."""
    d.say("utility", "rt_call", {"call": CALL})
    for h, kw in answers or (("home-02", 9.0), ("home-01", 6.0), ("home-03", 0.0)):
        d.say(h, "rt_answer", {"answer": {"id": "call-1", "kw": kw}})


def gap_of(d, home, short):
    """home reports its shortfall, the market ticks, and the gap the desk opened."""
    d.say(home, "rt_capacity", {"short": short})
    d.m.tick()
    return next(r for r in d.m.rt.calls.values() if r["kind"] == "gap")


def filled(d):
    """The call, then home-02 (dispatched 8 kW) says it gives 4 kW less at 17:30 and claims 12 kW short at 17:45 and 3 kW at 18:00;
    the gap's answers: home-03 4 kW, home-01 2.5 kW."""
    called(d)
    gap = gap_of(d, "home-02", {Q[2]: 4.0, Q[3]: 12.0, END: 3.0})
    for h, kw in (("home-03", 4.0), ("home-01", 2.5)):
        d.say(h, "rt_answer", {"answer": {"id": gap["id"], "kw": kw}})
    return gap


def sale(d, owed):
    """A booked sale, 17:00-19:00 in four half hours at $0.80/kWh: each home owes owed[h] kW in every half hour, and 1 kW less than that was sold."""
    slots = [{"id": i, "start": beckn.add_minutes(Q[0], 30 * i), "price": 0.8} for i in range(4)]
    d.m.events["sale-1"] = {"need": {"event_id": "sale-1", "window_start": Q[0], "window_end": f"{DAY} 19:00", "slots": slots},
                            "commitments": {h: {"status": "ACCEPTED", "contract": {"commitments": [{"id": i, "kw": kw} for i in range(4)]}} for h, kw in owed.items()},
                            "offers": {}, "readings": {}, "baselines": {}, "finalized": True, "final_meters": sorted(owed),
                            "capacity_offered_final": {i: sum(owed.values()) - 1.0 for i in range(4)}}


def raised(folder, **cfg):
    """A desk whose clock waits (no dataset time passes that could close a round), with the booked sale; home-02 falls 4 kW short, 1 kW of it within
    the margin; home-01 covers 2 kW and home-03 says the price is under its minimum, so the 1 kW left is offered again at $1.00, to home-03 alone.
    On the quiet path the desk counts on half the margin, so 1.5 kW are left."""
    d = Desk(folder, clock_waits=True, **cfg)
    sale(d, {"home-01": 3.0, "home-02": 5.0, "home-03": 2.0})
    d.m.rt.settled = d.m.now()                                         # as the waiting clock says it: this step's reports are all in
    gap = gap_of(d, "home-02", {Q[2]: 4.0, Q[3]: 4.0})
    d.say("home-01", "rt_answer", {"answer": {"id": gap["id"], "kw": 2.0}})
    d.say("home-03", "rt_answer", {"answer": {"id": gap["id"], "kw": 0.0, "below_min_price": True}})
    return d, gap


def test_steps_between_lists_each_quarter_hour_from_the_start_up_to_but_not_including_the_end():
    assert steps_between(Q[0], END) == Q
    assert steps_between(f"{DAY} 23:30", "2025-01-29 00:15") == [f"{DAY} 23:30", f"{DAY} 23:45", "2025-01-29 00:00"]
    assert steps_between(f"{DAY} 17:05", Q[2]) == [f"{DAY} 17:05", f"{DAY} 17:20"]
    assert steps_between(Q[1], Q[1]) == [] and steps_between(Q[2], Q[1]) == []


def test_real_is_a_finite_number_and_anything_else_is_none():
    assert (real("2.5"), real(3), real(-1.25)) == (2.5, 3.0, -1.25)
    assert [real(v) for v in (None, "", "kw", float("nan"), float("inf"), -float("inf"), [1.0], {})] == [None] * 8


def test_a_call_is_asked_of_every_member_and_filled_from_the_biggest_answers_up_to_the_call_and_its_margin(desk):
    called(desk)
    assert [(to, a["price_usd_per_kwh"]) for to, a in desk.out("rt_ask", "ask")] == [(h, 0.8) for h in MEMBERS]
    # 10 kW and its 10 % margin are 11 kW: home-02's 9 kW is held to its 8 kW nameplate, home-01 gives the 3 kW left of its 6, home-03 nothing
    assert {to: x["steps"] for to, x in desk.out("rt_dispatch", "dispatch")} == {"home-02": dict.fromkeys(Q, 8.0), "home-01": dict.fromkeys(Q, 3.0)}
    assert desk.out("rt_confirm", "confirm") == [("utility", {"id": "call-1", "kw": 10.0, "short_kw": 0.0, "homes": ["home-01", "home-02"]})]


def test_a_shortfall_counts_for_what_is_owed_is_asked_of_the_others_filled_up_to_what_they_give_and_the_rest_reported(desk):
    gap = filled(desk)
    assert desk.m.rt.reports["home-02"] == {Q[2]: 4.0, Q[3]: 8.0}           # it owes 8 kW at 17:45 and nothing at 18:00
    assert [(to, a["price_usd_per_kwh"]) for to, a in desk.out("rt_ask", "ask") if a["id"] == gap["id"]] == [("home-01", 0.8), ("home-03", 0.8)]
    # 8 kW short at its worst: home-03's 4 kW and home-01's 2.5 kW, each at half of it at 17:30, where the shortfall is half
    assert {to: (x["id"], x["steps"]) for to, x in desk.out("rt_dispatch", "dispatch") if x["kind"] == "gap"} == {
        "home-03": ("call-1", {Q[2]: 2.0, Q[3]: 4.0}), "home-01": ("call-1", {Q[2]: 1.25, Q[3]: 2.5})}
    owes = {"home-02": dict.fromkeys(Q, 8.0), "home-01": {Q[0]: 3.0, Q[1]: 3.0, Q[2]: 4.25, Q[3]: 5.5}, "home-03": {Q[2]: 2.0, Q[3]: 4.0}}
    assert desk.m.rt.calls["call-1"]["alloc"] == owes and desk.out("rt_confirm", "dispatched")[-1] == ("utility", {"id": "call-1", "alloc": owes})
    assert desk.out("rt_confirm", "warning") == [("utility", {"id": gap["id"], "short_kw": 1.5, "start": Q[2], "end": END, "why": "not given"})]


def test_a_gap_the_others_can_cover_is_filled_from_the_biggest_answer_exactly_to_the_shortfall(desk):
    called(desk)
    gap = gap_of(desk, "home-02", {Q[2]: 2.0, Q[3]: 4.0})
    for h, kw in (("home-01", 2.5), ("home-03", 4.0)):
        desk.say(h, "rt_answer", {"answer": {"id": gap["id"], "kw": kw}})
    assert {to: x["steps"] for to, x in desk.out("rt_dispatch", "dispatch") if x["kind"] == "gap"} == {"home-03": {Q[2]: 2.0, Q[3]: 4.0}}
    assert (gap["confirmed_kw"], gap["short_kw"], gap["round"]) == (4.0, 0.0, 0) and desk.out("rt_confirm", "warning") == []


def test_a_gap_nobody_can_fill_is_offered_up_the_price_ladder_then_left_open_and_reported(desk):
    called(desk)
    gap = gap_of(desk, "home-02", {Q[2]: 4.0, Q[3]: 8.0})
    for _ in range(3):
        for h in ("home-01", "home-03"):
            desk.say(h, "rt_answer", {"answer": {"id": gap["id"], "kw": 0.0}})
    assert [(to, a["price_usd_per_kwh"]) for to, a in desk.out("rt_ask", "ask") if a["id"] == gap["id"]] == [
        (h, price) for price in (0.8, 1.0, 1.2) for h in ("home-01", "home-03")]
    assert [x for _, x in desk.out("rt_dispatch", "dispatch") if x["kind"] == "gap"] == []
    assert desk.out("rt_confirm", "warning") == [("utility", {"id": gap["id"], "short_kw": 8.0, "start": Q[2], "end": END, "why": "not given"})]
    assert (gap["phase"], gap["round"], gap["confirmed_kw"]) == ("dispatched", 2, 0.0)


@pytest.mark.parametrize("path, left", [({}, 1.0), ({"report_rule": "exception"}, 1.5)])       # every member asked, and the quiet path a live run takes
def test_a_gap_offered_again_at_a_higher_price_is_filled_once_the_member_asked_again_has_answered_with_the_clock_still_held(tmp_path, path, left):
    d, gap = raised(tmp_path, **path)
    waits = Conductor(SimpleNamespace(market=d.m), wire_files=[]).market_waits      # what the waiting clock holds every clock for at the market
    assert [(to, a["price_usd_per_kwh"]) for to, a in d.out("rt_ask", "ask")] == [("home-01", 0.8), ("home-03", 0.8), ("home-03", 1.0)]
    assert (gap["phase"], gap["round"], gap["kw"]) == ("asking", 1, left) and waits(d.m.now()) == [f"call {gap['id']}: answers to come"]
    d.say("home-03", "rt_answer", {"answer": {"id": gap["id"], "kw": 1.5}})
    # the one member asked again has answered: filled at once, on the step the clock holds, and the clock has nothing left to wait for
    assert [(to, x["steps"], x["price_usd_per_kwh"]) for to, x in d.out("rt_dispatch", "dispatch")] == [
        ("home-01", {Q[2]: 2.0, Q[3]: 2.0}, 0.8), ("home-03", {Q[2]: left, Q[3]: left}, 1.0)]
    assert (gap["phase"], gap["short_kw"], d.m.now()) == ("dispatched", 0.0, f"{DAY} 16:00") and d.out("rt_confirm", "warning") == []
    assert waits(d.m.now()) == []


def test_a_member_dispatched_for_a_gap_is_not_asked_at_the_higher_price_and_its_answer_come_again_is_not_dispatched_twice(tmp_path):
    d, gap = raised(tmp_path)
    twice = d.say("home-01", "rt_answer", {"answer": {"id": gap["id"], "kw": 2.0}})      # its first answer, delivered a second time
    assert isinstance(twice, beckn.Refused) and twice == "answer ignored" and gap["answers"] == {} and gap["phase"] == "asking"
    d.say("home-03", "rt_answer", {"answer": {"id": gap["id"], "kw": 1.5}})
    assert gap["alloc"] == {"home-01": {Q[2]: 2.0, Q[3]: 2.0}, "home-03": {Q[2]: 1.0, Q[3]: 1.0}} and gap["asked_price"] == {"home-01": 0.8, "home-03": 1.0}
    assert [to for to, _ in d.out("rt_dispatch", "dispatch")] == ["home-01", "home-03"]


def test_on_the_quiet_path_a_member_that_just_said_it_has_nothing_is_not_asked_and_what_is_left_is_reported(tmp_path):
    d = Desk(tmp_path, report_rule="exception")
    called(d)                                                           # home-03 had nothing for the call at 16:00
    gap = gap_of(d, "home-02", {Q[2]: 4.0, Q[3]: 8.0})
    d.say("home-01", "rt_answer", {"answer": {"id": gap["id"], "kw": 2.5}})
    assert [to for to, a in d.out("rt_ask", "ask") if a["id"] == gap["id"]] == ["home-01"]
    assert {to: x["steps"] for to, x in d.out("rt_dispatch", "dispatch") if x["kind"] == "gap"} == {"home-01": {Q[2]: 1.25, Q[3]: 2.5}}
    assert d.out("rt_confirm", "warning") == [("utility", {"id": gap["id"], "short_kw": 5.5, "start": Q[2], "end": END, "why": "not given"})]


def test_a_shortfall_the_sales_margin_covers_to_within_half_a_kw_moves_no_power_and_one_past_that_is_a_gap(desk):
    sale(desk, {"home-01": 3.0, "home-02": 5.0, "home-03": 2.0})       # 10 kW owed in each half hour against 9 sold: 1 kW of margin
    desk.say("home-02", "rt_capacity", {"short": {Q[2]: 1.25, Q[3]: 1.25}}, wall=1.0)
    desk.m.rt.tick()                                                   # the 0.25 kW past the margin is under the 0.5 kW the desk moves at least
    assert desk.m.rt.calls == {} and desk.m.rt.absorbed == {Q[2]: 1.0, Q[3]: 1.0} and desk.out("rt_ask", "ask") == []
    desk.clock.at = f"{DAY} 16:05"
    desk.say("home-02", "rt_capacity", {"short": {Q[2]: 1.75, Q[3]: 1.75}}, wall=2.0)
    desk.m.rt.tick()                                                   # 0.75 kW past it is a gap, asked of the other two
    assert [(g["kw"], g["short_by_ts"]) for g in desk.m.rt.calls.values()] == [(0.75, {Q[2]: 0.75, Q[3]: 0.75})]
    assert [to for to, _ in desk.out("rt_ask", "ask")] == ["home-01", "home-03"]


PAID = {"call_id": "call-1", "paid_usd": 3.175, "full_price_usd": 7.6, "delivered_kwh": 9.5, "currency": "USD",       # the buyer's settlement of the filled call
        "by_home_kwh": {"home-01": 3.0, "home-02": 4.0, "home-03": 1.5, "home-04": 1.0}, "by_home_batt_kwh": {"home-02": 2.0}}


def test_a_call_pays_the_nodes_it_dispatched_the_price_on_their_measured_kwh_times_their_class_share_once(desk):
    filled(desk)
    assert desk.say("utility", "on_status", {"settlement": PAID}) == "call call-1: 3.175 USD to 3 homes"
    # $0.80 a kWh times 0.18375 (2 of home-02's kWh came from its battery: 0.7); home-02, dispatched 8 kWh, is paid on the 4 it gave; home-03 is paid
    # because the gap put it on the call; home-04 was never dispatched. The shares come to $2.2225 with home-04's $0.147, the bill to $2.2225 / 0.7
    paid = {to: (x["payment"], x["delivered_kwh"]) for to, x in desk.out("on_status", "settlement")}
    assert paid == {"home-01": (0.441, 3.0), "home-02": (1.414, 4.0), "home-03": (0.2205, 1.5)}
    assert desk.m.rt.calls["call-1"]["result"]["fee_usd"] == 1.0995 and "differs" not in desk.m.rt.calls["call-1"]     # the bill less what was paid: $3.175 - $2.0755 (home-04 was never dispatched)
    assert desk.say("utility", "on_status", {"settlement": PAID}) == "call call-1 already paid" and len(desk.out("on_status", "settlement")) == 3


def test_a_top_up_pays_each_node_only_what_its_new_share_adds_and_takes_nothing_back(desk):
    filled(desk)
    desk.say("utility", "on_status", {"settlement": PAID})
    late = {**PAID, "top_up": 1, "paid_usd": 3.28, "full_price_usd": 8.0, "delivered_kwh": 10.0, "by_home_kwh": {**PAID["by_home_kwh"], "home-01": 3.5}}
    # home-01's late half kWh: 3.5 x $0.80 x 0.18375 = $0.5145 owed, $0.441 of it paid; the other shares don't move, and the bill is $2.296 / 0.7
    assert desk.say("utility", "on_status", {"settlement": late}) == "call call-1: top-up to 1 homes"
    assert [(to, x["payment"], x["delivered_kwh"], x.get("top_up")) for to, x in desk.out("on_status", "settlement")][3:] == [("home-01", 0.0735, 3.5, 1)]
    assert desk.say("utility", "on_status", {"settlement": {**PAID, "top_up": 2}}) == "call call-1: top-up to 0 homes"      # back to $0.441: nothing taken back
    assert desk.say("utility", "on_status", {"settlement": late}) == "call call-1 already paid" and desk.m.rt.calls["call-1"]["paid_by_home"]["home-01"] == 0.5145


def test_a_gap_filled_at_a_raised_price_under_a_sale_earns_its_helper_the_step_up_on_kwh_beyond_its_booking_out_of_the_keep(desk):
    sale(desk, {"home-01": 3.0, "home-02": 5.0, "home-03": 2.0})
    desk.say("home-02", "rt_capacity", {"short": {Q[2]: 4.0, Q[3]: 4.0}})
    desk.m.rt.tick()                                                   # 4 kW short, 1 kW of it within the margin
    gap = next(iter(desk.m.rt.calls.values()))
    for h, kw in (("home-01", 0.0), ("home-03", 0.0), ("home-01", 3.0), ("home-03", 0.0)):
        desk.say(h, "rt_answer", {"answer": {"id": gap["id"], "kw": kw, **({} if kw else {"below_min_price": True})}})
    assert desk.out("rt_dispatch", "dispatch") == [("home-01", {"id": gap["id"], "steps": {Q[2]: 3.0, Q[3]: 3.0}, "price_usd_per_kwh": 1.0, "kind": "gap",
                                                                "start": Q[2], "end": END, "event_id": "sale-1"})]
    booked = {"home-01": 6.0, "home-02": 10.0, "home-03": 4.0}.get
    # 0.5 kWh beyond its 6 kWh booking, of the 1.5 the gap asked: 0.5 x $0.80 x 0.18375 x (1.00 / 0.80 - 1) = $0.018375
    sp = {"usd_per_kwh": 0.8, "fee": 1.0, "pool": 5.0, "per_home": {"home-01": 1.2, "home-02": 0.5}}
    desk.m.rt.premiums(desk.m.events["sale-1"], sp, {"home-01": 6.5, "home-02": 3.0, "home-03": 4.0}, booked)
    assert sp == {"usd_per_kwh": 0.8, "fee": 0.9816, "pool": 5.0184, "per_home": {"home-01": 1.2184, "home-02": 0.5}, "premium_usd": {"home-01": 0.0184}}
    # all 1.5 kWh beyond it come to $0.055125, and the keep holds $0.03
    capped = {"usd_per_kwh": 0.8, "fee": 0.03, "pool": 5.0, "per_home": {"home-01": 1.2}}
    desk.m.rt.premiums(desk.m.events["sale-1"], capped, {"home-01": 8.0}, booked)
    assert (capped["premium_usd"], capped["fee"], capped["pool"], capped["per_home"]) == ({"home-01": 0.03}, 0.0, 5.03, {"home-01": 1.23})


def test_a_repeated_call_answer_or_end_changes_nothing(desk):
    desk.say("utility", "rt_call", {"call": CALL})
    for h, kw in (("home-02", 9.0), ("home-02", 9.0), ("home-01", 6.0)):
        desk.say(h, "rt_answer", {"answer": {"id": "call-1", "kw": kw}})
    assert desk.m.rt.calls["call-1"]["phase"] == "asking"            # home-02 twice is one answer: home-03's is still to come
    desk.say("home-03", "rt_answer", {"answer": {"id": "call-1", "kw": 0.0}})
    assert desk.say("utility", "rt_call", {"call": CALL}) == "call call-1 already known"
    desk.say("home-02", "rt_answer", {"answer": {"id": "call-1", "kw": 9.0}})
    assert len(desk.out("rt_ask", "ask")) == 3 and [to for to, _ in desk.out("rt_dispatch", "dispatch")] == ["home-02", "home-01"]
    assert desk.say("utility", "rt_end", {"end": {"id": "call-1", "at": Q[2]}}) == f"call call-1 ended at {Q[2]}"
    assert desk.say("utility", "rt_end", {"end": {"id": "call-1", "at": Q[2]}}) == "call call-1 already ended"
    assert [(to, x["steps"]) for to, x in desk.out("rt_dispatch", "dispatch") if x.get("release")] == [
        ("home-02", {Q[2]: -8.0, Q[3]: -8.0}), ("home-01", {Q[2]: -3.0, Q[3]: -3.0})]


def test_after_5_minutes_the_market_tick_fills_a_call_with_the_answers_in_and_a_later_answer_is_not_dispatched(desk):
    called(desk, ("home-02", 9.0), ("home-01", 6.0))
    desk.clock.at = f"{DAY} 16:04"
    desk.m.tick()
    assert desk.m.rt.calls["call-1"]["phase"] == "asking" and desk.out("rt_dispatch", "dispatch") == []
    desk.clock.at = f"{DAY} 16:05"
    desk.m.tick()
    desk.say("home-03", "rt_answer", {"answer": {"id": "call-1", "kw": 4.0}})
    assert [to for to, _ in desk.out("rt_dispatch", "dispatch")] == ["home-02", "home-01"] and sorted(desk.m.rt.calls["call-1"]["alloc"]) == ["home-01", "home-02"]
    assert desk.out("rt_confirm", "confirm")[0][1]["kw"] == 10.0 and desk.m.failing == {}


def test_an_answer_for_a_gap_that_does_not_exist_from_a_member_not_asked_or_under_another_key_is_refused(desk):
    called(desk)
    gap = gap_of(desk, "home-02", {Q[2]: 4.0, Q[3]: 8.0})
    outs = [desk.say("home-01", "rt_answer", {"answer": {"id": "gap-none", "kw": 2.0}}),
            desk.say("home-02", "rt_answer", {"answer": {"id": gap["id"], "kw": 2.0}}),        # the member short is not asked to cover itself
            desk.say("home-01", "rt_answer", {"answer": {"id": gap["id"], "kw": 2.0}}, key=desk.keys["home-03"])]
    assert outs == ["answer ignored", "answer ignored", "rejected: bad signature"] and all(isinstance(o, beckn.Refused) for o in outs)
    assert gap["answers"] == {} and gap["phase"] == "asking"
    desk.m.reset()                                                     # a new play: the gaps of the last one are gone
    late = desk.say("home-03", "rt_answer", {"answer": {"id": gap["id"], "kw": 4.0}})
    assert isinstance(late, beckn.Refused) and late == "answer ignored" and desk.m.rt.calls == {}


def test_a_report_older_than_the_one_in_or_from_a_non_member_is_refused(desk):
    called(desk)
    first = desk.say("home-02", "rt_capacity", {"short": {Q[3]: 2.0}}, wall=2000.0)
    old = desk.say("home-02", "rt_capacity", {"short": {Q[3]: 8.0}}, wall=1000.0)
    stranger = desk.say("home-04", "rt_capacity", {"short": {Q[3]: 8.0}})
    assert first == f"home-02 short 2.0 kW from {Q[3]}: checked at the next 5 minutes"
    assert (old, stranger) == ("report ignored: a newer one is in", "report ignored: not a member") and all(isinstance(o, beckn.Refused) for o in (old, stranger))
    assert desk.m.rt.reports == {"home-02": {Q[3]: 2.0}}


def test_a_call_that_overlaps_another_or_comes_after_its_window_asks_nobody_and_is_confirmed_at_0_kw(desk):
    called(desk)
    over = desk.say("utility", "rt_call", {"call": {**CALL, "id": "call-2", "start": Q[3], "end": f"{DAY} 18:30"}})
    desk.clock.at = f"{DAY} 18:30"
    late = desk.say("utility", "rt_call", {"call": {**CALL, "id": "call-3", "start": END, "end": f"{DAY} 18:30"}})
    assert (over, late) == ("call call-2 refused: it overlaps call call-1", f"call call-3 arrived after its window ({DAY} 18:30): confirmed 0 kW")
    assert isinstance(over, beckn.Refused) and isinstance(late, beckn.Refused) and len(desk.out("rt_ask", "ask")) == 3
    assert desk.out("rt_confirm", "confirm")[1:] == [("utility", {"id": "call-2", "kw": 0.0, "short_kw": 10.0, "homes": [], "refused": "it overlaps call call-1"}),
                                                     ("utility", {"id": "call-3", "kw": 0.0, "short_kw": 10.0, "homes": [], "too_late": True})]


def test_the_service_drops_an_answer_past_its_time_to_live_and_holds_a_fresh_one_to_the_enrolment_nameplate(agent_config, tmp_path):
    from murmur.agents.community.service import CommunityAgent
    agent_config(agent_name="community", buyers=["utility"], sync_broadcast=True, replay_start=f"{DAY} 16:00", replay_loop_days=0)
    c, acks = CommunityAgent(), []
    c.town = SimpleNamespace(send=lambda *a: {}, ack=lambda mid, fence, status, note: acks.append((status, note)))
    c.market.pins, c.market.save_pins = {}, lambda: None
    keys = {n: signing.load_or_create(tmp_path / f"{n}.key") for n in ("utility", "home-02")}

    def inbox(sender, action, message, age=0.0):
        body = beckn.make(action, sender=sender, receiver="community", transaction_id="t", message=message, key=keys[sender], wall=time.time() - age)
        c.handle({"body": body, "kind": beckn.kind(action), "from": sender, "message_id": f"m-{len(acks)}", "fence": 1})
        return acks[-1]
    assert inbox("utility", "rt_call", {"call": CALL}) == ("processed", {"result": "call call-1: asked 3 homes"})
    status, note = inbox("home-02", "rt_answer", {"answer": {"id": "call-1", "kw": 99.0}}, age=1000.0)
    assert (status, note["skipped"]) == ("rejected", "expired") and 100 <= note["late_s"] < 110      # 100 s past its 900 s, plus the moment it took to reach the door
    assert c.market.rt.calls["call-1"]["answers"] == {}
    assert inbox("home-02", "rt_answer", {"answer": {"id": "call-1", "kw": 99.0}})[0] == "processed"
    assert c.market.rt.calls["call-1"]["answers"]["home-02"]["kw"] == 25.9      # 5 kW battery, 9.6 kW two-way car, 5.6 kW dryer, 1.7 kW water heater, half its 8 kW cooling

"""What the market has scheduled, quarter hour by quarter hour (market_schedule.py): the day's question to each buyer from 10:00 to 16:00 until it
is answered; a sale while its contract is still open, up to its deadline; the notice before its window where members hear one; its evening from
the agents' lead through the window, the readings and the settlement, a day past the window at most; and a call of the desk while it asks, while
it runs, and a buyer's call until it is settled. Everything else is empty: a sale that failed or sold nothing, one that is done, a gap once its
quarter hours are over.
"""
from __future__ import annotations

import pytest

from murmur.agents.community.market_schedule import opens_brake
from tests.test_community_market import sale

D0, D1, D2 = "2025-01-27", "2025-01-28", "2025-01-29"        # the market's clock is at 12:00 on the first; sale-1 runs 17:00 to 18:00 on the second, to be signed by 16:00 on the first
OPEN, NOTICE = "sale-1: its contract is still open", "sale-1: the notice to its members"
PLAN, WINDOW, AFTER = "sale-1: its members plan it", "sale-1: its window", "sale-1: its readings and settlement"


def signed(tmp_path, **cfg):
    """sale-1 with its final contract out and its notice gone, and both days' question answered: what is left is its evening."""
    m = sale(tmp_path, **cfg)
    m.last_discover_day = D1
    m.events["sale-1"].update(phase="homes", finalized=True, final_sent=True, notice_sent=True)
    return m, m.events["sale-1"]


def test_the_days_question_is_scheduled_from_10_to_16_of_a_day_a_buyer_has_not_answered_for(tmp_path):
    m = sale(tmp_path, buyers=["utility", "grid-op"])
    m.events.clear()
    m.last_discover_day = None
    ask = "the question to utility for tomorrow"
    assert [m.scheduled(f"{D0} {hm}") for hm in ("09:45", "10:00", "15:45", "16:00")] == [None, ask, ask, None]      # as the clock has always waited for it
    assert [opens_brake(None, f"{D0} {hm}", f"{D0} {hm}") for hm in ("09:45", "10:00", "15:45", "16:00")] == [False, True, True, False]
    m.last_discover_day = D0
    assert m.scheduled(f"{D0} 10:00") == "the question to grid-op for tomorrow"       # each buyer is asked, and the second has still to answer
    m.other_discover["grid-op"] = D0
    assert m.scheduled(f"{D0} 10:00") is None and m.scheduled(f"{D1} 09:45") is None and m.scheduled(f"{D1} 10:00") == ask      # tomorrow it is asked again


@pytest.mark.parametrize("phase", ["offers", "clearing", "cleared", "utility", "homes"])
def test_a_sale_whose_contract_is_still_open_is_scheduled_at_every_quarter_hour_up_to_its_deadline_and_not_after(tmp_path, phase):
    m = sale(tmp_path)
    m.last_discover_day = D1
    m.events["sale-1"]["phase"] = phase
    assert [m.scheduled(f"{D0} {hm}") for hm in ("12:15", "13:00", "16:00", "16:15")] == [OPEN, OPEN, OPEN, None]
    if phase != "homes":                                               # never signed: no evening of it is to come
        assert [m.scheduled(f"{D1} {hm}") for hm in ("16:30", "17:00", "18:00")] == [None, None, None]


def test_a_signed_sale_is_scheduled_from_its_members_lead_through_its_window_to_its_settlement_and_a_day_past_the_window_at_most(tmp_path):
    m, ev = signed(tmp_path)
    assert [m.scheduled(f"{D0} {hm}") for hm in ("12:15", "16:00")] == [None, None]             # signed: nothing of it until its evening
    hours = ("16:15", "16:30", "16:45", "17:00", "17:45", "18:00", "18:15", "23:45")
    assert [m.scheduled(f"{D1} {hm}") for hm in hours] == [None, PLAN, PLAN, WINDOW, WINDOW, AFTER, AFTER, AFTER]
    assert m.scheduled(f"{D2} 18:00") == AFTER and m.scheduled(f"{D2} 18:15") is None           # the market asks after it for a day, and no longer
    ev["phase"] = "settling"
    assert m.scheduled(f"{D1} 18:15") == AFTER
    ev["phase"] = "done"
    assert [m.scheduled(f"{D1} {hm}") for hm in hours] == [None] * 8                            # all of it done
    ev["readings_missing"] = {"home-01": [1]}
    assert m.scheduled(f"{D1} 18:15") == AFTER                                                  # paid on less than was sold: the readings are still asked for
    for phase in ("failed", "no_offer"):
        ev["phase"] = phase
        assert [m.scheduled(f"{D1} {hm}") for hm in hours] == [None] * 8


def test_the_lead_is_the_agents_30_minutes_or_what_the_configuration_names_and_the_notice_is_scheduled_only_where_members_hear_one(tmp_path):
    m, ev = signed(tmp_path, clock_lead_minutes=60)
    assert [m.scheduled(f"{D1} {hm}") for hm in ("15:45", "16:00")] == [None, PLAN]
    ev["notice_sent"] = False
    assert [m.scheduled(f"{D1} {hm}") for hm in ("14:45", "15:00", "15:45")] == [None, NOTICE, NOTICE]       # two hours before the window, until it has gone
    ev["finalized"] = False
    assert m.scheduled(f"{D1} 15:00") is None                          # no final contract yet: no notice either
    quiet, ev = signed(tmp_path, report_rule="exception")
    ev["notice_sent"] = False
    assert [quiet.scheduled(f"{D1} {hm}") for hm in ("15:00", "16:15", "16:30")] == [None, None, PLAN]      # members that speak by exception hear no notice


def test_a_call_of_the_desk_is_scheduled_while_it_asks_while_it_runs_and_a_buyers_call_until_it_is_settled(tmp_path):
    m, _ = signed(tmp_path)
    m.events.clear()
    call = m.rt.calls["call-1"] = {"id": "call-1", "kind": "short_notice", "phase": "asking", "start": f"{D1} 19:00", "end": f"{D1} 20:00"}
    runs, settles = "call call-1: it runs until 20:00", "call call-1: its settlement"
    assert m.scheduled(f"{D1} 12:00") == m.scheduled(f"{D2} 23:45") == "call call-1: answers to come"       # its answers fall due by the clock
    call["phase"] = "dispatched"
    assert [m.scheduled(f"{D1} {hm}") for hm in ("18:45", "19:45", "20:00", "22:00")] == [runs, runs, settles, settles]
    assert m.scheduled(f"{D2} 20:00") == settles and m.scheduled(f"{D2} 20:15") is None
    call["end_early"] = f"{D1} 19:30"
    assert [m.scheduled(f"{D1} {hm}") for hm in ("19:15", "19:30")] == ["call call-1: it runs until 19:30", settles]
    call["settled"] = {"paid_usd": 4.2}
    assert m.scheduled(f"{D1} 19:30") is None
    call["lacking"] = {"home-01": [f"{D1} 19:00"]}
    assert m.scheduled(f"{D1} 19:30") == settles                       # settled short: its readings are still asked for
    m.rt.calls["call-1"] = {"id": "call-1", "kind": "short_notice", "phase": "dispatched", "start": f"{D1} 09:00", "end": f"{D1} 10:00", "too_late": True}
    assert m.scheduled(f"{D1} 10:00") is None                          # it came after its window: nobody was asked, nothing is owed
    m.rt.calls["call-1"] = {"id": "gap-1", "kind": "gap", "phase": "dispatched", "start": f"{D1} 19:00", "end": f"{D1} 19:30"}
    assert [m.scheduled(f"{D1} {hm}") for hm in ("19:15", "19:30")] == ["call gap-1: it runs until 19:30", None]       # a gap is paid with the sale it covers

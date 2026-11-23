"""The community's report when its clock moves over several quarter hours in one move: every quarter hour gets its row, in order, and goes upward.

Where rows are written as a quarter hour begins, every one the clock came to is written at once. On a real clock (report_when_ended) the row of the step
the clock held at is written at once, as it always was, and the rows of the quarter hours it passed over are written as their meter readings come
in, in order, and when the clock next moves at the latest. The members' batteries, where the agent holds them, run every quarter hour of the move, and
each row says what the level above asked for its own quarter hour. A move back, a move of more than two days and a new play write one row, as before.
"""
from __future__ import annotations

from types import SimpleNamespace

from murmur.agents.community import community as cm, community_rules as cr
from tests.test_community_market import DEF, sale

DAY = "2025-01-28"
Q = [f"{DAY} {17 + k // 4:02d}:{15 * (k % 4):02d}" for k in range(9)]         # 17:00, 17:15 ... 19:00
ABOVE = {"aggregator": {"id": "aggregator"}}
SHARED = {"rating_kw": 40.0, "energy_kwh": 100.0, "run_by_agent": True}


def market(play: str = "play-1") -> SimpleNamespace:
    """A market with no sale on, as the community's step reads it."""
    return SimpleNamespace(events={}, play=play)


def read(c: cm.Community) -> list[tuple]:
    """Each report row's quarter hour and the net power it says."""
    return [(r["timestamp"], r["reported_p_net_kw"]) for r in c.report]


def fed(c: cm.Community, *rows: tuple[str, float]) -> None:
    c.feed([{"ts": ts, "meter_kw": kw} for ts, kw in rows])


def test_every_quarter_hour_the_clock_came_to_in_one_move_gets_its_row_in_order_and_each_goes_upward():
    c = cm.define({**DEF, **ABOVE, "meter": {q: -float(k) for k, q in enumerate(Q[:5])}})        # its meter is known ahead, as a replay's record is
    m = market()
    assert c.step(m, Q[0])["timestamp"] == Q[0]
    last = c.step(m, Q[4])                                             # four quarter hours in one move
    assert read(c) == [(q, -float(k)) for k, q in enumerate(Q[:5])] and last is c.report[-1]
    assert c.outbox == c.report and c.step(m, Q[4]) is None            # each row waits to go upward, oldest first, and none is written twice


def test_on_a_real_clock_the_rows_of_the_quarter_hours_passed_over_are_written_as_their_readings_come_in_order():
    c, m = cm.define({**DEF, **ABOVE, "report_when_ended": True}), market()
    fed(c, (Q[0], -1.0), (Q[1], -2.0))
    assert c.step(m, Q[0]) is None and c.step(m, Q[1])["timestamp"] == Q[0]      # a quarter hour's row is written once it has ended
    assert c.step(m, Q[5])["timestamp"] == Q[1] and c.rows_due == Q[2:5]         # one move over four: the step the clock held at has its reading and its row at once
    assert c.step(m, Q[5]) is None                                               # the others wait for their readings
    fed(c, (Q[3], -4.0))
    assert c.step(m, Q[5]) is None and read(c) == [(Q[0], -1.0), (Q[1], -2.0)]   # a later reading alone writes nothing: rows go in order
    fed(c, (Q[2], -3.0))
    assert c.step(m, Q[5])["timestamp"] == Q[3] and c.rows_due == [Q[4]]         # 17:30 and 17:45 together, in order
    fed(c, (Q[4], -5.0), (Q[5], -6.0))
    assert c.step(m, Q[5])["timestamp"] == Q[4] and c.rows_due == []             # 18:15 itself has not ended yet
    assert read(c) == [(q, -float(k + 1)) for k, q in enumerate(Q[:5])] and c.outbox == c.report


def test_on_a_real_clock_a_row_still_without_its_reading_is_written_when_the_clock_next_moves_and_says_so():
    c, m = cm.define({**DEF, "report_when_ended": True}), market()
    fed(c, (Q[0], -1.0), (Q[3], -4.0))
    c.step(m, Q[0])
    c.step(m, Q[3])                                                    # passed over 17:15 and 17:30, which nothing feeds
    assert read(c) == [(Q[0], -1.0)] and c.rows_due == Q[1:3]
    assert c.step(m, Q[4])["timestamp"] == Q[3]                        # the clock moves on: they can wait no longer
    assert read(c) == [(Q[0], -1.0), (Q[1], None), (Q[2], None), (Q[3], -4.0)] and [r["text"] for r in c.report[1:3]] == [cr.NO_METER] * 2
    fed(c, (Q[1], -2.0))                                               # a reading that comes after its row is put beside it: what was reported stays
    assert (c.report[1]["reported_p_net_kw"], c.report[1]["meter_p_net_kw"]) == (None, -2.0)


def test_one_step_at_a_time_writes_what_it_always_wrote():
    for ended, rows in ((False, Q[:4]), (True, Q[:3])):
        c, m = cm.define({**DEF, "report_when_ended": ended, "meter": {Q[1]: -2.0}}), market()
        assert [bool(c.step(m, q)) for q in Q[:4]] == [not ended, True, True, True]
        assert [r["timestamp"] for r in c.report] == rows and c.rows_due == []
        assert [r["text"] for r in c.report] == [cr.QUIET if r["timestamp"] == Q[1] else cr.NO_METER for r in c.report]


def test_a_move_back_a_move_of_more_than_two_days_and_a_new_play_write_one_row_and_leave_what_was_due():
    c, m = cm.define({**DEF, "report_when_ended": True}), market()
    c.step(m, Q[0])
    c.step(m, Q[4])
    assert c.rows_due == Q[1:4]
    assert c.step(m, Q[2])["timestamp"] == Q[1] and c.rows_due == []                   # the clock set back: the run begins again from there
    assert [r["timestamp"] for r in c.report] == [Q[0], Q[1]]
    assert c.step(m, "2025-02-03 17:00")["timestamp"] == "2025-02-03 16:45"            # six days on: no row for the 570 quarter hours between
    c.step(m, "2025-02-03 18:00")
    assert c.rows_due == ["2025-02-03 17:15", "2025-02-03 17:30", "2025-02-03 17:45"]
    assert c.step(market("play-2"), "2025-02-03 19:00")["timestamp"] == "2025-02-03 18:45" and c.rows_due == []      # a new play: the last one's rows are not written in it
    assert [r["timestamp"] for r in c.report][2:] == ["2025-02-03 16:45", "2025-02-03 17:00", "2025-02-03 18:45"]


def test_the_members_batteries_run_every_quarter_hour_of_the_move_and_each_row_says_what_was_asked_for_its_own():
    c, m = cm.define({**DEF, **ABOVE, "limit_out_kw": 200.0, "battery": SHARED}), market()
    c.asked("aggregator", {"id": "req-1", "community": "community-1", "made_at": Q[0], "rows": [{"ts": q, "battery_kw": 20.0} for q in Q[2:4]]}, Q[0])
    c.feed([{"ts": q, "idle_kw": 10.0, **({"store_kwh": 50.0} if q == Q[0] else {})} for q in Q[:5]])
    c.step(m, Q[0])
    c.step(m, Q[4])                                                    # four quarter hours in one move: the request's two are among them
    assert [(b["ts"], b["asked_kw"], b["gave_kw"]) for b in c.battery_ran] == [(Q[0], 0.0, 0.0), (Q[1], 0.0, 0.0), (Q[2], 20.0, 20.0), (Q[3], 20.0, 20.0), (Q[4], 0.0, 0.0)]
    assert read(c) == [(Q[0], 10.0), (Q[1], 10.0), (Q[2], 30.0), (Q[3], 30.0), (Q[4], 10.0)]      # the meter the agent reads once its battery has run
    assert [r["reported_soc_percent"] for r in c.report] == [50.0, 50.0, 45.0, 40.0, 40.0]
    assert [r["text"] for r in c.report] == [cr.QUIET, cr.QUIET, f"{cr.QUIET}; battery gives 20 kW", f"{cr.QUIET}; battery gives 20 kW", cr.QUIET]


def test_the_market_sends_every_row_of_a_move_upward_signed_oldest_first_and_a_new_play_drops_what_was_due(tmp_path):
    c = cm.define({**DEF, **ABOVE, "report_when_ended": True})
    m = sale(tmp_path, community=c)

    def tick(ts: str) -> list[str]:
        """The market's tick at this time: the quarter hours of the report rows it sent upward."""
        del m.sent[:]
        m.clock.configure(ts, 60, 0, ts, hold=True)
        m.tick()
        return [body["message"]["report"]["timestamp"] for to, kind, body, _ in m.sent if (to, kind) == ("aggregator", "community.report")]
    fed(c, *((q, -float(k)) for k, q in enumerate(Q[:6])))
    assert tick(Q[0]) == [] and tick(Q[1]) == [Q[0]]
    assert tick(Q[5]) == Q[1:5] and c.sent_up == 5 and c.outbox == []               # a move of four: the row of 17:15 and the three it passed over, all read
    tick(Q[8])
    assert c.rows_due == Q[6:8]
    m.reset()                                                          # a new play of the same days
    assert tick(Q[0]) == ["2025-01-28 16:45"] and c.rows_due == []     # the row a start has always written, and none of the play before

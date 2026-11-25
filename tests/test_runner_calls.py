"""An evening with an emergency call: the run is not settled while a buyer still holds a call it has not settled, the clock goes on
to the step the call is settled at, and an evening that reaches its end with the call still open says so."""
from __future__ import annotations

import pytest

from demo.runner.evening import CALLS_S
from tests.test_runner import evening

CALL = {"id": "call-2025-01-28-1830-emergency-1", "kind": "emergency", "start": "2025-01-28 18:30", "end": "2025-01-28 19:30", "kw": 2.0,
        "confirmed_kw": 2.0, "status": "OPEN", "paid_usd": None, "delivered_kwh": None}
HOLD = ("community/demo/conductor", {"hold": True})


def done(parts) -> None:
    parts.sale.update(phase="done", readings=15, readings_missing={})


def test_an_evening_is_not_settled_while_a_buyer_holds_a_call_it_has_not_settled(tmp_path):
    e, parts, wall = evening(tmp_path, pace_s=0, leap=True)
    said = []
    e.say = lambda *x: said.append(" ".join(str(v) for v in x))
    parts.calls.append(dict(CALL))
    done(parts)
    assert e.look() is None and parts.posts == []                      # the sale's money is final, the call's is not: the clock is not held
    assert e.owed() == [CALL["id"], CALL["id"]]                        # each buyer is asked (the scripted parts answer both alike)
    parts.clock.update(now="2025-01-28 23:00")
    assert e.look() is None and parts.posts == []                      # the clock goes on, however far, while the call is open
    assert sum("call(s) still to settle" in line for line in said) == 1     # said once
    parts.calls[0].update(status="COMPLETE", paid_usd=3.26, delivered_kwh=1.6)
    assert e.look() is None and parts.posts == [HOLD]                  # the buyer has settled it: now the clock is told to hold
    parts.clock["mode"] = "held"
    assert e.look() == "settled" and e.owed() == []


@pytest.mark.parametrize("status", ["COMPLETE", "REFUSED"])
def test_a_call_that_was_refused_or_settled_holds_nothing_up(tmp_path, status):
    e, parts, _ = evening(tmp_path, pace_s=0, leap=True)
    parts.calls.append({**CALL, "status": status})
    done(parts)
    assert e.look() is None and parts.posts == [HOLD]


def test_the_buyers_are_not_asked_for_their_calls_before_the_sale_is_done_or_after_the_clock_is_held(tmp_path):
    e, parts, _ = evening(tmp_path, pace_s=0, leap=True)
    asked = lambda: [u for u in parts.asked if u.endswith("/calls")]      # noqa: E731
    parts.calls.append(dict(CALL))
    assert e.look() is None and asked() == []                          # the sale is open
    parts.sale.update(phase="done", readings_missing={"home-01": ["3"]})
    assert e.look() is None and asked() == []                          # a reading is missing: the sale's own money is not final yet
    done(parts)
    parts.calls.clear()
    assert e.look() is None and asked() == ["utility/calls", "grid-operator/calls"] and parts.posts == [HOLD]
    assert e.look() is None and len(asked()) == 2                      # held: the buyers are not asked again


def test_an_evening_that_reaches_its_end_with_a_call_still_open_waits_a_moment_and_then_says_so(tmp_path):
    e, parts, wall = evening(tmp_path, pace_s=0, leap=True)
    parts.calls.append(dict(CALL))
    done(parts)
    parts.clock.update(now="2025-01-29 02:45", at_gate="2025-01-29 03:00", mode="at_gate")     # the clock stands before the evening's last step
    assert e.look() is None                                            # the buyer may be settling it on this very step
    wall.t += CALLS_S - 1
    assert e.look() is None
    wall.t += 2
    assert e.look() == "settled, with a call open" and parts.posts == []


def test_a_call_settled_at_the_evenings_end_ends_it_settled(tmp_path):
    e, parts, wall = evening(tmp_path, pace_s=0, leap=True)
    parts.calls.append(dict(CALL))
    done(parts)
    parts.clock.update(now="2025-01-29 02:45", at_gate="2025-01-29 03:00", mode="at_gate")
    assert e.look() is None
    parts.calls[0]["status"] = "COMPLETE"
    assert e.look() is None and parts.posts == [HOLD]
    assert e.look() == "settled"

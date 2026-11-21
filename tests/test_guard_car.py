"""The home guard's rule for a charging car: a limit may put off only as much full-power charging as the car can wait for.

A limit of A amps leaves the car charging at A x 240 V and takes the rest of its charging power off for the length of the call;
the car must still be ready when it leaves, so the full-power hours a limit puts off may not pass the car's slack (wait_h)."""
from __future__ import annotations

from murmur.node.guard import Guard

CAR = {"target": "car-charger", "status": "charging", "max_amps": 32.0, "wait_h": 2.0, "leaves": "07:00", "charge_kw": 7.2}
SALE = {"tool": "limit_ev_charging", "start": "2025-01-28 18:00", "end": "2025-01-28 21:00"}          # three hours


def limit(amps, car=CAR):
    return Guard._limit_ev_charging(None, {"amps": amps}, dict(car), {}, {**SALE, "args": {"amps": amps}})


def test_a_pause_longer_than_the_cars_slack_is_refused_and_a_shorter_one_is_done():
    assert limit(0)["status"] == "blocked" and limit(0)["why"] == "The car must be ready by 07:00, so it can't wait that long."
    roomy = limit(0, {**CAR, "wait_h": 3.0})
    assert (roomy["status"], roomy["applied"], roomy["expected_kw"]) == ("done", {"amps": 0.0}, 7.2)


def test_a_partial_limit_that_puts_off_more_charging_than_the_slack_is_refused():
    out = limit(6)                                           # 7.2 - 1.44 = 5.76 kW off for 3 h: 2.4 h of full power put off, past 2.0 h
    assert out["status"] == "blocked" and out["why"] == "The car must be ready by 07:00, so it can't put off that much charging."


def test_a_partial_limit_within_the_slack_is_done_with_the_power_it_takes_off():
    out = limit(16)                                          # 7.2 - 3.84 = 3.36 kW off for 3 h: 1.4 h put off, inside 2.0 h
    assert (out["status"], out["applied"]) == ("done", {"amps": 16.0})
    assert abs(out["expected_kw"] - 3.36) < 1e-9


def test_amps_below_six_are_raised_to_six_and_above_the_charger_are_held_to_it():
    assert limit(3)["why"] == limit(6)["why"]                # 3 A is raised to 6 A, which puts off too much
    full = limit(40, {**CAR, "max_amps": 30.0})              # 30 A x 240 V = 7.2 kW: nothing is taken off
    assert (full["status"], full["applied"], full["expected_kw"]) == ("done", {"amps": 30.0}, 0.0)

"""The peak allocation: the plan made at 14:00, the replay inside every limit, the score by the ruler, and the whole pipeline on a synthetic
pair of releases; on ENGIE's data (marked engie_data) headline result 1: the hours with a transformer at 80% or more fall from 96 to 19 with
every battery held for the peak, and to 84 without the plants' batteries."""
from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import releases_for_peak as synthetic  # noqa: E402
from experiments.engie import data, fleet, grid  # noqa: E402
from experiments.engie.meter_cleaning import outputs_present  # noqa: E402
from experiments.engie.peak_allocation import __main__ as cli  # noqa: E402
from experiments.engie.peak_allocation import plan, replay, score  # noqa: E402
from experiments.engie.peak_allocation.pipeline import CASES, run  # noqa: E402
from releases_for_peak import engie_root  # noqa: E402

DAYS = 10
EVENING = 19 - plan.H0                    # the plan's column for 19:00
NO_BREAK = {"charge_outside_10_to_90": 0, "device_power_over_rating": 0, "sent_out_over_the_connection_limit": 0}


def recorded_fleet(kinds=("community", "pv_bess"), site=-500.0, limit=np.inf, rated=None) -> fleet.Fleet:
    """1 MW, 2 MWh batteries that charge from 10:00 and give from 16:00 every day, as the synthetic reports show; each site draws 500 kW
    (or sends out `site`). rated: the power ratings, when they differ from what the batteries do."""
    steps = pd.date_range("2025-01-01 06:00", periods=DAYS * 96, freq="15min")          # UTC, from local midnight
    at = steps.tz_localize("UTC").tz_convert(synthetic.ZONE)
    power = np.full(len(kinds), 1000.0)
    soc, bt = synthetic.batteries_as_recorded(np.asarray(at.hour + at.minute / 60), power, 2 * power)
    rat = fleet.Ratings([f"b{j}" for j in range(len(kinds))], np.array(kinds), 2 * power, power if rated is None else np.asarray(rated, float),
                        np.full(len(kinds), limit))
    return fleet.from_arrays(steps, rat, site + bt, soc)


def one_transformer(take, power, expected=None) -> plan.Asked:
    """What the plan knows of a grid with one transformer, relieved 1 point per MW the asked batteries give."""
    take = np.asarray(take)
    expected = np.full((DAYS, plan.NH, 1), 50.0) if expected is None else expected
    return plan.Asked(take, np.asarray(power, float) * take, np.array([100.0]), np.array([True]), expected)


def test_the_fleet_reads_each_batterys_loss_and_drops_a_spike():
    F = recorded_fleet(("community", "pv_bess", "datacenter"), rated=[1000, 1000, 3000])
    np.testing.assert_allclose(F.f, synthetic.GIVE_F)          # the third never gives at full power: it takes the fleet's median
    np.testing.assert_allclose(F.grec, F.p + 500, atol=1e-6)   # each battery's power at the connection, read back from its charge
    np.testing.assert_allclose(F.p0, -500.0, atol=1e-6)
    assert (F.days, int(F.hour[0]), int(F.minute[1])) == (DAYS, 0, 15)
    steps, s = F.steps, F.s.copy()
    s[3 * 96 + 8, 0] += 0.25                                   # a single-step correction of the charge, straight back after
    G = fleet.from_arrays(steps, F.rat, F.p, s)
    np.testing.assert_allclose(G.s, F.s)


def test_waterfill_splits_in_proportion_and_never_above_room():
    np.testing.assert_allclose(plan.waterfill(6, np.array([1.0, 2, 3]), np.array([10.0, 10, 10])), [1, 2, 3])
    np.testing.assert_allclose(plan.waterfill(6, np.array([1.0, 1, 1]), np.array([1.0, 10, 10])), [1, 2.5, 2.5])
    np.testing.assert_allclose(plan.waterfill(100, np.array([1.0, 1, 0]), np.array([3.0, 4, 9])), [3, 4, 0])


def test_need_reads_only_the_transformers_the_batteries_relieve():
    A = plan.Asked(np.ones(1, dtype=bool), np.array([1000.0]), np.array([50.0, 0.1]), np.array([True, False]), np.zeros((1, plan.NH, 2)))
    L = np.array([[81.0, 99.0], [79.0, 99.0], [np.nan, 99.0]])
    np.testing.assert_allclose(plan.need(L, 79.9, A), [2.2, 0.0, 0.0])


def test_true_overloads_come_first_and_what_is_left_goes_to_the_worst_hour():
    L = np.full((plan.NH, 1), 50.0)
    L[EVENING], L[EVENING + 1] = 103.0, 82.0                   # 3.1 MW brings 19:00 under 100%; both hours under 80% would take 25.2
    g, asked_mw = plan.plan(L, np.array([5000.0]), one_transformer([True], [10_000.0]), emin=np.zeros(1), f=np.ones(1))
    want = np.zeros(plan.NH)
    want[EVENING] = 5000.0
    np.testing.assert_allclose(g[0], want)
    np.testing.assert_allclose(asked_mw, want / 1000)


def test_the_request_is_shared_by_energy_left_and_the_rest_goes_to_the_highest_loaded_hours():
    L = 50 + 0.1 * np.arange(plan.NH)[:, None]
    L[EVENING], L[EVENING + 1] = 81.0, 80.5                    # needs 1.1 MW at 19:00 and 0.6 MW at 20:00
    g, asked_mw = plan.plan(L, np.array([1500.0, 500.0]), one_transformer([True, True], [1000.0, 1000.0]), emin=np.zeros(2), f=np.ones(2))
    np.testing.assert_allclose(asked_mw[[EVENING, EVENING + 1]], [1.1, 0.6])
    np.testing.assert_allclose(g[:, EVENING], [1000.0, 350.0])     # 825 and 275 asked, then the rest of the evening's energy
    np.testing.assert_allclose(g[:, EVENING + 1], [500.0, 150.0])
    np.testing.assert_allclose(g.sum(axis=1), [1500.0, 500.0])
    assert (g <= 1000.0 + 1e-9).all() and not np.delete(g, [EVENING, EVENING + 1], axis=1).any()


def test_the_first_day_gives_a_third_of_the_usable_energy_from_18_to_21():
    g = plan.first_day(np.array([1800.0, 1800.0]), one_transformer([True, False], [1000.0, 1000.0]), emin=np.full(2, 200.0), f=np.full(2, 0.95))
    third = 1600 * 0.95 / 3
    np.testing.assert_allclose(g[0], [0, 0, 0, 0, third, third, third, 0, 0, 0])
    assert not g[1].any()


def test_the_plan_expects_yesterday_evening_moved_by_this_morning():
    F = recorded_fleet()
    loading = np.full((DAYS, 24, 1), 60.0)
    loading[:, 8:12, 0] += np.arange(DAYS)[:, None]            # each morning a point above the one before
    A = plan.asked(np.ones(2, dtype=bool), F, np.array([[0.5, 0.0, 0.0]]), loading)
    assert np.isnan(A.expected[0]).all()
    np.testing.assert_allclose(A.expected[1:, 18 - plan.H0, 0], 61.0)          # no battery gives at 18:00 as recorded
    np.testing.assert_allclose(A.expected[1:, 16 - plan.H0, 0], 61.5)          # 1 MW of communities' batteries gave at 16:00, 0.5 point a MW
    np.testing.assert_allclose(A.sle, [25.0])                                  # half the asked power is a community's
    assert A.pos.tolist() == [True] and A.power.tolist() == [1000.0, 1000.0]


def test_the_replay_gives_what_the_plan_asks_inside_every_limit():
    F = recorded_fleet()
    expected = np.full((DAYS, plan.NH, 1), 50.0)
    expected[:, EVENING] = 80.5                                # every evening needs 0.6 MW at 19:00
    take = np.array([True, False])
    r = replay.replay(F, one_transformer(take, F.rat.power_kw, expected))
    assert ((r.level >= F.emin - 1e-6) & (r.level <= F.emax + 1e-6)).all()
    assert (np.abs(np.where(r.new >= 0, r.new, r.new * F.f) / fleet.DT) <= F.rat.power_kw + 1e-6).all()
    np.testing.assert_allclose(r.new[:, 1], F.d[:, 1], atol=1e-9)              # a battery nobody asks runs as recorded
    np.testing.assert_allclose(r.after[:, 1], F.p[:, 1], atol=1e-6)
    given = np.where(r.new >= 0, -r.new, -r.new * F.f) / fleet.DT
    np.testing.assert_allclose(given[(F.day >= 1) & (F.hour == 19), 0], 1000.0, rtol=1e-6)    # it keeps its charge for 19:00
    np.testing.assert_allclose(r.asked[1:, EVENING], 0.6)
    assert not r.asked[0].any() and r.lost_kwh == 0.0                          # the first day has no yesterday to plan from


def test_a_site_never_sends_out_more_than_its_connection_takes():
    F = recorded_fleet(("pv_bess",), site=200.0, limit=600.0)
    expected = np.full((DAYS, plan.NH, 1), 50.0)
    expected[:, EVENING] = 85.0
    r = replay.replay(F, one_transformer([True], F.rat.power_kw, expected))
    assert (r.after <= np.maximum(600.0, F.p) + 1e-9).all()
    np.testing.assert_allclose(r.after[(F.day >= 1) & (F.hour == 19), 0], 600.0)   # 400 kW of the battery fit beside the site's 200


def test_the_score_moves_each_transformer_by_the_ruler():
    F = recorded_fleet(("community",))
    hour, day = F.hour[::4], F.day[::4]
    base = np.where((hour == 19)[:, None], 81.0, 79.0) * np.ones((1, 2))
    R = grid.Readings(F.steps[::4], base, np.array([35, 38]), hour, day, np.full(len(hour), 2025))
    after = F.p.copy()
    after[F.hour == 19] += 1000.0                              # the community sends out 1 MW more at 19:00
    r = replay.Run(after, F.d.copy(), F.s * F.rat.energy_kwh, 0.0, np.zeros((DAYS, plan.NH)))
    ruler = np.array([[2.0, 0.0, 0.0], [0.5, 0.0, 0.0]])
    np.testing.assert_allclose(score.loading_after(r, F, R, base, ruler)[hour == 19], [[79.0, 80.5]] * DAYS)
    sc = score.score(r, F, R, base, ruler)
    assert (sc["hours_at_80_or_more"], sc["of_which_new"], sc["by_hour"], sc["evenings_with_one"]) == (DAYS, 0, {19: DAYS}, DAYS)
    assert sc["limits_broken"] == NO_BREAK and sc["highest_loading"] == 80.5


@pytest.fixture(scope="module")
def allocated(tmp_path_factory):
    """The command run once on the synthetic pair, with no meter-cleaning results to start from."""
    pair = synthetic.write_pair(tmp_path_factory.mktemp("releases"))
    out = tmp_path_factory.mktemp("peak_allocation")
    assert cli.main(["--data-dir", str(pair.root), "--out", str(out)]) == 0
    return pair, out, json.loads((out / "peak_allocation.json").read_text())


def test_the_pipeline_runs_the_meter_cleaning_first_when_its_results_are_missing(allocated):
    _, out, res = allocated
    assert outputs_present(out / "meter_cleaning")
    assert [res[key]["batteries_asked"] for key, _ in CASES] == [9, 6, 3]
    assert [res[key]["their_power_mw"] for key, _ in CASES] == [15.0, 7.5, 3.0]
    assert res["batteries_mw"] == {"community": 3.0, "datacenter": 4.5, "pv_bess": 7.5}


def test_holding_the_batteries_for_the_peak_cuts_the_strained_hours(allocated):
    _, _, res = allocated
    recorded = res["as_recorded_hours_at_80_or_more"]
    every, no_plants, communities = (res[key]["hours_at_80_or_more"] for key, _ in CASES)
    assert recorded > 10 and every < recorded / 4 and every <= no_plants < recorded and communities < recorded
    for key, _ in CASES:
        assert res[key]["limits_broken"] == NO_BREAK and res[key]["hours_at_100_or_more"] == 0 and res[key]["evenings_with_a_request"] > 0
    assert res["all_asked"]["the_unasked_moved_from_their_record_mw_mean"] == 0.0


def test_results_for_other_transformers_are_refused(allocated, tmp_path):
    pair, out, _ = allocated
    other = tmp_path / "cleaning"
    shutil.copytree(out / "meter_cleaning", other)
    cols = json.loads((other / "transformers.json").read_text())
    (other / "transformers.json").write_text(json.dumps({**cols, "transformers": cols["transformers"][::-1]}))
    with pytest.raises(ValueError, match="other transformers"):
        run(pair.root, tmp_path, other, say=lambda _: None)


def test_the_command_line_says_what_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(data.ENV, raising=False)
    assert cli.main(["--out", str(tmp_path / "out")]) == 2
    assert data.ENV in capsys.readouterr().err


@pytest.fixture(scope="module")
def engie_allocated(tmp_path_factory):
    out = tmp_path_factory.mktemp("engie_peak_allocation")
    return run(engie_root(data.MARK_2025, data.MARK_2023), out, out / "meter_cleaning", say=lambda _: None)


@pytest.mark.engie_data
def test_engie_the_fleet_as_reported():
    F = fleet.from_reports(data.release_2025(engie_root(data.MARK_2025)))
    assert (len(F.rat.ids), len(F.steps), F.days) == (80, 35040, 365)
    assert {k: int((F.rat.kind == k).sum()) for k in fleet.KINDS} == {"community": 20, "datacenter": 10, "pv_bess": 50}


@pytest.mark.engie_data
def test_engie_headline_result_one(engie_allocated):
    r = engie_allocated
    assert r["as_recorded_hours_at_80_or_more"] == 96
    assert (r["all_asked"]["hours_at_80_or_more"], r["all_asked"]["by_hour"]) == (19, {19: 19})
    assert r["plants_not_asked"]["hours_at_80_or_more"] == 84 and r["communities_only"]["hours_at_80_or_more"] == 81
    for key, _ in CASES:
        assert r[key]["limits_broken"] == NO_BREAK and r[key]["hours_at_100_or_more"] == 0
    assert r["batteries_mw"] == {"community": 25.8, "datacenter": 35.5, "pv_bess": 183.2}
    assert (r["all_asked"]["their_power_mw"], r["all_asked"]["give_at_19_and_20_mw"]) == (244.5, [242.6, 209.8])

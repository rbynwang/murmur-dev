"""The meter cleaning: the reading cleaner, its proof, the ruler and the whole pipeline on a synthetic pair of releases; on ENGIE's data
(marked engie_data) the cleaning's published figures."""
from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import releases_for_peak as synthetic  # noqa: E402
from experiments.engie import data, grid  # noqa: E402
from releases_for_peak import engie_root  # noqa: E402
from experiments.engie.meter_cleaning import __main__ as cli  # noqa: E402
from experiments.engie.meter_cleaning import cleaner, proof, ruler  # noqa: E402
from experiments.engie.meter_cleaning.pipeline import run  # noqa: E402

OUTPUTS = ["cleaning.json", "cleaning_past_only.json", "loading_2025_clean.npy", "loading_2025_clean_past_only.npy", "ruler.json",
           "ruler_by_kind.npy", "transformers.json"]


def shared_truth(rng: np.random.Generator, hours: int = 24 * 40, sensors: int = 12) -> np.ndarray:
    """Readings driven by two things every sensor shares: a daily swing and a slow drift."""
    t = np.arange(hours)
    drivers = np.stack([np.sin(2 * np.pi * t / 24), rng.standard_normal(hours).cumsum() / 10], axis=1)
    return 60 + drivers @ rng.uniform(2, 8, (2, sensors))


def test_clean_rebuilds_each_hour_and_sets_jumps_aside():
    rng = np.random.default_rng(1)
    truth = shared_truth(rng)
    X = truth + rng.normal(0, 1.0, truth.shape)
    jump = rng.random(truth.shape) < 0.002
    X[jump] += 25
    X[rng.random(truth.shape) < 0.03] = np.nan
    rebuilt, bad, sd = cleaner.clean(X, 2)
    assert np.sqrt(np.mean((rebuilt - truth) ** 2)) < 0.6                 # well under the readings' own noise of 1 point
    seen = jump & np.isfinite(X)
    assert (bad & seen).sum() >= 0.9 * seen.sum() and (bad & ~jump).sum() <= 0.01 * X.size     # a reading set aside wrongly is rebuilt
    assert 0.8 < np.median(sd) < 1.2
    assert np.isfinite(rebuilt).all()                                       # missing readings are rebuilt too


def test_past_only_uses_nothing_after_the_hour_it_cleans():
    rng = np.random.default_rng(2)
    X = shared_truth(rng) + rng.normal(0, 1.0, (24 * 40, 12))
    older = cleaner.patterns(X[:24 * 5] + 0.5, 2)                          # patterns of an older stretch of the same sensors
    first, bad1 = cleaner.past_only(X, 24, 2, older=older)
    for t0 in (5, 24 * 10 + 3, 24 * 30 + 5):                                # inside the first days, the daily days and a seven-day block
        later = X.copy()
        later[t0 + 1:] += 30
        again, bad2 = cleaner.past_only(later, 24, 2, older=older)
        np.testing.assert_array_equal(first[:t0 + 1], again[:t0 + 1])
        np.testing.assert_array_equal(bad1[:t0 + 1], bad2[:t0 + 1])


def test_one_hour_fits_known_patterns_and_sets_a_glitch_aside():
    m, sd = np.full(12, 50.0), np.ones(12)
    V = np.stack([np.ones(12), np.tile([1.0, -1.0], 6)]) / np.sqrt(12)       # two shared patterns
    clean_hour = m + np.array([6.0, 3.0]) @ V
    x = clean_hour.copy()
    x[2] += 20
    rebuilt, flagged = cleaner.one_hour(x, m, V, sd)
    np.testing.assert_allclose(rebuilt, clean_hour, atol=1e-9)
    assert np.flatnonzero(flagged).tolist() == [2]
    few = np.full(12, np.nan)
    few[2] = 60.0                                                            # fewer readings than patterns: the usual level stands
    rebuilt, flagged = cleaner.one_hour(few, m, V, sd)
    assert (rebuilt == m).all() and not flagged.any()


def test_single_hour_jumps_counts_only_a_rise_that_comes_straight_back():
    B = np.full((7, 4), 50.0)
    B[2, 0] = 50 + proof.JUMP                     # up for one hour: a jump
    B[2, 1] = 50 - proof.JUMP                     # down for one hour: not one
    B[2, 2], B[3, 2] = 50 + proof.JUMP, np.nan    # the hour after is missing: not counted
    B[3:, 3] = 70.0                               # up to stay: not one
    assert proof.single_hour_jumps(B) == 1
    jump_share, miss_share = proof.fault_shares(B)
    assert jump_share == pytest.approx(1 / np.isfinite(B).sum() * proof.JUMP_SCALE) and miss_share == pytest.approx(1 / B.size)


def test_faulty_adds_noise_jumps_and_gaps_in_the_shares_asked():
    truth = np.full((2000, 50), 60.0)
    noisy, jump = proof.faulty(truth, np.random.default_rng(3), 2.0, 0.01, 0.05)
    assert abs(jump.mean() - 0.01) < 0.002 and abs(np.isnan(noisy).mean() - 0.05) < 0.005
    plain = np.isfinite(noisy) & ~jump
    assert abs(np.std(noisy[plain] - 60) - 2.0) < 0.05
    assert abs(np.mean(noisy[jump & np.isfinite(noisy)] - 60) - (proof.JUMP + 40) / 2) < 1.0
    again, _ = proof.faulty(truth, np.random.default_rng(3), 2.0, 0.01, 0.05)
    np.testing.assert_array_equal(noisy, again)


def test_best_patterns_is_the_one_closest_to_the_truth_at_loaded_hours():
    avg = {1: {"error_when_true_is_70_or_more": 3.0}, 2: {"error_when_true_is_70_or_more": 0.9}, 3: {"error_when_true_is_70_or_more": 1.0}}
    assert proof.best_patterns(avg) == 2


def test_the_ruler_fit_reads_known_slopes_back():
    rng = np.random.default_rng(4)
    n = 600
    X = ruler.design(rng.uniform(300, 700, n), rng.uniform(5, 15, n), rng.uniform(-5, 5, (n, 3)))
    B = np.array([[20, 10], [.08, .05], [.3, .2], [-.5, .1], [-.3, -.2], [-.6, .4]])       # coefficients x transformers
    relief, fitted, se = ruler.response(X, X @ B + rng.normal(0, .2, (n, 2)), np.ones(n, dtype=bool))
    np.testing.assert_allclose(relief, -B[3:].T, atol=0.02)
    np.testing.assert_allclose(fitted, B, atol=0.5)
    assert relief.shape == (2, 3) and (se > 0).all()


def test_a_data_folder_is_a_release_or_holds_the_releases(tmp_path, monkeypatch):
    one = tmp_path / "any_name"
    one.mkdir()
    (one / data.MARK_2025).touch()
    assert data.release_2025(one) == one and data.release_2025(tmp_path) == one
    with pytest.raises(data.DataMissing, match="no subfolder"):
        data.release_2023(tmp_path)
    (tmp_path / "another").mkdir()
    (tmp_path / "another" / data.MARK_2025).touch()
    with pytest.raises(data.DataMissing, match="2 subfolders"):
        data.release_2025(tmp_path)
    monkeypatch.setenv(data.ENV, str(one))
    assert data.data_dir(None) == one and data.data_dir(str(tmp_path)) == tmp_path
    with pytest.raises(data.DataMissing, match="does not exist"):
        data.data_dir(str(tmp_path / "nowhere"))
    monkeypatch.delenv(data.ENV)
    with pytest.raises(data.DataMissing, match=data.ENV):
        data.data_dir(None)


def test_the_command_line_says_what_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(data.ENV, raising=False)
    assert cli.main(["--out", str(tmp_path / "out")]) == 2
    assert data.ENV in capsys.readouterr().err
    (tmp_path / "empty").mkdir()
    assert cli.main(["--data-dir", str(tmp_path / "empty"), "--out", str(tmp_path / "out")]) == 2
    assert data.MARK_2025 in capsys.readouterr().err


@pytest.fixture(scope="module")
def cleaned(tmp_path_factory):
    """The pipeline run once on the synthetic pair."""
    pair = synthetic.write_pair(tmp_path_factory.mktemp("releases"))
    out = tmp_path_factory.mktemp("meter_cleaning")
    said: list[str] = []
    return pair, out, run(pair.root, out, say=said.append), said


def test_the_pipeline_writes_every_output(cleaned):
    _, out, reports, said = cleaned
    assert sorted(p.name for p in out.iterdir()) == sorted(OUTPUTS) and len(said) == 4
    assert json.loads((out / "transformers.json").read_text())["transformers"] == list(synthetic.TRAFO)
    for name in ("loading_2025_clean.npy", "loading_2025_clean_past_only.npy"):
        assert np.load(out / name).shape == (synthetic.DAYS * 24, len(synthetic.TRAFO))
    c = reports["cleaning"]
    assert json.loads((out / "cleaning.json").read_text())["patterns_kept"] == c["patterns_kept"] in proof.PATTERNS_TRIED
    by_k = c["hours_at_80_or_more_in_2025_by_patterns_kept"]
    assert list(by_k) == list(proof.PATTERNS_TRIED) and by_k[c["patterns_kept"]] == c["readings_2025"]["hours_at_80_or_more"]["after_cleaning"]
    assert reports["cleaning_past_only"]["proof_on_2023"]["steps_a_day"] == 24


def test_cleaning_comes_closer_to_the_truth_than_the_readings(cleaned):
    pair, out, reports, _ = cleaned
    readings = grid.readings_2025(data.release_2025(pair.root)).loading
    seen = np.isfinite(readings)
    error = lambda a: float(np.sqrt(np.mean((a - pair.loading_2025)[seen] ** 2)))
    assert error(np.load(out / "loading_2025_clean.npy")) < 0.5 * error(readings)
    assert error(np.load(out / "loading_2025_clean_past_only.npy")) < 0.5 * error(readings)
    true = int(grid.strained(pair.loading_2025).sum())
    whole = reports["cleaning"]["readings_2025"]["hours_at_80_or_more"]
    past = reports["cleaning_past_only"]["readings_2025"]["hours_at_80_or_more"]
    assert abs(whole["after_cleaning"] - true) < abs(whole["as_read"] - true)
    assert abs(past["past_only_cleaner"] - true) < abs(past["as_read"] - true)
    assert 0 < reports["cleaning"]["single_hour_jumps_in_2025"] <= int(pair.jumps_2025.sum())
    kept = reports["cleaning"]["proof_on_2023_by_patterns_kept"][reports["cleaning"]["patterns_kept"]]
    assert kept["strained_hours_true"] == int(grid.strained(pair.truth_2023).sum())          # the proof reads the 2023 truth it was given


def test_the_ruler_reads_the_known_response_back(cleaned):
    _, out, reports, _ = cleaned
    np.testing.assert_allclose(np.load(out / "ruler_by_kind.npy"), synthetic.RELIEF, atol=0.1)
    r = reports["ruler"]
    assert r["same_80_participants_at_the_same_buses_in_both_releases"] is True
    assert set(r) >= {f"T{c}" for c in ruler.REPORTED} | {"what_it_means"}


@pytest.fixture(scope="module")
def engie_cleaned(tmp_path_factory):
    return run(engie_root(data.MARK_2025, data.MARK_2023), tmp_path_factory.mktemp("engie_meter_cleaning"), say=lambda _: None)


@pytest.mark.engie_data
def test_engie_readings_as_they_come():
    R = grid.readings_2025(data.release_2025(engie_root(data.MARK_2025)))
    assert R.loading.shape == (8760, 66) and int(np.isnan(R.loading).sum()) == 18476
    assert int(grid.strained(R.loading).sum()) == 196 and int((grid.top(R.loading) >= 100).sum()) == 10
    assert round(float(np.nanmax(R.loading)), 1) == 110.8 and proof.single_hour_jumps(R.loading) == 705


@pytest.mark.engie_data
def test_engie_published_cleaning_figures(engie_cleaned):
    c = engie_cleaned["cleaning"]
    r = c["readings_2025"]
    assert c["patterns_kept"] == 2 and c["single_hour_jumps_in_2025"] == 705
    assert r["hours_at_80_or_more"] == {"as_read": 196, "after_cleaning": 94, "in_both": 79}
    assert {j: c["hours_at_80_or_more_in_2025_by_patterns_kept"][j] for j in (2, 3, 4)} == {2: 94, 3: 97, 4: 116}     # how fragile the count is
    assert r["hours_at_100_or_more"] == {"as_read": 10, "after_cleaning": 0}
    assert r["highest_loading"] == {"as_read": 110.8, "after_cleaning": 85.3}
    assert r["by_hour_after_cleaning"] == {19: 78, 20: 16} and r["which_transformers_after_cleaning"] == {35: 84, 38: 74}
    assert (r["glitches_set_aside"], r["missing_rebuilt"], r["noise_found_points_per_sensor"]["median"]) == (1978, 18476, 1.46)
    best = c["proof_on_2023_by_patterns_kept"][2]
    assert (best["strained_hours_true"], best["as_read"], best["after_cleaning"], best["both"]) == (51.0, 184.67, 52.33, 42.67)
    noise = c["proof_by_noise_added"]
    assert [noise[n]["as_read"] for n in proof.NOISE_TRIED] == [172.67, 164.33, 182.0]
    assert [noise[n]["after_cleaning"] for n in proof.NOISE_TRIED] == [50.33, 50.67, 50.0]
    assert [noise[n]["error_when_true_is_70_or_more"] for n in proof.NOISE_TRIED] == [0.66, 0.76, 0.89]
    p = engie_cleaned["cleaning_past_only"]["readings_2025"]
    assert p["hours_at_80_or_more"] == {"as_read": 196, "whole_year_cleaner": 94, "past_only_cleaner": 96, "in_both_cleaners": 92}
    assert p["by_hour_past_only"] == {19: 80, 20: 16} and p["which_transformers_past_only"] == {35: 83, 38: 77}


@pytest.mark.engie_data
def test_engie_published_ruler(engie_cleaned):
    r = engie_cleaned["ruler"]
    t35, t38 = r["T35"], r["T38"]
    assert (t35["single_slope_per_100_mw"], t35["all_batteries_in_proportion_per_100_mw"], t35["relief_per_100_mw_given_by"]["pv_bess"]) == (3.52, 3.14, "+3.95 (+-0.10)")
    assert (t38["single_slope_per_100_mw"], t38["all_batteries_in_proportion_per_100_mw"], t38["relief_per_100_mw_given_by"]["pv_bess"]) == (3.4, 1.16, "+1.50 (+-0.08)")
    assert t38["the_grids_own_load_per_100_mw"] == 4.49
    assert r["what_it_means"]["most_relief_all_batteries_at_full_power_points"] == {"T35": 7.7, "T38": 2.8}
    assert (t35["on_weeks_the_fit_never_saw"]["share_explained"], t38["on_weeks_the_fit_never_saw"]["share_explained"]) == (0.959, 0.987)
    assert r["same_80_participants_at_the_same_buses_in_both_releases"] is True and r["hours_used"] == 2628

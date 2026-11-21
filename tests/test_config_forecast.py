"""Configuration, the files a service writes, the replay clock and a home's forecasts.

config.load layers the built-in DEFAULTS, the dataset's agent_defaults and the node's agent.json, and keeps the replay start inside the dataset's range; a secret
is an owner-only file; dataset and model files are named inside their folders. files.write_atomic swaps a whole file in and set_aside keeps an unusable one beside
it. The replay clock steps, holds, loops and jumps on a fixture home's record. A fixture home on forecast "temp_regression" forecasts every step it is asked for
from days already over, and fits its line on a synthetic record; kinds of day and the day-ahead temperature follow the calendar; the trained HomeForecaster and
TreeModel read tiny synthetic trees from tmp_path. The device catalog and the tool shelves are read for the fixture homes."""
from __future__ import annotations

import gzip
import json
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from murmur import config, files, replay
from murmur.node import devices, tools
from murmur.node.forecast import HomeForecaster, clear_sky, cos_zenith
from murmur.node.home import MemberNode
from murmur.node.home_days import day_kind, last_same_kind_step, temp_forecast
from murmur.node.treemodel import TreeModel
from murmur.protocol import signing
from tests.world import home

DAY2_10H, DAY2_18H = 96 + 40, 96 + 72          # rows of 2025-01-28 10:00 and 18:00: 96 quarter hours a day
NODE = {"f": 0, "thr": 0.0, "leaf": False, "v": 0.0, "miss_left": False, "cat": False, "l": 0, "r": 0, "bitset": 0}


@pytest.fixture
def wall(monkeypatch):
    """The replay's wall clock, moved by hand: [unix seconds]."""
    now = [1.8e9]
    monkeypatch.setattr(replay, "time", SimpleNamespace(time=lambda: now[0]))
    return now


def record(loop_days: int = 0) -> replay.Replay:
    return replay.Replay("homes/HH001", "2025-01-27 00:00", 60, loop_days)


def tree(*nodes: dict) -> dict:
    """One tree in the export's column form: a split sends a row left at x <= thr (or by its category bitset), a leaf adds v."""
    return {k: [n.get(k, d) for n in nodes] for k, d in NODE.items()}


def const(baseline: float) -> dict:
    return {"baseline": baseline, "trees": [tree({"leaf": True})], "bitsets": [[]]}


def write_model(path: Path, features: list[str], quantiles: dict, **more) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump({"features": features, "quantiles": {str(q): t for q, t in quantiles.items()}, **more}, f)


# ---------------------------------------------------------------------------------------------------------------- configuration
def test_settings_are_the_defaults_then_the_datasets_own_then_agent_json(agent_config):
    plain = config.load()
    assert (plain["battery_kwh"], plain["profile"], plain["clock_profile"]) == (13.5, "homes/HH001", "homes/HH001")
    agent_config(battery_kwh=20.0, profile="homes/HH002", llm_model="small")
    cfg = config.load()
    assert (cfg["battery_kwh"], cfg["profile"], cfg["clock_profile"], cfg["llm_model"], cfg["battery_kw"]) == (20.0, "homes/HH002", "homes/HH001", "small", 5.0)


def test_loaded_settings_are_a_copy_that_leaves_the_defaults_alone():
    config.load()["opt_out_days"]["home-01"] = ["2025-01-28"]
    assert config.DEFAULTS["opt_out_days"] == {} and config.load()["opt_out_days"] == {}


def test_a_built_in_default_saved_in_agent_json_leaves_the_datasets_default_in_force(agent_config, monkeypatch):
    monkeypatch.setitem(config.dataset_meta()["agent_defaults"], "battery_kwh", 9.0)
    agent_config(battery_kwh=13.5)
    assert config.load()["battery_kwh"] == 9.0
    agent_config(battery_kwh=12.0)
    assert config.load()["battery_kwh"] == 12.0


@pytest.mark.parametrize("start, kept", [("2025-01-27 06:00", True), ("2025-01-28 23:45", True), ("2025-01-26 23:45", False),
                                         ("2025-01-29 00:00", False), ("", False)])
def test_a_replay_start_outside_the_datasets_range_takes_the_datasets_start(agent_config, start, kept):
    agent_config(replay_start=start)
    assert config.load()["replay_start"] == (start if kept else "2025-01-27 00:00")


def test_a_secret_is_an_owner_only_file_read_back_without_its_spaces(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    assert config.secret("bus-token") == ""
    config.write_secret("bus-token", "  abc123 \n")
    f = tmp_path / "secrets" / "bus-token"
    assert (f.read_text(), f.stat().st_mode & 0o777, f.parent.stat().st_mode & 0o777) == ("abc123\n", 0o600, 0o700)
    assert config.secret("bus-token") == "abc123"


def test_dataset_and_model_files_are_named_inside_their_folders():
    assert config.DATA_DIR == Path(__file__).resolve().parent / "fixtures" / "data"
    assert config.data_path("homes/HH001.csv.gz") == config.DATA_DIR / "homes" / "HH001.csv.gz" and config.events_file() == config.DATA_DIR / "grid_events.json"
    assert config.model_path("models/forecast") == config.model_path("forecast") == config.MODELS_DIR / "forecast" and \
        config.model_path("models/models/forecast") == config.MODELS_DIR / "models" / "forecast"


# ---------------------------------------------------------------------------------------------------------------- files
def test_write_atomic_swaps_in_the_whole_file_and_clears_its_own_stale_temp_files(tmp_path):
    path = tmp_path / "state" / "plan.json"
    files.write_atomic(path, b"old")
    path.with_name(".plan.json.7.7").write_bytes(b"ha")          # left by a write killed before its rename
    path.with_name(".offer.json.7.7").write_bytes(b"x")
    files.write_atomic(path, b"new")
    assert (path.read_bytes(), path.stat().st_mode & 0o777) == (b"new", 0o600)
    assert sorted(p.name for p in path.parent.iterdir()) == [".offer.json.7.7", "plan.json"]


def test_set_aside_keeps_an_unusable_file_beside_it_as_old(tmp_path, caplog):
    p = tmp_path / "wishes.json"
    p.write_text("{not json")
    files.set_aside(p)
    assert not p.exists() and (tmp_path / "wishes.json.old").read_text() == "{not json"
    files.set_aside(tmp_path / "absent.json")
    assert "couldn't be set aside" in caplog.text


# ---------------------------------------------------------------------------------------------------------------- the replay clock
def test_a_running_clock_moves_one_dataset_step_per_step_seconds_and_stops_at_the_end(wall):
    rp, seen = record(), []
    for dt in (59, 1, 600, 1e6):
        wall[0] += dt
        seen.append(rp.current())
    assert seen == [0, 1, 11, 191] and rp.ts(11) == "2025-01-27 02:45" and not rp.held


def test_a_looping_clock_plays_one_step_at_one_wall_moment_and_starts_its_day_again(wall):
    wall[0] = 1000 * 96 * 60 + 5 * 60 + 30                         # five steps into a looped day
    a = replay.Replay("homes/HH001", "2025-01-28 00:00", 60, 1)
    wall[0] += 3600
    b = replay.Replay("homes/HH001", "2025-01-28 00:00", 60, 1)
    assert a.current() == b.current() == 96 + 65
    wall[0] += 31 * 60
    assert a.current() == 96


def test_a_held_clock_stays_on_its_step_until_it_is_set_running_again(wall):
    rp = record()
    rp.configure("2025-01-28 17:00", 60, 0, hold=True)
    wall[0] += 3600
    assert (rp.current(), rp.clock()["now"], rp.held) == (96 + 68, "2025-01-28 17:00", True)
    rp.configure("2025-01-28 17:00", 60, 0)
    wall[0] += 120
    assert (rp.current(), rp.held) == (96 + 70, False)


def test_a_jump_to_a_wall_moment_puts_clocks_set_at_different_times_on_one_step(wall):
    at_wall, a, b = wall[0] - 150, record(), record()
    a.configure("2025-01-27 00:00", 60, 0, at="2025-01-28 18:00", at_wall=at_wall)
    wall[0] += 600
    b.configure("2025-01-27 00:00", 60, 0, at="2025-01-28 18:00", at_wall=at_wall)
    assert a.current() == b.current() == DAY2_18H + 12 and a.clock()["start"] == "2025-01-28 18:00"
    with pytest.raises(ValueError, match="not in dataset"):
        a.configure("2025-02-01 00:00", 60, 0)


def test_a_jump_without_a_wall_moment_shows_the_asked_step_now(wall):
    rp = record()
    rp.configure("2025-01-27 00:00", 60, 0, at="2025-01-28 10:00")
    assert rp.current() == DAY2_10H


def test_a_held_jump_on_a_looping_clock_holds_the_asked_step(wall):
    wall[0] += 11 * 60                                             # eleven steps into a looped day
    rp = record(loop_days=1)
    rp.configure("2025-01-27 00:00", 60, 1, at="2025-01-28 10:00", hold=True)
    wall[0] += 120                                                 # two steps on: running, it would show 10:30
    assert (rp.current(), rp.held) == (DAY2_10H, True)


# ---------------------------------------------------------------------------------------------------------------- a home's own forecasts
def evening() -> dict:
    """A sale 18:00-21:00 on the second day, in six half-hour slots."""
    slots = [{"id": f"s{k}", "start": f"2025-01-28 {18 + k // 2}:{30 * (k % 2):02d}"} for k in range(6)]
    return {"event_id": "ev-1", "window_start": "2025-01-28 18:00", "window_end": "2025-01-28 21:00", "slots": slots}


@pytest.fixture
def offer_day(tmp_path):
    """home-01 on forecast temp_regression, its clock held at 10:00 on the second day, and its forecast for the evening sale."""
    node, _ = home("home-01", tmp_path)
    node.replay.configure("2025-01-28 10:00", 60, 0, hold=True)
    return node, node.forecast_window(evening())


def test_a_temp_regression_home_forecasts_every_step_from_now_through_the_evening(offer_day):
    _, fc = offer_day
    assert (len(fc["lead"]), len(fc["steps"]), len(fc["post"])) == (31, 12, 32)
    assert (fc["lead"][0]["ts"], fc["steps"][0]["ts"], fc["post"][0]["ts"]) == ("2025-01-28 10:15", "2025-01-28 18:00", "2025-01-28 21:00")
    assert all(math.isfinite(x[k]) for part in ("lead", "steps", "post") for x in fc[part] for k in ("pv_p50", "load_p50", "ev_kw"))
    assert fc["post"][-1] == {"ts": "2025-01-29 04:45", "pv_p50": 0.0, "load_p50": 0.0, "ev_kw": 0.0}      # past the record's end
    assert fc["method"] == "load: hour-of-day regression on day-ahead temperature, previous 21 days; PV: previous 3 days; EV: latest session"


def test_with_too_little_history_for_the_line_a_step_is_forecast_as_the_same_step_the_day_before(offer_day, monkeypatch):
    node, _ = offer_day
    dim = [dict(r, pv_kw=0.5 * r["pv_kw"]) if r["ts_local"][:10] == "2025-01-28" else r for r in node.replay.rows]
    monkeypatch.setattr(node.replay, "rows", dim)                          # the fixture's two days have the same sun: the second one dims
    fc = node.forecast_window(evening())
    before = lambda x: node.replay.row(node.replay.idx_of(x["ts"]) - 96)          # noqa: E731
    assert [x["load_p50"] for x in fc["steps"]] == [round(before(x)["base_kw"], 3) for x in fc["steps"]]
    assert [x["pv_p50"] for x in fc["lead"]] == [round(before(x)["pv_kw"], 3) for x in fc["lead"]] and max(x["pv_p50"] for x in fc["lead"]) > 1.0


def test_the_car_is_forecast_to_charge_its_latest_session_at_full_power_from_the_same_time_today(offer_day):
    _, fc = offer_day
    assert fc["ev"] == {"arrival": "2025-01-28 18:30", "deadline": "2025-01-29 07:00", "kwh": 14.0, "max_kw": 7.2}
    assert [x["ev_kw"] for x in fc["steps"]] == [0.0, 0.0] + [7.2] * 7 + [5.6, 0.0, 0.0]


def test_the_real_time_forecast_answers_every_asked_step_from_days_already_over(tmp_path):
    node, _ = home("home-01", tmp_path)
    ts = [f"2025-01-28 {h}:{m:02d}" for h in (18, 19) for m in (0, 15, 30, 45)]
    rt = node.rt_forecast(DAY2_10H, ts)
    assert list(rt) == ts and rt == {t: (node.replay.row(i - 96)["pv_kw"], node.replay.row(i - 96)["base_kw"]) for t, i in zip(ts, range(DAY2_18H, DAY2_18H + 8))}
    assert node.rt_forecast(40, ["2025-01-28 16:00"]) == {"2025-01-28 16:00": (0.0, 0.0)}     # at 10:00 the day before, its 16:00 is still to come


def test_a_trained_home_without_model_files_falls_back_to_the_day_ahead_rule_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "none")
    node, _ = home("home-01", tmp_path, forecast="trained")
    logged: list[str] = []
    node.log = lambda kind, **kw: logged.append(kind)
    rt = node.rt_forecast(DAY2_10H, ["2025-01-28 18:00"])
    assert rt == {"2025-01-28 18:00": (node.replay.row(DAY2_18H - 96)["pv_kw"], node.replay.row(DAY2_18H - 96)["base_kw"])}
    assert logged == ["rt_forecast_fallback"]


def test_temp_regression_reads_the_line_through_the_same_hour_on_earlier_days_at_the_forecast_temperature(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_META", {})                            # a dataset with no settings file: the fixture's stay unread, and uncached
    monkeypatch.setattr(replay, "_CACHE", {})
    lines = ["ts_local,pv_kw,base_kw,temp_c,fc_temp_c"]                # six days whose load is 0.5 kW, 0.05 kW per hour of day and 0.1 kW per degree
    for q in range(6 * 96):
        t = q / 96 + (q % 96) / 10
        lines.append(f"2025-02-{q // 96 + 1:02d} {q % 96 // 4:02d}:{15 * (q % 4):02d},0.0,{0.5 + 0.05 * (q % 96 // 4) + 0.1 * t},{t},{t + 3}")
    (tmp_path / "homes").mkdir()
    with gzip.open(tmp_path / "homes" / "LINE.csv.gz", "wt") as f:
        f.write("\n".join(lines) + "\n")
    (tmp_path / "homes" / "LINE_ev.csv").write_text("arrival_local,deadline_local,kwh,max_kw\n")
    rp = replay.Replay("homes/LINE", "2025-02-01 00:00", 60, 0)
    node = MemberNode("home-01", {"forecast": "temp_regression"}, SimpleNamespace(ctl=None), rp, signing.load_or_create(tmp_path / "k.key"),
                      send=lambda *a: None, trusted=lambda: [], log=lambda *a, **k: None)
    i = 5 * 96 + 72                                                # 18:00 on the sixth day: the line has 5 days x 4 quarter hours, all at 18:xx
    assert node.rt_forecast(5 * 96, [rp.ts(i)])[rp.ts(i)] == pytest.approx((0.0, 0.5 + 0.05 * 18 + 0.1 * rp.row(i)["fc_temp_c"]))


def test_a_holiday_counts_as_a_sunday_and_the_same_kind_step_is_on_the_last_past_day_of_that_kind():
    assert [day_kind(d, {"2025-01-28"}) for d in ("2025-01-24", "2025-01-25", "2025-01-26", "2025-01-28")] == [0, 1, 2, 2]
    assert last_same_kind_step(DAY2_18H, DAY2_10H, record().ts, set()) == DAY2_18H - 96
    assert last_same_kind_step(DAY2_18H, DAY2_10H, record().ts, {"2025-01-27"}) is None      # the record holds no earlier weekday


def test_the_day_ahead_temperature_misses_by_one_error_per_day():
    err = temp_forecast("2025-01-28 06:00", 0.0)
    assert temp_forecast("2025-01-28 18:00", 5.0) == pytest.approx(5.0 + err) and temp_forecast("2025-01-27 18:00", 0.0) != err


# ---------------------------------------------------------------------------------------------------------------- trained trees
@pytest.fixture
def trained(monkeypatch, tmp_path):
    """home-01's trained forecaster on constant trees in tmp_path: load 0.6 / 1.0 / 1.5 (mean 1.1) of its scale, solar 0.5 / 0.8 / 0.9 of clear sky."""
    write_model(tmp_path / "forecast" / "home_base_load.json.gz", ["hour"], {0.1: const(0.6), 0.5: const(1.0), 0.9: const(1.5)}, extra={"mean": const(1.1)})
    write_model(tmp_path / "forecast" / "solar_per_kw.json.gz", ["hour"], {0.1: const(0.5), 0.5: const(0.8), 0.9: const(0.9)})
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    rp = record()
    return HomeForecaster("home-01", rp), rp


def test_trained_load_is_the_trees_times_the_homes_mean_hour_widened_by_the_share_of_hours_missing(trained):
    fc, rp = trained
    out = fc.forecast(DAY2_10H, ["2025-01-28 18:00", "2025-01-28 18:45", "2025-01-29 00:00"])
    s = sum(rp.rows[i]["base_kw"] for i in range(0, DAY2_10H, 4)) / 34        # the 34 hourly readings before the issue hour
    wide = 1 + (336 - 34) / 336
    assert list(out) == ["2025-01-28 18:00", "2025-01-28 18:45"] and out["2025-01-28 18:00"] == out["2025-01-28 18:45"]
    assert out["2025-01-28 18:45"]["load"] == pytest.approx((s - 0.4 * s * wide, s, s + 0.5 * s * wide))
    assert (out["2025-01-28 18:45"]["load_mean"], out["2025-01-28 18:45"]["pv"]) == (pytest.approx(1.1 * s), (0.0, 0.0, 0.0))
    assert (fc.last["how"], fc.last["readings_of_336"]) == ("model, missing inputs as no value", 34)


def test_trained_solar_is_the_trees_share_of_clear_sky_sunlight_per_kw_of_panels(trained):
    fc, _ = trained
    sun = clear_sky(cos_zenith(datetime(2025, 1, 28, 17, 0), 42.36, -71.06))     # the hour from noon at the dataset's UTC-5
    assert 460 < sun < 480
    pv = fc.forecast(DAY2_10H, ["2025-01-28 12:00"])["2025-01-28 12:00"]["pv"]
    assert pv == pytest.approx(tuple(q * sun / 1000 * 3.0 for q in (0.5, 0.8, 0.9)))


@pytest.fixture
def tiny(monkeypatch, tmp_path) -> TreeModel:
    """The middle quantile and the mean: 1 plus two trees over [kind, temp], temp <= 10 adding 0.25 (a missing temp goes left) else 0.75,
    and kind 7 or 9 adding 10 else 20 (an unknown kind is missing and goes right). The 10 % and 90 % quantiles are 12 and 15: they cross it."""
    temp = tree({"f": 1, "thr": 10.0, "miss_left": True, "l": 1, "r": 2}, {"leaf": True, "v": 0.25}, {"leaf": True, "v": 0.75})
    kind = tree({"f": 0, "cat": True, "l": 1, "r": 2}, {"leaf": True, "v": 10.0}, {"leaf": True, "v": 20.0})
    both = {"baseline": 1.0, "trees": [temp, kind], "bitsets": [[0] * 8, [0b110] + [0] * 7]}
    write_model(tmp_path / "tiny" / "m.json.gz", ["temp", "kind"], {0.9: const(15.0), 0.1: const(12.0), 0.5: both}, order=["kind", "temp"],
                categories={"kind": [3.0, 7.0, 9.0]}, widen=0.5, extra={"mean": both})
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    return TreeModel.load(config.model_path("models/tiny") / "m.json.gz")


ROWS = [{"temp": 5.0, "kind": 7.0}, {"temp": 12.0, "kind": 3.0}, {"temp": None, "kind": 5.0}, {"temp": 10.0, "kind": 9.0}]


def test_a_tree_model_adds_up_the_leaves_each_row_reaches(tiny):
    np.testing.assert_array_equal(tiny.matrix(ROWS), [[1.0, 5.0], [0.0, 12.0], [np.nan, np.nan], [2.0, 10.0]])
    assert tiny.predict_extra("mean", ROWS).tolist() == [11.25, 21.75, 21.25, 11.25]
    assert (tiny.quantiles, tiny.has("mean"), tiny.has("charging_logit")) == ([0.1, 0.5, 0.9], True, False)


def test_tree_quantiles_are_sorted_per_row_and_widened_when_calibrated(tiny):
    assert [x.tolist() for x in tiny.predict(ROWS, calibrated=False)] == [[11.25, 12.0, 12.0, 11.25], [12.0, 15.0, 15.0, 12.0], [15.0, 21.75, 21.25, 15.0]]
    lo, _, hi = tiny.predict(ROWS)
    assert (lo.tolist(), hi.tolist()) == ([10.75, 11.5, 11.5, 10.75], [15.5, 22.25, 21.75, 15.5])


# ---------------------------------------------------------------------------------------------------------------- devices and tools
def test_a_home_has_the_switched_on_devices_that_draw_on_its_row():
    assert sorted(devices.catalog()["devices"]["home"]) == ["dryer", "hpwh", "v2h"]
    specs, arrays, row = devices.for_node("home", "home-02")
    assert (sorted(specs), row, float(arrays["dryer"][row].max())) == (["dryer", "hpwh", "v2h"], 1, pytest.approx(5.6))
    specs, _, row = devices.for_node("home", "home-01")
    assert (sorted(specs), row, specs["hpwh"]["kw"]) == (["hpwh"], 0, 1.7)      # its dryer and car rows draw nothing
    assert (devices.stagger_min(), devices.catch_up_after_min()) == (120, 90)


def test_devices_follow_the_switch_and_a_node_off_the_catalog_has_none(monkeypatch):
    monkeypatch.setattr(devices, "_ON", "hpwh")
    assert sorted(devices.for_node("home", "home-02")[0]) == ["hpwh"]
    monkeypatch.setattr(devices, "_ON", "")
    assert devices.for_node("home", "home-02") == ({}, {}, None)
    monkeypatch.setattr(devices, "_ON", "all")
    assert devices.for_node("home", "home-09") == ({}, {}, None)
    specs, _, row = devices.for_node("building", "building-01")
    assert (sorted(specs), row) == (["fans", "plugs"], 0)


def test_a_homes_tool_shelf_is_found_by_its_record_id_and_tier():
    assert tools.home_id("home-03") == "HH003"
    shelf = tools.shelf("home-01", 1)
    assert shelf == ["delay_appliance", "discharge_car", "limit_ev_charging", "set_battery", "set_room_ac", "set_water_heater"]
    assert tools.shelf("home-03", 2) == ["limit_ev_charging", "set_battery", "set_thermostat", "set_water_heater"]
    assert tools.shelf("home-01", 3) == ["limit_ev_charging"] and tools.shelf("home-01", 4) == tools.shelf("home-09", 1) == []
    assert all(c["required"] and not {"start", "end"} & set(c["properties"]) for c in (tools.spec("home", t)["function"]["parameters"] for t in shelf))  # code sets times

"""What the meter-cleaning and peak-allocation tests share: a small synthetic pair of ENGIE-like releases, and ENGIE's own data folder when the
run is given one.

The synthetic 2023 release holds a true grid state built with a known response to the batteries (RELIEF), so the ruler has a right answer.
The 2025 release holds noisy readings of the same transformers (single-hour jumps, gaps, rows of bad quality or of another source) and the
batteries' reports (slots never sent, late copies, reports signed in another participant's name, bad signatures, one spike of charge, a
participant without a battery). File names, columns and clocks are ENGIE's; every number is made up. Five weeks of each year keep the
pipelines fast.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.engie import data

ZONE = "America/Chicago"
DAYS = 35
DT = 0.25
TRAFO = (33, 34, 35, 36, 37, 38, 39, 40, 41, 42)
KINDS = ("community", "datacenter", "pv_bess")
KIND = {"C1": "community", "C2": "community", "C3": "community", "D1": "datacenter", "D2": "datacenter", "D3": "datacenter",
        "P1": "pv_bess", "P2": "pv_bess", "P3": "pv_bess"}
POWER = {"community": 1000.0, "datacenter": 1500.0, "pv_bess": 2500.0}       # kW; every battery holds two hours at full power
GIVE_F = 0.95                     # kWh that reach the connection per kWh taken out of a store
BUS = {name: 100 + n for n, name in enumerate([*KIND, "N1"])}
# true loading, points = BASE + LOAD x the grid's own load (MW) + DRAW x the sites' draw with batteries idle (MW) - RELIEF x MW given, by kind
BASE = np.array([20, 25, 24, 30, 28, 20, 26, 24, 30, 35.0])
LOAD = np.array([.06, .05, .085, .045, .05, .09, .05, .06, .04, .03])
DRAW = np.array([.2, .3, .3, .1, .2, .2, .4, .3, .1, .2])
RELIEF = np.array([[.10, .05, .20], [.05, .10, .15], [.50, .30, .60], [.00, .05, .10], [.05, .00, .10],
                   [-.05, .10, .45], [.30, .40, -.10], [-.20, .00, .30], [.10, .10, .10], [.00, .00, .05]])


@dataclass(frozen=True)
class Pair:
    root: Path                    # holds release_2023/ and release_2025/
    truth_2023: np.ndarray        # hours x transformers
    loading_2025: np.ndarray      # the true loading behind the 2025 readings
    jumps_2025: np.ndarray        # where a 2025 reading was given a single-hour jump


def _clock(year: int) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """Every 15 minutes from local midnight of 1 January, stamped in UTC as ENGIE does; the local time of day in hours; the local day."""
    steps = pd.date_range(f"{year}-01-01 06:00", periods=DAYS * 96, freq="15min", tz="UTC")
    at = steps.tz_convert(ZONE)
    return steps, np.asarray(at.hour + at.minute / 60), np.asarray(at.dayofyear) - 1


def _evening(x: np.ndarray) -> np.ndarray:
    return np.exp(-((x - 19.5) / 2.0) ** 2)


def _grid_and_sites(rng: np.random.Generator, x: np.ndarray, day: np.ndarray, kinds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The grid's own load (MW) and each site's net power with its battery idle (kW, + sent out), every 15 minutes."""
    lift = 1 + 0.06 * rng.standard_normal(DAYS)
    bg = 380 + 260 * _evening(x) * lift[day] + 40 * np.exp(-((x - 8) / 1.5) ** 2) + rng.normal(0, 3, len(x))
    sun = np.clip(np.sin(np.pi * (x - 7) / 10), 0, None) * rng.uniform(0.3, 1.0, DAYS)[day]
    shape = {"community": -(1200 + 1800 * _evening(x)), "datacenter": np.full(len(x), -2500.0), "pv_bess": 3000 * sun - 50}
    site = np.stack([shape[k] * rng.uniform(0.8, 1.2) for k in kinds], axis=1) + rng.normal(0, 30, (len(x), len(kinds)))
    return bg, site


def _hourly(a: np.ndarray) -> np.ndarray:
    """The mean over each hour of a series with a row every 15 minutes from the hour."""
    return a.reshape(len(a) // 4, 4, *a.shape[1:]).mean(axis=1)


def true_loading(bg: np.ndarray, site: np.ndarray, bt: np.ndarray, kinds: np.ndarray) -> np.ndarray:
    """The transformers' loading, hours x transformers, from the 15-minute grid load (MW), sites (kW) and batteries (kW given)."""
    given = np.stack([_hourly(bt[:, kinds == k].sum(axis=1)) / 1000 for k in KINDS], axis=1)
    return BASE + np.outer(_hourly(bg), LOAD) + np.outer(-_hourly(site.sum(axis=1)) / 1000, DRAW) - given @ RELIEF.T


def batteries_as_recorded(x: np.ndarray, power: np.ndarray, energy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Charge at half power from 10:00 until 90% full, give at full power from 16:00 until 10%: each store's charge after each step (share of
    its energy) and what each battery gives at the connection (kW, + out)."""
    level, soc, bt = 0.5 * energy, np.empty((len(x), len(power))), np.empty((len(x), len(power)))
    for t, h in enumerate(x):
        if 10 <= h < 14:
            w = np.maximum(np.minimum(0.5 * power * DT, 0.9 * energy - level), 0.0)
            g = -w / DT
        elif 16 <= h < 22:
            w = -np.maximum(np.minimum(power * DT / GIVE_F, level - 0.1 * energy), 0.0)
            g = -w * GIVE_F / DT
        else:
            w = g = np.zeros(len(power))
        level = level + w
        soc[t], bt[t] = level / energy, g
    return soc, bt


def _release_2023(folder: Path, rng: np.random.Generator, ids: list[str], kinds: np.ndarray, power: np.ndarray) -> np.ndarray:
    steps, x, day = _clock(2023)
    bg, site = _grid_and_sites(rng, x, day, kinds)
    bt = np.repeat(rng.uniform(-0.8, 0.8, (DAYS * 24, len(ids))), 4, axis=0) * power        # a simulated year: any battery power will do
    p = site + bt
    truth = true_loading(bg, site, bt, kinds) + rng.normal(0, 0.3, (DAYS * 24, len(TRAFO)))
    hours = pd.Index(steps[::4], name="timestamp")
    pd.DataFrame({f"loading_pct_t{c}": truth[:, i] for i, c in enumerate(TRAFO)}, index=hours).to_parquet(folder / "grid_powerflow_results_2023.parquet")
    pd.DataFrame({"net_load_dispatched_mw": bg - p.sum(axis=1) / 1000}, index=pd.Index(steps, name="timestamp")).to_parquet(
        folder / "system_prices_and_load_2023_15min.parquet")
    pd.DataFrame({"p_net_kw": p.ravel(), "bess_power_true_kw": bt.ravel()},
                 index=pd.MultiIndex.from_product([steps, ids], names=["timestamp", "entity_id"])).to_parquet(folder / "agents_timeseries_2023_15min.parquet")
    pd.DataFrame({"entity_id": ids, "bus": [BUS[i] for i in ids]}).to_parquet(folder / "agents_metadata.parquet")
    return truth


def _reports(steps: pd.DatetimeIndex, ids: list[str], p: np.ndarray, soc: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    n = len(ids)
    r = pd.DataFrame({"timestamp": steps.repeat(n), "entity_id": np.tile(ids, len(steps)), "reported_p_net_kw": p.ravel(),
                      "reported_soc_percent": 100 * soc.ravel()})
    r["claimed_entity_id"], r["auth_status"], r["delivered_at"] = r.entity_id, "valid", r.timestamp + pd.to_timedelta(2, unit="min")
    r = r[rng.random(len(r)) >= 0.01]
    late = r.sample(40, random_state=1).assign(delivered_at=lambda d: d.delivered_at + pd.to_timedelta(1, unit="h"), reported_p_net_kw=9e5)
    forged = r.sample(40, random_state=2).assign(reported_p_net_kw=-9e5, reported_soc_percent=1.0)
    forged["claimed_entity_id"] = np.where(forged.entity_id == "C1", "C2", "C1")
    unsigned = r.sample(40, random_state=3).assign(auth_status="invalid", reported_soc_percent=99.0)
    idle = pd.DataFrame({"timestamp": steps, "entity_id": "N1", "claimed_entity_id": "N1", "auth_status": "valid", "delivered_at": steps,
                         "reported_p_net_kw": -400.0, "reported_soc_percent": 0.0})
    return pd.concat([r, late, forged, unsigned, idle], ignore_index=True).sample(frac=1, random_state=4)


def _readings(hours: pd.DatetimeIndex, loading: np.ndarray, rng: np.random.Generator) -> tuple[pd.DataFrame, np.ndarray]:
    noisy = loading + rng.normal(0, 1.5, loading.shape)
    jump = rng.random(loading.shape) < 0.003
    noisy = noisy + jump * rng.uniform(12, 40, loading.shape)
    o = pd.DataFrame({"source": "scada_trafo_loading", "asset_id": np.tile([str(c) for c in TRAFO], len(hours)), "measured_at": hours.repeat(len(TRAFO)),
                      "value": noisy.ravel(), "quality": "good"})
    o.loc[rng.random(len(o)) < 0.03, ["value", "quality"]] = [250.0, "bad"]
    o = o[rng.random(len(o)) >= 0.01]
    return pd.concat([o, o.head(200).assign(source="scada_line_loading", value=300.0)], ignore_index=True), jump


def _release_2025(folder: Path, rng: np.random.Generator, ids: list[str], kinds: np.ndarray, power: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    steps, x, day = _clock(2025)
    bg, site = _grid_and_sites(rng, x, day, kinds)
    soc, bt = batteries_as_recorded(x, power, 2 * power)
    loading = true_loading(bg, site, bt, kinds)
    reported = soc.copy()
    reported[3 * 96 + 8, 0] += 0.25                       # one report whose charge jumps for a single step and comes straight back
    _reports(steps, ids, site + bt, reported, rng).to_parquet(folder / "reports.parquet")
    obs, jump = _readings(steps[::4], loading, rng)
    obs.to_parquet(folder / "obs_grid.parquet")
    limit = [np.nan if i == "D1" else 4500.0 if i == "P1" else 1e5 for i in ids]
    pd.DataFrame({"entity_id": [*ids, "N1"], "entity_type": [*kinds, "community"], "bess_power_kw": [*power, 0.0], "bess_energy_kwh": [*(2 * power), 0.0],
                  "poi_limit_kw": [*limit, 1e5]}).to_parquet(folder / "asset_ratings.parquet")
    pd.DataFrame({"entity_id": [*ids, "N1"], "entity_type": [*kinds, "community"], "bus": [BUS[i] for i in [*ids, "N1"]]}).to_parquet(folder / "nodes.parquet")
    return loading, jump


def engie_root(*markers: str) -> Path:
    """ENGIE's data folder ($MURMUR_ENGIE_DATA_DIR), or a skip that says which release it lacks."""
    root = Path(os.environ[data.ENV])
    for marker in markers:
        try:
            data.release(root, marker)
        except data.DataMissing as e:
            pytest.skip(f"{data.ENV} holds no release with {marker}: {e}")
    return root


def write_pair(root: Path, seed: int = 7) -> Pair:
    """Both releases, in root/release_2023 and root/release_2025."""
    rng = np.random.default_rng(seed)
    ids = list(KIND)
    kinds = np.array([KIND[i] for i in ids])
    power = np.array([POWER[k] for k in kinds])
    (root / "release_2023").mkdir(parents=True)
    (root / "release_2025").mkdir()
    truth = _release_2023(root / "release_2023", rng, ids, kinds, power)
    loading, jump = _release_2025(root / "release_2025", rng, ids, kinds, power)
    return Pair(root, truth, loading, jump)

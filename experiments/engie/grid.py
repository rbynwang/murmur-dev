"""The grid's transformer loading: ENGIE's hourly 2025 readings, and the true 2023 state of the same 66 transformers."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .data import MARK_2023, local, utc


@dataclass(frozen=True)
class Readings:
    """ENGIE's 2025 transformer readings: one row an hour, one column a transformer, percent of rating, NaN where no good reading came."""
    hours: pd.DatetimeIndex       # UTC, time-zone free
    loading: np.ndarray           # hours x transformers
    trafo: np.ndarray             # the transformers' ids, in column order
    hour: np.ndarray              # local hour of the day of each row
    day: np.ndarray               # local day of the year of each row, from 0
    year: np.ndarray              # local year of each row

    def column(self, trafo_id: int) -> int:
        return int(np.flatnonzero(self.trafo == trafo_id)[0])


def readings_2025(folder: Path) -> Readings:
    """The readings ENGIE marks good, from its supervisory system's transformer loading."""
    o = pq.read_table(folder / "obs_grid.parquet", columns=["source", "asset_id", "measured_at", "value", "quality"]).to_pandas()
    o = o[(o.quality == "good") & (o.source == "scada_trafo_loading")]
    table = o.assign(U=utc(o.measured_at)).pivot_table(index="U", columns="asset_id", values="value")
    table.columns = table.columns.astype(int)
    hours = pd.DatetimeIndex(table.index)
    at = local(hours)
    return Readings(hours, table.to_numpy(), np.asarray(table.columns), np.asarray(at.hour), np.asarray(at.dayofyear) - 1, np.asarray(at.year))


def grid_2023(folder: Path) -> pd.DataFrame:
    """The 2023 release's true grid state, one row an hour."""
    return pd.read_parquet(folder / MARK_2023)


def truth_2023(g23: pd.DataFrame, trafo: np.ndarray) -> np.ndarray:
    """The true 2023 loading of the transformers, in the given column order."""
    return g23[[f"loading_pct_t{c}" for c in trafo]].to_numpy()


def system_load_2023(folder: Path) -> pd.DataFrame:
    """The 2023 release's system load and prices, every 15 minutes."""
    return pd.read_parquet(folder / "system_prices_and_load_2023_15min.parquet")


def by_day_hour(R: Readings, loading: np.ndarray, days: int, year: int) -> np.ndarray:
    """A loading table (the readings' rows) laid out by local day of `year` and hour: days x 24 x transformers, NaN where no row falls."""
    out = np.full((days, 24, loading.shape[1]), np.nan)
    ok = R.year == year
    out[R.day[ok], R.hour[ok]] = loading[ok]
    return out


def top(loading: np.ndarray) -> np.ndarray:
    """The highest loading of each hour across the transformers (NaN for an hour with no reading at all)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmax(loading, axis=1)


def strained(loading: np.ndarray, at: float = 80.0) -> np.ndarray:
    """The hours in which any transformer is at `at` percent or more."""
    return top(loading) >= at

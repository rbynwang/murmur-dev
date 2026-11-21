"""Where ENGIE's data releases are, the participants' clock, and how a pipeline writes what it finds.

ENGIE publishes two releases of the same grid and the same 80 participants:

  the 2025 release   the trust challenge: the participants' reports, their ratings, meter and device readings, hourly grid readings (noisy, with no
                     truth) and prices. Its folder holds `reports.parquet`.
  the 2023 release   a simulated year that holds the true grid state: true transformer loading, each participant's true battery power, the grid's
                     own load. Its folder holds `grid_powerflow_results_2023.parquet`.

A data folder (`--data-dir`, else $MURMUR_ENGIE_DATA_DIR) is either one release's own folder or a folder that holds the releases as subfolders,
under any names. The recorded evening runs that `year_runs compare` reads are not data: they come with that package (year_runs/evening_runs.json.gz).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ENV = "MURMUR_ENGIE_DATA_DIR"
MARK_2025 = "reports.parquet"
MARK_2023 = "grid_powerflow_results_2023.parquet"
ZONE = "America/Chicago"          # the participants' local clock


class DataMissing(FileNotFoundError):
    """A data folder or one of ENGIE's releases is not where the run was told to look."""


def data_dir(arg: str | os.PathLike | None = None) -> Path:
    """The data folder: the argument, else $MURMUR_ENGIE_DATA_DIR."""
    raw = arg or os.environ.get(ENV)
    if not raw:
        raise DataMissing(f"no data folder: pass --data-dir or set {ENV} to the folder that holds ENGIE's releases")
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise DataMissing(f"the data folder {root} does not exist")
    return root


def release(root: Path, marker: str) -> Path:
    """The folder of one release: `root` itself when it holds `marker`, else the one subfolder of `root` that does."""
    if (root / marker).exists():
        return root
    found = sorted(p for p in root.iterdir() if p.is_dir() and (p / marker).exists())
    if len(found) != 1:
        what = "no subfolder" if not found else f"{len(found)} subfolders"
        raise DataMissing(f"{what} of {root} holds {marker}: point the data folder at ENGIE's release, or at a folder that holds it")
    return found[0]


def release_2025(root: Path) -> Path:
    return release(root, MARK_2025)


def release_2023(root: Path) -> Path:
    return release(root, MARK_2023)


def utc(x: Any) -> pd.DatetimeIndex:
    """Timestamps as a time-zone-free UTC index."""
    return pd.DatetimeIndex(pd.to_datetime(x, utc=True)).tz_localize(None)


def local(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """A time-zone-free UTC index on the participants' local clock."""
    return index.tz_localize("UTC").tz_convert(ZONE)


def counts_by_hour(hours: np.ndarray) -> dict[int, int]:
    """How many of the given local hours of the day fall on each hour, in hour order."""
    s = pd.Series(np.asarray(hours)).value_counts().sort_index()
    return {int(h): int(n) for h, n in s.items()}


def mw(x: float) -> float:
    return round(float(x), 1)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False))


def parser(description: str) -> argparse.ArgumentParser:
    """The arguments every pipeline takes: the data folder and the output folder."""
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--data-dir", default=None, help=f"the folder that holds ENGIE's releases (default ${ENV})")
    p.add_argument("--out", required=True, help="the folder the results are written to (made if missing)")
    return p


def out_dir(arg: str) -> Path:
    out = Path(arg).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return out

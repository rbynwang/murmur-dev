"""The recorded evenings the demo pages replay: gzip JSON files under `demo/recordings/`, with neutral participant ids.

Each set is one folder: `evening_2025-01-28` (one evening with three single sites), `whole_evening_2025-01-28` (the same evening
with twelve single sites), `year_engie_weather` and `year_real_weather` (twelve evenings of 2025, one a month, each with its
`results_engie.json.gz`).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent / "recordings"
RESULTS = "results_engie.json.gz"


def load(path: str | Path) -> dict[str, Any]:
    """One recording (or a set's results file), read from its gzip JSON."""
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))


def evenings(folder: str | Path) -> list[Path]:
    """A set's evening recordings, in date order."""
    return sorted(Path(folder).glob("trace_engie_*.json.gz"))


def results(folder: str | Path) -> dict[str, Any]:
    """A year set's results: its title, lead, one row per evening and the lines under the table."""
    return load(Path(folder) / RESULTS)

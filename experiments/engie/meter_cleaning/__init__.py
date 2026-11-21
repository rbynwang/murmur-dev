"""Meter cleaning: ENGIE's 2025 grid readings are noisy snapshots, not ground truth, so they are cleaned, the cleaning is proven on the 2023 true
grid state, and the ruler (each transformer's response to the batteries) is read off that true state.

  python -m experiments.engie.meter_cleaning --data-dir DIR --out OUT

Writes into OUT:
  cleaning.json                       the proof on 2023 by patterns kept and by noise level, and what the whole-year cleaner finds in 2025
  cleaning_past_only.json             the cleaner that uses only the past, proven the same way, and its 2025 readings against the whole-year cleaner's
  ruler.json                          each listed transformer's true response by kind of participant, with its checks
  loading_2025_clean.npy              the 2025 readings cleaned with the whole year (hours x transformers, the readings' column order)
  loading_2025_clean_past_only.npy    the same, each hour cleaned with the past only: what the peak allocation reads
  ruler_by_kind.npy                   transformers x kinds (community, datacenter, pv_bess): points of loading relieved per MW given
  transformers.json                   the transformers' ids in column order, and the readings' hours
"""
from __future__ import annotations

from pathlib import Path

CLEAN_PAST = "loading_2025_clean_past_only.npy"
RULER = "ruler_by_kind.npy"
COLUMNS = "transformers.json"


def outputs_present(folder: Path) -> bool:
    """Whether a folder holds what the peak allocation reads from a meter-cleaning run."""
    return all((folder / name).exists() for name in (CLEAN_PAST, RULER, COLUMNS))

"""The figures of the year's results page, read from the runs' own result files.

`data/` holds those result files cut down to what the page shows; each file says what it holds in its "what":
  with_and_without.json   each run with the community agent and without it, by weather version and tier
  two_versions.json       the two weather versions side by side, by tier, with the community agent
  summary.json            the homes, the chosen evenings in each season, the runs that failed, tier 1 by season
  pay.json                what buyers pay and members are paid, an evening, by weather version and tier
  monthly_evenings.json   one evening a month over NANDA Town with real signed messages, by weather version
  baseline.json           the candidate baselines, judged on evenings they were not fitted on
A weather version is `engie_weather` (ENGIE's own weather) or `real_weather` (ENGIE's seasons with the real
day-to-day movement of 2025). Nothing here formats a number; `words` and `tables` do that.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"
VERSIONS = ("engie_weather", "real_weather")
ENGIE, REAL = VERSIONS
TIERS = (1, 2, 3)
MODES = ("with", "without")
SEASONS = ("winter", "spring", "summer", "autumn")
Figures = dict[str, Any]


@lru_cache(maxsize=None)
def load(name: str) -> Figures:
    """One data file."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def one(counts: set[int], what: str) -> int:
    """The one value a set of counts must agree on."""
    if len(counts) != 1:
        raise ValueError(f"{what} differ: {sorted(counts)}")
    return counts.pop()


def run(version: str, tier: int, mode: str) -> Figures:
    """One run over the chosen evenings: a weather version and a tier, with the community agent or without it."""
    return load("with_and_without.json")[version][f"tier{tier}"][mode]


def runs() -> list[Figures]:
    """Every run: both weather versions, three tiers, with the community agent and without it."""
    return [run(v, t, m) for v in VERSIONS for t in TIERS for m in MODES]


def evenings() -> int:
    """The chosen evenings each run counts; every run counts the same ones."""
    return one({r["evenings"] for r in runs()}, "the runs' numbers of evenings")


def evening_runs() -> int:
    """Evening runs counted over every run."""
    return sum(r["evenings"] for r in runs())


def failed_runs() -> int:
    """Runs that failed, over both weather versions."""
    summary = load("summary.json")
    return sum(len(summary[v]["failed_runs"]) for v in VERSIONS)


def per_season() -> int:
    """Chosen evenings in each season; every season has the same number."""
    return one(set(load("summary.json")["evenings_by_season"].values()), "the seasons' numbers of evenings")


def homes() -> int:
    """The homes of the community."""
    return load("summary.json")["homes"]


def seasons(by_season: dict[str, Any]) -> list[str]:
    """The seasons a table has figures for, in the order of the year."""
    return [s for s in SEASONS if s in by_season]


def tier1_seasons() -> list[str]:
    """The seasons of tier 1's figures, in the order of the year."""
    return seasons(load("summary.json")[ENGIE]["tier1_by_season"])


def tier1_season(version: str, season: str) -> Figures:
    """Tier 1 in one season, with the community agent."""
    return load("summary.json")[version]["tier1_by_season"][season]


def both_versions(version: str, tier: int) -> Figures:
    """One tier on one weather version, for the two versions side by side."""
    return load("two_versions.json")[version][f"tier{tier}"]


def pay(version: str, tier: int) -> Figures:
    """What buyers pay and members are paid, an evening, on one weather version and tier."""
    return load("pay.json")[version][f"tier{tier}"]


def baseline(version: str) -> Figures:
    """The candidate baselines on one weather version."""
    return load("baseline.json")[version]


def baseline_seasons() -> list[str]:
    """The seasons of the baselines' mean errors, in the order of the year."""
    return seasons(baseline(ENGIE)["by_season_mean_error_pct"])


def monthly(version: str) -> list[Figures]:
    """One evening a month on one weather version, in date order."""
    return sorted(load("monthly_evenings.json")[version], key=lambda e: e["evening"])


def monthly_count() -> int:
    """How many monthly evenings each weather version has (the same for both)."""
    return one({len(monthly(v)) for v in VERSIONS}, "the weather versions' numbers of monthly evenings")


def monthly_totals(version: str) -> Figures:
    """The monthly evenings of one weather version taken together: kW averaged over the evenings, counts summed."""
    rows = monthly(version)

    def total(key: str) -> float:
        return sum(e[key] for e in rows)

    return {
        "promised_kw": total("promised_kw") / len(rows),
        "delivered_by_the_truth_kw": total("delivered_by_the_truth_kw") / len(rows),
        "delivered_by_the_meter_kw": total("delivered_by_the_meter_kw") / len(rows),
        "evenings_kept_by_the_truth": sum(e["delivered_by_the_truth_kw"] >= e["promised_kw"] for e in rows),
        "half_hours_short_by_the_truth": total("half_hours_short_by_the_truth"),
        "half_hours_short_by_the_meter": total("half_hours_short_by_the_meter"),
        "half_hours": total("half_hours"),
        "lowest_cover_share": min(e["cover_share"] for e in rows),
        "messages_accepted": total("messages_accepted"),
        "bad_signatures": total("bad_signatures"),
        "refused": total("refused"),
        "evenings_settled": sum(e["ended"] == "settled" for e in rows),
    }

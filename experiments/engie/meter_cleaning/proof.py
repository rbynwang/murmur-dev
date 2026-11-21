"""The proof of the cleaner on true data, and what it finds in the 2025 readings.

2025 has no truth: ENGIE keeps it. ENGIE's 2023 release holds the true state of the same 66 transformers, so the true 2023 loading is given the
faults the 2025 readings show (noise, single-hour jumps, missing readings), cleaned by the same code and compared with the truth it came from.
The number of shared patterns kept is the one that comes closest to the truth at loaded hours (true loading 70% or more).
"""
from __future__ import annotations

import numpy as np

from ..data import counts_by_hour
from ..grid import Readings, strained, top
from .cleaner import clean, past_only, patterns

SEED = 2025
JUMP = 12                           # points: a reading this far above the same transformer's readings an hour before and after is a jump
JUMP_SCALE = 1.6                    # the share of jumps added to the truth, against the share counted
PATTERNS_TRIED = (1, 2, 3, 4, 5, 6, 8)
NOISE_TRIED = (1.5, 2.0, 2.6)
NOISE = 2.6                         # points of noise in a 2025 reading
TRIALS = 3


def single_hour_jumps(B: np.ndarray) -> int:
    """How many readings (hours x transformers) stand JUMP points or more above the same transformer's readings an hour before and an hour
    after; a reading next to a missing one is not counted."""
    mid = B[1:-1]
    return int(((mid - B[:-2] >= JUMP) & (mid - B[2:] >= JUMP)).sum())


def fault_shares(B0: np.ndarray) -> tuple[float, float]:
    """The share of readings that jump and the share missing, from the 2025 readings."""
    return single_hour_jumps(B0) / np.isfinite(B0).sum() * JUMP_SCALE, float(np.isnan(B0).mean())


def faulty(truth: np.ndarray, rng: np.random.Generator, noise: float, jump_share: float, miss_share: float) -> tuple[np.ndarray, np.ndarray]:
    """The truth with noise, jumps of JUMP to 40 points and missing readings added; also where the jumps are."""
    noisy = truth + rng.normal(0, noise, truth.shape)
    jump = rng.random(truth.shape) < jump_share
    noisy = noisy + jump * rng.uniform(JUMP, 40, truth.shape)
    noisy[rng.random(truth.shape) < miss_share] = np.nan
    return noisy, jump


def _mean(rows: list[dict]) -> dict:
    return {m: round(float(np.mean([r[m] for r in rows])), 2) for m in rows[0]}


def by_patterns(truth: np.ndarray, B0: np.ndarray, i35: int, i38: int, rng: np.random.Generator) -> dict:
    """The cleaner on the faulty truth for each number of patterns kept, averaged over trials."""
    jump_share, miss_share = fault_shares(B0)
    rows: dict[int, list] = {}
    for _ in range(TRIALS):
        noisy, jump = faulty(truth, rng, NOISE, jump_share, miss_share)
        for k in PATTERNS_TRIED:
            Rb, bad, _ = clean(noisy, k)
            e = Rb - truth
            hot = truth >= 70
            t80, c80, n80 = strained(truth), strained(Rb), strained(noisy)
            rows.setdefault(k, []).append({
                "error_all": float(np.sqrt(np.mean(e ** 2))), "error_when_true_is_70_or_more": float(np.sqrt(np.mean(e[hot] ** 2))),
                "error_T35": float(np.sqrt(np.mean(e[:, i35] ** 2))), "error_T38": float(np.sqrt(np.mean(e[:, i38] ** 2))),
                "bias_when_true_is_70_or_more": float(np.mean(e[hot])), "strained_hours_true": int(t80.sum()), "as_read": int(n80.sum()),
                "after_cleaning": int(c80.sum()), "both": int((t80 & c80).sum()), "jumps_caught_share": float((bad & jump).sum() / max(jump.sum(), 1))})
    return {k: _mean(v) for k, v in rows.items()}


def best_patterns(avg: dict) -> int:
    return int(min(avg, key=lambda k: avg[k]["error_when_true_is_70_or_more"]))


def by_noise(truth: np.ndarray, B0: np.ndarray, k: int, rng: np.random.Generator) -> dict:
    """Which noise level, added to the truth, makes the cleaner find the noise it finds in 2025."""
    jump_share, miss_share = fault_shares(B0)
    out = {}
    for noise in NOISE_TRIED:
        rows = []
        for _ in range(TRIALS):
            noisy, _ = faulty(truth, rng, noise, jump_share, miss_share)
            Rb, _, sd = clean(noisy, k)
            e = Rb - truth
            t80, c80, n80 = strained(truth), strained(Rb), strained(noisy)
            rows.append({"noise_the_cleaner_finds": float(np.median(sd)), "error_when_true_is_70_or_more": float(np.sqrt(np.mean(e[truth >= 70] ** 2))),
                         "strained_hours_true": int(t80.sum()), "as_read": int(n80.sum()), "after_cleaning": int(c80.sum()), "both": int((t80 & c80).sum()),
                         "highest_true": float(truth.max()), "highest_after_cleaning": float(Rb.max())})
        out[noise] = _mean(rows)
    return out


def readings_2025(R: Readings, clean_loading: np.ndarray, bad: np.ndarray, sd: np.ndarray) -> dict:
    """What the whole-year cleaner finds in the 2025 readings."""
    B0 = R.loading
    r80, c80 = strained(B0), strained(clean_loading)
    return {"noise_found_points_per_sensor": {"median": round(float(np.median(sd)), 2), "lowest": round(float(sd.min()), 2), "highest": round(float(sd.max()), 2)},
            "glitches_set_aside": int(bad.sum()), "missing_rebuilt": int(np.isnan(B0).sum()),
            "hours_at_80_or_more": {"as_read": int(r80.sum()), "after_cleaning": int(c80.sum()), "in_both": int((r80 & c80).sum())},
            "hours_at_100_or_more": {"as_read": int((top(B0) >= 100).sum()), "after_cleaning": int((top(clean_loading) >= 100).sum())},
            "highest_loading": {"as_read": round(float(np.nanmax(B0)), 1), "after_cleaning": round(float(clean_loading.max()), 1)},
            "by_hour_after_cleaning": counts_by_hour(R.hour[c80]), "by_hour_as_read": counts_by_hour(R.hour[r80]),
            "which_transformers_after_cleaning": {int(R.trafo[c]): int(n) for c, n in enumerate((clean_loading >= 80).sum(axis=0)) if n > 0}}


def _score(R_: np.ndarray, truth: np.ndarray, sl: slice = slice(None)) -> dict:
    e = (R_ - truth)[sl]
    h = (truth >= 70)[sl]
    t80, c80 = strained(truth[sl]), strained(R_[sl])
    return {"error_all": float(np.sqrt(np.mean(e ** 2))), "error_when_true_is_70_or_more": float(np.sqrt(np.mean(e[h] ** 2))),
            "bias_when_true_is_70_or_more": float(np.mean(e[h])), "strained_true": int(t80.sum()), "strained_found": int(c80.sum()), "of_them_true": int((t80 & c80).sum())}


def past_only_proof(truth: np.ndarray, B0: np.ndarray, k: int, per_day: int) -> dict:
    """The past-only cleaner against the whole-year cleaner on the faulty truth (per_day rows a day); its first days use the 2025 readings'
    patterns as the other year."""
    rng = np.random.default_rng(SEED)
    jump_share, miss_share = fault_shares(B0)
    other, jan, rows = patterns(B0, k), slice(0, 31 * per_day), []
    for _ in range(TRIALS):
        noisy, jump = faulty(truth, rng, NOISE, jump_share, miss_share)
        whole, _, _ = clean(noisy, k)
        past, badp = past_only(noisy, per_day, k, older=other)
        rows.append({"as_read": {"strained_true": int(strained(truth).sum()), "strained_found": int(strained(noisy).sum())},
                     "whole_year": _score(whole, truth), "past_only": _score(past, truth), "whole_year_january": _score(whole, truth, jan),
                     "past_only_january": _score(past, truth, jan), "jumps_caught_share_past_only": float((badp & jump).sum() / max(1, jump.sum()))})
    avg = lambda key: _mean([r[key] for r in rows])
    return {"steps_a_day": per_day, "as_read": avg("as_read"), "whole_year_cleaner": avg("whole_year"), "past_only_cleaner": avg("past_only"),
            "january_alone": {"whole_year_cleaner": avg("whole_year_january"), "past_only_cleaner": avg("past_only_january")},
            "jumps_caught_share_past_only": round(float(np.mean([r["jumps_caught_share_past_only"] for r in rows])), 3)}


def past_only_2025(R: Readings, P25: np.ndarray, bad25: np.ndarray, W25: np.ndarray) -> dict:
    """The past-only cleaner's 2025 readings against the whole-year cleaner's."""
    B0 = R.loading
    r80, w80, p80 = strained(B0), strained(W25), strained(P25)
    return {"hours": int(len(B0)), "hours_at_80_or_more": {"as_read": int(r80.sum()), "whole_year_cleaner": int(w80.sum()), "past_only_cleaner": int(p80.sum()),
                                                           "in_both_cleaners": int((w80 & p80).sum())},
            "hours_at_100_or_more": {"whole_year_cleaner": int((top(W25) >= 100).sum()), "past_only_cleaner": int((top(P25) >= 100).sum())},
            "the_two_cleaners_differ_by_points": {"mean_abs": round(float(np.abs(P25 - W25).mean()), 2),
                                                  "mean_abs_where_loading_is_70_or_more": round(float(np.abs(P25 - W25)[W25 >= 70].mean()), 2),
                                                  "largest": round(float(np.abs(P25 - W25).max()), 1)},
            "glitches_set_aside": int(bad25.sum()), "extra_strained_hours_in_the_first_28_days": int((p80 & ~w80)[:28 * 24].sum()), "fewer": int((w80 & ~p80).sum()),
            "by_hour_past_only": counts_by_hour(R.hour[p80]), "which_transformers_past_only": {int(R.trafo[c]): int(n) for c, n in enumerate((P25 >= 80).sum(axis=0)) if n > 0}}

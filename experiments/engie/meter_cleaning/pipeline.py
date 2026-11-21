"""The meter-cleaning pipeline: clean the 2025 grid readings, prove the cleaning on the 2023 true state, read the ruler."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .. import data, grid
from ..fleet import ratings
from . import CLEAN_PAST, COLUMNS, RULER, proof, ruler
from .cleaner import EVERY, FIRST, WARM, clean, past_only, patterns


def run(root: Path, out: Path, say=print) -> dict:
    """The whole pipeline; returns the three reports it writes."""
    f25, f23 = data.release_2025(root), data.release_2023(root)
    t0 = time.time()
    R = grid.readings_2025(f25)
    g23 = grid.grid_2023(f23)
    truth = grid.truth_2023(g23, R.trafo)
    per_day = int(round(86400 / (g23.index[1] - g23.index[0]).total_seconds()))      # rows a day in the 2023 state
    B0 = R.loading
    jumps = proof.single_hour_jumps(B0)
    jump_share, miss_share = proof.fault_shares(B0)
    say(f"readings: {B0.shape[0]} hours x {B0.shape[1]} transformers; strained as read {int(grid.strained(B0).sum())}; single-hour jumps {jumps}")

    rng = np.random.default_rng(proof.SEED)
    avg = proof.by_patterns(truth, B0, R.column(35), R.column(38), rng)
    k = proof.best_patterns(avg)
    report = {"what": "cleaning the 2025 grid readings, proven on the 2023 true state with the same faults added",
              "single_hour_jumps_in_2025": jumps,
              "faults_added_to_2023": {"noise_points": proof.NOISE, "share_of_readings_that_jump": round(jump_share, 5), "share_missing": round(miss_share, 4)},
              "proof_on_2023_by_patterns_kept": avg, "patterns_kept": k, "proof_by_noise_added": proof.by_noise(truth, B0, k, rng)}
    W25, bad, sd = clean(B0, k)
    report["readings_2025"] = proof.readings_2025(R, W25, bad, sd)
    report["hours_at_80_or_more_in_2025_by_patterns_kept"] = {j: int(grid.strained(clean(B0, j)[0]).sum()) for j in proof.PATTERNS_TRIED}
    best = avg[k]
    report["how_far_to_trust_the_2025_count"] = (f"On 2023, where the truth is known, {best['strained_hours_true']:.0f} hours are truly at 80% or more; the faulty readings "
                                                 f"show {best['as_read']:.0f}, and after cleaning {best['after_cleaning']:.0f}, of which {best['both']:.0f} are true ones.")
    np.save(out / "loading_2025_clean.npy", W25)
    data.write_json(out / "cleaning.json", report)
    say(f"whole-year cleaner: {k} patterns kept; strained hours {report['readings_2025']['hours_at_80_or_more']}; with other numbers of patterns "
        f"{report['hours_at_80_or_more_in_2025_by_patterns_kept']}  ({time.time() - t0:.0f} s)")

    past = {"what": "the reading cleaner using the past only, against the whole-year cleaner, on the 2023 true state with the same faults added", "patterns_kept": k,
            "patterns_learned_again": f"from the other year for the first {FIRST} days, then from its own past: daily to day {WARM}, then every {EVERY} days",
            "proof_on_2023": proof.past_only_proof(truth, B0, k, per_day)}
    P25, bad25 = past_only(B0, 24, k, older=patterns(truth, k))
    past["readings_2025"] = proof.past_only_2025(R, P25, bad25, W25)
    np.save(out / CLEAN_PAST, P25)
    data.write_json(out / "cleaning_past_only.json", past)
    say(f"past-only cleaner: strained hours {past['readings_2025']['hours_at_80_or_more']}  ({time.time() - t0:.0f} s)")

    rul = ruler.read(f23, f25, ratings(f25), R.trafo)
    np.save(out / RULER, rul.by_kind)
    data.write_json(out / "ruler.json", rul.report)
    data.write_json(out / COLUMNS, {"transformers": [int(c) for c in R.trafo], "first_hour_utc": str(R.hours[0]), "last_hour_utc": str(R.hours[-1]), "hours": len(R.hours)})
    say(f"ruler: T35 {rul.report['T35']['all_batteries_in_proportion_per_100_mw']}, T38 {rul.report['T38']['all_batteries_in_proportion_per_100_mw']} points per 100 MW  "
        f"({time.time() - t0:.0f} s)")
    return {"cleaning": report, "cleaning_past_only": past, "ruler": rul.report}

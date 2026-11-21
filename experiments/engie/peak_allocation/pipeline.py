"""The peak-allocation pipeline: the year replayed with the batteries held for the evening peak, in three cases of who is asked."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .. import data, grid
from ..fleet import KINDS, from_reports
from ..meter_cleaning import CLEAN_PAST, COLUMNS, RULER, outputs_present
from ..meter_cleaning.pipeline import run as run_cleaning
from .plan import asked
from .replay import replay
from .score import score

CASES = (("all_asked", "every battery of the 80"), ("plants_not_asked", "the communities and data centers; the solar-and-battery plants run as recorded"),
         ("communities_only", "the 20 communities; plants and data centers run as recorded"))


def run(root: Path, out: Path, cleaning: Path, say=print) -> dict:
    f25 = data.release_2025(root)
    if not outputs_present(cleaning):
        say(f"no meter-cleaning results in {cleaning.name}/: running the meter cleaning first")
        cleaning.mkdir(parents=True, exist_ok=True)
        run_cleaning(root, cleaning, say)
    t0 = time.time()
    R = grid.readings_2025(f25)
    if json.loads((cleaning / COLUMNS).read_text())["transformers"] != [int(c) for c in R.trafo]:
        raise ValueError("the meter-cleaning results hold other transformers than these readings")
    base, ruler = np.load(cleaning / CLEAN_PAST), np.load(cleaning / RULER)
    fleet = from_reports(f25)
    year = int(data.local(fleet.steps[:1]).year[0])
    loading = grid.by_day_hour(R, base, fleet.days, year)
    PM, kind = fleet.rat.power_kw, fleet.rat.kind
    res = {"what": "the batteries held for the evening peak: at 14:00 a plan from the grid's expected loading alone; ENGIE's 2025 records",
           "readings": "cleaned with the past only", "the_rest_goes_to": "the evening's highest-loaded hours",
           "as_recorded_hours_at_80_or_more": int(grid.strained(base).sum()), "batteries_mw": {k: data.mw(PM[kind == k].sum() / 1000) for k in KINDS}}
    say(f"records read: {len(fleet.rat.ids)} batteries, {len(fleet.steps)} steps; strained hours as recorded {res['as_recorded_hours_at_80_or_more']} ({time.time() - t0:.0f} s)")
    takes = {"all_asked": np.ones(len(kind), dtype=bool), "plants_not_asked": kind != "pv_bess", "communities_only": kind == "community"}
    for key, who in CASES:
        take = takes[key]
        r = replay(fleet, asked(take, fleet, ruler, loading))
        sc = score(r, fleet, R, base, ruler)
        moved = (r.after - fleet.p)[:, ~take].sum(axis=1) / 1000 if (~take).any() else np.zeros(len(fleet.steps))
        res[key] = {"who_is_asked": who, "batteries_asked": int(take.sum()), "their_power_mw": data.mw(PM[take].sum() / 1000), **sc,
                    "give_at_19_and_20_mw": [sc["batteries_give_by_hour_mw"][19], sc["batteries_give_by_hour_mw"][20]],
                    "evenings_with_a_request": int((r.asked.sum(axis=1) > 0.5).sum()), "largest_request_mw": round(float(r.asked.max()), 1),
                    "the_unasked_moved_from_their_record_mw_mean": round(float(np.abs(moved).mean()), 3)}
        say(f"{key}: hours at 80% or more {sc['hours_at_80_or_more']} (by hour {sc['by_hour']}), limits broken {sc['limits_broken']} ({time.time() - t0:.0f} s)")
    data.write_json(out / "peak_allocation.json", res)
    hours = {key: res[key]["hours_at_80_or_more"] for key, _ in CASES}
    say(f"hours with a transformer at 80% or more: {res['as_recorded_hours_at_80_or_more']} as recorded; {hours['all_asked']} with every battery held for the "
        f"peak, {hours['plants_not_asked']} without the plants' batteries, {hours['communities_only']} with the communities' batteries alone")
    return res

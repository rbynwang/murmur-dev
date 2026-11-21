"""How a replayed year scores on the grid: the hours a transformer is at 80% or more, and whether any limit broke.

The grid's loading after the replay is the cleaned reading less what the batteries' change moves each transformer, by the ruler: the change in
what each kind of participant sends out, hour by hour, times that kind's relief per MW.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import counts_by_hour, mw
from ..fleet import DT, Fleet
from ..grid import Readings, top
from .replay import Run


def loading_after(run: Run, fleet: Fleet, R: Readings, base: np.ndarray, ruler: np.ndarray) -> np.ndarray:
    """Every transformer's loading, hour by hour, once the batteries run as replayed."""
    delta = run.after - fleet.p
    kj = fleet.rat.kj
    dK = np.stack([pd.Series(delta[:, kj == q].sum(axis=1) / 1000, index=fleet.steps).resample("1h").mean().reindex(R.hours).fillna(0.0).to_numpy()
                   for q in range(ruler.shape[1])], axis=1)
    return base - dK @ ruler.T


def score(run: Run, fleet: Fleet, R: Readings, base: np.ndarray, ruler: np.ndarray) -> dict:
    A = loading_after(run, fleet, R, base, ruler)
    highest = top(A)
    a80, a100, b80 = highest >= 80, highest >= 100, top(base) >= 80
    PM, f = fleet.rat.power_kw, fleet.f
    given = np.where(run.new >= 0, -run.new, -run.new * f) / DT            # kW at the connection, + given
    device = np.where(run.new >= 0, run.new, run.new * f) / DT             # kW at the battery
    return {"hours_at_80_or_more": int(a80.sum()), "of_which_new": int((a80 & ~b80).sum()), "evenings_with_one": len(set(R.day[a80].tolist())),
            "hours_at_100_or_more": int(a100.sum()), "highest_loading": round(float(np.nanmax(A)), 1), "by_hour": counts_by_hour(R.hour[a80]),
            "limits_broken": {"charge_outside_10_to_90": int(((run.level < fleet.emin - 1e-6) | (run.level > fleet.emax + 1e-6)).sum()),
                              "device_power_over_rating": int((np.abs(device) > PM + 1e-6).sum()),
                              "sent_out_over_the_connection_limit": int((run.after > np.maximum(fleet.rat.limit_kw, fleet.p) + 1e-6).sum())},
            "suns_surplus_lost_mwh": round(run.lost_kwh / 1000, 1),
            "batteries_give_by_hour_mw": {h: mw(np.maximum(given[fleet.hour == h], 0).sum(axis=1).mean() / 1000) for h in range(14, 24)}}

"""The ruler: how far each transformer's loading falls when the batteries give 1 MW, read off ENGIE's true 2023 grid state.

The 2023 release holds every transformer's true loading every hour, each participant's true battery power and the grid's own load; in it the load
the plants serve is the grid's own load plus the 80's net draw. So for each transformer its true loading is explained by the grid's own load, by
what the 80 draw with their batteries taken out, and by what the batteries give, separately for the three kinds of participant, fitted on the hours
in the top 30% of load, where strain happens. Checked three ways: on weeks the fit never saw, on the top 10% of load alone, on hour-to-hour changes.
A single slope per transformer against the whole system's load, the same for every participant, is reported beside it for comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..fleet import KINDS, Ratings
from .. import grid

REPORTED = (35, 38, 36, 37, 39, 40)   # the transformers the report lists: the two strained ones first, then their neighbours


@dataclass(frozen=True)
class Ruler:
    by_kind: np.ndarray               # transformers x kinds: points of loading relieved per MW given
    report: dict


def single_slope(g23: pd.DataFrame, s23: pd.DataFrame, trafo: np.ndarray) -> np.ndarray:
    """One slope per transformer, points of loading per 100 MW of system load, on the upper half of the year's load."""
    net = s23.net_load_dispatched_mw.reindex(g23.index).to_numpy()
    hi = net >= np.median(net)
    return np.array([np.polyfit(net[hi], g23[f"loading_pct_t{c}"].to_numpy()[hi], 1)[0] * 100 for c in trafo])


def fit(A: np.ndarray, y: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least squares of y on A over the chosen rows: the coefficients and their standard errors."""
    b = np.linalg.lstsq(A[rows], y[rows], rcond=None)[0]
    r = y[rows] - A[rows] @ b
    se = np.sqrt(np.outer(np.diag(np.linalg.inv(A[rows].T @ A[rows])), r.var(axis=0)))
    return b, se


def design(background: np.ndarray, draw: np.ndarray, given: np.ndarray) -> np.ndarray:
    """The explaining columns: a constant, the grid's own load, the 80's draw without batteries, and what each kind of battery gives."""
    return np.column_stack([np.ones(len(background)), background, draw, given])


def response(X: np.ndarray, Y: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each transformer's relief by kind (transformers x kinds, points per MW given), with the fitted coefficients and their standard errors."""
    B, SE = fit(X, Y, rows)
    return -B[3:].T, B, SE


def _hourly(ts: pd.DataFrame, col: str, hours: pd.DatetimeIndex, ids: list[str]) -> np.ndarray:
    return ts.pivot(index="timestamp", columns="entity_id", values=col).resample("1h").mean().reindex(hours)[ids].to_numpy() / 1000


def read(folder_2023: Path, folder_2025: Path, rat: Ratings, trafo: np.ndarray) -> Ruler:
    g23, s23 = grid.grid_2023(folder_2023), grid.system_load_2023(folder_2023)
    hrs = g23.index
    x = s23.resample("1h").mean().reindex(hrs)
    ts = pd.read_parquet(folder_2023 / "agents_timeseries_2023_15min.parquet", columns=["p_net_kw", "bess_power_true_kw"]).reset_index()
    P, BT = _hourly(ts, "p_net_kw", hrs, rat.ids), _hourly(ts, "bess_power_true_kw", hrs, rat.ids)     # MW; P + sent out, BT + given
    md = pd.read_parquet(folder_2023 / "agents_metadata.parquet")
    md = md.set_index("entity_id") if "entity_id" in md.columns else md
    nodes = pd.read_parquet(folder_2025 / "nodes.parquet").set_index("entity_id")
    same = bool((md.bus.reindex(rat.ids).to_numpy() == nodes.bus.reindex(rat.ids).to_numpy()).all())
    net = x.net_load_dispatched_mw.to_numpy()
    bg = net + P.sum(axis=1)                                   # the grid's own load: what the plants serve less the 80's net draw
    nobat = -(P - BT).sum(axis=1)                              # the 80's draw with their batteries taken out
    GK = np.stack([BT[:, rat.kind == k].sum(axis=1) for k in KINDS], axis=1)
    Y = grid.truth_2023(g23, trafo)
    X = design(bg, nobat, GK)
    top30, top10 = net >= np.quantile(net, .7), net >= np.quantile(net, .9)
    even_weeks = (np.asarray(hrs.dayofyear) // 7) % 2 == 0
    RK, B, SE = response(X, Y, top30)
    B10, _ = fit(X, Y, top10)
    dX = np.diff(X, axis=0)
    dX[:, 0] = 1
    Bd, _ = fit(dX, np.diff(Y, axis=0), top30[1:])
    Btr, _ = fit(X, Y, top30 & even_weeks)
    te = top30 & ~even_weeks
    res = Y[te] - X[te] @ Btr
    share = np.array([rat.power_kw[rat.kind == k].sum() for k in KINDS])
    share = share / share.sum()
    fleet = RK @ share * 100                                   # points per 100 MW when every battery gives in proportion to its power
    SL = single_slope(g23, s23, trafo)
    out = {"what": "each transformer's true response to the batteries, from ENGIE's 2023 true grid state", "same_80_participants_at_the_same_buses_in_both_releases": same,
           "hours_used": int(top30.sum()), "identity": "the load the plants serve = the grid's own load + the 80's net draw (exact in the 2023 release)",
           "share_of_battery_power_by_kind_2025": {k: round(float(w), 3) for k, w in zip(KINDS, share)}}
    col = {int(c): i for i, c in enumerate(trafo)}
    for c in REPORTED:
        i = col[c]
        out[f"T{c}"] = {"single_slope_per_100_mw": round(float(SL[i]), 2), "all_batteries_in_proportion_per_100_mw": round(float(fleet[i]), 2),
                        "the_grids_own_load_per_100_mw": round(float(B[1, i] * 100), 2),
                        "relief_per_100_mw_given_by": {k: f"{RK[i, j] * 100:+.2f} (+-{SE[3 + j, i] * 100:.2f})" for j, k in enumerate(KINDS)},
                        "the_same_on_the_top_10_percent_of_load": {k: round(float(-B10[3 + j, i] * 100), 2) for j, k in enumerate(KINDS)},
                        "the_same_from_hour_to_hour_changes": {k: round(float(-Bd[3 + j, i] * 100), 2) for j, k in enumerate(KINDS)},
                        "on_weeks_the_fit_never_saw": {"error_points": round(float(res[:, i].std()), 2), "share_explained": round(float(1 - res[:, i].var() / Y[te][:, i].var()), 3)}}
    i35, i38 = col[35], col[38]
    out["what_it_means"] = {"T35_share_of_the_single_slope": round(float(fleet[i35] / SL[i35]), 2), "T38_share_of_the_single_slope": round(float(fleet[i38] / SL[i38]), 2),
                            "most_relief_all_batteries_at_full_power_points": {"T35": round(float(fleet[i35] * rat.power_kw.sum() / 1e5), 1),
                                                                               "T38": round(float(fleet[i38] * rat.power_kw.sum() / 1e5), 1)}}
    return Ruler(RK, out)


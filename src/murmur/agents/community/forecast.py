"""Tomorrow's community demand by hour, from the trained community model, as the community agent reads it when a sale opens.

The model's inputs are fed exactly as in training: the members' own load on the days before, the calendar and the weather forecast.
With fewer than 21 such days, the dataset's community_load model stands in.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import numpy as np

from murmur.protocol import envelope as beckn
from murmur import config
from murmur.node.forecast import HomeForecaster
from murmur.replay import _load

FIT_DAYS = 42                  # the days each hour's fit reads
FIT_MIN = 21                   # with fewer, community_load stands in
SPREAD = 1.25                  # the fit's own days understate a new day's miss: chosen on evenings up to 29 Jun, the date-limited copies' cut-off
REACH = 1.25                   # a forecast stays within this factor of what its days metered. A few warm days in spring can't set a slope, and without the bound a fit can run thousands of times past the truth
COOL_C, HEAT_C = 20.0, 10.0    # above this the homes cool, below this they heat
ZERO_FLOOR = 0.01              # a community's load is never zero: a reading of 0 kW, or under this share of the series' own median, counts as missing


class _Community:
    """A replay-shaped view of the whole community: base_kw and pv_kw summed over the homes, weather from the first."""

    def __init__(self, profiles: list[str]):
        first_rows, index, _ = _load(profiles[0])
        rows = [dict(r) for r in first_rows]
        for r in rows:
            r["base_kw"], r["pv_kw"] = 0.0, 0.0
        for p in profiles:
            prow, pidx, _ = _load(p)
            for r in rows:
                j = pidx.get(r["ts_local"])
                gone = [c for c in ("base_kw", "pv_kw") if j is None or c in prow[j].get("_missing", ())]
                if gone:                                # one member's reading blank or absent: the community's sum for that step isn't known, and it is never the sum of the rest
                    r["_missing"] = tuple(sorted({*r.get("_missing", ()), *gone}))
                if j is not None:
                    r["base_kw"] += prow[j]["base_kw"]
                    r["pv_kw"] += prow[j]["pv_kw"]
        self.rows, self.index = rows, index
        self.sessions: list = []

    def row(self, i: int) -> dict[str, Any]:
        return self.rows[max(0, min(i, len(self.rows) - 1))]

    def ts(self, i: int) -> str:
        return self.row(i)["ts_local"]

    def idx_of(self, ts: str) -> int | None:
        return self.index.get(ts)


@lru_cache(maxsize=4)
def _setup(members: tuple[str, ...] = ()):
    """members: the homes on the desk, by name. Empty means every home in the dataset. The model works on a community's load relative to its own
    last 14 days, so it takes any group."""
    meta = config.dataset_meta()
    fleet = json.loads(config.data_path("fleet_v2.json").read_text())["homes"]
    if members:
        fleet = [h for h in fleet if h["name"] in set(members)]
    comm = _Community([h["profile"] for h in fleet])
    if "fc_temp_c" not in comm.rows[0]:
        raise ValueError(f"dataset {meta['name']} has no issued weather forecasts: no community forecast")
    fc = HomeForecaster("community", comm, {"lat": meta.get("community", {}).get("lat", 42.26),
                                           "lon": meta.get("community", {}).get("lon", -71.80), "pv_kw_dc": 0.0},
                        correct_pv=False, min_share=ZERO_FLOOR)
    from murmur.node.forecast import _model
    fc.load_m = _model(str(config.model_path(meta.get("models", "forecast_2025_26")) / "community_load.json.gz"))
    return comm, fc, len(fleet)


def _kept_out() -> set[str]:
    """The benchmark's kept days, as fleet_errors.json lists them. A table of past errors holds none of them, and neither does a fit."""
    meta = config.dataset_meta()
    return set(json.loads((config.model_path(meta.get("models_2026", "forecast_2026")) / "fleet_errors.json").read_text())["kept_out"])


def fit_days(comm: _Community, issue: str, kept: set[str]) -> list[str]:
    """The last FIT_DAYS whole days that were over at the issue time, newest first, none of them kept."""
    out, d, first = [], date.fromisoformat(issue[:10]), date.fromisoformat(comm.ts(0)[:10])
    while len(out) < FIT_DAYS and d > first:
        d -= timedelta(days=1)
        if d.isoformat() not in kept and all(comm.idx_of(f"{d} {h:02d}:00") is not None for h in range(24)):
            out.append(d.isoformat())
    return out


def _cell(comm: _Community, ts: str, col: str) -> float:
    """One reading by its time stamp. No value where the row is absent from the file or the cell was blank: never 0."""
    i = comm.idx_of(ts)
    if i is None:
        return float("nan")
    r = comm.row(i)
    if col not in r or col in r.get("_missing", ()) or (col == "base_kw" and float(r[col]) <= 0):      # and a community's load of 0 kW is no reading either
        return float("nan")
    return float(r[col])


def _inputs(comm: _Community, holidays: set[date], day: str, hour: int) -> list[float]:
    """An hour's inputs, all known the day before: cooling and heating degrees in the issued forecast, and whether it's a day off."""
    t = _cell(comm, f"{day} {hour:02d}:00", "fc_temp_c")
    d = date.fromisoformat(day)
    return [1.0, max(t - COOL_C, 0.0), max(HEAT_C - t, 0.0), float(d.weekday() >= 5 or d in holidays)] if np.isfinite(t) else [float("nan")] * 4


def _metered_kw(comm: _Community, day: str, hour: int) -> float:
    return sum(_cell(comm, f"{day} {hour:02d}:{15 * k:02d}", "base_kw") for k in range(4)) / 4


def own_fit(comm: _Community, holidays: set[date], day: str, days: list[str]) -> list[dict[str, Any] | None]:
    """Each hour of `day` from the community's own meters: log kW on _inputs() over `days`, then the range from how far those days fell from the line, widened by SPREAD.
    A day whose reading or forecast for that hour is missing is left out of that hour's fit, and the range widens by the share left out. An hour with under FIT_MIN days
    left, or no forecast of its own, has no fit: None, and the caller's stand-in answers for it. `dropped` on each hour says how many days were left out."""
    hours: list[dict[str, Any] | None] = []
    for h in range(24):
        x = np.array([_inputs(comm, holidays, d, h) for d in days])
        m = np.array([_metered_kw(comm, d, h) for d in days])
        ok = np.isfinite(m) & np.isfinite(x).all(axis=1)
        if ok.any():                                    # under a hundredth of the hour's own median: no reading
            ok &= np.where(np.isfinite(m), m, 0.0) >= ZERO_FLOOR * float(np.median(m[ok]))
        mine = np.array(_inputs(comm, holidays, day, h))
        if ok.sum() < FIT_MIN or not np.isfinite(mine).all():
            hours.append(None)
            continue
        dropped = int(len(days) - ok.sum())
        if dropped:
            x, m = x[ok], m[ok]
        y = np.log(np.maximum(m, 1e-6))
        b = np.linalg.lstsq(x, y, rcond=None)[0]
        lo, mid, hi = np.quantile(y - x @ b, (.1, .5, .9))
        at = float(np.clip(mine @ b + mid, y.min() - np.log(REACH), y.max() + np.log(REACH)))
        base = float(config.dataset_meta().get("community_forecast_spread") or SPREAD)      # a dataset may set its own: on ENGIE's two months 1.25 holds the truth 68% of the time and 2.0 holds it 82%
        spread = base * (1 + dropped / len(days)) if dropped else base
        hours.append({"hour": h, "p10_kw": round(float(np.exp(at + spread * (lo - mid))), 1), "p50_kw": round(float(np.exp(at)), 1), "p90_kw": round(float(np.exp(at + spread * (hi - mid))), 1),
                      **({"dropped": dropped} if dropped else {})})
    return hours


def forecast(day: str, issued_at: str | None = None, members: list[str] | None = None) -> dict[str, Any]:
    """Hourly 10/50/90 % of the community's base demand (kW, all homes, or just `members`) on `day`, as forecast at `issued_at`
    (default 10:00 the day before, the call for offers). days_read says how many days its own fit read: 0 means community_load answers."""
    comm, fc, n = _setup(tuple(sorted(members or ())))
    issue = issued_at or f"{beckn.add_minutes(f'{day} 00:00', -1440)[:10]} 10:00"
    now = comm.idx_of(issue)
    ts = [f"{day} {h:02d}:00" for h in range(24)]
    if now is None or any(comm.idx_of(t) is None for t in ts):
        meta = config.dataset_meta()
        raise ValueError(f"{day} (issued {issue}) is outside the data ({meta['range'][0]} to {meta['range'][1]})")
    if issue >= ts[0]:
        raise ValueError("the forecast must be issued before the day starts")
    out = fc.forecast(now, ts)
    hours = [{"hour": int(t[11:13]), "p10_kw": round(float(out[t]["load"][0]), 1), "p50_kw": round(float(out[t]["load"][1]), 1),
              "p90_kw": round(float(out[t]["load"][2]), 1)} for t in ts if t in out]
    try:
        days = fit_days(comm, issue, _kept_out())
    except (OSError, ValueError, KeyError):
        days = []                                         # no list of kept days, so no fit
    said = dict(getattr(fc, "last", None) or {})
    how, missing = said.get("how") or "no reading to forecast from", float(said.get("missing_share") or 0.0)
    fitted = len(days) >= FIT_MIN
    if fitted:
        fit = own_fit(comm, fc.holidays, day, days)
        mine = {x["hour"]: x for x in hours}             # an hour with no fit of its own takes the model's hour, or the model's stand-in
        none = [h for h in range(24) if fit[h] is None]
        dropped = sum((x or {}).pop("dropped", 0) for x in fit)
        hours = [fit[h] or mine[h] for h in range(24) if fit[h] is not None or h in mine]
        fit_how = "the community's own fit on its last days"
        if len(none) == 24:
            fitted = False                              # nothing could be fitted: the answer is the model's, or its stand-in's
        else:
            how = fit_how + (f"; {len(none)} hours by {how}" if none else "")
            missing = round((dropped + len(none) * len(days)) / (24 * len(days)), 4)
    if not hours:                                       # an empty list would give a peak of 0.0 kW, and the community agent divides by it
        raise ValueError(f"no reading to forecast {day} from: the last {FIT_DAYS} days hold nothing usable")
    stand_in = how not in ("model", "the community's own fit on its last days")
    best = max(range(15, 19), key=lambda h0: sum(x["p50_kw"] for x in hours if h0 <= x["hour"] < h0 + 3))
    win = [x for x in hours if best <= x["hour"] < best + 3]
    return {"day": day, "issued_at": issue, "homes": n, "unit": "kW, the community's base demand (all homes, EVs excluded)",
            "hours": hours,
            "peak_window": {"start": f"{best:02d}:00", "end": f"{best + 3:02d}:00",
                            "mean_p50_kw": round(float(sum(x["p50_kw"] for x in win)) / 3, 1),
                            "why": "the 3 hours between 15:00 and 21:00 with the highest forecast demand"},
            "days_read": len(days) if fitted else 0,
            "how": how, "stand_in": stand_in, "inputs_missing_share": missing,      # which answer this is, and what share of what it reads was missing: blank, absent, or a meter that froze
            "model": (f"the community's own meters: each hour, its last {len(days)} days against the issued forecast's cooling and heating degrees and days off; "
                      f"the range from how far those days missed, widened {SPREAD:g} times" if fitted else
                      "community_load: gradient-boosted trees (10/50/90 % quantiles) trained on National Grid's R-1 "
                      "average Massachusetts home, May 2025 - Jun 2026; range widened by its rolling-test errors"),
            "information": "the community's metered demand up to the issue time and the ECMWF weather forecast as "
                           "issued about 48 h ahead; nothing from the day itself"}

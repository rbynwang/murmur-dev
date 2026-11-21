"""Kinds of day and the day-ahead temperature a forecast reads: what a home's or a building's forecast needs from the calendar."""
from __future__ import annotations

import random
from typing import Callable
from murmur.protocol import envelope as beckn
import os as _os


SLOT = beckn.SLOT_MINUTES


POST_STEPS = 32                     # the evening after the window that offers forecast (8 h)


TRAINED = ("trained",)   # the forecast setting that runs the trained models (forecast.HomeForecaster)


REBOUND_FRACTIONS = (0.25, 0.5, 0.75, 1.0)   # battery delivery levels the evening rebound is forecast for


TEMP_FC_SIGMA_C = 2.1    # day-ahead temperature forecast error (see temp_forecast)


BACKUP = _os.environ.get("MURMUR_BATTERY_MODE") == "backup"


def temp_forecast(ts: str, actual_c: float) -> float:
    """Day-ahead temperature forecast for a step = the dataset's temperature plus one error per day, drawn from a
    normal distribution with sigma 2.1 C (mean absolute error 1.7 C = 3 F; NWS verification for Wichita, summer 2000:
    next-day maximum temperature MAE 2.4 F for forecasters and 3.5 F for MOS guidance). Same error for every home
    (weather errors are regional), seeded by the date so every run is repeatable."""
    return actual_c + random.Random(f"temp-forecast-{ts[:10]}").gauss(0.0, TEMP_FC_SIGMA_C)


def day_kind(day: str, holidays) -> int:
    """A building's kind of day: 0 a weekday, 1 a Saturday, 2 a Sunday or a holiday of the dataset."""
    from datetime import date
    wd = date.fromisoformat(day).weekday()
    return 2 if wd == 6 or day in holidays else 1 if wd == 5 else 0


def last_same_kind_step(i: int, now: int, ts_of: Callable[[int], str], holidays, reach: int = 28) -> int | None:
    """The same quarter hour on the most recent day of the same kind that is already past at step `now`, looking back up to `reach` days.
    None where the record doesn't reach such a day. A building's load follows its timetable far more than the weather, so yesterday's Sunday says little about a Monday."""
    want, d = day_kind(ts_of(i)[:10], holidays), 1
    while i - 96 * d >= now:
        d += 1
    for k in range(d, d + reach):
        j = i - 96 * k
        if j < 0:
            return None
        if day_kind(ts_of(j)[:10], holidays) == want:
            return j
    return None

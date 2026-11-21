"""The year replayed with the plan: every 15 minutes each battery's new step, inside its limits, and what its site sends out.

  from 14:00   an asked battery gives what the plan says, as far as its charge allows; when the plan asks nothing of it in an hour it charges as
               recorded, as far as its store has room
  12:00-14:00  an asked battery only charges as recorded, so it reaches the evening as full as its record allows
  before noon  it runs as recorded, inside its charge limits
  not asked    a battery the aggregator does not ask runs as recorded all day
Everywhere a site never sends out more than its connection allows (or than it sent as recorded, where that is more); solar the connection cannot
take is counted as lost.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..fleet import DT, Fleet
from .plan import H0, NH, Asked, first_day, plan


@dataclass(frozen=True)
class Run:
    after: np.ndarray               # steps x batteries: the site's net power with the new battery run, kW, + sent out
    new: np.ndarray                 # steps x batteries: the store's new step, kWh, + charging
    level: np.ndarray               # steps x batteries: kWh in the store after the step
    lost_kwh: float                 # solar the connection could not take
    asked: np.ndarray               # days x plan hours: MW the request asked of all asked batteries


def replay(fleet: Fleet, A: Asked) -> Run:
    emin, emax, f = fleet.emin, fleet.emax, fleet.f
    T, N = fleet.p.shape
    x = np.clip(fleet.s[0] * fleet.rat.energy_kwh, emin, emax)
    after, new, level = np.empty((T, N)), np.empty((T, N)), np.empty((T, N))
    target = np.zeros((N, NH))
    asked = np.zeros((fleet.days, NH))
    lost = 0.0
    for t in range(T):
        dt, h = fleet.d[t], fleet.hour[t]
        if h == H0 and fleet.minute[t] == 0:
            D = int(fleet.day[t])
            if D == 0:
                target = first_day(x, A, emin, f)
            else:
                target, asked[D] = plan(A.expected[D], x, A, emin, f)
        as_recorded = np.where(dt >= 0, np.minimum(dt, np.maximum(emax - x, 0.0)), -np.minimum(-dt, np.maximum(x - emin, 0.0)))
        if h >= H0:
            want = target[:, h - H0] * DT / f
            w = np.where(want > 0, -np.minimum(want, np.maximum(x - emin, 0.0)), np.minimum(np.maximum(dt, 0.0), np.maximum(emax - x, 0.0)))
        elif h >= 12:
            w = np.minimum(np.maximum(dt, 0.0), np.maximum(emax - x, 0.0))
        else:
            w = as_recorded
        w = np.where(A.take, w, as_recorded)
        given = np.where(w >= 0, -w, -w * f) / DT
        lim = np.maximum(fleet.rat.limit_kw, fleet.p[t])
        room = np.maximum(lim - fleet.p0[t], 0.0)
        over = (w < 0) & (given > room + 1e-9)
        if over.any():
            given = np.where(over, room, given)
            w = np.where(over, -room * DT / f, w)
        sent = fleet.p0[t] + given
        cut = sent > lim + 1e-9
        if cut.any():
            lost += float(((sent - lim) * DT)[cut].sum())
            sent = np.minimum(sent, lim)
        x = x + w
        new[t], after[t], level[t] = w, sent, x
    return Run(after, new, level, lost, asked)

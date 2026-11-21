"""The plan the aggregator makes at 14:00 for the hours 14:00 to 24:00: which battery gives how much in which hour. It reads only the grid's
expected loading, never a price.

  1. The need. For each hour, the MW the asked batteries must give so that no transformer reaches 80% (and, first, none reaches 100%), from the
     loading the grid would have if they gave nothing.
  2. Which hours. True overloads first, as many as the batteries can bring under 100%; then as many hours as they can bring under 80%, the ones
     that need least first. "Can" is checked exactly: the k largest needs must fit what the batteries can give over their k fullest hours.
  3. Who. Hours are filled from the largest amount down; in each, the amount is split in proportion to the energy each battery still has, never
     above its power.
  4. What is left goes first to strained hours the batteries cannot clear, the worst first, then to the evening's highest-loaded hours.

What the plan knows about tonight: yesterday evening's loading, moved by how this morning (08:00 to 12:00) differs from yesterday morning. The first
day has no yesterday, so every asked battery gives a third of its usable energy in each hour from 18:00 to 21:00.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from ..fleet import Fleet

H0, H1 = 14, 24                     # the hours the plan covers
NH = H1 - H0
NO_LOADING_ORDER = np.array([5, 6, 4, 7, 3, 8, 2, 9, 1, 0])    # 19:00, 20:00, 18:00, ... for an evening with no expected loading at all


@dataclass(frozen=True)
class Asked:
    """Which batteries the aggregator may ask, and what follows from that."""
    take: np.ndarray                # by battery: may be asked
    power: np.ndarray               # by battery: kW it may be asked for (its rating; 0 when not asked)
    sle: np.ndarray                 # by transformer: points relieved per 100 MW when the asked batteries give in proportion to their power
    pos: np.ndarray                 # by transformer: relieved by more than half a point per 100 MW
    expected: np.ndarray            # days x plan hours x transformers: the loading expected at 14:00 if the asked batteries gave nothing


def asked(take: np.ndarray, fleet: Fleet, ruler: np.ndarray, loading: np.ndarray) -> Asked:
    """take: which batteries may be asked. ruler: transformers x kinds, points relieved per MW given. loading: days x 24 x transformers, the grid as
    it ran (the batteries as recorded)."""
    kj, PM = fleet.rat.kj, fleet.rat.power_kw
    kinds = sorted(set(kj[take].tolist()))
    given = np.stack([fleet.by_hour(np.maximum(fleet.grec[:, kj == q], 0).sum(axis=1) / 1000) for q in range(ruler.shape[1])], axis=2)   # MW given as recorded, by kind
    without = loading + given[..., kinds] @ ruler[:, kinds].T          # the loading had the asked kinds given nothing
    sle = ruler[:, kj][:, take] @ (PM[take] / PM[take].sum()) * 100
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        morning = np.nanmean(loading[:, 8:12], axis=1)                  # this morning's loading, published before 14:00
    ahead = np.full(without.shape, np.nan)
    ahead[1:] = without[:-1] + (morning[1:] - morning[:-1])[:, None, :]
    return Asked(take, PM * take, sle, sle > .5, ahead[:, H0:H1])


def need(L: np.ndarray, target: float, A: Asked) -> np.ndarray:
    """MW the asked batteries must give in each hour to bring every transformer they relieve under `target`. L: hours x transformers."""
    n = (L[:, A.pos] - target) / A.sle[A.pos] * 100
    n = np.where(np.isnan(n), -np.inf, n)
    return np.maximum(n.max(axis=1), 0.0)


def waterfill(want: float, w: np.ndarray, room: np.ndarray) -> np.ndarray:
    """Split `want` in proportion to w, never above room."""
    a = np.zeros_like(room)
    act = (room > 1e-9) & (w > 1e-9)
    rem = float(want)
    for _ in range(len(room) + 1):
        if rem <= 1e-9 or not act.any():
            break
        share = rem * (w * act) / (w * act).sum()
        over = act & (share >= room - a - 1e-12)
        if not over.any():
            a = a + share
            break
        add = np.where(over, room - a, 0.0)
        a = a + add
        rem -= float(add.sum())
        act = act & ~over
    return a


def first_day(x: np.ndarray, A: Asked, emin: np.ndarray, f: np.ndarray) -> np.ndarray:
    """No yesterday to read: each asked battery gives a third of its usable energy in each hour from 18:00 to 21:00."""
    e = np.maximum(x - emin, 0.0) * f * A.take
    g = np.zeros((len(x), NH))
    g[:, 18 - H0:21 - H0] = np.minimum(A.power, e / 3)[:, None]
    return g


def plan(L: np.ndarray, x: np.ndarray, A: Asked, emin: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """L: plan hours x transformers, the loading expected. x: kWh in each store now. Returns kW at the connection for each battery and hour, and
    the MW the request asks of all asked batteries together in each hour (what the batteries give beyond it is the plan's last step)."""
    e = np.maximum(x - emin, 0.0) * f * A.take
    g = np.zeros((len(x), NH))
    left = e.copy()
    can = np.array([np.minimum(e, k * A.power).sum() for k in range(1, NH + 1)]) / 1000      # MWh the batteries can give over their k fullest hours

    def fits(v: np.ndarray) -> bool:
        v = np.sort(v[v > 1e-9])[::-1]
        return bool((np.cumsum(v) <= can[:len(v)] + 1e-6).all())

    n100, n80 = need(L, 99.9, A), need(L, 79.9, A)
    R = np.zeros(NH)
    for h in np.argsort(n100):
        if n100[h] > 0:
            t = R.copy()
            t[h] = n100[h]
            R = t if fits(t) else R
    for h in np.argsort(n80):
        if n80[h] > R[h]:
            t = R.copy()
            t[h] = n80[h]
            R = t if fits(t) else R
    for h in np.argsort(-R):
        if R[h] > 0:
            got = waterfill(R[h] * 1000, left, np.minimum(A.power, left))
            g[:, h] = got
            left = left - got
    for h in [int(h) for h in np.argsort(-n80) if n80[h] > R[h] + 1e-9]:         # strained hours the batteries cannot clear: all that is left, the worst first
        room = np.minimum(A.power - g[:, h], left)
        g[:, h] += room
        left = left - room
    asked_mw = g.sum(axis=0) / 1000
    peak = np.max(np.where(np.isnan(L[:, A.pos]), -np.inf, L[:, A.pos]), axis=1)    # the evening's highest-loaded hours, as expected at 14:00
    order = np.argsort(-peak) if np.isfinite(peak).any() else NO_LOADING_ORDER
    for h in order:
        room = np.minimum(A.power - g[:, h], left)
        g[:, h] += room
        left = left - room
    return g, asked_mw

"""The 80 participants' batteries as ENGIE's 2025 reports show them, every 15 minutes.

How the reports are read (each point checked against ENGIE's meter and device readings):
  - only reports a participant signed in its own name with a valid signature count, the first delivery of each slot; gaps are interpolated
  - a report stamped T gives the battery's charge at the end of that step
  - charging enters the store one to one; giving loses part on the way to the connection: `f`, measured for each battery from its full-power
    giving steps (what its rating allows over what the charge fell), the fleet's median where a battery has too few such steps
  - a one-step spike of charge that comes straight back (a correction of the battery's own estimate) is replaced by the mean of its neighbours
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .data import local, utc

LO, HI, DT = 0.10, 0.90, 0.25       # the charge a battery keeps between, and the length of a step in hours
KINDS = ("community", "datacenter", "pv_bess")


@dataclass(frozen=True)
class Ratings:
    """The participants that have a battery, in id order, with their ratings."""
    ids: list[str]
    kind: np.ndarray                  # ENGIE's kind of participant
    energy_kwh: np.ndarray
    power_kw: np.ndarray
    limit_kw: np.ndarray              # the connection's limit (infinite where ENGIE gives none)

    @property
    def kj(self) -> np.ndarray:
        """Each participant's kind as an index into KINDS."""
        return np.array([KINDS.index(k) for k in self.kind])


def ratings(folder: Path) -> Ratings:
    rat = pd.read_parquet(folder / "asset_ratings.parquet").set_index("entity_id")
    ids = sorted(rat.index[rat.bess_energy_kwh > 0])
    return Ratings(ids, rat.entity_type[ids].to_numpy(), rat.bess_energy_kwh[ids].to_numpy(float), rat.bess_power_kw[ids].to_numpy(float),
                   rat.poi_limit_kw[ids].fillna(np.inf).to_numpy(float))


@dataclass(frozen=True)
class Fleet:
    """The batteries' recorded behaviour, steps x participants. Power is kW at the connection, + sent out."""
    steps: pd.DatetimeIndex           # UTC, time-zone free, every 15 minutes
    rat: Ratings
    p: np.ndarray                     # the site's reported net power
    s: np.ndarray                     # the battery's charge, share of its energy, after the spike fix
    f: np.ndarray                     # kWh that reach the connection per kWh taken out of the store, by battery
    d: np.ndarray                     # the recorded store step, kWh, inside the rating
    grec: np.ndarray                  # the battery's recorded power at the connection
    p0: np.ndarray                    # the site with its battery idle
    hour: np.ndarray                  # local clock of each step
    minute: np.ndarray
    day: np.ndarray                   # local day of the year, from 0

    @property
    def emin(self) -> np.ndarray:
        return LO * self.rat.energy_kwh

    @property
    def emax(self) -> np.ndarray:
        return HI * self.rat.energy_kwh

    @property
    def days(self) -> int:
        return int(self.day.max()) + 1

    def by_hour(self, v: np.ndarray) -> np.ndarray:
        """The mean of a per-step series over each local (day, hour)."""
        a, c = np.zeros((self.days, 24)), np.zeros((self.days, 24))
        np.add.at(a, (self.day, self.hour), v)
        np.add.at(c, (self.day, self.hour), 1)
        return a / np.maximum(c, 1)


def from_arrays(steps: pd.DatetimeIndex, rat: Ratings, p: np.ndarray, s: np.ndarray) -> Fleet:
    """The fleet from reported power and charge (steps x participants), as the module's header describes."""
    E, PM = rat.energy_kwh, rat.power_kw
    cap = PM * DT
    s = s.copy()
    raw = np.diff(s, axis=0, prepend=s[:1]) * E
    f = np.full(len(rat.ids), np.nan)
    for j in range(len(rat.ids)):
        g = -raw[:, j]
        m = (g > .9 * cap[j]) & (g < 1.3 * cap[j])
        if m.sum() > 50:
            f[j] = float(np.median(cap[j] / g[m]))
    f = np.where(np.isnan(f), np.nanmedian(f), f)
    a, b, c = s[:-2], s[1:-1], s[2:]
    up, dn = (b - a) * E, (c - b) * E
    spike = ((up * dn < 0) & ((np.abs(up) > 1.25 * cap / f) | (np.abs(dn) > 1.25 * cap / f)) & (np.minimum(np.abs(up), np.abs(dn)) > .5 * cap)
             & (np.abs(c - a) * E < 2 * cap / f))
    s[1:-1][spike] = ((a + c) / 2)[spike]
    raw = np.diff(s, axis=0, prepend=s[:1]) * E
    d = np.clip(raw, -cap / f, cap)
    grec = np.where(d >= 0, -d, -d * f) / DT
    at = local(steps)
    return Fleet(steps, rat, p, s, f, d, grec, p - grec, np.asarray(at.hour), np.asarray(at.minute), np.asarray(at.dayofyear) - 1)


def from_reports(folder: Path) -> Fleet:
    """The fleet from the 2025 release's reports and ratings."""
    rat = ratings(folder)
    cols = ["timestamp", "delivered_at", "entity_id", "claimed_entity_id", "reported_p_net_kw", "reported_soc_percent", "auth_status"]
    r = pq.read_table(folder / "reports.parquet", columns=cols).to_pandas()
    r = r[(r.entity_id == r.claimed_entity_id) & (r.auth_status == "valid")].sort_values("delivered_at").drop_duplicates(["entity_id", "timestamp"])
    r["U"] = utc(r.timestamp)
    steps = pd.date_range(r.U.min(), r.U.max(), freq="15min")
    p = r.pivot_table(index="U", columns="entity_id", values="reported_p_net_kw").reindex(steps)[rat.ids].interpolate(limit_direction="both").to_numpy()
    s = r.pivot_table(index="U", columns="entity_id", values="reported_soc_percent").reindex(steps)[rat.ids].interpolate(limit_direction="both").to_numpy() / 100
    return from_arrays(steps, rat, p, s)

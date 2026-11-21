"""What the referee reads of ENGIE's 2025 release, and the constants of its checks.

ENGIE's rules (the release's SUBMISSION.md): a call at 30 minutes after a slot starts and a revised call at 2 hours, each made only from what
had arrived by then; the scored interval is 1 March to 31 December 2025 (UTC); January and February are the warm-up, and nothing is fitted on
later data. The slots are the release's own year: every 15 minutes of 2025 on the participants' local clock.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RT, RV = pd.Timedelta(30, "min"), pd.Timedelta(2, "h")         # the two deadlines after a slot starts
HOUR_END = pd.Timedelta(45, "min")                              # an hour's last slot starts 45 minutes into it
TOL = 0.05                     # a meter that differs by more than this share of the participant's size contradicts the report
SOC_TOL = 3.0                  # points of charge the battery's own reading may differ by at the hour's end
STUCK = 4                      # the same non-zero power this many slots running (an hour) is a stuck value
T0, T1 = pd.Timestamp("2025-01-01 06:00", tz="UTC"), pd.Timestamp("2026-01-01 05:45", tz="UTC")
SCORE0, SCORE1 = pd.Timestamp("2025-03-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")
LIT_WM2 = 75.0                 # sunlight above this is daylight: night readings carry noise up to about 66 W/m2
DARK_DAYS = 14                 # an hour is dark at a site when it was dark there on each of the 14 days before

REPORTS = ["event_id", "timestamp", "delivered_at", "entity_id", "claimed_entity_id", "seq", "reported_p_net_kw", "reported_soc_percent",
           "auth_status", "text"]


def ts(x) -> pd.Series:
    return pd.to_datetime(x, utc=True)


def load(folder: Path) -> dict[str, pd.DataFrame]:
    """The reports, the ratings, the utility's meter, the batteries' own readings, and which hours are dark at each site."""
    r = pd.read_parquet(folder / "reports.parquet", columns=REPORTS)
    r["t"], r["dl"] = ts(r.timestamp), ts(r.delivered_at)
    r = r.drop(columns=["timestamp", "delivered_at"])
    rat = pd.read_parquet(folder / "asset_ratings.parquet").set_index("entity_id")
    am = pd.read_parquet(folder / "obs_ami.parquet", columns=["obs_id", "entity_id", "measured_at", "available_at", "p_net_kw"])
    am["t"], am["m_av"] = ts(am.measured_at), ts(am.available_at)
    am = am.rename(columns={"obs_id": "m_id", "p_net_kw": "m_kw"})[["entity_id", "t", "m_id", "m_av", "m_kw"]]
    dv = pd.read_parquet(folder / "obs_device.parquet", columns=["obs_id", "entity_id", "measured_at", "available_at", "bess_soc_percent_end"])
    dv["t"], dv["d_av"] = ts(dv.measured_at) + HOUR_END, ts(dv.available_at)     # an hour's reading holds the charge at its last slot
    dv = dv.rename(columns={"obs_id": "d_id", "bess_soc_percent_end": "d_soc"})[["entity_id", "t", "d_id", "d_av", "d_soc"]]
    ir = pd.read_parquet(folder / "obs_irradiance.parquet", columns=["entity_id", "measured_at", "ghi_wm2"])
    return {"r": r, "rat": rat, "am": am, "dv": dv, "dark": dark_hours(ir)}


def dark_hours(ir: pd.DataFrame) -> pd.DataFrame:
    """For each UTC day, site and UTC hour: dark there on each of the 14 days before (readings come two hours late, so only past days count),
    and the hour before and the hour after dark too, so dusk and dawn, when the meter shows real output, are left out."""
    h = ts(ir.measured_at)
    ir = ir.assign(d=h.dt.floor("D"), hod=h.dt.hour, lit=(ir.ghi_wm2.fillna(0) > LIT_WM2).astype(float))
    ents = sorted(ir.entity_id.unique())
    w = ir.pivot_table(index="d", columns=["entity_id", "hod"], values="lit", aggfunc="max").sort_index().fillna(0.0)
    w = w.reindex(columns=pd.MultiIndex.from_product([ents, range(24)]), fill_value=0.0)
    a = (w.rolling(DARK_DAYS, min_periods=7).max().shift(1) == 0).to_numpy().reshape(len(w), len(ents), 24)
    a = a & np.roll(a, 1, axis=2) & np.roll(a, -1, axis=2)
    days, n = w.index, len(w)
    return pd.DataFrame({"d": days.repeat(len(ents) * 24), "entity_id": np.tile(np.repeat(np.asarray(ents, dtype=object), 24), n),
                         "hod": np.tile(np.arange(24), n * len(ents)), "dark": a.reshape(-1)})

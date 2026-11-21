"""One row per participant and report slot, with everything the checks need and the moment each piece became known.

  transport(r)   how each delivered row stands: a bad signature, another participant's name, the n-th delivery of a report (a duplicate
                 within half an hour, a replay after), and its lag
  build(data)    the slots: the report itself (own name, good signature, first delivery), the transport findings, the numbers' own checks,
                 the utility's meter and the battery's own reading beside it, and the word pattern on its note
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .inputs import HOUR_END, RT, RV, SCORE0, SOC_TOL, STUCK, T0, T1, TOL
from .notes import NOTE_PAT

FINDINGS = (("sig", "bad_sig", False), ("name", "other", False), ("dup", "dup", False), ("replay", "replay", True))   # a replay counts where it arrives


def transport(r: pd.DataFrame) -> pd.DataFrame:
    r = r.sort_values("dl").copy()
    r["bad_sig"] = r.auth_status.eq("invalid")
    r["other"] = r.entity_id.ne(r.claimed_entity_id)
    key = [r.entity_id, r.claimed_entity_id, r.seq]
    r["nth"] = r.groupby(key).cumcount()
    delay = (r.dl - r.groupby(key).dl.transform("first")).dt.total_seconds() / 60
    r["dup"] = (r.nth > 0) & (delay < 30)
    r["replay"] = (r.nth > 0) & (delay >= 30)
    r["lag"] = (r.dl - r.t).dt.total_seconds() / 60
    return r


def _reports(K: pd.DataFrame, r: pd.DataFrame) -> pd.DataFrame:
    """The report of each slot, and the first row of each transport finding: for a replay the slot it arrives in, else the slot it names."""
    gen = r[~r.other & ~r.bad_sig & (r.nth == 0)].drop_duplicates(["entity_id", "t"])
    cols = ["entity_id", "t", "event_id", "dl", "lag", "reported_p_net_kw", "reported_soc_percent", "text"]
    K = K.merge(gen[cols].rename(columns={"reported_p_net_kw": "p", "reported_soc_percent": "soc"}), on=["entity_id", "t"], how="left")
    for name, mask, by_arrival in FINDINGS:
        x = r[r[mask]].assign(t=r.dl.dt.floor("15min") if by_arrival else r.t).drop_duplicates(["entity_id", "t"])
        x = x[["entity_id", "t", "dl", "event_id"]].rename(columns={"dl": name + "_dl", "event_id": name + "_id"})
        K = K.merge(x, on=["entity_id", "t"], how="left")
    return K


def _numbers(K: pd.DataFrame, dark: pd.DataFrame) -> pd.DataFrame:
    """The numbers' own checks, known at 30 minutes: limits, a charge step the battery cannot make, a plant sending out at night, stuck values."""
    g = K.groupby("entity_id", sort=False)
    K["limits"] = ((K.soc < 9.5) | (K.soc > 90.5) | (K.p > K.poi_limit_kw * 1.05 + 5) | (K.p > (K.pv_ac_kw + K.bess_power_kw) * 1.05 + 5)
                   | (-K.p > K.peak_kw_rounded * 1.3 + K.bess_power_kw))
    K["step"] = g.soc.diff().abs() / 100 * K.bess_energy_kwh / .25 > 1.3 * K.bess_power_kw / .85
    K["d"], K["hod"] = K.t.dt.floor("D"), K.t.dt.hour
    K = K.merge(dark, on=["d", "entity_id", "hod"], how="left")
    K["dark"] = K.dark.eq(True)                       # an hour with no sunlight record at the site is not dark
    K["dark_out"] = (K.entity_type == "pv_bess") & K.dark & (K.p > K.bess_power_kw * 1.05 + .01 * K.pv_ac_kw)
    g = K.groupby("entity_id", sort=False)
    same = (K.p == g.p.shift(1)) & (K.p.abs() > 1)
    run = (~same).groupby(K.entity_id, sort=False).cumsum()
    K["pos"] = same.groupby([K.entity_id, run], sort=False).cumsum()
    K["rem"] = K.groupby([K.entity_id, run], sort=False).pos.transform("max") - K.pos
    next_in_time = (g.dl.shift(-1) <= K.t + RT).fillna(False)
    K["stuck_rt"] = (K.pos + 1 + ((K.rem >= 1) & next_in_time).astype(int)) >= STUCK        # at 30 minutes the next report may be in already
    K["stuck_rv"] = (K.pos + 1 + K.rem.clip(upper=7)) >= STUCK                               # at 2 hours up to seven more are
    return K


def _meter(K: pd.DataFrame, am: pd.DataFrame) -> pd.DataFrame:
    """The utility's meter beside each slot, and whether it is the meter that looks wrong: stuck, or a one-slot jump the report does not share."""
    K = K.merge(am, on=["entity_id", "t"], how="left")
    g = K.groupby("entity_id", sort=False)
    K["m_gap"] = (K.p - K.m_kw).abs() / K["size"]
    m_same = (K.m_kw == g.m_kw.shift(1)) & (K.m_kw.abs() > 1)
    m_run = (~m_same).groupby(K.entity_id, sort=False).cumsum()
    m_len = m_same.groupby([K.entity_id, m_run], sort=False).transform("sum") + 1
    up = K.m_kw - g.m_kw.shift(1)
    alone = ((up.abs() > TOL * K["size"]) & ((K.p - g.p.shift(1)).abs() < .4 * up.abs()) & ((K.m_kw - g.m_kw.shift(-1)).abs() > TOL * K["size"])
             & (g.m_av.shift(-1) <= K.t + RV) & ((g.m_kw.shift(-1) - g.m_kw.shift(1)).abs() < TOL * K["size"]))
    K["m_suspect"] = (m_len >= STUCK) | alone.fillna(False)
    return K


def _device(K: pd.DataFrame, dv: pd.DataFrame) -> pd.DataFrame:
    """The battery's own reading for the hour each slot is in: equal at the hour's end, between the hour's two ends inside it. If it is the
    device that has not moved while the report moved smoothly, the device is the suspect."""
    K["hend"] = K.t.dt.floor("h") + HOUR_END
    K = K.merge(dv.rename(columns={"t": "hend"}), on=["entity_id", "hend"], how="left")
    g = K.groupby("entity_id", sort=False)
    d_prev, end = g.d_soc.shift(4), K.t == K.hend
    lo, hi = np.minimum(d_prev, K.d_soc), np.maximum(d_prev, K.d_soc)
    K["d_gap"] = np.where(end, (K.soc - K.d_soc).abs(), np.maximum(np.maximum(lo - K.soc, K.soc - hi), 0.0))
    K["d_tol"] = np.where(end, SOC_TOL, SOC_TOL + 2)
    jumped = g.step.rolling(4, min_periods=1).max().reset_index(level=0, drop=True).reindex(K.index).fillna(0) > 0
    K["d_suspect"] = ((K.d_soc - d_prev).abs() < .05) & ((K.soc - g.soc.shift(4)).abs() > 1) & ~jumped
    return K


def build(data: dict[str, pd.DataFrame], r: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The slots of every participant over the release's year, and the delivered rows as transport() leaves them."""
    r = transport(data["r"] if r is None else r)
    rat = data["rat"]
    K = pd.MultiIndex.from_product([sorted(rat.index), pd.date_range(T0, T1, freq="15min")], names=["entity_id", "t"]).to_frame(index=False)
    K = _reports(K, r)
    for c in ("pv_ac_kw", "bess_power_kw", "bess_energy_kwh", "poi_limit_kw", "peak_kw_rounded", "entity_type"):
        K[c] = K.entity_id.map(rat[c])
    K["pv_ac_kw"] = K.pv_ac_kw.fillna(0)
    warm = K[(K.t < SCORE0) & K.p.notna()]            # a participant's size: its 98th-percentile power in the warm-up, at least 50 kW
    K["size"] = K.entity_id.map(warm.groupby("entity_id").p.apply(lambda s: float(s.abs().quantile(.98)))).clip(lower=50)
    K = K.sort_values(["entity_id", "t"]).reset_index(drop=True)
    K = _device(_meter(_numbers(K, data["dark"]), data["am"]), data["dv"])
    K["note_hit"] = K.text.fillna("").str.lower().str.contains(NOTE_PAT, regex=True)
    return K.drop(columns=["d", "hod", "hend"]), r

"""Lies of known kind and size, planted in ENGIE's own 2025 reports and judged: the only way to know what the checks catch, since ENGIE keeps
the true labels.

Each planted case is a run of 8 slots (2 hours) in one participant's reports, put where every call was trusted, and at least 16 slots from any
other case. Only the report changes; the meter and the battery's device keep what they recorded, as they would if a participant lied.

  off by 3, 6, 10, 20, 50% of size   power moved by that share of the participant's size, either way (down where up would pass its rating)
  nothing flowing                    power reported as zero while a fifth of its size or more is flowing
  stuck                              the first slot's power and charge repeated for two hours while the truth moves
  after dark                         a solar-and-battery plant reports half of what its solar and battery could send, at an hour dark at its site
  charge 20 points too high          the battery reported fuller than it is (at most 90%)
  yesterday's numbers                the same two hours of the day before sent again as today's

The planted lies change only numbers, so their calls leave notes to the word pattern and depend on no model's answers. Read the result as a map
of what can and cannot be seen, not as a score: the kinds and sizes are chosen here, not by ENGIE.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calls import decide
from .inputs import RV, SCORE0, SCORE1
from .slots import build

RUN, PER, SEED = 8, 150, 11
OFF = (.03, .06, .10, .20, .50)


def _window(x: np.ndarray, f) -> np.ndarray:
    return f(np.lib.stride_tricks.sliding_window_view(x, RUN), axis=1)


def _share(x: pd.DataFrame, col: str) -> dict:
    return {k: round(float((x[col] == k).mean()), 3) for k in ("untrusted", "unverifiable", "trusted")}


def plan(K: pd.DataFrame, rt0: pd.DataFrame, rv0: pd.DataFrame, per: int = PER) -> tuple[pd.DataFrame, dict]:
    """Where each case goes and what it reports: rows of K, the kind, and the new power and charge; up to `per` runs of each kind."""
    rng = np.random.default_rng(SEED)
    sc = ((K.t >= SCORE0) & (K.t < SCORE1)).to_numpy()
    ok = ((rv0.status == "trusted") & (rt0.status == "trusted")).to_numpy() & K.event_id.notna().to_numpy() & sc
    ent, p, soc, size, n = K.entity_id.to_numpy(), K.p.to_numpy(), K.soc.to_numpy(), K["size"].to_numpy(), len(K)
    top = K.pv_ac_kw.to_numpy() + K.bess_power_kw.to_numpy()
    m = n - RUN + 1
    good = np.zeros(n, dtype=bool)
    good[:m] = (_window(ok.astype(int), np.sum) == RUN) & (ent[:m] == ent[RUN - 1:])
    pmin, pspan = np.full(n, np.nan), np.full(n, np.nan)
    pmin[:m] = _window(np.nan_to_num(np.abs(p)), np.min)
    pspan[:m] = _window(np.nan_to_num(p), np.max) - _window(np.nan_to_num(p), np.min)
    dark = np.zeros(n, dtype=bool)
    dark[:m] = _window((K.dark & (K.entity_type == "pv_bess")).to_numpy().astype(int), np.sum) == RUN
    day_ok = np.zeros(n, dtype=bool)
    day_ok[96:] = K.event_id.notna().to_numpy()[:-96] & (ent[96:] == ent[:-96])
    dprev = np.zeros(n, dtype=bool)
    dprev[:m] = _window(day_ok.astype(int), np.sum) == RUN
    taken, plans = np.zeros(n, dtype=bool), []

    def pick(name, cond, make):
        cand = np.flatnonzero(good & cond)
        rng.shuffle(cand)
        got = 0
        for i in cand:
            if got >= per:
                break
            if taken[max(0, i - 16): i + RUN + 16].any():
                continue
            taken[i: i + RUN] = True
            idx = np.arange(i, i + RUN)
            p_new, soc_new = make(idx)
            plans.append(pd.DataFrame({"row": idx, "family": name, "p_new": p_new, "soc_new": soc_new}))
            got += 1
        return got

    def off(x):
        def make(idx):
            v = p[idx] + rng.choice([-1, 1]) * x * size[idx]
            return np.where(v > top[idx], p[idx] - x * size[idx], v), soc[idx]
        return make

    every, counts = np.ones(n, dtype=bool), {}
    for x in OFF:
        counts[f"off by {int(x * 100)}% of size"] = pick(f"off by {int(x * 100)}% of size", every, off(x))
    counts["nothing flowing"] = pick("nothing flowing", pmin >= .2 * size, lambda idx: (np.zeros(RUN), soc[idx]))
    counts["stuck"] = pick("stuck", pspan >= .05 * size, lambda idx: (np.full(RUN, p[idx[0]]), np.full(RUN, soc[idx[0]])))
    counts["after dark"] = pick("after dark", dark, lambda idx: (np.full(RUN, .5) * top[idx] * (1 + .01 * rng.standard_normal(RUN)), soc[idx]))
    counts["charge 20 points too high"] = pick("charge 20 points too high", np.nan_to_num(soc) <= 65, lambda idx: (p[idx], np.minimum(soc[idx] + 20, 90)))
    counts["yesterday's numbers"] = pick("yesterday's numbers", dprev & (np.abs(np.nan_to_num(p) - np.nan_to_num(np.roll(p, 96))) >= .05 * size),
                                         lambda idx: (p[idx - 96], soc[idx - 96]))
    P = pd.concat(plans, ignore_index=True)
    P["event_id"] = K.event_id.to_numpy()[P.row.to_numpy()]
    return P, counts


def run(data: dict, K: pd.DataFrame, r: pd.DataFrame, per: int = PER) -> dict:
    """Plant every case into the delivered rows, build and call again, and say what each kind of lie looks like at each deadline."""
    rt0, rv0 = decide(K, "realtime"), decide(K, "revised")
    P, counts = plan(K, rt0, rv0, per)
    r2 = r.set_index("event_id")
    r2.loc[P.event_id, "reported_p_net_kw"] = P.p_new.to_numpy()
    r2.loc[P.event_id, "reported_soc_percent"] = P.soc_new.to_numpy()
    K2, _ = build(data, r=r2.reset_index())
    if not (K2.entity_id.to_numpy() == K.entity_id.to_numpy()).all():
        raise ValueError("the planted build lays out its slots differently")
    rt, rv = decide(K2, "realtime"), decide(K2, "revised")
    rows = P.row.to_numpy()
    P["rt"], P["rv"] = rt.status.to_numpy()[rows], rv.status.to_numpy()[rows]
    P["rt_why"], P["rv_why"] = rt.why.to_numpy()[rows], rv.why.to_numpy()[rows]
    P["meter"] = rv.meter_checked.to_numpy()[rows]
    P["device"] = (K2.d_av.notna() & (K2.d_av <= K2.t + RV)).to_numpy()[rows]
    P["pos"] = P.groupby(P.row.diff().ne(1).cumsum()).cumcount()           # the slot's place in its run of 8
    out = {"what": f"lies planted in ENGIE's 2025 reports where the referee had trusted everything, {per} runs of 2 hours per kind", "planted_runs": counts,
           "kinds": {}}
    for fam, x in P.groupby("family", sort=False):
        m, nm = x[x.meter], x[~x.meter]
        out["kinds"][fam] = {"slots": int(len(x)), "at_30_minutes": _share(x, "rt"), "at_2_hours": _share(x, "rv"),
                             "at_2_hours_where_a_meter_arrived": {**_share(m, "rv"), "slots": int(len(m))} if len(m) else None,
                             "at_2_hours_with_no_meter": {**_share(nm, "rv"), "slots": int(len(nm))} if len(nm) else None,
                             "caught_by_at_2_hours": {k: int(v) for k, v in x.rv_why[x.rv != "trusted"].value_counts().items()},
                             "caught_by_at_30_minutes": {k: int(v) for k, v in x.rt_why[x.rt != "trusted"].value_counts().items()}}
    st = P[P.family == "stuck"]
    if len(st):
        out["kinds"]["stuck"]["not_trusted_at_30_minutes_by_slot_of_the_run"] = {int(k): round(float(v), 2) for k, v in (st.rt != "trusted").groupby(st.pos).mean().items()}
    ch = P[P.family == "charge 20 points too high"]
    if len(ch):
        out["kinds"]["charge 20 points too high"]["at_2_hours_at_hour_ends_with_a_device"] = _share(ch[ch.device], "rv") | {"slots": int(ch.device.sum())}
    sc = ((K.t >= SCORE0) & (K.t < SCORE1)).to_numpy()
    other = np.ones(len(K), dtype=bool)
    other[rows] = False
    changed = other & sc & ((rt.status.to_numpy() != rt0.status.to_numpy()) | (rv.status.to_numpy() != rv0.status.to_numpy()))
    out["slots_not_planted_whose_call_changed"] = int(changed.sum())
    return out

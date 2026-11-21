"""The referee's calls: for every slot at each deadline trusted, unverifiable or untrusted with its reason; who is compromised; ENGIE's files.

At a deadline only what had arrived by then counts. Reasons are applied in order of weight, and a slot carries its weightiest one:

  untrusted      signature, name (another participant's), replay, note (addressed to the checker), limits, dark (a plant sending out more than
                 its battery can in the middle of the night), meter (more than 5% of size off), device (the battery's own charge differs), stuck
  unverifiable   missing, late, jump (a charge step the battery cannot make, which its own reading shows too), duplicate, meter_suspect and
                 device_suspect (the meter or the device is the one that looks wrong)

A participant is compromised when it signed a lie on two different days (a report in another's name, a note aimed at the checker), or when
its meter contradicted three or more reports in a row, not merely stuck ones, on three different days. Bad signatures and replays are not
held against the sender: someone else can do those to it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .inputs import RT, RV, SCORE0, SCORE1, TOL

REASONS = [("signature", "untrusted", .99), ("name", "untrusted", .99), ("replay", "untrusted", .97), ("note", "untrusted", .95),
           ("limits", "untrusted", .95), ("dark", "untrusted", .95), ("meter", "untrusted", .93), ("device", "untrusted", .9),
           ("stuck", "untrusted", .85), ("missing", "unverifiable", .7), ("late", "unverifiable", .7), ("jump", "unverifiable", .6),
           ("duplicate", "unverifiable", .6), ("meter_suspect", "unverifiable", .6), ("device_suspect", "unverifiable", .6)]
ACTION = {"signature": "flag_for_review", "name": "quarantine_settlement", "replay": "flag_for_review", "note": "flag_for_review",
          "limits": "quarantine_settlement", "dark": "quarantine_settlement", "meter": "quarantine_settlement", "device": "flag_for_review",
          "jump": "flag_for_review", "device_suspect": "flag_for_review", "stuck": "request_resend", "missing": "request_resend",
          "late": "request_resend", "duplicate": "none", "meter_suspect": "flag_for_review"}
CITED = {"signature": "sig_id", "name": "name_id", "replay": "replay_id", "duplicate": "dup_id"}     # the row a transport finding rests on


def decide(K: pd.DataFrame, horizon: str, notes: pd.Series | None = None) -> pd.DataFrame:
    """The call for every slot at one deadline ("realtime": 30 minutes, "revised": 2 hours). notes: True where a note addresses the checker
    (the model's reading), else the word pattern."""
    rv = horizon == "revised"
    dd = K.t + (RV if rv else RT)
    have = K.dl.notna() & (K.dl <= dd)
    note = K.note_hit if notes is None else notes.reindex(K.index).fillna(False)
    m_ok = rv & have & K.m_av.notna() & (K.m_av <= dd)
    d_ok = rv & have & K.d_av.notna() & (K.d_av <= dd)
    f = {"signature": K.sig_dl.notna() & (K.sig_dl <= dd), "name": K.name_dl.notna() & (K.name_dl <= dd), "replay": K.replay_dl.notna() & (K.replay_dl <= dd),
         "note": have & note, "limits": have & K.limits, "dark": have & K.dark_out, "meter": m_ok & (K.m_gap > TOL) & ~K.m_suspect,
         "device": d_ok & (K.d_gap > K.d_tol) & ~K.d_suspect, "device_suspect": d_ok & (K.d_gap > K.d_tol) & K.d_suspect, "jump": have & K.step,
         "stuck": have & (K.stuck_rv if rv else K.stuck_rt), "missing": ~have, "late": have & (K.dl > K.t + RT),
         "duplicate": K.dup_dl.notna() & (K.dup_dl <= dd), "meter_suspect": m_ok & (K.m_gap > TOL) & K.m_suspect}
    why, status, conf = pd.Series("", index=K.index), pd.Series("trusted", index=K.index), pd.Series(.8, index=K.index)
    for name, st, c in REASONS[::-1]:
        hit = f[name]
        why[hit], status[hit], conf[hit] = name, st, c
    conf[(status == "trusted") & m_ok & (K.m_gap <= TOL)] = .97
    return pd.DataFrame({"entity_id": K.entity_id, "timestamp": K.t, "horizon": horizon, "decided_at": dd, "status": status, "why": why,
                         "confidence": conf, "meter_checked": m_ok, **{"f_" + k: v for k, v in f.items()}})


def verdicts(K: pd.DataFrame, r: pd.DataFrame, dec_rv: pd.DataFrame, notes: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Who is compromised and from when, each piece of evidence counted from the moment it could be known; and by participant, the days of
    each kind of evidence."""
    note = K.note_hit if notes is None else notes.reindex(K.index).fillna(False)
    x = r[r.other]
    ev = [pd.DataFrame({"entity_id": x.entity_id, "at": x.dl, "kind": "name", "id": x.event_id})]
    x = K[note & K.dl.notna()]
    ev.append(pd.DataFrame({"entity_id": x.entity_id, "at": x.dl, "kind": "note", "id": x.event_id}))
    x = K[(dec_rv.f_meter & ~dec_rv.f_stuck).to_numpy()].copy()
    x["ep"] = (x.groupby("entity_id").t.diff().dt.total_seconds().div(900).fillna(99) > 2).cumsum()      # runs of contradicted slots
    x = x[x.groupby(["entity_id", "ep"]).t.transform("size") >= 3]
    ev.append(pd.DataFrame({"entity_id": x.entity_id, "at": x.t + RV, "kind": "meter", "id": x.event_id}))
    e = pd.concat(ev).sort_values("at")
    e["day"], e["clear"] = e["at"].dt.floor("D"), e.kind != "meter"
    rows = []
    for a, x in e.groupby("entity_id"):
        c, m = x[x.clear].drop_duplicates("day"), x[~x.clear].drop_duplicates("day")
        when = ([c["at"].iloc[1]] if len(c) >= 2 else []) + ([m["at"].iloc[2]] if len(m) >= 3 else [])
        if when:
            t = min(when)
            cited = [{"table": "reports", "id": i} for i in x[x["at"] <= t].drop_duplicates("day").id.head(4)]
            rows.append({"entity_id": a, "flagged_at": t, "verdict": "compromised", "days_another_name": int(x[x.kind == "name"].day.nunique()),
                         "days_note_to_checker": int(x[x.kind == "note"].day.nunique()), "days_meter_contradicts": int(m.day.nunique()),
                         "evidence": json.dumps(cited), "confidence": float(min(.99, .7 + .04 * (len(c) + len(m))))})
    by = e.groupby(["entity_id", "kind"]).day.nunique().unstack(fill_value=0).reindex(columns=["name", "note", "meter"], fill_value=0)
    return pd.DataFrame(rows), by


def scored(dec: pd.DataFrame) -> pd.DataFrame:
    return dec[(dec.timestamp >= SCORE0) & (dec.timestamp < SCORE1)]


def tally(dec: pd.DataFrame) -> dict:
    s = scored(dec)
    return {"slots": int(len(s)), "status": {k: int(v) for k, v in s.status.value_counts().items()},
            "why": {k: int(v) for k, v in s.why[s.why != ""].value_counts().items()}, "share_not_trusted": round(float((s.status != "trusted").mean()), 4),
            "checked_against_a_meter": round(float(s.meter_checked.mean()), 3)}


def engie_files(K: pd.DataFrame, decs: list[pd.DataFrame], ag: pd.DataFrame, out: Path) -> tuple[int, int]:
    """decisions.parquet and agents.parquet in ENGIE's layout. A slot left out counts as trusted, so only the others are written, each citing
    the rows it rests on, and only rows that had arrived by the time of the call."""
    rows = []
    for dec in decs:
        x = scored(dec)
        x = x[x.status != "trusted"]
        k = K.loc[x.index]
        rid = k.event_id.where(k.dl <= x.decided_at)
        for w, c in CITED.items():
            rid = rid.where(x.why != w, k[c])
        ev = [json.dumps(([{"table": "reports", "id": a}] if isinstance(a, str) else [])
                         + ([{"table": "obs_ami", "id": b}] if w in ("meter", "meter_suspect") and isinstance(b, str) else [])
                         + ([{"table": "obs_device", "id": c}] if w == "device" and isinstance(c, str) else [])) for a, b, c, w in zip(rid, k.m_id, k.d_id, x.why)]
        rows.append(pd.DataFrame({"entity_id": x.entity_id, "timestamp": x.timestamp, "horizon": x.horizon, "decided_at": x.decided_at, "status": x.status,
                                  "decision": x.status.map({"untrusted": "reject", "unverifiable": "hold"}), "action": x.why.map(ACTION), "evidence": ev,
                                  "confidence": x.confidence, "note": x.why}))
    d = pd.concat(rows, ignore_index=True)
    d.to_parquet(out / "decisions.parquet", index=False)
    a = ag[["entity_id", "flagged_at", "verdict", "evidence", "confidence"]]
    a.to_parquet(out / "agents.parquet", index=False)
    return len(d), len(a)


ALLOWED = {"horizon": {"realtime", "revised"}, "status": {"trusted", "untrusted", "unverifiable"}, "decision": {"accept", "reject", "hold"},
           "action": {"none", "request_resend", "quarantine_settlement", "suspend_agent", "flag_for_review"}}


def check_files(out: Path, D: dict[str, pd.DataFrame]) -> dict:
    """ENGIE's two files held to ENGIE's rules: allowed values, one row per slot and deadline, no call after its deadline, and no cited row
    that had not arrived (a report by its delivery, an observation by its availability) when the call or verdict was made."""
    d, a = pd.read_parquet(out / "decisions.parquet"), pd.read_parquet(out / "agents.parquet")
    when = {"reports": D["r"].groupby("event_id").dl.min().to_dict(), "obs_ami": D["am"].groupby("m_id").m_av.min().to_dict(),
            "obs_device": D["dv"].groupby("d_id").d_av.min().to_dict()}
    cited = early = unknown = 0
    for evs, ats in ((d.evidence, d.decided_at), (a.evidence, a.flagged_at)):
        for ev, at in zip(evs, ats):
            for item in json.loads(ev):
                cited += 1
                t = when.get(item["table"], {}).get(item["id"])
                unknown += t is None
                early += t is not None and t > at
    deadline = d.timestamp + d.horizon.map({"realtime": RT, "revised": RV})
    return {"values_not_allowed": int(sum((~d[c].isin(v)).sum() for c, v in ALLOWED.items()) + (~a.verdict.isin({"compromised", "faulty", "healthy"})).sum()),
            "rows_sharing_a_slot_and_deadline": int(d.duplicated(["entity_id", "timestamp", "horizon"]).sum()),
            "calls_after_their_deadline": int((d.decided_at > deadline).sum()), "evidence_cited": cited, "cited_rows_not_in_the_release": int(unknown),
            "cited_before_they_had_arrived": int(early)}


def summary(K: pd.DataFrame, rt: pd.DataFrame, rv: pd.DataFrame, ag: pd.DataFrame, by: pd.DataFrame, read_by: str) -> dict:
    """The calls in numbers: both deadlines, the meter as judge of the 30-minute call, and the participants."""
    sc = ((K.t >= SCORE0) & (K.t < SCORE1)).to_numpy()
    met = sc & rv.meter_checked.to_numpy()
    contra = met & (K.m_gap > TOL).to_numpy()
    rt_st, rt_why = rt.status.to_numpy(), rt.why.to_numpy()
    stuck_days = K[rv.f_stuck.to_numpy()].assign(day=lambda d: d.t.dt.floor("D")).groupby("entity_id").day.nunique()
    clear = (ag.days_another_name + ag.days_note_to_checker) >= 2 if len(ag) else pd.Series([], dtype=bool)
    n = int(K.entity_id.nunique())
    return {"what": "the referee's checks on ENGIE's 2025 reports, scored interval 1 March to 31 December", "notes_read_by": read_by,
            "at_30_minutes": tally(rt), "at_2_hours": tally(rv),
            "the_meter_as_judge_of_the_30_minute_call": {
                "slots_with_a_meter_in_time": int(met.sum()), "of_which_the_meter_contradicts_the_report": int(contra.sum()),
                "already_not_trusted_at_30_minutes": int((contra & (rt_st != "trusted")).sum()),
                "by_reason_at_30_minutes": {k: int(v) for k, v in pd.Series(rt_why[contra & (rt_st != "trusted")]).value_counts().items()},
                "agreed_with_the_meter_yet_untrusted_at_30_minutes": int((met & ~contra & (rt_st == "untrusted")).sum()),
                "of_which_stuck_values": int((met & ~contra & (rt_why == "stuck")).sum()), "of_slots_that_agreed": int((met & ~contra).sum())},
            "participants": {"all": n, "with_a_report_in_anothers_name": int((by["name"] > 0).sum()), "with_a_note_aimed_at_the_checker": int((by["note"] > 0).sum()),
                             "with_the_meter_contradicting_3_in_a_row": int((by["meter"] > 0).sum()), "with_none_of_these": n - len(by),
                             "called_compromised": int(len(ag)), "of_which_on_clear_evidence": int(clear.sum()), "of_which_on_the_meter_alone": int((~clear).sum()),
                             "with_stuck_values_on_3_or_more_days": int((stuck_days >= 3).sum())}}

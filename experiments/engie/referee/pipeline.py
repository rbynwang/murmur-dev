"""The referee's pipeline: the notes read, every slot called at both deadlines, who is compromised, ENGIE's two files, and the planted lies.

Writes into OUT: referee.json (the calls in numbers), decisions.parquet and agents.parquet (ENGIE's layout), notes.json (the notes test),
plant.json (the planted lies) and, when a model server was asked, model_readings.json (its answers, in the form of the recorded file).
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import data
from . import notes, plant
from .calls import check_files, decide, engie_files, summary, verdicts
from .inputs import load
from .slots import build


def _readings(known, new, given: Path | None, say) -> tuple[notes.Readings | None, str]:
    model = notes.model_from_env()
    if model:
        url, name = model
        say(f"asking the model {name} for {new.nunique()} new texts, {len(known)} everyday sentences and the fresh set")
        rd = notes.read_with_model(sorted(new.unique()), known, notes.fresh(), url, name)
        return rd, f"the model {name}, asked in this run"
    if given is not None and not given.exists():
        raise data.DataMissing(f"no readings file at {given}")
    path = given or notes.READINGS
    if not path.exists():
        return None, "the word pattern"
    rd = notes.Readings.load(path)
    missing = sum(rd.answer(u) is None for u in new.unique())
    if missing:
        say(f"the readings file holds no answer for {missing} of {new.nunique()} new texts: those notes are not flagged")
    return rd, f"the recorded answers of the model {rd.model}"


def run(root: Path, out: Path, readings: Path | None = None, say=print) -> dict:
    t0 = time.time()
    folder = data.release_2025(root)
    D = load(folder)
    K, r = build(D)
    say(f"slots built: {len(K):,} ({K.entity_id.nunique()} participants), {len(r):,} delivered rows ({time.time() - t0:.0f} s)")
    known = notes.library(K)
    new = notes.new_words(K, known)
    rd, read_by = _readings(known, new, readings, say)
    if rd is not None and notes.model_from_env():
        rd.write(out / "model_readings.json", "the model's answers in this run")
    nf = notes.flags(K, new, rd)
    rt, rv = decide(K, "realtime", nf), decide(K, "revised", nf)
    ag, by = verdicts(K, r, rv, nf)
    res = summary(K, rt, rv, ag, by, read_by)
    n_d, n_a = engie_files(K, [rt, rv], ag, out)
    res["files"] = {"decisions.parquet rows (not plainly trusted)": n_d, "agents.parquet rows": n_a, "held_to_engies_rules": check_files(out, D)}
    data.write_json(out / "referee.json", res)
    say(f"notes read by {read_by}; calls written ({time.time() - t0:.0f} s)")
    ck = res["files"]["held_to_engies_rules"]
    say(f"ENGIE's files: {n_d:,} decision rows, {n_a} agent rows; values not allowed {ck['values_not_allowed']}, rows sharing a key "
        f"{ck['rows_sharing_a_slot_and_deadline']}, calls after their deadline {ck['calls_after_their_deadline']}, evidence cited "
        f"{ck['evidence_cited']:,}, cited before it had arrived {ck['cited_before_they_had_arrived']}, not in the release {ck['cited_rows_not_in_the_release']}")
    for h, key in (("30 minutes", "at_30_minutes"), ("2 hours", "at_2_hours")):
        s = res[key]["status"]
        say(f"at {h}, of {res[key]['slots']:,} slots: trusted {s.get('trusted', 0):,}, unverifiable {s.get('unverifiable', 0):,}, untrusted {s.get('untrusted', 0):,}")
    if rd is not None:
        nres = notes.summary(K, known, new, rd, notes.fresh())
        data.write_json(out / "notes.json", nres)
        e = nres["engie_new_words"]
        say(f"notes: {nres['notes_with_new_words']:,} with new words; the model flags {e['model_says_checker']['notes']:,}, "
            f"the word pattern {e['word_pattern_flags_notes']:,}")
    pres = plant.run(D, K, r)
    data.write_json(out / "plant.json", pres)
    say(f"planted lies judged: {sum(pres['planted_runs'].values())} runs ({time.time() - t0:.0f} s)")
    return res

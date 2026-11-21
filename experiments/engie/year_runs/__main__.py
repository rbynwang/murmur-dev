"""python -m experiments.engie.year_runs {choose,compare,evening} ...: the year's evenings, the runs with and without the community agent,
and a recorded evening's signed messages."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from . import compare, evening

YEAR_SETS = Path(__file__).resolve().parents[3] / "demo" / "recordings"


def _write(out: Path, name: str, value) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(value, indent=1, ensure_ascii=False))


def run_choose(args, say=print) -> int:
    from .. import data
    from . import choose
    try:
        folder = data.release_2025(data.data_dir(args.data_dir))
    except data.DataMissing as e:
        print(f"year_runs choose: {e}", file=sys.stderr)
        return 2
    prices = choose.evening_prices(folder, data.ZONE)
    year = sorted(d.year for d in prices.index)[len(prices) // 2]
    chosen = choose.choose(prices, year, data.ZONE)
    _write(Path(args.out), "evenings_48.json", {"what": f"four evenings a month of ENGIE's {year}, chosen by rule before any run", "rule": choose.RULE,
                                                "evenings": chosen})
    diff = choose.compare(chosen, compare.load(Path(args.recording))["evenings"])
    say(f"{len(chosen)} evenings chosen from {len(prices)} evenings' prices; against the recorded choice: "
        + ("all equal (evening, kind, price, middle)" if not diff else f"{len(diff)} differ: " + "; ".join(diff[:6])))
    return 0 if not diff else 1


def _year_sets() -> dict[str, list[str]]:
    sets = {}
    for f in sorted(YEAR_SETS.glob("year_*/results_engie.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            sets[f.parent.name] = [s["id"] for s in json.load(fh)["scenarios"]]
    return sets


def run_compare(args, say=print) -> int:
    rec = compare.load(Path(args.recording))
    tab = compare.table(rec)
    dearest = {}
    for e in rec["evenings"]:
        m = e["evening"][:7]
        if e["kind"] == "dearest" and e["price_18_21_usd_mwh"] > dearest.get(m, ("", -1.0))[1]:
            dearest[m] = (e["evening"], e["price_18_21_usd_mwh"])
    sets = {k: {"evenings": len(v), "each_months_dearest_of_the_48": sum(d == dearest.get(d[:7], ("",))[0] for d in v)} for k, v in _year_sets().items()}
    _write(Path(args.out), "with_and_without.json", {"what": "the 48 evenings with the community agent and without it (the control: it promises everything "
                                                             "offered), counted the same way from each run's own rows", "runs": len(rec["runs"]),
                                                     "by_weather_tier_case": tab, "recorded_year_sets": sets})
    say(f"{len(rec['runs'])} runs on {len(rec['evenings'])} evenings; {compare.headline(tab)}")
    for key, row in tab.items():
        say(f"  {key:22} promised {row['promised_kw']:8,.1f}  truth {row['delivered_by_the_truth_kw']:8,.1f}  meter {row['delivered_by_the_meter_kw']:8,.1f}  "
            f"kept {row['evenings_kept_by_the_truth']:2}/{row['evenings_kept_by_the_meter']:2}  short {-row['mean_miss_by_the_truth_pct']:4.1f}%  "
            f"worst {-row['worst_evening_by_the_truth_pct']:4.1f}%  members ${row['members_get_usd']:,}")
    for k, v in sets.items():
        say(f"  {k}: {v['evenings']} evenings, of which {v['each_months_dearest_of_the_48']} are their month's dearest evening of the 48")
    return 0


def run_evening(args, say=print) -> int:
    trace = evening.load(Path(args.recording))
    rows = evening.exchanges(trace)
    v = evening.verdict(rows)
    _write(Path(args.out), "evening_messages.json", {"evening": trace["meta"].get("day"), "exchanges": rows, "verdict": v})
    for r in rows:
        a, rep = r["answer"] or {}, r["report"]
        say(f"  {r['participant']:12} {r['kind']:24} request {r['request']['kind']} signed {r['request']['signer']}; answer {a.get('kind')} signed "
            f"{a.get('signer')}; report rows sent {rep.get('sent')}, kept {rep.get('kept')}, flagged {rep.get('flagged')}")
    say(f"{v['participants']} participants ({', '.join(v['kinds'])}) answer the aggregator: requests {v['request_kinds']} all signed by one key "
        f"{v['requests_signed_by_one_key']}; answers {v['answer_kinds']} each signed by its own key {v['answers_signed_by_their_own_keys']}; "
        f"signed report rows sent and kept {v['reports_sent_and_kept']}")
    return 0 if all(v[k] for k in ("requests_signed_by_one_key", "answers_signed_by_their_own_keys", "reports_sent_and_kept")) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The year's evenings, the runs with and without the community agent, and a recorded evening's messages.")
    sub = p.add_subparsers(dest="what", required=True)
    c = sub.add_parser("choose", help="the 48 evenings from ENGIE's 2025 prices, against the recorded choice")
    c.add_argument("--data-dir", default=None, help="the folder that holds ENGIE's releases (default $MURMUR_ENGIE_DATA_DIR)")
    c.add_argument("--recording", default=str(compare.RECORDING), help="the recorded runs, whose evenings are the recorded choice")
    m = sub.add_parser("compare", help="with and without the community agent, from the recorded runs")
    m.add_argument("--recording", default=str(compare.RECORDING), help="the recorded runs (default: this package's evening_runs.json.gz)")
    e = sub.add_parser("evening", help="who answers the aggregator in a recorded evening, in which signed messages")
    e.add_argument("--recording", default=str(evening.RECORDED), help="a recorded evening (default: the evening of 28 January 2025)")
    for s in (c, m, e):
        s.add_argument("--out", required=True, help="the folder the results are written to (made if missing)")
    args = p.parse_args(argv)
    return {"choose": run_choose, "compare": run_compare, "evening": run_evening}[args.what](args)


if __name__ == "__main__":
    sys.exit(main())

"""The runner's compare command (demo/runner/compare.py) on small made-up runs: a run folder with a summary.json and a record.json.gz.

Two runs are the same evening when they came to the same outcome and sent the same messages, whatever belongs to each run alone: wall
times, message ids, signatures and keys, the tag a run puts at the end of an id, the order in which messages between different pairs came
and what follows from it (which buyer settled last, which buyer's order a pooled sale goes by), a report row sent twice, the clock's pace.
What differs is printed under its kind, 20 lines of each at most, and the command exits 1.
"""
from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path

import pytest

from demo.runner import compare
from demo.runner.__main__ import main as runner

ORDER = {"utility": "flex-need-2025-01-28", "grid-operator": "grid-operator-need-2025-01-28"}      # each buyer's order on the evening's window
ASKS = {"utility": 9.0, "grid-operator": 5.4}                                                       # what each asks, kW
Q = [f"2025-01-28 {19 + k // 4:02d}:{15 * (k % 4):02d}" for k in range(6)]                         # 19:00 to 20:15
SIZE = "compared, A | B: 32 | 32 figures of the outcome, 10 | 10 messages, 4 | 4 report rows"


def message(run: str, n: int, frm: str, to: str, kind: str, said: dict, txn: str) -> dict:
    """One message as the bus keeps it. Everything that belongs to the run carries the run's name: the ids, the key, the signature, the wall times."""
    body = {"context": {"action": kind.split(".", 1)[1], "bapId": to, "bppId": frm, "transactionId": txn, "messageId": f"id-{run}-{n}", "timestamp": f"2026-11-22T08:00:{n:02d}Z",
                        "ttl": "PT900S", "sentWall": 1000.0 + n + len(run)},
            "message": said, "signer": f"key of {frm} in {run}", "sig": f"signed in {run}: {n}"}
    return {"event": "accepted", "message_id": f"{run}:{frm}:{to}:{n}", "from": frm, "to": to, "kind": kind, "body": body, "at": 1000.0 + n + len(run)}


def row(run: str, n: int, frm: str, ts: str, kw: float) -> dict:
    said = {"report": {"entity_id": frm.upper(), "timestamp": ts, "reported_p_net_kw": kw, "text": "runs its own schedule"}}
    return message(run, n, frm, "aggregator", "community.report", said, f"report:{ts[:10]}")


def evening(run: str, tag: str, first: str = "utility") -> tuple[dict, list[dict]]:
    """A small evening as one run kept it: its summary and its bus record. `tag` is what this run's ids of a contract and a gap end in, and
    `first` the buyer whose order arrived first: the sale both orders share goes by that order's id, and calls its members with its need."""
    sale, gap, txn = ORDER[first], f"gap-2025-01-28T19:00-{tag}", {b: f"order-{o}-{tag}ab12" for b, o in ORDER.items()}
    need = {"event_id": sale, "buyer": f"{first} (stand-in)", "window_start": "2025-01-28 18:00", "slots": [{"id": 0, "kw_requested": ASKS[first], "price": 2.04}],
            "pool": {"orders": 2, "kw": {"0": 14.4}}}
    reading = {"context": {"action": "on_status", "transactionId": f"community-{sale}", "messageId": f"reading-{run}", "timestamp": "2026-11-22T08:00:30Z", "sentWall": 1030.0 + len(run)},
               "message": {"performance": {"contract_id": f"{sale}:home-01", "slot_id": 2, "usage_kw": 1.25}}, "signer": f"key of home-01 in {run}", "sig": f"reading signed in {run}"}
    events = [message(run, 1, "community", "home-01", "beckn.discover", {"intent": {"need": need}}, f"community-{sale}"),
              *[message(run, 2 + i, "community", b, "beckn.init", {"contract": {"id": f"contract-{o}", "event_id": o, "community_event": sale, "capacityOffered": {"1": 2.43}}}, txn[b])
                for i, (b, o) in enumerate(ORDER.items())],
              message(run, 4, "utility", "community", "beckn.on_init", {"contract": {"id": f"contract-{ORDER['utility']}", "status": "DRAFT"}}, txn["utility"]),
              message(run, 5, "community", "utility", "beckn.confirm", {"contract": {"id": f"contract-{ORDER['utility']}", "status": "DRAFT"}}, txn["utility"]),
              message(run, 6, "community", "home-02", "beckn.rt_ask", {"ask": {"id": gap, "start": Q[0], "end": Q[3], "price_usd_per_kwh": 2.04, "kind": "gap"}}, gap),
              message(run, 7, "home-02", "community", "beckn.rt_answer", {"answer": {"id": gap, "kw": 3.01}}, gap),
              message(run, 8, "community", "home-02", "beckn.rt_dispatch", {"dispatch": {"id": gap, "steps": {Q[0]: 2.221, Q[1]: 2.24}, "kind": "gap", "event_id": sale}}, gap),
              message(run, 9, "home-01", "community", "beckn.on_status", {"batch": [reading]}, "readings-home-01"),
              message(run, 10, "utility", "community", "beckn.on_status", {"settlement": {"paid_usd": 12.9933, "components": [{"id": 1, "pay": 0.5836}]}}, txn["utility"]),
              *[row(run, 11 + k, "site-pv-01", Q[k], -5.0 - k) for k in range(3)], row(run, 20, "community", Q[0], 31.5)]
    events += [{"event": "ack", "message_id": e["message_id"], "by": e["to"], "status": "processed", "note": {}, "at": e["at"] + 0.2} for e in events]
    result = {"seller_usd": 20.7893, "split": {"pool": 14.573, "per_home": {"home-01": 7.0, "home-02": 7.573}}, "components": [{"id": 1, "pay": len(run)}],
              "by_buyer": {b: {"order": o, "paid_usd": 1.4437 * ASKS[b]} for b, o in ORDER.items()}}
    sold = {"phase": "done", "kw_requested": [ASKS[first]], "offers": 2, "accepted": 2, "readings": 12, "readings_missing": {}, "capacity_offered_kw": {"0": 0.0, "1": 3.88}, "result": result}
    asked = {"id": "battery-2025-01-28", "to": "community", "sent": {"at": "2025-01-28 14:00", "wall": 1014.0 + len(run), "town": "accepted"}, "answer": {"taken": True, "rows": 40}}
    summary = {"run": "demo-run", "ended": "settled", "ports": {"bus": 51000 + len(run)}, "clock": {"steps": 144, "wall_s": 58.5 * len(run)},
               "community": {"now": "2025-01-28 21:45", "roster": 2, "events": {sale: sold}, "reputation": {"home-01": 1.058, "home-02": 1.06}},
               "aggregator": {"pubkey": f"key of the aggregator in {run}", "now": "2025-01-28 21:45", "communities": {"site-pv-01": {"report_rows": 3, "last": Q[2]}}, "requests": [asked],
                              "flags": [{"community": "site-pv-01", "timestamp": Q[len(run) % 3], "what": "the same power 4 quarter hours running"}], "flagged": 3, "not_kept": {}}}
    return summary, events


def write(folder: Path, summary: dict, events: list[dict]) -> str:
    folder.mkdir()
    (folder / "summary.json").write_text(json.dumps(summary))
    with gzip.open(folder / "record.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"events": events, "next": len(events)}, f)
    return str(folder)


def find(events: list[dict], kind: str, frm: str) -> int:
    """Where the first message of this kind from this sender stands in a record."""
    return next(i for i, e in enumerate(events) if e.get("kind") == kind and e["from"] == frm)


@pytest.fixture
def runs(tmp_path, capsys):
    """Compares run A, the small evening, with run B: the same evening as another run kept it, after `change(summary, events)` has changed it.
    `first` is the buyer whose order came first in B, `first_a` in A. Gives back the exit code and the lines printed after the two folders' names."""
    def compared(change=lambda summary, events: None, first: str = "utility", first_a: str = "utility") -> tuple[int, list[str]]:
        a, b = evening("a", "0de923", first_a), evening("other", "740c2e", first)
        change(*b)
        code = compare.main(write(tmp_path / f"a{len(list(tmp_path.iterdir()))}", *a), write(tmp_path / f"b{len(list(tmp_path.iterdir()))}", *b))
        return code, capsys.readouterr().out.splitlines()[2:]
    return compared


def test_two_runs_that_differ_only_in_what_belongs_to_a_run_are_the_same_evening(runs):
    def another_run(summary, events):
        events.insert(6, events.pop(find(events, "community.report", "site-pv-01")))     # a report row arrives between the desk's messages: another pair, another order
        events.insert(2, events.pop(find(events, "beckn.on_status", "home-01")))         # and a member's readings before the buyers' contracts
        events.append(copy.deepcopy(events[find(events, "community.report", "community")]))      # a report row is sent a second time
        result = next(iter(summary["community"]["events"].values()))["result"]
        result["by_buyer"] = dict(reversed(result["by_buyer"].items()))
        result["seller_usd"] += 1e-13                              # the same sum, added up in another order
    assert runs(another_run) == (0, [SIZE, "the same evening"])


def test_a_pooled_sale_that_goes_by_the_other_buyers_order_is_the_same_evening_and_a_note_says_so(runs):
    note = ("note: the sale goes by the order flex-need-2025-01-28 in A and grid-operator-need-2025-01-28 in B, whichever buyer answered first: both are read as "
            "flex-need-2025-01-28, and what the call to the members says of that one order (need.buyer, each slot's kw_requested) is not compared")
    assert runs(first="grid-operator") == (0, [SIZE.replace("32 | 32", "31 | 31"), note, "the same evening"])        # one figure less each: what the one order asks

    def another_pool(summary, events):
        events[find(events, "beckn.discover", "community")]["body"]["message"]["intent"]["need"]["pool"]["kw"]["0"] = 12.0
        events[find(events, "beckn.init", "community")]["body"]["message"]["contract"]["capacityOffered"]["1"] = 2.5
    code, lines = runs(another_pool, first="grid-operator")                              # what all the orders ask together, and each order's own contract, are still compared
    assert code == 1 and lines[2:] == ["messages of kind beckn.discover: 1 lines differ", "  community -> home-01: message.intent.need.pool.kw.0: 14.4 | 12.0",
                                       "messages of kind beckn.init: 1 lines differ", "  community -> utility: message.contract.capacityOffered.1: 2.43 | 2.5"]

    def another_ask(summary, events):
        events[find(events, "beckn.discover", "community")]["body"]["message"]["intent"]["need"]["slots"][0]["kw_requested"] = 8.0
    code, lines = runs(another_ask)                                                       # both sales go by the same order: what that order asks is compared too
    assert code == 1 and lines == [SIZE, "messages of kind beckn.discover: 1 lines differ", "  community -> home-01: message.intent.need.slots.0.kw_requested: 9.0 | 8.0"]

    def another_phase(summary, events):
        next(iter(summary["community"]["events"].values()))["phase"] = "settling"
    code, lines = runs(another_phase, first="grid-operator", first_a="grid-operator")     # and the sale keeps the id both runs know it by, here the grid operator's
    assert code == 1 and lines == [SIZE, "the outcome: 1 lines differ", '  community.events.grid-operator-need-2025-01-28.phase: "done" | "settling"']


def test_what_belongs_to_a_run_is_taken_out_of_a_body_and_nothing_else():
    body = {"context": {"action": "rt_ask", "transactionId": "order-flex-need-2025-01-28-6b26ad1380", "messageId": "m", "timestamp": "2026-11-22T08:44:39Z", "sentWall": 1.5, "ttl": "PT900S"},
            "message": {"ask": {"id": "gap-2025-01-28T19:00-0de923", "contract": "call-2025-01-28-1900-emergency-1a2b3c:home-01"}, "report": {"timestamp": "2025-01-28 19:00"},
                        "batch": [{"context": {"messageId": "r", "sentWall": 2.5, "action": "on_status"}, "message": {"usage_kw": 1.25}, "signer": "k", "sig": "s"}],
                        "contract": {"id": "contract-flex-need-2025-01-28"}, "why": "order-of-magnitude more, see gap-notes", "sentWall": 3.5}, "signer": "k", "sig": "s"}
    assert compare.strip(body) == {"context": {"action": "rt_ask", "transactionId": "order-flex-need-2025-01-28", "ttl": "PT900S"},
                                   "message": {"ask": {"id": "gap-2025-01-28T19:00", "contract": "call-2025-01-28-1900-emergency:home-01"}, "report": {"timestamp": "2025-01-28 19:00"},
                                               "batch": [{"context": {"action": "on_status"}, "message": {"usage_kw": 1.25}}],
                                               "contract": {"id": "contract-flex-need-2025-01-28"}, "why": "order-of-magnitude more, see gap-notes", "sentWall": 3.5}}


def test_money_that_differs_is_printed_leaf_by_leaf_with_both_runs_figures(runs):
    def paid_less(summary, events):
        result = summary["community"]["events"][ORDER["utility"]]["result"]
        result["seller_usd"], result["split"]["per_home"]["home-02"] = 20.8394, 7.6231
        summary["ended"] = "settled, with an alarm standing"
        summary["aggregator"]["requests"][0]["answer"]["rows"] = 36
        del summary["community"]["reputation"]["home-02"]
    sale = f"community.events.{ORDER['utility']}.result"
    assert runs(paid_less) == (1, [SIZE.replace("32 | 32", "32 | 31"), "the outcome: 5 lines differ", "  aggregator.requests.0.answer.rows: 40 | 36", f"  {sale}.seller_usd: 20.7893 | 20.8394",
                                   f"  {sale}.split.per_home.home-02: 7.573 | 7.6231", "  community.reputation.home-02: 1.06 | nothing", '  ended: "settled" | "settled, with an alarm standing"'])


def test_a_message_that_says_something_else_is_set_beside_the_one_in_its_place_and_one_that_is_missing_is_named(runs):
    def other_words(summary, events):
        events[find(events, "beckn.rt_dispatch", "community")]["body"]["message"]["dispatch"]["steps"][Q[0]] = 2.5       # the desk dispatched another amount
        events[find(events, "beckn.on_status", "home-01")]["body"]["message"]["batch"][0]["message"]["performance"]["usage_kw"] = 1.3      # a signed reading inside a batch reads otherwise
        del events[find(events, "beckn.on_status", "utility")]                                                           # the buyer's settlement never came
        events.append(message("other", 30, "utility", "community", "beckn.rt_call", {"call": {"id": "call-2025-01-28-1900-emergency-9f8e7d", "kw": 20.0}}, "alert"))
    code, lines = runs(other_words)
    assert code == 1 and lines[1:] == [
        "messages of kind beckn.rt_dispatch: 1 lines differ", f"  community -> home-02: message.dispatch.steps.{Q[0]}: 2.221 | 2.5",
        "messages of kind beckn.on_status: 2 lines differ", "  home-01 -> community: message.batch.0.message.performance.usage_kw: 1.25 | 1.3",
        '  utility -> community, only in A: {"context":{"action":"on_status","bapId":"community","bppId":"utility","transactionId":"order-flex-need-2025-01-28","ttl":"PT900S"},'
        '"message":{"settlement":{"components":[{"id":1,"pay":0.5836}],"paid_... (215 characters)',       # a body is cut at 200 characters
        "messages of kind beckn.rt_call: 1 lines differ", '  utility -> community, only in B: {"context":{"action":"rt_call","bapId":"community","bppId":"utility","transactionId":'
        '"alert","ttl":"PT900S"},"message":{"call":{"id":"call-2025-01-28-1900-emergency","kw":20.0}}}']


def test_the_same_messages_between_a_pair_in_another_order_are_another_evening(runs):
    def confirmed_first(summary, events):
        i, j = find(events, "beckn.init", "community"), find(events, "beckn.confirm", "community")
        events[i], events[j] = events[j], events[i]                # the contract is confirmed to the buyer before its terms went
    code, lines = runs(confirmed_first)
    assert code == 1 and lines[1] == "messages in another order: 1 lines differ" and len(lines) == 3
    assert lines[2].startswith("  community -> utility: message 1 of 2 is beckn.init {") and " | beckn.confirm {" in lines[2]


def test_report_rows_are_compared_by_their_quarter_hour_and_a_run_that_went_on_longer_shows_its_span(runs):
    def ran_on(summary, events):
        events[find(events, "community.report", "site-pv-01") + 1]["body"]["message"]["report"]["reported_p_net_kw"] = -4.0      # site-pv-01 at 19:15
        events.extend(row("other", 40 + k, "site-pv-01", Q[k], -9.0) for k in (3, 4, 5))
        del events[find(events, "community.report", "community")]                    # the community's own row for 19:00
    assert runs(ran_on) == (1, [SIZE.replace("4 | 4", "4 | 6"), "report rows: 3 lines differ", f"  site-pv-01 -> aggregator {Q[1]}: reported_p_net_kw: -6.0 | -4.0",
                                f"  community -> aggregator, only in A: 1 rows, {Q[0]} to {Q[0]}", f"  site-pv-01 -> aggregator, only in B: 3 rows, {Q[3]} to {Q[5]}"])


def test_twenty_lines_of_each_kind_are_printed_and_the_rest_counted(runs):
    def many(summary, events):
        summary["community"]["reputation"] = {f"home-{k:02d}": 0.9 for k in range(1, 26)}
    code, lines = runs(many)
    assert code == 1 and lines[1] == "the outcome: 25 lines differ" and lines[-1] == "  ... and 5 more" and len(lines) == 2 + 20 + 1
    assert lines[2:5] == ["  community.reputation.home-01: 1.058 | 0.9", "  community.reputation.home-02: 1.06 | 0.9", "  community.reputation.home-03: nothing | 0.9"]


def test_the_command_says_so_when_a_folder_has_no_record_and_answers_through_the_runners_own_door(tmp_path, capsys, monkeypatch):
    a, b = write(tmp_path / "a", *evening("a", "0de923")), write(tmp_path / "b", *evening("b", "740c2e"))
    monkeypatch.setattr(sys, "argv", ["demo.runner", "compare", a, b])
    assert runner() == 0 and capsys.readouterr().out.splitlines() == [f"A is {a}", f"B is {b}", SIZE, "the same evening"]
    (tmp_path / "b" / "record.json.gz").unlink()
    assert runner() == 2
    said = capsys.readouterr()
    assert said.out == "" and said.err.startswith("cannot compare: FileNotFoundError") and "record.json.gz" in said.err

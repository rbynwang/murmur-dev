"""Are two finished runs the same evening?

  python -m demo.runner compare RUN_A RUN_B

RUN_A and RUN_B are run folders, each with the summary.json and the record.json.gz its `evening` command wrote. Two runs of one
configuration play the same evening, whatever their pace and whether or not their clocks leaped. This says so and exits 0, or prints
what differs, the first 20 lines of each kind, and exits 1 (2 when a folder cannot be read).

What is compared:

  the outcome      how each run ended; the sale as the community holds it at the end (its phase, its offers, commitments and readings
                   by count, the capacity sold, the result with the money and each buyer's and each member's part), the members'
                   reputations and where its clock stood; the aggregator's view (each participant's rows by count and span, each
                   request with what was sent and what was answered, how many rows it flagged)
  the messages     every message the bus accepted that is no report row: between each sender and receiver the same messages of
                   each kind, as often, and in the same order
  the report rows  the same set of rows upward: sender, receiver, the row's own quarter hour and all it says. A row sent twice is
                   one row

What is left out, because it belongs to a run and not to the evening: wall times (a context's timestamp and sentWall, the wall time a
request went at), message ids, signatures and keys (every run makes its own keys), and the tag of its run that the id of an order's
contract, of a gap and of a call ends in.

Which of two messages between different pairs came first is not compared either, and three things follow from that order alone:
`result.components`, the table of whichever buyer settled last (each buyer's own table is compared with its settlement message); the
aggregator's last 200 flags, a window in the order they arrived (their count is compared); and the order a pooled sale goes by. A sale
that several buyers' orders share takes the id of the first of them to arrive, and calls its members with that order's need. Where
the two runs' sale goes by different orders, a note says so, the ids of that sale's orders are read as one name, and what belongs to
the one order is left out: in the call to the members its buyer and what it asks by half hour (`need.buyer`, each slot's
`kw_requested`; what all the orders ask together, `need.pool`, is compared), and `kw_requested` in the outcome.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable

SHOWN = 20                                                # lines printed of each kind of difference
REPORT = "community.report"
OF_THE_KEY = ("sig", "signer")                           # in any signed body, however deep: every run makes its own keys
OF_THE_SENDING = ("messageId", "timestamp", "sentWall")  # in a context: the id it went under and the wall time it was made
TAG = re.compile(r"\b((?:order|gap|call)-\S*?)-[0-9a-f]{6,16}(?=$|[\s:])")       # the id of an order's contract, a gap or a call: it ends in a digest of its sender's play
LEFT_OUT = re.compile(r"^aggregator\.(pubkey|flags)\b|\.sent\.wall$|\.result\.components\b")
CLOSE = 1e-9                                             # two numbers this close, beside their size, are the same number

Said = dict[tuple[str, str], list[tuple[str, str]]]      # sender and receiver -> their messages as (kind, body), in the order the bus accepted them
Rows = set[tuple[str, str, str, str]]                    # report rows: sender, receiver, the row's quarter hour, what it says


def load(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A run's summary, and every message its bus accepted, in the order it accepted them."""
    with gzip.open(run / "record.json.gz", "rt", encoding="utf-8") as f:
        events = json.load(f)["events"]
    return json.loads((run / "summary.json").read_text()), [e for e in events if e.get("event") == "accepted"]


def strip(x: Any, context: bool = False) -> Any:
    """A message body without what belongs to its run: signatures and keys at any depth, each context's message id and wall times, and
    the run's tag at the end of an id."""
    if isinstance(x, dict):
        gone = OF_THE_KEY + (OF_THE_SENDING if context else ())
        return {k: strip(v, k == "context") for k, v in x.items() if k not in gone}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return TAG.sub(r"\1", x) if isinstance(x, str) else x


def canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def flat(x: Any, path: str = "") -> dict[str, Any]:
    """Every leaf of a nested answer under its dotted path."""
    if isinstance(x, (dict, list)) and x:
        items = x.items() if isinstance(x, dict) else enumerate(x)
        return {p: v for k, child in items for p, v in flat(child, f"{path}.{k}" if path else str(k)).items()}
    return {path: x}


def same(a: Any, b: Any) -> bool:
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)      # noqa: E731
    if number(a) and number(b):
        return abs(a - b) <= CLOSE * max(1.0, abs(a), abs(b))
    return a == b


def leaves(a: Any, b: Any, lead: str = "") -> list[str]:
    """Each leaf two answers do not share, as `path: A's | B's`."""
    fa, fb = flat(a), flat(b)
    word = lambda f, p: json.dumps(f[p], ensure_ascii=False) if p in f else "nothing"      # noqa: E731
    return [f"{lead}{p}: {word(fa, p)} | {word(fb, p)}" for p in sorted(set(fa) | set(fb)) if p not in fa or p not in fb or not same(fa[p], fb[p])]


# ------------------------------------------------------------------ the order a pooled sale goes by
def orders(events: list[dict[str, Any]]) -> dict[str, str]:
    """Each order of a sale that several orders share -> one name for the sale: the first of its orders' ids in the alphabet. An order's
    contract names both ids (`event_id`, the order's own; `community_event`, the sale's), so the record says which orders share a sale."""
    shared: dict[str, set[str]] = {}
    for e in events:
        body = e.get("body")
        c = (body.get("message") or {}).get("contract") if isinstance(body, dict) else None
        if isinstance(c, dict) and isinstance(c.get("community_event"), str) and isinstance(c.get("event_id"), str):
            shared.setdefault(c["community_event"], set()).add(c["event_id"])
    return {o: min(group) for group in shared.values() if len(group) > 1 for o in group}


def renamer(names: dict[str, str]) -> Callable[[str], str]:
    """Text with each order's id read as its sale's one name, wherever it stands: alone, in a contract's id, in a transaction's."""
    if not names:
        return lambda text: text
    ids = re.compile("|".join(re.escape(o) for o in sorted(names, key=len, reverse=True)))
    return lambda text: ids.sub(lambda m: names[m.group(0)], text)


def sales(summary: dict[str, Any]) -> list[str]:
    events = (summary.get("community") or {}).get("events")
    return sorted(events) if isinstance(events, dict) else []


def without_its_order(body: Any) -> Any:
    """A call to a member without what belongs to the one order its sale goes by: the buyer, and what that order asks by half hour."""
    need = ((body.get("message") or {}).get("intent") or {}).get("need") if isinstance(body, dict) else None
    if isinstance(need, dict) and "pool" in need:
        need.pop("buyer", None)
        for slot in need.get("slots") or []:
            if isinstance(slot, dict):
                slot.pop("kw_requested", None)
    return body


# ------------------------------------------------------------------ what a run came to, and what it said
def outcome(summary: dict[str, Any], rename: Callable[[str], str], flipped: set[str]) -> dict[str, Any]:
    """What a run came to, without what belongs to the run."""
    kept = flat(json.loads(rename(json.dumps({"ended": summary.get("ended"), "community": summary.get("community"), "aggregator": summary.get("aggregator")}))))
    own = re.compile(r"^community\.events\.(%s)\.kw_requested\b" % "|".join(map(re.escape, sorted(flipped)))) if flipped else None
    return {p: v for p, v in kept.items() if not LEFT_OUT.search(p) and not (own and own.search(p))}


def told(events: list[dict[str, Any]], rename: Callable[[str], str], flipped: set[str]) -> tuple[Said, Rows]:
    """What a record says: between each sender and receiver the messages that are no report rows, and the report rows as a set."""
    said: Said = {}
    rows: Rows = set()
    for e in events:
        frm, to, kind, body = str(e.get("from")), str(e.get("to")), str(e.get("kind")), strip(e.get("body"))
        row = (body.get("message") or {}).get("report") if kind == REPORT and isinstance(body, dict) else None
        if isinstance(row, dict):
            rows.add((frm, to, str(row.get("timestamp")), canon({k: v for k, v in row.items() if k != "timestamp"})))
            continue
        text = rename(canon(body))
        if flipped and any(name in text for name in flipped):
            text = canon(without_its_order(json.loads(text)))
        said.setdefault((frm, to), []).append((kind, text))
    return said, rows


def unmatched(xs: list[Any], ys: list[Any]) -> list[Any]:
    """The items of xs that ys does not hold as often, in their order."""
    left, out = Counter(ys), []
    for x in xs:
        if left[x] > 0:
            left[x] -= 1
        else:
            out.append(x)
    return out


def cut(text: str, most: int = 200) -> str:
    return text if len(text) <= most else f"{text[:most]}... ({len(text)} characters)"


def message_lines(a: Said, b: Said) -> dict[str, list[str]]:
    """What the messages of two records do not share, by kind: a message of one run beside the message of the other that stands in its
    place, leaf by leaf; a message only one run has; and, where two runs sent the same messages between a pair, the first that came in
    another order."""
    out: dict[str, list[str]] = {}
    for pair in sorted(set(a) | set(b)):
        xa, xb, who = a.get(pair, []), b.get(pair, []), f"{pair[0]} -> {pair[1]}"
        only_a, only_b = unmatched(xa, xb), unmatched(xb, xa)
        if not only_a and not only_b:
            n = next((i for i, (x, y) in enumerate(zip(xa, xb)) if x != y), None)
            if n is not None:
                out.setdefault("messages in another order", []).append(f"{who}: message {n + 1} of {len(xa)} is {xa[n][0]} {cut(xa[n][1], 120)} | {xb[n][0]} {cut(xb[n][1], 120)}")
            continue
        for kind in sorted({k for k, _ in only_a + only_b}):
            lines = out.setdefault(f"messages of kind {kind}", [])
            for x, y in zip_longest([m for k, m in only_a if k == kind], [m for k, m in only_b if k == kind]):
                if x is None or y is None:
                    lines.append(f"{who}, only in {'B' if x is None else 'A'}: {cut(x or y)}")
                else:
                    lines += leaves(json.loads(x), json.loads(y), f"{who}: ")
    return out


def row_lines(a: Rows, b: Rows) -> list[str]:
    """What the report rows of two records do not share: a quarter hour both reported in other words, leaf by leaf; and for each sender the
    quarter hours only one run reported, by count and span."""
    only_a, only_b = {r[:3]: r[3] for r in a - b}, {r[:3]: r[3] for r in b - a}
    lines = [d for key in sorted(set(only_a) & set(only_b)) for d in leaves(json.loads(only_a[key]), json.loads(only_b[key]), f"{key[0]} -> {key[1]} {key[2]}: ")]
    for name, mine, other in (("A", only_a, only_b), ("B", only_b, only_a)):
        alone = sorted(k for k in mine if k not in other)
        for frm, to in sorted({k[:2] for k in alone}):
            times = [k[2] for k in alone if k[:2] == (frm, to)]
            lines.append(f"{frm} -> {to}, only in {name}: {len(times)} rows, {times[0]} to {times[-1]}")
    return lines


def differences(run_a: Path, run_b: Path) -> tuple[dict[str, list[str]], list[str]]:
    """What two runs do not share, as lines under the kind of difference; and what there is to say before them: how much was compared,
    and each sale that goes by another order in the two runs."""
    (sum_a, events_a), (sum_b, events_b) = load(run_a), load(run_b)
    names = {**orders(events_a), **orders(events_b)}
    by_a, by_b = ({names.get(s, s): s for s in sales(summary)} for summary in (sum_a, sum_b))      # each sale's one name -> the order it goes by in this run
    flips = [(by_a[name], by_b[name]) for name in sorted(set(by_a) & set(by_b)) if by_a[name] != by_b[name]]
    flipped = {names[a] for a, _ in flips}
    rename = renamer({o: name for o, name in names.items() if name in flipped})                     # a sale that goes by the same order in both runs keeps its ids
    (said_a, rows_a), (said_b, rows_b) = told(events_a, rename, flipped), told(events_b, rename, flipped)
    out_a, out_b = outcome(sum_a, rename, flipped), outcome(sum_b, rename, flipped)
    found = {"the outcome": leaves(out_a, out_b), **message_lines(said_a, said_b), "report rows": row_lines(rows_a, rows_b)}
    count = lambda said: sum(len(v) for v in said.values())      # noqa: E731
    notes = [f"compared, A | B: {len(out_a)} | {len(out_b)} figures of the outcome, {count(said_a)} | {count(said_b)} messages, {len(rows_a)} | {len(rows_b)} report rows"]
    notes += [f"note: the sale goes by the order {a} in A and {b} in B, whichever buyer answered first: both are read as {names[a]}, and what the call to the members says "
              "of that one order (need.buyer, each slot's kw_requested) is not compared" for a, b in flips]
    return {k: v for k, v in found.items() if v}, notes


def main(run_a: str, run_b: str) -> int:
    try:
        found, notes = differences(Path(run_a), Path(run_b))
    except (OSError, ValueError, KeyError) as exc:        # a folder without its summary or its record, or one that can't be read
        print(f"cannot compare: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print("\n".join([f"A is {run_a}", f"B is {run_b}", *notes]))
    if not found:
        print("the same evening")
        return 0
    for kind, lines in found.items():
        print(f"{kind}: {len(lines)} lines differ")
        for line in lines[:SHOWN]:
            print(f"  {line}")
        if len(lines) > SHOWN:
            print(f"  ... and {len(lines) - SHOWN} more")
    return 1

"""Who answers the aggregator in a recorded evening, and in which signed messages.

A recorded evening (demo/recordings/<set>/trace_engie_<date>.json.gz) shows every envelope the message network carried as terminal lines of its
steps: the envelope (`from=... to=... kind=...`), its context (`transactionId=...`) and its signature (`signer <key>... sig ...`). Each
participant that answers the aggregator does it in the same three signed messages:

  request   the aggregator's request, signed with the aggregator's key (kind community.request)
  answer    the participant's answer, signed with its own key (kind community.answer)
  report    one signed report row a quarter hour, in the layout every ENGIE participant sends, kept by the aggregator's agent

A request the test planted to be refused is left out (its transaction is named `planted-...`).
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

RECORDED = Path(__file__).resolve().parents[3] / "demo" / "recordings" / "evening_2025-01-28" / "trace_engie_2025-01-28.json.gz"
AGGREGATOR, COMMUNITY = "aggregator", "coordinator"
ENVELOPE = re.compile(r"from=(\S+)\s+to=(\S+)\s+kind=(\S+)")
TRANSACTION = re.compile(r"transactionId=(\S+)")
SIGNER = re.compile(r"signer ([0-9a-f]+)")
NUMBER = r"([\d,]+)"
SITE_ROWS = {"sent": re.compile(r"signed rows sent: " + NUMBER), "kept": re.compile(r"kept by the aggregator's agent: " + NUMBER),
             "flagged": re.compile(r"flagged: " + NUMBER)}
COMMUNITY_ROWS = {"sent": re.compile(r"sent upward, each signed: " + NUMBER), "kept": re.compile(r"held by the aggregator's agent: " + NUMBER),
                  "flagged": re.compile(r"flagged by its three row rules[^:]*: " + NUMBER), "not_kept": re.compile(r"messages it did not keep[^:]*: " + NUMBER)}


def load(path: Path = RECORDED) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def kind_of(node: str) -> str:
    return "community" if node == COMMUNITY else "solar-and-battery plant" if node.startswith("site-pv-") else \
        "data center" if node.startswith("site-dc-") else "other"


def _found(pattern: re.Pattern, text: str) -> int | None:
    m = pattern.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def envelopes(trace: dict) -> list[dict]:
    """Every envelope of the evening: sender, addressee, kind, transaction, signer, and the step that shows it."""
    out = []
    for s in trace["steps"]:
        lines = [str(t.get("text")) for t in s.get("terminal", [])]
        env = next((ENVELOPE.search(x) for x in lines if ENVELOPE.search(x)), None)
        if env:
            tx = next((TRANSACTION.search(x).group(1) for x in lines if TRANSACTION.search(x)), None)
            sig = next((SIGNER.search(x).group(1) for x in lines if SIGNER.search(x)), None)
            out.append({"from": env.group(1), "to": env.group(2), "kind": env.group(3), "transaction": tx, "signer": sig, "step": s["id"], "at": s["sim_time"]})
    return out


def _report(trace: dict, node: str) -> dict:
    """The signed report rows a participant sent upward, and what the aggregator's agent kept of them."""
    for s in trace["steps"]:
        text = " ".join(str(t.get("text")) for t in s.get("terminal", []))
        if node == COMMUNITY and s["from"] == AGGREGATOR and "report upward" in s["title"]:
            return {k: _found(p, text) for k, p in COMMUNITY_ROWS.items()} | {"step": s["id"]}
        if node != COMMUNITY and s["from"] == node and s["to"] == AGGREGATOR and "reports upward" in s["title"]:
            return {k: _found(p, text) for k, p in SITE_ROWS.items()} | {"step": s["id"]}
    return {}


def exchanges(trace: dict) -> list[dict]:
    """For each participant the aggregator asks: its request, its answer and its report, in the order the requests went out."""
    env = [e for e in envelopes(trace) if not str(e["transaction"]).startswith("planted-")]
    asked = [e for e in env if e["from"] == AGGREGATOR and e["kind"] == "community.request"]
    rows = []
    for q in asked:
        node = q["to"]
        a = next((e for e in env if e["from"] == node and e["to"] == AGGREGATOR and e["transaction"] == q["transaction"]), None)
        rows.append({"participant": node, "kind": kind_of(node), "request": {k: q[k] for k in ("kind", "signer", "step", "at")},
                     "answer": {k: a[k] for k in ("kind", "signer", "step", "at")} if a else None, "report": _report(trace, node)})
    return rows


def verdict(rows: list[dict]) -> dict:
    """Whether every participant answered the same aggregator in the same three signed messages."""
    answered = [r for r in rows if r["answer"]]
    return {"participants": len(rows), "kinds": sorted({r["kind"] for r in rows}), "answered": len(answered),
            "request_kinds": sorted({r["request"]["kind"] for r in rows}), "answer_kinds": sorted({r["answer"]["kind"] for r in answered}),
            "requests_signed_by_one_key": len({r["request"]["signer"] for r in rows}) == 1 and None not in {r["request"]["signer"] for r in rows},
            "answers_signed_by_their_own_keys": len({r["answer"]["signer"] for r in answered}) == len(answered)
                                                and not {r["answer"]["signer"] for r in answered} & {r["request"]["signer"] for r in rows},
            "reports_sent_and_kept": all(r["report"].get("sent") and r["report"].get("kept") and not r["report"].get("flagged")
                                         and not r["report"].get("not_kept") for r in rows)}

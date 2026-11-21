"""Step 9: after a sale the node reports what happened. Code writes the facts; the model words them for the person; numbers in its words
that aren't in the facts are flagged. The labelled answer goes up to the community agent.
"""
from __future__ import annotations

from typing import Any

from murmur.node import note_words

SHORT_SHARE = 0.02      # measured delivery this far under what was sold, and the person is told
SYSTEM = ("You write a short report for the owner or manager of a home or building after a power sale. Use only the facts given, and copy each number as it is. "
          "Say what was owed, what was done and whether anything went wrong. Two short sentences, in plain words.")
TOOL = {"type": "function", "function": {
    "name": "file_report", "description": "Files the report.",
    "parameters": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string", "description": "two short sentences"}}}}}


def facts(agent: Any, sale: dict[str, Any], ts: str) -> list[dict[str, str]]:
    """What the node knows at the end of the sale, each fact with its source."""
    tel = agent.sim.tel or {}
    word = getattr(agent, "word", "home")
    out = [{"label": "records", "text": f'The sale ran {sale["start"][11:16]} to {sale["end"][11:16]} and the {word} owed {sale["owed_kw"]:.1f} kW.'}]
    for c in agent.log_calls:
        out.append({"label": "records", "text": f'{c["target"]}: {c["status"]}, {c["expected_kw"]:.2f} kW expected.' + (f' {c["why"]}' if c["why"] else "")})
    if agent.sim.E > 0 and "set_battery" in agent.shelf:
        out.append({"label": "measured", "text": f'Battery at {tel.get("soc_pct", 0):.0f}% at {ts[11:16]}.'})
    if hasattr(agent, "delivered"):                          # what the meter says of the sale: at its end the last plan has no steps left to fall short in
        n, fmt = numbers(agent, sale), agent.kw_text
        out.append({"label": "measured", "text": f'The {word} sold {fmt(n["sold_kwh"])} kWh, and the meter shows {fmt(max(0.0, n["delivered_kwh"]))} kWh delivered, {fmt(n["short_kwh"])} kWh short.'})
        out.append({"label": "measured", "text": agent.delivered(sale)})
    for w in agent.guard.wishes:
        out.append({"label": "human", "text": f'The owner asked: {w["wish"].replace("_", " ")}.'})
    last = (getattr(agent, "reports", None) or [{}])[-1].get("ts") or ""
    for m in getattr(agent, "told", ()):              # what the owner or manager was told since the last report
        if last < m["ts"] <= ts:
            out.append({"label": "records", "text": f'Told the {m["to"]}: {m["text"]}'})
    return out


def write(agent: Any, sale: dict[str, Any], ts: str) -> dict[str, Any]:
    fs = facts(agent, sale, ts)
    a = agent.brain.ask(SYSTEM, [TOOL], "Facts:\n" + "\n".join(f'- {x["text"]}' for x in fs))      # one prompt for both, or a building's report queues as an exception
    said = next((c["args"].get("summary") for c in a["calls"] if c["name"] == "file_report" and isinstance(c.get("args"), dict)), None)
    text = (said if isinstance(said, str) else "") or a["text"]       # junk in the tool's place isn't a report, and the sale's report is written once
    by = "model" if text else "code"                         # the model's plain text counts as the model's: a report that comes back with no tool call is still the model's words
    if not text:
        text = " ".join(x["text"] for x in fs[:2])           # no answer from the model: the facts themselves are the report
    return {"node": agent.name, "ts": ts, "summary": str(text)[:400], "facts": fs, "ms": a["ms"], "by": by}


def fell_short(agent: Any, sale: dict[str, Any], ts: str) -> str | None:
    """The person hears, in plain words, when what the meter shows is more than 2% under what the node sold. One message per sale: this runs in step 9, which
    runs once. It goes on the person's own channel and into the report, and never on the market's wire."""
    n = numbers(agent, sale)
    if n["sold_kwh"] <= 0 or n["delivered_kwh"] >= (1 - SHORT_SHARE) * n["sold_kwh"]:
        return None
    fmt = agent.kw_text
    gave = f'the meter shows {fmt(n["delivered_kwh"])} kWh delivered, {fmt(n["short_kwh"])} kWh less' if n["delivered_kwh"] > 0 else "the meter shows none of it delivered"
    text = f'I sold {fmt(n["sold_kwh"])} kWh {note_words.when_of(sale["start"], ts)} and {gave}. Only what the meter shows is paid.'
    agent.tell(text, "delivery", ts)
    return text


def numbers(agent: Any, sale: dict[str, Any]) -> dict[str, float]:
    """The sale in numbers, from the node's own meter against its own day without the sale. What the market hears of step 9, and what the person's message
    says. sold: what the node owed, its sale and any dispatch on top. delivered: what its meter shows it gave, net, a step over making up for a step under."""
    rows = [t for t in agent.sim.recent.values() if sale["start"] <= t["ts"] < sale["end"]]
    sold = sum(sale["by_ts"].values()) * 0.25
    delivered = sum(t["grid_kw"] - t["grid_cf_kw"] for t in rows) * 0.25
    return {"owed_kw": round(float(sale["owed_kw"]), 3), "sold_kwh": round(sold, 3), "delivered_kwh": round(delivered, 3), "short_kwh": round(max(0.0, sold - delivered), 3)}


def send(agent: Any, rep: dict[str, Any], sale: dict[str, Any]) -> dict[str, Any]:
    """The labelled answer goes up. A node with no market side, or a message that can't go, keeps its report: the sale is over and nothing waits on this.
    Only the numbers go: the summary, what was told and what the person asked stay on the node, on its log and in its own list."""
    desk = agent.ctx.desk
    up = {"sale": sale["start"], "ts": rep["ts"], **numbers(agent, sale)}
    agent.ctx.log.add("report", ts=rep["ts"], sale=sale["start"], by=rep["by"], summary=rep["summary"], facts=rep["facts"])
    try:
        out = desk.report(up) if hasattr(desk, "report") else {"sent": False}
    except Exception as exc:
        out = {"sent": False, "why": type(exc).__name__}
    rep["sent"] = out.get("sent") is not False      # a transport may answer with nothing: only a refusal means it didn't go
    agent.ctx.log.add("report_sent", ts=rep["ts"], sale=sale["start"], sent=rep["sent"], by=rep["by"], facts=len(rep["facts"]))
    return rep

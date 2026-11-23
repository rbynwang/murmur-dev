"""The steps of a followed node's record rows: steps(sh, node, rows, wall), and flush(sh, node, ts, wall) for rows still waiting.

A row is the hosts' record door's ({n, kind, node, ts, step, ...}). Rows come in the order the node wrote them. A row without a time
(a model's turn, a device call's start and end) takes the time of the node's next row that has one. A step of the agent is shown when
its closing row is read: a "step" row of the same step and time with state "done", which brackets every row the step wrote. What a
node writes outside a step (the receipt of its offer and of its contract, a note's reading, what it told its person) is shown at once.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .. import names as N
from .fmt import J, T, n2
from .lines_node import answer_of, driver_lines, guard_lines, io_lines, model_lines, receipt_lines, report_lines, told_line
from .shape import Row, Shaping, Step
from .words_node import ROWS

Rec = dict[str, Any]
NOTE = "You read a note"                  # how the note reader's prompt begins


def side_beat(sh: Shaping, node: str, row: Row, home: str, building: str) -> Row:
    """A Row in the beat of the node's side: a home's or a building's."""
    return replace(row, beat=home if N.is_home(sh.name(node)) else building)


def words(sh: Shaping, node: str) -> dict[str, str]:
    return {"name": N.name_of(sh.name(node)), "Name": N.name_of(sh.name(node), start=True)}


def by(r: Rec) -> str:
    return "The receipt says the model wasn't asked." if str(r.get("by") or "").startswith("rule") else f"By {r.get('by')}."


def steps(sh: Shaping, node: str, rows: list[Rec], wall: float) -> list[Step]:
    """The steps a node's new rows make, in order. Rows with no time wait for the next that has one."""
    st = sh.nodes.setdefault(node, {"waiting": [], "open": {}, "io": []})
    out: list[Step] = []
    for r in rows:
        if not r.get("ts"):
            st["waiting"].append(r)
            continue
        for w in st["waiting"] + [r]:
            out += sh.shaped(ROWS["note_decision"], w, sh.tq(r["ts"]), wall, take, sh, node, st, {**w, "ts": r["ts"]}, wall,
                             kind=f"row {w.get('kind')}", node=node)
        st["waiting"] = []
    return out


def flush(sh: Shaping, node: str, ts: str, wall: float) -> list[Step]:
    """Rows that waited too long for a time take the clock's: none is lost."""
    st = sh.nodes.get(node)
    if not st or not st["waiting"]:
        return []
    waiting, st["waiting"] = st["waiting"], []
    return [s for w in waiting for s in sh.shaped(ROWS["note_decision"], w, sh.tq(ts), wall, take, sh, node, st, {**w, "ts": ts}, wall,
                                                    kind=f"row {w.get('kind')}", node=node)]


def take(sh: Shaping, node: str, st: dict[str, Any], r: Rec, wall: float) -> list[Step]:
    kind = r.get("kind")
    if kind == "step":
        key = (r.get("step"), r.get("ts"))
        if r.get("state") == "entered":
            st["open"][key] = []
            return []
        inside = st["open"].pop(key, [])
        return bracket(sh, node, st, str(r.get("step") or ""), inside, r, wall)
    if st["open"]:
        st["open"][list(st["open"])[-1]].append(r)
        return []
    return loose(sh, node, r, wall)


def bracket(sh: Shaping, node: str, st: dict[str, Any], name: str, rows: list[Rec], end: Rec, wall: float) -> list[Step]:
    """One step of the agent, read whole."""
    tq, w = sh.tq(end["ts"]), words(sh, node)
    if name[:1] in "1234":
        st["io"] += [x for x in rows if x.get("kind") == "step_io"]
        if name[:1] != "4":
            return []
        io, st["io"] = st["io"], []
        learn(sh, node, io)
        row = ROWS["safe"] if N.is_home(sh.name(node)) else replace(ROWS["safe"], beat="bld-offer", key=False, say=False)
        return [sh.step(row, tq, wall, frm=node, node=node, lines=io_lines(io), **w)]
    acts = [x for x in rows if x.get("kind") == "act"]
    receipt = next((x for x in rows if x.get("kind") == "receipt"), None) or {}
    if name.startswith("7"):
        opening = side_beat(sh, node, ROWS["opening"], "watch-home", "watch-bld")
        facts = " ".join(str(f.get("says") or "") for f in receipt.get("facts") or [])
        return [sh.step(opening, tq, wall, frm=node, node=node, facts=facts, by=by(receipt), lines=receipt_lines(receipt), **w)] + \
            calls(sh, node, acts, opening.beat, tq, wall)
    if name.startswith("8"):
        chose, asked = receipt.get("chose") or {}, receipt.get("asked") or {}
        opens = ", ".join(str((asked.get("letters") or {}).get(x, x)) for x in chose.get("open") or []) or "no new device call"
        left = n2(chose.get("left_kw") or 0)
        beat = "exc-code" if acts else "exc-model"
        say = {"changed": str(asked.get("what_changed") or "a change").rstrip("."), "opens": opens, "left": left, "by": by(receipt)}
        out = [sh.step(replace(ROWS["exception"], beat=beat, say=not acts), tq, wall, frm=node, node=node, lines=receipt_lines(receipt),
                       values={"owed_kw": chose.get("left_kw")}, **say, **w)]
        if not acts:
            return out + [sh.step(ROWS["own_plan"], tq, wall, frm=node, node=node, opens=opens, values={"owed_kw": chose.get("left_kw")},
                                  lines=[T("calc", f"code's plan: open {J(chose.get('open'))}, let go {J(chose.get('release'))}, uncovered {left} kW")], **w)]
        return out + calls(sh, node, acts, beat, tq, wall, say_first=True)
    if name.startswith("9"):
        out = [sh.step(ROWS["report_model"], tq, wall, frm=node, to="model", node=node, answer=answer_of(m), lines=model_lines(m), **w)
               for m in rows if m.get("kind") == "model"]
        return out + [sh.step(ROWS["report"], tq, wall, frm=node, node=node, summary=str(x.get("summary") or ""), lines=report_lines(x), **w)
                      for x in rows if x.get("kind") == "report"]
    sh.count[f"step {name}"] += 1
    return []


def calls(sh: Shaping, node: str, acts: list[Rec], beat: str, tq: int, wall: float, say_first: bool = False) -> list[Step]:
    """Each device call of a step: the guard's step, then the seal and the driver's."""
    out: list[Step] = []
    for i, a in enumerate(acts):
        ans = a.get("answer") or {}
        out.append(sh.step(replace(ROWS["guard"], beat=beat, say=say_first and i == 0), tq, wall, frm=node, to=a.get("tool"), node=node,
                           tool=str(a.get("tool")), status=str(ans.get("status")), lines=guard_lines(a)))
        if (a.get("seal") or {}).get("seal"):
            out.append(sh.step(replace(ROWS["driver"], beat=beat), tq, wall, frm="guard", to=ans.get("target"), node=node,
                               target=str(ans.get("target") or (a.get("args") or {}).get("target")), lines=driver_lines(a)))
    return out


def loose(sh: Shaping, node: str, r: Rec, wall: float) -> list[Step]:
    """A row written outside any step."""
    kind, tq, w = r.get("kind"), sh.tq(r["ts"]), words(sh, node)
    if kind == "receipt":
        point = r.get("point")
        if point == "offer":
            kw = [float(x) for x in (r.get("chose") or {}).get("kw_per_half_hour") or []]
            safe = [float(x) for x in (r.get("rule") or {}).get("kw_per_half_hour") or []]
            sh.ev.node(sh.name(node), offered_kw=max(kw or [0]))
            row = side_beat(sh, node, ROWS["offer"], "home-model", "bld-offer")
            return [sh.step(row, tq, wall, frm=node, node=node, kw=n2(max(kw or [0])), by=by(r), lines=receipt_lines(r),
                            values={"offer_kw": kw, "safe_offer_kw": safe}, **w)]
        if point == "commitment":
            facts = " ".join(str(f.get("says") or "") for f in r.get("facts") or [])
            return [sh.step(ROWS["commitment"], tq, wall, frm=node, node=node, answer=str((r.get("chose") or {}).get("answer") or "none"),
                            facts=facts, by=by(r), lines=receipt_lines(r), **w)]
        return [sh.step(ROWS["note_receipt"], tq, wall, frm=node, node=node, reason=str(r.get("reason") or ""), lines=receipt_lines(r), **w)]
    if kind == "model":
        first = str(r.get("system") or "").startswith(NOTE) and sh.once(node, "note", r["ts"])
        return [sh.step(ROWS["note_model" if first else "note_more"], tq, wall, frm=node, to="model", node=node, answer=answer_of(r),
                        lines=model_lines(r), **w)]
    if kind == "decision" and (r.get("note_key") or r.get("why") == "owner's note"):
        return [sh.step(ROWS["note_decision"], tq, wall, frm=node, node=node, said=str(r.get("text") or "the note"),
                        lines=[T("calc", f"read as: {J(r.get('answer'), 300)}"), T("calc", f"shortlist: {J(r.get('shortlist'))}, took {r.get('ms')} ms")], **w)]
    if kind == "told":
        return [sh.step(ROWS["told"], tq, wall, frm=node, to=str(r.get("to") or "owner"), node=node, text=str(r.get("text") or ""),
                        lines=told_line(r), **w)]
    sh.count[f"row {kind}"] += 1
    return []


def learn(sh: Shaping, node: str, io: list[Rec]) -> None:
    """What steps 1 to 4 say of the node itself, for its card: what it is, its tools, its battery."""
    shelf = next(((x.get("inputs") or {}).get("shelf") for x in io if str(x.get("step")).startswith("3")), None)
    battery = next(((x.get("inputs") or {}).get("battery") or {} for x in io if str(x.get("step")).startswith("4")), {})
    sh.ev.node(sh.name(node), kind="home" if N.is_home(sh.name(node)) else "building", shelf=shelf,
               battery_kwh=battery.get("kwh") if isinstance(battery, dict) else None)

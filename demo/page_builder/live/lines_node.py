"""The terminal lines of a followed node's steps, made from its record's rows in the recorded evenings' own formats, which the cards
parse (replay/panels.py): a guard's call and verdict, the seal and the driver's write, the small model's prompt, tools, answer and
token counts, a receipt's question, rule, choice and reason, and what the node told its person.
"""
from __future__ import annotations

from typing import Any

from .fmt import J, T, hm, n2

GUARD_LINES = 14                     # of the guard's own source lines a call ran through, how many are shown


def receipt_lines(r: dict[str, Any]) -> list[dict[str, str]]:
    """A receipt: what was asked, the rule's plan, what was chosen, whether it is less than the rule, and why."""
    facts = "; ".join(str(f.get("says") or "") for f in r.get("facts") or [])
    return [T("calc", f"asked: {J(r.get('asked'), 300)}"), T("calc", f"the rule's plan: {J(r.get('rule'), 240)}"),
            T("calc", f"code chose: {J(r.get('chose'), 240)}"),
            T("guard", f"less than the rule: {r.get('less_than_rule')}. By: {r.get('by')}. Facts cited: {facts}"[:600]),
            T("calc", f"reason: {r.get('reason')}")]


def io_lines(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Steps 1 to 4: each step's inputs and outputs, one line a step."""
    return [T("calc", f"{r.get('step')}: in {J(r.get('inputs'), 220)}, out {J(r.get('outputs'), 220)}") for r in rows]


def guard_lines(a: dict[str, Any]) -> list[dict[str, str]]:
    """A device call as the guard saw it: the call, its checks, what it could see, the source lines it ran, and its verdict."""
    ans, pol, seen = a.get("answer") or {}, a.get("policy") or {}, a.get("inputs") or {}
    who = a.get("who") or {}
    src = a.get("guard_lines") or []
    out = [T("tool", f"{a.get('tool')}({J(a.get('args'))})  from {hm(a.get('start'))} to {hm(a.get('end'))}"),
           T("guard", f"run_call: arguments clean, {J(a.get('clean'))}"),
           T("guard", f"policy {a.get('policy_version')}: allow={pol.get('allow')} by rule {pol.get('rule')}, for the role \"{who.get('role')}\" via {who.get('via')}"),
           T("calc", f"what the guard could see: owed {seen.get('owed_kw')} kW, alarm {seen.get('alarm')}, stopped {seen.get('stopped')}, "
                     f"menu {J(seen.get('menu'), 160)}")]
    out += [T("guard", f"{x.get('file')}:{x.get('line')}  {str(x.get('text') or '').strip()}") for x in src[:GUARD_LINES]]
    if len(src) > GUARD_LINES:
        out.append(T("note", f"… {len(src) - GUARD_LINES} more lines of the guard ran"))
    say = f"guard says {ans.get('status')}: {ans.get('target')}, expected {n2(ans.get('expected_kw') or 0)} kW"
    return out + [T("guard", say + (f", because {ans['why']}" if ans.get("why") else ""))]


def driver_lines(a: dict[str, Any]) -> list[dict[str, str]]:
    """The seal on exactly what the guard passed, the driver's write, and its answer."""
    seal, cmd, drv = a.get("seal") or {}, a.get("command") or {}, a.get("driver") or {}
    return [T("sign", f"guard seals the command: nonce {seal.get('nonce')}  seal {seal.get('seal')}  (HMAC over the exact values, works once)"),
            T("write", f"SimulatedDriver.send  {cmd.get('kind')}  node={cmd.get('node')}  tool={cmd.get('tool')}  target={cmd.get('target')}  "
                       f"values={J(cmd.get('values'))}  {hm(cmd.get('start'))} to {hm(cmd.get('end'))}"),
            T("in", f"driver answers {drv.get('status')}" + (f": {drv['why']}" if drv.get("why") else ""))]


def model_lines(m: dict[str, Any]) -> list[dict[str, str]]:
    """The small model's turn: which model, the prompt, the tools it was offered, its answer, and what it cost."""
    ans, mod = m.get("answer") or {}, m.get("model") or {}
    calls = ans.get("calls") or []
    out = [T("in", f"model {mod.get('name')}, digest {mod.get('digest')}, options {J(m.get('options'))}, prompt version {m.get('prompt')}"),
           T("think", f"system: {m.get('system')}"), T("think", f"user: {m.get('text')}"),
           T("tool", f"tools offered: {', '.join(str(x) for x in m.get('tools') or [])}")]
    out += [T("tool", f"answer: {c.get('name')}({J(c.get('args'))})") for c in calls] or [T("tool", f"answer: {ans.get('text') or ans.get('error')}")]
    tok = ans.get("tokens") or {}
    return out + [T("calc", f"{tok.get('in', 0):,} tokens read, {tok.get('out', 0):,} written, {int(ans.get('ms') or 0):,} ms.")]


def answer_of(m: dict[str, Any]) -> str:
    """The tool the model called, as a card names it."""
    calls = (m.get("answer") or {}).get("calls") or []
    return str(calls[0].get("name")) if calls else "nothing it was given"


def report_lines(r: dict[str, Any]) -> list[dict[str, str]]:
    return [T("out", f"summary: {r.get('summary')}")] + [T("note", f"{f.get('label')}: {f.get('text')}") for f in r.get("facts") or []]


def told_line(r: dict[str, Any]) -> list[dict[str, str]]:
    return [T("out", f"to the {r.get('to')}: {r.get('text')}")]

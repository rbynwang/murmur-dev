"""The right side of the split view: one card per moment. A card names the part it is about and who acted, says what came in,
the rule and what went out, then shows data cards of labels and values and the terminal's caption.

Every value comes from the recording: a step's values, a terminal line or the ledger, as far as the story has reached. A row
with no value is left out, so no row of dashes or blanks is ever shown. The record calls the community agent "the coordinator";
outside the record's own lines a card uses the design's name.
"""
from __future__ import annotations

import re
from typing import Any

from .. import names as N
from .panels import CARDS, card, lines, trim
from .text import in_scope, num

Step = dict[str, Any]
ROLE = {"agg-clean": 1, "agg-share": 1, "agg-ref": 1, "mkt": 1, "utl": 1, "buy-u": 1, "buy-g": 1, "co-fc": 2, "co-agent": 2,
        "co-market": 2, "co-desk": 2, "co-cover": 2, "co-report": 2, "site-pv": 2, "site-dc": 2, "town": 3, "h-agent": 4, "b-agent": 4,
        "h-model": 4, "b-model": 4, "h-tools": 5, "b-tools": 5, "h-guard": 5, "b-guard": 5, "h-seal": 5, "b-seal": 5, "h-driver": 5,
        "b-driver": 5, "h-dev": 6, "b-dev": 6, "h-person": 7, "b-person": 7, "r-read": 8, "r-check": 8, "r-settle": 8, "r-pay": 8}
# What kind of actor each layer of the record is. A node's own steps are its code's
ACTOR = {"buyer": "stand-in", "coordinator": "code", "market": "code", "home_agent": "code", "building_agent": "code",
         "guard": "guard", "model": "AI model", "driver": "simulated", "device": "simulated", "person": "person"}
# What kind of actor a row of "who acted" names only once, on the opening card and in the bar
SAID_ONCE = {"stand-in", "simulated", "offline, on ENGIE's records"}
# The lines of the record that state a rule, best first. The first one a moment holds is shown
RULES = [r"each reading is checked at each door: [^.]*", r"The book fills each order from firm power first.*",
         r"(?<=By: rule: )plans are decided by code", r"Use only the facts given, and copy each number as it is",
         r"same window as the open sale.*", r"(?<=method: )mean of the last .*",
         r"policy [\d-]+: allow=\w+ by rule [\w.]+, for the role \"\w+\"",
         r"The coordinator names the meters and this buyer's share of the capacity sold", r"One call goes to all \d+ members"]
TERM_CAP = {"buyers": ["buyers", "utility, grid operator: orders, contracts, calls"], "market": ["community agent", "market.py, rt_market.py: the working"],
            "desk": ["desk", "rt_market.py: what is short, and what moved"], "model": ["model", "prompts and answers, in full. Nothing is hidden"],
            "chain": ["tool server", "context.py, guard.py, drivers.py"], "device": ["devices", "each write, with readings before and after"],
            "people": ["people", "what is kept for them, and what they said"], "ret": ["return path", "readings, checks, settlement, payment"],
            "aggpart": ["aggregator", "what this part read and worked out for the day"]}
SITE_TERM = ["single site", "its signed messages with the aggregator"]


def design_name(x: Any) -> Any:
    """The record's word for the community agent, "the coordinator", in the design's name; lists keep their shape."""
    if isinstance(x, list):
        return [design_name(y) for y in x]
    if isinstance(x, str):
        return re.sub(r"\bcoordinator\b", "community agent",
                      re.sub(r"\bThe coordinator\b", "The community agent", re.sub(r"\bthe coordinator\b", "the community agent", x)))
    return x


def kind_of(ms: list[Step], block: str) -> str:
    """Which data cards a moment shows: its box's own, unless the record shows the moment is really the model's or the guard's."""
    lays = {s.get("layer") for s in ms}
    if block.startswith(("agg-", "site-")):
        return "aggpart"
    if block.startswith("buy") or block in ("mkt", "utl"):
        return "buyers"
    if block in ("co-desk", "co-report"):
        return "desk"
    if block.startswith("co-"):
        return "model" if "model" in lays else "market"
    if block.startswith("r-"):
        return "ret"
    if block[2:] == "dev":
        return "device"
    if block[2:] == "person":
        return "people"
    if block[2:] == "model" or "model" in lays:
        return "model"
    return "chain" if "guard" in lays else "node"


def on_block(kind: str, block: str, node: str) -> str:
    """The box the card is about: the moment's own, except where the moment belongs to the model or the guard of a node."""
    if kind == "model":
        return "co-agent" if block.startswith("co-") and not node else f"{block[0]}-model"
    if kind == "chain":
        return f"{block[0]}-guard"
    return block


def who_row(ev: Any, block: str, kind: str, keys: list[Step], ms: list[Step], say_s: Step, node: str, answered: bool) -> list[list[str]]:
    """Who acted, and what kind of actor each one is, by the record's own layers. answered: a community moment whose card is a
    node's own answer, so it names the node."""
    tags: list[str] = []
    node_card = block[:2] in ("h-", "b-") or answered

    def add(x: str | None) -> None:
        if x and x not in tags:
            tags.append(x)
    if kind == "model" or any(s.get("layer") == "model" for s in keys):
        add("AI model")
    for s in [say_s] + keys:
        lay = str(s.get("layer") or "")
        if (lay == "person" and str(s.get("from")) != "person") or (lay in ("driver", "device") and kind != "device") \
                or (node_card and lay in ("coordinator", "market")):
            continue
        add(ACTOR.get(lay))
    if block.startswith("site-"):
        who, tags = ev.map.full(block), ["its own key on NANDA Town"]
    elif block.startswith("agg-"):
        who, tags = "The aggregator's " + ev.map.full(block).lower(), ["offline, on ENGIE's records"]
    elif block.startswith("buy") or block in ("mkt", "utl", "r-settle"):
        who = N.names_of([s.get("from") for s in ms if s.get("layer") == "buyer" and s.get("from") in ("utility", "grid-operator")]) or ev.map.full(block)
    elif (block.startswith("co-") and not answered) or block in ("r-check", "r-pay"):
        who, tags = "coordinator", ["code"]
    elif kind == "people":
        who = ev.map.full(block)
    elif kind == "device" and not node:
        who = f"{ev.total} nodes"
    else:
        acts = [s for s in ms if s.get("layer") in ("model", "home_agent", "building_agent", "guard")] or ms
        names = list(dict.fromkeys([node] * bool(node) + [str(s.get("node")) for s in acts if s.get("node")]))
        who = N.names_of(names, 2) if names else N.name_of(node, start=True)
    rows = [[who, ""]] + [["", t] for t in tags[:3]]
    return [design_name(r) for r in rows if r[1] not in SAID_ONCE]


def own_names(block: str, ms: list[Step]) -> set[str]:
    if block.startswith("buy") or block in ("mkt", "utl"):
        return {"utility", "grid-operator"}
    if block.startswith("co-"):
        return {"coordinator", "model"}
    if block.startswith("r-"):
        return {"coordinator", "utility", "grid-operator", "all nodes"}
    return {str(s.get("node")) for s in ms if s.get("node")} | {"guard", "driver", "model", "the node's code"}


def pick(steps: list[Step]) -> Step | None:
    """The message to name when several went: one that crossed Town first, then a device's write, then the rest."""
    for want in ("town", "device", "market", "coordinator", "buyer"):
        hit = next((s for s in steps if s.get("layer") == want), None)
        if hit:
            return hit
    return steps[0] if steps else None


def flow(ev: Any, block: str, carry: str, ms: list[Step], path: list[str]) -> tuple[list[str], list[str]]:
    """What came in and what went out, in the steps' own titles, with who it came from or went to and how many more like it."""
    me = own_names(block, ms)
    ins = [s for s in ms if s.get("to") in me and s.get("from") and s.get("from") not in me]
    outs = [s for s in ms if s.get("from") in me and s.get("to") and s.get("to") not in me and s.get("layer") != "guard"]
    outs = [s for s in outs if s.get("layer") != "person" or len(outs) == sum(1 for x in outs if x.get("layer") == "person")]

    def row(steps: list[Step], who: str) -> list[str]:
        s = pick(steps)
        if not s:
            return []
        same = sum(1 for x in steps if x.get("layer") == s.get("layer"))
        title, name = re.sub(r"\s*\(.*?\)", "", str(s.get("title") or "")), N.name_of(s.get(who))
        return [title, "" if name.lower() in title.lower() else name, str(same - 1) if same > 1 else ""]
    came, went = row(ins, "from"), row(outs, "to")
    if not came and carry and path and path[0] != block and not (path[0] == path[-1] and "model" not in {s.get("layer") for s in ms}):
        came = [carry, ev.map.full(path[0]), ""]
    return came, went


def rule_row(ms: list[Step], say_s: Step, did: str) -> str:
    """The rule the record states for this moment, in its own words."""
    text = [t for s in ms for t in lines(s)] + [str(s.get("plain") or "") for s in [say_s] + ms] + [str(s.get("title") or "") for s in ms]
    for pat in RULES:
        r = re.compile(pat)
        m = next((m for t in text for m in [r.search(t)] if m), None)
        if m and m.group(0).rstrip(".") not in did:
            return trim(re.sub(r'[{}"]', "", in_scope(m.group(0))))
    return ""


def some_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cards that hold something: a card with every field left out goes too."""
    return [x for x in cards if x.get("rows") or x.get("tbl") or x.get("q") or x.get("six") or x.get("nine") or x.get("says")]


def fit_cols(cols: str, n: int) -> str:
    """The card columns for the cards that are left."""
    m = re.match(r"repeat\((\d+),(.*)\)$", cols)
    if m:
        return f"repeat({min(int(m.group(1)), max(n, 1))},{m.group(2)})"
    return " ".join(cols.split()[:max(n, 1)])


def moment_card(ev: Any, mo: Any, ms: list[Step], keys: list[Step], say_s: Step, block: str, node: str, allv: dict[str, str],
                fresh: dict[str, str], seen: dict[str, Any], hero: list[str] | None, say: str, path: list[str]) -> dict[str, Any]:
    kind = kind_of(ms, block)
    own = next((str(s.get("node")) for s in ms if s.get("layer") == "model" and s.get("node")), "") if kind == "model" else ""
    answered = block.startswith("co-") and bool(own)
    cb = on_block(kind, block, node or own)
    came, went = flow(ev, cb if answered else block, mo.carry, ms, path)
    c = {"v": allv, "fresh": fresh, "seen": seen, "ms": ms, "mo": mo, "say_s": say_s, "block": block, "node": node}
    cards, cols = CARDS[kind](ev, c)
    cards = some_cards(cards)
    plain = in_scope(str(say_s.get("plain") or ""))
    did = plain if len(plain) <= 124 else trim(say, 124)
    return {"kind": kind, "cb": cb, "l": ROLE[cb], "who": who_row(ev, block, kind, keys, ms, say_s, node, answered),
            "in": design_name(came), "out": design_name(went), "did": design_name(did), "rule": design_name(rule_row(ms, say_s, did)),
            "cd": cards, "cols": fit_cols(cols, len(cards)), "term": design_name(SITE_TERM if cb.startswith("site-") else term_cap(kind, node)),
            "rev": None, "gap": None, "big": design_name(hero)}


def term_cap(kind: str, node: str) -> list[str]:
    """The terminal's caption for a card. A node is named in plain words, never by its id."""
    if kind == "node":
        return [N.name_of(node, start=True) or "node agent", f'{"building_agent" if N.is_building(node) else "home_agent"}: every step as recorded']
    return list(TERM_CAP[kind])


def start_card(ev: Any) -> dict[str, Any]:
    """Before the first moment: this run, on the same regions as a moment, and the evening line by line in the terminal."""
    m, com = ev.meta, ev.meta.get("community") or {}
    run = card("This run", [["Day", m.get("day")], ["Case", f'{m.get("case")}, tier {m.get("tier")}' if m.get("tier") else m.get("case")],
                            ["Code", str(m.get("code_commit") or "")[:7]], ["Model", ev.model_short], ["Recorded", str(m.get("made_at") or "")]], hot=True)
    sites = ev.engie.get("single_sites")
    nodes = card("Who is in it", [["Buyers", f"{len(ev.orders)} stand-ins"], ["Homes", com.get("homes")], ["Buildings", com.get("buildings")],
                                  *([["Single sites", sites]] if sites else []), ["Agents", f'{com.get("thinkers")} of {ev.total}'], ["Plans", "by code"]])
    tot = ev.ledger.get("totals") or {}
    day = card("How the day ended", [["Sold", f'{tot.get("sold_kwh"):,.0f} kWh' if num(tot.get("sold_kwh")) else ""],
                                     ["On the meters", f'{tot.get("delivered_kwh"):,.0f} kWh' if num(tot.get("delivered_kwh")) else ""],
                                     ["Buyers pay", f'${tot.get("seller_usd"):,.2f}' if num(tot.get("seller_usd")) else ""],
                                     ["Messages", f'{tot.get("messages"):,}' if isinstance(tot.get("messages"), int) else ""],
                                     ["Model answers", str(m.get("model_calls")) if m.get("model_calls") is not None else ""]])
    flow_rows = [["Asked by", "The aggregator, on the order of two buyers"],
                 ["Sellers", f'{com.get("homes")} homes, a small office and shops of ENGIE\'s community 19. Code makes each offer'],
                 ["Promise", "The community agent, with a cover from its own record"], ["Messages", "Signed envelopes, carried unread"],
                 ["Money", "The meters settle it"]]
    brief = {"t": "This evening, line by line", "r": [[c, a, b] for c, (a, b) in zip(("c1", "c4h", "c2", "c3", "cr"), flow_rows)]}
    return {"kind": "start", "cb": "", "l": 0, "cd": some_cards([run, nodes, day]), "cols": "1fr 1fr 1fr",
            "term": ["terminal", "the record of each moment, as it was written"], "rev": None, "gap": None, "big": [], "flow": [],
            "truth": "", "brief": brief}


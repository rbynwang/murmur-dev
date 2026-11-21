"""The data cards of a moment's card, by the kind of part the moment is about: the buyers' orders, the community agent's book,
a node's own numbers and nine steps, the small model's answer, a device call through the guard, the evening half hour by half
hour, what a person was told, the return path, the desk, and the aggregator's own parts.

Each builder takes the evening and the moment's context (its figures, its steps, its box) and gives its cards and the grid
columns they stand in.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import names as N
from . import words as W
from .text import first, num, trim

Step = dict[str, Any]
Row = list[Any]
NEED = {"keep_battery_full": "keep the battery full", "keep_car_ready": "keep the car ready", "keep_house_as_is": "leave the house as it is",
        "keep_hot_water": "keep hot water", "keep_machines_on": "let the machines run", "keep_lights_on": "keep the lights up"}
TILE = {"call": "offers", "offers-in": "offers", "split": "split", "buyer-contract": "contracts", "node-contract": "contracts"}
STEP_WORDS = [(("pre-cool",), 6), (("next device", "receipt: opening"), 7), (("whole plan", "carries out the plan", "own plan"), 8),
              (("safe offer", "checks the model's answer"), 5), (("step 6", "says accepted"), 6)]


def lines(s: Step) -> list[str]:
    return [str(x.get("text") or "") for x in s.get("terminal") or []]


def grab(ms: list[Step], pat: str, group: int = 1) -> str:
    """The first thing in a moment's terminal lines that matches, or nothing."""
    r = re.compile(pat)
    return next((m.group(group) for s in ms for t in lines(s) for m in [r.search(t)] if m), "")


def said(ms: list[Step], pat: str, group: int = 1) -> str:
    """The same, in the steps' plain sentences."""
    r = re.compile(pat)
    return next((m.group(group) for s in ms for m in [r.search(str(s.get("plain") or ""))] if m), "")


def kw2(v: Any, d: int = 2) -> str:
    x = first(v)
    return "" if x is None else f"{x:,.{d}f} kW"


def answer_step(ms: list[Step], say_s: Step) -> Step:
    """The one model answer a moment is about, for its big text and its card alike: the model step that explains the moment,
    or, for one named for the model's whole plan, the node's last answer at that time."""
    own = [s for s in ms if s.get("layer") == "model" and s.get("node") == say_s.get("node")]
    same = [s for s in own if s.get("sim_time") == say_s.get("sim_time")] if re.search("whole plan", str(say_s.get("title"))) else []
    return same[-1] if same else say_s


def largest_short(ms: list[Step]) -> Step | None:
    """The step in a moment with the largest shortfall a node reported, if any did."""
    tell = [(float(m.group(1).replace(",", "")), s) for s in ms for m in [re.search(r"short by up to ([\d,.]+) kW", str(s.get("plain") or ""))] if m]
    return max(tell, key=lambda x: x[0])[1] if tell else None


def no_value(v: Any) -> bool:
    """Whether a field holds nothing to show: empty, blank, a dash, or an empty value turned into words. A real 0 is a value."""
    return v is None or str(v).strip().lower() in ("", "-", "–", "—", "none", "null", "nan", "undefined")


def card(h: str, rows: list[Row] | None = None, hot: bool = False, **more: Any) -> dict[str, Any]:
    """A data card. A row with no value is left out, and so is a table row; None in a table is a cell left empty on purpose."""
    c: dict[str, Any] = {"h": h, "rows": [[str(r[0]), str(r[1]), 1 if len(r) > 2 and r[2] else 0] for r in rows or [] if not no_value(r[1])]}
    if hot:
        c["hot"] = 1
    if more.get("tbl"):
        more["tbl"] = more["tbl"][:1] + [r for r in more["tbl"][1:] if any(x is None or not no_value(x) for x in r[1:])]
    c.update({k: v for k, v in more.items() if v not in (None, "", [])})
    return c


def buyers(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    v, ms, mo = c["v"], c["ms"], c["mo"]
    cards = []
    for key, name in (("utility", "Utility"), ("grid-operator", "Grid operator")):
        o = ev.orders.get(key) or {}
        cards.append(card(name, [["Demand", o.get("kw")], ["Window", o.get("win")], ["Price", o.get("price")], ["Order value", o.get("worth")],
                                 ["Deposit", o.get("dep")]]))
    if mo.id == "orders":
        told = re.search(r"buyers are told at (.+?), and the answer is due by (.+)$", next((t for s in ms for t in lines(s) if "buyers are told" in t), ""))
        cards.append(card("Both orders", [["Asked", v.get("asked"), 1], ["Deposits", v.get("deposits")], ["Buyers told", told.group(1) if told else ""],
                                          ["Answer due", told.group(2) if told else ""]], hot=True))
    else:
        cards.append(card("The final list", [["Accepted", v.get("accepted"), 1], ["Declined", v.get("declined")], ["Sold", v.get("sold")],
                                             ["Baselines", grab(ms, r"baselines for (\d+ meters)")]], hot=True))
    return cards, "1fr 1fr 1fr"


def market(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    v, fresh, mo, seen = c["v"], c["fresh"], c["mo"], c["seen"]
    hot = TILE.get(mo.id, "book")
    half = lambda k: str(v.get(k) or "").split(", ")[0]  # noqa: E731
    tiles = [("book", "Order book", [["Asked", v.get("asked")], ["Sold", v.get("sold")]]), ("offers", "Offers", [["In", v.get("offers")], ["Offered", v.get("offered")]]),
             ("round", "Second round", [["Asked again", seen.get("_asked_again")]]), ("margin", "Margin", [["Fixed", v.get("margin")]]),
             ("split", "Homes, buildings", [["Homes", half("ask_h")], ["Buildings", half("ask_b")]]), ("reserve", "Reserve", [["Reserve", v.get("reserve")], ["Of nodes", v.get("nodes")]]),
             ("contracts", "Contracts", [["Accepted", v.get("accepted")], ["Declined", v.get("declined")]]), ("desk", "Desk", [["Reports", v.get("reports")], ["Rounds", v.get("rounds")]])]
    keys = {"book": ("asked", "sold"), "offers": ("offers", "offered"), "margin": ("margin",), "split": ("ask_h", "ask_b"), "reserve": ("reserve", "nodes"),
            "contracts": ("accepted", "declined"), "desk": ("reports", "rounds")}
    out = [card(name, [[r[0], r[1], k == hot and any(x in fresh for x in keys.get(k, ()))] for r in rows], hot=k == hot) for k, name, rows in tiles]
    return out, "repeat(4,minmax(0,1fr))"


def step_nos(ms: list[Step]) -> list[int]:
    """Which of the nine steps a moment's steps belong to, by their titles."""
    out: list[int] = []
    for s in ms:
        t = str(s.get("title") or "").lower()
        m = re.match(r"steps? (\d)(?: to (\d))?", t)
        if m:
            out += list(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
        for words, n in STEP_WORDS:
            if any(w in t for w in words):
                out.append(7 if n == 8 and "carries out" in t and s.get("stage") != "exception" else n)
    return sorted(set(out))


def node_card(ev: Any, name: str) -> dict[str, Any]:
    """What the record says this node is. The cast has more on a followed node."""
    f = ev.followed.get(name) or {}
    row = (ev.ledger.get("nodes") or {}).get(name) or {}
    shelf, bat = f.get("shelf") or [], f.get("battery_kwh")
    return card(N.name_of(name, start=True) or "This node", [["Kind", f.get("kind") or row.get("kind") or ("building" if N.is_building(name) else "home")],
                                                            ["Plans", "by code" if name else ""], ["Battery", f"{bat:,.1f} kWh" if num(bat) else ""],
                                                            ["Devices", trim(", ".join(f.get("devices") or []), 22)], ["Shelf", f"{len(shelf)} tools" if shelf else ""]])


def ladder(ev: Any, ms: list[Step]) -> dict[str, Any]:
    """The nine steps, each tagged with who does it, as on the map; the moment's own steps are marked."""
    now = step_nos(ms)
    tag = {"tool": "", "code": "code", "model": "AI"}
    return {"h": "Nine steps", "nine": [[n, name, tag.get(who, who), 1 if n in now else 0, 1 if who == "model" else 0] for n, name, who in W.NINE]}


def numbers(ev: Any, c: dict[str, Any], name: str) -> dict[str, Any]:
    seen, ms, fresh = c["seen"], c["ms"], c["fresh"]
    tab = lambda k: first((seen.get(k) or {}).get(name))  # noqa: E731
    nr = (ev.ledger.get("nodes") or {}).get(name) or {}
    safe = tab("_safe_offer_kw")
    rows: list[Row] = [["Safe offer", kw2(safe), "home_safe" in fresh or "code_safe" in fresh]]
    if safe is not None:
        rows += [["Of it firm", kw2(nr.get("firm_kw"))], ["Tentative", kw2(nr.get("tentative_kw"))]]
    made = tab("_offer_kw")
    rows += [["Offered", kw2(nr.get("offered_kw")) or kw2(made) if made is not None else "", "home_offer" in fresh or "uni_offer" in fresh],
             ["Contract", kw2(tab("_contract_kw"))]]
    extra = [("Can add", grab(ms, r"can add ([\d,.]+ kW)")), ("Owes on top", said(ms, r"now owes ([\d,.]+ kW) on top")),
             ("Left uncovered", grab(ms, r"which leaves ([\d,.]+ kW) uncovered"))]
    rows += [[a, b, True] for a, b in extra if b]
    return card("Its numbers", rows[:6], hot=True)


def node(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    name = c["node"] or next((str(s.get("node")) for s in c["ms"] if s.get("node")), "")
    return [node_card(ev, name), ladder(ev, c["ms"]), numbers(ev, c, name)], "1fr 1.72fr 1.1fr"


def model(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    ms = c["ms"]
    asked = [s for s in ms if s.get("layer") == "model"]
    s = answer_step(ms, c["say_s"])
    one = [s]
    tools = grab(one, r"^tools offered: (.+)$")
    ans = said(one, r"The model answers: (\w+)") or grab(one, r'"(margin": [\d.]+)').replace('":', "")
    reason = (grab(one, r'"reason": "([^"]+)') or grab(one, r'"summary": "([^"]+)') or grab(one, r'"reason_for_(?:owner|manager)": "([^"]+)')
              or grab(one, r"^answer: (.+)$") or grab([x for x in ms if x.get("node") == s.get("node") and x.get("sim_time") == s.get("sim_time")], r"^reason(?: given)?: (.+)$"))
    took = re.search(r"([\d,]+) tokens read, ([\d,]+) written, ([\d,]+) ms", " ".join(lines(s)))
    took_ms = took.group(3) if took else grab(one, r"^([\d,]+) ms\.")
    wait = grab(one, r"waited ([\d.]+) s in the model's queue")
    prompt = grab(one, r"^system: (.+)") if "fixed form" in str(tools) else ""
    a = card("Asked", [["For", N.name_of(s.get("node"), start=True)], ["Answers", str(len(asked)) if asked else "0"],
                       ["Prompt", trim(prompt, 46)] if prompt else ["Tools", trim(str(tools).replace(", ", " "), 48)]])
    needs = [NEED.get(w, w.replace("_", " ")) for w in dict.fromkeys(re.findall(r'"wish": "(\w+)"', " ".join(t for t in lines(s) if t.startswith("answer:"))))]
    job = ["Need", ", ".join(needs)] if needs else ["Need", "none in this note"] if ans == "no_wish" else ["Wrote", "the report"] if ans == "file_report" else ["Said", ans]
    b = card("Answer", [job + [True], ["It says" if ans == "file_report" else "Why", trim(reason, 108)]], hot=True)
    d = card("The model", [["Model", ev.model_short], ["Read", f"{took.group(1)} tokens" if took else ""], ["Wrote", f"{took.group(2)} tokens" if took else ""],
                           ["Took", f'{int(took_ms.replace(",", "")) / 1000:.1f} s' if took_ms else ""], ["Waited", f"{wait} s" if wait else ""]])
    return [a, b, d], "1.12fr 1.42fr 1fr"


def call_of(s: Step) -> tuple[str, str, str, str]:
    """A guard step's call: the tool, its target, its other values, its window."""
    m = re.match(r"(\w+)\((\{.*\})\)(?:\s+from (\d\d:\d\d) to (\d\d:\d\d))?", next((t for t in lines(s) if re.match(r"\w+\(\{", t)), ""))
    args = json.loads(m.group(2))
    rest = ", ".join(f"{k} {v}" for k, v in args.items() if k != "target")
    return m.group(1), str(args.get("target") or ""), rest, f"{m.group(3)} to {m.group(4)}" if m.group(3) else ""


def checks(s: Step) -> list[list[Any]]:
    """The guard's six checks: all six passed on a call the guard let through."""
    says = next((t for t in reversed(lines(s)) if t.startswith("guard says")), "")
    status = (re.search(r"guard says (\w+)", says) or [None, ""])[1]
    return [[n, name, "ok" if status in ("done", "adjusted") else ""] for n, name, _ in W.CHECKS]


def chain(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    ms = c["ms"]
    gs = [s for s in ms if s.get("layer") == "guard"]
    g = gs[0]
    tool, target, vals, win = call_of(g)
    a = card("The call", [["Tool", tool], ["Target", target], ["Values", trim(vals, 44)], ["When", win], ["Expected", grab([g], r"expected ([\d,.]+ kW)"), True]])
    b = card("Safety guard", [["Says", grab([g], r"guard says (\w+)"), True], ["Policy", grab([g], r"allow=\w+ by rule ([\w.]+)")]], hot=True, six=checks(g))
    if len(gs) > 2:
        rows = [[call_of(s)[1] or str(s.get("to")), grab([s], r"expected ([\d,.]+ kW)") or grab([s], r"guard says (\w+)")] for s in gs]
        more = len(rows) - 4
        d = card(f"{len(rows)} calls here", tbl=[[trim(x[0], 17), x[1]] for x in rows[:4]] + ([[f"and {more} more", None]] if more > 0 else []))
        return [a, b, d], "1.14fr 1.08fr 1.2fr"
    dr = next((s for s in ms if s.get("layer") == "driver"), None)
    one = [dr] if dr else []
    d = card("Seal and driver", [["Seal", grab(one, r"seal (\w+)")], ["Driver", grab(one, r"^(\w+Driver)")], ["Answer", grab(one, r"driver answers (\w+)")],
                                 ["Live by", grab(one, r"would go by (\w+)")]])
    return [a, b, d], "1.26fr 1.12fr 1fr"


def device(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """The evening, half hour by half hour, from the delivery steps."""
    ms, v = c["ms"], c["v"]
    ds = [s for s in ms if (s.get("values") or {}).get("live_kw") is not None]
    rows = [["kW"] + [str(s.get("sim_time"))[11:16] for s in ds]]
    for lab, key in (("Homes", "live_homes_kw"), ("Buildings", "live_buildings_kw"), ("All", "live_kw")):
        rows.append([lab] + [f'{num((s.get("values") or {}).get(key)) or 0:,.0f}' for s in ds])
    title = "Below the no-sale twin" if ev.engie.get("window_from_settled_truth") else "Below the no-sale twin, the monitor's estimate"
    t = card(title, tbl=rows, hot=True)
    told = grab(ms, r"told rows in the record: (\[.*\])")
    told_n = str(len(json.loads(told))) if told else ("0" if grab(ms, r"(no message to a person exists|told only when a node gives less)") else "")
    d = card("So far", [["Below the twin", v.get("twin"), True], ["Nodes", str(ev.total)], ["People told", told_n]])
    return [t, d], "2.2fr 1fr"


def people(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """What the node's agent told its person in plain words, and what a person can write."""
    who = "home owner" if c["block"] == "h-person" else "building manager"
    a = card(f"What the {who} was told", q=trim(grab(c["ms"], r"^to the (?:owner|manager): (.+)$"), 200), hot=True)
    b = card("What they can write", says=[[x, y] for x, y in W.SAYS[:4]])
    return [a, b], "1.2fr 1fr"


def ret(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    v, fresh, block, seen = c["v"], c["fresh"], c["block"], c["seen"]
    got, _, due = str(v.get("readings") or "").partition(" of ")
    lost = said(c["ms"], r"holding (\d+) readings")
    cards = [("r-read", "Readings", [["In", got, "readings" in fresh], ["Due", due], ["Meters", v.get("meters")]] + ([["Lost", lost, True]] if lost else [])),
             ("r-check", "Checks", [["Refused", v.get("refused"), "refused" in fresh], ["Missing", seen.get("_missing") or ""]]),
             ("r-settle", "Settlement", [["Buyers", v.get("buyers_pay"), "buyers_pay" in fresh], ["Utility", v.get("pay_u")], ["Grid op.", v.get("pay_g")],
                                         ["Meters", v.get("delivered")]]),
             ("r-pay", "Payment", [["Sellers", v.get("sellers"), "sellers" in fresh], ["Homes", v.get("homes_usd")], ["Buildings", v.get("bld_usd")],
                                   ["Kept" if ev.sites else "Keeps", v.get("keep")]])]
    return [card(n, rows, hot=b == block) for b, n, rows in cards], "repeat(4,minmax(0,1fr))"


def desk(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    v, ms = c["v"], c["ms"]
    tell = largest_short(ms) or next((s for s in ms if re.search(r"tells the desk", str(s.get("title")))), None)        # the report the big figure names
    one = [tell] if tell else []
    short = re.search(r"short: \{\"[\d-]+ (\d\d:\d\d)\": ([\d.]+)", " ".join(lines(tell))) if tell else None
    a = card("Reported", [["Node", N.name_of(str(tell.get("node")) if tell else "", start=True)], ["Short by", said(one, r"short by up to ([\d,.]+ kW)"), True],
                          ["From", short.group(1) if short else ""], ["Reason", said(one, r"Reason: ([^.]+)")]], hot=bool(tell))
    b = card("The desk's sum, kW", [["Reserve", v.get("reserve")]])
    ask = re.search(r"rt_ask to (\d+) members?", " ".join(t for s in ms for t in lines(s)))
    conf = grab(ms, r"^confirmed ([\d,.]+ kW)")
    d = card("What the desk did", [["Asked", f'{ask.group(1)} member{"" if ask.group(1) == "1" else "s"}' if ask else ""],
                                   ["Confirmed", v.get("call_conf") or conf, bool(conf)], ["Reserve", v.get("reserve")], ["Reports", v.get("reports")],
                                   ["Rounds moved", v.get("rounds")]], hot=not tell)
    return [a, b, d], "1fr 1.2fr 1fr"


def aggpart(ev: Any, c: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """One of the aggregator's own parts, or a single site: the cards the step itself carries."""
    cards = [card(str(h), [[str(a), str(b)] for a, b in rows]) for s in c["ms"]
             for h, rows in ((s.get("values") or {}).get("agg_cards") or (s.get("values") or {}).get("site_cards") or [])]
    return cards, " ".join(["1fr"] * max(1, len(cards)))


CARDS = {"aggpart": aggpart, "buyers": buyers, "market": market, "node": node, "model": model, "chain": chain, "device": device,
         "people": people, "ret": ret, "desk": desk}

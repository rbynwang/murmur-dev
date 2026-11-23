"""The beats of a live evening: every kind of moment a running network can show, in rank order.

A beat is a moment's kind. Most take their words (headline, big figure, caption, path) from the replay's own table of moments
by id, changed on this evening's own copy of it where a live evening must say something else: a recording knows the whole
evening, a live moment only what has happened so far. The beats a recording never had (the question about tomorrow, a note
read as it comes, a buyer's call, the desk, each surprise) bring their own words, and figures() reads what those words name.

Rank is the table's order: the order in which the beats' first steps arrive inside one quarter-hour, a node's rows at the
tick and the desk's exchanges seconds later. `per` says what makes an instance of a beat besides the quarter-hour: "tq"
nothing more, "node" the node, "half" the half hour. In a path or a block, "{buyer}" stands for the box of the buyer a
moment's steps name, and "{side}" for the side of its node.
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple

from ..names import capital
from ..replay import moments as M
from ..replay import panels as P
from ..replay.text import kw, num

Step = dict[str, Any]


class Beat(NamedTuple):
    id: str
    rank: int
    mo: M.Mo
    per: str


# kind: (headline, the page's word for the surprise, block, side path)
SURPRISES = {"note": ("An owner writes to their home", "Owner's note", "h-person", ("person", "agent")),
             "car_now": ("An owner needs the car now", "Car needed now", "h-person", ("person", "agent")),
             "weather": ("The weather changes", "Weather change", "h-dev", ()),
             "building_closed": ("A building closes early", "Building closes", "b-person", ()),
             "building_need": ("A building needs its power back", "Building needs power", "b-person", ()),
             "emergency": ("A grid emergency is called", "Grid emergency", "{buyer}", ()),
             "battery_fault": ("A battery fails", "Battery fault", "h-agent", ()),
             "battery_low": ("A battery runs low", "Battery low", "h-agent", ())}
WORDS = {f"s-{kind}": row[1] for kind, row in SURPRISES.items()}
# The beats of each rank, and what an instance is counted by
RANKS = [(("orders",), "tq"), (("ask",), "tq"), (("call",), "tq"), (("home-safe",), "node"), (("home-model",), "node"),
         (("bld-offer",), "node"), (("offers-in",), "tq"), (("book",), "tq"), (("buyer-contract",), "tq"), (("node-contract",), "tq"),
         (("frozen",), "tq"), (("tomorrow",), "tq"), (("battery-ask", "ask-refused"), "tq"), (("site-ask", "site-answer"), "tq"),
         (tuple(WORDS), "tq"), (("note-read",), "node"), (("told",), "node"), (("watch-home", "watch-bld"), "node"),
         (("window",), "half"), (("community-report",), "tq"), (("site-report",), "tq"), (("exc-model",), "node"),
         (("exc-code",), "node"), (("report",), "node"), (("call-in",), "tq"), (("desk",), "tq"), (("call-desk",), "tq"),
         (("readings",), "tq"), (("settle",), "tq"), (("pay",), "tq")]
# What a live evening says differently from the recording's table
CHANGES = {"bld-offer": {"big": "{other_offer}", "cap": "offered by {other_place}"},
           "watch-home": {"big": "{calls_here}"},
           "watch-bld": {"big": "{calls_here}", "cap": "device calls at {other_place}"},
           "window": {"big": "{hh_now}", "cap": "below the no-sale twin, {hh_span}"},
           "book": {"cap": "sold in the fullest half hour, firm power first"},
           "buyer-contract": {"cap": "in the fullest half hour, at {price}"},
           "node-contract": {"big": "{contracts}"},
           "told": {"cap": "what the node told its person"}}


def _live() -> list[M.Mo]:
    """The moments only a live evening has. Their steps come by their beat, so each rule takes nothing."""
    none = M.st()
    return [M.Mo("tomorrow", "The community agent asks about tomorrow", none, "", block="buy-u", path=("co-market", "town", "buy-u")),
            M.Mo("note-read", "The small model reads the note", none, "", block="{side}-model", side_path=("person", "agent", "model", "agent"),
                 big="{note_need}", cap="read from the note by the small model"),
            M.Mo("call-in", "A buyer calls on short notice", none, "", block="co-desk", path=("{buyer}", "town", "co-desk"), big="{call_kw}",
                 cap="called for at short notice"),
            M.Mo("desk", "A shortfall reaches the desk", none, "", block="co-desk", side_path=("agent", "town", "co-desk"), big="{short_now}",
                 cap="reported short"),
            M.Mo("call-desk", "The desk answers the call", none, "", block="co-desk", path=("co-desk", "town", "{buyer}"), big="{call_got}",
                 cap="confirmed of {call_kw} called")] + [
            M.Mo(f"s-{kind}", title, none, "", block=block, side_path=side) for kind, (title, _, block, side) in SURPRISES.items()]


def beats(sites: bool) -> list[Beat]:
    """Every beat of a live evening in rank order, each with its moment's words. The table is made anew for each call, so
    what is changed here is this evening's copy alone. Without single sites their three beats are not there."""
    mos = {m.id: m for m in M.table(sites) + _live()}
    out = []
    for rank, (ids, per) in enumerate(RANKS):
        for i in ids:
            if i in mos:
                for name, words in CHANGES.get(i, {}).items():
                    setattr(mos[i], name, words)
                out.append(Beat(i, rank, mos[i], per))
    return out


def figures(ms: list[Step], seen: dict[str, Any]) -> dict[str, str]:
    """The figures only a live moment's big text and caption name, each read from the moment's own steps: the half hour just
    delivered and its span, the need read from a note, a buyer's call and what the desk confirmed of it, the device calls
    that ran here, and how many contracts went out. A figure the steps lack stays out."""
    o: dict[str, str] = {}
    vals = [s.get("values") or {} for s in ms]
    hh = next((s for s in ms if (s.get("values") or {}).get("live_kw") is not None), None)
    if hh:
        h, m = (int(x) for x in str(hh.get("sim_time"))[11:16].split(":"))
        end = (h * 60 + m + 30) % 1440
        o["hh_now"], o["hh_span"] = f'{kw(hh["values"]["live_kw"])} kW', f"{h:02d}:{m:02d} to {end // 60:02d}:{end % 60:02d}"
    wishes = list(dict.fromkeys(w for s in ms for t in P.lines(s) for w in re.findall(r'"wish": "(\w+)"', t)))
    if wishes:
        o["note_need"] = capital(", ".join(P.NEED.get(w, w.replace("_", " ")) for w in wishes))
    elif any("no_wish" in str(s.get("plain")) or "sets no wish" in str(s.get("title")) for s in ms):
        o["note_need"] = "No need"
    if num(seen.get("call_kw")) is not None:
        o["call_kw"] = f'{kw(seen["call_kw"])} kW'
    got = next((v["call_confirmed_kw"] for v in reversed(vals) if num(v.get("call_confirmed_kw")) is not None), None)
    if got is not None:
        o["call_got"] = f"{kw(got, 1)} kW"
    done = sum(1 for s in ms if s.get("layer") == "guard" and "done" in str(s.get("title")))
    if done:
        o["calls_here"] = str(done)
    sent = next((v["contracts"] for v in vals if v.get("contracts") is not None), None) or P.grab(ms, r"^confirm to (\d+) nodes?")
    if sent:
        o["contracts"] = str(sent)
    return o

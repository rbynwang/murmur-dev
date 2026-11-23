"""What a presenter may ask of the console (POST /console/do), checked field by field, and every sentence the console says.

check(body, facts) gives (command, None), the command with every field checked and each default filled in, or (None, words): why
it is refused, in words of the one fixed list below. Nothing of a refused body is repeated in the words.

  {"do": "hello"}                    is the key good?
  {"do": "start", "run_to"?}         start the evening anew; run_to: go straight to that quarter-hour and hold there
  {"do": "hold"}  {"do": "go"}       hold the clock once its step is finished; let it go on
  {"do": "step"}                     only while held: play to the next quarter-hour that is played
  {"do": "run_to", "ts"}             to a quarter-hour of this evening after the clock's, "YYYY-MM-DD HH:MM"
  {"do": "pace", "speed"}            "0.5", "1", "2", "4" or "max"
  {"do": "surprise", "kind", ...}    one of the eight kinds, with the fields FIELDS gives that kind

facts is what the driver knows when the command comes:

  play        idle | starting | running | held | settled | failed
  now         the clock's dataset time, or None while there is none
  span        [the evening's first quarter-hour, its last]
  roster      {"homes": [{"id", "name", "battery"}], "buildings": [{"id", "name"}], "buyers": [ids]}, as /console/state shows it
  follow      {"home": id, "building": id}: the followed ones, a surprise's `who` when none is named
  surprises   the kinds this network takes (every kind when not given)

Every sentence the console says of itself (a refusal here, and the driver's busy, error, warn and link) is say() of one entry of
SAY. Its only variables are a part's role name, by the part's key in ROLES, and a surprise's page word, by its kind: never an
address, a port, a path, a node's id or an exception's text.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

SPEEDS = {"0.5": 16000, "1": 8000, "2": 4000, "4": 2000, "max": 0}     # a speed, and how long a moment stays on screen at it, in ms: at
                                                                       # 1 the 8 seconds a moment of the recorded replay has at its own 1x
WORDS = {"note": "Owner's note", "car_now": "Car needed now", "weather": "Weather change", "building_closed": "Building closes",
         "building_need": "Building needs power", "emergency": "Grid emergency", "battery_fault": "Battery fault", "battery_low": "Battery low"}
KINDS = tuple(WORDS)                                # the eight kinds of surprise, each with the page's word for it
ROLES = {"bus": "message bus", "community": "community agent", "homes": "homes' host", "buildings": "buildings' host", "buyer": "buyer",
         "aggregator": "aggregator", "site": "single site", "model": "small model", "meter": "community's meter", "peer": "other network"}
NOTE = "Please keep the battery full tonight."
TEXT_MAX = 200
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:(00|15|30|45)")
WHO = {"note": "home", "car_now": "home", "building_closed": "building", "building_need": "building", "battery_fault": "battery", "battery_low": "battery"}
NUMBERS = {"weather": {"pv": (0, 1, 0.2), "load": (0.5, 2, 1.3), "dT": (-10, 10, 6), "hours": (0.5, 24, 3)},       # field: least, most, default
           "building_need": {"share": (0.05, 1, 0.25), "hours": (0.5, 6, 3.5)},
           "emergency": {"kw": (1, 2000, 20), "minutes": (15, 240, 60)},
           "battery_low": {"pct": (5, 100, 10)}}
OTHER = {"note": ("text",), "emergency": ("buyer",), "battery_fault": ("on",)}
FIELDS = {k: (*(("who",) if k in WHO else ()), *OTHER.get(k, ()), *NUMBERS.get(k, ())) for k in KINDS}       # what each kind of surprise takes
TAKES = {"hello": (), "start": ("run_to",), "hold": (), "go": (), "step": (), "run_to": ("ts",), "pace": ("speed",), "surprise": ("kind",)}
RANGE = "The number {field} must be from {least} to {most}."

SAY = {
    # a command refused
    "unreadable": "The command is not a JSON object the console can read.",
    "too_long": "The command is longer than 4,096 bytes.",
    "not_known": "The console does not know that command.",
    "field": "The command carries a field the console does not take.",
    "no_evening": "No evening is running.",
    "starting_already": "The network is already starting.",
    "not_held": "Step works only while the clock is held.",
    "when": "The time must be a quarter-hour of this evening, after the clock's.",
    "speed": "The speed is one of 0.5, 1, 2, 4 and max.",
    "kind": "The console does not know that surprise.",
    "not_here": "This network does not take that surprise.",
    "home": "That home is not in this network.",
    "building": "That building is not in this network.",
    "buyer": "That buyer is not in this network.",
    "no_battery": "That home has no battery.",
    "no_batteries": "No home of this network has a battery.",
    "text": "The note is one printable line of 1 to 200 characters.",
    "on": "On must be true or false.",
    "preset": "A tap names one of the six events and nothing else.",
    **{f"{kind}.{field}": RANGE.format(field=field, least=least, most=most)
       for kind, fields in NUMBERS.items() for field, (least, most, _) in fields.items()},
    # busy: what the console is doing
    "starting": "Starting the network.",
    "restarting": "Starting the network again from its processes.",
    "surprise_waits": "{word}: waiting for the clock to stand.",
    "running_to": "Running to the chosen time.",
    "next_day": "Starting the next evening.",
    # error: what stopped it
    "no_start": "The network did not start.",
    "no_clock": "Not every part took the clock.",
    "no_answer": "No answer from the {role}.",
    "stopped": "A part of the network has stopped: the {role}.",
    # warn: what the presenter should know
    "log_full": "This run's log is full: no more moments are shown.",
    "refused": "{word} was not posted: the {role} refused it.",
    "not_posted": "{word} was not posted: no answer from the {role}.",
    "not_settled": "The evening ended without its settlement.",
    "stalled": "The clock stood too long: the next evening is started.",
    # link: the other console of a pair
    "peer_up": "The other network answers.",
    "peer_down": "The other network does not answer.",
    # a sentence that is not on the list
    "unknown": "The console cannot say more.",
}


def say(what: str, role: str | None = None, word: str | None = None) -> str:
    """One sentence of the fixed list. role: a part, by its key in ROLES; word: a surprise, by its kind. Never raises: a name
    that is on no list is said in general words."""
    line = SAY.get(what) if isinstance(what, str) else None
    part = ROLES.get(role) if isinstance(role, str) else None
    name = WORDS.get(word) if isinstance(word, str) else None
    return (line or SAY["unknown"]).format(role=part or "network", word=name or "The surprise")


def sentences() -> set[str]:
    """Every sentence say() can give."""
    return {say(k, role, word) for k in SAY for role in (None, *ROLES) for word in (None, *WORDS)}


class Refused(Exception):
    """A command that is not taken: its one argument is the refusal's entry in SAY."""


def check(body: Any, facts: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """A command checked against what the driver knows: (the command with its defaults, None) or (None, the refusal's words)."""
    try:
        return checked(body, facts if isinstance(facts, dict) else {}), None
    except Refused as no:
        return None, say(no.args[0])


def checked(body: Any, facts: dict[str, Any]) -> dict[str, Any]:
    do = body.get("do") if isinstance(body, dict) else None
    if not isinstance(do, str) or do not in TAKES:
        raise Refused("not_known")
    play, kind = facts.get("play"), body.get("kind")
    if do == "surprise" and not (isinstance(kind, str) and kind in FIELDS):
        raise Refused("kind")
    if any(not isinstance(k, str) or k not in ("do", *TAKES[do], *(FIELDS[kind] if do == "surprise" else ())) for k in body):
        raise Refused("field")
    if do == "hello":
        return {"do": do}
    if do == "start":
        if play == "starting":
            raise Refused("starting_already")
        first = (facts.get("span") or [None])[0]
        return {"do": do, "run_to": None if body.get("run_to") is None else when(body["run_to"], first, facts)}
    if do == "pace":
        if not isinstance(body.get("speed"), str) or body["speed"] not in SPEEDS:
            raise Refused("speed")
        return {"do": do, "speed": body["speed"]}
    if do == "step" and play != "held":
        raise Refused("not_held")
    if play not in ("running", "held") and not (play == "starting" and do in ("hold", "go")):
        raise Refused("no_evening")
    if do == "run_to":
        return {"do": do, "ts": when(body.get("ts"), facts.get("now"), facts)}
    return surprise(kind, body, facts) if do == "surprise" else {"do": do}


def when(ts: Any, after: Any, facts: dict[str, Any]) -> str:
    """A quarter-hour of the evening later than `after`, as it was given."""
    last = (facts.get("span") or [None, None])[-1]
    try:
        good = isinstance(ts, str) and bool(TIME.fullmatch(ts)) and bool(datetime.strptime(ts, "%Y-%m-%d %H:%M")) \
            and isinstance(after, str) and isinstance(last, str) and after[:16] < ts <= last[:16]
    except ValueError:
        good = False
    if not good:
        raise Refused("when")
    return ts


def ids(rows: Any) -> list[str]:
    """The ids of a roster's rows, each a row {"id": ...} or the id itself."""
    return [str(r["id"]) if isinstance(r, dict) else str(r) for r in rows or () if not isinstance(r, dict) or r.get("id")]


def surprise(kind: str, body: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """A surprise's fields, each checked, each one not given at its default."""
    if kind not in (KINDS if facts.get("surprises") is None else facts["surprises"]):
        raise Refused("not_here")
    roster, follow = facts.get("roster") or {}, facts.get("follow") or {}
    out: dict[str, Any] = {"do": "surprise", "kind": kind}
    if kind in WHO:
        out["who"] = who(WHO[kind], body.get("who"), roster, follow)
    if kind == "note":
        text = NOTE if body.get("text") is None else body["text"]
        text = text.strip() if isinstance(text, str) else ""
        if not 1 <= len(text) <= TEXT_MAX or not text.isprintable():
            raise Refused("text")
        out["text"] = text
    if kind == "emergency":
        buyers = ids(roster.get("buyers"))
        out["buyer"] = buyers[0] if body.get("buyer") is None and buyers else body.get("buyer")
        if not isinstance(out["buyer"], str) or out["buyer"] not in buyers:
            raise Refused("buyer")
    if kind == "battery_fault":
        out["on"] = True if body.get("on") is None else body["on"]
        if not isinstance(out["on"], bool):
            raise Refused("on")
    for field, (least, most, usual) in NUMBERS.get(kind, {}).items():
        x = usual if body.get(field) is None else body[field]
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not least <= x <= most:      # which no NaN is, and nothing endless
            raise Refused(f"{kind}.{field}")
        out[field] = x
    return out


def who(what: str, named: Any, roster: dict[str, Any], follow: dict[str, Any]) -> str:
    """The node a surprise is for: the one named, which must be in the roster (and hold a battery, for a battery's surprise);
    else the followed one; else the first that will do."""
    side = "building" if what == "building" else "home"
    here = ids(roster.get(side + "s"))
    fit = ids(r for r in roster.get("homes") or () if isinstance(r, dict) and r.get("battery")) if what == "battery" else here
    if named is None:
        named = follow.get(side) if follow.get(side) in fit else fit[0] if fit else None
        if named is None:
            raise Refused("no_batteries" if what == "battery" and here else side)
    if not isinstance(named, str) or named not in here:
        raise Refused(side)
    if named not in fit:
        raise Refused("no_battery")
    return named

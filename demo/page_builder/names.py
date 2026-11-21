"""Display names for the participants a recording names by id. A page never shows a home's or a building's id: it says
"home 39" or "the shopping center". A home's number is its number among the community's 200 homes. Single sites keep
their ids, which the terminal lines show as recorded (message ids, `to=`).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

HOME_NUMBER = {"home-01": 1, "home-02": 2, "home-03": 39, "home-04": 71, "home-05": 84, "home-06": 90, "home-07": 139,
               "home-08": 197}
PLACE = {"building-01": "the shopping center", "building-02": "the office", "utility": "the utility",
         "grid-operator": "the grid operator"}
HOME, BUILDING = "home-", "building-"      # how a home's and a building's ids begin
NODE_PAD = re.compile(r"\b(home-\d{2}|building-\d{2})\b( *)")
MARK_A, MARK_Z = "", ""          # around a name in a terminal line, until it is painted into its span


def is_home(who: Any) -> bool:
    return str(who or "").startswith(HOME)


def is_building(who: Any) -> bool:
    return str(who or "").startswith(BUILDING)


def capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def name_of(who: Any, start: bool = False) -> str:
    """A home, a building or a buyer by its plain name; any other word stays as it is. start: at the head of a sentence."""
    t = str(who or "")
    out = f"home {HOME_NUMBER[t]}" if t in HOME_NUMBER else PLACE.get(t)
    if out is None:
        return t
    return capital(out) if start else out


def names_of(who: Iterable[Any], most: int = 3) -> str:
    """Several of them on one line, the first with a capital: "Home 2, home 84 and 1 more"."""
    seen = list(dict.fromkeys(str(x) for x in who if x))
    said = [name_of(x, start=not i) for i, x in enumerate(seen[:most])]
    return ", ".join(said) + (f" and {len(seen) - most} more" if len(seen) > most else "")


def fixed_name(node: Any) -> str:
    """The name a card or a terminal heading gives a node: a home always with its capital, a building as in a sentence."""
    t = str(node or "")
    return name_of(t, start=is_home(t))


def named(text: Any, mark: bool = False) -> str:
    """A terminal line or a page string with its node ids named. A name opening a line or a sentence gets its capital; an id
    followed by a column gap keeps a two-space gap after its name. mark wraps each name in the marks paint() turns into a span."""
    def put(m: re.Match[str]) -> str:
        raw, pad = m.group(1), m.group(2)
        name = fixed_name(raw)
        head = m.string[:m.start()].rstrip(" ")
        if not head or head[-1] in ".!?":
            name = capital(name)
        if len(pad) >= 2:
            pad = "  "
        return (f"{MARK_A}{'h' if is_home(raw) else 'b'}{name}{MARK_Z}" if mark else name) + pad
    return NODE_PAD.sub(put, str(text))


def cast_names(tr: dict[str, Any]) -> dict[str, list[str]]:
    """Every home and building of a recording, by the name the page gives it, homes in the order of their numbers."""
    cast = tr.get("cast") or {}
    listed = [str(x) for k in ("thinkers", "code_only") for x in (cast.get(k) if isinstance(cast.get(k), list) else [])]
    ids = set(listed) | {str(f.get("node")) for f in (cast.get("follow") or {}).values() if f.get("node")} | set((tr.get("ledger") or {}).get("nodes") or {})
    homes = sorted((i for i in ids if i in HOME_NUMBER), key=HOME_NUMBER.get)
    return {"homes": [fixed_name(i) for i in homes], "buildings": [fixed_name(i) for i in sorted(i for i in ids if is_building(i))]}

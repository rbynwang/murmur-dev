"""A building guard's fixed figures and its small checks of times, zones and shares."""
from __future__ import annotations

import re
from datetime import date
from typing import Any


VOLTS = 240.0


OPEN_C, EMPTY_C = 1.5, 3.0       # warmer than normal: while people may be in, and in empty zones


SETPOINT_C = (13.0, 29.0)        # the code's range for a cooling setpoint


GAP_C = 2.8                      # between heating and cooling setpoints


RECOVER_MIN = 60                 # an empty zone is back at temperature this long before anyone is due


RAMP_MIN = 30                    # the ramp and the fade start this long before the sale


COP = 4.4


OCCUPIED_ADD = .10               # occupied zones add 10% of the rest (the sale's rule)


FAN_MIN = 50.0                   # percent while the building is open: fans slow, and only closed wings stop


MAX_DIM = 50.0


AMPS = (6.0, 80.0)


WRAP = {"set_battery", "limit_ev_charging"}                 # for these an end earlier than start means the next morning


TIME = re.compile(r"\d{4}-\d\d-\d\d[ T]([01]\d|2[0-3]):[0-5]\d(:\d\d)?|([01]\d|2[0-3]):[0-5]\d")


def mins(x: str) -> int:
    """Minutes since midnight."""
    x = x[11:16] if len(x) > 5 else x
    return int(x[:2]) * 60 + int(x[3:5])


def clock(m: float) -> str:
    m = int(m) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def good(x: Any) -> bool:
    """A real local time, HH:MM or with its date."""
    if not isinstance(x, str) or not TIME.fullmatch(x):
        return False
    try:
        return len(x) == 5 or bool(date.fromisoformat(x[:10]))
    except ValueError:
        return False


def day_of(call: dict[str, Any], f: dict[str, Any]) -> str:
    """The call's day: its own date, or the step's when it gives only HH:MM."""
    s = str(call["start"])
    return s[:10] if len(s) > 5 else str(f.get("ts", ""))[:10]


def span(call: dict[str, Any]) -> tuple[int, int]:
    """Start and end in minutes. Full timestamps say their own day. For HH:MM, an end earlier than start means the next morning where the card says so."""
    s, e = str(call["start"]), str(call["end"])
    a, b = mins(s), mins(e)
    if len(s) > 5 and len(e) > 5:
        return a, b + 1440 * (date.fromisoformat(e[:10]) - date.fromisoformat(s[:10])).days
    return a, b + 1440 if b <= a and call["tool"] in WRAP else b


def held_share(rise_c: float, pre_c: float, cap: float, cool_kw: float, hours: float) -> float:
    """The share of the cooling the building's stored cold can carry: the card's formula, 1 at most."""
    return max(0.0, min(1.0, (rise_c + pre_c) * cap / max(1e-6, cool_kw * COP * hours)))


def zone_kw(d: dict[str, Any], offset_c: float) -> float:
    """kW a zone group gives at this offset: rooms with no booking at the offset, the rest at +1.5 C at most, with the 10% occupied add."""
    if d.get("cool_kw", 0.0) <= 0:
        return 0.0
    free = float(d.get("free_share", 1.0 if d.get("state") == "free" else 0.0))
    args = (d.get("pre_c", 0.0), d["cap"], d["cool_kw"], d.get("hours", 3.0))
    s_free = held_share(offset_c, *args)
    s_open = held_share(min(offset_c, float(d.get("open_c", OPEN_C))), *args)
    s_open += OCCUPIED_ADD * (1 - s_open)
    return d["cool_kw"] * (free * s_free + (1 - free) * s_open)


def with_times(try_: dict[str, Any], call: dict[str, Any], start: str | None = None, end: str | None = None) -> dict[str, Any]:
    keep = {k: clock(mins(call[k])) for k in ("start", "end") if good(call.get(k))}
    return {**try_, **keep, **({"start": start} if start else {}), **({"end": end} if end else {})}


def _touches(window: str, s: int, e: int) -> bool:
    """Does the call touch this HH:MM-HH:MM window of the agreement's schedule?"""
    a, b = int(window[:2]) * 60 + int(window[3:5]), int(window[6:8]) * 60 + int(window[9:11])
    b += 1440 if b <= a else 0
    return any(s + k < b and e + k > a for k in (-1440, 0, 1440))

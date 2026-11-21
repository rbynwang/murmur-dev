"""How the Full record writes times and figures: a step's day and time, kW, dollars, and a value that may be a list of
half hours."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
LONG_DECIMAL = re.compile(r"\d+\.\d{4,}")


def stamp(ts: str) -> str:
    """A recorded time as the page shows it: "Tue 18:00"."""
    return f"{WEEKDAYS[dt.date.fromisoformat(ts[:10]).weekday()]} {ts[11:16]}"


def num(v: Any) -> float | None:
    """A recorded number, or None where the record holds none."""
    return None if v is None else float(v)


def kw(v: Any, d: int = 0) -> str:
    return f"{num(v):,.{d}f}"


def usd(v: Any) -> str:
    return f"${num(v):,.2f}"


def rng(v: Any, d: int = 0) -> str:
    """One number for a value that may be a list of half hours: the number, or lowest to highest."""
    if isinstance(v, (list, tuple)):
        xs = [num(x) for x in v]
        a, b = min(xs), max(xs)
        return kw(a, d) if round(a, d) == round(b, d) else f"{kw(a, d)} to {kw(b, d)}"
    return kw(v, d)


def first(v: Any) -> float | None:
    """The highest half hour of a value that may be a list."""
    if isinstance(v, (list, tuple)):
        return max(num(x) for x in v)
    return num(v)


def slot0(v: list[Any]) -> float | None:
    """The first half hour: a pair of numbers shown together must come from the same half hour."""
    return num(v[0])


def short_nums(text: str) -> str:
    """A lever's long decimals, cut to three places for a table cell. The terminal keeps them whole."""
    return LONG_DECIMAL.sub(lambda m: f"{float(m.group(0)):.3f}", text)

"""The year's 48 evenings, chosen by rule before any run: four a month of ENGIE's 2025.

THE RULE.
  not a holiday, not the two days the clocks change, not the year's first week
  the month's two dearest evenings by ENGIE's real-time price from 18:00 to 21:00
  two ordinary evenings: the price nearest the month's middle
  picks in a month at least three days apart
  at least one Saturday or Sunday in each month

How each part is read. An evening's price is the mean of ENGIE's 15-minute market price, in cents, from 18:00 to 21:00 on the participants'
local clock. The holidays are the US federal holidays as observed; the clocks change on the days the local clock's offset changes; the first
week is 1 to 7 January. The month's middle is the median price of its eligible evenings. The two dearest are taken first; then, nearest the
middle first (the earlier evening first where two are as near), the ordinary ones that keep three days from every pick. When none of the
four falls on a Saturday or Sunday, the second ordinary one gives way to the weekend evening nearest the middle that keeps three days from
the other three.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RULE = ["not a holiday, not the two days the clocks change, not the year's first week",
        "the month's two dearest evenings by ENGIE's real-time price from 18:00 to 21:00",
        "two ordinary evenings: the price nearest the month's middle", "picks in a month at least three days apart",
        "at least one Saturday or Sunday in each month"]
APART = 3
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _nth(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month (n = -1: the last)."""
    if n > 0:
        d = date(year, month, 1)
        return d + timedelta((weekday - d.weekday()) % 7 + 7 * (n - 1))
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(1)
    return d - timedelta((d.weekday() - weekday) % 7)


def holidays(year: int) -> set[date]:
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    seen = {d - timedelta(1) if d.weekday() == 5 else d + timedelta(1) if d.weekday() == 6 else d for d in fixed}
    return seen | {_nth(year, 1, 0, 3), _nth(year, 2, 0, 3), _nth(year, 5, 0, -1), _nth(year, 9, 0, 1), _nth(year, 10, 0, 2), _nth(year, 11, 3, 4)}


def clock_changes(year: int, zone: str) -> set[date]:
    starts = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="D", tz=zone)
    off = [t.utcoffset() for t in starts]
    return {starts[i].date() for i in range(len(starts) - 1) if off[i] != off[i + 1]}


def evening_prices(folder: Path, zone: str) -> pd.Series:
    """Each local day's mean price from 18:00 to 21:00, by date."""
    m = pd.read_parquet(folder / "market_prices.parquet", columns=["timestamp", "price_usd_mwh"])
    at = pd.DatetimeIndex(pd.to_datetime(m.timestamp, utc=True)).tz_convert(zone)
    sel = np.asarray((at.hour >= 18) & (at.hour < 21))
    price = pd.Series(m.price_usd_mwh.round(2).to_numpy()[sel])
    return price.groupby(np.asarray([d.date() for d in at[sel]])).mean()


def _apart(d: date, picks: list[date]) -> bool:
    return all(abs((d - x).days) >= APART for x in picks)


def month(p: pd.Series) -> list[dict]:
    """The four evenings of one month from its eligible evenings' prices (indexed by date, in date order)."""
    mid = float(np.median(p))
    dear: list[date] = []
    for d in p.sort_values(ascending=False).index:
        if len(dear) == 2:
            break
        if _apart(d, dear):
            dear.append(d)
    near = sorted(p.index, key=lambda d: (abs(p[d] - mid), d))
    ordinary: list[date] = []
    for d in near:
        if len(ordinary) == 2:
            break
        if _apart(d, dear + ordinary):
            ordinary.append(d)
    if not any(d.weekday() >= 5 for d in dear + ordinary):
        ordinary = [ordinary[0], next(d for d in near if d.weekday() >= 5 and _apart(d, dear + ordinary[:1]))]
    return sorted(({"evening": d.isoformat(), "kind": kind, "weekday": DAYS[d.weekday()], "price_18_21_usd_mwh": round(float(p[d]), 1),
                    "months_middle_price": round(mid, 1)} for kind, ds in (("dearest", dear), ("ordinary", ordinary)) for d in ds), key=lambda x: x["evening"])


def choose(prices: pd.Series, year: int, zone: str) -> list[dict]:
    skip = holidays(year) | clock_changes(year, zone) | {date(year, 1, d) for d in range(1, 8)}
    out = []
    for m in range(1, 13):
        days = [d for d in prices.index if d.year == year and d.month == m and d not in skip]
        out += month(prices[sorted(days)])
    return out


def compare(chosen: list[dict], recorded: list[dict]) -> list[str]:
    """Where a choice differs from a recorded one: evening, kind, price and middle, in date order."""
    a = sorted(tuple(x[k] for k in ("evening", "kind", "price_18_21_usd_mwh", "months_middle_price")) for x in chosen)
    b = sorted(tuple(x[k] for k in ("evening", "kind", "price_18_21_usd_mwh", "months_middle_price")) for x in recorded)
    return [f"chosen {x}, recorded {y}" for x, y in zip(a, b) if x != y] + ([f"{len(a)} chosen, {len(b)} recorded"] if len(a) != len(b) else [])

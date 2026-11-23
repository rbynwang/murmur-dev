"""The evening's timeline: where the clock's quarter-hours sit between the day-ahead sale and the settlement.

Dataset time is counted in quarter-hours (tq) from 09:45 on the day before the sale's day, where every clock starts an evening:
10:00 on that day is 1, 18:00 on the sale's day is 129. build() reads the evening's request, the configuration's events and the
single sites' requests, and gives a Timeline:

  t0            the dataset time of tq 0
  n             the timeline's length in quarter-hours: where its last part ends
  parts         five stretches, [{id, from, to}] in tq: the day before the sale's (dayahead), the sale's day up to an hour before
                the window (request), that hour (before), the window, and the ninety minutes after it (settle)
  pins          the named stops, [{tq, kind: "stop", id}]: the sale, the earliest request, an hour before the window (before),
                its start (delivery), its end, and the last of the readings, 45 minutes after it
  stops         every quarter-hour the clock must play, as dataset times, for the conductor's `stops`
  first, last   the evening's first and last quarter-hour: a time a presenter runs to lies between them

The clock itself may go on past n, to the end of the dataset: n is where the picture ends, not where the clock does.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

FMT = "%Y-%m-%d %H:%M"                              # a dataset time
QUARTER = timedelta(minutes=15)
PARTS = ("dayahead", "request", "before", "window", "settle")
STOPS = ("sale", "request", "before", "delivery", "end", "readings")
TOP = 400                                           # the largest tq and n the page takes
READINGS = (15, 30, 45)                             # minutes after the window at which the readings come in and the sale settles


def when(ts: Any) -> datetime:
    """A dataset time, read. ValueError when the text is none."""
    return datetime.strptime(str(ts)[:16].replace("T", " "), FMT)


def shift(ts: Any, minutes: float) -> str:
    """The dataset time this many minutes after ts."""
    return (when(ts) + timedelta(minutes=minutes)).strftime(FMT)


def tq(ts: Any, t0: Any) -> int:
    """The quarter-hours from t0 to a dataset time. A time inside a quarter-hour counts with its start."""
    return (when(ts) - when(t0)) // QUARTER


@dataclass(frozen=True)
class Timeline:
    t0: str
    n: int
    parts: list[dict[str, Any]]
    pins: list[dict[str, Any]]
    stops: list[str]
    first: str
    last: str

    def tq(self, ts: Any) -> int:
        """The quarter-hours from t0 to a dataset time: 1 at 10:00 on the day before the sale's, 129 at 18:00 on its day."""
        return tq(ts, self.t0)

    def ts(self, q: int) -> str:
        """The dataset time of a quarter-hour: what tq() counts back from."""
        return shift(self.t0, 15 * q)


def build(evening: dict[str, Any], events: list[dict[str, Any]] | None, sites: dict[str, Any] | None = None) -> Timeline:
    """The timeline of one evening. evening: the runner's (date, window, feed, battery_request); events: the configuration's, each
    with its `at`; sites: the single sites by name, each with its `requests`. ValueError when the day or the window cannot be read."""
    try:
        day = str(evening["date"])
        t0 = shift(f"{day} 09:45", -1440)
        w0, w1 = (shift(f"{day} {x}", 0) for x in evening["window"])
    except (KeyError, TypeError) as exc:
        raise ValueError("an evening has a date and a window of two times") from exc
    if w1 <= w0:                                      # a window that ends after midnight
        w1 = shift(w1, 1440)
    rows = sorted(str(k) for k in evening.get("feed") or ())
    first, last = shift(t0, 15), rows[-1][:16] if rows else shift(f"{day} 02:45", 1440)

    def quarter(ts: Any) -> str:
        return shift(t0, 15 * tq(ts, t0))
    asked = [evening.get("battery_request") or {}] + [r for s in (sites or {}).values() for r in s.get("requests") or []]
    asks = sorted(quarter(r["made_at"]) for r in asked if r.get("made_at"))
    after = [shift(w1, m) for m in READINGS]
    named = {"sale": first, "before": shift(w0, -60), "delivery": w0, "end": w1, "readings": after[-1]} | ({"request": asks[0]} if asks else {})
    stops = {*named.values(), f"{day} 10:00", *asks, *after, *(quarter(e["at"]) for e in events or () if e.get("at"))}
    at = shift(w0, -30)                               # from here a node may open its watch: every quarter-hour to the window's end
    while at < w1:
        stops.add(at)
        at = shift(at, 15)
    edges = [0]
    for ts in (f"{day} 00:00", named["before"], w0, w1, shift(w1, 90)):
        edges.append(max(edges[-1] + 1, tq(ts, t0)))  # in order whatever the window: a part is never empty
    return Timeline(t0=t0, n=edges[-1], parts=[{"id": p, "from": a, "to": b} for p, a, b in zip(PARTS, edges, edges[1:])],
                    pins=[{"tq": tq(named[k], t0), "kind": "stop", "id": k} for k in STOPS if first <= named.get(k, "") <= last],
                    stops=sorted(s for s in stops if first <= s <= last), first=first, last=last)


def marked(pins: list[dict[str, Any]], now: int, running: bool) -> list[dict[str, Any]]:
    """The pins as the feed sends them, by where the clock stands: [{tq, kind, id, state, jump}] in clock order. A pin the clock
    has reached is past, the first one after it is next, the others are ahead; a stop ahead of a running clock may be run to."""
    out: list[dict[str, Any]] = []
    for p in sorted(pins, key=lambda p: p["tq"]):
        ahead = p["tq"] > now
        state = "past" if not ahead else "ahead" if any(x["state"] != "past" for x in out) else "next"
        out.append({"tq": p["tq"], "kind": p["kind"], "id": p["id"], "state": state, "jump": bool(ahead and running and p["kind"] == "stop")})
    return out

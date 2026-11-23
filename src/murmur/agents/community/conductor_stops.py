"""Which steps the waiting clock must play: a stop is a quarter hour with something scheduled at it. Every other quarter hour is empty, and a
clock that leaps moves over a run of empty ones in one move.

A stop is: a gate, and for a gate that was opened that step and the one after it (what a runner posts at a gate is acted on in the next step);
a step the driver named (`stops`, and where it runs to); a quarter hour at which the market itself has something scheduled
(market_schedule.py); and the last step of the data.
"""
from __future__ import annotations

AHEAD = 96 * 2                 # how far ahead the door looks for the next stop (GET /demo/conductor, `next_stop`): the most one move can cover


class ConductorStops:
    """The schedule of stops, and where a leap lands."""

    def why_stop(self, k: int) -> str | None:
        """Why step k must be played, in a few words, or None when it is empty."""
        r, cond = self.c.clock, self.cond
        ts = r.ts(k)
        if ts in cond["gates"]:
            return "a gate"
        if ts in cond["opened"]:
            return "a gate was opened"
        if ts in cond["stops"]:
            return "a stop the driver set"
        if ts == cond["run_to"]:
            return "where the driver runs to"
        if k >= len(r.rows) - 1:
            return "the last step of the data"
        try:
            return self.c.market.scheduled(ts)
        except Exception as exc:                          # noqa: BLE001  a schedule that can't be read is no ground for a leap: the step is played
            why = f"the market's schedule can't be read: {type(exc).__name__}"
            if cond["unread"] != why:                     # told once, not at every look
                cond["unread"] = why
                self.c.event("clock_schedule_unread", error=f"{type(exc).__name__}: {exc}"[:160])
            return why

    def next_stop(self, i: int, within: int = AHEAD) -> int | None:
        """The first step after i that must be played, no further than `within` steps on; None when every one of them is empty."""
        last = min(i + within, len(self.c.clock.rows) - 1)
        return next((k for k in range(i + 1, last + 1) if self.why_stop(k)), None)

    def landing(self, i: int) -> int:
        """Where the clocks land from step i when the clock leaps: on the next stop (the step after i itself, when that one must be played), or
        leap_max steps on if no stop comes first. It never lands past a stop. Before a stop that is a gate it lands one step short, where the gate
        holds it as it holds any step. The market is read under its lock, so the schedule a leap rests on is one moment's."""
        r = self.c.clock
        far = min(i + self.leap_max(), len(r.rows) - 1)
        with self.c.market.lock:
            stop = self.next_stop(i, far - i)
        if stop is None:
            return far
        return stop - 1 if r.ts(stop) in self.cond["gates"] else stop

    def gate_opened(self, ts: str) -> None:
        """A gate was opened: its step and the one after it are played, wherever the clock is."""
        k = self.c.clock.idx_of(ts)
        if k is not None:
            self.cond["opened"] = self.cond["opened"] | {ts, self.c.clock.ts(k + 1)}

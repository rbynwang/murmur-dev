"""What the market has scheduled: the quarter hours at which something of its own falls due by the clock alone. A clock that leaps over empty
time stops at each of them and plays it (conductor_stops.py); everything else of the market's comes with a message, which a step waits for.
"""
from __future__ import annotations

from typing import Any

from murmur.protocol import envelope as beckn

LEAD_MIN = 30                # a node's agent plans a sale this long before it opens (node/agent_levers.py); cfg clock_lead_minutes where the nodes were given another lead
NOTICE_MIN = 120             # the notice to committed members goes this long before the window, where members hear one at all (Market._tick_sale)
OPEN_MIN = 1440              # a sale or a call that is not settled is asked after for a day past its end, and no longer (Market._tick_sale, gaps.CHASE_FOR_MIN)
UNSIGNED = ("offers", "clearing", "cleared", "utility")      # a sale's phases before its buyers have signed


def opens_brake(answered: str | None, now_ts: str, soon: str) -> bool:
    """Every day at 10:00 the market asks its buyers for tomorrow's request. The clock waits from 10:00 until the answer is in, or until 16:00
    without one. `answered`: the last day whose 10:00 question the buyer has answered; `soon`: the step a wait can still reach in time."""
    d = soon[:10]
    return soon[11:16] >= "10:00" and now_ts < f"{d} 16:00" and (answered or "") < d


class MarketSchedule:
    """What the market has scheduled: the quarter hours at which something of its own falls due by the clock alone."""

    def scheduled(self, ts: str) -> str | None:
        """What the market has at quarter hour `ts`, in a few words, or None when it has nothing there:

          the day's question   10:00 to 16:00 of a day a buyer has not yet answered for
          a sale's contract    every quarter hour up to commit_by while its buyers or its members have still to sign
          a sale's notice      from two hours before its window until the notice has gone (where members hear one)
          a sale's evening     from the agents' lead before the window, through the window, the readings and the settlement, to its
                               phase `done`; a day past the window at most
          a call of the desk   while its answers are to come, through the quarter hours it covers, and a buyer's call until it is settled

        It reads the market as it stands: under the market's lock where the answer decides something, as the waiting clock asks it."""
        for b in self.buyers:
            if opens_brake(self.last_discover_day if b == self.utility else self.other_discover.get(b), ts, ts):
                return f"the question to {b} for tomorrow"
        lead = float(self.cfg.get("clock_lead_minutes", LEAD_MIN))
        for eid, ev in list(self.events.items()):
            why = self._sale_at(ev, ts, lead)
            if why:
                return f"{eid}: {why}"
        for rec in list(self.rt.calls.values()):
            end = rec.get("end_early") or rec["end"]
            if rec.get("phase") == "asking":
                return f'call {rec["id"]}: answers to come'
            if ts < end:
                return f'call {rec["id"]}: it runs until {end[11:16]}'
            if rec["kind"] != "gap" and not rec.get("too_late") and (not rec.get("settled") or rec.get("lacking")) and ts <= beckn.add_minutes(end, OPEN_MIN):
                return f'call {rec["id"]}: its settlement'
        return None

    def _sale_at(self, ev: dict[str, Any], ts: str, lead: float) -> str | None:
        n, ph = ev["need"], ev["phase"]
        if (ph in UNSIGNED or (ph == "homes" and not ev.get("final_sent"))) and ts <= n["commit_by"]:
            return "its contract is still open"
        if ph in UNSIGNED + ("failed", "no_offer") or (ph == "done" and not ev.get("readings_missing")):
            return None                                   # never signed, or all of it done: nothing of it is to come
        if not self.quiet and ev.get("finalized") and not ev.get("notice_sent") and ts >= beckn.add_minutes(n["window_start"], -NOTICE_MIN):
            return "the notice to its members"
        if beckn.add_minutes(n["window_start"], -lead) <= ts <= beckn.add_minutes(n["window_end"], OPEN_MIN):
            return "its members plan it" if ts < n["window_start"] else "its window" if ts < n["window_end"] else "its readings and settlement"
        return None

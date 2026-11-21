"""A single site as a participant: one solar-and-battery plant or one data center, answering the aggregator for itself.

It takes the aggregator's signed request for battery power by quarter hour, gives what its own limits allow (a data center may also pause
work, to be run later), and reports one row per quarter hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from murmur.agents.community import community

STEP_H = 0.25
SOC_LOW, SOC_HIGH = 0.10, 0.90
REQUEST_FROM, CHARGE_ONLY_FROM = 14, 12           # the aggregator's request covers 14:00 to midnight; from 12:00 the battery only charges, so it meets the evening full


@dataclass
class Limits:
    """What a person at the site has ruled for the evening. None: no word given."""
    give_max_kw: float | None = None              # the battery gives no more than this at the connection
    hold: bool = False                            # the battery stays as it is: nothing is given on request
    pause_max_kw: float | None = None             # a data center pauses no more work than this
    why: str = ""                                 # one plain line for the answer, written by the node, never the person's own words


@dataclass
class Site:
    id: str
    kind: str                                     # "pv_bess" or "datacenter"
    rating_kw: float
    energy_kwh: float
    out_factor: float = 1.0                       # what reaches the connection per kWh taken out of the store
    limit_out_kw: float = float("inf")            # the most the site may send out at its connection
    store_kwh: float = 0.0
    wait_h: float = 0.0                           # a data center: how long postponed work may wait
    limits: Limits = field(default_factory=Limits)
    asked_kw: dict[int, float] = field(default_factory=dict)       # the request in force, by hour of the day
    pause_kw: dict[int, float] = field(default_factory=dict)       # a data center: work to pause, by hour of the day
    queue: list[list[float]] = field(default_factory=list)         # postponed work: [kWh left, quarter hours until it must have run]
    gaps: list[dict[str, Any]] = field(default_factory=list)       # every quarter hour where what was given differs from what was asked

    def __post_init__(self) -> None:
        if self.kind not in ("pv_bess", "datacenter", "shared_battery"):          # shared_battery: a community's own battery, run by its community agent with this same arithmetic (community.py)
            raise ValueError("a single site is a solar-and-battery plant or a data center")
        self.emin, self.emax = SOC_LOW * self.energy_kwh, SOC_HIGH * self.energy_kwh
        self.store_kwh = min(max(self.store_kwh, self.emin), self.emax)

    # ---------------------------------------------------------------- the request and the answer
    def ask(self, battery_kw: dict[int, float], pause_kw: dict[int, float] | None = None) -> dict[str, Any]:
        """The aggregator's request for today: kW at the connection by hour of the day, and for a data center the work to pause. Returns the answer: what the site will
        give in each hour by its limits as they stand now, and why wherever that is less."""
        for name, rows in (("battery", battery_kw), ("pause", pause_kw or {})):
            for h, v in rows.items():
                if not (isinstance(h, int) and 0 <= h <= 23 and community.amount(v)):
                    raise community.Refused(f"a request's {name} rows are an hour of the day and a number that isn't negative")
        if pause_kw and self.kind != "datacenter":
            raise community.Refused("only a data center is asked to pause work")
        self.asked_kw, self.pause_kw = dict(battery_kw), dict(pause_kw or {})
        x, out = self.store_kwh, {}
        for h in sorted(self.asked_kw):
            asked = self.asked_kw[h]; give, why = self._allowed(asked)
            can = max(x - self.emin, 0.0) * self.out_factor                # kWh at the connection the charge still holds: the kW it can give for one whole hour
            if give > can + 1e-9:
                give, why = can, "the charge runs out"
            x -= give / self.out_factor
            out[h] = {"asked_kw": round(asked, 3), "will_give_kw": round(give, 3), **({"why_less": why} if give < asked - 1e-3 else {})}
        return {"site": self.id, "battery": out, "pause": {h: round(self._pause_allowed(v), 3) for h, v in self.pause_kw.items()}}

    def _allowed(self, asked: float) -> tuple[float, str]:
        if self.limits.hold:
            return 0.0, self.limits.why or "the site holds its battery"
        give, why = min(asked, self.rating_kw), ("" if asked <= self.rating_kw + 1e-3 else "above the battery's rating")          # a watt of rounding in a request is not a request above the rating
        if self.limits.give_max_kw is not None and give > self.limits.give_max_kw:
            give, why = self.limits.give_max_kw, self.limits.why or "the site set a limit"
        return give, why

    def _pause_allowed(self, asked: float) -> float:
        return asked if self.limits.pause_max_kw is None else min(asked, self.limits.pause_max_kw)

    # ---------------------------------------------------------------- one quarter hour
    def step(self, ts: str, base_kw: float, recorded_kw: float, own_kwh: float, postponable_share: float = 0.0, price_usd_kwh: float | None = None) -> dict[str, Any]:
        """One quarter hour. base_kw: what the site sends out with its battery idle (negative: it draws). recorded_kw: what ENGIE's record shows it sent out, which the
        connection is known to carry. own_kwh: the battery's own schedule for this step (plus: it charges). Returns what happened and the row that goes up."""
        hour = int(ts[11:13]); asked = self.asked_kw.get(hour) if hour >= REQUEST_FROM else None; x = self.store_kwh
        if hour >= REQUEST_FROM:
            want, _ = self._allowed(asked or 0.0)
            w = -min(want * STEP_H / self.out_factor, max(x - self.emin, 0.0)) if want > 0 else min(max(own_kwh, 0.0), max(self.emax - x, 0.0))
        elif hour >= CHARGE_ONLY_FROM:
            w = min(max(own_kwh, 0.0), max(self.emax - x, 0.0))
        else:
            w = min(own_kwh, max(self.emax - x, 0.0)) if own_kwh >= 0 else -min(-own_kwh, max(x - self.emin, 0.0))
        gives = (-w if w >= 0 else -w * self.out_factor) / STEP_H            # kW at the connection, plus: given
        lim = max(self.limit_out_kw, recorded_kw); room = max(lim - base_kw, 0.0)
        if w < 0 and gives > room + 1e-9:                                    # the connection has no room for it: the battery gives what fits
            gives, w = room, -room * STEP_H / self.out_factor
        # ---- a data center's work that can wait
        paused = back = 0.0
        if self.kind == "datacenter":
            want_pause = self._pause_allowed(self.pause_kw.get(hour, 0.0)) if hour >= REQUEST_FROM else 0.0
            paused = min(want_pause, max(postponable_share, 0.0) * max(-base_kw, 0.0))
            more_to_come = paused > 0 or any(self.pause_kw.get(h, 0.0) > 0 for h in range(hour + 1, 24))
            for q in self.queue:
                if not more_to_come or q[1] <= 1:                            # the evening's pauses are over, or this piece is due now: it runs, at the steady rate that is never late
                    run = q[0] / max(q[1], 1.0); back += run / STEP_H; q[0] -= run
                q[1] -= 1                                                    # waiting counts against its deadline
            self.queue = [q for q in self.queue if q[0] > 1e-9]
            if paused > 0:
                self.queue.append([paused * STEP_H, max(1.0, round(self.wait_h / STEP_H))])
        sent = min(base_kw + gives + paused - back, lim)
        self.store_kwh = x + w
        if asked and abs(max(gives, 0.0) - asked) > 1e-3:
            self.gaps.append({"ts": ts, "asked_kw": round(asked, 3), "given_kw": round(max(gives, 0.0), 3), "gap_kw": round(max(gives, 0.0) - asked, 3)})
        text = "follows the aggregator's request" if asked else "runs its own schedule"
        return {"ts": ts, "battery_kw": gives, "store_step_kwh": w, "store_kwh": self.store_kwh, "sent_out_kw": sent, "paused_kw": paused, "run_again_kw": back,
                "row": community.row(self.id, ts, sent, 100 * self.store_kwh / self.energy_kwh, price_usd_kwh, text)}

    def owed_kwh(self) -> float:
        """Work a data center has postponed and not yet run."""
        return sum(q[0] for q in self.queue)

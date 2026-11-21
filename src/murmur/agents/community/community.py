"""One community at one point of the grid, and what sits behind it.

The community promises upward only what its members' offers can keep (the cover), records each sale and what it delivered, checks each
half hour sold against its connection's limit, and reports one row per quarter hour to its aggregator. A community has its members'
batteries, not a battery of its own. Its member record, its record of sales and what it took from above are kept on disk; everything else
is built again from its configuration.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from murmur.protocol import envelope as beckn
from murmur.agents.community.community_rules import ID, STEP_MIN, TIME, amount, number, row
from murmur.agents.community.community_feed import CommunityFeed
from murmur.agents.community.community_asked import CommunityAsked
from murmur.agents.community.members import Members, Refused      # Refused: the community's refusal, which its callers read as community.Refused

STEP_H = STEP_MIN / 60
LAST, START = 10, 3                                                  # the cover looks at the last 10 sales on record, and trusts the record once it holds 3
KEY = re.compile(r"[0-9a-f]{64}$")                                   # an Ed25519 public key, as signing.public_hex writes it


# =================================================================================================== 1. the community, as the wires define it
@dataclass(frozen=True)
class Battery:
    """The battery the community shares. out_factor: the share of what its state of charge loses that reaches the grid, as measured (0.894 in ENGIE's files).
    in_factor: the share of what it takes at the meter that reaches its cells (ENGIE's record shows no loss on the way in)."""
    rating_kw: float
    energy_kwh: float
    out_factor: float = 1.0
    in_factor: float = 1.0
    run_by_agent: bool = False          # the community agent steps the battery itself each quarter hour (Community.run_battery); False: its power and charge come with the feed


class Meter:
    """The community's own meter at its connection: net power per quarter hour, taking from the grid negative. Times are the market's own clock, "YYYY-MM-DD HH:MM"."""

    def __init__(self) -> None:
        self.kw: dict[str, float] = {}
        self.told: dict[str, float] = {}            # what someone outside expects for a step to come: a forecast, or a replay's record

    def add(self, ts: str, kw: float) -> None:
        if not (isinstance(ts, str) and TIME.match(ts) and number(kw)):
            raise ValueError("a meter reading is a time and a number")
        self.kw[ts[:16].replace("T", " ")] = float(kw)

    def expect(self, ts: str, kw: float) -> None:
        if not (isinstance(ts, str) and TIME.match(ts) and number(kw)):
            raise ValueError("an expected reading is a time and a number")
        self.told[ts[:16].replace("T", " ")] = float(kw)

    def at(self, ts: str) -> float | None:
        return self.kw.get(ts[:16])

    def expected(self, ts: str, days: int = 7) -> float | None:
        """What the meter should read at a step to come: what was told, else the same quarter hour on the days before, averaged over those it has."""
        ts = ts[:16]
        if ts in self.told:
            return self.told[ts]
        if ts in self.kw:
            return self.kw[ts]
        seen = [self.kw[t] for t in (beckn.add_minutes(ts, -1440 * k) for k in range(1, days + 1)) if t in self.kw]
        return sum(seen) / len(seen) if seen else None


# =================================================================================================== 5. the utility's limit
def fit(net_kw: float, battery_kw: float, sale_kw: float, limit_out_kw: float, limit_in_kw: float | None = None) -> dict[str, Any]:
    """One step at the connection. net_kw: the meter with neither the battery nor the sale, taking from the grid negative. battery_kw: what the members' batteries add, giving
    positive. sale_kw: what the members' cut adds. If together they would send out more than the utility allows, the battery gives way first, because nothing was promised
    on it, and then the sale is cut to fit. If they would draw more than allowed, the battery charges less; a sale can't help there. What stands, and what was cut."""
    b, s, cut = float(battery_kw), float(sale_kw), {}
    over = net_kw + b + s - limit_out_kw
    if over > 1e-9:
        less = min(max(b, 0.0), over)
        if less > 0:
            b, over, cut["battery_kw"] = b - less, over - less, round(less, 3)
        less = min(max(s, 0.0), over)
        if less > 0:
            s, over, cut["sale_kw"] = s - less, over - less, round(less, 3)
        if over > 1e-6:
            cut["still_over_kw"] = round(over, 3)       # the meter alone sends out more than the limit: nothing in this plan can lower it
    if limit_in_kw is not None:
        under = -(net_kw + b + s) - limit_in_kw
        if under > 1e-9:
            less = min(max(-b, 0.0), under)
            if less > 0:
                b, under, cut["charging_kw"] = b + less, under - less, round(less, 3)
            if under > 1e-6:
                cut["still_drawing_over_kw"] = round(under, 3)
    return {"battery_kw": b, "sale_kw": s, "net_kw": net_kw + b + s, "cut": cut or None}


# =================================================================================================== the community and its community agent's step
@dataclass
class Community(CommunityFeed, CommunityAsked):
    """One point of the grid and what sits behind it. limit_out_kw: the most it may send out at its connection, which the utility sets. limit_in_kw: the most it may
    draw, where the utility gives one (ENGIE's files give none)."""
    id: str
    point: str
    limit_out_kw: float
    limit_in_kw: float | None = None
    battery: Battery | None = None
    solar_kw: float = 0.0
    meter: Meter = field(default_factory=Meter)
    members: Members = field(default_factory=Members)
    report: list[dict[str, Any]] = field(default_factory=list)
    refusals: Counter = field(default_factory=Counter)                # messages not taken in, by kind: counted, and their content not kept
    battery_kw: dict[str, float] = field(default_factory=dict)        # what the members' batteries are planned to give, by quarter hour
    soc_pct: float | None = None                                      # its state of charge, as last read
    price: Callable[[str], float | None] | None = None                # the step's price in $ per kWh, where the market gives one
    soc: dict[str, float] = field(default_factory=dict)               # its state of charge by quarter hour, where the feed gives it
    prices: dict[str, float] = field(default_factory=dict)            # the step's price by quarter hour, where the feed gives it
    report_ended: bool = False                                        # on a real clock: a quarter hour's row is written once it has ended, when its meter reading exists
    log: Callable[..., None] = lambda *a, **k: None
    last_step: str | None = None
    keep_rows: int = 96 * 14
    sales: list[dict[str, Any]] = field(default_factory=list)         # per sale: what its members offered, what it promised upward, what was delivered
    gaps: list[dict[str, Any]] = field(default_factory=list)          # per sale: delivery less promise, for the community and for each member. For the record only: no rule reads it
    sales_path: Path | None = None
    aggregator: str | None = None                                     # the one party above it whose signed request it takes, by its name on the network. None: nobody above may ask
    aggregator_key: str | None = None                                 # that party's public key, where its enrolment gives one. Without it the first signed message pins the key (market.py)
    requests: list[dict[str, Any]] = field(default_factory=list)      # each request from above and the community's answer to it: taken, or refused and why. Never the request's own words
    outbox: list[dict[str, Any]] = field(default_factory=list)        # report rows still to go upward, oldest first
    sent_up: int = 0                                                  # report rows that went upward
    keep_out: int = 96 * 2                                            # rows that wait at most: with nobody to hear them the oldest are let go, and the report itself keeps them
    asked_rows: dict[str, dict[str, float]] = field(default_factory=dict)      # what it took from above, by quarter hour: kept in its own file, so a restart still holds it
    asked_path: Path | None = None
    idle: dict[str, dict[str, float]] = field(default_factory=dict)   # where it holds the members' batteries itself: what it was fed for a quarter hour ("idle_kw", "own_kwh", "recorded_kw", "store_kwh")
    engine: Any = None                                                # the battery's own arithmetic (site.Site), made at the first quarter hour it runs
    battery_ran: list[dict[str, Any]] = field(default_factory=list)   # what the battery did in each quarter hour the agent ran it

    # ---- the cover, from the record
    def cover(self, margin: float, before: str = "", known_by: str = "") -> dict[str, Any]:
        """The share of its members' offers the community promises upward. The fixed margin gives offers / (1 + margin). On ENGIE's evenings the homes deliver a steady
        80% of what they offer, so that promise holds on 1 evening of 31. The record gives the lowest share of its offers the community delivered on its last 10 sales,
        and the promise is the lower of the two: never more generous than the margin. Only sales before this one count, and the margin stands alone until 3 are on record.
        Where the clearing gives its own time (known_by), only sales whose result was in by then count: a sale cleared the morning before its evening can't know how the
        evening in between went."""
        fixed = 1 / (1 + margin)
        done = sorted((s for s in self.sales if s.get("delivered_kw") is not None and float(s.get("offered_kw") or 0.0) > 0 and (not before or s["start"] < before)
                       and (not known_by or str(s.get("delivered_at") or s["start"]) <= known_by)), key=lambda s: s["start"])
        if len(done) < START:
            return {"share": fixed, "by": "the fixed margin", "sales_on_record": len(done)}
        low = min(s["delivered_kw"] / s["offered_kw"] for s in done[-LAST:])
        return {"share": min(fixed, low), "by": "the record" if low < fixed else "the fixed margin", "lowest_delivered_share": round(low, 4), "sales_on_record": len(done)}

    def record_sale(self, sale: str, start: str, offered_kw: float, promised_kw: float) -> dict[str, Any]:
        row = next((s for s in self.sales if s["sale"] == sale), None)
        if row is None:
            row = {"sale": sale, "start": str(start)[:16], "delivered_kw": None}
            self.sales.append(row)
        row.update(offered_kw=round(float(offered_kw), 3), promised_kw=round(float(promised_kw), 3))
        self._save_sales()
        return row

    def sale_delivered(self, sale: str, delivered_kw: float, at: str = "", members: dict[str, dict[str, float]] | None = None) -> dict[str, Any] | None:
        """What a sale delivered goes onto the record, with the gap to what was promised: delivery less promise, above zero over and below zero under.
        members: each member's contract, delivery and gap in kWh, as the settlement counted them. The gaps are kept for the record only: no rule reads them, so a
        missed promise brings no reward and no penalty, and every gap is written down."""
        row = next((s for s in self.sales if s["sale"] == sale), None)
        if row is not None:
            row["delivered_kw"] = round(float(delivered_kw), 3)
            if row.get("promised_kw") is not None:        # kept beside the sales, in a list of its own: a sale's own row stays as the cover reads it
                gap = {"sale": sale, "start": row.get("start"), "promised_kw": row["promised_kw"], "delivered_kw": row["delivered_kw"], "gap_kw": round(float(delivered_kw) - float(row["promised_kw"]), 3)}
                if members:
                    gap["members"] = {str(h): {k: round(float(v), 3) for k, v in m.items()} for h, m in members.items()}
                self.gaps = [g for g in self.gaps if g.get("sale") != sale] + [gap]
            if at:
                row["delivered_at"] = str(at)[:16]                      # when the result came in: a later clearing counts this sale only if it is made after that
            self._save_sales()
        return row

    def _save_sales(self) -> None:
        if self.sales_path:
            self.sales_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.sales_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"community": self.id, "sales": self.sales, **({"gaps": self.gaps} if self.gaps else {})}, indent=1))
            tmp.replace(self.sales_path)


    def promise_sale(self, need: dict[str, Any], cap: dict[Any, float], offered: dict[Any, float], margin: float, now: str = "") -> dict[str, Any]:
        """At the clearing: no half hour is promised beyond the cover's share of what the members offered for it. The members are still asked for what the clearing gave
        them, so the difference is the cover. cap is changed in place."""
        c = {**self.cover(margin, str(need.get("window_start") or "")[:16], str(now or "")[:16]), "cut": {}}
        for sid, kw in offered.items():
            top = round(float(kw) * c["share"], 2)
            if float(cap.get(sid) or 0.0) > top + 0.005:
                c["cut"][sid] = {"from_kw": cap[sid], "to_kw": top}
                cap[sid] = top
        if c["cut"]:
            self.log("community_cover", event_id=need.get("event_id"), share=round(c["share"], 4), by=c["by"], cut=c["cut"])
        return c

    # ---- where the market calls in (market.py)
    def refuses(self, member: str, need: dict[str, Any]) -> str | None:
        """An offer at the door: the member record's word on it (2)."""
        return self.members.refuses(member, {"id": need.get("event_id"), "kind": "evening_sale", "day": str(need.get("window_start") or "")[:10], "start": need.get("window_start")})

    def fit_sale(self, need: dict[str, Any], cap: dict[Any, float], alloc: dict[str, dict[Any, float]]) -> dict[str, Any]:
        """After the clearing (5): each half hour sold is checked against the utility's limit at the connection, on what the meter is expected to read and what the shared
        battery is planned to give. A sale that would break it is cut to fit, and each member's part of that half hour with it. cap and alloc are changed in place."""
        rec: dict[str, Any] = {"limit_out_kw": self.limit_out_kw, "limit_in_kw": self.limit_in_kw, "checked": 0, "not_checked": [], "cut": {}}
        for s in need.get("slots") or []:
            sid, t0 = s["id"], str(s.get("start") or "")[:16]
            quarters = [t0, beckn.add_minutes(t0, STEP_MIN)] if TIME.match(t0) else []
            seen = [(t, self.meter.expected(t)) for t in quarters]
            if not seen or any(v is None for _, v in seen):
                rec["not_checked"].append(sid)                         # no meter to go by for this half hour: said, not guessed
                continue
            rec["checked"] += 1
            was = float(cap.get(sid) or 0.0)
            fits = [fit(v, self.battery_kw.get(t, 0.0), was, self.limit_out_kw, self.limit_in_kw) for t, v in seen]
            for (t, _), f in zip(seen, fits):
                if f["cut"] and "battery_kw" in f["cut"]:
                    self.battery_kw[t] = f["battery_kw"]
            now = min(f["sale_kw"] for f in fits)
            if now < was - 0.005:
                cap[sid] = round(now, 2)
                for h in list(alloc):
                    if sid in alloc[h]:
                        alloc[h][sid] = round(alloc[h][sid] * now / was, 3)
                        if alloc[h][sid] < 0.05:        # as the clearing has it: under 0.05 kW nobody is asked
                            del alloc[h][sid]
                    if not alloc[h]:
                        del alloc[h]
                rec["cut"][sid] = {"from_kw": round(was, 2), "to_kw": round(now, 2), "why": "the utility's limit at the connection"}
        if rec["cut"] or rec["not_checked"]:
            self.log("community_limit", event_id=need.get("event_id"), cut=rec["cut"], not_checked=rec["not_checked"], limit_out_kw=self.limit_out_kw)
        return rec


    def view(self) -> dict[str, Any]:
        return {"id": self.id, "point": self.point, "limit_out_kw": self.limit_out_kw, "limit_in_kw": self.limit_in_kw, "solar_kw": self.solar_kw,
                "battery": None if self.battery is None else {"rating_kw": self.battery.rating_kw, "energy_kwh": self.battery.energy_kwh, "out_factor": self.battery.out_factor, "in_factor": self.battery.in_factor,
                                                              "soc_pct": self.soc_pct, "run_by_agent": self.battery.run_by_agent, "quarter_hours_run": len(self.battery_ran), "gaps": len(self.engine.gaps) if self.engine else 0},
                "meter": {"readings": len(self.meter.kw), "last": max(self.meter.kw) if self.meter.kw else None}, "members": self.members.view(),
                "refused": dict(self.refusals), "report_rows": len(self.report), "report_when_ended": self.report_ended, "aggregator": self.aggregator, "aggregator_key_on_file": bool(self.aggregator_key),
                "requests": [{k: v for k, v in r.items() if k != "digest"} for r in self.requests[-20:]], "battery_ran": list(self.battery_ran[-200:]), "report_rows_sent_up": self.sent_up, "report_rows_waiting": len(self.outbox), "fed": {"battery_steps": len(self.battery_kw), "soc_steps": len(self.soc), "price_steps": len(self.prices), "expected_steps": len(self.meter.told)}, "sales_on_record": len(self.sales), "last_sales": self.sales[-LAST:]}


def define(d: Any, members_path: str | Path | None = None, log: Callable[..., None] | None = None, sales_path: str | Path | None = None, asked_path: str | Path | None = None) -> Community:
    """A community from its definition: {"id", "point", "limit_out_kw", and where there are any: "limit_in_kw", "battery": {"rating_kw", "energy_kwh", "out_factor", "in_factor"},
    "solar_kw", "meter": {time: kW}, "members": [what Members.enrol takes], "report_when_ended": true on a real clock, "aggregator": {"id": its name on the network,
    "public_key": its key where the enrolment gives one}}. A definition that doesn't hold is an error, not a guess."""
    if not isinstance(d, dict):
        raise ValueError("the community's definition is a set of named fields")
    cid, point = d.get("id"), str(d.get("point") if d.get("point") is not None else "")
    if not (isinstance(cid, str) and ID.match(cid)) or not ID.match(point):
        raise ValueError("a community has an id and the point of the grid it sits on")
    if not (number(d.get("limit_out_kw")) and d["limit_out_kw"] > 0) or d.get("limit_in_kw") is not None and not (number(d["limit_in_kw"]) and d["limit_in_kw"] > 0):
        raise ValueError("a community has the limit at its connection: what it may send out, in kW, and what it may draw if the utility gives one")
    bat = d.get("battery")
    if bat is not None:
        if not isinstance(bat, dict) or not (number(bat.get("rating_kw")) and bat["rating_kw"] > 0 and number(bat.get("energy_kwh")) and bat["energy_kwh"] > 0) \
                or not all(number(bat.get(k, 1.0)) and 0 < bat.get(k, 1.0) <= 1 for k in ("out_factor", "in_factor")):
            raise ValueError("the members' batteries have a rating in kW, their energy in kWh, and the shares that reach the grid on the way out and the cells on the way in, above 0 and at most 1")
        if bat.get("run_by_agent") not in (None, True, False) or bat.get("run_by_agent") and float(bat.get("in_factor", 1.0)) != 1.0:
            raise ValueError("the members' batteries are held by the community agent or not, and where they are, nothing is lost on the way in (ENGIE's record shows no loss there)")
        bat = Battery(float(bat["rating_kw"]), float(bat["energy_kwh"]), float(bat.get("out_factor", 1.0)), float(bat.get("in_factor", 1.0)), bool(bat.get("run_by_agent")))
    if not amount(d.get("solar_kw", 0.0)):
        raise ValueError("solar is a size in kW")
    if not isinstance(d.get("report_when_ended", False), bool):
        raise ValueError("report_when_ended is yes or no")
    agg = d.get("aggregator")
    if agg is not None and not (isinstance(agg, dict) and not set(agg) - {"id", "public_key"} and isinstance(agg.get("id"), str) and ID.match(agg["id"])
                                and (agg.get("public_key") is None or isinstance(agg["public_key"], str) and KEY.match(agg["public_key"]))):
        raise ValueError("an aggregator is its id on the network and, where the enrolment gives one, its public key")
    c = Community(cid, point, float(d["limit_out_kw"]), None if d.get("limit_in_kw") is None else float(d["limit_in_kw"]), bat, float(d.get("solar_kw", 0.0)),
                  members=Members(point, members_path), log=log or (lambda *a, **k: None), report_ended=d.get("report_when_ended", False),
                  aggregator=None if agg is None else agg["id"], aggregator_key=None if agg is None else agg.get("public_key"))
    if sales_path:
        c.sales_path = Path(sales_path)
        if c.sales_path.exists():
            kept = json.loads(c.sales_path.read_text())
            c.sales, c.gaps = list(kept.get("sales") or []), list(kept.get("gaps") or [])
    if asked_path:
        c.asked_path = Path(asked_path)
        c._load_asked()
    for t, v in (d.get("meter") or {}).items():
        c.meter.add(t, v)
    for m in d.get("members") or []:
        if m.get("member") not in c.members.rows:
            c.members.enrol(m["member"], connects_at=str(m.get("connects_at", point)), devices=m.get("devices") or [], sales=m.get("sales") or ("evening_sale",), pay_share=m.get("pay_share"),
                            at=str(m.get("at") or ""))
    return c


def for_agent(cfg: dict[str, Any], state_dir: str | Path | None, log: Callable[..., None]) -> Community | None:
    """The community this agent stands for, from its config (key "community"), or None when the config defines none."""
    if not cfg.get("community"):
        log("community_not_defined", why="the config defines no community")
        return None
    c = define(cfg["community"], Path(state_dir) / "community_members.json" if state_dir else None, log, Path(state_dir) / "community_sales.json" if state_dir else None,
               Path(state_dir) / "community_requests.json" if state_dir else None)
    log("community", **{k: v for k, v in c.view().items() if k in ("id", "point", "limit_out_kw", "limit_in_kw")}, members=len(c.members.rows))
    return c

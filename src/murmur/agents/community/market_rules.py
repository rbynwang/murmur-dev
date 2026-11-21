"""The market's checks and arithmetic that need no state: what an offer or an order may say, an offer's firm part, and an evening's rebound at a delivery level."""
from __future__ import annotations

from typing import Any
from murmur.protocol import envelope as beckn
from murmur.settlement import meter_check as mc


SLOT_H = beckn.SLOT_MINUTES / 60


MAX_CONFIDENCE = 0.9 * 1.2          # a home's confidence: 0.9 x sensor health x reputation (reputation is capped at 1.2)


PARTS = ("battery_kw", "ev_pause_kw", "ac_kw", "light_kw", "app_kw")   # what an offer's kW is made of


DEPOSIT_SHARE = 0.10                # our choice, no real rule exists: a deposit is this share of the energy it holds, at the order's price


READINGS_DUE_MIN = 45               # after the window: the nodes' batches have gone (report_rule.HOLD_MIN)


READINGS_CHASE_AFTER_MIN = 60       # after the window: past the nodes' batches, which go 45 minutes after their last reading


READINGS_CHASE_EVERY_MIN = 30       # between two rounds of asking. After READINGS_CHASES rounds each gap doubles, so a node that's gone isn't asked 48 times a day


CALL_HOLD_S = 30.0                  # a live call for offers waits this long at most for a second buyer's order


READINGS_CHASES = 3                 # rounds of asking before the buyers are told to settle on less than was sold


READINGS_EXTRA_MIN = 240            # however busy the inbox stays, this long past readings_wait_minutes it goes ahead


BUILDING_FIRM_SHARE = 0.534         # the firm share of what a building sheds, where its offer gives none


POOL_HEADROOM = 0.9                 # the pool is short when the order and its margin would take more than this share of the offers: a home asked for nearly all it offered can go
                                    # over its comfort limit when people come home (asked for 96 % or more of its offer), and at 79 % of the pool it stays inside


ROUND2_MIN_SHARE = 0.01             # short by less than this share of the order: not worth asking the model again


ROUND2_BEFORE_MIN = 90              # the second round goes out when all offers are in, or this long before the clearing's deadline: five model answers take about 90 sim minutes live


CENT = 0.01                         # a buyer's sums and the community agent's agree to this. On a real day they agree to the last digit


def whole(v: Any) -> bool:
    """A whole number. True is an int to Python, and to a slot's id it would be slot 1."""
    return isinstance(v, int) and not isinstance(v, bool)


def firm_part(o: dict[str, Any], x: dict[str, Any]) -> float:
    """kW of this offer slot that is firm. The node's own estimate comes first. Without one, stored energy is firm and the rest is
    tentative, except for a building's signed-off firm share of what it sheds."""
    kw = float(x.get("kw_offered") or 0.0)
    if x.get("firm_kw") is not None:
        return max(0.0, min(kw, float(x["firm_kw"])))
    stored = min(kw, float(x.get("battery_kw") or 0.0))
    return stored + (kw - stored) * (BUILDING_FIRM_SHARE if o.get("node") == "building" else 0.0)


def _evening_bad(e: Any, top: float) -> bool:
    """An evening the rebound guard can't add up. Each row has the same steps, and at least one: with none the guard looks at nothing, for every node in the sale. top: this node's
    nameplate, or a number that says nothing. One curve past it would fill the guard's whole evening and take the sale's batteries down with it."""
    cf = e.get("import_cf_kw") if isinstance(e, dict) else None
    curves = e.get("rebound_kw") if isinstance(e, dict) else None
    if not isinstance(cf, list) or not cf or (isinstance(curves, dict) and not (curves and all(_fraction(k) for k in curves))):
        return True
    rows = [cf, e.get("import_noev_kw")] + (list(curves.values()) if isinstance(curves, dict) else [curves])
    return not all(isinstance(r, list) and len(r) == len(cf) and all(mc.sane(q) and abs(q) <= top for q in r) for r in rows)


def _fraction(k: Any) -> bool:
    """A delivery level the guard can place: _rebound_at reads these keys as numbers."""
    try:
        return 0.0 <= float(k) <= 1.0
    except (TypeError, ValueError):
        return False


def offer_problem(o: Any, slots: Any = None, rated: float | None = None) -> str | None:
    """Why this offer can't go in the pool, or None. One node's bad numbers would otherwise reach everyone: a negative offer sells nothing for the whole community, a NaN spreads through the
    book, and a slot the sale doesn't have stops the clearing, and the honest offers with it. It takes one node's key to send one, so nothing past this line may need anyone to be honest.
    slots: the sale's half hours. rated: this node's nameplate, where it's on file."""
    good = lambda v: mc.sane(v) and v >= 0      # noqa: E731

    def when(v: Any) -> bool:
        try:
            return bool(beckn.add_minutes(v, 0))
        except (TypeError, ValueError):
            return False
    if not isinstance(o, dict) or not isinstance(o.get("slots"), list) or not o["slots"]:
        return "no slots"
    for x in o["slots"]:
        if not isinstance(x, dict) or not whole(x.get("id")) or not good(x.get("kw_offered")):
            return "a slot without a real id and kW"
        if slots is not None and x["id"] not in slots:
            return f"a slot this sale doesn't have: {x['id']}"
        if any(x.get(k) is not None and not good(x[k]) for k in PARTS + ("firm_kw", "tentative_kw")):
            return "a slot with a part that isn't a real kW"
    if len({x["id"] for x in o["slots"]}) != len(o["slots"]):
        return "the same slot twice"
    if not good(o.get("confidence")) or not good(o.get("energy_kwh")):
        return "no real confidence or energy"
    held = o.get("held_back_kw")
    if held is not None and not (isinstance(held, dict) and all(good(v) for v in held.values())):
        return "a held-back figure that isn't a real kW"
    top = mc.TOP if rated is None else rated
    if o.get("evening") is not None and _evening_bad(o["evening"], top):
        return "an evening the rebound guard can't read"
    f = o.get("ev_flex")
    if f is not None and not (isinstance(f, dict) and good(f.get("kwh")) and good(f.get("max_kw")) and 0 < f["max_kw"] <= top and f["kwh"] <= 48 * f["max_kw"]
                              and when(f.get("latest_finish")) and (not f.get("arrival") or when(f["arrival"]))):
        return "a car the evening's restart can't place"    # at no power its charge never ends, and the clearing would wait for it forever
    return None


def need_problem(n: dict[str, Any], deposit: Any = None) -> str | None:
    """Why this order can't open a sale or join one, or None. The tick reads every need each second and the book every kW and price in it, so what's wrong here would stop the market,
    and on a shared window the honest order with it. A number is a real one or the order stays out. It's the door the offers have: a buyer can't be asked to be honest either."""
    rows = n["slots"]
    if not isinstance(n["event_id"], str) or not n["event_id"] or not isinstance(n["offer_id"], str):
        return "no id that can be read"
    if [s["id"] for s in rows] != list(range(len(rows))) or not rows:
        return "half hours that aren't numbered from 0"     # a slot's start is worked out from its id, and two with one id would share a start
    for s in rows:
        if not mc.sane(s["kw_requested"]) or s["kw_requested"] < 0:
            return "a kW that isn't real"
        if not mc.sane(s["price"]) or s["price"] <= 0:
            return "a price that isn't real"
        if not mc.sane(s["penalty"]) or s["penalty"] < 0:
            return "a penalty that isn't real"
    if not isinstance(n.get("currency"), str) or not isinstance(n.get("name"), str):
        return "a name or a currency that can't be read"
    return None if deposit is None or (mc.sane(deposit) and deposit >= 0) else "a deposit that isn't real"


def _rebound_at(curves: dict[str, list[float]] | list[float], frac: float) -> list[float]:
    """A home's evening rebound for delivering `frac` of its battery offer, interpolated between the delivery
    levels it forecast (0 % = no rebound)."""
    if isinstance(curves, list):
        return [frac * x for x in curves]
    pts = [(0.0, [0.0] * len(next(iter(curves.values()))))] + sorted((float(k), v) for k, v in curves.items())
    for (f0, c0), (f1, c1) in zip(pts, pts[1:]):
        if frac <= f1 + 1e-9:
            w = 0.0 if f1 == f0 else (frac - f0) / (f1 - f0)
            return [a + w * (b - a) for a, b in zip(c0, c1)]
    return pts[-1][1]


UP_REQUEST, UP_ANSWER, UP_REPORT = "community.request", "community.answer", "community.report"      # the kinds between a community and the level above it


def community_id(text: str) -> bool:
    from murmur.agents.community.community import ID
    return bool(ID.match(text))

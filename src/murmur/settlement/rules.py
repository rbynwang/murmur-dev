"""Measurement and settlement, by the published rules in force: baselines from the last 10 days of the same kind, the same-day adjustment,
pay by measured delivery per class of device (the price book's shares), and what the community agent and the aggregator keep.

baseline_rule, pay_rule, bill_rule and policy_rule say which rule is in force. A signed record states its rule from them.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

_BOOK: dict[str, Any] | None = None


def price_book() -> dict[str, Any]:
    global _BOOK
    if _BOOK is None:
        from murmur.config import data_path
        _BOOK = json.loads(data_path("devices/price_book.json").read_text())
    return _BOOK


def baseline_rule() -> str:
    """The baseline in force, as a record states it."""
    lift = ", plus the meter's load in the hour starting 2 hours before the event, above its baseline for that hour" if price_book().get("same_day_adjustment") else ""
    return f"mean of the last 10 days of the same kind, weekday or weekend, that aren't holidays or event days{lift}"


def catalog_terms(catalog: dict[str, Any]) -> dict[str, Any]:
    """A buyer's catalog as it goes out. The dataset's catalog names the DEG demand-flex policy, whose cap at the offer and shortfall penalty are off here,
    and its offers are signed on every step of a sale, so each offer says what is in force: the change to the policy, the price as the most a kWh can
    cost, and the baseline's method."""
    for o in catalog["offers"]:
        a = o["offerAttributes"]
        a["contractAttributes"]["policy"]["changed"] = "cap at the offer and shortfall penalty off" + ("" if keeps() is None else f"; each kWh billed at the price x its class's share / {1 - keeps():g}")
        if o.get("descriptor", {}).get("shortDesc"):
            o["descriptor"]["shortDesc"] = up_to() + o["descriptor"]["shortDesc"]
        for side in a["inputs"]:
            if side["role"] == "buyer":
                side["inputs"]["baselineMethodology"] = {"lastOf": 10, "sameKind": True, "sameDayAdjustment": bool(price_book().get("same_day_adjustment"))}
    return catalog


def keeps() -> float | None:
    """The part of a bill that doesn't go to the nodes, from the price book (coordinator_keeps). None: a book that states none, where a buyer pays the one price."""
    k = price_book().get("coordinator_keeps")
    return None if k is None else float(k)


def kept_split() -> dict[str, float] | None:
    """Who the kept part of a bill goes to, where the price book says so: {"community_operator": its share of the bill, "aggregator": its share of the bill}.
    The two add up to coordinator_keeps. None: a book that names one keeper, the community agent.
    The community's operator runs the community agent; the aggregator (such as ENGIE) is a role of its own, and one company may hold both."""
    s = price_book().get("kept_split")
    if not s:
        return None
    s = {str(k): float(v) for k, v in s.items()}
    k = keeps()
    if k is None or set(s) != {"community_operator", "aggregator"} or abs(sum(s.values()) - k) > 1e-9:
        raise ValueError("price book: kept_split names community_operator and aggregator, and their shares add up to coordinator_keeps")
    return s


def kept_words(k: float) -> str:
    """Who keeps the part of a bill that doesn't go to the nodes, in words."""
    s = kept_split()
    return f"the coordinator keeps {k:g} of the bill" if s is None else f"{k:g} of the bill is kept: {s['community_operator']:g} by the community's operator and {s['aggregator']:g} by the aggregator"


def keep_words() -> str:
    """What follows a node's share in any rule the market states."""
    k = keeps()
    return "The coordinator keeps the rest" if k is None else f"The buyer pays that divided by {1 - k:g}, so {kept_words(k)}"


def up_to() -> str:
    """What goes before a price wherever one is shown: under each class's rate the order's price is the most a kWh can cost."""
    return "up to " if keeps() is not None else ""


def class_rule() -> str:
    """share_out's rule, as a contract and a payment state it."""
    x = price_book()["x"]
    return (f"the order's price on each measured kWh a node delivered, times its class's share: home battery or two-way car {x['home_battery']:g}, building {x['building']:g}, "
            f"any other home device {x['home_other']:g}. {keep_words()} (devices/price_book.json)")


def pay_rule() -> str:
    """How a node's pay follows from its delivery, in the rules in force: class_rule."""
    return class_rule()


def bill_rule() -> str:
    """What a buyer pays, as an order, a settlement and a model's facts state it."""
    k = keeps()
    if k is None:
        return "the order's price on every measured kWh"
    x = {c: f"{v / (1 - k):g}" for c, v in price_book()["x"].items()}
    return (f"each measured kWh at its class's own rate, the order's price times {x['home_battery']} for a home battery or two-way car, {x['building']} for a building and "
            f"{x['home_other']} for any other home device, so the order's price is the most a kWh can cost and {kept_words(k)}")


def policy_rule() -> str:
    """What a settlement is worked out under."""
    port = "beckn/DEG specification/policies/demand-flex-contractpolicy.rego (ported)"
    return f"{port}, with its cap and penalty off: paid for all that was delivered, stopping at the capacity sold only in a half hour a call covers. The bill: {bill_rule()}"


def similar_days(event_day: date, event_days: set[date], n: int = 10, max_back: int = 70) -> list[date]:
    """ISO-NE's last 10-of-10: the last n days of the same type (weekday or weekend), no holiday, no event, newest first."""
    from murmur.config import dataset_meta
    first = date.fromisoformat(dataset_meta().get("baseline_from", "2026-05-11"))     # the dataset's first full day after its warm-up
    days, k, hol, wk = [], 0, baseline_holidays(), event_day.weekday() >= 5
    while len(days) < n and k < max_back:
        k += 1
        d = event_day - timedelta(days=k)
        if d < first:
            break
        if d in hol or d in event_days or (d.weekday() >= 5) != wk:
            continue
        days.append(d)
    return days


BASELINE_REACH, BASELINE_THIN = 45, 5              # how far back the days of a fall-back baseline are looked for, and under how many days a baseline is flagged
TEN_CLEAN = "10 clean days of the same kind"
SAME_KIND = "clean days of the same kind in the last 45: fewer than 10"
ANY_KIND = "clean days of any kind in the last 45: none of the same kind"
SALE_DAYS = "sale days of the same kind in the last 45, with what was recorded as delivered added back: no clean day"
NO_BASELINE = "no baseline: no day in the last 45 to measure against"


def baseline_days(event_day: date, event_days: set[date]) -> dict[str, Any]:
    """The days a baseline rests on, and the rule that chose them. With 10 clean days of the same kind in reach it is similar_days. When nearly every weekday is a
    sale day there are none, and a baseline on no days would be 0 kW: nothing would count as delivered and nobody would be paid, without a word. So, in this order
    and flagged each time: the clean days of the same kind in the last 45; then the clean days of any kind in those 45; then the sale days of the same kind, to whose
    use the amount recorded as delivered is added back (add_back); then none, which the settlement says and holds on."""
    from murmur.config import dataset_meta
    days = similar_days(event_day, event_days)
    if len(days) >= 10:
        return {"days": days, "rule": TEN_CLEAN, "flag": False, "add_back": False}
    first, hol, wk = date.fromisoformat(dataset_meta().get("baseline_from", "2026-05-11")), baseline_holidays(), event_day.weekday() >= 5
    back = [d for d in (event_day - timedelta(days=k) for k in range(1, BASELINE_REACH + 1)) if d >= first and d not in hol]
    for rule, pick in ((SAME_KIND, [d for d in back if d not in event_days and (d.weekday() >= 5) == wk]), (ANY_KIND, [d for d in back if d not in event_days]),
                       (SALE_DAYS, [d for d in back if d in event_days and (d.weekday() >= 5) == wk])):
        if pick:
            return {"days": pick[:10], "rule": rule, "flag": True, "add_back": rule == SALE_DAYS}
    return {"days": [], "rule": NO_BASELINE, "flag": True, "add_back": False}


def mean_of_days(usage_by_day: dict[date, list[float]], days: list[date]) -> dict[str, Any]:
    """A baseline from the days given: each half hour's mean over the days that have a reading."""
    days = [d for d in days if d in usage_by_day]
    if not days:
        return {"per_slot": [], "days": []}
    n = len(usage_by_day[days[0]])
    return {"per_slot": [round(sum(usage_by_day[d][j] for d in days) / len(days), 3) for j in range(n)], "days": [d.isoformat() for d in days], "candidates": len(days)}


def ten_of_ten(usage_by_day: dict[date, list[float]], event_day: date, event_days: set[date]) -> dict[str, Any]:
    """The baseline on the last 10 days of the same kind (similar_days)."""
    return mean_of_days(usage_by_day, similar_days(event_day, event_days))


def adjusted(base: float, pre_kw: float | None, pre_base: float | None) -> float:
    """The same-day adjustment (Massachusetts Targeted Dispatch; PJM's and ISO-NE's baselines have one too): the node's load in
    the hour starting 2 hours before the event, above its baseline for that hour, is added. Never negative."""
    if not price_book().get("same_day_adjustment") or pre_kw is None or pre_base is None:
        return base
    return base + clamp0(float(pre_kw) - float(pre_base))


def node_class(name: str, building: bool = False) -> str:
    return "datacenter" if str(name).startswith("dc-") else "building" if building else "home_other"


def meter_kwh(m: dict[Any, dict[str, float]], hours: float, cap: dict[Any, float] | None = None,
              building: bool = False, name: str = "") -> tuple[dict[str, float], dict[str, float]]:
    """Per slot: (kWh delivered, kWh the node itself is paid for at the order's price: its share of it).
    cap: a building's kW per slot."""
    b = price_book()
    rest, batt = {}, {}
    capk = {str(k): float(v) for k, v in (cap or {}).items()}
    for i, v in m.items():
        if "BASELINE" not in v or "USAGE" not in v:
            continue
        batt[str(i)] = clamp0(float(v.get("BATT") or 0.0))
        x = float(v["BASELINE"]) - float(v["USAGE"]) - batt[str(i)]
        if str(i) in capk:                         # the cap is on the whole meter: a campus battery counts inside it, not on top
            batt[str(i)] = min(batt[str(i)], capk[str(i)])
            x = min(x, capk[str(i)] - batt[str(i)])
        rest[str(i)] = x
    if sum(rest.values()) < 0:                     # a negative event pays nothing (the season's average never goes below 0)
        rest = {k: 0.0 for k in rest}
    xr = float(b["x"][node_class(name, building)])
    xb = xr if building else float(b["x"]["home_battery"])     # a building's battery earns the business rate, as in Massachusetts
    return ({k: (batt[k] + rest[k]) * hours for k in rest}, {k: (batt[k] * xb + rest[k] * xr) * hours for k in rest})


def trim_called(val: dict[str, tuple[dict[str, float], dict[str, float]]], capped: dict[Any, float], hours: float) -> None:
    """In a half hour a call covers the booking pays only up to the capacity sold (deg_settle's capped), so each node's booked kWh there
    shrink by the same factor. Its part of the call is paid under the call."""
    for sid, kw in (capped or {}).items():
        tot = sum(v[0].get(str(sid), 0.0) for v in val.values()) / hours
        if tot > float(kw) > 0:
            f = float(kw) / tot
            for v in val.values():
                for d in v:
                    if str(sid) in d:
                        d[str(sid)] *= f


def to_ten_thousandths(per: dict[str, float], total: float) -> dict[str, float]:
    """Each share rounded to $0.0001 so that the shares add up to `total` rounded the same way: as plain rounding gives them when it
    already does, else the ten-thousandths rounding left over (or took too many) go to (or come from) the shares it moved most, ties
    broken by name. So a split never loses a fraction of a cent, nor pays one twice."""
    plain = {h: round(v, 4) for h, v in per.items()}
    want = round(total * 10000)
    if round(sum(plain.values()) * 10000) == want:
        return plain
    units = {h: math.floor(v * 10000 + 1e-9) for h, v in per.items()}
    left = want - sum(units.values())
    frac = {h: round(v * 10000 - units[h], 6) for h, v in per.items()}      # to a millionth: equal shares tie however the floats fell, and go by name
    order = sorted(per, key=lambda h: (-frac[h], h)) if left > 0 else sorted(per, key=lambda h: (frac[h], h))
    for h in order[:abs(left)]:
        units[h] += 1 if left > 0 else -1
    return {h: units[h] / 10000 for h in per}


def within(per: dict[str, float], bill: float) -> dict[str, float]:
    """No split pays out more than its bills brought in. A full price the bills don't bear out could ask for it: a buyer's word, or a copy of the meters short of what the split reads."""
    pool = sum(per.values())
    return per if pool <= bill else {h: v * bill / pool for h, v in per.items()}


def share_out(seller: float, full: float, val: dict[str, tuple[dict[str, float], dict[str, float]]]) -> dict[str, Any]:
    """seller: the bills. full: the same kWh at the order's price. Each node's pay is that price, read as full over the kWh, times its class's share, so a change in the
    bill can't move it. The rest of the bill is kept: coordinator_keeps of it, when the buyers' meters are the ones the split reads."""
    kwh = sum(sum(v[0].values()) for v in val.values())
    rate = full / kwh if kwh > 0 else 0.0
    scaled = within({h: sum(v[1].values()) * rate for h, v in val.items()}, seller)
    per = {h: round(v, 4) for h, v in scaled.items()}
    if sum(per.values()) > seller + 1e-9:            # rounding up past a short bill: the bill, to the ten-thousandth below it, is all there is
        per = to_ten_thousandths(scaled, math.floor(seller * 10000 + 1e-9) / 10000)
    pool = sum(per.values())
    return {"pool": round(pool, 4), "fee": round(seller - pool, 4), "per_home": per, "usd_per_kwh": round(rate, 4),
            "rule": class_rule()}


def baseline_holidays() -> set[date]:
    """The holidays a baseline skips: the dataset's own list (dataset.json)."""
    from murmur.config import dataset_meta
    return {date.fromisoformat(d) for d in dataset_meta().get("holidays", [])}


def clamp0(x: float) -> float:
    return x if x >= 0 else 0.0


def deg_settle(slots: list[dict[str, Any]], offered: dict[int, float], meters: dict[str, dict[int, dict[str, float]]],
               hours: float = 0.5, currency: str = "USD",
               caps: dict[str, dict[int, float]] | None = None,
               share: dict[Any, float] | None = None, capped: dict[Any, float] | None = None) -> dict[str, Any]:
    """slots: [{id, price}]; offered: {slot_id: kW}, shown on each row; meters: {meter: {slot_id: {BASELINE, USAGE, BATT}}}, BATT where a battery gave.
    caps: {meter: {slot_id: kW}}, the building nodes: the most each one's measured reduction counts in a half hour (BUILDING_CAP_X x its commitment, see
    building_counted_kwh), at the building's share. The homes have none.
    share: {slot_id: 0-1}, this buyer's part of what the pool delivered, when two buyers' orders fill from one pool (the community agent's clearing).
    Each buyer settles its own part on the same meters, so no kWh is paid for twice.
    capped: {slot_id: kW}, the half hours a call covers: the booking stops at the capacity sold, because the call pays for what's beyond it.
    Every kWh delivered is paid for, with no cap at the offer and no penalty: `total` is the bill, each kWh at its class's rate, and `full_price_usd` the
    same kWh at the slot's price."""
    rows, total, full = [], 0.0, 0.0
    keep = keeps()
    caps = caps or {}
    part = {str(k): float(v) for k, v in (share or {}).items()}
    lim = {str(k): float(v) for k, v in (capped or {}).items()}
    per = {n: meter_kwh(m, hours, caps.get(n), n in caps, n) for n, m in meters.items()}
    for s in slots:
        i = s["id"]
        k = part.get(str(i), 1.0)
        off = float(offered.get(i, 0.0))
        delivered = sum(p[0].get(str(i), 0.0) for p in per.values()) / hours
        cut = lim[str(i)] / delivered if str(i) in lim and delivered > lim[str(i)] else 1.0     # each class by the same factor, as trim_called does
        delivered = k * (min(delivered, lim[str(i)]) if str(i) in lim else delivered)
        pay = delivered * hours * s["price"]
        full += pay
        if keep is not None:                       # the nodes' part of the half hour, over what they're left of the bill
            pay = k * cut * sum(p[1].get(str(i), 0.0) for p in per.values()) * s["price"] / (1.0 - keep)
        total += pay
        rows.append({"id": i, "price": s["price"], "offered": round(off, 3), "delivered": round(delivered, 3),
                     "eligible": round(delivered, 3), "pay": round(pay, 4), "penalty": 0.0, "net": round(pay, 4)})
    flows = [{"role": "buyer", "value": round(-total, 4), "currency": currency},
             {"role": "seller", "value": round(total, 4), "currency": currency}]
    return {"components": rows, "total": round(total, 4), "revenue_flows": flows,
            "net_zero_ok": abs(sum(f["value"] for f in flows)) < 1e-9,
            "policy": policy_rule(), "full_price_usd": round(full, 4)}


def call_shares(full_usd: float, by_home_kwh: dict[str, float], batt_kwh: dict[str, float], buildings: set[str], bill_usd: float | None = None) -> dict[str, Any]:
    """A call's payment on the price book: each node's kWh at the call's price, times its class's share, stored energy at the battery
    share, a building at its own. full_usd: the call's kWh at its price. bill_usd: what its buyer pays (call_bill), and the difference is kept, as in the booking."""
    b = price_book()["x"]
    bill = full_usd if bill_usd is None else bill_usd
    kwh = sum(float(v) for v in by_home_kwh.values())
    rate = full_usd / kwh if kwh > 0 else 0.0
    per = {}
    for h, v in by_home_kwh.items():
        v = float(v)
        if h in buildings:
            per[h] = v * float(b["building"]) * rate
        else:
            s = min(v, clamp0(float(batt_kwh.get(h, 0.0))))
            per[h] = (s * float(b["home_battery"]) + (v - s) * float(b["home_other"])) * rate
    per = within(per, bill)
    pool = sum(per.values())
    return {"pool": round(pool, 4), "fee": round(bill - pool, 4), "per_home": to_ten_thousandths(per, pool),
            "usd_per_kwh": round(rate, 4), "rule": f"the call's price on what each node added, times its class's share. {keep_words()} (price_book.json)"}


def call_bill(full_usd: float, by_home_kwh: dict[str, float], batt_kwh: dict[str, float], buildings: set[str]) -> float:
    """What a call costs its buyer: what call_shares gives its nodes, over what they're left of the bill. So the keep holds even where a half hour's kWh went to no node."""
    k = keeps()
    return full_usd if k is None else round(call_shares(full_usd, by_home_kwh, batt_kwh, buildings)["pool"] / (1.0 - k), 4)


def deposit_statement(total_usd: float, held_usd: float) -> dict[str, float]:
    """A buyer's deposit against its bill. It held tentative power, so it counts toward what the buyer owes. If the bill is smaller the rest goes back: credited and refunded
    always add up to what was held. The sellers' money doesn't change: they are paid on what was delivered. A deposit is set at the order's price and a bill at each class's
    rate, so on a poor delivery of cheap kWh it can pass the bill, and then nothing is due."""
    held = clamp0(float(held_usd))
    used = min(held, clamp0(float(total_usd)))
    return {"held_usd": round(held, 4), "credited_usd": round(used, 4), "refund_usd": round(held - used, 4),
            "still_due_usd": round(float(total_usd) - used, 4)}


BUILDING_CAP_X = 1.2     # a building counts at most this times its commitment in the split (the reputation's cap)


def building_counted_kwh(meter: dict[Any, dict[str, float]], committed_kw: dict[Any, float], hours: float = 0.5) -> float:
    """A building node's measured delivery as the program counts it: in each half hour its reduction against the
    baseline, at most BUILDING_CAP_X x what it committed for that half hour. A building's baseline can rest on days
    without its own routine evening cut, so uncapped that routine would count as far more than it delivered.
    meter: {slot_id: {BASELINE, USAGE}}; committed_kw: {slot_id: kW} (keys compared as strings). The same cap holds in
    the community agent's split (Market.settle), at the stand-in buyers' settlement (Utility.settle, per half hour
    through deg_settle's caps) and in their calls (GridWatch.settle: at most 1.2 x booked + dispatched)."""
    com = {str(k): float(v or 0.0) for k, v in (committed_kw or {}).items()}
    return sum(min(clamp0(v["BASELINE"] - v["USAGE"]), BUILDING_CAP_X * com.get(str(sid), 0.0)) * hours
               for sid, v in meter.items() if "BASELINE" in v and "USAGE" in v)


def split(seller_total: float, delivered_kwh: dict[str, float], fee_share: float = 0.0,
          cap_kwh: dict[str, float] | None = None) -> dict[str, Any]:
    """seller_total less its fee_share part, shared pro rata to measured delivery: a call's pay on the one-buyer path (GapSettle.settle).
    cap_kwh: participants whose measured delivery counts at most this much (a building: building_counted_kwh, its
    reduction capped at BUILDING_CAP_X x its commitment in each half hour, as the buyer counts it). A building's
    baseline can rest on days without its own routine evening cut, so uncapped that routine would take most of the
    homes' pool."""
    pool = seller_total * (1 - fee_share)
    cap_kwh = cap_kwh or {}
    counted = {h: (min(clamp0(v), clamp0(cap_kwh[h])) if h in cap_kwh else clamp0(v)) for h, v in delivered_kwh.items()}
    tot = sum(counted.values())
    pay = to_ten_thousandths({h: pool * v / tot for h, v in counted.items()}, pool) if tot > 0 else {h: 0.0 for h in counted}
    out = {"pool": round(pool, 4), "fee": round(seller_total - pool, 4), "per_home": pay,
           "rule": "pro rata to measured delivery (clamp0(BASELINE - USAGE) x hours)"}
    if cap_kwh:
        out["caps_kwh"] = {h: round(v, 3) for h, v in cap_kwh.items()}
        out["rule"] += f"; a building counts at most {BUILDING_CAP_X:g} x its commitment in each half hour"
    return out


def day_of(ts_local: str) -> date:
    return datetime.strptime(ts_local[:10], "%Y-%m-%d").date()

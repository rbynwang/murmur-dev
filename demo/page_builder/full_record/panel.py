"""The trade panel and the tables beside the sheet: what each step's recorded values set in them. A step sets the text of
some elements (x, by element id), the width of some bars (w, in % of the evening's largest kW) and the community's cells
(g, one digit a node)."""
from __future__ import annotations

from typing import Any

from ..templating import Markup, render
from .figures import first, kw, num, rng, slot0, usd
from .record import Record

PAYS = (("buyer_utility_usd", "tv-pay-util"), ("buyer_grid_operator_usd", "tv-pay-grid"), ("paid_usd", "tv-paid"), ("paid_homes_usd", "tv-paid-h"), ("paid_buildings_usd", "tv-paid-b"),
        ("coordinator_keep_usd", "tv-keep"))
SPLITS = ("asked_homes_kw", "asked_buildings_kw", "offered_homes_kw", "offered_buildings_kw")


def small(value: str, unit: str) -> Markup:
    """A figure with its unit set small."""
    return render("full_record/parts.html#small", value=value, unit=unit)


def split(x: dict[str, Any], w: dict[str, Any], what: str, a: float, b: float, unit: str, money: str = "") -> None:
    """Homes against buildings: the two bars and their two lines."""
    w["b-hom"] = round(a / (a + b) * 100, 2)
    w["b-bld"] = round(b / (a + b) * 100, 2)
    x["hb-what"] = what
    x["hb-a"] = f"Homes {money}{kw(a)}{unit}, {a / (a + b) * 100:.0f}%"
    x["hb-b"] = f"Buildings {money}{kw(b)}{unit}, {b / (a + b) * 100:.0f}%"


def values_to_state(rec: Record, s: dict[str, Any], v: dict[str, Any], st: dict[str, Any], seen: dict[str, Any]) -> None:
    """What this step's values set in the panel and the tables. `seen` holds every value recorded so far."""
    x, w = st.setdefault("x", {}), st.setdefault("w", {})
    sc = rec.scale or 1.0
    seen.update(v)
    if "asked_kw" in v:
        x["tv-asked"] = small(rng(v["asked_kw"]), "kW")
        x["co-asked"] = f'{rng(v["asked_kw"])} kW'
        w["b-asked"] = round((first(v["asked_kw"]) or 0) / sc * 100, 2)
    if ("order_utility_kw" in v or "order_grid_operator_kw" in v) and "asked_kw" not in v:
        tot = (first(seen.get("order_utility_kw")) or 0) + (first(seen.get("order_grid_operator_kw")) or 0)
        x["tv-asked"] = small(kw(tot), "kW")
        x["co-asked"] = f"{kw(tot)} kW"
        w["b-asked"] = round(tot / sc * 100, 2)
    for k, id_ in (("order_utility_kw", "c-util-kw"), ("order_grid_operator_kw", "c-grid-kw")):
        if k in v:
            x[id_] = f"{rng(v[k], 1)} kW"
    if "price_usd_per_kwh" in v:
        price = f'${num(v["price_usd_per_kwh"]):.2f} per kWh'
        x["c-util-price"], x["c-grid-price"], x["tv-price"] = price, price, f"at {price}"
    if "deposit_usd" in v:
        x["tv-deposit"] = usd(v["deposit_usd"])
    if "offers_in" in v:
        x["tv-offers"] = small(kw(v["offers_in"]), "in")
        x["co-offers-n"] = f'{kw(v["offers_in"])} of {len(rec.nodes)}'
    if "offered_kw" in v:
        x["tv-offered"] = small(rng(v["offered_kw"]), "kW")
    if "offered_firm_kw" in v or "offered_tentative_kw" in v:
        firm, tent = seen["offered_firm_kw"], seen["offered_tentative_kw"]
        x["tv-firm"] = small(rng(firm), "kW")
        x["tv-tent"] = small(rng(tent), "kW")
        w["b-firm"] = round(slot0(firm) / sc * 100, 2)
        w["b-tent"] = round(slot0(tent) / sc * 100, 2)
    if "sold_kw" in v:
        x["tv-sold"] = small(rng(v["sold_kw"]), "kW")
        w["b-sold"] = round((first(v["sold_kw"]) or 0) / sc * 100, 2)
    if "reserve_kw" in v:
        x["tv-reserve"] = small(rng(v["reserve_kw"]), "kW")
        x["co-res"] = f'{rng(v["reserve_kw"])} kW'
    if "asked_of_nodes_kw" in v:
        x["tv-nodes"] = small(rng(v["asked_of_nodes_kw"]), "kW")
    if "margin" in v:
        x["tv-margin"] = x["co-margin"] = f'{num(v["margin"]) * 100:.0f}%'
    ah, ab = seen.get("asked_homes_kw"), seen.get("asked_buildings_kw")
    h, b = (ah, ab) if ah is not None and ab is not None else (seen.get("offered_homes_kw"), seen.get("offered_buildings_kw"))
    if h is not None and b is not None and any(k in v for k in SPLITS):
        a, c = slot0(h), slot0(b)
        w["b-hom"] = round(a / (a + c) * 100, 2)
        w["b-bld"] = round(c / (a + c) * 100, 2)
        x["hb-what"] = "Asked, 1st half hour" if ah is not None else "Offered, 1st half hour"
        x["hb-a"] = f"Homes {kw(a)} kW, {a / (a + c) * 100:.0f}%"
        x["hb-b"] = f"Buildings {kw(c)} kW, {c / (a + c) * 100:.0f}%"
        x["co-hb"] = f"Homes {kw(a)} kW, buildings {kw(c)} kW"
    if "deposit_held_usd" in v:
        x["tv-dheld"] = usd(v["deposit_held_usd"])
    if "deposit_back_usd" in v:
        x["tv-dback"] = usd(v["deposit_back_usd"])
    if "accepted" in v:
        x["tv-acc"] = x["co-acc"] = f'{kw(v["accepted"])} accepted, {kw(seen.get("declined") or 0)} declined'
    delivery(rec, s, v, x, w, seen)
    settlement(rec, v, x, w, seen)


def delivery(rec: Record, s: dict[str, Any], v: dict[str, Any], x: dict[str, Any], w: dict[str, Any], seen: dict[str, Any]) -> None:
    """The half-hour columns: the monitor's live estimate in the window, then what the meters show."""
    sc, hs = rec.scale or 1.0, rec.half_hours
    if "live_kw" in v:
        k = [str(h.get("start")) for h in hs].index(str(s.get("sim_time") or "")[11:16])
        w[f"hh-{k}"] = round(num(v["live_kw"]) / sc * 100, 2)
        x[f"hhv-{k}"] = kw(v["live_kw"])
        x[f"rt-true-{k}"] = kw(v["live_kw"], 1)
        seen.setdefault("_live", {})[k] = num(v["live_kw"])
        x["tv-deliv"] = small(kw(sum(seen["_live"].values()) / 2), "kWh below the twin")
        split(x, w, "Delivering now", num(v.get("live_homes_kw")) or 0, num(v.get("live_buildings_kw")) or 0, " kW")
    if str(s.get("title") or "") == "The buyer counts each meter" and hs:
        for k, h in enumerate(hs[:6]):
            w[f"hh-{k}"] = round(num(h["delivered_kw"]) / sc * 100, 2)
            x[f"hhv-{k}"] = kw(h["delivered_kw"])
            x[f"rt-del-{k}"] = kw(h["delivered_kw"], 1)
        x["tv-deliv"] = small(kw(rec.ledger["totals"]["delivered_kwh"]), "kWh on the meters")
        split(x, w, "On the meters", sum(num(h.get("delivered_homes_kw")) or 0 for h in hs) / 2, sum(num(h.get("delivered_buildings_kw")) or 0 for h in hs) / 2, " kWh")


def settlement(rec: Record, v: dict[str, Any], x: dict[str, Any], w: dict[str, Any], seen: dict[str, Any]) -> None:
    """Readings in, what the buyers pay, what each node is paid and what the community agent keeps."""
    hs = rec.half_hours
    if "readings_in" in v:
        exp = seen["readings_expected"]
        x["tv-read"] = x["rp-read"] = f'{kw(v["readings_in"])} of {kw(exp)}'
        w["b-read"] = round(num(v["readings_in"]) / max(1.0, num(exp)) * 100, 2)
        for k, h in enumerate(hs[:6]):
            x[f"rt-read-{k}"] = f'{kw(h.get("readings"))} of {kw(h.get("readings_expected"))}'
    for k, id_ in PAYS:
        if k in v:
            x[id_] = usd(v[k])
    if "buyer_grid_operator_usd" in v or "buyer_utility_usd" in v:
        x["rp-buy"] = usd((num(seen.get("buyer_utility_usd")) or 0) + (num(seen.get("buyer_grid_operator_usd")) or 0))
        for k, h in enumerate(hs[:6]):
            x[f"rt-buy-{k}"] = usd(sum(num(y) or 0 for y in (h.get("buyer_usd") or {}).values()))
    if "paid_usd" in v:
        x["rp-pay"] = usd(v["paid_usd"])
        split(x, w, "Paid", num(seen.get("paid_homes_usd")) or 0, num(seen.get("paid_buildings_usd")) or 0, "", "$")
        for k, h in enumerate(hs[:6]):
            x[f"rt-node-{k}"] = usd(sum(num(y) or 0 for y in (h.get("nodes_usd") or {}).values()))
            x[f"rt-keep-{k}"] = usd(h.get("coordinator_keep_usd"))


def grid_state(rec: Record, v: dict[str, Any], st: dict[str, Any], seen: dict[str, Any]) -> None:
    """The community's cells, one digit a node: 0 nothing yet, 1 offered, 2 accepted, 3 paid."""
    if not any(k in v for k in ("offers_in", "accepted", "paid_usd")):
        return
    n = len(rec.nodes)
    offers = int(num(seen.get("offers_in")) or 0)
    acc = int(num(seen.get("accepted")) or 0)
    paid = n if seen.get("paid_usd") else 0
    st["g"] = "".join("3" if i < paid else "2" if i < acc else "1" if i < offers else "0" for i in range(n))

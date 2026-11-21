"""The numbers a replay page shows, as far as the story has reached: each figure of the whole picture's list, the one number
each box is known by, and the evening's table half hour by half hour. Every value comes from the recording: a step's values,
a sentence or terminal line of a step, or the ledger."""
from __future__ import annotations

import json
import re
from typing import Any

from .. import names as N
from .moments import side
from .text import first, kw, num, usd

Step = dict[str, Any]


def take_facts(s: Step, seen: dict[str, Any]) -> None:
    """Numbers a step gives in a sentence, a terminal line or per node, not under a value key: kept with what they belong to."""
    v, node, plain, title = s.get("values") or {}, str(s.get("node") or ""), str(s.get("plain") or ""), str(s.get("title") or "")
    for k in ("safe_offer_kw", "offer_kw", "contract_kw", "owed_kw"):
        if v.get(k) is not None:
            seen.setdefault(f"_{k}", {}).setdefault(node, v[k])
    if s.get("layer") == "guard" and "done" in title:
        calls = seen.setdefault("_calls", {})
        calls[node] = calls.get(node, 0) + 1
    if s.get("layer") == "device" and v.get("live_kw") is not None:
        seen.setdefault("_live", {})[str(s.get("sim_time"))[11:16]] = v["live_kw"]
    m = re.search(r"short by up to ([\d,.]+) kW", plain)
    if m:
        seen["_short"] = N.named(f"{m.group(1)} kW, {node}")
    m = re.search(r"([\d,]+) reports? reached the desk, ([\d,]+) rounds? moved power, and ([\d,]+) warnings?", plain)
    if m:
        seen["_desk"] = m.groups()
    lines = [str(x.get("text") or "") for x in s.get("terminal") or []]
    m = re.search(r"Refused here: (\d+)", " ".join(lines))
    if m:
        seen["_refused"] = m.group(1)
    m = re.search(r"Confirmed ([\d,.]+) kW", plain)
    if m:
        seen["_conf"] = seen.get("_conf", 0.0) + float(m.group(1).replace(",", ""))
    if v.get("readings_expected") is not None:
        seen["_read_exp"] = v["readings_expected"]
    for t in lines:
        m = re.match(r"asked again: (\[.*\])$", t)
        if m:
            seen["_asked_again"] = f"{len(json.loads(m.group(1).replace(chr(39), chr(34))))} nodes"
        m = re.search(r"readings are in: .*?(\d+) missing", t)
        if m:
            seen["_missing"] = m.group(1)


def _k1(v: dict[str, Any], key: str) -> str:
    x = first(v.get(key))
    return f"{kw(x)} kW" if x is not None else ""


def _nk(tab: dict[str, Any], n: Any, d: int = 2) -> str:
    x = first(tab.get(n))
    return f"{kw(x, d)} kW" if x is not None else ""


def trade_all(ev: Any, v: dict[str, Any]) -> dict[str, str]:
    """Every figure the page can show, as far as the story has reached. A figure nobody has reached yet stays out."""
    hs = ev.ledger.get("half_hours") or []
    tot = ev.ledger.get("totals") or {}
    o: dict[str, str] = {}
    ou, og = first(v.get("order_utility_kw")), first(v.get("order_grid_operator_kw"))
    if v.get("asked_kw") is not None:
        o["asked"] = _k1(v, "asked_kw")
    elif ou is not None or og is not None:
        o["asked"] = f"{kw((ou or 0) + (og or 0))} kW"
    if ou is not None:
        o["util_kw"] = f"{kw(ou)} kW"
    if og is not None:
        o["grid_kw"] = f"{kw(og)} kW"
    if num(v.get("price_usd_per_kwh")) is not None:
        o["price"] = f'${num(v["price_usd_per_kwh"]):.2f} per kWh'
        o["window"] = ev.window
    dep = tot.get("deposits") or {}
    if "deposit_usd" in v and dep:
        o["deposits"] = usd(sum(num(x.get("placed_usd")) or 0 for x in dep.values()))
    if v.get("asked_kw") is not None:
        o["members"] = str(ev.total)
    if v.get("offers_in") is not None:
        o["offers"] = f'{kw(v["offers_in"])} of {ev.total}'
    for a, b in (("offered", "offered_kw"), ("firm", "offered_firm_kw"), ("tent", "offered_tentative_kw"), ("off_h", "offered_homes_kw"),
                 ("off_b", "offered_buildings_kw"), ("sold", "sold_kw"), ("nodes", "asked_of_nodes_kw"), ("reserve", "reserve_kw")):
        if v.get(b) is not None:
            o[a] = _k1(v, b)
    for a in ("agg_watch", "agg_asked", "agg_trusted", "site_asked", "site_rows", "site_ask_cap", "site_ans_cap", "site_rep_cap",
              "site_notes", "site_notes_cap", "site_paused", "site_pause_cap"):
        if v.get(a) is not None:
            o[a] = str(v[a])
    if v.get("site_asked") is not None:                    # a step that carries the sites' figures but not their captions
        o.setdefault("site_ask_cap", "asked of the largest solar-and-battery plant at 19:00. The same signed request a community gets")
        o.setdefault("site_ans_cap", "signed, with the reason wherever it will give less. No coordinator in between")
    if v.get("site_rows") is not None:
        o.setdefault("site_rep_cap", "signed rows from the three sites, each equal to what the sharing-out expects")
    if num(v.get("margin")) is not None:
        o["margin"] = f'{num(v["margin"]) * 100:.0f}%'
    ah, ab = first(v.get("asked_homes_kw")), first(v.get("asked_buildings_kw"))
    if ah is not None and ab is not None:
        o["ask_h"] = f"{kw(ah)} kW, {ah / (ah + ab) * 100:.0f}%"
        o["ask_b"] = f"{kw(ab)} kW, {ab / (ah + ab) * 100:.0f}%"
    if num(v.get("deposit_held_usd")) is not None:
        o["dep_held"] = usd(v["deposit_held_usd"])
    if num(v.get("deposit_back_usd")) is not None:
        o["dep_back"] = usd(v["deposit_back_usd"])
    if v.get("accepted") is not None:
        o["accepted"] = kw(v["accepted"])
        o["declined"] = kw(v.get("declined") or 0)
    if v.get("_conf"):
        o["call_conf"] = f'{kw(v["_conf"], 1)} kW'
    live = v.get("_live") or {}
    for i, h in enumerate(hs[:6]):
        x = live.get(str(h.get("start")))
        if x is not None:
            o[f"hh{i}"] = f"{kw(x)} kW"
    if live:
        o["twin"] = f"{kw(sum(num(x) or 0 for x in live.values()) / 2)} kWh"
    if v.get("readings_in") is not None:
        exp = v.get("_read_exp") or v.get("readings_expected") or tot.get("readings_expected")
        o["readings"] = f'{kw(v["readings_in"])} of {kw(exp)}' if exp else kw(v["readings_in"])
        o["meters"] = str(ev.total)
        o["refused"] = str(v.get("_refused", "0"))
    _money(ev, v, tot, o)
    _nodes(ev, v, o)
    return o


def _money(ev: Any, v: dict[str, Any], tot: dict[str, Any], o: dict[str, str]) -> None:
    pu, pg = num(v.get("buyer_utility_usd")), num(v.get("buyer_grid_operator_usd"))
    if pu is not None:
        o["pay_u"] = usd(pu)
    if pg is not None:
        o["pay_g"] = usd(pg)
    if pu is not None and pg is not None:
        o["buyers_pay"] = usd(pu + pg)
    if pu is not None or pg is not None:
        if num(tot.get("sold_kwh")) is not None:
            o["sold_kwh"] = f'{kw(tot["sold_kwh"])} kWh'
        if num(tot.get("delivered_kwh")) is not None:
            o["delivered"] = f'{kw(tot["delivered_kwh"])} kWh'
    if num(v.get("paid_usd")) is not None:
        o["sellers"] = usd(v["paid_usd"])
    if num(v.get("paid_homes_usd")) is not None:
        o["homes_usd"] = usd(v["paid_homes_usd"])
    if num(v.get("paid_buildings_usd")) is not None:
        o["bld_usd"] = usd(v["paid_buildings_usd"])
    if num(v.get("coordinator_keep_usd")) is not None:
        o["keep"] = usd(v["coordinator_keep_usd"])
    if ev.sites and o.get("keep"):
        o["pay_cap"] = (f'to sellers. Of the rest, the community\'s operator keeps {usd(v["operator_keep_usd"])} and the aggregator '
                        f'{usd(v["aggregator_keep_usd"])}' if num(v.get("operator_keep_usd")) is not None
                        and num(v.get("aggregator_keep_usd")) is not None else f'to sellers. {o["keep"]} of the bill is kept')


def _nodes(ev: Any, v: dict[str, Any], o: dict[str, str]) -> None:
    desk = v.get("_desk")
    if desk:
        o["reports"], o["rounds"], o["warnings"] = desk
    safe, offer, con, owed, calls = (v.get("_safe_offer_kw") or {}, v.get("_offer_kw") or {}, v.get("_contract_kw") or {},
                                     v.get("_owed_kw") or {}, v.get("_calls") or {})
    o["home_safe"], o["home_offer"] = _nk(safe, ev.home), _nk(offer, ev.home)
    o["uni_offer"], o["other_offer"] = _nk(offer, ev.uni, 0), _nk(offer, ev.other, 0)
    o["second_safe"], o["second_offer"] = _nk(safe, ev.second), _nk(offer, ev.second)
    row = (ev.ledger.get("nodes") or {}).get(ev.home) or {}
    if o["home_safe"]:
        o["home_firm"] = f'{kw(first(row.get("firm_kw")), 2)} kW' if first(row.get("firm_kw")) is not None else ""
        o["home_tent"] = f'{kw(first(row.get("tentative_kw")), 2)} kW' if first(row.get("tentative_kw")) is not None else ""
    o["c_home"], o["c_code"], o["c_uni"], o["c_other"] = (_nk(con, ev.home), _nk(con, ev.code_home), _nk(con, ev.uni, 0),
                                                          _nk(con, ev.other, 0))
    o["short_now"] = str(v.get("_short") or "")
    o["owed_uni"], o["owed_home"] = _nk(owed, ev.uni, 0), _nk(owed, ev.home, 1)
    for k, n in (("calls_uni", ev.uni), ("calls_other", ev.other), ("calls_home", ev.home)):
        if calls.get(n):
            o[k] = str(calls[n])


def block_nums(ev: Any, steps: list[Step], v: dict[str, str]) -> dict[str, str]:
    """The one number each box is known by on the whole picture's map, from the story's own steps and ledger."""
    cnt: dict[tuple[str, str], int] = {}
    for s in steps:
        key = (str(s.get("layer")), side(s) if s.get("node") else "")
        cnt[key] = cnt.get(key, 0) + 1
    com = ev.meta.get("community") or {}
    tot = ev.ledger.get("totals") or {}
    o: dict[str, str] = {"buy-u": v.get("util_kw", ""), "buy-g": v.get("grid_kw", ""),
                         "co-market": f'{v["sold"]} sold' if v.get("sold") else ""}
    if v.get("reports"):
        o["co-desk"] = f'{v["reports"]} reports'
    if num(tot.get("messages")) is not None:
        o["town"] = f'{kw(tot["messages"])} messages'
    o["h-agent"], o["b-agent"] = f'{com.get("homes")} of {com.get("homes")} by code', f'{com.get("buildings")} of {com.get("buildings")} by code'
    for sd in "hb":
        ans, calls, writes = cnt.get(("model", sd), 0), cnt.get(("guard", sd), 0), cnt.get(("driver", sd), 0)
        o[f"{sd}-model"] = f'{ans} answer{"" if ans == 1 else "s"} shown' if ans else ""
        tools = calls + cnt.get(("tools", sd), 0)
        o[f"{sd}-tools"] = f'{tools} call{"" if tools == 1 else "s"}' if tools else ""
        o[f"{sd}-guard"] = f'{calls} passed' if calls else ""
        o[f"{sd}-seal"] = f'{writes} seal{"" if writes == 1 else "s"}' if writes else ""
        o[f"{sd}-driver"] = f'{writes} write{"" if writes == 1 else "s"}' if writes else ""
        o[f"{sd}-dev"] = f'{writes} simulated' if writes else ""
        o[f"{sd}-person"] = f'{(ev.meta.get("people_told") or {}).get("homes" if sd == "h" else "buildings")} told'
    o["r-read"] = v.get("readings", "")
    o["r-check"] = f'{v.get("refused", "0")} refused' if v.get("readings") else ""
    o["r-settle"], o["r-pay"] = v.get("buyers_pay", ""), v.get("sellers", "")
    o["trade"] = f'{v.get("sold", "")} sold, {v.get("buyers_pay", "")} paid'.strip(", ")
    return {k: x for k, x in o.items() if x}


def ledger_rows(ledger: dict[str, Any]) -> list[list[str]]:
    """The evening's table, half hour by half hour, as the whole picture's trade box shows it."""
    hs = (ledger.get("half_hours") or [])[:6]
    rows = [["kW per half hour"] + [str(h.get("start")) for h in hs]]
    for lab, key in (("Asked", "asked_kw"), ("Offered, firm", "offered_firm_kw"), ("Offered, tentative", "offered_tentative_kw"),
                     ("Offered in all", "offered_kw"), ("Sold", "sold_kw"), ("Reserve", "reserve_kw"), ("Asked of the nodes", "asked_of_nodes_kw"),
                     ("Homes offered", "offered_homes_kw"), ("Buildings offered", "offered_buildings_kw"), ("Homes asked", "asked_homes_kw"),
                     ("Buildings asked", "asked_buildings_kw"), ("Delivered, on the meters", "delivered_kw"), ("Below the no-sale twin", "true_kw")):
        rows.append([lab] + [kw(h.get(key), 1) if num(h.get(key)) is not None else "—" for h in hs])
    rows.append(["Readings"] + [f'{kw(h.get("readings"))} of {kw(h.get("readings_expected"))}' for h in hs])
    rows.append(["Buyers pay"] + [usd(sum(num(x) or 0 for x in (h.get("buyer_usd") or {}).values())) for h in hs])
    rows.append(["To nodes"] + [usd(sum(num(x) or 0 for x in (h.get("nodes_usd") or {}).values())) for h in hs])
    rows.append(["Coordinator keeps"] + [usd(h.get("coordinator_keep_usd")) for h in hs])
    return rows

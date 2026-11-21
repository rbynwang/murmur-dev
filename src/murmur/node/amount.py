"""What a node may tell the market: the amount (kW per half hour, firm and tentative), and the few figures the market needs to check it.

Nothing about the household goes on the market's wire: no note, no reason, no device list. leaks() names any field that would.
"""
from __future__ import annotations

import re
from typing import Any, Callable


KW = None                       # one plain value: a number, yes or no, an id or a time
ANY = "*"                       # keys that are data: a slot's id, a quarter hour, a delivery level
GONE = object()                 # a key the list doesn't name
SLOT = {k: KW for k in ("id", "kw_offered", "battery_kw", "ev_pause_kw", "ac_kw", "light_kw", "app_kw", "firm_kw", "tentative_kw")}
OFFER = {
    "event_id": KW, "home": KW, "node": KW, "energy_kwh": KW, "confidence": KW, "slots": [SLOT],
    "held_back_kw": {ANY: KW},                                                                       # the second round's list of who to ask
    "evening": {"start": KW, "step_min": KW, "import_cf_kw": [KW], "import_noev_kw": [KW], "rebound_kw": {ANY: [KW]}},      # the rebound guard
    "ev_flex": {"kwh": KW, "max_kw": KW, "latest_finish": KW, "arrival": KW},                        # the evening's restart of the car
    "battery": {"kw": KW, "out_of_service": KW}, "air_conditioning": {"raw_kw": KW}, "lighting": {"raw_kw": KW},      # how big a member is: who the desk asks first
    "weather": {"pv": KW, "load": KW, "from": KW},                                                   # a what-if day, for the independent check's replay
    "agent": {"decided_by": KW, "decision": KW, "round": KW},                                        # which decision it was
}
READING = {"contract_id": KW, "event_id": KW, "home": KW, "slot_id": KW, "start": KW, "committed_kw": KW, "usage_kw": KW, "battery_kw": KW, "pre_kw": KW,
           "truth": {"usage_without_event_kw": KW, "delivered_true_kw": KW}}
REPORT = {"sale": KW, "ts": KW, "owed_kw": KW, "sold_kwh": KW, "delivered_kwh": KW, "short_kwh": KW}
ALLOWED: dict[str, dict[str, Any]] = {
    "on_discover": {"offer": OFFER},
    "on_confirm": {"contract": {"id": KW, "event_id": KW, "home": KW, "status": KW}},
    "on_status": {"performance": READING, "node_report": REPORT},
    "rt_answer": {"answer": {"id": KW, "kw": KW, "below_min_price": KW}},
    "rt_capacity": {"short": {ANY: KW}, "abnormal": KW, "drift": KW},
}
# What these messages carry and the market never reads. Dropped here without a word: anything else dropped is news, and goes to the node's log
NOT_NEEDED = {
    "offer.kept_out", "offer.forecast_method", "offer.health", "offer.price_floor", "offer.made_at", "offer.valid_until", "offer.appliances", "offer.sellable",
    "offer.battery.kwh", "offer.battery.usable_kwh", "offer.battery.energy_scale", "offer.battery.window_start_kwh",
    "offer.air_conditioning.kw", "offer.air_conditioning.cooling_forecast_kw", "offer.air_conditioning.agent_share",
    "offer.lighting.kw", "offer.lighting.lighting_on_kw", "offer.lighting.share", "offer.lighting.agent_share",
    "offer.agent.reason", "offer.agent.take_part", "offer.agent.battery_share", "offer.agent.cooling_share", "offer.agent.lighting_share", "offer.agent.pause_ev", "offer.agent.devices_off",
    "offer.agent.wishes", "offer.agent.seen", "offer.agent.flags",
    "contract.reason", "answer.why", "reason",
    "performance.soc_end_pct", "performance.modes", "performance.ev_held",
    "node_report.by", "node_report.summary", "node_report.facts",
}
TIME = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d(:\d\d)?$")


def plain(v: Any) -> bool:
    """A value the market can read and nobody could have written a sentence in: a number, yes or no, nothing, an id or a time."""
    if v is None or isinstance(v, (bool, int, float)):
        return True
    return isinstance(v, str) and (not re.search(r"\s", v) or TIME.match(v) is not None)


def keep(v: Any, rule: Any, path: str, out: list[str]) -> Any:
    """v as far as the rule allows it. What goes is written in out, by where it was."""
    if v is None:                                       # "no evening", "no car": the market reads that as it is
        return None
    if rule is KW:
        if plain(v):
            return v
        out.append(path)
        return None
    if isinstance(rule, list):
        if isinstance(v, list):
            return [keep(x, rule[0], path, out) for x in v]
        out.append(path)
        return []
    if not isinstance(v, dict):
        out.append(path)
        return {}
    kept = {}
    for k, x in v.items():
        sub = rule.get(k, rule.get(ANY, GONE))
        name = f"{path}.{k}" if path else str(k)
        if sub is GONE:
            out.append(name)
        else:
            kept[k] = keep(x, sub, path if ANY in rule else name, out)
    return kept


def market_facts(action: str, message: dict[str, Any]) -> dict[str, Any]:
    """The one thing the market reads out of a reason, before the reason goes."""
    if action == "rt_capacity" and message.get("reason") == "the forecast changed":
        return {**message, "drift": True}
    if action == "rt_answer" and "price" in str((message.get("answer") or {}).get("why") or ""):
        return {**message, "answer": {**message["answer"], "below_min_price": True}}
    return message


def only(action: str, message: dict[str, Any], log: Callable[..., None] | None = None) -> dict[str, Any]:
    """The message as it may leave the node. A kind of message nobody listed carries nothing."""
    gone: list[str] = []
    if action not in ALLOWED:
        gone.append(action)
        out: dict[str, Any] = {}
    else:
        out = keep(market_facts(action, message), ALLOWED[action], "", gone)
    news = [p for p in gone if p not in NOT_NEEDED]
    if news and log is not None:
        log("wire_kept_back", message_kind=action, fields=news[:12])
    return out


def leaks(action: str, message: dict[str, Any]) -> list[str]:
    """Where in this message something is that may not leave a node. For tests, and for anyone who wants to check a record."""
    if action not in ALLOWED:
        return [action]
    gone: list[str] = []
    keep(message, ALLOWED[action], "", gone)
    return gone

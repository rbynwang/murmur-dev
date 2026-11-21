"""What a meter reading may say before money moves on it: a member's enrolled devices bound what it can claim, a reading must be a
number in range for its half hour, and a buyer's baseline must rest on enough days.
"""
from __future__ import annotations

import csv
import json
import logging
import math
from functools import lru_cache
from typing import Any, Callable

from murmur.protocol import envelope as beckn
from murmur import config
from murmur.settlement import rules as st

TOL_KW = 0.02             # readings carry three decimals, and a meter at its limit reads its limit
SOLAR_SLACK = 1.25        # today can be sunnier than the best of the days just gone
ENERGY_SLACK_KWH = 1.0
TOP = 1e9                 # past anything a sale can say in kW, kWh or dollars
BATTERY_SLACK = 1.1       # solar can put some back into a battery inside the window. Honest homes reach 0.97 of what was stored
SLOT_H = beckn.SLOT_MINUTES / 60
MONEY_FIELDS = ("usage_kw", "battery_kw")      # what a repeat may not change. A commitment isn't the meter's: it's held to the community agent's numbers when it's read
_FACTS: dict[str, dict[str, Any]] = {}
log = logging.getLogger("murmur.meters")


def real(v: Any) -> bool:
    """A real number. Text is not one, even text float() would take: a node that signs "nan" would take a buyer's whole bill with it."""
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:                                  # JSON's integers have no top
        return False


def sane(v: Any) -> bool:
    """A real number a sum of them can't take past a float's top: two of 1e308 add up to infinity, a payment of NaN goes nowhere, and Town can't carry either."""
    return real(v) and abs(v) <= TOP


# ------------------------------------------------------------------ what the data says a node is
@lru_cache(maxsize=1)
def _enrolled() -> dict[str, dict[str, Any]]:
    from murmur.node import simulator_building as building
    out = {h["name"]: h for h in json.loads(config.data_path("fleet_v2.json").read_text()).get("homes", [])}
    return {**out, **{b["name"]: {**b, "kind": "building"} for b in building.registry()}}


def _car_kw(profile: str) -> float:
    """The home's car charger: its first session's, as the node's own adapter takes it."""
    name = config.dataset_meta().get("profile_alias", {}).get(profile, profile)
    try:
        with open(config.data_path(f"{name}_ev.csv" if "/" in name else f"ev_{name}.csv")) as f:
            return next((float(r["max_kw"]) for r in csv.DictReader(f)), 0.0)
    except (OSError, ValueError, KeyError):
        return 0.0


def _owner_car_kwh(name: str, default: float) -> float:
    return float(_owners().get(name, {}).get("v2h_kwh", default))


@lru_cache(maxsize=1)
def _owners() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(config.data_path("owners.json").read_text())["homes"]
    except (OSError, ValueError, KeyError):
        return {}


def _stored(b: dict[str, Any]) -> float:
    """kWh a battery can give from full, above its reserve."""
    return float(b.get("kwh", 0.0)) * max(0.0, float(b.get("soc_max_pct", 100.0)) - float(b.get("reserve_pct", 0.0))) / 100.0 * float(b.get("eta", 0.95))


def _home(h: dict[str, Any]) -> dict[str, Any]:
    from murmur.node import devices
    from murmur.node import hvac
    name, b = h["name"], h.get("battery") or {}
    power = float(b.get("kw", 0.0))
    kw = power + (_car_kw(h["profile"]) if h.get("has_ev", True) else 0.0)
    p = hvac.params_for(name)
    kw += float(p["cool_cap_kw"]) / 2.0 if p else 0.0              # kW of heat removed, at a low COP
    spec, arr, row = devices.for_node("home", name)
    dev = {k: float(arr[k][row].max()) for k in spec}
    car = dev.get("v2h", 0.0)
    rated_kw = round(kw + sum(dev.values()), 1)
    return {"kind": "home", "rated_kw": rated_kw, "intake_kw": rated_kw - car, "export_kw": float(h["export_limit_kw"]), "battery_kw": power + car,
            "stored_kwh": _stored(b) + (_owner_car_kwh(name, float(spec["v2h"].get("event_kwh", 0.0))) if car > 0 else 0.0)}


def _building(b: dict[str, Any]) -> dict[str, Any]:
    from murmur.node import simulator_building as building
    from murmur.node import devices
    p = building.params(b["name"])
    bat = p.get("battery") or {}
    kw = float(bat.get("kw", 0.0)) + float(p["thermal"]["cool_cap_kw"]) / 2.0
    try:
        cat = devices.catalog()
    except (FileNotFoundError, OSError, ValueError):       # a dataset without the devices: as SimulatedBuilding._own_devices
        cat = {}
    row = (cat.get("rows", {}).get("building") or {}).get(b["name"])
    if row is not None:
        kw += sum(float(devices.array("building", k)[row].max()) for k in cat["devices"].get("building") or {})
    kw += max(building._light_series(b["profile"]).values(), default=0.0)
    return {"kind": "building", "rated_kw": round(kw, 1), "intake_kw": round(kw, 1), "export_kw": float(p.get("export_limit_kw", 5000.0 if float(bat.get("kwh", 0.0)) > 0 else 2000.0)),
            "battery_kw": float(bat.get("kw", 0.0)), "stored_kwh": _stored(bat)}


def facts(name: str) -> dict[str, Any] | None:
    """A node's nameplate, what it can take in above its usual load (a two-way car charges on the charger it already counts), its export limit, the power and energy it can
    give from storage. From the data. None for a name the data doesn't hold, such as a test's stand-in: its readings are checked as numbers only. A pooled
    community agent refuses such a node's offers (no nameplate in Market.rated), so it never reaches a sale."""
    if name in _FACTS:
        return _FACTS[name]
    try:
        e = _enrolled().get(name)
        if not e:
            return None
        _FACTS[name] = _building(e) if e.get("kind") == "building" else _home(e)
        return _FACTS[name]
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:     # not kept: the next reading asks again
        log.error("no enrolment facts for %s: %s", name, str(exc)[:200])
        return None


def rated(names: list[str]) -> dict[str, float]:
    """Market.rated, as the community agent's service sets it on a pooled market: each member's nameplate from its enrolment."""
    return {n: f["rated_kw"] for n in names if (f := facts(n))}


def own_kind(o: Any, sender: str) -> Any:
    """A signed offer says "node": "building", and a building is paid at another rate and capped differently, so what it is comes from its enrolment, not its offer."""
    f = facts(sender)
    if f is None or not isinstance(o, dict):
        return o
    return {**o, "node": "building"} if f["kind"] == "building" else {k: v for k, v in o.items() if k != "node"}


# ------------------------------------------------------------------ one reading
def slot_of(r: dict[str, Any]) -> int | None:
    s = r.get("slot_id")
    return s if isinstance(s, int) and not isinstance(s, bool) else None


def _base_of(baselines: Any, home: str, sid: Any) -> Any:
    return (((baselines or {}).get(home) or {}).get(str(sid)) or {}).get("BASELINE")


def value_problem(r: dict[str, Any], fact: dict[str, Any] | None, base: Any = None) -> str | None:
    """Why these numbers can't be true, or None."""
    u = r.get("usage_kw")
    if not real(u):
        return "its usage isn't a real number"
    for k in ("committed_kw", "battery_kw"):
        if r.get(k) is not None and not real(r[k]):
            return f"its {k} isn't a real number"
    if real(r.get("committed_kw")) and r["committed_kw"] < 0:
        return "it committed less than nothing"
    if fact:
        if u < -fact["export_kw"] - TOL_KW:
            return f"{-u:g} kW going out is past its meter's {fact['export_kw']:g} kW"
        top = max(float(base), 0.0) if real(base) else fact["rated_kw"]
        if u > top + fact["intake_kw"] + TOL_KW:
            return f"{u:g} kW coming in is past its baseline and the {fact['intake_kw']:g} kW it can add"
        if real(r.get("battery_kw")) and r["battery_kw"] < -fact["battery_kw"] - TOL_KW:
            return f"{-r['battery_kw']:g} kW into a battery that takes {fact['battery_kw']:g}"
    return None


def reading_problem(r: Any, slots: Any = None, fact: dict[str, Any] | None = None, base: Any = None) -> str | None:
    """Why this reading of a sale can't count, or None. slots: the sale's half hours."""
    if not isinstance(r, dict):
        return "it isn't a reading"
    sid = slot_of(r)
    if sid is None:
        return "it names no real slot"
    if slots is not None and sid not in slots:
        return f"this sale has no slot {sid}"
    return value_problem(r, fact, base)


def _differs(a: Any, b: Any) -> bool:
    return real(a) and real(b) and abs(float(a) - float(b)) > 2 * TOL_KW / 10


def _bad_pre(pre: Any, fact: dict[str, Any] | None, pre_base: Any) -> bool:
    """Its load before the event. It raises the node's own baseline, so it can't pass what the meter could have taken in."""
    if not real(pre):
        return True
    if not fact:
        return False
    return not -fact["export_kw"] - TOL_KW <= pre <= (max(float(pre_base), 0.0) if real(pre_base) else 0.0) + fact["intake_kw"] + TOL_KW


def no_bad_truth(r: dict[str, Any]) -> dict[str, Any]:
    """The twin's answer rides on a simulated node's reading. A real node has none, and no money reads it. What can't be read is left out here, so nothing later trips on it."""
    t = r.get("truth")
    ok = isinstance(t, dict) and all(real(v) for v in t.values())
    return r if ok else {k: v for k, v in r.items() if k != "truth"}


def true_kw(r: dict[str, Any]) -> float:
    """The delivered kW the twin saw, for the record. 0 where there is no twin."""
    v = (r.get("truth") or {}).get("delivered_true_kw") if isinstance(r.get("truth"), dict) else None
    return float(v) if real(v) else 0.0


# ------------------------------------------------------------------ the buyer's door
def buyer_refuses(ct: dict[str, Any], sender: str, r: dict[str, Any], event: Callable[..., None]) -> str | None:
    """None if this reading may be kept. Else why not, once it's counted and logged. A contract's slots are all a reading can name."""
    need = ct.get("need") or {}
    slots = {int(s["id"]) for s in need.get("slots") or []} or None
    sid = slot_of(r)
    why = reading_problem(r, slots, facts(sender), _base_of(ct.get("baselines"), sender, sid))
    have = (ct.get("meter_readings") or {}).get(sender) or {}
    if why is None and sid in have and (_differs(r.get("usage_kw"), have[sid]) or _differs(r.get("battery_kw") or 0.0, (ct.get("meter_batt") or {}).get(sender, {}).get(sid))):
        why = "it changes a reading already in"
    if why is None:
        (ct.get("rejected_slots") or {}).get(sender, {}).pop(sid, None)
        return None
    ct["rejected_readings"] = ct.get("rejected_readings", 0) + 1
    if sid is not None and sid not in have and (slots is None or sid in slots):
        ct.setdefault("rejected_slots", {}).setdefault(sender, {})[sid] = why     # no later true reading: this slot goes unpaid, and nobody waits for it
    event("reading_refused", home=sender, event_id=need.get("event_id"), slot=str(r.get("slot_id"))[:24], why=why)
    return beckn.Refused(f"rejected: {why}")


def pre_kw(ct: dict[str, Any], sender: str, r: dict[str, Any], event: Callable[..., None]) -> float | None:
    """The node's load before the event, if it may count. Ask before keeping the reading. The first stands, every honest reading of a sale carries the same one, and a repeat of a
    half hour can't bring one in: that's a second try at a settlement already seen."""
    pre = r.get("pre_kw")
    if pre is None:
        return None
    was = (ct.get("meter_pre") or {}).get(sender)
    repeat = slot_of(r) in ((ct.get("meter_readings") or {}).get(sender) or {})
    bad = _bad_pre(pre, facts(sender), (ct.get("pre_baselines") or {}).get(sender))
    if not bad and was is None and not repeat:
        return float(pre)
    if bad or _differs(pre, was) or was is None:
        ct["pre_refused"] = ct.get("pre_refused", 0) + 1
        event("reading_pre_refused", home=sender, event_id=(ct.get("need") or {}).get("event_id"), pre_kw=str(pre)[:24], kept=was)
    return None


def committed(ct: dict[str, Any], home: str, sid: Any) -> float:
    """What this meter owed in this half hour. A reading says, and the community agent says too (ct["owed"], with "readings are in"), so a reading moves it only inside what
    the community agent allows."""
    return against_owed(float(((ct.get("meter_committed") or {}).get(home) or {}).get(int(sid), 0.0)), (ct.get("owed") or {}).get(home), sid)


def against_owed(said: float, owed: dict[Any, Any] | None, sid: Any) -> float:
    """owed: {slot: (its contract's kW, with the gaps it was dispatched for)}. A dispatch that reached a node after it read the half hour isn't on its reading, so the node's word stands anywhere between."""
    o = (owed or {}).get(int(sid), (owed or {}).get(str(sid)))
    if o is None:
        return said
    lo, hi = float(o[0]), float(o[1])
    room = 0.01 + 0.002 * hi
    return lo if said < lo - room else hi if said > hi + room else said


def _limit_battery(rows: dict[Any, dict[str, float]], fact: dict[str, Any], cut: dict[str, Any]) -> None:
    """A battery claim cut in place to the enrolled battery: its rate in each half hour, then what it stores over the window."""
    for i, v in rows.items():
        if "BATT" in v and v["BATT"] > fact["battery_kw"] + TOL_KW:
            cut.setdefault("battery_kw", {})[str(i)] = v["BATT"]
            v["BATT"] = fact["battery_kw"]
    kwh = sum(max(v.get("BATT", 0.0), 0.0) for v in rows.values()) * SLOT_H
    room = BATTERY_SLACK * fact["stored_kwh"] + ENERGY_SLACK_KWH
    if kwh > room:
        cut["battery_kwh"] = {"said": round(kwh, 3), "stored": round(room, 3)}
        for v in rows.values():
            if v.get("BATT", 0.0) > 0:
                v["BATT"] *= room / kwh


def _limit_building(rows: dict[Any, dict[str, float]], fact: dict[str, Any]) -> dict[str, Any]:
    """Cuts a building's battery claims in place to its enrolled battery and to what its meter delivered (its reduction itself is
    capped at its commitment: rules.building_counted_kwh). Returns what was cut: nothing, for an honest building."""
    cut: dict[str, Any] = {}
    _limit_battery(rows, fact, cut)
    for v in rows.values():
        if "BATT" in v:
            v["BATT"] = min(v["BATT"], max(v["BASELINE"] - v["USAGE"], 0.0))
    return cut


def _limit_home(name: str, rows: dict[Any, dict[str, float]], fact: dict[str, Any], solar: dict[str, float] | None) -> dict[str, Any]:
    """Cuts this home's slots in place to what could count. Returns what was cut: nothing, for an honest home."""
    cut: dict[str, Any] = {}
    _limit_battery(rows, fact, cut)                  # the battery rate first: per half hour, then over the window
    # what counts: its nameplate in each half hour
    for i, v in rows.items():
        if v["BASELINE"] - v["USAGE"] > fact["rated_kw"] + TOL_KW:
            cut.setdefault("nameplate_kw", {})[str(i)] = round(v["BASELINE"] - v["USAGE"], 3)
            v["USAGE"] = v["BASELINE"] - fact["rated_kw"]
            if "BATT" in v:
                v["BATT"] = min(v["BATT"], fact["rated_kw"])
    # and over the window: what it stored, its solar, its own load going to zero
    if solar is not None:
        got = sum(max(v["BASELINE"] - v["USAGE"], 0.0) for v in rows.values()) * SLOT_H
        room = fact["stored_kwh"] + ENERGY_SLACK_KWH + sum(max(v["BASELINE"], 0.0) + SOLAR_SLACK * float(solar.get(str(i), 0.0)) for i, v in rows.items()) * SLOT_H
        if got > room:
            cut["energy_kwh"] = {"said": round(got, 3), "could": round(room, 3)}
            for v in rows.values():
                x = v["BASELINE"] - v["USAGE"]
                if x > 0:
                    v["USAGE"] = v["BASELINE"] - x * room / got
                    if "BATT" in v:
                        v["BATT"] = min(v["BATT"], x * room / got)
    # and the battery rate is paid on what the meter delivered: a claim past that only moves kWh to the better rate, with nothing behind them. It isn't shown as a cut, because an
    # honest battery runs past its meter whenever the house's own load rises, and that is common, so a note here would say nothing
    for v in rows.values():
        if "BATT" in v:
            v["BATT"] = min(v["BATT"], max(v["BASELINE"] - v["USAGE"], 0.0))
    return cut


def limit(meters: dict[str, dict[Any, dict[str, float]]], solar: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every node's slots cut to what could count, in place: a home's to its battery, nameplate and window, a building's battery claims
    to its enrolled battery (its reduction has its cap). Returns what was cut, by node."""
    cut = {}
    for h, rows in meters.items():
        f = facts(h)
        if f and f["kind"] == "home":
            c = _limit_home(h, rows, f, (solar or {}).get(h))
        elif f and f["kind"] == "building":
            c = _limit_building(rows, f)
        else:
            c = {}
        if c:
            cut[h] = c
    return cut


def counted(ct: dict[str, Any], bases: dict[str, Any]) -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, Any]]:
    """The contract's meters as settlement counts them, and what was left out or cut. The utility's settlement and the call's measure read this one view."""
    meters: dict[str, dict[int, dict[str, float]]] = {}
    notes: dict[str, Any] = {}
    owed = ct.get("owed")
    for home in ct.get("meters", []):
        for sid, usage in (ct.get("meter_readings") or {}).get(home, {}).items():
            base = bases.get(home, {}).get(str(sid), {}).get("BASELINE")
            if base is None or int(sid) in (ct.get("abnormal") or {}).get(home, ()):
                continue
            if owed is not None and not {int(sid), str(sid)} & set(owed.get(home) or ()):      # it never owed this half hour: nobody asked for it
                notes.setdefault("not_owed", {}).setdefault(home, []).append(int(sid))
                continue
            row = meters.setdefault(home, {})[int(sid)] = {"BASELINE": base, "USAGE": usage}
            row["BATT"] = float((ct.get("meter_batt") or {}).get(home, {}).get(sid, 0.0))
            row["BASELINE"] = st.adjusted(base, (ct.get("meter_pre") or {}).get(home), (ct.get("pre_baselines") or {}).get(home))
    cut = limit(meters, ct.get("solar"))
    if cut:
        notes["capped"] = cut
    return meters, notes


def recent_solar(rp: Any, days: list[Any], slots: list[dict[str, Any]]) -> dict[str, float]:
    """The most solar this meter's home made in each half hour of the window on the days just gone: what it could have today."""
    out: dict[str, float] = {}
    for s in slots:
        best = 0.0
        for d in days:
            t = d.isoformat() + s["start"][10:]
            i, j = rp.idx_of(t), rp.idx_of(beckn.add_minutes(t, 15))
            if i is not None and j is not None:
                best = max(best, (float(rp.row(i)["pv_kw"]) + float(rp.row(j)["pv_kw"])) / 2.0)
        out[str(s["id"])] = round(best, 3)
    return out

"""What the market and a buyer must refuse before money moves: readings past what a member owed, a call it never took, a settlement that doesn't add up, and two buyers who disagree."""
from __future__ import annotations

import json
from typing import Any, Callable
from murmur.protocol import envelope as beckn
from murmur.settlement.meter_check import MONEY_FIELDS, TOL_KW, _base_of, _differs, facts, reading_problem, real, sane, slot_of, value_problem


def at_most_nameplate(home: str, kw: float) -> float:
    """kw, held to the node's nameplate where its enrolment gives one."""
    f = facts(home)
    return min(kw, f["rated_kw"]) if f else kw


# ------------------------------------------------------------------ a call's reading, at the buyer
def _half_hours(rec: dict[str, Any]) -> tuple[str, str]:
    """The first half hour a call's reading can name, and the end of what it can reach: a gap's helper under a call can owe past the call's end, and earns nothing there."""
    first = rec["start"][:14] + ("00" if rec["start"][14:16] < "30" else "30")
    return first, beckn.add_minutes(rec["end"], 360)


def _start_problem(rec: dict[str, Any], start: Any) -> str | None:
    try:
        ok = isinstance(start, str) and beckn.add_minutes(start, 0) == start and start[14:16] in ("00", "30")
    except (TypeError, ValueError):
        ok = False
    if not ok:
        return "its half hour can't be read"
    first, last = _half_hours(rec)
    return None if first <= start < last else f"{start} is no half hour of this call"


def allowed_kw(rec: dict[str, Any], home: str, start: str) -> float | None:
    """kW the desk dispatched this node for in this half hour. None: the desk's list hasn't come (its confirm was lost)."""
    a = rec.get("alloc")
    if a is None:
        return None
    end = beckn.add_minutes(start, 30)
    return sum(float(kw) for t, kw in (a.get(home) or {}).items() if start <= t < end) / 2.0


def call_refuses(rec: dict[str, Any], sender: str, r: dict[str, Any], event: Callable[..., None]) -> str | None:
    """None if this reading of a call may be kept. A call pays only those it dispatched, and they share what it pays, so a stranger's reading takes from them."""
    why = _start_problem(rec, r.get("start")) or value_problem(r, facts(sender))
    if why is None and rec.get("alloc") is not None and sender not in rec["alloc"]:
        why = "the desk didn't dispatch this node for this call"
    have = (rec.get("readings") or {}).get(sender, {}).get(r.get("start")) if why is None else None
    if have and (_differs(r.get("usage_kw"), have["usage_kw"]) or _differs(r.get("battery_kw") or 0.0, have.get("said_battery_kw", have["battery_kw"]))):
        why = "it changes a reading already in"
    if why is None:
        return None
    rec["rejected"] = rec.get("rejected", 0) + 1
    event("reading_refused", home=sender, event_id=rec.get("id"), start=str(r.get("start"))[:24], why=why)
    return beckn.Refused(f"rejected: {why}")


def take_list(rec: dict[str, Any], alloc: Any, event: Callable[..., None]) -> None:
    """The desk's list of who owes what under this call. A node asked and not dispatched knows the call's id, so what came before the list is held to it too."""
    rec["alloc"] = alloc if isinstance(alloc, dict) else {}
    for h in [h for h in rec.get("readings") or {} if h not in rec["alloc"]]:
        rec["rejected"] = rec.get("rejected", 0) + 1
        del rec["readings"][h]
        event("reading_refused", home=h, event_id=rec.get("id"), why="the desk didn't dispatch this node for this call")
    for h, rows in (rec.get("readings") or {}).items():
        for start, row in rows.items():
            row["dispatched_kw"] = min(row["dispatched_kw"], allowed_kw(rec, h, start) + TOL_KW)


def call_row(rec: dict[str, Any], sender: str, r: dict[str, Any]) -> dict[str, float]:
    """A call's reading as the buyer keeps it: what it was dispatched for is the desk's word, and the battery rate stops at its battery and car."""
    said = float(r.get("committed_kw") or 0.0)
    ok = allowed_kw(rec, sender, r["start"])
    disp = said if ok is None or said <= ok + TOL_KW else ok
    batt = float(r.get("battery_kw") or 0.0)
    f = facts(sender)
    return {"usage_kw": float(r["usage_kw"]), "dispatched_kw": disp, "battery_kw": min(batt, f["battery_kw"]) if f else batt, "said_battery_kw": batt}


def keep_call_row(rec: dict[str, Any], sender: str, r: dict[str, Any]) -> None:
    """The first of a half hour stands for what the meter said, as in a sale. What it was dispatched for follows the desk's word, which can come after the first reading."""
    rows = rec["readings"].setdefault(sender, {})
    row, first = call_row(rec, sender, r), rows.get(r["start"])
    rows[r["start"]] = {**row, **{k: first[k] for k in ("usage_kw", "battery_kw", "said_battery_kw") if k in first}} if first else row


# ------------------------------------------------------------------ the community agent's door
def owed_slots(market: Any, ev: dict[str, Any], home: str) -> dict[int, tuple[float, float]]:
    """What this node owes in each half hour of this sale: (its contract's kW, and that with what the desk dispatched under the sale to cover a gap). Nothing without an accepted contract."""
    c = ev["commitments"].get(home) or {}
    if c.get("status") != "ACCEPTED":
        return {}
    lo = {x["id"]: float(x["kw"]) for x in c["contract"]["commitments"]}
    hi = dict(lo)
    n = ev["need"]
    sid_of = {s["start"]: s["id"] for s in n["slots"]}
    for g in market.rt.calls.values():
        if g.get("kind") == "gap" and (g.get("parent") or {}).get("id") == n["event_id"]:
            for t, kw in (g["alloc"].get(home) or {}).items():
                sid = sid_of.get(t[:14] + ("00" if t[14:16] < "30" else "30"))
                if sid is not None:
                    hi[sid] = hi.get(sid, 0.0) + float(kw) / 2.0
    return {k: (lo.get(k, 0.0), v) for k, v in hi.items()}


def owed_kw(market: Any, ev: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    """The same for every node, as "readings are in" tells the buyers: they settle on it, and a reading's own word can't move it."""
    return {h: {str(k): [round(a, 3), round(b, 3)] for k, (a, b) in owed_slots(market, ev, h).items()} for h in ev["commitments"] if ev["commitments"][h].get("status") == "ACCEPTED"}


def owed_of(told: Any) -> dict[str, dict[int, tuple[float, float]]] | None:
    """The buyer's copy of owed_kw. None from a community agent that doesn't say."""
    return {h: {int(k): (float(v[0]), float(v[1])) for k, v in d.items()} for h, d in told.items()} if isinstance(told, dict) else None


def _refused(market: Any, ev: dict[str, Any] | None, sender: str, r: Any, why: str) -> str:
    sid = slot_of(r) if isinstance(r, dict) else None
    if ev is not None:
        ev["readings_refused"] = ev.get("readings_refused", 0) + 1
        if sid is not None and sid not in (ev["readings"].get(sender) or {}):
            ev.setdefault("rejected_slots", {}).setdefault(sender, {})[sid] = why
    market.log("v2_reading_refused", event_id=(ev or {}).get("need", {}).get("event_id"), home=sender, slot=str((r or {}).get("slot_id") if isinstance(r, dict) else "")[:24], why=why)
    return beckn.Refused(f"reading refused: {why}")


def market_refuses(market: Any, sender: str, r: Any, body: dict[str, Any]) -> str | None:
    """None if a node's reading goes on to the market, which keeps or ignores it. Else why not, once it's counted and logged. The buyers hold the same line on their own copies."""
    if not isinstance(r, dict):
        return _refused(market, None, sender, r, "it isn't a reading")
    sent = (body.get("context") or {}).get("sentWall")
    if isinstance(sent, (int, float)) and sent < market.run_wall:
        market.log("v2_reading_ignored", home=sender, why="sent before this run started")
        return beckn.Refused("reading ignored: sent before this run started")
    eid = r.get("event_id")
    if not isinstance(eid, str):
        return _refused(market, None, sender, r, "it names no event")
    rec = market.rt.calls.get(eid)
    if rec is not None:
        why = reading_problem(r, None, facts(sender))
        have = ((rec.get("readings") or {}).get(sender) or {}).get(slot_of(r))
        if why is None and have and any(_differs(r.get(k) or 0.0, have.get(k) or 0.0) for k in MONEY_FIELDS):
            why = "it changes a reading already in"
        if why:
            rec["refused"] = rec.get("refused", 0) + 1
            return _refused(market, None, sender, r, why)
        return None
    ev = market.events.get(eid)
    if ev is None or (ev.get("finalized") and sender not in (ev.get("final_meters") or [])):
        market.log("v2_reading_ignored", event_id=eid[:80], home=sender)
        return None                                        # the market's own answer: nothing here to keep
    sid = slot_of(r)
    why = "it's another node's reading" if r.get("home") != sender else None
    why = why or reading_problem(r, {s["id"] for s in ev["need"]["slots"]}, facts(sender), _base_of(ev.get("baselines"), sender, sid))
    if why is None and market.pooled and sid not in owed_slots(market, ev, sender):
        why = f"it owes nothing in slot {sid}"
    have = (ev["readings"].get(sender) or {}).get(sid)
    if why is None and have and any(_differs(r.get(k) or 0.0, have.get(k) or 0.0) for k in MONEY_FIELDS):
        why = "it changes a reading already in"
    if why is None:
        (ev.get("rejected_slots") or {}).get(sender, {}).pop(sid, None)
        return None
    return _refused(market, ev, sender, r, why)


def clean_actuals(meters: dict[str, Any], log: Callable[..., None], event_id: str) -> dict[str, dict[str, dict[str, float]]]:
    """The buyers' meters as the split reads them. What can't be read is left out, so one node's bad row costs that node and nobody else."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    bad = set()
    for h, m in (meters.items() if isinstance(meters, dict) else ()):
        for k, v in (m.items() if isinstance(m, dict) else ()):
            if isinstance(v, dict) and sane(v.get("BASELINE")) and sane(v.get("USAGE")) and (v.get("BATT") is None or sane(v["BATT"])):
                out.setdefault(h, {})[k] = v
            else:
                bad.add(h)
        if not isinstance(m, dict):
            bad.add(h)
    if bad:
        log("v2_bad_actuals", event_id=event_id, homes=sorted(bad)[:8], count=len(bad))
    return out


def keep_lower(meters: dict[str, dict[Any, dict[str, float]]], h: str, k: Any, v: dict[str, float]) -> None:
    """One buyer's row for the split. A node that told the buyers different things is counted on the copy that pays it less: a bigger copy at one buyer would otherwise be shared
    out at the rate of what both paid, and every other seller would pay for it. Honest copies are the same row."""
    have = meters.setdefault(h, {}).setdefault(k, v)
    if v["BASELINE"] - v["USAGE"] < have["BASELINE"] - have["USAGE"]:
        meters[h][k] = v


def _kw_of(x: Any) -> bool:
    return x is None or (isinstance(x, dict) and all(sane(v) for v in x.values()))


def lacking_problem(x: Any) -> str | None:
    """A buyer's list of the half hours it has no reading for: {node: [slot, ...]}. The tick reads it every second, so what it can't read would stop the market for every sale."""
    ok = x is None or (isinstance(x, dict) and all(isinstance(v, list) and all(isinstance(k, int) and not isinstance(k, bool) for k in v) for v in x.values()))
    return None if ok else "a list of what it lacks that can't be read"


def baselines_problem(x: Any) -> str | None:
    """{node: {slot: {"BASELINE": kW}}}. Every reading is held to these, and the desk's tick reads them."""
    ok = isinstance(x, dict) and all(isinstance(d, dict) and all(isinstance(b, dict) and (b.get("BASELINE") is None or sane(b["BASELINE"])) for b in d.values()) for d in x.values())
    return None if ok else "baselines that can't be read"


def settlement_problem(s: Any) -> str | None:
    """Why the split can't work from this settlement, or None. Each field the split, the sale's record or the tick goes on to read is held here, at the door. A settlement that gets past
    is stored and answered for, so a split that stops on it later pays nobody and can't run again: one junk field would hold every seller's pay for good. A settlement refused here
    is asked for again (ask_settlement), and its order keeps why (v2_settlement_refused names the buyer). A row in `actuals` that can't be read isn't refused: it costs that node
    (clean_actuals)."""
    if not isinstance(s, dict):
        return "it isn't a settlement"
    rows = s.get("revenue_flows")
    paid = next((f.get("value") for f in rows if isinstance(f, dict) and f.get("role") == "seller"), None) if isinstance(rows, list) else None
    if not isinstance(rows, list) or not all(isinstance(f, dict) for f in rows) or not sane(paid):
        return "no real sum for the sellers"
    if paid < 0:
        return "less than nothing for the sellers"         # the market's rules have no penalty, and a split of a negative sum would bill the nodes
    if "full_price_usd" in s and not (sane(s["full_price_usd"]) and s["full_price_usd"] >= 0):
        return "a full price that can't be read"           # every node's rate reads it
    comps = s.get("components")
    if comps is not None and not (isinstance(comps, list) and all(isinstance(r, dict) and sane(r.get("delivered", 0.0)) for r in comps)):
        return "components that can't be read"
    caps = s.get("caps_kw")
    if not _kw_of(s.get("capped_kw")) or not (caps is None or (isinstance(caps, dict) and all(_kw_of(v) for v in caps.values()))):
        return "caps that can't be read"
    top = s.get("top_up")
    if top is not None and not (isinstance(top, int) and not isinstance(top, bool) and top >= 0):
        return "a top-up round that can't be read"
    if s.get("currency") is not None and not isinstance(s["currency"], str):
        return "a currency that can't be read"
    meters = s.get("actuals")
    if meters is not None and not isinstance(meters, dict):
        return "actuals that can't be read"
    if meters is not None and paid > 0 and not any(v["BASELINE"] - v["USAGE"] > 0 or (v.get("BATT") or 0.0) > 0 for m in clean_actuals(meters, lambda *a, **k: None, "").values() for v in m.values()):
        return "a sum for the sellers and no meter that shows them delivering"      # it would pay nobody, with the sale marked done
    try:
        json.dumps({k: v for k, v in s.items() if k != "actuals"}, allow_nan=False)     # whatever else it carries goes on the record, and a NaN there stops the routes that serve it
    except (TypeError, ValueError, RecursionError):
        return "a number that isn't real"
    return lacking_problem(s.get("lacking"))


def call_settlement_problem(s: Any, rec: dict[str, Any], buyer: str, most_kwh: float) -> str | None:
    """settlement_problem, for a call: why this one can't be paid on, or None. What gets past here is taken for paid, and only a top-up could mend it, so one junk number would hold all that
    the call's nodes are owed, or pay one of them less than nothing. A call refused here keeps why (settlement_refused, with an rt_settlement_refused log) until one that can be read comes.
    most_kwh: what the call could bring in, at its kW."""
    if not isinstance(s, dict):
        return "it isn't a settlement"
    if rec.get("from") != buyer:
        return "it isn't this buyer's call"
    money, kwh, top = [s.get("paid_usd", 0.0)] + ([s["full_price_usd"]] if "full_price_usd" in s else []), s.get("delivered_kwh", 0.0), s.get("top_up")
    if not all(sane(v) and v >= 0 for v in money):
        return "no real sum"
    if not (sane(kwh) and kwh >= 0) or kwh > most_kwh + 0.01:
        return "a delivery the call can't have brought in"
    homes, batt = s.get("by_home_kwh"), s.get("by_home_batt_kwh")
    if not all(x is not None and isinstance(x, dict) and all(sane(v) and v >= 0 for v in x.values()) for x in (homes, {} if batt is None else batt)):
        return "kWh that can't be read"
    if sum(homes.values()) > kwh + 0.01 + 1e-4 * len(homes):
        return "more kWh for its nodes than it says the call brought in"     # a node's rate is the sum over them all, so a stranger's kWh would take from each of them
    read = s.get("read")
    if read is not None and not (isinstance(read, dict) and all(isinstance(v, list) for v in read.values())):
        return "a list of what it read that can't be read"
    if top is not None and not (isinstance(top, int) and not isinstance(top, bool) and top >= 0):
        return "a top-up round that can't be read"
    if s.get("currency") is not None and not isinstance(s["currency"], str):
        return "a currency that can't be read"
    try:
        json.dumps(s, allow_nan=False)                     # it stays on the record, and a NaN there stops the routes that serve it
    except (TypeError, ValueError, RecursionError):
        return "a number that isn't real"
    return None


def buyers_disagree(orders: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Half hours where two buyers hold different meters for one node: it told them different things, and each pays on its own copy. Each is held to its limits, and this says so."""
    seen: dict[tuple[str, str], float] = {}
    out: dict[str, list[str]] = {}
    for od in orders:
        for h, m in ((od.get("settlement") or {}).get("actuals") or {}).items():
            for k, v in (m.items() if isinstance(m, dict) else ()):
                u = v.get("USAGE") if isinstance(v, dict) else None
                if real(u) and _differs(u, seen.setdefault((h, str(k)), u)):
                    out.setdefault(h, []).append(str(k))
    return out

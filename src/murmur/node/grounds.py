"""What an offer carries about the node's own state, so that what changes later can be told from what the offer already allowed for.

  keep_out      a person's wishes take their parts out of the safe offer
  stamp, seen   the person's settings and the node's conditions when the offer went out
  since_offer   what changed after the offer and bears on what it holds: the facts a commitment's receipt cites
"""
from __future__ import annotations

import json
from typing import Any

from murmur.node.note_reader import quoted
from murmur.node import note_words
from murmur.node import note_reader

OFFER_KW = {"battery": "battery_kw", "car": "ev_pause_kw", "cooling": "ac_kw", "devices": "app_kw", "lighting": "light_kw"}      # each part of an offer, as a slot names it
ROOMS = ("cooling", "lighting")      # what a space's own day bears on
WISH_DEVICES = {"keep_hot_water": {"hpwh"}, "keep_machines_on": {"pool", "dish", "dryer", "plugs"}, "keep_house_as_is": {"fans"}, "keep_car_ready": {"ev", "v2h"}}      # what each wish takes out of an offer's devices


def stamp(w: dict[str, Any]) -> str:
    """The owner's or manager's wishes, as a mark to compare later."""
    return json.dumps({k: v for k, v in w.items() if k != "notes"}, sort_keys=True, default=str) + str(len(w.get("notes") or []))


def settings_moved(mark: str, w: dict[str, Any], price: float | None) -> list[tuple[str, tuple[str, ...] | None]]:
    """What a change in the person's own settings bears on, from the stamp the offer went out with. Only what takes something away can bear on a commitment, and each setting has its own part:
    a minimum price that rises and stays under the sale's price takes nothing away. A day off isn't here: code says no to that day by itself. New words on file are, at a node that has
    no note step, where the answer is the only reading they get. price: the sale's, or None if it isn't known, and then a higher minimum counts."""
    words = ("The owner's or manager's wishes changed after the offer went out.", None)
    if mark == stamp(w):
        return []
    try:
        end = mark.rindex("}") + 1
        old, notes = json.loads(mark[:end]), mark[end:]
    except ValueError:
        return [words]                              # a mark that can't be read: it isn't what is on file now, and that's all that can be said
    out: list[tuple[str, tuple[str, ...] | None]] = []
    for key, part in (("battery_max_share", "battery"), ("cooling_max_share", "cooling"), ("lighting_max_share", "lighting")):
        if key in w and float(w[key]) < float(old.get(key, 1.0)):
            out.append((f"The share of the {part} that may be sold came down after the offer went out.", (part,)))
    if set(w.get("devices_off") or ()) - set(old.get("devices_off") or ()):
        out.append(("More devices were taken out of sales after the offer went out.", ("devices",)))
    if w.get("no_ev_pause") and not old.get("no_ev_pause"):
        out.append(("The car may no longer be paused for a sale.", ("car",)))
    least = float(w.get("min_price_usd_per_kwh") or 0.0)
    if least > float(old.get("min_price_usd_per_kwh") or 0.0) and (price is None or least > price):
        out.append(("The lowest price they will take rose above this sale's after the offer went out.", None))
    if notes != str(len(w.get("notes") or [])):
        out.append(words)
    return out


def schedule_in(v2: Any, need: dict[str, Any]) -> list[dict[str, str]]:
    """The node's day-before plan over the window: busy and free blocks only, which is all a calendar may say."""
    from murmur.node import context
    agent = getattr(v2, "agent", None)
    a, b, day = need["window_start"][11:16], need["window_end"][11:16], need["window_start"][:10]
    try:
        svc = agent.ctx.schedule if agent is not None else context.Schedule("building" if getattr(v2, "is_building", False) else "home")
        rows = svc.blocks(v2.name, day)
    except (OSError, KeyError, ValueError, IndexError, AttributeError):
        return []
    return [{"space": r["space"], "state": r["state"], "from": r["start"], "to": r["end"]} for r in rows if r["start"] < b and r["end"] > a][:12]


def parts_left(offer: dict[str, Any]) -> set[str]:
    """The parts of this offer with kW in them."""
    return {p for p, k in OFFER_KW.items() if any(float(s.get(k) or 0.0) > 0 for s in offer.get("slots") or [])}

def in_force(w: dict[str, Any], start: str) -> bool:
    """Does this wish reach a sale that starts then? One with no end of its own holds through the next sale."""
    return not w.get("until") or w["until"] > start


def keep_out(offer: dict[str, Any], wishes: list[dict[str, Any]], need: dict[str, Any]) -> dict[str, Any]:
    """The offer less what a wish in force keeps out, at every node, thinking or not: the wish closes those devices at the sale, so a kW left in is a kW nobody can deliver,
    and the buyers would learn of it only at delivery."""
    live = [w for w in wishes if in_force(w, need["window_start"])]
    if not live:
        return offer
    from murmur.protocol import envelope as beckn
    from murmur.node.offer_shape import drop_devices, scale_offer
    parts = {note_reader.PART[w["wish"]] for w in live}
    gone = set().union(*[WISH_DEVICES.get(w["wish"], set()) for w in live])
    out = drop_devices(offer, sorted(gone & set((offer.get("appliances") or {}).get("by_device") or {})))
    if not offer.get("node") == "building":         # the evening's rebound and the car follow the battery and the pause
        out = scale_offer(out, 0.0 if "battery" in parts else 1.0, "car" not in parts, True)
    else:
        out = json.loads(json.dumps(out))
    for s in out["slots"]:
        for p in parts - {"devices"}:
            kw = float(s.get(OFFER_KW[p]) or 0.0)
            if kw:
                s[OFFER_KW[p]] = 0.0
                s["kw_offered"] = round(max(0.0, float(s["kw_offered"]) - kw), 2)
    out["energy_kwh"] = round(sum(s["kw_offered"] for s in out["slots"]) * beckn.SLOT_MINUTES / 60, 2)
    out["kept_out"] = {"parts": sorted(parts), "why": sorted({note_words.SAYS[w["wish"]] for w in live})}
    return out


def seen(v2: Any, w: dict[str, Any]) -> dict[str, Any]:
    """What the node knew when its offer went out. It goes with the offer, so what is new later can be told from what the offer already allowed for."""
    ov = getattr(v2.adapter, "overrides", None) or {}
    wishes = getattr(getattr(getattr(v2, "agent", None), "guard", None), "wishes", None) or []
    return {"note": note_reader.note_key(ov) if ov.get("note") else None, "ev_now": bool(ov.get("ev_now")), "day": bool(ov.get("closed") or ov.get("zone_event")), "limits": stamp({**w, "notes": []}),
            "wishes": [[x["wish"], x.get("from") or ""] for x in wishes]}


def since_offer(v2: Any, offer: dict[str, Any], w: dict[str, Any], start: str = "", price: float | None = None) -> list[dict[str, Any]]:
    """What could make a commitment inside the offer a real question: what changed after the offer went out and bears on what it holds. The commitment's receipt cites
    these, each by its id, and an empty list reads as nothing changed. A note written before the offer isn't here, and neither is a wish it already allowed for, or one that has
    ended by the sale. At a node with a note step the note itself isn't here at all: what it asks for is here, as the wish the model read in it, and a note with no wish changes nothing."""
    sim = v2.adapter
    ov = getattr(sim, "overrides", None) or {}
    agent = offer.get("agent") or {}
    had = agent.get("seen") or {}
    reader = getattr(v2, "agent", None)
    out: list[tuple[str, tuple[str, ...] | None]] = []
    if ov.get("note") and reader is None and had.get("note") != note_reader.note_key(ov):
        out.append((f'A note came in: "{quoted(ov["note"])}"', None))
    if ov.get("ev_now") and not had.get("ev_now"):
        out.append(("The owner needs the car now.", ("car",)))
    if float(getattr(sim, "E", 0.0)) > 0 and float(getattr(sim, "P", 1.0)) <= 0 and not (offer.get("battery") or {}).get("out_of_service"):
        out.append(("The battery shut off after the offer went out.", ("battery",)))
    if (ov.get("closed") or ov.get("zone_event")) and not had.get("day"):
        out.append(("The building's day changed after the offer went out.", None if ov.get("closed") else ROOMS))
    if reader is not None and "limits" in had:
        out += settings_moved(had["limits"], {**w, "notes": []}, price)
    elif agent.get("wishes") is not None:
        out += settings_moved(agent["wishes"], w, price)
    known = {tuple(x) for x in had.get("wishes") or []}
    for x in getattr(getattr(reader, "guard", None), "wishes", None) or []:
        if (x["wish"], x.get("from") or "") not in known and in_force(x, start):
            out.append((note_words.SAYS[x["wish"]], (note_reader.PART[x["wish"]],)))
    left = parts_left(offer)
    keep = [(x, a) for x, a in dict(out).items() if a is None or not offer.get("slots") or left & set(a)]     # a change in a part with no kW in the offer changes nothing it holds
    return [{"id": f"F{i + 1}", "says": x, **({} if a is None else {"bears_on": list(a)})} for i, (x, a) in enumerate(keep)]

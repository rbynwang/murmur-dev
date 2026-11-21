"""The shapes of an offer under a person's standing limits: the owner's wishes (a home), the manager's policy (a building), and the
arithmetic that takes a share of the planner's safe offer without ever giving more than it. The decision log of a node lives here too."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from murmur.protocol import envelope as beckn

DEFAULT_WISHES = {"skip_until": None, "skip_days": [], "no_ev_pause": False, "battery_max_share": 1.0,
                  "min_price_usd_per_kwh": 0.0, "notes": [], "devices_off": []}
DEFAULT_POLICY = {"skip_until": None, "skip_days": [], "cooling_max_share": 1.0, "lighting_max_share": 1.0,
                  "min_price_usd_per_kwh": 0.0, "notes": [], "devices_off": []}
REBOUND_FRACTIONS = (0.25, 0.5, 0.75, 1.0)


def _plain(o: Any) -> Any:
    """json.dumps default: numpy scalars as plain Python values."""
    for m in ("item", "tolist"):
        if hasattr(o, m):
            return getattr(o, m)()
    return str(o)


class Wishes:
    """The owner's standing wishes for a home, read from a file beside its state."""
    DEFAULT, WHO = DEFAULT_WISHES, "the owner"

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        try:
            w = {**self.DEFAULT, **json.loads(path.read_text())}
        except (OSError, ValueError, TypeError, RecursionError):
            w = json.loads(json.dumps(self.DEFAULT))
        self.w = {k: w.get(k, v) for k, v in self.DEFAULT.items()}

    def get(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.w))

    def skips(self, day: str) -> str | None:
        """Why this day is off by the person's wish, or None."""
        w = self.get()
        if w["skip_until"] and day <= w["skip_until"]:
            return f"{self.WHO} asked to skip events until {w['skip_until']}"
        if day in w["skip_days"]:
            return f"{self.WHO} asked to skip {day}"
        return None


class FacilityPolicy(Wishes):
    """The facility manager's standing policy for a building: days off, the most of its cooling and of its lighting it may offer, a minimum price."""
    DEFAULT, WHO = DEFAULT_POLICY, "the facility manager"


def drop_devices(offer: dict[str, Any], off: list[str]) -> dict[str, Any]:
    """The offer without these devices' part (never more than it was): the planner's kW for the rest, in proportion."""
    a = offer.get("appliances") or {}
    by = a.get("by_device") or {}
    total = sum(by.values())
    gone = sum(v for k, v in by.items() if k in off)
    if not off or total <= 0 or gone <= 0:
        return offer
    out = json.loads(json.dumps(offer))
    keep = 1.0 - gone / total
    for s in out["slots"]:
        a0 = float(s.get("app_kw") or 0.0)
        s["app_kw"] = round(a0 * keep, 3)
        s["kw_offered"] = round(max(0.0, s["kw_offered"] - (a0 - s["app_kw"])), 2)
    out["energy_kwh"] = round(sum(s["kw_offered"] for s in out["slots"]) * beckn.SLOT_MINUTES / 60, 2)
    out["appliances"] = {**a, "kw": round(float(a.get("kw", 0.0)) * keep, 3), "mean_kw": round(float(a.get("mean_kw", 0.0)) * keep, 3),
                         "by_device": {k: v for k, v in by.items() if k not in off}}
    return out


def scale_offer(offer: dict[str, Any], share: float, pause_ev: bool, take_part: bool) -> dict[str, Any]:
    """The planner's safe offer with only part of its battery and, or not, its car's pause. Never more than the planner offered. The evening
    follows: the rebound at a delivery level f of the new offer is the planner's at f x share, and without the car's pause the evening is the
    no-event one. Unchanged shares give the planner's offer to the decimal."""
    from murmur.agents.community.market_rules import _rebound_at
    share = max(0.0, min(1.0, share)) if take_part else 0.0
    ev_on = pause_ev and take_part
    had_ev = any(float(s.get("ev_pause_kw") or 0.0) > 0.0 for s in offer["slots"])
    out = json.loads(json.dumps(offer))
    for s in out["slots"]:
        b0, e0, k0 = s["battery_kw"], s["ev_pause_kw"], s["kw_offered"]
        s["battery_kw"] = round(b0 * share, 2)
        s["ev_pause_kw"] = round(e0 if ev_on else 0.0, 2)
        other = 0.0 if not take_part else float(s.get("ac_kw") or 0.0) + float(s.get("app_kw") or 0.0)
        s["kw_offered"] = 0.0 if s["battery_kw"] + s["ev_pause_kw"] + other <= 0 else \
            round(max(0.0, min(k0, k0 - (b0 - s["battery_kw"]) - (e0 - s["ev_pause_kw"]))), 2)
    if all(abs(a["kw_offered"] - b["kw_offered"]) < 1e-9 for a, b in zip(out["slots"], offer["slots"])):
        out["energy_kwh"] = offer["energy_kwh"]
    else:
        out["energy_kwh"] = round(sum(s["kw_offered"] for s in out["slots"]) * beckn.SLOT_MINUTES / 60, 2)
    ev = out.get("evening") or {}
    if ev.get("rebound_kw") and share < 0.999:
        old = offer["evening"]["rebound_kw"]
        ev["rebound_kw"] = {str(f): [round(x, 2) for x in _rebound_at(old, f * share)] for f in REBOUND_FRACTIONS}
    if not ev_on and had_ev:
        if ev.get("import_cf_kw"):
            ev["import_noev_kw"] = list(ev["import_cf_kw"])
        out["ev_flex"] = None
    return out


def scale_building_offer(offer: dict[str, Any], cooling_share: float, lighting_share: float, take_part: bool) -> dict[str, Any]:
    """A building's safe offer with only part of its cooling (ac_kw) and of its lighting (light_kw) per half hour. Never more than the planner offered."""
    cs = max(0.0, min(1.0, cooling_share)) if take_part else 0.0
    ls = max(0.0, min(1.0, lighting_share)) if take_part else 0.0
    out = json.loads(json.dumps(offer))
    for s in out["slots"]:
        a0, l0, k0 = float(s.get("ac_kw") or 0.0), float(s.get("light_kw") or 0.0), float(s["kw_offered"])
        a1, l1 = round(a0 * cs, 2), round(l0 * ls, 2)
        if "ac_kw" in s:
            s["ac_kw"] = a1
        if "light_kw" in s:
            s["light_kw"] = l1
        if not take_part:
            s.update({"kw_offered": 0.0, "battery_kw": 0.0, "ev_pause_kw": 0.0})
            continue
        s["kw_offered"] = round(max(0.0, min(k0, k0 - (a0 - a1) - (l0 - l1))), 2)
    if all(abs(a["kw_offered"] - b["kw_offered"]) < 1e-9 for a, b in zip(out["slots"], offer["slots"])):
        out["energy_kwh"] = offer["energy_kwh"]
    else:
        out["energy_kwh"] = round(sum(s["kw_offered"] for s in out["slots"]) * beckn.SLOT_MINUTES / 60, 2)
    for k, sh in (("air_conditioning", cs), ("lighting", ls)):
        if isinstance(out.get(k), dict):
            out[k]["agent_share"] = round(sh, 2)
    return out


def held_back(limit: dict[str, Any], final: dict[str, Any]) -> dict[str, float]:
    """kW per half hour between what the rule allows and what was offered."""
    return {str(a["id"]): round(max(0.0, float(a["kw_offered"]) - float(b["kw_offered"])), 2) for a, b in zip(limit["slots"], final["slots"])}


def kw_of(offer: dict[str, Any]) -> list[float]:
    return [round(float(s.get("kw_offered") or 0.0), 2) for s in offer.get("slots") or []]


def mean_kw(offer: dict[str, Any]) -> float:
    k = kw_of(offer)
    return sum(k) / max(1, len(k))


class Decisions:
    """The node's decision log: plain JSON values only (the planner's numbers can be numpy scalars)."""

    def __init__(self, n: int = 60):
        self.items: deque = deque(maxlen=n)
        self.lock = threading.Lock()
        self.seq = 0

    def add(self, **d: Any) -> dict[str, Any]:
        d = json.loads(json.dumps(d, default=_plain))
        with self.lock:
            self.seq += 1
            d = {"n": self.seq, "wall": round(time.time(), 3), **d}
            self.items.append(d)
            return d

    def list(self, n: int = 30) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.items)[-n:]

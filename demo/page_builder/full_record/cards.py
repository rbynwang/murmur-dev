"""What a step shows on the sheet's own cards: the small model's queue, the envelope on Town, the guard's six checks, the
tool chain, the appliance table and the coordinator's and buyers' cards. Each reads the step's own recorded lines."""
from __future__ import annotations

import json
import re
from typing import Any

from ..templating import esc
from .anchors import device_anchor, queue_kind
from .figures import short_nums, usd
from .naming import data
from .record import Record

TOOK = re.compile(r"([\d,]+) tokens read, ([\d,]+) written, ([\d,]+) ms")
ENVELOPE = re.compile(r"envelope\s+message_id=(\S+)\s+from=\S+\s+to=\S+\s+kind=(\S+)")
SIGNER = re.compile(r"signer (\S+)\s+sig (\S+)")
BODY = re.compile(r"body\s+([\d,]+) bytes")
CHECK = re.compile(r"#\s*steps?\s+([1-6])(?:\s+to\s+([1-6]))?")
POLICY = re.compile(r"policy\b", re.I)
READS = re.compile(r"device reads at (\d\d:\d\d)[^:]*: (.*)")
PAIR = re.compile(r"(\w+)=(\S+)")
EVERY_NODE = re.compile(r"(home-\d+|building-\d+): at (\d\d:\d\d) (.*)")
REFUSED = re.compile(r"Refused here: (\d+)")
ORDER = re.compile(r"place_order\((.*)\)$")

# The readings an appliance card shows, and what it calls them
DEVICE_KEYS = {"battery": ("soc_pct", "batt_kw"), "campus": ("soc_pct", "batt_kw"), "car": ("ev_kw", "ev_held", "v2h_kw"), "cooling": ("cool_kw", "cool_own_day_kw", "t_dev_c"),
               "plant": ("cool_kw", "cool_own_day_kw", "t_dev_c"), "lights": ("light_dim_kw",), "plugs": ("grid_kw", "grid_cf_kw"), "water": ("grid_kw", "grid_cf_kw")}
KEY_NAME = {"soc_pct": "charge %", "batt_kw": "battery kW", "ev_kw": "charging kW", "ev_held": "car held", "v2h_kw": "giving kW", "cool_kw": "cooling kW", "cool_own_day_kw": "its own day",
            "t_dev_c": "warmer by C", "light_dim_kw": "dimmed kW", "grid_kw": "meter kW", "grid_cf_kw": "no-sale kW"}


def texts(s: dict[str, Any]) -> list[str]:
    return [str(t.get("text") or "") for t in s.get("terminal") or []]


def queue_state(rec: Record, s: dict[str, Any], x: dict[str, Any], st: dict[str, Any], seen: dict[str, Any]) -> None:
    """The small model's bars: answers of this kind so far, against the most of any kind; and its last answer."""
    cat = queue_kind(s)
    q = seen.setdefault("_q", {})
    q[cat] = q.get(cat, 0) + 1
    top = max(rec.queue_max.values())
    x[f"qn-{cat}"] = str(q[cat])
    st.setdefault("w", {})[f"q-{cat}"] = min(100.0, round(q[cat] / max(1, top) * 100, 1))
    took = TOOK.search(" ".join(texts(s)))
    secs = int(took.group(3).replace(",", "")) / 1000
    x["q-last"] = esc(data(f'Last answer: {s.get("node")}, {took.group(1)} tokens read, {took.group(2)} written, {secs:.1f} s'))


def town_state(s: dict[str, Any], st: dict[str, Any], seen: dict[str, Any]) -> None:
    """The envelope on the channel: its outside only, as Town sees it."""
    seen["_town"] = seen.get("_town", 0) + 1
    x = st.setdefault("x", {})
    x["town-n"] = f'{seen["_town"]}'
    x["env-from"], x["env-to"] = esc(data(s.get("from") or "")), esc(data(s.get("to") or ""))
    for text in texts(s):
        m = ENVELOPE.match(text)
        if m:
            x["env-id"], x["env-kind"] = esc(data(m.group(1))), esc(m.group(2))
        m = SIGNER.match(text)
        if m:
            x["env-sig"] = esc(m.group(2))
        m = BODY.match(text)
        if m:
            x["env-size"] = esc(m.group(1)) + " bytes, unread"


def guard_state(s: dict[str, Any], k: dict[str, str], x: dict[str, Any]) -> list[list[float]]:
    """The six checks, all passed (every call of these recordings is done), when in its trace the guard reached each
    one, and what it said."""
    lines = texts(s)
    said = next(t for t in reversed(lines) if t.startswith("guard says"))
    reached: list[int] = []
    marks: list[list[float]] = []
    for i, t in enumerate(lines):
        m = CHECK.search(t)
        if m:
            for n in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1):
                if n not in reached:
                    reached.append(n)
                    marks.append([round(i / max(1, len(lines)), 3), n])
    for i in range(1, 7):
        k[f"ck-{i}"] = "ok"
    x["lk-guard"] = esc(data(said[:170]))
    return marks


def chain_state(s: dict[str, Any], lay: str, x: dict[str, Any]) -> None:
    """The tool chain's boxes, each from the line that says it: a guard step's first call on the menu and its policy, a
    driver step's seal and what the driver took."""
    for t in s.get("terminal") or []:
        text, kd = str(t.get("text") or ""), t.get("kind")
        if lay == "guard" and kd == "tool" and "lk-menu" not in x:
            x["lk-menu"] = esc(data(text[:130]))
        if POLICY.match(text):
            x["lk-policy"] = esc(data(text[:130]))
        if lay == "driver" and kd == "sign":
            x["lk-seal"] = esc(data(text[:130]))
        if lay == "driver" and kd == "in":
            x["lk-driver"] = esc(data(text[:130]))


def show_read(key: str, r: tuple[str, dict[str, str]]) -> str:
    """One reading of a device, by the figures its card shows; a home that keeps none of them shows its meter."""
    keep = [q for q in DEVICE_KEYS.get(key, ()) if q in r[1]] or [q for q in ("grid_kw", "grid_cf_kw") if q in r[1]]
    return r[0] + "  " + "  ".join(f"{KEY_NAME.get(q, q)} {r[1][q]}" for q in keep)


def device_state(rec: Record, s: dict[str, Any], x: dict[str, Any]) -> None:
    """Before and after, from the record's own readings of the device: a write shows its lever, and the delivery steps
    carry the followed nodes' readings on."""
    lay, node = s.get("layer"), str(s.get("node") or "")
    if lay == "device" and s.get("to"):
        a = device_anchor(str(s.get("to")))
        if not a:
            return
        key = a[5:]
        rows = rec.device_rows()
        if node and rows.get(key) and rows[key] != node:
            return
        reads = [(m.group(1), dict(PAIR.findall(m.group(2)))) for m in (READS.match(t) for t in texts(s)) if m]
        sets = [y.get("text") for y in s.get("terminal") or [] if y.get("kind") == "write"]
        x[f"dv-{key}-who"] = esc(data(f'{s.get("to")}, {s.get("node")}'))
        x[f"dv-{key}-set"] = esc(data(short_nums(str(sets[0]))[:90]))
        x[f"dv-{key}-was"] = esc(show_read(key, reads[0]))
        x[f"dv-{key}-now"] = esc(show_read(key, reads[-1]))
        return
    if lay == "device" and str(s.get("from")) == "all nodes":
        for t in texts(s):
            m = EVERY_NODE.match(t)
            if not m:
                continue
            r = (m.group(2), dict(PAIR.findall(m.group(3))))
            for key, who in rec.card_nodes().items():
                if who == m.group(1):
                    x[f"dv-{key}-now"] = esc(show_read(key, r))


def card_state(s: dict[str, Any], x: dict[str, Any]) -> None:
    """The coordinator's and the buyers' cards, from what the record says at that step."""
    t, plain = str(s.get("title") or ""), str(s.get("plain") or "")
    low = t.lower()
    if "second round" in low:
        x["co-r2"] = esc(data(plain))
    if "desk" in low and s.get("layer") in ("market", "coordinator"):
        x["co-desk"] = esc(data(plain))
    if s.get("layer") == "market" and s.get("stage") == "readings" or "readings are in" in low:
        hit = next((str(y.get("text") or "") for y in s.get("terminal") or [] if y.get("kind") == "guard"), "")
        m = REFUSED.search(hit)
        if m:
            x["rp-chk"] = f"{m.group(1)} refused"
    m = ORDER.match(next((str(y.get("text") or "") for y in s.get("terminal") or [] if y.get("kind") == "in"), ""))
    if m and s.get("layer") == "buyer":
        o = json.loads(m.group(1))
        who = "grid" if str(s.get("from")).startswith("grid") else "util"
        x[f"c-{who}-win"] = esc(f'{o.get("date")}, {o.get("start")} to {o.get("end")}')
        x[f"c-{who}-dep"] = usd(o.get("deposit_usd"))
        hours = int(str(o.get("end"))[:2]) - int(str(o.get("start"))[:2])
        x[f"c-{who}-val"] = usd(float(o.get("kw")) * hours * float(o.get("price_usd_per_kwh")))

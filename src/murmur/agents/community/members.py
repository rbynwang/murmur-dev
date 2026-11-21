"""The community's record of its members: who belongs behind its connection, each one's kinds and sizes of device, and what a member may hand its community agent."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from murmur.agents.community.community_rules import DEVICES, ID, SALES, amount, number


class Members:
    """The community's record of its members: who belongs, each one's kinds and sizes of device, what each agreed to (which kinds of sale, what share of the
    pay) and its opt-outs. Every change is kept with its time. path: where the record lives between runs, or None to keep it in memory."""

    def __init__(self, point: str = "", path: str | Path | None = None):
        self.point, self.path = point, Path(path) if path else None
        self.rows: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        if self.path and self.path.exists():
            d = json.loads(self.path.read_text())
            self.rows, self.history = d.get("members") or {}, d.get("history") or []

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"point": self.point, "members": self.rows, "history": self.history}, indent=1))
            tmp.replace(self.path)

    def note(self, at: str, member: str, what: str, **more: Any) -> None:
        self.history.append({"at": at, "member": member, "what": what, **more})
        self.save()

    def enrol(self, member: str, *, connects_at: str, devices: list[dict[str, Any]], sales: list[str] | tuple[str, ...] = ("evening_sale",), pay_share: float | None = None,
              at: str = "") -> dict[str, Any]:
        """A member joins. It must sit behind this community's one connection, and its devices are kinds and sizes: no make, no state, no name of a room."""
        if not (isinstance(member, str) and ID.match(member)):
            raise ValueError("a member is known by an id")
        if self.point and connects_at != self.point:
            raise ValueError("this member does not connect behind this community's connection")
        kept = []
        for d in devices or []:
            if not isinstance(d, dict) or set(d) - {"kind", "kw", "kwh"} or d.get("kind") not in DEVICES or not amount(d.get("kw")) or ("kwh" in d and not amount(d["kwh"])):
                raise ValueError(f"a device on the record is a kind from {', '.join(DEVICES)} with its kW, and kWh if it stores energy")
            kept.append({k: (d[k] if k == "kind" else float(d[k])) for k in ("kind", "kw", "kwh") if k in d})
        row = {"member": member, "connects_at": connects_at, "devices": kept, "agreed": self._agreed(sales, pay_share, at), "opt_outs": [], "enrolled_at": at}
        self.rows[member] = row
        self.note(at, member, "enrolled", sales=row["agreed"]["sales"], pay_share=row["agreed"]["pay_share"], devices=len(kept))
        return row

    @staticmethod
    def _agreed(sales: Any, pay_share: Any, at: str) -> dict[str, Any]:
        sales = list(sales or [])
        if not sales or any(s not in SALES for s in sales):
            raise ValueError(f"a member agrees to kinds of sale from {', '.join(SALES)}")
        if pay_share is not None and not (number(pay_share) and 0 <= pay_share <= 1):
            raise ValueError("a share of the pay is a number from 0 to 1")
        return {"sales": sales, "pay_share": None if pay_share is None else float(pay_share), "since": at}


    def refuses(self, member: str, sale: dict[str, Any]) -> str | None:
        """Why this member's offer for this sale isn't taken, or None. sale: {"id", "kind", "day", "start"}."""
        row = self.rows.get(member)
        if row is None:
            return "not on this community's member record"
        if sale.get("kind") not in row["agreed"]["sales"]:
            return "has not agreed to this kind of sale"
        for o in row["opt_outs"]:                    # written into the member record between runs: the record is the community's own file
            if "sale" in o and o["sale"] == sale.get("id"):
                return "opted out of this sale"
            if "day" in o and o["day"] == sale.get("day"):
                return "opted out for this day"
            if "until" in o and str(sale.get("start") or "") < o["until"]:
                return "opted out until a later time"
            if not {"sale", "day", "until"} & set(o):
                return "opted out"
        return None

    def view(self) -> dict[str, Any]:
        kinds: Counter = Counter(d["kind"] for r in self.rows.values() for d in r["devices"])
        return {"members": len(self.rows), "agreed": dict(Counter(s for r in self.rows.values() for s in r["agreed"]["sales"])), "opted_out": sum(1 for r in self.rows.values() if r["opt_outs"]),
                "devices": dict(kinds), "kw_on_record": round(sum(d["kw"] for r in self.rows.values() for d in r["devices"]), 1), "changes": len(self.history)}


# =================================================================================================== 3. refusals
class Refused(ValueError):
    """A definition, request or row the community doesn't take in. Its words name the rule and never what was in it."""

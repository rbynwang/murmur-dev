"""A live evening as the replay's builder reads one. It is made from the run's facts before any step exists, and filled as the
run goes on with what the cards read beside the steps: the buyers' orders, the followed nodes, the sale's totals.

facts = {day, homes, buildings, sites, follow: {thinking_home, second_home, mall_or_office}, half_hours, model}: the sale's
day; how many homes, buildings and single sites the network runs (a count or a list); the nodes the story follows; the
window's half hours by their starts ("18:00"); the small model's name.
"""
from __future__ import annotations

import re
from typing import Any

from ..replay.evening import Evening
from ..replay.text import kw as whole, num, usd


def count(x: Any) -> int:
    return len(x) if isinstance(x, (list, tuple, set, dict)) else int(x or 0)


def hm(when: Any) -> str:
    """A time of day as the page writes it, from "18:00" or from a whole timestamp."""
    m = re.search(r"\d\d:\d\d", str(when))
    return m.group(0) if m else str(when)


class LiveEvening(Evening):
    """The evening a live story is built on: the recording's shape, with nothing recorded yet."""

    def __init__(self, facts: dict[str, Any]):
        follow = {key: {"node": str(node)} for key, node in (facts.get("follow") or {}).items() if node}
        halves = [{"start": hm(h.get("start") if isinstance(h, dict) else h)} for h in facts.get("half_hours") or []]
        super().__init__({"meta": {"day": str(facts["day"]), "model": str(facts.get("model") or ""),
                                   "community": {"homes": count(facts.get("homes")), "buildings": count(facts.get("buildings"))},
                                   # the meter's own sums against the no-sale twin, so the half hours' card is not called an estimate
                                   "engie": {"single_sites": count(facts.get("sites")), "window_from_settled_truth": True}},
                          "cast": {"follow": follow}, "ledger": {"half_hours": halves, "totals": {}, "nodes": {}}})

    def order(self, buyer: str, kw: Any, start: Any, end: Any, price: Any, deposit: Any) -> None:
        """A buyer's order as it was placed, in the words the buyers' card shows (the builder's form, replay/evening.py:44-47).
        Its value if delivered in full is worked out here, as the recorder worked it out: kW, hours and price multiplied."""
        a, b = hm(start), hm(end)
        worth = None
        if num(kw) is not None and num(price) is not None and re.fullmatch(r"\d\d:\d\d", a) and re.fullmatch(r"\d\d:\d\d", b):
            minutes = (int(b[:2]) * 60 + int(b[3:]) - int(a[:2]) * 60 - int(a[3:])) % 1440
            worth = kw * minutes / 60 * price
        self.orders[str(buyer)] = {"kw": f"{whole(kw)} kW" if num(kw) is not None else "", "win": f"{a} to {b}",
                                   "price": f"${price:.2f} per kWh" if num(price) else "", "worth": usd(worth),
                                   "dep": f"${deposit:,.2f}" if num(deposit) else ""}

    def totals(self, deposits: dict[str, Any] | None = None, sold_kwh: Any = None, delivered_kwh: Any = None) -> None:
        """The sale's totals as far as they are known, under the names the figures read (replay/figures.py:64-143): each
        buyer's deposit as placed (a number, or its ledger row), the kWh sold and the kWh the meters show."""
        tot = self.ledger["totals"]
        for buyer, placed in (deposits or {}).items():
            tot.setdefault("deposits", {})[str(buyer)] = dict(placed) if isinstance(placed, dict) else {"placed_usd": placed}
        tot.update({k: v for k, v in (("sold_kwh", sold_kwh), ("delivered_kwh", delivered_kwh)) if v is not None})

    def node(self, name: str, kind: Any = None, battery_kwh: Any = None, devices: Any = None, shelf: Any = None, firm_kw: Any = None,
             tentative_kw: Any = None, offered_kw: Any = None) -> None:
        """What is known of a node, merged into what its card reads (replay/panels.py:125-150, figures.py:167-170): what it is
        and has, and its offer's firm and tentative parts. A node named here for the first time is followed from here on."""
        cast = self.followed.setdefault(str(name), {"node": str(name)})
        cast.update({k: v for k, v in (("kind", kind), ("battery_kwh", battery_kwh), ("devices", devices), ("shelf", shelf)) if v is not None})
        row = self.ledger["nodes"].setdefault(str(name), {})
        row.update({k: v for k, v in (("kind", kind), ("firm_kw", firm_kw), ("tentative_kw", tentative_kw), ("offered_kw", offered_kw))
                    if v is not None})

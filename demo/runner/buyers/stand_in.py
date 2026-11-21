"""The two stand-in buyers: the utility and the grid operator. Each orders for the evening, contracts with the community agent, sends
baselines and settles on the members' signed readings.
"""
from __future__ import annotations

from typing import Any

from murmur.protocol import envelope as beckn
from demo.runner.buyers.utility import Utility


class StandInBuyer(Utility):
    CLASS_RATES = True                                  # the desk pays a pool's call by class, so a call is billed by class too

    def __init__(self, name: str = "utility"):
        super().__init__(f"{name}.key")
        self.name = name
        if name != "utility":
            self.ORDER_PREFIX = f"{name}-need-"
            self.PARTICIPANT = f"{name}-stand-in"
        # the program's days stay out of every baseline, whether or not this buyer orders on them
        self.event_days = {beckn.need_from_catalog(r, o)["window_start"][:10] for r, o in Utility._pairs(self)}
        self.watch.price_rule = False

    def _pairs(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(o["resource"], o["offer"]) for o in self.orders.values()]

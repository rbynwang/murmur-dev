"""The community's small rules: what the level above may send, a number taken in, and a report row in the participants' own form."""
from __future__ import annotations

import json
import math
import re
from typing import Any


STEP_MIN = 15


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")              # a name a machine gave: no room for a sentence


TIME = re.compile(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?(Z|[+-]\d\d:\d\d)?$")




SALES = ("evening_sale", "grid_call")                                # the kinds of sale a member can agree to: the day-ahead evening sale, and a call during it


DEVICES = ("battery", "car_charger", "two_way_car", "heating", "cooling", "water_heater", "laundry", "dishwasher", "pool_pump", "lighting", "solar", "plant", "other")




FEED = frozenset({"ts", "meter_kw", "expect_kw", "battery_kw", "soc_pct", "price_usd_kwh", "idle_kw", "own_kwh", "recorded_kw", "store_kwh"})      # what the community is told while it runs: numbers by the quarter hour


RUNS = frozenset({"idle_kw", "own_kwh", "recorded_kw", "store_kwh"})        # only where the community agent holds the members' batteries itself (Battery.run_by_agent): what its meter reads with the battery idle, the battery's own schedule, what the connection is known to carry, and the charge it starts from


ASKED = frozenset({"ts", "battery_kw", "price_usd_kwh"})            # what the level above may ask for, by the quarter hour: never the community's own meter or its battery's charge


REQUEST = frozenset({"id", "community", "made_at", "rows"})         # a request from above: its id, the community it is for, when it was made, and its rows


REQUEST_ROWS = 96 * 2                                                # two days of quarter hours at most in one request


def _digest(rows: Any) -> str:
    """One request's rows as a short mark, so the same request can be known again without keeping what it said."""
    import hashlib
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


def number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def amount(v: Any) -> bool:
    return number(v) and v >= 0


# =================================================================================================== 6. the report upward
def row(entity_id: str, timestamp: Any, net_kw: float | None, soc_pct: float | None, price_usd_kwh: float | None, text: str, meter_kw: float | None = None,
        members: Any = ()) -> dict[str, Any]:
    """One quarter hour, as ENGIE's participants send it: who, when, net power (taking from the grid negative), the battery's state of charge, a quote to buy or sell at the
    step's price, and one plain line. The community's own meter stands beside it. Nothing of a single member is in it: a line that names one is refused."""
    if any(m and re.search(rf"(?<![A-Za-z0-9_.:-]){re.escape(str(m))}(?![A-Za-z0-9_.:-])", text) for m in members):
        raise ValueError("a community's report names no member")
    return {"entity_id": entity_id, "timestamp": timestamp, "reported_p_net_kw": None if net_kw is None else round(float(net_kw), 3),
            "reported_soc_percent": None if soc_pct is None else round(float(soc_pct), 2), "quote_side": None if net_kw is None else "buy" if net_kw < 0 else "sell",
            "quote_price_usd_kwh": None if price_usd_kwh is None else round(float(price_usd_kwh), 6), "text": text, "meter_p_net_kw": None if meter_kw is None else round(float(meter_kw), 3)}


def line(members: int, promised_kw: float, cover_kw: float, battery_kw: float, until: str, noun: str = "members") -> str:
    return f"community coordinator: {members} {noun} promise {promised_kw:,.0f} kW until {until[-5:]}, {cover_kw:,.0f} kW held as cover; battery gives {battery_kw:,.0f} kW"


QUIET = "community coordinator: no sale in this step"


NO_METER = "community coordinator: no meter reading for this step"

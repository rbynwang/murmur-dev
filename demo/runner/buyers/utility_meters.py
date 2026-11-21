"""A stand-in buyer's view of a member's meter, built from the dataset."""
from __future__ import annotations

from typing import Any


def _meter_cfg(home: dict[str, Any], ev_max: float) -> dict[str, Any]:
    b = home["battery"]
    return {"battery_kwh": b["kwh"], "battery_kw": b["kw"], "reserve_pct": b["reserve_pct"],
            "soc_max_pct": b["soc_max_pct"], "soc0_pct": b.get("soc0_pct", 55.0), "eta": b["eta"],
            "ev_max_kw": ev_max, "has_ev": home["has_ev"], "export_limit_kw": home["export_limit_kw"]}

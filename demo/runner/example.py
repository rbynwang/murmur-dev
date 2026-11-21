"""The demo's example evening, on the synthetic community (synthetic.py): 25 days of data from 2025-01-05, the evening of
2025-01-28 from 18:00 to 21:00, three homes and the office answering two buyers through the community agent, and a solar-and-
battery plant and a data center answering the aggregator beside it.

  python -m demo.runner example [--out out/example]     writes data/, evening.json and sites.json there

evening.json holds what the runner needs beyond the dataset: the window, who takes part, each buyer's order, the community's
definition (its connection, its shared battery, a week of its meter and its members' devices), the evening's feed (the load of
the rest of the community, the shared battery's charge and the price, by the quarter hour) and the aggregator's request to the
community's battery.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .synthetic import BUILDING, HOMES, Community, days_from, hour_of

FIRST_DAY, DAYS, EVENING = "2025-01-05", 25, "2025-01-28"      # a buyer's baseline reads 14 days back, the community's own fit 21 whole days
METER_FROM = "2025-01-20 10:00"                                 # the community's own meter: the week before the evening's clock starts
WINDOW = ["18:00", "21:00"]
ORDER_KW = {"utility": 9.0, "grid-operator": 5.4}
BATTERY = {"rating_kw": 40.0, "energy_kwh": 110.0, "out_factor": 0.9}


def base_kw(ts: str, rng: np.random.Generator) -> float:
    """The rest of the community at this quarter hour: what it draws less what its solar sends out (negative: it sends out)."""
    h = hour_of(ts)
    sun = max(0.0, math.sin(math.pi * (h - 7.5) / 9.0)) if 7.5 <= h <= 16.5 else 0.0
    return round(30.0 + (18.0 if 17 <= h < 22 else 0.0) - 55.0 * sun + float(rng.normal(0, 1.5)), 1)


def evening(c: Community) -> dict[str, Any]:
    rng = np.random.default_rng(7)
    steps = c.steps
    meter = {ts: base_kw(ts, rng) for ts in steps if METER_FROM <= ts < "2025-01-27 10:00"}
    feed = {ts: {"base_kw": base_kw(ts, rng), "soc_pct": 50.0, "price_usd_kwh": round(0.042 + (0.11 if 17 <= hour_of(ts) < 21 else 0.0), 5),
                 "battery_gives_kw": 0.0, "battery_takes_kw": 0.0} for ts in steps if "2025-01-27 10:00" <= ts < "2025-01-29 03:00"}
    members = [{"member": name, "at": "2025-01-27 00:00", "devices": [{"kind": "battery", "kw": kw, "kwh": kwh}, {"kind": "solar", "kw": 3.0 + i}]}
               for i, (name, (_, _, kwh, kw)) in enumerate(HOMES.items())]
    members.append({"member": BUILDING, "at": "2025-01-27 00:00", "devices": []})
    ask = {"made_at": f"{EVENING} 14:00",
           "rows": [{"ts": ts, "battery_kw": round(0.8 * BATTERY["rating_kw"], 1) if "19:00" <= ts[11:] < "21:00" else 0.0}
                    for ts in steps if ts[:10] == EVENING and ts[11:] >= "14:00"]}
    return {"date": EVENING, "window": WINDOW, "tier": 1, "community": "COMMUNITY_01", "homes": list(HOMES), "buildings": [BUILDING],
            "order_kw": ORDER_KW, "community_definition": {"id": "COMMUNITY_01", "point": "1", "limit_out_kw": 120.0, "solar_kw": 75.0,
                                                           "battery": BATTERY, "report_when_ended": True, "meter": meter, "members": members},
            "feed": feed, "battery_request": ask}


def constant(value: float) -> dict[str, Any]:
    """A model of one leaf: the same value for every row, in the tree export's column form (node/treemodel.py)."""
    leaf = {"f": [0], "thr": [0.0], "leaf": [True], "v": [0.0], "miss_left": [False], "cat": [False], "l": [0], "r": [0], "bitset": [0]}
    return {"baseline": value, "trees": [leaf], "bitsets": [[0] * 8]}


def plain(level: float, what: str) -> dict[str, Any]:
    """A model that says `level` times the series' own scale for every hour, within 10 % either way."""
    return {"features": ["temp"], "quantiles": {"0.1": constant(0.9 * level), "0.5": constant(level), "0.9": constant(1.1 * level)},
            "extra": {"mean": constant(level)}, "meta": {"what": what}}


def write_models(models: Path) -> None:
    """The forecast models the community agent reads. A synthetic community has no history to train on, so they are plain: its load
    at each hour is the mean of its own last 14 days, within 10 % either way (community_load). The community's forecaster is built
    on the homes' own models (home_base_load, solar_per_kw), which it replaces with community_load and gives no array of its own, so
    those two say only the plain level and nothing per kW of solar; the example's homes forecast by temperature regression and read
    neither. A dataset of measured days brings trained models in their place."""
    out = models / "forecast"
    out.mkdir(parents=True, exist_ok=True)
    for name, model in (("community_load", plain(1.0, "the community's load as the mean of its last 14 days, within 10 % either way")),
                        ("home_base_load", plain(1.0, "a home's load as the mean of its last 14 days, within 10 % either way")),
                        ("solar_per_kw", plain(0.0, "no solar per kW: the community's forecaster has no array of its own"))):
        with open(out / f"{name}.json.gz", "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as g:
            g.write(json.dumps(model, sort_keys=True).encode())
    (out / "fleet_errors.json").write_text(json.dumps({"kept_out": []}) + "\n")


def write(out: Path) -> str:
    """Writes the example into `out` (data/, models/, evening.json, sites.json) and says what it wrote."""
    out = Path(out)
    c = Community(days_from(FIRST_DAY, DAYS), EVENING)
    n = c.write(out / "data", out / "sites.json")
    write_models(out / "models")
    (out / "evening.json").write_text(json.dumps(evening(c), indent=1, sort_keys=True) + "\n")
    return f"{n} files in {out / 'data'}; {out / 'models'}; {out / 'evening.json'}; {out / 'sites.json'}"

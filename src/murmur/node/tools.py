"""The device tools a node's agent can call: each tool's card (what it moves, its range, its step), and each node's shelf of tools.
The cards are package data (tools.json, shelves.json, home_setup.json).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
PROMPT_VERSION = "2026-11-07"
TYPES = {"string": "string", "number": "number", "enum": "string", "time": "string"}


@lru_cache(maxsize=1)
def bundle() -> dict[str, Any]:
    return json.loads((HERE / "tools.json").read_text())


@lru_cache(maxsize=1)
def shelves() -> dict[str, Any]:
    return json.loads((HERE / "shelves.json").read_text())


@lru_cache(maxsize=1)
def home_setup() -> dict[str, Any]:
    return json.loads((HERE / "home_setup.json").read_text())


@lru_cache(maxsize=1)
def _profiles() -> dict[str, str]:
    from murmur import config
    try:
        return {h["name"]: str(h.get("profile") or "") for h in json.loads(config.data_path("fleet_v2.json").read_text())["homes"]}
    except (OSError, ValueError, KeyError):
        return {}


def home_id(name: str) -> str:
    """A home's id in the records (home_setup.json, shelves.json, the plans): the stem of its dataset profile, homes/HH010 -> HH010."""
    prof = _profiles().get(name)
    return Path(prof).name.upper() if prof else name.upper()


def shelf(name: str, tier: int) -> list[str]:
    """The tools this home holds at this tier."""
    return sorted((shelves()["homes"].get(home_id(name)) or {}).get(f"tier{tier}", []))


def building_shelf(key: str) -> list[str]:
    return list(shelves()["buildings"].get(key, []))


def spec(side: str, tool: str, targets: list[str] | None = None, only: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """The tool as the model sees it: its description and example, with start and end left to code. only: the values that fit now."""
    c = bundle()[side].get(tool) or bundle()["common"][tool]
    mv = c["model_view"]
    props: dict[str, Any] = {}
    req: list[str] = []
    for p in mv["parameters"]:
        if p["name"] in ("start", "end"):
            continue
        d: dict[str, Any] = {"type": TYPES.get(p["type"], "string"), "description": p.get("says", "")}
        if p["type"] == "enum":
            vals = [x.strip() for x in str(p["allowed"]).split("|") if x.strip()]
            d["enum"] = list(targets) if (p["name"] == "target" and targets) else (only or {}).get(p["name"], vals)
        elif p["name"] == "target" and targets:
            d["enum"] = list(targets)
        props[p["name"]] = d
        req.append(p["name"])
    desc = mv["description"]
    if mv.get("example"):
        desc += " Example: " + re.sub(r', (start|end)="[^"]*"', "", mv["example"])
    return {"type": "function", "function": {"name": tool, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": req}}}

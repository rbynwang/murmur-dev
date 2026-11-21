"""Members built from the fixture dataset the way a host builds them, with no bus: what a member sends lands in a list."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from murmur import config
from murmur.agents.home import HomeNodes
from murmur.agents.host_common import node_class
from murmur.node.offer_rule import BuildingRule, HomeRule
from murmur.node.offer_shape import FacilityPolicy, Wishes
from murmur.node.simulator import SimulatedHome
from murmur.protocol import signing
from murmur.replay import Replay

EVENING = {"replay_start": "2025-01-27 00:00", "replay_step_seconds": 60, "replay_loop_days": 0, "forecast": "temp_regression", "control_mode": "rolling",
           "buyers": ["utility"], "report_rule": "exception"}


@dataclass
class Model:
    """A model that answers every question with the calls it was given, one list per question in turn ([] when they run out)."""
    answers: list[list[dict[str, Any]]] = field(default_factory=list)
    text: str = ""
    model: str = "scripted"
    asked: list[tuple[str, str]] = field(default_factory=list)

    def ask(self, system: str, tools: list[dict[str, Any]], text: str) -> dict[str, Any]:
        self.asked.append((system, text))
        calls = self.answers.pop(0) if self.answers else []
        return {"calls": calls, "text": self.text, "ms": 1, "error": None}


def home(name: str = "home-01", tmp: Path | None = None, **cfg: Any) -> tuple[Any, list]:
    """(the member node, the list of what it sent) for one home of the fixture dataset."""
    c = {**EVENING, **cfg}
    h = next(x for x in json.loads(config.data_path("fleet_v2.json").read_text())["homes"] if x["name"] == name)
    rp = Replay(h["profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
    b = h["battery"]
    acfg = {"battery_kwh": b["kwh"], "battery_kw": b["kw"], "reserve_pct": b["reserve_pct"], "soc_max_pct": b["soc_max_pct"], "soc0_pct": b.get("soc0_pct", 55.0),
            "eta": b["eta"], "ev_max_kw": rp.sessions[0]["max_kw"] if rp.sessions else 0.0, "has_ev": h["has_ev"], "export_limit_kw": h["export_limit_kw"],
            "control": "auto", "forecast": c["forecast"], "opt_out_days": [], "name": name, "control_mode": c["control_mode"], "owner_limits": {}}
    sim = SimulatedHome(acfg, rp)
    HomeNodes.owner_setup(HomeNodes(), name, sim)            # the owner's limits, charging power and car energy, as a host sets them
    folder = tmp or config.state_dir()
    key = signing.load_or_create(folder / f"{name}.key")
    sent: list = []
    node = node_class(c)(name, acfg, sim, rp, key, send=lambda to, kind, body, mid: sent.append((to, kind, body, mid)), trusted=lambda: [], log=lambda *a, **k: None)
    node.brain = HomeRule(node, Wishes(folder / f"{name}_wishes.json"), label=name)
    return node, sent


def agent(node: Any, model: Model | None = None) -> Any:
    """The node's agent, with a scripted model."""
    from murmur.node.agent import NodeAgent
    return NodeAgent(node, 1, model or Model(), lambda rec: None)


def building_rule(node: Any, folder: Path) -> BuildingRule:
    return BuildingRule(node, FacilityPolicy(folder / "policy.json"), label=node.name)

"""The building members a host runs: the same protocol code and threads as the homes, a building's own levers and agent."""
from __future__ import annotations

from typing import Any, Callable
from murmur import config
from murmur.protocol import signing
from murmur.node.home import MemberNode
from murmur.node.offer_rule import BuildingRule
from murmur.node.offer_shape import FacilityPolicy
from murmur.replay import Replay
from murmur.agents.host_common import node_class
from murmur.agents.host import NodeHost


class BuildingHost(NodeHost):
    """The building nodes in one process: the same protocol code and threads, a building's own simulator and levers
    (node/simulator_building.py, node/building_levers.py). Their identities come from secrets/host_tokens.json too, so the two daemons are set up the same way."""
    kind = "buildings"
    port_key = "buildings_port"

    def roster(self) -> list[dict[str, Any]]:
        from murmur.node import simulator_building as building
        return building.enabled({"buildings": self.cfg.get("buildings") or "all"})

    def make_node(self, b: dict[str, Any], send: Callable) -> MemberNode:
        from murmur.node import simulator_building as building
        c, name = self.cfg, b["name"]
        rp = Replay(b["profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
        acfg = {"agent_name": name, "name": name, "building": name, "control": "auto", "forecast": c.get("forecast"), "control_mode": "rolling", "opt_out_days": [],
                "owner_limits": c.get("owner_limits") or {}}
        sim = building.SimulatedBuilding(acfg, rp)
        key = signing.load_or_create(self.keydir / f"{name}.key")
        return node_class(c)(name, acfg, sim, rp, key, send=send, trusted=self.trusted, log=self._logger(name))

    def thinking(self) -> list[str]:
        """A building thinks once its agent exists: cfg thinking_buildings, default every building."""
        want = self.cfg.get("thinking_buildings", True)
        return [n for n in self.homes if want is True or (isinstance(want, list) and n in want)] if self.agent_class() else []

    @staticmethod
    def agent_class() -> Any:
        """The building's agent: node/building_agent.py's BuildingAgent(node, brain, record), a NodeAgent subclass. If it can't be
        imported, the buildings run on their code (controller, guard and rule-based offers), and /health says so."""
        try:
            from murmur.node.building_agent import BuildingAgent
        except ImportError:
            return None
        return BuildingAgent

    def make_agent(self, name: str, brain: Any, record_: Callable[[dict[str, Any]], None]) -> Any:
        cls = self.agent_class()
        return cls(self.homes[name], brain, record_, **self.log_arg(cls, name))

    def make_mind(self, name: str) -> Any:
        """Steps 5 and 6, as a home's, under the manager's policy. It can only lower what the planner offered."""
        return BuildingRule(self.homes[name], FacilityPolicy(config.state_dir() / f"{name}_policy.json"), label=name, log=self._logger(name))

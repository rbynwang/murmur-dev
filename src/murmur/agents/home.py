"""The homes a host runs: each home's replay, battery and car from the dataset, its owner's limits, its agent and its rule for offers and commitments."""
from __future__ import annotations

import inspect
import json
from typing import Any, Callable
from murmur import config
from murmur.protocol import signing
from murmur.node.simulator import SimulatedHome
from murmur.node.home import MemberNode
from murmur.node import record
from murmur.node.llm_client import NodeModel
from murmur.node.offer_rule import HomeRule
from murmur.node.offer_shape import Wishes
from murmur.replay import Replay
from murmur.agents.host_common import log, node_class


class HomeNodes:
    """The homes a host runs: each home's replay, battery and car from the dataset, its owner's limits, its agent and its rule for offers and commitments."""

    # ------------------------------------------------------------------ what differs from the buildings
    def roster(self) -> list[dict[str, Any]]:
        """The dataset's homes this host runs: those its configuration names under "homes", or every one."""
        wanted = self.cfg.get("homes") or "all"
        return [x for x in json.loads(config.data_path("fleet_v2.json").read_text())["homes"] if x["kind"] == "replay" and (wanted == "all" or x["name"] in wanted)]

    def make_node(self, h: dict[str, Any], send: Callable) -> MemberNode:
        c, name = self.cfg, h["name"]
        rp = Replay(h["profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
        b = h["battery"]
        acfg = {"battery_kwh": b["kwh"], "battery_kw": b["kw"], "reserve_pct": b["reserve_pct"],
                "soc_max_pct": b["soc_max_pct"], "soc0_pct": b.get("soc0_pct", 55.0), "eta": b["eta"],
                "ev_max_kw": rp.sessions[0]["max_kw"] if rp.sessions else 0.0, "has_ev": h["has_ev"],
                "export_limit_kw": h["export_limit_kw"], "control": "auto", "forecast": c.get("forecast"),
                "opt_out_days": c.get("opt_out_days", {}).get(name, []),
                "name": name, "control_mode": c.get("control_mode", "fixed"),
                "owner_limits": c.get("owner_limits") or {}}
        sim = SimulatedHome(acfg, rp)
        self.owner_setup(name, sim)
        key = signing.load_or_create(self.keydir / f"{name}.key")
        return node_class(c)(name, acfg, sim, rp, key, send=send, trusted=self.trusted, log=self._logger(name))

    def owner_setup(self, name: str, sim: Any) -> None:
        """Each owner's own limits, from the dataset's owners.json. A dataset without the file keeps the defaults."""
        o = self.owners().get(name)
        if o is None or sim.ctl is None:
            return
        lim = sim.ctl.limits
        lim.max_rise_c, lim.max_rise_away_c, lim.precool_c = o["max_rise_c"], o["max_rise_away_c"], o["precool_c"]
        sim.P_ch = float(o["charge_kw"]) if o.get("charge_kw") else sim.P_ch
        if "v2h" in (sim.app or {}):
            sim.app = {**sim.app, "v2h": {**sim.app["v2h"], "event_kwh": float(o["v2h_kwh"])}}

    def owners(self) -> dict[str, Any]:
        if not hasattr(self, "_owners"):
            try:
                self._owners = json.loads(config.data_path("owners.json").read_text())["homes"]
            except (OSError, ValueError, KeyError):
                self._owners = {}
        return self._owners

    def thinking(self) -> list[str]:
        """cfg thinking_homes: a list of names, or how many. A number takes every 10th home first, the benchmark's thinking homes."""
        want = self.cfg.get("thinking_homes") or 0
        if isinstance(want, list):
            return [n for n in want if n in self.homes]
        names = list(self.homes)
        return (names[9::10] + [n for i, n in enumerate(names) if (i + 1) % 10])[:int(want)]

    def log_arg(self, cls: type, name: str) -> dict[str, Any]:
        """An agent that takes a log (node/agent.py's NodeAgent does) writes its device calls to the node's log too."""
        return {"log": self.logs[name]} if "log" in inspect.signature(cls.__init__).parameters else {}

    def make_agent(self, name: str, brain: Any, record_: Callable[[dict[str, Any]], None]) -> Any:
        from murmur.node.agent import NodeAgent
        return NodeAgent(self.homes[name], int(self.entries[name].get("tier") or 1), brain, record_, **self.log_arg(NodeAgent, name))

    def make_mind(self, name: str) -> Any:
        """Steps 5 and 6, the offer and the answer: code's rule under the owner's wishes."""
        return HomeRule(self.homes[name], Wishes(config.state_dir() / f"{name}_wishes.json"), label=name, log=self._logger(name))

    # ------------------------------------------------------------------ thinking nodes
    def attach_agent(self, name: str) -> None:
        """A new run starts each agent afresh: what it planned last time means nothing now. Its log goes on."""
        from murmur.node import tools as T
        lock, log_ = self.locks[name], self.logs[name]
        brain = NodeModel(self.mind, lock, name)
        brain.agent = self.agents[name] = self.make_agent(name, record.RecordingBrain(brain, log_, T.PROMPT_VERSION, self.version, self.mind.client.options), self._recorder(name))
        self.homes[name].brain = self.make_mind(name)

    def _recorder(self, name: str) -> Callable[[dict[str, Any]], None]:
        def f(rec: dict[str, Any]) -> None:
            self.decisions[name].append(rec)
            self.logs[name].decision(rec)
        return f

"""The simulated node behind a context server: writes, releases, reads, limits, keep-outs and holds on the dataset's replay."""
from __future__ import annotations

from typing import Any
from murmur.node import control as rt_control
from murmur.node import policy as P
from murmur.node.calls import HELD_BY_CONTROLLER


class ContextSim:
    """The simulated node behind a context server: writes, releases, reads, limits, keep-outs and holds on the dataset's replay."""

    # ------------------------------------------------------------------ the simulated device
    def _sim_write(self, call: dict[str, Any], ans: dict[str, Any]) -> None:
        self._write(call, ans, self._f)

    def _sim_release(self, target: str | None = None) -> None:
        """One device leaves the sale, or all of them. With levers open again the controller could use every device, so when all are let go it stands
        down too: writes stop, and the node leaves the sale until a person clears it. An agent lets one call go by itself (let_go). A home node that can't has
        that call let go here, and a building node that can't lets go of everything, its levers open again with nothing in them."""
        node = self.node
        if target is not None and hasattr(node, "let_go"):
            return node.let_go(target)            # NodeAgent and BuildingAgent let one call go. What follows is for a node that can't
        if target is None or getattr(node, "zm", None) is not None:
            node.close()
            node.calls = []
            if target is None and getattr(node, "sim", None) is not None:
                node.sim.rt_override("stop", True)
            elif target is not None:
                node.open()                       # with no levers the controller would take back the group the person just asked for: what's left stays shut until the agent opens it
            return
        tools = {c["tool"] for c in node.calls if c["target"] == target}
        node.calls = [c for c in node.calls if c["target"] != target]
        node.guard.writers.pop(target, None)
        if node.sim.levers is not None and tools:
            node.reopen(tools)

    def _sim_read(self, target: str) -> dict[str, Any]:
        d = next((x for x in self.facts()["devices"].values() if x["target"] == target), {})
        keep = {k: v for k, v in d.items() if k not in ("tool", "target") and isinstance(v, (str, int, float, bool))}
        return {"status": "done", "why": "", "reading": keep, "view": f"{target}: " + ", ".join(f"{k} {v}" for k, v in list(keep.items())[:8]) + "."}

    def _sim_limit(self, group: str, name: str, value: float) -> None:
        rt_control.write_limit(self.node.sim, group, name, value)

    def _sim_keep_out(self, group: str, out: bool) -> None:
        """A person's "not this group" reaches the controller too, on a node with no agent call running. It stays through offers until the person takes it back."""
        sim = getattr(self.node, "sim", None)
        if not hasattr(sim, "kept_out"):
            return
        keys = {k for t in self.node.shelf if P.group_of(t) == group for k in HELD_BY_CONTROLLER.get(t, ())}
        sim.kept_out = (sim.kept_out | keys) if out else (sim.kept_out - keys)

    def _sim_hand_back(self, keep: set[str]) -> None:
        node = self.node
        if getattr(node, "zm", None) is not None:
            if node.sim.levers is None:           # with no levers the whole building is the controller's, so a person's word takes it out of the sale
                node.open()
            node.reopen(keep)
            return
        node.all_open(keep)                       # every device open, the device's own rating still limiting each, and these closed again

    def _sim_hold(self, why: str) -> None:
        sim = getattr(self.node, "sim", None)
        if hasattr(sim, "hold_alarm"):
            sim.hold_alarm(why)

    def _sim_clear_stop(self) -> None:
        sim = getattr(self.node, "sim", None)
        if hasattr(sim, "rt_override"):
            sim.overrides.pop("alarm_hold", None)
            sim.rt_override("stop", False)

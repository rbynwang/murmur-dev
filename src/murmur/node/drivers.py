"""The only road to a device: one interface, with a simulated driver and real drivers that refuse until they are built.

  Gate     the seal: a call the guard passed becomes a Ticket, and only a ticket's Command reaches a driver
  Router   the driver per device group
  Driver   read, write, release, set_limit; SimulatedDriver acts on the dataset's replay

A real driver (Home Assistant, Matter, BACnet, OCPP, Modbus) refuses every write: no real device is driven by this code.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import linecache
import secrets
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable

from murmur.node.guard import blocked

KINDS = ("setpoint", "schedule", "cap_power", "dim_switch", "charge_discharge")
GUARD_FILES = ("node/guard.py", "node/guard_building.py", "node/guard_building_tools.py", "node/guard_building_rules.py")   # the lines a record keeps
KIND = {"set_battery": "charge_discharge", "discharge_car": "charge_discharge",
        "limit_ev_charging": "cap_power", "set_pool_pump": "cap_power", "limit_air_handler": "cap_power", "set_plant_demand_limit": "cap_power",
        "set_thermostat": "setpoint", "set_room_ac": "setpoint", "set_zone_cooling": "setpoint",
        "set_water_heater": "schedule", "delay_appliance": "schedule", "stop_plant_early": "schedule",
        "dim_lights": "dim_switch", "switch_plugs": "dim_switch", "set_zone_standby": "dim_switch"}


@dataclass(frozen=True)
class Command:
    node: str
    tool: str
    kind: str
    target: str
    values: dict[str, Any]
    start: str
    end: str


@dataclass(frozen=True)
class Ticket:
    command: Command
    call: dict[str, Any]
    answer: dict[str, Any]
    nonce: str
    seal: str


def _bytes(x: Any) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()


def refuse(why: str) -> dict[str, Any]:
    return {"status": "blocked", "why": why}


class Driver:
    """The one interface. A driver answers done, blocked (nothing was sent) or failed (sent, and the device didn't respond)."""
    name = "driver"

    def __init__(self) -> None:
        self._honest: Callable[[Ticket], bool] | None = None

    def attach(self, honest: Callable[[Ticket], bool]) -> None:
        """A driver trusts one gate, for good. A second can't take over."""
        if self._honest is not None:
            raise RuntimeError("this driver already has a gate")
        self._honest = honest

    def send(self, ticket: Any) -> dict[str, Any]:
        if self._honest is None or not isinstance(ticket, Ticket) or not self._honest(ticket):
            return refuse("Nothing was sent: this command has no guard's seal.")
        return self._write(ticket)

    def _write(self, ticket: Ticket) -> dict[str, Any]:
        raise NotImplementedError

    def read(self, target: str) -> dict[str, Any]:
        raise NotImplementedError

    def release(self, target: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def set_limit(self, group: str, name: str, value: float) -> dict[str, Any]:
        raise NotImplementedError


class SimulatedDriver(Driver):
    """The simulated node. Each node hands over its own functions, so homes and buildings use the same class:
    write(call, answer), release(target or None), read(target), limit(group, name, value)."""
    name = "simulated"

    def __init__(self, write: Callable[[dict[str, Any], dict[str, Any]], Any], release: Callable[[str | None], Any] | None = None,
                 read: Callable[[str], dict[str, Any]] | None = None, limit: Callable[[str, str, float], Any] | None = None):
        super().__init__()
        self._apply, self._release, self._read, self._limit = write, release, read, limit
        self.sent: list[Command] = []

    def _write(self, ticket: Ticket) -> dict[str, Any]:
        try:
            self._apply(ticket.call, ticket.answer)
        except Exception as exc:                       # the device's side broke: say so, and let the guard give the point back
            return {"status": "failed", "why": f"The device didn't take it: {type(exc).__name__}."}
        self.sent.append(ticket.command)
        return {"status": "done", "why": ""}

    def read(self, target: str) -> dict[str, Any]:
        return self._read(target) if self._read else {"status": "blocked", "why": "No reading is wired for this device."}

    def release(self, target: str | None = None) -> dict[str, Any]:
        if self._release:
            self._release(target)
        return {"status": "done", "why": ""}

    def set_limit(self, group: str, name: str, value: float) -> dict[str, Any]:
        if self._limit is None:
            return refuse("This node has no such limit.")
        self._limit(group, name, value)
        return {"status": "done", "why": ""}


class RealDriver(Driver):
    """A real path to a device, not connected yet. It refuses every write, and imports no network code, so it can't reach one."""
    protocol = "real"

    def __init__(self) -> None:
        super().__init__()
        self.name = self.protocol

    def _no(self, what: str) -> dict[str, Any]:
        return refuse(f"{self.protocol} driver isn't connected, so nothing was sent to {what}.")

    def _write(self, ticket: Ticket) -> dict[str, Any]:
        return self._no(ticket.command.target)

    def read(self, target: str) -> dict[str, Any]:
        return self._no(target)

    def release(self, target: str | None = None) -> dict[str, Any]:
        return {"status": "done", "why": f"{self.protocol} sent nothing, so there is nothing to release."}

    def set_limit(self, group: str, name: str, value: float) -> dict[str, Any]:
        return self._no(group)


class HomeAssistantDriver(RealDriver):
    """Makers' clouds and CTA-2045 modules, through Home Assistant on the site's edge node."""
    protocol = "Home Assistant"


class MatterDriver(RealDriver):
    """Local thermostats. Most homes' cards assume this path."""
    protocol = "Matter"


class BacnetDriver(RealDriver):
    """Buildings, through the BMS or JACE. Writes must use priority 9 to 14, and an edge node stays off smoke-control segments."""
    protocol = "BACnet"


class OcppDriver(RealDriver):
    """Chargers: a charging profile with a limit in amps."""
    protocol = "OCPP"


class ModbusDriver(RealDriver):
    """Site batteries, through the site controller."""
    protocol = "Modbus"


REAL = {"home_assistant": HomeAssistantDriver, "matter": MatterDriver, "bacnet": BacnetDriver, "ocpp": OcppDriver, "modbus": ModbusDriver}
ROUTES = {"home": {"energy_storage": "home_assistant", "ev_charging": "ocpp", "hvac_zones": "matter", "water_heating": "home_assistant",
                   "appliances": "home_assistant", "pools_and_water_features": "home_assistant"},
          "building": {"energy_storage": "modbus", "ev_charging": "ocpp", "central_plant": "bacnet", "hvac_zones": "bacnet",
                       "lighting_and_shading": "bacnet", "plug_loads": "bacnet"}}


class Router(Driver):
    """A node's devices sit on different paths: one driver per device group. Group names come from each tool's card."""
    name = "router"

    def __init__(self, side: str, group_of: Callable[[str], str]):
        super().__init__()
        self.group_of = group_of
        self.routes = {g: REAL[p]() for g, p in ROUTES[side].items()}

    def _write(self, ticket: Ticket) -> dict[str, Any]:
        d = self.routes.get(self.group_of(ticket.command.tool))
        return d._write(ticket) if d else refuse(f"No driver is set up for {ticket.command.target}.")

    def read(self, target: str) -> dict[str, Any]:
        return refuse(f"No real driver is connected, so {target} can't be read.")

    def release(self, target: str | None = None) -> dict[str, Any]:
        for d in self.routes.values():
            d.release(target)
        return {"status": "done", "why": ""}

    def set_limit(self, group: str, name: str, value: float) -> dict[str, Any]:
        d = self.routes.get(group)
        return d.set_limit(group, name, value) if d else refuse(f"No driver is set up for {group}.")


class Gate:
    """Guard, then seal, then driver. run() is the only way to get a seal: there is no other public way to make a ticket."""

    def __init__(self, node: str, guard: Any, driver: Driver):
        self.node, self.guard, self.driver = node, guard, driver
        self.__key = secrets.token_bytes(32)
        self.__used: set[str] = set()
        self.last: dict[str, Any] = {}                 # the last run's command and the driver's reply, for the record
        driver.attach(self.__honest)

    def run(self, call: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
        """The guard's answer. If the driver then can't deliver, the answer says so and the guard forgets the call: the point is free."""
        memory = {k: copy.deepcopy(v) for k, v in vars(self.guard).items()
                  if k != "setup" and (v is None or isinstance(v, (dict, list, set, tuple, str, int, float)))}     # every piece of its state: a day's name too
        self.last = {}
        try:
            ans = self.__traced_check(call, facts)
        except Exception as exc:                       # a guard that breaks has said no
            self.__forget(memory)
            return blocked(str((call.get("args") or {}).get("target", "")), f"The guard couldn't check this ({type(exc).__name__}), so nothing was sent.")
        if ans["status"] not in ("done", "adjusted"):
            return ans
        kind = KIND.get(call["tool"])
        t = self.__ticket(kind, call, ans) if kind else None
        try:
            out = self.driver.send(t) if t else refuse(f"{call['tool']} has no command kind.")
        except Exception as exc:                       # a driver that breaks hasn't delivered: the point goes back, as for any failure
            out = {"status": "failed", "why": f"The device didn't take it: {type(exc).__name__}."}
        self.last = {**self.last, "command": asdict(t.command) if t else None, "driver": out, "seal": {"nonce": t.nonce, "seal": t.seal[:16]} if t else None}     # the seal, cut to 16 characters as every signature on the page is: recording only
        if out["status"] == "done":
            return ans
        self.__forget(memory)
        return {**ans, "status": "failed" if out["status"] == "failed" else "blocked", "applied": {}, "expected_kw": 0.0, "confirm_by": "",
                "why": out["why"], "try_instead": {}}

    def __traced_check(self, call: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
        """Recording only: the guard's own answer, and the lines of the guard's files (GUARD_FILES) it ran, kept in self.last for the node's record. Tracing watches and changes
        nothing, and a fault in it never reaches the guard's answer."""
        seen: list[tuple[str, int, str]] = []

        def local(frame: Any, event: str, arg: Any) -> Any:
            if event == "line":
                seen.append((frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name))
            return local

        def top(frame: Any, event: str, arg: Any) -> Any:
            return local if frame.f_code.co_filename.endswith(GUARD_FILES) else None
        before = sys.gettrace()
        sys.settrace(top)
        try:
            return self.guard.check(call, facts)
        finally:
            sys.settrace(before)
            try:
                lines, last = [], None
                for name, no, fn in seen:
                    if (name, no) != last:
                        src = linecache.getline(name, no)
                        lines.append({"file": name.rsplit("/", 1)[-1], "line": no, "fn": fn, "text": src.strip()[:200], "indent": len(src) - len(src.lstrip())})
                        last = (name, no)
                self.last["guard_lines"] = lines
            except Exception:                          # the record loses its lines, and the guard's answer stands
                pass

    def __forget(self, memory: dict[str, Any]) -> None:
        for k, v in memory.items():
            setattr(self.guard, k, v)

    def release_all(self) -> dict[str, Any]:
        """Every agent limit ends now, and the devices go back to their own day. A driver that breaks doesn't stop the rest of this."""
        try:
            out = self.driver.release()
        except Exception as exc:
            out = {"status": "failed", "why": f"The release didn't go through: {type(exc).__name__}."}
        if hasattr(self.guard, "clear"):
            self.guard.clear()
        return out

    def __seal(self, nonce: str, command: Command, call: dict[str, Any], answer: dict[str, Any]) -> str:
        return hmac.new(self.__key, nonce.encode() + _bytes([asdict(command), call, answer]), hashlib.sha256).hexdigest()

    def __ticket(self, kind: str, call: dict[str, Any], ans: dict[str, Any]) -> Ticket:
        c = Command(self.node, call["tool"], kind, ans["target"], dict(ans["applied"]), call["start"], call["end"])
        nonce = secrets.token_hex(8)
        return Ticket(c, call, ans, nonce, self.__seal(nonce, c, call, ans))

    def __honest(self, t: Ticket) -> bool:
        try:
            good = hmac.compare_digest(t.seal, self.__seal(t.nonce, t.command, t.call, t.answer))
        except (TypeError, AttributeError, ValueError):     # a ticket with no real seal is no ticket
            return False
        if not good or t.nonce in self.__used:
            return False
        self.__used.add(t.nonce)
        return True


def make(side: str, mode: str, group_of: Callable[[str], str], **sim: Any) -> Driver:
    """simulated, or real: the real ones refuse every write, so running a node on them changes nothing outside it."""
    if mode == "real":
        return Router(side, group_of)
    if mode == "simulated":
        return SimulatedDriver(**sim)
    raise ValueError(f"no driver mode {mode!r}")

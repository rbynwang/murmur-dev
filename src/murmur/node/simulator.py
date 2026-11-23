"""A home driven by the dataset's replay: simulated load, solar, battery and car, on the dataset's weather. No real home or meter is
behind it. Sign convention: battery kW > 0 discharging; grid kW > 0 exporting.
"""
from __future__ import annotations

from typing import Any

import os
from murmur.node import devices
from murmur.node import hvac
from murmur.node import control
from murmur.node import rolling
from murmur.node.simulator_rules import BACKUP, SUB
from murmur.node.simulator_rolling import SimulatedRolling

CATCH_UP = 96 * 2              # quarter hours a home steps one by one when its clock has moved on (advance); a host gives back as many meter rows (agents/host_doors.py)


class SimulatedHome(SimulatedRolling):
    name = "simulated"

    def __init__(self, cfg: dict[str, Any], replay):
        self.cfg, self.replay = cfg, replay
        self.E = float(cfg["battery_kwh"]); self.P = float(cfg["battery_kw"])
        self.R = float(cfg["reserve_pct"]) / 100; self.SM = float(cfg["soc_max_pct"]) / 100
        self.eta = float(cfg.get("eta", 0.95)); self.ev_max = float(cfg["ev_max_kw"])
        self.P_ch = float(os.environ.get("MURMUR_CHARGE_KW") or 1e9)      # benchmark: Powerwall 3 charges at 5 kW
        self.has_ev = bool(cfg.get("has_ev", True))
        self.export_limit = float(cfg["export_limit_kw"])
        self.soc0 = float(cfg["soc0_pct"]) / 100
        self.soc = self.soc0
        self.ev_left = 0.0; self.ev_deadline = None; self.ev_session = None
        self.cf = {"soc": self.soc, "ev_left": 0.0, "ev_deadline": None}      # the no-event twin
        self.plan: dict[str, dict[str, Any]] = {}                               # ts -> action (v2 contract)
        self.ev_holds: list[tuple[str, str]] = []                              # [(from_ts, until_ts)], one per contract
        self.idx: int | None = None
        self.tel: dict[str, Any] = {}
        self.recent: dict[int, dict[str, Any]] = {}                            # idx -> telemetry, last ~4 days
        # the real-time design (control_mode "rolling")
        self.mode = cfg.get("control_mode", "fixed")
        self.x = 0.0                                                            # indoor C minus the house's own day
        self.rt_extra: dict[str, float] = {}                                    # ts -> kW dispatched on top (calls)
        self.overrides: dict[str, Any] = {}                                     # the owner: ev_now, comfort, stop
        self.house = hvac.House.of(cfg.get("name") or cfg.get("agent_name"), getattr(replay, "profile", "")) \
            if self.mode == "rolling" else None
        self.ctl = rolling.RollingController(self, self.house, control.Limits(**(cfg.get("owner_limits") or {}))) \
            if self.mode == "rolling" else None
        # benchmark: the node's other smart systems (node/devices.py)
        node = "building" if getattr(self, "name", "") == "building" else "home"
        self.app, self.dev_arr, self.dev_row = devices.for_node(node, cfg.get("name") or cfg.get("agent_name") or "")
        self.dev_off: set[str] = set()                         # what the offer left out: replaced at each offer
        self.kept_out: set[str] = set()                        # a person's word: it stays through offers until the person takes it back
        self.app_q: dict[str, float] = {}                      # kWh waiting, by device
        self.app_hold_end: str | None = None
        self.v2h_day, self.v2h_used = None, 0.0
        self.ev_wait: dict[str, Any] | None = None       # a car plugged in and waiting for its timer: the session to come
        self.ev_skip: dict[str, Any] | None = None       # a session already dealt with: the owner started it early, or its car left first
        self.v2h_owed = 0.0                              # kWh a two-way car gave and must get back before it leaves
        self.e_part = self.meter_room = 0.0              # in this 5-minute part: what the car draws, and what the meter can still send out
        # data with plug-in times holds a two-way car to its card: the home's car circuit, the owner's kWh counted leaving the car, no
        # giving while it draws. Data without plug-in times runs without these rules.
        self.car_rules = bool(getattr(replay, "plugins", None))
        self.v2h_kw = 0.0                     # what a two-way car gave this step: it earns the battery rate
        # the node agent's device tools (murmur/node): None = the controller may use every device. A dict = only what
        # the agent's calls opened, until they end: battery_kw, ev (the plan may pause the car), ev_kw (its floor), v2h_kw
        self.levers: dict[str, Any] | None = None
        self.held_out: set[str] = set()      # with no levers, what a wish keeps out: a building's levers can't stand open all but a few (BuildingAgent.hold_out)
        # the controller's writes don't go through the guard, so _clip holds them to the limit where they're written. The node's log takes these rows
        self.clips: list[dict[str, Any]] = []
        self.clip_at: dict[str, str] = {}                # the last step each limit stopped a write
        self.reset_on: Any = None                        # the clock a reset found, until the new run's clock comes (rt_reset)
        self.car_first = False                           # an owner's wish turned ev_now on, not a person: the wish's end turns it off. A person's own word takes it over
        self.note_seen: str | None = None                # the door's note the node's agent has read, by note_reader.note_key: a newer one doesn't push it aside

    # --- physics -------------------------------------------------------------------
    def _caps(self, soc: float, dt: float = 0.25) -> tuple[float, float]:
        P = (0.0 if "battery" in self.held_out else self.P) if self.levers is None else min(self.P, float(self.levers.get("battery_kw", 0.0)))
        can_dis = max(0.0, min(P, (soc - self.R) * self.E * self.eta / dt))
        can_ch = max(0.0, min(self.P, self.P_ch, (self.SM - soc) * self.E / self.eta / dt))
        return can_dis, can_ch

    def _soc_after(self, soc: float, b: float, dt: float = 0.25) -> float:
        if self.E <= 0:                                            # a home without a battery (b is always 0)
            return soc
        soc += (-b) * dt * self.eta / self.E if b < 0 else -b * dt / self.eta / self.E
        return min(self.SM, max(self.R * 0.999, soc))

    def _ev_demand(self, ev_left: float, ev_deadline: str | None) -> float:
        return min(self.ev_max, ev_left / 0.25) if (self.has_ev and ev_left > 0.01 and ev_deadline) else 0.0

    def _backup_refill(self, ts, soc: float, can_ch: float) -> float:
        """Benchmark's held-for-the-grid mode: no discharge for the house; surplus solar charges it, and overnight it
        refills from the grid at a gentle 2 kW (backup batteries keep themselves full)."""
        if ts and (ts[11:13] >= "22" or ts[11:13] < "06") and soc < self.SM - 1e-3:
            return -min(can_ch, 2.0)
        return 0.0

    def _default(self, pv: float, base: float, ev: float, soc: float, ts=None) -> float:
        can_dis, can_ch = self._caps(soc)
        net = base + ev - pv                                       # >0 deficit
        if BACKUP and net > 0:
            return self._backup_refill(ts, soc, can_ch)
        return min(net, can_dis) if net > 0 else -min(-net, can_ch)

    def _clip_export(self, grid: float) -> tuple[float, float]:
        return (self.export_limit, grid - self.export_limit) if grid > self.export_limit else (grid, 0.0)

    def _step(self, i: int) -> None:
        row = self.replay.row(i)
        ts = row["ts_local"]
        self._plug_in(i, ts)
        sess = self.replay.session_starting(i)
        if sess:
            if self.ev_skip and self.ev_skip["arrival"] == sess["arrival"]:
                self.ev_skip = None                                        # it already started, or its car has gone
            else:
                carry = self._owed_now() if sess.get("plug_in") else 0.0   # a new session must not wipe what the car gave
                leaves = min(self.ev_deadline, sess["deadline"]) if self.ev_wait and self.ev_deadline else sess["deadline"]   # the owner may have moved it up
                self.ev_wait, self.v2h_owed = None, carry
                self.ev_left, self.ev_deadline, self.ev_session = sess["kwh"] + carry, leaves, sess["arrival"]
            self.cf["ev_left"], self.cf["ev_deadline"] = sess["kwh"], sess["deadline"]
        if self.ev_deadline and ts >= self.ev_deadline:
            self._car_left(ts)
        if self.cf["ev_deadline"] and ts >= self.cf["ev_deadline"]:
            self.cf["ev_left"], self.cf["ev_deadline"] = 0.0, None
        self._simulate(i, row)

    def _plug_in(self, i: int, ts: str) -> None:
        """A car on a timer is plugged in hours before its session starts: from here it can give, and it draws nothing yet.
        It reads as plugged in (ev_deadline) with nothing to charge (ev_left 0) until the session starts."""
        plug = self.replay.session_plugging(i)
        if not plug or not self.has_ev:
            return
        if self.ev_deadline and ts >= self.ev_deadline:
            self._car_left(ts)                                      # it left and came back in the same step
        self.ev_deadline = max(self.ev_deadline or "", plug["deadline"])
        if plug["arrival"] > ts:
            self.ev_wait = plug

    def _car_left(self, ts: str) -> None:
        w = self.ev_wait
        if w and w["arrival"] > ts:
            self.ev_skip = w                                        # gone before its timer: that session never runs
        self.ev_left, self.ev_deadline, self.ev_wait, self.v2h_owed = 0.0, None, None, 0.0

    def _car_now(self) -> None:
        """The owner's "now" beats the timer: the session waiting for it starts here, with what the car gave."""
        w = self.ev_wait
        if w and self.overrides.get("ev_now"):
            self.ev_left += w["kwh"] + self.v2h_owed
            self.ev_session, self.ev_wait, self.ev_skip = w["arrival"], None, w


    def _owed_now(self) -> float:
        """What the car still has to get back. A session already drawing carries it in ev_left, and owed energy goes in last."""
        return self.v2h_owed if self.ev_wait else min(self.v2h_owed, self.ev_left)

    def _twin(self, row: dict[str, Any]) -> float:
        pv, base = row["pv_kw"], row["base_kw"]
        ev = self._ev_demand(self.cf["ev_left"], self.cf["ev_deadline"])
        b = self._default(pv, base, ev, self.cf["soc"], row["ts_local"])
        self.cf["soc"] = self._soc_after(self.cf["soc"], b)
        self.cf["ev_left"] = max(0.0, self.cf["ev_left"] - ev * 0.25)
        return self._clip_export(pv + b - base - ev)[0]

    def _simulate(self, i: int, row: dict[str, Any]) -> None:
        self._car_now()
        if self.mode == "rolling":
            return self._simulate_rolling(i, row)
        pv, base, ts = row["pv_kw"], row["base_kw"], row["ts_local"]
        grid_cf = self._twin(row)
        act = self.plan.get(ts)
        ev = self._ev_demand(self.ev_left, self.ev_deadline)
        held = ev > 0 and any(a <= ts < b for a, b in self.ev_holds)
        if held and self.ev_deadline:                               # never hold an EV past the point where it
            need_min = self.ev_left / max(0.1, self.ev_max) * 60    # could no longer finish by its departure
            held = self.replay.minutes_between(ts, self.ev_deadline) - 15 > need_min
        ev_now, stop = bool(self.overrides.get("ev_now")), bool(self.overrides.get("stop"))
        if held and not ev_now:
            ev = 0.0                                                # staggered restart after an event
        held = held and not ev_now
        can_dis, can_ch = self._caps(self.soc)
        # a managed restart after an event charges the EV from the grid in its assigned slot; the battery keeps its
        # energy for the house's evening load (that is what the community agent's evening forecast assumes)
        managed = bool(self.ev_session and any(self.ev_session[:10] == a[:10] for a, _ in self.ev_holds))
        b = self._default(pv, base, 0.0 if managed else ev, self.soc, ts)
        mode, ev_cut = "self_consumption", 0.0
        if act and "deliver_kw" in act and not stop:                # v2: X kW less import than the twin
            extra = (grid_cf + act["deliver_kw"]) - (pv + b - base - ev)
            if extra > 0 and ev > 0 and not ev_now:                 # EV first: the energy is only deferred
                ev_cut = min(ev, extra)
                ev -= ev_cut
                extra -= ev_cut
            if extra > 0:
                nb = min(can_dis, b + extra)
                extra -= nb - b
                b = nb
            mode = "deliver"
        elif act and "precharge_to" in act:                         # v2: be full when the event starts
            steps_left = max(1, act["by_idx"] - i)
            need_kwh = (act["precharge_to"] - self.soc) * self.E
            if need_kwh > 1e-3:
                req = need_kwh / (steps_left * 0.25) / self.eta
                if req > max(0.0, -b):
                    b = -min(can_ch, req)
                mode = "precharge"
        self.soc = self._soc_after(self.soc, b)
        self.ev_left = max(0.0, self.ev_left - ev * 0.25)
        grid, curtailed = self._clip_export(pv + b - base - ev)
        self.idx = i
        self.tel = {
            "ts": ts, "idx": i, "pv_kw": round(pv, 3), "load_kw": round(base, 3),
            "ev_kw": round(ev, 3), "batt_kw": round(b, 3), "soc_pct": round(self.soc * 100, 2),
            "grid_kw": round(grid, 3), "curtailed_kw": round(curtailed, 3), "mode": mode,
            "ev_plugged": bool(self.ev_deadline), "ev_need_kwh": round(self.ev_left, 2),
            "ev_deadline": self.ev_deadline, "ev_held": held or ev_cut > 0,
            "price_usd_mwh": row["price_usd_mwh"], "override": None,
            "plan": dict(act) if act else None, "grid_cf_kw": round(grid_cf, 3), "soc_cf_pct": round(self.cf["soc"] * 100, 2),
            "source": "replay",
        }
        self.recent[i] = self.tel
        if len(self.recent) > 400:                                  # by distance from this step: rows left ahead of a replay must go, not this run's own
            for k in [k for k in self.recent if not i - 384 < k <= i]:
                self.recent.pop(k, None)

    # --- the real-time design (control_mode "rolling") -------------------------------------------
    def _clip(self, limit: str, ts: str, wanted: float, held_at: float) -> None:
        """A write the limit stopped, for the record: one row when a limit starts to bite, not one every 5 minutes."""
        if wanted <= held_at + 0.01:
            return
        last = self.clip_at.get(limit)
        self.clip_at[limit] = ts
        if last is None or self.replay.minutes_between(last, ts) > 15:
            self.clips = (self.clips + [{"limit": limit, "at": ts, "wanted": round(wanted, 2), "held_at": round(held_at, 2)}])[-50:]

    def _sub_ts(self, ts: str, j: int) -> str:
        return rolling.add_minutes(ts, j * 15 // SUB)


    def advance(self) -> dict[str, Any]:
        cur = self.replay.current()
        if self.idx is None or cur < self.idx or cur - self.idx > CATCH_UP:
            if self.reset_on is not None and self.reset_on != self.replay._line:     # the new run's clock is in: a step played since the reset was on the old one, and isn't this run's
                self.reset_on = None
                self.afresh()
            self.idx = cur - 1                                    # (re)start: no catch-up across days
            self.cf = {"soc": self.soc, "ev_left": self.ev_left, "ev_deadline": self.ev_deadline}
        while self.idx < cur:
            self._step(self.idx + 1)
        return self.tel

    def run_default(self, i_from: int, i_to: int, soc0: float | None = None) -> list[tuple[str, float]]:
        """Meter readings (ts, grid_kw) of this home in default mode over [i_from, i_to): what the utility's
        meter history would hold. Used for baselines; does not touch the live state."""
        soc = self.soc0 if soc0 is None else soc0
        ev_left, ev_deadline, out = 0.0, None, []
        for i in range(i_from, i_to):
            row = self.replay.row(i)
            ts = row["ts_local"]
            sess = self.replay.session_starting(i)
            if sess:
                ev_left, ev_deadline = sess["kwh"], sess["deadline"]
            if ev_deadline and ts >= ev_deadline:
                ev_left, ev_deadline = 0.0, None
            ev = self._ev_demand(ev_left, ev_deadline)
            b = self._default(row["pv_kw"], row["base_kw"], ev, soc, row["ts_local"])
            soc = self._soc_after(soc, b)
            ev_left = max(0.0, ev_left - ev * 0.25)
            out.append((ts, self._clip_export(row["pv_kw"] + b - row["base_kw"] - ev)[0]))
        return out

    # --- v2 contract plan -------------------------------------------------------------
    def set_battery_fault(self, on: bool) -> dict[str, Any]:
        """What-if accident: the battery's inverter trips (0 kW either way) until it is cleared. The home's offers and
        delivery follow from its limits, as they would with a real fault."""
        if on and self.P > 0:
            self._P0, self.P = self.P, 0.0
        elif not on and getattr(self, "_P0", None):
            self.P, self._P0 = self._P0, None
        return {"battery_fault": self.P == 0 and self.E > 0, "battery_kw": self.P}

    def set_soc(self, pct: float) -> dict[str, float]:
        """What-if: the battery holds this much from now on, held inside its own band (reserve to top): below its reserve the next step would put it
        back there with no energy flowing. The no-event twin holds the same. It is this home without the sale: a charge that changed for another
        reason changed there too, so nothing of the change reads as the sale's doing (grid_kw - grid_cf_kw, which the meter and the plan rest on)."""
        was = self.soc
        self.soc = self.cf["soc"] = min(self.SM, max(self.R, float(pct) / 100))
        return {"soc_pct": round(self.soc * 100, 2), "was_pct": round(was * 100, 2)}

    def set_plan(self, actions: dict[str, dict[str, Any]], ev_hold: tuple[str, str] | None = None) -> None:
        self.plan.update(actions)
        if ev_hold:
            self.ev_holds = (self.ev_holds + [tuple(ev_hold)])[-6:]

    def clear_plan(self, contract_id: str) -> None:
        self.plan = {ts: a for ts, a in self.plan.items() if a.get("contract_id") != contract_id}

    # --- adapter interface ------------------------------------------------------------
    def telemetry(self) -> dict[str, Any]:
        return dict(self.advance())

    def limits(self) -> dict[str, Any]:
        return {"battery_kwh": self.E, "battery_kw": self.P, "reserve_pct": self.R * 100,
                "soc_max_pct": self.SM * 100, "ev_max_kw": self.ev_max if self.has_ev else 0.0,
                "export_limit_kw": self.export_limit, "eta": self.eta, "control": self.cfg.get("control", "auto")}

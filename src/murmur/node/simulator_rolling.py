"""The simulated home on the rolling 5-minute plan: its devices, the car's two-way charger, the lights, and what a person or the desk changes while a sale runs."""
from __future__ import annotations

from typing import Any
from murmur.node import control
from murmur.node.simulator_rules import BACKUP, DONE_BY, NOTES_WAITING, SUB


class SimulatedRolling:
    """The simulated home on the rolling 5-minute plan: its devices, the car's two-way charger, the lights, and what a person or the desk changes while a sale runs."""

    def _simulate_rolling(self, i: int, row: dict[str, Any]) -> None:
        pv, base, ts = row["pv_kw"], row["base_kw"], row["ts_local"]
        grid_cf = self._twin(row)
        h, lim = self.house, self.ctl.limits
        if self.overrides.get("comfort"):
            lim = control.Limits(**{**lim.as_dict(), **self.overrides["comfort"]})
        cool0, cop0, tin0, occ0 = h.at(ts) if h else (0.0, 3.0, None, 1)
        dt = 0.25 / SUB
        acc = {"b": 0.0, "e": 0.0, "du": 0.0, "grid": 0.0, "cur": 0.0, "dim": 0.0, "v2h": 0.0}
        decided, held_any, mode = None, False, "self_consumption"
        stop = bool(self.overrides.get("stop"))
        for j in range(SUB):
            self._car_now()
            active = (not stop) and self.ctl.active(i)
            if active and decided is None:
                decided = self.ctl.decide(i, first_dt=(SUB - j) * dt)
                if not decided.get("ok"):
                    decided = None
            ev_dem = min(self.ev_max, self.ev_left / dt) if (self.has_ev and self.ev_left > 0.01 and self.ev_deadline) else 0.0
            # what the plan says for this part (or the home's default job when it owes nothing)
            if active and decided:
                b, u = decided["b"], decided["u"]
                e = min(decided["e"], ev_dem) if self.ctl.ev_controlled(ts) else ev_dem
                mode = "rolling"
            else:
                e = ev_dem
                b = self._default(pv, base, e, self.soc, ts) if dt == 0.25 else None
                if b is None:
                    can_dis, can_ch = self._caps(self.soc, dt)
                    net = base + e - pv
                    if BACKUP and net > 0:
                        b = self._backup_refill(ts, self.soc, can_ch)
                    else:
                        b = min(net, can_dis) if net > 0 else -min(-net, can_ch)
                u = h.thermostat(self.x, ts, dt) if h else 0.0
            # the guard, every 5 minutes
            if ev_dem > 0:
                mins = self.replay.minutes_between(self._sub_ts(ts, j), self.ev_deadline)
                need_min = self.ev_left / max(0.1, self.ev_max) * 60
                if self.overrides.get("ev_now") or mins - lim.ev_keep_h * 60 <= need_min + 5:
                    e = ev_dem                                       # the owner's car first; never late
            if self.levers is not None and self.levers.get("ev_kw") is not None:
                e = max(e, min(ev_dem, float(self.levers["ev_kw"])))     # a limit, not a pause: the agent's amps
            held_any = held_any or (ev_dem > 0 and e < ev_dem - 0.01)
            can_dis, can_ch = self._caps(self.soc, dt)
            self._clip("battery_kw", ts, b, can_dis)
            b = max(-can_ch, min(can_dis, b))
            if h:
                lo, hi = h.dq_bounds(ts)
                u = max(lo, min(hi, u))
                a = h.a(dt)
                x_hi = lim.max_rise_c if occ0 else lim.max_rise_away_c
                x_hi = min(x_hi, float((self.overrides.get("comfort_limit") or {}).get("max_rise_c" if occ0 else "max_rise_away_c", x_hi)))      # a person's word, whatever the slot holds
                if h.step(self.x, u, dt) > x_hi + 1e-6:              # too warm: cool at least enough
                    self._clip("rise_c", ts, h.step(self.x, u, dt), x_hi)
                    u = min(hi, max(u, (a * self.x - x_hi) * h.ua / (1.0 - a)))
                if h.step(self.x, u, dt) < -lim.precool_c - 1e-6:    # too cold: cool less
                    u = max(lo, min(u, (a * self.x + lim.precool_c) * h.ua / (1.0 - a)))
                self.x = h.step(self.x, u, dt)
                du = u / max(1.0, cop0)
            else:
                du = 0.0
            self.e_part, self.meter_room = e, self.export_limit - (pv + b - base - du - e)
            dim = self._light_dim(ts, decided if (active and decided) else None)   # a building's lighting; 0 at home
            grid, cur = self._clip_export(pv + b - base - du - e + dim)
            self.soc = self._soc_after(self.soc, b, dt)
            self.ev_left = max(0.0, self.ev_left - e * dt)
            for k, v in (("b", b), ("e", e), ("du", du), ("grid", grid), ("cur", cur), ("dim", dim), ("v2h", self.v2h_kw)):
                acc[k] += v / SUB
        act = self.plan.get(ts)
        self.idx = i
        last = (self.ctl.last or {}) if mode == "rolling" else {}
        self.tel = {
            "ts": ts, "idx": i, "pv_kw": round(pv, 3), "load_kw": round(base + acc["du"] - acc["dim"], 3),
            "ev_kw": round(acc["e"], 3), "batt_kw": round(acc["b"], 3), "v2h_kw": round(acc["v2h"], 3), "soc_pct": round(self.soc * 100, 2),
            "grid_kw": round(acc["grid"], 3), "curtailed_kw": round(acc["cur"], 3), "mode": mode,
            "ev_plugged": bool(self.ev_deadline), "ev_need_kwh": round(self.ev_left, 2),
            "ev_deadline": self.ev_deadline, "ev_held": held_any,
            "price_usd_mwh": row["price_usd_mwh"], "override": dict(self.overrides) if self.overrides else None,
            "plan": dict(act) if act else None, "grid_cf_kw": round(grid_cf, 3), "soc_cf_pct": round(self.cf["soc"] * 100, 2),
            "source": "replay", "control": "rolling",
            "owed_kw": round(self.ctl.target_at(ts), 3), "rt_extra_kw": round(self.rt_extra.get(ts, 0.0), 3),
            "cool_kw": round(cool0 + acc["du"], 3), "cool_own_day_kw": round(cool0, 3),
            "t_in_c": round(tin0 + self.x * (h.sign(ts) if h else 1), 2) if tin0 is not None else None, "t_dev_c": round(self.x, 2),
            "occupied": bool(occ0), "short_kwh_plan": round(last.get("short_kwh", 0.0), 3) if last else 0.0,
            "replans": self.ctl.replans,
        }
        self.tel.update(self._extra_tel(ts, acc))
        self.recent[i] = self.tel
        if len(self.recent) > 400:                                  # by distance from this step: rows left ahead of a replay must go, not this run's own
            for k in [k for k in self.recent if not i - 384 < k <= i]:
                self.recent.pop(k, None)

    def dev_now(self, ts: str) -> dict[str, float]:
        """kW each device can give at this step on the node's own day: its share of what it draws."""
        j = self.replay.idx_of(ts) if self.app else None
        if j is None:
            return {}
        out = {}
        held = None if self.levers is None else self.levers.get("devices")     # the agent's levers: only what its calls opened
        for k, spec in self.app.items():
            if k not in self.dev_off and k not in self.kept_out and (held is None or k in held):
                x = self._dev_kw(k, spec, j)
                if held is not None and spec.get("kind") == "source":           # a car gives what its call opened. The plan reads this too, and must not count a closed car
                    x = min(x, float(self.levers.get("v2h_kw", 0.0)))
                if x > 1e-6:
                    out[k] = x
        return out

    def _dev_kw(self, k: str, spec: dict[str, Any], j: int) -> float:
        x = float(self.dev_arr[k][self.dev_row, j]) * float(spec.get("share", 1.0))
        return min(x, self.ev_max) if self.car_rules and spec["kind"] == "source" else x     # the car circuit carries no more back

    def app_now(self, ts: str) -> float:
        return sum(self.dev_now(ts).values())

    def _v2h_give(self, x: float, ts: str, dt: float) -> float:
        """A plugged-in car gives from its battery; what it gives is charged back before it leaves, and it never
        gives more than the time left can put back (the owner's car first)."""
        spec = self.app["v2h"]
        if not (self.has_ev and self.ev_deadline) or ts >= self.ev_deadline or self.overrides.get("ev_now"):
            return 0.0                                              # the owner's now stops it at once
        if self.car_rules and self.e_part > 0.01:
            return 0.0                                              # one charger: it can't draw and give at once
        if self.v2h_day != ts[:10]:
            self.v2h_day, self.v2h_used = ts[:10], 0.0
        eff = float(spec.get("eff", 0.9))
        out = 1.0 / eff if self.car_rules else 1.0                  # kWh leaving the car for each kWh reaching the home
        give = max(0.0, min(x, (float(spec.get("event_kwh", 15.0)) - self.v2h_used) / out / dt, self.v2h_room(ts) * eff / dt))
        lim = (self.levers or {}).get("v2h_kwh")                    # the call's own max_kwh
        if lim is not None:
            give = min(give, max(0.0, float(lim)) / out / dt)
            self.levers["v2h_kwh"] = max(0.0, float(lim) - give * dt * out)
        self.v2h_owed += give * dt / eff
        if not self.ev_wait:
            self.ev_left += give * dt / eff                         # a timer car takes it on when its session starts
        self.v2h_used += give * dt * out
        return give

    def v2h_room(self, ts: str) -> float:
        """kWh the time left can still put back, after what the car must get anyway. A car on a timer charges from its timer."""
        if not self.ev_deadline:
            return 0.0
        eff = float(self.app["v2h"].get("eff", 0.9)) if "v2h" in self.app else 0.9
        w = self.ev_wait
        keep = self.ctl.limits.ev_keep_h if self.ctl else 0.0
        hours = max(0.0, self.replay.minutes_between(max(ts, w["arrival"]) if w else ts, self.ev_deadline) / 60.0 - keep)
        need = self.ev_left + (w["kwh"] + self.v2h_owed if w else 0.0)
        return max(0.0, self.ev_max * eff * hours - need)

    def _due(self, ts: str) -> bool:
        """A machine's done-by is the owner's: when the time left is what it and those before it still need, the stagger gives way."""
        need = 0.0
        for k in sorted(DONE_BY, key=lambda d: DONE_BY[d]):
            left = self.app_q.get(k, 0.0)
            if left > 1e-6:
                need += left / max(1e-6, float(self.app[k].get("kw", 1.0))) * 60
                if self.replay.minutes_between(ts, f"{ts[:11]}{DONE_BY[k]}") <= need + 15:
                    return True
        return False

    def _light_dim(self, ts: str, decided: dict[str, Any] | None) -> float:
        """A node's other smart systems (benchmark, MURMUR_DEVICES). While something is owed they wait, turn down or give;
        afterwards what waited catches up one device at a time at its own power, staggered per node. Positive = less
        load now; negative = the catch-up."""
        self.v2h_kw = 0.0
        if not self.app:
            return 0.0
        dt = 0.25 / SUB
        stop = bool(self.overrides.get("stop"))
        if not stop and self.ctl.app_holding(ts):
            kw = 0.0
            for k, x in sorted(self.dev_now(ts).items(), key=lambda d: self.app[d[0]]["kind"] == "source"):   # the car last: it takes what the meter has left
                spec = self.app[k]
                if spec["kind"] == "source":
                    if self.levers is not None:
                        x = min(x, float(self.levers.get("v2h_kw", 0.0)))
                    if self.car_rules:
                        x = min(x, max(0.0, self.meter_room - kw))  # past the export limit it would leave the car and be thrown away
                    x = self._v2h_give(x, ts, dt)
                    self.v2h_kw += x
                elif spec["kind"] == "shift":
                    self.app_q[k] = self.app_q.get(k, 0.0) + x * dt
                kw += x
            self.app_hold_end = ts
            return kw
        if not any(v > 1e-6 for v in self.app_q.values()):
            return 0.0
        if self.app_hold_end and not stop and self.replay.minutes_between(self.app_hold_end, ts) < self.ctl.app_delay_min() and not self._due(ts):
            return 0.0
        for k in sorted(self.app_q, key=lambda d: (d not in DONE_BY, self.app[d].get("order", 9))):
            left = self.app_q.get(k, 0.0)
            if left > 1e-6:
                kw = min(float(self.app[k].get("kw", 1.0)), left / dt)
                self.app_q[k] = max(0.0, left - kw * dt)
                return -kw
        return 0.0

    def _extra_tel(self, ts: str, acc: dict[str, float]) -> dict[str, Any]:
        """More telemetry for a node with more levers (a building's lighting); nothing for a home."""
        return {}

    def rt_capacity(self, call_from: str, call_to: str) -> dict[str, Any]:
        """How many kW this home can add from call_from to call_to, on top of what it owes (a call's question)."""
        if self.mode != "rolling" or self.ctl is None:
            return {"kw": 0.0, "why": "fixed plan: this home cannot change its plan during the day"}
        i = self.idx if self.idx is not None else self.replay.current()
        return self.ctl.capacity(i, call_from, call_to)

    def rt_dispatch(self, extra: dict[str, float]) -> None:
        """kW owed on top of the booking, per 15-minute step (the community agent's dispatch for a call or a gap)."""
        for ts, kw in extra.items():
            self.rt_extra[ts] = round(self.rt_extra.get(ts, 0.0) + float(kw), 4)

    def rt_reset(self) -> None:
        """A new run starts from the node as it was built, whatever the last run left it with: no dispatch on top, no owner's wish, the battery at its first charge and the car
        with its day's budget whole. Live days play one date again and again: without this, a second play of a date would find the cars' budget for it spent and a battery low,
        and homes would be paid less with nobody told. A person's own word stays: an alarm (rt_override), a group kept out, a limit. A restart in the middle of a run doesn't come
        here: it goes on where it stopped."""
        self.rt_extra.clear()
        self.rt_override("clear")
        self.set_battery_fault(False)
        self.afresh()
        self.idx, self.reset_on = None, getattr(self.replay, "_line", None)

    def afresh(self) -> None:
        """Everything a play changes, as it was built. What a person set isn't here, nor what MemberNode.reset clears with the contract, nor the last reading, which stands until the next step's."""
        self.soc = self.soc0
        self.ev_left, self.ev_deadline, self.ev_session, self.ev_wait, self.ev_skip = 0.0, None, None, None, None
        self.cf = {"soc": self.soc, "ev_left": 0.0, "ev_deadline": None}
        self.recent.clear()
        self.x = 0.0
        self.dev_off, self.app_q, self.app_hold_end = set(), {}, None
        self.v2h_day, self.v2h_used, self.v2h_owed, self.v2h_kw = None, 0.0, 0.0, 0.0
        self.e_part = self.meter_room = 0.0
        self.levers, self.held_out = None, set()
        self.clips, self.clip_at = [], {}
        self.note_seen = None                   # the same words at the same moment of the same date are this run's note
        if self.ctl is not None:
            self.ctl.afresh()

    def rt_override(self, kind: str, value: Any = True) -> None:
        """The owner: ev_now (charge the car at full power, now), comfort ({max_rise_c: ...}), stop (leave the event),
        depart_at (the car leaves earlier: "YYYY-MM-DD HH:MM"), clear (back to the plan).

        A person's comfort stays in comfort_limit, where the agent can't write. "comfort" is the slot the plan reads: with no levers it's the person's word, and with
        levers open that word only tightens what the calls opened, so a looser word can't open what no call did. agent_levers.write_comfort is the agent's door to the slot.

        An alarm leaves alarm_hold behind, and that stays through a clear, a reset and the signal ending. It holds the stop, until a person's signed word takes it away:
        context.py's clear_alarm, or the host's code_channel (agents/host_people.py) for a node with no agent. The hold is read by its key, not its value, and always has a true value: no value anyone
        sends can read as "not held". An alarm's value is what the signal said, and a value that says nothing is still a signal: only None and False mean it ended."""
        held = "alarm_hold" in self.overrides
        if kind in ("ev_now", "clear"):
            self.car_first = False                                # what a person says of the car is theirs, whatever a wish had said
        if kind == "clear":
            keep = {k: v for k, v in self.overrides.items() if k in ("alarm", "alarm_hold", "stop")} if held else {}
            self.overrides.clear()
            self.overrides.update(keep)
        elif kind == "stop" and held:
            self.overrides["stop"] = True
        elif kind == "depart_at":
            if self.ev_deadline and value < self.ev_deadline:
                self.ev_deadline = value
        elif kind == "comfort" and value not in (None, False):
            self.overrides["comfort_limit"] = value
            self.overrides["comfort"] = value if self.levers is None else control.inside(self.overrides.get("comfort") or {}, value)
        elif kind == "comfort":
            self.overrides.pop("comfort_limit", None)
            if self.levers is None:
                self.overrides.pop("comfort", None)
        elif value in (None, False):
            self.overrides.pop(kind, None)
            if kind == "note":
                self.overrides.pop("note_before", None)
        elif kind == "alarm":                                     # life safety, whoever runs the node: the plan stands down until a person clears it
            why = value if value is True or (isinstance(value, str) and value.strip()) else self.overrides.get("alarm_hold") or "alarm"
            self.overrides.update({"alarm": why, "alarm_hold": why, "stop": True})
        else:
            if kind == "note":
                self._note_waits()
            self.overrides[kind] = value
            if kind == "note":                                    # with when it came: a date in it means what it meant then, and the same words again are a new note
                self.overrides["note_at"] = self.replay.ts(self.replay.current())
            elif kind == "ev_now":                                # the car charges at once, and the request goes the way a note goes too
                self._car_now_note()

    def _car_now_note(self) -> None:
        """A person's "I need the car now", by phone or by the door, also goes through the note path. So the agent knows of it, the person hears it was
        heard, and there is a receipt and a human fact in the report."""
        from murmur.node.note_reader import CAR_NOW
        self.rt_override("note", CAR_NOW)

    def _note_waits(self) -> None:
        """A new note while the one before it is still unread: that one waits beside it, and both are read, the older first. Without this, "Keep the battery full tonight"
        would go unread when "Also the car must be charged" comes before the next step, and the battery would run down. In place, so a reader taking one off at the same
        moment takes it off this list."""
        from murmur.node.note_reader import note_key
        if self.overrides.get("note") and note_key(self.overrides) != self.note_seen:
            q = self.overrides.setdefault("note_before", [])
            q.append({"note": self.overrides["note"], "at": self.overrides.get("note_at")})
            del q[:-NOTES_WAITING]

    def hold_alarm(self, why: Any) -> None:
        """An alarm's hold, from the record: back after a restart, or asserted at a step. The signal isn't touched, and an alarm already holding keeps its own words."""
        self.overrides["alarm_hold"] = self.overrides.get("alarm_hold") or why
        self.rt_override("stop", True)

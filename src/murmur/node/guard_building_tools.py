"""The building guard's checks of each of its device tools: zone cooling and standby, air handlers, the plant's demand limit and early stop, lights, plugs, the battery and the car ports."""
from __future__ import annotations

import math
from murmur.node.guard import answer, blocked, num
from murmur.node.guard_building_rules import AMPS, EMPTY_C, FAN_MIN, GAP_C, MAX_DIM, OPEN_C, RAMP_MIN, RECOVER_MIN, SETPOINT_C, VOLTS, _touches, clock, day_of, mins, span, with_times, zone_kw


class BuildingGuardTools:
    """The building guard's checks of each of its device tools: zone cooling and standby, air handlers, the plant's demand limit and early stop, lights, plugs, the battery and the car ports."""

    # ------------------------------------------------------------------ zones
    def _set_zone_cooling(self, a, d, f, call):
        t, c = d["target"], num(a.get("offset_c"))
        stop = self._zone_stop(d)
        if stop:
            return blocked(t, stop)
        if not d["running"]:
            return blocked(t, "No cooling is running in this zone, so an offset moves nothing.")
        if c is None:
            return blocked(t, "offset_c must be a number.")
        if c == 0:
            return blocked(t, "An offset of 0 moves nothing.")
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if c < 0:
            sale = f.get("sale")
            if sale and span(call)[0] < mins(sale["end"]) and span(call)[1] > mins(sale["start"]):
                return blocked(t, "A pre-cool adds load, so it can't run into the sale.")
            return self._precool(t, c, d, call, times)
        lead = clock(mins((f.get("sale") or call)["start"]) - RAMP_MIN)
        state = d.get("state", "open")                          # not known means people may be in
        lim = d.get("limit_c")
        if lim is not None and lim <= 0:
            return blocked(t, d.get("limit_why", "This zone may not run warmer now."))
        if state in ("open", "booked") and c > OPEN_C:
            why = "A booked floor stays within +1.5 C." if state == "booked" else "+3 C is for empty zones, and this one is open."
            return blocked(t, why, {"tool": "set_zone_cooling", "target": t, "offset_c": OPEN_C if lim is None else min(OPEN_C, lim), "start": lead, "end": times["end"]})
        back = self._back_by(d, call)
        if back is not None and c > OPEN_C and span(call)[1] > back:
            try_ = {"offset_c": c, "start": times["start"], "end": clock(back)} if back > span(call)[0] else {"offset_c": OPEN_C, **times}
            return blocked(t, f'It must be back at temperature {RECOVER_MIN} minutes before its {clock(mins(d["next_booking"]))} booking.', {"tool": "set_zone_cooling", "target": t, **try_})
        applied, status, why = c, "done", ""
        if c > EMPTY_C:
            applied, status, why = EMPTY_C, "adjusted", "+3 C is the most any zone may take."
        if lim is not None and applied > lim:
            applied, status, why = lim, "adjusted", d.get("limit_why", f"This zone's limit is +{lim:g} C.")
        top, base = d.get("top_c"), d.get("base_c")
        if top is not None and base is not None and state in ("open", "booked") and base + applied > top + 1e-9:
            applied = math.floor((top - base) * 10 + 1e-9) / 10   # down, or the rounding itself passes the top
            if applied <= 0:
                return blocked(t, f'{d.get("top_says", "Occupied zones stop")} at {top:g} C at 50% RH, and this {base:g} C base is already there.')
            status, why = "adjusted", f'{d.get("top_says", "Occupied zones stop")} at {top:g} C at 50% RH, so a {base:g} C base takes +{applied:g} C.'
        if base is not None and base + applied > SETPOINT_C[1]:
            return blocked(t, "A cooling setpoint stays between 13 and 29 C.")
        out = {"offset_c": applied, **times}
        if state == "part" and applied > float(d.get("open_c", OPEN_C)):
            out["booked_rooms_offset_c"] = float(d.get("open_c", OPEN_C))       # the controller holds rooms with a booking there
        kw = zone_kw(d, applied)
        if d.get("plant_covers"):                                # count once: the plant carries this part
            kw *= 1 - float(d.get("plant_part", 1.0))
            why = why or "The plant carries this kW, so it counts once, under the plant."
        return answer(status, t, out, kw + float(d.get("tenant_fan_kw", 0.0)) * min(1.0, applied / OPEN_C), why)

    def _precool(self, t, c, d, call, times):
        depth = float(d.get("precool_c", 1.0))
        applied, status, why = c, "done", ""
        if c < -depth:
            applied, status, why = -depth, "adjusted", f"Pre-cool stops at -{depth:g} C here."
        base = d.get("base_c")
        if base is not None and base + applied < SETPOINT_C[0]:
            return blocked(t, "A cooling setpoint stays between 13 and 29 C.")
        floor, cool = d.get("heat_floor_c"), d.get("cool_c")
        if floor is not None and cool is not None and cool + applied < floor + GAP_C - 1e-9:
            best = round(floor + GAP_C - cool, 1)
            return blocked(t, f"Heating can't go under {floor:g} C by day, and the {GAP_C:g} C gap stays, so cooling stops at {floor + GAP_C:g} C.",
                           {"tool": "set_zone_cooling", "target": t, "offset_c": best, **times})
        return answer(status, t, {"offset_c": applied, **times}, 0.0, why)

    def _set_zone_standby(self, a, d, f, call):
        t, mode = d["target"], a.get("mode")
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if mode not in ("on", "off"):
            return blocked(t, "mode must be on or off.")
        if mode == "off":                                       # keeps the zone on its schedule, and ends any standby this node holds
            ended = self._end("set_zone_standby", d, mins(call["start"]))
            stop = None if ended else self._zone_stop(d)
            if stop:                                            # nothing of ours to give back, so nothing is written there
                return blocked(t, stop)
            for w in ended:                                     # a stop never holds a zone in standby: this is how it gets out
                w["ended"] = True
            return {**answer("done", t, {"mode": "off", **times}), "released": True}
        stop = self._zone_stop(d)
        if stop:
            return blocked(t, stop)
        if d.get("booked") or d.get("event_here"):
            return blocked(t, "This zone holds a booking or an event, so it stays on its schedule.")
        if d["mall_open"]:
            return blocked(t, "No mall zone counts as free while it is open.")
        if d["doas_open"]:
            return blocked(t, "An outdoor air unit stays on until every zone it serves is closed.")
        if d.get("closed"):
            return answer("done", t, {"mode": "on", **times}, 0.0, "Closed wing: the BMS schedule stops its air.")
        if not d["sensors"]:
            alt = d.get("instead")
            return blocked(t, "Every room needs a working occupant sensor, and CO2 is only a second check.",
                           {"tool": "set_zone_standby", "target": alt, "mode": "on", **times} if alt else None)
        if not d["standby_ok"]:
            return blocked(t, d.get("standby_why", "Its standby would stop outdoor air in an open building."),
                           {"tool": "set_zone_cooling", "target": t, "offset_c": EMPTY_C, "start": clock(mins((f.get("sale") or call)["start"])), "end": times["end"]})
        back = self._back_by(d, call)
        if back is not None and span(call)[1] > back:
            return blocked(t, f'It must be back at temperature {RECOVER_MIN} minutes before its {clock(mins(d["next_booking"]))} booking.',
                           {"tool": "set_zone_standby", "target": t, "mode": "on", "start": times["start"], "end": clock(back)} if back > span(call)[0] else None)
        limit = d.get("write_limit")
        if limit:                                               # Daikin boxes store each write: one long window, not short ones
            sale = f.get("sale")
            if sale and span(call)[1] - span(call)[0] < mins(sale["end"]) - mins(sale["start"]):
                return blocked(t, "Each change is a stored write, so one long window replaces short ones.",
                               {"tool": "set_zone_standby", "target": t, "mode": "on", "start": clock(mins(sale["start"])), "end": clock(mins(sale["end"]))})
            if self.mode_day and self.mode_day != day_of(call, f):
                self.mode_writes.clear()
            self.mode_day = day_of(call, f)
            if self.mode_writes.get(t, 0) + 2 > limit:
                return blocked(t, "Today's mode writes on these boxes are used up.")
        return answer("done", t, {"mode": "on", **times}, 0.0, "The saving shows under limit_air_handler and set_zone_cooling.")

    # ------------------------------------------------------------------ air handlers
    def _limit_air_handler(self, a, d, f, call):
        t, sp = d["target"], num(a.get("speed_percent"))
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        stop = self._zone_stop(d)
        if stop:
            return blocked(t, stop)
        if d["doas"]:
            return blocked(t, "A dedicated outdoor air unit holds its flow.")
        if not d["oa_ok"]:
            return blocked(t, "The unit has no outdoor airflow reading, and a fixed damper loses air as the fan slows.")
        if not d["co2_ok"]:
            return blocked(t, "A failed CO2 sensor ends any fan cap on that zone, and design airflow returns.")
        if d["hood"]:
            return blocked(t, "Hood make-up air takes no fan limit during service.")
        if sp is None:
            return blocked(t, "speed_percent must be a number.")
        floor = float(d.get("floor_percent", FAN_MIN))
        if sp < FAN_MIN:
            return blocked(t, "No agent stop while the area is open, so fans slow to about half flow.",
                           {"tool": "limit_air_handler", "target": t, "speed_percent": max(FAN_MIN, floor), **times})
        now = float(d.get("speed_now", 100.0))
        if sp >= now or floor >= now:                           # lifting the ask to the floor would raise a fan that runs under it
            return blocked(t, "It already runs at or below that speed, and a cap never raises a fan.")
        if not d["eased"]:
            e = d.get("ease_with") or {}
            return blocked(t, "Its zones aren't eased yet, so boxes would starve. Close the boxes first.", with_times(e, call, end=times["end"]) if e else None)
        applied, status, why = sp, "done", ""
        if sp < floor:
            applied, status, why = floor, "adjusted", d.get("floor_why", f"This unit stays at {floor:g} percent or more.")
        return answer(status, t, {"speed_percent": applied, **times}, float(d["kw_now"]) * (1 - (applied / now) ** 3), why)

    # ------------------------------------------------------------------ the plant
    def _set_plant_demand_limit(self, a, d, f, call):
        t, pct = d["target"], num(a.get("limit_percent"))
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if not d["running"]:
            return blocked(t, "The chillers are off, so there is nothing to cap.")
        if d["computer_room"]:
            return blocked(t, "This plant cools a computer room, and that cooling is never touched.")
        lab = float(d.get("lab_share", 0.0))
        if lab > 0 and not d["lab_live"]:
            return blocked(t, "No live lab load reading, so no cap on this loop.")
        if not d["zones_coast"]:
            z = d.get("ease_with") or {}
            return blocked(t, "Zones on this plant aren't set to coast, so the cap would only warm the water.", with_times(z, call) if z else None)
        if pct is None:
            return blocked(t, "limit_percent must be a number.")
        now = float(d["percent_now"])
        room, trimmed = d.get("room_percent"), ""
        if room is not None and pct < room:                     # a person lowered the comfort limit: past this the zones reach it early, and the plant comes back mid-sale
            pct, trimmed = room, d["limit_why"]
        if pct >= now:
            return blocked(t, trimmed or "The chillers already run under that percent, so a cap would move nothing.")
        lab_floor = math.ceil(now * lab * (1 + float(d.get("lab_margin", .10))) - 1e-9) if lab > 0 else 0
        chillers = d["chillers"]
        lowest = min(c["floor"] for c in chillers)
        need = max(lab_floor, lowest)
        if pct < need:
            c0 = min(chillers, key=lambda c: c["floor"])
            why = f"Labs set a floor of {lab_floor} percent on this loop." if lab_floor > lowest else f'{c0["product"]} stays at {lowest:g} percent or more.'
            return blocked(t, why, {"tool": "set_plant_demand_limit", "target": t, "limit_percent": need, **times})
        per = {c["name"]: max(pct, c["floor"]) for c in chillers}
        run = [c for c in chillers if c.get("running", True)] or chillers
        eff = sum(per[c["name"]] * c.get("count", 1) for c in run) / sum(c.get("count", 1) for c in run)
        if eff >= now:                                          # the running chillers' floors sit above where they run
            return blocked(t, "The chillers already run under their floors, so a cap would move nothing.")
        kw = float(d["plant_kw"]) * (1 - eff / now)
        high = [c for c in chillers if c["floor"] > pct]
        if high:
            c0 = high[0]
            return answer("adjusted", t, {**{f'{c["name"]} ({c["product"]})': {"limit_percent": per[c["name"]]} for c in chillers}, **times}, kw,
                          f'{c0["product"]} stays at {c0["floor"]:g} percent.')
        return answer("adjusted" if trimmed else "done", t, {"limit_percent": pct, **times}, kw, trimmed)

    def _stop_plant_early(self, a, d, f, call):
        t = d["target"]
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if not d["whole"]:
            return blocked(t, "Whole plants only: taking one chiller off is staging, and that stays in the BMS.", {"tool": "stop_plant_early", "target": d.get("plant", t), **times})
        if d.get("labs"):
            return blocked(t, "Labs share this water, so it can't stop.")
        if d.get("shared"):
            return blocked(t, "This plant is shared with another building.")
        if not d["running"]:
            return blocked(t, "The chillers are off, so there is nothing to stop.")
        if d["hot"] or d.get("limit_lowered"):                  # the list hides it too, but a rule that keeps people cool can't rest on what a model was shown
            return blocked(t, f'A stop can\'t be turned down, so {"on a hot evening" if d["hot"] else "with the comfort limit lowered"} the plant keeps running. Cap it instead.',
                           {"tool": "set_plant_demand_limit", "target": t, "limit_percent": max(c["floor"] for c in d.get("chillers", [{"floor": 70}])), **times})
        if not d["cleared"]:
            return blocked(t, "No signed list shows that nothing critical hangs on this loop.",
                           {"tool": "set_plant_demand_limit", "target": t, "limit_percent": max(c["floor"] for c in d.get("chillers", [{"floor": 70}])), **times})
        if not d["pre_ran"]:
            return blocked(t, "Pre-cool didn't run today, so there is no stored cold to coast on.",
                           {"tool": "set_plant_demand_limit", "target": t, "limit_percent": max(c["floor"] for c in d.get("chillers", [{"floor": 70}])), **times})
        if d.get("stops_today", 0) >= 1 or self.day_stops.get(t) == day_of(call, f):
            return blocked(t, "One stop and one start per chiller per day, and today's stop is used.")
        off = d.get("normal_off")
        if off and mins(call["end"]) < mins(off):
            return blocked(t, f"Ending before the plant's normal off time, {clock(mins(off))}, would restart it: a second start.",
                           {"tool": "stop_plant_early", "target": t, "start": times["start"], "end": clock(mins(off))})
        return answer("done", t, times, float(d["can_give_kw"]))

    # ------------------------------------------------------------------ rooms
    def _dim_lights(self, a, d, f, call):
        t, cut = d["target"], num(a.get("cut_percent"))
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if d.get("exam"):
            return blocked(t, "A room in this group is in an exam, so it is never touched.")
        if d.get("avoid"):
            return blocked(t, f'This is a time to avoid: {d["avoid"]}.')
        if d["utility"]:
            return blocked(t, "A utility event holds this target, and utility commands outrank the agent.")
        if d["override"]:
            return blocked(t, "A person's override is running, and the agent never cancels one.")
        if not d["shed_ok"]:
            alt = d.get("instead")
            return blocked(t, "An area here reads Load shed Allowed No, and the agent can't change that point.",
                           {"tool": "dim_lights", "target": alt, "cut_percent": cut, **times} if alt else None)
        if not d["running"]:
            return blocked(t, "The lights are already off, so there is no kW to move.")
        if cut is None or cut < 1 or cut > 100:
            return blocked(t, "cut_percent must be 1 to 50, or 100 for off.")
        kw, lim = float(d["running_kw"]) * float(d.get("scale", 1.0)), min(MAX_DIM, float(d.get("limit_pct", MAX_DIM)))     # a map can lower the 50%, never raise it
        if lim <= 0:
            return blocked(t, d.get("limit_why", "No dim is allowed here now."))
        fc = float(d.get("egress_fc") or 0.0)
        if d["egress"] and cut != 100:                          # 1 fc stays at the darkest point: 1.6 fc measured gives 37%, and no measure gives no dim
            if fc <= 1.0:
                return blocked(t, "This zone is on an exit route with no measured light to spare, so it takes no dim.")
            lim = min(lim, float(math.floor(100 * (1 - 1 / fc))))
        if cut == 100:
            if d.get("limit_lowered"):                          # a person's limit binds off as well
                return blocked(t, d.get("limit_why", "A person lowered this limit."), {"tool": "dim_lights", "target": t, "cut_percent": lim, **times})
            if not d.get("all_empty") or d["egress"]:
                return blocked(t, "Off needs every area empty, and away from exit routes.", {"tool": "dim_lights", "target": t, "cut_percent": lim, **times})
            return answer("done", t, {"cut_percent": 100, **times}, kw)
        if cut > lim:
            return answer("adjusted", t, {"cut_percent": lim, **times}, kw * lim / 100, d.get("limit_why", f"{lim:g}% is the most the guard allows."))
        return answer("done", t, {"cut_percent": cut, **times}, kw * cut / 100)

    def _switch_plugs(self, a, d, f, call):
        t, st = d["target"], a.get("state")
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if st == "on":
            return blocked(t, "The agent can't hold controlled receptacles on.", {"tool": "switch_plugs", "target": t, "state": "auto", **times})
        if st not in ("off", "auto"):
            return blocked(t, "state must be off or auto.")
        if st == "auto":
            ended = self._end("switch_plugs", d, mins(call["start"]))
            if not ended:
                return blocked(t, "This node holds nothing here to give back.")
            for w in ended:
                w["handed_back"] = True
            return {**answer("done", t, {"state": "auto", **times}, 0.0, "The plugs go back to their sensors."), "released": True}
        if any(w.get("handed_back") for p in self._points("switch_plugs", d) for w in self.writers.get(p, [])):
            return blocked(t, "One off and one hand-back per group per window, and this group has had both.")
        if d["override"]:
            return blocked(t, "An occupant override is running, and the agent never removes one.")
        if not d["loads_ok"]:
            alt = d.get("instead")
            return blocked(t, d.get("loads_why", "The group holds a load that can't be switched."), {"tool": "switch_plugs", "target": alt, "state": "off", **times} if alt else None)
        if not d.get("any_time") and not d["free"]:
            return blocked(t, "Only free zones: empty, with no booking. Unknown counts as occupied.")
        return answer("done", t, {"state": "off", **times}, float(d["can_give_kw"]))

    # ------------------------------------------------------------------ site
    def _set_battery(self, a, d, f, call):
        t, act, kw = d["target"], a.get("action"), num(a.get("kw"))
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if act not in ("charge", "discharge", "hold"):
            return blocked(t, "action must be charge, discharge or hold.")
        if d.get("tripped"):
            return blocked(t, "The battery tripped in the last 10 minutes. It stays off and the agent doesn't retry.")
        for k, why in (("utility", "A utility command is active, so the plan stands down and reports."), ("generator", "A generator is running, so the plan stands down."),
                       ("other_program", "Another program holds these hours for this battery.")):
            if d[k]:
                return blocked(t, why)
        if act == "hold":
            if kw:
                return answer("adjusted", t, {"action": "hold", "kw": 0, **times}, 0.0, "With hold, kw is 0.")
            return answer("done", t, {"action": "hold", "kw": 0, **times})
        if kw is None or kw <= 0:
            return blocked(t, "A charge or discharge needs more than 0 kW.", {"tool": "set_battery", "target": t, "action": "hold", "kw": 0, **times})
        rating = float(d["rating_kw"])
        if kw > rating:
            return blocked(t, f"{rating:g} kW is the planning rating, and the overload isn't for planning.", {"tool": "set_battery", "target": t, "action": act, "kw": rating, **times})
        s, e = span(call)
        sale = f.get("sale")
        if act == "charge":
            if sale and s < mins(sale["end"]) and e > mins(sale["start"]):
                return blocked(t, "A charge adds load, so it can't run into the sale.", {"tool": "set_battery", "target": t, "action": "hold", "kw": 0, **times})
            limits = d.get("charge_limit_kw") or {}
            low = [(w, v) for w, v in limits.items() if _touches(w, s, e) and kw > v]
            if low:
                edge = min(mins(w[:5]) for w, _ in low)
                return blocked(t, "The charge limit for part of this call is below that.",
                               {"tool": "set_battery", "target": t, "action": "charge", "kw": kw, "start": clock(edge - (e - s)), "end": clock(edge)})
            return answer("done", t, {"action": "charge", "kw": kw, **times}, -kw)
        hours = (e - s) / 60.0
        above = float(d["stored_kwh"]) - float(d["reserve_kwh"]) - self._promised(d, f)
        if kw * hours > above + 1e-6:
            best = math.floor(max(0.0, above) / hours)
            return blocked(t, f"The call needs {kw * hours:,.0f} kWh and only {above:,.0f} kWh sits above the reserve.",
                           {"tool": "set_battery", "target": t, "action": "discharge", "kw": best, **times} if best > 0 else None)
        need = float(d.get("award_kwh", 0.0))                    # a discharge outside an award can't use what an award needs
        if need and sale and not (mins(sale["start"]) <= s and e <= mins(sale["end"])) and above - kw * hours < need:
            return blocked(t, "That would use energy the award needs.")
        export = max(0.0, kw - float(d["import_kw"]))
        if any(_touches(w, s, e) and export > v for w, v in (d.get("discharge_limit_kw") or {}).items()):
            return blocked(t, "Export would pass the discharge limit for part of this call.")
        room = float(d["import_kw"]) - float(d["trip_kw"])
        if kw >= room:
            best = max(0.0, math.ceil(room) - 1)
            if best <= 0:
                return blocked(t, f'Import is already at the {d["trip_kw"]:g} kW trip point.')
            return answer("adjusted", t, {"action": "discharge", "kw": best, **times}, best,
                          f'Import must stay above the {d["trip_kw"]:g} kW trip point, and {best + 1:g} kW would leave it at {d["trip_kw"]:g} kW.')
        return answer("done", t, {"action": "discharge", "kw": kw, **times}, kw)

    def _limit_ev_charging(self, a, d, f, call):
        t, amps = d["target"], num(a.get("amps"))
        times = {k: clock(mins(call[k])) for k in ("start", "end")}
        if not d["control"]:
            alt = d.get("instead")
            return blocked(t, "Those ports have no control path.", {"tool": "limit_ev_charging", "target": alt, "amps": a.get("amps"), **times} if alt else None)
        if amps is None or amps < 0 or 0 < amps < AMPS[0] or amps > AMPS[1]:
            return blocked(t, "A port takes 0, or 6 to 80 A, with nothing between.", {"tool": "limit_ev_charging", "target": t, "amps": AMPS[0], **times})
        sessions = [x for x in d.get("sessions", []) if x.get("amps", 0) > 0]
        if not sessions:
            return blocked(t, "No session is drawing power here, so it moves 0 kW.")
        if amps > 0 and amps >= max(x["amps"] for x in sessions):
            return blocked(t, "Every car here draws less than that, so it moves 0 kW, and a limit never raises a port.")
        s, e = span(call)
        volts = float(d.get("volts", VOLTS))
        day = str(call["start"])[:10] if len(str(call["start"])) > 5 else None
        lost = [x for x in sessions if not self._car_ok(x, amps, s, e, volts, day)]
        if lost:
            alt = d.get("instead")
            if alt:
                return blocked(t, "A car that must leave stays out of the limit.", {"tool": "limit_ev_charging", "target": alt, "amps": a.get("amps"), **times})
            if amps < AMPS[0] and all(self._car_ok(x, AMPS[0], s, e, volts, day) for x in sessions):
                return blocked(t, "A pause would leave a car short when it leaves.", {"tool": "limit_ev_charging", "target": t, "amps": AMPS[0], **times})
            return blocked(t, "A car must leave and still needs its charge.")
        kw = sum(max(0.0, volts * (x["amps"] - amps) / 1000) for x in sessions)
        return answer("done", t, {"amps": amps, **times}, kw, d.get("note", ""))

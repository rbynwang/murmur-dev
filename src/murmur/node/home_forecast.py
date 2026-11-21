"""A member's own forecasts: solar and house load per 15-minute step (the straight-line fit on temperature, or the trained models), the car's charging, and the battery's default run."""
from __future__ import annotations

from typing import Any
from murmur.protocol import envelope as beckn
from murmur.node.forecast import HomeForecaster
from murmur.node.home_days import BACKUP, POST_STEPS, TRAINED, last_same_kind_step, temp_forecast


class HomeForecasting:
    """A member's own forecasts: solar and house load per 15-minute step (the straight-line fit on temperature, or the trained models), the car's charging, and the battery's default run."""

    def rt_forecast(self, i: int, ts_list: list[str]) -> dict[str, tuple[float, float]]:
        """The 5-minute loop's forecast of solar and house load for the next steps (RollingController corrects it with what
        the meter reads now): the trained models (forecast = "trained") made from the history up to now, once an
        hour; else today's day-ahead method run from now."""
        hour = i // 4
        if self._rt_fc["hour"] != hour:
            self._rt_fc = {"hour": hour, "vals": {}}
        vals = self._rt_fc["vals"]
        todo = [t for t in ts_list if t not in vals]
        if todo:
            if self.cfg.get("forecast") in TRAINED:
                try:
                    f = self._models().forecast(i, todo) or {}
                    for t, v in f.items():
                        vals[t] = (float(v["pv"][1]), float(v.get("load_mean", v["load"][1])))
                except Exception as exc:                       # no model files: the day-ahead method below
                    self.log("rt_forecast_fallback", error=str(exc)[:160])
            saved, self._fc_now = self._fc_now, i
            try:
                for t in todo:
                    if t not in vals:
                        vals[t] = self._naive(t)
            finally:
                self._fc_now = saved
        return {t: vals[t] for t in ts_list if t in vals}

    def _models(self):
        """The home's trained forecaster, made on first use. Raises where its files or the dataset's columns are missing."""
        if self._forecaster is None:
            self._forecaster = HomeForecaster(self.name, self.replay)
        return self._forecaster

    def _ev_latest(self, day: str) -> dict[str, Any] | None:
        """The latest charging session that has already started, moved to `day`: the EV forecast."""
        if not self.adapter.has_ev:
            return None
        now = self.now_ts()
        for s in reversed(self.replay.sessions):
            if s["arrival"] <= now:
                arrival = day + s["arrival"][10:]
                return {"arrival": arrival, "deadline": beckn.add_minutes(arrival, self.replay.minutes_between(
                            s["arrival"], s["deadline"])), "kwh": s["kwh"],
                        "max_kw": min(self.adapter.ev_max, s["max_kw"])}
        return None

    @staticmethod
    def _ev_profile(ev: dict[str, Any] | None, ts_list: list[str]) -> list[float]:
        """Unmanaged charging (full power from arrival until done) on the given 15-minute steps."""
        out, left = [], (ev or {}).get("kwh", 0.0)
        if ev:
            t = ev["arrival"]
            while left > 1e-6 and t < ev["deadline"] and t < ts_list[0]:      # energy charged before the steps
                left -= min(ev["max_kw"] * 0.25, left)
                t = beckn.add_minutes(t, 15)
        for ts in ts_list:
            kw = 0.0
            if ev and ev["arrival"] <= ts < ev["deadline"] and left > 1e-6:
                kw = min(ev["max_kw"], left / 0.25)
                left -= kw * 0.25
            out.append(kw)
        return out

    def _naive(self, ts: str) -> tuple[float, float]:
        """(PV, load) forecast for one 15-minute step. PV: mean of the same step on the previous 3 days.
        Load: the same, or (forecast = "temp_regression", the default) a straight-line fit of load on temperature
        for that hour of day over the previous 21 days, applied to the day-ahead temperature forecast."""
        if self._tf and ts in self._tf:                     # forecast = "trained": PV median, load expected value
            f = self._tf[ts]
            return f["pv"][1], f.get("load_mean", f["load"][1])
        i = self.replay.idx_of(ts)
        if i is None:
            return 0.0, 0.0
        days = self._past_days(i, 3)
        pv = [self.replay.row(i - 96 * d)["pv_kw"] for d in days]
        ld = [self.replay.row(i - 96 * d)["base_kw"] for d in days]
        if not days:
            return 0.0, 0.0
        load = sum(ld) / len(ld)
        if self.cfg.get("forecast", "temp_regression") == "temp_regression":
            fit = self._load_fit(i)
            if fit:
                row = self.replay.row(i)
                tf = row.get("fc_temp_c")                  # the forecast as issued, where the dataset has it
                load = max(0.0, fit[0] + fit[1] * (tf if tf is not None else temp_forecast(ts, row["temp_c"])))
        trained = self._building_load(ts)
        return sum(pv) / len(pv), load if trained is None else trained

    def _building_load(self, ts: str) -> float | None:
        """A building's own forecast of its total load, where its settings ask for one. None past what its record, the models or the calendar reach, and the rule stands in.
        "same_kind_day": the same quarter hour on the last day of the same kind (weekday, Saturday, Sunday or holiday). On ENGIE's 2025 it is off by under 2% in the sale window,
        where the temperature line over days of every kind is off by 8 to 11%."""
        if self.is_building and self.cfg.get("building_forecast") == "same_kind_day":
            from murmur import config
            i = self.replay.idx_of(ts)
            if i is None:
                return None
            now = self._fc_now if getattr(self, "_fc_now", None) is not None else self.now_idx()
            j = last_same_kind_step(i, now, self.replay.ts, set(config.dataset_meta().get("holidays") or []))
            return None if j is None else float(self.replay.row(j)["base_kw"])
        return None

    def _range(self, ts: str) -> dict[str, float]:
        """The trained forecast's 10 % and 90 % values for a step (empty under the other methods)."""
        f = (self._tf or {}).get(ts)
        if not f:
            return {}
        return {"pv_p10": round(f["pv"][0], 3), "pv_p90": round(f["pv"][2], 3),
                "load_p10": round(f["load"][0], 3), "load_p90": round(f["load"][2], 3)}

    def _past_days(self, i: int, n: int) -> list[int]:
        """The n most recent whole days d for which step i - 96 d is already in the past (before the forecast was
        made): an offer made at 10:00 for tomorrow 16:00 cannot use today's 16:00."""
        now = getattr(self, "_fc_now", None)
        now = self.now_idx() if now is None else now
        first = 1
        while i - 96 * first >= now:
            first += 1
        return [d for d in range(first, first + n) if i - 96 * d >= 0]

    def _load_fit(self, i: int) -> tuple[float, float] | None:
        """Ordinary least squares load = a + b x temperature, on the same hour of day over the previous 21 days
        (84 points). History only: nothing from the forecast day is used."""
        h0 = i - (i % 4)                                    # first 15-minute step of this hour
        key = (self.replay.ts(h0)[11:13], self.replay.ts(i)[:10], self._fc_now)
        if key in self._fits:
            return self._fits[key]
        xs, ys = [], []
        for d in self._past_days(h0 + 3, 21):
            for q in range(4):
                j = h0 + q - 96 * d
                if j >= 0:
                    r = self.replay.row(j)
                    xs.append(r["temp_c"]); ys.append(r["base_kw"])
        fit = None
        if len(xs) >= 20:
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            if sxx > 1e-6:
                b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
                fit = (my - b * mx, b)
        self._fits[key] = fit
        return fit

    # ------------------------------------------------------------------ H3 Offer
    def forecast_window(self, need: dict[str, Any]) -> dict[str, Any]:
        day = need["window_start"][:10]
        self._fc_now = self.now_idx()
        ev = self._ev_latest(day)
        win = [(s["id"], beckn.add_minutes(s["start"], 15 * k)) for s in need["slots"] for k in (0, 1)]
        post_ts = [beckn.add_minutes(need["window_end"], 15 * k) for k in range(POST_STEPS)]
        ev_win, ev_post = self._ev_profile(ev, [t for _, t in win]), self._ev_profile(ev, post_ts)
        # from now to the window: where the battery will stand when the window opens (no event)
        lead_ts, t = [], self.replay.ts(self._fc_now + 1)
        while t < need["window_start"] and len(lead_ts) < 96 * 3:
            lead_ts.append(t)
            t = beckn.add_minutes(t, 15)
        ev_lead = [0.0] * len(lead_ts)
        for d in sorted({x[:10] for x in lead_ts}):               # each day's expected session before the window
            prof = self._ev_profile(self._ev_latest(d), lead_ts)
            ev_lead = [x + y for x, y in zip(ev_lead, prof)]
        self._tf = None
        if self.cfg.get("forecast") in TRAINED:
            try:
                self._tf = self._models().forecast(self._fc_now, lead_ts + [t for _, t in win] + post_ts) or None
            except Exception as exc:                     # no model files etc.: today's method, and say so
                self.log("v2_forecast_fallback", error=str(exc)[:200])
            if self._tf and ev:                          # the EV: the latest session, scaled to what the EV model
                x = self._forecaster.ev_expected(day)    # expects in 15:00-20:00 (never above the session itself)
                if x is not None and "kw_by_hour" in x:  # a car forecast in kW by hour of the day itself, for the whole community to add up
                    part = x["takes_part"] or (int(need["window_start"][11:13]), int(need["window_end"][11:13])) != x["window"]   # the chance is for its own window
                    kw = lambda t: x["kw_by_hour"][int(t[11:13])]                      # noqa: E731  (past midnight: the night before, the nearest forecast)
                    ev_win, ev_post = [kw(t) if part else 0.0 for _, t in win], [kw(t) for t in post_ts]   # a car out of the sale still charges after it
                    ev = {**ev, "expected_kwh_window": round(x["mean_kwh"], 2), "p_charging": round(x["p_charging"], 2), "in_sale": part}
                elif x is not None:
                    span = [f"{day} {h:02d}:{m:02d}" for h in range(15, 20) for m in (0, 15, 30, 45)]
                    full = sum(self._ev_profile(ev, span)) * 0.25
                    k = min(1.0, x["mean_kwh"] / full) if full > 0.1 else 1.0
                    ev_win, ev_post = [v * k for v in ev_win], [v * k for v in ev_post]
                    ev = {**ev, "expected_kwh_15_20": round(x["mean_kwh"], 2), "p_charging": round(x["p_charging"], 2),
                          "scale": round(k, 3)}
        lead = []
        for ts, evk in zip(lead_ts, ev_lead):
            pv, ld = self._naive(ts)
            lead.append({"ts": ts, "pv_p50": round(pv, 3), "load_p50": round(ld, 3), "ev_kw": round(evk, 2)})
        steps, post = [], []
        for (sid, ts), evk in zip(win, ev_win):
            pv, ld = self._naive(ts)
            steps.append({"slot_id": sid, "ts": ts, "pv_p50": round(pv, 3), "load_p50": round(ld, 3), "ev_kw": round(evk, 2),
                          **self._range(ts)})
        for ts, evk in zip(post_ts, ev_post):
            pv, ld = self._naive(ts)
            post.append({"ts": ts, "pv_p50": round(pv, 3), "load_p50": round(ld, 3), "ev_kw": round(evk, 2)})
        method = ("load: hour-of-day regression on day-ahead temperature, previous 21 days"
                  if self.cfg.get("forecast", "temp_regression") == "temp_regression" else "load: previous 3 days")
        ev_how = "; EV: latest session"
        method = f"{self._forecaster.method}{ev_how}" if self._tf else f"{method}; PV: previous 3 days; EV: latest session"
        self._tf = None
        return {"event_id": need["event_id"], "method": method,
                "steps": steps, "post": post, "ev": ev, "lead": lead,
                "soc_now_pct": self.observe().get("soc_pct")}

    @staticmethod
    def _battery_run(steps: list[dict[str, Any]], E: float, Emax: float, P: float, eta: float, ev_on: bool,
                     extra: list[float] | None = None) -> tuple[list[float], float]:
        """Net import per step with the battery in its default job (cover deficit, store surplus), plus extra[k] kW
        of delivery on top at step k. E, Emax: kWh the battery can still deliver (AC side).
        build_offer starts it where the forecast says it will stand when the window opens."""
        imp = []
        for k, st in enumerate(steps):
            net = st["load_p50"] + (st["ev_kw"] if ev_on else 0.0) - st["pv_p50"]
            b = (0.0 if BACKUP else min(P, net)) if net > 0 else -min(P, -net)
            if extra and k < len(extra):
                b += extra[k]
            b = max(-min(P, (Emax - E) / 0.25 / (eta * eta)), min(b, P, E / 0.25))
            E -= b * 0.25 if b > 0 else b * 0.25 * eta * eta
            imp.append(net - b)
        return imp, E

    def _weather(self) -> dict[str, Any] | None:
        """The what-if weather in force for this home ({pv, load, from}), or None on the dataset's own weather."""
        from murmur import replay as replay_mod
        w = getattr(self.replay, "weather", None)
        w = w if w is not None else replay_mod.WEATHER
        if not w.get("from"):
            return None
        return {"pv": round(float(w.get("pv", 1.0)), 4), "load": round(float(w.get("load", 1.0)), 4), "from": w["from"]}

    def _fc_words(self, fc: dict[str, Any]) -> str:
        st = fc.get("steps") or []
        if not st:
            return "no forecast"
        pv = [x.get("pv_p50", 0.0) for x in st]
        ld = [x.get("load_p50", 0.0) for x in st]
        ev = fc.get("ev") or {}
        m = str(fc.get("method", ""))
        src = "trained models" if m.startswith("trained") else m.split(":")[0][:40] or "forecast"
        out = f"{src}: solar {min(pv):.1f}-{max(pv):.1f} kW, house load {min(ld):.1f}-{max(ld):.1f} kW in the window"
        if ev.get("expected_kwh_15_20") is not None:
            out += f"; EV {ev['expected_kwh_15_20']:.1f} kWh expected 15-20 h (charging chance {ev.get('p_charging', 0):.0%})"
        elif ev:
            out += "; EV session expected"
        return out

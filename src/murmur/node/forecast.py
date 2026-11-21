"""Trained day-ahead forecasts for a home (forecast = "trained"): its base load and its solar, each as 10/50/90 % quantiles, from the
exported gradient-boosted trees in $MURMUR_MODELS_DIR, evaluated with numpy only (node/treemodel.py).
"""
from __future__ import annotations

import json

import math
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

import numpy as np

from murmur import config
from murmur.protocol.envelope import add_minutes
from murmur.node.treemodel import TreeModel

LAGS = (48, 72, 96, 168)
BAR_14D, BAR_24H = 269, 19     # the load forecast's own bar: readings it wants of the last 336 hours, and of the last 24
STUCK_HOURS = 6                # a meter that repeats one value this many hours running, after the reading it froze on, has no reading for those hours
RULE_DAYS, RULE_BACK = 3, 35   # the plain rule: the same hour on the last three days of the same kind, looked for this many days back
SHAPE_BACK = 60                # the last known whole day is looked for this far back
RANGE_RULE, RANGE_SHAPE = 0.30, 0.40      # the range a stand-in carries, as a share of its value
STRETCH_24H, STRETCH_WEATHER = 0.15, 0.55 # how much wider the model's range gets with no mean of the last 24 hours, and with no weather forecast for the hour
MODEL = "model"
NO_VALUE = "model, missing inputs as no value"
RULE = "plain rule: same hour, last three days of the same kind"
SHAPE = "last known day's shape"
BACK, AHEAD = 336 * 4 + 8, 48 * 4          # quarter hours around the issue time that a forecast's inputs reach


@lru_cache(maxsize=24)
def _model(path: str) -> TreeModel:
    return TreeModel.load(path)

@lru_cache(maxsize=1)
def _roster() -> dict[str, dict[str, Any]]:
    try:
        return {h["name"]: h for h in json.loads(config.data_path("fleet_v2.json").read_text())["homes"]}
    except (OSError, ValueError, KeyError):
        return {}



def cos_zenith(utc: datetime, lat: float, lon: float) -> float:
    """cos(solar zenith) at the middle of the hour starting at `utc` (NOAA simplified formulas, as in training)."""
    t = utc + timedelta(minutes=30)
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60.0
    g = 2 * math.pi / 365.0 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    ha = math.radians((hour * 60 + eqt + 4 * lon) / 4 - 180)
    la = math.radians(lat)
    return math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)


def clear_sky(cz: float) -> float:
    """Haurwitz clear-sky sunlight, W/m2."""
    return 1098 * cz * math.exp(-0.057 / max(cz, 0.01)) if cz > 0.01 else 0.0


class HomeForecaster:
    """forecast(now_idx, ts_list) -> {ts: {"pv": (p10, p50, p90), "load": (p10, p50, p90), "load_mean": kW}}.
    The agent's energy balance uses load_mean (an offer adds hours up; a skewed load's median is low) and the PV
    median; the 10-90 % values travel with the forecast."""

    def __init__(self, name: str, replay, home: dict[str, Any] | None = None, correct_pv: bool = True, min_share: float | None = None):
        meta = config.dataset_meta()
        self.replay = replay
        self.min_share = min_share                      # for a community's load, which is never zero: a reading of 0 kW, or under this share of the series' own median, is no reading. None for a home, where zero use can be real
        self._min_kw: float | None = None
        self.home = home or _roster().get(name, {})
        mdir = config.model_path(meta.get("models", "forecast_2025_26"))
        self.load_m = _model(str(mdir / "home_base_load.json.gz"))
        self.pv_m = _model(str(mdir / "solar_per_kw.json.gz"))
        self.ev_m = _model(str(mdir / "ev_window.json.gz")) if (mdir / "ev_window.json.gz").exists() else None
        self._evd: tuple[dict, dict] | None = None             # each day's unmanaged EV kWh (15-20 h, whole day)
        comm = meta.get("community", {})
        self.lat = float(self.home.get("lat", comm.get("lat", 42.26)))
        self.lon = float(self.home.get("lon", comm.get("lon", -71.80)))
        self.pv_kw = float(self.home.get("pv_scale_kw", self.home.get("pv_kw_dc", 0.0)) or 0.0)
        self.static = {"is_hp": int(self.home.get("heating_type") == "heat_pump"),
                       "has_ev": int(bool(self.home.get("has_ev", False)))}
        self.tz = int(meta.get("tz_offset_h", -4))
        self.tz_name = meta.get("tz_name")
        self.holidays = {date.fromisoformat(d) for d in meta.get("holidays", [])}
        self._corr: dict[str, dict[int, float]] = {}          # per-hour solar correction, for the current day
        self.correct_pv = correct_pv
        self.method = ("trained: home_base_load (gradient-boosted trees on 100 synthetic homes) and solar_per_kw "
                       "(trained on a measured research house's PV, corrected per hour of day by this array's last 14 days), "
                       "10/50/90 %, ECMWF forecasts issued 48 h ahead; EV: ev_window (expected kWh 15-20 h, trained on "
                       "synthetic EV homes) scales the latest session")

    # ------------------------------------------------------------------ the home's own hourly history
    def _row(self, i: int) -> dict[str, Any] | None:
        return self.replay.row(i) if 0 <= i < len(self.replay.rows) else None

    def _val(self, i: int | None, col: str) -> float:
        r = self._row(i) if i is not None else None
        if r is None or col not in r or col in r.get("_missing", ()):      # a cell that was blank in the file is no reading (replay.py)
            return float("nan")
        return float(r[col])

    # ------------------------------------------------------------------ rows by their own time stamps
    def _absent(self, a: int, b: int) -> int:
        """Quarter-hour rows absent from the file between two neighbouring rows, by their own time stamps. A clock change is no gap."""
        da, db = (datetime.strptime(self.replay.ts(i), "%Y-%m-%d %H:%M") for i in (a, b))
        d = int((db - da).total_seconds() // 60)
        if d == 15 or d <= 0:                           # in step, or the hour that repeats when the clocks fall back
            return 0
        if self.tz_name and d - 15 == round((self._offset(db) - self._offset(da)) * 60):
            return 0                                    # the clocks went forward
        return max(0, d // 15 - 1)

    def _lined_up(self, tau: int) -> dict[int, int] | None:
        """Rows by how many quarter hours they lie from tau, from their own time stamps: {-4: the row an hour before, ...}. None when every row around tau is in its
        place, which is every file the project's builder writes: then it is row tau + k. A row absent from the file leaves its place empty and shifts nothing:
        counted by position, a few absent hours would move every earlier reading by as many hours, and the forecast would go wrong with no sign of it."""
        key = (len(self.replay.rows), tau)              # kept for the one forecast it was worked out in (_history clears it)
        if getattr(self, "_grid", (None, None))[0] == key:
            return self._grid[1]
        lo, hi = max(0, tau - BACK), min(len(self.replay.rows) - 1, tau + AHEAD)
        t0, grid = self.replay.ts(tau), None
        if self.replay.ts(lo) != add_minutes(t0, -15 * (tau - lo)) or self.replay.ts(hi) != add_minutes(t0, 15 * (hi - tau)):
            grid, o = {0: tau}, 0
            for i in range(tau - 1, lo - 1, -1):
                o -= 1 + self._absent(i, i + 1)
                grid[o] = i
            o = 0
            for i in range(tau + 1, hi + 1):
                o += 1 + self._absent(i - 1, i)
                grid[o] = i
        self._grid, self._grid_back = (key, grid), (key, None if grid is None else {row: o for o, row in grid.items()})
        return grid

    def _at(self, tau: int, i: int, k: int) -> int | None:
        """The row k quarter hours after row i (before it, for k below 0), by time stamp. i is a row a forecast reads: tau itself, or an hour it forecasts."""
        grid = self._lined_up(tau)
        if grid is None:
            return i + k
        o = self._grid_back[1].get(i)
        return None if o is None else grid.get(o + k)

    def _history(self, tau: int) -> tuple[list[float], set[int]]:
        """The hourly meter readings before tau, newest first: the last 336 hours, each lined up by its time stamp. No value where the cell was blank, where the row is
        absent, and where the meter repeats one value for STUCK_HOURS or more: the reading it froze on stands, and the repeats after it are no readings. The rows of
        those repeats come back too, so a same-hour reading days back isn't taken from one either."""
        self._grid = (None, None)                       # each forecast lines its rows up afresh: the file behind this forecaster may not be the one the last forecast read
        rows = [self._at(tau, tau, -4 * k) for k in range(1, 337)]
        vals = [self._val(i, "base_kw") if i is not None and i >= 0 else float("nan") for i in rows]
        self._min_kw = None
        if getattr(self, "min_share", None) is not None:        # a reading that arrives as 0 kW, wherever it comes from: a blank someone filled, a meter that reports nothing
            real = [v for v in vals if np.isfinite(v) and v > 0]
            self._min_kw = self.min_share * float(np.median(real)) if real else 0.0
            vals = [float("nan") if np.isfinite(v) and (v <= 0 or v < self._min_kw) else v for v in vals]
        stuck: set[int] = set()
        k = len(vals) - 1                               # from the oldest: a run of one value, and the newer readings that repeat it
        while k > 0:
            j = k
            while j > 0 and np.isfinite(vals[k]) and vals[j - 1] == vals[k]:
                j -= 1
            if k - j >= STUCK_HOURS:
                for x in range(j, k):
                    stuck.add(rows[x])
                    vals[x] = float("nan")
            k = j - 1 if j < k else k - 1
        return vals, stuck

    def _mean(self, i0: int, i1: int, col: str) -> tuple[float, int]:
        """mean of `col` over hour starts in [i0, i1) (steps of 4)."""
        xs = [self._val(j, col) for j in range(max(0, i0), i1, 4)]
        xs = [x for x in xs if np.isfinite(x)]
        return (sum(xs) / len(xs), len(xs)) if xs else (float("nan"), 0)

    def _hour_start(self, i: int) -> int:
        return i - int(self.replay.ts(i)[14:16]) // 15

    def _context(self, now_idx: int) -> dict[str, float]:
        """What is known at the forecast's issue time: the last complete hour ends where the current hour starts."""
        tau = self._hour_start(now_idx)
        vals, stuck = self._history(tau)
        seen = [x for x in reversed(vals) if np.isfinite(x)]          # oldest first: the order of the sum fixes its last digit
        day = [x for x in reversed(vals[:24]) if np.isfinite(x)]
        n14, n24 = len(seen), len(day)
        scale = sum(seen) / n14 if seen else float("nan")
        last24 = sum(day) / n24 if day else float("nan")
        return {"tau": tau, "scale": scale if n14 >= BAR_14D else float("nan"), "last24": last24 if n24 >= BAR_24H else float("nan"),
                "any_scale": scale, "any_last24": last24, "n14": n14, "n24": n24, "missing": 1 - n14 / 336, "stuck": stuck}

    def _day_temps(self, i: int) -> tuple[float, float, float]:
        day = self.replay.ts(i)[:10]                    # the day's 24 hours by their time stamps, so an absent row can't pull in the next day's
        xs = [self._val(self.replay.idx_of(f"{day} {h:02d}:00"), "fc_temp_c") for h in range(24)]
        xs = [x for x in xs if np.isfinite(x)]
        return (sum(xs) / len(xs), max(xs), min(xs)) if xs else (float("nan"),) * 3

    def _stand_in(self, tau: int, h0s: list[int], stuck: set[int]) -> tuple[dict[int, tuple[float, float, float]], str]:
        """With nothing in the last 14 days the model can't run. The plain rule answers first: each hour, the mean of the same hour on the last three days of the same
        kind (a working day, or a weekend or holiday) that were over at the issue time and have a reading, up to RULE_BACK days back. If an hour has none, the last
        whole day on record gives its shape. Each carries a plain range, a share of its value on either side. ({hour's row: (low, middle, high)}, which it was)."""
        issue = date.fromisoformat(self.replay.ts(tau)[:10])
        off = lambda d: d.weekday() >= 5 or d in self.holidays       # noqa: E731

        def read(d: date, hh: str) -> float:
            i = self.replay.idx_of(f"{d} {hh}:00")
            return self._known(i, tau, "base_kw", stuck)
        out: dict[int, tuple[float, float, float]] = {}
        for h in h0s:
            ts = self.replay.ts(h)
            day, vals = date.fromisoformat(ts[:10]), []
            for back in range(1, RULE_BACK + 1):
                d = day - timedelta(days=back)
                if d >= issue or off(d) != off(day):
                    continue
                v = read(d, ts[11:13])
                if np.isfinite(v):
                    vals.append(v)
                if len(vals) == RULE_DAYS:
                    break
            if not vals:
                out = {}
                break
            v = sum(vals) / len(vals)
            out[h] = (max(0.0, v * (1 - RANGE_RULE)), v, v * (1 + RANGE_RULE))
        if out:
            return out, RULE
        for back in range(1, SHAPE_BACK + 1):           # the last whole day with every hour read, whatever kind of day it was
            d = issue - timedelta(days=back)
            shape = {f"{hh:02d}": read(d, f"{hh:02d}") for hh in range(24)}
            if all(np.isfinite(v) for v in shape.values()):
                return {h: (max(0.0, shape[self.replay.ts(h)[11:13]] * (1 - RANGE_SHAPE)), shape[self.replay.ts(h)[11:13]], shape[self.replay.ts(h)[11:13]] * (1 + RANGE_SHAPE)) for h in h0s}, SHAPE
        return {}, ""

    def _known(self, j: int | None, tau: int, col: str, stuck: set[int] | tuple = ()) -> float:
        v = self._val(j, col) if j is not None and 0 <= j < tau and j not in stuck else float("nan")
        floor = getattr(self, "_min_kw", None)
        return float("nan") if col == "base_kw" and floor is not None and np.isfinite(v) and (v <= 0 or v < floor) else v

    # ------------------------------------------------------------------ features, as in training

    def _offset(self, d) -> float:
        """UTC offset of a local time: the dataset's fixed one, or the real one when the dataset crosses the clock changes."""
        if not self.tz_name:
            return self.tz
        from zoneinfo import ZoneInfo
        return d.replace(tzinfo=ZoneInfo(self.tz_name)).utcoffset().total_seconds() / 3600
    def _features(self, h0: int, ctx: dict[str, float]) -> tuple[dict[str, float], dict[str, float], float, float]:
        r = self._row(h0)
        ts = r["ts_local"]
        d = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        doy = d.timetuple().tm_yday
        tmean, tmax, tmin = self._day_temps(h0)
        scale, tau = ctx["scale"], ctx["tau"]
        lags = {k: self._known(self._at(tau, h0, -4 * k), tau, "base_kw", ctx.get("stuck", ())) for k in LAGS}
        base = {"hour": d.hour, "dow": d.weekday(), "weekend": int(d.weekday() >= 5), "holiday": int(d.date() in self.holidays),
                "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                "temp": self._val(h0, "fc_temp_c"), "rh": self._val(h0, "fc_rh_pct"),
                "cloud": self._val(h0, "fc_cloud_pct"), "sw": self._val(h0, "fc_sw_wm2"),
                "wind": self._val(h0, "fc_wind_ms"), "tday_mean": tmean, "tday_max": tmax, "tday_min": tmin}
        load = dict(base)
        for k, v in lags.items():
            load[f"lag{k}"] = v / scale
        n3 = [lags[k] for k in (48, 72, 96) if np.isfinite(lags[k])]
        load["naive3"] = (sum(n3) / len(n3) / scale) if n3 else float("nan")
        load["last24"] = ctx["last24"] / scale
        load["log_scale"] = math.log(max(scale, 1e-6)) if np.isfinite(scale) else float("nan")
        tm48 = self._known(self._at(tau, h0, -192), tau, "temp_c")
        load["temp_meas_lag48"] = tm48
        load["dtemp48"] = load["temp"] - tm48
        load.update(self.static)
        # solar: per kW of panels, relative to clear-sky sunlight at this hour
        utc = d - timedelta(hours=self._offset(d))
        cz = cos_zenith(utc, self.lat, self.lon)
        cs = clear_sky(max(cz, 0.0))
        pv = {"hour": d.hour, "cosz": cz, "sw": base["sw"], "direct": self._val(h0, "fc_direct_wm2"),
              "diffuse": self._val(h0, "fc_diffuse_wm2"), "cloud": base["cloud"], "temp": base["temp"]}
        pv["csi_fc"] = pv["sw"] / max(cs, 1.0) if cs > 20 else float("nan")
        per_kw = {k: self._known(self._at(tau, h0, -4 * k), tau, "pv_kw") / self.pv_kw if self.pv_kw > 0 else float("nan") for k in (48, 72, 96)}
        pv["lag48_csi"] = per_kw[48] / (cs / 1000) if cs > 20 else float("nan")
        p3 = [v for v in per_kw.values() if np.isfinite(v)]
        pv["naive3_csi"] = (sum(p3) / len(p3)) / (cs / 1000) if (cs > 20 and p3) else float("nan")
        return load, pv, cz, cs

    def _pv(self, feats: list, h0s: list[int]) -> dict[int, tuple[float, float, float]]:
        """The solar model's 10/50/90 % in kW for each hour start (0 at night)."""
        pv = {h: (0.0, 0.0, 0.0) for h in h0s}
        day = [k for k, f in enumerate(feats) if f[2] > 0.05 and f[3] > 20 and self.pv_kw > 0]
        if day:
            plo, pmid, phi = self.pv_m.predict([feats[k][1] for k in day])
            for j, k in enumerate(day):
                f = feats[k][3] / 1000 * self.pv_kw
                pv[h0s[k]] = (max(0.0, plo[j] * f), max(0.0, pmid[j] * f), max(0.0, phi[j] * f))
        return pv

    def _pv_correction(self, now_idx: int, days: int = 14) -> dict[int, float]:
        """Per hour of day: what this array made over the last `days` days / what the solar model said for them, each
        day forecast as it would have been (at 10:00 the day before). It corrects what the model cannot know about
        these panels (orientation, shading: it learned on another roof). Only days already over are used; an hour with
        too little sun keeps 1.0; the factor stays within 0.5-1.5."""
        if self.pv_kw <= 0:
            return {}
        day0 = now_idx - (int(self.replay.ts(now_idx)[11:13]) * 4 + int(self.replay.ts(now_idx)[14:16]) // 15)
        key = self.replay.ts(day0)
        if key in self._corr:
            return self._corr[key]
        num: dict[int, float] = {}
        den: dict[int, float] = {}
        h0s, feats = [], []
        for d in range(1, days + 1):
            p0 = day0 - 96 * d                              # 00:00 of a past day, already over
            issue = p0 - 96 + 40                            # 10:00 the day before it
            if issue < 0:
                break
            ctx = self._context(issue)
            if not np.isfinite(ctx["scale"]) or ctx["scale"] <= 0:
                continue
            hs = list(range(p0, p0 + 96, 4))
            h0s += hs
            feats += [self._features(h, ctx) for h in hs]
        pred = self._pv(feats, h0s) if h0s else {}             # all the past days in one pass of the trees
        for h in h0s:
            if pred[h][1] > 0:
                hr = int(self.replay.ts(h)[11:13])
                num[hr] = num.get(hr, 0.0) + self._val(h, "pv_kw")
                den[hr] = den.get(hr, 0.0) + pred[h][1]
        out = {hr: float(min(1.5, max(0.5, num[hr] / den[hr]))) for hr in den if den[hr] > 0.05 * self.pv_kw * days / 7}
        self._corr = {key: out}                             # one day's factors (the next day recomputes)
        return out

    # ------------------------------------------------------------------ the EV in the event window
    def _ev_days(self) -> tuple[dict[str, float], dict[str, float]]:
        """kWh the car(s) drew each day if nobody intervened (full power from arrival until done or departure, as the
        home charges): (15:00-20:00 by day, whole day by day), from the home's own charging sessions."""
        if self._evd is None:
            win: dict[str, float] = {}
            day: dict[str, float] = {}
            for x in self.replay.sessions:
                t, left = x["arrival"], float(x["kwh"])
                while left > 1e-6 and t < x["deadline"]:
                    e = min(float(x["max_kw"]) * 0.25, left)
                    left -= e
                    day[t[:10]] = day.get(t[:10], 0.0) + e
                    if "15:00" <= t[11:16] < "20:00":
                        win[t[:10]] = win.get(t[:10], 0.0) + e
                    t = add_minutes(t, 15)
            self._evd = (win, day)
        return self._evd

    def ev_expected(self, day: str) -> dict[str, float] | None:
        """The EV model for `day`: kWh the car(s) will draw 15:00-20:00 if nobody intervenes (expected value, 10/50/90 %)
        and the chance the car charges then, from what was known at 10:00 the day before (its charging up to two days
        back, the calendar, the day's forecast temperature). None without an EV, the model or 9 days of history."""
        if self.ev_m is None or not self.home.get("has_ev") or not self.replay.sessions:
            return None
        D = date.fromisoformat(day)
        first = self.replay.ts(0)[:10]
        if str(D - timedelta(days=9)) < first:
            return None
        win, dayk = self._ev_days()
        past = [str(D - timedelta(days=k)) for k in range(2, 9)]       # lags 2..8, all over before the offer
        i0 = self.replay.idx_of(f"{day} 00:00")
        temps = [self._val(j, "fc_temp_c") for j in range(i0, i0 + 96, 4)] if i0 is not None else []
        temps = [x for x in temps if np.isfinite(x)]
        row = {"dow": D.weekday(), "weekend": int(D.weekday() >= 5), "holiday": int(D in self.holidays),
               "tday_fc": sum(temps) / len(temps) if temps else float("nan"),
               "win_lag2": win.get(past[0], 0.0), "win_lag7": win.get(str(D - timedelta(days=7)), 0.0),
               "win_mean7": sum(win.get(d, 0.0) for d in past) / 7, "win_share7": sum(win.get(d, 0.0) > 0.1 for d in past) / 7,
               "day_mean7": sum(dayk.get(d, 0.0) for d in past) / 7,
               "charger_kw": max(float(x["max_kw"]) for x in self.replay.sessions), "n_ev": float(self.home.get("n_ev", 1))}
        lo, mid, hi = self.ev_m.predict([row], calibrated=False)
        mean = float(self.ev_m.predict_extra("mean", [row])[0])
        logit = float(self.ev_m.predict_extra("charging_logit", [row])[0])
        return {"mean_kwh": max(0.0, mean), "p10_kwh": max(0.0, float(lo[0])), "p50_kwh": max(0.0, float(mid[0])),
                "p90_kwh": max(0.0, float(hi[0])), "p_charging": 1.0 / (1.0 + math.exp(-logit))}

    def forecast(self, now_idx: int, ts_list: list[str]) -> dict[str, dict[str, tuple[float, float, float]]]:
        ctx = self._context(now_idx)
        hours: dict[int, str] = {}
        for ts in ts_list:
            i = self.replay.idx_of(ts)
            if i is not None:
                hours.setdefault(self._hour_start(i), ts)
        missing = float(ctx.get("missing", 0.0))
        self.last = {"how": None, "missing_share": round(missing, 4), "readings_of_336": ctx.get("n14"), "stuck_hours": len(ctx.get("stuck", ()))}
        if not hours:
            return {}
        h0s = sorted(hours)
        how = MODEL
        if not np.isfinite(ctx["scale"]) or ctx["scale"] <= 0:      # under the code's own bar: a marked stand-in, never an empty forecast
            if np.isfinite(ctx.get("any_scale", float("nan"))) and ctx["any_scale"] > 0:
                ctx, how = {**ctx, "scale": ctx["any_scale"], "last24": ctx["any_last24"]}, NO_VALUE      # the model can run: what is missing goes in as "no value"
            else:
                how = None                              # no reading at all in the last 14 days: the model has nothing to stand on
        feats = [self._features(h, ctx) for h in h0s]
        rows = [f[0] for f in feats]
        if how is not None:
            lo, mid, hi = self.load_m.predict(rows)
            s = ctx["scale"]
            load = {h: (max(0.0, lo[k] * s), max(0.0, mid[k] * s), max(0.0, hi[k] * s)) for k, h in enumerate(h0s)}
            mean = self.load_m.predict_extra("mean", rows) * s if self.load_m.has("mean") else mid * s
            load_mean = {h: max(0.0, float(mean[k])) for k, h in enumerate(h0s)}
            no_weather = {h: not np.isfinite(rows[k]["temp"]) for k, h in enumerate(h0s)}
            self.last["weather_missing_share"] = round(sum(no_weather.values()) / len(h0s), 4)
            for h in h0s:                               # the range widens with what is missing. Nothing missing: the model's own range, to the last digit
                wider = 1 + missing + (STRETCH_24H if not np.isfinite(ctx["last24"]) else 0.0) + (STRETCH_WEATHER if no_weather[h] else 0.0)
                if wider != 1.0:
                    a, b, c = load[h]
                    load[h] = (max(0.0, b - (b - a) * wider), b, b + (c - b) * wider)
        else:
            load, how = self._stand_in(ctx["tau"], h0s, ctx.get("stuck", set()))
            if not load:
                self.last["how"] = "no reading to forecast from"
                return {}
            load_mean = {h: load[h][1] for h in h0s}
        self.last["how"] = how
        pv = self._pv(feats, h0s)
        corr = self._pv_correction(now_idx) if self.correct_pv else {}
        if corr:
            pv = {h: tuple(v * corr.get(int(self.replay.ts(h)[11:13]), 1.0) for v in x) for h, x in pv.items()}
        out = {}
        for ts in ts_list:
            i = self.replay.idx_of(ts)
            if i is not None and self._hour_start(i) in load:
                h = self._hour_start(i)
                out[ts] = {"pv": pv[h], "load": load[h], "load_mean": load_mean[h]}
        return out

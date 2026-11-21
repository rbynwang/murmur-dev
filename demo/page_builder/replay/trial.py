"""The whole picture's two parts beside the tree. The first: what the community agent adds, from ENGIE's trial of 200 homes on
31 sale evenings (the promise against delivery with its switch off and on, its members' batteries and the limit at the
connection, and the power sent out around midday). The second, on an evening with single sites: the evening cut, the money,
and what the tests found. Every figure is read from the trial's and the tests' result files, kept in `facts/`."""
from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import templating as T

FACTS = Path(__file__).resolve().parent.parent / "facts"
R, S = "replay/trial.html#", "replay/story.html#part"
TIERS = (("tier1", "Tier 1"), ("tier2", "Tier 2"), ("tier3", "Tier 3"))


@lru_cache(maxsize=None)
def facts(name: str) -> dict[str, Any]:
    return json.loads((FACTS / f"{name}.json").read_text(encoding="utf-8"))


def n0(x: Any) -> str:
    return f"{float(x):,.0f}"


def pct0(x: Any) -> str:
    return f"{float(x) * 100:.0f}%"


def day(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def path(name: str, cover: dict[str, Any]) -> T.Markup:
    """The cover's path for one tier: the share of the homes' offers the community agent promises upward, evening by evening,
    on one scale from 0 to 100%."""
    pts = cover["path"]
    x0, x1, top, bot = 5.0, 143.0, 5.0, 51.0
    X = lambda i: x0 + (x1 - x0) * i / max(1, len(pts) - 1)  # noqa: E731
    Y = lambda v: bot - (bot - top) * float(v)  # noqa: E731
    step = (x1 - x0) / max(1, len(pts) - 1)
    line = " ".join(f'{"M" if not i else "L"}{X(i):.1f} {Y(q["share"]):.1f}' for i, q in enumerate(pts))
    tips = T.join(T.render(R + "tip", x=f"{X(i) - step / 2:.1f}", w=f"{step:.1f}", date=f"{day(q['evening']).day} {day(q['evening']):%b}",
                           share=pct0(q["share"]), source=q["from"]) for i, q in enumerate(pts))
    return T.render(R + "path", name=name, first=pct0(cover["first"]), last=pct0(cover["last"]), n=len(pts), line=line,
                    cx=f"{X(len(pts) - 1):.1f}", cy=f"{Y(pts[-1]['share']):.1f}", tips=tips)


def bars(title: str, items: list[tuple[str, float, str, str]], full: float | None = None, note: str = "") -> T.Markup:
    """One comparison: a bar per state on one scale, its value at the tip."""
    top = full or max(v for _, v, _, _ in items)
    rows = T.join(T.render(R + "bar", label=lab, state=cl, share=f"{v / top:.4f}", value=n0(v), unit=unit) for lab, v, unit, cl in items)
    return T.render(R + "bars", title=title, rows=rows, note=T.render(R + "note", text=note) if note else T.Markup(""))


def promise(f: dict[str, Any]) -> T.Markup:
    tiers = f["tiers"]
    n = tiers["tier1"]["evenings"]
    rows = [("Sold, or promised, kW", lambda c: n0(c["sold_kw"]), lambda o: n0(o["promised_kw"])),
            ("Delivered, by the buyer's meter, kW", lambda c: n0(c["delivered_metered_kw"]), lambda o: n0(o["delivered_metered_kw"])),
            ("Delivered, by the truth, kW", lambda c: n0(c["delivered_true_kw"]), lambda o: n0(o["delivered_true_kw"])),
            (f"Evenings it held, by the buyer's meter, of {n}", lambda c: str(c["evenings_the_meter_covered_what_was_sold"]), lambda o: str(o["held_by_the_meter"])),
            (f"Evenings it held, by the truth, of {n}", lambda c: str(c["evenings_delivery_covered_what_was_sold"]), lambda o: str(o["held"])),
            ("Average miss, by the truth, kW", lambda c: n0(c["mean_miss_kw"]), lambda o: n0(o["mean_miss_kw"]))]
    body = T.join(T.render(R + "row", label=lab, cells=T.join(T.render(R + "cells", off=off(tiers[t]["switch_off"]), on=on(tiers[t])) for t, _ in TIERS))
                  for lab, off, on in rows)
    return T.render(R + "promise", src=f["files"][0], n=n, tiers=T.join(T.render(R + "tier", name=name) for _, name in TIERS),
                    switch=T.join(T.render(R + "switch") for _ in TIERS), offered=T.join(T.render(R + "offered", kw=n0(tiers[t]["offered_kw"])) for t, _ in TIERS),
                    rows=body, paths=T.join(path(name, tiers[t]["cover"]) for t, name in TIERS))


def batteries(f: dict[str, Any]) -> T.Markup:
    rule, tiers = f["rule"], f["tiers"]
    peaks = {t: tiers[t]["import_peak_of_day_kw"] for t, _ in TIERS}
    shaped = {round(float(p["with_homes_battery_shaped"])) for p in peaks.values()}
    peak_note = f'With tier 3 homes the shaped figure is {n0(peaks["tier3"]["with_homes_battery_shaped"])} kW.' if len(shaped) > 1 else ""
    sent = rule["most_sent_out_kw"]
    return T.render(R + "batteries", src=f["files"][1], n=rule["evenings"], bars=T.join([
        bars(f'The batteries give, {rule["window"]["start"]} to {rule["window"]["end"]}',
             [("As recorded", rule["battery_in_window_as_recorded_kw"], "kW", "off"), ("Held for the window", rule["battery_given_in_window_kw"], "kW", "on")]),
        bars("The day's highest quarter-hour, drawn from the grid",
             [("As recorded", peaks["tier1"]["recorded"], "kW", "off"), ("Battery held for the window", peaks["tier1"]["battery_held"], "kW", "on"),
              ("Shaped around the peak, tier 1 homes", peaks["tier1"]["with_homes_battery_shaped"], "kW", "on")], note=peak_note),
        bars(f'Most sent out at once, against the limit of {n0(rule["limit_kw"])} kW', [("As recorded", sent["recorded"], "kW", "off"), ("With the plan", sent["plan"], "kW", "on")],
             full=rule["limit_kw"], note="The limit comes from ENGIE's files. The plan stays inside it." if rule["limit_kept"] else "The limit comes from ENGIE's files.")]))


def midday(f: dict[str, Any]) -> T.Markup:
    m = f["midday"]
    out, high, none = m["sent_out_kwh_a_day"], m["highest_sent_out_kw"], m["days_with_nothing_sent_out"]
    return T.render(R + "midday", src=f["files"][2], days=m["days"], start=f"{day(m['from']).day} {day(m['from']):%B}",
                    end=f"{day(m['to']).day} {day(m['to']):%B %Y}", bars=T.join([
                        bars("Sent out in a day", [("As recorded", out["as_recorded"], "kWh", "off"), ("With the rule", out["with_the_rule"], "kWh", "on")]),
                        bars("Most sent out at once, on an average day", [("As recorded", high["as_recorded"]["mean_of_days"], "kW", "off"),
                                                                           ("With the rule", high["with_the_rule"]["mean_of_days"], "kW", "on")]),
                        bars("Most sent out at once, on any day", [("As recorded", high["as_recorded"]["highest"], "kW", "off"),
                                                                    ("With the rule", high["with_the_rule"]["highest"], "kW", "on")],
                             note=f'Days with nothing sent out: {none["as_recorded"]} as recorded, {none["with_the_rule"]} with the rule.')]))


def months(f: dict[str, Any]) -> str:
    """The months the trial's evenings fall in: "January and February 2025"."""
    path_ = f["tiers"]["tier1"]["cover"]["path"]
    d0, d1 = day(path_[0]["evening"]), day(path_[-1]["evening"])
    return f"{d0:%B} and {d1:%B %Y}" if d0.month != d1.month else f"{d1:%B %Y}"


def community_part() -> T.Markup:
    """What the community agent adds, from ENGIE's trial: one screen, three cards side by side."""
    f = facts("trial")
    was = [str(f["tiers"][t]["kept_by_the_meter_before_recount"]) for t, _ in TIERS]
    return T.render(R + "part", n=f["tiers"]["tier1"]["evenings"], months=months(f), window=f'{f["window"]["start"]} to {f["window"]["end"]}',
                    promise=promise(f), batteries=batteries(f), midday=midday(f), was=f"{was[0]}, {was[1]} and {was[2]}", files=", ".join(f["files"]))


def cut_part() -> T.Markup:
    """The evening cut, the money, and what the tests found, from the tests' own result files."""
    t = facts("tests")
    h, ra = t["strained_hours"], t["request_agent"]
    home_year = t["home_flexibility_usd_an_evening"] * 45           # a Massachusetts programme's season: about 45 three-hour evenings
    return T.render(S, as_recorded=h["as_recorded"], shared_out=h["shared_out"], home_year=f"${home_year:,.0f}",
                    home_year_low=f"${home_year * .75 / 2.04:,.0f}", sites=t["sites_equal_to_the_replay"], cut_only=h["cut_only"],
                    without_plants=h["cut_only_without_plants"], hold_without=h["one_in_20_holds_without_the_round"],
                    hold_with=h["one_in_20_holds_with_the_round"], overstated=h["everyone_overstates_nobody_checks"], kept=ra["kept_as_written"],
                    requests=ra["requests"], read_right=ra["read_exactly_right"], notes=ra["notes"],
                    miss_with=f'{abs(t["true_shortfall_pct"]["with"]):.1f}%', miss_without=f'{abs(t["true_shortfall_pct"]["without"]):.1f}%',
                    pause_mw=f'{t["data_centers_postponable_mw"]:.0f}', paused=h["data_centers_pause_all"])

"""The figures the architecture-and-data page quotes, read from the two data files beside this module.

  data/facts.json   ENGIE's asset ratings (participants by kind, and the ratings of the community that hosts our homes and
                    buildings) and the recorded evening the page steps through (the moments of its replay page as that page
                    shows them, the run's own result, the message count of the year set); each block says where its figures
                    come from
  data/survey.json  the product survey: for homes and for buildings, the number of brands, how many products are dated 2025
                    or later, and each kind of equipment with its number of products and how an agent reaches it

Some of the page's words state a figure in words ("Ten members offer", "all 80 batteries", "no signature failed"); `load()`
stops when the data say otherwise, so the words cannot drift from the figures beside them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
WINDOW_TOLERANCE_KW = 0.6  # the replay's headline for 18:00 is rounded to whole kW, so it may miss the exact figure by this much


@dataclass(frozen=True)
class Equipment:
    """One kind of equipment in the survey."""
    name: str
    reach: str  # "commanded" (the agent commands it), "through" (through another device or the building's system), "watched"
    products: int


@dataclass(frozen=True)
class Group:
    name: str
    kinds: tuple[Equipment, ...]


@dataclass(frozen=True)
class Side:
    """The survey of one side: the equipment met in a home, or in a building."""
    brands: int
    dated_2025_or_later: int
    groups: tuple[Group, ...]

    @property
    def products(self) -> int:
        return sum(k.products for g in self.groups for k in g.kinds)

    @property
    def kinds(self) -> int:
        return sum(len(g.kinds) for g in self.groups)


@dataclass(frozen=True)
class Moment:
    """A moment of the recorded evening's replay: its place in the replay and the headline the replay shows for it."""
    number: int
    headline: str


@dataclass(frozen=True)
class Figures:
    participants: int
    solar_and_battery_plants: int
    data_centers: int
    communities: int
    host_solar_kw: float
    host_connection_limit_kw: float
    host_home_batteries_kw: float
    host_home_batteries_kwh: float
    home: Side
    building: Side
    brands: int  # in homes and buildings together: a brand found on both sides counts once
    moments_in_the_replay: int
    moments: dict[str, Moment]
    needed_at_19_mw: float
    all_batteries_can_give_mw: float
    settled_kwh: int
    less_at_18_kw: dict[str, float]
    messages: int
    site_rows: int
    site_rows_as_planned: int
    promised_kw: float
    delivered_kw: float
    year_set_messages: int

    @property
    def products(self) -> int:
        return self.home.products + self.building.products

    @property
    def kinds(self) -> int:
        return self.home.kinds + self.building.kinds


def _side(raw: dict) -> Side:
    groups = tuple(Group(g["group"], tuple(Equipment(k["kind"], k["reach"], k["products"]) for k in g["kinds"]))
                   for g in raw["groups"])
    return Side(raw["brands"], raw["dated_2025_or_later"], groups)


def _check(f: Figures, evening: dict) -> None:
    """Stops the build when a figure the page writes out in words ("ten", "all 80", "none") is not what the data hold."""
    window_kw = float(f.moments["window"].headline.split()[0])
    wrong = [what for ok, what in (
        (evening["ended"] == "settled", "the evening did not end settled, but the page says the buyers paid"),
        (evening["bad_signatures"] == 0, "a signature failed, but the page says none did"),
        (f.site_rows_as_planned == f.site_rows, "a single site's report row differs from the plan, but the page says each is as expected"),
        (f.moments["call"].headline == "10", "the community did not call ten members, but the page says ten offer"),
        (f.participants == 80, "ENGIE's dataset does not hold 80 participants, but the page says all 80"),
        (abs(window_kw - f.less_at_18_kw["all"]) < WINDOW_TOLERANCE_KW, "the replay's 18:00 headline is not the evening's 18:00 cut"),
    ) if not ok]
    if wrong:
        raise ValueError("overview figures: " + "; ".join(wrong))


def load() -> Figures:
    """The page's figures from the data files, checked against the words that state them."""
    facts = json.loads((DATA / "facts.json").read_text(encoding="utf-8"))
    survey = json.loads((DATA / "survey.json").read_text(encoding="utf-8"))
    engie, evening = facts["engie"], facts["evening"]
    f = Figures(
        participants=engie["participants"], solar_and_battery_plants=engie["solar_and_battery_plants"],
        data_centers=engie["data_centers"], communities=engie["communities"], host_solar_kw=engie["host_solar_kw"],
        host_connection_limit_kw=engie["host_connection_limit_kw"], host_home_batteries_kw=engie["host_home_batteries_kw"],
        host_home_batteries_kwh=engie["host_home_batteries_kwh"],
        home=_side(survey["home"]), building=_side(survey["building"]), brands=survey["brands_in_homes_and_buildings"],
        moments_in_the_replay=evening["moments_in_the_replay"],
        moments={mid: Moment(m["number"], m["headline"]) for mid, m in evening["moments"].items()},
        needed_at_19_mw=evening["needed_at_19_mw"], all_batteries_can_give_mw=evening["all_batteries_can_give_mw"],
        settled_kwh=evening["settled_kwh"], less_at_18_kw=evening["less_at_18_kw"], messages=evening["messages"],
        site_rows=evening["site_rows"], site_rows_as_planned=evening["site_rows_as_planned"],
        promised_kw=evening["promised_kw"], delivered_kw=evening["delivered_kw"], year_set_messages=evening["year_set_messages"])
    _check(f, evening)
    return f

"""The tiles, cards and tables of the year's results page, filled from `figures` into the snippets of
`templates/year_results/parts.html`.

Row and column words are plain text and are escaped into the page. The weather versions' short names under the pairs
of columns are fixed wording of the parts (`version_columns`), except in the weather table, whose column words are
escaped like its row words: both read the same, and the page keeps the bytes it is published with.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ..templating import Markup, join, render
from . import figures as fg
from .words import (LINE, RULE, TIER_WORDS, VERSION_SHORT, VERSION_WORDS, day, failed, n0, n1, pct0, pct1, ratio2,
                    short_or_over, signed_pct1, usd0, usd2)

PARTS = "year_results/parts.html"
BUILDINGS = (("building-01", "The shops"), ("building-02", "The small office"))
CANDIDATES = {"the rule": "The rule, as today", "the rule, corrected": "The rule times one fitted factor",
              "yesterday": "Yesterday evening", "fitted line": "Fitted line"}
SEASON_CANDIDATES = (RULE, LINE)
Shown = Callable[[fg.Figures], str]


def part(name: str, **values: Any) -> Markup:
    """One snippet of the page's parts, filled."""
    return render(f"{PARTS}#{name}", **values)


def table(kind: str, head: Markup, rows: Iterable[Markup]) -> Markup:
    """A table of one kind (its class) with its header rows and body rows."""
    return part("table", kind=kind, head=head, rows=join(rows))


def head_rows(groups: Iterable[str], columns: Markup) -> Markup:
    """The two header rows of a table whose columns come in pairs: the pairs' names, then each column's."""
    return part("head_rows", groups=join(part("group", label=g) for g in groups), columns=columns)


def columns(labels: Iterable[str]) -> Markup:
    """Column headers, one for each word."""
    return join(part("column", label=label) for label in labels)


def version_columns(pairs: int) -> Markup:
    """The weather versions' short names under each pair of columns."""
    return join(part("version_columns") for _ in range(pairs))


def row(label: str, cells: Iterable[str]) -> Markup:
    """A body row: its label, then its cells."""
    return part("row", label=label, cells=join(part("cell", value=c) for c in cells))


def tiles() -> Markup:
    """The four tiles at the top: runs counted, shortfall, evenings met and pay, at tier 1 on ENGIE's weather."""
    a, b = fg.run(fg.ENGIE, 1, "with"), fg.run(fg.ENGIE, 1, "without")
    return part("tiles", runs=fg.evening_runs(), evenings=fg.evenings(), failed=failed(fg.failed_runs()),
                miss_with=pct1(-a["mean_miss_by_the_truth_pct"]), miss_without=pct1(-b["mean_miss_by_the_truth_pct"]),
                kept_with=a["evenings_kept_by_the_truth"], kept_without=b["evenings_kept_by_the_truth"],
                paid_with=usd0(a["members_get_usd"]), paid_without=usd0(b["members_get_usd"]))


def agent_rows(evenings: int, half_hours: int) -> tuple[tuple[str, Shown], ...]:
    """The rows of a tier's card: each row's words and how a run's figure is shown."""
    return (("Promised, kW", lambda r: n0(r["promised_kw"])),
            ("Truly delivered, kW", lambda r: n0(r["delivered_by_the_truth_kw"])),
            ("Delivered by the buyers' meter, kW", lambda r: n0(r["delivered_by_the_meter_kw"])),
            (f"Evenings the promise was truly met, of {evenings}", lambda r: str(r["evenings_kept_by_the_truth"])),
            (f"Evenings met by the buyers' meter, of {evenings}", lambda r: str(r["evenings_kept_by_the_meter"])),
            (f"Half hours truly short, of {half_hours}", lambda r: str(r["half_hours_short_by_the_truth"])),
            ("Average true shortfall", lambda r: pct1(-r["mean_miss_by_the_truth_pct"])),
            ("Worst evening, truly short by", lambda r: pct1(-r["worst_evening_by_the_truth_pct"])),
            ("Buyers pay, an evening", lambda r: usd0(r["buyers_pay_usd"])),
            ("Members are paid, an evening", lambda r: usd0(r["members_get_usd"])))


def agent_card(tier: int, top: float) -> Markup:
    """One tier with the community agent and without it: the true shortfall on ENGIE's weather as bars, measured
    against the largest shortfall of every run (`top`), then both weather versions in a table."""
    miss = {m: -fg.run(fg.ENGIE, tier, m)["mean_miss_by_the_truth_pct"] for m in fg.MODES}
    bars = join(part("bar", mode=m, label=m.capitalize(), width=f"{100 * miss[m] / top:.1f}", value=pct1(miss[m]))
                for m in fg.MODES)
    rows = (part("row", label=label, cells=join(part("mode_cell", mode=m, value=shown(fg.run(v, tier, m)))
                                                for v in fg.VERSIONS for m in fg.MODES))
            for label, shown in agent_rows(fg.evenings(), fg.run(fg.ENGIE, tier, "with")["half_hours"]))
    head = head_rows((VERSION_WORDS[v] for v in fg.VERSIONS), columns(fg.MODES * len(fg.VERSIONS)))
    return part("agent_card", tier=tier, words=TIER_WORDS[tier], bars=bars, table=table("t4", head, rows))


def agent_cards() -> Markup:
    """The three tiers' cards."""
    top = max(-r["mean_miss_by_the_truth_pct"] for r in fg.runs())
    return join(agent_card(t, top) for t in fg.TIERS)


def weather_table() -> Markup:
    """The two weather versions side by side, by tier, with the community agent."""
    shown: tuple[tuple[str, str, Callable[[Any], str]], ...] = (
        ("Offered, kW", "offered_kw", n0),
        ("Promised, kW", "promised_kw", n0),
        (f"Evenings short of the promise by the buyers' meter, of {fg.evenings()}", "evenings_short_of_the_promise",
         str),
        ("Worst evening against the promise, by the buyers' meter", "worst_evening_gap_share",
         lambda x: short_or_over(100 * x)),
        ("The buyers' baseline is off by", "baseline_error_share", lambda x: pct1(100 * x)),
        ("Homes: delivered for each kWh contracted", "homes_delivered_over_contract", ratio2),
        ("Buildings: delivered for each kWh contracted", "buildings_delivered_over_contract", ratio2))
    head = head_rows((f"Tier {t}" for t in fg.TIERS), columns(VERSION_SHORT[v] for t in fg.TIERS for v in fg.VERSIONS))
    rows = (row(label, (f(fg.both_versions(v, t)[key]) for t in fg.TIERS for v in fg.VERSIONS))
            for label, key, f in shown)
    return table("t6", head, rows)


def season_table() -> Markup:
    """Tier 1 by season on both weather versions."""
    groups = ("Promised, kW", f"Evenings short, of {fg.per_season()}", "Baseline off by")
    shown: tuple[tuple[str, Callable[[Any], str]], ...] = (
        ("promised_kw", n0), ("evenings_short_of_the_promise", str), ("baseline_error_share", lambda x: pct1(100 * x)))
    rows = (row(s.capitalize(), (f(fg.tier1_season(v, s)[key]) for key, f in shown for v in fg.VERSIONS))
            for s in fg.tier1_seasons())
    return table("t6", head_rows(groups, version_columns(len(groups))), rows)


def pay_table() -> Markup:
    """What buyers pay and members are paid, an evening, by tier and weather version."""
    shown: list[tuple[str, Shown]] = [
        ("Buyers pay", lambda x: usd0(x["buyers_pay"])),
        ("Members get", lambda x: usd0(x["members_get"])),
        ("Members' share of what buyers pay", lambda x: pct0(x["share"])),
        ("A home, on average", lambda x: usd2(x["home_avg"])),
        ("The lowest home", lambda x: usd2(x["home_min"])),
        ("The highest home", lambda x: usd2(x["home_max"])),
        (f"Homes paid, of {fg.homes()}", lambda x: str(x["homes_paid"]))]
    shown += [(label, lambda x, b=b: usd2(x["buildings"][b])) for b, label in BUILDINGS]
    head = head_rows((f"Tier {t}" for t in fg.TIERS), version_columns(len(fg.TIERS)))
    rows = (row(label, (f(fg.pay(v, t)) for t in fg.TIERS for v in fg.VERSIONS)) for label, f in shown)
    return table("t6", head, rows)


def town_card(version: str) -> Markup:
    """The monthly evenings of one weather version, one row each."""
    rows = (part("town_row", day=day(e["evening"]), promised=n1(e["promised_kw"]),
                 truth=n1(e["delivered_by_the_truth_kw"]), meter=n1(e["delivered_by_the_meter_kw"]),
                 short=e["half_hours_short_by_the_truth"], half_hours=e["half_hours"], share=pct0(e["cover_share"]),
                 share_from="its record" if e["cover_by"] == "the record" else "fixed")
            for e in fg.monthly(version))
    return part("card", title=VERSION_WORDS[version], table=table("tm", part("town_head"), rows))


def town_totals() -> Markup:
    """The monthly evenings of both weather versions taken together."""
    n = fg.monthly_count()
    shown: tuple[tuple[str, Shown], ...] = (
        ("Promised, kW", lambda s: n1(s["promised_kw"])),
        ("Delivered by the truth, kW", lambda s: n1(s["delivered_by_the_truth_kw"])),
        ("Delivered by the buyers' meter, kW", lambda s: n1(s["delivered_by_the_meter_kw"])),
        ("The meter reads over the truth by, kW",
         lambda s: n1(s["delivered_by_the_meter_kw"] - s["delivered_by_the_truth_kw"])),
        (f"Evenings the truth met the promise, of {n}", lambda s: str(s["evenings_kept_by_the_truth"])),
        ("Half hours short by the truth", lambda s: f"{s['half_hours_short_by_the_truth']} of {s['half_hours']}"),
        ("Half hours short by the buyers' meter",
         lambda s: f"{s['half_hours_short_by_the_meter']} of {s['half_hours']}"),
        ("Lowest share of the offers promised", lambda s: pct0(s["lowest_cover_share"])),
        ("Signed messages over NANDA Town", lambda s: n0(s["messages_accepted"])),
        ("Signatures that failed", lambda s: str(s["bad_signatures"])),
        ("Messages refused", lambda s: str(s["refused"])),
        (f"Evenings settled, of {n}", lambda s: str(s["evenings_settled"])))
    totals = {v: fg.monthly_totals(v) for v in fg.VERSIONS}
    head = part("head_row", columns=columns(VERSION_WORDS[v] for v in fg.VERSIONS))
    rows = (row(label, (f(totals[v]) for v in fg.VERSIONS)) for label, f in shown)
    return part("card", title=f"Over the {n} evenings", table=table("t2", head, rows))


def town_cards() -> Markup:
    """The monthly evenings: one card for each weather version, then both taken together."""
    return join([*(town_card(v) for v in fg.VERSIONS), town_totals()])


def baseline_table() -> Markup:
    """The candidate baselines on both weather versions."""
    shown: tuple[tuple[str, Shown], ...] = (
        ("Mean error", lambda c: pct1(c["mean_error_pct"])),
        ("Leans high or low by", lambda c: signed_pct1(c["bias_pct"])),
        ("Evenings within 5%", lambda c: str(c["evenings_within_5_pct"])),
        ("Evenings off by more than 15%", lambda c: str(c["evenings_off_by_more_than_15_pct"])))
    head = head_rows((label for label, _ in shown), version_columns(len(shown)))
    rows = (row(CANDIDATES[k], (f(fg.baseline(v)["candidates"][k]) for _, f in shown for v in fg.VERSIONS))
            for k in fg.baseline(fg.ENGIE)["candidates"])
    return table("t6", head, rows)


def baseline_season_table() -> Markup:
    """The mean error of the rule and of the fitted line by season, on both weather versions."""
    head = head_rows((CANDIDATES[k] for k in SEASON_CANDIDATES), version_columns(len(SEASON_CANDIDATES)))
    rows = (row(s.capitalize(), (pct1(fg.baseline(v)["by_season_mean_error_pct"][s][k])
                                 for k in SEASON_CANDIDATES for v in fg.VERSIONS))
            for s in fg.baseline_seasons())
    return table("t6", head, rows)

"""The numbers and sentences of the year's results page, written in their final form.

Numbers are formatted here. The sentences that carry figures are plain text, escaped when they are placed into the
page; the fixed wording of the page sits in `templates/year_results/`.
"""
from __future__ import annotations

import datetime as dt

from . import figures as fg

TIER_WORDS = {1: "the full device mix", 2: "water heaters", 3: "no added devices"}
VERSION_WORDS = {fg.ENGIE: "ENGIE's weather", fg.REAL: "Real day-to-day weather"}
VERSION_SHORT = {fg.ENGIE: "ENGIE's", fg.REAL: "real"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
RULE, LINE = "the rule", "fitted line"


def n0(x: float) -> str:
    """A number to the unit, with thousands separated."""
    return f"{x:,.0f}"


def n1(x: float) -> str:
    """A number to one decimal, with thousands separated."""
    return f"{x:,.1f}"


def usd0(x: float) -> str:
    """Dollars to the dollar."""
    return f"${x:,.0f}"


def usd2(x: float) -> str:
    """Dollars to the cent."""
    return f"${x:,.2f}"


def pct1(x: float) -> str:
    """A percentage to one decimal."""
    return f"{x:.1f}%"


def pct0(share: float) -> str:
    """A share as a whole percentage."""
    return f"{100 * share:.0f}%"


def signed_pct1(x: float) -> str:
    """A percentage to one decimal with its sign."""
    return f"{x:+.1f}%"


def ratio2(x: float) -> str:
    """A ratio to two decimals."""
    return f"{x:.2f}"


def short_or_over(percent: float) -> str:
    """How far an evening fell short of the promise or went over it."""
    return f"{abs(percent):.1f}% short" if percent < 0 else f"{percent:.1f}% over"


def day(evening: str) -> str:
    """An evening's date as the page writes it, such as "24 Jan"."""
    d = dt.date.fromisoformat(evening)
    return f"{d.day} {MONTHS[d.month - 1]}"


def failed(count: int) -> str:
    """How many runs failed, for the first tile."""
    return f"{count} failed" if count else "None failed"


def agent_find() -> str:
    """What the community agent changes, at tier 1 on ENGIE's weather."""
    n, a, b = fg.evenings(), fg.run(fg.ENGIE, 1, "with"), fg.run(fg.ENGIE, 1, "without")
    ratio = b["mean_miss_by_the_truth_pct"] / a["mean_miss_by_the_truth_pct"]
    return ("The community agent does not change what is delivered or what members are paid. It changes the promise. "
            "Without it the community promises everything its members offer "
            f"and truly falls short on {n - b['evenings_kept_by_the_truth']} of {n} evenings at tier 1. "
            f"With it the true shortfall is {pct1(-a['mean_miss_by_the_truth_pct'])} in place of "
            f"{pct1(-b['mean_miss_by_the_truth_pct'])}, about {ratio:.0f} times smaller.")


def weather_find() -> str:
    """What real weather changes, at tier 1."""
    e, r = fg.both_versions(fg.ENGIE, 1), fg.both_versions(fg.REAL, 1)
    return ("Real weather changes the measurement, not the sale. "
            f"At tier 1 the promise is {n0(e['promised_kw'])} kW on ENGIE's weather "
            f"and {n0(r['promised_kw'])} kW on real weather, "
            f"while the buyers' baseline is off by {pct1(100 * e['baseline_error_share'])} "
            f"and {pct1(100 * r['baseline_error_share'])}.")


def town_find() -> str:
    """The monthly evenings: the worst one on ENGIE's weather, and how the community agent's record answered it."""
    rows = fg.monthly(fg.ENGIE)
    worst = min(range(len(rows)), key=lambda i: rows[i]["delivered_by_the_truth_kw"] - rows[i]["promised_kw"])
    w, after = rows[worst], rows[worst + 1:]
    if not after:
        raise ValueError("the worst monthly evening is the last one: no evening follows it to tell of")
    return ("These ran with real signed messages: eight homes, a small office and shops, their community agent "
            "and the aggregator's agent. kW are averages over the evening. "
            f"On ENGIE's weather the worst evening was {day(w['evening'])}, "
            f"{n0(w['promised_kw'] - w['delivered_by_the_truth_kw'])} kW short by the truth. "
            "After it the community agent's own record lowered its promise to "
            f"{pct0(min(e['cover_share'] for e in after))} of the offers, "
            f"and the {len(after)} evenings that followed were short in "
            f"{sum(e['half_hours_short_by_the_truth'] for e in after)} half hours.")


def baseline_find() -> str:
    """What a fitted baseline line does to the mean error, on both weather versions."""
    e, r = fg.baseline(fg.ENGIE)["candidates"], fg.baseline(fg.REAL)["candidates"]
    return ("The baseline is the buyers' estimate of what the community would have drawn with no sale. "
            "Delivery, pay and whether a promise was kept all rest on it, and today it is a rule. "
            f"A line fitted on what is known before 18:00 cuts the mean error from {pct1(e[RULE]['mean_error_pct'])} "
            f"to {pct1(e[LINE]['mean_error_pct'])} on ENGIE's weather "
            f"and from {pct1(r[RULE]['mean_error_pct'])} to {pct1(r[LINE]['mean_error_pct'])} on real weather. "
            "Every candidate is judged only on evenings it was not fitted on, one month left out at a time.")


def baseline_limit() -> str:
    """How far the baseline's first look goes."""
    return ("This is a first look, not a trained product. "
            f"{fg.baseline(fg.ENGIE)['evenings']} evenings a version is little, only one form of model was tried, "
            "it was tried for the whole community at tier 1 only, and nothing in the buyers' code was changed.")

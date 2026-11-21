"""The year's results page: the chosen evenings of ENGIE's 2025 at three tiers on two versions of the weather, with the
community agent and without it; what members are paid; one evening a month over NANDA Town; and a first look at a
better baseline. A standalone page in the split view's colours and type.

`page()` returns the whole page. Every number on it is read from the runs' own result files, kept in `data/` and read
by `figures`; `words` formats the numbers and writes the sentences that carry them; `tables` fills the tiles, cards and
tables. The page's structure and fixed wording are `templates/year_results/page.html` (it ends with an empty line, as
the page ends with a newline) and `templates/year_results/parts.html`; the style sheet is
`static/year_results/year_results.css`.
"""
from __future__ import annotations

from ..templating import render, static
from . import figures, tables, words


def page() -> str:
    """The year's results page, one standalone HTML document."""
    return str(render(
        "year_results/page.html",
        css=static("year_results/year_results.css"),
        evenings=figures.evenings(), per_season=figures.per_season(), homes=figures.homes(),
        tier1=words.TIER_WORDS[1], tier2=words.TIER_WORDS[2], tier3=words.TIER_WORDS[3],
        tiles=tables.tiles(),
        agent_find=words.agent_find(), agent_cards=tables.agent_cards(),
        weather_find=words.weather_find(), weather_table=tables.weather_table(), season_table=tables.season_table(),
        pay_table=tables.pay_table(),
        town_find=words.town_find(), town_cards=tables.town_cards(),
        baseline_find=words.baseline_find(), baseline_table=tables.baseline_table(),
        baseline_season_table=tables.baseline_season_table(), baseline_limit=words.baseline_limit(),
    ))

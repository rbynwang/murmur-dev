"""The replay pages' style sheet and scripts: static files under static/replay/, joined for each kind of replay page.

The kinds:
  "two_view"    one evening in the split view and the Data view (it carries the live mode)
  "three_view"  one evening in the split view, the whole picture and the Full record
  "year"        the same three views over a year's evenings, with their results

css(kind) is the text of the page's one <style> element, and each item of scripts(kind) the text of one <script> element, in
page order. Each text begins with the newline that follows its start tag, so the page writes it between the start tag and
the end tag with nothing added. The files are joined as they are. parts.css and sites.css end without a newline: on the
single-evening pages the single sites' rules carry on the parts' line, and the file after them begins with the newline that
ends it.

The style sheet (static/replay/css/), in page order:
  page        the page's own layout: the switcher, the map, the right column, the terminals, the bar, the results view
  whole       the whole picture: the overview, the world to zoom into, the mini map
  levels      the three levels on the map: the market and the utility, the community agent, home and building agents
  community   what the community agent adds, from the ENGIE trial: the whole picture's own part
  screens     phones, lower and narrower screens
  opening     an ENGIE evening's opening card
  parts       the top band with the aggregator's parts, the community agent's band of six boxes; the notes under the terminal hidden
  sites       the single sites (single-evening pages)
  sections    the map in three sections, with NANDA Town's band through all of them
  year        a year's page: the row of evenings takes height the map gives back
  data_view   the Data view (two-view pages)
  fit         nothing in a box is cut: the map's measured state (data-fit 0 to 6, data-fitw 0 to 3, data-fitb)
  fit_year    a year's page before the measure has run
  live        Live (two-view pages): the bar, the surprises drawer, the timeline and the parts' dots
  live_public Live for an audience: the LIVE mark and the day, the strip of six events, the banner, the card for a phone

The main script (static/replay/js/main_*.js) is one async function, cut into files at its section comments: the files are
pieces of that one script, not scripts of their own, and only their join in this order is a program.
  main_state   the opening of the function: the packed days, the page's state, small helpers
  main_links   drawing the connectors between blocks
  main_fit     the measured fit of the map (fitBranches and the states it sets) and measure(), which draws a view's links
  main_lines   the views, painting the blocks, and the terminal's lines and fixed texts
  main_moment  the moment in fixed places: the card, the bar, the terminal, the message's travel, the split view's play
  main_whole   the whole picture: the tree, its zoom, the mini map, the pointer
  main_steps   moving through a story: steps, tabs, the Full record, reading a block
  main_input   clicks, keys, the theme, the speed, the window's resizing (the fit is measured again when the map's room changes)
  main_grow    a live story: the split view playing what Live adds to it, moment by moment (FG.grow)
  main_start   the scenarios (one page plays any of its days), the start, and the end of the function
After it, in the same element: the single sites' mode (sites_mode, single-evening pages) and the Data view (data_view,
two-view pages). The two-view page's last element is Live, with the id LIVE_ID: one function cut into files at its section
comments as the main script is (live_open opens it and live_ask ends it). It runs when the page's address carries
?live=<base address>, or when the page is given out at the "/" of a server that answers with a live state (a console); then the
split view plays the running network's moments as the state at that address sends them, with the bar, the timeline, a
presenter's controls and surprises drawer, the audience's strip of events (live_crowd) and the card for a phone (live_qr).

DATA_VIEW_OPEN is the text of the one more <script> element that the Data view page writes just before its data elements:
an address that names no view opens the Data view.
"""
from __future__ import annotations

from .templating import Markup, static

KINDS = ("two_view", "three_view", "year")
LIVE_ID = "lv-js"

_SHEET = ("page", "whole", "levels", "community", "screens", "opening", "parts")
_CSS = {
    "two_view": _SHEET + ("sites", "sections", "data_view", "fit", "live", "live_public"),
    "three_view": _SHEET + ("sites", "sections", "fit"),
    "year": _SHEET + ("sections", "year", "fit", "fit_year"),
}
_MAIN = ("main_state", "main_links", "main_fit", "main_lines", "main_moment", "main_whole", "main_steps", "main_input",
         "main_grow", "main_start")
_LIVE = ("live_open", "live_read", "live_adopt", "live_story", "live_timeline", "live_bar", "live_crowd", "live_qr", "live_drawer", "live_console",
         "live_ask")
_SCRIPTS = {
    "two_view": (_MAIN + ("sites_mode", "data_view"), _LIVE),
    "three_view": (_MAIN + ("sites_mode",),),
    "year": (_MAIN,),
}


def _known(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"no replay page of kind {kind!r}; the kinds are {', '.join(KINDS)}")
    return kind


def css(kind: str) -> Markup:
    """The text of the page's <style> element."""
    return static(*(f"replay/css/{name}.css" for name in _CSS[_known(kind)]))


def scripts(kind: str) -> list[Markup]:
    """The text of each <script> element that runs, in page order; for "two_view" the last one is the live mode's."""
    return [static(*(f"replay/js/{name}.js" for name in element)) for element in _SCRIPTS[_known(kind)]]


DATA_VIEW_OPEN: Markup = static("replay/js/open_data_view.js")

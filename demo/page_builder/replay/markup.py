"""A replay page's markup: the split view (the map, the phone's strip of stages, the right-hand card), the whole picture (the
same map with every box open, the trial's part and, with single sites, the cut's), the frame of the Full record, a year set's
results and switcher, and the playback bar. The structure is `templates/replay/page.html` and `templates/replay/map.html`."""
from __future__ import annotations

from typing import Any

from .. import templating as T
from . import trial
from .evening import Evening

P, M = "replay/page.html#", "replay/map.html#"
# In the three-section map the branch columns are narrow, so each box's second line is said in fewer words
SHORT = {"h-agent": "Code plans, with a receipt", "b-agent": "Code plans, by zone", "h-model": "Reads notes, words reports",
         "b-model": "Reads notes, words reports", "h-tools": "Device calls start here", "b-tools": "Device calls start here",
         "h-guard": "Checks every call", "b-guard": "Checks every call", "h-seal": "One use, as passed", "b-seal": "One use, as passed",
         "h-person": "Writes in, and is told", "b-person": "Writes in, and is told"}
# A single site's frame: its name and hue, its note, its box's line, and what stands inside it
SITES = {"site-pv": ("Solar-and-battery plant", "c8", "Its battery is under a peak contract. What it buys and sells stays its own.",
                     "Holds for the peak", [("Its own limits", "rating, charge, connection"), ("Battery", "hardware"), ("Its operator", "may set a limit")]),
         "site-dc": ("Data center", "c9", "It buys its power as before. Here it only shifts when it draws.", "Less at the peak",
                     [("Its own limits", "rating, charge, connection"), ("Battery and jobs", "work that can wait"), ("Its operator", "may set a limit")])}
EMPTY = T.Markup("")


def box(ev: Evening, b: str, open_: bool, name: str = "", hue: str = "") -> T.Markup:
    """One box of the map. open_: the whole picture's map, where a box shows its number and its input instead of its line."""
    _, n, h, kind, sub = ev.map.by[b]
    kd = T.render(M + "kind", kind=kind) if kind else EMPTY
    if open_:
        return T.render(M + "box_open", hue=hue or h, b=b, name=name or n, kind=kd)
    return T.render(M + "box", hue=hue or h, b=b, name=name or n, kind=kd, sub=SHORT.get(b, sub))


def site(ev: Evening, b: str, open_: bool) -> T.Markup:
    label, hue, note, sub, inside = SITES[b]
    ins = T.join(T.render(M + "inside", what=w, does=d) for w, d in inside)
    if b not in ev.map.by:                                  # an evening without single sites: the frame stands as the design has it, unlit
        return T.render(M + "site_unrun", hue=hue, label=label, note=note, sub=sub, inside=ins)
    return T.render(M + "site", hue=hue, label=label, note=note, agent=box(ev, b, open_, "Site agent", hue), inside=ins)


def map_markup(ev: Evening, open_: bool) -> T.Markup:
    """The map in three sections under the aggregator: the community, the solar-and-battery plant, the data center."""
    row = lambda ids: T.join(box(ev, b, open_) for b in ids)  # noqa: E731
    com = ev.meta.get("community") or {}
    top = T.join([row(["agg-clean", "agg-share", "mkt", "agg-ref", "buy-u", "buy-g"]), T.render(M + "trade") if open_ else EMPTY, row(["utl"])])
    return T.render(M + "map", root=T.render(M + "root") if open_ else EMPTY, top=top, more=T.render(M + "more") if open_ else EMPTY,
                    six=row(["co-fc", "co-cover", "co-agent", "co-market", "co-desk", "co-report"]), town=row(["town"]),
                    homes=f'{com.get("homes")} home agents', buildings=f'{com.get("buildings")} building agents',
                    home=row([f"h-{x}" for x in ("agent", "model", "tools", "guard", "seal", "driver")]), home_base=row(["h-dev", "h-person"]),
                    bld=row([f"b-{x}" for x in ("agent", "model", "tools", "guard", "seal", "driver")]), bld_base=row(["b-dev", "b-person"]),
                    pv=site(ev, "site-pv", open_), dc=site(ev, "site-dc", open_), ret=row(["r-read", "r-check", "r-settle", "r-pay"]))


def switcher(listing: list[dict[str, Any]]) -> T.Markup:
    """A year set's row of evenings across the top: one button per evening."""
    if len(listing) < 2:
        return EMPTY
    return T.render(P + "scen", buttons=T.join(T.render(P + "scen_button", id=s["id"], about=s.get("about") or s["line"], name=s["name"]) for s in listing))


def results(listing: list[dict[str, Any]], res: dict[str, Any] | None) -> T.Markup:
    """A year set's results: what the community promised and what was delivered, evening by evening, from the set's own file."""
    if not res:
        return EMPTY
    cases = res["cases"]
    rows = T.join(T.render(P + "result", id=s["id"], name=s["name"], date=s["date"], cover_from=c["cover_from"], share=f'{100 * c["share"]:.0f}%',
                           offered=f'{c["offered_kw"]:.1f}', promised=f'{c["promised_kw"]:.1f}', truth=f'{c["delivered_truth_kw"]:.1f}',
                           meter=f'{c["delivered_meter_kw"]:.1f}', kept="kept" if c["kept_truth"] else "short", short_truth=c["short_truth"],
                           half_hours=c["half_hours"], short_meter=c["short_meter"], messages=c["messages"])
                  for s in listing for c in [cases[s["id"]]])
    return T.render(P + "results", title=res["title"], lead=res["lead"], rows=rows, lines=" ".join(res["lines"]), not_real=res["not_real"], foot=res["foot"])


def body(ev: Evening, listing: list[dict[str, Any]], res: dict[str, Any] | None = None) -> T.Markup:
    """The page's markup between <body> and its data. ev is the first evening the page plays."""
    parts = [trial.community_part()] + ([trial.cut_part()] if ev.sites else [])
    return T.render(P + "app", scen=switcher(listing), map=map_markup(ev, False),
                    strip=T.join(T.render(M + "stage", i=i, name=n) for i, (n, _) in enumerate(ev.map.strip)),
                    story_button=T.render(P + "story_button") if ev.sites else EMPTY, overview=map_markup(ev, True),
                    parts=T.join(T.render(P + "part", html=p) for p in parts), results=results(listing, res),
                    truth=T.render(P + ("truth_words" if ev.engie.get("site_notes") else "truth")),
                    results_tab=T.render(P + "results_tab") if res else EMPTY)

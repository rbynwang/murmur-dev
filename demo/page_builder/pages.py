"""The ten published pages, by file name: the six replay pages built from the recorded evenings in `demo/recordings/`, and the
method note, the year's results and the architecture page.

A replay page is one document: its style sheet, its markup, the list of the evenings it plays, each evening packed (its data,
its whole-picture markup and its Full record, as gzip-compressed, base64-encoded JSON that the page inflates when the evening
is chosen), and its scripts. The two-view page (split view and Data view) also carries the Data view's data, and its Data
view copy opens on the Data view; index.html is the split view.
"""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import Any, Callable

from . import assets, explainer, full_record, overview, recordings, year_results
from . import templating as T
from .replay import data_view, markup
from .replay.day import pack
from .replay.evening import Evening

D = "replay/document.html#"
YEAR_MIN_W = 10000          # a year's evenings share one tree width, so a short evening's tree still holds the community agent's row
REPLAYS = {
    "Murmur_NG_Agent_Network_v6_Split_View.html": ("evening_2025-01-28", "two_view", False),
    "Murmur_NG_Agent_Network_v6_Data_View.html": ("evening_2025-01-28", "two_view", True),
    "Murmur_NG_Agent_Network_v5_Three_Views.html": ("evening_2025-01-28", "three_view", False),
    "Murmur_NG_Whole_Evening_v5_Three_Views.html": ("whole_evening_2025-01-28", "three_view", False),
    "Murmur_NG_Year_ENGIE_weather_v5_Three_Views.html": ("year_engie_weather", "year", False),
    "Murmur_NG_Year_real_weather_v5_Three_Views.html": ("year_real_weather", "year", False),
}
INDEX_FROM = "Murmur_NG_Agent_Network_v6_Split_View.html"
OTHERS: dict[str, Callable[[], str]] = {
    "Murmur_NG_Simulation_Explainer_v2.html": explainer.page,
    "Murmur_NG_Year_Results_v2.html": year_results.page,
    "Murmur_NG_Architecture_and_Data.html": overview.page,
}


def evenings(folder: Path) -> tuple[list[Path], list[dict[str, str]], dict[str, Any] | None]:
    """A set's recordings, the list of evenings the page's switcher shows, and a year set's results."""
    files = recordings.evenings(folder)
    if len(files) == 1:
        return files, [{"id": "only", "name": files[0].name.split(".")[0], "date": "", "line": "", "about": ""}], None
    res = recordings.results(folder)
    return files, [{k: s.get(k, "") for k in ("id", "name", "date", "line", "about")} for s in res["scenarios"]], res


def packed(day: dict[str, Any]) -> str:
    """One evening, as the page carries it."""
    raw = json.dumps(day, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode()


def replay(set_name: str, kind: str, opens_data_view: bool = False) -> str:
    """One replay page."""
    files, listing, res = evenings(recordings.ROOT / set_name)
    days = []
    first: Evening | None = None
    for f, item in zip(files, listing):
        tr = recordings.load(f)
        day = pack(tr, two_view=kind == "two_view", min_w=YEAR_MIN_W if kind == "year" else 0)
        day["long"] = full_record.render(tr, item["id"])
        days.append(T.render(D + "day", id=item["id"], packed=packed(day)))
        first = first or Evening(tr)
    js = assets.scripts(kind)
    live = kind == "two_view"
    scripts = T.join([T.render(D + "script", js=s) for s in (js[:-1] if live else js)] + ([T.render(D + "live", id=assets.LIVE_ID, js=js[-1])] if live else []))
    return str(T.render(D + "page", css=assets.css(kind), body=markup.body(first, listing, res),
                        opening=T.render(D + "opening", js=assets.DATA_VIEW_OPEN) if opens_data_view else T.Markup(""),
                        listing=T.render(D + "listing", json=T.script_json({"first": listing[0]["id"], "list": listing})), days=T.join(days),
                        data_view=T.render(D + "data_view", json=T.script_json(data_view.payload())) if kind == "two_view" else T.Markup(""),
                        scripts=scripts))


def pages() -> dict[str, str]:
    """Every published page, by its file name."""
    out = {name: replay(*spec) for name, spec in REPLAYS.items()}
    out["index.html"] = out[INDEX_FROM]
    out.update({name: make() for name, make in OTHERS.items()})
    return out

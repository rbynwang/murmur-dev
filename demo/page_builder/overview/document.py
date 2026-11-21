"""The architecture-and-data page as one self-contained document: `templates/overview/page.html` holds its frame and the words
that carry no figure, `static/overview/` its style sheet and script, and the four built sections come from `sections.py`.

The pictures of the recorded evening are the files `pictures/moment_<NN>.webp`, each the replay page at moment NN (1440 x 900
at 1.25 device pixels, light theme), placed in the page as data so it opens with no other file.
"""
from __future__ import annotations

from pathlib import Path

from ..templating import render, static
from . import sections
from .figures import load

PICTURES = Path(__file__).resolve().parent / "pictures"


def pictures() -> dict[int, bytes]:
    """The pictures in `pictures/`, by the replay moment each shows."""
    return {int(p.stem.removeprefix("moment_")): p.read_bytes() for p in sorted(PICTURES.glob("moment_*.webp"))}


def render_page(shots: dict[int, bytes]) -> str:
    """The page with the given pictures of the replay, by moment."""
    f = load()
    return str(render("overview/page.html", style=static("overview/style.css"), script=static("overview/script.js"),
                      architecture=sections.architecture(), sources=sections.sources(f), survey=sections.survey(f),
                      evening=sections.evening(f, shots)))


def page() -> str:
    """The whole page, with the pictures in `pictures/`."""
    return render_page(pictures())

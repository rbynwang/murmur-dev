"""The pages that are not replays: the method note and the architecture page are pinned by their sha256, and the year's results
page is the published page byte for byte. The published pages are not part of a clone: point MURMUR_PUBLISHED_DIR at a folder that
holds them to run that comparison. Every step of the architecture page's recorded evening has its picture, and no picture is
left over."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from demo.page_builder import explainer, overview, year_results
from demo.page_builder.overview import document
from demo.page_builder.pages import INDEX_FROM, OTHERS, REPLAYS

METHOD_NOTE = "f0707a9c3f2677f6a360c9de39fbc195c3d1c151e01dc32a59862e478d9a4658"
ARCHITECTURE = "4acd18e99c778ab288cd038b9737bfd9fc5f402a08085da1bd815538bb65318f"


def test_method_note_is_the_proven_one() -> None:
    assert hashlib.sha256(explainer.page().encode("utf-8")).hexdigest() == METHOD_NOTE


def test_architecture_page_is_the_proven_one() -> None:
    assert hashlib.sha256(overview.page().encode("utf-8")).hexdigest() == ARCHITECTURE


def test_every_step_of_the_recorded_evening_has_its_picture() -> None:
    shots = document.pictures()
    assert sorted(shots) == [1, 11, 21, 22, 23, 28, 33, 36]
    with pytest.raises(ValueError, match=r"missing for the steps at moments \[23\]"):
        document.render_page({moment: data for moment, data in shots.items() if moment != 23})
    with pytest.raises(ValueError, match=r"of moments no step shows \[99\]"):
        document.render_page({**shots, 99: shots[1]})


def test_year_results_is_the_published_page() -> None:
    folder = os.environ.get("MURMUR_PUBLISHED_DIR")
    published = Path(folder) / "Murmur_NG_Year_Results_v2.html" if folder else None
    if published is None or not published.is_file():
        pytest.skip("the published pages are not in this clone: set MURMUR_PUBLISHED_DIR to a folder that holds them")
    assert year_results.page().encode("utf-8") == published.read_bytes()


def test_ten_pages_under_their_published_names() -> None:
    names = set(REPLAYS) | {"index.html"} | set(OTHERS)
    assert len(names) == 10 and INDEX_FROM in REPLAYS

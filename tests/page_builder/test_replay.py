"""The replay pages' own pieces: each evening's packed data and whole-picture markup, the page markup, the list of evenings and
the Data view's data. Each is pinned by the sha256 it had when it was proven against the published pages, and the build gives
the same bytes in every run, whatever the hash seed."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from demo.page_builder import assets, recordings, templating as T
from demo.page_builder.pages import REPLAYS, YEAR_MIN_W, evenings
from demo.page_builder.replay import data_view, markup
from demo.page_builder.replay.day import pack
from demo.page_builder.replay.evening import Evening

ROOT = Path(__file__).resolve().parents[2]
# (set, page kind): sha256 of every evening's packed data, of their whole-picture markup, of the page markup, of the list of evenings
PROVEN = {
    ("evening_2025-01-28", "two_view"): ("f9e557e70978320746ceb7af88e3a138cf22429994bf88760afeb52066264d1c",
                                         "56a71545adbbfadaf39f310b50c04a8249190b5f4b29e851d152434b5029db47",
                                         "14cdc327b520d803191342aa5f16de5587f8510697539dfad2447461bf8158a5",
                                         "a59bb7c25714ca68e158f8b41855b8722d5d0a4a779cf8a4ca8f9d629849c5ca"),
    ("evening_2025-01-28", "three_view"): ("49205a4e9bda5b892df7edf24dcc80aa9b109b03c63670ab9488cf613edf56a7",
                                           "56a71545adbbfadaf39f310b50c04a8249190b5f4b29e851d152434b5029db47",
                                           "14cdc327b520d803191342aa5f16de5587f8510697539dfad2447461bf8158a5",
                                           "a59bb7c25714ca68e158f8b41855b8722d5d0a4a779cf8a4ca8f9d629849c5ca"),
    ("whole_evening_2025-01-28", "three_view"): ("c1a26b8abbc0eb793f26d5e20bc6e4496832094ce004655167ee827c319fe7a1",
                                                 "e81d20188072d57c487c4c9dc6e8d12de15c2265ea87f59e9d7157d6ce5dbc7b",
                                                 "8f99a6f026529d9d4ce2f928bf6499ffbc86a877c0b77ea6369b2ff98972d2a2",
                                                 "a59bb7c25714ca68e158f8b41855b8722d5d0a4a779cf8a4ca8f9d629849c5ca"),
    ("year_engie_weather", "year"): ("a98b5ae2d44572ea8b72ea1169dee87f4d95aff1292947e75caa852b171a5001",
                                     "94ae7362a43449b65fe80a61012baa1859be584eb9fa900921501687a950433d",
                                     "e1779961dda7fa45c09f605694ef5fd1b1ae67337c740b0a3bdd07d32748bb30",
                                     "37d1c55b9a0795118e9d85827914a9a4e2baf3d55ceab5d618520033fc4c74e7"),
    ("year_real_weather", "year"): ("3648328293a25a0b65f2f26470ee1f9ee80949efbcfacc3f3342c01fda649dec",
                                    "482636524db01a9cfb0cbfa7a6e2630635a9f5d4528685262735d19f8c5456ff",
                                    "4d86a1dba008c33ba22a469217d314c66b32e8c5a5c181b41bf593e75ed56421",
                                    "c8191d2e04a84711dff62e7f52edbafd09a20e38812ba372c017066bc9f86e5c"),
}
DATA_VIEW = "bcb3fd1f0f2b5116e68c2f5be6a8704626360e0627de7008eda4c7409afbb7cd"
NODE_ID = re.compile(r"\b(?:home|building)-\d\d\b")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pieces(set_name: str, kind: str) -> tuple[str, str, str, str]:
    files, listing, res = evenings(recordings.ROOT / set_name)
    days = [pack(recordings.load(f), kind == "two_view", YEAR_MIN_W if kind == "year" else 0) for f in files]
    return (sha("".join(json.dumps(x["d"], ensure_ascii=False, separators=(",", ":")) for x in days)), sha("".join(x["world"] for x in days)),
            sha(str(markup.body(Evening(recordings.load(files[0])), listing, res))),
            sha(str(T.script_json({"first": listing[0]["id"], "list": listing}))))


def data_view_sha() -> str:
    return sha(str(T.script_json(data_view.payload())))


@pytest.mark.parametrize("set_name,kind", sorted(PROVEN))
def test_pieces_are_the_proven_ones(set_name: str, kind: str) -> None:
    assert pieces(set_name, kind) == PROVEN[(set_name, kind)]


def test_data_view_is_the_proven_one() -> None:
    assert data_view_sha() == DATA_VIEW


def test_every_replay_page_has_proven_pieces() -> None:
    assert {(s, k) for s, k, _ in REPLAYS.values()} == set(PROVEN)


def test_same_bytes_in_every_run() -> None:
    """Two runs with different hash seeds give the same pieces: no set's order reaches a page."""
    code = ("import json; from tests.page_builder.test_replay import PROVEN, pieces, data_view_sha; "
            "print(json.dumps([pieces(*k) for k in sorted(PROVEN)] + [data_view_sha()]))")
    runs = [subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)},
                           capture_output=True, text=True, check=True).stdout for seed in ("1", "2")]
    assert runs[0] == runs[1]
    assert json.loads(runs[0]) == [list(PROVEN[k]) for k in sorted(PROVEN)] + [DATA_VIEW]


@pytest.mark.parametrize("set_name", sorted({s for s, _ in PROVEN}))
def test_no_home_or_building_id_on_a_page(set_name: str) -> None:
    """A page names homes and buildings; their ids stay in the recordings."""
    files, listing, res = evenings(recordings.ROOT / set_name)
    for f in files:
        assert not NODE_ID.search(json.dumps(pack(recordings.load(f)), ensure_ascii=False)), f.name
    assert not NODE_ID.search(str(markup.body(Evening(recordings.load(files[0])), listing, res)))


def test_data_view_panels() -> None:
    p = data_view.payload()
    assert set(p["order"]) == set(p["panels"]) and {b["p"] for b in p["box"].values()} <= set(p["panels"])
    assert all(set(panel["k"]) <= set("esmo") for panel in p["panels"].values())


def test_assets_of_each_kind() -> None:
    """A two-view page runs its main script and the live mode, the other kinds the main script; every static file is used."""
    assert [len(assets.scripts(k)) for k in assets.KINDS] == [2, 1, 1]
    text = (ROOT / "demo/page_builder/assets.py").read_text(encoding="utf-8")
    unused = sorted(p.name for p in (ROOT / "demo/page_builder/static/replay").rglob("*.*") if f'"{p.stem}"' not in text and p.name not in text)
    assert not unused

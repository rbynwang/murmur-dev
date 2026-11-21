"""The Full record of each recorded evening, as every replay page carries it. Each document is pinned by the sha256 it had when it
was proven against the published pages: the same document but for the paragraph on an earlier course run, which is gone, and the
play lengths that the renamed ids' lengths move. It names homes and buildings, never their ids, and a recording without steps has
no Full record."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from demo.page_builder.full_record import render
from demo.page_builder.recordings import load

RECORDINGS = Path(__file__).resolve().parents[2] / "demo/recordings"
PROVEN = {
    "evening_2025-01-28/trace_engie_2025-01-28.json.gz": "e9e1af40c2194cd8dfe14a6b9ed1c61867be36b853a281f9cd1773a81a23e940",
    "whole_evening_2025-01-28/trace_engie_2025-01-28.json.gz": "2da88691e25c3b93a4d3badb61acb13b89cbe7d535328f6c29805109299943bb",
    "year_engie_weather/trace_engie_2025-01-24.json.gz": "02fb70f2f1f5aaa576bf908d15ec4f6003d96193dcfd8f44df52c010b4b04542",
    "year_engie_weather/trace_engie_2025-02-14.json.gz": "918391fbe331dbc3e6359ad67e9f5a765671e0407731e671edb57484eec8e2d8",
    "year_engie_weather/trace_engie_2025-03-04.json.gz": "67fb2efdd6d0b7d9e4a149abf01999a74107d5d46913332dd5bcbe78dff108f3",
    "year_engie_weather/trace_engie_2025-04-07.json.gz": "466948ebff6bb4a3b339f26f8a6d85c0bd632d879b676c224f081fd564fa6123",
    "year_engie_weather/trace_engie_2025-05-02.json.gz": "b85c6f305aac5477e23e8533efb3986dd449496c20e1470fe16e8561e98a0a35",
    "year_engie_weather/trace_engie_2025-06-17.json.gz": "06020c87016f9c24030ed8af20b3942edd6065e3195494e9d979f05c8f1101c8",
    "year_engie_weather/trace_engie_2025-07-23.json.gz": "ee8a3b5e0f02f42f1d21df4e4877624ebe640b58f0efc6a8809ea5e6862fac08",
    "year_engie_weather/trace_engie_2025-08-15.json.gz": "81eb906c60574acb41460a5fdc5ffd2e415e3cae5e2975f5087f5099aa259e41",
    "year_engie_weather/trace_engie_2025-09-19.json.gz": "fab8d933af803cc0c6e389a51def77e3f319ec12e874351d596edd56718ee948",
    "year_engie_weather/trace_engie_2025-10-28.json.gz": "0d07c45fdaa11d3de3d4fbbcf7d7e1277e539da81a3d37337d168d01f3eafc9d",
    "year_engie_weather/trace_engie_2025-11-28.json.gz": "8610b58a862f764149000fb228fbe125118bb1650530e8c8cb0c659b45772e51",
    "year_engie_weather/trace_engie_2025-12-26.json.gz": "40995f72cc6bfc536b7b8640a8508d3ddbb954fb15a8d36b0a16a0f979a0fcf4",
    "year_real_weather/trace_engie_2025-01-24.json.gz": "c8e7b87d53779705e5e4f4626ac6e6bda4e4c3eece913bba5147550a64ae5ba2",
    "year_real_weather/trace_engie_2025-02-14.json.gz": "5367d72407ad9c50102c41cd67aad149f5d9d4879177875ae7453725b9268833",
    "year_real_weather/trace_engie_2025-03-04.json.gz": "308c2b8af762c089fc68e68318b9a6c60e2e04a0f04281879275b61ab4fecc40",
    "year_real_weather/trace_engie_2025-04-07.json.gz": "ab6db33e4b734057f3b145570176d74d7c9a4c14c775d660612b9e95e98eac0c",
    "year_real_weather/trace_engie_2025-05-02.json.gz": "b309ad41a023d510f03628c618eb044cd51cd1a505391597857c447df4150449",
    "year_real_weather/trace_engie_2025-06-17.json.gz": "e2c673b958811295736f0101fc4c6b1c5883ae3e0527c531ab4caab4ab3b31a0",
    "year_real_weather/trace_engie_2025-07-23.json.gz": "90011e7d9af240d8aa311149b2b9badfe3e4ee3de3d44375e79d63add43332d6",
    "year_real_weather/trace_engie_2025-08-15.json.gz": "b64bd455142f772d9b78d15bc334088cc040c583cfa5b5855c69a603b0d98dec",
    "year_real_weather/trace_engie_2025-09-19.json.gz": "26c9978b2bad1399b5bf8ad35082e95db32a60e3630998ddcd8e5e57aff2fd84",
    "year_real_weather/trace_engie_2025-10-28.json.gz": "e3654069e2d35bd9b08972ec4cb8a30bf67706dd6c845540bb26f805ae418d3f",
    "year_real_weather/trace_engie_2025-11-28.json.gz": "37354b8f383a27d4745bafb5f0beedbecc0cc726fec232f65e1dd31dd73b6345",
    "year_real_weather/trace_engie_2025-12-26.json.gz": "8b1398461aec525321521341cfcbbe5f5b78dbebbd412b23036071828830446d",
}


@pytest.mark.parametrize("rel", sorted(PROVEN))
def test_full_record_is_the_proven_one(rel: str) -> None:
    doc = render(load(RECORDINGS / rel), rel)
    assert hashlib.sha256(doc.encode("utf-8")).hexdigest() == PROVEN[rel]


def test_every_recorded_evening_is_pinned() -> None:
    assert {p.relative_to(RECORDINGS).as_posix() for p in RECORDINGS.glob("*/trace_engie_*.json.gz")} == set(PROVEN)


def test_full_record_names_homes_and_buildings() -> None:
    doc = render(load(RECORDINGS / "evening_2025-01-28/trace_engie_2025-01-28.json.gz"), "the evening")
    assert doc.startswith('<!doctype html>\n<html lang="en">\n<head><script>document.addEventListener(')
    assert "Home 71" in doc and "The shopping center" in doc
    assert "home-0" not in doc and "building-0" not in doc


def test_a_recording_without_steps_has_no_full_record() -> None:
    with pytest.raises(ValueError, match="evening 9: the recording holds no steps"):
        render({"steps": []}, "evening 9")
